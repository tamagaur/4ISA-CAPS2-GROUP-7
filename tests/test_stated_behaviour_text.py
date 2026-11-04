"""Text that states what the system does must be true of the code (2026-11-03).

A reviewer found two comments saying the app splits the month's order into weekly purchase orders; no code does. They
were the whole written justification for the 8-business-day window. The API also described MASE as beating "a simple
last-month guess"; its denominator is the one-step naive error over the months before the first test origin
(analytics/forecasting/diagnostic_metrics.naive_scale), not last month's value as a forecast of the test months."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCES = [p for top in ("analytics", "backend", "scripts") for p in (REPO / top).rglob("*.py")
           if "archive" not in p.parts and "__pycache__" not in p.parts]
BACKEND = [p for p in SOURCES if p.relative_to(REPO).parts[0] == "backend"]
FRONTEND = [p for p in (REPO / "frontend" / "src").rglob("*") if p.suffix in (".js", ".jsx")]


def _hits(pattern: str, sources) -> list[str]:
    rx = re.compile(pattern, re.I)
    return [f"{p.relative_to(REPO)}:{i}" for p in sources
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if rx.search(line)]


def test_no_source_claims_the_app_splits_the_order_into_weekly_pos():
    # The wording of the claim, not the word "split": the corrected comments must be able to deny it.
    assert _hits(r"the app splits it|released as weekly", SOURCES) == []


def test_the_review_window_says_weekly_ordering_is_an_assumption():
    for name in ("analytics/optimization/lp.py", "scripts/run_lp.py", "analytics/params.py"):
        text = " ".join((REPO / name).read_text(encoding="utf-8").split())
        assert "neither implements nor verifies" in text, name


def test_no_api_text_calls_the_mase_check_a_last_month_guess():
    assert _hits(r"last-month guess|simple last[- ]month", BACKEND) == []


def test_no_page_calls_the_mase_check_a_last_month_guess():
    assert _hits(r"last-month (guess|estimate)|simple last[- ]month|simply repeating last", FRONTEND) == []


def test_no_page_says_ssm_or_the_app_splits_the_order():
    assert _hits(r"splits? into weekly|splits? (it )?into weekly purchase", FRONTEND) == []


def test_the_policy_card_says_weekly_ordering_is_unverified():
    text = " ".join((REPO / "frontend/src/components/Charts.jsx").read_text(encoding="utf-8").split())
    assert "neither implements nor verifies" in text


def test_the_not_planned_reason_states_the_denominator():
    from backend.routers.recommendations import NOT_PLANNED_REASONS
    assert "month-to-month change" in NOT_PLANNED_REASONS["mase_gate"]
    assert "before the test months" in NOT_PLANNED_REASONS["mase_gate"]
