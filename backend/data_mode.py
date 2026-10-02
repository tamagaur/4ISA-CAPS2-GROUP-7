"""
backend.data_mode — PREVIEW mode: real data plus Unilever's 2021-22
placeholder months, for a five-year view of the dashboard.

Asked for 2026-09-23 (Audrey): see what the dashboard looks like over five
years before SSM's real 2021-22 files arrive. The database already holds
placeholder rows for that span (is_demo = true, loaded by
scripts/apply_synth_v2_to_public.py), and every page reads through the
`_Real` views, which drop them. Preview is the one switch that lets a
request read them, and only where it is safe to.

A request opts in with the header `X-Data-Mode: preview`. No header, or
`real`, is the app exactly as before: same SQL text, same payload.

WHAT PREVIEW ADDS — Unilever_SKU_Demand_Fact rows with is_demo = true dated
BEFORE the first real month, and nothing else:
  - not the 2026-03..2026-08 placeholder months after the last real month.
    They sit where the forecasts are, so they would read as actuals for the
    very month being forecast.
  - not Del Monte's placeholder rows, and no placeholder inventory, purchase
    or return rows. Stock, purchases and every Del Monte figure stay real.
The bound is read live from the real data (MIN of the `_Real` view). When
SSM's own 2021-22 files load (DEC-27 anticipates them), real history starts
earlier and the placeholder drops out with no code change.

DESCRIPTIVE figures are sums and statistics of the demand history — the
sales trend, ABC mix, category trends, Pareto, FSN, STL decomposition, a
SKU's volatility and trend — so preview recomputes them per request from
the relation above.

PREDICTIVE AND PRESCRIPTIVE figures (added 2026-09-24) come from files, not
per request: the forecast router refuses placeholder rows everywhere except
scripts/preview_router_synth.py (DEC-27, tests/forecasting/test_router.py),
and fitting the global model per request would be far too slow.
scripts/build_preview_outputs.py runs that sanctioned preview, applies
run_lp.py's own safety stock / ROP / LP steps, checks the pipeline still
reproduces the live Forecast_Result, and writes reports/preview/app_*.
forecast_source() and lp_source() below hand those rows to the routers in the
shape of Forecast_Result and LP_Recommendation, so every existing query runs
unchanged on them. When the files are absent, preview falls back to the real
tables and the payload's data_mode.real_only says so.

NOTHING IS WRITTEN. ABC tiers and SKU traits for placeholder months are
computed per request with the pipeline's own functions and discarded:
classify_abc() plus orchestrate_abc's exclusion steps, and
analytics.segmentation.traits. ABC_Classification, sku_traits, sku_segment,
Forecast_Result and LP_Recommendation are only ever read — the same isolation
apply_synth_v2_to_public.py checks at cutover.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
from fastapi import Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.classification.abc import classify_abc
from analytics.optimization.lp_inputs import PLACEHOLDERS
from analytics.classification.orchestrate_abc import _split_negative_revenue, _split_zero_revenue
from analytics.segmentation.traits import (
    average_demand_interval,
    coefficient_of_variation,
    first_sale_index,
    has_restart,
    history_months,
    longest_positive_run,
    trend_stats,
)

REAL = "real"
PREVIEW = "preview"
DATA_MODE_HEADER = "X-Data-Mode"


def get_data_mode(
    x_data_mode: str | None = Header(
        None,
        alias=DATA_MODE_HEADER,
        description="'preview' adds Unilever's 2021-22 placeholder months. "
        "Omit (or 'real') for real data only.",
    ),
) -> str:
    """FastAPI dependency. Anything other than real/preview is a 400, the
    same rule backend.principals applies to ?principal=: silently ignoring a
    bad value would serve real data while the UI claimed preview."""
    if x_data_mode is None:
        return REAL
    value = x_data_mode.strip().lower()
    if value in ("", REAL):
        return REAL
    if value == PREVIEW:
        return PREVIEW
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unknown {DATA_MODE_HEADER} {x_data_mode!r}. Expected 'real' or 'preview'.",
    )


# ---- the demand source ------------------------------------------------------

REAL_UNILEVER_DEMAND = "Unilever_SKU_Demand_Fact_Real"
_FIRST_REAL_MONTH = "(SELECT MIN(calendar_month) FROM Unilever_SKU_Demand_Fact_Real)"
# Same columns as the _Real view (both are SELECT * of the base table), so it
# drops into any FROM that names the view. Postgres 17 needs no alias on a
# FROM subquery; call sites that already alias the view keep their alias.
PREVIEW_UNILEVER_DEMAND = (
    "(SELECT * FROM Unilever_SKU_Demand_Fact"
    " WHERE is_demo = false"
    f" OR (is_demo = true AND calendar_month < {_FIRST_REAL_MONTH}))"
)


def unilever_demand(mode: str) -> str:
    """The relation to read Unilever demand from. Real mode returns the
    view's name verbatim, so real-mode SQL is character-for-character what
    it was before preview existed."""
    return PREVIEW_UNILEVER_DEMAND if mode == PREVIEW else REAL_UNILEVER_DEMAND


def placeholder_window(db: Session) -> dict | None:
    """The placeholder months preview adds: {start, end, rows,
    quantity_total, first_real_month}, or None when there are none (real
    history already reaches back past them). rows + quantity_total are the
    fingerprint scripts/build_preview_outputs.py records, so a rebuilt
    placeholder shows up as outdated what-if files (preview_block)."""
    row = db.execute(text(f"""
        SELECT MIN(calendar_month) AS start, MAX(calendar_month) AS last, COUNT(*) AS n,
               SUM(quantity_sold) AS qty, {_FIRST_REAL_MONTH} AS first_real_month
        FROM Unilever_SKU_Demand_Fact
        WHERE is_demo = true AND calendar_month < {_FIRST_REAL_MONTH}
    """)).mappings().first()
    if not row or not row["n"]:
        return None
    return {
        "principal": "unilever",
        "start": row["start"],
        "end": row["last"],
        "rows": int(row["n"]),
        "quantity_total": float(row.get("qty") or 0),
        "first_real_month": row["first_real_month"],
    }


def _outputs_stale(outputs: dict | None, placeholder: dict | None) -> bool | None:
    """Whether the what-if files were built on different placeholder data
    than the database holds now. Measured 2026-09-29: the files were built
    2026-09-23 on the v1 placeholder, the 2026-09-28 synthetic v2 cutover
    replaced it, and nothing said so. None when it cannot be told: no files,
    or files built before the build recorded this fingerprint."""
    meta = (outputs or {}).get("meta", {})
    built = meta.get("placeholder_window")
    if not built:
        return None
    live_rows = placeholder["rows"] if placeholder else 0
    live_qty = placeholder["quantity_total"] if placeholder else 0.0
    if int(built["rows"]) != live_rows or abs(float(built["quantity_total"]) - live_qty) > 0.5:
        return True
    return _lp_model_changed(meta.get("lp_model"))


def _lp_model_changed(built_model: dict | None) -> bool:
    """Whether the what-if LP was solved with other settings than the live
    LP uses now. Found 2026-10-02: app_lp.csv was built 2026-09-29 under the
    old model (order = target stock on 72 of 75 rows) and still read as
    current, because only the placeholder data was compared. A build that
    recorded no model at all predates the net-of-stock model (aa315f8), so
    it is stale too."""
    inputs = (built_model or {}).get("inputs")
    if not isinstance(inputs, dict):
        return True

    def same(a, b) -> bool:
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return a == b

    return any(key not in inputs or not same(inputs[key], value) for key, value in PLACEHOLDERS.items())


def is_placeholder_period(period: str | None, window: dict | None) -> bool:
    return bool(period and window and window["start"] <= period <= window["end"])


def placeholder_months(window: dict | None, through: str | None = None) -> list[str]:
    """Every placeholder month, oldest first, optionally only those <= through."""
    if not window:
        return []
    end = window["end"] if through is None else min(window["end"], through)
    if end < window["start"]:
        return []
    return [str(p) for p in pd.period_range(window["start"], end, freq="M")]


def preview_block(db: Session, *, real_only: list[str] | None = None) -> dict:
    """The `data_mode` object a preview payload carries. Real-mode payloads
    carry nothing, so they stay byte-for-byte what they were. `real_only`
    names the fields of this payload that preview deliberately left on real
    data, so nobody has to infer it. `outputs` describes the file-backed
    forecasts and LP (None when they have not been built)."""
    outputs = preview_outputs()
    placeholder = placeholder_window(db)
    block = {"mode": PREVIEW, "placeholder": placeholder,
             "outputs": outputs["meta"] if outputs else None,
             "outputs_stale": _outputs_stale(outputs, placeholder)}
    if real_only:
        block["real_only"] = real_only
    return block


# ---- predictive and prescriptive: file-backed ---------------------------------

PREVIEW_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "preview")
_OUTPUT_FILES = ("app_forecast.csv", "app_lp.csv", "app_meta.json")
_outputs_cache: dict = {"stamp": None, "value": None}


def preview_outputs() -> dict | None:
    """{forecasts, lp, meta} from scripts/build_preview_outputs.py, or None when
    any file is missing. Re-read whenever a file changes (mtime), so a rebuild
    shows up without restarting the API."""
    paths = [os.path.join(PREVIEW_OUTPUT_DIR, f) for f in _OUTPUT_FILES]
    if not all(os.path.isfile(p) for p in paths):
        return None
    stamp = tuple(os.path.getmtime(p) for p in paths)
    if _outputs_cache["stamp"] != stamp:
        with open(paths[2], encoding="utf-8") as f:
            meta = json.load(f)
        _outputs_cache.update(stamp=stamp, value={
            "forecasts": pd.read_csv(paths[0], dtype={"forecast_date": str}),
            "lp": pd.read_csv(paths[1], dtype={"planning_cycle_date": str}),
            "meta": meta,
        })
    return _outputs_cache["value"]


def predictive_preview(mode: str) -> bool:
    """True when this request's forecasts and LP come from the preview files."""
    return mode == PREVIEW and preview_outputs() is not None


