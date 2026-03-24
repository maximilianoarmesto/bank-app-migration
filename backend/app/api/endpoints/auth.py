"""
Authentication endpoints.

Routes
------
POST /api/auth/token    — Exchange username + password for an access + refresh token pair.
POST /api/auth/refresh  — Exchange a valid refresh token for a new token pair.
POST /api/auth/logout   — Invalidate the current access token (server-side blacklist).
GET  /api/auth/me       — Return the currently authenticated user's profile.

All authentication events (success and failure) are recorded in the audit log
so that security teams can review brute-force attempts and anomalous patterns.
Where a database session is available, the record is persisted to the
``audit_logs`` table.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    verify_password,
    verify_refresh_token,
    create_access_token,
    create_refresh_token,
    TOKEN_TYPE_ACCESS,
)
from app.core.config import settings
from app.core.audit_log import AuditEventType, log_event
from app.models.user import User
from app.schemas.auth import Token, TokenRefreshRequest
from app.schemas.user import User as UserSchema
from app.api.deps import (
    get_current_user,
    get_current_active_user,
    _client_ip,
    _user_agent,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory token blacklist (logout / revocation)
# ---------------------------------------------------------------------------
# In production replace with a Redis SET or a DB table for multi-worker safety.

_token_blacklist: set[str] = set()


def revoke_token(token: str) -> None:
    """Add *token* to the blacklist so it is rejected on future requests."""
    _token_blacklist.add(token)


def is_token_revoked(token: str) -> bool:
    """Return ``True`` if *token* has been explicitly revoked."""
    return token in _token_blacklist


# ---------------------------------------------------------------------------
# Helper: extract raw Bearer token from the Authorization header
# ---------------------------------------------------------------------------


def _extract_bearer(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:]
    return None


# ---------------------------------------------------------------------------
# POST /token  — Login
# ---------------------------------------------------------------------------


@router.post("/token", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """
    Authenticate with username and password.

    Returns both an access token (short-lived) and a refresh token
    (long-lived) on success.  Any failure is written to the audit log.
    """
    ip = _client_ip(request)
    ua = _user_agent(request)

    user = db.query(User).filter(User.username == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        log_event(
            AuditEventType.LOGIN_FAILURE,
            actor_username=form_data.username,
            action="POST /api/auth/token",
            client_ip=ip,
            user_agent=ua,
            detail="Invalid username or password",
            db=db,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        log_event(
            AuditEventType.INACTIVE_USER_ACCESS,
            actor_id=user.id,
            actor_username=user.username,
            action="POST /api/auth/token",
            client_ip=ip,
            user_agent=ua,
            detail="Disabled account attempted login",
            db=db,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh_token = create_refresh_token(data={"sub": user.username})

    log_event(
        AuditEventType.LOGIN_SUCCESS,
        actor_id=user.id,
        actor_username=user.username,
        action="POST /api/auth/token",
        client_ip=ip,
        user_agent=ua,
        db=db,
    )
    db.commit()

    return Token(
        access_token=access_token,
        token_type="bearer",
        refresh_token=refresh_token,
    )


# ---------------------------------------------------------------------------
# POST /refresh  — Token refresh
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    body: TokenRefreshRequest,
    db: Session = Depends(get_db),
) -> Token:
    """
    Exchange a valid refresh token for a new access + refresh token pair.

    The old refresh token is revoked (single-use rotation).
    """
    ip = _client_ip(request)
    ua = _user_agent(request)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if is_token_revoked(body.refresh_token):
        log_event(
            AuditEventType.INVALID_TOKEN,
            action="POST /api/auth/refresh",
            client_ip=ip,
            user_agent=ua,
            detail="Revoked refresh token reuse attempt",
            db=db,
        )
        db.commit()
        raise credentials_exception

    payload = verify_refresh_token(body.refresh_token)
    if payload is None:
        log_event(
            AuditEventType.INVALID_TOKEN,
            action="POST /api/auth/refresh",
            client_ip=ip,
            user_agent=ua,
            detail="Refresh token verification failed",
            db=db,
        )
        db.commit()
        raise credentials_exception

    username: str | None = payload.get("sub")
    if username is None:
        log_event(
            AuditEventType.INVALID_TOKEN,
            action="POST /api/auth/refresh",
            client_ip=ip,
            user_agent=ua,
            detail="Refresh token missing 'sub' claim",
            db=db,
        )
        db.commit()
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        log_event(
            AuditEventType.UNAUTHORIZED_ACCESS,
            actor_username=username,
            action="POST /api/auth/refresh",
            client_ip=ip,
            user_agent=ua,
            detail="User not found or inactive during token refresh",
            db=db,
        )
        db.commit()
        raise credentials_exception

    # Revoke the consumed refresh token (rotation).
    revoke_token(body.refresh_token)

    new_access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    new_refresh_token = create_refresh_token(data={"sub": user.username})

    log_event(
        AuditEventType.TOKEN_REFRESH,
        actor_id=user.id,
        actor_username=user.username,
        action="POST /api/auth/refresh",
        client_ip=ip,
        user_agent=ua,
        db=db,
    )
    db.commit()

    return Token(
        access_token=new_access_token,
        token_type="bearer",
        refresh_token=new_refresh_token,
    )


# ---------------------------------------------------------------------------
# POST /logout  — Revoke current token
# ---------------------------------------------------------------------------


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Invalidate the current Bearer token.

    The token is added to the server-side blacklist so that subsequent
    requests using the same token are rejected even before the JWT expiry.
    """
    raw_token = _extract_bearer(request)
    if raw_token:
        revoke_token(raw_token)

    log_event(
        AuditEventType.LOGOUT,
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="POST /api/auth/logout",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
        db=db,
    )
    db.commit()


# ---------------------------------------------------------------------------
# GET /me  — Current user profile
# ---------------------------------------------------------------------------


@router.get("/me", response_model=UserSchema)
async def read_users_me(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Return the profile of the currently authenticated (and active) user."""
    return current_user
