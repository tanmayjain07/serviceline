"""Invitation schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.models.enums import Role
from app.schemas.common import ORMModel


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role


class InvitationRead(ORMModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: EmailStr
    role: Role
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    status: str


class InvitationCreated(InvitationRead):
    """Returned once, at creation, and never again.

    `accept_url` embeds the raw token. Only its hash is stored, so this is the
    single moment the token exists in a readable form outside the invite email.
    Milestone 3 replaces this field with an actual email send.
    """

    accept_url: str


class InvitationPreview(BaseModel):
    """What an invited person sees before they accept.

    Deliberately minimal: the company name and the role on offer, nothing else.
    An expired or revoked token reveals nothing at all.
    """

    tenant_name: str
    email: EmailStr
    role: Role
    expires_at: datetime
    requires_signup: bool
