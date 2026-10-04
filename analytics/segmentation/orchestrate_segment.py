"""
analytics.segmentation.orchestrate_segment — Phase 2 binning orchestration
(reports/BINNING_ROUND1_2026-09.md). BINS ONLY: builds sku_traits once per
cohort, then sku_segment rows for one scheme at a time. No forecasting
model is run or scored here — that is Phase 3.

principal is a parameter throughout (never hardcoded), but only Unilever
has a wired demand source today — DEMAND_SOURCE_BY_PRINCIPAL below is the
single place a second principal's SKU-grain source would be registered.
Del Monte has none (Sales Register is invoice-grain, no SKU column, per
CLAUDE.md's Data realities) — calling this for 'delmonte' raises rather
than silently returning nothing.

Deterministic: every fetch orders by product_key ASC, matching the
tiebreak convention introduced in analytics.classification.abc (2026-09-17).
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from uuid import uuid4

import numpy as np
import pandas as pd
from sqlalchemy import Engine, MetaData, Table, create_engine, select, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from analytics.config import get_settings
from analytics.segmentation import bins as bin_schemes
from analytics.segmentation.traits import (
    history_months, first_sale_index, longest_positive_run,
    trend_stats, coefficient_of_variation, average_demand_interval,
    has_restart, stability_group, missing_month_indices,
)

DEMAND_SOURCE_BY_PRINCIPAL = {
    "unilever": "unilever_sku_demand_fact_real",
}

# sku_traits' own columns. build_traits() also returns tier_a_periods, which
# stability_v1's bin_reason reads but the table has no column for, so the
# upsert selects these explicitly.
TRAIT_TABLE_COLUMNS = [
    "run_id", "principal", "product_key", "cohort_period", "abc_method",
    "history_months", "first_sale_period", "longest_run", "trend", "cv",
    "restart_flag", "stability_group", "revenue_share_2026_02",
    "adi", "trend_pvalue", "trend_slope",  # migration 0022
]

TOTAL_PERIODS = 38  # 2023-01 .. 2026-02 inclusive, the only fully-real Unilever span (CLAUDE.md Data realities)


@dataclass
class SegmentRunReport:
    principal: str
    cohort_period: str
    abc_method: str
    run_id: str
    cohort_size: int
    traits_written: int = 0
    scheme_bin_counts: dict = field(default_factory=dict)  # scheme -> {bin: n}
    # product_key -> ['YYYY-MM', ...] months whose quantity is blank: missing, skipped by every trait, never 0
    missing_quantity: dict = field(default_factory=dict)


def _period_grid(start: str, end: str) -> list[str]:
    return [str(p) for p in pd.period_range(start, end, freq="M")]


def _fetch_cohort(engine: Engine, principal: str, cohort_period: str, abc_method: str) -> list[int]:
    metadata = MetaData()
    abc = Table("abc_classification", metadata, autoload_with=engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(abc.c.product_key)
            .where(and_(
                abc.c.principal == principal,
                abc.c.classification_period == cohort_period,
                abc.c.method == abc_method,
                abc.c.tier == "A",
            ))
            .order_by(abc.c.product_key.asc())
        ).fetchall()
    return [r[0] for r in rows]


def _fetch_demand_matrix(
    engine: Engine, principal: str, product_keys: list[int], start: str, end: str,
) -> dict[int, np.ndarray]:
    """One zero-filled monthly quantity array per product_key, ascending,
    over [start, end] inclusive. No row this period = a genuine zero-sale
    month (same "no row = fact, not gap" precedent as
    orchestrate_abc._fetch_unilever_sku_revenue). A negative month (returns
    exceeding sales) is kept as it is (DEC-15: flagged, never clamped); the
    traits that count sales months only count qty > 0 anyway. A row with a
    blank (NULL) quantity is MISSING - NaN, never 0 (DEC-31) - and every
    trait skips it (analytics.segmentation.traits); build_traits flags it."""
    source = DEMAND_SOURCE_BY_PRINCIPAL.get(principal)
    if source is None:
        raise NotImplementedError(
            f"No SKU-grain demand source registered for principal={principal!r} "
            f"(DEMAND_SOURCE_BY_PRINCIPAL). Del Monte has none per CLAUDE.md's "
            f"Data realities — do not fabricate one here."
        )
    metadata = MetaData()
    demand = Table(source, metadata, autoload_with=engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(demand.c.product_key, demand.c.calendar_month, demand.c.quantity_sold)
            .where(and_(
                demand.c.product_key.in_(product_keys),
                demand.c.calendar_month >= start,
                demand.c.calendar_month <= end,
            ))
        ).fetchall()
    periods = _period_grid(start, end)
    return _matrix_from_rows(rows, product_keys, periods), periods


def _matrix_from_rows(rows, product_keys: list[int], periods: list[str]) -> dict[int, np.ndarray]:
    """(product_key, period, qty) rows -> one array per product over `periods`:
    no row = 0, a NULL qty = NaN (missing, never 0), a negative kept (DEC-15)."""
    df = pd.DataFrame(rows, columns=["product_key", "period", "qty"])
    df["qty"] = df["qty"].astype(float)
    period_index = {p: i for i, p in enumerate(periods)}
    matrices: dict[int, np.ndarray] = {pk: np.zeros(len(periods)) for pk in product_keys}
    for row in df.itertuples():
        idx = period_index.get(row.period)
        if idx is None:
            continue
        qty = row.qty if not pd.isna(row.qty) else np.nan                # blank quantity: missing, never 0
        matrices[row.product_key][idx] = qty  # negatives kept (DEC-15); clipped to 0 until 2026-09-30
    return matrices


def _fetch_stability_and_revenue(
    engine: Engine, principal: str, product_keys: list[int], cohort_period: str, abc_method: str,
) -> tuple[dict[int, int], dict[int, float]]:
    from sqlalchemy import func
    metadata = MetaData()
    abc = Table("abc_classification", metadata, autoload_with=engine)
    with engine.connect() as conn:
        a_periods_rows = conn.execute(
            select(abc.c.product_key, func.count().label("n"))
            .where(and_(
                abc.c.principal == principal, abc.c.method == abc_method, abc.c.tier == "A",
                abc.c.product_key.in_(product_keys),
            ))
            .group_by(abc.c.product_key)
        ).fetchall()
        revenue_rows = conn.execute(
            select(abc.c.product_key, abc.c.revenue_share)
            .where(and_(
                abc.c.principal == principal, abc.c.method == abc_method,
                abc.c.classification_period == cohort_period,
                abc.c.product_key.in_(product_keys),
            ))
        ).fetchall()
    a_periods = {pk: 0 for pk in product_keys}
    for pk, n in a_periods_rows:
        a_periods[pk] = n
    revenue = {pk: None for pk in product_keys}
    for pk, rs in revenue_rows:
        revenue[pk] = float(rs) if rs is not None else None
    return a_periods, revenue


def _fetch_sku_codes(engine: Engine, principal: str, product_keys: list[int]) -> dict[int, str]:
    metadata = MetaData()
    prod = Table("product_dimension", metadata, autoload_with=engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(prod.c.product_key, prod.c.sku_code)
            .where(and_(prod.c.principal == principal, prod.c.product_key.in_(product_keys)))
        ).fetchall()
    return {pk: code for pk, code in rows}


def _fetch_observed_periods(engine: Engine, principal: str, start: str, end: str) -> set[str]:
    """Months in [start, end] the principal has ANY demand row for. A month
    outside this set is a data gap, not a zero-sale month, and ADI drops it
    (traits.average_demand_interval)."""
    metadata = MetaData()
    demand = Table(DEMAND_SOURCE_BY_PRINCIPAL[principal], metadata, autoload_with=engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(demand.c.calendar_month).distinct()
            .where(and_(demand.c.calendar_month >= start, demand.c.calendar_month <= end))
        ).fetchall()
    return {r[0] for r in rows}


def build_traits(
    engine: Engine, principal: str, cohort_period: str, abc_method: str,
    demand_start: str, demand_end: str, run_id: str,
) -> tuple[pd.DataFrame, SegmentRunReport]:
    product_keys = _fetch_cohort(engine, principal, cohort_period, abc_method)
    matrices, periods = _fetch_demand_matrix(engine, principal, product_keys, demand_start, demand_end)
    observed_periods = _fetch_observed_periods(engine, principal, demand_start, demand_end)
    observed = np.array([p in observed_periods for p in periods], dtype=bool)
    a_periods, revenue = _fetch_stability_and_revenue(engine, principal, product_keys, cohort_period, abc_method)

    records = []
    for pk in product_keys:  # already product_key ASC from _fetch_cohort
        qty = matrices[pk]
        fs_idx = first_sale_index(qty)
        trend, trend_pvalue, trend_slope = trend_stats(qty)
        records.append(dict(
            run_id=run_id,
            principal=principal,
            product_key=pk,
            cohort_period=cohort_period,
            abc_method=abc_method,  # part of the upsert key per migration 0020
            history_months=history_months(qty),
            first_sale_period=periods[fs_idx] if fs_idx is not None else None,
            longest_run=longest_positive_run(qty),
            trend=trend,
            trend_pvalue=trend_pvalue,
            trend_slope=trend_slope,
            cv=coefficient_of_variation(qty),
            adi=average_demand_interval(qty, observed),
            tier_a_periods=a_periods.get(pk, 0),
            restart_flag=has_restart(qty),
            stability_group=stability_group(a_periods.get(pk, 0), TOTAL_PERIODS),
            revenue_share_2026_02=revenue.get(pk),
            # the flag; not a sku_traits column (the upsert selects TRAIT_TABLE_COLUMNS)
            missing_quantity_periods=[periods[i] for i in missing_month_indices(qty)],
        ))
    traits_df = pd.DataFrame.from_records(records)
    report = SegmentRunReport(
        principal=principal, cohort_period=cohort_period, abc_method=abc_method,
        run_id=run_id, cohort_size=len(product_keys), traits_written=len(traits_df),
        missing_quantity={r["product_key"]: r["missing_quantity_periods"] for r in records
                          if r["missing_quantity_periods"]},
    )
    return traits_df, report


# scheme name -> how to call its bins.py function from one build_traits() row.
# None-safe: pandas turns a missing cv/trend_pvalue/trend_slope into NaN, and the
# scheme functions test `is None`.
def _opt(value):
    return None if pd.isna(value) else float(value)


SCHEME_BUILDERS = {
    "length_v1": lambda r: bin_schemes.length_v1(r.history_months),
    "length_v2": lambda r: bin_schemes.length_v2(r.history_months),
    "trend_v1": lambda r: bin_schemes.trend_v1(r.history_months, r.trend, _opt(r.trend_pvalue), _opt(r.trend_slope)),
    "volatility_v1": lambda r: bin_schemes.volatility_v1(r.history_months, _opt(r.cv)),
    "stability_v1": lambda r: bin_schemes.stability_v1(r.stability_group, r.tier_a_periods, TOTAL_PERIODS),
    "combined_v1": lambda r: bin_schemes.combined_v1(r.history_months, r.trend, _opt(r.trend_pvalue), _opt(r.trend_slope)),
}

# length_v1 is deliberately NOT a default: its 132 approved rows stay as
# written on 2026-09-17 for audit unless a run names it explicitly.
ROUND2_SCHEMES = ["length_v2", "trend_v1", "volatility_v1", "stability_v1", "combined_v1"]


def build_segments(
    traits_df: pd.DataFrame, run_id: str, sku_codes: dict[int, str], abc_method: str, scheme: str,
) -> pd.DataFrame:
    """abc_method is threaded through rather than hardcoded: it is part of
    sku_segment's upsert key (["product_key", "cohort_period", "abc_method",
    "scheme"]), so stamping a literal "single" on a --abc-method t3m run would
    have collided with the approved single-method cohort and silently
    overwritten it."""
    records = []
    for row in traits_df.sort_values("product_key").itertuples():
        bin_name, reason = SCHEME_BUILDERS[scheme](row)
        records.append(dict(
            run_id=run_id,
            principal=row.principal,
            product_key=row.product_key,
            sku_code=sku_codes.get(row.product_key),
            cohort_period=row.cohort_period,
            abc_method=abc_method,
            scheme=scheme,
            bin=bin_name,
            bin_reason=reason,
        ))
    return pd.DataFrame.from_records(records)


def _to_records(df: pd.DataFrame) -> list[dict]:
    """Rows as dicts with every missing value as None. pandas holds a missing
    float as NaN, and Postgres NUMERIC stores NaN as a real value rather than
    NULL — so an unmeasurable cv/trend_pvalue/trend_slope would land as 'NaN',
    count as non-null, and sort above every real number."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def _upsert(engine: Engine, table_name: str, df: pd.DataFrame, conflict_cols: list[str], update_cols: list[str], schema: str | None = None) -> int:
    if df.empty:
        return 0
    metadata = MetaData(schema=schema)
    table = Table(table_name, metadata, autoload_with=engine, schema=schema)
    records = _to_records(df)
    with engine.begin() as conn:
        stmt = pg_insert(table).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_cols,
            set_={c: getattr(stmt.excluded, c) for c in update_cols},
        )
        conn.execute(stmt)
    return len(records)


