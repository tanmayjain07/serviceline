"""Tenant isolation.

This is the file the client said they would personally try to break. It attacks
isolation from four directions:

  1. Configuration -- is the database actually set up to enforce RLS at all?
  2. The database layer -- what a session sees with no context, the wrong
     context, and the right context.
  3. The API layer -- what happens when a caller manipulates IDs in requests,
     which is exactly how the previous developer's build leaked.
  4. Writes -- can a bound session create or move a row into another tenant?

If any test here fails, the product is not shippable, regardless of what else
works.
"""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import bind_invite_token
from app.core.security import hash_invite_token

# ---------------------------------------------------------------------------
# 1. Configuration: is the guarantee even switched on?
# ---------------------------------------------------------------------------


def test_application_role_cannot_bypass_rls(db):
    """The role the API connects with must not be able to see past policies.

    A single `ALTER ROLE ... BYPASSRLS` -- the kind of thing someone does at
    2am to make a permissions error go away -- would silently void every other
    test in this file. So it is asserted first.
    """
    role, is_privileged = db.execute(
        text(
            "SELECT current_user, rolsuper OR rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )
    ).one()
    assert is_privileged is False, (
        f"The application connects as {role!r}, which can bypass row-level "
        "security. Tenant isolation would not be enforced."
    )


def test_application_role_is_not_the_table_owner(db):
    """A table's owner bypasses RLS unless FORCE is set.

    We set FORCE as well, but the app role must not be the owner regardless --
    two independent protections rather than one.
    """
    rows = db.execute(
        text(
            """
            SELECT c.relname, pg_get_userbyid(c.relowner) = current_user
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            """
        )
    ).all()
    owned = [name for name, is_owner in rows if is_owner]
    assert owned == [], f"The application role owns tables: {owned}"


def test_every_tenant_scoped_table_has_rls_enabled_forced_and_policies(db, rls_tables):
    """Adding a tenant-scoped table without a policy must fail the build.

    `RLS_TABLES` in app/models/__init__.py is the declared list; this compares it
    against reality. A new table with a tenant_id and no policy is the single
    most likely way isolation gets broken in future, and this is the tripwire.
    """
    rows = db.execute(
        text(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = ANY(:tables)
            """
        ),
        {"tables": list(rls_tables)},
    ).all()

    assert {r[0] for r in rows} == set(rls_tables)
    for name, enabled, forced, policies in rows:
        assert enabled, f"{name}: RLS not enabled"
        assert forced, f"{name}: FORCE ROW LEVEL SECURITY not set"
        assert policies > 0, f"{name}: RLS enabled but no policies"


def test_audit_log_is_append_only_for_the_application_role(db, make_company):
    """The app role has SELECT and INSERT on audit_log and nothing else.

    So there is no code path -- deliberate, accidental, or malicious -- that can
    rewrite or erase history. This is a privilege check, not an RLS check, which
    is why it does not depend on tenant context.
    """
    make_company()

    with pytest.raises(DBAPIError) as excinfo:
        db.execute(text("UPDATE audit_log SET action = 'tampered'"))
    assert "permission denied" in str(excinfo.value).lower()
    db.rollback()

    with pytest.raises(DBAPIError) as excinfo:
        db.execute(text("DELETE FROM audit_log"))
    assert "permission denied" in str(excinfo.value).lower()
    db.rollback()


# ---------------------------------------------------------------------------
# 2. The database layer
# ---------------------------------------------------------------------------


def test_session_with_no_tenant_context_sees_nothing(db, make_company):
    """Failing closed.

    Two companies exist. A session that forgot to bind a tenant -- a bug, a new
    background job, a misconfigured connection -- gets an empty result set
    rather than everyone's data. This is the property that makes the whole
    approach safe: the default is deny, not leak.
    """
    make_company("Northline Mechanical")
    make_company("Riverside Plumbing")

    for table in ("tenants", "memberships", "audit_log"):
        count = db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        assert count == 0, f"{table} leaked {count} rows to an unbound session"

    # Sanity check that the rows really do exist -- otherwise the assertions
    # above would pass on an empty database and prove nothing.
    total = db.execute(
        text("SELECT count(*) FROM users")  # users is global, so visible
    ).scalar_one()
    assert total == 2


def test_bound_session_sees_only_its_own_tenant(bound_db, make_company):
    a = make_company("Northline Mechanical")
    b = make_company("Riverside Plumbing")

    session_a = bound_db(tenant_id=a.tenant_id)
    session_b = bound_db(tenant_id=b.tenant_id)

    names_a = session_a.execute(text("SELECT name FROM tenants")).scalars().all()
    names_b = session_b.execute(text("SELECT name FROM tenants")).scalars().all()

    assert names_a == ["Northline Mechanical"]
    assert names_b == ["Riverside Plumbing"]

    ids_a = session_a.execute(text("SELECT tenant_id FROM memberships")).scalars().all()
    ids_b = session_b.execute(text("SELECT tenant_id FROM memberships")).scalars().all()

    assert {str(i) for i in ids_a} == {a.tenant_id}
    assert {str(i) for i in ids_b} == {b.tenant_id}


def test_explicit_query_for_another_tenants_id_returns_nothing(bound_db, make_company):
    """Even naming the other tenant's ID directly returns no rows.

    This is the difference between RLS and application-level filtering. With
    filtering, `WHERE tenant_id = <someone else's id>` returns their data. Here
    the policy is AND-ed on top and the result is empty.
    """
    a = make_company()
    b = make_company()

    session_a = bound_db(tenant_id=a.tenant_id)
    rows = session_a.execute(
        text("SELECT count(*) FROM memberships WHERE tenant_id = :other"),
        {"other": b.tenant_id},
    ).scalar_one()
    assert rows == 0


def test_cannot_insert_a_row_into_another_tenant(bound_db, make_company, client, api):
    """WITH CHECK blocks writes aimed at another tenant.

    A handler that took `tenant_id` from a request body instead of the token --
    a classic mistake -- would be stopped here by the database.
    """
    a = make_company()
    b = make_company()

    me = a.get(f"{api}/auth/me").json()
    user_id = me["id"]

    session_a = bound_db(tenant_id=a.tenant_id)
    with pytest.raises(DBAPIError) as excinfo:
        session_a.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role) "
                "VALUES (gen_random_uuid(), :tenant, :user, 'technician')"
            ),
            {"tenant": b.tenant_id, "user": user_id},
        )
    assert "row-level security" in str(excinfo.value).lower()


def test_cannot_move_a_row_into_another_tenant(bound_db, make_company):
    """An UPDATE that reassigns tenant_id is rejected by WITH CHECK.

    Without this, isolation could be defeated by moving rows rather than reading
    them.
    """
    a = make_company()
    b = make_company()

    session_a = bound_db(tenant_id=a.tenant_id)
    with pytest.raises(DBAPIError) as excinfo:
        session_a.execute(
            text("UPDATE memberships SET tenant_id = :other"),
            {"other": b.tenant_id},
        )
    assert "row-level security" in str(excinfo.value).lower()


def test_invite_token_context_exposes_exactly_one_row(bound_db, make_company, api, db):
    """The one deliberate exception is exactly one row wide.

    The `invitations_select_by_token` policy is the only widening in the schema.
    It must expose the single invitation matching the presented hash -- not the
    tenant's other invitations, and certainly not another tenant's.
    """
    a = make_company()
    b = make_company()

    invite_a = a.post(
        f"{api}/invitations", json={"email": "tech-a@example.com", "role": "technician"}
    ).json()
    a.post(
        f"{api}/invitations",
        json={"email": "second-a@example.com", "role": "dispatcher"},
    )
    b.post(
        f"{api}/invitations", json={"email": "tech-b@example.com", "role": "technician"}
    )

    raw_token = parse_qs(urlparse(invite_a["accept_url"]).query)["token"][0]

    # A session with the token hash bound and NO tenant bound.
    bind_invite_token(db, hash_invite_token(raw_token))
    rows = db.execute(text("SELECT id, email FROM invitations")).all()

    assert len(rows) == 1, f"token context exposed {len(rows)} invitations"
    assert rows[0][1] == "tech-a@example.com"


def test_transaction_scoped_context_does_not_leak_between_transactions(
    db, make_company
):
    """`SET LOCAL` really is transaction-scoped.

    This is what makes the pattern safe under connection pooling. If the binding
    survived a commit or rollback, a pooled connection could carry one tenant's
    context into the next request -- the single most dangerous failure mode of
    this design.
    """
    a = make_company()

    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": a.tenant_id},
    )
    assert db.execute(text("SELECT count(*) FROM tenants")).scalar_one() == 1

    db.rollback()

    assert db.execute(
        text("SELECT current_setting('app.tenant_id', true)")
    ).scalar_one() in (
        None,
        "",
    )
    assert db.execute(text("SELECT count(*) FROM tenants")).scalar_one() == 0


# ---------------------------------------------------------------------------
# 3. The API layer -- ID manipulation, which is how the last build leaked
# ---------------------------------------------------------------------------


def test_cannot_patch_another_tenants_membership(make_company, api):
    """The exact attack the client described: use another company's record ID."""
    a = make_company()
    b = make_company()

    members_a = a.get(f"{api}/memberships").json()["items"]
    victim_id = members_a[0]["id"]

    response = b.patch(f"{api}/memberships/{victim_id}", json={"role": "technician"})
    assert response.status_code == 404, response.text

    # And confirm nothing actually changed.
    assert a.get(f"{api}/memberships").json()["items"][0]["role"] == "owner"


def test_cannot_revoke_another_tenants_invitation(make_company, api):
    a = make_company()
    b = make_company()

    invite = a.post(
        f"{api}/invitations", json={"email": "tech@example.com", "role": "technician"}
    ).json()

    response = b.delete(f"{api}/invitations/{invite['id']}")
    assert response.status_code == 404

    assert a.get(f"{api}/invitations").json()[0]["status"] == "pending"


def test_cannot_switch_into_a_company_you_do_not_belong_to(make_company, api):
    a = make_company()
    b = make_company()

    response = b.post(f"{api}/auth/switch-tenant", json={"tenant_id": a.tenant_id})
    assert response.status_code == 403


def test_login_with_another_companys_tenant_id_is_refused(client, make_company, api):
    a = make_company()
    b = make_company()

    response = client.post(
        f"{api}/auth/login",
        json={
            "email": b.owner_email,
            "password": b.owner_password,
            "tenant_id": a.tenant_id,
        },
    )
    assert response.status_code == 403


def test_audit_log_is_scoped_to_the_callers_company(make_company, api):
    a = make_company("Northline Mechanical")
    b = make_company("Riverside Plumbing")

    entries_a = a.get(f"{api}/audit-log").json()
    entries_b = b.get(f"{api}/audit-log").json()

    assert entries_a["total"] == 1
    assert entries_b["total"] == 1
    assert entries_a["items"][0]["entity_label"] == "Northline Mechanical"
    assert entries_b["items"][0]["entity_label"] == "Riverside Plumbing"

    labels_b = {e["entity_label"] for e in entries_b["items"]}
    assert "Northline Mechanical" not in labels_b


def test_tenants_current_returns_only_the_token_scoped_company(make_company, api):
    a = make_company("Northline Mechanical")
    b = make_company("Riverside Plumbing")

    assert a.get(f"{api}/tenants/current").json()["name"] == "Northline Mechanical"
    assert b.get(f"{api}/tenants/current").json()["name"] == "Riverside Plumbing"


def test_forged_tenant_claim_in_a_token_still_cannot_read_data(make_company, api):
    """A token is signed, so a caller cannot rewrite `tid` -- but verify the
    consequence anyway: an unsigned or tampered token is rejected outright,
    rather than being treated as a tenant switch."""
    a = make_company()
    b = make_company()

    tampered = b.access_token[:-6] + "AAAAAA"
    response = b.get(f"{api}/tenants/current", token=tampered)
    assert response.status_code == 401

    # And a syntactically valid token signed with the wrong key is refused.
    import jwt

    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tid": a.tenant_id,
            "role": "owner",
            "typ": "access",
            "exp": 9999999999,
        },
        # 32+ bytes, so the test exercises signature rejection rather than
        # tripping PyJWT's short-key warning.
        "not-the-real-secret-but-long-enough-for-hs256",
        algorithm="HS256",
    )
    assert b.get(f"{api}/tenants/current", token=forged).status_code == 401


# ---------------------------------------------------------------------------
# 4. Surface area
# ---------------------------------------------------------------------------


def test_no_endpoint_exposes_the_global_users_table(client):
    """`users` has no tenant_id and therefore no RLS policy.

    It is protected instead by never being reachable except through a
    membership, which is RLS-scoped. This asserts that no route has appeared
    that would list or fetch users directly -- the one way this design could be
    undermined by a future change.
    """
    paths = client.get("/openapi.json").json()["paths"].keys()
    offenders = [p for p in paths if "/users" in p]
    assert offenders == [], f"Routes expose users directly: {offenders}"
