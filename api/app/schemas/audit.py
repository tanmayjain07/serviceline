"""Audit log schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from pydantic import EmailStr, field_validator

from app.schemas.common import ORMModel


class AuditEntryRead(ORMModel):
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    entity_label: str | None
    actor_user_id: uuid.UUID | None
    actor_email: EmailStr | None
    changes: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime

    @field_validator("ip_address", mode="before")
    @classmethod
    def stringify_ip(cls, value: object) -> str | None:
        """psycopg returns INET columns as ipaddress objects, not strings.

        Keeping INET in the database is right -- it validates on write and
        supports network operators -- but the JSON contract is a plain string,
        so the conversion happens here rather than by weakening the column type.
        """
        if value is None:
            return None
        if isinstance(value, IPv4Address | IPv6Address):
            return str(value)
        return str(value)
