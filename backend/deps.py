"""
backend.deps — FastAPI dependency injection: DB session, auth, pagination.

Phase 6 (CLAUDE.md Step 24):
  get_db()   → yields a SQLAlchemy session pointed at Supabase.
  get_current_user() → validates a JWT from the Authorization: Bearer header;
    raises 401 if missing, malformed, expired, or invalid. No SSM client
    data is served without a valid token.

Story #89: replaces the previous static X-API-Key scheme (see git history)
with real per-user JWT auth backed by the Users table (analytics/db/schema.sql
Section 6) and bcrypt password hashes. get_current_user() keeps the same
no-argument-from-caller shape (Depends(get_current_user)) so every router's
Depends() call site is unaffected by the swap; only its body and return
type changed (str API key -> auth_utils.TokenPayload with user_id/email/role,
which routers can use for role-gating e.g. admin-only endpoints).

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

from backend.auth_utils import JWTError, TokenPayload, decode_access_token

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


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization")
) -> TokenPayload:
    """Validates a JWT from the Authorization: Bearer <token> header. Raises
    401 if the header is missing, malformed, or the token is invalid/expired
    — no SSM client data is served without a valid token.

    Returns the decoded TokenPayload (user_id, email, role) so callers that
    need role-gating (e.g. POST /auth/register, admin-only) can inspect
    `.role` via Depends(get_current_user) without a second lookup.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Provide it as "
            "'Authorization: Bearer <token>'.",
        )
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return decode_access_token(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        ) from exc
