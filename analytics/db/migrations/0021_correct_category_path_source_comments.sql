-- analytics/db/migrations/0021_correct_category_path_source_comments.sql
--
-- Corrects the COMMENT on category_path_source, set by 0011:96 and restated by
-- 0012:69. Comments only — no column, constraint, index or row is touched, and
-- no behaviour changes.
--
-- WHAT WAS WRONG
--
-- Both comments describe `keyword_rule` as a populated source:
--   "keyword_rule (description-keyword fallback at confidence >= 0.6,
--    validated out-of-sample at 97.4% accuracy)"
--
-- It has never been populated, and cannot be:
--   * _fit_keyword_rule() (run_canonical_load.py:797) and _predict_category()
--     (:812) are never called. KEYWORD_CONFIDENCE_THRESHOLD (:828) is
--     referenced by nothing, so the 0.6 gate exists only in prose.
--   * The fallback branch is unconditional (:938-941) — no prediction is
--     attempted.
--   * The SKUs it would cover have no SOH row, therefore no article
--     description to tokenize, and Unilever demand data carries no product
--     name (unilever_sku.yaml's "Product" column is a bare code).
-- Live count 2026-09-20: 0 rows with category_path_source = 'keyword_rule'.
-- 94.6% / 97.4% were out-of-sample validation figures for a rule that was
-- fitted, evaluated, and then not deployed. Describing them as the accuracy of
-- a live source states intended behaviour as current state.
--
-- Both comments also cite "~79% of Unilever demand SKUs" for direct_soh_match.
-- Live: 1,718 of 2,098 = 81.9%; unclassified 380 = 18.1%, carrying 0.159% of
-- all-time real demand revenue.
--
-- SCRATCH-VERIFY ONLY. Not applied to public in this pass.

BEGIN;

COMMENT ON COLUMN Product_Dimension.category_path_source IS
'How category_path was populated for this row.
 direct_soh_match - most-recent SOH snapshot CATEGORY DESC. 1,718 of 2,098 Unilever grain=sku rows (81.9%) as of 2026-09-20.
 keyword_rule     - NEVER POPULATED (0 rows). A description-keyword fallback was fitted and validated out-of-sample in Phase 0 (94.6% overall, 97.4% at confidence >= 0.6) but was never wired into the loader, and cannot be: the rows needing it have no SOH row and so no description text to tokenize. The value remains legal so a future implementation need not re-migrate. Treat any claim that this source is active as false.
 unclassified     - failed direct match; category_path is the literal string ''UNCLASSIFIED'', not NULL. 380 rows (18.1%), 0.159% of all-time real demand revenue.
 source_file_defect - Del Monte grain=category rows whose source Sell Out file held a broken-lookup artifact instead of a real category label; category_path is also the literal ''UNCLASSIFIED'', revenue preserved via a per-(region,_period) sum.
 NULL             - not yet processed by the loader, or not applicable for this row''s grain.
 Comment corrected by migration 0021 (2026-09-20); 0011 and 0012 described keyword_rule as live and cited ~79% for direct_soh_match.';

COMMIT;

-- Rollback (not run, kept for review): restore 0012's wording verbatim.
-- Rolling back reinstates a comment that is factually wrong, so this exists for
-- procedural completeness only — prefer correcting forward.
-- BEGIN;
-- COMMENT ON COLUMN Product_Dimension.category_path_source IS
-- 'How category_path was populated for this row: direct_soh_match (most-recent SOH snapshot CATEGORY DESC, ~79% of Unilever demand SKUs), keyword_rule (description-keyword fallback at confidence >= 0.6, validated out-of-sample at 97.4% accuracy), unclassified (failed both - category_path is the literal string ''UNCLASSIFIED'', not NULL - Unilever grain=sku only), source_file_defect (Del Monte grain=category rows whose source Sell Out file held a broken-lookup artifact instead of a real category label - category_path is also the literal string ''UNCLASSIFIED'', revenue preserved via a per-(region,_period) sum, see PHASE1_EXECUTION_PLAN_2026-09.md item 40a), or NULL (not yet processed by the loader / not applicable for this row''s grain). See reports/PROJECT_STATE_2026-09.md §8.';
-- COMMIT;
