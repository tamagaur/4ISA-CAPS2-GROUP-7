# MA3 metric reconciliation — which number is THE number

**Read-only. 2026-09-06. No code, model, or data changed.** Reconciles the
conflicting MA3 accuracy figures now in circulation. Every number below was
either quoted from the code that produced it or recomputed live against
`Unilever_SKU_Demand_Fact_Real` and confirmed to reproduce the committed report
it came from.

MA3 stays the deployed method (the paired head-to-head vs SBA α=0.3 is settled).
This document only makes the reported numbers consistent.

---

## 0. The headline

There are **three** MA3 median-MASE figures in writing, and **three** MASE<1.0
pass rates, because two independent things vary between the runs: the
**evaluation protocol** and the **eligibility population**. They are not
contradictory — they answer slightly different questions.

| Source | Protocol | Population | MA3 MASE median | MA3 MASE<1.0 |
|---|---|---|---|---|
| `BASELINE_FORECAST_RUN.md` | 80/20 single split | 119 (`status='ok'`) | **0.940** | **67/119 = 56.3 %** |
| `MODEL_BAKEOFF_UNILEVER.md` + this session's recheck | rolling-origin, 1-step, refit each origin | 89 (rolling-evaluable) | **0.819** | **60/89 = 67.4 %** |
| `SEASONALITY_AND_BASELINES.md` / `ADVISER_EVIDENCE.md` | 6-month walk-forward, **seasonal-12 MASE scale** | 129 / 89-subset | **0.838 / 0.795** | **62.0 % / 64.0 %** |

**Like-for-like (same 89 SKUs, only the protocol changes):**

| Protocol (same 89 SKUs) | MA3 MASE median | MA3 MASE<1.0 |
|---|---|---|
| 80/20 single split | **0.945** | **50/89 = 56.2 %** |
| rolling-origin 1-step | **0.819** | **60/89 = 67.4 %** |

**Conclusion: the 56.3 % → 67.4 % gap is ~100 % protocol, ~0 % population.**
Switching the 119-SKU population to the 89-SKU one, holding the 80/20 protocol
fixed, moves the rate from 56.3 % to 56.2 % — a rounding wobble. The rolling-origin
protocol alone lifts it to 67.4 %.

---

## TASK 1 — DENOMINATOR RECONCILIATION

### 1a. The 56.3 % figure — eligibility predicate, quoted

`scripts/run_baseline_forecast.py`, per-SKU loop (lines 284–319). A Tier-A SKU
(latest real ABC period `2026-02`, `tier='A'`, from `fetch_tier_a`) reaches
`status='ok'` — and therefore the MA3 pass-rate denominator — only if it clears
**all** of:

```python
# line 284-288  — must have demand rows at all
if sku_df is None or sku_df.empty:
    records.append(_row_shell(... status="insufficient_data")); continue

# line 290-292
series = build_series(sku_df)            # zero-filled monthly, resample("MS").fillna(0.0)
months_span = int(len(series))
months_with_sales = int((series > 0).sum())

# line 307-310  — >= 3 REAL (non-zero) months, not span
if months_with_sales < MIN_MONTHS_WITH_SALES:          # MIN_MONTHS_WITH_SALES = 3
    records.append(... status="insufficient_data"); continue

# line 312-315  — not dead: some sale in the last 6 months
if months_span >= 6 and series.tail(6).sum() <= 0:
    records.append(... status="dead_sku"); continue

ev = evaluate_sku(series)                 # line 317 — only 'ok' SKUs get here
```

The pass rate itself (`_print_report`, lines 460, 467, 521–525):

```python
mase = {m: _method_series(df_ok, m, "mase") for m in METHODS}      # line 460
# _method_series(df_ok, m, "mase") == pd.to_numeric(df_ok["ma3_mase"]).dropna()   (line 429-430)
# df_ok == df[df["status"] == "ok"]                                                (line 434)
...
ma3 = mase["ma3"]
ma3_pass, ma3_n = int((ma3 < 1.0).sum()), len(ma3)                 # line 521-522
```

