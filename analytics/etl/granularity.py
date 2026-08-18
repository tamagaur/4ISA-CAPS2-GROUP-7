"""
analytics.etl.granularity - Granularity Resolver: monthly invoice totals -> daily intervals.

Phase 3B (CLAUDE.md Step 7 - Checkpoint: no date gaps in output series; row counts plausible):
  Problem: Sales Register files are INVOICE-LEVEL only (no SKU breakdown).
  Solution: Disaggregate monthly totals into a daily time series.
    1. Distribute monthly invoice totals across business days in each month.
    2. Cross-reference UnileverLaUnionSalesperSKU2023to2026.xls for SKU-level
       estimates where available (Unilever La Union territory).
  Output: Reconstructed daily demand series per SKU, validated for continuity.

Per ARCHITECTURE.md DEC-03 (locked): grain is per-principal, not uniform.
  - Unilever: real per-SKU monthly demand exists (Unilever La Union file,
    confirmed monthly-only via its calendar_month column - no day-level
    date exists anywhere in that source) -> resolve_unilever_sku_grain()
    passes it through, it does not need disaggregation from an invoice
    total.
  - Del Monte: Sales Register is invoice-level only, no SKU column exists
    anywhere in that file family (confirmed - profiling/grain_map.md).
    Allocating a monthly invoice total down to SKU would be fabrication
    (ARCHITECTURE.md explicitly forbids this - it is not a baseline
    option). The honest, non-fabricating operation for Del Monte is:
    distribute the monthly total across business days at CATEGORY grain
    (the grain the data actually supports per DEC-03), not SKU grain.

Do NOT assume SKU-level data exists beyond the confirmed Unilever file.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class GranularityValidationResult:
    ok: bool
    date_gaps: list[str]           # ISO dates missing from an otherwise-continuous series
    total_mismatch: dict | None    # {'expected': x, 'got': y} if reconstructed sum != source total


def business_days_in_month(period: str) -> pd.DatetimeIndex:
    """period is 'YYYY-MM'. Returns Mon-Fri calendar days in that month.
    'Business days' here means weekday calendar days - SSM's actual
    operating calendar (holidays, etc.) is not confirmed in the source
    data, so this is the most defensible default, not an assumption
    dressed up as fact."""
    start = pd.Period(period, freq="M").start_time
    end = pd.Period(period, freq="M").end_time
    return pd.bdate_range(start, end, freq="B")


def resolve_delmonte_category_grain(monthly_df: pd.DataFrame, amount_col: str = "net_amount") -> tuple[pd.DataFrame, GranularityValidationResult]:
    """Distribute each row's monthly total evenly across that month's
    business days, at category grain (DEC-03). Even distribution is the
    only allocation that does not fabricate a shape the data doesn't
    support - it is stated as such, not disguised as a forecast.

    Expects monthly_df to already be canonical + deduped (i.e. has gone
    through transform.transform_fact) with columns: _period, _principal,
    plus a category/region grouping column and amount_col.
    """
    required = {"_period", amount_col}
    missing = required - set(monthly_df.columns)
    if missing:
        raise KeyError(f"resolve_delmonte_category_grain missing required columns: {missing}")

    rows = []
    for period, group in monthly_df.groupby("_period"):
        bdays = business_days_in_month(period)
        if len(bdays) == 0:
            continue
        per_day_share = 1.0 / len(bdays)
        for _, row in group.iterrows():
            daily_amount = row[amount_col] * per_day_share
            for d in bdays:
                new_row = row.to_dict()
                new_row["date"] = d.date().isoformat()
                new_row[amount_col] = daily_amount
                new_row["_grain_resolution"] = "even_business_day_distribution"
                rows.append(new_row)

    out = pd.DataFrame(rows)

    # Validate: no date gaps within any month we produced, and the
    # reconstructed sum must reconcile to the source monthly total.
    date_gaps: list[str] = []
    for period, group in monthly_df.groupby("_period"):
        expected_days = set(d.date().isoformat() for d in business_days_in_month(period))
        got_days = set(out.loc[out["_period"] == period, "date"]) if not out.empty else set()
        date_gaps.extend(sorted(expected_days - got_days))

    total_mismatch = None
    if not out.empty:
        expected_total = monthly_df[amount_col].sum()
        got_total = out[amount_col].sum()
        if abs(expected_total - got_total) > 0.01:
            total_mismatch = {"expected": float(expected_total), "got": float(got_total)}

    result = GranularityValidationResult(ok=not date_gaps and total_mismatch is None, date_gaps=date_gaps, total_mismatch=total_mismatch)
    return out, result


def resolve_unilever_sku_grain(sku_daily_df: pd.DataFrame) -> tuple[pd.DataFrame, GranularityValidationResult]:
    """Unilever already has real per-SKU demand (the La Union file) -
    nothing to disaggregate. This function validates continuity only
    and passes the data through unchanged, so downstream SARIMA input
    is never silently altered here.

    DEC-10: required columns match Transform's real post-transform_fact()
    output for unilever_sku (sku_code, calendar_month 'YYYY-MM' - see
    transform.reformat_calendar_month() - and quantity_sold), not the
    analytics layer's later COALESCE(sku_code, category_path) "sku_id"
    convention (backend/schemas/abc.py) or a day-level "date" that
    doesn't exist anywhere in this source. Continuity is checked at
    MONTH grain accordingly - a daily pd.date_range gap-check against
    monthly data would flag nearly every day of every month as "missing",
    which is meaningless here. This also matches sarima.py's own monthly
    seasonality assumption (SARIMA_SEASONAL_PERIOD = 12)."""
    required = {"sku_code", "calendar_month", "quantity_sold"}
    missing = required - set(sku_daily_df.columns)
    if missing:
        raise KeyError(f"resolve_unilever_sku_grain missing required columns: {missing}")

    date_gaps: list[str] = []
    for sku_code, group in sku_daily_df.groupby("sku_code"):
        periods = pd.PeriodIndex(group["calendar_month"], freq="M").sort_values()
        if periods.empty:
            continue
        full_range = pd.period_range(periods.min(), periods.max(), freq="M")
        missing_periods = full_range.difference(periods)
        date_gaps.extend(str(p) for p in missing_periods)

    result = GranularityValidationResult(ok=not date_gaps, date_gaps=date_gaps, total_mismatch=None)
    return sku_daily_df.copy(), result


def resolve_granularity(monthly_df: pd.DataFrame, sku_daily_df: pd.DataFrame | None, principal: str) -> tuple[pd.DataFrame, GranularityValidationResult]:
    """Dispatch per DEC-03: Unilever -> SKU passthrough+validate,
    Del Monte -> even business-day distribution at category grain.
    `principal` must be 'unilever' or 'delmonte' - anything else raises,
    it does not guess."""
    if principal == "unilever":
        if sku_daily_df is None:
            raise ValueError("principal='unilever' requires sku_daily_df (the confirmed La Union SKU source).")
        return resolve_unilever_sku_grain(sku_daily_df)
    elif principal == "delmonte":
        return resolve_delmonte_category_grain(monthly_df)
    else:
        raise ValueError(f"Unknown principal '{principal}' - expected 'unilever' or 'delmonte'.")
