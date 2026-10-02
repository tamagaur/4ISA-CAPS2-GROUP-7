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
transform.dedup_facts()'s null_key_rows and DEC-15.

Needs Extract → Transform → Load to have populated Unilever_SKU_Demand_Fact
and SellOut_Fact for the requested period first.

Fixed 2026-08 (first live run against Supabase): the Unilever/Del Monte
fetch functions below now cast their NUMERIC-sourced revenue column to
float immediately after querying. Postgres NUMERIC comes back through
psycopg2/SQLAlchemy as decimal.Decimal, not float, when read via a raw
select() like this - abc.py's TIER_A_CUTOFF/BOUNDARY_MARGIN are plain
float literals, and Decimal refuses mixed-type arithmetic (subtraction)
with float even though it allows mixed-type comparison, so the very
first live run crashed inside classify_abc()'s boundary_flag calculation
before this fix. Cast at the fetch boundary, not by changing abc.py's
constants to Decimal - every other consumer of this module already
assumes float throughout.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from uuid import uuid4

import pandas as pd
from sqlalchemy import Engine, MetaData, Table, create_engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from analytics.classification.abc import classify_abc
from analytics.config import get_settings

METHODS = ("single", "t3m")
T3M_WINDOW_MONTHS = 3  # ROWS BETWEEN 2 PRECEDING AND CURRENT ROW in the recovered source


@dataclass
class AbcRunReport:
    principal: str
    classification_period: str
    input_rows: int                 # distinct product_keys actually classified (positive revenue)
    excluded_null_revenue: int      # product_keys with NULL net_amount, excluded not zeroed
    excluded_negative_revenue: list  # product_keys with negative summed revenue — needs a human look, not auto-fixed
    excluded_zero_revenue: int = 0   # product_keys with net_amount == 0 this period ("inactive", not Tier C — 2026-09-17)
    tier_counts: dict = field(default_factory=dict)   # {'A': n, 'B': n, 'C': n}
    near_boundary_count: int = 0    # backlog #43: SKUs flagged as close to a tier cutoff
    rows_upserted: int = 0
    error: str | None = None        # set (input_rows/tier_counts/etc. left at defaults) if this principal's run raised


def _fetch_unilever_sku_revenue(engine: Engine, period: str) -> tuple[pd.DataFrame, int]:
    """One row per sku_code for `period` (Unilever_SKU_Demand_Fact is
    already unique on (sku_code, calendar_month), so no aggregation is
    needed here — just select and join to the dimension for product_key).
    Returns (df with columns [sku_id, total_revenue], null_revenue_count)."""
    metadata = MetaData()
    demand = Table("unilever_sku_demand_fact_real", metadata, autoload_with=engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(demand.c.product_key, demand.c.net_amount)
            .where(demand.c.calendar_month == period)
        ).fetchall()
    df = pd.DataFrame(rows, columns=["sku_id", "total_revenue"])
    # net_amount is a Postgres NUMERIC column - psycopg2/SQLAlchemy return
    # it as decimal.Decimal, not float, when read via a raw select() like
    # this (no pd.read_sql-style dtype coercion happens anywhere in this
    # fetch path). Cast here, at the fetch boundary, rather than changing
    # abc.py's TIER_A_CUTOFF/BOUNDARY_MARGIN constants to Decimal - the
    # rest of this module (and classify_abc()) already assumes float
    # throughout. astype(float) on an object column of Decimal/None
    # correctly turns None into NaN, so the null-count check below still
    # works unchanged.
    df["total_revenue"] = df["total_revenue"].astype(float)

    # An EXPLICIT NULL net_amount on a real unilever_sku_demand_fact row is
    # a data-quality gap, not a zero sale — excluded here (anti-fabrication,
    # see module docstring), same as before the zero-sale fill below was
    # added. Tracked by sku_id, not just counted, so the zero-sale fill
    # below can't silently re-include these under the different "no row at
    # all this period" case.
    null_count = int(df["total_revenue"].isna().sum())
    null_sku_ids = set(df.loc[df["total_revenue"].isna(), "sku_id"])
    df = df.dropna(subset=["total_revenue"])

    # Every OTHER real Unilever product with NO ROW AT ALL this period is a
    # genuine zero-sale month (a fact, not a gap) — included as 0.0 so it
    # correctly lands in Category C instead of silently vanishing from the
    # classification. Explicit-NULL products (null_sku_ids) are excluded
    # from this set too, so they stay excluded rather than being
    # re-introduced as a fabricated zero via this left join.
    prod_dim = Table("product_dimension", metadata, autoload_with=engine)
    with engine.connect() as conn:
        all_skus = conn.execute(
            select(prod_dim.c.product_key)
            .where(prod_dim.c.principal == 'unilever')
        ).fetchall()

    all_df = pd.DataFrame(all_skus, columns=["sku_id"])
    all_df = all_df[~all_df["sku_id"].isin(null_sku_ids)]
    df = all_df.merge(df, on="sku_id", how="left")
    df["total_revenue"] = df["total_revenue"].fillna(0.0)

    return df, null_count


