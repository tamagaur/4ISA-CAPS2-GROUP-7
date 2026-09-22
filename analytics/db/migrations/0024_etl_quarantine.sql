-- analytics/db/migrations/0024_etl_quarantine.sql
--
-- Adds etl_quarantine: one row per source row the canonical load did not
-- insert, with the rule that stopped it.
--
-- Why: the 2026-09-21 completeness audit found 649 quarantined real rows
-- (432 sales, 27 purchase, 188 Del Monte inventory, 2 conflicting sales rows)
-- that existed only as a count in a log line. The database is the
-- deliverable; a row SSM sent that is not in a fact table has to be findable
-- in the database too, with where it came from and why it is not loaded.
--
-- Every exclusion is recorded, not only the quarantine class: source-of-truth
-- filter, footer/junk checks, exact-duplicate collapse, the sell-out
-- defect-category merge, NOT NULL exclusions and conflicting groups.
-- scripts/run_canonical_load.py writes it (one run_id per load).
--
-- raw_values holds the row as Transform saw it (canonical column names where
-- the column map applies, the source's own header otherwise), so nothing has
-- to be re-extracted to review a row. No foreign keys on purpose: a
-- quarantined row is exactly the row that could not be tied to a dimension.

BEGIN;

CREATE TABLE IF NOT EXISTS etl_quarantine (
    quarantine_key  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          TEXT NOT NULL,      -- one per run_canonical_load invocation
    table_name      TEXT NOT NULL,      -- fact table the row was headed for
    rule            TEXT NOT NULL,      -- function or check list that excluded it
    reason          TEXT NOT NULL,      -- what about THIS row triggered the rule
    _src_file       TEXT,
    _src_sheet      TEXT,
    _row_ordinal    BIGINT,             -- 0-based data row within the sheet (Extract)
    is_demo         BOOLEAN NOT NULL DEFAULT false,
    raw_values      JSONB NOT NULL,
    quarantined_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_etl_quarantine_run_table ON etl_quarantine (run_id, table_name, rule);

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP TABLE IF EXISTS etl_quarantine;
-- COMMIT;
