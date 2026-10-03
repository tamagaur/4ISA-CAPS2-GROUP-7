-- analytics/db/migrations/0040_derived_receipt_opening_flag.sql
--
-- H2 and H3 of reports/diagnostics/coverage_check_2026-10-03.md (Yuan, 2026-10-03).
--
-- 1. Derived receipts (DEC-31 item 1) learn that a product missing from a Unilever
--    count that was taken has 0 on hand, as backend/stock_status.py reads those counts:
--    Unilever's SOH files never list a zero-stock item (0 of 27,321 raw rows read 0/0).
--      opening_flag  missing from the previous month's count -> opening 0 (H3)
--      closing_flag  missing from this month's count          -> closing 0 (the reverse case)
--      count_flag    the assumed-zero opening comes from a count on record as possibly
--                    partial (scripts/fill_missing.POSSIBLY_PARTIAL_COUNTS)
--    Separate columns, not more values of `flag`: a row can carry an assumption AND a
--    negative balance, and `flag` with derived_receipt_fact_flag_matches_balance stays
--    exactly the negative-balance rule (stored, receipt shown as 0, flagged).
--
-- 2. A Del Monte branch missing from a month that has real rows for the other branch is
--    filled with a copy of that branch's adjacent real month (H2), tagged
--    'synthetic_branch_adjacent'. The five Del Monte fact tables' fill_source checks (0038)
--    are re-created with that value added; every value they allowed is kept. Unilever
--    demand's check is not touched. The _Real views are not touched.
--
-- Numbered 0040: 0039 is reserved by the stock-timing fix. Needs 0038.

BEGIN;

-- 1. assumed-zero counts
ALTER TABLE derived_receipt_fact ADD COLUMN IF NOT EXISTS opening_flag TEXT;
ALTER TABLE derived_receipt_fact ADD COLUMN IF NOT EXISTS closing_flag TEXT;
ALTER TABLE derived_receipt_fact ADD COLUMN IF NOT EXISTS count_flag TEXT;
ALTER TABLE derived_receipt_fact DROP CONSTRAINT IF EXISTS derived_receipt_fact_opening_flag_check;
ALTER TABLE derived_receipt_fact ADD CONSTRAINT derived_receipt_fact_opening_flag_check
    CHECK (opening_flag IS NULL OR (opening_flag = 'opening_assumed_0_not_in_count' AND opening_pieces = 0));
ALTER TABLE derived_receipt_fact DROP CONSTRAINT IF EXISTS derived_receipt_fact_closing_flag_check;
ALTER TABLE derived_receipt_fact ADD CONSTRAINT derived_receipt_fact_closing_flag_check
    CHECK (closing_flag IS NULL OR (closing_flag = 'closing_assumed_0_not_in_count' AND closing_pieces = 0));
ALTER TABLE derived_receipt_fact DROP CONSTRAINT IF EXISTS derived_receipt_fact_count_flag_check;
ALTER TABLE derived_receipt_fact ADD CONSTRAINT derived_receipt_fact_count_flag_check
    CHECK (count_flag IS NULL OR (count_flag = 'after_possibly_partial_count' AND opening_flag IS NOT NULL));
COMMENT ON COLUMN derived_receipt_fact.opening_flag IS
    'opening_assumed_0_not_in_count: not in the previous month''s Unilever count (a count that was taken), so opening stock is 0 - Unilever files omit zero rows (migration 0040).';
COMMENT ON COLUMN derived_receipt_fact.closing_flag IS
    'closing_assumed_0_not_in_count: in the previous count but not in this month''s (a count that was taken), so closing stock is 0 (migration 0040).';
COMMENT ON COLUMN derived_receipt_fact.count_flag IS
    'after_possibly_partial_count: the assumed-zero opening comes from a count on record as possibly partial (scripts/fill_missing.POSSIBLY_PARTIAL_COUNTS; migration 0040).';

-- 2. the branch-copy tag
ALTER TABLE sales_fact DROP CONSTRAINT IF EXISTS sales_fact_fill_source_check;
ALTER TABLE sales_fact ADD CONSTRAINT sales_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap', 'synthetic_branch_adjacent')));
ALTER TABLE purchase_fact DROP CONSTRAINT IF EXISTS purchase_fact_fill_source_check;
ALTER TABLE purchase_fact ADD CONSTRAINT purchase_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap', 'synthetic_branch_adjacent')));
ALTER TABLE salesreturn_fact DROP CONSTRAINT IF EXISTS salesreturn_fact_fill_source_check;
ALTER TABLE salesreturn_fact ADD CONSTRAINT salesreturn_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap', 'synthetic_rate_transfer', 'synthetic_branch_adjacent')));
ALTER TABLE sellout_fact DROP CONSTRAINT IF EXISTS sellout_fact_fill_source_check;
ALTER TABLE sellout_fact ADD CONSTRAINT sellout_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap', 'synthetic_branch_adjacent')));
ALTER TABLE inventory_fact DROP CONSTRAINT IF EXISTS inventory_fact_fill_source_check;
ALTER TABLE inventory_fact ADD CONSTRAINT inventory_fact_fill_source_check CHECK (
    fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap', 'synthetic_branch_adjacent')));

COMMIT;
