"""
User management endpoints — protected by authentication and self/admin
authorization enforced via dependency injection.

Access-control policy
---------------------
- **Create (register)**: public — no token required.
- **List all users**: admin only.
- **Read / Update a user**: the user themselves OR an admin.
  - Attempts by other users are rejected with HTTP 403 and written to
    the audit log.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_password_hash
from app.core.audit_log import AuditEventType, log_event
from app.models.user import User
from app.schemas.user import User as UserSchema, UserCreate, UserUpdate
from app.api.deps import (
    get_current_active_user,
    require_admin,
    require_self_or_admin,
    _client_ip,
    _user_agent,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# POST /  — Register (public)
# ---------------------------------------------------------------------------


@router.post("/", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
def create_user(
    request: Request,
    user: UserCreate,
    db: Session = Depends(get_db),
) -> User:
    """
    Register a new user account.  No authentication is required.

    Duplicate username or email is rejected with HTTP 400.
    """
    db_user = (
        db.query(User)
        .filter((User.username == user.username) | (User.email == user.email))
        .first()
    )
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered",
        )

    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        hashed_password=hashed_password,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    log_event(
        AuditEventType.USER_CREATED,
        resource="user",
        resource_id=str(db_user.id),
        action="POST /api/users/",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
        detail=f"New user registered: '{db_user.username}'",
    )

    return db_user


# ---------------------------------------------------------------------------
# GET /  — List all users (admin only)
# ---------------------------------------------------------------------------


@router.get("/", response_model=List[UserSchema])
def read_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> List[User]:
    """
    Return a paginated list of all users.

    Restricted to administrators.  Non-admin attempts are rejected with
    HTTP 403 and written to the audit log by the ``require_admin`` dependency.
    """
    return db.query(User).offset(skip).limit(limit).all()


# ---------------------------------------------------------------------------
# GET /{user_id}  — Read a single user
# ---------------------------------------------------------------------------


@router.get("/{user_id}", response_model=UserSchema)
def read_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_self_or_admin()),
) -> User:
    """
    Return the profile of a single user.

    The requesting user must be the account owner or an admin.
    Cross-user access attempts are rejected with HTTP 403 and written to
    the audit log by the ``require_self_or_admin`` dependency.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


# ---------------------------------------------------------------------------
# PUT /{user_id}  — Update a user
# ---------------------------------------------------------------------------


@router.put("/{user_id}", response_model=UserSchema)
def update_user(
    request: Request,
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_self_or_admin()),
) -> User:
    """
    Partially update a user profile.

    The requesting user must be the account owner or an admin.
    Cross-user update attempts are rejected with HTTP 403 and written to
    the audit log by the ``require_self_or_admin`` dependency.
    """
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    update_data = user_update.dict(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(db_user, field_name, value)

    db.commit()
    db.refresh(db_user)

    log_event(
        AuditEventType.USER_UPDATED,
        actor_id=current_user.id,
        actor_username=current_user.username,
        resource="user",
        resource_id=str(user_id),
        action=f"PUT /api/users/{user_id}",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
        detail=f"Updated fields: {list(update_data.keys())}",
    )

    return db_user
