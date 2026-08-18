"""Invitation -- a pending offer of membership in a tenant."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import Role, enum_column

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class Invitation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "invitations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role: Mapped[Role] = mapped_column(enum_column(Role), nullable=False)

    # Only the SHA-256 hash is stored. The raw token exists exactly twice: in
    # the response to the invite call and in the email. A database dump does not
    # yield working invitation links.
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tenant: Mapped[Tenant] = relationship()

    @property
    def is_pending(self) -> bool:
        return self.accepted_at is None and self.revoked_at is None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Invitation {self.email!r} tenant={self.tenant_id}>"
