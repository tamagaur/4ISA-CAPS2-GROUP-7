-- analytics/db/migrations/0042_in_transit_stock_and_review_flag.sql
--
-- Written 2026-10-04 on kelvin/review-flags. NOT applied anywhere when
-- written: it goes to public only through scripts/run_canonical_load.py
-- (--schema public --target-public --schema-only), after it is committed, a
-- backup is taken, and 0041 (data marts) is already in schema_migrations.
--
-- 1. In-transit stock: Unilever's SOH file carries "PO Qty" (open purchase
--    orders, CS/PC text like "12/0") beside each count row. The extract has
--    always staged it (analytics/etl/extract/ssis_soh.py, po_qty_raw) but no
--    column held it. Checked in staging/ssis_soh, 2026-10-04: 39 counts,
--    27,321 rows (one is each sheet's totals row); 11,811 non-blank values,
--    all "<cases>/<pieces>", none "0/0", the pieces part 0 on every one; each
--    count has 209-414 non-blank values. The file writes nothing rather than
--    "0/0", so the loader stores a blank as 0 on order
--    (analytics/etl/transform_ssis_soh.py).
--      po_qty_cases   open PO quantity, cases
--      po_qty_pieces  open PO quantity, loose pieces
--    NULL on every row loaded before this migration: "not parsed yet", never
--    "nothing on order". They fill when the Unilever stock slices are
--    reloaded through scripts/run_canonical_load.py (one fingerprint
--    sign-off by a person). Del Monte's stock file has no PO column, so its
--    rows stay NULL.
--
-- 2. review_flag: "review before ordering", one row per product per planning
--    cycle, written by scripts/compute_review_flags.py
--    (analytics/forecasting/review_flag.py has the two rules). It changes no
--    forecast and no order; GET /recommendations reads it, and PATCH refuses
--    to accept a flagged row unless the person confirms they reviewed it.
--      needs_review     TRUE = a rule tripped; FALSE = assessed, none did;
--                       NULL = neither rule could be assessed
--      reasons          'collapse', 'over_forecast_run'
--      collapse         last-3 / last-12-month mean < 0.5; NULL = under 12
--                       months since the first sale
--      over_run_months  over-forecast months in a row ending the month
--                       before the cycle, counted back at most 6 (so 6 =
--                       "6 or more"); NULL = no served model to score
--      served_bin       the bin whose model was scored
--      forecast_generated_at  the Forecast_Result run it was checked against
--
-- Expected after apply (read-only counts on public, 2026-10-04):
--   inventory_fact rows            60,993 (Unilever 27,282 real + 11,895
--                                  generated; Del Monte 5,541 real + 16,275
--                                  generated), unchanged
--   po_qty_cases / po_qty_pieces   NULL on all 60,993
--   Inventory_Fact_Real            gains the two columns at the end (no view
--                                  depends on it, checked 2026-10-04)
--   review_flag                    new, 0 rows
--
-- Names are unqualified on purpose (public via the runner, or its scratch
-- schema), like every migration. Safe to run twice.

BEGIN;

-- 0041 (data marts) is reserved ahead of this one and must land first; this
-- file reaching kelvin-etl before it must not let the runner apply it out of
-- order.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE filename LIKE '0041\_%') THEN
        RAISE EXCEPTION '0042 needs migration 0041 (data marts) applied first';
    END IF;
END
$$;

ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS po_qty_cases NUMERIC;
ALTER TABLE Inventory_Fact ADD COLUMN IF NOT EXISTS po_qty_pieces NUMERIC;
COMMENT ON COLUMN Inventory_Fact.po_qty_cases IS
    'Unilever SOH "PO Qty", cases: open purchase orders at the count (in transit). A blank cell is stored as 0 (the file never writes 0/0). NULL = loaded before migration 0042, not parsed yet.';
COMMENT ON COLUMN Inventory_Fact.po_qty_pieces IS
    'Unilever SOH "PO Qty", loose pieces part. Same NULL rule as po_qty_cases.';

-- SELECT * is expanded when a view is created, so the view is re-created to
-- carry the new columns (as 0028 and 0038 did).
CREATE OR REPLACE VIEW Inventory_Fact_Real AS
SELECT * FROM Inventory_Fact WHERE is_demo = false;

CREATE TABLE IF NOT EXISTS review_flag (
    product_key            BIGINT NOT NULL REFERENCES product_dimension (product_key),
    planning_cycle_date    DATE NOT NULL,
    principal              TEXT NOT NULL CHECK (principal IN ('unilever', 'delmonte')),
    needs_review           BOOLEAN,
    reasons                TEXT[] NOT NULL DEFAULT '{}'
                           CHECK (reasons <@ ARRAY['collapse', 'over_forecast_run']::TEXT[]),
    collapse               BOOLEAN,
    collapse_ratio         NUMERIC,
    over_run_months        INTEGER CHECK (over_run_months >= 0),
    served_bin             TEXT,
    forecast_generated_at  TIMESTAMPTZ,
    computed_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_key, planning_cycle_date),
    CHECK ((needs_review IS TRUE) = (cardinality(reasons) > 0))
);
CREATE INDEX IF NOT EXISTS ix_review_flag_cycle ON review_flag (planning_cycle_date);
ALTER TABLE review_flag ENABLE ROW LEVEL SECURITY;

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- DROP TABLE IF EXISTS review_flag;
-- DROP VIEW IF EXISTS Inventory_Fact_Real;
-- ALTER TABLE Inventory_Fact DROP COLUMN IF EXISTS po_qty_cases, DROP COLUMN IF EXISTS po_qty_pieces;
-- CREATE VIEW Inventory_Fact_Real AS SELECT * FROM Inventory_Fact WHERE is_demo = false;
-- COMMIT;
