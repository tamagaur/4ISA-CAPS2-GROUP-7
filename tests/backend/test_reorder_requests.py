"""
tests/backend/test_reorder_requests.py - staff dismissal requests, stock counts and the recommendation's history
(migration 0070, backend/routers/reorder_requests.py and backend/stock_observation.py), plus the guards they add to
the quantity-change flow (backend/routers/reorder_approval.py) and to the direct decision (PATCH).

Like tests/backend/test_reorder_approval.py, the fake session answers by SQL text: these tests check which
statements run, in what order, with what values, and which never run. Migration 0070 is NOT applied to the live
database, so the SQL itself has not run against Postgres; the constraints it relies on are read from the file.
"""
from __future__ import annotations

import datetime
import pathlib
import re

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend import auth_utils, stock_observation
from backend.api_errors import ApiError
from backend.routers import recommendations as rec
from backend.routers import reorder_approval as ra
from backend.routers import reorder_requests as rr
from backend.schemas.recommendations import (
    ApprovalNote, DismissalRequestIn, QuantityChangeRequest, RecommendationDecision, RejectRequest, StockObservationIn,
    VerifyObservationBody,
)
from tests.backend.test_recommendations import FakeResult, _item_row

REPO = pathlib.Path(__file__).resolve().parents[2]
CYCLE = datetime.date(2026, 3, 1)
ASKED_AT = datetime.datetime(2026, 10, 28, 9, 0, tzinfo=datetime.timezone.utc)


def _user(user_id: int, email: str, role: str = "staff"):
    return auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=user_id, email=email, role=role, full_name=email.split("@")[0]))


STAFF = _user(1, "staff@ssmcapstone.com")
OTHER = _user(4, "other@ssmcapstone.com")
ADMIN = _user(2, "admin@ssmcapstone.com", "admin")


def _request_row(**over):
    row = {"request_key": 4, "recommendation_key": 1, "sku_code": "U-1", "product_name": "Uni One",
           "planning_cycle_date": CYCLE, "recommended_q_i": 47160.0, "reason": "Still 30 cases on the shelf",
           "state": "pending_approval", "requested_by": "staff@ssmcapstone.com", "requested_at": ASKED_AT,
           "resolved_by": None, "resolved_at": None, "resolution_note": None, "reversed_by": None, "reversed_at": None}
    return {**row, **over}


def _observation_row(**over):
    row = {"observation_key": 11, "recommendation_key": 1, "sku_code": "U-1", "product_name": "Uni One",
           "quantity_entered": 30.0, "unit_entered": "cases", "pieces_per_case": 24.0, "quantity_pieces": 720.0,
           "counted_at": None, "location": "Bay 3", "notes": None, "context": "dismissal_request",
           "quantity_change_key": None, "dismissal_request_key": 4, "reported_by": "staff@ssmcapstone.com",
           "reporter_role": "staff", "reported_at": ASKED_AT, "verification_state": "unverified",
           "verified_by": None, "verified_at": None, "verification_note": None}
    return {**row, **over}


