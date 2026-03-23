"""
Audit logging module for security-relevant events.

Every unauthorized access attempt is recorded here so that security teams
can review suspicious activity.  Entries are written to the application
logger under the "audit" component name and also held in memory so that
integration tests can inspect them without requiring a live log sink.

Design decisions
----------------
- Pure Python, no extra dependencies.
- Thread-safe append-only in-memory store (suitable for testing / single-worker).
- Production deployments should configure a log aggregator (ELK, Splunk, etc.)
  to capture the structured JSON emitted by the ``security_audit`` logger.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List
from dataclasses import dataclass, field, asdict

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
    """Taxonomy of security-relevant events captured by the audit log."""

    # Authentication
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    LOGOUT = "LOGOUT"
    TOKEN_REFRESH = "TOKEN_REFRESH"
    INVALID_TOKEN = "INVALID_TOKEN"

    # Authorization failures
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"
    FORBIDDEN_ACCESS = "FORBIDDEN_ACCESS"   # authenticated but wrong role/ownership
    INACTIVE_USER_ACCESS = "INACTIVE_USER_ACCESS"

    # Sensitive operations
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    ACCOUNT_CREATED = "ACCOUNT_CREATED"
    ACCOUNT_UPDATED = "ACCOUNT_UPDATED"
    ACCOUNT_DELETED = "ACCOUNT_DELETED"


# ---------------------------------------------------------------------------
# Audit record
# ---------------------------------------------------------------------------


@dataclass
class AuditRecord:
    """Immutable record of a single security-relevant event."""

    event_type: AuditEventType
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Who
    actor_id: Optional[int] = None       # user.id performing the action
    actor_username: Optional[str] = None

    # What / where
    resource: Optional[str] = None       # e.g. "bank_account", "user"
    resource_id: Optional[str] = None    # e.g. the account id
    action: Optional[str] = None         # e.g. "GET /bank-accounts/42"

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
    """Return a snapshot of all audit records collected so far."""
    return list(_audit_records)


def clear_audit_records() -> None:
    """Flush the in-memory store.  Intended for use in tests only."""
    _audit_records.clear()


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
) -> AuditRecord:
    """
    Record a security-relevant event and emit it to the security audit logger.

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
        Additional human-readable context (e.g. the validation error message).

    Returns
    -------
    AuditRecord
        The record that was stored.
    """
    record = AuditRecord(
        event_type=event_type,
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

    # Emit to the structured security-audit logger.  Unauthorized / forbidden
    # events are logged at WARNING; authentication failures at ERROR.
    log_message = record.to_json()

    if event_type in (
        AuditEventType.LOGIN_FAILURE,
        AuditEventType.INVALID_TOKEN,
        AuditEventType.INACTIVE_USER_ACCESS,
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
