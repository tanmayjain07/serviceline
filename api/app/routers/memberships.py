"""Team management: list members, change roles, deactivate."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import bad_request, not_found
from app.deps import (
    Principal,
    client_ip,
    get_current_user,
    get_db,
    get_principal,
    require_role,
)
from app.models import Membership, Role, Tenant, User
from app.schemas.common import Page
from app.schemas.membership import MembershipRead, MembershipUpdate
from app.services import audit, limits

router = APIRouter(prefix="/memberships", tags=["team"])


def _to_read(membership: Membership, user: User) -> MembershipRead:
    return MembershipRead(
        id=membership.id,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        role=membership.role,
        is_active=membership.is_active,
        created_at=membership.created_at,
        email=user.email,
        full_name=user.full_name,
        last_login_at=user.last_login_at,
    )


def _active_owner_count(db: Session, tenant_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role == Role.OWNER,
                Membership.is_active.is_(True),
            )
        )
        or 0
    )


@router.get("", response_model=Page[MembershipRead])
def list_members(
    limit: int = 50,
    offset: int = 0,
    # Technicians are deliberately excluded: a tech has no business reason to
    # see the full roster, and the client was explicit that techs must not see
    # other technicians' details. Accountants get read access for reporting.
    _caller: Membership = Depends(
        require_role(Role.OWNER, Role.DISPATCHER, Role.ACCOUNTANT)
    ),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Page[MembershipRead]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    # No explicit `WHERE tenant_id = ...` here, and that is deliberate: RLS
    # supplies it. This is the point of the design -- forgetting the filter
    # yields nothing, not everything.
    total = db.scalar(select(func.count()).select_from(Membership)) or 0

    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .order_by(Membership.created_at)
        .limit(limit)
        .offset(offset)
    ).all()

    return Page[MembershipRead](
        items=[_to_read(m, u) for m, u in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{membership_id}", response_model=MembershipRead)
def update_member(
    membership_id: uuid.UUID,
    payload: MembershipUpdate,
    request: Request,
    _owner: Membership = Depends(require_role(Role.OWNER)),
    actor: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> MembershipRead:
    """Change a team member's role or active state.

    A membership belonging to another tenant is invisible to this query under
    RLS, so it 404s -- the same response as an ID that does not exist anywhere.
    That is deliberate: a 403 would confirm the row exists.
    """
    membership = db.get(Membership, membership_id)
    if membership is None:
        raise not_found("Team member")

    user = db.get(User, membership.user_id)
    if user is None:
        raise not_found("Team member")

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return _to_read(membership, user)

    # Guard against a company locking itself out. Every tenant must keep at
    # least one active owner -- otherwise nobody can manage billing or invite
    # anyone, and recovery becomes a support ticket.
    losing_owner = membership.role == Role.OWNER and (
        fields.get("is_active") is False
        or (fields.get("role") is not None and fields["role"] != Role.OWNER)
    )
    if losing_owner and _active_owner_count(db, membership.tenant_id) <= 1:
        raise bad_request(
            "A company must have at least one active owner. Promote someone "
            "else to owner first."
        )

    # Reactivating a member consumes a seat, so it has to pass the plan check.
    if fields.get("is_active") is True and not membership.is_active:
        tenant = db.get(Tenant, membership.tenant_id)
        if tenant is not None:
            limits.assert_seat_available(db, tenant)

    before = {key: getattr(membership, key) for key in fields}
    for key, value in fields.items():
        setattr(membership, key, value)

    def _serialise(mapping: dict) -> dict:
        return {k: (v.value if hasattr(v, "value") else v) for k, v in mapping.items()}

    changes = audit.diff(_serialise(before), _serialise(fields))
    if changes:
        audit.record(
            db,
            tenant_id=membership.tenant_id,
            actor=actor,
            action="membership.updated",
            entity_type="membership",
            entity_id=membership.id,
            entity_label=user.email,
            changes=changes,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

    db.flush()
    return _to_read(membership, user)
