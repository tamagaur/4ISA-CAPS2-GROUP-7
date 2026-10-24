# Published accuracy figures, pinned (2026-10-24)

Why: `mart.accuracy_mart` and `mart.error_decomposition` read real sales at every mart refresh, so loading March 2026 would have moved every figure the manuscript quotes, with no trace. These are pinned to the data they used. Machine-readable copy: `PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json` (aggregates only, with the sha256 of every input). Per-product input rows are in the git-ignored `local/published_snapshot_2026-10-24/` (hard rule 9).

**Actuals version: `actuals-2026-02-b31bf58d9b5e`** (Unilever per-SKU sales through 2026-02, 24,906 rows; the md5 of one month:rows:pieces:pesos line per calendar month, `analytics/actuals_version.py`). Mart refresh 41 (2026-10-22 14:25 UTC). Unilever sales have no `etl_load_event` rows, so a content fingerprint is the version key.

## Figures pinned

| Figure | Value | Source |
|---|---|---|
| MASE < 1, Tier A (2026-02, `t12m_new`) | 109 of 175 (62.3%) | `Forecast_Result` for 2026-03, status ok |
| Median MASE | 0.827 | same |
| Median product WAPE, as served / calendar-adjusted | 40.22% / 42.56% | frozen as-served rows (`ACCURACY_AS_SERVED.md`, headline) |
| Pooled WAPE (pieces) | 32.92% / 32.46% | same |
| Total WAPE (pesos) | 11.17% / 12.09% | same |
| Error split, Tier A, pieces (over / absorbed by safety stock / beyond) | 12,242,746 / 4,847,983 / 2,669,295 | `mart.error_decomposition_row`, 4,370 product-months |
| Exceedance: product-months where demand beat the forecast by more than safety stock | **17.14%** (749 of 4,370) | same |
| Pesos beyond safety stock, Tier A | **₱38,187,551** | same |

The verbatim headline, MASE and per-route tables of `ACCURACY_AS_SERVED.md` are stored in the JSON with the document's hash.

Reproduce: `python -m scripts.snapshot_published_figures --verify` recomputes 51 figures from the frozen rows (no database write) and fails on any difference or on a changed input file. It also says whether the live actuals have moved since; a moved version never changes the pinned figures.

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
