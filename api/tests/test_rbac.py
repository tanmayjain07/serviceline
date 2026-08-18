"""Role-based access control.

The client was explicit: "I know enough to check whether hiding a button is your
idea of security." Every assertion here is against the API, not the UI.
"""

from __future__ import annotations

import pytest

ROLES = ["owner", "dispatcher", "technician", "accountant"]


@pytest.fixture
def company_with_team(client, api, make_company):
    """A company with one member of every role.

    Returns (owner_company, {role: auth_headers}).
    """
    owner = make_company("Northline Mechanical")
    headers = {"owner": {"Authorization": f"Bearer {owner.access_token}"}}

    for role in ("dispatcher", "technician", "accountant"):
        invite = owner.post(
            f"{api}/invitations", json={"email": f"{role}@example.com", "role": role}
        )
        assert invite.status_code == 201, invite.text
        token = invite.json()["accept_url"].split("token=")[1]

        accepted = client.post(
            f"{api}/invitations/accept",
            json={
                "token": token,
                "full_name": f"{role.title()} Person",
                "password": "correct-horse-battery",
            },
        )
        assert accepted.status_code == 200, accepted.text
        headers[role] = {"Authorization": f"Bearer {accepted.json()['access_token']}"}

    return owner, headers


# ---------------------------------------------------------------------------
# Reading the team roster
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["owner", "dispatcher", "accountant"])
def test_team_roster_is_readable_by_owner_dispatcher_and_accountant(
    client, api, company_with_team, role
):
    _owner, headers = company_with_team
    assert client.get(f"{api}/memberships", headers=headers[role]).status_code == 200


def test_technicians_cannot_read_the_team_roster(client, api, company_with_team):
    """A technician has no business reason to see the roster.

    The client's brief: a technician "cannot see pricing or other techs'
    schedules". Extending that to the roster is the conservative reading, and
    it is cheaper to loosen later than to discover a leak.
    """
    _owner, headers = company_with_team
    response = client.get(f"{api}/memberships", headers=headers["technician"])
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Company settings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["dispatcher", "technician", "accountant"])
def test_only_the_owner_can_change_company_settings(
    client, api, company_with_team, role
):
    _owner, headers = company_with_team
    response = client.patch(
        f"{api}/tenants/current", headers=headers[role], json={"name": "Renamed Co"}
    )
    assert response.status_code == 403


def test_the_owner_can_change_company_settings_and_it_is_audited(
    api, company_with_team
):
    owner, _headers = company_with_team
    response = owner.patch(
        f"{api}/tenants/current",
        json={"name": "Northline Mechanical & Plumbing", "trade_type": "multi_trade"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Northline Mechanical & Plumbing"
    assert response.json()["trade_type"] == "multi_trade"

    actions = [e["action"] for e in owner.get(f"{api}/audit-log").json()["items"]]
    assert "tenant.updated" in actions


def test_everyone_can_read_their_own_company(client, api, company_with_team):
    _owner, headers = company_with_team
    for role in ROLES:
        response = client.get(f"{api}/tenants/current", headers=headers[role])
        assert response.status_code == 200, role
        assert response.json()["name"] == "Northline Mechanical"


# ---------------------------------------------------------------------------
# Invitations and the audit log
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["dispatcher", "technician", "accountant"])
def test_only_the_owner_can_invite(client, api, company_with_team, role):
    _owner, headers = company_with_team
    response = client.post(
        f"{api}/invitations",
        headers=headers[role],
        json={"email": "someone@example.com", "role": "technician"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("role", ["dispatcher", "technician", "accountant"])
def test_only_the_owner_can_read_the_audit_log(client, api, company_with_team, role):
    """The client's insurance carrier asks about the audit log.

    It records who changed what, including role changes, so it is owner-only.
    """
    _owner, headers = company_with_team
    assert client.get(f"{api}/audit-log", headers=headers[role]).status_code == 403


@pytest.mark.parametrize("role", ["dispatcher", "technician", "accountant"])
def test_only_the_owner_can_change_roles(client, api, company_with_team, role):
    owner, headers = company_with_team
    members = owner.get(f"{api}/memberships").json()["items"]
    target = next(m for m in members if m["role"] == "technician")

    response = client.patch(
        f"{api}/memberships/{target['id']}",
        headers=headers[role],
        json={"role": "owner"},
    )
    assert response.status_code == 403


def test_a_technician_cannot_promote_themselves(client, api, company_with_team):
    """Privilege escalation, attempted the obvious way."""
    owner, headers = company_with_team
    members = owner.get(f"{api}/memberships").json()["items"]
    tech = next(m for m in members if m["role"] == "technician")

    response = client.patch(
        f"{api}/memberships/{tech['id']}",
        headers=headers["technician"],
        json={"role": "owner"},
    )
    assert response.status_code == 403

    # And confirm nothing moved.
    members_after = owner.get(f"{api}/memberships").json()["items"]
    assert (
        next(m for m in members_after if m["id"] == tech["id"])["role"] == "technician"
    )


# ---------------------------------------------------------------------------
# The last-owner guard
# ---------------------------------------------------------------------------


def test_a_company_cannot_remove_its_only_owner(api, make_company):
    """Otherwise the company locks itself out and recovery is a support ticket."""
    owner = make_company()
    members = owner.get(f"{api}/memberships").json()["items"]
    own_membership = members[0]

    demote = owner.patch(
        f"{api}/memberships/{own_membership['id']}", json={"role": "dispatcher"}
    )
    assert demote.status_code == 400
    assert "at least one active owner" in demote.json()["detail"]

    deactivate = owner.patch(
        f"{api}/memberships/{own_membership['id']}", json={"is_active": False}
    )
    assert deactivate.status_code == 400


def test_the_only_owner_can_step_down_once_someone_else_is_promoted(
    api, company_with_team
):
    owner, _headers = company_with_team
    members = owner.get(f"{api}/memberships").json()["items"]
    dispatcher = next(m for m in members if m["role"] == "dispatcher")
    self_membership = next(m for m in members if m["role"] == "owner")

    promote = owner.patch(
        f"{api}/memberships/{dispatcher['id']}", json={"role": "owner"}
    )
    assert promote.status_code == 200

    step_down = owner.patch(
        f"{api}/memberships/{self_membership['id']}", json={"role": "dispatcher"}
    )
    assert step_down.status_code == 200
