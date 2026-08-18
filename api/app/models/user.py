"""User -- a person. Deliberately global, not tenant-scoped.

A user is an identity, not a seat. The same person can hold memberships in
several tenants (see ADR-002 in docs/architecture.md), so this table has no
tenant_id and no RLS policy. Nothing in the API ever lists users directly --
they are only ever reachable through a membership, which *is* RLS-protected.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.models.membership import Membership


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Staff at ServiceLine itself, not a tenant role. Grants access to the
    # internal admin surface (milestone 5). Never settable through the API.
    is_superadmin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email!r}>"
