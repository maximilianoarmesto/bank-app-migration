"""
Audit logging module for security-relevant and business-relevant events.

Every unauthorized access attempt, authentication event, and sensitive data
mutation is recorded here so that security teams can review suspicious
activity and administrators can perform thorough transaction and account
audits.

Storage strategy
----------------
- **Persistent**: each event is written to the ``audit_logs`` database table
  via SQLAlchemy.  Rows are append-only — the application never issues UPDATE
  or DELETE against this table.
- **In-memory cache**: events are also appended to ``_audit_records`` for
  fast in-process inspection (tests, same-request correlation).
- **Structured logger**: every event is emitted to the ``security_audit``
  Python logger so that log-aggregators (ELK, Splunk, etc.) can capture the
  JSON payload independently of the database.

Tamper-resistance
-----------------
Each persisted row carries an ``integrity_hash``: an HMAC-SHA256 digest
computed over a canonical JSON representation of the row's immutable fields
(event_type, timestamp, actor_id, actor_username, resource, resource_id,
action, client_ip, user_agent, detail).  Any direct-database edit that
changes these fields without recalculating the hash will be detected by
``verify_audit_record_integrity``.

The HMAC key is derived from ``settings.secret_key`` so that the same
application secret that signs JWTs also protects audit records.  Rotating
the key invalidates existing hashes (i.e. previously-stored records will
fail verification until the old key is used for verification), which is
an acceptable trade-off for a single-key setup — production deployments
should use a dedicated, separately-rotated audit HMAC key stored as a
secret.

Thread / multi-worker safety
----------------------------
- The in-memory ``_audit_records`` list is fine for single-worker deployments
  and tests.  For multi-worker production deployments the database is the
  canonical store; ``get_audit_records()`` should be replaced with a DB
  query.
- ``log_event`` accepts an optional ``db`` parameter.  When provided, the
  record is written to the database *and* the in-memory list.  When omitted
  (backward-compatible, test-friendly), only the in-memory list is updated.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from dataclasses import dataclass, field, asdict

from sqlalchemy.orm import Session

from app.core.config import settings

# ---------------------------------------------------------------------------
# Logger configuration
# ---------------------------------------------------------------------------

security_audit_logger = logging.getLogger("security_audit")

if not security_audit_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
    )
    security_audit_logger.addHandler(_handler)
    security_audit_logger.setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class AuditEventType(str, Enum):
    """Taxonomy of security-relevant and business-relevant events."""

    # Authentication
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    LOGOUT = "LOGOUT"
    TOKEN_REFRESH = "TOKEN_REFRESH"
    INVALID_TOKEN = "INVALID_TOKEN"

    # Authorization failures
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"
    FORBIDDEN_ACCESS = "FORBIDDEN_ACCESS"    # authenticated but wrong role/ownership
    INACTIVE_USER_ACCESS = "INACTIVE_USER_ACCESS"

    # User operations
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"

    # Account operations
    ACCOUNT_CREATED = "ACCOUNT_CREATED"
    ACCOUNT_UPDATED = "ACCOUNT_UPDATED"
    ACCOUNT_DELETED = "ACCOUNT_DELETED"

    # Transaction operations
    TRANSACTION_CREATED = "TRANSACTION_CREATED"
    TRANSACTION_UPDATED = "TRANSACTION_UPDATED"

    # Audit-specific
    AUDIT_LOG_ACCESSED = "AUDIT_LOG_ACCESSED"
    AUDIT_INTEGRITY_FAILURE = "AUDIT_INTEGRITY_FAILURE"


# ---------------------------------------------------------------------------
# In-process audit record (dataclass — no DB dependency)
# ---------------------------------------------------------------------------


@dataclass
class AuditRecord:
    """In-process representation of a single audit event."""

    event_type: AuditEventType
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Who
    actor_id: Optional[int] = None
    actor_username: Optional[str] = None

    # What / where
    resource: Optional[str] = None
    resource_id: Optional[str] = None
    action: Optional[str] = None

    # Network context
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None

    # Free-form diagnostic detail
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# In-memory store (test-friendly, append-only)
# ---------------------------------------------------------------------------

_audit_records: List[AuditRecord] = []


def get_audit_records() -> List[AuditRecord]:
    """Return a snapshot of all in-memory audit records collected so far."""
    return list(_audit_records)


def clear_audit_records() -> None:
    """Flush the in-memory store.  Intended for use in tests only."""
    _audit_records.clear()


# ---------------------------------------------------------------------------
# Integrity / HMAC helpers
# ---------------------------------------------------------------------------

_CANONICAL_FIELDS = (
    "event_type",
    "timestamp",
    "actor_id",
    "actor_username",
    "resource",
    "resource_id",
    "action",
    "client_ip",
    "user_agent",
    "detail",
)


def _compute_integrity_hash(fields: dict) -> str:
    """
    Compute an HMAC-SHA256 digest over the canonical JSON representation of
    the given *fields* mapping.

    The canonical form sorts keys alphabetically and uses ``default=str``
    for any non-JSON-serialisable values (e.g. ``Decimal``, ``datetime``).
    """
    canonical = json.dumps(
        {k: fields.get(k) for k in sorted(_CANONICAL_FIELDS)},
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    key = settings.secret_key.encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def verify_audit_record_integrity(record_dict: dict) -> bool:
    """
    Return ``True`` if the ``integrity_hash`` stored in *record_dict* matches
    a freshly-computed digest of the same fields.

    Parameters
    ----------
    record_dict:
        A plain dictionary representation of a persisted ``AuditLog`` row,
        as returned by ``AuditLog.__dict__`` or a Pydantic schema's
        ``model_dump()``.
    """
    stored_hash: Optional[str] = record_dict.get("integrity_hash")
    if not stored_hash:
        return False
    expected = _compute_integrity_hash(record_dict)
    return hmac.compare_digest(stored_hash, expected)


# ---------------------------------------------------------------------------
# Persist to database
# ---------------------------------------------------------------------------


def _persist_to_db(record: AuditRecord, integrity_hash: str, db: Session) -> None:
    """Write *record* to the ``audit_logs`` table.

    Imported lazily to avoid a circular import at module load time.
    """
    # Late import to avoid circular dependency: audit_log ← models ← database ← audit_log
    from app.models.audit_log import AuditLog  # noqa: PLC0415

    row = AuditLog(
        event_type=record.event_type.value,
        timestamp=datetime.fromisoformat(record.timestamp),
        actor_id=record.actor_id,
        actor_username=record.actor_username,
        resource=record.resource,
        resource_id=record.resource_id,
        action=record.action,
        client_ip=record.client_ip,
        user_agent=record.user_agent,
        detail=record.detail,
        integrity_hash=integrity_hash,
    )
    db.add(row)
    # Flush so the row gets a PK but don't commit — let the caller control the
    # transaction boundary.  If the outer transaction rolls back, the audit
    # row rolls back too (acceptable — the operation itself didn't complete).
    db.flush()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_event(
    event_type: AuditEventType,
    *,
    actor_id: Optional[int] = None,
    actor_username: Optional[str] = None,
    resource: Optional[str] = None,
    resource_id: Optional[str] = None,
    action: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    detail: Optional[str] = None,
    db: Optional[Session] = None,
) -> AuditRecord:
    """
    Record a security- or business-relevant event.

    The event is:

    1. Appended to the in-memory ``_audit_records`` list.
    2. Persisted to the ``audit_logs`` database table when *db* is provided.
    3. Emitted to the ``security_audit`` Python logger.

    Parameters
    ----------
    event_type:
        One of ``AuditEventType`` describing what happened.
    actor_id:
        Database ID of the authenticated user performing the action,
        or ``None`` for unauthenticated requests.
    actor_username:
        Username of the authenticated user, or ``None``.
    resource:
        Logical resource being accessed (e.g. ``"bank_account"``).
    resource_id:
        Identifier of the specific resource instance.
    action:
        HTTP method + path of the attempted operation.
    client_ip:
        IP address of the requesting client.
    user_agent:
        User-Agent header value.
    detail:
        Additional human-readable context.
    db:
        Optional SQLAlchemy session.  When provided the record is also
        persisted to the database.

    Returns
    -------
    AuditRecord
        The in-memory record that was created.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    record = AuditRecord(
        event_type=event_type,
        timestamp=timestamp,
        actor_id=actor_id,
        actor_username=actor_username,
        resource=resource,
        resource_id=resource_id,
        action=action,
        client_ip=client_ip,
        user_agent=user_agent,
        detail=detail,
    )

    _audit_records.append(record)

    # Compute integrity hash over the canonical fields
    integrity_hash = _compute_integrity_hash(record.to_dict())

    # Persist to database if a session was provided
    if db is not None:
        try:
            _persist_to_db(record, integrity_hash, db)
        except Exception:  # noqa: BLE001 — never let audit failure crash the request
            security_audit_logger.exception(
                "audit_log: failed to persist event %s to database", event_type
            )

    # Emit to the structured security-audit logger
    log_message = record.to_json()

    if event_type in (
        AuditEventType.LOGIN_FAILURE,
        AuditEventType.INVALID_TOKEN,
        AuditEventType.INACTIVE_USER_ACCESS,
        AuditEventType.AUDIT_INTEGRITY_FAILURE,
    ):
        security_audit_logger.error(log_message)
    elif event_type in (
        AuditEventType.UNAUTHORIZED_ACCESS,
        AuditEventType.FORBIDDEN_ACCESS,
    ):
        security_audit_logger.warning(log_message)
    else:
        security_audit_logger.info(log_message)

    return record
