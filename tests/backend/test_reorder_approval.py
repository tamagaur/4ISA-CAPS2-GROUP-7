"""
tests/backend/test_reorder_approval.py - the reorder approval flow (migration 0068) and the admin reversal of a
decision (migration 0067), backend/routers/reorder_approval.py.

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
from backend.routers import recommendations as rec
from backend.routers import reorder_approval as ra
from backend.schemas.recommendations import (
    ApprovalNote, QuantityChange, QuantityChangeRequest, RecommendationDecision, RejectRequest, ReverseRequest,
)
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


def _change_row(**over):
    row = {"change_key": 7, "recommendation_key": 1, "sku_code": "U-1", "product_name": "Uni One",
           "planning_cycle_date": CYCLE, "recommended_q_i": 384.80, "proposed_q_i": 390.0, "reason": "Truck is full",
           "reviewed": False, "state": "pending_approval", "proposed_by": "planner@ssmcapstone.com",
           "proposed_at": PROPOSED_AT, "resolved_by": None, "resolved_at": None, "resolution_note": None}
    return {**row, **over}


class _DB:
    """A session for one request. `row` is the recommendation (_ROW_SQL), `change` the lp_quantity_change row,
    `grants` the user ids with a direct-apply grant, `decide_matches` whether the guarded accept UPDATE finds an
    open current row, `prior` the decision a reversal would find."""

    def __init__(self, *, status="pending", q_i=384.80, current_cycle=CYCLE, grants=(), change=None,
                 propose_wins=True, decide_matches=True, open_change=None, prior=None, approval=True,
                 reversal=True, users=None, pack=None, status_after_insert=None):
        self.row = {"recommendation_key": 1, "q_i": q_i, "status": status, "planning_cycle_date": CYCLE,
                    "sku": "U-1", "current_cycle": current_cycle, "pack": pack}
        self.grants, self.change = set(grants), change
        self.propose_wins, self.decide_matches, self.open_change = propose_wins, decide_matches, open_change
        self.prior, self.approval, self.reversal, self.users = prior, approval, reversal, users or {}
        # What the row reads as when the proposer re-reads it under a lock after its INSERT: another transaction's
        # accept that committed in between shows up here (the race, audit 2026-10-23).
        self.status_after_insert = status_after_insert
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
        if "lp_direct_apply_grant" in sql and ("INSERT" in sql or "DELETE" in sql):   # a grant or revoke that changes a row
            return FakeResult([{"user_id": params["uid"]}])
        if "FROM lp_direct_apply_grant WHERE user_id" in sql:
            return FakeResult([{"one": 1}] if params["uid"] in self.grants else [])
        if "SELECT lr.recommendation_key, lr.q_i, lr.status, lr.planning_cycle_date" in sql:
            return FakeResult([self.row])
        if "AS pack FROM lp_recommendation lr" in sql:   # the PATCH path's pack lookup (backend/case_pack.py)
            return FakeResult([{"q_i": self.row["q_i"], "pack": self.row["pack"]}])
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
        if sql.startswith("SELECT lr.status, lr.planning_cycle_date,") and "FOR UPDATE OF lr" in sql:
            self.locked_after_insert = True
            return FakeResult([{"status": self.status_after_insert or self.row["status"],
                                "planning_cycle_date": CYCLE, "current_cycle": self.row["current_cycle"]}])
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


def _propose(db, user=PLANNER, quantity=390.0, **extra):
    # A reason is required since 2026-10-28 (test_a_quantity_change_needs_a_reason below).
    extra.setdefault("reason", "Truck is full")
    response = type("R", (), {"status_code": 200})()
    out = ra.change_quantity(1, QuantityChangeRequest(quantity=quantity, **extra), response, db=db, current_user=user)
    return out, response.status_code


# ── 1. a planner's edit is held, not applied ──────────────────────────────────────────────────────────────

def test_a_planners_quantity_edit_is_held_and_nothing_is_applied():
    db = _DB(change=_change_row())
    out, status = _propose(db, reason="  Truck is full ")
    assert status == 202 and out.outcome == "held" and out.item is None
    assert out.change.state == "pending_approval" and out.change.proposed_q_i == 390.0
    assert db.run("INSERT INTO lp_quantity_change")
    insert_params = db.run("INSERT INTO lp_quantity_change")[0][1]
    assert insert_params["quantity"] == 390.0 and insert_params["reason"] == "Truck is full"
    assert insert_params["proposed_by"] == "planner@ssmcapstone.com"
    # the recommendation row is not written: no UPDATE of lp_recommendation, no mart write, no decision columns
    assert db.run("UPDATE lp_recommendation") == []
    assert db.commits == 1


def test_a_proposal_is_audited_with_who_and_both_quantities():
    db = _DB(change=_change_row())
    _propose(db)
    (entry,) = db.audit
    assert entry["action"] == "Reorder Quantity Change Proposed"
    assert entry["user_email"] == "planner@ssmcapstone.com"
    assert "384.8 -> 390" in entry["details"] and "change 7" in entry["details"] and "awaiting approval" in entry["details"]


def test_the_proposal_insert_is_guarded_to_a_pending_current_row_with_a_different_quantity():
    sql = ra._PROPOSE_SQL
    assert "lr.status = 'pending'" in sql
    assert "MAX(l2.planning_cycle_date)" in sql and "p2.principal = pd.principal" in sql
    assert "<> lr.q_i" in sql
    assert "ON CONFLICT (recommendation_key) WHERE state = 'pending_approval' DO NOTHING" in sql


@pytest.mark.parametrize("quantity", [384.80, 384.8004])
def test_the_recommended_quantity_is_not_a_change(quantity):
    db = _DB()
    with pytest.raises(ApiError) as err:
        _propose(db, quantity=quantity)
    assert err.value.status_code == 400 and err.value.code == "quantity_unchanged"
    assert db.run("INSERT INTO lp_quantity_change") == [] and db.run("UPDATE lp_recommendation") == []


def test_a_second_proposal_on_a_row_with_one_open_is_refused():
    db = _DB(propose_wins=False, open_change={"change_key": 7, "proposed_by": "other@ssmcapstone.com"})
    with pytest.raises(HTTPException) as err:
        _propose(db)
    assert err.value.status_code == 409 and "awaiting approval" in err.value.detail and "other@ssmcapstone.com" in err.value.detail
    assert db.rolled_back


@pytest.mark.parametrize("row, text", [
    (dict(status="accepted"), "already accepted"),
    (dict(status="pending", current_cycle=datetime.date(2026, 4, 1)), "superseded"),
])
def test_only_a_pending_current_row_can_be_proposed_on(row, text):
    with pytest.raises(HTTPException) as err:
        _propose(_DB(**row))
    assert err.value.status_code == 409 and text in err.value.detail


def test_the_proposal_endpoint_needs_migration_0068():
    with pytest.raises(ApiError) as err:
        _propose(_DB(approval=False))
    assert err.value.status_code == 503 and err.value.code == "approval_not_ready"


# ── 2. an admin approves ──────────────────────────────────────────────────────────────────────────────────

def test_an_admin_approving_makes_the_ordinary_accept_with_the_proposed_quantity():
    db = _DB(change=_change_row())
    out = ra.approve_change(7, ApprovalNote(note="OK for the Friday truck"), db=db, admin=ADMIN)
    assert out.state == "approved" and out.resolved_by == "admin@ssmcapstone.com"
    update_change = db.run("UPDATE lp_quantity_change")[0][1]
    assert update_change["state"] == "approved" and update_change["note"] == "OK for the Friday truck"
    (accept_sql, accept) = db.run("UPDATE lp_recommendation lr")[0]
    assert accept["status"] == "accepted" and accept["decided_q"] == 390.0
    assert accept["decided_by"] == "planner@ssmcapstone.com"        # the planner made the decision
    assert accept["reason"] == "Truck is full"                      # decision_reason reused
    assert accept["decided_at"] == update_change["resolved_at"]
    # The change is settled BEFORE the accept, so the open-change guard in the accept lets it through, and a
    # refused accept rolls the settlement back with it.
    order = db.statements()
    assert order.index(next(s for s in order if s.startswith("UPDATE lp_quantity_change"))) < \
        order.index(next(s for s in order if s.startswith("UPDATE lp_recommendation")))
    assert "NOT EXISTS" in accept_sql and "lp_quantity_change" in accept_sql
    assert db.commits == 1


def test_an_approval_is_audited_with_the_approver_and_both_quantities():
    db = _DB(change=_change_row())
    ra.approve_change(7, None, db=db, admin=ADMIN)
    (entry,) = db.audit
    assert entry["action"] == "Reorder Quantity Change Approved"
    assert entry["user_email"] == "admin@ssmcapstone.com" and entry["role"] == "admin"
    assert "384.8 -> 390" in entry["details"] and "planner@ssmcapstone.com" in entry["details"]
    assert "2026-10-23 09:00 UTC" in entry["details"]


def test_a_refused_accept_rolls_the_settlement_back():
    db = _DB(change=_change_row(), decide_matches=False)
    with pytest.raises(HTTPException) as err:
        ra.approve_change(7, None, db=db, admin=ADMIN)
    assert err.value.status_code == 409
    assert db.rolled_back and db.commits == 0 and db.audit == []


def test_approval_is_refused_when_the_recommendation_moved_since_the_proposal():
    db = _DB(change=_change_row(recommended_q_i=300.0), q_i=384.80)
    with pytest.raises(ApiError) as err:
        ra.approve_change(7, None, db=db, admin=ADMIN)
    assert err.value.status_code == 409 and err.value.code == "recommendation_changed"
    assert db.run("UPDATE lp_quantity_change") == [] and db.run("UPDATE lp_recommendation") == []


def test_a_change_on_a_superseded_cycle_is_closed_not_left_in_the_queue():
    """Audit 2026-10-23 finding 9: approve answered 409 and rolled back, so the change stayed pending for ever."""
    db = _DB(change=_change_row(), current_cycle=datetime.date(2026, 4, 1))
    with pytest.raises(HTTPException) as err:
        ra.approve_change(7, None, db=db, admin=ADMIN)
    assert err.value.status_code == 409 and "superseded" in err.value.detail
    closed = db.run("UPDATE lp_quantity_change")
    assert len(closed) == 1 and closed[0][1]["state"] == "rejected" and "superseded" in closed[0][1]["note"]
    assert db.commits == 1 and db.run("UPDATE lp_recommendation") == []  # the closure is kept, no decision written
    assert len(db.audit) == 1


def test_the_change_list_names_an_approval_whose_decision_was_later_reversed():
    sql = " ".join(ra._CHANGE_COLUMNS.split())
    assert "lp_decision_reversal" in sql and "rv.reversed_at" in sql and "c.state = 'approved'" in sql
    change = QuantityChange(**_change_row(state="approved", reversed_by="admin@ssmcapstone.com",
                                          reversed_at=PROPOSED_AT))
    assert change.state == "approved" and change.reversed_by == "admin@ssmcapstone.com"


@pytest.mark.parametrize("state", ["approved", "rejected"])
def test_a_settled_change_is_not_settled_twice(state):
    db = _DB(change=_change_row(state=state, resolved_by="admin@ssmcapstone.com", resolved_at=PROPOSED_AT))
    for call in (lambda: ra.approve_change(7, None, db=db, admin=ADMIN),
                 lambda: ra.reject_change(7, RejectRequest(reason="stock is fine"), db=db, admin=ADMIN)):
        with pytest.raises(HTTPException) as err:
            call()
        assert err.value.status_code == 409 and f"already {state}" in err.value.detail
    assert db.run("UPDATE lp_quantity_change") == []


def test_approval_locks_the_change_and_the_recommendation():
    assert "FOR UPDATE OF c, lr" in ra._CHANGE_LOCKED_SQL


# ── 3. an admin rejects ───────────────────────────────────────────────────────────────────────────────────

def test_an_admin_rejecting_leaves_the_recommendation_untouched_and_keeps_the_change():
    db = _DB(change=_change_row())
    out = ra.reject_change(7, RejectRequest(reason="  Over the warehouse ceiling "), db=db, admin=ADMIN)
    assert out.state == "rejected" and out.resolution_note == "Over the warehouse ceiling"
    assert out.proposed_q_i == 390.0                                # the change is the record, not deleted
    assert db.run("UPDATE lp_recommendation") == [] and db.run("DELETE") == []
    assert db.run("UPDATE lp_quantity_change")[0][1]["state"] == "rejected"


def test_a_rejection_is_audited_with_who_and_both_quantities_and_the_reason():
    db = _DB(change=_change_row())
    ra.reject_change(7, RejectRequest(reason="Over the warehouse ceiling"), db=db, admin=ADMIN)
    (entry,) = db.audit
    assert entry["action"] == "Reorder Quantity Change Rejected" and entry["user_email"] == "admin@ssmcapstone.com"
    assert "384.8 -> 390" in entry["details"] and "Over the warehouse ceiling" in entry["details"]
    assert "planner@ssmcapstone.com" in entry["details"]


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_rejection_needs_a_reason(reason):
    with pytest.raises(ValidationError):
        RejectRequest(reason=reason)


def test_a_missing_change_is_a_404():
    with pytest.raises(HTTPException) as err:
        ra.approve_change(99, None, db=_DB(change=None), admin=ADMIN)
    assert err.value.status_code == 404


# ── 4. a user with the grant applies directly ─────────────────────────────────────────────────────────────

def test_a_user_with_a_grant_applies_a_quantity_change_at_once():
    db = _DB(grants={3})
    out, status = _propose(db, user=BYPASS, reason="Truck is full")
    assert status == 200 and out.outcome == "applied" and out.change is None and out.item is not None
    assert db.run("INSERT INTO lp_quantity_change") == []           # nothing is held
    (sql, accept) = db.run("UPDATE lp_recommendation lr")[0]
    assert accept["status"] == "accepted" and accept["decided_q"] == 390.0
    assert accept["decided_by"] == "trusted@ssmcapstone.com"
    (entry,) = db.audit
    assert entry["action"] == "Reorder Recommendation Accepted" and "applied directly" in entry["details"]
    assert "390" in entry["details"] and "384.8" in entry["details"]


def test_an_admins_own_quantity_change_applies_at_once_without_a_grant():
    db = _DB()
    out, status = _propose(db, user=ADMIN)
    assert status == 200 and out.outcome == "applied"
    assert db.run("FROM lp_direct_apply_grant") == []               # an admin is never looked up
    assert db.run("INSERT INTO lp_quantity_change") == []


def test_patch_with_a_different_quantity_works_for_a_user_with_the_grant():
    db = _DB(grants={3})
    rec.update_recommendation(1, RecommendationDecision(status="accepted", decided_quantity=390), db=db, current_user=BYPASS)
    assert db.run("UPDATE lp_recommendation lr")[0][1]["decided_q"] == 390


# ── 5. a user without the grant cannot ────────────────────────────────────────────────────────────────────

def test_patch_with_a_different_quantity_is_refused_for_a_user_without_the_grant():
    db = _DB()
    with pytest.raises(ApiError) as err:
        rec.update_recommendation(1, RecommendationDecision(status="accepted", decided_quantity=390), db=db,
                                  current_user=PLANNER)
    assert err.value.status_code == 403 and err.value.code == "approval_required"
    assert "quantity-change" in err.value.detail
    assert db.run("UPDATE lp_recommendation") == [] and db.audit == []


def test_patch_with_the_recommended_quantity_or_none_still_accepts_for_everyone():
    for quantity in (None, 384.80):
        db = _DB()
        rec.update_recommendation(1, RecommendationDecision(status="accepted", decided_quantity=quantity), db=db,
                                  current_user=PLANNER)
        assert db.run("UPDATE lp_recommendation lr")


def test_dismissing_needs_no_approval():
    db = _DB()
    rec.update_recommendation(1, RecommendationDecision(status="dismissed", reason="Overstocked"), db=db, current_user=PLANNER)
    assert db.run("UPDATE lp_recommendation lr")


def test_before_migration_0068_a_quantity_edit_applies_as_it_did():
    db = _DB(approval=False)
    rec.update_recommendation(1, RecommendationDecision(status="accepted", decided_quantity=390), db=db, current_user=PLANNER)
    assert db.run("UPDATE lp_recommendation lr")[0][1]["decided_q"] == 390
    assert "lp_quantity_change" not in db.run("UPDATE lp_recommendation lr")[0][0]
    assert db.run("FROM lp_direct_apply_grant") == []


def test_a_row_with_a_change_awaiting_approval_cannot_be_decided_directly():
    db = _DB(decide_matches=False, open_change={"change_key": 7, "proposed_by": "planner@ssmcapstone.com"})
    with pytest.raises(HTTPException) as err:
        rec.update_recommendation(1, RecommendationDecision(status="dismissed", reason="no longer needed"), db=db, current_user=PLANNER)
    assert err.value.status_code == 409 and "awaiting approval" in err.value.detail and "change 7" in err.value.detail
    assert db.rolled_back


# ── 6. who can see and settle the queue ───────────────────────────────────────────────────────────────────

def test_only_an_admin_can_approve_reject_reverse_or_grant():
    from fastapi.testclient import TestClient
    from backend.deps import get_db
    from backend.main import app

    db = _DB(change=_change_row())
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer " + auth_utils.create_access_token(
                user_id=1, email="planner@ssmcapstone.com", role="staff", full_name="Planner")}
            calls = [("post", "/recommendations/changes/7/approve", {}),
                     ("post", "/recommendations/changes/7/reject", {"reason": "no"}),
                     ("post", "/recommendations/1/reverse", {"reason": "mis-click"}),
                     ("get", "/recommendations/direct-apply-grants", None),
                     ("put", "/recommendations/direct-apply-grants/3", {"granted": True})]
            for method, path, body in calls:
                resp = getattr(client, method)(path, headers=headers, **({"json": body} if body is not None else {}))
                assert resp.status_code in (401, 403), (path, resp.status_code)
    finally:
        app.dependency_overrides.clear()
    assert db.run("UPDATE") == [] and db.run("INSERT") == [] and db.run("DELETE") == []


def test_the_admin_routes_also_check_the_role_not_only_the_key():
    """lp.decide or users.manage can be ticked for a staff account (permission overrides); these routes are still
    the admin's."""
    for dependency in (ra.require_lp_admin, ra.require_grant_admin):
        with pytest.raises(ApiError) as err:
            dependency(current_user=PLANNER)
        assert err.value.status_code == 403 and err.value.code == "admin_required"
        assert dependency(current_user=ADMIN) is ADMIN


