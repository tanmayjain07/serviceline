"""The audit log screen.

Owner-only. Read-only by construction: the application's database role has been
granted SELECT and INSERT on `audit_log` and nothing else, so there is no code
path -- intended or accidental -- that can alter or delete an entry.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.models import AuditLogEntry, Membership, Role
from app.schemas.audit import AuditEntryRead
from app.schemas.common import Page

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=Page[AuditEntryRead])
def list_entries(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, max_length=80),
    since: datetime | None = None,
    until: datetime | None = None,
    _owner: Membership = Depends(require_role(Role.OWNER)),
    db: Session = Depends(get_db),
) -> Page[AuditEntryRead]:
    conditions = []
    if action:
        conditions.append(AuditLogEntry.action == action)
    if since:
        conditions.append(AuditLogEntry.created_at >= since)
    if until:
        conditions.append(AuditLogEntry.created_at <= until)

    # Again, no tenant filter: RLS applies it. The composite index
    # (tenant_id, created_at DESC) matches this ordering.
    total = (
        db.scalar(select(func.count()).select_from(AuditLogEntry).where(*conditions))
        or 0
    )
    rows = db.scalars(
        select(AuditLogEntry)
        .where(*conditions)
        .order_by(AuditLogEntry.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return Page[AuditEntryRead](
        items=[AuditEntryRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
