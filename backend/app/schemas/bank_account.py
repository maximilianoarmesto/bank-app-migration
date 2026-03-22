from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal


class BankAccountBase(BaseModel):
    account_number: str
    account_type: str
    balance: Decimal = Decimal("0.00")
    currency: str = "USD"


class BankAccountCreate(BankAccountBase):
    owner_id: int


class BankAccountUpdate(BaseModel):
    account_type: Optional[str] = None
    balance: Optional[Decimal] = None
    currency: Optional[str] = None
    is_active: Optional[bool] = None


class BankAccount(BankAccountBase):
    id: int
    is_active: bool
    owner_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True