# Model bake-off under the 80/20 single-split protocol

**Read-only. 2026-09-06. No code / model / DB change.** The existing bake-off
(`MODEL_BAKEOFF_UNILEVER.md`) is rolling-origin 1-step only. The manuscript
specifies a single 80/20 chronological split. That comparison had never been run.
This is it.

- **Protocol:** `analytics.forecasting.sarima.train_holdout_split(series, 0.20)`
  (first 80 % by position = train, last 20 % = holdout), **one fit**, **one
  multi-step forecast over the whole holdout**, then
  `analytics.forecasting.baseline.evaluate_baseline` (lag-1 MASE scale; MAPE
  excludes zero-actual points). Both imported verbatim, not reimplemented.
- **Models:** all 17 in `scripts/model_bakeoff.py`. XGBoost and auto-ARIMA are
  excluded — XGBoost is feature-engineered and refits per origin by construction
  (no single-fit multi-step form); auto-ARIMA's per-SKU order search is a separate
  harness (its fixed-order cousins `sarima_plain` and `sarima_seasonal` are in the 17).
- **Populations, reported separately:** (a) the **89** rolling-evaluable SKUs
  (like-for-like vs the existing bake-off), (b) all **119** `status='ok'` SKUs
  (what 80/20 can actually serve).
- Per-SKU output: `reports/bakeoff_8020_per_sku_89_2026-09.csv`,
  `reports/bakeoff_8020_per_sku_119_2026-09.csv`.

---

## HORIZON GENERATION — how each model produces the multi-step holdout forecast

The 80/20 holdout is 6–8 months for a full-history SKU, 1–2 for a short one.
Model functions in the bake-off return a 1-step point forecast; extended to the
holdout horizon `h` as follows (stated so the comparison is honest):

| model | multi-step policy |
|---|---|
| naive | **flat** carry-forward of last value |
| mean | **flat** = training mean |
| ma3 | **flat** = mean(last 3 train months) — identical to `baseline.moving_average_forecast` |
| ma6 | **flat** = mean(last 6 train months) |
| croston, sba, sba_a3, tsb | **flat** per-period demand rate (these estimate a rate, inherently flat) |
| snaive12 | **tile** the last 12 observed months forward (flat carry-forward if < 12 mo) |
| drift | **linear extrapolation** of the `x[0] → x[-1]` slope: `x[-1] + slope·k` |
| ses | native `.forecast(h)` — flat (converges to last level) |
| holt / holt_damped | native `.forecast(h)` — linear / damped **trend extrapolation** |
| hw_add12 | native `.forecast(h)` — trend + additive 12-month seasonal; **NaN if < 24 mo** |
| theta | native `.forecast(h)` — Theta recomposition |
| sarima_plain (1,1,1) | native **recursive** `.forecast(h)` |
| sarima_seasonal (1,1,1)(0,1,1)₁₂ | native **recursive** `.forecast(h)`; **NaN if < 28 mo** |

The flat models (naive, mean, ma3, ma6, croston-family) do not "extrapolate" —
they hold one number across the horizon. The trend/seasonal models
(holt, hw, sarima, drift) project forward and are the ones exposed by a long
single-origin horizon.

---

## SANITY: the harness reproduces the settled numbers

MA3 under this harness, 80/20:
- on the **119**: MASE median **0.9406**, MASE<1.0 **67/119** — matches
  `BASELINE_FORECAST_RUN.md` to the digit.
- on the **89**: MASE median **0.945**, MASE<1.0 **50/89** — matches the
  reconciliation report's like-for-like figure.

---

## (a) 89 ROLLING-EVALUABLE SKUs — 80/20

### Scale-free (median | mean | p75 | p90), ranked by MASE median

