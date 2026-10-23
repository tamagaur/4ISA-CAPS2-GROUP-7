"""
tests/backend/test_reorder_approval.py - the admin reversal of a decision (migration 0067),
backend/routers/reorder_approval.py.

Like tests/backend/test_recommendation_decisions.py, the fake session answers by SQL text, so these tests check
what the code asks the database and what it does with the answer: which statements run, in what order, with what
values, and which never run. The two migrations are NOT applied to the live database, so the SQL itself has not
run against Postgres; the shapes it relies on (the partial unique index, FOR UPDATE OF, ck_lp_decision_shape) are
read from the migration files below.
"""
from __future__ import annotations

import datetime
import pathlib
import re

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend import auth_utils, planning_mart
from backend.api_errors import ApiError
from backend.routers import reorder_approval as ra
from backend.schemas.recommendations import ReverseRequest
from tests.backend.test_recommendations import FakeResult, _item_row

REPO = pathlib.Path(__file__).resolve().parents[2]
CYCLE = datetime.date(2026, 3, 1)
PROPOSED_AT = datetime.datetime(2026, 10, 23, 9, 0, tzinfo=datetime.timezone.utc)


def _user(user_id: int, email: str, role: str = "staff"):
    return auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=user_id, email=email, role=role, full_name=email.split("@")[0]))


PLANNER = _user(1, "planner@ssmcapstone.com")
BYPASS = _user(3, "trusted@ssmcapstone.com")
ADMIN = _user(2, "admin@ssmcapstone.com", "admin")


class _DB:
    """A session for one request. `row` is the recommendation (_ROW_SQL), `change` the lp_quantity_change row,
    `grants` the user ids with a direct-apply grant, `decide_matches` whether the guarded accept UPDATE finds an
    open current row, `prior` the decision a reversal would find."""

    def __init__(self, *, status="pending", q_i=384.80, current_cycle=CYCLE, grants=(), change=None,
                 propose_wins=True, decide_matches=True, open_change=None, prior=None, approval=True,
                 reversal=True, users=None):
        self.row = {"recommendation_key": 1, "q_i": q_i, "status": status, "planning_cycle_date": CYCLE,
                    "sku": "U-1", "current_cycle": current_cycle}
        self.grants, self.change = set(grants), change
        self.propose_wins, self.decide_matches, self.open_change = propose_wins, decide_matches, open_change
        self.prior, self.approval, self.reversal, self.users = prior, approval, reversal, users or {}
        self.sql: list[tuple[str, dict]] = []
        self.audit: list[dict] = []
        self.commits = 0
        self.rolled_back = False

    def run(self, needle: str) -> list[tuple[str, dict]]:
        return [(s, p) for s, p in self.sql if needle in s]

    def statements(self) -> list[str]:
        return [" ".join(s.split())[:60] for s, _ in self.sql]

    def execute(self, stmt, params=None):
        sql, params = str(stmt), dict(params or {})
        self.sql.append((sql, params))
        sql = " ".join(sql.split())     # the statements wrap lines; the dispatch below does not care where
        if "to_regclass('review_flag')" in sql:
            return FakeResult([{"review_flag": False, "on_order": True, "decision_cols": True,
                                "approval": self.approval, "reversal": self.reversal}])
        if "INSERT INTO audit_log" in sql:
            self.audit.append(params)
            return FakeResult([])
        if "FROM lp_direct_apply_grant WHERE user_id" in sql:
            return FakeResult([{"one": 1}] if params["uid"] in self.grants else [])
        if "SELECT lr.recommendation_key, lr.q_i, lr.status, lr.planning_cycle_date" in sql:
            return FakeResult([self.row])
        if "SELECT q_i FROM lp_recommendation WHERE recommendation_key" in sql:
            return FakeResult([self.row["q_i"]])
        if "INSERT INTO lp_quantity_change" in sql:
            return FakeResult([{"change_key": 7}] if self.propose_wins else [])
        if "FROM lp_quantity_change WHERE recommendation_key" in sql:
            return FakeResult([self.open_change] if self.open_change else [])
        if "FROM lp_quantity_change c" in sql and "WHERE c.change_key" in sql:
            return FakeResult([self.change] if self.change else [])
        if "FROM lp_quantity_change c" in sql:
            return FakeResult([self.change] if self.change else [])
        if "UPDATE lp_quantity_change" in sql:
            self.change = {**self.change, "state": params["state"], "resolved_by": params["resolved_by"],
                           "resolved_at": params["resolved_at"], "resolution_note": params["note"]}
            return FakeResult([{"change_key": params["change_key"]}])
        if "UPDATE lp_recommendation lr" in sql:
            return FakeResult([{"sku": "U-1", "planning_cycle_date": CYCLE}] if self.decide_matches else [])
        if "AS current_cycle" in sql and "FROM lp_recommendation d" in sql:
            return FakeResult([{"status": self.row["status"], "planning_cycle_date": CYCLE,
                                "current_cycle": self.row["current_cycle"]}])
        if "FOR UPDATE OF lr" in sql:
            return FakeResult([self.prior] if self.prior else [])
        if "SELECT user_id, email, role FROM users" in sql:
            user = self.users.get(params["uid"])
            return FakeResult([user] if user else [])
        if "MAX(classification_period) AS p FROM ABC_Classification" in sql:
            return FakeResult([{"principal": "unilever", "p": "2026-02"}])
        if "FROM lp_recommendation lr" in sql:
            return FakeResult([_item_row(current_stock=100.0, rop_i=30.0, q_i=self.row["q_i"])])
        return FakeResult([])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rolled_back = True


