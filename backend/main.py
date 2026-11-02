"""
backend.main — FastAPI application entry point.

Phase 6 (CLAUDE.md Steps 22–25):
  Mounts routers for all five data endpoint groups plus auth (Story #89).
  All data endpoints require authentication before serving data (Step 24) —
  each router declares dependencies=[Depends(get_current_user)] itself (see
  backend/deps.py), so this file just includes them.
  Architecture boundary: this process reads from Supabase only.
    It does NOT import the analytics package.

Auth: JWT via Authorization: Bearer <token>, issued by POST /auth/login and
verified in backend/deps.py:get_current_user against the Users table
(bcrypt password hashes). Replaces the earlier static X-API-Key scheme.

CORS: the frontend (Vite dev server) runs on a different origin than this
API, so without CORS headers the browser blocks every request before it
even reaches a router - it fails client-side as a generic network error,
not as an HTTP error status. CORS_ALLOWED_ORIGINS in .env overrides the
default dev-server origins for staging/prod.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend import mailer
from backend.api_errors import ApiError, api_error_handler
from backend.client_ip import RealClientIPMiddleware
from backend.error_redaction import validation_error_handler
from backend.deps import check_db_connection, get_db
from backend.input_guard import InputGuardMiddleware
from backend.security_headers import SecurityHeadersMiddleware
from backend.routers import (
    abc, audit_log, auth, category_trends, dashboard, dashboard_range, data_mode, decomposition, demo, forecast, fsn,
    inventory, notifications, pareto, permissions, policy_comparison, recommendations, reorder_approval, reorder_requests,
    segment, sku, two_factor, users,
)

logger = logging.getLogger(__name__)

load_dotenv(override=False)

_DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
_allowed_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS).split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fails the server boot immediately if SUPABASE_DB_URL is missing or
    unreachable, instead of letting that surface later as a confusing
    error on whatever request happens to hit the DB first.

    Skipped when get_db is overridden (tests/backend/*.py all do this via
    app.dependency_overrides to inject a FakeSession) — in that mode the
    real engine is never touched by any request either, so checking it
    would just fail the test suite against a DB it was never going to use.
    """
    mailer.warn_if_frontend_url_unset()
    if get_db in app.dependency_overrides:
        logger.info("get_db is overridden (test/mock mode) — skipping startup DB connectivity check.")
    else:
        try:
            check_db_connection()
        except Exception:
            logger.exception("Startup DB connectivity check failed — refusing to start.")
            raise
        logger.info("Startup DB connectivity check passed.")
    yield


# APP_ENV=production hides the interactive docs (/docs, /redoc) and the
# /openapi.json map of every route: useful on a laptop, only a map for
# strangers on a public server. Every route still needs a token either way.
_SHOW_DOCS = os.environ.get("APP_ENV", "").strip().lower() != "production"

app = FastAPI(
    title="SSM Decision Support Dashboard API",
    description="Read-only API over Supabase-stored ETL/ABC/MA3-forecast/LP pipeline outputs.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _SHOW_DOCS else None,
    redoc_url="/redoc" if _SHOW_DOCS else None,
    openapi_url="/openapi.json" if _SHOW_DOCS else None,
)

# Registered first, so innermost: CORS and gzip still wrap what it answers. NUL characters and JSON NaN/Infinity
# are refused with a 400 instead of reaching Postgres, bcrypt or the error encoder (backend/input_guard.py).
app.add_middleware(InputGuardMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# On Render, request.client becomes the visitor's real IP (Cloudflare's
# CF-Connecting-IP) instead of a forwarded address the visitor can set; the
# per-IP sign-in limits depend on it. See backend/client_ip.py.
app.add_middleware(RealClientIPMiddleware)
# Browser-enforced response headers (backend/security_headers.py); HSTS only where APP_ENV=production.
app.add_middleware(SecurityHeadersMiddleware, hsts=not _SHOW_DOCS)
# GET /sku is ~0.94 MB of JSON (2,783 rows) but ~0.057 MB gzipped, measured
# 2026-10-07; added last so it wraps the other middleware. Only applies when
# the client sends Accept-Encoding: gzip; bodies under 1000 bytes are left alone.
app.add_middleware(GZipMiddleware, minimum_size=1000)

# The permissions contract's error body: {"detail": <sentence>, "code": ...}
# (backend/api_errors.py).
app.add_exception_handler(ApiError, api_error_handler)
# 422 without the values of password/token/secret/key fields (backend/error_redaction.py).
app.add_exception_handler(RequestValidationError, validation_error_handler)

app.include_router(auth.router)
app.include_router(two_factor.router)
app.include_router(users.router)
app.include_router(permissions.router)
app.include_router(inventory.router)
app.include_router(forecast.router)
app.include_router(recommendations.router)
app.include_router(reorder_approval.router)
app.include_router(reorder_requests.router)
app.include_router(notifications.router)  # the bell (migration 0071, 2026-10-28)
app.include_router(abc.router)
app.include_router(dashboard.router)
app.include_router(dashboard_range.router)
app.include_router(sku.router)
app.include_router(audit_log.router)
app.include_router(segment.router)
app.include_router(policy_comparison.router)
app.include_router(fsn.router)
app.include_router(pareto.router)
app.include_router(decomposition.router)
app.include_router(category_trends.router)
app.include_router(data_mode.router)
app.include_router(demo.router)


@app.get("/health", tags=["health"])
@app.get("/status", tags=["health"])
def health() -> dict[str, str]:
    """Unauthenticated liveness check — deliberately outside every
    router's get_current_user dependency so uptime monitoring doesn't
    need an API key. Only confirms the process is up, not that Supabase
    is reachable (see the `lifespan` startup check above for that).

    Two paths, same check: Render's health check uses /health; the
    sidebar's status light uses /status, because EasyPrivacy (Brave
    Shields, uBlock Origin, AdBlock) blocks ||onrender.com/health, which
    showed SYS OFFLINE in those browsers while the app itself worked."""
    return {"status": "ok"}
