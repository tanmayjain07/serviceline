# ServiceLine

Multi-tenant field service scheduling for HVAC and plumbing contractors.
**React · Python · PostgreSQL**

[![CI](https://github.com/tanmayjain70/serviceline/actions/workflows/ci.yml/badge.svg)](https://github.com/tanmayjain70/serviceline/actions/workflows/ci.yml)

> **Milestone 1 of 5 — the foundation.** Multi-tenancy with database-enforced
> isolation, authentication, role-based access control, team invitations, seat
> limits, and an append-only audit log. Customers, jobs, and the dispatch board
> arrive in milestone 2.

---

## Live demo

**<https://serviceline-web.onrender.com>**

> Hosted on a free tier that sleeps when idle, so the **first sign-in can take
> up to a minute** while the server wakes. Everything after that is fast. The
> login page tells you this while it waits.

Two separate companies share the demo. Every account uses the password
`demo-password`.

| Account | Company | Role | What it shows |
|---|---|---|---|
| `owner@northline.demo` | Northline Mechanical | Owner | Everything: team, invitations, settings, audit log |
| `tech@northline.demo` | Northline Mechanical | Technician | Restricted — the team, settings and audit pages are gone, and the API returns **403** if called directly |
| `owner@buckeye.demo` | Buckeye Plumbing | Owner | A different company entirely |
| `books@shared.demo` | **Both** | Accountant | One person in two companies, with the company switcher |

### Try to break it

That is the point of shipping two companies rather than one.

1. Sign in as `owner@northline.demo`, open **Team**, and copy a membership ID
   out of the network tab
2. Sign in as `owner@buckeye.demo` and call
   `PATCH /api/v1/memberships/{that-id}` with your own token
3. You get **404** — not 403, which would confirm the row exists

The database refuses to return the row at all. There is no `WHERE tenant_id`
clause in the handler to forget.

---

## The interesting part

Every contractor company is a tenant, and no company may ever see another's
data. The usual way to build that is `WHERE tenant_id = ?` in every query — an
approach whose failure mode is a *missing* clause, which is exactly the kind of
defect you cannot write a failing test for until after it has already leaked.

Here, isolation is enforced by PostgreSQL itself:

```python
# app/routers/memberships.py — note what is NOT here
total = db.scalar(select(func.count()).select_from(Membership)) or 0
```

No tenant filter. The database supplies it. A query that forgets to scope
returns **nothing**, not everything.

```sql
CREATE POLICY memberships_tenant_isolation ON memberships
    FOR ALL USING (tenant_id = app_current_tenant())
    WITH CHECK (tenant_id = app_current_tenant());
```

Backed by:

- A runtime database role with **no `BYPASSRLS`** that **owns no tables**
- `FORCE ROW LEVEL SECURITY` on every protected table, so even the owner is subject
- **Transaction-scoped** context (`SET LOCAL`), so a pooled connection can never
  carry one tenant's context into the next request
- A **startup check** that refuses to boot if any of the above is not true

Full reasoning and the trade-offs, including the two deliberate exceptions:
**[docs/architecture.md](docs/architecture.md)**

---

## Proof

```
87 passed in 63s          pytest, 92% coverage, green in CI
33/33 checks passed       local end-to-end smoke test over real HTTP
27/27 checks passed       against the deployed demo, over the public internet
ruff check: clean         ruff format: clean
tsc --noEmit: clean       vite build: clean
```

`tests/test_tenant_isolation.py` attacks isolation four ways — configuration,
the database layer, the API layer, and writes. Highlights:

| Test | Proves |
|---|---|
| `test_session_with_no_tenant_context_sees_nothing` | The system fails **closed** |
| `test_explicit_query_for_another_tenants_id_returns_nothing` | Naming another tenant's ID does not help |
| `test_cannot_insert_a_row_into_another_tenant` | `WITH CHECK` blocks cross-tenant writes |
| `test_cannot_move_a_row_into_another_tenant` | Isolation cannot be defeated by moving rows |
| `test_cannot_patch_another_tenants_membership` | The ID-manipulation attack, over HTTP |
| `test_transaction_scoped_context_does_not_leak_between_transactions` | Safe under connection pooling |
| `test_audit_log_is_append_only_for_the_application_role` | The app **cannot** rewrite history |
| `test_application_role_cannot_bypass_rls` | Nobody quietly granted `BYPASSRLS` |

---

## Features

**Tenancy & identity**
- Self-serve company signup with a 14-day trial
- One person can belong to **several companies** with a different role in each,
  with an in-app company switcher
- JWT access + refresh tokens, single-flight refresh on the client

**Team**
- Four roles — owner, dispatcher, technician, accountant — enforced **server-side**
- Invitations with hashed, single-use, 7-day tokens
- Seat limits per plan, counting pending invitations, with a 402 upgrade prompt
- A company can never remove its last active owner

**Audit**
- Append-only log with field-level before/after diffs, actor, IP, and user agent
- Enforced by database privileges, not by convention

---

## Running it locally

**Prerequisites:** PostgreSQL 16+, Python 3.12+, Node 20+.

### 1. Database

```powershell
$env:PGSUPERPASSWORD = "<your postgres superuser password>"
.\scripts\bootstrap-db.ps1
```

Creates the two roles and both databases, and asserts that the application role
cannot bypass RLS.

### 2. API

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

copy .env.example .env
# then set JWT_SECRET:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

API on <http://127.0.0.1:8000> · docs at `/docs` · OpenAPI at `/openapi.json`

### 3. Frontend

```powershell
cd web
npm install
npm run dev
```

App on <http://localhost:5173>, proxying `/api` to the backend.

### 4. Verify

```powershell
cd api
.\.venv\Scripts\python.exe -m pytest            # 87 tests
cd ..
.\scripts\smoke-test.ps1                        # 33 live checks
```

---

## Try it in two minutes

1. Sign up at <http://localhost:5173/signup> as **Northline Mechanical**
2. Open a **different browser profile** and sign up as **Riverside Plumbing**
3. In Northline → **Team** → invite `mike@example.com` as a technician
4. Copy the invite link shown once on screen, open it, accept
5. Sign in as Mike — no Team, Settings, or Audit log in the sidebar, and the API
   returns **403** if you call those endpoints directly
6. Try to reach Northline's records from Riverside — every attempt is a **404**

Step 6 is the one the client cares about. `scripts/smoke-test.ps1` automates all
of it.

---

## Layout

```
serviceline/
├── api/
│   ├── alembic/versions/       migrations, including all RLS policies
│   ├── app/
│   │   ├── core/               config, db + tenant binding, security, errors
│   │   ├── models/             SQLAlchemy models
│   │   ├── routers/            auth, tenants, memberships, invitations, audit
│   │   ├── schemas/            Pydantic request/response models
│   │   ├── services/           audit, seat limits, slugs
│   │   ├── deps.py             session + auth + RBAC dependencies
│   │   └── main.py             app factory + startup isolation check
│   ├── tests/                  87 tests
│   ├── Dockerfile              pinned runtime, non-root
│   └── docker-entrypoint.sh    migrate -> seed -> serve
├── web/
│   └── src/
│       ├── components/         layout, shared UI primitives
│       ├── lib/                API client, auth context, types
│       └── pages/              login, signup, invite, team, settings, audit
├── scripts/                    database bootstrap (local + cloud), smoke test
├── render.yaml                 deployment as code
└── docs/
    ├── architecture.md         how isolation works, and six ADRs
    └── deployment.md           deploying to Neon + Render
```

---

## Tech

| | |
|---|---|
| **Backend** | FastAPI · SQLAlchemy 2 · Alembic · psycopg 3 · PyJWT · bcrypt |
| **Frontend** | React 19 · TypeScript · Vite · TanStack Query · React Router · Tailwind 4 |
| **Database** | PostgreSQL 17 with row-level security |
| **Tooling** | pytest · ruff · GitHub Actions |

---

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| **1** | Tenancy, auth, RBAC, invitations, audit log | ✅ **Done** |
| 2 | Customers, service addresses, jobs, dispatch board | Next |
| 3 | Technician mobile view, offline-resilient submits, photos, signatures | |
| 4 | Invoicing with gapless numbering, PDF, reporting | |
| 5 | Stripe billing, super-admin, read-only impersonation | |

Milestone 2 moves the authoritative timezone from the company to the **service
address** — one target customer works both sides of the Ohio/Indiana line, where
half of Indiana observes Central time.

---

## License

MIT
