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

ROUND TRIPS (2026-10-04). Every statement costs a network round trip to
Supabase (~0.1 s from the team's machines, more from Render), so a request
pays for each one whatever its size. Before this date every request paid four
before its first query: the pool's pre-ping (two with the engine's
postgresql_readonly option, one without — measured, speed baseline
2026-10-04), BEGIN, and the session check, plus a ROLLBACK after. Now:
  - no pre-ping: connections are recycled after POOL_RECYCLE_SECONDS and kept
    alive with TCP keepalives instead. A connection the server dropped anyway
    fails that one request and is replaced, which pre-ping would have hidden;
  - GET/HEAD requests read through a second pool whose connections are in
    autocommit (no BEGIN, no ROLLBACK, no SET: psycopg2's transaction
    characteristics are never touched on them);
  - everything else writes through the transactional pool, where each new
    connection is marked read-write once (psycopg2 then sends BEGIN READ
    WRITE, with no session-level SET);
  - the session check also returns the user's permission overrides and, on a
    read, the data version backend/response_cache.py keys on: one round trip.

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
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.auth_utils import JWTError, TokenPayload, decode_access_token
from backend.sessions import CLOSE_IF_IDLE_SQL, SESSION_IDLE_MINUTES

_engine: Engine | None = None
_read_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None
_ReadSessionLocal: sessionmaker | None = None

# Below the 5-minute idle limit common to proxies and NAT in front of a pooler,
# so the pool hands out no connection old enough to have been dropped silently.
POOL_RECYCLE_SECONDS = 280
_CONNECT_ARGS = {
    "connect_timeout": 10,
    "sslmode": "require",
    # TCP keepalives keep an idle pooled connection open through NAT, in place
    # of the per-checkout pre-ping.
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}


def _db_url() -> str:
    load_dotenv(override=False)
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError(
            "SUPABASE_DB_URL is not set. Copy .env.example to .env and fill "
            "in your real Supabase connection string before starting the API."
        )
    return db_url


def _get_engine() -> Engine:
    """The transactional engine (every request that may write). Created
    lazily on first use (not at import time) so importing backend.deps never
    fails just because SUPABASE_DB_URL isn't set yet — e.g. during test
    collection."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            _db_url(), pool_pre_ping=False, pool_recycle=POOL_RECYCLE_SECONDS, connect_args=_CONNECT_ARGS,
        )

        # Every transaction starts as BEGIN READ WRITE. SUPABASE_DB_URL is
        # Supabase's transaction pooler, whose server connections are shared:
        # a script that opens its connection with psycopg2's
        # set_session(readonly=True, autocommit=True) sets
        # default_transaction_read_only on the shared server session, and every
        # client handed that connection later inherits it. Found 2026-09-28
        # when sign-ins failed with "cannot execute INSERT in a read-only
        # transaction" (seen before on 2026-09-18, see scripts/run_sql.py).
        # Set once per connection, outside autocommit, psycopg2 only adds READ
        # WRITE to each BEGIN (measured: checkout + SELECT 1 + commit is 3 round
        # trips, BEGIN READ WRITE / SELECT / COMMIT). The engine option this
        # replaces (postgresql_readonly) added a round trip to every pre-ping.
        @event.listens_for(_engine, "connect")
        def _read_write(dbapi_connection, _record):
            dbapi_connection.readonly = False

    return _engine


def _get_read_engine() -> Engine:
    """The engine GET/HEAD requests read through: autocommit, so a request
    sends its statements and nothing else (no BEGIN, no ROLLBACK). Reads see
    committed data either way; the one write a read can make (closing an idle
    session, below) is a single statement."""
    global _read_engine
    if _read_engine is None:
        _read_engine = create_engine(
            _db_url(), pool_pre_ping=False, pool_recycle=POOL_RECYCLE_SECONDS, connect_args=_CONNECT_ARGS,
            isolation_level="AUTOCOMMIT",
        )
    return _read_engine


def check_db_connection() -> None:
    """Runs a trivial query against Supabase to confirm SUPABASE_DB_URL is
    both set and reachable. Called from backend.main's startup hook so a
    bad connection string fails loudly when the server boots, instead of
    surfacing as a confusing error on whatever request happens to be
    first. Raises (RuntimeError if unset, sqlalchemy.exc.* if unreachable)
    rather than returning a bool — startup should crash, not limp on."""
    from backend import batch, lp_cycle, marts, permissions  # they import this module

    _get_engine().connect().close()
    # Opens the read pool's first connection, and asks in the same round trip
    # which optional tables exist, so even the first request's session check
    # reads permissions and the data version with it.
    with Session(_get_read_engine()) as db:
        batch.prefetch(db, [(permissions.READY_SQL, {}), (marts.REFRESH_PRESENT_SQL, {}),
                            (lp_cycle.LP_RUN_PRESENT_SQL, {})])
        permissions.permissions_ready(db)
        marts.present(db)
        lp_cycle.lp_run_present(db)


READ_METHODS = ("GET", "HEAD")


def get_db(request: Request = None) -> Generator[Session, None, None]:
    """Yields a SQLAlchemy session pointed at Supabase. Closed after each
    request regardless of success or failure. A GET/HEAD request gets the
    autocommit read pool; anything else (and a caller outside a request,
    e.g. backend/scripts/seed_admin.py) the transactional one."""
    global _SessionLocal, _ReadSessionLocal
    reads = request is not None and request.method in READ_METHODS
    if reads:
        if _ReadSessionLocal is None:
            _ReadSessionLocal = sessionmaker(bind=_get_read_engine(), autoflush=False)
        db = _ReadSessionLocal()
    else:
        if _SessionLocal is None:
            _SessionLocal = sessionmaker(bind=_get_engine(), autoflush=False, autocommit=False)
        db = _SessionLocal()
    db.info["read_request"] = reads
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
           s.last_seen_at < now() - make_interval(mins => :idle_minutes) AS idle{extra}
      FROM users u
      LEFT JOIN user_session s ON s.session_id = :session_id AND s.user_id = u.user_id
     WHERE u.user_id = :user_id
"""

