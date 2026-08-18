"""The current company's profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.deps import (
    Principal,
    client_ip,
    get_current_membership,
    get_current_user,
    get_db,
    get_principal,
    require_role,
)
from app.models import Membership, Role, Tenant, User
from app.schemas.tenant import TenantRead, TenantUpdate
from app.services import audit, limits

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _to_read(db: Session, tenant: Tenant) -> TenantRead:
    result = TenantRead.model_validate(tenant)
    result.seat_limit = limits.seat_limit(tenant)
    result.seats_used = limits.seats_used(db, tenant.id)
    return result


@router.get("/current", response_model=TenantRead)
def read_current(
    principal: Principal = Depends(get_principal),
    _membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> TenantRead:
    """Read the company the caller's token is scoped to.

    There is no `GET /tenants/{id}` on purpose. The only company a caller can
    ask about is the one their token already names, which removes an entire
    class of "forgot to check the ID" bug from the surface area.
    """
    tenant = db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise not_found("Company")
    return _to_read(db, tenant)


@router.patch("/current", response_model=TenantRead)
def update_current(
    payload: TenantUpdate,
    request: Request,
    _owner: Membership = Depends(require_role(Role.OWNER)),
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> TenantRead:
    tenant = db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise not_found("Company")

    fields = payload.model_dump(exclude_unset=True)
    before = {key: getattr(tenant, key) for key in fields}
    for key, value in fields.items():
        setattr(tenant, key, value)

    def _serialise(mapping: dict) -> dict:
        return {k: (v.value if hasattr(v, "value") else v) for k, v in mapping.items()}

    changes = audit.diff(_serialise(before), _serialise(fields))
    if changes:
        audit.record(
            db,
            tenant_id=tenant.id,
            actor=user,
            action="tenant.updated",
            entity_type="tenant",
            entity_id=tenant.id,
            entity_label=tenant.name,
            changes=changes,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

    db.flush()
    return _to_read(db, tenant)