def test_reversal_is_the_admins_route_and_checks_the_role_not_only_the_key():
    """lp.decide can be ticked for a staff account (permission overrides), and reversing is still the admin's."""
    with pytest.raises(ApiError) as err:
        ra.require_lp_admin(current_user=PLANNER)
    assert err.value.status_code == 403 and err.value.code == "admin_required"
    assert ra.require_lp_admin(current_user=ADMIN) is ADMIN


# ── 7. reversing a decision ───────────────────────────────────────────────────────────────────────────────

def _prior(**over):
    row = {"recommendation_key": 1, "q_i": 384.80, "status": "accepted", "decided_at": PROPOSED_AT,
           "decided_by": "planner@ssmcapstone.com", "decided_q_i": 390.0, "decision_reason": "Truck is full",
           "sku": "U-1", "planning_cycle_date": CYCLE}
    return {**row, **over}


def test_a_reversal_returns_the_row_to_pending_and_keeps_the_decision():
    db = _DB(status="accepted", prior=_prior())
    ra.reverse_decision(1, ReverseRequest(reason="  Accepted the wrong product "), db=db, admin=ADMIN)
    kept = db.run("INSERT INTO lp_decision_reversal")[0][1]
    assert kept["prior_status"] == "accepted" and kept["prior_decided_q_i"] == 390.0
    assert kept["prior_reason"] == "Truck is full" and kept["prior_decided_by"] == "planner@ssmcapstone.com"
    assert kept["prior_decided_at"] == PROPOSED_AT and kept["q_i"] == 384.80
    assert kept["reversed_by"] == "admin@ssmcapstone.com" and kept["reason"] == "Accepted the wrong product"
    reset_sql = db.run("SET status = 'pending'")[0][0]
    for column in ("decided_at = NULL", "decided_by = NULL", "decided_q_i = NULL", "decision_reason = NULL"):
        assert column in reset_sql
    for never in ("q_i =", "rop_i", "ss_i"):
        assert never not in reset_sql.replace("decided_q_i", "")
    # the decision is copied BEFORE the row is reset, and nothing is deleted
    order = db.statements()
    assert order.index(next(s for s in order if s.startswith("INSERT INTO lp_decision_reversal"))) < \
        order.index(next(s for s in order if s.startswith("UPDATE lp_recommendation")))
    assert db.run("DELETE") == [] and db.commits == 1


