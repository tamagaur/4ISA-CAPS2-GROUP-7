"""
analytics.classification.orchestrate_abc — ABC orchestration (Phase 3C,
the "not-yet-written orchestration script" analytics/classification/abc.py's
own docstring flags as the caller's responsibility).

classify_abc() itself is grain-agnostic and DB-free by design (see its
docstring). This module is the one place that:
  1. Reads real revenue out of the two product-mart fact tables that
     honestly carry a product/category identifier — Unilever_SKU_Demand_Fact
     (SKU grain) and SellOut_Fact (category grain, Del Monte) — never
     Sales_Fact, which is invoice-grain with no product key (DEC-02).
  2. Aggregates to one row per product_key for the requested period,
     the shape classify_abc() requires.
  3. Runs classify_abc() ONCE PER PRINCIPAL, never combined. Unilever
     SKU revenue and Del Monte category revenue are not comparable
     magnitudes (different grain, different reporting scale) — a single
     combined Pareto ranking would let one principal's larger numbers
     dominate the other's tier cutoffs. This is a deliberate design
     decision, not an oversight; flag to Yuan if a combined view is
     wanted later, it would need its own explicit function, not a
     silent change here.
  4. Upserts into ABC_Classification, same ON CONFLICT DO UPDATE
     discipline as analytics/etl/load.py (never a silent overwrite of
     unrelated columns, never a plain INSERT that could duplicate a
     re-run).

Anti-fabrication: rows with NULL or negative revenue are never coerced
to zero or silently dropped — they're excluded from classify_abc()'s
input and counted in AbcRunReport so a human can see exactly what was
left out and why, same "flag, never drop" precedent as
transform.dedup_facts()'s null_key_rows and DEC-13.

Not yet run against a live database as of this writing — needs
Extract → Transform → Load to have populated Unilever_SKU_Demand_Fact
and SellOut_Fact for the requested period first.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import Engine, MetaData, Table, create_engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from analytics.classification.abc import classify_abc
from analytics.config import get_settings


@dataclass
class AbcRunReport:
    principal: str
    classification_period: str
    input_rows: int                 # distinct product_keys with usable revenue
    excluded_null_revenue: int      # product_keys with NULL net_amount, excluded not zeroed
    excluded_negative_revenue: list  # product_keys with negative summed revenue — needs a human look, not auto-fixed
    tier_counts: dict = field(default_factory=dict)   # {'A': n, 'B': n, 'C': n}
    near_boundary_count: int = 0    # backlog #43: SKUs flagged as close to a tier cutoff
    rows_upserted: int = 0


def _fetch_unilever_sku_revenue(engine: Engine, period: str) -> tuple[pd.DataFrame, int]:
    """One row per sku_code for `period` (Unilever_SKU_Demand_Fact is
    already unique on (sku_code, calendar_month), so no aggregation is
    needed here — just select and join to the dimension for product_key).
    Returns (df with columns [sku_id, total_revenue], null_revenue_count)."""
    metadata = MetaData()
    demand = Table("unilever_sku_demand_fact", metadata, autoload_with=engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(demand.c.product_key, demand.c.net_amount)
            .where(demand.c.calendar_month == period)
        ).fetchall()
    df = pd.DataFrame(rows, columns=["sku_id", "total_revenue"])
    null_count = int(df["total_revenue"].isna().sum())
    df = df.dropna(subset=["total_revenue"])
    return df, null_count


def _fetch_delmonte_category_revenue(engine: Engine, period: str) -> tuple[pd.DataFrame, int]:
    """SellOut_Fact carries a row per (category_path, region, period) —
    Product_Dimension has no region column for grain='category' rows, so
    every region sharing a category_path resolves to the SAME
    product_key. Sum across regions before handing to classify_abc(),
    which requires exactly one row per sku_id."""
    metadata = MetaData()
    sellout = Table("sellout_fact", metadata, autoload_with=engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(sellout.c.product_key, sellout.c.net_amount)
            .where(sellout.c._period == period)
        ).fetchall()
    raw = pd.DataFrame(rows, columns=["sku_id", "total_revenue"])
    null_count = int(raw["total_revenue"].isna().sum())
    raw = raw.dropna(subset=["total_revenue"])
    df = raw.groupby("sku_id", as_index=False)["total_revenue"].sum()
    return df, null_count


def _split_negative_revenue(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """classify_abc() raises on ANY negative total_revenue rather than
    silently coercing — that's correct for it as a pure function, but an
    orchestration script running unattended needs to keep going for the
    rest of a principal's products rather than aborting the whole run
    over one bad row. Negative rows are pulled out and reported, never
    zeroed or dropped without a trace."""
    negative_mask = df["total_revenue"] < 0
    negative_ids = df.loc[negative_mask, "sku_id"].tolist()
    return df.loc[~negative_mask].reset_index(drop=True), negative_ids


def _upsert_abc_classification(
    engine: Engine, tiered_df: pd.DataFrame, principal: str, classification_period: str,
) -> int:
    if tiered_df.empty:
        return 0
    metadata = MetaData()
    abc_table = Table("abc_classification", metadata, autoload_with=engine)
    records = [
        {
            "product_key": int(row.sku_id),
            "principal": principal,
            "classification_period": classification_period,
            "tier": row.tier,
            "revenue_share": float(row.revenue_share),
            "cumulative_share": float(row.cumulative_share),
            "boundary_flag": bool(row.boundary_flag),
        }
        for row in tiered_df.itertuples()
    ]
    with engine.begin() as conn:
        stmt = pg_insert(abc_table).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["product_key", "classification_period"],
            set_={
                "tier": stmt.excluded.tier,
                "revenue_share": stmt.excluded.revenue_share,
                "cumulative_share": stmt.excluded.cumulative_share,
                "boundary_flag": stmt.excluded.boundary_flag,
                "computed_at": stmt.excluded.computed_at,  # refreshed on re-run — EXCLUDED includes DEFAULT now() since computed_at isn't in `records`
            },
        )
        conn.execute(stmt)
    return len(records)


def run_abc_for_principal(engine: Engine, principal: str, classification_period: str) -> AbcRunReport:
    if principal == "unilever":
        revenue_df, null_count = _fetch_unilever_sku_revenue(engine, classification_period)
    elif principal == "delmonte":
        revenue_df, null_count = _fetch_delmonte_category_revenue(engine, classification_period)
    else:
        raise ValueError(f"Unknown principal '{principal}' — expected 'unilever' or 'delmonte'.")

    clean_df, negative_ids = _split_negative_revenue(revenue_df)

    if clean_df.empty:
        return AbcRunReport(
            principal=principal,
            classification_period=classification_period,
            input_rows=0,
            excluded_null_revenue=null_count,
            excluded_negative_revenue=negative_ids,
        )

    tiered = classify_abc(clean_df)
    rows_upserted = _upsert_abc_classification(engine, tiered, principal, classification_period)

    tier_counts = tiered["tier"].value_counts().to_dict()
    near_boundary_count = int(tiered["boundary_flag"].sum())
    return AbcRunReport(
        principal=principal,
        classification_period=classification_period,
        input_rows=len(clean_df),
        excluded_null_revenue=null_count,
        excluded_negative_revenue=negative_ids,
        tier_counts=tier_counts,
        near_boundary_count=near_boundary_count,
        rows_upserted=rows_upserted,
    )


def run_abc(classification_period: str) -> list[AbcRunReport]:
    """Runs ABC classification for both principals for one period.
    Each principal's ranking is independent — see module docstring."""
    settings = get_settings()
    engine = create_engine(settings.supabase_db_url, pool_pre_ping=True)
    return [
        run_abc_for_principal(engine, "unilever", classification_period),
        run_abc_for_principal(engine, "delmonte", classification_period),
    ]


def _print_report(report: AbcRunReport) -> None:
    print(f"\n=== ABC classification: {report.principal} / {report.classification_period} ===")
    print(f"  Products classified: {report.input_rows}")
    print(f"  Tier breakdown:      {report.tier_counts or '(none)'}")
    print(f"  Near tier boundary:  {report.near_boundary_count} (backlog #43, margin unconfirmed vs manuscript Sec.3.6)")
    print(f"  Rows upserted:       {report.rows_upserted}")
    if report.excluded_null_revenue:
        print(f"  Excluded (NULL revenue, not zeroed): {report.excluded_null_revenue}")
    if report.excluded_negative_revenue:
        print(f"  Excluded (negative revenue, needs a human look): {report.excluded_negative_revenue}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ABC/Pareto classification for both principals for one period.")
    parser.add_argument("--period", required=True, help="Classification period, 'YYYY-MM' (e.g. 2024-02).")
    args = parser.parse_args()

    reports = run_abc(args.period)
    for r in reports:
        _print_report(r)
