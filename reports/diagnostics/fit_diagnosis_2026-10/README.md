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

## Rules (fixed before computing)

| flag | rule |
|---|---|
| overfit | holdout MASE ÷ in-sample MASE **> 2.07** (given as the 95th percentile of MA3's own ratio on the same products and months; see the caveat below) |
| underfit | in-sample MASE **≥ 1** and holdout MASE **≥ 1** |
| bias, per product | mean signed error (forecast − actual) on the holdout. Flagged only when **\|t\| ≥ 2.571** (two-sided 95% t value, 5 degrees of freedom) over **its 6 months**. Only common-window SKUs have 6 months, so the 12 split SKUs are not bias-tested |
| bias, pooled | Σ(forecast − actual) / Σ actual over all holdout SKU-months, by served model |

Both MASEs use the **same scale**, so the ratio is the ratio of mean absolute errors.

### How in-sample is defined, per model

In-sample means the SKU's training months, i.e. the months before its holdout. Counting starts at the 3rd month after
first sale (`MIN_HISTORY`, the first month XGBoost can train on), and every model uses the same months.

| served model (bin) | in-sample fit for month *t* |
|---|---|
| MA3 (short) | the mean of the 3 months before *t*. MA3 has no fitted parameters, so its in-sample error is just its one-step error on the training months |
| TSB (medium) | the one-step fitted value of the TSB recursion (`baseline.tsb_forecast`, fixed α 0.3 / 0.1). Its starting states are the whole training window's averages, which is the only thing estimated from data. The router's guards apply (above the history's max, or below zero, means MA3) |
| XGBoost + MA3 average (long) | the booster trained on every pool row before the holdout's first month (the model the holdout's first month uses) predicts this SKU's own training rows. This is in-sample in the strict sense. The prediction is averaged with MA3 and the router's guards apply (no XGBoost number means MA3) |

13 short SKUs have **no in-sample months** (training is ≤ 3 months after first sale). Their ratio is undefined and they
are labelled "fit not testable".

### Caveat: the 2.07 threshold did not reproduce

Under the in-sample definition above, **the 95th percentile of MA3's own ratio is 2.691** (106 SKUs with a defined
ratio). Eight other natural definitions also failed to reproduce 2.07: start month 1 or 2, untrimmed series,
common-window SKUs only, the 20% split for all SKUs. They give 2.34 to 2.86. No derivation of 2.07 is on file. The
rule uses 2.07 as given; `overfit_at_recomputed_p95` in `per_sku.csv` is the sensitivity column. At 2.691, **6** SKUs
are overfit instead of 14.

## Results

**Overfit: 14 SKUs** (13 not fit, 1 borderline). In 11 of the 14, **MA3's own ratio on the same months is also above
2.07**. MA3 cannot memorise anything, so for these SKUs the jump comes from holdout months that are harder than the
training months (a level shift), not from a model that fit noise. Only 3 SKUs have a served ratio above 2.07 while
MA3's is not: `65004662`, `64784425`, `67749046`. `64401259` rests on 1 in-sample month and `64900506` on 1 holdout
month.

