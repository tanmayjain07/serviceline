"""Seed the public demo with two companies.

Run with `python -m app.seed_demo`. The container entrypoint calls this on every
start when DEMO_MODE=true, so it must be both idempotent and cheap.

WHY TWO COMPANIES

The whole point of the demo is the thing a client cannot see from a screenshot:
that one company genuinely cannot reach another's data. So the demo ships with
two tenants and published credentials for both, and invites the visitor to try
to cross the boundary themselves -- including by editing IDs in API requests.
A claim about isolation is worth less than a login that lets you test it.

SELF-HEALING RATHER THAN RESETTING

The demo is publicly writable, so a visitor could deactivate the demo owner and
lock everyone out. Rather than wiping the database on each start -- which would
be hostile to anyone mid-exploration, and is impossible anyway because the
application role has no DELETE policy on `tenants` -- this script re-asserts the
things that would break the demo: the demo users' passwords, and their
memberships being active. Everything else a visitor changes is left alone.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import session_scope
from app.core.security import (
    generate_invite_token,
    hash_password,
)
from app.models import (
    Invitation,
    Membership,
    Plan,
    Role,
    Tenant,
    TenantStatus,
    TradeType,
    User,
)
from app.services import audit

logger = logging.getLogger("serviceline.seed")

# Published in the README and on the demo login screen. There is nothing secret
# here by design.
DEMO_PASSWORD = "demo-password"

NORTHLINE_SLUG = "northline-demo"
BUCKEYE_SLUG = "buckeye-demo"


class DemoUser:
    def __init__(self, email: str, full_name: str, role: Role):
        self.email = email
        self.full_name = full_name
        self.role = role


NORTHLINE_PEOPLE = [
    DemoUser("owner@northline.demo", "Dale Whitcomb", Role.OWNER),
    DemoUser("dispatch@northline.demo", "Rosa Alvarez", Role.DISPATCHER),
    DemoUser("tech@northline.demo", "Mike Petrov", Role.TECHNICIAN),
]

BUCKEYE_PEOPLE = [
    DemoUser("owner@buckeye.demo", "Priya Raman", Role.OWNER),
    DemoUser("tech@buckeye.demo", "Sam Osei", Role.TECHNICIAN),
]

# Deliberately a member of BOTH companies, as an accountant in each. This is the
# many-to-many user model made visible: log in as this account and the company
# switcher appears. One bookkeeper serving several contractors is the real-world
# case that drove the design (ADR-002).
SHARED_ACCOUNTANT = DemoUser("books@shared.demo", "Janet Cole", Role.ACCOUNTANT)


def _upsert_user(db, person: DemoUser) -> User:
    """Create the user, or re-assert their password if they already exist.

    Re-asserting the password is what keeps the demo usable: if a visitor
    changes it, the next container start puts it back.
    """
    user = db.scalars(
        select(User).where(func.lower(User.email) == person.email.lower())
    ).one_or_none()

    if user is None:
        user = User(
            email=person.email,
            full_name=person.full_name,
            hashed_password=hash_password(DEMO_PASSWORD),
            is_active=True,
        )
        db.add(user)
        db.flush()
        logger.info("created demo user %s", person.email)
    else:
        user.hashed_password = hash_password(DEMO_PASSWORD)
        user.is_active = True

    return user


def _ensure_membership(db, tenant_id: uuid.UUID, user: User, role: Role) -> None:
    membership = db.scalars(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user.id,
        )
    ).one_or_none()

    if membership is None:
        db.add(
            Membership(tenant_id=tenant_id, user_id=user.id, role=role, is_active=True)
        )
    else:
        # Re-activate and restore the role, so a visitor cannot permanently
        # break the demo by demoting the owner.
        membership.is_active = True
        membership.role = role


def _seed_tenant(
    *,
    slug: str,
    name: str,
    trade: TradeType,
    timezone: str,
    plan: Plan,
    people: list[DemoUser],
    add_pending_invite: bool,
) -> None:
    """Create one demo company, or heal it if it already exists."""
    # A tenant's own row is only visible to a session bound to that tenant, so
    # finding an existing demo tenant means looking it up by slug in an unscoped
    # session first -- which returns nothing under RLS. Instead the slug is
    # deterministic, so the tenant id is derived from it and stays stable across
    # runs. uuid5 gives us a repeatable id from a name.
    tenant_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{slug}.serviceline.demo")

    with session_scope(tenant_id=tenant_id) as db:
        tenant = db.get(Tenant, tenant_id)

        if tenant is None:
            tenant = Tenant(
                id=tenant_id,
                name=name,
                slug=slug,
                trade_type=trade,
                timezone=timezone,
                plan=plan,
                status=TenantStatus.ACTIVE,
                trial_ends_at=datetime.now(UTC) + timedelta(days=365),
            )
            db.add(tenant)
            db.flush()
            logger.info("created demo tenant %s", slug)
            created = True
        else:
            created = False

        users = [_upsert_user(db, person) for person in people]
        for person, user in zip(people, users, strict=True):
            _ensure_membership(db, tenant_id, user, person.role)

        accountant = _upsert_user(db, SHARED_ACCOUNTANT)
        _ensure_membership(db, tenant_id, accountant, SHARED_ACCOUNTANT.role)

        if created:
            owner = users[0]
            db.flush()
            audit.record(
                db,
                tenant_id=tenant_id,
                actor=owner,
                action="tenant.created",
                entity_type="tenant",
                entity_id=tenant_id,
                entity_label=name,
            )
            for person, user in zip(people[1:], users[1:], strict=True):
                audit.record(
                    db,
                    tenant_id=tenant_id,
                    actor=owner,
                    action="membership.created",
                    entity_type="membership",
                    entity_id=user.id,
                    entity_label=f"{person.full_name} ({person.role.value})",
                )

        if add_pending_invite:
            pending = db.scalars(
                select(Invitation).where(
                    Invitation.tenant_id == tenant_id,
                    Invitation.accepted_at.is_(None),
                    Invitation.revoked_at.is_(None),
                )
            ).first()
            if pending is None:
                _, token_hash = generate_invite_token()
                db.add(
                    Invitation(
                        tenant_id=tenant_id,
                        email="newhire@northline.demo",
                        role=Role.TECHNICIAN,
                        token_hash=token_hash,
                        expires_at=datetime.now(UTC)
                        + timedelta(days=settings.invite_expiry_days),
                        invited_by_user_id=users[0].id,
                    )
                )


def seed() -> None:
    _seed_tenant(
        slug=NORTHLINE_SLUG,
        name="Northline Mechanical",
        trade=TradeType.HVAC,
        timezone="America/New_York",
        plan=Plan.PRO,
        people=NORTHLINE_PEOPLE,
        add_pending_invite=True,
    )
    # Indiana on purpose. Half the state observes Central time, which is exactly
    # the case that pushed scheduling timezones down to the service address in
    # milestone 2 rather than leaving them on the company.
    _seed_tenant(
        slug=BUCKEYE_SLUG,
        name="Buckeye Plumbing",
        trade=TradeType.PLUMBING,
        timezone="America/Indiana/Indianapolis",
        plan=Plan.STARTER,
        people=BUCKEYE_PEOPLE,
        add_pending_invite=False,
    )
    logger.info("demo seed complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seed()
    print("Demo data ready.")
    print(f"  Northline Mechanical -> owner@northline.demo / {DEMO_PASSWORD}")
    print(f"  Buckeye Plumbing     -> owner@buckeye.demo   / {DEMO_PASSWORD}")
    print(f"  Both companies       -> books@shared.demo    / {DEMO_PASSWORD}")
