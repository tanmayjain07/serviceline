"""Shared HTTP error helpers.

A note on 404-vs-403: when a caller asks for a resource that exists but belongs
to another tenant, we return 404, not 403. A 403 confirms the row exists, which
leaks the very thing tenant isolation is supposed to hide (an attacker could
enumerate IDs and learn how many jobs a competitor has). In practice this is
mostly academic here because RLS means the row simply is not visible to the
query -- but the rule is stated so nobody "helpfully" improves the error later.
"""

from __future__ import annotations

from fastapi import HTTPException, status


def not_found(what: str = "Resource") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found"
    )


def forbidden(detail: str = "Insufficient permissions") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def payment_required(detail: str) -> HTTPException:
    """Used when a plan limit blocks the action.

    402 is unusual but correct here, and it lets the frontend show an upgrade
    prompt without string-matching an error message.
    """
    return HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)
