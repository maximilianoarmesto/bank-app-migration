from fastapi import APIRouter
from .endpoints import auth, users, bank_accounts

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["authentication"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(bank_accounts.router, prefix="/bank-accounts", tags=["bank-accounts"])