"""Enumerations shared across models and schemas."""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum


def enum_column[E: enum.Enum](enum_cls: type[E], length: int = 20) -> SAEnum:
    """A VARCHAR-backed enum column that stores the enum's *value*.

    `values_callable` is the important part and is easy to miss. By default
    SQLAlchemy persists the enum member's NAME, so `Plan.TRIAL` would be stored
    as 'TRIAL' -- while the API, the CHECK constraints, and every JSON payload
    all use 'trial'. The result is a database whose contents do not match its own
    constraints. Setting values_callable makes the stored form and the wire form
    the same string.

    native_enum=False keeps these as VARCHAR + CHECK rather than Postgres ENUM
    types, because adding a value to a Postgres ENUM inside a transaction is
    awkward, and altering one is worse. A CHECK constraint is trivial to migrate.
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        validate_strings=True,
        values_callable=lambda enum_type: [member.value for member in enum_type],
    )


class Role(enum.StrEnum):
    """A user's role *within a single tenant*.

    Roles live on the membership, not the user, because one person can belong to
    several tenants with a different role in each -- an owner of their own
    company who is also the accountant for another.
    """

    OWNER = "owner"
    DISPATCHER = "dispatcher"
    TECHNICIAN = "technician"
    ACCOUNTANT = "accountant"


# Ordered most- to least-privileged. Used by the `require_role` dependency so
# that a check for "dispatcher or above" is a single comparison rather than a
# hand-maintained list at every call site.
ROLE_RANK: dict[Role, int] = {
    Role.OWNER: 40,
    Role.DISPATCHER: 30,
    Role.ACCOUNTANT: 20,
    Role.TECHNICIAN: 10,
}


class Plan(enum.StrEnum):
    TRIAL = "trial"
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"


class TenantStatus(enum.StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    SUSPENDED = "suspended"


class TradeType(enum.StrEnum):
    HVAC = "hvac"
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    MULTI_TRADE = "multi_trade"
    OTHER = "other"


# Technician seat limits per plan. Enforced in app/services/limits.py.
# `None` means unlimited.
SEAT_LIMITS: dict[Plan, int | None] = {
    Plan.TRIAL: 5,
    Plan.STARTER: 5,
    Plan.PRO: 20,
    Plan.BUSINESS: None,
}
