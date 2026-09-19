-- analytics/db/migrations/0020_sku_traits_abc_method.sql
--
-- Adds `abc_method` to sku_traits and widens its natural key to
-- (product_key, cohort_period, abc_method).
--
-- Why: migration 0018 gave sku_SEGMENT an abc_method column and included it in
-- that table's UNIQUE key (0018:45, 0018:50), but sku_TRAITS got neither. Its
-- upsert conflict target is ["product_key", "cohort_period"] only
-- (analytics/segmentation/orchestrate_segment.py:243), so a t3m cohort run
-- would overwrite the single-method cohort's traits outright rather than
-- coexisting with them — silently, with no conflict raised. sku_segment does
-- not have this problem; sku_traits does.
--
-- This matters now because orchestrate_abc.py gained --method t3m
-- (2026-09-20), making a second cohort genuinely producible.
--
-- Existing rows were all produced by the single-method cohort run
-- (run_id 'segment_unilever_2026-02_99b89896', 132 rows), so they take
-- abc_method='single' via the column default. No backfill UPDATE is needed;
-- the DEFAULT populates them on ADD COLUMN.
--
-- SCRATCH ONLY. Not applied to public. The 132 live sku_traits rows are not
-- at risk from the current single-method pipeline, so there is no urgency to
-- cut this over — it is a prerequisite for a t3m segmentation run, which is
-- itself gated behind the adviser's classification-window ruling.

BEGIN;

ALTER TABLE sku_traits
    ADD COLUMN IF NOT EXISTS abc_method TEXT NOT NULL DEFAULT 'single'
        CHECK (abc_method IN ('single', 't3m'));

-- 0018 created this as UNIQUE (product_key, cohort_period). Postgres names an
-- inline table-level UNIQUE constraint <table>_<col>_<col>_key.
ALTER TABLE sku_traits DROP CONSTRAINT IF EXISTS sku_traits_product_key_cohort_period_key;

ALTER TABLE sku_traits ADD CONSTRAINT sku_traits_product_key_cohort_period_abc_method_key
    UNIQUE (product_key, cohort_period, abc_method);

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE sku_traits DROP CONSTRAINT IF EXISTS sku_traits_product_key_cohort_period_abc_method_key;
-- ALTER TABLE sku_traits ADD CONSTRAINT sku_traits_product_key_cohort_period_key
--     UNIQUE (product_key, cohort_period);
-- ALTER TABLE sku_traits DROP COLUMN IF EXISTS abc_method;
-- COMMIT;
