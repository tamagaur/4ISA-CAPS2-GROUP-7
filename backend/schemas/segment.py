"""
backend.schemas.segment — Pydantic models for GET /segment.

Surfaces the Phase-2 segmentation layer (migration 0018: sku_traits +
sku_segment) for ONE SKU. Every field maps 1:1 onto a real column; the only
derived value is `cv_band`, a display label over the stored `cv` (see
backend/routers/segment.py's CV_BAND_* thresholds), and the raw cv is
always returned beside it so the label never stands in for the number.

`analyzed=False` is a first-class answer, not an error: the segmentation
run covers a specific cohort (as of 2026-09, the 132 Unilever Tier A SKUs
of the 2026-02 single-period ABC run), so most SKUs legitimately have no
row yet. A product that doesn't exist at all is a 404, same as
GET /forecast/{sku_id}.
"""
from __future__ import annotations

from pydantic import BaseModel


class SkuTraits(BaseModel):
    cohort_period: str  # 'YYYY-MM' — the ABC period this cohort was drawn from
    history_months: int  # months with quantity_sold > 0
    first_sale_period: str | None = None
    longest_run: int  # longest unbroken run of selling months
    trend: str  # 'up' | 'down' | 'none' (Mann-Kendall, p < 0.05)
    cv: float | None = None  # coefficient of variation of monthly quantity
    cv_band: str | None = None  # 'low' | 'medium' | 'high' — display band over cv, never a substitute for it
    restart_flag: bool
    stability_group: str  # 'all_38' | 'at_least_30' | 'churn'
    revenue_share_2026_02: float | None = None
    adi: float | None = None  # months since first sale / months with a sale (1.0 = sells every month)
    trend_pvalue: float | None = None  # Mann-Kendall two-sided p, from first sale
    trend_slope: float | None = None  # Theil-Sen slope, units/month, from first sale


class SkuSegmentRow(BaseModel):
    scheme: str  # e.g. 'length_v1'
    abc_method: str  # 'single' | 't3m'
    cohort_period: str
    bin: str
    bin_reason: str  # human-readable, printed verbatim by the UI


class SegmentResponse(BaseModel):
    sku_id: str
    product_name: str | None = None
    principal: str
    analyzed: bool
    not_analyzed_reason: str | None = None
    traits: SkuTraits | None = None
    segments: list[SkuSegmentRow] = []
