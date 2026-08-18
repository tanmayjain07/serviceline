"""SQLAlchemy models.

Every model is imported here so that `Base.metadata` is fully populated before
Alembic inspects it. Adding a model without importing it here is the classic way
to produce a migration that silently drops a table.
"""

from app.models.audit import AuditLogEntry
from app.models.base import Base
from app.models.enums import (
    ROLE_RANK,
    SEAT_LIMITS,
    Plan,
    Role,
    TenantStatus,
    TradeType,
)
from app.models.invitation import Invitation
from app.models.membership import Membership
from app.models.tenant import Tenant
from app.models.user import User

__all__ = [
    "ROLE_RANK",
    "SEAT_LIMITS",
    "AuditLogEntry",
    "Base",
    "Invitation",
    "Membership",
    "Plan",
    "Role",
    "Tenant",
    "TenantStatus",
    "TradeType",
    "User",
]

# Tables that carry a tenant_id and are protected by row-level security.
# tests/test_tenant_isolation.py asserts that this list exactly matches the set
# of tables with RLS enabled in the live database -- so adding a tenant-scoped
# table without a policy fails the build.
RLS_TABLES: tuple[str, ...] = (
    "tenants",
    "memberships",
    "invitations",
    "audit_log",
)