def test_a_non_admin_lists_only_their_own_changes():
    db = _DB(change=_change_row())
    ra.list_changes(state="pending_approval", recommendation_key=None, db=db, current_user=PLANNER)
    sql, params = db.run("FROM lp_quantity_change c")[-1]
    assert "c.proposed_by = :me" in sql and params["me"] == "planner@ssmcapstone.com"
    db = _DB(change=_change_row())
    out = ra.list_changes(state="pending_approval", recommendation_key=None, db=db, current_user=ADMIN)
    sql, params = db.run("FROM lp_quantity_change c")[-1]
    # No requester filter for an admin (the requester's-name join on c.proposed_by, 2026-10-28, is not a filter).
    assert "c.proposed_by = :me" not in sql and "me" not in params and out.count == 1
    assert params == {"state": "pending_approval"}


def test_the_state_filter_is_checked():
    with pytest.raises(HTTPException) as err:
        ra.list_changes(state="done", recommendation_key=None, db=_DB(), current_user=ADMIN)
    assert err.value.status_code == 400


# ── 7. reversing a decision ───────────────────────────────────────────────────────────────────────────────

def _prior(**over):
    row = {"recommendation_key": 1, "q_i": 384.80, "status": "accepted", "decided_at": PROPOSED_AT,
           "decided_by": "planner@ssmcapstone.com", "decided_q_i": 390.0, "decision_reason": "Truck is full",
           "sku": "U-1", "planning_cycle_date": CYCLE, "lp_run_key": 6}
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


