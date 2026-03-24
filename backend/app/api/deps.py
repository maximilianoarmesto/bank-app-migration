"""
Reusable FastAPI dependency functions for authentication and authorization.

This module centralises all access-control logic so that individual route
handlers import a single, named dependency rather than duplicating auth
checks.  Every access-control violation is forwarded to the audit log so
that unauthorised attempts are permanently recorded for security review.

Dependency hierarchy
--------------------
get_current_user
    └─ get_current_active_user   (rejects disabled accounts)
          └─ require_admin        (rejects non-admins)

Ownership guards
----------------
require_account_owner_or_admin(account_id)
    Builds a dependency that checks the authenticated user owns the
    requested bank account, or falls back to admin bypass.

require_self_or_admin(user_id)
    Builds a dependency that checks the authenticated user is accessing
    their own profile, or falls back to admin bypass.

Database session
----------------
All guards that log audit events accept an optional ``db`` keyword-argument
so that the audit record is persisted within the same request transaction.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_token
from app.core.audit_log import AuditEventType, log_event
from app.models.user import User
from app.models.bank_account import BankAccount

# ---------------------------------------------------------------------------
# OAuth2 token scheme
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")

# ---------------------------------------------------------------------------
# Helper: extract client context from request (for audit logging)
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    """Return the best-guess client IP from common proxy headers."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "unknown")


# ---------------------------------------------------------------------------
# Core: get_current_user
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Decode the Bearer token and return the corresponding ``User`` record.

    Raises HTTP 401 and writes an audit record when:
    - The token is missing or malformed.
    - The token cannot be verified (expired, wrong signature, etc.).
    - The ``sub`` claim does not match any user in the database.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = verify_token(token)
    if payload is None:
        log_event(
            AuditEventType.INVALID_TOKEN,
            action=f"{request.method} {request.url.path}",
            client_ip=_client_ip(request),
            user_agent=_user_agent(request),
            detail="Token verification failed",
            db=db,
        )
        db.commit()
        raise credentials_exception

    username: str | None = payload.get("sub")
    if username is None:
        log_event(
            AuditEventType.INVALID_TOKEN,
            action=f"{request.method} {request.url.path}",
            client_ip=_client_ip(request),
            user_agent=_user_agent(request),
            detail="Token missing 'sub' claim",
            db=db,
        )
        db.commit()
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        log_event(
            AuditEventType.UNAUTHORIZED_ACCESS,
            actor_username=username,
            action=f"{request.method} {request.url.path}",
            client_ip=_client_ip(request),
            user_agent=_user_agent(request),
            detail=f"No user found for username '{username}'",
            db=db,
        )
        db.commit()
        raise credentials_exception

    return user


# ---------------------------------------------------------------------------
# Active-user guard
# ---------------------------------------------------------------------------


async def get_current_active_user(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Extends ``get_current_user`` by rejecting deactivated accounts.

    Raises HTTP 403 and writes an audit record when ``user.is_active`` is
    ``False``.
    """
    if not current_user.is_active:
        log_event(
            AuditEventType.INACTIVE_USER_ACCESS,
            actor_id=current_user.id,
            actor_username=current_user.username,
            action=f"{request.method} {request.url.path}",
            client_ip=_client_ip(request),
            user_agent=_user_agent(request),
            detail="Deactivated account attempted access",
            db=db,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )
    return current_user


# ---------------------------------------------------------------------------
# Admin guard
# ---------------------------------------------------------------------------


async def require_admin(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Extends ``get_current_active_user`` by restricting access to admins only.

    Raises HTTP 403 and writes an audit record when ``user.is_admin`` is
    ``False``.
    """
    if not current_user.is_admin:
        log_event(
            AuditEventType.FORBIDDEN_ACCESS,
            actor_id=current_user.id,
            actor_username=current_user.username,
            resource="admin",
            action=f"{request.method} {request.url.path}",
            client_ip=_client_ip(request),
            user_agent=_user_agent(request),
            detail="Non-admin user attempted admin-only operation",
            db=db,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions — administrator role required",
        )
    return current_user


# ---------------------------------------------------------------------------
# Ownership guards (factory functions)
# ---------------------------------------------------------------------------


def require_account_owner_or_admin(account_id_param: str = "account_id") -> Callable:
    """
    Return a dependency that verifies the requesting user owns the bank
    account identified by ``account_id_param`` in the path, or is an admin.

    Usage::

        @router.get("/{account_id}")
        def get_account(
            account_id: int,
            db: Session = Depends(get_db),
            _: User = Depends(require_account_owner_or_admin()),
        ): ...
    """

    async def _guard(
        request: Request,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        raw_id = request.path_params.get(account_id_param)
        if raw_id is None:
            # If the path param is missing, let the route handler surface the
            # 404 itself — no ownership check is possible.
            return current_user

        try:
            account_id = int(raw_id)
        except (TypeError, ValueError):
            return current_user

        account = db.query(BankAccount).filter(BankAccount.id == account_id).first()

        if account is None:
            # 404 surfaced by the route handler; ownership check is moot.
            return current_user

        if account.owner_id != current_user.id and not current_user.is_admin:
            log_event(
                AuditEventType.FORBIDDEN_ACCESS,
                actor_id=current_user.id,
                actor_username=current_user.username,
                resource="bank_account",
                resource_id=str(account_id),
                action=f"{request.method} {request.url.path}",
                client_ip=_client_ip(request),
                user_agent=_user_agent(request),
                detail=(
                    f"User '{current_user.username}' attempted to access "
                    f"bank account {account_id} owned by user {account.owner_id}"
                ),
                db=db,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions — you do not own this account",
            )

        return current_user

    return _guard


def require_self_or_admin(user_id_param: str = "user_id") -> Callable:
    """
    Return a dependency that verifies the requesting user is accessing their
    own profile (``user_id`` matches ``current_user.id``) or is an admin.

    Usage::

        @router.get("/{user_id}")
        def get_user(
            user_id: int,
            db: Session = Depends(get_db),
            _: User = Depends(require_self_or_admin()),
        ): ...
    """

    async def _guard(
        request: Request,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        raw_id = request.path_params.get(user_id_param)
        if raw_id is None:
            return current_user

        try:
            target_user_id = int(raw_id)
        except (TypeError, ValueError):
            return current_user

        if target_user_id != current_user.id and not current_user.is_admin:
            log_event(
                AuditEventType.FORBIDDEN_ACCESS,
                actor_id=current_user.id,
                actor_username=current_user.username,
                resource="user",
                resource_id=str(target_user_id),
                action=f"{request.method} {request.url.path}",
                client_ip=_client_ip(request),
                user_agent=_user_agent(request),
                detail=(
                    f"User '{current_user.username}' (id={current_user.id}) attempted to access "
                    f"profile of user {target_user_id}"
                ),
                db=db,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions — you can only access your own profile",
            )

        return current_user

    return _guard