| SKU | product | bin / model | verdict | in-sample MASE | holdout MASE | ratio | MA3's ratio | months in / out |
|---|---|---|---|---|---|---|---|---|
| `64401259` | BESTFOODS ALL PURPOSE DRSG 4X3.5L | short / ma3 | not fit | 0.009 | 1.833 | 193.42 | 193.42 | 1 / 6 |
| `68764004` | LADY'S CHOICE SS HAM DOY 24X220ML | medium / tsb | not fit | 0.702 | 3.005 | 4.28 | 4.23 | 12 / 6 |
| `69695564` | LADY'S CHOICE REAL MAYO 4X3.5L | long / xgb_ma3_avg | not fit | 0.561 | 2.246 | 4.00 | 3.49 | 15 / 6 |
| `64784421` | KNORR CUBES CHICKEN DUO 48X6X20G | medium / tsb | not fit | 0.571 | 2.049 | 3.59 | 3.18 | 11 / 6 |
| `64788596` | CREAM SILK RO ULTREBORN HF 24(11+1)X22ML | medium / tsb | not fit | 0.806 | 2.682 | 3.33 | 3.11 | 11 / 6 |
| `67749043` | KNORR SINIGANG SAM ORIG 24X12X11G | long / xgb_ma3_avg | not fit | 0.889 | 2.625 | 2.95 | 2.77 | 29 / 6 |
| `64861488` | SURF PWDR PURPLE BLOOMS L 40(6+1)65G | short / ma3 | not fit | 0.765 | 1.878 | 2.46 | 2.46 | 3 / 6 |
| `68438409` | KNORR BN CUBES CHICKEN SINGLES 48X12X10G | long / xgb_ma3_avg | not fit | 0.841 | 1.978 | 2.35 | 2.21 | 29 / 6 |
| `65004662` | BESTFOODS RGLR MYNS MAYOMAGICDOY24X220ML | long / xgb_ma3_avg | not fit | 0.901 | 2.118 | 2.35 | 1.78 | 29 / 6 |
| `68763994` | LADY'S CHOICE SS CHICKEN JAR 12X470ML | medium / tsb | borderline | 0.484 | 1.097 | 2.27 | 2.12 | 11 / 6 |
| `64784425` | KNORR CUBES PORK DUO 48X6X20G | medium / tsb | not fit | 0.748 | 1.694 | 2.27 | 2.06 | 12 / 6 |
| `67749045` | KNORR SINIGANG NA GABI 24X12X11G | long / xgb_ma3_avg | not fit | 0.741 | 1.628 | 2.20 | 2.09 | 29 / 6 |
| `67749046` | KNORR SINIGANG ISDA 24X12X11G | long / xgb_ma3_avg | not fit | 0.598 | 1.284 | 2.15 | 1.80 | 29 / 6 |
| `64900506` | CREAM SILK TMT RBOND STRT 24(11+1)X18ML | short / ma3 | not fit | 1.040 | 2.181 | 2.10 | 2.10 | 3 / 1 |

**Underfit: 1 SKU.** `64900506` has in-sample MASE 1.040 and holdout MASE 2.181. It is also on the overfit list.

**Biased: 2 of the 107 tested SKUs**, both over-forecast:

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

All three models over-forecast on balance. TSB over-forecasts most, but only 1 TSB SKU passes the per-product t test,
because 6 months leave each product test little power.

## Cross-tab: the 28 not-fit SKUs

| fit class | short (MA3) | medium (TSB) | long (XGBoost+MA3) | total |
|---|---|---|---|---|
| overfit | 2 | 4 | 6 | 12 |
| overfit + underfit | 1 | 0 | 0 | 1 |
| biased (over-forecast) | 0 | 1 | 0 | 1 |
| none of the three | 2 | 4 | 5 | 11 |
| fit not testable (no in-sample months) | 3 | 0 | 0 | 3 |
| **total** | **8** | **9** | **11** | **28** |

Selection caveat (`../README.md`): these 28 were picked *because* they scored badly. A pattern found inside them does
not, on its own, support a model change.

## Files

| file | contents |
|---|---|
| `per_sku.csv` | 119 scored SKUs: holdout source and months, in-sample months, MASE scale, in-sample and holdout MASE, ratio, MA3's in-sample, holdout and ratio, WAPE, mean and SD of the error, t, the sums used for pooled bias, verdict, flags, `overfit_at_recomputed_p95` |
| `classified.csv` | the same 119 rows: verdict, the three flags and one `fit_class` label |
| `run_fit_diagnosis.py` | the script. Its harness functions are reused by `reports/simulation/synthetic_2026-10/run_simulation.py`. `--cache FILE` keeps a local pickle of the loaded rows |