**Denominator = Tier-A SKUs with `status='ok'` AND a *defined* MA3 MASE.** On the
live data `status='ok'` is 119, and 0 of those 119 have an undefined
(flat-training-window) MA3 MASE, so `len(ma3) = 119`. `67/119 = 56.3 %`.

### 1b. The 67.4 % figure — eligibility predicate, quoted

`scripts/model_bakeoff.py`. Cohort (line 350–351):

```python
if args.cohort == "tierA":
    pks = [pk for pk in tier_a if pk in series]      # tier_a = tier='A', ABC 2026-02 (line 108-112)
```

then each SKU must survive `backtest_sku` (lines 249–262):

```python
def backtest_sku(series, test_months, min_train, real_test_index):   # test_months=6, min_train=12
    ...
    n = len(series)
    origins = list(series.index[max(min_train, n - test_months):n])   # line 258
    if len(origins) < 3:
        return None                                                   # line 259-260 — SKU dropped
```

and the pass count (my `ma3_vs_sba` script, matching `summarize` line 310–314):
`(ma3_mase < 1).sum()` over every SKU that produced a row, `/` the count with a
defined `ma3_mase`. All 89 have a defined `ma3_mase`, so `60/89 = 67.4 %`.

The binding clause is `origins = series.index[max(12, n-6):n]` with
`len(origins) >= 3`. For `n <= 14` this yields fewer than 3 origins (`max(12, n-6)`
is 12, leaving `n-12 < 3` positions); those SKUs return `None` and never enter the
bake-off.

### 1c. The population difference — exact

| | count |
|---|---|
| Tier A (ABC `2026-02`) | 132 |
| `run_baseline_forecast` `status='ok'` (56.3 % denominator) | **119** |
| `model_bakeoff` cohort (67.4 % denominator) | **89** |
| in the 119 but **not** the 89 | **30** |
| in the 89 but **not** the 119 | **0** (the 89 is a strict subset of the 119) |
| Tier A in neither (13 `insufficient_data`, 0 `dead_sku`) | 13 |

The 30 SKUs excluded only by the bake-off — **every one because its full series
span is ≤ 12 months, so it cannot supply 3 rolling origins with 12 training
months before the first** (`product_key / sku_code`, span in months):

| pk | sku_code | span | pk | sku_code | span | pk | sku_code | span |
|---|---|---|---|---|---|---|---|---|
| 147 | 64856586 | 8 | 741 | 64900614 | 9 | 1120 | 64860720 | 8 |
| 150 | 64861486 | 12 | 747 | 64926066 | 9 | 1280 | 65086431 | 5 |
| 151 | 64861490 | 12 | 775 | 65244857 | 4 | 1340 | 64856620 | 8 |
| 159 | 64900602 | 10 | 913 | 64900506 | 7 | 1341 | 64900613 | 9 |
| 168 | 64953872 | 5 | 921 | 64985753 | 6 | 1351 | 65071340 | 6 |
| 169 | 64953874 | 7 | 1037 | 64861488 | 12 | 1396 | 64985759 | 6 |
| 171 | 64961947 | 8 | 1043 | 64900488 | 9 | 1545 | 64967994 | 8 |
| 174 | 64971078 | 10 | 1054 | 65071335 | 7 | 1547 | 64997200 | 5 |
| 711 | 64401259 | 10 | 1119 | 64856638 | 8 | 1775 | 65244853 | 4 |
| 737 | 64900492 | 9 | | | | | | |
| 738 | 64900508 | 7 | | | | | | |
| 739 | 64900598 | 10 | | | | | | |

