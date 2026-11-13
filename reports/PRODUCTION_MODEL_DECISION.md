# Production model decision — is MA3 the right forecaster for the dashboard?

**Read-only. 2026-09-06. No code, model, or DB change.** Rolling-origin 1-step,
refit at every origin, last 6 months, the 89 evaluable Tier-A Unilever SKUs
(ABC period 2026-02). Model functions reused verbatim from
`scripts/model_bakeoff.py`. Per-SKU matrix: `reports/model_decision_per_sku_2026-09.csv`.

Candidates: **MA3** (incumbent), **SBA α=0.3**, **Holt-Winters additive(12)**,
**Theta**, **ARIMA(1,1,1)**.

## VERDICT — up front

**MA3, no change.** No candidate beats MA3 at p < 0.05 on any metric. The one
model with a better headline median (Holt-Winters) achieves it only by refusing
to forecast the harder third of the SKUs — on a like-for-like population it is the
**worst** of the five. The only candidate that is genuinely different in
behaviour (SBA α=0.3) is different in the wrong direction for a
service-weighted replenishment system: it systematically under-forecasts.
Switching costs code and buys nothing measurable.

The recommendation rests on **MASE, evaluated by paired signed-rank test** — see
§7 for why that is the correct metric for this system.

---

## 0. FULL METRIC MATRIX

### Scale-free metrics (median | mean | p75 | p90)

| model | n | MASE | MAPE | sMAPE |
|---|---|---|---|---|
| **MA3** | 89 | 0.819 \| 0.968 \| 1.136 \| 1.794 | 0.351 \| 1.703 \| 0.503 \| 0.860 | 0.296 \| 0.356 \| 0.407 \| 0.595 |
| SBA α=0.3 | 89 | 0.788 \| 0.957 \| 1.162 \| 1.778 | 0.333 \| 1.737 \| 0.438 \| 0.762 | 0.314 \| 0.359 \| 0.405 \| 0.640 |
| HW additive(12) | **66** | 0.741 \| 0.886 \| 1.035 \| 1.451 | 0.351 \| 0.554 \| 0.498 \| 0.841 | 0.288 \| 0.344 \| 0.382 \| 0.593 |
| Theta | 89 | 0.792 \| 0.981 \| 1.093 \| 1.624 | 0.363 \| 1.487 \| 0.486 \| 0.968 | 0.301 \| 0.359 \| 0.412 \| 0.598 |
| ARIMA(1,1,1) | 89 | 0.804 \| 1.009 \| 1.130 \| 1.662 | 0.365 \| 1.751 \| 0.558 \| 0.965 | 0.317 \| 0.367 \| 0.423 \| 0.610 |

**HW's `n` is 66, not 89** — it needs ≥ 24 months and 23 of the 89 don't have it.
Its column is not comparable to the others as printed. See §5 and the correction below.

### Scale-dependent metrics — per-SKU WIN COUNTS

Computed on the **66 SKUs evaluable for all five models** (ties split evenly):

| metric | MA3 | SBA α=0.3 | HW add(12) | Theta | ARIMA(1,1,1) |
|---|---|---|---|---|---|
| MAE wins | 14.0 | 13.0 | **21.0** | 7.0 | 11.0 |
| MSE wins | 8.0 | 14.0 | **21.0** | 8.0 | 15.0 |
| RMSE wins | 8.0 | 14.0 | **21.0** | 8.0 | 15.0 |
| MdAE wins | 12.0 | **18.0** | 15.0 | 11.0 | 10.0 |

> **Pooled medians (SCALE-BIASED — do not decide on these; reported only because
> asked):** median MAE MA3 1630 / SBA 1725 / HW 2584 / Theta 1516 / ARIMA 1526;
> median RMSE MA3 1957 / SBA 2094 / HW 3068 / Theta 1891 / ARIMA 1884; median MdAE
> MA3 1210 / SBA 1439 / HW 1991 / Theta 1206 / ARIMA 1163. A 50,000-unit SKU
> dominates a 200-unit one in every one of these numbers.

