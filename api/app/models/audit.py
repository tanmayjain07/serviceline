"""Audit log -- who did what, when, within a tenant.

Dale's insurance carrier asks for two years of retention. The table is designed
so that extending to seven is a retention-policy change rather than a rebuild:
entries are immutable, append-only, and carry enough context to be read years
later without joining to rows that may since have been deleted (hence the
denormalised actor_email and entity_label).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class AuditLogEntry(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "audit_log"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Kept even if the user row is later removed.
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    entity_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuditLogEntry {self.action} {self.entity_type}>"
