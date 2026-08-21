"""Customers and the addresses work is performed at."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import CustomerKind

if TYPE_CHECKING:
    from app.models.job import Job


class Customer(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "customers"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[CustomerKind] = mapped_column(
        Enum(CustomerKind, native_enum=False, length=20, validate_strings=True),
        nullable=False,
        default=CustomerKind.RESIDENTIAL,
    )

    # For a company this is the trading name; for a household, the family name.
    # One field rather than first/last because dispatchers type whatever the
    # customer calls themselves, and splitting it invites arguments about
    # "Mr and Mrs Whitcomb".
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Customers are deactivated, never deleted: their service history has to
    # outlive the relationship.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    addresses: Mapped[list[ServiceAddress]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="ServiceAddress.created_at",
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="customer")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Customer {self.name!r}>"


class ServiceAddress(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "service_addresses"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # "Main office", "Unit 4", "Rear workshop". Optional -- most residential
    # customers have exactly one address and no name for it.
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    line1: Mapped[str] = mapped_column(String(200), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(60), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)

    # THE authoritative timezone for anything scheduled at this address.
    #
    # It lives here rather than on the tenant because one target contractor
    # works northwest Ohio and across the Indiana line, and half of Indiana
    # observes Central time. A company-level timezone would quietly tell a
    # customer the wrong arrival hour, and the first anyone would hear of it is
    # a technician turning up an hour late.
    #
    # tenants.timezone is only the default offered when creating a new address.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    customer: Mapped[Customer] = relationship(back_populates="addresses")
    jobs: Mapped[list[Job]] = relationship(back_populates="service_address")

    @property
    def one_line(self) -> str:
        parts = [self.line1, self.line2, self.city, f"{self.state} {self.postal_code}"]
        return ", ".join(p for p in parts if p)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ServiceAddress {self.one_line!r} tz={self.timezone}>"
