"""Fixtures for the cross-endpoint invariants (tests/invariants/).

These drive the real FastAPI app in-process against the LIVE database, inside one transaction that is
`SET TRANSACTION READ ONLY` and always rolled back (hard rule 7: transaction-scoped, never a session-level
setting), so a write would fail rather than land.

Skipped is not passed: if the live database is not configured these tests FAIL, naming the variable. They never
skip, because an invariant that quietly does not run is how a suite looks healthy while the integration is broken.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
load_dotenv(REPO / ".env")

REQUIRED_ENV = ("SUPABASE_DB_URL",)


def _configured(name: str) -> bool:
    v = os.environ.get(name, "")
    return bool(v) and "<" not in v          # the .env.example placeholder has "<database-password>"


@pytest.fixture(scope="session")
def live_env():
    missing = [n for n in REQUIRED_ENV if not _configured(n)]
    if missing:
        pytest.fail(f"live invariants cannot run: environment variable(s) not set: {', '.join(missing)} "
                    "(set in .env or the shell). This is a FAILURE, not a skip.", pytrace=False)


@pytest.fixture(scope="session")
def db(live_env):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from analytics.config import long_read_db_url
    engine = create_engine(long_read_db_url())
    conn = engine.connect()
    tx = conn.begin()
    conn.execute(text("SET TRANSACTION READ ONLY"))
    session = Session(bind=conn, autoflush=False)
    session.info["read_request"] = True
    try:
        yield session
    finally:
        session.close()
        tx.rollback()
        conn.close()
        engine.dispose()


@pytest.fixture(scope="session")
def get(db):
    """get(path) -> parsed JSON of a GET against the real app (admin token, session check bypassed as in
    scripts/smoke_api.py). Memoised: each path is requested once per run."""
    from fastapi.testclient import TestClient

    from backend.auth_utils import create_access_token
    from backend.deps import get_current_user, get_db, get_token_payload
    from backend.main import app

    def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = get_token_payload
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + create_access_token(user_id=1, email="invariants@local",
                                                                role="admin", full_name="Invariants")}
    cache: dict[str, dict] = {}

    def _get(path: str) -> dict:
        if path not in cache:
            r = client.get(path, headers=headers)
            assert r.status_code == 200, f"GET {path} answered {r.status_code}: {r.text[:200]}"
            cache[path] = r.json()
        return cache[path]

    yield _get
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(scope="session")
def sql(db):
    from sqlalchemy import text

    def _sql(query: str, **params) -> list[dict]:
        return [dict(r._mapping) for r in db.execute(text(query), params)]
    return _sql


@pytest.fixture(scope="session")
def plan(get):
    return get("/recommendations?principal=unilever")