These are the **2024–2025-launch SKUs** — "new but already selling well" per
`FORECASTING_METHOD_RECOMMENDATION.md` §2. Under the 80/20 protocol they still
get evaluated (holdout = last 1–2 months). Their MA3 MASE<1.0 rate under 80/20
is **17/30 = 56.7 %** — statistically identical to the 89-SKU set's 56.2 %, which
is why dropping them doesn't move the pass *rate* (only the count: 67/119 vs
50/89).

### 1d. Which denominator is THE reported figure

**The 89-SKU rolling-origin figure (`60/89 = 67.4 %`, MASE median 0.819) is the
defensible one to report as the headline**, for three reasons:

1. **Protocol validity.** Rolling-origin with refit at each origin is how the
   forecast is actually used — re-run before every order cycle, one month ahead.
   The 80/20 single split forecasts 6–8 months ahead from one fixed origin and
   scores a 3-month moving average against demand up to 8 months later, which the
   deployed pipeline never does. `LP_READINESS.md` Task 6 row 4 already flags the
   manuscript's "80/20 split" as not matching the deployed backtest.
2. **Population honesty.** The 30 SKUs the bake-off drops have 4–12 months of
   history — too short for *any* backtest to say something trustworthy about
   (their 80/20 holdout is 1–2 points). Excluding them is the more conservative
   claim, not the more flattering one (the rate barely changes either way).
3. **Consistency with the model choice.** The MA3-vs-SBA decision, the 17-model
   ranking, Holt-Winters, SARIMA's rejection — all of it is on the 89-SKU
   rolling-origin basis. Reporting the pass rate on a different basis than the
   model comparison invites exactly the confusion this document exists to fix.

**Caveat to state alongside it:** `60/89` counts only SKUs with ≥ ~15 months of
history. The honest full-Tier-A framing is *"of 132 Tier-A SKUs, 89 have enough
history to backtest, and MA3 beats a naive forecast on 60 of those (67 %); 13 are
`insufficient_data` and 30 more are too short to backtest."* Do not report
`67 %` as "of all Tier A".

If a single-split number must appear (e.g. to match a manuscript that keeps the
80/20 language), the correct pairing is **MASE median 0.945 / MASE<1.0 50/89 =
56.2 %** on the same 89 SKUs — never the 80/20 rate against the 89-SKU
denominator crossed with the rolling-origin one.

---

## TASK 2 — EVALUATION PROTOCOL

### 2a. `run_baseline_forecast.py` — single 80/20 chronological split

`evaluate_sku`, line 197:

```python
def evaluate_sku(series: pd.Series) -> dict:
    train, holdout = train_holdout_split(series, holdout_fraction=HOLDOUT_FRACTION)   # HOLDOUT_FRACTION = 0.20
    horizon = len(holdout)
    forecasters = build_forecasters(horizon, SBA_ALPHA)
    for m in METHODS:
        fc = forecasters[m](train)                      # ONE forecast, from ONE origin
        metrics = evaluate_baseline(fc, holdout, train)
```

`train_holdout_split` (`analytics/forecasting/sarima.py`):

```python
"""Step 14: strictly temporal 80/20 split. First 80% (by position, on a series
already sorted ascending by date) is training; last 20% is holdout."""
n_holdout = max(1, round(len(series) * holdout_fraction))
split_idx = len(series) - n_holdout
train, holdout = series.iloc[:split_idx], series.iloc[split_idx:]
```

→ **one fit, one multi-step forecast** (`horizon = len(holdout)`, i.e. the last
~20 % of each series, 6–8 months for a full-history SKU), no refit, no walk
forward. MA3's forecast is `moving_average_forecast(train, horizon, 3)` — the mean
of the last 3 *training* months, held flat across the entire holdout
(`baseline.py:118-124`).

MASE scale (`evaluate_baseline`, `baseline.py:224`): `scale = train.diff().abs().mean()`
— **plain lag-1**.

### 2b. `model_bakeoff.py` — rolling-origin, 1-step, refit every origin

`backtest_sku`, lines 249–288:

