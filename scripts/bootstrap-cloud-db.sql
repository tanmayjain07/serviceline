-- ServiceLine: one-time cloud database bootstrap.
--
-- Run this ONCE against a fresh Neon (or any managed Postgres) database, using
-- the provider's default owner role. In Neon: open your project, choose the SQL
-- Editor, paste this in, run it.
--
--   >>> BEFORE RUNNING: replace CHANGE_ME_app_password on the line below with a
--   >>> password you generate, and use the same value in DATABASE_URL.
--
-- WHY THIS EXISTS
--
-- The application connects as a role that deliberately cannot escape row-level
-- security. That needs a second role -- one that does not own the tables and
-- does not have BYPASSRLS -- because a table's owner bypasses RLS policies by
-- default. Migrations run as the owner; the API runs as this restricted role.
--
-- IMPORTANT, AND SPECIFIC TO NEON: create this role with SQL, as below. A role
-- created through the Neon *console UI* is automatically granted the
-- `neon_superuser` role, which carries BYPASSRLS, and that would silently void
-- tenant isolation. The API's startup check (app/main.py::verify_isolation)
-- refuses to boot if this happens, so the failure is loud rather than silent --
-- but it is easier not to trip it in the first place.
--
-- Idempotent: safe to re-run.

-- ---------------------------------------------------------------------------
-- 1. The application role
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    -- >>> EDIT THIS LINE <<<
    app_password constant text := 'CHANGE_ME_app_password';
BEGIN
    -- Deliberately checks the shape of the value rather than comparing it to
    -- the placeholder literal. A guard written as
    -- `IF app_password = 'CHANGE_ME_app_password'` is silently destroyed by a
    -- find-and-replace over this file: the guard becomes a comparison against
    -- the real password, so it fires every time.
    IF length(app_password) < 16 OR app_password ILIKE '%change%me%' THEN
        RAISE EXCEPTION
            'Set a real password of at least 16 characters on the line above '
            'before running this script.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'serviceline_app') THEN
        EXECUTE format(
            'CREATE ROLE serviceline_app LOGIN PASSWORD %L '
            'NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
            app_password
        );
        RAISE NOTICE 'created role serviceline_app';
    ELSE
        EXECUTE format(
            'ALTER ROLE serviceline_app PASSWORD %L', app_password
        );
        RAISE NOTICE 'role serviceline_app already existed; password updated';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. Connect and schema usage
-- ---------------------------------------------------------------------------
-- Table-level grants are issued by the migration, not here, because the tables
-- do not exist yet. This grants only what is needed to connect and see the
-- schema.
--
-- GRANT CONNECT needs the database named literally, so it is built dynamically
-- rather than hardcoding whatever the database happens to be called.
DO $$
BEGIN
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO serviceline_app', current_database()
    );
END
$$;

GRANT USAGE ON SCHEMA public TO serviceline_app;

-- The application must never create objects.
REVOKE CREATE ON SCHEMA public FROM serviceline_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- 3. Verify -- this is the whole point of the file
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    privileged boolean;
BEGIN
    SELECT rolsuper OR rolbypassrls
      INTO privileged
      FROM pg_roles
     WHERE rolname = 'serviceline_app';

    IF privileged THEN
        RAISE EXCEPTION
            'serviceline_app has SUPERUSER or BYPASSRLS. Row-level security '
            'would not apply and tenants could read each other''s data. If this '
            'role was created through the Neon console, DROP it and re-create '
            'it with this script instead.';
    END IF;

    RAISE NOTICE 'verified: serviceline_app has neither SUPERUSER nor BYPASSRLS';
END
$$;

-- Show the outcome so it is visible in the SQL editor.
SELECT rolname,
       rolsuper     AS is_superuser,
       rolbypassrls AS can_bypass_rls,
       rolcanlogin  AS can_login
  FROM pg_roles
 WHERE rolname IN ('serviceline_app', current_user);
