"""Operational endpoints: health, readiness, and the root redirect."""

from __future__ import annotations


def test_healthz_does_not_touch_the_database(client):
    """Liveness must not depend on Postgres.

    A liveness probe that queries the database will take the whole API out of
    rotation during a brief database blip, turning a degraded service into an
    outage. Database health belongs in /readyz.
    """
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_checks_the_database(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_root_redirects_to_the_docs(client):
    """The root URL must not be a dead end.

    Anyone who types the API host into a browser previously got a bare
    `{"detail":"Not Found"}` and reasonably concluded the server was down.
    """
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"] == "/docs"

    followed = client.get("/")
    assert followed.status_code == 200
    assert "text/html" in followed.headers["content-type"]


def test_openapi_document_is_served(client):
    """The frontend's TypeScript client is generated from this document."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "ServiceLine API"