def run(
    principal: str, cohort_period: str, abc_method: str, schema: str | None = None,
    schemes: list[str] | None = None,
) -> SegmentRunReport:
    schemes = schemes or ROUND2_SCHEMES
    unknown = [s for s in schemes if s not in SCHEME_BUILDERS]
    if unknown:
        raise ValueError(f"unknown scheme(s) {unknown}; known: {sorted(SCHEME_BUILDERS)}")
    settings = get_settings()
    # SUPABASE_DB_URL (settings.supabase_db_url) is read-only on this project's
    # Supabase pooler config (confirmed 2026-09-17 - see report's Open items;
    # not investigated further, out of this task's scope). SUPABASE_DIRECT_URL
    # is the writable connection used by every other write path this session.
    db_url = os.environ.get("SUPABASE_DIRECT_URL") or settings.supabase_db_url
    engine = create_engine(db_url, pool_pre_ping=True)
    run_id = f"segment_{principal}_{cohort_period}_{uuid4().hex[:8]}"

    traits_df, report = build_traits(
        engine, principal, cohort_period, abc_method, "2023-01", "2026-02", run_id,
    )
    sku_codes = _fetch_sku_codes(engine, principal, traits_df["product_key"].tolist())
    segments_df = pd.concat(
        [build_segments(traits_df, run_id, sku_codes, abc_method, s) for s in schemes], ignore_index=True,
    )

    traits_written = _upsert(
        # abc_method is in the key per migration 0020 — without it a t3m cohort
        # silently overwrites single's traits (sku_segment already keys on it,
        # 0018:50; sku_traits was the gap).
        engine, "sku_traits", traits_df[TRAIT_TABLE_COLUMNS], ["product_key", "cohort_period", "abc_method"],
        ["run_id", "history_months", "first_sale_period", "longest_run", "trend",
         "cv", "restart_flag", "stability_group", "revenue_share_2026_02",
         "adi", "trend_pvalue", "trend_slope"],
        schema=schema,
    )
    report.traits_written = traits_written
    segments_written = _upsert(
        engine, "sku_segment", segments_df, ["product_key", "cohort_period", "abc_method", "scheme"],
        ["run_id", "sku_code", "bin", "bin_reason"],
        schema=schema,
    )
    for s in schemes:
        report.scheme_bin_counts[s] = segments_df.loc[segments_df["scheme"] == s, "bin"].value_counts().to_dict()
    print(f"traits written: {traits_written}, segments written: {segments_written}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 2 binning: sku_traits + sku_segment, one row per SKU per scheme.")
    parser.add_argument("--principal", default="unilever")
    parser.add_argument("--cohort-period", default="2026-02")
    parser.add_argument("--abc-method", default="single")
    parser.add_argument(
        "--schema", required=True,
        help="Schema to WRITE results into. REQUIRED and deliberately has no default — "
             "it previously defaulted to public, so a rehearsal took an extra flag while a "
             "live write took none. Same rule as orchestrate_abc.py's --schema. Real data "
             "is always read from public regardless of this flag.",
    )
    parser.add_argument(
        "--schemes", nargs="+", default=ROUND2_SCHEMES, choices=sorted(SCHEME_BUILDERS),
        help="Schemes to write. Default is the five Round 2 schemes; length_v1 is only "
             "rewritten if named here.",
    )
    args = parser.parse_args()

    r = run(args.principal, args.cohort_period, args.abc_method, schema=args.schema, schemes=args.schemes)
    print(r)
