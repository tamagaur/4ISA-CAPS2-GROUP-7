"""
backend.routers.segment — GET /segment?sku=<sku_code>

A SKU's demand pattern, its trend and variability (question D4 of the
analytical mapping, reports/PROJECT_DIAGNOSIS_2026-09-21.md §3), from the
Phase-2 segmentation layer (reports/BINNING_ROUND1_2026-09.md, migration
0018): sku_traits holds the measured facts (history length, Mann-Kendall
trend, coefficient of variation, stability group, restart flag) and
sku_segment holds the bin each scheme put the SKU in, with a human-
readable bin_reason. Both were fully populated (132 rows each) but had no
endpoint, so nothing in the app could show them. This reads them for one
SKU at a time — the SKU Forecast page and the Reorder detail modal each
show one product, so a per-SKU read is the natural grain.

GET /segment/summary, the portfolio rollup behind the dashboard's
Diagnostic card, was removed 2026-09-24 with that card: the analytical
mapping has descriptive, predictive and prescriptive questions only.

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

PREVIEW (2026-09-23, X-Data-Mode: preview, backend/data_mode.py): the same
cohort, with its demand-series traits (history, first sale, run length,
trend, CV, ADI, restart) recomputed over the placeholder start through the
cohort month instead of the run's 2023-01 start, by the same
analytics.segmentation.traits functions, and the bins that depend only on
them rebuilt with orchestrate_segment.SCHEME_BUILDERS. Nothing is written.
stability_group (stability_v1) and revenue_share_2026_02 stay the stored
values: they come from the ABC runs, and stability's groups are defined
against the 38 real periods ('all_38'), so extending them is a method
change, not a display one. The payload's data_mode.real_only says so.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.params import XYZ_CV_HIGH, XYZ_CV_LOW, abc_method
from analytics.segmentation.orchestrate_segment import SCHEME_BUILDERS
from backend.data_mode import (
    PREVIEW,
    demand_matrix,
    get_data_mode,
    placeholder_window,
    preview_block,
    observed_periods,
    series_traits,
)
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import (
    PrincipalQuery,
    principal_clause,
)
from backend.schemas.segment import (
    SegmentResponse,
    SkuSegmentRow,
    SkuTraits,
)
from backend.response_cache import cached

router = APIRouter(prefix="/segment", tags=["segment"])

# sku_traits.cv's bands: the same XYZ cut-offs as the volatility_v1 bins
# (analytics/segmentation/bins.py), from analytics.params.
CV_BAND_MEDIUM = XYZ_CV_LOW  # cv below this -> 'low'
CV_BAND_HIGH = XYZ_CV_HIGH  # cv at or above this -> 'high'


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


# Bins built from the demand series alone, so preview can rebuild them.
# stability_v1 is left out: it reads the ABC runs (see the module docstring).
_SERIES_SCHEMES = ("length_v1", "length_v2", "trend_v1", "volatility_v1", "combined_v1")
_PREVIEW_REAL_ONLY = ["traits.stability_group", "traits.revenue_share_2026_02", "segments.stability_v1"]


def _preview_payload(response, db: Session, window: dict, cohort_period: str, **extra):
    """The response plus the data_mode block naming the traits window, and
    any `extra` fields for that block."""
    block = preview_block(db, real_only=_PREVIEW_REAL_ONLY)
    block["traits_window"] = {"start": window["start"], "end": cohort_period}
    block.update(extra)
    return JSONResponse({**jsonable_encoder(response), "data_mode": block})


@router.get("", response_model=SegmentResponse)
@cached("GET /segment")
def get_segment(
    sku: str = Query(..., description="Product_Dimension.sku_code of the SKU whose demand pattern to read."),
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("forecast.view", "lp.view")),
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
    # The cohort of the Tier A basis in use (DEC-37): runs on other bases are kept
    # in the tables, and unpinned they return each scheme once per basis.
    basis = abc_method(product["principal"])

    traits_row = db.execute(
        text("""
            SELECT cohort_period, history_months, first_sale_period, longest_run, trend, cv,
                   restart_flag, stability_group, revenue_share_2026_02,
                   adi, trend_pvalue, trend_slope
            FROM sku_traits
            WHERE product_key = :product_key AND abc_method = :abc_method
            ORDER BY cohort_period DESC
            LIMIT 1
        """),
        {"product_key": product_key, "abc_method": basis},
    ).mappings().first()

    segment_rows = db.execute(
        text("""
            SELECT scheme, abc_method, cohort_period, bin, bin_reason
            FROM sku_segment
            WHERE product_key = :product_key AND abc_method = :abc_method
              AND cohort_period = (SELECT MAX(cohort_period) FROM sku_segment
                                   WHERE product_key = :product_key AND abc_method = :abc_method)
            ORDER BY scheme, abc_method
        """),
        {"product_key": product_key, "abc_method": basis},
    ).mappings().all()

    # Preview: this cohort member's series traits and series-based bins,
    # recomputed over the placeholder start through its cohort month.
    window = placeholder_window(db) if mode == PREVIEW and traits_row is not None else None
    if window:
        cohort_period = traits_row["cohort_period"]
        matrices, periods = demand_matrix(db, [product_key], window["start"], cohort_period, PREVIEW)
        observed = observed_periods(db, window["start"], cohort_period, PREVIEW)
        traits_row = {**traits_row, **series_traits(matrices[product_key], periods, observed)}
        recomputed = SimpleNamespace(stability_group=traits_row["stability_group"], tier_a_periods=None, **{
            k: traits_row[k] for k in ("history_months", "trend", "trend_pvalue", "trend_slope", "cv")
        })
        segment_rows = [
            {**r, **dict(zip(("bin", "bin_reason"), SCHEME_BUILDERS[r["scheme"]](recomputed)))}
            if r["scheme"] in _SERIES_SCHEMES and r["cohort_period"] == cohort_period else r
            for r in segment_rows
        ]

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
            # migration 0022 columns; .get() so a row shape from before the
            # migration still reads as "not measured" rather than failing.
            adi=_to_float(traits_row.get("adi")),
            trend_pvalue=_to_float(traits_row.get("trend_pvalue")),
            trend_slope=_to_float(traits_row.get("trend_slope")),
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
    response = SegmentResponse(
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
    if window:
        return _preview_payload(response, db, window, traits_row["cohort_period"])
    return response
