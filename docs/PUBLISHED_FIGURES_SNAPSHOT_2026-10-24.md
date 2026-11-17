# Published accuracy figures, pinned (2026-10-24)

Why: `mart.accuracy_mart` and `mart.error_decomposition` read real sales at every mart refresh, so loading March 2026 would have moved every figure the manuscript quotes, with no trace. These are pinned to the data they used. Machine-readable copy: `PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json` (aggregates only, with the sha256 of every input). Per-product input rows are in `docs/published_snapshot_2026-10-24/`, tracked and trimmed to the columns the check reads (hard rule 9 exception of 2026-10-23: these figures are published). Product keys, months and quantities only; no prices, names or safety-stock values.

**Actuals version: `actuals-2026-02-b31bf58d9b5e`** (Unilever per-SKU sales through 2026-02, 24,906 rows; the md5 of one month:rows:pieces:pesos line per calendar month, `analytics/actuals_version.py`). Mart refresh 61 (2026-11-10 13:18 UTC; re-pinned 2026-11-10, see below). Unilever sales have no `etl_load_event` rows, so a content fingerprint is the version key.

## Figures pinned

Re-pinned 2026-11-10 (twice that day, each with its own change): first for succession + fading served (the MASE and headline
rows); then for the error decomposition, which now reads the treated backtest (runs 16, 17, 18, label "... succession + fading,
calendar-adjusted") instead of the untreated runs 11, 12, 13 (27 decomposition figures moved). The March-impact table below is
of 2026-10-24 and still describes run 11; rerun `--march-impact` for today's.

As of 2026-11-17 the rows below are the JSON's, re-pinned 2026-11-12 (163b42f, the calendar factor per product; mart refresh
74). Until 2026-11-17 this table still showed the 2026-11-10 values (110 of 175, median 0.823; 37.88% / 29.69% / 10.77%;
17.44%), two re-pins behind its own JSON. `--verify` reads the JSON, never this table. The six evaluation metrics (MAE, RMSE,
MAPE, WAPE, MASE on the backtest, R²) are pinned separately: `docs/EVALUATION_METRICS.md`.

| Figure | Value | Source |
|---|---|---|
| MASE < 1, Tier A (2026-02, `t12m_new`) | 115 of 175 (65.7%) | `Forecast_Result` for 2026-03, status ok: the stored holdout MASE (plan entry test), not the backtest MASE of `EVALUATION_METRICS.md` |
| Median MASE | 0.755 | same |
| Median product WAPE, as served / calendar-adjusted | 38.55% / 36.37% | as-served backtest rows, 310 products / 4,370 product-months (scored months 2024-01..2026-02) |
| Pooled WAPE (pieces) | 30.12% / 28.87% | same; the calendar-adjusted figure is `EVALUATION_METRICS.md`'s full-span WAPE over every scored product |
| Total WAPE (pesos) | 10.02% / 8.70% | same |
| Error split, Tier A, pieces (over / absorbed by safety stock / beyond) | 9,389,241 / 5,083,650 / 3,096,724 | `mart.error_decomposition_row`, 4,370 product-months |
| Exceedance: product-months where demand beat the forecast by more than safety stock | **19.50%** (852 of 4,370) | same |
| Pesos beyond safety stock, Tier A | **₱43,767,343** | same |

The verbatim headline, MASE and per-route tables of `ACCURACY_AS_SERVED.md` are stored in the JSON with the document's hash.

Reproduce: `python -m scripts.snapshot_published_figures --verify` recomputes 51 figures from the frozen rows (no database write) and fails on any difference or on a changed input file. Since 2026-11-16 it also recomputes every pinned figure from live and FAILS on a moved actuals version or any live figure that differs (exit 3 when live cannot be read); re-pinning (`--write`) is a decision. `scripts/check.sh` runs it.

## What loading March 2026 would change (`--march-impact`, nothing loaded)

March actuals are unknown, so the effect is bracketed by the best and worst month already scored. Tier A, decomposition basis (calendar-adjusted run 11).

| Figure | Today | After March (range) | Why |
|---|---|---|---|
| Scored Tier A product-months | 4,370 | +175 (4.0%) | 175 ok March forecasts get an actual |
| Exceedance rate | 17.14% | 16.57% to 18.10% | March at the best (2.2%) or worst (42.2%) monthly rate so far |
| Pooled WAPE (pieces) | 32.46% | 31.97% to 33.66% | monthly range 17.0% to 69.8% |
| Pesos beyond safety stock | ₱38,187,551 | ₱38.22M to ₱42.43M | March's own beyond-pesos, best to worst month |
| Every peso figure of every old month | as above | of order 0.04% | price per piece is pooled over scored months, so one more month moves it (measured by dropping a month: median product price 0.00%, max 3.36%) |
| MASE 109 of 175, median 0.827 | stored | **unchanged** | stored on `Forecast_Result`; changes only when the runner is rerun |
| Stored forecasts (`mart.forecast_run_value`, runs 1 to 13) | frozen | **unchanged** | never rebuilt |
| `ACCURACY_AS_SERVED.md` | window to 2026-02 | every row moves | recomputed over a window to 2026-03 |

## Stamps now on every published figure

`actuals_version` (key, latest actual month, row count, fingerprint, mart refresh id and time) is returned by `GET /dashboard` (`forecast_accuracy`), `GET /dashboard/accuracy`, and every `GET /dashboard/error-decomposition*` route, and printed at the top of `ACCURACY_AS_SERVED.md` when the script regenerates it.
