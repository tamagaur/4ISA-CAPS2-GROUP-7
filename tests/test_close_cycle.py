"""scripts/close_cycle.py: the gate, the state machine, resumption, reopening (migration 0069).
The SQL runs against Postgres in tests/etl/test_rollover_scratch.py (scratch schema)."""
from __future__ import annotations

import datetime
import re
import sys

import pytest

from scripts import close_cycle as cc

CYCLE = datetime.date(2026, 3, 1)
P = cc.cycle_params(CYCLE)
ALL_OK = {k: True for k in cc.CHECKS}


class _Cur:
    def __init__(self, conn):
        self.conn, self.rowcount = conn, 3

    def execute(self, sql, params=None):
        self.conn.sql.append(" ".join(str(sql).split()))


class _Conn:
    def __init__(self):
        self.sql, self.commits, self.rollbacks = [], 0, 0

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def writes(self):
        return [s for s in self.sql if s.split()[0] in ("UPDATE", "INSERT", "DELETE")]


def _status(state=None, steps=(), checks=None, rows=110, closed_rows=0):
    row = None if state is None else {"state": state, "steps_done": list(steps), "closed_by": "Y", "closed_at": "t",
                                      "closing_started_by": "Y", "closing_started_at": "t", "reopened_by": None,
                                      "reopened_at": None, "reopen_count": 0}
    return {"checks": checks or dict(ALL_OK), "cycle_row": row, "ledger_present": True, "rows": rows,
            "closed_rows": closed_rows, "decided_rows": 1}


@pytest.fixture
def settled(monkeypatch):
    calls = []
    monkeypatch.setattr(cc.receipt_settlement, "settle",
                        lambda cur, period, write=False: calls.append((period, write)) or
                        {"settles": 2, "not_visible": 1, "tested": 2, "untested": 0})
    return calls


def _run(monkeypatch, status, fn=cc.close, write=True):
    monkeypatch.setattr(cc, "read_status", lambda cur, params: status)
    conn = _Conn()
    out = []
    result = fn(conn, "public", P, "Yuan", write, out=out.append)
    return conn, result, out


def test_the_next_cycle_and_the_month_come_from_the_cycle():
    assert (P["next_cycle"], P["period"]) == (datetime.date(2026, 4, 1), "2026-03")
    assert cc.cycle_params(datetime.date(2025, 12, 1))["next_cycle"] == datetime.date(2026, 1, 1)


def test_a_dry_run_writes_nothing(monkeypatch, settled):
    conn, result, out = _run(monkeypatch, _status(), write=False)
    assert result["action"] == "dry_run" and conn.writes() == [] and settled == []
    assert any("dry run" in line for line in out)


def test_a_close_refuses_while_the_pipeline_has_not_run_and_writes_nothing(monkeypatch, settled):
    bad = dict(ALL_OK, sales_loaded=False, lp_next=False)
    monkeypatch.setattr(cc, "read_status", lambda cur, params: _status(checks=bad))
    conn = _Conn()
    with pytest.raises(SystemExit) as exc:
        cc.close(conn, "public", P, "Yuan", True, out=lambda *_: None)
    assert exc.value.code == 2 and conn.writes() == [] and settled == []
    conn, result, out = _run(monkeypatch, _status(checks=bad), write=False)
    assert result["action"] == "refused" and "per-SKU sales" in " ".join(result["reason"])


def test_a_close_runs_its_steps_each_in_its_own_committed_transaction(monkeypatch, settled):
    conn, result, out = _run(monkeypatch, _status())
    assert result["action"] == "closed" and result["changed"]
    assert settled == [("2026-03", True)]
    names = [s.split(" SET ")[0] if " SET " in s else s[:40] for s in conn.writes()]
    assert any("SET state = 'closing'" in s for s in conn.writes())
    assert any(s.startswith("UPDATE lp_recommendation lr SET closed_at = now()") for s in conn.writes())
    assert any("SET state = 'closed'" in s for s in conn.writes())
    assert conn.commits == 4          # start, settle, close plan, record: each committed on its own


