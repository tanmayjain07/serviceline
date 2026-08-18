# ServiceLine — Architecture

Milestone 1: multi-tenancy, authentication, role-based access control, and the
audit log. Customers, jobs, and the dispatch board arrive in milestone 2.

This document explains how tenant isolation works and records the decisions that
would otherwise have to be reverse-engineered from the code.

---

## 1. The problem this design solves

ServiceLine is a single application serving many contractor companies from one
database. Every company's data must be invisible to every other company.

The common way to build this is to put `WHERE tenant_id = ?` in every query.
That approach fails in a specific and predictable way: the defect is an
*absence*. One endpoint ships without the clause, nothing breaks in testing, and
months later one customer sees another's data. You cannot reliably test for a
missing filter, because there is no failing case to write until after it has
already leaked.

So isolation here is not a filter that developers must remember to write. It is
a property the database enforces on every query, whether the application asks
for it or not.

---

## 2. How isolation works

### The mechanism

Every tenant-scoped table has PostgreSQL **row-level security** enabled and
forced, with a policy comparing the row's `tenant_id` to a value stored on the
current transaction:

```sql
CREATE POLICY memberships_tenant_isolation ON memberships
    FOR ALL USING (tenant_id = app_current_tenant())
    WITH CHECK (tenant_id = app_current_tenant());
```

`app_current_tenant()` reads a transaction-local setting:

```sql
CREATE FUNCTION app_current_tenant() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
$$;
```

At the start of each request, after the JWT is verified, the session is bound:

```python
session.execute(
    text("SELECT set_config(:key, :value, true)"),
    {"key": "app.tenant_id", "value": str(tenant_id)},
)
```

The consequences are worth stating plainly:

- A query with **no** `WHERE tenant_id` returns only the current tenant's rows.
- A query that explicitly names **another** tenant's id returns nothing — the
  policy is AND-ed on top of whatever the application asked for.
- An `INSERT` or `UPDATE` aimed at another tenant is **rejected**, not silently
  redirected, because of `WITH CHECK`.
- With **no tenant bound at all**, `current_setting` returns NULL, every
  comparison evaluates to NULL, and the result set is empty. The system fails
  closed.

### Why two database roles

A table's owner bypasses row-level security by default, and a superuser bypasses
it always. So the application never connects as either:

| Role | Used by | Privileges |
|---|---|---|
| `serviceline_owner` | Alembic migrations | Owns the tables, has DDL rights |
| `serviceline_app` | The API at runtime | No DDL, no `BYPASSRLS`, not a table owner |

On top of that, every protected table also has `FORCE ROW LEVEL SECURITY`, which
removes the owner exemption too. That is two independent reasons the application
cannot escape its tenant, and the test suite asserts both.

`app/main.py` re-checks all of this at startup and **refuses to boot** if the
connected role is privileged or any table is missing its policies. A
misconfigured environment fails loudly rather than quietly serving one company's
data to another.

### Why transaction-local, not session-local

`set_config(..., is_local => true)` is the parameterisable form of `SET LOCAL`.
It is scoped to the transaction and discarded on COMMIT or ROLLBACK.

This matters because of connection pooling. A session-level setting would
persist on a pooled connection and be inherited by whichever request picked that
connection up next — one tenant's context silently applied to another tenant's
queries. That is the single most dangerous failure mode of this design, and
transaction scoping eliminates it. SQLAlchemy also issues a ROLLBACK when
returning a connection to the pool, which is a second, independent guarantee.