| model | n | MASE | MAPE | sMAPE |
|---|---|---|---|---|
| **sba_a3** | 89 | **0.833** \| 0.993 \| 1.203 \| 1.707 | 0.336 \| 4.196 \| 0.522 \| 0.889 | 0.313 \| 0.371 \| 0.406 \| 0.626 |
| hw_add12 | **62** | 0.890 \| 1.002 \| 1.235 \| 1.579 | 0.379 \| 0.684 \| 0.561 \| 0.897 | 0.337 \| 0.373 \| 0.461 \| 0.540 |
| **ma3** | 89 | **0.945** \| 1.036 \| 1.225 \| 1.625 | 0.402 \| 5.131 \| 0.623 \| 1.019 | 0.334 \| 0.380 \| 0.447 \| 0.637 |
| theta | 89 | 0.949 \| 1.042 \| 1.187 \| 1.686 | 0.389 \| 5.113 \| 0.617 \| 1.252 | 0.320 \| 0.382 \| 0.436 \| 0.690 |
| sarima_plain | 89 | 0.969 \| 1.046 \| 1.252 \| 1.586 | 0.379 \| 5.213 \| 0.620 \| 1.104 | 0.316 \| 0.386 \| 0.464 \| 0.711 |
| tsb | 89 | 0.976 \| 1.037 \| 1.173 \| 1.593 | 0.432 \| 4.961 \| 0.587 \| 1.203 | 0.331 \| 0.385 \| 0.427 \| 0.677 |
| ses | 89 | 0.981 \| 1.056 \| 1.209 \| 1.623 | 0.407 \| 5.194 \| 0.607 \| 1.543 | 0.329 \| 0.391 \| 0.447 \| 0.720 |
| holt_damped | 89 | 0.983 \| 1.088 \| 1.342 \| 1.812 | 0.426 \| 4.728 \| 0.652 \| 1.218 | 0.356 \| 0.392 \| 0.460 \| 0.574 |
| sba (α.1) | 89 | 0.990 \| 1.070 \| 1.224 \| 1.672 | 0.375 \| 4.257 \| 0.584 \| 1.401 | 0.342 \| 0.403 \| 0.467 \| 0.771 |
| snaive12 | 89 | 0.995 \| 1.143 \| 1.291 \| 1.884 | 0.384 \| 4.806 \| 0.599 \| 1.332 | 0.333 \| 0.427 \| 0.463 \| 0.766 |
| naive | 89 | 1.004 \| 1.102 \| 1.444 \| 1.924 | 0.385 \| 3.886 \| 0.603 \| 1.152 | 0.342 \| 0.387 \| 0.458 \| 0.674 |
| drift | 89 | 1.015 \| 1.181 \| 1.629 \| 2.107 | 0.434 \| 4.194 \| 0.648 \| 1.308 | 0.366 \| 0.411 \| 0.462 \| 0.720 |
| ma6 | 89 | 1.018 \| 1.072 \| 1.234 \| 1.675 | 0.440 \| 5.055 \| 0.600 \| 1.552 | 0.344 \| 0.398 \| 0.443 \| 0.734 |
| croston | 89 | 1.022 \| 1.094 \| 1.209 \| 1.601 | 0.394 \| 4.488 \| 0.622 \| 1.527 | 0.357 \| 0.409 \| 0.454 \| 0.786 |
| holt | 89 | 1.024 \| 1.111 \| 1.256 \| 1.770 | 0.470 \| 4.841 \| 0.651 \| 1.089 | 0.376 \| 0.401 \| 0.470 \| 0.574 |
| mean | 89 | 1.059 \| 1.159 \| 1.314 \| 1.776 | 0.423 \| 4.892 \| 0.658 \| 1.819 | 0.380 \| 0.431 \| 0.474 \| 0.842 |
| **sarima_seasonal** | **42** | **1.240** \| **2.2×10⁹** \| 1.892 \| 4.319 | 0.459 \| 1.2×10⁹ \| 0.879 \| 1.388 | 0.398 \| 0.594 \| 0.689 \| 1.209 |

### Undefined / not-scored

| model | not scored (NaN forecast) | MAPE ∞ | MASE undef | sMAPE NaN |
|---|---|---|---|---|
| hw_add12 | **27 / 89** (< 24 mo history) | 0 | 0 | 0 |
| sarima_seasonal | **47 / 89** (< 28 mo history) | 0 | 0 | 0 |
| all other 15 models | 0 | 0 | 0 | 0 |

