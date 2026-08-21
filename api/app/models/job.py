"""Jobs, who is assigned to them, and what they cost."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import (
    JobPriority,
    JobStatus,
    JobType,
    LineItemKind,
    enum_column,
)

if TYPE_CHECKING:
    from app.models.customer import Customer, ServiceAddress
    from app.models.membership import Membership


class Job(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "job_number", name="uq_jobs_tenant_number"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Per-tenant, resetting each year: "2026-0147". Allocated under a row lock
    # (see services/job_numbers.py) because two dispatchers creating jobs in the
    # same second would otherwise collide. Gaps are acceptable and expected --
    # the client confirmed nobody has ever asked about a missing job number.
    # Invoice numbers, in milestone 4, are a different matter entirely.
    job_number: Mapped[str] = mapped_column(String(20), nullable=False)

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    service_address_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_addresses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    job_type: Mapped[JobType] = mapped_column(
        enum_column(JobType),
        nullable=False,
        default=JobType.REPAIR,
    )
    priority: Mapped[JobPriority] = mapped_column(
        enum_column(JobPriority),
        nullable=False,
        default=JobPriority.NORMAL,
    )
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus),
        nullable=False,
        default=JobStatus.UNSCHEDULED,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Two separate note fields, deliberately. Anything a technician writes about
    # access, hazards or a difficult customer must never appear on the invoice
    # or in a customer email. Keeping them in one field with a convention would
    # last exactly until the first time someone forgot.
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Scheduling -------------------------------------------------------
    #
    # The booked window is stored as a LOCAL date and time, because that is what
    # it is: the customer was told "the 14th, between 8 and 12", and that promise
    # does not move if a timezone rule changes. It is interpreted against the
    # service address's timezone, not the company's.
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    arrival_window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    arrival_window_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    # ...and separately as absolute instants, derived from the above and the
    # address's timezone whenever either changes.
    #
    # These exist for one reason: double-booking detection. A technician with a
    # job in Ohio from 8-12 Eastern and another in Indiana from 11-1 Central does
    # NOT have a clash, but comparing wall-clock times says they do. Overlap can
    # only be computed on real instants, so they are stored rather than derived
    # per query.
    window_start_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    window_end_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    customer: Mapped[Customer] = relationship(back_populates="jobs")
    service_address: Mapped[ServiceAddress] = relationship(back_populates="jobs")
    assignments: Mapped[list[JobAssignment]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    line_items: Mapped[list[JobLineItem]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobLineItem.sort_order",
    )

    @property
    def lead_assignment(self) -> JobAssignment | None:
        return next((a for a in self.assignments if a.is_lead), None)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Job {self.job_number} {self.status.value}>"


class JobAssignment(UUIDPrimaryKey, Timestamps, Base):
    """Who is working a job.

    One row per person. Exactly one may be the lead -- enforced by a partial
    unique index in the migration, not by application convention.

    The lead owns the job and is the column it appears in on the dispatch board.
    Helpers see it on their own schedule but do not move it. This resolves the
    contradiction in the original brief, which asked for multiple assigned
    technicians *and* a board with one column per technician, without saying what
    dragging one copy of a two-person job should do.
    """

    __tablename__ = "job_assignments"
    __table_args__ = (
        UniqueConstraint("job_id", "membership_id", name="uq_job_assignments_person"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # References the membership, not the user: a person's right to be assigned
    # work belongs to their membership of this company, and pointing at the
    # tenant-scoped row keeps the foreign key inside the tenant boundary.
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), nullable=False, index=True
    )

    is_lead: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    job: Mapped[Job] = relationship(back_populates="assignments")
    membership: Mapped[Membership] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        role = "lead" if self.is_lead else "helper"
        return f"<JobAssignment {role} job={self.job_id}>"


class JobLineItem(UUIDPrimaryKey, Timestamps, Base):
    """Labour and parts recorded against a job.

    Technicians may add these; they may not see the money. The API strips
    unit_price_cents and the computed total from the response for technician
    callers, which is why price is nullable -- a technician logging two hours of
    labour genuinely does not supply one.
    """

    __tablename__ = "job_line_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[LineItemKind] = mapped_column(
        enum_column(LineItemKind),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)

    # Hours for labour, units for parts. Numeric, not float: 0.25 of an hour
    # must round-trip exactly.
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("1")
    )

    # Money is integer minor units throughout. Floats and currency do not mix,
    # and Numeric would invite arithmetic in the database that the application
    # cannot see.
    unit_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    job: Mapped[Job] = relationship(back_populates="line_items")

    @property
    def total_cents(self) -> int | None:
        if self.unit_price_cents is None:
            return None
        return int(self.quantity * self.unit_price_cents)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobLineItem {self.kind.value} {self.description!r}>"


class JobNumberCounter(Base):
    """Per-tenant, per-year counter for job numbers.

    A table rather than a Postgres sequence, because sequences are cluster
    objects: one per tenant per year would mean DDL at runtime, which the
    application role deliberately cannot perform. A row locked with
    SELECT ... FOR UPDATE is both simpler and correct under concurrency.
    """

    __tablename__ = "job_number_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobNumberCounter {self.year} next={self.next_value}>"
