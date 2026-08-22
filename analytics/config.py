"""
analytics.config — Central configuration loader.

Phase 3A (CLAUDE.md Step 1):
  Loads SUPABASE_DB_URL and SUPABASE_KEY from .env via python-dotenv.
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

REQUIRED_KEYS = ("SUPABASE_DB_URL", "SUPABASE_KEY")


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
        supabase_key=values["SUPABASE_KEY"],
    )