def test_a_decided_row_with_no_lp_run_cannot_be_reversed_into_the_plan():
    """Row 4 (SKU 20292811, accepted 2026-08-24, lp_run_key NULL) is outside the plan at 109 rows. Reversing it would
    make it pending, and a pending row is always plan (backend/lp_cycle.PLAN_STATUS_SQL), so the plan would read 110
    (QA 2026-10-24 finding 2). It is refused, and nothing is written."""
    db = _DB(status="accepted", prior=_prior(recommendation_key=4, sku="20292811", lp_run_key=None, decided_q_i=None,
                                              decided_by="planner@ssmcapstone.com"))
    with pytest.raises(HTTPException) as err:
        ra.reverse_decision(4, ReverseRequest(reason="qa"), db=db, admin=ADMIN)
    assert err.value.status_code == 409 and "not part of the current plan" in err.value.detail
    assert db.run("INSERT INTO lp_decision_reversal") == [] and db.run("SET status = 'pending'") == []
    assert db.audit == [] and db.commits == 0 and db.rolled_back


def test_the_reversal_lookup_reads_the_lp_run_key():
    assert "lr.lp_run_key" in ra._REVERSAL_ROW_SQL


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


# ── 8. who may apply directly ─────────────────────────────────────────────────────────────────────────────