HW leads the squared-error win counts — but again only among the 66 it can serve,
and MSE/RMSE reward its tendency to over-smooth toward the mean on long, stable
series. On MdAE (typical error, outlier-robust) SBA leads and HW is mid-pack.

### Undefined / infinite

| model | MAPE = ∞ | MASE = ∞ | not evaluable (SKU dropped) | sMAPE = NaN |
|---|---|---|---|---|
| MA3 | 0 | 0 | 0 | 0 |
| SBA α=0.3 | 0 | 0 | 0 | 0 |
| HW additive(12) | 0 | 0 | **23** | 0 |
| Theta | 0 | 0 | 0 | 0 |
| ARIMA(1,1,1) | 0 | 0 | 0 | 0 |

No MAPE blow-ups on this 89-SKU set — the near-zero-actual SKUs that produce the
999.999 sentinels in `Forecast_Result` are among the 30 short-history / 13
insufficient SKUs, not the 89. MAPE means are still inflated (MA3 1.70, ARIMA
1.75) by a handful of 3–8× ratios that are finite but meaningless — which is why
median, not mean, is the honest MAPE summary, and why MAPE is not load-bearing
here at all.

---

## 0b. PROJECT THRESHOLD PASS RATES

| model | MASE < 1.0 (beats naive) | MAPE < 0.20 (manuscript hard gate) | sMAPE < 0.30 |
|---|---|---|---|
| MA3 | **60/89 (67 %)** | 6/89 (7 %) | 46/89 (52 %) |
| SBA α=0.3 | 60/89 (67 %) | 13/89 (15 %) | 40/89 (45 %) |
| HW additive(12) | 45/66 (68 %) | 8/66 (12 %) | 36/66 (55 %) |
| Theta | 57/89 (64 %) | 8/89 (9 %) | 44/89 (49 %) |
| ARIMA(1,1,1) | 60/89 (67 %) | 10/89 (11 %) | 41/89 (46 %) |

**The `MAPE < 0.20` gate is unachievable on this data.** The best any of the five
models manages is SBA at **15 %** of SKUs; MA3, HW, Theta and ARIMA are all
between 7 % and 12 %. This is not a model failure — monthly FMCG demand at SKU
grain, with the intermittency and the return/adjustment months this catalog has,
does not forecast to ±20 % per SKU regardless of method. **The gate itself should
be removed from the pipeline and the manuscript, or replaced with `MASE < 1.0`**
(which ~67 % of evaluable SKUs clear) plus a per-SKU sMAPE report. This needs to
be settled with the adviser before defence — it is a finding about the target,
not about MA3.

`MASE < 1.0`: MA3, SBA, ARIMA and HW are all within 1 point of each other
(64–68 %). `sMAPE < 0.30`: MA3 (52 %) is second only to HW-on-its-easy-66 (55 %)
and clearly ahead of SBA (45 %), Theta (49 %) and ARIMA (46 %).

---

## 1. SPREAD AND TAILS (MASE)

| model | mean | median | p75 | p90 | max | MASE > 1.5 | MASE > 2.0 |
|---|---|---|---|---|---|---|---|
| MA3 | 0.968 | 0.819 | 1.136 | 1.794 | 3.15 | 14/89 | 7/89 |
| SBA α=0.3 | 0.957 | 0.788 | 1.162 | 1.778 | 2.97 | 13/89 | 5/89 |
| HW additive(12) | 0.886 | 0.741 | 1.035 | 1.451 | 2.33 | 6/66 | 3/66 |
| Theta | 0.981 | 0.792 | 1.093 | 1.624 | 4.04 | 12/89 | 6/89 |
| ARIMA(1,1,1) | 1.009 | 0.804 | 1.130 | 1.662 | 4.30 | 15/89 | 7/89 |

- **ARIMA(1,1,1) has the worst mean (1.009 — worse than naive), worst max (4.30),
  and joint-worst `>1.5` count.** Its occasional blow-ups (a differenced AR/MA
  model chasing a spike on a 15–20-month series) are exactly the inventory
  failure mode to avoid. Ruled out.
- **Theta's max is 4.04** — same failure mode, less often.
- MA3 vs SBA on the full 89: SBA has marginally fewer extreme tails (5 vs 7 above
  2.0). Real but tiny.
