-- analytics/db/migrations/0051_sku_traits_stability_group_pattern.sql
--
-- sku_traits.stability_group CHECK widening. The live constraint (0018) hardcodes the
-- 'single' (38-period) basis's labels: ('all_38', 'at_least_30', 'churn'). traits.py's
-- stability_group() (analytics/segmentation/traits.py:192-205) builds the label from
-- f"all_{total_periods}" / f"at_least_{near_permanent}", where total_periods is whatever
-- the product's abc_method actually has — 38 for 'single', 27 for 't12m_new' (DEC-38) per
-- the NEAR_PERMANENT_RATIO comment at traits.py:184-189. orchestrate_segment.py --write for
-- t12m_new/2026-02 therefore emits 'all_27' / 'at_least_21', which the literal-list CHECK
-- rejects.
--
-- Fix: pattern-based, not another literal list — a literal list is exactly what broke the
-- first time a second abc_method appeared, and a future basis (any period count) would
-- break it again. CHECK accepts 'churn' or any all_<N> / at_least_<N> shape; it no longer
-- encodes a specific horizon at all.

BEGIN;

ALTER TABLE sku_traits DROP CONSTRAINT IF EXISTS sku_traits_stability_group_check;
ALTER TABLE sku_traits ADD CONSTRAINT sku_traits_stability_group_check
    CHECK (stability_group = 'churn' OR stability_group ~ '^(all|at_least)_[0-9]+$');

COMMIT;

-- Rollback (not run, kept for review):
-- BEGIN;
-- ALTER TABLE sku_traits DROP CONSTRAINT IF EXISTS sku_traits_stability_group_check;
-- ALTER TABLE sku_traits ADD CONSTRAINT sku_traits_stability_group_check
--     CHECK (stability_group IN ('all_38', 'at_least_30', 'churn'));
-- COMMIT;
