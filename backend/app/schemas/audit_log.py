"""
Pydantic schemas for the audit log API.

Includes:
- ``AuditLogEntry`` — the read schema for a persisted audit log row.
- ``AuditLogSearchParams`` — validated query parameters for the search endpoint.
- ``AuditLogPage`` — paginated response envelope.
- ``AuditLogIntegrityReport`` — result of an integrity-check run.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class AuditLogEntry(BaseModel):
    """Serialised representation of a single ``AuditLog`` database row."""

    id: int
    event_type: str
    timestamp: datetime

    actor_id: Optional[int] = None
    actor_username: Optional[str] = None

    resource: Optional[str] = None
    resource_id: Optional[str] = None
    action: Optional[str] = None

    client_ip: Optional[str] = None
    user_agent: Optional[str] = None

    detail: Optional[str] = None

    # Integrity hash is exposed so that API consumers can perform their own
    # offline verification if they choose to mirror the audit log.
    integrity_hash: str

    # Computed at query time by the endpoint — not stored in the DB.
    integrity_valid: Optional[bool] = None

    class Config:
        from_attributes = True


class AuditLogPage(BaseModel):
    """Paginated list of audit log entries."""

    data: List[AuditLogEntry]
    total: int
    page: int
    page_size: int
    total_pages: int


class AuditLogIntegrityReport(BaseModel):
    """Summary of an integrity verification run over a set of audit records."""

    total_checked: int
    passed: int
    failed: int
    all_valid: bool
    failed_ids: List[int] = Field(default_factory=list)