class _DB:
    """One request's session. `row` is the recommendation, `request` the lp_dismissal_request row, `observations`
    the lp_stock_observation rows, `open_change` / `open_dismissal` what the open-request reads find."""

    def __init__(self, *, status="pending", q_i=47160.0, current_cycle=CYCLE, pack=24.0, request=None,
                 open_change=None, open_dismissal=None, insert_wins=True, decide_matches=True, observations=(),
                 requests=True, grants=(), changes=(), reversals=(), history_status="pending"):
        self.row = {"recommendation_key": 1, "q_i": q_i, "status": status, "planning_cycle_date": CYCLE,
                    "product_key": 9, "sku": "U-1", "pack": pack, "current_cycle": current_cycle}
        self.request, self.open_change, self.open_dismissal = request, open_change, open_dismissal
        self.insert_wins, self.decide_matches, self.requests = insert_wins, decide_matches, requests
        self.observations, self.grants = list(observations), set(grants)
        self.changes, self.reversals, self.history_status = list(changes), list(reversals), history_status
        self.sql: list[tuple[str, dict]] = []
        self.audit: list[dict] = []
        self.inserted_observations: list[dict] = []
        self.commits = 0
        self.rolled_back = False

    def run(self, needle: str) -> list[tuple[str, dict]]:
        return [(s, p) for s, p in self.sql if needle in " ".join(s.split())]

    def index(self, needle: str) -> int:
        return next(i for i, (s, _) in enumerate(self.sql) if needle in " ".join(s.split()))

    def execute(self, stmt, params=None):
        raw, params = str(stmt), dict(params or {})
        self.sql.append((raw, params))
        sql = " ".join(raw.split())
        if "to_regclass('review_flag')" in sql:
            return FakeResult([{"review_flag": False, "on_order": True, "decision_cols": True, "approval": True,
                                "reversal": True, "requests": self.requests}])
        if "INSERT INTO audit_log" in sql:
            self.audit.append(params)
            return FakeResult([])
        if "UPDATE lp_recommendation lr" in sql:
            return FakeResult([{"sku": "U-1", "planning_cycle_date": CYCLE}] if self.decide_matches else [])
        if "FROM lp_direct_apply_grant WHERE user_id" in sql:
            return FakeResult([{"one": 1}] if params["uid"] in self.grants else [])
        if "INSERT INTO lp_stock_observation" in sql:
            self.inserted_observations.append(params)
            return FakeResult([{"observation_key": 11}])
        if "UPDATE lp_stock_observation" in sql:
            return FakeResult([{"observation_key": params["k"]}])
        if "FROM lp_stock_observation o" in sql:
            return FakeResult(self.observations)
        if "INSERT INTO lp_dismissal_request" in sql:
            return FakeResult([{"request_key": 4}] if self.insert_wins else [])
        if "UPDATE lp_dismissal_request" in sql:
            self.request = {**self.request, "state": params["state"], "resolved_by": params["resolved_by"],
                            "resolved_at": params["resolved_at"], "resolution_note": params["note"]}
            return FakeResult([{"request_key": params["request_key"]}])
        if "FROM lp_dismissal_request WHERE recommendation_key" in sql:
            return FakeResult([self.open_dismissal] if self.open_dismissal else [])
        if "FROM lp_dismissal_request d" in sql:
            if "INSERT" not in sql and self.request is None and "request_key = :request_key" not in sql:
                return FakeResult([])
            return FakeResult([self.request] if self.request else [])
        if "FROM lp_quantity_change WHERE recommendation_key" in sql:
            return FakeResult([self.open_change] if self.open_change else [])
        if "INSERT INTO lp_quantity_change" in sql:
            return FakeResult([{"change_key": 7}])
        if "FROM lp_quantity_change c" in sql:
            if "c.change_key = :change_key" in sql:
                return FakeResult([{"change_key": 7, "recommendation_key": 1, "sku_code": "U-1", "product_name": "Uni One",
                                    "planning_cycle_date": CYCLE, "recommended_q_i": self.row["q_i"],
                                    "proposed_q_i": 48000.0, "reason": "Complete the cases", "reviewed": False,
                                    "state": "pending_approval", "proposed_by": "staff@ssmcapstone.com",
                                    "proposed_at": ASKED_AT, "resolved_by": None, "resolved_at": None,
                                    "resolution_note": None, "reversed_by": None, "reversed_at": None}])
            return FakeResult(self.changes)
        if "FROM lp_decision_reversal WHERE" in sql:
            return FakeResult(self.reversals)
        if "AS current_cycle" in sql and "FROM lp_recommendation d" in sql:
            return FakeResult([{"status": self.row["status"], "planning_cycle_date": CYCLE,
                                "current_cycle": self.row["current_cycle"]}])
        if "lr.generated_at" in sql:   # the history's row
            return FakeResult([{"recommendation_key": 1, "q_i": self.row["q_i"], "status": self.history_status,
                                "planning_cycle_date": CYCLE, "generated_at": ASKED_AT - datetime.timedelta(days=3),
                                "lp_run_key": 6, "decided_q_i": None, "decision_reason": None, "decided_at": None,
                                "decided_by": None, "sku_code": "U-1", "product_name": "Uni One", "pack": self.row["pack"]}])
        if sql.startswith("SELECT lr.product_key,"):   # the PATCH path's product and pack
            return FakeResult([{"product_key": 9, "pack": self.row["pack"]}])
        if sql.startswith("SELECT lr.recommendation_key, lr.q_i, lr.status, lr.planning_cycle_date, lr.product_key"):
            return FakeResult([self.row])
        if sql.startswith("SELECT lr.status, lr.planning_cycle_date,") and "FOR UPDATE OF lr" in sql:
            return FakeResult([{"status": self.row["status"], "planning_cycle_date": CYCLE,
                                "current_cycle": self.row["current_cycle"]}])
        if "MAX(classification_period) AS p FROM ABC_Classification" in sql:
            return FakeResult([{"principal": "unilever", "p": "2026-02"}])
        if "FROM lp_recommendation lr" in sql and "WHERE lr.recommendation_key = :key" in sql:
            return FakeResult([_item_row(current_stock=100.0, rop_i=30.0, q_i=self.row["q_i"])])
        return FakeResult([])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rolled_back = True


