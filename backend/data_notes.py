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
        "treated as an outlier (team review, 2026-09-29)."
    ),
    ("delmonte", "2023-02"): (
        "Ilocos warehouse only — Pangasinan's count is missing (200 rows, ₱2.5M vs about ₱8.7M "
        "other months)."
    ),
}

_PRINCIPAL_NAMES = {"unilever": "Unilever", "delmonte": "Del Monte"}


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
