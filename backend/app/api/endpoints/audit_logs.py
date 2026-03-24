"""
Audit log query endpoints — restricted to administrators.

Routes
------
GET  /api/audit-logs/            — Paginated, filterable audit log search.
GET  /api/audit-logs/{log_id}    — Retrieve a single audit log entry by id.
GET  /api/audit-logs/integrity   — Verify integrity hashes for a range of records.

Access-control policy
---------------------
All routes require an authenticated, active administrator (``require_admin``).
Non-admin access attempts are rejected with HTTP 403 and are themselves
written to the audit log.

Search / filter parameters
--------------------------
- ``event_type``     — Filter by exact ``AuditEventType`` value.
- ``actor_id``       — Filter by the numeric user id of the actor.
- ``actor_username`` — Case-insensitive substring match on the actor username.
- ``resource``       — Filter by exact resource name (e.g. ``"bank_account"``).
- ``resource_id``    — Filter by exact resource identifier.
- ``search``         — Full-text substring search across ``action``, ``detail``,
                       ``actor_username``, ``resource``, and ``resource_id``.
- ``from_ts``        — ISO 8601 lower bound for ``timestamp`` (inclusive).
- ``to_ts``          — ISO 8601 upper bound for ``timestamp`` (inclusive).
- ``page``           — 1-based page number (default 1).
- ``page_size``      — Records per page, 1–200 (default 50).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.audit_log import (
    AuditEventType,
    log_event,
    verify_audit_record_integrity,
)
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogEntry, AuditLogIntegrityReport, AuditLogPage
from app.api.deps import require_admin, _client_ip, _user_agent
from app.models.user import User

router = APIRouter()

# Maximum allowed page size — prevents runaway queries
_MAX_PAGE_SIZE = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_entry(row: AuditLog, *, verify_integrity: bool = False) -> AuditLogEntry:
    """Convert an ORM row to an ``AuditLogEntry`` schema, optionally running
    the integrity check and attaching the result."""
    entry = AuditLogEntry.model_validate(row)
    if verify_integrity:
        entry.integrity_valid = verify_audit_record_integrity(
            {
                "event_type": row.event_type,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "actor_id": row.actor_id,
                "actor_username": row.actor_username,
                "resource": row.resource,
                "resource_id": row.resource_id,
                "action": row.action,
                "client_ip": row.client_ip,
                "user_agent": row.user_agent,
                "detail": row.detail,
                "integrity_hash": row.integrity_hash,
            }
        )
    return entry


# ---------------------------------------------------------------------------
# GET /  — Paginated search
# ---------------------------------------------------------------------------


@router.get("/", response_model=AuditLogPage)
def search_audit_logs(
    request: Request,
    # Filters
    event_type: Optional[str] = Query(None, description="Exact AuditEventType value"),
    actor_id: Optional[int] = Query(None, description="Actor user id"),
    actor_username: Optional[str] = Query(
        None, description="Case-insensitive substring match on actor username"
    ),
    resource: Optional[str] = Query(None, description="Exact resource name"),
    resource_id: Optional[str] = Query(None, description="Exact resource id"),
    search: Optional[str] = Query(
        None,
        description="Substring search across action, detail, actor_username, resource, resource_id",
    ),
    from_ts: Optional[datetime] = Query(
        None, description="ISO 8601 lower timestamp bound (inclusive)"
    ),
    to_ts: Optional[datetime] = Query(
        None, description="ISO 8601 upper timestamp bound (inclusive)"
    ),
    # Pagination
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE, description="Records per page"),
    # Dependencies
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AuditLogPage:
    """
    Return a paginated, searchable list of audit log entries.

    Results are ordered by ``timestamp`` descending (newest first).
    Only administrators may call this endpoint.
    """
    query = db.query(AuditLog)

    # -- Exact-match filters ---------------------------------------------------
    if event_type is not None:
        # Validate against the enum to surface helpful errors
        valid_types = [e.value for e in AuditEventType]
        if event_type not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown event_type '{event_type}'. Valid values: {valid_types}",
            )
        query = query.filter(AuditLog.event_type == event_type)

    if actor_id is not None:
        query = query.filter(AuditLog.actor_id == actor_id)

    if actor_username is not None:
        query = query.filter(
            AuditLog.actor_username.ilike(f"%{actor_username}%")
        )

    if resource is not None:
        query = query.filter(AuditLog.resource == resource)

    if resource_id is not None:
        query = query.filter(AuditLog.resource_id == resource_id)

    # -- Full-text search across multiple columns ------------------------------
    if search is not None:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                AuditLog.action.ilike(pattern),
                AuditLog.detail.ilike(pattern),
                AuditLog.actor_username.ilike(pattern),
                AuditLog.resource.ilike(pattern),
                AuditLog.resource_id.ilike(pattern),
                AuditLog.client_ip.ilike(pattern),
            )
        )

    # -- Timestamp range -------------------------------------------------------
    if from_ts is not None:
        query = query.filter(AuditLog.timestamp >= from_ts)

    if to_ts is not None:
        query = query.filter(AuditLog.timestamp <= to_ts)

    # -- Count before pagination -----------------------------------------------
    total = query.count()

    # -- Order and paginate ----------------------------------------------------
    rows: List[AuditLog] = (
        query.order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    total_pages = max(1, math.ceil(total / page_size))

    # Record this access in the audit log (self-referential, intentional)
    log_event(
        AuditEventType.AUDIT_LOG_ACCESSED,
        actor_id=current_user.id,
        actor_username=current_user.username,
        resource="audit_log",
        action=f"GET {request.url.path}",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
        detail=f"search params: event_type={event_type}, actor_id={actor_id}, "
               f"actor_username={actor_username}, resource={resource}, "
               f"resource_id={resource_id}, search={search!r}, "
               f"from_ts={from_ts}, to_ts={to_ts}, page={page}, page_size={page_size}",
        db=db,
    )

    return AuditLogPage(
        data=[_row_to_entry(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# GET /integrity  — Bulk integrity verification
# ---------------------------------------------------------------------------


@router.get("/integrity", response_model=AuditLogIntegrityReport)
def verify_integrity(
    request: Request,
    from_ts: Optional[datetime] = Query(
        None, description="ISO 8601 lower timestamp bound (inclusive)"
    ),
    to_ts: Optional[datetime] = Query(
        None, description="ISO 8601 upper timestamp bound (inclusive)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AuditLogIntegrityReport:
    """
    Verify the HMAC-SHA256 integrity hashes of all audit log records within
    the optional timestamp window.

    Returns a summary report including the ids of any records whose stored
    hash does not match a freshly-computed digest — a non-empty ``failed_ids``
    list is a strong indicator of tampering or data corruption.

    Accessing this endpoint is itself logged as an ``AUDIT_LOG_ACCESSED``
    event.
    """
    query = db.query(AuditLog)

    if from_ts is not None:
        query = query.filter(AuditLog.timestamp >= from_ts)
    if to_ts is not None:
        query = query.filter(AuditLog.timestamp <= to_ts)

    rows: List[AuditLog] = query.order_by(AuditLog.timestamp.asc()).all()

    passed = 0
    failed_ids: List[int] = []

    for row in rows:
        valid = verify_audit_record_integrity(
            {
                "event_type": row.event_type,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "actor_id": row.actor_id,
                "actor_username": row.actor_username,
                "resource": row.resource,
                "resource_id": row.resource_id,
                "action": row.action,
                "client_ip": row.client_ip,
                "user_agent": row.user_agent,
                "detail": row.detail,
                "integrity_hash": row.integrity_hash,
            }
        )
        if valid:
            passed += 1
        else:
            failed_ids.append(row.id)
            # Emit a high-severity audit event for each tampered record
            log_event(
                AuditEventType.AUDIT_INTEGRITY_FAILURE,
                actor_id=current_user.id,
                actor_username=current_user.username,
                resource="audit_log",
                resource_id=str(row.id),
                action=f"GET {request.url.path}",
                client_ip=_client_ip(request),
                user_agent=_user_agent(request),
                detail=f"Integrity hash mismatch for audit_log row id={row.id}",
                db=db,
            )

    log_event(
        AuditEventType.AUDIT_LOG_ACCESSED,
        actor_id=current_user.id,
        actor_username=current_user.username,
        resource="audit_log",
        action=f"GET {request.url.path}",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
        detail=f"Integrity check: {passed} passed, {len(failed_ids)} failed",
        db=db,
    )

    return AuditLogIntegrityReport(
        total_checked=len(rows),
        passed=passed,
        failed=len(failed_ids),
        all_valid=len(failed_ids) == 0,
        failed_ids=failed_ids,
    )


# ---------------------------------------------------------------------------
# GET /{log_id}  — Single record retrieval
# ---------------------------------------------------------------------------


@router.get("/{log_id}", response_model=AuditLogEntry)
def get_audit_log_entry(
    request: Request,
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> AuditLogEntry:
    """
    Return a single audit log entry by its database id.

    The response includes ``integrity_valid`` — ``True`` when the stored
    HMAC-SHA256 hash matches a freshly-computed digest of the row's fields.

    Only administrators may call this endpoint.
    """
    row = db.query(AuditLog).filter(AuditLog.id == log_id).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit log entry {log_id} not found",
        )

    log_event(
        AuditEventType.AUDIT_LOG_ACCESSED,
        actor_id=current_user.id,
        actor_username=current_user.username,
        resource="audit_log",
        resource_id=str(log_id),
        action=f"GET {request.url.path}",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
        db=db,
    )

    return _row_to_entry(row, verify_integrity=True)