```python
n = len(series)
origins = list(series.index[max(min_train, n - test_months):n])   # last 6 months
...
for name, fn in MODELS.items():
    preds = []
    for t in origins:
        tr = series[series.index < t].to_numpy(float)   # EXPANDING window, refit here
        f = fn(tr)                                        # 1-step-ahead only
        preds.append(max(0.0, f) ...)
```

→ **6 separate origins, refit at each, 1-step-ahead each time.** MASE scale
(line 264): `scale = float(np.mean(np.abs(np.diff(base))))` where
`base = series[series.index < origins[0]]` — **plain lag-1** on the
pre-first-origin window. Same denominator family as 2a, different protocol.

### 2c. `SEASONALITY_AND_BASELINES.md` / `ADVISER_EVIDENCE.md` — a third variant

Quoted from `ADVISER_EVIDENCE.md` §2: *"6-month walk-forward holdout (expanding
window, real actuals fed in as they become available), MASE scale = mean absolute
seasonal (period=12) training-set difference, same convention `evaluate_sarima()`
uses."* Rolling-origin like 2b, but the **MASE denominator is the seasonal-12
difference, not lag-1** — which is why its MA3 median (0.795–0.838) sits between
the other two. This set predates the synthetic-contamination purge (it analyses
the old 136-SKU Tier A) and should be treated as **superseded** by
`MODEL_BAKEOFF_UNILEVER.md` for any current claim.

### 2d. The manuscript

Manuscript §3.4.2.2: *"employs a strict 80/20 time-based split … The first 80 % of
the dataset is used for model training, while the remaining 20 % serves as the
holdout set."* This matches **2a only** (`run_baseline_forecast.py`), which is
**not** how the deployed method is backtested or how the model comparison was
done. `LP_READINESS.md` Task 6 row 4 already records this.

### 2e. Like-for-like — MA3 under 80/20 on the SAME 89 SKUs

Recomputed live (`train_holdout_split` + `moving_average_forecast` +
`evaluate_baseline`, verbatim from the modules), on exactly the 89 SKUs the
bake-off evaluates:

| | 80/20 single split | rolling-origin 1-step | Δ |
|---|---|---|---|
| MA3 MASE median | **0.945** | **0.819** | −0.126 |
| MA3 MASE mean | 1.036 | 0.968 | −0.068 |
| MA3 MASE < 1.0 | **50/89 (56.2 %)** | **60/89 (67.4 %)** | +11.2 pp |
| MA3 MAPE median | 0.402 | 0.351 | −0.051 |
| MA3 MAPE < 0.20 | 10/89 | 6/89 | — |

*(the 80/20-on-119 recomputation reproduces `BASELINE_FORECAST_RUN.md` to the
digit: MASE median 0.9405, 67/119, MAPE median 0.4049, MAPE<0.20 19/119 — so the
80/20-on-89 numbers above are produced by the same verified path.)*

**Why rolling-origin looks better:** a 3-month average forecasting **one month
ahead** and refitting monthly tracks a drifting series; the same average
forecasting **6–8 months ahead from a frozen origin** cannot. The 80/20 protocol
penalises every level-forecaster (naive, MA3, SBA) for horizon it will never
actually forecast at.

---

## TASK 3 — WHAT IS IN `Forecast_Result` RIGHT NOW

### 3a. Protocol and gate

The **132 rows** were written by `scripts/run_baseline_forecast.py --write`
(`_write_forecast_result`, lines 801–990), one transaction, `generated_at`
2026-09-01 for all rows. Confirmed live:

- `status='ok'`: **119** rows, `model_params.method = "ma3"`,
  `lp_input_method = "ma3_one_step"`, `provisional = false`.
- `status='insufficient_data'`: **13** rows, `method = "trailing_average"`,
  `lp_input_method = "trailing_avg_provisional"`.
- `status='dead_sku'`: **0**.
- Gate params on every row: `abc_period_used = "2026-02"`,
  `min_months_threshold = 3`, `abc_tier_a_cutoff = 0.8`.

