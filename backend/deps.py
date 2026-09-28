"""
backend.deps — FastAPI dependency injection: DB session, auth, pagination.

Phase 6 (CLAUDE.md Step 24):
  get_db()   → yields a SQLAlchemy session pointed at Supabase.
  get_current_user() → validates a JWT from the Authorization: Bearer header;
    raises 401 if missing, malformed, expired, or invalid. No SSM client
    data is served without a valid token. Since 2026-09-28 it also checks
    the account and its session in the database on every request (see
    _load_active_principal), so signing out, an admin's change to the
    account and the 30-minute idle limit take effect immediately.

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
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.auth_utils import JWTError, TokenPayload, decode_access_token
from backend.sessions import CLOSE_IF_IDLE_SQL, SESSION_IDLE_MINUTES

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
        _engine = create_engine(
            db_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10, "sslmode": "require"},
            # Every transaction starts as BEGIN READ WRITE. SUPABASE_DB_URL is
            # Supabase's transaction pooler, whose server connections are
            # shared: a script that opens its connection with psycopg2's
            # set_session(readonly=True, autocommit=True) sets
            # default_transaction_read_only on the shared server session, and
            # every client handed that connection later inherits it. Found
            # 2026-09-28 when sign-ins failed with "cannot execute INSERT in a
            # read-only transaction" (seen before on 2026-09-18, see
            # scripts/run_sql.py).
            execution_options={"postgresql_readonly": False},
        )
    return _engine


def check_db_connection() -> None:
    """Runs a trivial query against Supabase to confirm SUPABASE_DB_URL is
    both set and reachable. Called from backend.main's startup hook so a
    bad connection string fails loudly when the server boots, instead of
    surfacing as a confusing error on whatever request happens to be
    first. Raises (RuntimeError if unset, sqlalchemy.exc.* if unreachable)
    rather than returning a bool — startup should crash, not limp on."""
    from sqlalchemy import text

    engine = _get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


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


def get_token_payload(
    authorization: str | None = Header(default=None, alias="Authorization")
) -> TokenPayload:
    """Validates a JWT from the Authorization: Bearer <token> header. Raises
    401 if the header is missing, malformed, or the token is invalid/expired.
    Checks the signature only; get_current_user adds the database check."""
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


ACTIVE_PRINCIPAL_SQL = """
    SELECT u.email, u.full_name, u.role, s.session_id, s.ended_at,
           s.last_seen_at < now() - make_interval(mins => :idle_minutes) AS idle
      FROM users u
      LEFT JOIN user_session s ON s.session_id = :session_id AND s.user_id = u.user_id
     WHERE u.user_id = :user_id
"""

SESSION_ENDED = "Your session has ended. Please sign in again."


def _load_active_principal(db: Session, payload: TokenPayload) -> TokenPayload:
    """The account and session behind a validly signed token, read fresh.

    Until 2026-09-28 a signature check was all a token needed for its 8
    hours, so signing out, deleting an account or demoting an admin changed
    nothing until it expired, and the 30-minute idle rule only fed the Audit
    Log's numbers. Now a request is refused (401) when the account is gone,
    or its session was signed out, ended by an admin change, or idle for
    SESSION_IDLE_MINUTES. The role returned is the database's, not the
    token's, so require_admin sees a demotion on the very next request."""
    if payload.session_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SESSION_ENDED)
    params = {
        "user_id": payload.user_id,
        "session_id": payload.session_id,
        "idle_minutes": SESSION_IDLE_MINUTES,
    }
    row = db.execute(text(ACTIVE_PRINCIPAL_SQL), params).mappings().first()
    if row is None or row["session_id"] is None or row["ended_at"] is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SESSION_ENDED)
    if row["idle"]:
        # Recorded as ended at its last activity, the same way a heartbeat
        # after the gap would have closed it.
        try:
            db.execute(text(CLOSE_IF_IDLE_SQL), params)
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SESSION_ENDED)
    return TokenPayload(
        user_id=payload.user_id,
        email=row["email"],
        role=row["role"],
        full_name=row["full_name"],
        session_id=payload.session_id,
    )


def get_current_user(
    payload: TokenPayload = Depends(get_token_payload),
    db: Session = Depends(get_db),
) -> TokenPayload:
    """The signed-in user for this request: a valid token whose account and
    session are still live (see _load_active_principal). Raises 401
    otherwise — no SSM client data is served without both.

    Returns user_id/email/role/full_name as the database has them now, so
    routers can role-gate on `.role` (e.g. require_admin) without a second
    lookup."""
    return _load_active_principal(db, payload)


def require_admin(current_user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
    """get_current_user plus a 403 for anyone whose role isn't 'admin'.

    Used on the endpoints that change shared data — the SKU master
    (POST/PATCH /sku) and reorder decisions (PATCH /recommendations) — so a
    staff account can read every page but not alter what the others see.
    The frontend hides those buttons for staff too; this is the check that
    actually holds, since the role in the browser's copy of the token is
    only read for display."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin account can do this.",
        )
    return current_user
