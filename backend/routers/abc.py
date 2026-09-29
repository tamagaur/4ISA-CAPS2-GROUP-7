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

PREVIEW (2026-09-23, X-Data-Mode: preview, backend/data_mode.py): no stored
run covers Unilever's 2021-22 placeholder months, so for those months the
tiers are computed on request with the ABC run's own steps and never
written. A month in the window resolves to that month's computed run;
last_known also sees each product's newest placeholder tier, so a product
whose only tiers are placeholder ones is listed, labelled by its
tier_period. A month a stored run covers reads the stored run, unchanged.
Stock and reorder points stay real — there is no placeholder stock.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.data_mode import (
    PREVIEW,
    REAL,
    abc_relation,
    abc_single,
    get_data_mode,
    latest_per_product,
    placeholder_months,
    lp_source,
    placeholder_window,
    preview_block,
)
from backend.deps import TokenPayload, get_current_user, get_db
from backend.lp_cycle import current_cycle
from backend.principals import (
    PrincipalQuery,
    latest_abc_period,
    normalize_principal,
    principal_clause,
)
from backend.stock_units import STOCK_AT_LATEST_SQL
from analytics.classification.abc import abc_rules, pareto_check
from backend.schemas.abc import ABCItem, ABCResponse, ABCRules, ParetoCheck, TierSummary

router = APIRouter(prefix="/abc", tags=["abc"])


def _summarize(items: list[ABCItem], period: str | None) -> tuple[list[TierSummary], ParetoCheck | None]:
    """tier_summary plus the run's Pareto check (manuscript §3.4.4.2.2).
    Only CURRENT-run rows feed shares: a carried-forward row's revenue_share
    is a fraction of another month's revenue. The check needs one principal —
    two principals' shares are fractions of two different totals."""
    summary: dict[str, TierSummary] = {}
    current = [i for i in items if i.tier_period == period]
    for item in items:
        entry = summary.setdefault(item.tier, TierSummary(tier=item.tier, sku_count=0, revenue_share_total=0.0))
        entry.sku_count += 1
        if item.tier_period == period:
            entry.revenue_share_total += item.revenue_share or 0.0
        else:
            entry.carried_forward_count += 1
    one_principal = len({i.principal for i in current}) == 1
    for entry in summary.values():
        ranked_here = entry.sku_count - entry.carried_forward_count
        entry.sku_share = round(ranked_here / len(current), 6) if current and one_principal else None
    # Cumulative shares go along so the check reads the top items' share off
    # one stored running total instead of summing ~140 separately rounded
    # shares (see pareto_check).
    check = (
        pareto_check([i.revenue_share for i in current], [i.cumulative_share for i in current])
        if one_principal else None
    )
    return sorted(summary.values(), key=lambda t: t.tier), (ParetoCheck(**check) if check else None)


def _stock_status(stock_pieces: float | None, reorder_point: float | None) -> str:
    """Cover against the SKU's own reorder point, both in PIECES
    (backend/stock_units.py). Until 2026-09-29 this compared stock in CASES
    with rop_i in pieces, called a SKU with loose pieces but no full case
    out of stock, and judged every SKU without a reorder point against a
    flat 100 — so no Class A SKU could ever read as above its reorder point.

    NO DATA: no stock record at the latest snapshot (or no usable pack size
    to express it in pieces). CRITICAL: no stock at all. NO ROP: stock on
    hand but no reorder point to judge it by — the LP's current cycle plans
    Category A only, so most B and C products land here rather than in a
    comparison against an invented threshold.
    """
    if stock_pieces is None:
        return "NO DATA"
    if stock_pieces <= 0:
        return "CRITICAL"
    if reorder_point is None:
        return "NO ROP"
    return "IN STOCK" if stock_pieces > reorder_point else "LOW"


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
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> ABCResponse:
    # The placeholder is Unilever's, so a Del Monte-only request has nothing
    # to add and reads exactly as in real mode.
    window = (
        placeholder_window(db)
        if mode == PREVIEW and normalize_principal(principal) in (None, "unilever")
        else None
    )
    if view == "last_known":
        return _with_data_mode(_get_abc_last_known(db, classification_period, principal, window, mode), db, mode)
    return _with_data_mode(_get_abc_period(db, classification_period, principal, window, mode), db, mode)


def _with_data_mode(response: ABCResponse, db: Session, mode: str):
    """Real mode returns the model untouched. Preview adds the data_mode
    block beside it, so a preview payload says so and a real one is
    unchanged."""
    if mode != PREVIEW:
        return response
    return JSONResponse({**jsonable_encoder(response), "data_mode": preview_block(db)})