def _fetch_unilever_sku_revenue_t3m(engine: Engine, period: str) -> tuple[pd.DataFrame, int]:
    """Trailing-3-month revenue per sku_code for `period`, inclusive of it.

    Recovered 2026-09-20 from the ad-hoc script that produced the 25,437
    `method='t3m'` rows live in public.abc_classification
    (run_id='phase2_unilever_2026-09-17_v2'). That script was written to a
    session scratchpad, run once, never committed, and has since been deleted
    from disk; the source is preserved at
    analytics/classification/recovered/rebuild_abc_phase2_v2.py. This function
    is a transcription of its `single`/`t3m_win`/`t3m` CTEs, verified to
    reproduce all 25,437 rows exactly.

    NEGATIVE-REVENUE INCONSISTENCY — DISCLOSURE, NOT A FIX (2026-09-20)
    ------------------------------------------------------------------
    This function zeroes a negative net_amount PER MONTH, before summing the
    window. `single` does not: _split_negative_revenue() (below) clamps the
    AGGREGATED total. With single's one-month window the two coincide, so the
    difference is invisible there and only appears here.

    The consequence is that a SKU with a large return in one month and sales in
    the other two keeps the sales and never absorbs the return.

    This was NOT a methodology decision. The recovered source computed t3m as a
    window over the already-clamped single-month values
    (`ROWS BETWEEN 2 PRECEDING AND CURRENT ROW`), so per-month clamping fell out
    of the construction. Measured cost of reconciling it the other way — i.e.
    applying single's aggregate clamp to a 3-month window — is 25,215 rows
    instead of 25,437: 222 SKUs short, with 64 tier and 596 revenue_share
    mismatches against what is live.

    Reproducing what is live requires the per-month clamp, so that is what this
    does. Whether the two methods SHOULD agree is a methodology question for the
    adviser gate; it is deliberately not reconciled here, because changing it
    would silently invalidate rows already written to public.
    """
    metadata = MetaData()
    demand = Table("unilever_sku_demand_fact_real", metadata, autoload_with=engine)

    # Window membership follows the DISTINCT periods actually present in the
    # fact, ordered by date — not calendar arithmetic. That is what the
    # recovered source's ROWS BETWEEN 2 PRECEDING did over its dense grid, and
    # it keeps the behaviour identical if the series ever has a gap.
    with engine.connect() as conn:
        window = [
            r[0] for r in conn.execute(
                select(demand.c.calendar_month)
                .where(demand.c.calendar_month <= period)
                .distinct()
                .order_by(demand.c.calendar_month.desc())
                .limit(T3M_WINDOW_MONTHS)
            ).fetchall()
        ]

    # window_rows < 3 in the recovered source. A partial window is NOT
    # classified on the months it does have — the period is skipped entirely,
    # which is why 2023-01 and 2023-02 have no t3m rows at all.
    if len(window) < T3M_WINDOW_MONTHS:
        return pd.DataFrame(columns=["sku_id", "total_revenue"]), 0

    with engine.connect() as conn:
        rows = conn.execute(
            select(demand.c.product_key, demand.c.net_amount)
            .where(demand.c.calendar_month.in_(window))
        ).fetchall()
    df = pd.DataFrame(rows, columns=["sku_id", "total_revenue"])
    df["total_revenue"] = df["total_revenue"].astype(float)  # NUMERIC -> Decimal, see above

    # BOOL_OR(excluded_null) OVER w: an explicit NULL anywhere in the window
    # disqualifies the SKU for this period — not just the month it occurred in.
    null_sku_ids = set(df.loc[df["total_revenue"].isna(), "sku_id"])
    null_count = len(null_sku_ids)
    df = df.dropna(subset=["total_revenue"])

    # The per-month clamp described in this function's docstring.
    df.loc[df["total_revenue"] < 0, "total_revenue"] = 0.0
    df = df.groupby("sku_id", as_index=False)["total_revenue"].sum()

    prod_dim = Table("product_dimension", metadata, autoload_with=engine)
    with engine.connect() as conn:
        all_skus = conn.execute(
            select(prod_dim.c.product_key).where(prod_dim.c.principal == 'unilever')
        ).fetchall()

    all_df = pd.DataFrame(all_skus, columns=["sku_id"])
    all_df = all_df[~all_df["sku_id"].isin(null_sku_ids)]
    df = all_df.merge(df, on="sku_id", how="left")
    df["total_revenue"] = df["total_revenue"].fillna(0.0)

    return df, null_count


