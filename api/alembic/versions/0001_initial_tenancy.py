"""Initial schema: tenancy, users, memberships, invitations, audit log, and RLS.

Revision ID: 0001_initial_tenancy
Revises:
Create Date: milestone 1

This migration does three distinct jobs, in order:

  1. Creates the tables.
  2. Grants the low-privilege application role exactly the privileges it needs
     -- notably, only SELECT and INSERT on audit_log, which makes the audit
     trail append-only at the database level rather than by convention.
  3. Enables, FORCES, and defines row-level security policies.

Step 3 is the one that matters. Read docs/architecture.md ADR-001 before
changing any policy in this file.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_initial_tenancy"
down_revision = None
branch_labels = None
depends_on = None


APP_ROLE = "serviceline_app"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Tables
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("trade_type", sa.String(length=20), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("plan", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seat_limit_override", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "trade_type IN ('hvac','plumbing','electrical','multi_trade','other')",
            name="ck_tenants_trade_type",
        ),
        sa.CheckConstraint(
            "plan IN ('trial','starter','pro','business')", name="ck_tenants_plan"
        ),
        sa.CheckConstraint(
            "status IN ('trialing','active','past_due','canceled','suspended')",
            name="ck_tenants_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "is_superadmin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    # Case-insensitive uniqueness on email. Storing the address as entered but
    # comparing lowercased avoids "Dale@" and "dale@" becoming two accounts.
    op.create_index(
        "ix_users_email_lower", "users", [sa.text("lower(email)")], unique=True
    )

    op.create_table(
        "memberships",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner','dispatcher','technician','accountant')",
            name="ck_memberships_role",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_memberships_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "invitations",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner','dispatcher','technician','accountant')",
            name="ck_invitations_role",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_invitations_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name="fk_invitations_invited_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_invitations"),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )
    op.create_index("ix_invitations_tenant_id", "invitations", ["tenant_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("entity_label", sa.String(length=255), nullable=True),
        sa.Column("changes", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.dialects.postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_audit_log_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_log_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    # The query the audit screen actually runs: this tenant, newest first.
    op.create_index(
        "ix_audit_log_tenant_created",
        "audit_log",
        ["tenant_id", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # 2. The tenant-context helper
    # ------------------------------------------------------------------
    # Every policy calls this rather than repeating the current_setting()
    # expression, so there is exactly one definition of "the current tenant" in
    # the database.
    #
    # When the GUC is unset, current_setting(..., true) returns NULL, so the
    # function returns NULL and every `tenant_id = app_current_tenant()`
    # comparison evaluates to NULL -- which is not TRUE, so no rows are
    # returned. An unauthenticated or mis-wired connection therefore sees
    # nothing, rather than seeing everything.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_current_tenant() RETURNS uuid
        LANGUAGE sql
        STABLE
        AS $$
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_current_invite_token() RETURNS text
        LANGUAGE sql
        STABLE
        AS $$
            SELECT NULLIF(current_setting('app.invite_token_hash', true), '')
        $$;
        """
    )
    # The identity of the caller, independent of any tenant. Needed because
    # login and the company switcher must read a user's memberships *before* a
    # tenant has been chosen -- see the memberships_select_own policy below.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_current_user() RETURNS uuid
        LANGUAGE sql
        STABLE
        AS $$
            SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
        $$;
        """
    )

    # ------------------------------------------------------------------
    # 3. Privileges for the application role
    # ------------------------------------------------------------------
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON tenants, memberships, invitations "
        f"TO {APP_ROLE};"
    )
    # No DELETE on users: accounts are deactivated, never destroyed, so that
    # audit entries and (from milestone 2) completed jobs keep their actor.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON users TO {APP_ROLE};")
    # Append-only audit trail, enforced by the absence of UPDATE and DELETE.
    # The application literally cannot rewrite history through this role.
    op.execute(f"GRANT SELECT, INSERT ON audit_log TO {APP_ROLE};")
    op.execute(f"GRANT EXECUTE ON FUNCTION app_current_tenant() TO {APP_ROLE};")
    op.execute(f"GRANT EXECUTE ON FUNCTION app_current_invite_token() TO {APP_ROLE};")
    op.execute(f"GRANT EXECUTE ON FUNCTION app_current_user() TO {APP_ROLE};")
    # The app role must never be able to create objects in the schema.
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {APP_ROLE};")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC;")

    # ------------------------------------------------------------------
    # 4. Row-level security
    # ------------------------------------------------------------------
    # ENABLE turns policies on for everyone except the table owner and
    # superusers. FORCE removes the owner exemption too. We use a separate
    # non-owning role for the application *and* force the policies, so there are
    # two independent reasons the app cannot escape its tenant.
    for table in ("tenants", "memberships", "invitations", "audit_log"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

    # -- tenants ------------------------------------------------------
    # A tenant row is visible only to a session bound to that tenant.
    op.execute(
        """
        CREATE POLICY tenants_select ON tenants
            FOR SELECT USING (id = app_current_tenant());
        """
    )
    op.execute(
        """
        CREATE POLICY tenants_update ON tenants
            FOR UPDATE USING (id = app_current_tenant())
            WITH CHECK (id = app_current_tenant());
        """
    )
    # Signup generates the tenant UUID in application code, binds the session to
    # it, and only then inserts. That lets even the creation path be constrained
    # to "you may only insert the tenant you are already bound to", instead of
    # the looser WITH CHECK (true).
    op.execute(
        """
        CREATE POLICY tenants_insert ON tenants
            FOR INSERT WITH CHECK (id = app_current_tenant());
        """
    )
    # No DELETE policy: with RLS enabled, a command with no policy is denied.
    # Tenant deletion is an operator action, not an application one.

    # A user must be able to see the *name* of every company they belong to, to
    # render the company switcher, before any tenant has been chosen. Note the
    # inner SELECT on memberships is itself subject to memberships' policies, so
    # this cannot be used to enumerate companies you are not a member of.
    op.execute(
        """
        CREATE POLICY tenants_select_own_membership ON tenants
            FOR SELECT USING (
                EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.tenant_id = tenants.id
                      AND m.user_id = app_current_user()
                      AND m.is_active
                )
            );
        """
    )

    # -- memberships, audit_log ---------------------------------------
    for table in ("memberships", "audit_log"):
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                FOR ALL USING (tenant_id = app_current_tenant())
                WITH CHECK (tenant_id = app_current_tenant());
            """
        )

    # You can always read your own memberships, in any tenant. This is what
    # makes login possible: authenticate, bind app.user_id, and ask "which
    # companies do I belong to?" without yet being bound to any of them.
    #
    # It is SELECT-only and scoped to `user_id = me`, so it grants no visibility
    # into anyone else's membership, in this tenant or any other. Multiple
    # permissive policies on the same command are OR-ed together in Postgres,
    # so this widens SELECT without weakening the isolation policy above.
    op.execute(
        """
        CREATE POLICY memberships_select_own ON memberships
            FOR SELECT USING (user_id = app_current_user());
        """
    )

    # -- invitations ---------------------------------------------------
    op.execute(
        """
        CREATE POLICY invitations_tenant_isolation ON invitations
            FOR ALL USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        """
    )
    # The one deliberate exception in the whole schema.
    #
    # Accepting an invitation requires reading a row belonging to a tenant the
    # caller is not yet a member of. Rather than granting the application a
    # BYPASSRLS escape hatch -- which would then exist for every other query
    # too -- we widen access by exactly one row: the invitation whose token hash
    # the caller can already produce. Possession of the token is the
    # authorisation, and the token is single-purpose, hashed at rest, and
    # expires in 7 days.
    #
    # Note this is SELECT only. Accepting the invitation (writing the
    # membership) happens after the session has been re-bound to the
    # invitation's tenant.
    op.execute(
        """
        CREATE POLICY invitations_select_by_token ON invitations
            FOR SELECT USING (token_hash = app_current_invite_token());
        """
    )

    # users has no RLS: a user is a global identity that may belong to several
    # tenants, so there is no tenant_id to filter on. It is protected instead by
    # never being exposed through an endpoint that is not already scoped by a
    # membership lookup. tests/test_tenant_isolation.py asserts this.


def downgrade() -> None:
    for table in ("audit_log", "invitations", "memberships", "tenants"):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP FUNCTION IF EXISTS app_current_user();")
    op.execute("DROP FUNCTION IF EXISTS app_current_invite_token();")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant();")
    op.drop_table("audit_log")
    op.drop_table("invitations")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("tenants")
