from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from .bank_account import BankAccount


class UserBase(BaseModel):
    username: str
    email: EmailStr
    first_name: str
    last_name: str


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: Optional[bool] = None


class User(UserBase):
    id: int
    is_active: bool
    is_admin: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    bank_accounts: List[BankAccount] = []

    class Config:
        from_attributes = True