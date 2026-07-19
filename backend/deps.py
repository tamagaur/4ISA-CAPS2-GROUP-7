"""
backend.deps — FastAPI dependency injection: DB session, auth, pagination.

Phase 6 (CLAUDE.md Step 24):
  get_db()   → yields a SQLAlchemy session pointed at Supabase.
  get_current_user() → validates Supabase JWT or API key; raises 401 if invalid.
  No SSM client data is served without a valid auth token.

Auth strategy chosen: static API key (X-API-Key header), not Supabase JWT.
Flagged, not silently decided — the docstring above says "confirm with
Yuan first". API key is the simpler of the two AND the only one directly
supportable by requirements.txt as pinned today: JWT verification needs a
JWT library (python-jose / PyJWT) to check the signature, and neither is
in requirements.txt. Adding one means asking Yuan for the same override
RULES.md already requires for new dependencies. If Supabase JWT auth is
confirmed later, swap get_current_user()'s body only — every router
already depends on get_current_user via Depends(), so no router changes.

get_db() uses a SYNC SQLAlchemy Session, not async — also flagged: async
would need an async driver (asyncpg / psycopg[async]), and requirements.txt
only pins psycopg2-binary (sync). Every router endpoint below is defined
as a plain `def` (not `async def`) so FastAPI runs it in its threadpool,
which is the correct way to use a sync DB call without blocking the
event loop.
"""
from __future__ import annotations

import os
from collections.abc import Generator

from dotenv import load_dotenv
from fastapi import Header, HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _get_engine() -> Engine:
    """Lazily creates a single module-level engine on first use (not at
    import time) so importing backend.deps never fails just because
    SUPABASE_DB_URL isn't set yet — e.g. during test collection."""
    global _engine
    if _engine is None:
        load_dotenv(override=False)
        db_url = os.environ.get("SUPABASE_DB_URL")
        if not db_url:
            raise RuntimeError(
                "SUPABASE_DB_URL is not set. Copy .env.example to .env and fill "
                "in your real Supabase connection string before starting the API."
            )
        _engine = create_engine(db_url, pool_pre_ping=True)
    return _engine


def get_db() -> Generator[Session, None, None]:
    """Yields a SQLAlchemy session pointed at Supabase. Closed after each
    request regardless of success or failure."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), autoflush=False, autocommit=False)
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    """Validates the X-API-Key header against BACKEND_API_KEY. Raises 401
    if missing or incorrect — no SSM client data is served without it.

    Raises a clear RuntimeError (not a silent pass-through) if the server
    itself is misconfigured (BACKEND_API_KEY unset), so a bad deployment
    fails loudly at request time rather than accidentally accepting any
    key or none at all.
    """
    load_dotenv(override=False)
    expected = os.environ.get("BACKEND_API_KEY")
    if not expected:
        raise RuntimeError(
            "BACKEND_API_KEY is not set on the server. Set it in .env before "
            "starting the API — refusing to authenticate against an unset key."
        )
    if not x_api_key or x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Provide it via the X-API-Key header.",
        )
    return x_api_key
