"""
backend.routers.abc — GET /abc

Phase 6 (CLAUDE.md Step 23):
  Returns ABC tier assignments for all active SKUs.
  Reads from ABC_Classification table in Supabase. Requires auth.

Implemented 2026-08 (was a stub — see git history). Joins
ABC_Classification to Product_Dimension for sku_id/product_name:
COALESCE(sku_code, category_path) per backend/schemas/abc.py's own
note — Del Monte rows carry a category_path here, not a SKU code
(DEC-03). Reads the LATEST classification_period per (principal, sku)
by default (a re-run of analytics/classification/orchestrate_abc.py
upserts rather than appending, so in practice there is only ever one
row per product_key+period, but "latest period across all products
present" is still an explicit MAX(), not an assumption that every
product shares one global period).

tier_summary (backlog #44) is computed here rather than trusted from
individual rows, so it can never silently drift from what `items`
actually contains.

Fixed 2026-08: stock_status was previously `random.choices(...)` — a
placeholder that re-rolled a fake status on every request instead of
reading real inventory. Replaced with the same real, deterministic rule
GET /inventory already uses (backend/routers/inventory.py), extended to
prefer each SKU's actual reorder point (from the latest pending
LP_Recommendation — same source SKUManagement/ReorderRecommendations
read) over the flat 100-unit fallback when one exists.

Fixed 2026-08 (again): current_stock used to COALESCE a missing
Inventory_Fact_Real row to 0, which _stock_status then read as
CRITICAL — but "no inventory record for this product_key" and
"confirmed zero stock" are different facts. Inventory_Fact_Real is a
partial load as of 2025-12 (~509 of ~1,628 ABC-classified products have
a row at all; more coverage expected, per Yuan), so most products
legitimately have no match here yet. current_stock is now left NULL
when there's no match, and stock_status reports "NO DATA" instead of
silently fabricating CRITICAL.

BOTH PRINCIPALS (2026-09-17): `?principal=` is back (see
backend/principals.py) after the 2026-09 Unilever-only period — Del Monte
is in scope again. Omit it (or pass 'all') for both. The latest-period
lookup is filtered by the SAME principal as the row query on purpose:
ABC_Classification carries both principals, so an unfiltered
MAX(classification_period) can resolve to a period the selected principal
has no rows for at all, rendering an empty page that looks like a bug.

NOTE (updated 2026-09-21): Del Monte HAS abc_classification rows again —
run_id 'dm_category_2026-09-21_v1', 673 'single' rows for 2023-01..2025-12,
category grain (DEC-03). Those products have no sku_code (and 59 of the 85
have no product_name), which is why sku_id must fall back to
category_path: with a '' fallback every Del Monte row shared one empty
sku_id, and the ABC page, which keyed its rows on it, collided on all 85.
product_key is returned as well so the frontend has a key that is unique
by construction. Open question for the data side, NOT resolved here: that
run ranks ~63 sub-categories per month in 2023-24 but only 4-5 top-level
categories in 2025, so view=last_known mixes the two grains for Del Monte.

METHOD FILTER (migration 0017): abc_classification's natural key widened
to (product_key, classification_period, method), and a 't3m' run is now
live alongside 'single' (25,437 + 23,223 rows). Every read here MUST pin
method='single' or each SKU comes back twice and revenue_share sums to
~200%.

The method fix here was also made independently upstream in e6a7a13
(same five sites, same verified 0.9986-vs-1.9973 evidence); this version
supersedes it only by ALSO pinning method in the MAX(classification_period)
lookups, which that commit left unfiltered.

LAST-KNOWN VIEW (2026-09-21, ?view=last_known): the default view lists
only the SKUs ranked in ONE period — 710 of Unilever's 2,098 for 2026-02 —
because ABC ranks by that month's revenue and a SKU with no sales that
month is simply absent. GET /sku already switched to each product's most
recent tier (1,531 carry one), so the two pages disagreed about the same
SKUs. last_known uses the same rule as GET /sku: DISTINCT ON product_key,
newest 'single' run at or before the anchor. Each item carries
tier_period so a carried-forward tier is always labelled with its age.
What is NOT merged across periods: revenue_share / cumulative_share /
boundary_flag are per-run facts, so tier_summary.revenue_share_total sums
current-run rows only. The default view is unchanged, so existing callers
and tests see exactly what they did before.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.principals import (
    PrincipalQuery,
    latest_abc_period,
    latest_inventory_period,
    principal_clause,
)
from backend.schemas.abc import ABCItem, ABCResponse, TierSummary

router = APIRouter(prefix="/abc", tags=["abc"])


def _stock_status(current_stock: float | None, reorder_point: float | None) -> str:
    """Real, deterministic stock status — no simulation, no fabricated
    zero. Mirrors GET /inventory's rule (current_stock > 100 -> IN STOCK,
    > 0 -> LOW, else CRITICAL), but uses the SKU's own reorder_point as
    the LOW/IN STOCK cutoff instead of the flat 100-unit default whenever
    a pending LP_Recommendation exists for it — a real per-SKU threshold,
    not a guess. current_stock=None means Inventory_Fact_Real simply has
    no row for this product yet (partial load) — reported as its own
    "NO DATA" status, never coerced into CRITICAL.
    """
    if current_stock is None:
        return "NO DATA"
    if current_stock <= 0:
        return "CRITICAL"
    if reorder_point is not None:
        return "IN STOCK" if current_stock > reorder_point else "LOW"
    return "IN STOCK" if current_stock > 100 else "LOW"


@router.get("", response_model=ABCResponse)
def get_abc(
    classification_period: str | None = Query(
        None,
        description="'YYYY-MM'. Resolves to the latest classified period at or before it, per principal; "
        "omit for the latest period present.",
    ),
    principal: str | None = PrincipalQuery,
    view: Literal["period", "last_known"] = Query(
        "period",
        description="'period' (default): only SKUs ranked in that run. "
        "'last_known': every product's most recent tier at or before it, with tier_period.",
    ),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> ABCResponse:
    if view == "last_known":
        return _get_abc_last_known(db, classification_period, principal)

    # The row query reads under the same principal scope the period is
    # resolved under — resolving the latest period under a different scope
    # than the rows are read under is exactly how an empty page gets
    # rendered for a principal that does have data.
    _, scope_params = principal_clause(principal, "principal")

    # The page always sends a month, and each principal has its own latest
    # run (Del Monte's is 2025-12 while Unilever's is 2026-02). An exact
    # match on the requested month therefore returned nothing for Del Monte
    # at 2026-02. Resolve to the latest classified period AT OR BEFORE the
    # request instead — the same helper view=last_known already uses; with
    # no month given it is the plain latest period, as before.
    period = latest_abc_period(db, principal, at_or_before=classification_period)
    if period is None:
        return ABCResponse(items=[], count=0, classification_period=None, tier_summary=[])

    query = """
        SELECT
            ac.product_key,
            COALESCE(pd.sku_code, pd.category_path, '') AS sku_id,
            pd.product_name,
            ac.principal,
            ac.tier,
            ac.revenue_share,
            ac.cumulative_share,
            ac.boundary_flag,
            inv.current_stock AS current_stock,
            rop.rop_i AS reorder_point
        FROM abc_classification ac
        JOIN product_dimension pd ON pd.product_key = ac.product_key
        LEFT JOIN (
            SELECT product_key, SUM(quantity_on_hand) AS current_stock
            FROM inventory_fact_real
            WHERE _period = :inv_period
            GROUP BY product_key
        ) inv ON inv.product_key = ac.product_key
        LEFT JOIN (
            SELECT DISTINCT ON (product_key) product_key, rop_i
            FROM lp_recommendation
            WHERE status = 'pending'
            ORDER BY product_key, planning_cycle_date DESC
        ) rop ON rop.product_key = ac.product_key
        WHERE ac.classification_period = :period AND ac.method = 'single'
    """
    query += principal_clause(principal, "ac.principal")[0]
    query += " ORDER BY ac.tier, ac.revenue_share DESC NULLS LAST"

    params: dict = {
        "period": period,
        "inv_period": latest_inventory_period(db, principal),
        **scope_params,
    }

    rows = db.execute(text(query), params).mappings().all()
    items = [
        ABCItem(
            product_key=r["product_key"],
            sku_id=r["sku_id"] or "",
            product_name=r["product_name"],
            principal=r["principal"],
            tier=r["tier"],
            tier_period=period,
            revenue_share=r["revenue_share"],
            cumulative_share=r["cumulative_share"],
            boundary_flag=bool(r["boundary_flag"]),
            current_stock=float(r["current_stock"]) if r["current_stock"] is not None else None,
            stock_status=_stock_status(
                float(r["current_stock"]) if r["current_stock"] is not None else None,
                float(r["reorder_point"]) if r["reorder_point"] is not None else None,
            ),
        )
        for r in rows
    ]

    tier_summary: dict[str, TierSummary] = {}
    for item in items:
        entry = tier_summary.setdefault(item.tier, TierSummary(tier=item.tier, sku_count=0, revenue_share_total=0.0))
        entry.sku_count += 1
        entry.revenue_share_total += item.revenue_share or 0.0

    return ABCResponse(
        items=items,
        count=len(items),
        classification_period=period,
        tier_summary=sorted(tier_summary.values(), key=lambda t: t.tier),
    )


def _get_abc_last_known(
    db: Session, classification_period: str | None, principal: str | None
) -> ABCResponse:
    """view=last_known — every product's most recent 'single' tier at or
    before the anchor period, the same rule GET /sku uses.

    The anchor is the newest run AT OR BEFORE the requested month (not an
    exact match), so a month past the latest run — the ABC page seeds from
    the dashboard's end month, which routinely runs ahead of it — lands on
    the nearest real run instead of an empty page. It stays an upper bound:
    no tier from a later run can appear.
    """
    period = latest_abc_period(db, principal, at_or_before=classification_period)

    pd_scope_sql, pd_scope_params = principal_clause(principal, "pd.principal")
    # Never-ranked products: counted, not listed. Listing them would add
    # Del Monte's ~15k tierless rows to a page about tiers; the count is what
    # tells the reader how much of the product master ABC does not cover.
    unclassified_sql = (
        "SELECT COUNT(*) AS n FROM product_dimension pd WHERE NOT EXISTS ("
        " SELECT 1 FROM abc_classification a WHERE a.product_key = pd.product_key"
        " AND a.method = 'single'"
        " AND (CAST(:period AS TEXT) IS NULL OR a.classification_period <= CAST(:period AS TEXT)))"
        + pd_scope_sql
    )
    unclassified = db.execute(
        text(unclassified_sql), {"period": period, **pd_scope_params}
    ).mappings().first()
    unclassified_count = int(unclassified["n"]) if unclassified else 0

    if period is None:
        return ABCResponse(
            items=[], count=0, classification_period=None, tier_summary=[],
            unclassified_count=unclassified_count,
        )

    ac_scope_sql, ac_scope_params = principal_clause(principal, "principal")
    # method='single' inside the DISTINCT ON is what keeps this one row per
    # product_key (migration 0017) — see the module docstring.
    query = f"""
        WITH latest AS (
            SELECT DISTINCT ON (product_key)
                   product_key, principal, tier, revenue_share,
                   cumulative_share, boundary_flag, classification_period
            FROM abc_classification
            WHERE method = 'single' AND classification_period <= :period{ac_scope_sql}
            ORDER BY product_key, classification_period DESC
        )
        SELECT
            ac.product_key,
            COALESCE(pd.sku_code, pd.category_path, '') AS sku_id,
            pd.product_name,
            ac.principal,
            ac.tier,
            ac.classification_period AS tier_period,
            ac.revenue_share,
            ac.cumulative_share,
            ac.boundary_flag,
            inv.current_stock AS current_stock,
            rop.rop_i AS reorder_point
        FROM latest ac
        JOIN product_dimension pd ON pd.product_key = ac.product_key
        LEFT JOIN (
            SELECT product_key, SUM(quantity_on_hand) AS current_stock
            FROM inventory_fact_real
            WHERE _period = :inv_period
            GROUP BY product_key
        ) inv ON inv.product_key = ac.product_key
        LEFT JOIN (
            SELECT DISTINCT ON (product_key) product_key, rop_i
            FROM lp_recommendation
            WHERE status = 'pending'
            ORDER BY product_key, planning_cycle_date DESC
        ) rop ON rop.product_key = ac.product_key
        ORDER BY ac.tier,
                 (ac.classification_period = :period) DESC,
                 ac.classification_period DESC,
                 ac.revenue_share DESC NULLS LAST
    """
    params: dict = {
        "period": period,
        "inv_period": latest_inventory_period(db, principal),
        **ac_scope_params,
    }
    rows = db.execute(text(query), params).mappings().all()

    items = [
        ABCItem(
            product_key=r["product_key"],
            sku_id=r["sku_id"] or "",
            product_name=r["product_name"],
            principal=r["principal"],
            tier=r["tier"],
            tier_period=r["tier_period"],
            revenue_share=r["revenue_share"],
            cumulative_share=r["cumulative_share"],
            boundary_flag=bool(r["boundary_flag"]),
            current_stock=float(r["current_stock"]) if r["current_stock"] is not None else None,
            stock_status=_stock_status(
                float(r["current_stock"]) if r["current_stock"] is not None else None,
                float(r["reorder_point"]) if r["reorder_point"] is not None else None,
            ),
        )
        for r in rows
    ]

    tier_summary: dict[str, TierSummary] = {}
    for item in items:
        entry = tier_summary.setdefault(item.tier, TierSummary(tier=item.tier, sku_count=0, revenue_share_total=0.0))
        entry.sku_count += 1
        if item.tier_period == period:
            entry.revenue_share_total += item.revenue_share or 0.0
        else:
            entry.carried_forward_count += 1

    return ABCResponse(
        items=items,
        count=len(items),
        classification_period=period,
        tier_summary=sorted(tier_summary.values(), key=lambda t: t.tier),
        unclassified_count=unclassified_count,
    )
