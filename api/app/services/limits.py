"""Plan limits.

Milestone 1 enforces seat counts only; job-count limits arrive with jobs in
milestone 2 and Stripe enforcement in milestone 5. The rule agreed with the
client:

  * A "seat" is an ACTIVE membership, of any role.
  * Adding a member beyond the limit is blocked with an upgrade prompt (HTTP
    402), not an error.
  * Downgrading a plan does not silently deactivate anyone -- the owner must
    free the seats first.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import bad_request, payment_required
from app.models import Membership, Tenant
from app.models.enums import SEAT_LIMITS, Plan


def seat_limit(tenant: Tenant) -> int | None:
    """None means unlimited. An override always wins, for comped accounts."""
    if tenant.seat_limit_override is not None:
        return tenant.seat_limit_override
    return SEAT_LIMITS[tenant.plan]


def seats_used(db: Session, tenant_id) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.is_active.is_(True))
        )
        or 0
    )


def assert_seat_available(
    db: Session,
    tenant: Tenant,
    *,
    additional: int = 1,
    exclude_invitation_id: uuid.UUID | None = None,
) -> None:
    """Raise 402 if activating `additional` more members would exceed the plan.

    Pending invitations are counted too. Otherwise an owner on a 5-seat plan
    could send twelve invitations and only discover the problem as people accept
    them one by one -- which is a far worse experience than being told up front.

    `exclude_invitation_id` exists because of that same counting. When someone
    accepts an invitation, the row is still pending at the moment we check, so
    counting it *and* adding a seat for the person accepting it would reject the
    last legitimate member of every plan. The invitation being redeemed is
    therefore excluded from the pending tally.
    """
    limit = seat_limit(tenant)
    if limit is None:
        return

    from app.models import Invitation  # local import avoids a cycle

    conditions = [
        Invitation.tenant_id == tenant.id,
        Invitation.accepted_at.is_(None),
        Invitation.revoked_at.is_(None),
        Invitation.expires_at > func.now(),
    ]
    if exclude_invitation_id is not None:
        conditions.append(Invitation.id != exclude_invitation_id)

    used = seats_used(db, tenant.id)
    pending = (
        db.scalar(select(func.count()).select_from(Invitation).where(*conditions)) or 0
    )

    if used + pending + additional > limit:
        raise payment_required(
            f"Your {tenant.plan.value} plan includes {limit} team members "
            f"({used} active, {pending} invited). Upgrade to add more."
        )


def assert_downgrade_allowed(db: Session, tenant: Tenant, new_plan: Plan) -> None:
    new_limit = SEAT_LIMITS[new_plan]
    if new_limit is None:
        return
    used = seats_used(db, tenant.id)
    if used > new_limit:
        raise bad_request(
            f"You have {used} active team members but the {new_plan.value} plan "
            f"includes {new_limit}. Deactivate {used - new_limit} before "
            f"switching plans."
        )
