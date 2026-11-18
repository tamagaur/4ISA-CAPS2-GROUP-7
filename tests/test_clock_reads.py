"""Every place the backend reads the wall clock for a DATE, and why each is safe near a Philippine-time month boundary.

SSM is in Philippine time (UTC+8, no daylight saving); Render runs UTC and Supabase's session time zone is UTC (read on live
2026-11-18: SHOW timezone = UTC; no timestamp-without-time-zone column in public). Between 16:00 and 24:00 UTC the Philippine
calendar date is already the next one. The system never asks the clock what "this month" is: the latest month, the planning
cycle, the loaded month and every range come from the data (backend/routers/dashboard._latest_sales_period, lp_cycle, the batch's
expected_month). This test fails when a NEW reader of the date clock appears, so a month that shifts with the hour cannot enter
unnoticed: add the new reader to ALLOWED with the reason it is safe, or use the data.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLOCK = re.compile(
    r"date\.today\(\)|utcnow\(\)|datetime\.(?:datetime\.)?(?:now|today)\((?!\s*(?:datetime\.)?timezone\.utc\))|now\([^)]*\)\.date"
    r"|Timestamp\.(?:now|today)|localtime\(|CURRENT_DATE|CURRENT_TIMESTAMP\s*::\s*date|now\(\)\s*::\s*date|::date\s*\+"
    r"|date_trunc\('[a-z]+',\s*now\(\)|EXTRACT\([^)]*now\(\)", re.IGNORECASE)

# (file, the text of the match) -> why it cannot move a figure or a period.
ALLOWED = {
    ("backend/routers/dashboard.py", "date.today()"):
        "_resolve_sales_anchor's last resort, reached only when no sales exist anywhere: a range anchor, never a figure.",
    ("backend/routers/inventory.py", "CURRENT_DATE"):
        "'overdue' expected receipts: a count of days, in UTC like expected_on itself (computed from decided_at::date in UTC); "
        "up to 8 hours a day the Philippine date is one ahead. Live holds no expected receipt (0 rows, 2026-11-02).",
    ("backend/expected_receipts.py", "::date +"):
        "expected_on = the order's UTC date + lead days: a day early against the Philippine calendar for an order accepted "
        "00:00-08:00 there. Inside the month-load closure (docs/MONTH_LOAD_REHEARSAL.json), so not edited.",
    ("backend/routers/recommendations.py", "utcnow()"):
        "decided_at as a naive UTC value into a timestamptz column: right while the session time zone is UTC (live: UTC). "
        "Inside the month-load closure, so not edited; the other writers use an aware UTC time.",
}


def test_no_new_reader_of_the_date_clock_in_the_backend():
    found = {}
    for path in sorted((REPO / "backend").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        for match in CLOCK.finditer(path.read_text(encoding="utf-8")):
            key = (rel, match.group(0))
            found[key] = found.get(key, 0) + 1
    # A second reader of an allowed kind in the same file is a new reader: each reason covers exactly one.
    more = sorted(k for k, n in found.items() if k in ALLOWED and n > 1)
    assert not more, f"a further reader of an allowed kind in the same file: {more}"
    unknown = sorted(set(found) - set(ALLOWED))
    assert not unknown, ("a new reader of the date clock: decide whether it can shift near a Philippine-time month boundary, "
                         f"then add it to ALLOWED with the reason: {unknown}")
    stale = sorted(set(ALLOWED) - set(found))
    assert not stale, f"ALLOWED lists a reader that is gone: {stale}"


def test_decision_timestamps_are_timezone_aware():
    """The decision, approval and request writers send an aware UTC time, so the stored instant does not depend on the
    database session's time zone (a local copy created on a Philippine machine would otherwise read 8 hours off)."""
    for name in ("reorder_approval.py", "reorder_requests.py"):
        source = (REPO / "backend" / "routers" / name).read_text(encoding="utf-8")
        assert "utcnow()" not in source, name