Eligibility gate = **exactly the `run_baseline_forecast.py` `status` gate from
Task 1a** (Tier A 2026-02 → `months_with_sales ≥ 3` → not dead).

### 3b. The stored metrics are 80/20 single-split — NOT the bake-off

`_write_forecast_result` line 933–937 writes the `Forecast_Result.mape` / `.mase`
columns from `r["ma3_mape"]` / `r["ma3_mase"]`, and `model_params
.holdout_metrics_all_methods` from `_all_method_metrics(r)` (line 758–769) — all
of which come from `evaluate_sku` → `train_holdout_split` → **single 80/20 split**
(Task 2a). The `.mape` column is `_clean_metric(r["ma3_mape"], 100.0)` — MA3
holdout MAPE **× 100** (a fraction stored as a percent), capped at 999.999.
`model_params.train_months` / `holdout_months` confirm it: 30/8, 24/6, 21/5 —
i.e. ~80/20 of each SKU's own length.

**The bake-off numbers (`model_bakeoff_recheck_2026-09.csv`) are a separate,
report-only run and are NOT in the database.**

### 3c. Three sample SKUs, both protocols

| SKU (`product_key`) | `Forecast_Result` (80/20 single split, in DB) | Bake-off recheck (rolling-origin 1-step, report only) |
|---|---|---|
| **21051980** (pk 19) | `mase` 0.640 · `mape` col 46.396 (= 0.464×100) · `model_params` ma3: mae 170.9, rmse 185.7 · train 30 / holdout 8 | `ma3_mase` **0.372** · `ma3_mape` 0.334 · `ma3_smape` 0.230 |
| **62687204** (pk 38) | `mase` 0.509 · `mape` col 100.43 (= 1.004×100, near-zero-actual blow-up) · train 24 / holdout 6 | `ma3_mase` **0.424** · `ma3_mape` 0.747 · `ma3_smape` 0.515 |
| **62687212** (pk 39) | `mase` 0.569 · `mape` col 33.931 (= 0.339×100) · train 21 / holdout 5 | `ma3_mase` **0.517** · `ma3_mape` 0.330 · `ma3_smape` 0.269 |

Same SKU, same method, materially different MASE depending on protocol — the DB
holds the 80/20 value.

---

## TASK 4 — MANUSCRIPT & REPORT EXPOSURE (every MA3 figure now in writing)

### 4a. The manuscript itself — no stale MA3 numbers

`scratch/manuscript_full.txt` (from `3ISA_7_CP-1_Manuscript.pdf`): grep for
`MASE` / `MAPE` / `moving average` / `MA3` with any numeric result → **the
manuscript reports zero forecasting accuracy figures.** Line 22636 is the only
substantive hit — a definition (*"If a given MASE value is below 1.0, this
indicates …"*), not a result. Its forecasting exposure is **qualitative** (SARIMA
as primary method, seasonality, 80/20 split, five-year span) and is already
catalogued in `LP_READINESS.md` Task 6 — **no numeric MA3 claim to fix in the
manuscript today.**

### 4b. `reports/` — every MA3 metric on disk

