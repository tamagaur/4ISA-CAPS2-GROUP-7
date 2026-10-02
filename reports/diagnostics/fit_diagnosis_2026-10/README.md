# Fit diagnosis 2026-10: overfit, underfit and bias (Unilever, real data only)

**Unilever only. Del Monte has no product-level sales**, so it is not forecast and has no product-level fit to diagnose.

Cohort: Unilever **Tier A as of 2026-02** (ABC method `single`, 132 SKUs), real rows only
(`Unilever_SKU_Demand_Fact_Real`, 2023-01..2026-02). The run is read-only: one `READ ONLY` transaction, rolled back.
Script: `run_fit_diagnosis.py` (beside this file). Run 2026-10-02.

## Check (passed before anything was scored)

| check | result |
|---|---|
| live router re-run reproduces `public.forecast_result` at 2026-03-01 (status, method, forecast_value) | 132/132 |
| live router re-run reproduces stored MASE (`ok` rows) | 119/119 |
| verdicts (common window / 20% split, thresholds in `../README.md`) | 79 fit / 12 borderline / 28 not fit (same as on record) |

## Holdout used (same as the verdicts on record)

- **107 SKUs: the common window, 2025-09..2026-02** (6 months). The router runs one step ahead with the SKU's served bin
  held fixed. MASE scale = the mean absolute lag-1 change over the real months before 2025-09.
- **12 short-bin SKUs: the stored 20% split** (`train_holdout_split`), with its own training scale. The common window
  cannot score these SKUs: 8 first sold in 2025-09..2025-11, and 4 first sold in 2025-08, which leaves a single month
  before the window and so no lag-1 change to scale by.
- 13 SKUs with fewer than 3 months of sales are not scored (status `insufficient_data`).

## Rules

| flag | rule |
|---|---|
| overfit (MA3 as the control) | the served model's ratio, holdout MASE ÷ in-sample MASE, exceeds **both** (a) **2.69**, the 95th percentile of MA3's own ratio over the same products and months, **and** (b) **that same product's own MA3 ratio**. MA3-served products are reported as **not assessable (control)** |
| underfit | in-sample MASE **≥ 1** and holdout MASE **≥ 1** |
| bias, per product | mean signed error (forecast − actual) on the holdout. Flagged only when **\|t\| ≥ 2.571** (two-sided 95% t value, 5 degrees of freedom) over **its 6 months**. Only common-window SKUs have 6 months, so the 12 split SKUs are not bias-tested |
| bias, pooled | Σ(forecast − actual) / Σ actual over all holdout SKU-months, by served model |

Both MASEs use the **same scale**, so the ratio is the ratio of mean absolute errors.

### Why MA3 is the control, and where 2.69 comes from

MA3 has no fitted parameters, so it cannot memorise its training months. When MA3's own error rises from in-sample to
holdout, the holdout months are simply harder. A served model counts as overfit only if its error rises **more than
MA3's does on the same product**, and also more than MA3's rise does on all but the top 5% of products.

**2.69** is measured, not chosen. For each scored product, MA3's holdout MASE is divided by MA3's in-sample MASE (in-sample
as defined below), and 2.69 is the 95th percentile of that ratio over the **106 products where it is defined**. Exact
value: 2.691; the script recomputes it every run and stores it as `ma3_p95_ratio`. 13 short products have no in-sample
months, so no ratio.

### How in-sample is defined, per model

In-sample means the SKU's training months, i.e. the months before its holdout. Counting starts at the 3rd month after
first sale (`MIN_HISTORY`, the first month XGBoost can train on), and every model uses the same months.

| served model (bin) | in-sample fit for month *t* |
|---|---|
| MA3 (short), and MA3 as the control for every product | the mean of the 3 months before *t*. MA3 has no fitted parameters, so its in-sample error is just its one-step error on the training months |
| TSB (medium) | the one-step fitted value of the TSB recursion (`baseline.tsb_forecast`, fixed α 0.3 / 0.1). Its starting states are the whole training window's averages, which is the only thing estimated from data. The router's guards apply (above the history's max, or below zero, means MA3) |
| XGBoost + MA3 average (long) | the booster trained on every pool row before the holdout's first month (the model the holdout's first month uses) predicts this SKU's own training rows. This is in-sample in the strict sense. The prediction is averaged with MA3 and the router's guards apply (no XGBoost number means MA3) |

## Finding

**Errors rose in the latest test period for simple and complex models alike: a harder period, not overfitting.**

- Over the 107 common-window products, median MASE rose from in-sample to holdout for MA3 (0.775 → 0.795) and for the
  served models (0.651 → 0.692).
