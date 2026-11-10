# Challenger forecast: diagnosis, choice, storage, comparison (2026-11-10)

Aggregates only (rule 9). Per-product rows are in the git-ignored `local/`. Nothing here changes what is served: the plan,
`Forecast_Result`, the LP and every API answer are untouched.

| Step | Where | Commit |
|---|---|---|
| Signed-error diagnosis (read-only) | `scripts/forecast_bias_diagnosis.py` | d147951 |
| Selection rule, written **before** any comparison | `docs/CHALLENGER_SELECTION_RULE.md`, `analytics/forecasting/selection_rule.py` | fe9ed9d |
| Challenger definition | `analytics/forecasting/challenger.py` (`damped_trend_v1`) | fe9ed9d |
| Storage | migration `0076_forecast_challenger.sql` (table `forecast_challenger`) | b744acf |
| Compute, store, compare | `scripts/challenger_forecast.py` | b744acf |

## 1. Diagnosis: which way the forecast misses, Sep 2025 - Feb 2026

Source: the Dashboard card's own scored rows (`backend.marts.accuracy_rows_query`). Calendar on = `mart.forecast_run` 11, the
card's default (as-served backtest, calendar-adjusted); calendar off = run 10. 208 products, 1,078 product-months.

| Signed error (forecast - actual) | Calendar on | Calendar off |
|---|---|---|
| Products with a positive mean error | **162 of 208** | 160 |
| Products with a negative mean error | 44 | 46 |
| Product-months over-forecast | 62.4% | 61.1% |
| Net bias, pooled (sum of errors / sum of actuals) | **+13.9%** | +12.6% |
| Positive mean AND over in most of their months | 120 | 117 |
| Over in 6 of 6 months (148 products have 6 scored months) | 13 (2.3 if no bias) | 10 |
| Over in 5 or 6 of 6 months | 34 (16.2 if no bias) | 32 |