def test_an_admin_grants_and_revokes_and_each_is_audited():
    users = {3: {"user_id": 3, "email": "trusted@ssmcapstone.com", "role": "staff"}}
    db = _DB(users=users)
    out = ra.set_direct_apply_grant(3, ra.DirectApplyGrantBody(granted=True), db=db, admin=ADMIN)
    assert out.can_apply_directly and out.reason == "granted"
    assert db.run("INSERT INTO lp_direct_apply_grant")[0][1] == {"uid": 3, "by": "admin@ssmcapstone.com"}
    assert db.audit[0]["action"] == "Direct Apply Granted" and db.audit[0]["details"] == "trusted@ssmcapstone.com"
    db = _DB(users=users)
    out = ra.set_direct_apply_grant(3, ra.DirectApplyGrantBody(granted=False), db=db, admin=ADMIN)
    assert not out.can_apply_directly and db.run("DELETE FROM lp_direct_apply_grant")
    assert db.audit[0]["action"] == "Direct Apply Revoked"


def test_granting_an_unknown_user_is_a_404():
    with pytest.raises(HTTPException) as err:
        ra.set_direct_apply_grant(99, ra.DirectApplyGrantBody(granted=True), db=_DB(), admin=ADMIN)
    assert err.value.status_code == 404


def test_the_caller_can_ask_whether_their_change_will_apply_at_once():
    assert ra.my_direct_apply(db=_DB(), current_user=ADMIN).reason == "admin"
    assert ra.my_direct_apply(db=_DB(grants={3}), current_user=BYPASS).reason == "granted"
    not_granted = ra.my_direct_apply(db=_DB(), current_user=PLANNER)
    assert not_granted.can_apply_directly is False and not_granted.reason == "not_granted"
    assert ra.my_direct_apply(db=_DB(approval=False), current_user=PLANNER).approval_ready is False