> **`sarima_seasonal` is broken under this protocol, not merely weak.** Of the 42
> SKUs it *can* fit, its recursive multi-step forecast **explodes** — mean MASE
> 2.2 billion, max 9.2 × 10¹³. Seasonal differencing (`D=1`) integrated forward
> 6–8 steps on a ~30-month series compounds without bound. Its finite-looking
> median (1.240) hides this; the model is unusable for single-origin multi-step
> and should be read as "fails" here, not "ranks 17th". Rolling-origin 1-step
> never exposed this because there is no compounding at h = 1.

### Scale-dependent — per-SKU WIN COUNTS

Only **42** SKUs are scored by all 17 models (hw needs 24 mo, sarima_seasonal
28 mo), so these counts are on a small, long-history-biased subset:

| metric | top 5 (wins of 42) |
|---|---|
| MAE | sba_a3 7.6 · hw_add12 7.0 · sarima_seasonal 6.0 · snaive12 4.0 · sarima_plain 3.0 |
| MSE / RMSE | sba_a3 9.0 · hw_add12 6.0 · sarima_seasonal 6.0 · snaive12 5.0 · mean 3.0 |
| MdAE | hw_add12 9.0 · snaive12 6.0 · sarima_seasonal 5.0 · drift 4.0 · sba_a3 3.7 |

### Gates

| model | MASE < 1.0 | MAPE < 0.20 | sMAPE < 0.30 |
|---|---|---|---|
| **sba_a3** | **60/89 (67 %)** | 10/89 (11 %) | 40/89 (45 %) |
| theta | 52/89 (58 %) | 11/89 (12 %) | 40/89 (45 %) |
| **ma3** | **50/89 (56 %)** | 10/89 (11 %) | 35/89 (39 %) |
| sarima_plain | 48/89 (54 %) | 11/89 (12 %) | 40/89 (45 %) |
| tsb | 49/89 (55 %) | 11/89 (12 %) | 35/89 (39 %) |
| hw_add12 | 34/62 (55 %) | 7/62 (11 %) | 25/62 (40 %) |
| naive | 44/89 (49 %) | 11/89 (12 %) | 33/89 (37 %) |
| mean | 35/89 (39 %) | 6/89 (7 %) | 29/89 (33 %) |

**`MAPE < 0.20` is unachievable under 80/20 too** — every model 7–12 %, no better
than under rolling-origin. The gate is a target problem, protocol-independent.

### Spread / tails (MASE): mean · median · p75 · p90 · max · count > 1.5 · > 2.0

| model | mean | median | p75 | p90 | max | > 1.5 | > 2.0 |
|---|---|---|---|---|---|---|---|
| sba_a3 | 0.993 | 0.833 | 1.203 | 1.707 | 3.19 | 12 | 5 |
| hw_add12 | 1.002 | 0.890 | 1.235 | 1.579 | **1.93** | 8 | **0** |
| ma3 | 1.036 | 0.945 | 1.225 | 1.625 | 2.81 | 14 | 6 |
| theta | 1.042 | 0.949 | 1.187 | 1.686 | 3.09 | 15 | 7 |
| naive | 1.102 | 1.004 | 1.444 | 1.924 | 3.54 | 21 | 7 |
| drift | 1.181 | 1.015 | 1.629 | 2.107 | 3.47 | 27 | 12 |

HW has the tightest tail (0 SKUs above MASE 2.0) — but on 62 long-history SKUs.
`drift` has the worst tail of the usable models (27 above 1.5). SBA α=0.3 has a
marginally better tail than MA3 (5 vs 6 above 2.0).

### Directional bias (per-SKU mean signed error; + = over-forecast)

| model | median per-SKU ME | over | under |
|---|---|---|---|
| **sba_a3** | **−33.6** | 38/89 | **51/89** |
| sba (α.1) | +40.2 | 51/89 | 38/89 |
| **ma3** | **+144.6** | **62/89** | 27/89 |
| naive | +92.4 | 52/89 | 37/89 |
| theta | +218.8 | 67/89 | 22/89 |
| holt | +256.0 | 62/89 | 27/89 |

Under multi-step 80/20 **almost every model over-forecasts** (a flat or trending
forecast held over 6–8 months, against demand that mostly drifts up). SBA α=0.3 is
the exception — it still **under-forecasts** (51/89). MA3 over-forecasts *more*
under 80/20 (+145) than under rolling-origin (+51) because its 3-month average is
held stale for the whole horizon.

