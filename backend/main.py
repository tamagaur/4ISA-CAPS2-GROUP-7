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
from fastapi.middleware.cors import CORSMiddleware

from backend.deps import check_db_connection, get_db
from backend.routers import (
    abc, audit_log, auth, bo_monitoring, dashboard, forecast, inventory, recommendations, segment, sku, users,
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


app = FastAPI(
    title="SSM Decision Support Dashboard API",
    description="Read-only API over Supabase-stored ETL/ABC/MA3-forecast/LP pipeline outputs.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(inventory.router)
app.include_router(forecast.router)
app.include_router(recommendations.router)
app.include_router(abc.router)
app.include_router(bo_monitoring.router)
app.include_router(dashboard.router)
app.include_router(sku.router)
app.include_router(audit_log.router)
app.include_router(segment.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Unauthenticated liveness check — deliberately outside every
    router's get_current_user dependency so uptime monitoring doesn't
    need an API key. Only confirms the process is up, not that Supabase
    is reachable (see the `lifespan` startup check above for that)."""
    return {"status": "ok"}