def _ask(db, user=STAFF, reason="Still 30 cases on the shelf", observation=None):
    return rr.request_dismissal(1, DismissalRequestIn(reason=reason, stock_observation=observation), db=db,
                                current_user=user)


# ── 1. a staff dismissal request is held, the recommendation stays active ──────────────────────────────────────

def test_a_dismissal_request_is_held_and_the_recommendation_is_not_touched():
    db = _DB(request=_request_row())
    out = _ask(db)
    assert out.state == "pending_approval" and out.request_key == 4
    (_, params), = db.run("INSERT INTO lp_dismissal_request")
    assert params["reason"] == "Still 30 cases on the shelf" and params["requested_by"] == "staff@ssmcapstone.com"
    assert db.run("UPDATE lp_recommendation") == [] and db.commits == 1
    (entry,) = db.audit
    assert entry["action"] == "Reorder Dismissal Requested" and "request 4" in entry["details"]
    assert "47160" in entry["details"] and entry["user_email"] == "staff@ssmcapstone.com"


@pytest.mark.parametrize("reason", ["", "   ", "no", "  short  ", "x" * 501])
def test_a_dismissal_request_needs_a_reason(reason):
    with pytest.raises(ValidationError):
        DismissalRequestIn(reason=reason)


# 8 to 500 characters once trimmed, as the Reorder page asks (Yuan, 2026-10-28): the request, and the rejection.
@pytest.mark.parametrize("make", [
    lambda r: DismissalRequestIn(reason=r),
    lambda r: QuantityChangeRequest(quantity=48000, reason=r),
    lambda r: RejectRequest(reason=r),
])
def test_a_request_or_rejection_reason_is_8_to_500_characters(make):
    for short in ("1234567", "   1234567   "):
        with pytest.raises(ValidationError):
            make(short)
    with pytest.raises(ValidationError):
        make("x" * 501)
    assert make("12345678").reason == "12345678"
    assert make("x" * 500)


def test_the_insert_is_guarded_to_a_pending_current_row_and_one_open_request():
    sql = " ".join(rr._INSERT_REQUEST_SQL.split())
    assert "lr.status = 'pending'" in sql and "MAX(l2.planning_cycle_date)" in sql
    assert "ON CONFLICT (recommendation_key) WHERE state = 'pending_approval' DO NOTHING" in sql


def test_the_row_is_locked_before_the_open_requests_are_read():
    db = _DB(request=_request_row())
    _ask(db)
    lock = db.index("FOR UPDATE OF lr")
    assert lock < db.index("FROM lp_quantity_change WHERE recommendation_key")
    assert lock < db.index("FROM lp_dismissal_request WHERE recommendation_key")
    assert lock < db.index("INSERT INTO lp_dismissal_request")


@pytest.mark.parametrize("open_kwargs, text", [
    ({"open_change": {"change_key": 7, "proposed_by": "other@ssmcapstone.com"}}, "quantity change awaiting approval"),
    ({"open_dismissal": {"request_key": 3, "requested_by": "other@ssmcapstone.com"}}, "dismissal request awaiting approval"),
])
def test_one_waiting_request_per_row_whichever_kind(open_kwargs, text):
    db = _DB(**open_kwargs)
    with pytest.raises(HTTPException) as err:
        _ask(db)
    assert err.value.status_code == 409 and text in err.value.detail
    assert db.run("INSERT INTO lp_dismissal_request") == [] and db.rolled_back and db.commits == 0


@pytest.mark.parametrize("row, text", [
    (dict(status="dismissed"), "already dismissed"),
    (dict(current_cycle=datetime.date(2026, 4, 1)), "superseded"),
])
def test_only_a_pending_current_row_can_be_asked_about(row, text):
    db = _DB(**row)
    with pytest.raises(HTTPException) as err:
        _ask(db)
    assert err.value.status_code == 409 and text in err.value.detail and db.run("INSERT INTO lp_dismissal_request") == []


