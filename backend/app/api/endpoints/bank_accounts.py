from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User
from app.models.bank_account import BankAccount
from app.schemas.bank_account import BankAccount as BankAccountSchema, BankAccountCreate, BankAccountUpdate
from app.api.endpoints.auth import get_current_user

router = APIRouter()


@router.post("/", response_model=BankAccountSchema, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    account: BankAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Users can only create accounts for themselves, admins can create for anyone
    if account.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    # Check if account number already exists
    existing_account = db.query(BankAccount).filter(
        BankAccount.account_number == account.account_number
    ).first()
    
    if existing_account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account number already exists"
        )
    
    # Create new bank account
    db_account = BankAccount(**account.dict())
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    
    return db_account


@router.get("/", response_model=List[BankAccountSchema])
def read_bank_accounts(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Users can only see their own accounts, admins can see all
    if current_user.is_admin:
        accounts = db.query(BankAccount).offset(skip).limit(limit).all()
    else:
        accounts = db.query(BankAccount).filter(
            BankAccount.owner_id == current_user.id
        ).offset(skip).limit(limit).all()
    
    return accounts


@router.get("/{account_id}", response_model=BankAccountSchema)
def read_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank account not found"
        )
    
    # Users can only access their own accounts, admins can access any
    if account.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    return account


@router.put("/{account_id}", response_model=BankAccountSchema)
def update_bank_account(
    account_id: int,
    account_update: BankAccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db_account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if db_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank account not found"
        )
    
    # Users can only update their own accounts, admins can update any
    if db_account.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    # Update account fields
    update_data = account_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_account, field, value)
    
    db.commit()
    db.refresh(db_account)
    
    return db_account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db_account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if db_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank account not found"
        )
    
    # Users can only delete their own accounts, admins can delete any
    if db_account.owner_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    db.delete(db_account)
    db.commit()