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
  - Unilever: real per-SKU MONTHLY demand exists (Unilever La Union file -
    one row per SKU per month, not daily) -> resolve_unilever_sku_grain()
    passes it through and validates month-to-month continuity, it does
    not need disaggregation from an invoice total. Which quantity field
    (sale_quantity_cases vs sale_quantity_pieces) is canonical is not yet
    confirmed against real data - see that function's docstring.
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


def resolve_delmonte_category_grain(
    monthly_df: pd.DataFrame, amount_col: str = "net_amount", expected_doc_type: str = "sell_out",
) -> tuple[pd.DataFrame, GranularityValidationResult]:
    """Distribute each row's monthly total evenly across that month's
    business days, at category grain (DEC-03). Even distribution is the
    only allocation that does not fabricate a shape the data doesn't
    support - it is stated as such, not disguised as a forecast.

    Expects monthly_df to already be canonical + deduped (i.e. has gone
    through transform.transform_fact) with columns: _period, _principal,
    plus a category/region grouping column and amount_col.

    Raises ValueError if any row's _doc_type isn't expected_doc_type
    (2026-08, Transform reconciliation story #16): DEC-03/§5.1 requires
    Del Monte's demand source to be Sell Out (category grain), never
    Sales Register (invoice grain) - allocating an invoice total down to
    category would still be a real number, but it would be answering a
    different, unsupported question than what the data actually shows.
    Nothing upstream previously stopped this function from being called
    on the wrong doc_type by accident; this makes that a loud, explicit
    error instead of a plausible-looking but architecturally-forbidden
    result."""
    required = {"_period", amount_col}
    missing = required - set(monthly_df.columns)
    if missing:
        raise KeyError(f"resolve_delmonte_category_grain missing required columns: {missing}")
    if "_doc_type" in monthly_df.columns:
        bad = set(monthly_df["_doc_type"].unique()) - {expected_doc_type}
        if bad:
            raise ValueError(
                f"resolve_delmonte_category_grain received doc_type(s) {sorted(bad)}, "
                f"expected only '{expected_doc_type}' — DEC-03/§5.1 forbids SKU/invoice-grain "
                f"fabrication via this path."
            )

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


# config/column_maps/unilever_sku.yaml's own comment: "not yet confirmed
# which canonical fact field... quantity_sold is populated from the
# quantity columns above [sale_quantity_cases / sale_quantity_pieces],
# not from GSV" - narrows the choice to these two, but does not decide
# between them. TODO(needs a person + real data, not this code): confirm
# empirically once the La Union file is available - check whether both
# columns are populated or one is mostly null, whether pack_size
# reconciles cases*pack_size to pieces on a real sample, and default to
# CASES (not pieces) if pack_size is absent or that reconciliation fails,
# since SSM orders/holds inventory in cases and the LP output becomes a
# purchase order. Not decided here — see resolve_unilever_sku_grain()'s
# required quantity_col argument below, which refuses to default.
UNILEVER_QUANTITY_FIELD_CANDIDATES = ("sale_quantity_cases", "sale_quantity_pieces")


def resolve_unilever_sku_grain(sku_daily_df: pd.DataFrame, quantity_col: str) -> tuple[pd.DataFrame, GranularityValidationResult]:
    """Unilever already has real per-SKU demand (the La Union file) -
    nothing to disaggregate. This function validates continuity only
    and passes the data through unchanged, so downstream SARIMA input
    is never silently altered here.

    quantity_col has no default on purpose: which of
    UNILEVER_QUANTITY_FIELD_CANDIDATES is canonical "quantity_sold" is an
    open question (see the module-level TODO above), unconfirmed against
    real data. Callers must pass it explicitly, keeping that decision
    visible at every call site instead of silently baked in here.

    Grain is monthly (transform.reformat_calendar_month has already
    normalized calendar_month to 'YYYY-MM' by the time this runs), not
    daily — the source file itself reports one row per SKU per month, so
    a day-grain continuity check would fabricate a granularity the data
    doesn't have."""
    if quantity_col not in UNILEVER_QUANTITY_FIELD_CANDIDATES:
        raise ValueError(
            f"quantity_col={quantity_col!r} is not one of the confirmed candidate "
            f"fields {UNILEVER_QUANTITY_FIELD_CANDIDATES} — resolve_unilever_sku_grain "
            f"will not guess at an unconfirmed column."
        )
    required = {"sku_code", "calendar_month", quantity_col}
    missing = required - set(sku_daily_df.columns)
    if missing:
        raise KeyError(f"resolve_unilever_sku_grain missing required columns: {missing}")

    date_gaps: list[str] = []
    for sku_code, group in sku_daily_df.groupby("sku_code"):
        months = pd.PeriodIndex(group["calendar_month"], freq="M").sort_values()
        if len(months) == 0:
            continue
        full_range = pd.period_range(months.min(), months.max(), freq="M")
        missing_months = full_range.difference(months)
        date_gaps.extend(str(m) for m in missing_months)

    result = GranularityValidationResult(ok=not date_gaps, date_gaps=date_gaps, total_mismatch=None)
    return sku_daily_df.copy(), result


def resolve_granularity(
    monthly_df: pd.DataFrame, sku_daily_df: pd.DataFrame | None, principal: str,
    unilever_quantity_col: str | None = None,
) -> tuple[pd.DataFrame, GranularityValidationResult]:
    """Dispatch per DEC-03: Unilever -> SKU passthrough+validate,
    Del Monte -> even business-day distribution at category grain.
    `principal` must be 'unilever' or 'delmonte' - anything else raises,
    it does not guess."""
    if principal == "unilever":
        if sku_daily_df is None:
            raise ValueError("principal='unilever' requires sku_daily_df (the confirmed La Union SKU source).")
        if unilever_quantity_col is None:
            raise ValueError(
                "principal='unilever' requires unilever_quantity_col explicitly - see "
                "resolve_unilever_sku_grain()'s docstring, this is not yet confirmed against real data."
            )
        return resolve_unilever_sku_grain(sku_daily_df, unilever_quantity_col)
    elif principal == "delmonte":
        return resolve_delmonte_category_grain(monthly_df)
    else:
        raise ValueError(f"Unknown principal '{principal}' - expected 'unilever' or 'delmonte'.")
