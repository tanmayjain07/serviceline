# Deploying ServiceLine

The public demo runs on three free tiers:

| Piece | Host | Why |
|---|---|---|
| PostgreSQL | [Neon](https://neon.com) | Free tier does not expire. Render's free Postgres is deleted after 30 days, which is useless for a demo you want working in six months. |
| API | [Render](https://render.com) — Docker web service | Free. Sleeps after 15 minutes idle. |
| Frontend | Render — static site | Free, always on, served from a CDN. |

Total cost: nothing. The one tradeoff is the API's cold start, discussed at the
end.

The deployment is described by [`render.yaml`](../render.yaml), so it lives in
the repository rather than only in a dashboard.

---

## Order matters

The API **refuses to start** against a database that is not enforcing tenant
isolation — see `verify_isolation()` in `api/app/main.py`. That check is
deliberate, but it means the database has to be prepared before the first deploy
or the deploy will fail loudly. Work through these in order.

---

## 1. Create the database

1. Sign up at [neon.com](https://neon.com) and create a project named
   `serviceline`. Any region; pick one near your users.
2. Neon gives you a connection string that looks like:

   ```
   postgresql://neondb_owner:SOMEPASSWORD@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

   Keep it. This is the **owner** connection, used only for migrations.

## 2. Create the restricted application role

The API connects as a role that cannot escape row-level security. That requires
a second role which does not own the tables and does not have `BYPASSRLS`,
because a table's owner bypasses RLS policies by default.

1. Open [`scripts/bootstrap-cloud-db.sql`](../scripts/bootstrap-cloud-db.sql).
2. Replace `CHANGE_ME_app_password` with a password you generate. Save it —
   it goes into `DATABASE_URL` in the next step.
3. Paste the whole file into Neon's **SQL Editor** and run it.

It prints a table at the end. `can_bypass_rls` must be `false` for
`serviceline_app`. If it is not, the script raises an exception rather than
letting you continue.

> **Do not create this role through the Neon console UI.** Roles created that way
> are automatically granted `neon_superuser`, which carries `BYPASSRLS` and would
> silently void tenant isolation. Create it with the SQL script, as above.

You now have two connection strings. They differ only in the credentials:

```
# owner  -> DATABASE_ADMIN_URL   (migrations only)
postgresql+psycopg://neondb_owner:OWNERPASS@ep-xxxx.../neondb?sslmode=require

# app    -> DATABASE_URL         (everything at runtime)
postgresql+psycopg://serviceline_app:APPPASS@ep-xxxx.../neondb?sslmode=require
```

Note the `+psycopg` after `postgresql`. SQLAlchemy needs it to select the
driver; Neon does not include it in the string it shows you, so add it to both.

### Use the direct endpoint, not the pooled one

Neon hands you a **pooled** hostname containing `-pooler`. Drop that segment and
use the direct host for both connection strings:

```
ep-something-12345-pooler.c-4.us-east-2.aws.neon.tech   <- what Neon shows
ep-something-12345.c-4.us-east-2.aws.neon.tech          <- use this
```

The pooler is PgBouncer in transaction-pooling mode. Our tenant binding is safe
there — `SET LOCAL` is scoped to a transaction, which PgBouncer keeps on one
server connection — but psycopg's server-side prepared statements interact badly
with transaction pooling, and Alembic's DDL wants a plain connection. At demo
traffic the pooler buys nothing, and SQLAlchemy already maintains its own pool
of five connections. Fewer moving parts wins.

### The owner role has BYPASSRLS, and that is expected

On Neon the default role is a member of `neon_superuser`, which carries
`BYPASSRLS`:

```
     rolname     | is_superuser | can_bypass_rls
-----------------+--------------+----------------
 neondb_owner    | f            | t
 serviceline_app | f            | f
```

This is exactly why the two-role split matters more on a managed provider than
it would on a database you administer yourself. `FORCE ROW LEVEL SECURITY` makes
a table's *owner* subject to its policies, but `BYPASSRLS` is a separate role
attribute that overrides policies regardless. Since the owner role cannot be
stripped of it on Neon, the guarantee rests entirely on the API never connecting
as that role — which is what `verify_isolation()` checks at startup, and what
`DATABASE_ADMIN_URL` being used only by Alembic enforces in practice.

## 3. Deploy from the blueprint

1. Sign up at [render.com](https://render.com) and connect your GitHub account.
2. **New → Blueprint**, choose the `serviceline` repository. Render reads
   `render.yaml` and proposes two services: `serviceline-api` and
   `serviceline-web`.
3. It will prompt for the values marked `sync: false`. Fill in what you can now:

   | Variable | Service | Value |
   |---|---|---|
   | `DATABASE_URL` | api | the app-role string from step 2 |
   | `DATABASE_ADMIN_URL` | api | the owner string from step 2 |
   | `CORS_ORIGINS` | api | leave a placeholder, fixed in step 4 |
   | `VITE_API_BASE_URL` | web | leave a placeholder, fixed in step 4 |

   `JWT_SECRET` is generated by Render and stays stable across deploys. Do not
   set it by hand and never reuse the development value.

4. Apply. The first Docker build takes five to ten minutes.

## 4. Point the two services at each other

Neither service knows the other's URL until both exist, so this is a second
pass. Once Render shows both URLs — something like
`https://serviceline-api.onrender.com` and
`https://serviceline-web.onrender.com`:

On **serviceline-api**, set:

```
CORS_ORIGINS=["https://serviceline-web.onrender.com"]
```

A JSON array, and no trailing slash. This is the browser origin allowed to call
the API; get it wrong and every request fails in the browser with a CORS error
while working perfectly from curl.

On **serviceline-web**, set:

```
VITE_API_BASE_URL=https://serviceline-api.onrender.com/api/v1
VITE_DEMO_MODE=true
```

Include the `/api/v1` suffix. Vite inlines these at **build** time, so the web
service needs a full redeploy — a restart is not enough.

Redeploy both.

## 5. Verify

```bash
# Liveness. Does not touch the database.
curl https://serviceline-api.onrender.com/healthz

# Readiness. Fails if Postgres is unreachable.
curl https://serviceline-api.onrender.com/readyz

# The demo data seeded on first boot.
curl -X POST https://serviceline-api.onrender.com/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"owner@northline.demo","password":"demo-password"}'
```

Then open the web URL and sign in with the buttons on the login page.

**The check that matters**: sign in as `owner@northline.demo`, note a membership
ID from the Team page, sign out, sign in as `owner@buckeye.demo`, and request
that ID directly. It returns 404 — not 403, which would confirm the row exists.

---

## The cold start, and how to live with it

Render's free tier suspends a web service after 15 minutes without traffic. The
next request wakes it, which takes roughly 50 seconds. Neon also suspends, but
wakes in about a second.

This is handled rather than hidden:

- The login page shows an explanatory message if a request takes longer than
  four seconds.
- The README says so above the demo link.

A visitor who was warned reads a slow first load as a known tradeoff. A visitor
who was not reads it as a broken application. That difference is the entire
reason the message exists.

To remove the delay, move the API to Render's Starter plan (about $7/month) and
change `plan: free` to `plan: starter` in `render.yaml`. Nothing else changes.

Avoid the popular trick of pinging the service every ten minutes to keep it
awake: it burns the free instance hours the demo depends on, and hosts
discourage it.

---

## Troubleshooting

**Deploy fails with `IsolationCheckFailed: ... has BYPASSRLS`**
The application role is privileged. It was almost certainly created through the
Neon console instead of the SQL script. Drop it and re-run
`scripts/bootstrap-cloud-db.sql`.

**Deploy fails with `Tables missing from the database`**
Migrations did not run. Check the deploy log for the `==> Running database
migrations` line and whatever followed it. Usually `DATABASE_ADMIN_URL` is
wrong or missing the `+psycopg` driver suffix.

**The site loads but every request fails in the browser**
CORS. Confirm `CORS_ORIGINS` on the API exactly matches the web origin —
scheme included, no trailing slash — and that it is a JSON array.

**The site calls `localhost` in production**
`VITE_API_BASE_URL` was not set at build time. Set it and trigger a full
redeploy of the static site.

**`exec /app/docker-entrypoint.sh: no such file or directory`**
The entrypoint has CRLF line endings, so the shebang points at an interpreter
whose name ends in a carriage return. `.gitattributes` pins `*.sh` to LF; if
this appears, the file was committed before that rule existed.