# ── 9. the migrations ─────────────────────────────────────────────────────────────────────────────────────

def _migration(name: str) -> str:
    return (REPO / "analytics/db/migrations" / name).read_text(encoding="utf-8")


def test_the_migrations_are_additive_and_the_numbers_are_free():
    names = sorted(p.name for p in (REPO / "analytics/db/migrations").glob("0*.sql"))
    numbers = [n[:4] for n in names]
    assert numbers.count("0067") == 1 and numbers.count("0068") == 1 and numbers.count("0069") == 1 and numbers.count("0070") == 1
    for name in ("0067_lp_decision_reversal.sql", "0068_lp_quantity_change_approval.sql",
                 "0070_lp_dismissal_request_stock_observation.sql"):
        sql = "\n".join(l for l in _migration(name).splitlines() if not l.strip().startswith("--"))
        assert not re.search(r"\b(DELETE|TRUNCATE|UPDATE|ALTER\s+TABLE\s+\w+\s+DROP)\b", sql, re.I)
        assert "DROP TABLE" not in sql.upper()
        # the runner splits on semicolons: none inside a comment line
        assert all(";" not in l for l in _migration(name).splitlines() if l.strip().startswith("--"))


def test_the_state_machine_the_code_assumes_is_in_the_migration():
    sql = _migration("0068_lp_quantity_change_approval.sql")
    assert "state IN ('pending_approval', 'approved', 'rejected')" in sql
    assert "UNIQUE INDEX IF NOT EXISTS ux_lp_quantity_change_one_open" in sql and "WHERE state = 'pending_approval'" in sql
    assert "proposed_q_i <> recommended_q_i" in sql
    # a settled change names who settled it, and a rejection names why
    assert "resolved_by IS NOT NULL" in sql and "resolution_note" in sql
    reversal = _migration("0067_lp_decision_reversal.sql")
    assert "prior_status IN ('accepted', 'dismissed')" in reversal and "length(btrim(reversal_reason)) > 0" in reversal
    # a reversed row goes back to the shape ck_lp_decision_shape (0062) already allows
    capture = _migration("0062_lp_recommendation_decision_capture.sql")
    assert "decided_q_i IS NULL OR status = 'accepted'" in capture and "status <> 'dismissed'" in capture


