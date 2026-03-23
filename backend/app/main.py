"""
FastAPI application factory for the Bank App Migration (SIA) API.

Middleware stack (innermost first)
-----------------------------------
1. ``TokenBlacklistMiddleware`` — rejects revoked tokens before they reach
   any route handler, ensuring that logged-out sessions are fully invalidated.
2. ``CORSMiddleware`` — allows the Next.js frontend to call the API.

Security notes
--------------
- Revoked tokens are stored in-memory.  For multi-worker / multi-process
  deployments, migrate ``_token_blacklist`` to a shared Redis instance.
- ``SECRET_KEY`` **must** be changed from the placeholder before production
  deployment.  Set it via the ``SECRET_KEY`` environment variable.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import router as api_router
from app.core.config import settings
from app.core.security import verify_token, TOKEN_TYPE_ACCESS
from app.core.audit_log import AuditEventType, log_event

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Bank App Migration (SIA)",
    description="A banking application migration system API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Token-blacklist middleware
# ---------------------------------------------------------------------------

# Import the blacklist checker from the auth endpoint module at request time
# to avoid a circular import at module level.


class TokenBlacklistMiddleware(BaseHTTPMiddleware):
    """
    Middleware that inspects every incoming Bearer token against the
    server-side revocation list.

    If the token has been explicitly revoked (e.g. by the /logout endpoint),
    the request is terminated with HTTP 401 before it reaches any route
    handler.  This ensures that logged-out tokens cannot be reused for the
    remainder of their JWT lifetime.

    Paths that do not carry a Bearer token (e.g. /docs, /health, the login
    endpoint) pass through unmodified.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_token = auth_header[7:]

            # Inline import to avoid circular dependency at module load.
            from app.api.endpoints.auth import is_token_revoked

            if is_token_revoked(raw_token):
                log_event(
                    AuditEventType.INVALID_TOKEN,
                    action=f"{request.method} {request.url.path}",
                    client_ip=(
                        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                        or (request.client.host if request.client else "unknown")
                    ),
                    user_agent=request.headers.get("user-agent", "unknown"),
                    detail="Revoked token used after logout",
                )
                return Response(
                    content='{"detail":"Token has been revoked. Please log in again."}',
                    status_code=401,
                    media_type="application/json",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        return await call_next(request)


app.add_middleware(TokenBlacklistMiddleware)

# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API router
# ---------------------------------------------------------------------------

app.include_router(api_router, prefix="/api")

# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def root() -> dict:
    return {"message": "Bank App Migration (SIA) API", "version": "1.0.0"}


@app.get("/health")
async def health_check() -> dict:
    return {"status": "healthy", "service": "Bank App Migration API"}