def _nullable(values) -> list:
    return [None if v is None or (isinstance(v, float) and np.isnan(v)) else v for v in values]


def forecast_source(mode: str, real_name: str = "Forecast_Result") -> tuple[str, dict]:
    """(relation, params) standing in for Forecast_Result. Real mode, or preview
    without the files: `real_name` verbatim — each caller passes its own
    spelling, so real-mode SQL is character-for-character unchanged."""
    if not predictive_preview(mode):
        return real_name, {}
    out = preview_outputs()
    df = out["forecasts"]
    params = {
        "pv_fc_keys": [int(v) for v in df["product_key"]],
        "pv_fc_dates": [str(v) for v in df["forecast_date"]],
        "pv_fc_values": _nullable(df["forecast_value"].astype(float)),
        "pv_fc_lower": _nullable(df["confidence_lower"].astype(float)),
        "pv_fc_upper": _nullable(df["confidence_upper"].astype(float)),
        "pv_fc_mape": _nullable(df["mape"].astype(float)),
        "pv_fc_mase": _nullable(df["mase"].astype(float)),
        "pv_fc_status": [str(v) for v in df["status"]],
        "pv_fc_params": [str(v) for v in df["model_params"]],
        "pv_generated_at": out["meta"]["built_at"],
    }
    return """(
        SELECT NULL::bigint AS forecast_key, u.product_key, u.forecast_date, u.forecast_value,
               u.confidence_lower, u.confidence_upper, u.mape, u.model_params,
               CAST(:pv_generated_at AS timestamptz) AS generated_at, u.mase, u.status
        FROM unnest(
            CAST(:pv_fc_keys AS bigint[]), CAST(:pv_fc_dates AS date[]), CAST(:pv_fc_values AS numeric[]),
            CAST(:pv_fc_lower AS numeric[]), CAST(:pv_fc_upper AS numeric[]), CAST(:pv_fc_mape AS numeric[]),
            CAST(:pv_fc_params AS jsonb[]), CAST(:pv_fc_mase AS numeric[]), CAST(:pv_fc_status AS text[])
        ) AS u(product_key, forecast_date, forecast_value, confidence_lower, confidence_upper, mape,
               model_params, mase, status)
    )""", params


