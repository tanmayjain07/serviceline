"""Request and response bodies for the auth flows."""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import Role, TradeType
from app.schemas.common import ORMModel

PASSWORD_MIN = 10


def _validate_password(value: str) -> str:
    """Length over composition rules.

    NIST dropped the "one uppercase, one symbol" advice years ago -- those rules
    push people towards Password1! and no further. A 10-character minimum with
    no composition requirement is both friendlier and stronger in practice.
    """
    if len(value) < PASSWORD_MIN:
        raise ValueError(f"Password must be at least {PASSWORD_MIN} characters")
    return value


class SignupRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    trade_type: TradeType = TradeType.HVAC
    timezone: str = Field(default="America/New_York", max_length=64)

    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str

    _check_password = field_validator("password")(_validate_password)

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown IANA timezone: {value}") from None
        return value

    @field_validator("company_name")
    @classmethod
    def check_company_name(cls, value: str) -> str:
        if not re.search(r"[A-Za-z0-9]", value):
            raise ValueError("Company name must contain letters or numbers")
        return value.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Optional: log straight into a specific company when the user belongs to
    # more than one. Omitted means "the only one you have", or a token with no
    # tenant if the user belongs to several.
    tenant_id: uuid.UUID | None = None


class SwitchTenantRequest(BaseModel):
    tenant_id: uuid.UUID


class RefreshRequest(BaseModel):
    refresh_token: str


class AcceptInviteRequest(BaseModel):
    token: str
    # Only required when the invited email does not already have an account.
    full_name: str | None = Field(default=None, max_length=200)
    password: str | None = None

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str | None) -> str | None:
        return _validate_password(value) if value is not None else None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    # Null when the user belongs to several companies and has not picked one
    # yet. The frontend uses this to decide whether to show a company chooser.
    tenant_id: uuid.UUID | None = None
    role: Role | None = None


class MembershipSummary(ORMModel):
    """A company the current user belongs to, for the account switcher."""

    tenant_id: uuid.UUID
    tenant_name: str
    tenant_slug: str
    role: Role
    is_active: bool


class MeResponse(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_superadmin: bool
    active_tenant_id: uuid.UUID | None
    active_role: Role | None
    memberships: list[MembershipSummary]
