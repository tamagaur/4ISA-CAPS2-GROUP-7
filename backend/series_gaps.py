"""
backend.series_gaps — why a month on a chart has no value, in one place.

Every chart-feeding endpoint that returns a monthly series marks each missing
or zero point with a short machine-readable `reason`, and any response that
contains one carries a top-level `gap_note` saying what the codes mean, so a
reader of the response (a person or a session) does not need the repo's docs.

  no_sale                    Unilever. A month with no sales row, between a
                             product's first and last sale: the product sold
                             nothing. Rendered as 0, never as a gap. Evidence
                             (2026-10-15): 4,473 in-span gap-months across 714
                             of 1,807 products; 38.3% of in-span months are
                             gaps in the lowest volume quartile against
                             5.7-9.5% in the other three; gaps come in long
                             runs; no clustering in real time. PROVISIONAL
                             until SSM confirms its sales listing omits
                             zero-sale months.
  blank_capture              A row exists and its quantity is NULL. Not zero:
                             value is null, left out of every analysis.
  outside_product_lifespan   Before the product's first sale or after its
                             last. Value is null: the product was not on sale.
  not_collected              Del Monte. A month in which the principal has no
                             data at all: a collection failure, not a zero.
  category_absent            Del Monte. The category has no row in a month
                             other categories reported. Cause unknown; not
                             read as zero sales.
  returns_exceeded_sales     Unilever (category-trends). The category has
                             sales rows that month, but every one's net
                             amount is <= 0 (returns matched or exceeded
                             sales) — distinct from no_sale, which means no
                             row at all. Revenue shown as 0, same as no_sale,
                             but the cause is different (B4, 2026-10-16).

Demonstration-only reasons (GET /demo/series, behind DM_DEMO_ENABLED; origins
real_copy / interpolated / bridged / backcast are kept strictly apart):
  no_data_recorded_before_2023  backcast: SSM's records begin January 2023;
                             the 2021-2022 months are generated for
                             visualisation only.
  interpolated               between two real months of the same series.
  taxonomy_change_bridge     across the 2024-03..2025-02 taxonomy change:
                             a pre-2025 Del Monte path carried forward from
                             its last real month (extrapolation, by decision).
  no_observation_before_series_start  backcast from 2023-01 for a Del Monte
                             series first seen later (anchor override).

These helpers only shape what a chart receives. They are not read by
build_series, the forecast runner, the LP or any analysis.
"""
from __future__ import annotations

REASON_NO_SALE = "no_sale"
REASON_BLANK_CAPTURE = "blank_capture"
REASON_OUTSIDE_LIFESPAN = "outside_product_lifespan"
REASON_NOT_COLLECTED = "not_collected"
REASON_CATEGORY_ABSENT = "category_absent"
REASON_RETURNS_EXCEEDED_SALES = "returns_exceeded_sales"
REASON_NO_DATA_BEFORE_2023 = "no_data_recorded_before_2023"
REASON_INTERPOLATED = "interpolated"
REASON_BRIDGED = "taxonomy_change_bridge"
REASON_NO_OBSERVATION_BEFORE_START = "no_observation_before_series_start"
REASON_FORWARD_FILLED = "series_gap_forward_filled"

REASON_TEXT: dict[str, str] = {
    REASON_NO_SALE: (
        "Unilever: no sales row between the product's first and last sale means it sold nothing that month. "
        "Shown as 0. Provisional until SSM confirms its sales listing omits zero-sale months."
    ),
    REASON_BLANK_CAPTURE: (
        "A row exists but its quantity was left blank when captured. Not zero: no value is shown or filled in."
    ),
    REASON_OUTSIDE_LIFESPAN: "Before the product's first sale or after its last: it was not on sale. No value.",
    REASON_NOT_COLLECTED: (
        "Del Monte: no category was reported this month (a collection failure). Not zero sales; no value is filled in."
    ),
    REASON_CATEGORY_ABSENT: (
        "Del Monte: this category has no row in a month other categories reported. "
        "Cause unknown; not read as zero sales."
    ),
    REASON_RETURNS_EXCEEDED_SALES: (
        "Unilever: this category has sales rows this month, but returns matched or exceeded sales in every one, "
        "so net revenue is 0. Different from no_sale, which means no row at all."
    ),
    REASON_NO_DATA_BEFORE_2023: (
        "SSM's records begin in January 2023. These months are generated for visualisation only (a flat "
        "back-cast at the series' own level); they are not data and not a result."
    ),
    REASON_INTERPOLATED: "Generated between two real months of the same series, for visualisation only.",
    REASON_BRIDGED: (
        "Del Monte: generated across the 2024-03..2025-02 taxonomy change (the path's last real month carried forward, "
        "extrapolation by decision), for visualisation only."
    ),
    REASON_NO_OBSERVATION_BEFORE_START: (
        "Del Monte: generated before this series' first real observation (a category relabelled in the 2025 "
        "taxonomy), for visualisation only."
    ),
    REASON_FORWARD_FILLED: (
        "Del Monte: this live category's real data stops before the demonstration window ends; generated flat "
        "at its own level from its last real month onward (not a taxonomy change), for visualisation only."
    ),
}


def next_month(period: str) -> str:
    y, m = map(int, period.split("-"))
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def month_range(start: str, end: str) -> list[str]:
    out, p = [], start
    while p <= end:
        out.append(p)
        p = next_month(p)
    return out


def unilever_points(
    by_period: dict[str, float | None], grid_start: str | None = None, grid_end: str | None = None,
) -> list[dict]:
    """One {'period', 'quantity', 'reason'} per month from the earlier of the
    product's first month and `grid_start` to the later of its last month and
    `grid_end`. `by_period` maps each month that HAS a row to its quantity
    (None = the row's quantity is NULL).

      row, quantity present          quantity, reason None
      row, quantity NULL             None, blank_capture
      no row, first sale < m < last  0.0, no_sale
      before first / after last      None, outside_product_lifespan
    """
    if not by_period:
        return []
    first, last = min(by_period), max(by_period)
    start = min(grid_start, first) if grid_start else first
    end = max(grid_end, last) if grid_end else last
    points: list[dict] = []
    for m in month_range(start, end):
        if m in by_period:
            q = by_period[m]
            points.append({"period": m, "quantity": q, "reason": None if q is not None else REASON_BLANK_CAPTURE})
        elif first < m < last:
            points.append({"period": m, "quantity": 0.0, "reason": REASON_NO_SALE})
        else:
            points.append({"period": m, "quantity": None, "reason": REASON_OUTSIDE_LIFESPAN})
    return points


def gap_note(reasons) -> str | None:
    """The top-level note for a response whose points use `reasons`; None when none do."""
    present = set(reasons)  # once: `reasons` is often a generator
    used = [r for r in REASON_TEXT if r in present]
    if not used:
        return None
    return " ".join(f"[{r}] {REASON_TEXT[r]}" for r in used)