### Paired Wilcoxon vs MA3 (p < 0.05 = significant), 89 SKUs

| model | MASE | sMAPE | MAE |
|---|---|---|---|
| sba_a3 | p=0.251 ns (sba better 49/89) | p=0.498 ns | p=0.168 ns (**ma3** median) |
| hw_add12 | p=0.120 ns (**ma3** 34/62) | p=0.050 ns (**ma3** median) | p=0.129 ns |
| theta | p=0.814 ns (**ma3** 47/89) | p=0.976 ns | p=0.448 ns |
| sarima_plain | p=0.380 ns (**ma3** 51/89) | p=0.398 ns | p=0.599 ns |
| tsb | p=0.271 ns (**ma3**) | p=0.263 ns | p=0.120 ns (**ma3**) |
| ses | p=0.056 ns (**ma3**) | p=0.086 ns (**ma3**) | **p=0.010 SIG — MA3 beats ses** |
| snaive12 | **p=0.048 SIG — MA3 beats snaive12** | p=0.139 ns | p=0.067 ns |
| croston | p=0.055 ns (**ma3**) | p=0.052 ns (**ma3**) | **p=0.018 SIG — MA3 beats croston** |
| holt | p=0.078 ns (**ma3**) | **p=0.049 SIG — MA3 beats holt** | p=0.544 ns |
| drift | **p=0.003 SIG — MA3 beats drift** | **p=0.004 SIG — MA3 beats drift** | p=0.053 ns |
| mean | **p=0.004 SIG — MA3 beats mean** | **p=0.004 SIG** | **p=0.005 SIG** |
| sarima_seasonal | **p<0.001 SIG — MA3 beats it** (n=42) | **p<0.001 SIG** | **p=0.002 SIG** |

**No model beats MA3 at p < 0.05 on any of MASE, sMAPE, or MAE.** MA3
significantly *beats* drift, mean, snaive12, sarima_seasonal (all metrics) and
ses / croston / holt on one metric each.

---

## (b) ALL 119 `status='ok'` SKUs — 80/20

### Scale-free (median | mean | p75 | p90), ranked by MASE median

| model | n | MASE med | MASE mean | MASE p90 | MAPE med | sMAPE med |
|---|---|---|---|---|---|---|
| **sba_a3** | 119 | **0.833** | 1.033 | 1.868 | 0.337 | 0.332 |
| hw_add12 | 62 | 0.890 | 1.002 | 1.579 | 0.379 | 0.337 |
| **ma3** | 119 | **0.940** | 1.021 | 1.779 | 0.405 | 0.344 |
| tsb | 119 | 0.960 | 1.018 | 1.719 | 0.394 | 0.354 |
| theta | 119 | 0.964 | 1.084 | 1.795 | 0.389 | 0.358 |
| holt_damped | 119 | 0.964 | 1.121 | 1.939 | 0.426 | 0.361 |
| snaive12 | 119 | 0.976 | 1.146 | 2.003 | 0.399 | 0.347 |
| ses | 119 | 0.984 | 1.078 | 1.792 | 0.400 | 0.351 |
| naive | 119 | 0.991 | 1.116 | 1.993 | 0.388 | 0.365 |
| sba (α.1) | 119 | 0.992 | 1.147 | 1.996 | 0.403 | 0.363 |
| sarima_plain | 119 | 0.996 | 1.121 | 2.104 | 0.408 | 0.359 |
| drift | 119 | 0.999 | 1.204 | 2.138 | 0.448 | 0.372 |
| ma6 | 119 | 1.005 | 1.058 | 1.728 | 0.429 | 0.354 |
| holt | 119 | 1.024 | 1.170 | 2.022 | 0.460 | 0.388 |
| croston | 119 | 1.033 | 1.157 | 2.009 | 0.416 | 0.382 |
| mean | 119 | 1.038 | 1.122 | 1.904 | 0.422 | 0.381 |
| sarima_seasonal | 42 | 1.240 | 2.2×10⁹ | 4.319 | 0.459 | 0.398 |

### Gates

