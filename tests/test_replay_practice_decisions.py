"""scripts/replay_practice_decisions.py: which decisions are carried over and which are refused, that nothing is applied twice, and that
every write goes through decide_row. The writes themselves need the local database: docs/MONTHLY_BATCH_REVIEW.md lists that run."""
from __future__ import annotations

import ast
import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import replay_practice_decisions as rp

CYCLE = datetime.date(2026, 3, 1)
LOCAL = "postgresql://postgres@127.0.0.1:55432/ssm_local"
PRACTICE = "postgresql://postgres@127.0.0.1:55432/ssm_practice"
LIVE = "postgresql://user:pw@aws-0.pooler.supabase.com:6543/postgres"
WHEN = datetime.datetime(2026, 11, 4, 9, 30)


def _row(key=1, status="pending", q_i=Decimal("120.00"), decided_q_i=None, **over):
    return {"recommendation_key": key, "product_key": 1000 + key, "planning_cycle_date": CYCLE, "q_i": q_i, "status": status,
            "decided_q_i": decided_q_i, "decision_reason": None, "decided_by": None, "decided_at": None, **over}


def _accepted(key=1, decided_q_i=None):
    return _row(key, "accepted", decided_q_i=decided_q_i, decided_by="planner@ssm", decided_at=WHEN, decision_reason="Truck has room" if decided_q_i else None)


def _dismissed(key=1):
    return _row(key, "dismissed", decided_by="admin@ssm", decided_at=WHEN, decision_reason="Stock already on the shelf")


# ---- where it may run -------------------------------------------------------------------------------------------------

def test_it_runs_only_between_two_databases_on_the_throwaway_server():
    assert rp.separate_databases(LOCAL, PRACTICE) is True


@pytest.mark.parametrize("pages,practice", [
    (LIVE, PRACTICE), (LOCAL, LIVE), (PRACTICE, PRACTICE), (LOCAL, LOCAL), (None, PRACTICE), (LOCAL, None), ("", ""),
    ("postgresql://postgres@127.0.0.1:5432/ssm_local", PRACTICE), (LOCAL, "postgresql://postgres@127.0.0.1:5432/ssm_practice"),
    (LOCAL, "postgresql://postgres@127.0.0.1:55432/other"),
])
def test_anywhere_else_it_refuses(pages, practice):
    assert rp.separate_databases(pages, practice) is False


def test_without_a_second_database_there_is_nothing_to_compare(monkeypatch):
    monkeypatch.delenv(rp.PAGES_URL_ENV, raising=False)
    monkeypatch.setenv("SUPABASE_DB_URL", LIVE)
    assert rp.preview_if_separate(CYCLE) is None


def test_the_command_refuses_outside_the_throwaway_server(monkeypatch):
    monkeypatch.setenv(rp.PAGES_URL_ENV, LIVE)
    monkeypatch.setenv("SUPABASE_DB_URL", LIVE)
    monkeypatch.setattr(rp.sys, "argv", ["replay", "--cycle", "2026-03", "--write"])
    assert rp.main() == 2


# ---- what is carried over ---------------------------------------------------------------------------------------------

def test_a_decision_on_the_page_is_carried_over():
    assert rp.plan_replay({1: _accepted()}, {1: _row()}).apply == [1]
    assert rp.plan_replay({1: _dismissed()}, {1: _row()}).apply == [1]


def test_an_adjusted_quantity_is_carried_over():
    plan = rp.plan_replay({1: _accepted(decided_q_i=Decimal("90.00"))}, {1: _row()})
    assert plan.apply == [1]


def test_pending_on_both_sides_stays_pending():
    plan = rp.plan_replay({1: _row()}, {1: _row()})
    assert plan.pending == [1] and not plan.apply and not plan.reverse


def test_running_it_again_applies_nothing():
    """The same decision on both sides: duplicates are impossible, not merely unlikely."""
    plan = rp.plan_replay({1: _accepted(), 2: _dismissed(2)}, {1: _accepted(), 2: _dismissed(2)})
    assert plan.already == [1, 2] and not plan.apply and not plan.reverse


def test_a_decision_reversed_on_the_page_is_reversed_on_the_copy():
    plan = rp.plan_replay({1: _row()}, {1: _accepted()})
    assert plan.reverse == [1] and not plan.apply


def test_a_decision_changed_on_the_page_is_reversed_then_applied():
    plan = rp.plan_replay({1: _dismissed()}, {1: _accepted()})
    assert plan.reverse == [1] and plan.apply == [1]


def test_a_new_quantity_on_the_page_is_reversed_then_applied():
    plan = rp.plan_replay({1: _accepted(decided_q_i=Decimal("90.00"))}, {1: _accepted(decided_q_i=Decimal("80.00"))})
    assert plan.reverse == [1] and plan.apply == [1]


# ---- what is not -----------------------------------------------------------------------------------------------------

def test_a_row_missing_from_the_copy_is_reported_and_left_alone():
    plan = rp.plan_replay({1: _accepted()}, {})
    assert plan.missing == [1] and not plan.apply


@pytest.mark.parametrize("over", [{"q_i": Decimal("121.00")}, {"product_key": 9}, {"planning_cycle_date": datetime.date(2026, 2, 1)}])
def test_a_different_row_behind_the_same_key_is_reported_and_left_alone(over):
    plan = rp.plan_replay({1: _accepted()}, {1: _row(**over)})
    assert plan.mismatched == [1] and not plan.apply and not plan.reverse