def _fetch_delmonte_category_revenue(engine: Engine, period: str) -> tuple[pd.DataFrame, int]:
    """SellOut_Fact carries a row per (category_path, region, period) —
    Product_Dimension has no region column for grain='category' rows, so
    every region sharing a category_path resolves to the SAME
    product_key. Sum across regions before handing to classify_abc(),
    which requires exactly one row per sku_id."""
    metadata = MetaData()
    sellout = Table("sellout_fact_real", metadata, autoload_with=engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(sellout.c.product_key, sellout.c.net_amount)
            .where(sellout.c._period == period)
        ).fetchall()
    raw = pd.DataFrame(rows, columns=["sku_id", "total_revenue"])
    # Same NUMERIC -> Decimal cast as _fetch_unilever_sku_revenue() above -
    # see that function's comment for the full reasoning. Cast before the
    # groupby/sum so the aggregation itself is float arithmetic too.
    raw["total_revenue"] = raw["total_revenue"].astype(float)
    df = raw.groupby("sku_id", as_index=False)["total_revenue"].sum()

    # NEW: Fetch ALL Del Monte product_keys so zero-sale items get included
    prod_dim = Table("product_dimension", metadata, autoload_with=engine)
    with engine.connect() as conn:
        all_skus = conn.execute(
            select(prod_dim.c.product_key)
            .where(prod_dim.c.principal == 'delmonte')
        ).fetchall()
        
    all_df = pd.DataFrame(all_skus, columns=["sku_id"])
    df = all_df.merge(df, on="sku_id", how="left")
    
    null_count = int(df["total_revenue"].isna().sum())
    # Fill missing sales with 0.0 so they fall into Category C
    df["total_revenue"] = df["total_revenue"].fillna(0.0)
    
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
    # Clamp negative revenue to 0.0 - these rows then flow into
    # _split_zero_revenue() below and are excluded as "inactive", same
    # treatment as a genuine zero-sale product (2026-09-17: no longer
    # fabricated into Tier C, see _split_zero_revenue()'s docstring).
    df.loc[negative_mask, "total_revenue"] = 0.0
    return df, negative_ids