| model | MASE < 1.0 | MAPE < 0.20 | sMAPE < 0.30 |
|---|---|---|---|
| **sba_a3** | **76/119 (64 %)** | 14/119 (12 %) | 50/119 (42 %) |
| **ma3** | **67/119 (56 %)** | 19/119 (16 %) | 49/119 (41 %) |
| tsb | 65/119 (55 %) | 22/119 (18 %) | 48/119 (40 %) |
| theta | 66/119 (55 %) | 17/119 (14 %) | 47/119 (39 %) |
| hw_add12 | 34/62 (55 %) | 7/62 (11 %) | 25/62 (40 %) |
| naive | 60/119 (50 %) | 18/119 (15 %) | 42/119 (35 %) |
| mean | 52/119 (44 %) | 16/119 (13 %) | 40/119 (34 %) |

Undefined: hw_add12 **57/119** not scored, sarima_seasonal **77/119** not scored;
all others 0.

### Directional bias

| model | median per-SKU ME | over | under |
|---|---|---|---|
| sba_a3 | **−84.8** | 45/119 | **74/119** |
| sba (α.1) | −33.4 | 58/119 | 61/119 |
| ma3 | **+65.9** | **71/119** | 48/119 |
| naive | +46.0 | 63/119 | 56/119 |

Same split as everywhere: **SBA α=0.3 under-forecasts, MA3 over-forecasts.**

### Paired Wilcoxon vs MA3, 119 SKUs — models that beat MA3 at p < 0.05

**None.**

- sba_a3: MASE p=0.579, sMAPE p=0.411, MAE p=0.956 — dead even, all three.
- hw_add12: MASE p=0.120 (MA3 median better), n=62.
- theta: MASE p=0.143 (MA3 better).
- tsb: MASE p=0.622 (MA3 better).

MA3 **significantly beats** (p<0.05, MA3 median lower): snaive12, ses, naive,
sba(α.1), drift, holt, croston, mean, sarima_seasonal (MASE and/or sMAPE and/or
MAE), plus holt_damped and sarima_plain on sMAPE.

---

## THE COMPARISON THAT MATTERS — rolling-origin vs 80/20, side by side

MASE median and MASE < 1.0 pass rate, 89-SKU population, both protocols:

| model | roll MASE med | 80/20 MASE med | Δ | roll rank | 80/20 rank | rank shift | roll MASE<1 | 80/20 MASE<1 |
|---|---|---|---|---|---|---|---|---|
| **sba_a3** | 0.788 | **0.833** | +0.045 | 2 | **1** | **+1** | 60/89 | **60/89** |
| hw_add12 (n=62) | **0.741** | 0.890 | +0.149 | **1** | 2 | −1 | 45/66 | 34/62 |
| **ma3** | 0.819 | 0.945 | +0.126 | 6 | **3** | **+3** | 60/89 | **50/89** |
| theta | 0.792 | 0.949 | +0.157 | 3 | 4 | −1 | — | 52/89 |
| sarima_plain | 0.804 | 0.969 | +0.165 | 4 | 5 | −1 | — | 48/89 |
| tsb | 0.815 | 0.976 | +0.161 | 5 | 6 | −1 | — | 49/89 |
| ses | 0.821 | 0.981 | +0.160 | 7 | 7 | 0 | — | 46/89 |
| holt_damped | 0.854 | 0.983 | +0.129 | 10 | 8 | +2 | — | 47/89 |
| sba (α.1) | 0.875 | 0.990 | +0.115 | 11 | 9 | +2 | — | 47/89 |
| snaive12 | 0.953 | 0.995 | +0.042 | 13 | 10 | +3 | — | 45/89 |
| naive | 1.081 | 1.004 | **−0.077** | 16 | 11 | **+5** | — | 44/89 |
| drift | 1.097 | 1.015 | **−0.082** | 17 | 12 | **+5** | — | 44/89 |
| **ma6** | 0.836 | 1.018 | +0.182 | 8 | **13** | **−5** | — | 42/89 |
| croston | 0.910 | 1.022 | +0.112 | 12 | 14 | −2 | — | 43/89 |
| **holt** | 0.841 | 1.024 | +0.183 | 9 | **15** | **−6** | — | 44/89 |
| mean | 1.014 | 1.059 | +0.045 | 15 | 16 | −1 | — | 35/89 |
| sarima_seasonal | 0.989 | **1.240**† | — | 14 | 17 | −3 | — | 16/42† |

