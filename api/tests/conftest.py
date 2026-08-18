"""Test fixtures.

Environment variables are set at the very top of this module, before anything
from `app` is imported, because `app.core.config` builds its Settings object at
import time. Environment variables take precedence over the .env file in
pydantic-settings, so this reliably redirects the whole test run at
`serviceline_test`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]

TEST_APP_URL = (
    "postgresql+psycopg://serviceline_app:app_dev_2026@localhost:5432/serviceline_test"
)
TEST_ADMIN_URL = (
    "postgresql+psycopg://serviceline_owner:owner_dev_2026"
    "@localhost:5432/serviceline_test"
)

os.environ["DATABASE_URL"] = TEST_APP_URL
os.environ["DATABASE_ADMIN_URL"] = TEST_ADMIN_URL
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("JWT_SECRET", "test-only-secret-do-not-use-anywhere-else")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, bind_context
from app.main import app
from app.models import RLS_TABLES

ALL_TABLES = ("audit_log", "invitations", "memberships", "users", "tenants")


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_database() -> None:
    """Bring the test database to head once per session."""
    from alembic.config import Config

    from alembic import command

    assert "serviceline_test" in settings.database_url, (
        "Refusing to run: tests are not pointed at serviceline_test. "
        f"Got {settings.database_url!r}"
    )

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def admin_engine():
    """An engine on the *owning* role, for setup and teardown only.

    TRUNCATE is a table-level operation, so it is not blocked by row-level
    security -- which is exactly why cleanup uses it rather than DELETE. No test
    may use this engine to read or write rows; doing so would test the wrong
    role entirely.
    """
    engine = create_engine(settings.database_admin_url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(_migrate_test_database, admin_engine) -> Iterator[None]:
    with admin_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(ALL_TABLES)} CASCADE"))
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient with lifespan run.

    Entering the context manager triggers `verify_isolation()`, so every test
    session also re-proves that the database really is enforcing RLS.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Iterator[Session]:
    """A raw session on the application role, with NO context bound.

    Tests use this to poke at the database the way the API does, and to prove
    what happens when tenant context is missing or belongs to someone else.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def bound_db():
    """Factory for a session bound to a given tenant (and optionally user)."""
    sessions: list[Session] = []

    def _make(
        tenant_id: uuid.UUID | str | None = None,
        user_id: uuid.UUID | str | None = None,
    ) -> Session:
        session = SessionLocal()
        bind_context(session, user_id=user_id, tenant_id=tenant_id)
        sessions.append(session)
        return session

    yield _make

    for session in sessions:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# Company factory
# ---------------------------------------------------------------------------


class Company:
    """A signed-up tenant plus its owner's credentials and token."""

    def __init__(self, client: TestClient, data: dict, email: str, password: str):
        self._client = client
        self.tenant_id: str = data["tenant_id"]
        self.access_token: str = data["access_token"]
        self.refresh_token: str = data["refresh_token"]
        self.owner_email = email
        self.owner_password = password

    def headers(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.access_token}"}

    def get(self, path: str, token: str | None = None, **kw):
        return self._client.get(path, headers=self.headers(token), **kw)

    def post(self, path: str, token: str | None = None, **kw):
        return self._client.post(path, headers=self.headers(token), **kw)

    def patch(self, path: str, token: str | None = None, **kw):
        return self._client.patch(path, headers=self.headers(token), **kw)

    def delete(self, path: str, token: str | None = None, **kw):
        return self._client.delete(path, headers=self.headers(token), **kw)


@pytest.fixture
def make_company(client: TestClient):
    """Create a company through the public signup endpoint.

    Deliberately uses the real HTTP flow rather than inserting rows directly, so
    every test starts from state the application itself can produce.
    """
    counter = {"n": 0}

    def _make(
        name: str | None = None,
        *,
        email: str | None = None,
        password: str = "correct-horse-battery",
        timezone: str = "America/New_York",
    ) -> Company:
        counter["n"] += 1
        n = counter["n"]
        name = name or f"Test Mechanical {n}"
        email = email or f"owner{n}-{uuid.uuid4().hex[:8]}@example.com"

        response = client.post(
            f"{settings.api_v1_prefix}/auth/signup",
            json={
                "company_name": name,
                "trade_type": "hvac",
                "timezone": timezone,
                "full_name": f"Owner {n}",
                "email": email,
                "password": password,
            },
        )
        assert response.status_code == 201, response.text
        return Company(client, response.json(), email, password)

    return _make


@pytest.fixture
def api() -> str:
    return settings.api_v1_prefix


@pytest.fixture
def rls_tables() -> tuple[str, ...]:
    return RLS_TABLES
