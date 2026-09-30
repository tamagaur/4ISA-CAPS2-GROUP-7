-- analytics/db/migrations/0033_etl_load_event_and_coverage.sql
--
-- Two tables the slice loader (scripts/load_slices.py) writes and the backend
-- will read (GET /admin/data-loads, planned 2026-09-30, not built):
--
-- 1. etl_load_event - one row per slice per run: what was attempted, what
--    happened (loaded / refused / partial / warning), why (reason code), and
--    the row counts the transaction actually changed. A refused slice writes
--    its event in a separate transaction after the rollback, so a refusal is
--    recorded even though it changed nothing. Dry runs write an event with
--    dry_run = true and change nothing else.
--    files holds file NAMES only (no directories, no connection strings):
--    the fact tables' _src_file carries the repo-relative path, which is
--    not repeated here.
--
-- 2. etl_coverage - one row per principal x table x month from 2021-01
--    through the current month: real / synthetic / partial / missing.
--    missing means no row at all for that month - a gap, never a zero.
--    partial means real rows exist but an expected branch has none (a
--    branch is the extract's infer_sheet_region() on each row's source
--    sheet, NOT the row's region column - sales_fact.region is the
--    customer's town). The loader refreshes the months a slice touches
--    inside the slice's own transaction; `run_canonical_load
--    --refresh-coverage` recomputes every month (the seed step after this
--    migration). Only principal x table pairs that can hold data are
--    listed: Unilever has no sales_fact / sellout_fact / purchase / return
--    source (DEC-29 "not applicable - never fill").
--
-- Security (reports/diagnostics/security_audit_2026-09-30.md): RLS on with
-- no policies, and no privileges for anon / authenticated, same as every
-- other public table since the 2026-09-28 lockdown. The backend reads them
-- as the table owner.

BEGIN;

CREATE TABLE IF NOT EXISTS etl_load_event (
    load_event_key          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                  TEXT NOT NULL,
    slice                   TEXT NOT NULL,
    principal               TEXT NOT NULL CHECK (principal IN ('delmonte', 'unilever')),
    table_name              TEXT NOT NULL,
    month                   TEXT NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    site                    TEXT,
    source                  TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK (status IN ('loaded', 'refused', 'partial', 'warning')),
    reason                  TEXT CHECK (reason IN (
                                'shrink_guard', 'shrink_allowed', 'missing_file', 'layout_changed',
                                'partial_month', 'fingerprint_unsigned', 'key_conflict_other_slice',
                                'row_balance', 'period_not_allowed', 'error')),
    detail                  TEXT,
    files                   TEXT[] NOT NULL DEFAULT '{}',
    real_rows_before        INTEGER NOT NULL DEFAULT 0,
    real_rows_removed       INTEGER NOT NULL DEFAULT 0,
    real_rows_added         INTEGER NOT NULL DEFAULT 0,
    real_rows_after         INTEGER NOT NULL DEFAULT 0,
    synthetic_rows_removed  INTEGER NOT NULL DEFAULT 0,
    quarantine_rows_removed INTEGER NOT NULL DEFAULT 0,
    quarantine_rows_added   INTEGER NOT NULL DEFAULT 0,
    allow_shrink            BOOLEAN NOT NULL DEFAULT false,
    dry_run                 BOOLEAN NOT NULL DEFAULT false,
    run_by                  TEXT NOT NULL,
    started_at              TIMESTAMPTZ NOT NULL,
    finished_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_etl_load_event_slice
    ON etl_load_event (principal, table_name, month, finished_at DESC);
CREATE INDEX IF NOT EXISTS ix_etl_load_event_run ON etl_load_event (run_id);

COMMENT ON TABLE etl_load_event IS
    'One row per slice per loader run (migration 0033). status loaded/refused/partial/warning, reason code, row counts the transaction changed. files = file names only.';

CREATE TABLE IF NOT EXISTS etl_coverage (
    principal           TEXT NOT NULL CHECK (principal IN ('delmonte', 'unilever')),
    table_name          TEXT NOT NULL,
    month               TEXT NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    status              TEXT NOT NULL CHECK (status IN ('real', 'synthetic', 'partial', 'missing')),
    real_rows           INTEGER NOT NULL,
    synthetic_rows      INTEGER NOT NULL,
    real_sites          TEXT[] NOT NULL DEFAULT '{}',
    expected_sites      TEXT[] NOT NULL DEFAULT '{}',
    last_load_event_key BIGINT REFERENCES etl_load_event (load_event_key),
    refreshed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (principal, table_name, month)
);

COMMENT ON TABLE etl_coverage IS
    'Per principal x table x month: real / synthetic / partial / missing (migration 0033). missing = a gap, render null, never 0. partial = an expected branch has no real rows.';

ALTER TABLE etl_load_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE etl_coverage ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON etl_load_event, etl_coverage FROM %I', r);
            EXECUTE format('REVOKE ALL ON SEQUENCE etl_load_event_load_event_key_seq FROM %I', r);
        END IF;
    END LOOP;
END
$$;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP TABLE IF EXISTS etl_coverage;
-- DROP TABLE IF EXISTS etl_load_event;
-- COMMIT;