def lp_source(mode: str, real_name: str = "LP_Recommendation") -> tuple[str, dict]:
    """(relation, params) standing in for LP_Recommendation, same contract as
    forecast_source(). Every preview row is 'pending' and undecidable: its
    recommendation_key is the product_key negated, which no real row has, so
    an accept or dismiss aimed at one finds nothing to change."""
    if not predictive_preview(mode):
        return real_name, {}
    out = preview_outputs()
    df = out["lp"]
    params = {
        "pv_lp_keys": [int(v) for v in df["product_key"]],
        "pv_lp_dates": [str(v) for v in df["planning_cycle_date"]],
        "pv_lp_q": _nullable(df["q_i"].astype(float)),
        "pv_lp_rop": _nullable(df["rop_i"].astype(float)),
        "pv_lp_ss": _nullable(df["ss_i"].astype(float)),
        "pv_generated_at": out["meta"]["built_at"],
    }
    return """(
        SELECT -u.product_key AS recommendation_key, u.product_key, u.planning_cycle_date,
               u.q_i, u.rop_i, u.ss_i, 'pending'::text AS status, NULL::timestamptz AS decided_at,
               NULL::text AS decided_by, CAST(:pv_generated_at AS timestamptz) AS generated_at
        FROM unnest(
            CAST(:pv_lp_keys AS bigint[]), CAST(:pv_lp_dates AS date[]), CAST(:pv_lp_q AS numeric[]),
            CAST(:pv_lp_rop AS numeric[]), CAST(:pv_lp_ss AS numeric[])
        ) AS u(product_key, planning_cycle_date, q_i, rop_i, ss_i)
    )""", params


