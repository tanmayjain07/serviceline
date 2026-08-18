"""Company slug generation."""

from __future__ import annotations

import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Words that would be confusing or hostile as a company slug.
RESERVED = frozenset(
    {
        "admin",
        "api",
        "app",
        "auth",
        "billing",
        "dashboard",
        "help",
        "internal",
        "login",
        "serviceline",
        "settings",
        "signup",
        "static",
        "support",
        "system",
        "www",
    }
)


def slugify(value: str) -> str:
    slug = _NON_ALNUM.sub("-", value.lower()).strip("-")
    return slug[:60] or "company"


def unique_slug(db: Session, name: str) -> str:
    """Find a free slug for a company name.

    Note this runs inside the signup transaction, so two simultaneous signups
    with the same company name can still race past the SELECT. The unique index
    on `tenants.slug` is the real guarantee; this loop only keeps the common
    case tidy. The signup handler catches IntegrityError and retries.
    """
    base = slugify(name)
    if base in RESERVED:
        base = f"{base}-co"

    candidate = base
    for _ in range(5):
        exists = db.scalar(select(Tenant.id).where(Tenant.slug == candidate))
        if exists is None:
            return candidate
        candidate = f"{base}-{secrets.token_hex(2)}"

    return f"{base}-{secrets.token_hex(4)}"
