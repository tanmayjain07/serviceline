"""Membership (team member) schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.models.enums import Role
from app.schemas.common import ORMModel


class MembershipRead(ORMModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: Role
    is_active: bool
    created_at: datetime

    # Flattened from the joined user so the team screen is a single request.
    email: EmailStr
    full_name: str
    last_login_at: datetime | None = None


class MembershipUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
