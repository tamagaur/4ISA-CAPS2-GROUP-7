-- 0066_lp_case_pack_rounding.sql - keep the order before case-pack rounding, and the pack size, on each plan row.
--
-- scripts/run_lp.py now rounds each order to whole case packs INSIDE the warehouse and allocation ceilings the LP
-- solved under (analytics/optimization/lp.round_to_case_packs). q_i stays THE order, the rounded quantity. Two
-- columns keep what rounding did to it, so the difference is auditable row by row:
--   q_i_before_pack_rounding  the quantity the LP solved, before rounding. NULL on rows written before this migration
--                             and on rows from a run with --no-case-pack-rounding.
--   pack_size                 pieces per case used for the rounding. NULL when the product has no usable pack size,
--                             in which case q_i equals q_i_before_pack_rounding.
-- need_i, the safety stock formula and the forecast are not touched. Nothing reads these columns for planning.
--
-- Expected on apply: 0 rows written. Every existing lp_recommendation row keeps every value and gets NULL in both
-- new columns.
--
-- Rollback: ALTER TABLE lp_recommendation DROP COLUMN IF EXISTS q_i_before_pack_rounding, DROP COLUMN IF EXISTS pack_size.
--           DELETE FROM schema_migrations WHERE filename = '0066_lp_case_pack_rounding.sql'.
-- (No semicolons in comments: scripts/run_canonical_load splits statements on them.)

ALTER TABLE lp_recommendation
    ADD COLUMN IF NOT EXISTS q_i_before_pack_rounding NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS pack_size NUMERIC(10,2);

ALTER TABLE lp_recommendation DROP CONSTRAINT IF EXISTS ck_lp_pack_rounding_nonneg;
ALTER TABLE lp_recommendation ADD CONSTRAINT ck_lp_pack_rounding_nonneg
    CHECK ((q_i_before_pack_rounding IS NULL OR q_i_before_pack_rounding >= 0) AND (pack_size IS NULL OR pack_size > 0));

COMMENT ON COLUMN lp_recommendation.q_i_before_pack_rounding IS
    'The order the LP solved before case-pack rounding. q_i is the rounded order. NULL = not rounded or written before 0066.';
COMMENT ON COLUMN lp_recommendation.pack_size IS
    'Pieces per case used to round q_i. NULL = no usable pack size, q_i not rounded.';