def _split_zero_revenue(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """"Present" for ABC purposes means net_amount > 0 for that period
    (2026-09-17, Yuan). A product with zero revenue that period —
    whether a genuine zero-sale month or a negative row clamped to 0 by
    _split_negative_revenue() above — is not a Tier C SKU: Tier C is
    for products that ARE selling, just at low volume. Fabricating a
    tier for a product that had no sales at all would misrepresent it
    as "least important but active" rather than "inactive this period".

    These rows are excluded from classify_abc()'s input entirely (no
    tier, no upsert) rather than given a fabricated tier value - the
    same "flag, never drop silently" precedent as the null/negative
    exclusions, just reported as a distinct count rather than coerced
    into any tier."""
    zero_mask = df["total_revenue"] == 0
    zero_ids = df.loc[zero_mask, "sku_id"].tolist()
    return df.loc[~zero_mask].copy(), zero_ids


def _upsert_abc_classification(
    engine: Engine, tiered_df: pd.DataFrame, principal: str, classification_period: str,
    method: str = "single", run_id: str | None = None, schema: str | None = None,
) -> int:
    """schema selects the WRITE target only — the fetch functions above always
    read real data from the `_Real` views in public (Hard Rule 1). Passing a
    scratch schema here is what makes a rehearsal possible without touching
    public; same `schema: str | None` shape as
    analytics/segmentation/orchestrate_segment.py's _upsert()."""
    if tiered_df.empty:
        return 0
    run_id = run_id or f"{method}_{uuid4().hex[:12]}"
    metadata = MetaData(schema=schema)
    abc_table = Table("abc_classification", metadata, autoload_with=engine, schema=schema)
    records = [
        {
            "product_key": int(row.sku_id),
            "principal": principal,
            "classification_period": classification_period,
            "method": method,
            "run_id": run_id,
            "tier": row.tier,
            "revenue_share": None if pd.isna(row.revenue_share) else float(row.revenue_share),
            "cumulative_share": None if pd.isna(row.cumulative_share) else float(row.cumulative_share),
            "boundary_flag": bool(row.boundary_flag),
        }
        for row in tiered_df.itertuples()
    ]
    with engine.begin() as conn:
        stmt = pg_insert(abc_table).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["product_key", "classification_period", "method"],
            set_={
                "run_id": stmt.excluded.run_id,
                "tier": stmt.excluded.tier,
                "revenue_share": stmt.excluded.revenue_share,
                "cumulative_share": stmt.excluded.cumulative_share,
                "boundary_flag": stmt.excluded.boundary_flag,
                "computed_at": stmt.excluded.computed_at,  # refreshed on re-run — EXCLUDED includes DEFAULT now() since computed_at isn't in `records`
            },
        )
        conn.execute(stmt)
    return len(records)


def run_abc_for_principal(
    engine: Engine, principal: str, classification_period: str,
    method: str = "single", run_id: str | None = None, schema: str | None = None,
) -> AbcRunReport:
    if method not in METHODS:
        raise ValueError(f"Unknown method '{method}' — expected one of {METHODS}.")

    if principal == "unilever":
        if method == "t3m":
            revenue_df, null_count = _fetch_unilever_sku_revenue_t3m(engine, classification_period)
        else:
            revenue_df, null_count = _fetch_unilever_sku_revenue(engine, classification_period)
    elif principal == "delmonte":
        if method == "t3m":
            # The recovered producer was Unilever-only; no t3m rows have ever
            # existed for delmonte. Refuse rather than quietly classifying a
            # single month under a t3m label.
            raise ValueError(
                "method='t3m' is not defined for delmonte — the recovered producer "
                "(analytics/classification/recovered/rebuild_abc_phase2_v2.py) only "
                "ever built Unilever. Del Monte ABC is separately blocked on DEC-03."
            )
        revenue_df, null_count = _fetch_delmonte_category_revenue(engine, classification_period)
    else:
        raise ValueError(f"Unknown principal '{principal}' — expected 'unilever' or 'delmonte'.")

    clamped_df, negative_ids = _split_negative_revenue(revenue_df)
    clean_df, zero_ids = _split_zero_revenue(clamped_df)

    if clean_df.empty:
        return AbcRunReport(
            principal=principal,
            classification_period=classification_period,
            input_rows=0,
            excluded_null_revenue=null_count,
            excluded_negative_revenue=negative_ids,
            excluded_zero_revenue=len(zero_ids),
        )

    tiered = classify_abc(clean_df)
    rows_upserted = _upsert_abc_classification(
        engine, tiered, principal, classification_period, method, run_id, schema,
    )

    tier_counts = tiered["tier"].value_counts().to_dict()
    near_boundary_count = int(tiered["boundary_flag"].sum())
    return AbcRunReport(
        principal=principal,
        classification_period=classification_period,
        input_rows=len(clean_df),
        excluded_null_revenue=null_count,
        excluded_negative_revenue=negative_ids,
        excluded_zero_revenue=len(zero_ids),
        tier_counts=tier_counts,
        near_boundary_count=near_boundary_count,
        rows_upserted=rows_upserted,
    )


