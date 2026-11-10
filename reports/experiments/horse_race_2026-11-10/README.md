# Forecast horse race, 2026-11-10 (backtest only)

Script: `run_horse_race.py` (reads only the throwaway copy `ssm_challenger`, a restore of the 2026-11-04 backup; writes
files). Aggregates: `results_table.csv` and `results_decjan.json`. Per-product rows are in the git-ignored `local/`.
Nothing served, planned or pinned changed.

**Frame.** The product-months of the stored as-served backtest (Tier A the month before), 4,370 rows over 2024-01 to 2026-02.
Every approach forecasts the same rows one step ahead, **from data strictly before the month**: the product's series,
company and category totals, and, for error feedback, only forecasts and actuals of earlier months. No setting was tuned on
any scored month. The windows are fixed 3-month ones, statsmodels' own estimates, and the calendar module's settings. The
actual is the as-served one: no row = 0, a net-negative month = 0, a blank month is not scored. That puts the served bias at
+13.8% in the main window; the card's +13.9% scores against raw net quantities.

**Metrics, each named.**
- **Pooled WAPE** = sum |f - a| / sum |a|.
- **MAPE** = the median over products of each product's mean |f - a| / a over its months with a > 0 (`diagnostic_metrics.mape`).
- **MASE** = the median over products of mean |f - a| / the product's naive scale, which is computed on its history before the window.
- **Bias** = sum (f - a) / sum |a|.
- The "vs served" interval is a 95% product bootstrap (2,000 draws).

**Product sets.**
- "All": every product in the window, 208 in Sep 2025 - Feb 2026.
- "Planned": the 109 products of the March 2026 plan (lp_run 6). 106 of them are in the main window and 89 in the earlier one; the other 3 have no scored month.

## Verdict

**No approach wins in a way that survives a second window.** The main-window winner trips the gate in substance. Its
forecasts are not fitted on the months scored. But its win is specific to those months, and it does not hold over the 20 months before.

| Approach | Main window, all | Main window, planned | Earlier window, all | Earlier window, planned |
|---|---|---|---|---|
| Top-down, company total, YoY seasonal naive | -2.21 pts [-5.84, +0.87] | -2.95 pts [-6.61, -0.41] | -0.56 [-2.06, +0.42] | **+0.88 [+0.45, +1.41] worse** |
| Top-down company YoY x error feedback (best in main) | -3.50 [-7.74, -0.10] | -3.19 [-7.39, -0.19] | **+1.05 [-0.70, +2.15]** | **+2.47 [+1.95, +2.98] worse** |
| Served x error feedback | -2.15 [-3.82, -0.66] | -0.47 [-2.10, +1.12] | **+1.08 [+0.22, +1.82] worse** | +0.38 [-0.31, +1.00] |
| Mean of served and top-down company YoY (most consistent) | -1.57 [-3.45, +0.03] | -1.93 [-3.74, -0.71] | -0.58 [-1.34, -0.07] | +0.15 [-0.06, +0.42] |

The most consistent approach is the plain mean of the served forecast and the top-down forecast. Its difference from served runs from 1.93 points better to 0.15 worse
across the four cells. That margin is inside or at the edge of the noise and too small to
matter for the plan. It is not a winner to quote. Pooled WAPE is the measure here because the review rule uses it; MAPE and
MASE by approach are in the tables below.

**Why top-down wins December 2025 and loses December 2024.** It sets this December from last December, scaled by the
year-over-year level. December fell in 2024 (0.68x its three prior months) and fell again in 2025 (0.62x), so in 2025 it
copied the right shape: December pooled WAPE 44.2% against the served 56.7%. In 2023 December rose (1.20x), so in 2024 it
copied the wrong shape: +8.9 pts worse than served [+2.6, +13.4].

## December and January: is there a real effect?

| | 2023/24 | 2024/25 | 2025/26 |
|---|---|---|---|
| December / mean(Sep-Nov), company pieces | **1.195** | 0.681 | 0.624 |
| January / mean(Oct-Dec), company pieces | 1.339 | 1.287 | 1.354 |
| Share of products below their prior-3 mean in December | (before the frame) | 89.6% | 91.7% |
| Share in January | 33.1% | 33.2% | 37.1% |

The share in other months has a median of 58.7% and a range of 35.2% to 87.5%.

- **January: a real, repeatable peak.** It is the highest month-over-prior-3 ratio of the year in all three years, in a
  tight band (1.29 to 1.35), and the fewest products fall in January. Part of it is arithmetic: the prior three months
  include the December dip. The served forecast already handles January. Its January bias is +0.5% in 2026, and January
  pooled WAPE (46.4%) is close to its six-month figure (41.5%).
