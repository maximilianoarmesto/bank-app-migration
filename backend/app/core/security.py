"""
Core security utilities for the banking application.

Provides:
- Password hashing / verification via bcrypt.
- JWT access-token and refresh-token creation.
- Token verification and decoding.
- Token-type constants used to distinguish access tokens from refresh tokens.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return ``True`` if *plain_password* matches *hashed_password*."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Return the bcrypt hash of *password*."""
    return pwd_context.hash(password)


# ---------------------------------------------------------------------------
# Token-type constants
# ---------------------------------------------------------------------------

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# Refresh tokens are valid for 7 days by default.
REFRESH_TOKEN_EXPIRE_DAYS = 7

# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


def create_access_token(
    data: dict, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a short-lived JWT access token.

    The token payload is a copy of *data* extended with:
    - ``exp`` — absolute expiry timestamp.
    - ``type`` — ``"access"`` so that refresh tokens are rejected here.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": TOKEN_TYPE_ACCESS})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(data: dict) -> str:
    """
    Create a long-lived JWT refresh token.

    The token payload is a copy of *data* extended with:
    - ``exp`` — absolute expiry timestamp (``REFRESH_TOKEN_EXPIRE_DAYS`` days).
    - ``type`` — ``"refresh"`` so that access tokens are rejected here.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": TOKEN_TYPE_REFRESH})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


def verify_token(token: str, expected_type: str = TOKEN_TYPE_ACCESS) -> Optional[dict]:
    """
    Verify and decode *token*.

    Parameters
    ----------
    token:
        The raw JWT string to verify.
    expected_type:
        Expected value of the ``type`` claim (``"access"`` or ``"refresh"``).
        Tokens whose ``type`` does not match are rejected even if the
        signature is valid — this prevents refresh tokens from being used
        where access tokens are expected and vice-versa.

    Returns
    -------
    dict | None
        Decoded payload on success, or ``None`` when verification fails.
    """
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        token_type: str | None = payload.get("type")
        if token_type != expected_type:
            return None
        return payload
    except JWTError:
        return None


def verify_refresh_token(token: str) -> Optional[dict]:
    """Convenience wrapper — verify a refresh token specifically."""
    return verify_token(token, expected_type=TOKEN_TYPE_REFRESH)
