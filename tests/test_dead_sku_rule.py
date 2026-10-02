"""tests/test_dead_sku_rule.py — item 11b: one dead-SKU / non-moving rule,
"no month with qty > 0 in the last 6 CALENDAR months" (Yuan, 2026-09-30),
shared by the forecast runner, the router preview and FSN."""
from __future__ import annotations

from pathlib import Path

from analytics.classification.fsn import classify_fsn, no_sale_in_last_months

REPO = Path(__file__).resolve().parents[1]
MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]


def test_a_returns_month_does_not_cancel_a_sale():
    # +5 then -10 in the tail: the old runner rule (tail(6).sum() <= 0) said dead.
    qty = [9] * 6 + [0, 0, 5, -10, 0, 0]
    assert not no_sale_in_last_months(MONTHS, qty, "2025-12")
    assert classify_fsn(qty, MONTHS)["fsn"] != "N"


def test_only_returns_is_no_sale():
    qty = [9] * 6 + [0, -3, 0, 0, -1, 0]
    assert no_sale_in_last_months(MONTHS, qty, "2025-12")


def test_calendar_months_not_rows():
    # The principal has no rows for 2025-09..2025-11 (a gap). The last 6
    # CALENDAR months (2025-07..2025-12) hold no sale.
    periods = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-12"]
    qty = [5, 5, 5, 5, 5, 5, 0, 0, 0]
    assert no_sale_in_last_months(periods, qty, "2025-12")
    assert classify_fsn(qty, periods)["fsn"] == "N"
    # The old FSN rule read the last 6 OBSERVED months (2025-04..2025-12) and saw sales.


def test_a_series_that_stops_early_is_judged_up_to_the_anchor():
    periods = MONTHS[:6]                     # rows stop at 2025-06
    assert not no_sale_in_last_months(periods, [5] * 6, "2025-06")
    assert no_sale_in_last_months(periods, [5] * 6, "2025-12")


def test_the_runner_and_the_preview_call_the_shared_rule():
    for rel in ("scripts/run_baseline_forecast.py", "scripts/preview_router_synth.py"):
        source = (REPO / rel).read_text(encoding="utf-8")
        assert "no_sale_in_last_months(" in source and "tail(6).sum()" not in source, rel