| file:line | value(s) | protocol / population | status |
|---|---|---|---|
| `BASELINE_FORECAST_RUN.md:18` | MA3 MASE median **0.940** | 80/20 split, 119 | current (for that protocol) |
| `BASELINE_FORECAST_RUN.md:19` | MA3 MASE mean **1.021** | 80/20, 119 | current |
| `BASELINE_FORECAST_RUN.md:20` | MA3 MASE<1.0 **56.303 %** | 80/20, 119 | current |
| `BASELINE_FORECAST_RUN.md:21` | MA3 MAPE median **0.405** | 80/20, 119 | current |
| `BASELINE_FORECAST_RUN.md:22` | MA3 MAPE<20 % **15.966 %** | 80/20, 119 | current |
| `BASELINE_FORECAST_RUN.md:23-24` | MA3 MAE median **1159.667** · RMSE median **1336.920** | 80/20, 119 | current |
| `BASELINE_FORECAST_RUN.md:25` | MA3 oracle wins **35** | 80/20, 119 | current |
| `BASELINE_FORECAST_RUN.md:33` | plain MA3 alone MASE<1.0 **67/119 = 56.3 %** | 80/20, 119 | current |
| `MODEL_BAKEOFF_UNILEVER.md:50` | MA3 row: MAPE med **0.351**, MASE med **0.819**, sMAPE med **0.296**, MAPE<.20 **7 %**, beat-naive **75 %**, n **89** | rolling-origin, 89 | current; **reproduced exactly by this session's recheck** |
| `MODEL_BAKEOFF_UNILEVER.md:75` | "MA3 … MASE **0.819**, beats naive **75 %**" | rolling-origin, 89 | current |
| `MODEL_BAKEOFF_UNILEVER.md:126` | MA3 sMAPE **0.296** (real) / **0.293** (+synth) | rolling-origin, 89 | current (synth row = diagnostic) |
| `MODEL_BAKEOFF_UNILEVER.md:170` | MA3 row repeated in auto-ARIMA addendum (same 0.351 / 0.819 / 0.296) | rolling-origin, 89 | current |
| `MODEL_BAKEOFF_UNILEVER.md:37-38` | "MA-family … MASE median **0.79–0.86**, sMAPE **0.30**" (band, includes MA3) | rolling-origin, 89 | current |
| `ADVISER_EVIDENCE.md:107` | ma3: n 129, mean MASE **1.630**, median **0.838**, %<1 **62.0 %**; 89-subset mean **1.001**, median **0.795**, %<1 **64.0 %**, wins **31** | 6-month walk-forward, **seasonal-12 scale**, pre-purge 136-set | **SUPERSEDED** by MODEL_BAKEOFF; different scale + contaminated population |
| `ADVISER_EVIDENCE.md:112` | "MA3 wins outright on **31/89**" | as above | superseded |
| `ADVISER_EVIDENCE.md:137` | "smooth demand favors MA3 … **40.3 %**" (31 of 77) | as above | superseded (directional point still holds) |
| `ADVISER_EVIDENCE.md:141` | MA3 intermittent/lumpy win share **16.7 % / 0.0 %** | as above | superseded (directional) |
| `ADVISER_EVIDENCE.md:267-269` | "MA3 wins outright on 31/89 (35 %)" | as above | superseded |
| `SEASONALITY_AND_BASELINES.md:194` | ma3: n 129, mean MASE **1.630**, median **0.838** | 6-month walk-forward, seasonal-12 scale, pre-purge | **SUPERSEDED** |
| `SEASONALITY_AND_BASELINES.md:206-207` | "MA3 … lowest median MASE (**0.838**) and most outright wins (**40/115**, 35 %)" | as above | superseded |
| `SEASONALITY_AND_BASELINES.md:219` | ma3 median MASE **0.795** (vs SARIMA subset) | as above | superseded |
| `SEASONALITY_AND_BASELINES.md:229` | "SARIMA wins vs ma3 **24 / 89 = 27 %**" | as above | superseded |
| `SEASONALITY_AND_BASELINES.md:233` | "MA3 alone beats SARIMA on **65/89 SKUs (73 %)**" | as above | superseded (conclusion still true, different exact %) |
| `FORECASTING_METHOD_RECOMMENDATION.md:70` | erratic row "0.928, 53.8 %" (ma3, full-catalog) | full 1,807-catalog intermittent-demand backtest | different scope (all tiers) — not a Tier-A figure |
| `FORECASTING_METHOD_RECOMMENDATION.md:114` | "MA3 close second" (smooth segment, qualitative) | full-catalog | qualitative |
| `FULL_DATA_AUDIT.md:320` | "≥24 (current) … 89 … median MAPE **59.44** … median MASE **1.285**" | **SARIMA**, not MA3 — E2 threshold table | not an MA3 figure, but sits in the forecasting section and could be misread |
| `FULL_DATA_AUDIT.md:330` | E3 early-exit table, median MASE **1.145–1.175** | **SARIMA**, not MA3 | same |
| `LP_READINESS.md:437` | "MA3 (bake-off: MASE 0.788 [SBA] vs 0.819 [MA3])" | rolling-origin, 89 | current |
| `LP_READINESS.md:458` | "the backtest is rolling-origin 1-step over the last 6 months, not one 80/20 split" | — | current (this reconciliation confirms it) |
| `LP_READINESS.md:494` | "switch the LP gate to `mase < 1` (→ 67 SKUs)" | mixes bases — see note | **imprecise: see below** |

