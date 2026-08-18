"""Tenant read/update schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import Plan, TenantStatus, TradeType
from app.schemas.common import ORMModel


class TenantRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    trade_type: TradeType
    timezone: str
    plan: Plan
    status: TenantStatus
    trial_ends_at: datetime | None
    created_at: datetime

    # Derived, not stored -- see app/services/limits.py.
    seat_limit: int | None = None
    seats_used: int = 0


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    trade_type: TradeType | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown IANA timezone: {value}") from None
        return value
