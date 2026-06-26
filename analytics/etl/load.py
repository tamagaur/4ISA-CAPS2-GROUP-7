"""
analytics.etl.load — Load cleaned data to Supabase via SQLAlchemy.

Phase 3B (CLAUDE.md Step 9 — Checkpoint: row counts match source files; no silent data loss):
  Pattern: upsert (INSERT ... ON CONFLICT DO UPDATE) — no silent overwrites.
  Strategy: batch inserts for performance.
  Post-load: spot-check 10 random SKUs manually (surfaced as a report, not automated).

TODO: Implement load_to_supabase(df: pd.DataFrame, table_name: str, engine) -> int.
      Return row count inserted/updated.
      Raise on any row count mismatch vs. source DataFrame.
"""
