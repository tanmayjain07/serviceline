"""The invitation lifecycle, and the seat limits that gate it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text


def token_of(invite: dict) -> str:
    return parse_qs(urlparse(invite["accept_url"]).query)["token"][0]


def invite_someone(company, api, email: str, role: str = "technician") -> dict:
    response = company.post(f"{api}/invitations", json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_invite_preview_accept_joins_the_company_with_the_right_role(
    client, api, make_company
):
    company = make_company("Northline Mechanical")
    invite = invite_someone(company, api, "mike@example.com", "technician")
    token = token_of(invite)

    preview = client.get(f"{api}/invitations/preview", params={"token": token})
    assert preview.status_code == 200
    assert preview.json() == {
        "tenant_name": "Northline Mechanical",
        "email": "mike@example.com",
        "role": "technician",
        "expires_at": preview.json()["expires_at"],
        "requires_signup": True,
    }

    accepted = client.post(
        f"{api}/invitations/accept",
        json={
            "token": token,
            "full_name": "Mike Technician",
            "password": "correct-horse-battery",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "technician"
    assert accepted.json()["tenant_id"] == company.tenant_id

    members = company.get(f"{api}/memberships").json()
    assert members["total"] == 2
    emails = {m["email"] for m in members["items"]}
    assert "mike@example.com" in emails

    actions = [e["action"] for e in company.get(f"{api}/audit-log").json()["items"]]
    assert "invitation.created" in actions
    assert "invitation.accepted" in actions


def test_the_raw_token_is_never_stored(client, api, make_company, bound_db):
    """Only the SHA-256 hash is persisted.

    A database dump therefore does not yield working invitation links.
    """
    company = make_company()
    invite = invite_someone(company, api, "mike@example.com")
    raw = token_of(invite)

    session = bound_db(tenant_id=company.tenant_id)
    stored = session.execute(text("SELECT token_hash FROM invitations")).scalar_one()
    assert stored != raw
    assert len(stored) == 64  # hex sha256


def test_an_invitation_can_only_be_accepted_once(client, api, make_company):
    company = make_company()
    token = token_of(invite_someone(company, api, "mike@example.com"))

    first = client.post(
        f"{api}/invitations/accept",
        json={
            "token": token,
            "full_name": "Mike Technician",
            "password": "correct-horse-battery",
        },
    )
    assert first.status_code == 200

    second = client.post(
        f"{api}/invitations/accept",
        json={
            "token": token,
            "full_name": "Someone Else",
            "password": "correct-horse-battery",
        },
    )
    assert second.status_code == 404


# ---------------------------------------------------------------------------
# Failure modes, all indistinguishable from one another
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_token",
    ["completely-made-up-token", "x" * 43],
    ids=["nonsense", "right-shape-wrong-value"],
)
def test_an_unknown_token_reveals_nothing(client, api, make_company, bad_token):
    make_company()
    assert (
        client.get(
            f"{api}/invitations/preview", params={"token": bad_token}
        ).status_code
        == 404
    )
    assert (
        client.post(f"{api}/invitations/accept", json={"token": bad_token}).status_code
        == 404
    )


def test_a_revoked_invitation_cannot_be_accepted(client, api, make_company):
    company = make_company()
    invite = invite_someone(company, api, "mike@example.com")
    token = token_of(invite)

    revoke = company.delete(f"{api}/invitations/{invite['id']}")
    assert revoke.status_code == 200

    response = client.post(
        f"{api}/invitations/accept",
        json={
            "token": token,
            "full_name": "Mike Technician",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 404
    assert company.get(f"{api}/invitations").json()[0]["status"] == "revoked"


def test_an_expired_invitation_cannot_be_accepted(client, api, make_company, bound_db):
    company = make_company()
    token = token_of(invite_someone(company, api, "mike@example.com"))

    # Age the invitation past its expiry. Done through the application role and
    # RLS policies, i.e. the same access the API itself has.
    session = bound_db(tenant_id=company.tenant_id)
    session.execute(
        text("UPDATE invitations SET expires_at = :past"),
        {"past": datetime.now(UTC) - timedelta(minutes=1)},
    )
    session.commit()

    response = client.post(
        f"{api}/invitations/accept",
        json={
            "token": token,
            "full_name": "Mike Technician",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 404
    assert company.get(f"{api}/invitations").json()[0]["status"] == "expired"


def test_accepting_without_a_password_is_refused_for_a_new_user(
    client, api, make_company
):
    company = make_company()
    token = token_of(invite_someone(company, api, "mike@example.com"))

    response = client.post(f"{api}/invitations/accept", json={"token": token})
    assert response.status_code == 400
    assert "choose a password" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Joining a second company with an existing account
# ---------------------------------------------------------------------------


def test_an_existing_account_must_prove_itself_to_accept(client, api, make_company):
    """Holding an invite link must not be enough to obtain someone's tokens.

    If the invited address already has a ServiceLine account, accepting requires
    that account's password. Without this check, anyone who intercepted an invite
    email could mint a session for an existing user.
    """
    company_a = make_company("Northline Mechanical")
    company_b = make_company("Riverside Plumbing")

    invite = invite_someone(company_b, api, company_a.owner_email, "accountant")
    token = token_of(invite)

    preview = client.get(f"{api}/invitations/preview", params={"token": token}).json()
    assert preview["requires_signup"] is False

    # No password: refused.
    assert (
        client.post(f"{api}/invitations/accept", json={"token": token}).status_code
        == 401
    )

    # Wrong password: refused.
    wrong = client.post(
        f"{api}/invitations/accept",
        json={"token": token, "password": "not-their-password"},
    )
    assert wrong.status_code == 401

    # Correct password: joined, and now a member of both companies.
    right = client.post(
        f"{api}/invitations/accept",
        json={"token": token, "password": company_a.owner_password},
    )
    assert right.status_code == 200
    assert right.json()["tenant_id"] == company_b.tenant_id
    assert right.json()["role"] == "accountant"

    me = client.get(
        f"{api}/auth/me",
        headers={"Authorization": f"Bearer {right.json()['access_token']}"},
    ).json()
    assert len(me["memberships"]) == 2


# ---------------------------------------------------------------------------
# Duplicate guards
# ---------------------------------------------------------------------------


def test_cannot_invite_an_existing_team_member(api, make_company):
    company = make_company()
    response = company.post(
        f"{api}/invitations",
        json={"email": company.owner_email, "role": "dispatcher"},
    )
    assert response.status_code == 409
    assert "already on your team" in response.json()["detail"]


def test_cannot_send_two_pending_invitations_to_the_same_address(api, make_company):
    company = make_company()
    invite_someone(company, api, "mike@example.com")
    response = company.post(
        f"{api}/invitations", json={"email": "mike@example.com", "role": "dispatcher"}
    )
    assert response.status_code == 409


def test_a_revoked_invitation_can_be_reissued(api, make_company):
    company = make_company()
    first = invite_someone(company, api, "mike@example.com", "technician")
    company.delete(f"{api}/invitations/{first['id']}")

    second = company.post(
        f"{api}/invitations", json={"email": "mike@example.com", "role": "dispatcher"}
    )
    assert second.status_code == 201
    assert second.json()["role"] == "dispatcher"


# ---------------------------------------------------------------------------
# Seat limits
# ---------------------------------------------------------------------------


def test_pending_invitations_count_towards_the_seat_limit(api, make_company):
    """The trial plan includes 5 seats, and the owner occupies one.

    Pending invitations are counted so the owner is told at invite time rather
    than discovering the problem as people accept one by one -- which the client
    would have experienced as the product being broken.
    """
    company = make_company()

    for n in range(4):
        invite_someone(company, api, f"tech{n}@example.com")

    tenant = company.get(f"{api}/tenants/current").json()
    assert tenant["seat_limit"] == 5
    assert tenant["seats_used"] == 1  # only the owner has actually joined

    blocked = company.post(
        f"{api}/invitations",
        json={"email": "onetoomany@example.com", "role": "technician"},
    )
    assert blocked.status_code == 402
    assert "Upgrade" in blocked.json()["detail"]


def test_revoking_an_invitation_frees_the_seat(api, make_company):
    company = make_company()
    invites = [invite_someone(company, api, f"tech{n}@example.com") for n in range(4)]

    assert (
        company.post(
            f"{api}/invitations",
            json={"email": "extra@example.com", "role": "technician"},
        ).status_code
        == 402
    )

    company.delete(f"{api}/invitations/{invites[0]['id']}")

    assert (
        company.post(
            f"{api}/invitations",
            json={"email": "extra@example.com", "role": "technician"},
        ).status_code
        == 201
    )


def test_deactivating_a_member_frees_a_seat_and_reactivating_reclaims_it(
    client, api, make_company
):
    company = make_company()

    # Fill four of the five seats with real members.
    member_ids = []
    for n in range(4):
        invite = invite_someone(company, api, f"tech{n}@example.com")
        client.post(
            f"{api}/invitations/accept",
            json={
                "token": token_of(invite),
                "full_name": f"Tech {n}",
                "password": "correct-horse-battery",
            },
        )

    tenant = company.get(f"{api}/tenants/current").json()
    assert tenant["seats_used"] == 5

    blocked = company.post(
        f"{api}/invitations", json={"email": "extra@example.com", "role": "technician"}
    )
    assert blocked.status_code == 402

    members = company.get(f"{api}/memberships").json()["items"]
    victim = next(m for m in members if m["email"] == "tech0@example.com")
    member_ids.append(victim["id"])

    company.patch(f"{api}/memberships/{victim['id']}", json={"is_active": False})
    assert company.get(f"{api}/tenants/current").json()["seats_used"] == 4

    # A seat is free again.
    assert (
        company.post(
            f"{api}/invitations",
            json={"email": "extra@example.com", "role": "technician"},
        ).status_code
        == 201
    )

    # Reactivating now would exceed the plan, so it is blocked with an upgrade
    # prompt rather than silently over-filling the company.
    reactivate = company.patch(
        f"{api}/memberships/{victim['id']}", json={"is_active": True}
    )
    assert reactivate.status_code == 402
