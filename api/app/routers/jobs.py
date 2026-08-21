"""Jobs: creating, scheduling, and moving through their lifecycle."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import bad_request, forbidden, not_found
from app.deps import (
    Principal,
    client_ip,
    get_current_membership,
    get_current_user,
    get_db,
    get_principal,
)
from app.models import (
    Customer,
    Job,
    JobLineItem,
    Membership,
    Role,
    ServiceAddress,
    User,
)
from app.models.enums import OPEN_JOB_STATUSES, JobStatus
from app.schemas.common import Page
from app.schemas.job import (
    AssignmentRead,
    ConflictingJob,
    JobCreate,
    JobDetail,
    JobPricedDetail,
    JobSchedule,
    JobStatusChange,
    JobSummary,
    JobUpdate,
    LineItemPricedRead,
    LineItemRead,
)
from app.services import audit, job_numbers, scheduling
from app.services import jobs as job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

# These routes declare response_model=None on purpose.
#
# The response shape depends on the caller's role: JobPricedDetail for anyone
# who may see money, JobDetail -- which has no price fields at all -- for a
# technician. Declaring response_model=JobDetail made FastAPI filter every
# response down to that schema, silently discarding the totals an owner is
# entitled to. Declaring the priced schema instead would have been worse: it
# would have added the price fields back as nulls for technicians, defeating the
# point of having two shapes.
#
# With no response_model, the Pydantic object the handler returns is serialised
# exactly as built. The cost is that OpenAPI cannot state one schema for the
# route, which is honest -- there genuinely is not one.

# Roles that may see money. From the brief: a technician "cannot see pricing or
# other techs' schedules". Rather than nulling price fields on the way out, the
# response is built from a schema that has no price field at all -- a shape that
# cannot leak what it does not contain.
MAY_SEE_PRICING = frozenset({Role.OWNER, Role.DISPATCHER, Role.ACCOUNTANT})
MAY_DISPATCH = frozenset({Role.OWNER, Role.DISPATCHER})


def _require_dispatch(membership: Membership) -> None:
    if membership.role not in MAY_DISPATCH:
        raise forbidden("Only an owner or dispatcher can schedule work.")


def _base_query():
    return select(Job).options(
        selectinload(Job.assignments),
        selectinload(Job.line_items),
        selectinload(Job.customer),
        selectinload(Job.service_address),
    )


def _load(db: Session, job_id: uuid.UUID, membership: Membership) -> Job:
    job = db.scalars(_base_query().where(Job.id == job_id)).unique().one_or_none()
    # Another tenant's job is invisible to the query, so this covers both
    # "no such job" and "not yours" with the same answer.
    if job is None:
        raise not_found("Job")

    # A technician sees only work they are on. This is the second half of the
    # same sentence in the brief, and it is enforced here rather than by
    # filtering the list endpoint alone -- otherwise a technician who guessed an
    # ID would still get the record.
    if membership.role is Role.TECHNICIAN and not job_service.is_assigned(
        job, membership.id
    ):
        raise not_found("Job")

    return job


def _summary(job: Job) -> JobSummary:
    lead = job.lead_assignment
    return JobSummary(
        id=job.id,
        job_number=job.job_number,
        title=job.title,
        status=job.status,
        priority=job.priority,
        job_type=job.job_type,
        customer_id=job.customer_id,
        customer_name=job.customer.name if job.customer else None,
        address_one_line=job.service_address.one_line if job.service_address else None,
        address_timezone=job.service_address.timezone if job.service_address else None,
        scheduled_date=job.scheduled_date,
        arrival_window_start=job.arrival_window_start,
        arrival_window_end=job.arrival_window_end,
        window_start_utc=job.window_start_utc,
        window_end_utc=job.window_end_utc,
        lead_membership_id=lead.membership_id if lead else None,
        lead_name=(
            lead.membership.user.full_name
            if lead and lead.membership and lead.membership.user
            else None
        ),
        helper_count=sum(1 for a in job.assignments if not a.is_lead),
    )


def _assignments(job: Job) -> list[AssignmentRead]:
    out: list[AssignmentRead] = []
    for a in job.assignments:
        out.append(
            AssignmentRead(
                membership_id=a.membership_id,
                is_lead=a.is_lead,
                full_name=a.membership.user.full_name
                if a.membership and a.membership.user
                else None,
                role=a.membership.role if a.membership else None,
            )
        )
    return sorted(out, key=lambda a: (not a.is_lead, a.full_name or ""))


def _detail(job: Job, membership: Membership) -> JobDetail:
    """Build the response shape this caller is entitled to."""
    summary = _summary(job).model_dump()

    if membership.role in MAY_SEE_PRICING:
        items = [LineItemPricedRead.model_validate(i) for i in job.line_items]
        total = sum(i.total_cents or 0 for i in items) if items else None
        return JobPricedDetail(
            **summary,
            description=job.description,
            customer_notes=job.customer_notes,
            internal_notes=job.internal_notes,
            service_address_id=job.service_address_id,
            assignments=_assignments(job),
            line_items=items,
            total_cents=total,
            completed_at=job.completed_at,
            canceled_at=job.canceled_at,
            created_at=job.created_at,
        )

    return JobDetail(
        **summary,
        description=job.description,
        customer_notes=job.customer_notes,
        # internal_notes deliberately omitted for technicians: it is where
        # dispatchers record things about a customer that nobody should repeat.
        internal_notes=None,
        service_address_id=job.service_address_id,
        assignments=_assignments(job),
        line_items=[LineItemRead.model_validate(i) for i in job.line_items],
        completed_at=job.completed_at,
        canceled_at=job.canceled_at,
        created_at=job.created_at,
    )


def _conflict_response(conflicts: list[Job]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "detail": (
                f"That technician already has {len(conflicts)} overlapping "
                f"job(s) in that window."
            ),
            "conflicts": [
                ConflictingJob.model_validate(c).model_dump(mode="json")
                for c in conflicts
            ],
        },
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@router.get("", response_model=Page[JobSummary])
def list_jobs(
    status_in: list[JobStatus] | None = Query(default=None, alias="status"),
    customer_id: uuid.UUID | None = None,
    mine: bool = False,
    scheduled_from: date | None = None,
    scheduled_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Page[JobSummary]:
    statement = _base_query()

    if status_in:
        statement = statement.where(Job.status.in_(status_in))
    if customer_id is not None:
        statement = statement.where(Job.customer_id == customer_id)
    if scheduled_from is not None:
        statement = statement.where(Job.scheduled_date >= scheduled_from)
    if scheduled_to is not None:
        statement = statement.where(Job.scheduled_date <= scheduled_to)

    # A technician's list is always their own, whether they asked for that or
    # not. `mine` is a convenience for everyone else.
    if membership.role is Role.TECHNICIAN or mine:
        statement = statement.where(Job.assignments.any(membership_id=membership.id))

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = (
        db.scalars(
            statement.order_by(
                Job.scheduled_date.is_(None),
                Job.scheduled_date,
                Job.arrival_window_start,
                Job.job_number,
            )
            .limit(limit)
            .offset(offset)
        )
        .unique()
        .all()
    )

    return Page[JobSummary](
        items=[_summary(j) for j in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/board", response_model=list[JobSummary])
def dispatch_board(
    week_of: date | None = None,
    days: int = Query(default=7, ge=1, le=14),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[JobSummary]:
    """Every open job in a date range, for the dispatch board.

    Returned flat rather than grouped by technician. The board has to render
    unassigned work too, and grouping server-side would mean inventing a bucket
    for "nobody" -- the client already knows how to lay out columns.

    The acceptance criterion is 25 technicians and 200 jobs, so this is one
    query with the joins eager-loaded, not one query per column.
    """
    _require_dispatch(membership)

    first = week_of or date.today()
    last = first + timedelta(days=days - 1)

    rows = (
        db.scalars(
            _base_query()
            .where(
                Job.status.in_(OPEN_JOB_STATUSES),
                # Unscheduled jobs have no date and belong in the tray, so they
                # are included regardless of the range.
                (Job.scheduled_date.is_(None))
                | ((Job.scheduled_date >= first) & (Job.scheduled_date <= last)),
            )
            .order_by(
                Job.scheduled_date.is_(None),
                Job.scheduled_date,
                Job.arrival_window_start,
            )
        )
        .unique()
        .all()
    )
    return [_summary(j) for j in rows]


@router.get("/{job_id}", response_model=None)
def read_job(
    job_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> JobDetail:
    return _detail(_load(db, job_id, membership), membership)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


@router.post("", response_model=None, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    request: Request,
    membership: Membership = Depends(get_current_membership),
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> JobDetail:
    _require_dispatch(membership)
    assert principal.tenant_id is not None

    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise not_found("Customer")

    address = db.get(ServiceAddress, payload.service_address_id)
    if address is None:
        raise not_found("Service address")
    if address.customer_id != customer.id:
        raise bad_request("That service address belongs to a different customer.")

    job = Job(
        tenant_id=principal.tenant_id,
        job_number=job_numbers.allocate(db, principal.tenant_id),
        customer_id=customer.id,
        service_address_id=address.id,
        title=payload.title.strip(),
        job_type=payload.job_type,
        priority=payload.priority,
        description=payload.description,
        customer_notes=payload.customer_notes,
        internal_notes=payload.internal_notes,
        scheduled_date=payload.scheduled_date,
        arrival_window_start=payload.arrival_window_start,
        arrival_window_end=payload.arrival_window_end,
        status=(
            JobStatus.SCHEDULED
            if payload.scheduled_date and payload.lead_membership_id
            else JobStatus.UNSCHEDULED
        ),
    )
    db.add(job)
    db.flush()

    scheduling.recompute_window(db, job)

    if payload.lead_membership_id is not None:
        job_service.set_lead(db, job, payload.lead_membership_id)
    if payload.helper_membership_ids:
        job_service.set_helpers(db, job, payload.helper_membership_ids)

    for index, item in enumerate(payload.line_items):
        db.add(
            JobLineItem(
                tenant_id=principal.tenant_id,
                job_id=job.id,
                kind=item.kind,
                description=item.description,
                quantity=item.quantity,
                unit_price_cents=item.unit_price_cents,
                sort_order=index,
            )
        )

    db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor=user,
        action="job.created",
        entity_type="job",
        entity_id=job.id,
        entity_label=f"{job.job_number} {job.title}",
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    db.refresh(job)
    return _detail(job, membership)


@router.patch("/{job_id}", response_model=None)
def update_job(
    job_id: uuid.UUID,
    payload: JobUpdate,
    request: Request,
    membership: Membership = Depends(get_current_membership),
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> JobDetail:
    assert principal.tenant_id is not None
    job = _load(db, job_id, membership)

    fields = payload.model_dump(exclude_unset=True)

    # A technician on the job may record what happened; they may not reschedule
    # it, move it to another address, or touch the internal notes.
    if membership.role is Role.TECHNICIAN:
        forbidden_fields = set(fields) & {
            "scheduled_date",
            "arrival_window_start",
            "arrival_window_end",
            "service_address_id",
            "internal_notes",
        }
        if forbidden_fields:
            raise forbidden(
                "A technician cannot change: " + ", ".join(sorted(forbidden_fields))
            )

    if "service_address_id" in fields:
        address = db.get(ServiceAddress, fields["service_address_id"])
        if address is None:
            raise not_found("Service address")
        if address.customer_id != job.customer_id:
            raise bad_request("That service address belongs to a different customer.")

    before = {k: getattr(job, k) for k in fields}
    for key, value in fields.items():
        setattr(job, key, value)

    # Any of date, times or address can change the instants.
    scheduling.recompute_window(db, job)
    db.flush()

    changes = audit.diff(
        {
            k: (v.value if hasattr(v, "value") else str(v) if v is not None else None)
            for k, v in before.items()
        },
        {
            k: (
                getattr(job, k).value
                if hasattr(getattr(job, k), "value")
                else str(getattr(job, k))
                if getattr(job, k) is not None
                else None
            )
            for k in fields
        },
    )
    if changes:
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor=user,
            action="job.updated",
            entity_type="job",
            entity_id=job.id,
            entity_label=f"{job.job_number} {job.title}",
            changes=changes,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

    return _detail(job, membership)


@router.post("/{job_id}/schedule", response_model=None)
def schedule_job(
    job_id: uuid.UUID,
    payload: JobSchedule,
    request: Request,
    membership: Membership = Depends(get_current_membership),
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> JobDetail:
    """Move a job on the dispatch board.

    Separate from PATCH because it is the one action the board performs on every
    drag: it changes when and who, checks for a clash, and moves the status
    between Unscheduled and Scheduled to match.
    """
    _require_dispatch(membership)
    assert principal.tenant_id is not None
    job = _load(db, job_id, membership)

    before = {
        "scheduled_date": str(job.scheduled_date) if job.scheduled_date else None,
        "lead": str(job.lead_assignment.membership_id) if job.lead_assignment else None,
    }

    fields = payload.model_dump(exclude_unset=True)
    if "scheduled_date" in fields:
        job.scheduled_date = payload.scheduled_date
    if "arrival_window_start" in fields:
        job.arrival_window_start = payload.arrival_window_start
    if "arrival_window_end" in fields:
        job.arrival_window_end = payload.arrival_window_end

    if (job.arrival_window_start is None) != (job.arrival_window_end is None):
        raise bad_request(
            "An arrival window needs both a start and an end, or neither."
        )

    scheduling.recompute_window(db, job)

    if "lead_membership_id" in fields:
        job_service.set_lead(db, job, payload.lead_membership_id)
    db.flush()

    lead = job.lead_assignment
    if lead is not None and not payload.allow_conflicts:
        clashes = scheduling.find_conflicts(
            db,
            membership_id=lead.membership_id,
            start_utc=job.window_start_utc,
            end_utc=job.window_end_utc,
            exclude_job_id=job.id,
        )
        if clashes:
            # Rolled back by the dependency when the exception propagates, so a
            # refused move leaves nothing behind.
            raise _conflict_response(clashes)

    # Keep status honest with the facts. A job with a date and a lead is
    # scheduled; one without either is not.
    if job.status in {JobStatus.UNSCHEDULED, JobStatus.SCHEDULED}:
        should_be = (
            JobStatus.SCHEDULED
            if job.scheduled_date is not None and lead is not None
            else JobStatus.UNSCHEDULED
        )
        if should_be is not job.status:
            job_service.transition(job, should_be)

    db.flush()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor=user,
        action="job.scheduled",
        entity_type="job",
        entity_id=job.id,
        entity_label=f"{job.job_number} {job.title}",
        changes=audit.diff(
            before,
            {
                "scheduled_date": str(job.scheduled_date)
                if job.scheduled_date
                else None,
                "lead": str(lead.membership_id) if lead else None,
            },
        ),
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    db.refresh(job)
    return _detail(job, membership)


@router.post("/{job_id}/status", response_model=None)
def change_status(
    job_id: uuid.UUID,
    payload: JobStatusChange,
    request: Request,
    membership: Membership = Depends(get_current_membership),
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> JobDetail:
    assert principal.tenant_id is not None
    job = _load(db, job_id, membership)

    # A technician drives their own job forward through the working statuses.
    # Invoicing and closing are somebody else's business.
    if membership.role is Role.TECHNICIAN and payload.status not in {
        JobStatus.EN_ROUTE,
        JobStatus.IN_PROGRESS,
        JobStatus.COMPLETE,
    }:
        raise forbidden(
            "A technician can only mark a job en route, in progress, or complete."
        )

    changes = job_service.transition(job, payload.status)
    if changes is not None:
        db.flush()
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor=user,
            action="job.status_changed",
            entity_type="job",
            entity_id=job.id,
            entity_label=f"{job.job_number} {job.title}",
            changes=changes,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

    return _detail(job, membership)
