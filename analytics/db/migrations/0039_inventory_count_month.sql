-- analytics/db/migrations/0039_inventory_count_month.sql
--
-- Written 2026-10-03 on kelvin/stock-timing-fix. NOT applied anywhere when
-- written: it goes to public only through scripts/run_canonical_load.py, after
-- it is committed and a backup is taken.
--
-- Every stock count records which month it belongs to. Migration 0010 added
-- Inventory_Fact.days_offset and demand_period for exactly this, and left the
-- backfill to scratch/backfill_0010.py, which is not in the repository. Checked
-- read-only on public 2026-10-03: 0 of 60,873 rows have either column, though
-- DEC-20 (ARCHITECTURE.md) records 27,282 of 27,282 filled. Had they been
-- filled, the LP could not have planned March 2026 from the count that closes
-- March (reports/diagnostics/lp_logic_check_2026-10-03).
--
-- demand_period  the month the count OPENS: _period + 1 month, every row.
--                A count's _period is the month it closes. Unilever's SSIS
--                file for _period is counted 1-6 days after that month ends
--                (DEC-20). Del Monte's sign-off reads "Actual as of" the last
--                day of _period (files opened 2026-10-03: SEPTEMBER 2025
--                reads 2025-09-30; DECEMBER 2025 reads 2026-12-31, a year
--                typo for 2025-12-31).
-- days_offset    days from the last day of _period to the count date:
--                snapshot_date - last day of _period, Unilever rows only
--                (their snapshot_date is the file's own count date, DEC-20).
--                NULL for Del Monte: its snapshot_date is a 1st-of-_period
--                placeholder (DEC-12) and the file's own date isn't loaded,
--                so an offset would be invented.
-- Generated rows (is_demo = true) get the same rule from their own columns.
--
-- Rows loaded later: the trigger fills both columns on every insert and on
-- any change to _period, snapshot_date or principal, so a new count can't
-- land without them. Every loader writes through it (run_canonical_load,
-- fill_missing, the synthetic builders); a value a loader passes for either
-- column is replaced by the rule.
--
-- Backfill: the UPDATE sets _period to itself, which fires the trigger on
-- every row, so the rule lives in one place (the function below).
--
-- Expected after apply (read-only counts on public, 2026-10-03):
--   rows                                 60,873 (Unilever 27,282 real + 11,895
--                                        generated; Del Monte 5,541 real +
--                                        16,155 generated)
--   demand_period filled                 60,873 of 60,873
--   days_offset filled                   39,177 (every Unilever row)
--   days_offset NULL                     21,696 (every Del Monte row)
--   real Unilever days_offset 1 / 2 / 3 / 6   17,338 / 5,506 / 3,653 / 785 rows
--                                        (6 = the 2026-03 count, 2026-04-06)
--
-- Names are unqualified on purpose (public via the runner, or its scratch
-- schema), like every migration. Safe to run twice.

BEGIN;

CREATE OR REPLACE FUNCTION inventory_fact_count_month() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.demand_period := to_char(to_date(NEW._period, 'YYYY-MM') + interval '1 month', 'YYYY-MM');
    NEW.days_offset := CASE
        WHEN NEW.principal = 'unilever' AND NEW._period IS NOT NULL
        THEN NEW.snapshot_date - (to_date(NEW._period, 'YYYY-MM') + interval '1 month' - interval '1 day')::date
    END;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_inventory_fact_count_month ON Inventory_Fact;
CREATE TRIGGER trg_inventory_fact_count_month
    BEFORE INSERT OR UPDATE OF _period, snapshot_date, principal ON Inventory_Fact
    FOR EACH ROW EXECUTE FUNCTION inventory_fact_count_month();

UPDATE Inventory_Fact SET _period = _period;

COMMIT;

-- Rollback (not run, kept for review): the columns go back to NULL.
-- BEGIN;
-- DROP TRIGGER IF EXISTS trg_inventory_fact_count_month ON Inventory_Fact;
-- DROP FUNCTION IF EXISTS inventory_fact_count_month();
-- UPDATE Inventory_Fact SET demand_period = NULL, days_offset = NULL;
-- COMMIT;