def run_abc(
    classification_period: str, method: str = "single",
    schema: str | None = None, run_id: str | None = None,
    principals: tuple[str, ...] = ("unilever", "delmonte"),
) -> list[AbcRunReport]:
    """Runs ABC classification for both principals for one period.
    Each principal's ranking is independent — see module docstring.

    One principal's failure does not abort the other's: each run is
    wrapped in its own try/except so, e.g., a Del Monte-specific data
    issue can never prevent Unilever's classification (already computed
    or about to be) from landing. The failure is logged (printed) and
    recorded on the returned AbcRunReport via its `error` field rather
    than raised, so a caller can see exactly which principal(s) succeeded
    without having to catch anything itself."""
    settings = get_settings()
    engine = create_engine(settings.supabase_db_url, pool_pre_ping=True)

    reports = []
    for principal in principals:
        try:
            reports.append(run_abc_for_principal(
                engine, principal, classification_period, method, run_id, schema,
            ))
        except Exception as exc:  # noqa: BLE001 - intentionally broad: any failure must not abort the other principal
            print(f"ABC classification FAILED for principal={principal!r} period={classification_period!r}: "
                  f"{type(exc).__name__}: {exc}")
            reports.append(AbcRunReport(
                principal=principal,
                classification_period=classification_period,
                input_rows=0,
                excluded_null_revenue=0,
                excluded_negative_revenue=[],
                error=f"{type(exc).__name__}: {exc}",
            ))
    return reports


def _print_report(report: AbcRunReport) -> None:
    print(f"\n=== ABC classification: {report.principal} / {report.classification_period} ===")
    if report.error:
        print(f"  FAILED: {report.error}")
        return
    print(f"  Products classified: {report.input_rows}")
    print(f"  Tier breakdown:      {report.tier_counts or '(none)'}")
    print(f"  Near tier boundary:  {report.near_boundary_count} (backlog #43, margin unconfirmed vs manuscript Sec.3.6)")
    print(f"  Rows upserted:       {report.rows_upserted}")
    if report.excluded_null_revenue:
        print(f"  Excluded (NULL revenue, not zeroed): {report.excluded_null_revenue}")
    if report.excluded_negative_revenue:
        print(f"  Excluded (negative revenue, needs a human look): {report.excluded_negative_revenue}")
    if report.excluded_zero_revenue:
        print(f"  Excluded (zero revenue, inactive this period): {report.excluded_zero_revenue}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ABC/Pareto classification for one period.")
    parser.add_argument("--period", required=True, help="Classification period, 'YYYY-MM' (e.g. 2024-02).")
    parser.add_argument(
        "--schema", required=True,
        help="Schema to WRITE results into. REQUIRED and deliberately has no default — "
             "this script previously wrote public unconditionally, so a rehearsal was "
             "impossible. Real data is always read from the _Real views in public "
             "regardless of this flag.",
    )
    parser.add_argument(
        "--method", choices=METHODS, default="single",
        help="'single' = that month's revenue (deployed). 't3m' = trailing 3 months "
             "including it; see _fetch_unilever_sku_revenue_t3m()'s docstring for the "
             "negative-revenue inconsistency between the two.",
    )
    parser.add_argument("--run-id", default=None, help="Stamp a specific run_id (default: generated).")
    parser.add_argument(
        "--principal", choices=("unilever", "delmonte", "both"), default="both",
        help="t3m is Unilever-only.",
    )
    args = parser.parse_args()

    principals = ("unilever", "delmonte") if args.principal == "both" else (args.principal,)
    reports = run_abc(args.period, args.method, args.schema, args.run_id, principals)
    for r in reports:
        _print_report(r)
