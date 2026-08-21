"""ServiceLine API application factory.

Note the startup check in `lifespan`. The application refuses to start if the
database is not actually enforcing tenant isolation -- if the role it connects
with can bypass RLS, or if any tenant-scoped table has policies missing. A
misconfigured environment fails loudly at boot rather than quietly serving one
company's data to another.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from app.models import RLS_TABLES
from app.routers import (
    audit,
    auth,
    customers,
    invitations,
    jobs,
    memberships,
    tenants,
)

logger = logging.getLogger("serviceline")


class IsolationCheckFailed(RuntimeError):
    """Raised at startup when the database is not enforcing tenant isolation."""


def verify_isolation() -> None:
    with engine.connect() as conn:
        role = conn.execute(text("SELECT current_user")).scalar_one()

        privileged = conn.execute(
            text(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )
        ).scalar_one()
        if privileged:
            raise IsolationCheckFailed(
                f"The API is connected as {role!r}, which is a superuser or has "
                "BYPASSRLS. Row-level security would not apply. Refusing to start."
            )

        rows = conn.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = ANY(:tables)
                """
            ),
            {"tables": list(RLS_TABLES)},
        ).all()

        found = {r[0] for r in rows}
        missing = set(RLS_TABLES) - found
        if missing:
            raise IsolationCheckFailed(
                f"Tables missing from the database: {sorted(missing)}. "
                "Have migrations been run?"
            )

        for name, enabled, forced, policy_count in rows:
            if not enabled:
                raise IsolationCheckFailed(
                    f"Table {name!r} does not have row-level security enabled."
                )
            if not forced:
                raise IsolationCheckFailed(
                    f"Table {name!r} does not have FORCE ROW LEVEL SECURITY, so "
                    "its owner would bypass the policies."
                )
            if policy_count == 0:
                raise IsolationCheckFailed(
                    f"Table {name!r} has RLS enabled but no policies, which "
                    "denies all access. This is almost certainly a mistake."
                )

        logger.info(
            "Tenant isolation verified: connected as %s, %d tables protected",
            role,
            len(rows),
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    verify_isolation()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="ServiceLine API",
        version="0.1.0",
        summary="Field service scheduling for HVAC and plumbing contractors.",
        description=(
            "Milestone 1: multi-tenancy, authentication, and role-based access "
            "control. Customers, jobs, and the dispatch board arrive in "
            "milestone 2."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = settings.api_v1_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(tenants.router, prefix=prefix)
    app.include_router(memberships.router, prefix=prefix)
    app.include_router(invitations.router, prefix=prefix)
    app.include_router(audit.router, prefix=prefix)
    app.include_router(customers.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Send the root URL to the API docs.

        Without this, anyone who types the API's host into a browser gets a bare
        `{"detail":"Not Found"}` and reasonably concludes the server is broken.
        It is not -- there is simply no page at the root, because the frontend is
        served separately. A redirect costs nothing and removes the confusion.
        """
        return RedirectResponse(url="/docs")

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        """Liveness only -- deliberately does not touch the database.

        A readiness probe that hits Postgres will cheerfully take the whole API
        out of rotation during a brief database blip, turning a degraded service
        into an outage. Database health belongs in /readyz.
        """
        return {"status": "ok", "environment": settings.environment}

    @app.get("/readyz", tags=["ops"])
    def readyz() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


app = create_app()
