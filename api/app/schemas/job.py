"""Request and response bodies for jobs.

Note what is *not* here: a single JobRead used for everyone. Technicians must
not see pricing, and the cleanest way to guarantee that is for their responses
to be built from a schema that has no price field at all -- rather than a shared
schema with a nullable field that some code path forgets to blank.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import JobPriority, JobStatus, JobType, LineItemKind, Role
from app.schemas.common import ORMModel


class LineItemCreate(BaseModel):
    kind: LineItemKind
    description: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(
        default=Decimal("1"), gt=0, max_digits=10, decimal_places=2
    )
    unit_price_cents: int | None = Field(default=None, ge=0)


class LineItemRead(ORMModel):
    id: uuid.UUID
    kind: LineItemKind
    description: str
    quantity: Decimal
    sort_order: int


class LineItemPricedRead(LineItemRead):
    """The same line item, with money. Never returned to a technician."""

    unit_price_cents: int | None
    total_cents: int | None


class AssignmentRead(ORMModel):
    membership_id: uuid.UUID
    is_lead: bool
    full_name: str | None = None
    role: Role | None = None


class JobBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    job_type: JobType = JobType.REPAIR
    priority: JobPriority = JobPriority.NORMAL
    description: str | None = None
    customer_notes: str | None = None
    internal_notes: str | None = None

    scheduled_date: date | None = None
    arrival_window_start: time | None = None
    arrival_window_end: time | None = None

    @model_validator(mode="after")
    def check_window(self):
        start, end = self.arrival_window_start, self.arrival_window_end
        if (start is None) != (end is None):
            raise ValueError(
                "An arrival window needs both a start and an end, or neither."
            )
        if start is not None and end is not None and end <= start:
            raise ValueError("The arrival window must end after it starts.")
        if start is not None and self.scheduled_date is None:
            raise ValueError("An arrival window needs a date.")
        return self


class JobCreate(JobBase):
    customer_id: uuid.UUID
    service_address_id: uuid.UUID
    lead_membership_id: uuid.UUID | None = None
    helper_membership_ids: list[uuid.UUID] = Field(default_factory=list)
    line_items: list[LineItemCreate] = Field(default_factory=list)


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    job_type: JobType | None = None
    priority: JobPriority | None = None
    description: str | None = None
    customer_notes: str | None = None
    internal_notes: str | None = None
    service_address_id: uuid.UUID | None = None

    scheduled_date: date | None = None
    arrival_window_start: time | None = None
    arrival_window_end: time | None = None


class JobSchedule(BaseModel):
    """Moving a job on the dispatch board.

    Separate from JobUpdate because it is a different action with different
    permissions and a different audit entry -- and because the board sends it on
    every drag, so it should carry as little as possible.
    """

    scheduled_date: date | None = None
    arrival_window_start: time | None = None
    arrival_window_end: time | None = None
    lead_membership_id: uuid.UUID | None = None

    # A dispatcher may knowingly double-book -- a quick callback between two
    # long installs is normal. The API reports the clash and refuses only until
    # the caller says they meant it.
    allow_conflicts: bool = False


class JobStatusChange(BaseModel):
    status: JobStatus


class JobSummary(ORMModel):
    """The list and board shape. Deliberately small.

    The board renders hundreds of these at once, so it carries what a card
    shows and nothing more.
    """

    id: uuid.UUID
    job_number: str
    title: str
    status: JobStatus
    priority: JobPriority
    job_type: JobType

    customer_id: uuid.UUID
    customer_name: str | None = None
    address_one_line: str | None = None
    address_timezone: str | None = None

    scheduled_date: date | None
    arrival_window_start: time | None
    arrival_window_end: time | None
    window_start_utc: datetime | None
    window_end_utc: datetime | None

    lead_membership_id: uuid.UUID | None = None
    lead_name: str | None = None
    helper_count: int = 0


class JobDetail(JobSummary):
    description: str | None
    customer_notes: str | None
    # Present only for roles that may read it. A technician's response omits the
    # field entirely rather than sending null, so the client cannot mistake
    # "not allowed" for "empty".
    internal_notes: str | None = None

    service_address_id: uuid.UUID
    assignments: list[AssignmentRead] = Field(default_factory=list)
    line_items: list[LineItemRead] = Field(default_factory=list)

    completed_at: datetime | None = None
    canceled_at: datetime | None = None
    created_at: datetime


class JobPricedDetail(JobDetail):
    """Job detail including money. Never returned to a technician."""

    line_items: list[LineItemPricedRead] = Field(default_factory=list)
    total_cents: int | None = None


class ConflictingJob(ORMModel):
    id: uuid.UUID
    job_number: str
    title: str
    scheduled_date: date | None
    arrival_window_start: time | None
    arrival_window_end: time | None


class ScheduleConflict(BaseModel):
    """Returned with 409 when a move would double-book someone."""

    detail: str
    conflicts: list[ConflictingJob]
