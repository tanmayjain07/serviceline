"""Jobs: numbering, scheduling across timezones, permissions, and the status machine.

The tests that matter most here are the ones covering decisions taken during
scoping rather than obvious CRUD -- particularly that two jobs in different
timezones do not falsely collide, which is the entire justification for storing
a window twice.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

TODAY = date(2026, 8, 14).isoformat()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def add_member(client, api, company, role: str, name: str) -> dict:
    """Invite someone and accept, returning their auth headers."""
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    invite = company.post(f"{api}/invitations", json={"email": email, "role": role})
    assert invite.status_code == 201, invite.text
    token = invite.json()["accept_url"].split("token=")[1]

    accepted = client.post(
        f"{api}/invitations/accept",
        json={"token": token, "full_name": name, "password": "correct-horse-battery"},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "membership_id": None,
        "email": email,
    }


def membership_id_for(company, api, email: str) -> str:
    rows = company.get(f"{api}/memberships").json()
    items = rows.get("items", rows)
    for m in items:
        if m["email"] == email:
            return m["id"]
    raise AssertionError(f"no membership for {email}")


def make_customer(company, api, *, timezone: str, name: str = "Acme Ltd") -> dict:
    response = company.post(
        f"{api}/customers",
        json={
            "kind": "company",
            "name": name,
            "phone": "555-0100",
            "address": {
                "line1": "12 Depot Road",
                "city": "Toledo",
                "state": "OH",
                "postal_code": "43604",
                "timezone": timezone,
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_job(company, api, customer, **overrides) -> dict:
    payload = {
        "customer_id": customer["id"],
        "service_address_id": customer["addresses"][0]["id"],
        "title": "Furnace not igniting",
        "job_type": "repair",
    }
    payload.update(overrides)
    response = company.post(f"{api}/jobs", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Job numbers
# ---------------------------------------------------------------------------


def test_job_numbers_are_sequential_within_a_company(make_company, api):
    company = make_company()
    customer = make_customer(company, api, timezone="America/New_York")

    numbers = [make_job(company, api, customer)["job_number"] for _ in range(3)]
    year = date.today().year

    assert numbers == [f"{year}-0001", f"{year}-0002", f"{year}-0003"]


def test_job_numbers_restart_per_company(make_company, api):
    """Two companies both start at 0001.

    The counter is per tenant, so a busy contractor does not push a new
    customer's first job number into the hundreds.
    """
    first, second = make_company(), make_company()
    c1 = make_customer(first, api, timezone="America/New_York")
    c2 = make_customer(second, api, timezone="America/New_York")

    make_job(first, api, c1)
    make_job(first, api, c1)

    assert make_job(second, api, c2)["job_number"].endswith("-0001")


# ---------------------------------------------------------------------------
# Scheduling across timezones -- the reason windows are stored twice
# ---------------------------------------------------------------------------


def test_window_is_converted_using_the_address_timezone(make_company, api):
    """08:00 Eastern and 08:00 Central are not the same instant."""
    company = make_company(timezone="America/New_York")

    eastern = make_customer(company, api, timezone="America/New_York", name="Ohio Co")
    central = make_customer(
        company, api, timezone="America/Indiana/Knox", name="Indiana Co"
    )

    window = {
        "scheduled_date": TODAY,
        "arrival_window_start": "08:00:00",
        "arrival_window_end": "12:00:00",
    }
    a = make_job(company, api, eastern, **window)
    b = make_job(company, api, central, **window)

    assert a["window_start_utc"] != b["window_start_utc"]
    assert a["window_start_utc"].startswith("2026-08-14T12:00")  # EDT = UTC-4
    assert b["window_start_utc"].startswith("2026-08-14T13:00")  # CDT = UTC-5


def test_jobs_in_different_timezones_do_not_falsely_conflict(make_company, api, client):
    """The Ohio/Indiana case, end to end.

    Ohio 08:00-12:00 Eastern is 12:00-16:00 UTC.
    Indiana 11:00-13:00 Central is 16:00-18:00 UTC.

    Their wall clocks overlap between 11 and 12; their instants merely touch.
    One technician can work both, and the API must not refuse the second.
    """
    company = make_company()
    tech = add_member(client, api, company, "technician", "Mike Petrov")
    tech_id = membership_id_for(company, api, tech["email"])

    ohio = make_customer(company, api, timezone="America/New_York", name="Ohio Co")
    indiana = make_customer(
        company, api, timezone="America/Indiana/Knox", name="Indiana Co"
    )

    make_job(
        company,
        api,
        ohio,
        scheduled_date=TODAY,
        arrival_window_start="08:00:00",
        arrival_window_end="12:00:00",
        lead_membership_id=tech_id,
    )

    second = make_job(company, api, indiana)
    response = company.post(
        f"{api}/jobs/{second['id']}/schedule",
        json={
            "scheduled_date": TODAY,
            "arrival_window_start": "11:00:00",
            "arrival_window_end": "13:00:00",
            "lead_membership_id": tech_id,
        },
    )
    assert response.status_code == 200, response.text


def test_overlapping_jobs_in_the_same_timezone_are_refused(make_company, api, client):
    company = make_company()
    tech = add_member(client, api, company, "technician", "Mike Petrov")
    tech_id = membership_id_for(company, api, tech["email"])
    customer = make_customer(company, api, timezone="America/New_York")

    make_job(
        company,
        api,
        customer,
        scheduled_date=TODAY,
        arrival_window_start="08:00:00",
        arrival_window_end="12:00:00",
        lead_membership_id=tech_id,
    )

    second = make_job(company, api, customer)
    response = company.post(
        f"{api}/jobs/{second['id']}/schedule",
        json={
            "scheduled_date": TODAY,
            "arrival_window_start": "11:00:00",
            "arrival_window_end": "13:00:00",
            "lead_membership_id": tech_id,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["conflicts"], "the clash should be named"


def test_a_dispatcher_may_double_book_deliberately(make_company, api, client):
    """The clash is a warning, not a prohibition.

    Squeezing a callback between two installs is normal, and software that
    refuses would be overruling the person holding the phone.
    """
    company = make_company()
    tech = add_member(client, api, company, "technician", "Mike Petrov")
    tech_id = membership_id_for(company, api, tech["email"])
    customer = make_customer(company, api, timezone="America/New_York")

    make_job(
        company,
        api,
        customer,
        scheduled_date=TODAY,
        arrival_window_start="08:00:00",
        arrival_window_end="12:00:00",
        lead_membership_id=tech_id,
    )
    second = make_job(company, api, customer)

    response = company.post(
        f"{api}/jobs/{second['id']}/schedule",
        json={
            "scheduled_date": TODAY,
            "arrival_window_start": "11:00:00",
            "arrival_window_end": "13:00:00",
            "lead_membership_id": tech_id,
            "allow_conflicts": True,
        },
    )
    assert response.status_code == 200, response.text


def test_back_to_back_jobs_are_not_a_conflict(make_company, api, client):
    company = make_company()
    tech = add_member(client, api, company, "technician", "Mike Petrov")
    tech_id = membership_id_for(company, api, tech["email"])
    customer = make_customer(company, api, timezone="America/New_York")

    make_job(
        company,
        api,
        customer,
        scheduled_date=TODAY,
        arrival_window_start="08:00:00",
        arrival_window_end="12:00:00",
        lead_membership_id=tech_id,
    )
    second = make_job(company, api, customer)

    response = company.post(
        f"{api}/jobs/{second['id']}/schedule",
        json={
            "scheduled_date": TODAY,
            "arrival_window_start": "12:00:00",
            "arrival_window_end": "14:00:00",
            "lead_membership_id": tech_id,
        },
    )
    assert response.status_code == 200, response.text


def test_changing_an_address_timezone_moves_its_open_jobs(make_company, api):
    """A corrected timezone must move the appointments booked at that address.

    Otherwise the board keeps showing the old instants and the double-booking
    check silently uses stale data.
    """
    company = make_company()
    customer = make_customer(company, api, timezone="America/New_York")
    address_id = customer["addresses"][0]["id"]

    job = make_job(
        company,
        api,
        customer,
        scheduled_date=TODAY,
        arrival_window_start="08:00:00",
        arrival_window_end="12:00:00",
    )
    assert job["window_start_utc"].startswith("2026-08-14T12:00")

    moved = company.patch(
        f"{api}/customers/{customer['id']}/addresses/{address_id}",
        json={"timezone": "America/Indiana/Knox"},
    )
    assert moved.status_code == 200, moved.text

    refreshed = company.get(f"{api}/jobs/{job['id']}").json()
    assert refreshed["window_start_utc"].startswith("2026-08-14T13:00")
    # The promise to the customer is unchanged -- only its interpretation moved.
    assert refreshed["arrival_window_start"] == "08:00:00"


# ---------------------------------------------------------------------------
# What a technician may see and do
# ---------------------------------------------------------------------------


def test_technicians_never_receive_pricing(make_company, api, client):
    """From the brief: a technician "cannot see pricing".

    The response is built from a schema with no price field, so this asserts the
    field is absent rather than null.
    """
    company = make_company()
    tech = add_member(client, api, company, "technician", "Mike Petrov")
    tech_id = membership_id_for(company, api, tech["email"])
    customer = make_customer(company, api, timezone="America/New_York")

    job = make_job(
        company,
        api,
        customer,
        lead_membership_id=tech_id,
        line_items=[
            {
                "kind": "labor",
                "description": "Diagnostic",
                "quantity": "1.50",
                "unit_price_cents": 12000,
            }
        ],
    )

    as_owner = company.get(f"{api}/jobs/{job['id']}").json()
    assert as_owner["total_cents"] == 18000
    assert as_owner["line_items"][0]["unit_price_cents"] == 12000

    as_tech = client.get(f"{api}/jobs/{job['id']}", headers=tech["headers"])
    assert as_tech.status_code == 200
    body = as_tech.json()
    assert "total_cents" not in body
    assert "unit_price_cents" not in body["line_items"][0]
    # They can still see what they logged.
    assert body["line_items"][0]["description"] == "Diagnostic"


def test_technicians_cannot_read_a_job_they_are_not_on(make_company, api, client):
    """Guessing the ID must not help -- the rule is enforced on read, not by
    filtering the list endpoint alone."""
    company = make_company()
    mine = add_member(client, api, company, "technician", "Mike Petrov")
    theirs = add_member(client, api, company, "technician", "Sam Osei")
    theirs_id = membership_id_for(company, api, theirs["email"])
    customer = make_customer(company, api, timezone="America/New_York")

    job = make_job(company, api, customer, lead_membership_id=theirs_id)

    response = client.get(f"{api}/jobs/{job['id']}", headers=mine["headers"])
    assert response.status_code == 404


def test_technicians_see_only_their_own_jobs_in_the_list(make_company, api, client):
    company = make_company()
    mine = add_member(client, api, company, "technician", "Mike Petrov")
    mine_id = membership_id_for(company, api, mine["email"])
    other = add_member(client, api, company, "technician", "Sam Osei")
    other_id = membership_id_for(company, api, other["email"])
    customer = make_customer(company, api, timezone="America/New_York")

    make_job(company, api, customer, lead_membership_id=mine_id, title="Mine")
    make_job(company, api, customer, lead_membership_id=other_id, title="Theirs")

    listed = client.get(f"{api}/jobs", headers=mine["headers"]).json()
    assert [j["title"] for j in listed["items"]] == ["Mine"]
    assert listed["total"] == 1


def test_technicians_cannot_reschedule(make_company, api, client):
    company = make_company()
    tech = add_member(client, api, company, "technician", "Mike Petrov")
    tech_id = membership_id_for(company, api, tech["email"])
    customer = make_customer(company, api, timezone="America/New_York")
    job = make_job(company, api, customer, lead_membership_id=tech_id)

    response = client.patch(
        f"{api}/jobs/{job['id']}",
        headers=tech["headers"],
        json={"scheduled_date": TODAY},
    )
    assert response.status_code == 403

    response = client.post(
        f"{api}/jobs/{job['id']}/schedule",
        headers=tech["headers"],
        json={"scheduled_date": TODAY},
    )
    assert response.status_code == 403


def test_technicians_cannot_read_internal_notes(make_company, api, client):
    company = make_company()
    tech = add_member(client, api, company, "technician", "Mike Petrov")
    tech_id = membership_id_for(company, api, tech["email"])
    customer = make_customer(company, api, timezone="America/New_York")

    job = make_job(
        company,
        api,
        customer,
        lead_membership_id=tech_id,
        internal_notes="Customer disputes every invoice. Photograph everything.",
        customer_notes="Please use the side gate.",
    )

    body = client.get(f"{api}/jobs/{job['id']}", headers=tech["headers"]).json()
    assert body["internal_notes"] is None
    assert body["customer_notes"] == "Please use the side gate."


def test_technicians_cannot_browse_the_customer_book(make_company, api, client):
    """A technician who leaves should not be able to export the customer list."""
    company = make_company()
    tech = add_member(client, api, company, "technician", "Mike Petrov")

    response = client.get(f"{api}/customers", headers=tech["headers"])
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# The status machine, over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "expected"),
    [("scheduled", 200), ("invoiced", 409), ("closed", 409)],
)
def test_status_transitions_are_enforced(make_company, api, target, expected):
    company = make_company()
    customer = make_customer(company, api, timezone="America/New_York")
    job = make_job(company, api, customer)

    response = company.post(f"{api}/jobs/{job['id']}/status", json={"status": target})
    assert response.status_code == expected, response.text


def test_a_technician_cannot_invoice_a_job(make_company, api, client):
    company = make_company()
    tech = add_member(client, api, company, "technician", "Mike Petrov")
    tech_id = membership_id_for(company, api, tech["email"])
    customer = make_customer(company, api, timezone="America/New_York")
    job = make_job(company, api, customer, lead_membership_id=tech_id)

    response = client.post(
        f"{api}/jobs/{job['id']}/status",
        headers=tech["headers"],
        json={"status": "invoiced"},
    )
    assert response.status_code == 403


def test_completing_a_job_stamps_completed_at(make_company, api):
    company = make_company()
    customer = make_customer(company, api, timezone="America/New_York")
    job = make_job(company, api, customer)

    for target in ("scheduled", "en_route", "in_progress", "complete"):
        response = company.post(
            f"{api}/jobs/{job['id']}/status", json={"status": target}
        )
        assert response.status_code == 200, f"{target}: {response.text}"

    assert response.json()["completed_at"] is not None


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


def test_a_job_has_at_most_one_lead(make_company, api, client):
    """Reassigning replaces the lead rather than adding a second one."""
    company = make_company()
    first = add_member(client, api, company, "technician", "Mike Petrov")
    second = add_member(client, api, company, "technician", "Sam Osei")
    first_id = membership_id_for(company, api, first["email"])
    second_id = membership_id_for(company, api, second["email"])
    customer = make_customer(company, api, timezone="America/New_York")

    job = make_job(company, api, customer, lead_membership_id=first_id)
    company.post(
        f"{api}/jobs/{job['id']}/schedule", json={"lead_membership_id": second_id}
    )

    body = company.get(f"{api}/jobs/{job['id']}").json()
    leads = [a for a in body["assignments"] if a["is_lead"]]
    assert len(leads) == 1
    assert leads[0]["membership_id"] == second_id


def test_accountants_cannot_be_assigned_work(make_company, api, client):
    company = make_company()
    accountant = add_member(client, api, company, "accountant", "Janet Cole")
    accountant_id = membership_id_for(company, api, accountant["email"])
    customer = make_customer(company, api, timezone="America/New_York")
    job = make_job(company, api, customer)

    response = company.post(
        f"{api}/jobs/{job['id']}/schedule",
        json={"lead_membership_id": accountant_id},
    )
    assert response.status_code == 400
    assert "read-only" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Tenant isolation, for the new tables
# ---------------------------------------------------------------------------


def test_a_company_cannot_read_another_companys_job(make_company, api):
    ours, theirs = make_company(), make_company()
    their_customer = make_customer(theirs, api, timezone="America/New_York")
    their_job = make_job(theirs, api, their_customer)

    assert ours.get(f"{api}/jobs/{their_job['id']}").status_code == 404
    assert (
        ours.post(
            f"{api}/jobs/{their_job['id']}/status", json={"status": "scheduled"}
        ).status_code
        == 404
    )


def test_a_company_cannot_read_another_companys_customer(make_company, api):
    ours, theirs = make_company(), make_company()
    their_customer = make_customer(theirs, api, timezone="America/New_York")

    assert ours.get(f"{api}/customers/{their_customer['id']}").status_code == 404
    assert (
        ours.patch(
            f"{api}/customers/{their_customer['id']}", json={"name": "Hijacked"}
        ).status_code
        == 404
    )


def test_a_job_cannot_borrow_another_companys_customer(make_company, api):
    """Naming a real ID from another tenant must not work either."""
    ours, theirs = make_company(), make_company()
    their_customer = make_customer(theirs, api, timezone="America/New_York")

    response = ours.post(
        f"{api}/jobs",
        json={
            "customer_id": their_customer["id"],
            "service_address_id": their_customer["addresses"][0]["id"],
            "title": "Should not exist",
        },
    )
    assert response.status_code == 404


def test_customer_search_only_finds_your_own(make_company, api):
    ours, theirs = make_company(), make_company()
    make_customer(theirs, api, timezone="America/New_York", name="Distinctive Name Ltd")
    make_customer(ours, api, timezone="America/New_York", name="Our Own Company")

    found = ours.get(f"{api}/customers", params={"search": "Distinctive"}).json()
    assert found["total"] == 0
    assert found["items"] == []