def _get_abc_period(
    db: Session, classification_period: str | None, principal: str | None, window: dict | None = None,
    mode: str = REAL,
) -> ABCResponse:
    """view=period — the SKUs ranked in one run."""
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
    abc_source, source_params = "abc_classification", {}
    # Preview: no stored run at or before a placeholder month, so that
    # month's run is computed now (backend/data_mode.abc_single).
    if period is None and window and classification_period and classification_period >= window["start"]:
        month = min(classification_period, window["end"])
        computed = abc_single(db, [month], PREVIEW)
        if not computed.empty:
            period = month
            abc_source, source_params = abc_relation(computed, with_stored=False)
    if period is None:
        return ABCResponse(items=[], count=0, classification_period=None, tier_summary=[], rules=ABCRules(**abc_rules()))
    # The reorder point each row's stock status is judged against: the LP's
    # own, or in preview with built outputs the five-year what-if's.
    lp_src, lp_params = lp_source(mode, "lp_recommendation")

    query = f"""
        SELECT
            ac.product_key,
            COALESCE(pd.sku_code, pd.category_path, '') AS sku_id,
            pd.product_name,
            ac.principal,
            ac.tier,
            ac.revenue_share,
            ac.cumulative_share,
            ac.boundary_flag,
            inv.stock_pieces AS current_stock,
            rop.rop_i AS reorder_point
        FROM {abc_source} ac
        JOIN product_dimension pd ON pd.product_key = ac.product_key
        LEFT JOIN ({STOCK_AT_LATEST_SQL}) inv ON inv.product_key = ac.product_key
        LEFT JOIN (
            SELECT product_key, rop_i
            FROM {lp_src}
            WHERE status = 'pending' AND planning_cycle_date = :current_cycle
        ) rop ON rop.product_key = ac.product_key
        WHERE ac.classification_period = :period AND ac.method = 'single'
    """
    query += principal_clause(principal, "ac.principal")[0]
    query += " ORDER BY ac.tier, ac.revenue_share DESC NULLS LAST"

    params: dict = {
        "period": period,
        # The LP's current cycle only, like every other LP read
        # (backend/lp_cycle.py): the newest pending row from ANY cycle let a
        # three-year-old superseded run supply the reorder point.
        "current_cycle": current_cycle(db, principal, mode),
        **scope_params,
        **source_params,
        **lp_params,
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

    tier_summary, check = _summarize(items, period)
    return ABCResponse(
        items=items,
        count=len(items),
        classification_period=period,
        tier_summary=tier_summary,
        rules=ABCRules(**abc_rules()),
        pareto_check=check,
    )


def _get_abc_last_known(
    db: Session, classification_period: str | None, principal: str | None, window: dict | None = None,
    mode: str = REAL,
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
    abc_source, source_params = "abc_classification", {}
    # Preview: every product's newest placeholder tier joins the stored runs.
    # Stored runs are all later than the placeholder, so a product with a
    # stored tier keeps it; the anchor only falls back to a placeholder month
    # when no stored run is at or before the request.
    if window:
        computed = latest_per_product(abc_single(db, placeholder_months(window, classification_period), PREVIEW))
        if not computed.empty:
            abc_source, source_params = abc_relation(computed, with_stored=True)
            if period is None:
                period = computed["classification_period"].max()

    pd_scope_sql, pd_scope_params = principal_clause(principal, "pd.principal")
    # Never-ranked products: counted, not listed. Listing them would add
    # Del Monte's ~15k tierless rows to a page about tiers; the count is what
    # tells the reader how much of the product master ABC does not cover.
    unclassified_sql = (
        "SELECT COUNT(*) AS n FROM product_dimension pd WHERE NOT EXISTS ("
        f" SELECT 1 FROM {abc_source} a WHERE a.product_key = pd.product_key"
        " AND a.method = 'single'"
        " AND (CAST(:period AS TEXT) IS NULL OR a.classification_period <= CAST(:period AS TEXT)))"
        + pd_scope_sql
    )
    unclassified = db.execute(
        text(unclassified_sql), {"period": period, **pd_scope_params, **source_params}
    ).mappings().first()
    unclassified_count = int(unclassified["n"]) if unclassified else 0

    if period is None:
        return ABCResponse(
            items=[], count=0, classification_period=None, tier_summary=[], rules=ABCRules(**abc_rules()),
            unclassified_count=unclassified_count,
        )

    ac_scope_sql, ac_scope_params = principal_clause(principal, "principal")
    lp_src, lp_params = lp_source(mode, "lp_recommendation")
    # method='single' inside the DISTINCT ON is what keeps this one row per
    # product_key (migration 0017) — see the module docstring.
    query = f"""
        WITH latest AS (
            SELECT DISTINCT ON (product_key)
                   product_key, principal, tier, revenue_share,
                   cumulative_share, boundary_flag, classification_period
            FROM {abc_source}
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
            inv.stock_pieces AS current_stock,
            rop.rop_i AS reorder_point
        FROM latest ac
        JOIN product_dimension pd ON pd.product_key = ac.product_key
        LEFT JOIN ({STOCK_AT_LATEST_SQL}) inv ON inv.product_key = ac.product_key
        LEFT JOIN (
            SELECT product_key, rop_i
            FROM {lp_src}
            WHERE status = 'pending' AND planning_cycle_date = :current_cycle
        ) rop ON rop.product_key = ac.product_key
        ORDER BY ac.tier,
                 (ac.classification_period = :period) DESC,
                 ac.classification_period DESC,
                 ac.revenue_share DESC NULLS LAST
    """
    params: dict = {
        "period": period,
        "current_cycle": current_cycle(db, principal, mode),
        **ac_scope_params,
        **source_params,
        **lp_params,
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

    tier_summary, check = _summarize(items, period)
    return ABCResponse(
        items=items,
        count=len(items),
        classification_period=period,
        tier_summary=tier_summary,
        unclassified_count=unclassified_count,
        rules=ABCRules(**abc_rules()),
        pareto_check=check,
    )
