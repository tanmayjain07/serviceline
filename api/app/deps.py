"""FastAPI dependencies: request-scoped DB session, authentication, and RBAC.

The ordering here is deliberate and is the safety-critical part of the API:

    request -> decode JWT -> open session -> bind tenant -> handler

The session is never handed to a handler before it has been bound to a tenant,
so there is no window in which a query could run without RLS context.
"""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, bind_context
from app.core.errors import forbidden, unauthorized
from app.core.security import decode_token
from app.models import Membership, Role, User
from app.models.enums import ROLE_RANK

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, as asserted by a signed token."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: Role | None
    is_superadmin: bool


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    if credentials is None:
        raise unauthorized()
    try:
        claims = decode_token(credentials.credentials, "access")
    except jwt.ExpiredSignatureError:
        raise unauthorized("Token expired") from None
    except jwt.InvalidTokenError:
        raise unauthorized("Invalid token") from None

    raw_role = claims.get("role")
    return Principal(
        user_id=uuid.UUID(claims["sub"]),
        tenant_id=uuid.UUID(claims["tid"]) if claims.get("tid") else None,
        role=Role(raw_role) if raw_role else None,
        is_superadmin=bool(claims.get("sa", False)),
    )


def get_unscoped_db() -> Iterator[Session]:
    """A session with NO tenant bound.

    Used only by the signup, login, and invitation-acceptance flows, which by
    definition run before a tenant context exists. Because RLS denies rows when
    `app.tenant_id` is unset, a handler that accidentally uses this dependency
    for tenant data gets an empty result set, not a cross-tenant leak. Failing
    closed is the whole point.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db(principal: Principal = Depends(get_principal)) -> Iterator[Session]:
    """The session every authenticated handler should use.

    Handlers must not call `session.commit()` themselves -- a commit ends the
    transaction and therefore discards the `SET LOCAL` tenant binding, so any
    query after it would run unscoped. This dependency owns the single
    transaction boundary for the request. See ADR-003.
    """
    if principal.tenant_id is None:
        raise forbidden("This endpoint requires an active tenant context")

    session = SessionLocal()
    try:
        bind_context(session, user_id=principal.user_id, tenant_id=principal.tenant_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_identity_db(principal: Principal = Depends(get_principal)) -> Iterator[Session]:
    """A session bound to the caller's identity but not necessarily to a tenant.

    Used by the handful of routes that are about the *person* rather than the
    company: `/auth/me` and `/auth/switch-tenant`. Under the
    `memberships_select_own` policy these can read the caller's own memberships
    across every tenant, and nothing else.
    """
    session = SessionLocal()
    try:
        bind_context(session, user_id=principal.user_id, tenant_id=principal.tenant_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise unauthorized("User no longer active")
    return user


def get_current_membership(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Membership:
    """Re-read the caller's membership from the database on every request.

    The role in the token is a claim; this is the fact. Re-checking means that
    demoting or deactivating someone takes effect immediately rather than
    whenever their access token happens to expire.
    """
    membership = db.scalars(
        select(Membership).where(
            Membership.tenant_id == principal.tenant_id,
            Membership.user_id == principal.user_id,
        )
    ).one_or_none()

    if membership is None or not membership.is_active:
        raise forbidden("You are no longer a member of this company")
    return membership


def require_role(*allowed: Role) -> Callable[..., Membership]:
    """Dependency factory: restrict a route to the given roles."""

    def _dependency(
        membership: Membership = Depends(get_current_membership),
    ) -> Membership:
        if membership.role not in allowed:
            raise forbidden(
                f"This action requires one of: {', '.join(r.value for r in allowed)}"
            )
        return membership

    return _dependency


def require_at_least(minimum: Role) -> Callable[..., Membership]:
    """Dependency factory: restrict a route by rank rather than a literal list.

    Note that ACCOUNTANT outranks TECHNICIAN for *reading* but is read-only; any
    mutating route should name its roles explicitly with `require_role` rather
    than relying on rank.
    """

    def _dependency(
        membership: Membership = Depends(get_current_membership),
    ) -> Membership:
        if ROLE_RANK[membership.role] < ROLE_RANK[minimum]:
            raise forbidden(f"This action requires at least the {minimum.value} role")
        return membership

    return _dependency


def client_ip(request: Request) -> str | None:
    """Best-effort client IP for the audit log.

    The result goes into a Postgres INET column, so it must be a valid address
    or nothing. X-Forwarded-For is caller-supplied and can contain anything, so
    it is parsed rather than trusted -- without this, a request with a junk
    header would fail with a 500 at INSERT time, turning the audit log into a
    denial-of-service surface.

    We read X-Forwarded-For at all only because the app runs behind a single
    known proxy in every deployed environment. If that stops being true, this is
    the line that has to change.
    """
    candidates: list[str] = []

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        candidates.append(forwarded.split(",")[0].strip())
    if request.client:
        candidates.append(request.client.host)

    for candidate in candidates:
        # Strip a port if one came along, e.g. "203.0.113.5:41234".
        host = candidate.rsplit(":", 1)[0] if candidate.count(":") == 1 else candidate
        for value in (candidate, host):
            try:
                return str(ipaddress.ip_address(value))
            except ValueError:
                continue

    # Not a routable address -- the test client, a unix socket, or a junk
    # header. Recording nothing is better than failing the request.
    return None
