"""
analytics.config — Central configuration loader.

Phase 3A (CLAUDE.md Step 1):
  Loads SUPABASE_DB_URL (required) and SUPABASE_KEY (optional, read by nothing) from .env via python-dotenv.
  Exposes a typed Settings object consumed by db/, etl/, and optimization/.

TODO: Implement Settings using pydantic-settings or os.environ; validate that
      required keys are present at import time so misconfigured runs fail fast.
Implementation note: uses a plain dataclass + os.environ rather than
pydantic-settings — pydantic-settings is not in requirements.txt and
RULES.md forbids adding a new dependency without Yuan's override.
python-dotenv is already pinned, so .env loading goes through it.

Fails fast: get_settings() raises a clear error immediately if a required
key is missing, rather than letting a downstream script (seed_date_dim.py,
db loaders, etc.) fail later with an opaque connection error.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

# SUPABASE_DB_URL only (2026-11-13). SUPABASE_KEY was required here too and nothing anywhere reads it (Settings.supabase_key has no
# reader; the local .env holds .env.example's placeholder, and scripts/local_pg.py, optin_run.py and data_management_app.py pass
# "local-dummy" just to get past this check). On a server without it (Render: the API never reads it, so nobody sets it) every
# script that calls get_settings() refused to start, the month load's ABC step (orchestrate_abc) and the migration runner among them.
REQUIRED_KEYS = ("SUPABASE_DB_URL",)


class MissingConfigError(RuntimeError):
    """Raised when a required environment variable is not set."""


@dataclass(frozen=True)
class Settings:
    supabase_db_url: str
    supabase_key: str


def _load_env_file(dotenv_path: str | None = None) -> None:
    """Loads .env into the process environment if present. Safe to call
    more than once (override=False keeps already-exported env vars, e.g.
    CI secrets, from being clobbered by a stray local .env)."""
    load_dotenv(dotenv_path=dotenv_path, override=False)


def _read_required(key: str) -> str:
    value = os.environ.get(key)
    if not value or not value.strip():
        raise MissingConfigError(
            f"{key} is not set. Copy .env.example to .env and fill in your "
            f"real Supabase values, or export {key} in your environment "
            f"before running this script."
        )
    return value.strip()


@lru_cache(maxsize=1)
def get_settings(dotenv_path: str | None = None) -> Settings:
    """Loads and validates configuration once per process. Raises
    MissingConfigError immediately if a required key is absent — this is
    the "fail fast" behavior the original TODO asked for, so a
    misconfigured run never gets partway through the pipeline before
    erroring out on a Supabase connection.

    Cached (lru_cache) so repeated calls across db/, etl/, optimization/
    don't re-parse .env; pass a different dotenv_path (e.g. in tests) only
    before the first call, or use get_settings.cache_clear() to reset."""
    _load_env_file(dotenv_path)
    values = {key: _read_required(key) for key in REQUIRED_KEYS}
    return Settings(
        supabase_db_url=values["SUPABASE_DB_URL"],
        supabase_key=os.environ.get("SUPABASE_KEY", "").strip(),   # optional, unread (REQUIRED_KEYS)
    )


def long_read_db_url() -> str:
    """The URL for a LONG read or a backup: SUPABASE_DIRECT_URL when it is set,
    else the pooler URL (SUPABASE_DB_URL).

    The :6543 transaction pooler drops a connection that sits on a long query
    ("SSL SYSCALL error: EOF detected": 2026-10-15, twice in a row on
    fetch_demand; the direct URL ran the same reads clean, and had been
    breaking runs for over a week). Use this for reads that take more than a
    few seconds. Despite its name, SUPABASE_DIRECT_URL holds the session pooler
    (port 5432) since 2026-11-04: db.<ref>.supabase.co is IPv6-only and does
    not resolve from every network. Never use
    it to change how a connection is configured: the rules on session-level
    SET (CLAUDE.md hard rule 7) apply to both URLs."""
    _load_env_file()
    db = os.environ.get("SUPABASE_DB_URL", "").strip()
    direct = os.environ.get("SUPABASE_DIRECT_URL", "").strip()
    if not db:
        return get_settings().supabase_db_url        # raises MissingConfigError, naming the variable
    # SUPABASE_DIRECT_URL is only a better ROUTE to the database SUPABASE_DB_URL names (same host, user and database,
    # another port). Until 2026-11-11 it won whenever it was set: .env holds it pointing at live, so a process told
    # SUPABASE_DB_URL=<a local copy> still read live (the compute_review_flags trap of 2026-11-10, here in every backup,
    # rehearsal script and long read). A direct URL naming a different database is now ignored, and said so.
    if direct and same_database(direct, db):
        return direct
    if direct:
        import sys
        print("long_read_db_url: SUPABASE_DIRECT_URL names a different database than SUPABASE_DB_URL; using SUPABASE_DB_URL",
              file=sys.stderr)
    return db


def same_database(a: str, b: str) -> bool:
    """True when two connection URLs name the same server host, user and database (the port may differ: the
    Supabase session and transaction poolers are one database on two ports)."""
    from urllib.parse import urlparse
    pa, pb = urlparse(a), urlparse(b)
    return ((pa.hostname or "").lower(), pa.username or "", pa.path.lstrip("/") or "postgres") == \
           ((pb.hostname or "").lower(), pb.username or "", pb.path.lstrip("/") or "postgres")

