"""Authentication: signup, login, token refresh, company switching, /me."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import bind_context
from app.core.errors import bad_request, forbidden, unauthorized
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.deps import (
    Principal,
    client_ip,
    get_identity_db,
    get_principal,
    get_unscoped_db,
)
from app.models import Membership, Role, Tenant, User
from app.models.enums import Plan, TenantStatus
from app.schemas.auth import (
    LoginRequest,
    MembershipSummary,
    MeResponse,
    RefreshRequest,
    SignupRequest,
    SwitchTenantRequest,
    TokenPair,
)
from app.services import audit, slug

logger = logging.getLogger("serviceline.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# A real bcrypt hash of a random string. Verified against when the email is not
# found, so that a request for a non-existent account costs the same time as one
# for a real account. Without this, response timing is an account-enumeration
# oracle.
_DUMMY_HASH = hash_password("timing-attack-mitigation-placeholder")


def _memberships_for(db: Session, user_id: uuid.UUID) -> list[Membership]:
    """Every active membership held by a user, across all tenants.

    Readable without a tenant binding thanks to the `memberships_select_own`
    RLS policy -- see migration 0001.
    """
    return list(
        db.scalars(
            select(Membership)
            .where(Membership.user_id == user_id, Membership.is_active.is_(True))
            .order_by(Membership.created_at)
        ).all()
    )


def _issue_tokens(
    db: Session, user: User, memberships: list[Membership], preferred: uuid.UUID | None
) -> TokenPair:
    """Mint a token pair, resolving which tenant the access token is scoped to.

    If the user belongs to exactly one company we log them straight into it. If
    they belong to several and have not said which, the access token carries no
    tenant and the frontend shows a company chooser -- that token can reach
    `/auth/me` and `/auth/switch-tenant` and nothing else.
    """
    chosen: Membership | None = None

    if preferred is not None:
        chosen = next((m for m in memberships if m.tenant_id == preferred), None)
        if chosen is None:
            raise forbidden("You do not have access to that company")
    elif len(memberships) == 1:
        chosen = memberships[0]

    return TokenPair(
        access_token=create_access_token(
            user_id=user.id,
            tenant_id=chosen.tenant_id if chosen else None,
            role=chosen.role.value if chosen else None,
            is_superadmin=user.is_superadmin,
        ),
        refresh_token=create_refresh_token(user_id=user.id),
        tenant_id=chosen.tenant_id if chosen else None,
        role=chosen.role if chosen else None,
    )


@router.post("/signup", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def signup(
    payload: SignupRequest,
    request: Request,
    db: Session = Depends(get_unscoped_db),
) -> TokenPair:
    """Create a company and its first owner.

    Note the ordering: the tenant's UUID is generated in Python and the session
    is bound to it *before* the INSERT. That lets the RLS policy on `tenants`
    be `WITH CHECK (id = app_current_tenant())` rather than the much looser
    `WITH CHECK (true)` -- even the creation path cannot insert a row for some
    other tenant.
    """
    email = payload.email.strip().lower()

    existing = db.scalar(select(User.id).where(func.lower(User.email) == email))
    if existing is not None:
        # An owner signing up twice is far more likely than an attacker probing
        # for accounts, and a vague error here produces support tickets. The
        # real protection against enumeration is rate limiting at the edge.
        raise bad_request(
            "An account with that email already exists. Sign in instead, "
            "or ask your company owner to invite you."
        )

    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.flush()

    tenant_id = uuid.uuid4()
    bind_context(db, user_id=user.id, tenant_id=tenant_id)

    tenant = Tenant(
        id=tenant_id,
        name=payload.company_name,
        slug=slug.unique_slug(db, payload.company_name),
        trade_type=payload.trade_type,
        timezone=payload.timezone,
        plan=Plan.TRIAL,
        status=TenantStatus.TRIALING,
        trial_ends_at=datetime.now(UTC) + timedelta(days=settings.trial_days),
    )
    db.add(tenant)

    membership = Membership(tenant_id=tenant.id, user_id=user.id, role=Role.OWNER)
    db.add(membership)

    # Flush before writing the audit entry, not after.
    #
    # SQLAlchemy's unit of work orders INSERTs across mappers using ORM
    # *relationships*, not raw ForeignKey metadata. AuditLogEntry deliberately
    # declares no relationships -- it is an append-only log with denormalised
    # columns so old entries stay readable -- which means the unit of work does
    # not know it depends on `tenants`, and will happily emit its INSERT first.
    # That fails the foreign key. Signup is the only handler that creates a
    # tenant and an audit entry in the same flush, so this is the only place it
    # bites, but the ordering is explicit here rather than implicit and fragile.
    db.flush()

    audit.record(
        db,
        tenant_id=tenant.id,
        actor=user,
        action="tenant.created",
        entity_type="tenant",
        entity_id=tenant.id,
        entity_label=tenant.name,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        # The realistic cause is a slug collision from two simultaneous signups
        # with the same company name -- `unique_slug` cannot see other tenants'
        # rows under RLS, so the unique index is the real arbiter. Anything else
        # reaching here is a bug, so log the detail rather than swallowing it.
        logger.warning("signup integrity error: %s", exc.orig, exc_info=True)
        raise bad_request("That company name is already taken. Try another.") from None

    return _issue_tokens(db, user, [membership], tenant.id)


@router.post("/login", response_model=TokenPair)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_unscoped_db),
) -> TokenPair:
    email = payload.email.strip().lower()
    user = db.scalars(select(User).where(func.lower(User.email) == email)).one_or_none()

    if user is None:
        verify_password(payload.password, _DUMMY_HASH)
        raise unauthorized("Incorrect email or password")

    if not verify_password(payload.password, user.hashed_password):
        raise unauthorized("Incorrect email or password")

    if not user.is_active:
        raise forbidden("This account has been deactivated")

    # Bind identity so the memberships policy lets us see the user's companies.
    bind_context(db, user_id=user.id)

    memberships = _memberships_for(db, user.id)
    if not memberships:
        raise forbidden(
            "Your account is not attached to a company. Ask an owner to invite you."
        )

    user.last_login_at = datetime.now(UTC)
    return _issue_tokens(db, user, memberships, payload.tenant_id)


@router.post("/refresh", response_model=TokenPair)
def refresh(
    payload: RefreshRequest, db: Session = Depends(get_unscoped_db)
) -> TokenPair:
    """Exchange a refresh token for a new pair.

    The returned access token is deliberately unscoped when the user belongs to
    several companies -- the client re-selects. Carrying the previous tenant
    through would mean a refresh could silently outlive the membership that
    justified it.
    """
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except jwt.ExpiredSignatureError:
        raise unauthorized("Refresh token expired") from None
    except jwt.InvalidTokenError:
        raise unauthorized("Invalid refresh token") from None

    user_id = uuid.UUID(claims["sub"])
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized("User no longer active")

    bind_context(db, user_id=user.id)
    memberships = _memberships_for(db, user.id)
    if not memberships:
        raise forbidden("Your account is not attached to a company")

    return _issue_tokens(db, user, memberships, None)


@router.post("/switch-tenant", response_model=TokenPair)
def switch_tenant(
    payload: SwitchTenantRequest,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_identity_db),
) -> TokenPair:
    """Re-issue an access token scoped to a different company.

    The membership is re-read here rather than trusted from the previous token,
    so revoking someone's access takes effect on their next switch even if their
    old token has not expired.
    """
    user = db.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise unauthorized("User no longer active")

    memberships = _memberships_for(db, user.id)
    return _issue_tokens(db, user, memberships, payload.tenant_id)


@router.get("/me", response_model=MeResponse)
def me(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_identity_db),
) -> MeResponse:
    user = db.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise unauthorized("User no longer active")

    memberships = _memberships_for(db, user.id)
    tenants = {
        t.id: t
        for t in db.scalars(
            select(Tenant).where(Tenant.id.in_([m.tenant_id for m in memberships]))
        ).all()
    }

    summaries = [
        MembershipSummary(
            tenant_id=m.tenant_id,
            tenant_name=tenants[m.tenant_id].name,
            tenant_slug=tenants[m.tenant_id].slug,
            role=m.role,
            is_active=m.is_active,
        )
        for m in memberships
        if m.tenant_id in tenants
    ]

    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_superadmin=user.is_superadmin,
        active_tenant_id=principal.tenant_id,
        active_role=principal.role,
        memberships=summaries,
    )