- The rise is concentrated in the products that look overfit at first sight. MA3 shows the same jump on them. On the
  17 TSB products, MA3's median ratio is 1.48 and TSB's is 1.82.
- No non-MA3 product clears 2.69 without also clearing its own MA3 ratio. 64 of the 89 non-MA3 products have a ratio
  above their own MA3 ratio but below 2.69, which is the ordinary gap between a fitted model and MA3.
- The 5 products that meet both conditions sit only **1.01–1.15×** above their own MA3 ratio.

## Results

| overfit status | products |
|---|---|
| overfit | **5** |
| not overfit | 84 |
| not assessable (control), MA3-served | 30 |

**Overfit: 5 products, all not fit.** Their margin over their own MA3 ratio is small, so read them as borderline cases
of the harder period, not as models that memorised noise.

| SKU | product | bin / model | in-sample MASE | holdout MASE | ratio | own MA3 ratio | ratio ÷ MA3's | in-sample months |
|---|---|---|---|---|---|---|---|---|
| `68764004` | LADY'S CHOICE SS HAM DOY 24X220ML | medium / tsb | 0.702 | 3.005 | 4.28 | 4.23 | 1.01 | 12 |
| `69695564` | LADY'S CHOICE REAL MAYO 4X3.5L | long / xgb_ma3_avg | 0.561 | 2.246 | 4.00 | 3.49 | 1.15 | 15 |
| `64784421` | KNORR CUBES CHICKEN DUO 48X6X20G | medium / tsb | 0.571 | 2.049 | 3.59 | 3.18 | 1.13 | 11 |
| `64788596` | CREAM SILK RO ULTREBORN HF 24(11+1)X22ML | medium / tsb | 0.806 | 2.682 | 3.33 | 3.11 | 1.07 | 11 |
| `67749043` | KNORR SINIGANG SAM ORIG 24X12X11G | long / xgb_ma3_avg | 0.889 | 2.625 | 2.95 | 2.77 | 1.07 | 29 |

**Underfit: 1 product.** `64900506` CREAM SILK TMT RBOND STRT 24(11+1)X18ML (short / MA3) has in-sample MASE 1.040
and holdout MASE 2.181. It is MA3-served, so its overfit status is "not assessable (control)".

**Biased: 2 of the 107 tested products**, both over-forecast:

| SKU | product | bin / model | verdict | mean error (units/month) | t | direction |
|---|---|---|---|---|---|---|
| `64314335` | DOVE SH KERATIN STRT&SILKY 288X13.5ML | medium / tsb | not fit | +18,322 | 3.60 | over-forecast |
| `64900598` | CREAM SILK TRI-KRTN SCD STRT 288X14ML | short / ma3 | fit | +4,748 | 2.75 | over-forecast |

**Pooled bias**, Σ(forecast − actual) / Σ actual over the holdout:

| served model | SKUs | pooled bias | SKUs with mean error > 0 |
|---|---|---|---|
| MA3 | 30 | +4.5% | 14 |
| TSB | 17 | +24.9% | 12 |
| XGBoost + MA3 average | 72 | +8.0% | 48 |

All three models over-forecast on balance. TSB over-forecasts most, but only 1 TSB product passes the per-product t
test, because 6 months leave each product test little power.

## Cross-tab: the 28 not-fit SKUs

| fit class | short (MA3) | medium (TSB) | long (XGBoost+MA3) | total |
|---|---|---|---|---|
| overfit | 0 | 3 | 2 | 5 |
| underfit | 1 | 0 | 0 | 1 |
| biased (over-forecast) | 0 | 1 | 0 | 1 |
| none of the three | 0 | 5 | 9 | 14 |
| none (overfit not assessable: MA3 is the control) | 4 | 0 | 0 | 4 |
| fit not testable (no in-sample months) | 3 | 0 | 0 | 3 |
| **total** | **8** | **9** | **11** | **28** |

Selection caveat (`../README.md`): these 28 were picked *because* they scored badly. A pattern found inside them does
not, on its own, support a model change.

## Files

| file | contents |
|---|---|
| `per_sku.csv` | 119 scored SKUs: holdout source and months, in-sample months, MASE scale, in-sample and holdout MASE, ratio, MA3's in-sample, holdout and ratio, `ma3_p95_ratio`, `overfit_status`, WAPE, mean and SD of the error, t, the sums used for pooled bias, verdict, flags |
| `classified.csv` | the same 119 rows: verdict, `overfit_status`, the three flags (`overfit` is blank for MA3-served products) and one `fit_class` label |
| `run_fit_diagnosis.py` | the script. Its harness functions are reused by `reports/simulation/synthetic_2026-10/run_simulation.py`. `--cache FILE` keeps a local pickle of the loaded rows |