# ---- ABC 'single' for placeholder months ------------------------------------

ABC_COLUMNS = [
    "product_key", "principal", "classification_period", "method",
    "tier", "revenue_share", "cumulative_share", "boundary_flag", "total_revenue",
]


def abc_single(db: Session, months: list[str], mode: str) -> pd.DataFrame:
    """ABC 'single' tiers for Unilever `months`, computed now — the steps
    of orchestrate_abc.run_abc_for_principal('unilever', ..., 'single')
    without the write:
      1. each product's net_amount for the month (the demand fact is unique
         on product and month, so one row each);
      2. an explicit NULL net_amount is excluded, never zeroed;
      3. _split_negative_revenue: a negative is clamped to 0 ...
      4. ... and _split_zero_revenue then excludes every zero, so only
         products that sold that month are ranked;
      5. classify_abc: shares, 80 / 95 cutoffs, boundary flag.
    The ABC run also left-joins every Unilever product at 0 before step 3.
    Step 4 removes every one of those rows again, so the join cannot change
    a tier or a share, and it is left out here.

    `mode` picks the demand source. Preview callers pass placeholder months;
    tests/backend/test_data_mode.py runs it on REAL months against the
    stored ABC_Classification to prove this path reproduces the ABC run."""
    if not months:
        return pd.DataFrame(columns=ABC_COLUMNS)
    rows = db.execute(
        text(f"""
            SELECT d.product_key, d.calendar_month AS period, d.net_amount
            FROM {unilever_demand(mode)} d
            WHERE d.calendar_month = ANY(:months)
        """),
        {"months": list(months)},
    ).mappings().all()
    raw = pd.DataFrame(
        [(int(r["product_key"]), r["period"], r["net_amount"]) for r in rows],
        columns=["sku_id", "period", "total_revenue"],
    )
    raw["total_revenue"] = raw["total_revenue"].astype(float)  # NUMERIC -> Decimal, cast as orchestrate_abc does

    frames = []
    for month in months:
        df = raw.loc[raw["period"] == month, ["sku_id", "total_revenue"]].dropna(subset=["total_revenue"]).copy()
        clamped, _negative_ids = _split_negative_revenue(df)
        clean, _zero_ids = _split_zero_revenue(clamped)
        if clean.empty:
            continue
        tiered = classify_abc(clean.reset_index(drop=True))
        tiered = tiered.rename(columns={"sku_id": "product_key"})
        tiered["classification_period"] = month
        frames.append(tiered)
    if not frames:
        return pd.DataFrame(columns=ABC_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    out["principal"] = "unilever"
    out["method"] = "single"
    return out[ABC_COLUMNS]


def abc_relation(computed: pd.DataFrame, *, with_stored: bool) -> tuple[str, dict]:
    """A FROM-able relation with ABC_Classification's column names and types
    holding `computed`'s rows — UNION ALL the stored table when with_stored.
    Rows travel as typed arrays through unnest(), so nothing is interpolated
    into the SQL text. The shares are cast to the table's own NUMERIC(7,4)
    (schema.sql), which rounds them exactly as an insert into it would, so a
    placeholder row carries the same precision as a stored one."""
    params = {
        "pv_abc_keys": [int(v) for v in computed["product_key"]],
        "pv_abc_periods": [str(v) for v in computed["classification_period"]],
        "pv_abc_tiers": [str(v) for v in computed["tier"]],
        "pv_abc_shares": [None if pd.isna(v) else float(v) for v in computed["revenue_share"]],
        "pv_abc_cumulative": [None if pd.isna(v) else float(v) for v in computed["cumulative_share"]],
        "pv_abc_boundary": [bool(v) for v in computed["boundary_flag"]],
    }
    placeholder_sql = """
        SELECT u.product_key, 'unilever'::text AS principal, u.classification_period,
               'single'::text AS method, u.tier, u.revenue_share, u.cumulative_share, u.boundary_flag
        FROM unnest(
            CAST(:pv_abc_keys AS bigint[]), CAST(:pv_abc_periods AS text[]), CAST(:pv_abc_tiers AS text[]),
            CAST(:pv_abc_shares AS numeric(7,4)[]), CAST(:pv_abc_cumulative AS numeric(7,4)[]),
            CAST(:pv_abc_boundary AS boolean[])
        ) AS u(product_key, classification_period, tier, revenue_share, cumulative_share, boundary_flag)
    """
    if not with_stored:
        return f"({placeholder_sql})", params
    return f"""(
        SELECT product_key, principal, classification_period, method, tier,
               revenue_share, cumulative_share, boundary_flag
        FROM ABC_Classification
        UNION ALL
        {placeholder_sql}
    )""", params


def latest_per_product(computed: pd.DataFrame) -> pd.DataFrame:
    """Each product's newest computed row. Enough for a last-known-tier read:
    every stored run is later than every placeholder month, so a product
    with a stored row never needs its placeholder rows at all."""
    if computed.empty:
        return computed
    return (
        computed.sort_values(["product_key", "classification_period"])
        .groupby("product_key", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


# ---- SKU traits over the preview window --------------------------------------

def demand_matrix(
    db: Session, product_keys: list[int], start: str, end: str, mode: str,
) -> tuple[dict[int, np.ndarray], list[str]]:
    """orchestrate_segment._fetch_demand_matrix, from `mode`'s demand source:
    one zero-filled monthly quantity array per product over [start, end]. No
    row is a zero-sale month, a NULL quantity is 0, a negative is clipped to
    0 — all three exactly as the segmentation run builds it."""
    periods = [str(p) for p in pd.period_range(start, end, freq="M")]
    index = {p: i for i, p in enumerate(periods)}
    matrices = {int(pk): np.zeros(len(periods)) for pk in product_keys}
    if not product_keys:
        return matrices, periods
    rows = db.execute(
        text(f"""
            SELECT d.product_key, d.calendar_month AS period, d.quantity_sold AS qty
            FROM {unilever_demand(mode)} d
            WHERE d.product_key = ANY(:keys) AND d.calendar_month >= :start AND d.calendar_month <= :end
        """),
        {"keys": [int(k) for k in product_keys], "start": start, "end": end},
    ).mappings().all()
    for r in rows:
        i = index.get(r["period"])
        if i is None:
            continue
        qty = 0.0 if r["qty"] is None else float(r["qty"])
        matrices[int(r["product_key"])][i] = max(qty, 0.0)
    return matrices, periods


def series_traits(qty: np.ndarray, periods: list[str]) -> dict:
    """The demand-series columns of orchestrate_segment.build_traits for one
    SKU. stability_group and revenue_share_2026_02 are not here: they come
    from ABC runs, not the demand series, and stay the stored values."""
    fs = first_sale_index(qty)
    trend, trend_pvalue, trend_slope = trend_stats(qty)
    return {
        "history_months": history_months(qty),
        "first_sale_period": periods[fs] if fs is not None else None,
        "longest_run": longest_positive_run(qty),
        "trend": trend,
        "trend_pvalue": trend_pvalue,
        "trend_slope": trend_slope,
        "cv": coefficient_of_variation(qty),
        "adi": average_demand_interval(qty),
        "restart_flag": has_restart(qty),
    }
