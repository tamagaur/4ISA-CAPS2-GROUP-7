# System coverage matrix: classification, predictive, prescriptive

Generated: **2026-10-21** (UTC, read-only queries against the live `public` and `demo` schemas, `BEGIN; SET TRANSACTION READ ONLY; ... ROLLBACK`).
Code at generation: `99d70d9` (branch `kelvin/freeze-package`).
Regenerate: `PYTHONUTF8=1 python scripts/run_sql.py scripts/sql/coverage_matrix.sql` (every figure below is one of its statements; the run ids are pinned at the top of that file).

## Runs this table reflects

| Path | Run | Created (UTC) | Notes |
|---|---|---|---|
| Unilever real, forecast | `Forecast_Result` batch `run.written_at` 2026-10-20T13:55:49Z, rows `generated_at` 2026-10-20 13:56:07; code `46d832d`, calendar factor on | 2026-10-20 13:56 | `Forecast_Result` has no run-id column; the batch is identified by its `generated_at` and `model_params.run`. 189 rows, one batch. |
| Unilever real, order plan | `lp_run.run_key = 4`, planning cycle 2026-03-01, scope `both` | 2026-10-20 13:58:17 | Rows in `lp_recommendation` with `lp_run_key = 4`. All 109 are Unilever. |
| Unilever synthetic | `demo.run.run_id = 12` | 2026-10-20 14:00:27 | Latest Unilever demo run, the one the API serves (`MAX(run_id)`, `backend/demo_data.py:58-61`, `backend/data_mode.py:115`). Runs 10 and 11 also exist: all three have the same sales (6,370 rows, 189 SKUs) and forecast (180) counts; the order plan has 96 SKUs in run 10 and 106 in runs 11 and 12. |
| Del Monte real | none | n/a | No Del Monte row in `Forecast_Result` or `lp_recommendation`. |
| Del Monte synthetic | `demo.run.run_id = 7` | 2026-10-16 07:10:10 | Only Del Monte demo run. |

## The table

As-of periods: ABC cohort = **2026-02** on the deployed Tier A basis `t12m_new` for Unilever (`analytics.params.TIER_A_BASIS`); Del Monte = **2025-12** on `single` (its latest period). Forecast and order plan = **2026-03** for Unilever, **2026-01** for Del Monte synthetic.

