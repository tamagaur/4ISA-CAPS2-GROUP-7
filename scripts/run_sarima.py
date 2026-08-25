"""
scripts.run_sarima — Phase 2: Run SARIMA forecasts and save to Forecast_Result.

Fixed 2026-08 (remediation pass, see plan-mode-produce-a-replicated-prism.md):
  - Seasonality is no longer disabled by default. The prior unconditional
    `fast_grid` override locked every fit's seasonal (P,D,Q) to (0,0,0),
    so despite sarima.py's SARIMA_SEASONAL_PERIOD=12, every production fit
    was a plain non-seasonal ARIMA. The real grid (sarima.py's
    DEFAULT_PARAM_GRID, which includes seasonal terms) is now the default;
    the old constrained grid is available opt-in via --fast, and any
    forecast produced under it stamps model_params with
    {"fast_mode": true, ...} so a reader can tell it wasn't fit with the
    real grid.
  - mape is never fabricated. The two `mape = 15.0` ("Mock passing MAPE")
    fallbacks are removed. Forecast_Result.status (added by
    migrations/0008_add_forecast_result_status.sql) now distinguishes
    'ok' / 'insufficient_data' / 'dead_sku' / 'fit_failed' / 'unreliable' —
    mape is NULL wherever it wasn't actually measured, never a stand-in
    number chosen to look like it passed the MAPE gate.
  - The overshoot guard tightened from 5x historical max to 2x, and now
    also re-checks its own fallback value (the fallback itself could still
    exceed the threshold on a recently-spiking series) and routes a
    zero-valued fallback to 'dead_sku' rather than reporting a 0.0 forecast
    as merely 'unreliable'.
"""
from __future__ import annotations

import argparse
import json
import os
import logging
import warnings
from dateutil.relativedelta import relativedelta

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from statsmodels.tsa.statespace.sarimax import SARIMAX

# Ensure we can import from analytics package
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.forecasting.sarima import fit_sarima, evaluate_sarima, SARIMAResult

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Opt-in only (--fast): a deliberately constrained, non-seasonal grid to
# keep local iteration fast. Never the default — see module docstring.
FAST_GRID = {"p": (0, 1), "d": (0, 1), "q": (0, 1), "P": (0,), "D": (0,), "Q": (0,)}

# Overshoot guard: a point forecast (or its own fallback) more than this
# multiple of the series' historical max is reported as status='unreliable'
# rather than as a trustworthy number.
OVERSHOOT_MULTIPLE = 2.0


