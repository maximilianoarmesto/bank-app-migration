from fastapi import APIRouter
from .endpoints import auth, users, bank_accounts, audit_logs

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["authentication"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(bank_accounts.router, prefix="/bank-accounts", tags=["bank-accounts"])
router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit-logs"])