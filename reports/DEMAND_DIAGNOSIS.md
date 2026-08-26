# Demand Diagnosis — Unilever Only

Diagnosis only. No model code changed, nothing refit, nothing written to
`forecast_result`. All numbers below are from live queries against
`Unilever_SKU_Demand_Fact_Real` (24,906 rows, 1,807 distinct SKUs),
`ABC_Classification`, and the existing `Forecast_Result` rows — read-only.

Companion CSVs: `reports/demand_diagnosis_shape_full.csv` (all 1,807
SKUs' demand-shape classification), `reports/demand_diagnosis_ok_mape_mase.csv`
(the 89 `status='ok'` rows, MAPE/MASE side by side).

---

## 1. Coverage gap — 136 of 1,807

**It's a filter, not a limit, a crash, or a partial run.** `run_sarima.py`'s query:

```sql
SELECT
    pd.product_key, pd.sku_code, pd.principal, d.period,
    SUM(d.quantity) as total_quantity
FROM (
    SELECT sf.product_key, sf._period as period, sf.quantity
    FROM SellOut_Fact_Real sf
    JOIN Product_Dimension p ON sf.product_key = p.product_key
    WHERE p.principal = 'delmonte'
    UNION ALL
    SELECT product_key, calendar_month as period, quantity_sold as quantity
    FROM Unilever_SKU_Demand_Fact_Real
) d
JOIN Product_Dimension pd ON d.product_key = pd.product_key
JOIN ABC_Classification abc ON abc.product_key = pd.product_key
WHERE abc.tier = 'A'
  AND abc.classification_period = (
      SELECT MAX(classification_period) FROM ABC_Classification abc2
      WHERE abc2.principal = abc.principal
  )
GROUP BY pd.product_key, pd.sku_code, pd.principal, d.period
ORDER BY pd.product_key, d.period ASC
```

No `LIMIT` anywhere in the pipeline. `WHERE abc.tier = 'A'` is the gate —
by design, only Tier-A (fast-moving) SKUs get a SARIMA fit at all; the
ABC-then-forecast structure is the point of the pipeline, not an
accident. Confirmed live: `ABC_Classification`'s latest Unilever
`classification_period` is **2026-08**, and Tier A at that period is
**exactly 136** — matching `Forecast_Result`'s row count 1:1
(`136 unilever / 0 delmonte`, status breakdown `ok=89, insufficient_data=37,
dead_sku=10`, no `fit_failed`, no `unreliable`). Nothing crashed and no
run was cut short; every Tier-A SKU that was attempted has a saved row.

**Without the Tier-A filter, all 1,807 classified SKUs would be
attempted** — Tier A (136) + Tier B (178) + Tier C (1,493) = 1,807, the
full `ABC_Classification` population for the 2026-08 period. (Note:
`Product_Dimension` now has 2,098 Unilever rows after this session's
earlier SOH Product_Dimension insert — the 291 new rows have zero sales
history in `Unilever_SKU_Demand_Fact_Real` and were never classified by
ABC at all, so they're outside both the 1,807 and the 136.)

---

## 2. Demand shape, per SKU (all 1,807)

Built each SKU's full 38-month grid (2023-01..2026-02, the corpus's real
span), zero-filled for months with no row (confirmed: **zero explicit
zero-quantity rows exist in the source — an absent month means zero
sold**, not a data gap). `ADI = 38 / months_with_demand`. `CV² =
(std/mean)²` of the non-zero months only.

| | |
|---|---|
| Mean % zero-months across all SKUs | 66.2% |
| Median % zero-months | 78.9% |

**Class counts (all 1,807):**

| Class | Count |
|---|---|
| intermittent | 589 |
| lumpy | 518 |
| unclassifiable (<2 nonzero months) | 398 |
| smooth | 263 |
| erratic | 39 |

**Class × ABC tier:**

| class | A | B | C | All |
|---|---|---|---|---|
| erratic | 0 | 5 | 34 | 39 |
| intermittent | 47 | 65 | 477 | 589 |
| lumpy | 12 | 18 | 488 | 518 |
| smooth | 77 | 90 | 96 | 263 |
| unclassifiable | 0 | 0 | 398 | 398 |
| **All** | **136** | **178** | **1,493** | **1,807** |

The 136 SKUs actually forecasted (Tier A) skew far more forecastable
than the corpus as a whole: **57% smooth, 35% intermittent, 9% lumpy, 0%
erratic, 0% unclassifiable** — vs. only 15% smooth corpus-wide. The
`unclassifiable` bucket (<2 nonzero months in 38 — essentially
one-off/dead SKUs) is 100% Tier C, confirming the ABC gate is doing
useful pre-filtering, not admitting noise into SARIMA.

---

## 3. Metric sanity — the 89 `status='ok'` rows

| | MAPE (%) | MASE |
|---|---|---|
| count | 89 | 89 |
| mean | 244.2 | 4.72 |
| min | 9.99 | 0.29 |
| 25% | 35.6 | 0.84 |
| median | 59.4 | 1.29 |
| 75% | 225.9 | 2.12 |
| max | 999.999 (capped) | 106.1 |

Correlation between the two metrics across these 89 rows: **r = 0.41** —
moderate at best. They frequently disagree about which SKUs forecast
well.

**MASE < 1 (beating naive seasonal): 33 / 89 (37%).**

**Highest-MAPE rows — confirmed, not refuted: huge MAPE tracks
near-zero actuals.** All 15 rows hitting the 999.999 cap (the code caps
`mape*100` at 999.999; raw MAPE exceeded ~1000% before capping) were
checked against their actual holdout values (reconstructed exactly as
`run_sarima.py` builds them: per-SKU date range, monthly-resampled,
zero-filled, last `round(len*0.2)` months as holdout). Every one of the
15 has at least one holdout month at or within a few units of zero —
several have literal **negative** `quantity_sold` values in the holdout
window (e.g. SKU 62720543: holdout `[0.0, 0.0, 5976.0, 192.0, -12.0]`;
SKU 68705295: holdout `[-288.0, 0.0, 144.0, 0.0, 0.0, 0.0, -6.0]`).
MAPE's denominator is `|actual|`, so a holdout point of `-1` or `-2`
turns a perfectly reasonable forecast error into a four-digit percentage
— this is a metric artifact, not a real accuracy failure. Notably, MASE
stays sane on the same rows (e.g. SKU 68302836: MAPE capped at 999.999,
MASE only 0.613 — actually beats naive seasonal despite the MAPE
number looking catastrophic). **MAPE should not be trusted as the
primary accuracy gate for this demand profile; MASE is the more honest
signal.**

(The negative `quantity_sold` values themselves are a separate,
unexplained finding worth a note to Yuan — `Unilever_SKU_Demand_Fact`
is sourced from `net_amount`-adjacent aggregation of the La Union file's
per-row quantities, and a negative monthly sum implies returns/
adjustments exceeding that month's gross sales for that SKU. Not
investigated further here — diagnosis-only scope.)

---

## 4. Seasonality reality check

**255 of 1,807 SKUs** have a per-SKU series span ≥ 36 months (≥3 full
12-month seasonal cycles) — computed the same way `run_sarima.py` builds
its series (first-sale to last-sale date range, monthly resampled,
zero-filled), not just "≥36 non-zero months." (529 SKUs clear the
weaker ≥24-month bar `run_sarima.py` actually gates on.)

**Sample of 20** (fixed seed, drawn from the 255-SKU ≥36-month pool),
lag-12 autocorrelation vs. the standard 95% significance bound
(±1.96/√n):

| sku_code | n | ACF(lag 12) | 95% bound | significant? |
|---|---|---|---|---|
| 20293279 | 38 | 0.049 | 0.318 | no |
| 20293283 | 38 | 0.053 | 0.318 | no |
| 21051980 | 38 | 0.022 | 0.318 | no |
| 65000841 | 38 | 0.120 | 0.318 | no |
| 65004665 | 38 | 0.199 | 0.318 | no |
| 67469129 | 38 | -0.033 | 0.318 | no |
| 67737493 | 38 | 0.175 | 0.318 | no |
| 67834803 | 38 | 0.053 | 0.318 | no |
| 68178534 | 38 | -0.004 | 0.318 | no |
| 68387098 | 38 | -0.104 | 0.318 | no |
| 68535281 | 38 | 0.036 | 0.318 | no |
| 68559747 | 36 | -0.006 | 0.327 | no |
| 68562672 | 38 | -0.039 | 0.318 | no |
| 68565212 | 38 | 0.019 | 0.318 | no |
| 68629960 | 38 | -0.140 | 0.318 | no |
| 68668443 | 38 | -0.071 | 0.318 | no |
| 68690506 | 38 | -0.157 | 0.318 | no |
| 68736087 | 38 | 0.052 | 0.318 | no |
| 68832572 | 38 | -0.011 | 0.318 | no |
| 68864119 | 38 | 0.050 | 0.318 | no |

**0 / 20 show statistically significant lag-12 autocorrelation.** Every
value is well inside the 95% bound (largest magnitude 0.199, bound
~0.32). This is a real, if small-sample, warning sign: on this sample,
**SARIMA's seasonal component has no measurable annual pattern to fit —
it is very likely fitting noise**, not structure. Consistent with the
demand-shape finding above (this corpus is dominated by
intermittent/lumpy demand with 66% zero-months on average; classical
seasonal decomposition assumes a much denser, more regular series than
most of these SKUs actually have). Worth widening this sample and/or
running a formal seasonality test (e.g. QS or Ljung-Box on seasonal
lags) before trusting the seasonal terms `run_sarima.py`'s grid search
selects, but the directional signal here is clear enough to flag now.

---

## Summary

- 136/1,807 forecasted is intentional (Tier-A ABC gate), not a bug — but confirms most SKUs (89%) never reach SARIMA at all under the current design.
- Tier A itself is reasonably forecastable-shaped (92% smooth+intermittent), the corpus at large is not (66% zero-months, 398 SKUs with <2 sales months ever).
- MAPE is unreliable on this data — near-zero and even negative holdout actuals repeatedly blow it up to the 999.999 cap on forecasts that MASE says are fine. MASE (33/89 <1) is the metric to trust.
- No measurable lag-12 seasonality found in a 20-SKU sample of the longest, best-covered series — the seasonal SARIMA terms are suspect and deserve a dedicated seasonality test before being relied on.
