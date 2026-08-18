"""Invitations: invite a colleague, preview an invite, accept it.

The accept flow is the most security-sensitive path in milestone 1, because it
is the only place a caller legitimately touches a tenant they are not yet a
member of. Two things keep it safe:

  * RLS shows exactly one invitation row -- the one whose token hash the caller
    can produce (see the `invitations_select_by_token` policy).
  * If the invited address already has an account, accepting requires that
    account's password. Without that check, anyone holding an invite link could
    mint tokens for an existing user.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import bind_context, bind_invite_token
from app.core.errors import bad_request, conflict, not_found, unauthorized
from app.core.security import (
    generate_invite_token,
    hash_invite_token,
    hash_password,
    verify_password,
)
from app.deps import (
    Principal,
    client_ip,
    get_current_user,
    get_db,
    get_principal,
    get_unscoped_db,
    require_role,
)
from app.models import Invitation, Membership, Role, Tenant, User
from app.schemas.auth import AcceptInviteRequest, TokenPair
from app.schemas.common import Message
from app.schemas.invitation import (
    InvitationCreate,
    InvitationCreated,
    InvitationPreview,
    InvitationRead,
)
from app.services import audit, limits

router = APIRouter(prefix="/invitations", tags=["invitations"])


def _status_of(inv: Invitation) -> str:
    if inv.accepted_at is not None:
        return "accepted"
    if inv.revoked_at is not None:
        return "revoked"
    if inv.expires_at <= datetime.now(UTC):
        return "expired"
    return "pending"


def _to_read(inv: Invitation) -> InvitationRead:
    return InvitationRead(
        id=inv.id,
        tenant_id=inv.tenant_id,
        email=inv.email,
        role=inv.role,
        expires_at=inv.expires_at,
        accepted_at=inv.accepted_at,
        revoked_at=inv.revoked_at,
        created_at=inv.created_at,
        status=_status_of(inv),
    )


@router.post("", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationCreate,
    request: Request,
    _owner: Membership = Depends(require_role(Role.OWNER)),
    actor: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> InvitationCreated:
    email = payload.email.strip().lower()

    tenant = db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise not_found("Company")

    # Pending invitations count towards the seat limit, so an owner is told
    # up-front rather than discovering the problem as people accept.
    limits.assert_seat_available(db, tenant)

    # Already on the team? Note this lookup is RLS-scoped to the current tenant,
    # so it cannot be used to discover whether the address belongs to a user in
    # some other company.
    already = db.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(func.lower(User.email) == email)
    )
    if already is not None:
        raise conflict("That person is already on your team")

    outstanding = db.scalar(
        select(Invitation.id).where(
            func.lower(Invitation.email) == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > func.now(),
        )
    )
    if outstanding is not None:
        raise conflict(
            "There is already a pending invitation for that address. "
            "Revoke it first if you want to change the role."
        )

    raw_token, token_hash = generate_invite_token()
    invitation = Invitation(
        tenant_id=tenant.id,
        email=email,
        role=payload.role,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(days=settings.invite_expiry_days),
        invited_by_user_id=actor.id,
    )
    db.add(invitation)

    audit.record(
        db,
        tenant_id=tenant.id,
        actor=actor,
        action="invitation.created",
        entity_type="invitation",
        entity_label=email,
        changes={"role": payload.role.value},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.flush()

    result = InvitationCreated(
        **_to_read(invitation).model_dump(),
        # Milestone 3 sends this by email instead of returning it. Until then it
        # is returned once, here, and never retrievable again -- only the hash
        # is stored.
        accept_url=f"{settings.cors_origins[0]}/accept-invite?token={raw_token}",
    )
    return result


@router.get("", response_model=list[InvitationRead])
def list_invitations(
    _owner: Membership = Depends(require_role(Role.OWNER)),
    db: Session = Depends(get_db),
) -> list[InvitationRead]:
    rows = db.scalars(select(Invitation).order_by(Invitation.created_at.desc())).all()
    return [_to_read(inv) for inv in rows]


@router.delete("/{invitation_id}", response_model=Message)
def revoke_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    _owner: Membership = Depends(require_role(Role.OWNER)),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Message:
    invitation = db.get(Invitation, invitation_id)
    if invitation is None:
        raise not_found("Invitation")
    if invitation.accepted_at is not None:
        raise bad_request("That invitation has already been accepted")
    if invitation.revoked_at is not None:
        return Message(detail="Invitation already revoked")

    invitation.revoked_at = datetime.now(UTC)
    audit.record(
        db,
        tenant_id=invitation.tenant_id,
        actor=actor,
        action="invitation.revoked",
        entity_type="invitation",
        entity_id=invitation.id,
        entity_label=invitation.email,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.flush()
    return Message(detail="Invitation revoked")


# --------------------------------------------------------------------------
# Unauthenticated endpoints -- reached by someone following an invite link.
# --------------------------------------------------------------------------


def _load_by_token(db: Session, raw_token: str) -> Invitation:
    """Resolve a raw invite token to its row, binding RLS context as we go.

    Order matters. We bind the token hash first, which makes exactly one
    invitation row visible. Only once we have that row -- proving the caller
    holds a valid token -- do we bind the tenant, which makes that tenant's
    other rows reachable for the rest of the transaction.
    """
    token_hash = hash_invite_token(raw_token)
    bind_invite_token(db, token_hash)

    invitation = db.scalars(
        select(Invitation).where(Invitation.token_hash == token_hash)
    ).one_or_none()

    # One message for every failure mode. A token that is wrong, expired,
    # revoked, or already used must be indistinguishable, or the endpoint
    # becomes an oracle for guessing tokens.
    if invitation is None:
        raise not_found("Invitation")
    if invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise not_found("Invitation")
    if invitation.expires_at <= datetime.now(UTC):
        raise not_found("Invitation")

    bind_context(db, tenant_id=invitation.tenant_id)
    return invitation


@router.get("/preview", response_model=InvitationPreview)
def preview_invitation(
    token: str = Query(min_length=10),
    db: Session = Depends(get_unscoped_db),
) -> InvitationPreview:
    """What the invited person sees before deciding to accept.

    Returns the company name, the role on offer, and whether they will need to
    choose a password. Nothing else about the company is exposed.
    """
    invitation = _load_by_token(db, token)
    tenant = db.get(Tenant, invitation.tenant_id)
    if tenant is None:
        raise not_found("Invitation")

    existing_user = db.scalar(
        select(User.id).where(func.lower(User.email) == invitation.email.lower())
    )

    return InvitationPreview(
        tenant_name=tenant.name,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        requires_signup=existing_user is None,
    )


@router.post("/accept", response_model=TokenPair)
def accept_invitation(
    payload: AcceptInviteRequest,
    request: Request,
    db: Session = Depends(get_unscoped_db),
) -> TokenPair:
    invitation = _load_by_token(db, payload.token)

    tenant = db.get(Tenant, invitation.tenant_id)
    if tenant is None:
        raise not_found("Invitation")

    user = db.scalars(
        select(User).where(func.lower(User.email) == invitation.email.lower())
    ).one_or_none()

    if user is None:
        if not payload.password or not payload.full_name:
            raise bad_request(
                "Please provide your name and choose a password to accept "
                "this invitation."
            )
        user = User(
            email=invitation.email.lower(),
            full_name=payload.full_name.strip(),
            hashed_password=hash_password(payload.password),
        )
        db.add(user)
        db.flush()
    else:
        # The account already exists, so accepting must prove ownership of it.
        # Otherwise possession of an invite link would be enough to obtain
        # tokens for someone else's account.
        if not payload.password or not verify_password(
            payload.password, user.hashed_password
        ):
            raise unauthorized(
                "That email already has a ServiceLine account. "
                "Enter its password to join this company."
            )
        if not user.is_active:
            raise unauthorized("That account has been deactivated")

    bind_context(db, user_id=user.id, tenant_id=invitation.tenant_id)

    # Re-check seats at acceptance time, not just at invite time -- the owner may
    # have filled the last seat in between.
    existing_membership = db.scalars(
        select(Membership).where(
            Membership.tenant_id == invitation.tenant_id,
            Membership.user_id == user.id,
        )
    ).one_or_none()

    if existing_membership is None:
        limits.assert_seat_available(db, tenant, exclude_invitation_id=invitation.id)
        membership = Membership(
            tenant_id=invitation.tenant_id, user_id=user.id, role=invitation.role
        )
        db.add(membership)
    else:
        if not existing_membership.is_active:
            limits.assert_seat_available(
                db, tenant, exclude_invitation_id=invitation.id
            )
        existing_membership.is_active = True
        existing_membership.role = invitation.role
        membership = existing_membership

    invitation.accepted_at = datetime.now(UTC)
    user.last_login_at = datetime.now(UTC)

    audit.record(
        db,
        tenant_id=invitation.tenant_id,
        actor=user,
        action="invitation.accepted",
        entity_type="membership",
        entity_label=user.email,
        changes={"role": invitation.role.value},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.flush()

    from app.core.security import create_access_token, create_refresh_token

    return TokenPair(
        access_token=create_access_token(
            user_id=user.id,
            tenant_id=invitation.tenant_id,
            role=invitation.role.value,
            is_superadmin=user.is_superadmin,
        ),
        refresh_token=create_refresh_token(user_id=user.id),
        tenant_id=invitation.tenant_id,
        role=invitation.role,
    )
