# Error reduction, 2026-11-10

Brief (Kelvin, 2026-11-10): make the error go down, measurably, in both windows. Switch on succession and fading (task 1,
served), then attack the rest (tasks 2 to 6, backtest).

Scripts here read only the throwaway copy `ssm_challenger` (127.0.0.1:55432, a restore of the 2026-11-04 backup) and the
as-served rows of the forecastability run. Shared frame, metrics and gate: `lab.py`. Per-product rows are in the
git-ignored `local/` (hard rule 9). The served change of task 1 is in `analytics/forecasting/treatments.py`.

**Scoring, every time.** Both windows: main 2025-09..2026-02, earlier 2024-01..2025-08. Pooled WAPE and MASE lead, MAPE
beside them, each defined in `lab.py` (the forecastability definitions, imported). Planned products (lp_run 6) apart from
all products. December and January on their own lines (`results_*.csv`). Every forecast uses only months before the one
it forecasts. **Gate**, fixed in `lab.py` before any candidate was scored: pooled WAPE lower in BOTH windows, the 95%
product-bootstrap interval below 0 in at least one, MASE not higher in either. "Strict" = both intervals below 0.

## Verdict

| Task | Result |
|---|---|
| 1. Succession + fading, served | **Holds, strict.** All products: pooled WAPE -3.47 pts [-7.26, -1.35] main, -2.63 [-4.43, -1.45] earlier; MASE 0.776 -> 0.731 and 0.888 -> 0.871; MAPE 44.5% -> 44.0% and 40.6% -> 40.2%. Planned: -3.39 [-8.70, -0.22] and -0.48 [-1.18, +0.17]. Served from this date; the plan is re-run (below). |
| 2. Temporal aggregation | **Not accepted.** On every product it is worse in the main window in every variant (+0.5 to +20.9 pts against S1): smoothing lags the 2025 fall even more. It helps the Knorr burst sellers, but only once they are picked out by their error; the best rule that finds them beforehand fails the gate (MASE up). |
| 3. Stock cover curve | **Forecast + safety stock beats the cover target at every matched leftover level, both windows.** No knee: above p95 the cover target adds stock and barely cuts stock-outs. |
| 4. Top 13 | 6 Knorr flavours (31% of the error): level right, timing wrong, flavour swaps; not planned. 6 falling Surf/Sunsilk/Dove/Cream Silk codes: fading/succession, partly caught. 1 re-code (Surf Fabcon SOL): caught by succession/fading. |
| 5. 14 planned products with MAPE > 100% | All 14 have a month whose sale fell below a quarter of the forecast (5 of the other 92 do). 7 are promo bundles. No rule from history catches them precisely (best: promo name, 7 of 14, precision 33%). |
| 6. More classes | Two small ones hold for all products only (fading on last month; promo/bundles on the 6-month median), neither for planned products. Soft fading, rising, post-spike and level-noise: dead. |

## Task 1: succession and fading, served

