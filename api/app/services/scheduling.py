"""Turning a booked window into instants, and detecting clashes.

The central idea: a booked window is a *promise in local time*. "The 14th,
between 8 and 12" means eight o'clock as the customer's clock reads it, at the
address the work happens at. Stored as an instant, that promise would silently
move if a timezone rule changed, and the customer would be told the wrong hour.

So the local form is authoritative and stored as written. The UTC form is
derived from it and stored alongside, because the one question local times
cannot answer is whether two windows overlap:

    Ohio,    08:00-12:00  America/New_York        = 12:00-16:00 UTC
    Indiana, 11:00-13:00  America/Indiana/Knox    = 16:00-18:00 UTC

(August, so both are on daylight time: Eastern is UTC-4, Central UTC-5.)

Compared as wall clocks those overlap between 11 and 12. As instants they merely
touch at 16:00 -- back to back, no clash. A technician can genuinely work both,
and a dispatch board that refuses the booking is wrong.

Indiana is not a contrived example. America/Indiana/Indianapolis is Eastern
while America/Indiana/Knox is Central: two addresses in the same state, an hour
apart.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import Job, JobAssignment, ServiceAddress
from app.models.enums import OPEN_JOB_STATUSES


class UnknownTimezone(ValueError):
    """Raised when an address carries a timezone this system cannot resolve."""


def resolve_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UnknownTimezone(f"Unknown IANA timezone: {name!r}") from exc


def to_utc(day: date, moment: time, timezone: str) -> datetime:
    """Interpret a local date and time at `timezone` as an absolute instant.

    Ambiguity is resolved deliberately rather than left to chance. On the
    autumn changeover an hour repeats, and `fold=0` selects the first --
    the earlier instant, which is the one a customer expecting "1:30am"
    would experience first. On the spring changeover an hour does not exist
    at all; Python maps it forward, which is the least surprising answer for
    an arrival window and matters little in practice, since nobody books a
    plumber for 2:30am.
    """
    zone = resolve_zone(timezone)
    return datetime.combine(day, moment, tzinfo=zone).astimezone(ZoneInfo("UTC"))


def window_to_utc(
    *,
    scheduled_date: date | None,
    start: time | None,
    end: time | None,
    timezone: str,
) -> tuple[datetime | None, datetime | None]:
    """Derive the stored UTC pair for a job's booked window.

    Returns (None, None) unless the whole window is present -- an unscheduled
    job, or one with a date but no times, has no instants to compare.
    """
    if scheduled_date is None or start is None or end is None:
        return None, None
    return (
        to_utc(scheduled_date, start, timezone),
        to_utc(scheduled_date, end, timezone),
    )


def recompute_window(db: Session, job: Job) -> None:
    """Refresh a job's UTC window from its local window and address timezone.

    Called after anything that could change either. Cheap, and much safer than
    trying to remember every path that invalidates it -- moving a job to a
    different service address changes the timezone without touching a time.
    """
    address = db.get(ServiceAddress, job.service_address_id)
    if address is None:  # pragma: no cover - foreign key makes this unreachable
        job.window_start_utc = job.window_end_utc = None
        return

    job.window_start_utc, job.window_end_utc = window_to_utc(
        scheduled_date=job.scheduled_date,
        start=job.arrival_window_start,
        end=job.arrival_window_end,
        timezone=address.timezone,
    )


def find_conflicts(
    db: Session,
    *,
    membership_id: uuid.UUID,
    start_utc: datetime | None,
    end_utc: datetime | None,
    exclude_job_id: uuid.UUID | None = None,
) -> list[Job]:
    """Jobs already booked for this person that overlap the given window.

    A warning, not a prohibition. Dispatchers double-book on purpose -- a quick
    callback squeezed between two long installs is normal -- so the board flags
    the clash and lets a human decide. Refusing the booking outright would mean
    the software knowing better than the person holding the phone.

    Two intervals overlap when each starts before the other ends. Touching
    endpoints are not an overlap: a job ending at 12:00 and one starting at
    12:00 are back to back, which is the whole point of a schedule.
    """
    if start_utc is None or end_utc is None:
        return []

    statement = (
        select(Job)
        .join(JobAssignment, JobAssignment.job_id == Job.id)
        .where(
            JobAssignment.membership_id == membership_id,
            Job.status.in_(OPEN_JOB_STATUSES),
            Job.window_start_utc.is_not(None),
            Job.window_end_utc.is_not(None),
            and_(Job.window_start_utc < end_utc, Job.window_end_utc > start_utc),
        )
        .order_by(Job.window_start_utc)
    )
    if exclude_job_id is not None:
        statement = statement.where(Job.id != exclude_job_id)

    return list(db.scalars(statement).unique())


def board_range_utc(
    first_day: date, last_day: date, timezone: str
) -> tuple[datetime, datetime]:
    """The instants spanning a run of local days, for a board query.

    Widened by a day at each end before use, because a tenant whose addresses
    span several timezones has days that start and finish at different moments;
    a range computed from one zone would clip jobs at the edges of the other.
    """
    zone = resolve_zone(timezone)
    start = datetime.combine(first_day, time.min, tzinfo=zone)
    end = datetime.combine(last_day, time.max, tzinfo=zone)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))


def overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    """Pure interval overlap, exposed for tests and for in-memory checks."""
    return a_start < b_end and a_end > b_start


__all__ = [
    "UnknownTimezone",
    "board_range_utc",
    "find_conflicts",
    "overlaps",
    "recompute_window",
    "resolve_zone",
    "to_utc",
    "window_to_utc",
]
