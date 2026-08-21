"""Allocating job numbers.

Format is `2026-0147`: the calendar year, then a per-tenant counter that resets
each January. Two dispatchers creating a job in the same second must not receive
the same number, and the unique constraint on (tenant_id, job_number) means a
collision is a failed request rather than corrupt data -- so the allocation has
to be correct rather than merely usually correct.

Gaps are acceptable and expected. The client was asked directly and confirmed
nobody has ever queried a missing job number. That matters, because gapless
allocation is a materially harder problem: it would forbid allocating a number
before the surrounding transaction is known to commit. Invoice numbers, in
milestone 4, *are* gapless, and will need exactly that treatment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import JobNumberCounter

# Four digits covers 9,999 jobs in a year. The widest tenant the client sells to
# has 40 technicians; at four jobs each per working day that is roughly 40,000 a
# year, so the format widens rather than wraps. Better an eight-character job
# number than a duplicate.
MIN_DIGITS = 4


def allocate(db: Session, tenant_id: uuid.UUID, *, year: int | None = None) -> str:
    """Return the next job number for this tenant, consuming it.

    Must be called inside the same transaction as the job insert. The counter
    row is held under a write lock from here until that transaction ends, so
    concurrent callers queue rather than collide.
    """
    year = year or datetime.now(UTC).year

    # Create the row for a tenant's first job of the year without a race: two
    # concurrent first-jobs would both find nothing and both try to insert.
    # ON CONFLICT DO NOTHING makes the loser a no-op rather than an error.
    db.execute(
        insert(JobNumberCounter)
        .values(tenant_id=tenant_id, year=year, next_value=1)
        .on_conflict_do_nothing(index_elements=["tenant_id", "year"])
    )

    # with_for_update() is the whole point of this function. Without it, two
    # transactions read the same next_value, both write value+1, and both jobs
    # get the same number -- at which point the unique constraint rejects one of
    # them and a dispatcher sees a 500 for no reason they could understand.
    counter = db.scalars(
        select(JobNumberCounter)
        .where(
            JobNumberCounter.tenant_id == tenant_id,
            JobNumberCounter.year == year,
        )
        .with_for_update()
    ).one()

    sequence = counter.next_value
    counter.next_value = sequence + 1
    db.flush()

    return f"{year}-{sequence:0{MIN_DIGITS}d}"


def peek(db: Session, tenant_id: uuid.UUID, *, year: int | None = None) -> str:
    """What `allocate` would return next, without consuming it.

    For showing a draft number in the UI. Deliberately takes no lock: it is a
    hint, not a reservation, and the value shown may be taken by someone else
    before the draft is saved.
    """
    year = year or datetime.now(UTC).year
    counter = db.scalars(
        select(JobNumberCounter).where(
            JobNumberCounter.tenant_id == tenant_id,
            JobNumberCounter.year == year,
        )
    ).one_or_none()
    sequence = counter.next_value if counter else 1
    return f"{year}-{sequence:0{MIN_DIGITS}d}"