# ── 8. a planner's quantity must be whole cases (audit finding 4, 2026-10-23) ─────────────────────────────
# 6,192 pieces on a pack of 288 is 21.5 cases and was applied. The edit is REFUSED (422 not_whole_cases), not
# rounded: the planner typed it. The LP rounds because nobody typed its number.

def _off_pack_refused(call):
    with pytest.raises(ApiError) as err:
        call()
    assert err.value.status_code == 422 and err.value.code == "not_whole_cases"
    return err.value


def test_direct_apply_by_a_granted_planner_refuses_a_part_case_quantity():
    db = _DB(q_i=5472.0, grants={3}, pack=288)
    err = _off_pack_refused(lambda: _propose(db, user=BYPASS, quantity=6192.0))
    assert err.extra["pack_size"] == 288 and err.extra["nearest_below"] == 6048 and err.extra["nearest_above"] == 6336
    assert "21.50 cases" in err.detail
    assert db.run("UPDATE lp_recommendation") == [] and db.audit == [] and db.commits == 0


def test_direct_apply_by_an_admin_refuses_it_too_and_a_whole_case_quantity_still_applies():
    db = _DB(q_i=5472.0, pack=288)
    _off_pack_refused(lambda: _propose(db, user=ADMIN, quantity=5 * 288 + 1.0))
    ok = _DB(q_i=5472.0, pack=288)
    out, status = _propose(ok, user=ADMIN, quantity=6048.0)       # 21 cases
    assert status == 200 and out.outcome == "applied"
    assert ok.run("UPDATE lp_recommendation lr")[0][1]["decided_q"] == 6048.0


