"""backend.stock_signal - the "possibly stock-limited" label and the MAPE variant that sets those months apart.

APPLIED 2026-11-15 (Kelvin's brief of that date; the recon of 2026-11-13 measured it). The label is now the CANDIDATE RULE
("absent_at_close"): a product-month is possibly stock-limited when the product is MISSING FROM THE COUNT TAKEN AT THE MONTH'S END
(a product absent from a count that was taken reads 0: Unilever's files never list a zero row); unknown when there is no count, or
the count is on record as possibly partial (analytics.params.POSSIBLY_PARTIAL_COUNTS, row flag count_possibly_partial). The stored
column mart.accuracy_mart.possibly_stock_limited (migration 0043/0050; opening or closing count 0, or below 1 week of the product's
12-month average; kelvin/surplus-bias-experiment 3226cc4 Part 0.1, adopted by Yuan 2026-10-04) is NOT changed (no database write):
the rule is applied at read time, and CURRENT_RULE stays selectable.

WHY (scripts/score_stock_limited_rule.py, live, 2026-11-13; Tier A run 21, 4,370 product-months):
  - The old rule fired on 59.6% of product-months (37%-89% a month). Its "below 1 week" branch (1,517 product-months) sold 0.93x
    the product's average against 0.94-0.95x unflagged, and no threshold from 0.1 to 4 weeks separates them: the normal low point
    between weekly deliveries in a monthly snapshot (3226cc4 README Part 0.2). "Absent at the opening count only" (276): 0.93x,
    restocked: no signal.
  - "Absent from the closing count" (811): median sales 0 when absent at both counts, 0.75x and 62% over-forecast when absent at the
    close only: what a stock-out looks like. Tier A: 59.6% -> about 17% of product-months.

MAPE. Chapter 3 (3.4.4.2.2.2) defines MAPE and sets no month apart, so the card's HEADLINE sets none apart. Beside it a VARIANT
leaves out the stock-limited months (MAPE_VARIANT_APART = "closing_count", the same months the label flags). From ae196dc (the
forecastability-gate branch, carried into live by 163b42f) the card's single MAPE had set apart months with a zero opening OR closing
count and called itself "as Chapter 3 defines it": that is gone.
"""
from __future__ import annotations

CURRENT_RULE = "count_or_week"            # the stored column, as mart.refresh wrote it
CANDIDATE_RULE = "absent_at_close"
RULES = (CURRENT_RULE, CANDIDATE_RULE)
RULE = CANDIDATE_RULE                     # the switch: applied 2026-11-15

MAPE_APART_MODES = ("either_count", "closing_count", "none")
MAPE_VARIANT_APART = "closing_count"      # the months the card's stock-limited MAPE variant sets apart (the headline sets none apart)


def _check(value: str, allowed: tuple[str, ...], name: str) -> str:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")
    return value


def candidate_flag(row: dict) -> bool | None:
    """The candidate label for one accuracy_mart row: absent from the closing count (closing_pieces = 0), unknown with no count or a
    possibly partial one."""
    closing = row.get("closing_pieces")
    if closing is None or row.get("count_possibly_partial"):
        return None
    return float(closing) == 0


def apply_to_rows(rows: list[dict], rule: str | None = None) -> list[dict]:
    """The rows as served. Under the stored rule they are returned untouched (the same list)."""
    rule = _check(rule or RULE, RULES, "RULE")
    if rule == CURRENT_RULE:
        return rows
    for r in rows:
        r["possibly_stock_limited"] = candidate_flag(r)
    return rows


def flag_sql(rule: str | None = None) -> str:
    """The SQL for the label inside a query over accuracy_mart's columns: the stored column under the old rule."""
    rule = _check(rule or RULE, RULES, "RULE")
    if rule == CURRENT_RULE:
        return "possibly_stock_limited"
    return "(CASE WHEN closing_pieces IS NULL OR count_possibly_partial THEN NULL ELSE closing_pieces = 0 END)"


def zero_stock_sql(mode: str) -> str:
    """The months a MAPE basis sets apart, as SQL over accuracy_mart's columns."""
    mode = _check(mode, MAPE_APART_MODES, "MAPE_APART")
    return {"either_count": "(opening_pieces = 0 OR closing_pieces = 0)",
            "closing_count": "(closing_pieces = 0 AND NOT COALESCE(count_possibly_partial, false))",
            "none": "false"}[mode]


def zero_stock_row(row: dict, mode: str) -> bool:
    """The same test on one row (backend/marts._stock_limited_month)."""
    mode = _check(mode, MAPE_APART_MODES, "MAPE_APART")
    if mode == "none":
        return False
    keys = ("opening_pieces", "closing_pieces") if mode == "either_count" else ("closing_pieces",)
    if mode == "closing_count" and row.get("count_possibly_partial"):
        return False
    return any(row.get(k) is not None and float(row[k]) == 0 for k in keys)