| | Unilever real | Unilever synthetic | Del Monte real | Del Monte synthetic |
|---|---|---|---|---|
| **CLASSIFICATION** | | | | |
| Unit classified | **SKU** (`Product_Dimension.grain = 'sku'`) | none: `demo` has no classification table. The cohort is borrowed from the real Tier A list (see Q1) | **Category** (`grain = 'category'`) | none: `demo` has no classification table |
| Classified, total | 1,091 | none (no classification of its own) | 4 | none |
| Tier A | 189 | none (the 189 SKUs in its sales table are the real Tier A) | 1 | none |
| Tier B | 230 | none | 1 | none |
| Tier C | 672 | none | 2 | none |
| Classification period | 2026-02, method `t12m_new` | none (inherits 2026-02 `t12m_new`) | 2025-12, method `single` | none |
| **PREDICTIVE** | | | | |
| Forecasts produced | 189 | 180 | none: Del Monte has no per-product forecast, no real row exists | 5 (categories) |
| Of which Tier A | 189 | 180 (all inside the real Tier A, 2026-02 `t12m_new`) | none | none: no tiers |
| Status `ok` | 175 (14 are not `ok`: 9 `insufficient_data`, 5 `dead_sku`) | none: the demo table has no status column | none | none: no status column |
| Pass the gate (MASE < 1.0) | 109 | none: no accuracy metric exists in `demo` by rule (CLAUDE.md rule 2) | none | none: same |
| Fail the gate | 66 (all of them `ok` rows with MASE >= 1.0; no `ok` row has a NULL MASE) | none | none | none |
| Forecast exactly zero | 12 (5 `dead_sku` zero-by-design, 7 `ma3` rows with status `ok`) | 2 | none | 0 |
| Models, with counts | `xgb_ma3_avg` 104, `ma3` 37, `tsb` 34, `trailing_average` 9, `zero_no_order` 5 | `ma3` 180 | none | `ma3` 5 |
| Forecast period | 2026-03 (all 189) | 2026-03 for 166; 14 forecast an earlier month (2025-09 1, 2025-10 1, 2025-11 1, 2025-12 3, 2026-01 3, 2026-02 5): each is the month after that series' last real month | none | 2026-01 (all 5) |
| **PRESCRIPTIVE** | | | | |
| In the order plan | 109 SKUs | 106 SKUs | none: no real LP, forecast and cost inputs do not exist | 5 categories |
| Order above zero | 73 | 60 | none | 5 |
| Total quantity | 426,982.66 **pieces** | 301,979.21 **pieces** (stock is the real count, `stock_source = 'real'`) | none | 16,063.74 **units, not labelled**: the schema and code do not say pieces or cases (`analytics/params.py:237` says only that Del Monte's sell-out "has no pieces") |
| Run id, created | `lp_run` 4, 2026-10-20 13:58:17 UTC | `demo.run` 12, 2026-10-20 14:00:27 UTC | none | `demo.run` 7, 2026-10-16 07:10:10 UTC |
| Planning cycle | 2026-03-01 | 2026-03 | none | 2026-01 |

Other Unilever classification bases at 2026-02, for reference only (not the deployed Tier A basis): `single` 132 / 194 / 384 (A/B/C, 710 total); `t3m` 143 / 215 / 485 (843 total). Del Monte at 2024-02, the last period before the January 2025 taxonomy break, `single`: 14 A / 17 B / 32 C (63 categories).

Del Monte synthetic coverage beyond the table: `demo.dm_category_sales` and `demo.dm_category_param` hold 82 category paths. 5 are forecastable (the five live 2025 categories), 77 are `series_ended_before_window_end` and carry no forecast on purpose, and 5 more paths are in `demo.dm_excluded` (one month between first and last real month, so no level or CV to generate from).

Real order plan, for context: the 109 SKUs in `lp_run` 4 are exactly the Tier A forecasts that pass the gate (status `ok` and MASE < 1.0 = 109). All 109 are `pending`.

## Answers

**1. Is the synthetic Unilever cohort restricted to Tier A by design?** Yes, in two places.
- [scripts/build_unilever_demo.py:60-76](../scripts/build_unilever_demo.py#L60-L76): the read of real sales joins `ABC_Classification` with `abc.tier = 'A'`, at the latest classification period on the deployed basis (`abc_method('unilever')`). Its header (lines 25-28) states the intent: the demo shows the same system as the real path, not a wider scope. The real path does the same in [scripts/run_baseline_forecast.py:171-180](../scripts/run_baseline_forecast.py#L171-L180) (`fetch_tier_a`, `abc.tier = 'A'`).
- [scripts/run_lp.py:1040-1054](../scripts/run_lp.py#L1040-L1054): for `--source demo`, a SKU is kept only if its real `Forecast_Result` row has status `ok` and MASE < 1.0 (the same test as the real LP's `CANDIDATE_QUERY`, line 205-228, which also requires `ac.tier = 'A'`). Only the SKU list crosses into `demo`, never the metric.
- Observed: all 189 SKUs in `demo.unilever_sku_sales` (run 12), all 180 in the demo forecast and all 106 in the demo order plan are in Tier A (`t12m_new`, 2026-02). No other tier is present. The cohort is not frozen: it follows Tier A as of the period at the time of each rerun.

**2. Does Del Monte classify by category rather than SKU on both paths?** Real: yes. All 673 Del Monte rows in `ABC_Classification` join to `Product_Dimension.grain = 'category'`, and there are no Del Monte rows at any other grain (queried over the whole table; all are method `single`). Synthetic: there is no classification at all, so the statement does not apply. The demo tables are keyed on `category_path`, so its forecasts and plan are category grain too. `build_dm_demo.py` contains no tier logic.

**3. Are the Unilever real and synthetic cohorts the same product set?** Nearly, and the synthetic is a subset.

| Set (product_key, as of the runs above) | Count |
|---|---|
| Real forecasts (`Forecast_Result`) | 189 |
| Synthetic sales cohort (`demo.unilever_sku_sales`, run 12) | 189, all 189 also in the real forecasts |
| Synthetic forecasts (`demo.unilever_sku_forecast`) | 180, all 180 also in the real forecasts |
| Real forecasts missing from the synthetic forecasts | 9, all with real status `insufficient_data` |
| Synthetic forecasts not in the real forecasts | 0 |
| Real order plan (`lp_run` 4) | 109 |
| Synthetic order plan (`demo.unilever_sku_lp`) | 106, all 106 also in the real plan |
| Real order plan SKUs missing from the synthetic plan | 3 (109 - 106; not decomposed further here) |

The two cohorts are the same Tier A list (189) at the sales level; they diverge downstream by 9 SKUs at the forecast step (the synthetic path has no forecast where the real one is `insufficient_data`) and by 3 more at the order plan.

## Things to know before quoting this

- **Stale line in CLAUDE.md.** It says the Del Monte demo order plan has "2 of 5 order >0". The database (run 7) has 5 of 5 above zero, 16,063.74 in total. This table uses the database. I did not edit CLAUDE.md.
- **Cohorts move.** ABC counts depend on the period and basis; every figure above carries both. A later forecast or LP run will change the Unilever real and synthetic columns.
- **The Unilever forecast period is not uniform in the synthetic path** (166 of 180 at 2026-03). The real path is uniform (189 of 189).
- **The 3-SKU gap between the real and synthetic order plans** is reported as a count only. Per-product detail stays out of git (rule 9).
- **Del Monte order unit is unlabelled** in the schema and code. Do not call it cases or pieces in the manuscript until SSM confirms the source unit.