def test_patch_by_a_granted_planner_refuses_a_part_case_quantity():
    db = _DB(q_i=5472.0, grants={3}, pack=288)
    _off_pack_refused(lambda: rec.update_recommendation(
        1, RecommendationDecision(status="accepted", decided_quantity=6192), db=db, current_user=BYPASS))
    assert db.run("UPDATE lp_recommendation lr") == [] and db.audit == []
    ok = _DB(q_i=5472.0, grants={3}, pack=288)
    rec.update_recommendation(1, RecommendationDecision(status="accepted", decided_quantity=6048), db=ok, current_user=BYPASS)
    assert ok.run("UPDATE lp_recommendation lr")[0][1]["decided_q"] == 6048


def test_a_proposal_that_would_be_held_is_refused_before_it_is_queued():
    db = _DB(q_i=5472.0, pack=288)
    _off_pack_refused(lambda: _propose(db, user=PLANNER, quantity=6192.0))
    assert db.run("INSERT INTO lp_quantity_change") == [] and db.commits == 0
    held = _DB(q_i=5472.0, pack=288, change=_change_row(recommended_q_i=5472.0, proposed_q_i=6048.0))
    out, status = _propose(held, user=PLANNER, quantity=6048.0)
    assert status == 202 and out.outcome == "held"