- **December: not established.** It was a trough in 2024 and 2025, when about 90% of products fell (the most of any month
  in those years), but a rise in 2023. Three Decembers cannot separate a seasonal trough from two bad years. December is
  where the served forecast fails worst: bias +42.6% in Dec 2025 and +68.9% in Dec 2024. In Dec 2024 the served forecast
  (56.7% pooled WAPE in 2025, 69.8% in 2024) was far worse than plain MA3 (50.5%). Its calendar factor for December learned
  from the 2023 rise and pushed the forecast up; at full strength (unshrunk) it is worse still, 84.4%.
- So December is partly a real effect in the last two years and partly the month where a lagging model hurts most. The
  data cannot yet say which dominates. Nothing tried predicts December in both years.

## Dead ends, one line each

- **Weekly grain: impossible.** No per-product data exists below monthly. The daily SSIS sheets have no product column
  (all 106 raw files read, 2026-09), and the only per-SKU file is monthly (40 months, zero day-level values).
- **Combination of MA3, TSB, seasonal naive and damped trend:** worse than served in both windows (+5.73 pts main,
  +2.75 earlier). TSB and seasonal naive drag it up.
- **Seasonal naive alone:** worst in every cell (+29.9 pts main).
- **Holt-Winters on the company total, allocated top-down:** the best in the earlier window (-1.28 pts, where it mostly
  falls back to MA3 for want of 24 months) and +9.67 pts worse in the main window.
- **Category totals instead of the company total:** no better than served over six months (+0.02 pts). Best in December
  and January of the main window, worse in both the earlier December and the earlier six months.
- **Calendar factor at full strength:** a tie over six months in both windows, worse in Dec 2024 (+14.7 pts), better in Dec
  2025 (-3.7 pts).
