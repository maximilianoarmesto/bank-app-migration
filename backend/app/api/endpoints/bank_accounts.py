"""
Bank account endpoints — all operations are protected by authentication and
ownership/admin authorization enforced via dependency injection.

Access-control policy
---------------------
- **Create**: any authenticated, active user may create an account.
  - Users may only set ``owner_id`` to their own id; admins may set any id.
- **List**: authenticated, active users see only their own accounts.
  - Admins see all accounts.
- **Read / Update / Delete**: owner OR admin only.
  - Non-owner, non-admin access attempts are rejected with HTTP 403 and
    written to the audit log.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.audit_log import AuditEventType, log_event
from app.models.user import User
from app.models.bank_account import BankAccount
from app.schemas.bank_account import (
    BankAccount as BankAccountSchema,
    BankAccountCreate,
    BankAccountUpdate,
)
from app.api.deps import (
    get_current_active_user,
    require_account_owner_or_admin,
    _client_ip,
    _user_agent,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# POST /  — Create bank account
# ---------------------------------------------------------------------------


@router.post("/", response_model=BankAccountSchema, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    request: Request,
    account: BankAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> BankAccount:
    """
    Create a new bank account.

    Non-admin users may only create accounts for themselves
    (``owner_id`` must equal ``current_user.id``).
    """
    if account.owner_id != current_user.id and not current_user.is_admin:
        log_event(
            AuditEventType.FORBIDDEN_ACCESS,
            actor_id=current_user.id,
            actor_username=current_user.username,
            resource="bank_account",
            action="POST /api/bank-accounts/",
            client_ip=_client_ip(request),
            user_agent=_user_agent(request),
            detail=(
                f"User '{current_user.username}' attempted to create an account "
                f"on behalf of user {account.owner_id}"
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions — you can only create accounts for yourself",
        )

    existing = (
        db.query(BankAccount)
        .filter(BankAccount.account_number == account.account_number)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account number already exists",
        )

    db_account = BankAccount(**account.dict())
    db.add(db_account)
    db.commit()
    db.refresh(db_account)

    log_event(
        AuditEventType.ACCOUNT_CREATED,
        actor_id=current_user.id,
        actor_username=current_user.username,
        resource="bank_account",
        resource_id=str(db_account.id),
        action="POST /api/bank-accounts/",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
    )

    return db_account


# ---------------------------------------------------------------------------
# GET /  — List bank accounts
# ---------------------------------------------------------------------------


@router.get("/", response_model=List[BankAccountSchema])
def read_bank_accounts(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> List[BankAccount]:
    """
    Return a paginated list of bank accounts.

    - Admins receive all accounts.
    - Regular users receive only their own accounts.
    """
    if current_user.is_admin:
        return db.query(BankAccount).offset(skip).limit(limit).all()
    return (
        db.query(BankAccount)
        .filter(BankAccount.owner_id == current_user.id)
        .offset(skip)
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# GET /{account_id}  — Read single bank account
# ---------------------------------------------------------------------------


@router.get("/{account_id}", response_model=BankAccountSchema)
def read_bank_account(
    request: Request,
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_account_owner_or_admin()),
) -> BankAccount:
    """
    Return a single bank account by id.

    Ownership or admin role is enforced by the ``require_account_owner_or_admin``
    dependency before this handler executes.
    """
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank account not found",
        )
    return account


# ---------------------------------------------------------------------------
# PUT /{account_id}  — Update bank account
# ---------------------------------------------------------------------------


@router.put("/{account_id}", response_model=BankAccountSchema)
def update_bank_account(
    request: Request,
    account_id: int,
    account_update: BankAccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_account_owner_or_admin()),
) -> BankAccount:
    """
    Partially update a bank account.

    Ownership or admin role is enforced by the ``require_account_owner_or_admin``
    dependency before this handler executes.
    """
    db_account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if db_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank account not found",
        )

    update_data = account_update.dict(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(db_account, field_name, value)

    db.commit()
    db.refresh(db_account)

    log_event(
        AuditEventType.ACCOUNT_UPDATED,
        actor_id=current_user.id,
        actor_username=current_user.username,
        resource="bank_account",
        resource_id=str(account_id),
        action=f"PUT /api/bank-accounts/{account_id}",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
        detail=f"Updated fields: {list(update_data.keys())}",
    )

    return db_account


# ---------------------------------------------------------------------------
# DELETE /{account_id}  — Delete bank account
# ---------------------------------------------------------------------------


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_account(
    request: Request,
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_account_owner_or_admin()),
) -> None:
    """
    Delete a bank account.

    Ownership or admin role is enforced by the ``require_account_owner_or_admin``
    dependency before this handler executes.
    """
    db_account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if db_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank account not found",
        )

    db.delete(db_account)
    db.commit()

    log_event(
        AuditEventType.ACCOUNT_DELETED,
        actor_id=current_user.id,
        actor_username=current_user.username,
        resource="bank_account",
        resource_id=str(account_id),
        action=f"DELETE /api/bank-accounts/{account_id}",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
