"""Password hashing, invitation tokens, and JWT encode/decode."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database -- never let this read as a match.
        return False


# --------------------------------------------------------------------------
# Invitation tokens
#
# The raw token goes in the invite email and is never stored. Only its SHA-256
# hash is persisted, so a database leak does not hand an attacker working
# invitation links.
# --------------------------------------------------------------------------


def generate_invite_token() -> tuple[str, str]:
    """Return (raw_token, token_hash)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_invite_token(raw)


def hash_invite_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------


def _encode(payload: dict[str, Any], expires: timedelta, token_type: TokenType) -> str:
    now = datetime.now(UTC)
    claims = {
        **payload,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    role: str | None,
    is_superadmin: bool = False,
) -> str:
    """Mint an access token.

    `tid` is deliberately part of the token rather than something the client
    passes per-request. The tenant a request runs against is therefore decided
    at login/switch time and signed, not chosen by the caller.
    """
    return _encode(
        {
            "sub": str(user_id),
            "tid": str(tenant_id) if tenant_id else None,
            "role": role,
            "sa": is_superadmin,
        },
        timedelta(minutes=settings.access_token_minutes),
        "access",
    )


def create_refresh_token(*, user_id: uuid.UUID) -> str:
    return _encode(
        {"sub": str(user_id)},
        timedelta(days=settings.refresh_token_days),
        "refresh",
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a token. Raises jwt exceptions on failure."""
    claims = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    if claims.get("typ") != expected_type:
        raise jwt.InvalidTokenError(
            f"expected a {expected_type} token, got {claims.get('typ')!r}"
        )
    return claims
