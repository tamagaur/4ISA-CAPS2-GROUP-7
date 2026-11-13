"""backend.stock_signal - read-time switches for the "possibly stock-limited" label and for the months MAPE sets apart.

BOTH SWITCHES ARE AT TODAY'S BEHAVIOUR, and with them nothing any route serves changes (built 2026-11-13, recon brief "whether the
stock-limited flag means anything"; not applied: changing either value is the team's decision, not this module's).

WHAT TODAY'S LABEL IS. mart.accuracy_mart.possibly_stock_limited (migration 0043, kept by 0050; kelvin/surplus-bias-experiment
3226cc4 Part 0.1, adopted by Yuan 2026-10-04): the opening or closing count is 0, or below 1 week of the product's 12-month average
sales. A product missing from a count that was taken counts as 0 (Unilever's files never list a zero row), so "count is 0" means
"absent from the count".

WHAT THE RECON MEASURED (scripts/score_stock_limited_rule.py, live, 2026-11-13; Tier A run 21, 4,370 product-months):
  - It fires on 59.6% of product-months (16%-50% "absent" plus a "below 1 week" branch, 37%-89% a month in all).
  - "Below 1 week" (1,517 product-months): those months sell 0.93x the product's average, the unflagged 0.94-0.95x. No threshold
    from 0.1 to 4 weeks separates them (0.85x-0.97x in every band). It is the normal low point between weekly deliveries seen in a
    monthly snapshot, as the experiment that wrote the rule said itself (3226cc4 README Part 0.2), and the yardstick is La Union's
    sales against an Ilocos Sur count.
  - "Absent from the closing count" (811): median sales 0 when absent at both counts, 0.75x and 62% over-forecast when absent at the
    close only. That is what a stock-out looks like. "Absent from the opening count only" (276): 0.93x, restocked; no signal.

THE CANDIDATE RULE ("absent_at_close"): possibly stock-limited = the product is absent from the count taken at the month's end; unknown
when there is no count, or the count is on record as possibly partial (analytics.params.POSSIBLY_PARTIAL_COUNTS, row flag
count_possibly_partial). Tier A: 59.6% -> about 17% of product-months, and the flagged months sell a median 0x-0.75x their average.

MAPE. The card's MAPE (the Chapter 3 measure) sets apart product-months with a zero opening OR closing count (MAPE_APART
"either_count", from ae196dc of 2026-11-12, the forecastability-gate branch, carried to live in 163b42f; no decision on record). That
also sets apart the "absent at the opening only" months, which sold normally. "closing_count" sets apart only the months the candidate
rule flags; "none" sets nothing apart. The scores per window are in the scoring script's output.
"""
from __future__ import annotations

CURRENT_RULE = "count_or_week"            # the stored column, as mart.refresh wrote it
CANDIDATE_RULE = "absent_at_close"
RULES = (CURRENT_RULE, CANDIDATE_RULE)
RULE = CURRENT_RULE                       # the switch: today's behaviour

MAPE_APART_MODES = ("either_count", "closing_count", "none")
MAPE_APART = "either_count"               # the switch: today's behaviour


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
    """The rows as served. Under today's rule they are returned untouched (the same list)."""
    rule = _check(rule or RULE, RULES, "RULE")
    if rule == CURRENT_RULE:
        return rows
    for r in rows:
        r["possibly_stock_limited"] = candidate_flag(r)
    return rows


def flag_sql(rule: str | None = None) -> str:
    """The SQL for the label inside a query over accuracy_mart's columns: the stored column under today's rule."""
    rule = _check(rule or RULE, RULES, "RULE")
    if rule == CURRENT_RULE:
        return "possibly_stock_limited"
    return "(CASE WHEN closing_pieces IS NULL OR count_possibly_partial THEN NULL ELSE closing_pieces = 0 END)"


def zero_stock_sql(mode: str | None = None) -> str:
    """The months MAPE sets apart, as SQL over accuracy_mart's columns (today: a zero opening or closing count)."""
    mode = _check(mode or MAPE_APART, MAPE_APART_MODES, "MAPE_APART")
    return {"either_count": "(opening_pieces = 0 OR closing_pieces = 0)",
            "closing_count": "(closing_pieces = 0 AND NOT COALESCE(count_possibly_partial, false))",
            "none": "false"}[mode]


def zero_stock_row(row: dict, mode: str | None = None) -> bool:
    """The same test on one row (backend/marts._zero_stock)."""
    mode = _check(mode or MAPE_APART, MAPE_APART_MODES, "MAPE_APART")
    if mode == "none":
        return False
    keys = ("opening_pieces", "closing_pieces") if mode == "either_count" else ("closing_pieces",)
    if mode == "closing_count" and row.get("count_possibly_partial"):
        return False
    return any(row.get(k) is not None and float(row[k]) == 0 for k in keys)