def test_a_reversal_is_audited_with_who_when_and_why():
    db = _DB(status="dismissed", prior=_prior(status="dismissed", decided_q_i=None, decision_reason="Overstocked"))
    ra.reverse_decision(1, ReverseRequest(reason="Dismissed by mistake"), db=db, admin=ADMIN)
    (entry,) = db.audit
    assert entry["action"] == "Reorder Decision Reversed" and entry["user_email"] == "admin@ssmcapstone.com"
    assert "dismissed" in entry["details"] and "planner@ssmcapstone.com" in entry["details"]
    assert "2026-10-23 09:00 UTC" in entry["details"] and "Dismissed by mistake" in entry["details"]


def test_a_pending_row_has_nothing_to_reverse():
    with pytest.raises(HTTPException) as err:
        ra.reverse_decision(1, ReverseRequest(reason="x"), db=_DB(status="pending", prior=None), admin=ADMIN)
    assert err.value.status_code == 409 and "still pending" in err.value.detail


def test_a_decision_in_a_superseded_cycle_is_history_and_not_reversed():
    db = _DB(status="accepted", prior=None, current_cycle=datetime.date(2026, 4, 1))
    with pytest.raises(HTTPException) as err:
        ra.reverse_decision(1, ReverseRequest(reason="x"), db=db, admin=ADMIN)
    assert err.value.status_code == 409 and "superseded" in err.value.detail
    assert db.run("INSERT INTO lp_decision_reversal") == []


def test_reversal_needs_migration_0067_and_a_reason():
    with pytest.raises(ApiError) as err:
        ra.reverse_decision(1, ReverseRequest(reason="x"), db=_DB(reversal=False), admin=ADMIN)
    assert err.value.status_code == 503 and err.value.code == "reversal_not_ready"
    for reason in ("", "   "):
        with pytest.raises(ValidationError):
            ReverseRequest(reason=reason)


def test_a_reversal_is_copied_to_the_planning_mart(monkeypatch):
    seen = []

    class Db:
        def begin_nested(self):
            import contextlib
            return contextlib.nullcontext()

        def execute(self, stmt, params=None):
            seen.append((str(stmt), dict(params or {})))

    monkeypatch.setattr(planning_mart, "present", lambda db: True)
    assert planning_mart.undecide(Db(), 5) is True
    sql, params = seen[0]
    assert "decision_status = 'pending'" in sql and "decided_at = NULL" in sql and params == {"key": 5}


# ── 8. the migration ──────────────────────────────────────────────────────────────────────────────────────

def _migration(name: str) -> str:
    return (REPO / "analytics/db/migrations" / name).read_text(encoding="utf-8")


def test_the_migration_is_additive_and_the_number_is_free():
    names = sorted(p.name for p in (REPO / "analytics/db/migrations").glob("0*.sql"))
    numbers = [n[:4] for n in names]
    assert numbers.count("0067") == 1
    text_ = _migration("0067_lp_decision_reversal.sql")
    sql = "\n".join(l for l in text_.splitlines() if not l.strip().startswith("--"))
    assert not re.search(r"\b(DELETE|TRUNCATE|UPDATE)\b", sql, re.I) and "DROP TABLE" not in sql.upper()
    # the runner splits on semicolons: none inside a comment line
    assert all(";" not in l for l in text_.splitlines() if l.strip().startswith("--"))


def test_the_shape_the_code_assumes_is_in_the_migrations():
    reversal = _migration("0067_lp_decision_reversal.sql")
    assert "prior_status IN ('accepted', 'dismissed')" in reversal and "length(btrim(reversal_reason)) > 0" in reversal
    # a reversed row goes back to the shape ck_lp_decision_shape (0062) already allows
    capture = _migration("0062_lp_recommendation_decision_capture.sql")
    assert "decided_q_i IS NULL OR status = 'accepted'" in capture and "status <> 'dismissed'" in capture