- HW's tails look best (3/66 above 2.0) — but on the 66 easy SKUs; see the
  correction in §5.

---

## 2. PAIRED WILCOXON SIGNED-RANK vs MA3

| comparison | metric | n | p-value | sig? | other better | MA3 better | median favours |
|---|---|---|---|---|---|---|---|
| MA3 vs SBA α=0.3 | MASE | 89 | 0.405 | ns | 50 | 39 | SBA |
| | sMAPE | 89 | 0.681 | ns | 47 | 42 | MA3 |
| | MAE | 89 | 0.436 | ns | 50 | 39 | MA3 |
| MA3 vs HW add(12) | MASE | 66 | 0.380 | ns | 30 | **36** | MA3 |
| | sMAPE | 66 | 0.234 | ns | 29 | **37** | MA3 |
| | MAE | 66 | 0.221 | ns | 30 | **36** | MA3 |
| MA3 vs Theta | MASE | 89 | 0.460 | ns | 43 | 46 | Theta |
| | sMAPE | 89 | 0.389 | ns | 44 | 45 | MA3 |
| | MAE | 89 | 0.287 | ns | 43 | 46 | Theta |
| MA3 vs ARIMA(1,1,1) | MASE | 89 | 0.265 | ns | 38 | **51** | ARIMA |
| | sMAPE | 89 | 0.105 | ns | 38 | **51** | MA3 |
| | MAE | 89 | 0.085 | ns | 38 | **51** | ARIMA |

**Not one candidate beats MA3 at p < 0.05 on any of MASE, sMAPE or MAE.** Every
p-value is between 0.085 and 0.68. Head-to-head, MA3 wins the SKU-count against
HW (36/66) and ARIMA (51/89) and is a coin-flip against SBA and Theta. The
"SBA has a better median MASE" result that started this whole thread does not
survive a paired test — p = 0.41.

---

## 3. STABILITY ACROSS ORIGINS

Per SKU: standard deviation of the 6 one-step signed errors. Median across SKUs,
and that median expressed as a fraction of the SKU's own mean demand:

| model | median err-std (units) | median (err-std ÷ SKU mean demand) |
|---|---|---|
| ARIMA(1,1,1) | 1982 | 33.3 % |
| HW additive(12) | 2993 | 33.6 % |
| SBA α=0.3 | 2006 | 34.0 % |
| MA3 | 2127 | 34.4 % |
| Theta | 2068 | 34.8 % |

**All five are within 1.5 percentage points.** No candidate delivers a
meaningfully steadier month-to-month error, so none offers the "safety stock that
stops swinging" benefit SSM is after. This dimension does not separate the models
and cannot be used to justify a switch.

---

## 4. DIRECTIONAL BIAS (signed error = forecast − actual; + = over-forecast)

| model | median signed err (SKU-origin) | median per-SKU ME | over-forecast | under-forecast |
|---|---|---|---|---|
| **MA3** | **+62** | **+51** | 286/530 (54 %) | 244/530 (46 %) |
| SBA α=0.3 | **−110** | **−287** | 222/530 (42 %) | **308/530 (58 %)** |
| HW additive(12) | +148 | +196 | 236/389 (61 %) | 153/389 (39 %) |
| Theta | +124 | +138 | 314/530 (59 %) | 216/530 (41 %) |
| ARIMA(1,1,1) | +91 | +85 | 296/530 (56 %) | 234/530 (44 %) |

**MA3 is the least biased of the five, and biased in the safe direction.** Its
+51-unit median per-SKU ME is the closest to zero; its 54/46 over/under split is
the most balanced.

**SBA α=0.3 is the only candidate that systematically under-forecasts** — 58 % of
SKU-origins, a −287-unit median per-SKU ME. For this system that is the wrong
direction: `ROP = forecast + safety stock`, so a forecast biased low pulls the
reorder point low, and the LP weights service level highest (w1 = 0.45 vs
w2 = 0.35 cost). [Corrected 2026-11-13: reversed. w1 = 0.45 is purchase cost, w2 = 0.35 the revenue-weighted share of need
met, w3 = 0.20 storage (analytics/params.py LP_WEIGHTS); the LP fills the need in layers before any weight applies, and the
ROP = forecast + SS model described here was retired 2026-09-30.] A model that under-shoots demand more than half the time
converts directly into stockout risk that the safety-stock buffer then has to
paper over. This is the single clearest behavioural difference in the whole
analysis, and it favours MA3 over its closest rival.

