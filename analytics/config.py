"""
analytics.config — Central configuration loader.

Phase 3A (CLAUDE.md Step 1):
  Loads SUPABASE_DB_URL and SUPABASE_KEY from .env via python-dotenv.
  Exposes a typed Settings object consumed by db/, etl/, and optimization/.

TODO: Implement Settings using pydantic-settings or os.environ; validate that
      required keys are present at import time so misconfigured runs fail fast.
"""