Served inside `router.route()`, so the stored holdout error (the plan's MASE < 1 entry test), the as-served backtest and
the review flags all describe the treated forecast. Rules and thresholds are those committed before scoring (f3ffe47);
switches in `analytics/params.py` (`SERVE_SUCCESSION`, `SERVE_FADING`).

Reproduction: `treatments.apply` on the 4,370 backtest rows equals the forecastability system on all 152 succession and 149
fading rows. The old system also applied the (dead-end) burst family split to 19 rows; the served version does not, which
moves the earlier-window figure by 0.01 pts (`results_task1_backtest.csv`).

| Scored line | Served pooled WAPE | Succession + fading | Difference [95%] | MASE | MAPE |
|---|---|---|---|---|---|
| Main, all | 41.53% | 38.07% | -3.47 [-7.26, -1.35] | 0.776 -> 0.731 | 44.5% -> 44.0% |
| Earlier, all | 30.49% | 27.86% | -2.63 [-4.43, -1.45] | 0.888 -> 0.871 | 40.6% -> 40.2% |
| Main, planned | 35.71% | 32.33% | -3.39 [-8.70, -0.22] | 0.577 -> 0.585 | 33.4% -> 32.9% |
| Earlier, planned | 28.97% | 28.49% | -0.48 [-1.18, +0.17] | 0.772 -> 0.772 | 31.4% -> 32.0% |
| Dec 2025, all | 56.71% | 53.62% | -3.09 [-8.00, -0.45] | 0.809 -> 0.799 | 54.4% -> 53.3% |
| Dec 2024, all | 69.75% | 65.15% | -4.61 [-12.41, -0.47] | 1.357 -> 1.246 | 62.3% -> 62.3% |
| Jan 2026, all | 46.41% | 45.15% | -1.26 [-4.37, +0.95] | 0.707 -> 0.707 | 27.4% -> 28.3% |
| Jan 2024 + 2025, all | 24.76% | 23.89% | -0.87 [-2.63, +0.36] | 0.940 -> 0.940 | 24.3% -> 25.0% |

**On live (2026-11-10, after the full backup `backups/full_backup_20261110T112912Z`, PASS).** Rehearsed first on a clone
of the throwaway copy, with identical results.

| | Before (lp_run 6, forecast of 2026-10-20) | After (lp_run 7, forecast of 2026-11-10) |
|---|---|---|
| Forecast for 2026-03, 175 ok products | total 2,054,193.51 pieces | 1,988,935.82 (-3.2%); 10 succession, 8 fading |
| Products with MASE < 1 (the plan's entry test) | 109 of 175 | 110 of 175 |
| Review flags | 64 of 189 | 63 of 189 |
| Plan rows / pieces / rows ordering > 0 | 109 / 435,988 / 73 | **110 / 419,344 / 72** |
| Products in / out of the plan | | Clear Cool Sport Menthol 288X12ML and Knorr Liquid Seasoning 12X500ML in; Rex Women Roll-on 24X45ML out (its pending row saved to `reports/lp_runs/retired_2026-03-01_20261110T114529Z.csv`) |
| Plan rows whose quantity changed | | 7 (net -16,644 pieces) |

As-served accuracy over the whole window 2023-10..2026-02 (`docs/ACCURACY_AS_SERVED.md`, regenerated from a1dd407),
calendar-adjusted as served: pooled WAPE 32.46% -> 29.69%, median product WAPE 42.56% -> 37.88%, peso WAPE 12.09% ->
10.77%. Re-pinned once: the published snapshot (51 figures; the 14 headline and 4 MASE figures moved, the 33 error
decomposition figures did not, because they read the stored backtest run 11) and the Chapter 4 figures (9 plan figures
moved; queries now read lp_run 7).

Not re-pinned: the stored mart backtest runs (run 11 and its siblings) behind the dashboard's forecast-error card and the
error decomposition still hold the untreated backtest. Writing treated runs needs new run labels, a new
`DEFAULT_BACKTEST_LABEL`, and a migration for the decomposition's label match: a decision, not done here.

Safety stock is not changed by the treatments. A product forecast to 0 by fading still carries safety stock sized on its
pre-collapse variability: Surf Fabcon SOL is ordered 23,400 pieces (all of it safety stock, forecast 0; it was 47,160).

## Task 2: temporal aggregation (`ta.py`)

ADIDA / MAPA: the history before t is cut into non-overlapping k-month buckets ending at t-1, the next bucket is forecast
by simple exponential smoothing (alpha 0.3 or fitted on the buckets), divided by k and multiplied by the served calendar
factor. k = 1 is the control (smoothing without aggregating).

| All products, pooled WAPE vs S1 | Main | Earlier |
|---|---|---|
| SES k=1 (control) | +6.62 | +1.54 |
| SES fitted, k=2 / k=3 | +6.55 / +11.23 | +2.19 / +1.99 |
| MAPA k=1,2,3 / k=1,2,3,4,6 | +6.87 / +8.88 | +1.08 / +3.03 |
| Mean of S1 and MAPA(1..6) | +0.50 | -0.28 |
| Mean of S1 and MAPA(1,2,3) | +0.60 | -0.50 [-0.84, -0.15] |

Every variant is worse in the main window: bias rises from +8.9% to +16-36%, because a smoother forecast is slower to
follow a falling level, and the main window is a falling level.

Burst sellers first, as the brief asks:

| | Main | Earlier |
|---|---|---|
| Knorr top-13 flavours (6 products), served -> MAPA(1..6) | 40.7% -> 38.6% | 20.0% -> 18.4% |
| Knorr Sinigang 67749043, served -> MAPA(1..6) / SES k=3 | 41.3% -> 36.9% / 31.0% | 20.5% -> 18.7% / 21.0% |
| BURST2 rows (post-hoc class), all, mean(S1, MAPA 1..6) | -0.54 [-2.09, +2.20] | -1.03 [-1.52, -0.37] (MASE lower in both) |
| BURST2 rows, planned (12 products in main) | +3.88 | -1.51 |
| Rule from history: plan MASE test fails -> MAPA(1..6), all | -0.66, MASE +0.017 | -0.30 [-0.51, -0.08] |

So the brief's mechanism is real (level right, timing wrong: a smoother level beats chasing), but only on products found
after the fact. Every rule that finds them before the month either raises MASE or hurts planned products. Not accepted.

## Task 3: stock cover as a curve (`cover.py`, `results_cover_curve.json`)

Products failing the plan's entry test at forecast time (trailing served MASE >= 1), 12+ months of history, monthly review,
zero lead time, lost sales, no carry-over. Cover = percentile of the last 12 months; forecast = S1 + z x sigma at the same
service level.

| All products, main window (71 products) | p90 | p95 | p97 | p98 | p99 | max |
|---|---|---|---|---|---|---|
| Cover: months short / leftover (months of sales) | 8.8% / 0.85 | 6.0% / 1.04 | 6.0% / 1.14 | 5.6% / 1.19 | 5.6% / 1.23 | 5.1% / 1.28 |
| Forecast + z sigma | 5.6% / 0.79 | 4.2% / 0.96 | 3.7% / 1.07 | 3.3% / 1.15 | 2.8% / 1.28 | 1.4% / 1.64 |

| All products, earlier window (136 products) | p90 | p95 | p97 | p98 | p99 | max |
|---|---|---|---|---|---|---|
| Cover | 7.7% / 0.73 | 5.7% / 0.82 | 5.0% / 0.86 | 4.6% / 0.89 | 4.4% / 0.91 | 4.0% / 0.93 |
| Forecast + z sigma | 4.6% / 0.64 | 2.9% / 0.79 | 1.9% / 0.89 | 1.7% / 0.96 | 0.9% / 1.08 | 0.3% / 1.41 |

At p90 and p95 the forecast policy has both fewer months short and less leftover. Above p95 the cover curve is flat
in stock-outs (12 months give two points above the 90th percentile), so there is no setting where stock falls and
stock-outs barely rise. On the BURST2 subset the cover target holds less stock at each percentile, but at matched
leftover the forecast policy is short less often (main: cover max 0.73 / 9.1% vs forecast p97 0.74 / 4.5%; earlier: cover
max 0.45 / 8.2% vs forecast p90 0.43 / 6.1%). Planned products with MASE >= 1 in the main window: 16 products, 30
product-months, too few to read.

## Task 4: the top 13 (`top.py`; per product in local/)

Served absolute error, main window, 4,520,004 pieces: 13 products carry 51.2%, 42 carry 80%. 6 of the 13 are planned.

| Group (of the 13) | Share of error | Class at forecast time | Does a treatment help? | What it is doing | Rule learned |
|---|---|---|---|---|---|
| Knorr Sinigang Orig 11G, Sinigang na Gabi, 4 Knorr cube flavours (not planned) | 30.7% | BURST2 / STABLE | Temporal aggregation and the 12-month mean help, only once picked out; nothing from history holds | Level right, months wrong: spikes, flavour swaps (pork down, chicken up, same month, stock on hand) | A product whose recent errors are two-sided with a stable level is not forecastable month by month; its plan should come from its level and a buffer, not a chased forecast. It is already excluded by the MASE gate |
| Surf powder Cherry Blossom, Rose Fresh, Sun Fresh; Sunsilk Smooth & Manageable; Dove Keratin; Cream Silk Ultreborn (5 planned) | 17.7% | FADING / SUCCESSION / STABLE | Fading/succession cut 4 of them (Cream Silk Ultreborn by 28%); Sunsilk S&M gets worse (+9%) | Falling codes, partly re-codes into bundles whose content does not parse | Falling level + a launch in the family: follow it down; the stable remainder is the lag the main window punishes |
| Surf Fabcon Blossom Fresh SOL 360X28ML (planned) | 2.8% | SUCCESSION then FADING | Yes: its missed pieces fall by 95% | A re-code (STR took over in Sep 2025) | Succession: caught a month before the collapse flag |

## Task 5: the 14 planned products with MAPE over 100% (`highmape.py`, `results_highmape.json`)

| Group | Products | What they share | Rule? |
|---|---|---|---|
| Promo / bundle codes ((12+2), (6+1), (5+1), PROMO) | 7 | Switch on and off; a month far below the forecast | The promo name catches all 7, but also 14 other planned products (precision 33%). The 6-month median lowers their median MAPE 2,197% -> 1,625% but fails for planned products in the earlier window |
| Re-coded or fading (Surf Fabcon SOL, Surf Cherry Blossom, Clear Complete Soft Care, Knorr Liquid Seasoning 1L) | 4 | Demand moving to another code | Succession/fading catch all 4; Surf Fabcon SOL MAPE 4,271% -> 737% |
| Small or declining (Sunsilk 24X180ML, Knorr soup, Sunsilk Damage Reconstruction) | 3 | Small monthly volumes (two under 1,200 pieces a month) | None |

What all 14 share: at least one main-window month whose sale fell below a quarter of the forecast. 5 of the other 92
planned products had such a month. MAPE divides by that small sale, so these 14 are 21.5% of the planned products' absolute
error but most of the MAPE tail. An on/off rule from history (a month below a quarter of the 12-month mean) catches 4 of
14 (post hoc). All 14 stay above 100% with succession + fading. Their MAPE belongs on its own line, not in a headline.

## Task 6: more classes (`classes2.py`, `results_classes2.json`), on top of S1

| Rule (fixed before scoring) | All products | Planned |
|---|---|---|
| SOFTFADE (collapse ratio 0.5..0.6 / 0.7 / 0.8): fading treatment earlier | worse in both | worse in both |
| FADE_LAST: fading -> min(served, last month) | holds: -0.10 / -0.06 | lower in both, inside the noise |
| RISING (ratio >= 1.25): max(served, last-3 mean) | worse in both | worse in both |
| POST_SPIKE: do not chase a spike | lower in both, inside the noise | worse in main (+0.49) |
| LEVEL_NOISE: 12-month mean | one window only | one window only |
| PROMO_MED: bundles -> 6-month median | holds: -0.38 [-0.82, -0.09] / -0.17 | worse in earlier (+0.06) |
| S2 = S1 + FADE_LAST + PROMO_MED | holds: -0.48 / -0.23 | earlier +0.06 |

None is served: the gains are under half a point, and none holds for the planned products that drive orders.

## Dead ends, one line each

- Temporal aggregation on every product: worse in the main window in every variant.
- Temporal aggregation on products failing the MASE test: pooled WAPE lower in both, median MASE higher in main.
- Soft fading (an earlier fading threshold): worse in both windows at 0.6, 0.7 and 0.8.
- Rising-product uplift: worse in both.
- Stock cover target in place of forecast + safety stock: dominated at every matched leftover level.
