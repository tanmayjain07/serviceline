"""Request and response bodies for customers and their service addresses."""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import CustomerKind
from app.schemas.common import ORMModel


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown IANA timezone: {value}") from None
    return value


class ServiceAddressBase(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=120)
    state: str = Field(min_length=1, max_length=60)
    postal_code: str = Field(min_length=1, max_length=20)
    notes: str | None = None
    is_primary: bool = False


class ServiceAddressCreate(ServiceAddressBase):
    # Optional on the way in: the API falls back to the company's default when
    # a dispatcher does not choose one, which is right for the overwhelming
    # majority of addresses. It is stored on the address regardless, so a later
    # change to the company default cannot silently move existing appointments.
    timezone: str | None = Field(default=None, max_length=64)

    _check_timezone = field_validator("timezone")(
        lambda v: _validate_timezone(v) if v is not None else v
    )


class ServiceAddressUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    line1: str | None = Field(default=None, min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, min_length=1, max_length=120)
    state: str | None = Field(default=None, min_length=1, max_length=60)
    postal_code: str | None = Field(default=None, min_length=1, max_length=20)
    timezone: str | None = Field(default=None, max_length=64)
    notes: str | None = None
    is_primary: bool | None = None
    is_active: bool | None = None

    _check_timezone = field_validator("timezone")(
        lambda v: _validate_timezone(v) if v is not None else v
    )


class ServiceAddressRead(ORMModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    label: str | None
    line1: str
    line2: str | None
    city: str
    state: str
    postal_code: str
    timezone: str
    notes: str | None
    is_primary: bool
    is_active: bool
    one_line: str
    created_at: datetime


class CustomerBase(BaseModel):
    kind: CustomerKind = CustomerKind.RESIDENTIAL
    name: str = Field(min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: EmailStr | None = None
    notes: str | None = None


class CustomerCreate(CustomerBase):
    # A customer with nowhere to send anyone is not much use, so the first
    # address can be created in the same request. Optional, because a
    # dispatcher taking a phone call may have the name before the address.
    address: ServiceAddressCreate | None = None


class CustomerUpdate(BaseModel):
    kind: CustomerKind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: EmailStr | None = None
    notes: str | None = None
    is_active: bool | None = None


class CustomerRead(ORMModel):
    id: uuid.UUID
    kind: CustomerKind
    name: str
    contact_name: str | None
    phone: str | None
    email: str | None
    notes: str | None
    is_active: bool
    created_at: datetime


class CustomerDetail(CustomerRead):
    addresses: list[ServiceAddressRead] = Field(default_factory=list)
    open_job_count: int = 0
