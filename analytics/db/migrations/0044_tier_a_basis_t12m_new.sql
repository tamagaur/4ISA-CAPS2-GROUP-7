-- 0044_tier_a_basis_t12m_new.sql — the 't12m_new' Tier A basis (DEC-37, PENDING TA CONFIRMATION).
--
-- Tier A for Unilever moves from the single month to: Class A on the last 12 months' revenue,
-- plus products first sold within those 12 months that are Class A on the last 3 months
-- (kelvin/tier-a-basis f753f4e, README section 7; analytics/classification/orchestrate_abc.py
-- classify_unilever_t12m_new). Which basis is Tier A is analytics.params.TIER_A_BASIS, so it can
-- be switched back; the 'single' runs keep being written.
--
--   1. method / abc_method accept 't12m_new' on abc_classification, sku_traits and sku_segment.
--   2. abc_classification.added_as_new: true on a row made Class A by the new-product rule (its
--      revenue_share / cumulative_share stay the 12-month ones, so it can sit past the 80% cut).
--      false on every existing row.
--
-- Rollback (after deleting the t12m_new rows of all three tables):
--   ALTER TABLE abc_classification DROP COLUMN added_as_new;
--   and re-add each CHECK with ('single', 't3m') only.

ALTER TABLE abc_classification DROP CONSTRAINT abc_classification_method_check;
ALTER TABLE abc_classification ADD CONSTRAINT abc_classification_method_check
    CHECK (method IN ('single', 't3m', 't12m_new'));

ALTER TABLE sku_traits DROP CONSTRAINT sku_traits_abc_method_check;
ALTER TABLE sku_traits ADD CONSTRAINT sku_traits_abc_method_check
    CHECK (abc_method IN ('single', 't3m', 't12m_new'));

ALTER TABLE sku_segment DROP CONSTRAINT sku_segment_abc_method_check;
ALTER TABLE sku_segment ADD CONSTRAINT sku_segment_abc_method_check
    CHECK (abc_method IN ('single', 't3m', 't12m_new'));

ALTER TABLE abc_classification ADD COLUMN IF NOT EXISTS added_as_new boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN abc_classification.added_as_new IS
    't12m_new basis: Class A by the new-product rule (first sold within the 12 months, Class A on the last 3), not by the 12-month 80% cut. Migration 0044.';
