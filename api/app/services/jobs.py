"""Job state changes and assignment.

The status field is a state machine. Enforcing it here rather than trusting
callers means a job cannot jump from Unscheduled straight to Invoiced, and the
technician mobile view in milestone 3 cannot reopen a closed job by replaying a
stale request from a phone that was out of signal for an hour -- which, given
the offline queue that milestone ships, is a request that will genuinely arrive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request, conflict, not_found
from app.models import Job, JobAssignment, Membership, Role
from app.models.enums import JOB_STATUS_TRANSITIONS, JobStatus


def assert_can_transition(current: JobStatus, target: JobStatus) -> None:
    """Raise unless `target` is reachable from `current`."""
    if current == target:
        return
    allowed = JOB_STATUS_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        if not allowed:
            raise conflict(
                f"A job that is {current.value} is finished and cannot change status."
            )
        readable = ", ".join(sorted(s.value for s in allowed))
        raise conflict(
            f"A job that is {current.value} cannot become {target.value}. "
            f"It can only become: {readable}."
        )


def transition(job: Job, target: JobStatus) -> dict[str, object] | None:
    """Move a job to `target`, maintaining the timestamps that go with it.

    Returns the field changes for the audit entry, or None if nothing moved.
    """
    current = job.status
    if current == target:
        return None

    assert_can_transition(current, target)

    now = datetime.now(UTC)
    job.status = target

    # Timestamps are set here rather than left to callers, because a completed_at
    # that disagrees with the status is the kind of inconsistency that only
    # surfaces months later in a report nobody can reconcile.
    if target is JobStatus.COMPLETE:
        job.completed_at = now
    elif target is JobStatus.CANCELED:
        job.canceled_at = now
    elif current is JobStatus.COMPLETE and target is JobStatus.IN_PROGRESS:
        # Reopening a job that was completed in error.
        job.completed_at = None
    elif current is JobStatus.CANCELED and target is JobStatus.UNSCHEDULED:
        job.canceled_at = None

    return {"status": {"from": current.value, "to": target.value}}


def assignable_memberships(db: Session) -> list[Membership]:
    """Active people who can be given work.

    Accountants are excluded: the role is read-only by definition, and offering
    them as a column on the dispatch board would be an invitation to a mistake.
    """
    return list(
        db.scalars(
            select(Membership)
            .where(
                Membership.is_active.is_(True),
                Membership.role.in_([Role.OWNER, Role.DISPATCHER, Role.TECHNICIAN]),
            )
            .order_by(Membership.created_at)
        ).unique()
    )


def _load_membership(db: Session, membership_id: uuid.UUID) -> Membership:
    membership = db.get(Membership, membership_id)
    # RLS makes a membership from another tenant invisible, so this is a 404
    # for both "does not exist" and "belongs to someone else" -- which is the
    # intended answer to each.
    if membership is None:
        raise not_found("Team member")
    if not membership.is_active:
        raise bad_request(
            "That team member is deactivated and cannot be assigned work."
        )
    if membership.role is Role.ACCOUNTANT:
        raise bad_request("Accountants are read-only and cannot be assigned jobs.")
    return membership


def set_lead(db: Session, job: Job, membership_id: uuid.UUID | None) -> None:
    """Set, replace or clear the job's lead technician.

    The lead owns the job and is the column it occupies on the dispatch board.
    Passing None unassigns it, which is what dragging a job back to the
    unassigned tray does.
    """
    existing_lead = next((a for a in job.assignments if a.is_lead), None)

    if membership_id is None:
        if existing_lead is not None:
            job.assignments.remove(existing_lead)
        return

    membership = _load_membership(db, membership_id)

    if existing_lead is not None:
        if existing_lead.membership_id == membership.id:
            return
        job.assignments.remove(existing_lead)
        # Flush the delete before inserting the replacement. SQLAlchemy's unit
        # of work orders inserts before deletes within a table, so without this
        # the new lead row hits the partial unique index while the old one is
        # still present, and a perfectly ordinary reassignment fails.
        db.flush()

    # If this person is already a helper, promote them rather than adding a
    # second row -- the unique constraint on (job_id, membership_id) would
    # reject that anyway, and a 500 is a poor way to learn it.
    helper = next(
        (a for a in job.assignments if a.membership_id == membership.id), None
    )
    if helper is not None:
        helper.is_lead = True
        return

    job.assignments.append(
        JobAssignment(
            tenant_id=job.tenant_id,
            job_id=job.id,
            membership_id=membership.id,
            is_lead=True,
        )
    )


def set_helpers(db: Session, job: Job, membership_ids: list[uuid.UUID]) -> None:
    """Replace the job's helpers, leaving the lead alone."""
    wanted = set(membership_ids)

    lead = next((a for a in job.assignments if a.is_lead), None)
    if lead is not None and lead.membership_id in wanted:
        # Naming the lead as a helper is a no-op rather than an error: the UI
        # sends the whole crew, and the caller should not have to subtract.
        wanted.discard(lead.membership_id)

    for assignment in [a for a in job.assignments if not a.is_lead]:
        if assignment.membership_id in wanted:
            wanted.discard(assignment.membership_id)
        else:
            job.assignments.remove(assignment)

    for membership_id in wanted:
        membership = _load_membership(db, membership_id)
        job.assignments.append(
            JobAssignment(
                tenant_id=job.tenant_id,
                job_id=job.id,
                membership_id=membership.id,
                is_lead=False,
            )
        )


def is_assigned(job: Job, membership_id: uuid.UUID) -> bool:
    """Whether this person is on the job, as lead or helper.

    Used to decide whether a technician may see a job at all. Technicians see
    only their own work -- a rule from the brief, enforced in the router rather
    than by hiding rows in the UI.
    """
    return any(a.membership_id == membership_id for a in job.assignments)