† `sarima_seasonal` mean MASE = 2.2 × 10⁹ under 80/20 — it does not "rank 17th",
it **fails**.

### Does the ranking change? Yes — meaningfully.

1. **The winner is the same: SBA α=0.3.** Best MASE median under rolling-origin
   (among models that serve all 89) *and* outright best under 80/20 (0.833).
   Holt-Winters' rolling-origin #1 is a population artifact (n=62) that a longer
   horizon erodes — its MASE median jumps +0.149 under 80/20, the biggest rise of
   any competitive model, and it drops to #2.
2. **MA3 climbs from #6 to #3.** Its flat forecast degrades *less* over a
   6–8-month single-origin horizon than the trend/average models. Everything
   above it under rolling (theta, sarima_plain, tsb) is above it by less, and
   ma6, croston, holt fall below it.
3. **Trend / longer-average models collapse:** `holt` −6, `ma6` −5,
   `sarima_seasonal` −3 (broken). A linear trend or a 6-month average projected
   forward 8 months on noisy data is far worse than under a 1-step refit.
4. **The naive family rises** (`naive` +5, `drift` +5, `snaive12` +3): under
   80/20 everyone is worse, so the gap between "does nothing" and "does something
   clever" narrows and even inverts (naive 1.004 now beats ma6, croston, holt).
5. **Every MASE median is worse under 80/20** except naive and drift — the
   protocol penalises forecasting 6–8 months ahead from one frozen origin, which
   is horizon the deployed pipeline never uses.

### One place 80/20 shifts things in SBA's favour

Under **rolling-origin**, MA3 and SBA α=0.3 have the **same** MASE<1.0 count
(60/89). Under **80/20**, SBA holds at **60/89 (67 %)** while MA3 drops to
**50/89 (56 %)** — an 11-point gap. SBA's flat rate estimate survives the long
horizon better than MA3's stale 3-month mean. But the paired test says the
per-SKU differences are **not consistent** — MASE p = 0.251 (89) / 0.579 (119).
The threshold count moves; the signed-rank test does not.

---

## VERDICT (forecasting accuracy only — implementation cost, LP behaviour, and current deployment explicitly excluded)

### Winner under 80/20: **SBA α=0.3.**

- Best MASE median on both populations (0.833 / 0.833).
- Best MASE < 1.0 pass rate on both (67 % / 64 %) — and under 80/20 that lead over
  MA3 is real (11 points) where under rolling-origin it was zero.
- Competitive on sMAPE (median 0.313, tied-best band) and the least-bad tail among
  the flat models.

### Does it differ from the rolling-origin winner? **No.**

SBA α=0.3 is the best full-population model under rolling-origin too (MASE median
0.788; Holt-Winters' 0.741 is on 62 SKUs and does not survive a longer horizon or
a like-for-like population). **Both protocols name SBA α=0.3.**

### Is the difference statistically significant? **No.**

Paired Wilcoxon, SBA α=0.3 vs MA3, under 80/20:
- 89 SKUs: MASE p = 0.251, sMAPE p = 0.498, MAE p = 0.168 — none significant.
- 119 SKUs: MASE p = 0.579, sMAPE p = 0.411, MAE p = 0.956 — dead even.

**Under the 80/20 protocol, exactly as under rolling-origin, no model beats MA3 at
p < 0.05 on any of MASE, sMAPE, or MAE — on either population.** SBA α=0.3 wins the
median and the pass-rate count; it does not win the paired test.

### Also confirmed, protocol-independent

- **`MAPE < 0.20` is unachievable** — best model 12–18 %, no better under 80/20
  than under rolling-origin. The gate is wrong for this data regardless of how it
  is measured.
- **`sarima_seasonal` is unusable for single-origin multi-step** — recursive
  seasonal-differenced forecasts explode (mean MASE 10⁹). This is a protocol
  interaction the rolling 1-step bake-off could not surface, and it is a concrete
  reason not to use seasonal SARIMA in a pipeline that ever forecasts more than
  one step from a fixed origin.
- **Directional bias is protocol-independent:** SBA α=0.3 under-forecasts
  (51–74 of the SKUs), MA3 over-forecasts. Not an accuracy statement — noted
  because the brief asked for the split under both protocols and it does not move.
