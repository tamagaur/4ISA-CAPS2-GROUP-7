# Fit diagnosis 2026-10-07 (exp/fit-diagnosis, not merged)

**Cohort:** Unilever Tier A, basis `t12m_new` (via `abc_method()`), ABC period 2026-02 = 189 products. 175 are
`ok` and scored; 9 insufficient_data + 5 dead_sku are not forecast. Del Monte is out (no product-level sales).
**Data:** real only (`Unilever_SKU_Demand_Fact_Real`), one READ ONLY transaction, nothing written.

## Method
- Re-runs the live router (same code as `run_baseline_forecast.py --write`, blank quantity = missing month) and
  checks it against `public.forecast_result` at 2026-03-01 first: status, method, forecast_value, stored MASE on
  all 189 rows matched. The "stored" rolling one-step holdout is this recomputation, reproduced bit-for-bit.
- Holdout = common window 2025-09..2026-02 (164 SKUs), else the stored 20% split (11 SKUs). Rolling one-step, served bin held fixed.
- **Overfit / underfit / bias rules are those of `../fit_diagnosis_2026-10/` (fixed before computing):**
  overfit = holdout/in-sample MASE ratio above both MA3's own 95th percentile (3.178 this run) and the SKU's own MA3 ratio
  (MA3-served SKUs are the control, not assessable); underfit = in-sample and holdout MASE both >= 1.
- **Bias lean:** t-test on the 6 monthly errors (forecast - actual), two-sided 95% (|t| >= 2.571). `high` = over-forecast,
  `low` = under-forecast, `neutral` = not significant. SKUs with < 6 holdout months are `not testable`. Sign counts of
  the mean error and the pooled bias (sum(f-a)/sum(a)) are given beside it, since 6 months has little power.

## Files
- `classified.csv` per SKU: fit_class, overfit/underfit, bias_lean, mean_error, pooled_bias_pct
- `per_sku.csv` full per-SKU metrics
- `aggregate_by_bin.csv`, `aggregate_by_model.csv`, `aggregate_by_bin_and_model.csv`
- `run_fit_diagnosis_2026-10-07.py` (reuses `../fit_diagnosis_2026-10/run_fit_diagnosis.py`)
