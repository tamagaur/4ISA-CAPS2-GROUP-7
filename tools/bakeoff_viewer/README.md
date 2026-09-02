# Model Bake-off Viewer

A standalone graphical view of the forecasting model bake-off — the
evidence behind the "MA3 / SBA / Theta beat everything else, ARIMA and
XGBoost don't help, synthetic data hurts" verdict.

**Not the product dashboard.** Self-contained HTML that reads frozen
snapshot CSVs — no backend, no live DB.

## Use it

Open **`bakeoff_viewer.html`** in any browser (double-click — no server).

Two toggles at the top:

- **Data** — `Real data only` (2023-01 → 2026-02) vs
  `Real + synthetic` (synthetic 2021-22 months prepended as training
  context, still tested on real months — a diagnostic, not a real option).
- **Metric** — MASE / sMAPE / MAPE.

Three charts + a table:

1. **Median metric per model** — bars sorted best → worst, with the pass
   threshold marked (MASE < 1.0, MAPE < 0.20).
2. **Per-SKU spread** — every SKU as a dot. Tight cluster = steady model;
   dots far right = blow-ups (this is where XGBoost's outlier problem shows).
3. **Best model per SKU** — oracle-winner counts (which model had the
   lowest error on each SKU).
4. **Summary table** — all models, all three median metrics, pass counts.

## Rebuild it

Run after any bake-off CSV changes. All six must exist first:

```
python -m scripts.model_bakeoff --cohort tierA
python -m scripts.model_bakeoff --cohort tierA --with-synthetic
python -m scripts.arima_bakeoff
python -m scripts.arima_bakeoff --with-synthetic
python -m scripts.xgboost_bakeoff
python -m scripts.xgboost_bakeoff --with-synthetic
python tools/bakeoff_viewer/build.py
```

`build.py` reads only `reports/*.csv` (no DB) and re-inlines the data into
`bakeoff_viewer.html`.

## Files

| file | |
|---|---|
| `bakeoff_viewer.html` | **the exhibit** — self-contained, committed snapshot |
| `template.html` | page with a `__VIZ_DATA__` placeholder |
| `build.py` | merges the six bake-off CSVs into the payload |
| `viz_data.json` | the data payload |
