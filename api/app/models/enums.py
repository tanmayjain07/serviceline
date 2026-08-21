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


# ---------------------------------------------------------------------------
# Milestone 2: customers, service addresses, and jobs
# ---------------------------------------------------------------------------


class CustomerKind(enum.StrEnum):
    RESIDENTIAL = "residential"
    COMPANY = "company"


class JobType(enum.StrEnum):
    """Constrained rather than free text.

    "Revenue by job type" is one of the reports the client asked for, and a
    free-text field makes that report meaningless the first time someone types
    "maintenence". Tenants who need finer categories get them in a later
    milestone as a per-tenant lookup table.
    """

    INSTALL = "install"
    REPAIR = "repair"
    MAINTENANCE = "maintenance"
    INSPECTION = "inspection"
    EMERGENCY = "emergency"
    OTHER = "other"


class JobPriority(enum.StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EMERGENCY = "emergency"


class JobStatus(enum.StrEnum):
    UNSCHEDULED = "unscheduled"
    SCHEDULED = "scheduled"
    EN_ROUTE = "en_route"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    INVOICED = "invoiced"
    CLOSED = "closed"
    CANCELED = "canceled"


# The status field is a state machine, not a free-form label. Writing the legal
# transitions down here -- rather than trusting each caller to be sensible --
# means a job cannot jump from Unscheduled straight to Invoiced, and the
# technician mobile view in milestone 3 cannot reopen a closed job by replaying
# a stale request.
#
# CANCELED is reachable from anywhere that has not yet been invoiced: work does
# get called off, but money that has been billed needs a credit note rather than
# a status change.
JOB_STATUS_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.UNSCHEDULED: frozenset({JobStatus.SCHEDULED, JobStatus.CANCELED}),
    JobStatus.SCHEDULED: frozenset(
        {JobStatus.UNSCHEDULED, JobStatus.EN_ROUTE, JobStatus.CANCELED}
    ),
    JobStatus.EN_ROUTE: frozenset(
        {JobStatus.IN_PROGRESS, JobStatus.SCHEDULED, JobStatus.CANCELED}
    ),
    JobStatus.IN_PROGRESS: frozenset({JobStatus.COMPLETE, JobStatus.CANCELED}),
    JobStatus.COMPLETE: frozenset({JobStatus.INVOICED, JobStatus.IN_PROGRESS}),
    JobStatus.INVOICED: frozenset({JobStatus.CLOSED}),
    JobStatus.CLOSED: frozenset(),
    JobStatus.CANCELED: frozenset({JobStatus.UNSCHEDULED}),
}

# Statuses a dispatcher considers "on the board" -- i.e. still needing attention.
OPEN_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {
        JobStatus.UNSCHEDULED,
        JobStatus.SCHEDULED,
        JobStatus.EN_ROUTE,
        JobStatus.IN_PROGRESS,
    }
)


class LineItemKind(enum.StrEnum):
    LABOR = "labor"
    PART = "part"
