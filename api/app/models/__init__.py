"""SQLAlchemy models.

Every model is imported here so that `Base.metadata` is fully populated before
Alembic inspects it. Adding a model without importing it here is the classic way
to produce a migration that silently drops a table.
"""

from app.models.audit import AuditLogEntry
from app.models.base import Base
from app.models.customer import Customer, ServiceAddress
from app.models.enums import (
    JOB_STATUS_TRANSITIONS,
    OPEN_JOB_STATUSES,
    ROLE_RANK,
    SEAT_LIMITS,
    CustomerKind,
    JobPriority,
    JobStatus,
    JobType,
    LineItemKind,
    Plan,
    Role,
    TenantStatus,
    TradeType,
)
from app.models.invitation import Invitation
from app.models.job import Job, JobAssignment, JobLineItem, JobNumberCounter
from app.models.membership import Membership
from app.models.tenant import Tenant
from app.models.user import User

__all__ = [
    "JOB_STATUS_TRANSITIONS",
    "OPEN_JOB_STATUSES",
    "ROLE_RANK",
    "SEAT_LIMITS",
    "AuditLogEntry",
    "Base",
    "Customer",
    "CustomerKind",
    "Invitation",
    "Job",
    "JobAssignment",
    "JobLineItem",
    "JobNumberCounter",
    "JobPriority",
    "JobStatus",
    "JobType",
    "LineItemKind",
    "Membership",
    "Plan",
    "Role",
    "ServiceAddress",
    "Tenant",
    "TenantStatus",
    "TradeType",
    "User",
]

# Tables that carry a tenant_id and are protected by row-level security.
# tests/test_tenant_isolation.py asserts that this list exactly matches the set
# of tables with RLS enabled in the live database -- so adding a tenant-scoped
# table without a policy fails the build.
#
# job_number_counters is in the list despite holding no customer data: its rows
# are per-tenant, and leaving it unprotected would let one tenant read another's
# job volume, which is commercially interesting information about a competitor.
RLS_TABLES: tuple[str, ...] = (
    "tenants",
    "memberships",
    "invitations",
    "audit_log",
    "customers",
    "service_addresses",
    "jobs",
    "job_assignments",
    "job_line_items",
    "job_number_counters",
)
