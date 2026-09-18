"""
backend.routers.segment — GET /segment?sku=<sku_code>

The Phase-2 diagnostic layer (reports/BINNING_ROUND1_2026-09.md, migration
0018) is the only "why does this SKU behave this way" content in the
schema: sku_traits holds the measured facts (history length, Mann-Kendall
trend, coefficient of variation, stability group, restart flag) and
sku_segment holds the bin each scheme put the SKU in, with a human-
readable bin_reason. Both were fully populated (132 rows each) but had no
endpoint, so nothing in the app could show them. This reads them for one
SKU at a time — the SKU Forecast page and the Reorder detail modal each
show one product, so a per-SKU read is the natural grain.

Resolution: sku_code -> Product_Dimension, scoped by ?principal= exactly as
GET /forecast/{sku_id} does (sku_code is not unique across principals).
404 only when no product row exists at all. A product with no traits/
segment row returns 200 with analyzed=False and a reason — the cohort is
deliberately narrow (Unilever Tier A, 2026-02), so "not analyzed" is the
common, honest answer, not a failure.

Latest cohort wins: sku_traits is unique on (product_key, cohort_period)
and sku_segment on (product_key, cohort_period, abc_method, scheme). If a
later cohort run lands, this returns that cohort's traits and every scheme
row from that same cohort, never a mix of cohorts.

cv_band is the ONE derived value here. Thresholds are a display
convention for the coefficient of variation of monthly demand (not a
pipeline output): under 0.5 reads as steady, 0.5-1.0 as variable, 1.0 and
above as erratic. The raw cv is returned beside the band so the label
never replaces the number.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.principals import PrincipalQuery, principal_clause
from backend.schemas.segment import (
    SegmentResponse,
    SegmentSummary,
    SkuSegmentRow,
    SkuTraits,
    TrendBucket,
    VolatilityBucket,
)

router = APIRouter(prefix="/segment", tags=["segment"])

CV_BAND_MEDIUM = 0.5  # cv below this -> 'low'
CV_BAND_HIGH = 1.0  # cv at or above this -> 'high'


def cv_band(cv: float | None) -> str | None:
    if cv is None:
        return None
    if cv < CV_BAND_MEDIUM:
        return "low"
    if cv < CV_BAND_HIGH:
        return "medium"
    return "high"


def _to_float(val) -> float | None:
    return None if val is None else float(val)


@router.get("", response_model=SegmentResponse)
def get_segment(
    sku: str = Query(..., description="Product_Dimension.sku_code of the SKU to read diagnostics for."),
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> SegmentResponse:
    scope_sql, scope_params = principal_clause(principal, "principal")
    product = db.execute(
        text(
            "SELECT product_key, product_name, principal FROM product_dimension "
            "WHERE sku_code = :sku" + scope_sql
        ),
        {"sku": sku, **scope_params},
    ).mappings().first()
    if product is None:
        raise HTTPException(status_code=404, detail=f"No product found for '{sku}' ({principal or 'any principal'})")

    product_key = product["product_key"]

    traits_row = db.execute(
        text("""
            SELECT cohort_period, history_months, first_sale_period, longest_run, trend, cv,
                   restart_flag, stability_group, revenue_share_2026_02
            FROM sku_traits
            WHERE product_key = :product_key
            ORDER BY cohort_period DESC
            LIMIT 1
        """),
        {"product_key": product_key},
    ).mappings().first()

    segment_rows = db.execute(
        text("""
            SELECT scheme, abc_method, cohort_period, bin, bin_reason
            FROM sku_segment
            WHERE product_key = :product_key
              AND cohort_period = (SELECT MAX(cohort_period) FROM sku_segment WHERE product_key = :product_key)
            ORDER BY scheme, abc_method
        """),
        {"product_key": product_key},
    ).mappings().all()

    traits = None
    if traits_row is not None:
        cv = _to_float(traits_row["cv"])
        traits = SkuTraits(
            cohort_period=traits_row["cohort_period"],
            history_months=int(traits_row["history_months"]),
            first_sale_period=traits_row["first_sale_period"],
            longest_run=int(traits_row["longest_run"]),
            trend=traits_row["trend"],
            cv=cv,
            cv_band=cv_band(cv),
            restart_flag=bool(traits_row["restart_flag"]),
            stability_group=traits_row["stability_group"],
            revenue_share_2026_02=_to_float(traits_row["revenue_share_2026_02"]),
        )

    segments = [
        SkuSegmentRow(
            scheme=r["scheme"],
            abc_method=r["abc_method"],
            cohort_period=r["cohort_period"],
            bin=r["bin"],
            bin_reason=r["bin_reason"],
        )
        for r in segment_rows
    ]

    analyzed = traits is not None or bool(segments)
    return SegmentResponse(
        sku_id=sku,
        product_name=product["product_name"],
        principal=product["principal"],
        analyzed=analyzed,
        not_analyzed_reason=(
            None if analyzed
            else "This SKU has no row in sku_traits or sku_segment — the segmentation run "
                 "has only covered its cohort (Unilever Tier A as of 2026-02) so far."
        ),
        traits=traits,
        segments=segments,
    )


# Declared BEFORE the "" route would shadow it? No — FastAPI matches the
# literal path first, so order here is for readability only.
@router.get("/summary", response_model=SegmentSummary)
def get_segment_summary(
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> SegmentSummary:
    """Cohort rollup of sku_traits for the dashboard's diagnostic panel.

    Answers "why is this portfolio hard to forecast" at portfolio grain:
    how many SKUs sit in each volatility band and which way their demand
    trends. Both come straight from sku_traits (cv, trend) — the same
    columns GET /segment returns per SKU, so the panel and the per-SKU
    drill-down can never disagree.

    Banding uses this module's cv_band() rather than SQL CASE, so the
    thresholds exist in exactly one place.

    Scoped to the LATEST cohort_period only. Mixing cohorts would sum two
    different runs' populations into one bar. An empty cohort for the
    requested principal returns analyzed_count=0 with a reason, never an
    empty chart that reads as "no volatility".
    """
    scope_sql, scope_params = principal_clause(principal, "st.principal")
    rows = db.execute(
        text(
            """
            SELECT st.cv, st.trend, st.revenue_share_2026_02 AS revenue_share
            FROM sku_traits st
            WHERE st.cohort_period = (
                SELECT MAX(cohort_period) FROM sku_traits st2
                WHERE TRUE
            )
            """
            + scope_sql
        ),
        scope_params,
    ).mappings().all()

    cohort = db.execute(text("SELECT MAX(cohort_period) AS p FROM sku_traits")).scalar()

    if not rows:
        return SegmentSummary(
            cohort_period=cohort,
            analyzed_count=0,
            blocked_reason=(
                "No segmentation rows for this scope — the run covers one cohort "
                f"(Unilever Tier A as of {cohort}) so far."
                if cohort else "The segmentation run has not been executed yet."
            ),
        )

    vol: dict[str, dict] = {}
    for r in rows:
        band = cv_band(_to_float(r["cv"])) or "unknown"
        entry = vol.setdefault(band, {"sku_count": 0, "revenue_share": 0.0, "any_share": False})
        entry["sku_count"] += 1
        share = _to_float(r["revenue_share"])
        if share is not None:
            entry["revenue_share"] += share
            entry["any_share"] = True

    trends: dict[str, int] = {}
    for r in rows:
        trends[r["trend"] or "none"] = trends.get(r["trend"] or "none", 0) + 1

    band_order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    trend_order = {"up": 0, "none": 1, "down": 2}

    return SegmentSummary(
        cohort_period=cohort,
        analyzed_count=len(rows),
        volatility=[
            VolatilityBucket(
                band=b,
                sku_count=v["sku_count"],
                # Left null, not 0.0, when no SKU in the band carried a share —
                # "not recorded" and "0% of revenue" are different facts.
                revenue_share=round(v["revenue_share"], 4) if v["any_share"] else None,
            )
            for b, v in sorted(vol.items(), key=lambda kv: band_order.get(kv[0], 9))
        ],
        trend=[
            TrendBucket(trend=t, sku_count=n)
            for t, n in sorted(trends.items(), key=lambda kv: trend_order.get(kv[0], 9))
        ],
    )