# Read in the same round trip as the session check once the tables exist
# (backend/permissions.permissions_ready, backend/marts.present remember that):
# the user's permission overrides (migration 0034) ...
OVERRIDES_COLUMN = """,
           (SELECT COALESCE(json_object_agg(o.permission_key, o.granted), '{}'::json)
              FROM user_permission_override o WHERE o.user_id = u.user_id) AS permission_overrides"""
# ... and, on a read, what the cached responses were built from: the marts'
# refresh status (every data load, fill, forecast run and LP run, and the
# refresh itself — mart.refresh_status, migration 0041), the latest reorder
# decision and the latest SKU added or edited through the app.
DATA_VERSION_COLUMN = """,
           (SELECT row_to_json(r)::text FROM mart.refresh_status r)
           || '|' || COALESCE((SELECT MAX(decided_at)::text FROM lp_recommendation), '')
           || '|' || COALESCE((SELECT MAX(audit_log_key)::text FROM audit_log
                               WHERE action IN ('Add SKU', 'Edit SKU')), '') AS data_version"""


def _principal_sql(db: Session) -> str:
    from backend import marts, permissions  # both import this module

    extra = ""
    if permissions.permissions_ready_known():
        extra += OVERRIDES_COLUMN
    info = getattr(db, "info", None)
    if isinstance(info, dict) and info.get("read_request") and marts.present_known():
        extra += DATA_VERSION_COLUMN
    return ACTIVE_PRINCIPAL_SQL.format(extra=extra)


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
    row = db.execute(text(_principal_sql(db)), params).mappings().first()
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
    return _principal_from_row(db, payload, row)


def _principal_from_row(db: Session, payload: TokenPayload, row) -> TokenPayload:
    """The checked principal, with what the session check read alongside it:
    the effective permission set (when the overrides were read) and, on the
    request's session, the data version (backend/response_cache.py)."""
    granted = None
    if "permission_overrides" in row:
        from backend import permissions

        granted = frozenset(permissions.effective(row["role"], dict(row["permission_overrides"] or {})))
    if "data_version" in row and isinstance(getattr(db, "info", None), dict):
        db.info["data_version"] = row["data_version"]
    return TokenPayload(
        user_id=payload.user_id,
        email=row["email"],
        role=row["role"],
        full_name=row["full_name"],
        session_id=payload.session_id,
        permissions=granted,
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
