# Tier A Forecast Viewer

A standalone per-SKU viewer for the Unilever Category A demand forecast —
the review artifact for the MA3-vs-everything-else decision and a defense
exhibit.

**Not the product dashboard.** This is a self-contained HTML file that reads a
frozen data snapshot — it does not talk to the backend or the live database.

## Use it

Open **`forecast_viewer.html`** in any browser (double-click — no server). For
each real Tier A SKU with enough history (89 of 132) it shows:

- full monthly actual sales, with the rolling test window shaded
- **5 models, each a toggleable line on the chart** — click a model's chip
  under the chart to show/hide it: **MA3** (deployed), Naive, SBA, Theta,
  SARIMA(1,1,1). MA3/Naive/SBA use only the last 1-3 months; Theta/SARIMA
  use the *full* training history at every origin — shown side by side on
  real numbers so "should we use more history" has an answer, not an
  assertion.
- per-SKU MASE / MAPE / MAE for all 5 methods (rolling backtest table)
- the next-month (or next-3-months, via the `1 mo` / `3 mo` toggle) point
  for each model — MA3/Naive/SBA are flat (same value repeated), Theta/SARIMA
  produce a shaped path
- a plain-language confidence line for the next-month number
- SKUs under 15 months (can't support a 6-origin rolling backtest) show the
  provisional trailing-average LP fallback instead of a scored forecast

**Backtest: rolling-origin, 1-step-ahead, last 6 real months, every model
refit at each origin** — this matches how the forecast is actually run in
production (re-run before each order cycle), and matches
`reports/model_bakeoff_unilever*.csv`/`.xlsx` exactly. (The tool used to run
a single 80/20 split that held one forecast flat for 6 months and penalised
MA3 for going stale — replaced; see git history if you need the old numbers.)

**`Real data` / `+ Synthetic` toggle** (SKU header): `+ Synthetic` prepends
the synthetic 2021-22 months to training (still the same real holdout), so
you can see per-SKU whether the extra history changes the forecast. **Only
offered for SKUs whose real sales already start at the 2023-01 data-window
open** — for a SKU that's a genuine later launch, prepending 2021-22 "sales"
would fabricate demand before the product existed, so the toggle is disabled
and flagged "new product" instead. Diagnostic only either way; the deployed
forecast always uses real data.

## Rebuild it

Run whenever fresh demand lands or the ABC period changes:

```
python tools/forecast_viewer/build.py                # full rebuild, hits the DB
python tools/forecast_viewer/build.py --html-only     # re-inline an existing viz_data.json, no DB
```

Fitting Theta and SARIMA at every rolling origin (and again for the
`+ Synthetic` variant) makes a full rebuild take a few minutes — that's
expected.

## Files

| file | |
|---|---|
| `forecast_viewer.html` | **the exhibit** — self-contained, committed snapshot |
| `template.html` | the page with a `__VIZ_DATA__` placeholder; `build.py` fills it |
| `build.py` | regenerates the data + the built HTML |
| `viz_data.json` | the data payload (actuals + recomputed forecasts + metrics) |

Data: actuals from `Unilever_SKU_Demand_Fact_Real` (real) /
`unilever_sku_demand_fact` (the `+ Synthetic` variant only, training months
before the SKU's real history — diagnostic, never scored against reported
results). Forecasts and metrics recomputed here (rolling-origin backtest);
`reports/baseline_forecast_per_sku.csv` is read only for demand class and
span, not accuracy numbers.
