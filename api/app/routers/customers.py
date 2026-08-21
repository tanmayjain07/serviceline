"""Customers and their service addresses."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import bad_request, not_found
from app.deps import (
    Principal,
    client_ip,
    get_current_user,
    get_db,
    get_principal,
    require_role,
)
from app.models import (
    Customer,
    Job,
    Membership,
    Role,
    ServiceAddress,
    Tenant,
    User,
)
from app.models.enums import OPEN_JOB_STATUSES
from app.schemas.common import Page
from app.schemas.customer import (
    CustomerCreate,
    CustomerDetail,
    CustomerRead,
    CustomerUpdate,
    ServiceAddressCreate,
    ServiceAddressRead,
    ServiceAddressUpdate,
)
from app.services import audit

router = APIRouter(prefix="/customers", tags=["customers"])

# Customers are a dispatcher's working data. Technicians see the customer only
# through a job they are assigned to, never the whole book -- which is also a
# competitive concern: a technician who leaves should not be able to export the
# customer list on their way out.
MANAGE = require_role(Role.OWNER, Role.DISPATCHER)
VIEW = require_role(Role.OWNER, Role.DISPATCHER, Role.ACCOUNTANT)


def _tenant_default_timezone(db: Session, tenant_id: uuid.UUID) -> str:
    tenant = db.get(Tenant, tenant_id)
    return tenant.timezone if tenant else "America/New_York"


def _detail(db: Session, customer: Customer) -> CustomerDetail:
    result = CustomerDetail.model_validate(customer)
    result.addresses = [
        ServiceAddressRead.model_validate(a) for a in customer.addresses if a.is_active
    ]
    result.open_job_count = (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.customer_id == customer.id, Job.status.in_(OPEN_JOB_STATUSES))
        )
        or 0
    )
    return result


def _load(db: Session, customer_id: uuid.UUID) -> Customer:
    customer = db.scalars(
        select(Customer)
        .where(Customer.id == customer_id)
        .options(selectinload(Customer.addresses))
    ).one_or_none()
    # Row-level security means another tenant's customer is simply not here.
    # 404 rather than 403: confirming the row exists would leak that it does.
    if customer is None:
        raise not_found("Customer")
    return customer


@router.get("", response_model=Page[CustomerRead])
def list_customers(
    search: str | None = Query(default=None, max_length=120),
    include_inactive: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _view: Membership = Depends(VIEW),
    db: Session = Depends(get_db),
) -> Page[CustomerRead]:
    """Search by name, phone, or street.

    Note the absence of a tenant filter. The database applies it, which is the
    whole point of the milestone 1 design: a forgotten clause here would return
    nothing rather than everything.
    """
    statement = select(Customer)
    if not include_inactive:
        statement = statement.where(Customer.is_active.is_(True))

    if search:
        term = f"%{search.strip()}%"
        # Matching the address means a subquery rather than a join, so a
        # customer with three matching addresses still appears once.
        address_match = (
            select(ServiceAddress.customer_id)
            .where(ServiceAddress.line1.ilike(term))
            .scalar_subquery()
        )
        statement = statement.where(
            or_(
                Customer.name.ilike(term),
                Customer.phone.ilike(term),
                Customer.contact_name.ilike(term),
                Customer.id.in_(address_match),
            )
        )

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(Customer.name).limit(limit).offset(offset)
    ).unique()

    return Page[CustomerRead](
        items=[CustomerRead.model_validate(c) for c in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=CustomerDetail, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    request: Request,
    _manage: Membership = Depends(MANAGE),
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CustomerDetail:
    assert principal.tenant_id is not None

    customer = Customer(
        tenant_id=principal.tenant_id,
        kind=payload.kind,
        name=payload.name.strip(),
        contact_name=payload.contact_name,
        phone=payload.phone,
        email=str(payload.email) if payload.email else None,
        notes=payload.notes,
    )
    db.add(customer)
    db.flush()

    if payload.address is not None:
        db.add(
            ServiceAddress(
                tenant_id=principal.tenant_id,
                customer_id=customer.id,
                label=payload.address.label,
                line1=payload.address.line1,
                line2=payload.address.line2,
                city=payload.address.city,
                state=payload.address.state,
                postal_code=payload.address.postal_code,
                timezone=payload.address.timezone
                or _tenant_default_timezone(db, principal.tenant_id),
                notes=payload.address.notes,
                # The first address is the primary one whatever the caller says:
                # a customer with addresses but no primary is a broken state the
                # UI would then have to handle everywhere.
                is_primary=True,
            )
        )
        db.flush()

    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor=user,
        action="customer.created",
        entity_type="customer",
        entity_id=customer.id,
        entity_label=customer.name,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    db.refresh(customer)
    return _detail(db, customer)


@router.get("/{customer_id}", response_model=CustomerDetail)
def read_customer(
    customer_id: uuid.UUID,
    _view: Membership = Depends(VIEW),
    db: Session = Depends(get_db),
) -> CustomerDetail:
    return _detail(db, _load(db, customer_id))


@router.patch("/{customer_id}", response_model=CustomerDetail)
def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    request: Request,
    _manage: Membership = Depends(MANAGE),
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CustomerDetail:
    assert principal.tenant_id is not None
    customer = _load(db, customer_id)

    fields = payload.model_dump(exclude_unset=True)
    before = {k: getattr(customer, k) for k in fields}
    for key, value in fields.items():
        setattr(customer, key, str(value) if key == "email" and value else value)

    changes = audit.diff(
        {k: (v.value if hasattr(v, "value") else v) for k, v in before.items()},
        {
            k: (
                getattr(customer, k).value
                if hasattr(getattr(customer, k), "value")
                else getattr(customer, k)
            )
            for k in fields
        },
    )
    if changes:
        db.flush()
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor=user,
            action="customer.updated",
            entity_type="customer",
            entity_id=customer.id,
            entity_label=customer.name,
            changes=changes,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

    return _detail(db, customer)


@router.post(
    "/{customer_id}/addresses",
    response_model=ServiceAddressRead,
    status_code=status.HTTP_201_CREATED,
)
def add_address(
    customer_id: uuid.UUID,
    payload: ServiceAddressCreate,
    request: Request,
    _manage: Membership = Depends(MANAGE),
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ServiceAddressRead:
    assert principal.tenant_id is not None
    customer = _load(db, customer_id)

    existing = [a for a in customer.addresses if a.is_active]
    make_primary = payload.is_primary or not existing
    if make_primary:
        for address in existing:
            address.is_primary = False
        db.flush()

    address = ServiceAddress(
        tenant_id=principal.tenant_id,
        customer_id=customer.id,
        label=payload.label,
        line1=payload.line1,
        line2=payload.line2,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
        timezone=payload.timezone or _tenant_default_timezone(db, principal.tenant_id),
        notes=payload.notes,
        is_primary=make_primary,
    )
    db.add(address)
    db.flush()

    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor=user,
        action="address.created",
        entity_type="service_address",
        entity_id=address.id,
        entity_label=address.one_line,
        changes={"timezone": address.timezone},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ServiceAddressRead.model_validate(address)


@router.patch(
    "/{customer_id}/addresses/{address_id}", response_model=ServiceAddressRead
)
def update_address(
    customer_id: uuid.UUID,
    address_id: uuid.UUID,
    payload: ServiceAddressUpdate,
    request: Request,
    _manage: Membership = Depends(MANAGE),
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ServiceAddressRead:
    assert principal.tenant_id is not None
    customer = _load(db, customer_id)

    address = next((a for a in customer.addresses if a.id == address_id), None)
    if address is None:
        raise not_found("Service address")

    fields = payload.model_dump(exclude_unset=True)
    before = {k: getattr(address, k) for k in fields}

    if fields.get("is_primary"):
        for other in customer.addresses:
            if other.id != address.id:
                other.is_primary = False
        db.flush()

    if fields.get("is_active") is False and address.is_primary:
        raise bad_request(
            "That is the customer's primary address. Make another address "
            "primary before deactivating this one."
        )

    for key, value in fields.items():
        setattr(address, key, value)
    db.flush()

    changes = audit.diff(before, {k: getattr(address, k) for k in fields})
    if changes:
        audit.record(
            db,
            tenant_id=principal.tenant_id,
            actor=user,
            action="address.updated",
            entity_type="service_address",
            entity_id=address.id,
            entity_label=address.one_line,
            changes=changes,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

    # A timezone change moves every future appointment at this address, so the
    # stored UTC windows have to be rebuilt. Doing it here rather than leaving
    # it to a nightly job means the dispatch board is never briefly wrong.
    if "timezone" in fields:
        from app.services import scheduling

        jobs = db.scalars(
            select(Job).where(
                Job.service_address_id == address.id,
                Job.status.in_(OPEN_JOB_STATUSES),
            )
        ).unique()
        for job in jobs:
            scheduling.recompute_window(db, job)

    return ServiceAddressRead.model_validate(address)