HW and Theta over-forecast most (61 %, 59 %) — that is the "safe" direction but it
is holding cost, which the LP also penalises. [Corrected 2026-11-13: it does not. The LP charges a flat storage cost per piece
ordered, the same for every product, which cannot change a plan; it has no holding-cost term on stock held.]

---

## 5. THE 30 SHORT-HISTORY SKUs (span 4–12 months)

These are excluded from the 89 but every one still gets a production forecast
(they clear `run_baseline_forecast.py`'s `status='ok'` gate). Can each candidate
produce a finite, sane forecast fitting on 4–12 months?

| model | finite & sane | NaN | zero/degenerate |
|---|---|---|---|
| MA3 | **30/30** | 0 | 0 |
| SBA α=0.3 | **30/30** | 0 | 0 |
| Theta | **30/30** | 0 | 0 |
| ARIMA(1,1,1) | **30/30** | 0 | 0 |
| **HW additive(12)** | **0/30** | **30** | 0 |

**Holt-Winters cannot serve a single one of the 30** (`m_hw_add` returns NaN when
`len(x) < 2 × 12`). Adopting HW as *the* production model would mean a second
model for 30 of 132 Tier-A SKUs — and a third path for the 13 `insufficient_data`
SKUs. Per the brief's own criterion ("a model that wins on the 89 but cannot serve
the other 43 Tier A SKUs is not deployable as a single method"), **HW is
disqualified outright.**

### Correction to HW's headline number

HW's MASE median of 0.741 is measured only on the 66 long-history SKUs. Measured
on **those exact 66 SKUs**, the other four models are all *better*:

| model, on HW's own 66 SKUs | MASE median | MASE mean | MASE p90 | MASE < 1 |
|---|---|---|---|---|
| SBA α=0.3 | **0.711** | 0.850 | 1.326 | 49/66 |
| Theta | 0.715 | 0.849 | 1.336 | 49/66 |
| **MA3** | **0.720** | 0.850 | 1.403 | 49/66 |
| ARIMA(1,1,1) | 0.733 | 0.875 | 1.413 | 50/66 |
| **HW additive(12)** | **0.741** | 0.886 | 1.451 | **45/66** |

**On a like-for-like population, Holt-Winters is the worst of the five, not the
best.** Its apparent advantage in §0/§1 is entirely a population artifact — it was
being scored only on the easiest third of the catalogue (the 23 SKUs it can't
serve have MA3 MASE median 1.136; those are what drag MA3's full-89 median from
0.720 up to 0.819). Imposing a 12-month seasonal structure — on a catalogue where
lag-12 autocorrelation is significant in only 5.1 % of SKUs — makes HW *worse*,
not better, even where it can run.

---

## 6. IMPLEMENTATION COST

| candidate | in `analytics/forecasting/`? | to adopt as production | new dep | params to tune |
|---|---|---|---|---|
| **MA3** | **yes** (`baseline.py::moving_average_forecast`), already deployed (`DEPLOYED_METHOD="ma3"`) | nothing | none | none (`MA_WINDOW=3`) |
| SBA α=0.3 | yes (`baseline.py::sba_forecast`, `alpha` is an argument) | change one constant `SBA_ALPHA` 0.1 → 0.3; update `DEPLOYED_METHOD`; re-run `--write` | none | α (would still be untuned — a coarse 5-point grid picked 0.3, no per-SKU CV) |
| Theta | **no** | new module wrapping `statsmodels.tsa.forecasting.theta.ThetaModel`; wire into `run_baseline_forecast` + backtest | none (statsmodels present) | `period` (falls back to 1 on short series — a silent behaviour switch to document) |
| ARIMA(1,1,1) | partial (`sarima.py` does a seasonal grid search, not a fixed non-seasonal order) | new fixed-order path or a heavy simplification of `sarima.py`; ~100× slower per fit than MA3 | none | (p,d,q) fixed at (1,1,1) — itself an untested choice vs auto-order, which the bake-off showed is *worse* |
| HW additive(12) | **no** | new module + **a fallback model for 30/132 Tier-A SKUs** + a seasonal-period decision | none | `seasonal_periods` — and lag-12 seasonality exists in only 5.1 % of SKUs (DEC-23), so the seasonal component fits noise for ~95 % of the catalogue |

MA3 is the only option with zero adoption cost. Every alternative requires code
for a gain that §2 shows is not statistically real.

---

## 7. VERDICT AND THE METRIC IT RESTS ON

### Decision: keep MA3. No change to the production model.

**Why:**

1. **No candidate beats MA3 at p < 0.05 on MASE, sMAPE, or MAE** (§2). The median
   gaps that make SBA/HW/Theta look better in a ranking table (−0.03, −0.08,
   −0.03 MASE) all evaporate under a paired signed-rank test. With 89 noisy
   monthly series, a 0.03 median difference is noise, and the test says so.
2. **Holt-Winters is disqualified twice over**: it cannot forecast 30 of 132
   Tier-A SKUs at all (§5), and on a like-for-like population it is the *worst* of
   the five, not the best (§5 correction). Its headline number was a population
   artifact.
3. **ARIMA(1,1,1) is the worst survivor** — mean MASE above 1.0 (loses to naive
   on average), worst max error (4.30), ~100× slower, beats MA3 on nothing (§1,
   §2).
4. **SBA α=0.3, the only real contender, is behaviourally wrong for this system**:
   it under-forecasts 58 % of the time with a −287-unit median bias (§4). In a
   `ROP = forecast + safety stock` pipeline whose LP weights service level highest
   (w1 = 0.45), a low-biased forecast is a stockout generator. [Corrected 2026-11-13: w1 = 0.45 is purchase cost, not
   service; see §4's correction.] MA3's mild
   over-forecast (+51, 54/46) is the safe direction.
5. **No candidate is meaningfully more stable across origins** (§3, all within
   1.5 pp) — so the one thing that could justify a switch on SSM's own terms
   (steadier safety stock) isn't on offer.
6. **MA3 costs nothing to keep** and is already the deployed method; every
   alternative is code for a null result.

### The metric the recommendation rests on: **MASE, judged by paired test.**

Not the pooled median, not MAPE, not MAE.

- **Scale-free.** Tier-A SKUs run from ~200 to >50,000 units/month. Any pooled or
  averaged scale-dependent metric (MAE, MSE, RMSE) lets the largest SKUs pick the
  model, and the resulting choice is meaningless for the small ones. MASE puts a
  200-unit SKU and a 50,000-unit SKU on the same footing — which is what a
  per-SKU replenishment recommendation needs.
- **Decision-relevant baseline.** `MASE < 1` means "beats reordering last month's
  demand" — and reordering last month's demand is exactly what SSM's planners
  could do with no system at all. MASE answers the only question that justifies
  the forecast existing: *does it beat the free alternative?*
- **Robust to this data's pathology.** MAPE is uninterpretable here — near-zero
  and negative actual months send it to 3–8× and beyond, and its `< 0.20` gate is
  unachievable for every model (§0b). sMAPE is a reasonable bounded secondary and
  it agrees with MASE (MA3 second-best). MASE, judged per-SKU and aggregated by a
  signed-rank test rather than a single median, is the metric that neither
  over-rewards the big SKUs nor breaks on the small ones.

### What is gained by switching: nothing measurable. What is risked: a
under-forecast bias (SBA) or a 30-SKU coverage hole (HW). Keep MA3.

### Separate, non-model finding for the adviser

The manuscript's `MAPE < 0.20` hard gate is **not achievable** on this data with
any of the five models (best is 15 %, §0b). Recommend replacing it with
`MASE < 1.0` + a per-SKU sMAPE report, and settling that with the adviser before
defence. This is independent of the MA3 decision.