def test_approving_a_held_part_case_quantity_is_refused_and_rolls_back():
    """A proposal held before the check existed: the admin cannot approve it into the plan."""
    db = _DB(q_i=5472.0, pack=288, change=_change_row(recommended_q_i=5472.0, proposed_q_i=6192.0))
    _off_pack_refused(lambda: ra.approve_change(7, None, db=db, admin=ADMIN))
    assert db.rolled_back and db.run("UPDATE lp_quantity_change") == [] and db.run("UPDATE lp_recommendation") == []
    ok = _DB(q_i=5472.0, pack=288, change=_change_row(recommended_q_i=5472.0, proposed_q_i=6048.0))
    assert ra.approve_change(7, None, db=ok, admin=ADMIN).state == "approved"


def test_the_checks_that_are_not_made():
    # No usable pack size (the LP leaves such rows unchanged), a pack of 1, zero, and the recommended quantity itself.
    for pack, quantity in ((None, 390.0), (1, 390.0), (288, 0.0)):
        db = _DB(q_i=5472.0, pack=pack, grants={3})
        out, _ = _propose(db, user=BYPASS, quantity=quantity)
        assert out.outcome == "applied"
    from backend.case_pack import check_whole_cases
    check_whole_cases(5472.4, 288, recommended=5472.4)       # an old off-pack row accepted as recommended is no edit
    check_whole_cases(5472.0000004, 288)                      # within the LP's tolerance of a whole pack


# ── 9. the race: a planner's proposal against an admin's accept on the same row (audit 2026-10-23) ───────────
# Before: the proposal INSERT read `status = 'pending'` without a lock, and the accept's "no open change" guard
# could not see an uncommitted insert, so both committed and left an open change on an accepted row. Postgres only
# takes KEY SHARE on the row for the insert's foreign key, which the accept's UPDATE does not conflict with.

def test_the_accept_locks_the_row_before_its_guarded_update():
    db = _DB()
    rec.update_recommendation(1, RecommendationDecision(status="accepted"), db=db, current_user=PLANNER)
    order = db.statements()
    lock = next(i for i, s in enumerate(order) if s.startswith("SELECT 1 FROM lp_recommendation WHERE recommendation_key"))
    assert "FOR UPDATE" in db.run("SELECT 1 FROM lp_recommendation WHERE recommendation_key")[0][0]
    assert lock < order.index(next(s for s in order if s.startswith("UPDATE lp_recommendation")))


def test_approving_a_change_takes_the_same_row_lock_before_the_accept():
    db = _DB(change=_change_row())
    ra.approve_change(7, None, db=db, admin=ADMIN)
    order = db.statements()
    assert order.index(next(s for s in order if s.startswith("SELECT 1 FROM lp_recommendation"))) <         order.index(next(s for s in order if s.startswith("UPDATE lp_recommendation")))


def test_a_proposal_that_loses_the_race_to_an_accept_is_rolled_back_and_refused():
    """The interleaving: the planner's INSERT ran (uncommitted), the admin's accept committed, and the planner's
    locked re-read now finds the row accepted. The proposal is rolled back, not committed on a decided row."""
    db = _DB(change=_change_row(), status_after_insert="accepted")
    with pytest.raises(HTTPException) as err:
        _propose(db, user=PLANNER)
    assert err.value.status_code == 409 and "already accepted" in err.value.detail
    assert db.rolled_back and db.commits == 0 and db.audit == []
    assert db.run("INSERT INTO lp_quantity_change")          # the insert was attempted, then rolled back with the txn


def test_a_proposal_that_wins_the_race_is_committed_and_the_accept_then_sees_it():
    """The other interleaving: the proposal commits first. The accept's guard (a fresh statement after its own row
    lock) finds the open change, so the accept is refused rather than deciding past it."""
    db = _DB(change=_change_row())
    out, status = _propose(db, user=PLANNER)
    assert status == 202 and out.outcome == "held" and db.commits == 1 and not db.rolled_back
    assert "FOR UPDATE OF lr" in next(s for s, _ in db.sql if s.lstrip().startswith("SELECT lr.status, lr.planning_cycle_date,"))
    blocked = _DB(decide_matches=False, open_change={"change_key": 7, "proposed_by": "planner@ssmcapstone.com"})
    with pytest.raises(HTTPException) as refusal:
        rec.update_recommendation(1, RecommendationDecision(status="accepted"), db=blocked, current_user=PLANNER)
    assert refusal.value.status_code == 409 and "awaiting approval" in refusal.value.detail
