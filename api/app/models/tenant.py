"""Tenant -- one contractor company subscribing to ServiceLine."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import Plan, TenantStatus, TradeType, enum_column

if TYPE_CHECKING:
    from app.models.membership import Membership


class Tenant(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, index=True
    )

    trade_type: Mapped[TradeType] = mapped_column(
        enum_column(TradeType), nullable=False, default=TradeType.HVAC
    )

    # The tenant's default IANA timezone. Note that from milestone 2 onward the
    # authoritative timezone for scheduling lives on the *service address*, not
    # here -- one of Dale's contractors works both sides of the Ohio/Indiana
    # line, where half of Indiana observes Central time. This field is only the
    # default for new addresses and the display default for company-wide views.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="America/New_York"
    )

    plan: Mapped[Plan] = mapped_column(
        enum_column(Plan), nullable=False, default=Plan.TRIAL
    )
    status: Mapped[TenantStatus] = mapped_column(
        enum_column(TenantStatus), nullable=False, default=TenantStatus.TRIALING
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Set by the internal super-admin when comping an account (milestone 5).
    # A non-null value overrides the plan's seat limit.
    seat_limit_override: Mapped[int | None] = mapped_column(nullable=True)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Tenant {self.slug!r}>"
