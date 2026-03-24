"""
Persistent audit log model.

Each row represents one security- or business-relevant event.  The
``integrity_hash`` column stores an HMAC-SHA256 digest of the record's
immutable fields so that any tampering (direct DB edit) can be detected at
query time.

Design decisions
----------------
- Append-only: rows are never updated or deleted through the application.
- ``integrity_hash`` is computed over a canonical JSON representation of the
  immutable fields and stored alongside the row for offline verification.
- The ``actor_*`` columns record a *snapshot* of the user's identity at the
  time of the event — they are not foreign keys so that deleting a user does
  not cascade-delete their audit trail.
"""

from __future__ import annotations

from sqlalchemy import Column, Integer, String, DateTime, Index
from sqlalchemy.sql import func

from app.core.database import Base


class AuditLog(Base):
    """Persistent, append-only record of a security- or business-relevant event."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    # What happened
    event_type = Column(String, nullable=False, index=True)

    # When
    timestamp = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Who performed the action (snapshot — not a FK)
    actor_id = Column(Integer, nullable=True, index=True)
    actor_username = Column(String, nullable=True, index=True)

    # What resource was affected
    resource = Column(String, nullable=True, index=True)
    resource_id = Column(String, nullable=True, index=True)
    action = Column(String, nullable=True)

    # Network context
    client_ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    # Free-form diagnostic detail
    detail = Column(String, nullable=True)

    # Tamper-evidence: HMAC-SHA256 over canonical JSON of the immutable fields
    integrity_hash = Column(String, nullable=False)

    # Composite indices for the most common search patterns
    __table_args__ = (
        Index("ix_audit_logs_event_type_timestamp", "event_type", "timestamp"),
        Index("ix_audit_logs_actor_id_timestamp", "actor_id", "timestamp"),
        Index("ix_audit_logs_resource_resource_id", "resource", "resource_id"),
    )