def test_an_admin_dismisses_directly_instead_of_asking():
    with pytest.raises(ApiError) as err:
        _ask(_DB(), user=ADMIN)
    assert err.value.status_code == 400 and err.value.code == "use_direct_dismissal"


def test_requests_need_migration_0070():
    with pytest.raises(ApiError) as err:
        _ask(_DB(requests=False))
    assert err.value.status_code == 503 and err.value.code == "requests_not_ready"


def test_losing_the_race_on_the_one_open_index_is_refused():
    db = _DB(insert_wins=False)
    with pytest.raises(HTTPException) as err:
        _ask(db)
    assert err.value.status_code == 409 and db.rolled_back and db.commits == 0


# ── 2. stock counts: converted, never stock on hand ────────────────────────────────────────────────────────

def test_a_cases_count_is_stored_with_its_pieces_and_the_pack_it_used():
    db = _DB(request=_request_row(), observations=[_observation_row()])
    out = _ask(db, observation=StockObservationIn(quantity=30, unit="cases", location=" Bay 3 "))
    (obs,) = db.inserted_observations
    assert obs["quantity_entered"] == 30 and obs["unit_entered"] == "cases" and obs["pieces_per_case"] == 24.0
    assert obs["quantity_pieces"] == 720.0 and obs["context"] == "dismissal_request" and obs["dismissal_request_key"] == 4
    assert obs["location"] == "Bay 3" and obs["reported_by"] == "staff@ssmcapstone.com" and obs["reporter_role"] == "staff"
    assert [a["action"] for a in db.audit] == ["Reorder Dismissal Requested", "Stock Count Reported"]
    assert "30 cases = 720 pieces at 24 per case" in db.audit[1]["details"] and "unverified" in db.audit[1]["details"]
    assert out.stock_observation.quantity_pieces == 720.0


@pytest.mark.parametrize("quantity, unit, pack, pieces, per_case", [
    (2000, "cases", 24, 48000.0, 24.0),     # 24 pieces a case: 2,000 cases are 48,000 pieces
    (20, "cases", 288, 5760.0, 288.0),      # a different product, a different ratio
    (1500.5, "pieces", 24, 1500.5, None),   # pieces need no pack size
    (0, "cases", 12, 0.0, 12.0),
])
def test_unit_conversion(quantity, unit, pack, pieces, per_case):
    assert stock_observation.to_pieces(quantity, unit, pack) == (pieces, per_case)


@pytest.mark.parametrize("pack", [None, 0])
def test_a_cases_count_without_a_pack_size_is_refused_not_guessed(pack):
    db = _DB(pack=pack)
    with pytest.raises(ApiError) as err:
        _ask(db, observation=StockObservationIn(quantity=3, unit="cases"))
    assert err.value.status_code == 422 and err.value.code == "no_case_size"
    assert db.run("INSERT INTO lp_dismissal_request") == [] and db.inserted_observations == []


def test_a_part_case_is_refused_before_anything_is_written():
    db = _DB()
    with pytest.raises(ApiError) as err:
        _ask(db, observation=StockObservationIn(quantity=2.5, unit="cases"))
    assert err.value.code == "not_whole_cases" and db.run("INSERT INTO lp_dismissal_request") == []


def test_only_pieces_and_cases_are_units():
    with pytest.raises(ValidationError):
        StockObservationIn(quantity=3, unit="packs")