def test_a_row_only_on_the_copy_is_reported_and_left_alone():
    plan = rp.plan_replay({}, {7: _row(7)})
    assert plan.only_in_practice == [7] and not plan.apply


def test_a_quantity_stored_differently_is_still_the_same_quantity():
    assert rp.same_row(_row(q_i=Decimal("120.00")), _row(q_i=120.0))
    assert rp.same_decision(_accepted(decided_q_i=Decimal("90.00")), _accepted(decided_q_i=90))


# ---- carrying it out -------------------------------------------------------------------------------------------------

def test_reversals_come_first_so_a_changed_decision_ends_as_the_page_has_it():
    order = []
    plan = rp.Plan(apply=[1], reverse=[1])
    done = rp.apply_plan(plan, {1: _dismissed()}, lambda key: order.append(("reverse", key)), lambda key, row: order.append(("decide", key, row["status"])))
    assert order == [("reverse", 1), ("decide", 1, "dismissed")] and done == {"applied": 1, "reversed": 1, "refused": []}


def test_a_row_refused_is_named_and_the_others_go_on():
    class Refused(Exception):
        detail = "This recommendation was already accepted"

    def decide(key, row):
        if key == 1:
            raise Refused()

    done = rp.apply_plan(rp.Plan(apply=[1, 2]), {1: _accepted(1), 2: _accepted(2)}, lambda key: None, decide)
    assert done["applied"] == 1 and done["refused"] == [{"recommendation_key": 1, "why": "This recommendation was already accepted"}]


def test_a_row_whose_reversal_failed_is_not_decided_over_it():
    decided = []

    def reverse(key):
        raise RuntimeError("no")

    done = rp.apply_plan(rp.Plan(apply=[1], reverse=[1]), {1: _dismissed()}, reverse, lambda key, row: decided.append(key))
    assert decided == [] and done["applied"] == 0 and done["refused"][0]["recommendation_key"] == 1


def test_an_unexpected_error_does_not_leak_its_text():
    def decide(key, row):
        raise RuntimeError("postgresql://u:pw@host/db is down")

    done = rp.apply_plan(rp.Plan(apply=[1]), {1: _accepted()}, lambda key: None, decide)
    assert done["refused"][0]["why"] == "RuntimeError"


def test_a_next_plan_on_the_copy_ends_the_replay(monkeypatch):
    sides = {LOCAL: ({1: _accepted()}, {"actionable_pending": 0}, CYCLE), PRACTICE: ({1: _row()}, {"actionable_pending": 1}, datetime.date(2026, 4, 1))}
    monkeypatch.setattr(rp, "_read_side", lambda url, params: sides[url])
    plan, summary, _ = rp.compare(CYCLE, LOCAL, PRACTICE)
    assert not plan.apply and summary["state"] == "plan_already_written"


def test_the_comparison_reports_the_pages_own_counts(monkeypatch):
    sides = {LOCAL: ({1: _accepted()}, {"actionable_pending": 0, "open_requests": 2}, CYCLE), PRACTICE: ({1: _row()}, {"actionable_pending": 1}, CYCLE)}
    monkeypatch.setattr(rp, "_read_side", lambda url, params: sides[url])
    _, summary, _ = rp.compare(CYCLE, LOCAL, PRACTICE)
    assert summary["to_apply"] == 1 and summary["pages"]["open_requests"] == 2 and summary["state"] == "compared"


def test_nothing_to_do_writes_nothing(monkeypatch):
    sides = {LOCAL: ({1: _accepted()}, {}, CYCLE), PRACTICE: ({1: _accepted()}, {}, CYCLE)}
    monkeypatch.setattr(rp, "_read_side", lambda url, params: sides[url])

    def no_writers(url):
        raise AssertionError("nothing should be written")

    monkeypatch.setattr(rp, "_writers", no_writers)
    summary = rp.replay(CYCLE, LOCAL, PRACTICE)
    assert summary["state"] == "replayed" and summary["applied"] == 0 and summary["already"] == 1


# ---- the existing workflow is the only way in ---------------------------------------------------------------------------

def _source() -> str:
    return Path(rp.__file__).read_text(encoding="utf-8")


def test_there_is_no_sql_write_in_this_file():
    """Every write is decide_row or reverse_decision, so the guards, the receipts and the mart stay in one place."""
    sql_strings = [n.value.upper() for n in ast.walk(ast.parse(_source())) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value != ast.get_docstring(ast.parse(_source()))]
    for word in ("UPDATE LP_RECOMMENDATION", "INSERT INTO", "DELETE FROM", "UPDATE EXPECTED_RECEIPT"):
        assert not [s for s in sql_strings if word in s], word


def test_the_writes_are_the_real_functions():
    source = _source()
    assert "rec.decide_row(" in source and "approval.reverse_decision(" in source


def test_it_keeps_who_when_why_and_how_much():
    body = _source().split("def decide(key: int, row: dict)")[1]
    for field in ('status=row["status"]', 'reason=row["decision_reason"]', 'decided_quantity=_quantity(row["decided_q_i"])',
                  'decided_by=row["decided_by"]', 'decided_at=row["decided_at"]'):
        assert field in body, field
