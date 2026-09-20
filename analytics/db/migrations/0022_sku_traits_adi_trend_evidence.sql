-- analytics/db/migrations/0022_sku_traits_adi_trend_evidence.sql
--
-- Adds adi, trend_pvalue, trend_slope to sku_traits.
--
-- Why: Round 2 binning (2026-09-20) bins on a Mann-Kendall test and reports
-- ADI per bin, but sku_traits stored only the resulting trend LABEL. The
-- p-value and Theil-Sen slope survived only as text inside
-- sku_segment.bin_reason, and ADI was not stored anywhere — so the measured
-- evidence behind a bin could not be queried once the session that computed
-- it ended.
--
-- All three are nullable on purpose: a SKU that never sold has no ADI, and a
-- series too short or constant to test has no p-value or slope
-- (analytics/segmentation/traits.py trend_stats). NULL means "not measurable",
-- never 0.
--
-- No backfill here: the values come from the demand series, not from other
-- columns, so analytics/segmentation/orchestrate_segment.py writes them on
-- its next run (upsert on the 0020 key). Existing rows stay NULL until then.

BEGIN;

ALTER TABLE sku_traits
    ADD COLUMN IF NOT EXISTS adi          NUMERIC,  -- months since first sale / months with a sale; 1.0 = sold every month
    ADD COLUMN IF NOT EXISTS trend_pvalue NUMERIC,  -- Mann-Kendall two-sided p, from first sale onward
    ADD COLUMN IF NOT EXISTS trend_slope  NUMERIC;  -- Theil-Sen slope, units/month, from first sale onward

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE sku_traits
--     DROP COLUMN IF EXISTS adi,
--     DROP COLUMN IF EXISTS trend_pvalue,
--     DROP COLUMN IF EXISTS trend_slope;
-- COMMIT;