**"Too high 3 or more months in a row" (the card's flag): 61 products**, 49 with the calendar factor off. All 49 are inside
the 61. If each month were over or under at random with the observed 62.4% chance of over, about **46** would carry the
flag (189 products have 3 or more months). With no bias at all, about 24 would. Most of the flag is therefore one general
upward bias, not 61 separate product failures.

Why the forecast runs high: the company total in pieces stepped down. Mar-Jun 2025 averaged 2,821,365 pieces a month;
Jul 2025 - Feb 2026 averaged 2,099,503 (Dec 2025 1,350,508, Feb 2026 1,766,710). Every served model forecasts from a
trailing level (MA3, TSB, and XGBoost averaged with MA3), so each follows that fall a step behind.

Mechanism tests on the 61 flagged runs. Each run was recomputed through `router.route()`; the max gap to the mart's stored
forecast was 0.0 pieces over 280 rows.

| Test | Definition | Products |
|---|---|---|
| (a) **lag on a decline** | the forecast before the calendar factor falls at every step of the run, and the run's sales sit below the 3 months before it | **26** |
| (b) one spike | replacing the 3-month average inside the forecast by the median of the same 3 months breaks the run | **4** of 38 testable (23 runs are TSB-served, which has no 3-month window) |
| (c) calendar factor | without the factor, one of the last 3 months is no longer too high | **12** (the 61 - 49 difference) |
| none of the three | | 16 |

Combinations: decline alone 11, decline with an untestable spike 14, decline + calendar 1, calendar alone 7, calendar + spike
1, calendar with an untestable spike 3, spike alone 3, untestable spike alone 5, none 16. The calendar factor tips 12
products into the flag, but carries only **2.6%** of the over-forecast pieces in the 61 runs.

**Named mechanism: (a), lag on a falling level.** It shows at company level (a fall of about a quarter in pieces from July
2025) and directly in 26 of the 61 runs. (b) explains 4. (c) is a threshold effect: it moves 12 products over the line but
adds little volume.

## 2. Accuracy with the calendar factor OFF

| Measure | Window | Calendar on | Calendar off |
|---|---|---|---|
| MASE < 1 (stored-MASE protocol, Tier A as of 2026-02) | holdout | **109 of 175** (median 0.827; equals the stored and pinned 109) | **101 of 175** (median 0.902) |
| Typical product, weighted (pooled WAPE, pieces) | Sep 2025 - Feb 2026 | 41.74% | 42.45% |
| Median product WAPE | Sep 2025 - Feb 2026 | 37.49% | 38.76% |
| Company total (pesos) | Sep 2025 - Feb 2026 | 13.34% | 13.27% |
| Net bias (pieces) | Sep 2025 - Feb 2026 | +13.9% | +12.6% |
| Too high 3+ months in a row | Sep 2025 - Feb 2026 | 61 | 49 |
| Typical product, weighted (pooled WAPE, pieces) | 2023-10 - 2026-02 | 32.51% | 32.96% |
| Median product WAPE | 2023-10 - 2026-02 | 43.27% | 40.77% |
| Company total (pesos) | 2023-10 - 2026-02 | 12.24% | 11.31% |
| Net bias (pieces) | 2023-10 - 2026-02 | +7.8% | +7.5% |

The whole-window rows score against the raw net quantity, as the card does. They equal the "raw net quantity" sensitivity
rows of `docs/ACCURACY_AS_SERVED.md` (43.27% / 40.77% median, 12.24% / 11.31% company total). The factor lowers the pooled
error and raises the MASE pass count. It raises the median product error over the whole window, and the bias and the
flag count in Sep - Feb.

## 3. The challenger and why

See `analytics/forecasting/challenger.py`. Damped-trend exponential smoothing for products with 12 or more sales months;
MA3, identical to the served model, for 3-11. The guards, zero floor, calendar factor and dead-SKU rule match the served
model. It was chosen because a trend term addresses lag on a falling level, the named mechanism. A median of 3 addresses a
single spike (4 products), and a different model family would not target the mechanism at all. Disclosed: damped Holt was in the 2026-09 bake-off and was
not better than MA3 there (median MASE 0.854 against 0.819).

## 4. Selection rule

`docs/CHALLENGER_SELECTION_RULE.md`, committed in fe9ed9d before any comparison. In short: once a year at the Dec/Jan
turn, over January to December of the closing year, never 2025-09 to 2026-02, with at least 6 months. Measure: pooled
WAPE in pieces. The challenger is recommended only if it is lower over the window, lower in both halves, and the 95%
product-bootstrap interval of the difference is entirely below zero. The verdict switches nothing.

## 5. Stored and scored

`forecast_challenger` (migration 0076), written by `scripts/challenger_forecast.py` at b744acf:

| Kind | Rows | Months | Reproduce check of the served side |
|---|---|---|---|
| backtest | 4,370 (310 products) | 2024-01 - 2026-02 | equals the stored as-served calendar-adjusted run (the card's default) row for row: 0 missing either side, max gap 0.0 pieces |
| cycle | 180 (175 ok + 5 dead-SKU) | 2026-03 | route() rerun equals `Forecast_Result.forecast_value` on all 175 ok rows, max gap 0 (checked on live, read-only, and on the copy) |

The stored run labelled 2023-10..2026-02 holds no rows before 2024-01, so the backtest starts there. Challenger methods in
the backtest: damped trend 3,111, MA3 1,169 (short bin, plus 217 guard fallbacks), dead-SKU zero 90. For March 2026 the
challenger totals 1,902,947 pieces against the served 2,017,571 (-5.7%; 11 guard fallbacks). That is a forecast with no
actual yet, not a comparison.

**Where it is stored: on the throwaway copy only** (`ssm_challenger` on 127.0.0.1:55432, a restore of
`backups/full_backup_20261104T175951Z`, with 0075 and 0076 applied). Not on live: the migration runner applies every
pending migration, and 0075 (Data API lockdown) is pending Kelvin's go. Putting it on live takes three steps: apply 0075 + 0076 with the runner,
then `challenger_forecast backtest --write --target-public` and `cycle --write --target-public`. After each future
forecast run, run `cycle --write`. It is not wired into `scripts/run_month.py`: that file is hashed by the month-load
attestation (`scripts/demo_rehearsal.FILES`), so an edit there would invalidate `docs/MONTH_LOAD_REHEARSAL.json`.

### The rule applied at past turns (run after fe9ed9d; evidence only, switches nothing)

| Turn | Months | Product-months | Pooled WAPE served | Pooled WAPE challenger | Delta | Halves | 95% interval of Delta | Verdict |
|---|---|---|---|---|---|---|---|---|
| 2023/2024 | none (no rows before 2024-01) | - | - | - | - | - | - | insufficient: served stays |
| 2024/2025 | 2024-01 - 2024-12 | 1,963 (242 products) | 31.23% | 34.27% | **+3.05 pts** | +2.06 / +4.25 | [+0.70, +4.97] | **served** (challenger worse, significantly) |
| 2025/2026 | 2025-01 - 2025-08 | 1,329 (207) | 29.34% | 29.94% | +0.60 pts | -0.48 / +1.87 | [-1.32, +2.29] | **served** (no difference shown) |
| 2026/2027 (first scheduled) | none yet: no real month after 2026-02 | - | - | - | - | - | - | insufficient until 6 of 2026-03 - 2026-12 are loaded |

Beside the verdict, not deciding it:

| Turn | | Median product WAPE | Net bias | Surplus share of miss | Too high 3+ in a row |
|---|---|---|---|---|---|
| 2024/2025 | served | 37.26% | +7.93% | 62.7% | 44 |
| 2024/2025 | challenger | 37.73% | +7.55% | 61.0% | 33 |
| 2025/2026 | served | 26.71% | +4.14% | 57.1% | 47 |
| 2025/2026 | challenger | 29.45% | +3.56% | 55.9% | 48 |

Reading: the trend term removes a little of the upward bias (and in 2024 a quarter of the 3-in-a-row runs) but adds more
error than it removes. On the months the rule may use, it does not beat the served forecast. The served forecast stays.
Whether it is worth looking for a different challenger is the team's call: the rule allows a new one only if it is committed
before the next turn.
