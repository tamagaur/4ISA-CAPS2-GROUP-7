# Tier A Forecast Viewer

A standalone per-SKU viewer for the Unilever Category A baseline forecasts
(`scripts/run_baseline_forecast.py` / `analytics/forecasting/baseline.py`).
It is the review artifact for the MA3-vs-SARIMA decision and a defense exhibit.

**Not the product dashboard.** This is a self-contained HTML file that reads a
frozen data snapshot — it does not talk to the backend or the live database.

## Use it

Open **`forecast_viewer.html`** in any browser (double-click — no server). For
each of the 132 real Tier A SKUs it shows:

- full monthly actual sales, with the 80/20 holdout window shaded
- the MA3 forecast over the holdout, plus the next-month (2026-03) point
- naive and SBA forecasts alongside (toggle, on by default)
- per-SKU MASE / MAPE / MAE for all three methods, holdout length, demand class
- a plain-language confidence line for the next-month number
- `insufficient_data` SKUs (< 3 months of sales) show the provisional
  trailing-average LP fallback instead of a scored forecast

Short-holdout SKUs (< 3 holdout months) are dimmed — a 0.38 MASE scored on
2 points is not more trustworthy than a 0.94 on 6.

**`Real data` / `+ Synthetic` toggle** (SKU header): `+ Synthetic` prepends
the synthetic 2021-22 months to training (still the same real holdout), so
you can see per-SKU whether the extra history changes the forecast — it
mostly doesn't for MA3, sometimes does for SBA. Diagnostic only; the
deployed forecasts always use real data.

## Rebuild it

Run this whenever `reports/baseline_forecast_per_sku.csv` changes or fresh
demand lands:

```
python tools/forecast_viewer/build.py      # from the repo root, .env present
```

That regenerates `viz_data.json` and re-inlines it into `forecast_viewer.html`.
Read-only against the DB.

## Files

| file | |
|---|---|
| `forecast_viewer.html` | **the exhibit** — self-contained, committed snapshot |
| `template.html` | the page with a `__VIZ_DATA__` placeholder; `build.py` fills it |
| `build.py` | regenerates the data + the built HTML |
| `viz_data.json` | the data payload (actuals + recomputed forecasts + metrics) |

Data: actuals from `Unilever_SKU_Demand_Fact_Real`; forecasts recomputed the
same way `baseline.py` does (80/20 split, MA3/Naive/SBA, one-step-ahead);
metrics from `reports/baseline_forecast_per_sku.csv`.
