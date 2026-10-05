"""
backend.data_notes — reviewed notes on source data the app shows as loaded
but should not lean on.

UNUSUAL_STOCK_SNAPSHOTS lists stock-on-hand snapshots the team has looked at
and judged unusual: an outlier count, or a count with a warehouse missing.
It is a short reviewed list on purpose, not a statistical rule. A rule loose
enough to catch Unilever's Feb 2026 count also flags months that really
happened — Unilever's Jul 2024 restock (₱27.9M after ₱8.9M) and Del Monte's
Dec 2023 Christmas stock (₱17.7M against about ₱8M either side) — and
calling a real restock an error would be worse than the problem it fixes.

What the Dashboard does with a flagged snapshot (backend/routers/dashboard.py,
backend/chart_insights.py): the point stays on the chart, marked, with the
reason in its tooltip — the data is not deleted or smoothed — but it is never
used as the month a change is measured against ("−51.3% vs Feb 2026" compared
Mar 2026 with the outlier), nor as "the" stock figure a sentence quotes.

Add an entry only after the team has reviewed the month, and write the reason
for a planner, with the figures that make it unusual. Figures checked against
Inventory_Fact_Real on 2026-10-01.
"""
from __future__ import annotations

UNUSUAL_STOCK_SNAPSHOTS: dict[tuple[str, str], str] = {
    ("unilever", "2026-02"): (
        "About twice the stock counted the month before and after (₱46.6M vs ₱24.3M and ₱22.7M); "
        "accepted for planning, pending SSM confirmation (decided 2026-10-03)."
    ),
    ("delmonte", "2023-02"): (
        "Ilocos warehouse only — Pangasinan's count is missing (200 rows, ₱2.5M vs about ₱8.7M "
        "other months)."
    ),
}

# How the order plan treats a reviewed count when it is the count that OPENS a
# planning month (backend/stock_units.stock_count_info, scripts/run_lp.py):
#   ("use", label)      plan from it; the label goes with the plan (lp_run,
#                       GET /recommendations) in place of the note above
#   ("missing", note)   refuse the plan as if no count existed; never fall
#                       back to another month's count
# A flagged count with no ruling here is used, carrying its note above. Add a
# ruling only on the team's decision, naming who made it and when.
OPENING_COUNT_RULINGS: dict[tuple[str, str], tuple[str, str]] = {
    # Decided 2026-10-03 (Yuan): plan March 2026 from the count of 2 March
    # 2026. Receipts records that would confirm or rule out a February
    # forward buy don't exist (reports/diagnostics/lp_logic_check_2026-10-03
    # section 5), so the count stands until SSM confirms it.
    ("unilever", "2026-02"): ("use", "accepted for planning, pending SSM confirmation (decided 2026-10-03)"),
}

# Caveats every plan for a principal carries (scripts/run_lp.py records them
# in lp_run.inputs.notes). Recorded 2026-10-03 (Yuan).
PLANNING_NOTES: dict[str, str] = {
    "unilever": ("stock counts are from the Ilocos Sur warehouse workbook; per-product sales are "
                 "La Union only - territory match unverified."),
}


def opening_count_ruling(principal: str, period: str) -> tuple[str, str] | None:
    """OPENING_COUNT_RULINGS' entry for this count, or None."""
    ruling = OPENING_COUNT_RULINGS.get((principal, period))
    if ruling is not None and ruling[0] not in ("use", "missing"):
        raise ValueError(f"OPENING_COUNT_RULINGS[{(principal, period)!r}] must be 'use' or 'missing', got {ruling[0]!r}")
    return ruling


# Weeks of cover divides one principal's stock by its sales; where the two come from
# different places the figure carries this caveat (GET /dashboard kpis.weeks_of_cover.caveat,
# Yuan 2026-10-04). Same fact as PLANNING_NOTES, in the card's words.
COVER_CAVEATS: dict[str, str] = {
    "unilever": "stock = Ilocos Sur warehouse; sales = La Union only; territory match unverified",
}

_PRINCIPAL_NAMES = {"unilever": "Unilever", "delmonte": "Del Monte"}


def _compact_pesos(value: float) -> str:
    """₱46.6M / ₱812.3K / ₱950 — the dashboard's compact peso format."""
    if abs(value) >= 1_000_000:
        return f"₱{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"₱{value / 1_000:.1f}K"
    return f"₱{value:,.0f}"


def flagged_count_note(principal: str, period: str, value: float | None, neighbours: list[float],
                       counted_on: str | None) -> str | None:
    """The stock card's note when the count it shows is in UNUSUAL_STOCK_SNAPSHOTS (Yuan,
    2026-10-04): "Counted 2 Mar 2026: unusually high (₱46.6M), accepted pending SSM
    confirmation" for a count the team accepted (OPENING_COUNT_RULINGS 'use'); a flagged
    count without that ruling gives its reviewed reason instead. High or low against the
    mean of the counts either side (`neighbours`). None when the count is not flagged."""
    reason = UNUSUAL_STOCK_SNAPSHOTS.get((principal, period))
    if reason is None:
        return None
    if counted_on:
        year, month, day = (int(x) for x in counted_on[:10].split("-"))
        when = f"Counted {day} {_MONTH_ABBR[month - 1]} {year}"
    else:
        year, month = int(period[:4]), int(period[5:7])
        when = f"Counted for {_MONTH_ABBR[month - 1]} {year} (exact date not recorded)"
    ruling = opening_count_ruling(principal, period)
    if ruling is not None and ruling[0] == "use" and value is not None and neighbours:
        level = sum(neighbours) / len(neighbours)
        direction = "high" if value > level else "low"
        return f"{when}: unusually {direction} ({_compact_pesos(value)}), accepted pending SSM confirmation"
    return f"{when}: {reason}"


_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def unusual_stock_snapshots(principal: str, periods) -> dict[str, str]:
    """{period: reason} for the flagged snapshots among `periods`.

    `principal` is 'unilever', 'delmonte' or 'all'. Under 'all' each
    principal's flags apply to its own contribution: a combined month is the
    sum of both principals' counts, so it carries a flagged contributor's
    problem with it, and the reason names whose count it is. (The combined
    series only has months where both principals have a count —
    _combine_principal_sums — so a flag here can name a month the 'all'
    series leaves empty; callers mark only points that exist.)"""
    wanted = set(periods)
    owners = ("unilever", "delmonte") if principal == "all" else (principal,)
    flags: dict[str, str] = {}
    for owner in owners:
        for (who, period), reason in UNUSUAL_STOCK_SNAPSHOTS.items():
            if who != owner or period not in wanted:
                continue
            text = f"{_PRINCIPAL_NAMES.get(who, who)}: {reason}" if principal == "all" else reason
            flags[period] = f"{flags[period]} {text}" if period in flags else text
    return flags