def test_no_stock_on_hand_or_plan_figure_is_written_by_the_request_code():
    for path in ("backend/routers/reorder_requests.py", "backend/stock_observation.py"):
        code = (REPO / path).read_text(encoding="utf-8")
        assert not re.search(r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+inventory_fact", code, re.I), path
        assert not re.search(r"UPDATE\s+lp_recommendation", code, re.I), path   # only decide_row writes the row
        assert not re.search(r"\b(q_i|rop_i|ss_i)\s*=", code), path


def test_nothing_in_the_plan_reads_the_new_tables():
    readers = []
    for root in ("analytics", "scripts", "transform"):
        for path in (REPO / root).rglob("*"):
            if path.suffix not in (".py", ".sql") or "__pycache__" in path.parts:
                continue
            # The migrations that create the tables, and 0071's notification table (a foreign key to a request,
            # read by the bell only), are not plan readers.
            if path.name.startswith(("0070_", "0071_")):
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            if "lp_stock_observation" in body or "lp_dismissal_request" in body:
                readers.append(path.relative_to(REPO).as_posix())
    assert readers == []


# ── 3. the admin settles a dismissal request ───────────────────────────────────────────────────────────────

def test_approving_makes_the_ordinary_dismiss_in_the_requesters_name():
    db = _DB(request=_request_row())
    out = rr.approve_dismissal(4, None, db=db, admin=ADMIN)
    assert out.state == "approved" and out.resolved_by == "admin@ssmcapstone.com"
    (_, params), = db.run("UPDATE lp_recommendation lr")
    assert params["status"] == "dismissed" and params["decided_by"] == "staff@ssmcapstone.com"
    assert params["reason"] == "Still 30 cases on the shelf" and params["decided_q"] is None
    # settled first, then the dismiss, in one transaction
    assert db.index("UPDATE lp_dismissal_request") < db.index("UPDATE lp_recommendation lr") and db.commits == 1
    (entry,) = db.audit
    assert entry["action"] == "Reorder Dismissal Request Approved" and "requested by staff@ssmcapstone.com" in entry["details"]
    assert entry["user_email"] == "admin@ssmcapstone.com"


def test_approval_locks_the_request_and_the_recommendation():
    assert rr._REQUEST_LOCKED_SQL.rstrip().endswith("FOR UPDATE OF d, lr")


def test_a_stale_request_is_not_approved_against_the_new_figure():
    db = _DB(q_i=50000.0, request=_request_row())   # the LP reran since: 47,160 -> 50,000
    with pytest.raises(ApiError) as err:
        rr.approve_dismissal(4, None, db=db, admin=ADMIN)
    assert err.value.status_code == 409 and err.value.code == "recommendation_changed"
    assert db.run("UPDATE lp_dismissal_request") == [] and db.run("UPDATE lp_recommendation") == []
    assert db.rolled_back and db.commits == 0


def test_a_request_on_a_superseded_cycle_is_closed_not_left_in_the_queue():
    db = _DB(current_cycle=datetime.date(2026, 4, 1), request=_request_row())
    with pytest.raises(HTTPException) as err:
        rr.approve_dismissal(4, None, db=db, admin=ADMIN)
    assert err.value.status_code == 409 and "closed" in err.value.detail
    (_, params), = db.run("UPDATE lp_dismissal_request")
    assert params["state"] == "rejected" and "superseded" in params["note"]
    assert db.run("UPDATE lp_recommendation") == [] and db.commits == 1
    assert db.audit[0]["action"] == "Reorder Dismissal Request Closed"


@pytest.mark.parametrize("state", ["approved", "rejected"])
def test_a_settled_request_is_not_settled_twice(state):
    db = _DB(request=_request_row(state=state, resolved_by="a@x", resolved_at=ASKED_AT))
    with pytest.raises(HTTPException) as err:
        rr.approve_dismissal(4, None, db=db, admin=ADMIN)
    assert err.value.status_code == 409 and "decided once" in err.value.detail and db.run("UPDATE lp_") == []


def test_nobody_settles_their_own_request():
    db = _DB(request=_request_row(requested_by="admin@ssmcapstone.com"))
    for call in (lambda: rr.approve_dismissal(4, None, db=db, admin=ADMIN),
                 lambda: rr.reject_dismissal(4, RejectRequest(reason="stock is fine"), db=db, admin=ADMIN)):
        with pytest.raises(ApiError) as err:
            call()
        assert err.value.status_code == 409 and err.value.code == "self_approval"
    assert db.run("UPDATE lp_") == []


def test_rejecting_keeps_the_recommendation_active_and_the_request_as_the_record():
    db = _DB(request=_request_row())
    out = rr.reject_dismissal(4, RejectRequest(reason=" We are out on the floor "), db=db, admin=ADMIN)
    assert out.state == "rejected" and out.resolution_note == "We are out on the floor"
    assert db.run("UPDATE lp_recommendation") == [] and db.commits == 1
    (entry,) = db.audit
    assert entry["action"] == "Reorder Dismissal Request Rejected" and "stays active" in entry["details"]
    assert "We are out on the floor" in entry["details"]


def test_a_refused_dismiss_rolls_the_settlement_back():
    db = _DB(request=_request_row(), decide_matches=False)
    with pytest.raises(HTTPException):
        rr.approve_dismissal(4, ApprovalNote(note="ok"), db=db, admin=ADMIN)
    assert db.rolled_back and db.commits == 0


# ── 4. the guards the new request adds to the existing paths ────────────────────────────────────────────────

def test_a_direct_decision_is_refused_while_a_dismissal_request_waits():
    db = _DB(decide_matches=False, open_dismissal={"request_key": 4, "requested_by": "staff@ssmcapstone.com"})
    with pytest.raises(HTTPException) as err:
        rec.update_recommendation(1, RecommendationDecision(status="accepted"), db=db, current_user=ADMIN)
    assert err.value.status_code == 409 and "dismissal request awaiting approval (request 4" in err.value.detail
    (sql, _), = db.run("UPDATE lp_recommendation lr")
    assert "FROM lp_dismissal_request dr" in sql and "dr.state = 'pending_approval'" in sql


def test_without_0070_the_decision_guard_is_unchanged():
    db = _DB(requests=False)
    rec.update_recommendation(1, RecommendationDecision(status="accepted"), db=db, current_user=ADMIN)
    (sql, _), = db.run("UPDATE lp_recommendation lr")
    assert "lp_dismissal_request" not in sql and "lp_quantity_change qc" in sql


def test_a_quantity_change_is_refused_while_a_dismissal_request_waits():
    db = _DB(open_dismissal={"request_key": 4, "requested_by": "other@ssmcapstone.com"})
    response = type("R", (), {"status_code": 200})()
    with pytest.raises(HTTPException) as err:
        ra.change_quantity(1, QuantityChangeRequest(quantity=48000, reason="Complete the cases"), response, db=db,
                           current_user=STAFF)
    assert err.value.status_code == 409 and "dismissal request awaiting approval" in err.value.detail
    assert db.rolled_back and db.commits == 0 and db.audit == []


def test_a_quantity_change_needs_a_reason():
    for reason in ("", "  "):
        with pytest.raises(ValidationError):
            QuantityChangeRequest(quantity=48000, reason=reason)
    with pytest.raises(ValidationError):
        QuantityChangeRequest(quantity=48000)


def test_a_held_quantity_change_carries_its_stock_count_and_the_cases_in_the_log():
    db = _DB(observations=[_observation_row(context="quantity_change", quantity_change_key=7, dismissal_request_key=None)])
    response = type("R", (), {"status_code": 200})()
    out = ra.change_quantity(1, QuantityChangeRequest(quantity=48000, reason="Complete the cases",
                                                      stock_observation=StockObservationIn(quantity=30, unit="cases")),
                             response, db=db, current_user=STAFF)
    assert response.status_code == 202 and out.outcome == "held"
    (obs,) = db.inserted_observations
    assert obs["context"] == "quantity_change" and obs["quantity_change_key"] == 7 and obs["quantity_pieces"] == 720.0
    proposed = next(a for a in db.audit if a["action"] == "Reorder Quantity Change Proposed")
    assert "47160 -> 48000 (2000 cases of 24)" in proposed["details"] and "Complete the cases" in proposed["details"]
    assert db.run("UPDATE lp_recommendation") == []   # still only a proposal
    assert out.change.stock_observation.quantity_pieces == 720.0


def test_a_stock_count_never_rides_on_a_change_that_applies_at_once():
    db = _DB()
    response = type("R", (), {"status_code": 200})()
    with pytest.raises(ApiError) as err:
        ra.change_quantity(1, QuantityChangeRequest(quantity=48000, reason="Complete the cases",
                                                    stock_observation=StockObservationIn(quantity=30)),
                           response, db=db, current_user=ADMIN)
    assert err.value.code == "observation_needs_request" and db.run("UPDATE lp_recommendation") == []


def test_an_admin_does_not_approve_a_quantity_change_they_proposed():
    db = _DB()
    db.execute = _with_change_by(db, "admin@ssmcapstone.com")
    with pytest.raises(ApiError) as err:
        ra.approve_change(7, None, db=db, admin=ADMIN)
    assert err.value.code == "self_approval" and db.rolled_back


def _with_change_by(db, email):
    inner = db.execute

    def execute(stmt, params=None):
        if "FROM lp_quantity_change c" in str(stmt) and "change_key = :change_key" in str(stmt):
            db.sql.append((str(stmt), dict(params or {})))
            return FakeResult([{"change_key": 7, "recommendation_key": 1, "sku_code": "U-1", "product_name": "Uni One",
                                "planning_cycle_date": CYCLE, "recommended_q_i": 47160.0, "proposed_q_i": 48000.0,
                                "reason": "x", "reviewed": False, "state": "pending_approval", "proposed_by": email,
                                "proposed_at": ASKED_AT, "resolved_by": None, "resolved_at": None,
                                "resolution_note": None, "reversed_by": None, "reversed_at": None}])
        return inner(stmt, params)
    return execute


# ── 5. an admin's direct dismissal, with a count ───────────────────────────────────────────────────────────

def test_a_direct_dismissal_records_its_count_apart_from_a_requested_one():
    db = _DB()
    rec.update_recommendation(1, RecommendationDecision(
        status="dismissed", reason="Warehouse still holds 30 cases",
        stock_observation=StockObservationIn(quantity=30, unit="cases", notes="checked with the storekeeper")),
        db=db, current_user=ADMIN)
    assert [a["action"] for a in db.audit] == ["Reorder Recommendation Dismissed", "Stock Count Reported"]
    (obs,) = db.inserted_observations
    assert obs["context"] == "direct_dismissal" and obs["quantity_change_key"] is None and obs["dismissal_request_key"] is None
    assert obs["reporter_role"] == "admin" and db.commits == 1


def test_a_direct_dismissal_with_a_bad_count_writes_nothing():
    db = _DB(pack=None)
    with pytest.raises(ApiError) as err:
        rec.update_recommendation(1, RecommendationDecision(
            status="dismissed", reason="no longer stocked", stock_observation=StockObservationIn(quantity=3, unit="cases")),
            db=db, current_user=ADMIN)
    assert err.value.code == "no_case_size" and db.run("UPDATE lp_recommendation") == [] and db.audit == []


def test_a_count_goes_with_a_dismissal_not_an_accept():
    with pytest.raises(ValidationError):
        RecommendationDecision(status="accepted", stock_observation=StockObservationIn(quantity=3))


# ── 6. verifying a count records the check, nothing else ───────────────────────────────────────────────────

def test_an_admin_verifies_a_count_and_no_stock_changes():
    db = _DB(observations=[_observation_row()])
    rr.verify_stock_observation(11, VerifyObservationBody(verified=True), db=db, admin=ADMIN)
    (_, params), = db.run("UPDATE lp_stock_observation")
    assert params["state"] == "verified" and params["by"] == "admin@ssmcapstone.com"
    assert db.audit[0]["action"] == "Stock Count Verified" and "stock on hand and the order plan are unchanged" in db.audit[0]["details"]
    assert not any(re.search(r"(INSERT\s+INTO|UPDATE)\s+(inventory_fact|lp_recommendation)", s, re.I) for s, _ in db.sql)


def test_rejecting_a_count_needs_a_note():
    with pytest.raises(ValidationError):
        VerifyObservationBody(verified=False, note=" ")


@pytest.mark.parametrize("over, code", [
    ({"verification_state": "verified", "verified_by": "a@x", "verified_at": ASKED_AT}, None),
    ({"reported_by": "admin@ssmcapstone.com"}, "self_approval"),
])
def test_a_count_is_checked_once_and_not_by_its_reporter(over, code):
    db = _DB(observations=[_observation_row(**over)])
    with pytest.raises((HTTPException, ApiError)) as err:
        rr.verify_stock_observation(11, VerifyObservationBody(verified=True), db=db, admin=ADMIN)
    assert err.value.status_code == 409 and getattr(err.value, "code", None) == code
    assert db.run("UPDATE lp_stock_observation") == []


# ── 7. who sees what ───────────────────────────────────────────────────────────────────────────────────────

def test_the_routes_need_the_right_keys_and_the_settling_ones_the_admin_role():
    routes = {r.endpoint.__name__: r for r in rr.router.routes}

    def keys(name):
        dep = next(d for d in routes[name].dependant.dependencies if getattr(d.call, "permission_keys", None)
                   or d.call is rr.require_lp_admin)
        return getattr(dep.call, "permission_keys", "admin")
    assert keys("request_dismissal") == ("lp.propose",)
    assert keys("list_dismissal_requests") == ("lp.decide", "lp.propose")
    assert keys("open_requests") == ("lp.view",)
    for name in ("approve_dismissal", "reject_dismissal", "verify_stock_observation"):
        assert routes[name].dependant.dependencies[-1].call is rr.require_lp_admin
    with pytest.raises(ApiError) as err:   # lp.decide ticked for a staff account is still not an admin
        rr.require_lp_admin(current_user=STAFF)
    assert err.value.code == "admin_required"


def test_a_non_admin_lists_only_their_own_requests_and_counts():
    db = _DB(request=_request_row())
    rr.list_dismissal_requests(state="all", recommendation_key=None, db=db, current_user=STAFF)
    rr.list_stock_observations(state="all", recommendation_key=None, db=db, current_user=STAFF)
    (_, p1), = db.run("ORDER BY d.requested_at DESC")
    (_, p2), = db.run("ORDER BY o.reported_at DESC")
    assert p1["me"] == p2["me"] == "staff@ssmcapstone.com"


def test_open_requests_name_the_requester_only_to_an_admin_or_themselves():
    db = _DB()
    rows = [{"kind": "dismissal", "key": 4, "recommendation_key": 1, "recommended_q_i": 47160.0, "proposed_q_i": None,
             "requested_at": ASKED_AT, "requested_by": "staff@ssmcapstone.com"}]
    db.execute = (lambda inner: lambda stmt, params=None: FakeResult(rows) if "UNION ALL" in str(stmt) else inner(stmt, params))(db.execute)
    assert rr.open_requests(db=db, current_user=OTHER).items[0].requested_by is None
    mine = rr.open_requests(db=db, current_user=STAFF).items[0]
    assert mine.mine and mine.requested_by == "staff@ssmcapstone.com"
    assert rr.open_requests(db=db, current_user=ADMIN).items[0].requested_by == "staff@ssmcapstone.com"


def test_the_history_runs_oldest_first_and_hides_other_peoples_requests_from_staff():
    change = {"change_key": 7, "recommendation_key": 1, "sku_code": "U-1", "product_name": "Uni One",
              "planning_cycle_date": CYCLE, "recommended_q_i": 47160.0, "proposed_q_i": 48000.0, "reason": "cases",
              "reviewed": False, "state": "approved", "proposed_by": "other@ssmcapstone.com",
              "proposed_at": ASKED_AT, "resolved_by": "admin@ssmcapstone.com",
              "resolved_at": ASKED_AT + datetime.timedelta(hours=1), "resolution_note": None,
              "reversed_by": None, "reversed_at": None}
    db = _DB(changes=[change], request=_request_row(), observations=[_observation_row()])
    admin_view = rr.recommendation_history(1, db=db, current_user=ADMIN)
    kinds = [e.kind for e in admin_view.events]
    assert kinds[0] == "recommended" and "change_proposed" in kinds and "change_approved" in kinds
    assert "dismissal_requested" in kinds and "stock_reported" in kinds
    assert [e.at for e in admin_view.events] == sorted(e.at for e in admin_view.events)
    staff_view = rr.recommendation_history(1, db=_DB(changes=[change]), current_user=STAFF)
    assert [e.kind for e in staff_view.events] == ["recommended"]


# ── 8. the migration ───────────────────────────────────────────────────────────────────────────────────────

def _migration() -> str:
    return (REPO / "analytics/db/migrations/0070_lp_dismissal_request_stock_observation.sql").read_text(encoding="utf-8")


def test_the_migration_is_additive_and_states_its_rules():
    sql = _migration()
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert not re.search(r"\b(DELETE|TRUNCATE|UPDATE|DROP)\b", body, re.I)
    assert all(";" not in l for l in sql.splitlines() if l.strip().startswith("--"))
    assert "ux_lp_dismissal_request_one_open" in sql and "WHERE state = 'pending_approval'" in sql
    assert "length(btrim(request_reason)) > 0" in sql
    assert "quantity_pieces = ROUND(quantity_entered * pieces_per_case, 2)" in sql
    assert "unit_entered IN ('pieces', 'cases')" in sql
    assert "verification_state IN ('unverified', 'verified', 'rejected')" in sql
    assert "DROP TABLE IF EXISTS lp_stock_observation, lp_dismissal_request" in sql   # the rollback, in a comment
