# Limitations and follow-ups found while doing the decision-capture work (2026-10-21)

Anti-loop file: things noticed, not done. Nothing here was started.

| # | Item | Why it matters | Where |
|---|---|---|---|
| 1 | A decision cannot be undone. accepted/dismissed are final (409 on any second decision). | A mis-click on Accept or Dismiss has no path back from the page. Needs a product decision (who may reopen, and is the reopen audited) before a transition is added. **Update 2026-10-23: built** as `POST /recommendations/{key}/reverse` (admin only, audited, the decision kept), migration 0067, not yet applied to public. | backend/routers/recommendations.py, state-machine comment above `_UPDATE_DECISION_SQL` |
| 2 | The frontend was not changed. | The API now returns `recommended_q_i`, `decided_q_i`, `decision_reason`, `decided_at`, `decided_by` and accepts `decided_quantity`, but no screen sends a quantity or shows recommended against decided. The existing dismiss dialog already requires a reason, so dismiss keeps working. | frontend/src/api/recommendations.js, ReorderRecommendations.jsx |
| 3 | `planning_mart` does not carry the decision fields. | GET reads them from `lp_recommendation` in one extra statement, only when the page has a decided row. Folding them into the mart means a new mart migration and refresh function. | backend/routers/recommendations.py `_decision_details` |
| 4 | Open-action reads stay pending-only on purpose: dashboard "awaiting a decision" count, pending-keys per tier, reorder preview and its `total_order_qty`, `superseded_count`. | After an accept, the product leaves those counts (it is done), and its accepted order quantity is in no total. If the planner wants "accepted this cycle, quantity to order" it is a new read, and it should use `decided_q_i` where set. | backend/routers/dashboard.py |
| 5 | Other tracked per-product files remain on the team remote (rule 9). Ignoring `reports/` does not untrack them. Examples: `reports/audit_B1_per_sku.csv`, `reports/bakeoff_8020_per_sku_*.csv`, `reports/demand_diagnosis_*.csv`, `reports/diagnostics/*/per_product_summary.csv`. | Same rule, same exposure as the two files removed. Needs a per-file look at what each holds before untracking. | `git ls-files reports` |
| 6 | `scripts/restore_abc_purge.py` reads `reports/abc_purge_backup_2026-08.json`. The file is untracked, still on this machine, and no longer on the remote. | A teammate who needs that restore must be given the file outside git. Moving it to `backups/` and changing `BACKUP_PATH` is the clean fix. | scripts/restore_abc_purge.py:39 |
| 7 | `tests/test_planning_mart.py::test_the_live_mart_answers_the_current_cycle_as_the_joins_do` fails when it runs after `tests/backend/test_recommendations.py` (abc_period joins '2026-02', mart None). It fails the same way on a clean checkout (stashed my changes and re-ran), and is skipped when run alone. | A test-order dependency, or the mart is not served in that process. Not caused by this work. | tests/test_planning_mart.py:310 |
| 8 | The task said 96 pending products. Live on 2026-10-21: the 2026-03 cycle has 110 rows (109 pending, 1 accepted), and 179 pending rows sit in 33 older cycles. | The 96 may be Tier A only or an older count. The numbers in the report are the measured ones. | local/baseline_2026-10-21_before.json |
| 9 | `ck_lp_decision_shape` is NOT VALID: it checks new and updated rows only. Any script that sets `status = 'dismissed'` without a reason now fails with a CheckViolation. None found in `scripts/` or `backend/`. | Intended, and visible when it happens. Validate the constraint after confirming no old dismissed rows exist (none did on 2026-10-21). | migration 0062 |
| 10 | Docs that name the next free migration number (reports/*.md) may still say 0061. CLAUDE.md now says 0063. | Collision risk if a teammate trusts an old doc. | grep "next free" |

## Full suite on 2026-10-21 (1,678 passed, 18 skipped, 7 failed)

All 7 failures also fail on a clean checkout (my changes stashed, same tests re-run), so none is from this work. Listed so they are not mistaken for it:

- tests/segmentation/test_blank_quantity_segmentation.py (2 tests): AttributeError 'NoneType' has no attribute 'connect'
- tests/test_abc_schema_contract.py::test_model_declares_every_live_column
- tests/test_marts.py::test_one_month_range_ranking_reproduces_every_stored_abc_run
- tests/test_params.py::test_every_parameter_is_pinned
- tests/test_planning_mart.py::test_the_live_mart_answers_the_current_cycle_as_the_joins_do (order-dependent)
- tests/test_runner_source_switch.py::test_lp_demo_source_for_unilever_runs_its_own_demo_builder_and_never_opens_the_real_path

## Found while building the stored error decomposition (migration 0063, 2026-10-21)

Anti-loop: noticed, not done.

| # | Item | Numbers | Where |
|---|---|---|---|
| 1 | The stored LP safety stock for earlier cycles is not comparable to the rebuilt one. 146 of 21,250 scored product-months (58 Tier A) have a stored `ss_i` (cycle = target month); those rows were generated 2026-08-24, `lp_run_key` NULL, 1-15 products per cycle. On the same 146 rows stored `ss_i` sums to 7,618 pieces, the rebuilt figure to 491,972. None of the 146 has `exceeds_safety_stock`, so no headline figure moves, but if one did, the small stored figure would overstate exposure. Used as instructed; both figures are kept per row (`safety_stock_stored_pieces`, `safety_stock_rebuilt_pieces`). | 146 rows | mart.error_decomposition_row |
| 2 | Live months (forecast_result runs) are Tier A only: `forecast_result` holds 189 products. B and C rows exist only for the 2024-01..2026-02 backtest window until a B/C live forecast is stored. New months for A flow in through `stored_run` forecasts at the next refresh after their actuals land. | 189 products | analytics/marts hook |
| 3 | The as-served backtest window is closed (2024-01..2026-02). New backtest months need `scripts.accuracy_as_served --write-run` / `--write-tier-runs` to be re-run under new labels (the script refuses an existing label). The decomposition picks up any run whose label matches `as-served backtest ... calendar-adjusted`. | runs 11, 12, 13 | scripts/accuracy_as_served.py |
| 4 | The first live run of the refresh hook failed (protect_days was passed as 8.0 to an integer parameter). The savepoint kept the other marts; fixed (int()) and re-run. A second signature mismatch would again print FAILED and keep the old decomposition rows rather than fail a data load. | - | analytics/marts.py |
| 5 | The decomposition has no freshness flag in `mart.refresh_status` (no `error_decomposition_stale`). It is rebuilt with every full refresh, so it is as fresh as sales_mart. | - | migration 0063 |
| 6 | Del Monte has no rows (no product-level forecasts); the endpoint says so. Product-level Tier B/C backtests use the Tier A XGBoost pool, as `local/error_direction_analysis.py` did. | - | by design |
| 7 | Adding runs 12 and 13 grew `mart.accuracy_mart` from 20,311 to 37,191 rows and lists two more runs in GET /dashboard/forecast-runs. The accuracy card's default run (label-based) is unchanged. | +16,880 rows | mart.forecast_run |
| 8 | Test failures seen in the files I ran, both already on the 2026-10-21 failing list above: tests/test_planning_mart.py::test_the_live_mart_answers_the_current_cycle_as_the_joins_do and tests/test_marts.py::test_one_month_range_ranking_reproduces_every_stored_abc_run. | 2 | - |

### Update 2026-10-21 (migration 0064)
Item 1 above is resolved: stored safety stock now counts only for an lp_recommendation row with an lp_run (only cycle 2026-03, 109 rows, no actuals yet), so all 21,250 rows are 'rebuilt' and no figure moved (snapshots in local/errdecomp_snapshot_{before,after}_0064.txt, identical md5). Item 7: runs 12/13 are labelled COUNTERFACTUAL; accuracy_mart still holds their 16,880 rows under that label. The decomposition's "all" totals and Tier B/C rows are counterfactual by the same token (response: counterfactual_note, by_tier[].counterfactual).

## Found during the fact-check fixes (2026-10-22)

Anti-loop: noticed, not done (except where the task listed it).

| # | Item | Numbers / where |
|---|---|---|
| 1 | REAL DEFECT, not fixed: the ORM model `ABCClassification` (analytics/db/models.py:333) lacks the live column `added_as_new` (migration 0044) and its method CHECK still lists only 'single','t3m' (live also has 't12m_new'). `tests/test_abc_schema_contract.py::test_model_declares_every_live_column` is right to fail. Nothing reads the model for DDL, so no runtime effect found. | analytics/db/models.py:333-362 |
| 2 | A decided (accepted/dismissed) row counts as plan only if it has any lp_run_key. A decided row carrying an OLDER run's key in the same cycle still counts; today none exists (the cycle has 109 pending rows, all run 5, plus the one run-less accepted row). | backend/lp_cycle.py PLAN_STATUS_SQL |
| 3 | The LP's warehouse constraint is applied to the planned products' stock plus orders (2,663,949 pieces, cycle 2026-03), not the whole warehouse. The whole-warehouse count of 2 Mar 2026 (3,800,930, 812 rows) exceeded the old 3,800,000; the next count (2026-03 period) is 1,685,621, so the two counts are not on one basis (cause not investigated). | inventory_fact_real, Unilever |
| 4 | lp_run 5 stored `warehouse_capacity` 3,800,000 and `default_procurement_cost_per_unit` 25.0 in its inputs. Left as history; the next run records the new values. A dry run with the new values changes no order, safety stock or target (0 of 109). | lp_run.inputs |
| 5 | The default procurement cost is applied to no row this cycle (all 109 have a stock-file price). `storage_cost_per_unit` 0.50 was "2% of 25"; kept, since changing it changes the objective for every product. | analytics/params.py |
| 6 | Per-product files still tracked in reports/ because they hold identifiers plus accuracy metrics, not sales or prices: reports/bakeoff_8020_per_sku_*.csv, ma3_per_sku_tierA.csv/.xlsx, ma3_vs_sba_a3_per_sku_2026-09.csv, model_decision_per_sku_2026-09.csv, experiment_artifacts/routing_*_per_sku_model.csv, diagnostics/model_audit_2026-10-03/p3_per_product.csv, forecast_error_business_2026-10-03/longwindow_per_product_summary.csv, surplus_bias_experiment_2026-10-03/*/per_product_candidates.csv. Also kept: files with revenue_share only (evidence/inputs/*) and first/last-sale-month files (tier_a_basis_2026-10-03/*). A stricter reading of hard rule 9 would untrack these too. | git ls-files reports |
| 7 | tools/dsd_dev_viewer/build.py reads reports/diagnostics/fit_review_common_2026-09-23.csv, now untracked: the working copy stays, but a fresh clone cannot build the viewer. | tools/dsd_dev_viewer/build.py:732 |
| 8 | Category YoY: SCRATCH COOKING AIDS (3 of 17 products) and DRESSINGS (13 of 38) read -100% on the matched basis because products stopped selling; UNCLASSIFIED has 87 products. The published Table 4.2.4 basis is the whole category, not matched products. | local/yoy_table_2026-10-22.txt |
| 9 | docs/ACCURACY_AS_SERVED.md says "computed from code version 3cfee40 (uncommitted changes in scripts/run_baseline_forecast.py)". Those uncommitted lines became 8ddf82d (3 lines added to run_baseline_forecast.py). Cite 8ddf82d. | docs/ACCURACY_AS_SERVED.md:3 |
| 10 | tests/test_planning_mart.py's live test is skipped unless SUPABASE_DB_URL is already in the environment; it ran in the full suite only because an earlier test's import loads .env. Order-dependent, not a defect in the mart. | tests/test_planning_mart.py:287 |
| 11 | The manifest staging/_manifest.json is 14 Sep 2026 and git-ignored; the extraction totals in the manuscript cannot be re-checked by a reader without it. PROJECT_STATE_2026-09.md quotes 2,089,347 rows (8 families) for an earlier build. | reports/CLAIM_CHECK_2026-10-22.md |
| 12 | The LP only solves because of a loosened hold: with `HOLD_SLACK_REL` at 0 the cycle-2026-03 plan has no solution, and the committed retry slack of 1e-7 (analytics/optimization/lp.py, `HOLD_SLACK_REL`, used in `solve_lp`; lowered from 1e-6 on 2026-10-22) leaves two products ordered under their need: 64985759 by 0.033 and 68395711 by 0.009 pieces (0.042 in all; need 431,443.460, orders 431,443.418 before case-pack rounding; at the old 1e-6 it was 0.34, 0.08 and 0.01 = 0.43). The case-pack-rounded plan total is 435,988 at both settings. The slack solved every cycle tried: 2026-03 on the stored forecasts, and 2025-06, 2025-09, 2025-11, 2026-01 and 2026-02 on the as-served backtest forecasts (run 11) with each month's own opening count (a solver check, not stored plans). | Not a business constraint. Checked 2026-10-22 against the live inputs: the first two stages (fill demand, fill safety stock) solve; the third (fill the rest of the target) is Infeasible. Dropping the warehouse ceiling (3,816,842; 1.15M pieces of room) or the allocation ceiling (1,264,829; about 829,000 of room) changes nothing, so neither binds. Dropping `hold_fill_safety_stock` makes it Optimal, and so does loosening all holds to a relative 1e-8, so the binding constraint is that hold: the safety-stock layer is pinned at the sum of its upper bounds (131,954.677 pieces) within about 1e-4, below CBC's own feasibility tolerance on rows of this size. A relative slack of 1e-8 would be enough here; 1e-6 was 100 times larger than needed, which let the cost stage pull 0.43 pieces under need. Changed to 1e-7 on 2026-10-22 (under-need 0.43 -> 0.042 pieces); still under one piece in 431,443. | analytics/optimization/lp.py (`HOLD_SLACK_REL`, `solve_lp`), scratch probe `infeas_probe.py` |

## Two cover measures, two windows (recorded 2026-11-03)

Both are Unilever pieces over pieces. They differ in how much history the sales average covers, so the two pages can read differently. Neither is wrong.

| | Dashboard: weeks of cover | Reorder page: days of cover |
|---|---|---|
| Grain | Portfolio | One product |
| Stock | Pieces at the count | Pieces at the cycle's opening count |
| Sales window | **12 months** up to the count | **3 sales months** up to the count (`SKU_COVER_HISTORY_MONTHS`); a month with no sales counts as 0 |
| Rate | Average pieces per week | Average pieces per month ÷ 30.44 calendar days (`DAYS_PER_MONTH`) |
| Code | `backend/marts.py` (`weeks_of_cover`), tooltip in `frontend/src/components/Dashboard.jsx` | `backend/routers/recommendations.py` `_cover`, notes in `ReorderRecommendations.jsx`, `ReorderModal.jsx` and `SKUForecast.jsx` |

Neither reads the forecast. Del Monte has no pieces, so its Dashboard card stays in pesos. The list behind the Dashboard's "Above the rule" card also stays in pesos, and says so in its tooltip.