- **Product's own December/January ratio:** worse or tied everywhere (+2.23 pts earlier).
- **Error feedback** (scaling the forecast by the company's actual/forecast over the last 3 months): it removes the bias
  in the main window (+13.8% to -0.2%) and wins there. It loses in the earlier window, where the bias was smaller and it
  over-corrects.

## Tables

### Main window, all products

| Approach | 6 months: pooled WAPE | 6 months: MAPE | 6 months: MASE | December: pooled WAPE | December: MAPE | December: MASE | January: pooled WAPE | January: MAPE | January: MASE | 6 months: bias | vs served, pooled WAPE (95% interval) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Top-down company YoY x error feedback | 38.0% | 36.8% | 0.688 | 44.1% | 33.4% | 0.416 | 48.6% | 30.8% | 0.726 | -3.0% | -3.50 pts [-7.74, -0.10] |
| Top-down, company total, YoY seasonal naive | 39.3% | 40.9% | 0.705 | 44.2% | 32.8% | 0.528 | 48.9% | 26.0% | 0.721 | +9.1% | -2.21 pts [-5.84, +0.87] |
| Served x company error feedback (last 3 months) | 39.4% | 39.1% | 0.754 | 49.6% | 40.7% | 0.654 | 47.3% | 30.7% | 0.768 | -0.2% | -2.15 pts [-3.82, -0.66] |
| Mean of served and top-down company YoY | 40.0% | 44.7% | 0.744 | 48.1% | 42.1% | 0.664 | 47.6% | 26.0% | 0.683 | +11.4% | -1.57 pts [-3.45, +0.03] |
| Served (as live: router + calendar factor) | 41.5% | 44.4% | 0.776 | 56.7% | 54.4% | 0.809 | 46.4% | 27.4% | 0.707 | +13.8% | - |
| Top-down, category total, YoY seasonal naive | 41.6% | 48.0% | 0.833 | 43.2% | 34.5% | 0.492 | 42.9% | 27.0% | 0.631 | +10.2% | +0.02 pts [-3.95, +2.90] |
| Served, calendar factor unshrunk | 41.6% | 45.9% | 0.780 | 53.0% | 46.9% | 0.779 | 47.8% | 24.4% | 0.728 | +15.1% | +0.06 pts [-1.15, +1.17] |
| Served + product's own Dec/Jan ratio | 41.7% | 47.1% | 0.777 | 58.1% | 41.3% | 0.620 | 46.1% | 33.3% | 0.861 | +15.3% | +0.14 pts [-1.38, +1.69] |
| MA3 | 41.8% | 50.5% | 0.876 | 63.3% | 79.9% | 1.041 | 50.8% | 38.7% | 0.897 | +9.6% | +0.26 pts [-2.58, +2.76] |
| Served, calendar factor off | 42.2% | 46.3% | 0.815 | 60.5% | 61.3% | 0.905 | 47.5% | 31.3% | 0.788 | +12.5% | +0.71 pts [-0.45, +1.89] |
| Combination incl. top-down company YoY | 44.8% | 50.0% | 0.844 | 62.0% | 63.8% | 0.890 | 47.4% | 27.4% | 0.806 | +18.5% | +3.29 pts [+0.60, +6.41] |
| Combination: mean of MA3, TSB, seasonal naive, damped trend | 47.3% | 52.7% | 0.867 | 70.0% | 71.5% | 0.996 | 47.7% | 27.7% | 0.790 | +20.8% | +5.73 pts [+2.20, +10.02] |
| TSB | 48.3% | 52.6% | 0.924 | 79.4% | 82.2% | 1.216 | 49.8% | 34.9% | 0.897 | +20.1% | +6.81 pts [+3.11, +11.25] |
| Top-down, company total, Holt-Winters | 51.2% | 56.9% | 1.097 | 68.2% | 86.9% | 1.110 | 75.5% | 70.4% | 1.734 | +4.4% | +9.67 pts [+5.24, +13.61] |
| Naive (last month) | 51.9% | 58.9% | 1.019 | 76.5% | 79.6% | 0.961 | 56.6% | 56.1% | 1.249 | +6.6% | +10.36 pts [+4.15, +15.46] |
| Seasonal naive (same month last year) | 71.4% | 54.2% | 1.097 | 88.0% | 51.5% | 0.838 | 63.1% | 32.3% | 0.871 | +42.9% | +29.91 pts [+16.63, +48.23] |

Rows scored: all months: 1078 product-months, 208 products / December: 186 product-months, 186 products / January: 184 product-months, 184 products.

### Main window, the planned products

| Approach | 6 months: pooled WAPE | 6 months: MAPE | 6 months: MASE | December: pooled WAPE | December: MAPE | December: MASE | January: pooled WAPE | January: MAPE | January: MASE | 6 months: bias | vs served, pooled WAPE (95% interval) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Top-down company YoY x error feedback | 32.5% | 26.9% | 0.540 | 38.4% | 28.8% | 0.343 | 42.0% | 28.3% | 0.690 | -8.0% | -3.19 pts [-7.39, -0.19] |
| Top-down, company total, YoY seasonal naive | 32.8% | 30.7% | 0.580 | 38.7% | 27.7% | 0.359 | 38.2% | 22.3% | 0.597 | +3.4% | -2.95 pts [-6.61, -0.41] |
| Served x company error feedback (last 3 months) | 35.2% | 31.9% | 0.572 | 46.8% | 34.4% | 0.483 | 43.0% | 28.0% | 0.753 | -3.8% | -0.47 pts [-2.10, +1.12] |
| Mean of served and top-down company YoY | 33.8% | 32.5% | 0.566 | 44.4% | 35.6% | 0.459 | 37.3% | 20.8% | 0.557 | +6.5% | -1.93 pts [-3.74, -0.71] |
| Served (as live: router + calendar factor) | 35.7% | 33.4% | 0.577 | 56.6% | 47.4% | 0.626 | 36.5% | 20.2% | 0.569 | +9.6% | - |
| Top-down, category total, YoY seasonal naive | 35.9% | 31.2% | 0.621 | 37.6% | 27.0% | 0.418 | 35.0% | 20.2% | 0.636 | +2.2% | +0.21 pts [-3.71, +3.01] |
| Served, calendar factor unshrunk | 34.6% | 33.3% | 0.591 | 51.4% | 39.8% | 0.535 | 32.0% | 16.8% | 0.636 | +11.0% | -1.07 pts [-1.81, -0.16] |
| Served + product's own Dec/Jan ratio | 34.9% | 34.4% | 0.587 | 56.7% | 32.5% | 0.471 | 34.6% | 25.2% | 0.721 | +12.0% | -0.78 pts [-2.54, +1.06] |
| MA3 | 38.1% | 37.2% | 0.675 | 63.7% | 69.7% | 0.939 | 50.0% | 36.3% | 0.921 | +3.8% | +2.43 pts [-0.91, +5.05] |
| Served, calendar factor off | 37.8% | 35.9% | 0.632 | 61.9% | 55.0% | 0.705 | 43.7% | 29.0% | 0.779 | +8.3% | +2.08 pts [+1.28, +2.73] |
| Combination incl. top-down company YoY | 40.6% | 34.4% | 0.619 | 60.4% | 50.5% | 0.686 | 41.8% | 24.4% | 0.718 | +16.6% | +4.87 pts [+2.30, +7.54] |
| Combination: mean of MA3, TSB, seasonal naive, damped trend | 44.0% | 36.4% | 0.651 | 71.7% | 57.8% | 0.778 | 43.1% | 24.6% | 0.730 | +19.9% | +8.33 pts [+4.69, +12.36] |
| TSB | 44.4% | 38.6% | 0.691 | 81.9% | 75.7% | 0.996 | 47.4% | 32.8% | 0.833 | +17.1% | +8.65 pts [+6.15, +10.87] |
| Top-down, company total, Holt-Winters | 49.9% | 50.1% | 0.942 | 68.6% | 76.3% | 1.049 | 78.3% | 73.2% | 1.876 | -1.0% | +14.17 pts [+10.20, +17.57] |
| Naive (last month) | 46.5% | 47.7% | 0.820 | 70.1% | 66.6% | 0.727 | 58.6% | 53.1% | 1.282 | +3.0% | +10.84 pts [+4.77, +15.78] |
| Seasonal naive (same month last year) | 74.0% | 45.4% | 0.851 | 97.6% | 43.1% | 0.558 | 50.3% | 28.2% | 0.775 | +53.1% | +38.32 pts [+17.80, +63.29] |

Rows scored: all months: 586 product-months, 106 products / December: 102 product-months, 102 products / January: 104 product-months, 104 products.

### Earlier window 2024-01 - 2025-08 (replication)

| Approach | all: pooled WAPE | all: vs served (95% interval) | planned: pooled WAPE | planned: vs served (95% interval) | December (all): pooled WAPE | December: vs served |
|---|---|---|---|---|---|---|
| Top-down company YoY x error feedback | 31.5% | +1.05 pts [-0.70, +2.15] | 31.4% | +2.47 pts [+1.95, +2.98] | 84.9% | +15.17 pts [+8.92, +19.73] |
| Top-down, company total, YoY seasonal naive | 29.9% | -0.56 pts [-2.06, +0.42] | 29.8% | +0.88 pts [+0.45, +1.41] | 78.7% | +8.91 pts [+2.64, +13.44] |
| Served x company error feedback (last 3 months) | 31.6% | +1.08 pts [+0.22, +1.82] | 29.4% | +0.38 pts [-0.31, +1.00] | 62.4% | -7.38 pts [-8.07, -6.86] |
| Mean of served and top-down company YoY | 29.9% | -0.58 pts [-1.34, -0.07] | 29.1% | +0.15 pts [-0.06, +0.42] | 74.2% | +4.45 pts [+1.31, +6.72] |
| Served (as live: router + calendar factor) | 30.5% | - | 29.0% | - | 69.8% | - |
| Top-down, category total, YoY seasonal naive | 31.2% | +0.72 pts [-0.70, +1.79] | 31.6% | +2.66 pts [+1.81, +3.84] | 79.0% | +9.23 pts [+2.19, +14.82] |
| Served, calendar factor unshrunk | 31.6% | +1.10 pts [+0.50, +1.77] | 29.2% | +0.25 pts [-0.36, +1.12] | 84.4% | +14.67 pts [+13.67, +16.02] |
| Served + product's own Dec/Jan ratio | 32.7% | +2.23 pts [+1.25, +3.11] | 31.5% | +2.56 pts [+1.12, +3.67] | 88.3% | +18.51 pts [+1.47, +34.31] |
| MA3 | 29.6% | -0.90 pts [-2.57, +0.29] | 30.6% | +1.65 pts [+0.71, +2.32] | 50.5% | -19.27 pts [-26.31, -14.38] |
| Served, calendar factor off | 30.9% | +0.39 pts [-0.21, +0.98] | 30.1% | +1.09 pts [+0.24, +1.70] | 55.2% | -14.54 pts [-15.90, -13.54] |
| Combination incl. top-down company YoY | 31.9% | +1.41 pts [-0.12, +3.49] | 29.6% | +0.68 pts [+0.02, +1.36] | 65.1% | -4.64 pts [-8.97, -1.27] |
| Combination: mean of MA3, TSB, seasonal naive, damped trend | 33.2% | +2.75 pts [+0.80, +5.47] | 30.4% | +1.47 pts [+0.56, +2.46] | 61.8% | -8.00 pts [-13.03, -3.52] |
| TSB | 32.2% | +1.70 pts [+0.38, +3.51] | 30.0% | +1.06 pts [+0.09, +1.76] | 54.9% | -14.87 pts [-16.74, -13.39] |
| Top-down, company total, Holt-Winters | 29.2% | -1.28 pts [-2.84, -0.22] | 29.6% | +0.61 pts [-0.11, +1.30] | 50.5% | -19.27 pts [-26.31, -14.38] |
| Naive (last month) | 33.5% | +3.04 pts [+0.03, +5.53] | 37.9% | +8.90 pts [+6.71, +10.86] | 57.0% | -12.80 pts [-22.46, -5.77] |
| Seasonal naive (same month last year) | 50.7% | +20.17 pts [+12.50, +31.04] | 39.3% | +10.33 pts [+6.60, +15.09] | 85.6% | +15.83 pts [-0.05, +33.65] |