### 4c. Code-embedded MA3 figures

| file:line | value | note |
|---|---|---|
| `analytics/forecasting/baseline.py:82-88` | class×method **win counts** (smooth 68, erratic 14, intermittent 81, lumpy 72 for MA3) | full 1,807-catalog, all tiers; win counts not MASE; feeds `RULE_METHOD_MAP` |
| `scripts/run_baseline_forecast.py:77-82` | same `CLASS_EVIDENCE_ROWS` counts, printed each run | same |
| `scripts/run_baseline_forecast.py:913-915` | `method_rationale` string: *"MA3 … beat SARIMA / naive / SBA / demand-class routing / …"* | stored in every `Forecast_Result.model_params`; **overstated** — the run it cites compared MA3 only vs SBA **α=0.1**; MA3 does not beat SBA α=0.3 / Theta / ARIMA(1,1,1) / Holt-Winters (already flagged in `LP_READINESS.md`) |

### 4d. The one internal inconsistency to be aware of before editing

`LP_READINESS.md` B8 says *"switch the LP gate to `mase < 1` (→ 67 SKUs)"*. That
**67** came from `run_baseline_forecast`'s 80/20 count (`67/119`). But the LP gate
also requires the forecast to be non-provisional and `status='ok'`, and the
`mase` stored in `Forecast_Result` is the **80/20** value — so a `mase < 1` gate
on the DB as it stands today would admit the **67** SKUs whose *stored 80/20*
MASE < 1, not the 60 whose *rolling-origin* MASE < 1. The two are ~the same size
but not the same SKUs. If the gate is changed, decide explicitly **which MASE**
it reads (the stored 80/20 one, or a re-run rolling-origin one) — do not carry the
`67` and the `0.819` into the same sentence.

---

## Summary for the manuscript revision

1. **No MA3 accuracy number needs fixing in the manuscript** — it contains none.
   The fix there is the qualitative SARIMA/seasonality/80-20/5-year language
   already in `LP_READINESS.md` Task 6.
2. **`BASELINE_FORECAST_RUN.md` and `MODEL_BAKEOFF_UNILEVER.md` are both
   internally correct** — they just describe different protocols. If one headline
   figure is wanted, use the **rolling-origin 89-SKU** set (MASE median **0.819**,
   MASE<1.0 **60/89 = 67 %**), stated as *"of the 89 Tier-A SKUs with enough
   history to backtest"* — never "of all 132".
3. **`ADVISER_EVIDENCE.md` and `SEASONALITY_AND_BASELINES.md` MA3 numbers
   (0.795 / 0.838, 31/89, 62–64 %) are superseded** — pre-purge population,
   different MASE scale. Cite `MODEL_BAKEOFF_UNILEVER.md` instead.
4. **`FULL_DATA_AUDIT.md` E2/E3 tables are SARIMA, not MA3** — relabel or drop if
   they migrate toward a forecasting-results section.
5. **`run_baseline_forecast.py:913` `method_rationale` overstates MA3** ("beat
   SBA") — true only vs SBA α=0.1. Not a reported-number bug, but it is written
   into every `Forecast_Result` row.
