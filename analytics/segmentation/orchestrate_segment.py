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
    mann_kendall_trend, coefficient_of_variation, has_restart, stability_group,
)

DEMAND_SOURCE_BY_PRINCIPAL = {
    "unilever": "unilever_sku_demand_fact_real",
}

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
    orchestrate_abc._fetch_unilever_sku_revenue)."""
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
    df = pd.DataFrame(rows, columns=["product_key", "period", "qty"])
    df["qty"] = df["qty"].astype(float)

    periods = _period_grid(start, end)
    period_index = {p: i for i, p in enumerate(periods)}
    matrices: dict[int, np.ndarray] = {pk: np.zeros(len(periods)) for pk in product_keys}
    for row in df.itertuples():
        idx = period_index.get(row.period)
        if idx is None:
            continue
        qty = row.qty if not pd.isna(row.qty) else 0.0
        matrices[row.product_key][idx] = max(qty, 0.0)  # negative rows clipped to 0, noted not investigated (see report Open items)
    return matrices, periods


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


def build_traits(
    engine: Engine, principal: str, cohort_period: str, abc_method: str,
    demand_start: str, demand_end: str, run_id: str,
) -> tuple[pd.DataFrame, SegmentRunReport]:
    product_keys = _fetch_cohort(engine, principal, cohort_period, abc_method)
    matrices, periods = _fetch_demand_matrix(engine, principal, product_keys, demand_start, demand_end)
    a_periods, revenue = _fetch_stability_and_revenue(engine, principal, product_keys, cohort_period, abc_method)

    records = []
    for pk in product_keys:  # already product_key ASC from _fetch_cohort
        qty = matrices[pk]
        fs_idx = first_sale_index(qty)
        records.append(dict(
            run_id=run_id,
            principal=principal,
            product_key=pk,
            cohort_period=cohort_period,
            history_months=history_months(qty),
            first_sale_period=periods[fs_idx] if fs_idx is not None else None,
            longest_run=longest_positive_run(qty),
            trend=mann_kendall_trend(qty),
            cv=coefficient_of_variation(qty),
            restart_flag=has_restart(qty),
            stability_group=stability_group(a_periods.get(pk, 0), TOTAL_PERIODS),
            revenue_share_2026_02=revenue.get(pk),
        ))
    traits_df = pd.DataFrame.from_records(records)
    report = SegmentRunReport(
        principal=principal, cohort_period=cohort_period, abc_method=abc_method,
        run_id=run_id, cohort_size=len(product_keys), traits_written=len(traits_df),
    )
    return traits_df, report


def build_segments_length_v1(traits_df: pd.DataFrame, run_id: str, sku_codes: dict[int, str]) -> pd.DataFrame:
    records = []
    for row in traits_df.sort_values("product_key").itertuples():
        bin_name, reason = bin_schemes.length_v1(row.history_months)
        records.append(dict(
            run_id=run_id,
            principal=row.principal,
            product_key=row.product_key,
            sku_code=sku_codes.get(row.product_key),
            cohort_period=row.cohort_period,
            abc_method="single",
            scheme="length_v1",
            bin=bin_name,
            bin_reason=reason,
        ))
    return pd.DataFrame.from_records(records)


def _upsert(engine: Engine, table_name: str, df: pd.DataFrame, conflict_cols: list[str], update_cols: list[str], schema: str | None = None) -> int:
    if df.empty:
        return 0
    metadata = MetaData(schema=schema)
    table = Table(table_name, metadata, autoload_with=engine, schema=schema)
    records = df.to_dict(orient="records")
    with engine.begin() as conn:
        stmt = pg_insert(table).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_cols,
            set_={c: getattr(stmt.excluded, c) for c in update_cols},
        )
        conn.execute(stmt)
    return len(records)


def run(principal: str, cohort_period: str, abc_method: str, schema: str | None = None) -> SegmentRunReport:
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
    segments_df = build_segments_length_v1(traits_df, run_id, sku_codes)

    traits_written = _upsert(
        engine, "sku_traits", traits_df, ["product_key", "cohort_period"],
        ["run_id", "history_months", "first_sale_period", "longest_run", "trend",
         "cv", "restart_flag", "stability_group", "revenue_share_2026_02"],
        schema=schema,
    )
    report.traits_written = traits_written
    segments_written = _upsert(
        engine, "sku_segment", segments_df, ["product_key", "cohort_period", "abc_method", "scheme"],
        ["run_id", "sku_code", "bin", "bin_reason"],
        schema=schema,
    )
    report.scheme_bin_counts["length_v1"] = segments_df["bin"].value_counts().to_dict()
    print(f"traits written: {traits_written}, segments written: {segments_written}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 2 binning Round 1: sku_traits + sku_segment (length_v1).")
    parser.add_argument("--principal", default="unilever")
    parser.add_argument("--cohort-period", default="2026-02")
    parser.add_argument("--abc-method", default="single")
    parser.add_argument("--schema", default=None, help="Target schema (default: public). Use a scratch schema first.")
    args = parser.parse_args()

    r = run(args.principal, args.cohort_period, args.abc_method, schema=args.schema)
    print(r)
