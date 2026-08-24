"""
scripts.run_sarima — Phase 2: Run SARIMA forecasts and save to Forecast_Result.

Reads Category A demand from the *_Real views (real_only — no synthetic
demo rows), fits a full seasonal SARIMA search per product via
analytics.forecasting.sarima, and writes only forecasts the model
actually produced. A product whose fit raises is skipped and logged to
a rejects list — never backfilled with a moving average or any other
substitute value. There is no fallback path in this script; if that
turns out to be needed, it must be a documented, visibly-tagged product
of its own, not silently indistinguishable from a real fit.
"""
from __future__ import annotations

import json
import logging
import os
import warnings

import numpy as np
import pandas as pd
import psycopg2
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from statsmodels.tsa.statespace.sarimax import SARIMAX

# Ensure we can import from analytics package
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.forecasting.sarima import fit_sarima, evaluate_sarima, SARIMAResult

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Step 4: matches the module docstring's stated rule ("2 full seasonal
# cycles at period=12" — see analytics/forecasting/sarima.py's own
# decompose_series minimum). A product with fewer months than this is
# SKIPPED (counted separately from a real fit failure), not rejected.
MIN_MONTHS_REQUIRED = 24


def main():
    load_dotenv(override=False)
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.error("SUPABASE_DB_URL not set in .env")
        return

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    # Step 1: Fetch historical monthly demand for Category A products.
    # Step 2: *_Real views only — is_demo=true rows must never enter the
    #   training data.
    # Step 3: ABC_Classification restricted to the MOST RECENT
    #   classification_period only — the unrestricted join used to pull
    #   in every product that was ever tier A across all 68 periods.
    logger.info("Fetching Category A demand data (real rows only, latest ABC period)...")
    query = """
        SELECT
            pd.product_key,
            pd.sku_code,
            d.period,
            SUM(d.quantity) as total_quantity
        FROM (
            SELECT product_key, _period as period, quantity FROM SellOut_Fact_Real
            UNION ALL
            SELECT product_key, calendar_month as period, quantity_sold as quantity FROM Unilever_SKU_Demand_Fact_Real
        ) d
        JOIN Product_Dimension pd ON d.product_key = pd.product_key
        JOIN ABC_Classification abc ON abc.product_key = pd.product_key
        WHERE abc.tier = 'A'
          AND abc.classification_period = (SELECT MAX(classification_period) FROM ABC_Classification)
        GROUP BY pd.product_key, pd.sku_code, d.period
        ORDER BY pd.product_key, d.period ASC
    """
    cur.execute(query)
    rows = cur.fetchall()

    if not rows:
        logger.warning("No Category A demand data found. Check ABC Classification and ETL data.")
        conn.close()
        return

    # Convert to DataFrame
    df = pd.DataFrame(rows, columns=['product_key', 'sku_code', 'period', 'quantity'])
    # Clean NaN quantities to 0 before pandas conversion
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
    # Convert 'YYYY-MM' to actual datetime for time series
    df['period'] = pd.to_datetime(df['period'] + '-01')

    skus = df['product_key'].unique()
    logger.info(f"Found {len(skus)} Category A products (latest ABC period) to forecast.")

    results_to_insert = []
    skipped_insufficient_history: list[tuple[int, str, int]] = []   # (product_key, sku_code, n_months)
    rejected_fit_failures: list[tuple[int, str, str]] = []          # (product_key, sku_code, reason)

    # Target date for the forecast (t+1) - assuming latest period + 1 month
    latest_period = df['period'].max()
    forecast_date = (latest_period + relativedelta(months=1)).date()

    for p_key in skus:
        sku_df = df[df['product_key'] == p_key].sort_values('period')
        sku_code = sku_df['sku_code'].iloc[0]

        # Prepare series
        series = sku_df.set_index('period')['quantity']
        series.index = pd.to_datetime(series.index)

        # Resample to Month Start ('MS') to ensure continuous timeline, filling missing months with 0.0
        series = series.resample('MS').asfreq().fillna(0.0)

        # Step 4: enforce the documented 24-month minimum. Skipped, not
        # rejected — this product simply doesn't have enough history yet,
        # it isn't a fit that failed.
        if len(series) < MIN_MONTHS_REQUIRED:
            logger.info(f"Skipping {sku_code} (key {p_key}): {len(series)} months of history, need {MIN_MONTHS_REQUIRED}.")
            skipped_insufficient_history.append((int(p_key), sku_code, len(series)))
            continue

        logger.info(f"Fitting SARIMA for {sku_code} ({len(series)} months)...")

        # Step 1: no fallback. If the fit or the full-series refit raises,
        # log it, record it in the rejects list, and move on — never
        # substitute a moving average or any other value.
        try:
            # Step 5: seasonal search enabled — fit_sarima's DEFAULT_PARAM_GRID
            # already searches P/D/Q over (0, 1) at seasonal_period=12 (the
            # manuscript's monthly seasonality); no custom grid override here
            # collapses that back to non-seasonal.
            result: SARIMAResult = fit_sarima(series, sku_id=sku_code, seasonal_period=12, holdout_fraction=0.2)

            # Evaluate on holdout (the portion fit_sarima withheld from training)
            train_len = len(result.train_series)
            holdout = series.iloc[train_len:]
            metrics = evaluate_sarima(result, holdout)
            mape_fraction = metrics['mape']

            if np.isnan(mape_fraction):
                raise ValueError("MAPE undefined — holdout demand was all-zero, evaluation is meaningless")

            mape_pct = min(float(mape_fraction) * 100, 999.999)

            # Refit the SAME selected (order, seasonal_order) on the FULL
            # series so the one-step forecast covers the period right
            # after the latest real data, not just after the 80% training
            # split — per fit_sarima/forecast_one_step's own documented
            # pattern (analytics/forecasting/sarima.py).
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
            f_val = float(forecast.predicted_mean.iloc[0])

            # Step 6: prediction interval from the model itself (95% CI,
            # statsmodels default alpha=0.05) — not left NULL.
            ci = forecast.summary_frame(alpha=0.05)
            conf_lower = float(ci['mean_ci_lower'].iloc[0])
            conf_upper = float(ci['mean_ci_upper'].iloc[0])

            # Step 7: real provenance — what was actually fitted, not a
            # fabrication flag. AIC is the full-series refit's own AIC, so
            # it describes the model that produced this forecast, not the
            # (different-length) training-split model from selection.
            model_params = json.dumps({
                "order": list(result.order),
                "seasonal_order": list(result.seasonal_order),
                "aic": float(full_fitted.aic),
            })

        except Exception as exc:
            logger.warning(f"SARIMA fit failed for {sku_code} (key {p_key}): {exc}. Skipping — no substitute value written.")
            rejected_fit_failures.append((int(p_key), sku_code, str(exc)))
            continue

        results_to_insert.append((
            int(p_key),
            forecast_date,
            f_val,
            conf_lower,
            conf_upper,
            mape_pct,
            model_params,
        ))

    # Step 3 (write): Insert into Forecast_Result. Fitting ~100+ SARIMA
    # models can take long enough that the connection opened at the top
    # of main() gets dropped by Supabase's pooler before we get here
    # (confirmed: "server closed the connection unexpectedly" on a real
    # run). Close it and open a fresh one just for the write, rather than
    # trust an hours-old connection with the one step that must not fail.
    if results_to_insert:
        logger.info(f"Inserting {len(results_to_insert)} real forecast records into DB...")
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()

        insert_query = """
            INSERT INTO Forecast_Result
            (product_key, forecast_date, forecast_value, confidence_lower, confidence_upper, mape, model_params)
            VALUES %s
            ON CONFLICT (product_key, forecast_date)
            DO UPDATE SET
                forecast_value = EXCLUDED.forecast_value,
                confidence_lower = EXCLUDED.confidence_lower,
                confidence_upper = EXCLUDED.confidence_upper,
                mape = EXCLUDED.mape,
                model_params = EXCLUDED.model_params
        """
        execute_values(cur, insert_query, results_to_insert)
        logger.info("Successfully saved forecasts.")
    else:
        logger.info("No forecasts to insert.")

    logger.info(
        f"Summary: {len(results_to_insert)} forecast, "
        f"{len(skipped_insufficient_history)} skipped (< {MIN_MONTHS_REQUIRED} months), "
        f"{len(rejected_fit_failures)} rejected (fit failed)."
    )
    if rejected_fit_failures:
        logger.info("Rejected products (fit failed, no forecast written):")
        for p_key, sku_code, reason in rejected_fit_failures:
            logger.info(f"  - {sku_code} (key {p_key}): {reason}")

    conn.close()

if __name__ == "__main__":
    main()