The cost is recorded in [ADR-003](#adr-003).

### The two deliberate widenings

Isolation this strict has to bend in exactly two places, and both are narrow
enough to state precisely.

**1. Reading your own memberships across tenants.** Login has to answer "which
companies does this person belong to?" *before* any company has been chosen. A
second key, `app.user_id`, supports one extra SELECT-only policy:

```sql
CREATE POLICY memberships_select_own ON memberships
    FOR SELECT USING (user_id = app_current_user());
```

Scoped to `user_id = me`, so it exposes nothing about anyone else, in any
company. Postgres OR-s permissive policies for the same command, so this widens
SELECT without weakening the isolation policy beside it.

**2. Reading the invitation you hold a token for.** Accepting an invitation
means touching a company you are not yet a member of. Rather than granting the
application a `BYPASSRLS` escape hatch — which would then exist for every other
query in the system — access is widened by exactly one row:

```sql
CREATE POLICY invitations_select_by_token ON invitations
    FOR SELECT USING (token_hash = app_current_invite_token());
```

Possession of the token is the authorisation. The token is single-purpose,
stored only as a SHA-256 hash, and expires in seven days.

### What is not protected by RLS

`users` has no `tenant_id`, because a user is a global identity that may belong
to several companies (see [ADR-002](#adr-002)). It is protected instead by never
being reachable except through a membership, which *is* RLS-scoped. The test
suite asserts that no route exposes it directly, so this cannot quietly change.

---

## 3. Data model

```
tenants ──┬─< memberships >── users
          ├─< invitations
          └─< audit_log
```

| Table | Purpose | RLS |
|---|---|---|
| `tenants` | One contractor company | yes |
| `users` | A person. Global identity | no — see above |
| `memberships` | user ↔ tenant, carrying the role | yes |
| `invitations` | Pending offer of membership | yes |
| `audit_log` | Append-only record of changes | yes |

**Roles** live on the membership, not the user, because the same person can be
an owner of one company and the accountant for another.

| Role | Can do |
|---|---|
| `owner` | Everything: billing, team, settings, audit log |
| `dispatcher` | Schedule jobs, manage customers, read the roster |
| `technician` | Only their own work. No roster, no pricing |
| `accountant` | Read-only: reports and exports |

**The audit log is append-only at the database level.** `serviceline_app` has
been granted `SELECT` and `INSERT` on `audit_log` and nothing else, so no code
path — deliberate, accidental, or malicious — can rewrite history through the
application.

---

## 4. Request lifecycle

```
  HTTP request
      │
      ▼
  get_principal      decode + verify the JWT. No database access.
      │
      ▼
  get_db             open a session, bind app.user_id and app.tenant_id,
      │              open one transaction for the whole request
      ▼
  require_role(...)  re-read the membership from the database and check
      │              the role. The token's claim is not trusted for this
      ▼
  handler            business logic. Never calls commit()
      │
      ▼
  get_db teardown    single commit, or rollback on any exception
```

The session is never handed to a handler before it has been bound, so there is
no window in which a query could run unscoped.

The role is re-read on every request rather than trusted from the token, so
demoting or deactivating someone takes effect immediately instead of whenever
their access token happens to expire.

---

## 5. Decisions

### ADR-001
**Tenant isolation is enforced by PostgreSQL row-level security, not by
application-level query filters.**

*Context.* The client had previously been delivered a system where one company
could see another's jobs, caused by a missing `WHERE` clause on one endpoint.

*Decision.* Enforce isolation in the database. Connect as a role that cannot
bypass it, and force policies so even the table owner is subject to them.

*Consequences.* Forgetting to scope a query yields an empty result rather than a
leak. In exchange: connection pooling needs care (ADR-003), background jobs must
set context explicitly, `tenant_id` must be indexed on every protected table,
and policy changes are migrations rather than code edits. Debugging is also less
obvious — a query returning nothing may be a missing binding rather than missing
data, which is why `verify_isolation()` runs at startup and the test suite
asserts the configuration directly.

*Rejected alternative: schema-per-tenant.* Stronger isolation still, but
migrations must run across every schema, connection pooling gets harder, and
cross-tenant reporting — which the internal admin screen in milestone 5 needs —
becomes painful. At the target scale of a few hundred tenants, RLS is the better
trade.

### ADR-002
**A user is a global identity; the user↔tenant relationship is many-to-many.**

*Context.* Two of the client's contractors share a bookkeeper, and the client
expects to log into customer accounts to help them onboard.

*Decision.* `users` has no `tenant_id`. Membership and role live on a join
table. Logging in with several memberships yields an access token with no tenant
on it; the user picks a company, and that choice is signed into the next token.

*Consequences.* Login is a two-step flow for multi-company users. Retro-fitting
this later would have been a painful migration, so it was built up front even
though only one case exists today.

### ADR-003
**One transaction per request. Route handlers never commit.**

*Context.* Tenant context is transaction-scoped (`SET LOCAL`), which is what
makes it safe under connection pooling. A commit in the middle of a request
would discard the binding, and every subsequent query in that request would run
unscoped — returning nothing, or failing a `WITH CHECK`, in ways that would look
like random bugs.

*Decision.* The `db` dependency owns the transaction boundary: bind, yield,
commit once on success, roll back on any exception.

*Consequences.* Handlers use `flush()` when they need generated ids, never
`commit()`. Long-running work cannot be split into several transactions inside
one request; when that becomes necessary it belongs in a background job with its
own explicit binding.

### ADR-004
**FastAPI with synchronous SQLAlchemy.**

*Context.* The dispatch board and the technician view both want a clean JSON API
rather than server-rendered pages. Django would have supplied a free admin
panel; FastAPI supplies Pydantic models that can generate the frontend's
TypeScript client, so the two sides cannot silently drift apart.

*Decision.* FastAPI, with **synchronous** SQLAlchemy sessions and regular `def`
route handlers, which Starlette runs in a threadpool.

*Consequences.* Async SQLAlchemy would raise the ceiling on concurrent I/O, but
this workload is a small number of dispatchers and technicians doing short
queries — connection count, not event-loop throughput, is the binding
constraint. Synchronous sessions make the transaction and context handling in
ADR-003 far easier to reason about and to get right, which matters more here
than theoretical throughput. Revisit if a single instance ever saturates.

### ADR-005
**Tokens are stored in `localStorage`, for now.**

*Context.* The alternative is httpOnly cookies, which are not readable by
JavaScript and therefore not exfiltrable by an XSS payload.

*Decision.* `localStorage`, with a short-lived access token (30 minutes) and a
refresh token, and single-flight refresh on the client.

*Consequences.* An XSS vulnerability would expose tokens. This is accepted for
milestone 1 on the basis that the app renders no user-supplied HTML and has a
small surface area. **Switch to httpOnly cookies when any of these become true:**
the app renders rich text or uploaded content, a third-party script is embedded,
or the product handles payment data directly. That switch also requires CSRF
protection and same-site deployment of API and frontend, which is why it is a
deliberate change rather than a default.

### ADR-006
**Enum columns are `VARCHAR` plus a `CHECK` constraint, storing the enum's
value.**

*Context.* SQLAlchemy's non-native `Enum` persists the member *name* by default,
so `Plan.TRIAL` is stored as `'TRIAL'` while the API and the CHECK constraints
both use `'trial'`. This produced a database whose contents did not satisfy its
own constraints, and it failed at INSERT time rather than at definition time.

*Decision.* A shared `enum_column()` helper sets `values_callable` so the stored
form and the wire form are the same string. A regression test asserts the stored
values directly.

*Consequences.* Adding an enum value is a one-line constraint migration rather
than an `ALTER TYPE`, which is awkward inside transactions.

---

## 6. Testing

74 tests. The suite that matters is `tests/test_tenant_isolation.py`, which
attacks isolation from four directions:

1. **Configuration** — is RLS actually enabled, forced, and policied? Is the
   connecting role really unprivileged? Does it own any tables?
2. **Database layer** — what a session sees with no context, with the wrong
   context, and when it explicitly names another tenant's id.
3. **API layer** — cross-tenant record IDs in requests, forged and tampered
   tokens, switching into a company you do not belong to. This is the attack
   that broke the client's previous build.
4. **Writes** — inserting into another tenant, and moving an existing row into
   one.

Plus: the audit log's append-only privileges, and that transaction-scoped
context really does not survive a rollback.

`scripts/smoke-test.ps1` runs the same acceptance criteria against a live server
over real HTTP — 33 checks, no test harness involved. It exists because one bug
in this build (a 500 on the audit log, caused by psycopg returning `INET`
columns as `ipaddress` objects) was invisible to the unit tests: Starlette's
TestClient reports its host as `"testclient"`, which is not a valid address, so
the column was always NULL in tests and never exercised the serialisation path.

---

## 7. Deployment shape

| Component | Target | Notes |
|---|---|---|
| API | Render or Fly.io | Container, `DATABASE_URL` on the app role |
| Frontend | Vercel | Static build, `/api` proxied to the API |
| Database | Neon | Managed Postgres, branching for staging |
| Migrations | CI, before deploy | Runs as `serviceline_owner` |

Estimated cost at 50 tenants: roughly $120–180/month, with no DevOps hire.

**Every account is created and owned by the client**, with the developer invited
as a member. No part of the product is ever hostage to a contractor's
credentials.

---

## 8. What milestone 1 deliberately leaves out

Customers, jobs, the dispatch board, the technician mobile view, photo upload,
signature capture, invoicing, reporting, Stripe billing, and the internal
super-admin screen. Those are milestones 2–5.

Two things in this milestone are groundwork for decisions already made with the
client:

- **Timezones.** `tenants.timezone` is the company default only. From milestone
  2 the authoritative timezone lives on the *service address*, because one of
  the client's contractors works both sides of the Ohio/Indiana line where half
  of Indiana observes Central time.
- **Seat limits.** Enforced now; the Stripe subscription that pays for them
  arrives in milestone 5. `seat_limit_override` already exists for comped
  accounts.
