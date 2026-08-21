"""Database engine, session factory, and RLS context binding.

The single most important thing in this file is `bind_context`. Read the notes
below before changing anything here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Postgres GUCs (transaction-scoped settings) that our RLS policies read.
TENANT_GUC = "app.tenant_id"
USER_GUC = "app.user_id"
INVITE_TOKEN_GUC = "app.invite_token_hash"

engine = create_engine(
    settings.database_url,
    # Pin the session timezone to UTC.
    #
    # timestamptz columns are stored as instants, but psycopg renders them on
    # read using the *session's* timezone -- which defaults to the server's
    # local zone. Without this, the same API returns "2026-08-14T12:00:00+00:00"
    # when deployed in London and "2026-08-14T17:30:00+05:30" on a laptop in
    # India. Same instant, different string, and any client comparing them as
    # text is wrong.
    connect_args={"options": "-c timezone=utc"},
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=settings.sql_echo,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def _set_local(session: Session, key: str, value: str) -> None:
    """`SET LOCAL`, in a form that accepts bind parameters.

    Two properties of `set_config(key, value, is_local => true)` matter:

    1. It is scoped to the current transaction. On COMMIT or ROLLBACK the value
       is discarded, which is what makes this safe under connection pooling: a
       pooled connection can never carry one tenant's context into the next
       request. (SQLAlchemy also issues a ROLLBACK when a connection returns to
       the pool -- a second, independent line of defence.)

    2. Because it is transaction-scoped, a COMMIT in the middle of a request
       would silently clear it, leaving later queries unscoped. That is why
       request handlers in this codebase never commit; the `db` dependency owns
       the single transaction boundary. See docs/architecture.md, ADR-003.
    """
    session.execute(
        text("SELECT set_config(:key, :value, true)"), {"key": key, "value": value}
    )


def bind_context(
    session: Session,
    *,
    user_id: uuid.UUID | str | None = None,
    tenant_id: uuid.UUID | str | None = None,
) -> None:
    """Bind the current transaction to a user and/or a tenant.

    `tenant_id` drives tenant isolation: every tenant-scoped table's policy
    compares its `tenant_id` column to this value.

    `user_id` exists for exactly one case -- reading your own memberships
    *across* tenants, which login and the company switcher have to do before any
    tenant has been chosen. Without it, login could not discover which companies
    you belong to without a privileged role, and adding a privileged role would
    weaken every other query in the system.
    """
    if user_id is not None:
        _set_local(session, USER_GUC, str(user_id))
    if tenant_id is not None:
        _set_local(session, TENANT_GUC, str(tenant_id))


def bind_invite_token(session: Session, token_hash: str) -> None:
    """Bind an invitation token hash to the current transaction.

    Accepting an invitation is the one flow where a user legitimately needs to
    read a row belonging to a tenant they are not yet a member of. Rather than
    punching a BYPASSRLS hole that would then exist for every query, we widen
    access by exactly one row: the invitation whose token hash the caller can
    already produce. Knowledge of the token is the authorisation.
    """
    _set_local(session, INVITE_TOKEN_GUC, token_hash)


def current_tenant(session: Session) -> str | None:
    """Return the tenant bound to this transaction, or None. Used by tests."""
    value = session.execute(
        text("SELECT current_setting(:key, true)"), {"key": TENANT_GUC}
    ).scalar()
    return value or None


@contextmanager
def session_scope(
    tenant_id: uuid.UUID | str | None = None,
    user_id: uuid.UUID | str | None = None,
) -> Iterator[Session]:
    """Transactional session scope for scripts, seeds, and background jobs.

    Request handling does not use this -- see app/deps.py.
    """
    session = SessionLocal()
    try:
        bind_context(session, user_id=user_id, tenant_id=tenant_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