def main():
    parser = argparse.ArgumentParser(description="Run SARIMA forecasts for Category A products and save to Forecast_Result.")
    parser.add_argument(
        "--fast", action="store_true", default=False,
        help="Use a constrained, non-seasonal grid for faster local runs. "
             "Stamps model_params with fast_mode:true. Default OFF — the "
             "real seasonal grid runs unless this is explicitly passed.",
    )
    parser.add_argument(
        "--principal", choices=["both", "unilever", "delmonte"], default="both",
        help="Scope this run to one principal. The query still fetches both "
             "(the Del Monte branch is not removed) — this filters in "
             "Python before fitting, so a scoped run can be made without "
             "touching the query itself. Default 'both'.",
    )
    args = parser.parse_args()

    load_dotenv(override=False)
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.error("SUPABASE_DB_URL not set in .env")
        return

    conn = psycopg2.connect(db_url)
    conn.autocommit = True  # each save_result() call below commits immediately, not batched to the end
    cur = conn.cursor()

    UPSERT_QUERY = """
        INSERT INTO Forecast_Result
        (product_key, forecast_date, forecast_value, confidence_lower, confidence_upper, mape, status, model_params)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (product_key, forecast_date)
        DO UPDATE SET
            forecast_value = EXCLUDED.forecast_value,
            mape = EXCLUDED.mape,
            status = EXCLUDED.status,
            model_params = EXCLUDED.model_params
    """

    def save_result(p_key, forecast_date, f_val, mape, status, model_params):
        """Writes one SKU's result immediately, not batched to the end of the
        run — so an interrupted run keeps everything it already computed
        instead of losing it all (results_to_insert used to hold everything
        in memory until a single INSERT after the whole loop finished)."""
        cur.execute(UPSERT_QUERY, (
            int(p_key), forecast_date, float(f_val), None, None, mape, status, json.dumps(model_params),
        ))

    # Step 1: Fetch historical monthly demand for Category A SKUs
    # Using SellOut_Fact (quantity) grouped by _period
    # We join with ABC_Classification to only forecast for 'A' class items
    logger.info("Fetching Category A SKUs demand data from both fact tables...")
    query = """
        SELECT
            pd.product_key,
            pd.sku_code,
            pd.principal,
            d.period,
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
        GROUP BY pd.product_key, pd.sku_code, pd.principal, d.period
        ORDER BY pd.product_key, d.period ASC
    """
    cur.execute(query)
    rows = cur.fetchall()

    if not rows:
        logger.warning("No Category A demand data found. Check ABC Classification and ETL data.")
        conn.close()
        return

    # Convert to DataFrame
    df = pd.DataFrame(rows, columns=['product_key', 'sku_code', 'principal', 'period', 'quantity'])
    # Clean NaN quantities to 0 before pandas conversion
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
    # Convert 'YYYY-MM' to actual datetime for time series
    df['period'] = pd.to_datetime(df['period'] + '-01')

    if args.principal != "both":
        before = df['product_key'].nunique()
        df = df[df['principal'] == args.principal]
        logger.info(f"--principal={args.principal}: scoped from {before} to {df['product_key'].nunique()} products (query/branches unchanged, filtered here).")

    # Step 2: Iterate over each SKU and run SARIMA
    skus = df['product_key'].unique()
    logger.info(f"Found {len(skus)} Category A SKUs to forecast.")
    if args.fast:
        logger.warning("--fast: using constrained non-seasonal grid, not the real one.")

    # Resumability: since each SKU is now saved immediately (see save_result
    # above), a run interrupted partway through can be restarted and pick up
    # where it left off instead of redoing already-saved SKUs from scratch.
    cur.execute("SELECT DISTINCT product_key FROM Forecast_Result")
    already_done = {r[0] for r in cur.fetchall()}
    if already_done:
        logger.info(f"{len(already_done)} product(s) already have a saved forecast — skipping those, resuming the rest.")

    for p_key in skus:
        if int(p_key) in already_done:
            continue
        sku_df = df[df['product_key'] == p_key].sort_values('period')
        sku_code = sku_df['sku_code'].iloc[0]

        # Target date for the forecast (t+1) relative to THIS SKU's latest actual data
        sku_latest_period = sku_df['period'].max()
        forecast_date = (sku_latest_period + relativedelta(months=1)).date()

        # Prepare series
        series = sku_df.set_index('period')['quantity']
        series.index = pd.to_datetime(series.index)

        # Resample to Month Start ('MS') to ensure continuous timeline, filling missing months with 0.0
        series = series.resample('MS').asfreq().fillna(0.0)

        # We need at least 2 seasonal periods (24 months) + some holdout for a robust model
        if len(series) < 12:
            logger.warning(f"SKU {sku_code} (key {p_key}) has insufficient data ({len(series)} periods). Reporting as insufficient_data, not silently 'passing'.")
            f_val = float(series.mean()) if len(series) > 0 else 0.0
            save_result(p_key, forecast_date, f_val, None, 'insufficient_data',
                        {"reason": "insufficient_data", "periods_available": int(len(series))})
            continue

        # Check for Dead/Inactive SKU
        if len(series) >= 6 and series.tail(6).sum() <= 0:
            logger.warning(f"SKU {sku_code} is inactive (recent 6 months sales <= 0). Forecasting 0.")
            save_result(p_key, forecast_date, 0.0, None, 'dead_sku', {"reason": "dead_sku", "recent_6mo_sum": 0})
            continue

        logger.info(f"Fitting SARIMA for {sku_code}...")
        param_grid = FAST_GRID if args.fast else None
        status = 'ok'
        mape = None
        f_val = None
        model_params = {}

        try:
            result: SARIMAResult = fit_sarima(series, sku_id=sku_code, param_grid=param_grid, holdout_fraction=0.2) \
                if param_grid is not None else fit_sarima(series, sku_id=sku_code, holdout_fraction=0.2)
            # Evaluate on holdout — a real, measured metric, not a placeholder
            train_len = len(result.train_series)
            holdout = series.iloc[train_len:]
            metrics = evaluate_sarima(result, holdout)
            raw_mape = metrics.get('mape')
            if raw_mape is not None and not pd.isna(raw_mape) and raw_mape != float('inf'):
                mape = min(float(raw_mape) * 100, 999.999)  # fraction -> percent, capped for the NUMERIC(6,3) column

            # Refit on FULL series before forecasting future
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                full_model = SARIMAX(
                    series,
                    order=result.order,
                    seasonal_order=result.seasonal_order,
                    enforce_stationarity=True,
                    enforce_invertibility=True,
                )
                full_fitted = full_model.fit(disp=False)

            forecast = full_fitted.get_forecast(steps=1)
            f_val = max(0.0, float(forecast.predicted_mean.iloc[0]))  # never a negative sales forecast

            model_params = {"order": list(result.order), "seasonal_order": list(result.seasonal_order)}
            if args.fast:
                model_params["fast_mode"] = True

            # Overshoot guard: a point forecast far past anything the series
            # has ever done is not a number to trust, even if the fit
            # converged cleanly.
            historical_max = float(series.max())
            if historical_max > 0 and f_val > historical_max * OVERSHOOT_MULTIPLE:
                fallback = float(series.tail(3).mean())
                # The fallback itself can still exceed the threshold on a
                # recently-spiking series — clamp it too rather than
                # trusting a naive average unconditionally.
                fallback = min(max(0.0, fallback), historical_max * OVERSHOOT_MULTIPLE)
                logger.warning(
                    f"SARIMA forecast for {sku_code} exploded ({f_val} > "
                    f"{OVERSHOOT_MULTIPLE}x historical max of {historical_max}). "
                    f"Falling back to a clamped recent average ({fallback})."
                )
                if fallback <= 0.0:
                    # A zero-valued fallback after an overshoot is a dead
                    # SKU reading, not merely an "unreliable" number.
                    status = 'dead_sku'
                    mape = None
                    f_val = 0.0
                    model_params = {"reason": "dead_sku_after_overshoot_guard"}
                else:
                    status = 'unreliable'
                    f_val = fallback
                    model_params["overshoot_guard_triggered"] = True

        except Exception as e:
            logger.warning(f"SARIMA fit failed for {sku_code}: {e}.")
            status = 'fit_failed'
            mape = None
            f_val = 0.0  # explicit sentinel — forecast_value stays NOT NULL, status says not to trust it
            model_params = {"reason": "fit_failed", "error": str(e)}

        save_result(p_key, forecast_date, f_val, mape, status, model_params)
        logger.info(f"Saved {sku_code}: status={status} mape={mape}")

    logger.info("Done — every SKU was saved immediately as it was computed.")
    conn.close()

if __name__ == "__main__":
    main()
