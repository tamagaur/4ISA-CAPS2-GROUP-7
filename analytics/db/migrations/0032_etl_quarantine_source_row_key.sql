-- analytics/db/migrations/0032_etl_quarantine_source_row_key.sql
--
-- One etl_quarantine row per source row: UNIQUE (table_name, _src_file,
-- _src_sheet, _row_ordinal).
--
-- Why: etl_quarantine had no natural key, so every reload appended a second
-- copy of every excluded row. The 2026-09-30 load rehearsal added 9,659
-- duplicates in one run (reports/diagnostics/load_readiness_2026-09-30.md,
-- check 4d). Slice loads (scripts/load_slices.py) now delete the quarantine
-- rows of the sheets they reload before writing new ones; this index makes
-- a second copy an error instead of a silent duplicate.
--
-- Checked read-only on public before writing this (2026-09-30): 0 groups
-- share (table_name, _src_file, _src_sheet, _row_ordinal) among the rows
-- with an ordinal. The 564 rows dm_fixes batch 7 wrote carry a NULL
-- _row_ordinal; NULLs are distinct under a plain unique index, so they never
-- collide, and a reload of their slice replaces them with ordinals.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_etl_quarantine_source_row
    ON etl_quarantine (table_name, _src_file, _src_sheet, _row_ordinal);

COMMENT ON INDEX uq_etl_quarantine_source_row IS
    'One quarantine row per source row (migration 0032). A slice reload deletes its own sheets'' rows first; a collision means another slice already recorded this row.';

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP INDEX IF EXISTS uq_etl_quarantine_source_row;
-- COMMIT;
