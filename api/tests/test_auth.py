"""Signup, login, tokens, and the multi-company switcher."""

from __future__ import annotations

from sqlalchemy import text


def test_signup_creates_company_owner_and_audit_entry(client, api, make_company):
    company = make_company("Northline Mechanical")

    assert company.tenant_id
    assert company.access_token
    assert company.refresh_token

    tenant = company.get(f"{api}/tenants/current").json()
    assert tenant["name"] == "Northline Mechanical"
    assert tenant["plan"] == "trial"
    assert tenant["status"] == "trialing"
    assert tenant["slug"] == "northline-mechanical"
    assert tenant["trial_ends_at"] is not None
    assert tenant["seat_limit"] == 5
    assert tenant["seats_used"] == 1

    entries = company.get(f"{api}/audit-log").json()
    assert entries["total"] == 1
    assert entries["items"][0]["action"] == "tenant.created"


def test_enum_columns_store_lowercase_values_not_python_names(db, make_company):
    """Regression test.

    SQLAlchemy's non-native Enum stores the member NAME by default, so `Plan.TRIAL`
    would land in the database as 'TRIAL' while the CHECK constraints and the JSON
    API both use 'trial'. `enum_column()` sets values_callable to prevent that.
    Without this test the mismatch is invisible until a constraint fires.
    """
    company = make_company()
    db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": company.tenant_id},
    )
    plan, status, trade = db.execute(
        text("SELECT plan, status, trade_type FROM tenants")
    ).one()
    assert (plan, status, trade) == ("trial", "trialing", "hvac")

    role = db.execute(text("SELECT role FROM memberships")).scalar_one()
    assert role == "owner"


