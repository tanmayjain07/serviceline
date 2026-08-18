"""Writing audit entries.

Entries are written on the same transaction as the change they describe, so an
action and its audit record either both land or neither does. That is the whole
reason this is a plain function taking a Session rather than a background task.

Ordering requirement: AuditLogEntry declares no ORM relationships, because it is
an append-only log with denormalised columns so that entries stay readable years
later even if the rows they describe are gone. The consequence is that
SQLAlchemy's unit of work does not know it depends on `tenants` or `users` and
may emit its INSERT before theirs. If you are creating the referenced row in the
same transaction, flush it before calling `record()`. See the note in
routers/auth.py::signup.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLogEntry, User


def record(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    action: str,
    entity_type: str,
    actor: User | None = None,
    entity_id: uuid.UUID | None = None,
    entity_label: str | None = None,
    changes: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLogEntry:
    entry = AuditLogEntry(
        tenant_id=tenant_id,
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        changes=changes,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:500] or None,
    )
    db.add(entry)
    return entry


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any] | None:
    """Build a {field: {from, to}} map of what actually changed.

    Returns None when nothing changed, so callers can skip writing a no-op
    audit entry.
    """
    changed = {
        key: {"from": before.get(key), "to": after[key]}
        for key in after
        if before.get(key) != after[key]
    }
    return changed or None