def test_a_decided_row_is_closed_not_changed_or_deleted():
    sql = " ".join(cc.CLOSE_PLAN_SQL.split())
    assert re.findall(r"SET (\w+)", sql) == ["closed_at"]
    assert "status" not in sql.split("WHERE")[0] and "decided" not in sql
    for const in (cc.CLOSE_PLAN_SQL, cc.START_SQL, cc.RECORD_SQL, cc.UNSETTLE_SQL, cc.REOPEN_PLAN_SQL, cc.REOPEN_CYCLE_SQL):
        assert not re.search(r"\b(DELETE|TRUNCATE|DROP)\b", const, re.I)


def test_running_a_close_twice_changes_nothing_the_second_time(monkeypatch, settled):
    conn, result, out = _run(monkeypatch, _status(state="closed", steps=cc.STEPS))
    assert result["action"] == "already_closed" and result["changed"] is False
    assert conn.writes() == [] and conn.commits == 0 and settled == []
    assert any("already closed" in line for line in out)


def test_a_close_that_failed_midway_resumes_and_skips_the_finished_steps(monkeypatch, settled):
    conn, result, out = _run(monkeypatch, _status(state="closing", steps=["settle_receipts"]))
    assert settled == []                                       # settlement was done, not repeated
    assert any(s.startswith("UPDATE lp_recommendation lr SET closed_at") for s in conn.writes())
    assert result["action"] == "closed" and [s for s, _ in result["steps"]] == ["close_plan"]


def test_a_step_that_fails_leaves_the_cycle_closing_with_the_finished_steps_recorded(monkeypatch):
    def boom(cur, period, write=False):
        raise RuntimeError("connection lost")
    monkeypatch.setattr(cc.receipt_settlement, "settle", boom)
    monkeypatch.setattr(cc, "read_status", lambda cur, params: _status())
    conn = _Conn()
    with pytest.raises(RuntimeError):
        cc.close(conn, "public", P, "Yuan", True, out=lambda *_: None)
    # the start (open -> closing) was committed before the work, the failed step rolled back, nothing after it ran
    assert conn.commits == 1 and conn.rollbacks >= 1
    assert not any("SET state = 'closed'" in s or "closed_at = now()" in s for s in conn.writes())


def test_reopen_undoes_every_step_in_one_transaction_without_a_restore(monkeypatch):
    conn, result, out = _run(monkeypatch, _status(state="closed", steps=cc.STEPS, closed_rows=110), fn=cc.reopen)
    assert result["action"] == "reopened" and result["changed"]
    writes = conn.writes()
    assert any("SET state = 'expected'" in s for s in writes)                    # receipts settled by the close come back
    assert any("SET closed_at = NULL" in s for s in writes)                      # plan rows reopened
    assert any("SET state = 'open'" in s and "reopen_count = reopen_count + 1" in s for s in writes)
    assert conn.commits == 1


def test_reopening_a_half_closed_cycle_works_too_and_an_open_one_has_nothing_to_reopen(monkeypatch):
    conn, result, _ = _run(monkeypatch, _status(state="closing", steps=["settle_receipts"]), fn=cc.reopen)
    assert result["action"] == "reopened"
    conn, result, _ = _run(monkeypatch, _status(state="open"), fn=cc.reopen)
    assert result["action"] == "nothing_to_reopen" and conn.writes() == []


def test_a_reopen_only_undoes_the_receipts_this_close_settled():
    sql = " ".join(cc.UNSETTLE_SQL.split())
    assert "er.settled_at >= pc.closing_started_at" in sql and "er.settled_by_period = %(period)s" in sql


# ---- the gate ------------------------------------------------------------------------------------------------------

def _main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["close_cycle", *argv])
    return cc.main()


@pytest.mark.parametrize("argv", [
    ["--cycle", "2026-03", "--approved-by", "Yuan"],                                   # no --expect-cycle
    ["--cycle", "2026-03", "--expect-cycle", "2026-03"],                               # no --approved-by
    ["--cycle", "2026-03", "--approved-by", "Yuan", "--expect-cycle", "2026-04"],      # names another cycle
    ["--cycle", "2026-03", "--approved-by", "Yuan", "--expect-cycle", "2026-03"],      # public without --target-public
])
def test_writing_needs_both_flags_the_same_cycle_and_target_public(monkeypatch, argv):
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, *argv)
    assert exc.value.code == 2


def test_the_docstring_says_what_happens_when_a_step_fails():
    assert "IF A STEP FAILS MIDWAY" in cc.__doc__ and "--reopen" in cc.__doc__ and "without a database restore" in cc.__doc__