def test_audit_entries_with_a_real_client_ip_serialise_as_strings(client, api):
    """Regression test.

    `ip_address` is a Postgres INET column, and psycopg returns INET values as
    Python ipaddress objects rather than strings. The audit-log response schema
    declares a string, so reading back any entry that actually captured an IP
    used to raise a 500. Every other test misses this because Starlette's
    TestClient reports its host as "testclient", which is not a valid address
    and is therefore stored as NULL -- so the bug only appeared against a real
    server. Forwarding a valid address here reproduces production conditions.
    """
    forwarded = {"X-Forwarded-For": "203.0.113.7"}
    signup = client.post(
        f"{api}/auth/signup",
        headers=forwarded,
        json={
            "company_name": "Forwarded Heating",
            "trade_type": "hvac",
            "timezone": "America/New_York",
            "full_name": "Ida Owner",
            "email": "ida@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert signup.status_code == 201
    token = signup.json()["access_token"]

    response = client.get(
        f"{api}/audit-log", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    entry = response.json()["items"][0]
    assert entry["ip_address"] == "203.0.113.7"
    assert isinstance(entry["ip_address"], str)


def test_a_junk_forwarded_header_does_not_break_the_request(client, api):
    """X-Forwarded-For is caller-supplied and can contain anything.

    An unparseable value must be dropped, not written to an INET column where it
    would fail the INSERT and turn the audit log into a denial-of-service
    surface.
    """
    response = client.post(
        f"{api}/auth/signup",
        headers={"X-Forwarded-For": "'; DROP TABLE tenants; --"},
        json={
            "company_name": "Junk Header Co",
            "trade_type": "hvac",
            "timezone": "America/New_York",
            "full_name": "Junk Owner",
            "email": "junk@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201

    token = response.json()["access_token"]
    entries = client.get(
        f"{api}/audit-log", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert entries["items"][0]["ip_address"] is None


def test_signup_rejects_a_duplicate_email(client, api, make_company):
    company = make_company()
    response = client.post(
        f"{api}/auth/signup",
        json={
            "company_name": "Another Company",
            "trade_type": "plumbing",
            "timezone": "America/New_York",
            "full_name": "Someone Else",
            "email": company.owner_email,
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_signup_rejects_a_short_password(client, api):
    response = client.post(
        f"{api}/auth/signup",
        json={
            "company_name": "Tiny Password Co",
            "trade_type": "hvac",
            "timezone": "America/New_York",
            "full_name": "Short Pass",
            "email": "short@example.com",
            "password": "abc123",
        },
    )
    assert response.status_code == 422


def test_signup_rejects_an_unknown_timezone(client, api):
    """Timezones are validated at the edge.

    The client operates across the Ohio/Indiana line, so timezone handling is a
    known source of pain. An invalid IANA name must never reach the database.
    """
    response = client.post(
        f"{api}/auth/signup",
        json={
            "company_name": "Bad Timezone Co",
            "trade_type": "hvac",
            "timezone": "America/Nowhere",
            "full_name": "Zone Person",
            "email": "zone@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 422


def test_signup_accepts_a_central_timezone(client, api, make_company):
    """Indiana/Central is a real case for this client, not a hypothetical."""
    company = make_company("Border Heating", timezone="America/Indiana/Knox")
    assert company.get(f"{api}/tenants/current").json()["timezone"] == (
        "America/Indiana/Knox"
    )


def test_login_succeeds_and_scopes_to_the_only_company(client, api, make_company):
    company = make_company()
    response = client.post(
        f"{api}/auth/login",
        json={"email": company.owner_email, "password": company.owner_password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == company.tenant_id
    assert body["role"] == "owner"


def test_login_rejects_a_wrong_password(client, api, make_company):
    company = make_company()
    response = client.post(
        f"{api}/auth/login",
        json={"email": company.owner_email, "password": "not-the-password"},
    )
    assert response.status_code == 401


def test_login_for_an_unknown_email_is_indistinguishable(client, api):
    response = client.post(
        f"{api}/auth/login",
        json={"email": "nobody@example.com", "password": "anything-at-all"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_login_is_case_insensitive_on_email(client, api, make_company):
    company = make_company(email="Dale.Owner@Example.COM")
    response = client.post(
        f"{api}/auth/login",
        json={"email": "dale.owner@example.com", "password": company.owner_password},
    )
    assert response.status_code == 200


def test_me_returns_the_active_company_and_all_memberships(api, make_company):
    company = make_company("Northline Mechanical")
    body = company.get(f"{api}/auth/me").json()

    assert body["email"] == company.owner_email.lower()
    assert body["active_tenant_id"] == company.tenant_id
    assert body["active_role"] == "owner"
    assert body["is_superadmin"] is False
    assert len(body["memberships"]) == 1
    assert body["memberships"][0]["tenant_name"] == "Northline Mechanical"


def test_refresh_returns_a_new_usable_access_token(client, api, make_company):
    company = make_company()
    response = client.post(
        f"{api}/auth/refresh", json={"refresh_token": company.refresh_token}
    )
    assert response.status_code == 200
    new_token = response.json()["access_token"]
    assert company.get(f"{api}/tenants/current", token=new_token).status_code == 200


def test_an_access_token_is_not_accepted_as_a_refresh_token(client, api, make_company):
    """Token type confusion.

    A long-lived refresh token being usable as an access token -- or the reverse
    -- is a classic mistake. The `typ` claim is checked on decode.
    """
    company = make_company()
    response = client.post(
        f"{api}/auth/refresh", json={"refresh_token": company.access_token}
    )
    assert response.status_code == 401


def test_a_refresh_token_is_not_accepted_as_a_bearer_token(api, make_company):
    company = make_company()
    response = company.get(f"{api}/tenants/current", token=company.refresh_token)
    assert response.status_code == 401


def test_requests_without_a_token_are_rejected(client, api):
    assert client.get(f"{api}/tenants/current").status_code == 401
    assert client.get(f"{api}/memberships").status_code == 401
    assert client.get(f"{api}/audit-log").status_code == 401


def test_a_user_in_two_companies_gets_an_unscoped_token_and_must_choose(
    client, api, make_company
):
    """The bookkeeper case.

    Two of the client's contractors share an accountant, so one identity in two
    companies is a real requirement, not a future nicety. Logging in without
    naming a company yields a token with no tenant, which can reach /auth/me and
    /auth/switch-tenant and nothing else.
    """
    company_a = make_company("Northline Mechanical")
    company_b = make_company("Riverside Plumbing")

    # Invite the same person into both companies.
    shared_email = "bookkeeper@example.com"
    tokens = []
    for company in (company_a, company_b):
        invite = company.post(
            f"{api}/invitations", json={"email": shared_email, "role": "accountant"}
        ).json()
        tokens.append(invite["accept_url"].split("token=")[1])

    accept_a = client.post(
        f"{api}/invitations/accept",
        json={
            "token": tokens[0],
            "full_name": "Sam Bookkeeper",
            "password": "correct-horse-battery",
        },
    )
    assert accept_a.status_code == 200

    accept_b = client.post(
        f"{api}/invitations/accept",
        json={"token": tokens[1], "password": "correct-horse-battery"},
    )
    assert accept_b.status_code == 200

    # Logging in without naming a company: no tenant on the token.
    login = client.post(
        f"{api}/auth/login",
        json={"email": shared_email, "password": "correct-horse-battery"},
    ).json()
    assert login["tenant_id"] is None
    assert login["role"] is None

    unscoped = {"Authorization": f"Bearer {login['access_token']}"}

    # /auth/me works and shows both companies.
    me = client.get(f"{api}/auth/me", headers=unscoped).json()
    names = sorted(m["tenant_name"] for m in me["memberships"])
    assert names == ["Northline Mechanical", "Riverside Plumbing"]

    # A tenant-scoped endpoint does not.
    assert client.get(f"{api}/tenants/current", headers=unscoped).status_code == 403

    # After switching, it does -- and shows the chosen company.
    switched = client.post(
        f"{api}/auth/switch-tenant",
        headers=unscoped,
        json={"tenant_id": company_b.tenant_id},
    ).json()
    assert switched["tenant_id"] == company_b.tenant_id
    assert switched["role"] == "accountant"

    scoped = {"Authorization": f"Bearer {switched['access_token']}"}
    tenant = client.get(f"{api}/tenants/current", headers=scoped).json()
    assert tenant["name"] == "Riverside Plumbing"


def test_deactivating_a_user_takes_effect_immediately(api, make_company, client):
    """The role in a token is a claim; the database is the fact.

    `get_current_membership` re-reads on every request, so revoking access does
    not wait for an access token to expire.
    """
    company = make_company()
    invite = company.post(
        f"{api}/invitations", json={"email": "tech@example.com", "role": "dispatcher"}
    ).json()
    token = invite["accept_url"].split("token=")[1]

    accepted = client.post(
        f"{api}/invitations/accept",
        json={
            "token": token,
            "full_name": "Dana Dispatcher",
            "password": "correct-horse-battery",
        },
    ).json()
    dispatcher_headers = {"Authorization": f"Bearer {accepted['access_token']}"}

    assert (
        client.get(f"{api}/memberships", headers=dispatcher_headers).status_code == 200
    )

    members = company.get(f"{api}/memberships").json()["items"]
    dispatcher = next(m for m in members if m["email"] == "tech@example.com")
    company.patch(f"{api}/memberships/{dispatcher['id']}", json={"is_active": False})

    # Same token, now refused.
    response = client.get(f"{api}/memberships", headers=dispatcher_headers)
    assert response.status_code == 403
