"""
tests/backend/test_batch.py — backend/batch.py: several reads in one round trip.

No database: a real (unbound) SQLAlchemy Session whose execute() is replaced, so
prefetch() runs its batching path, and the fake answers the one combined statement
with the JSON text Postgres would send back.
"""
from __future__ import annotations

import datetime
import json

from sqlalchemy.orm import Session

from backend import batch


class _Row(tuple):
    pass


class _OneResult:
    def __init__(self, values):
        self._values = values

    def one(self):
        return _Row(self._values)


def _session(answers):
    """A Session whose execute() records the statement and returns `answers`
    (one JSON-able list of rows per batched query, in order)."""
    db = Session()
    db.calls = []

    def execute(stmt, params=None):
        db.calls.append((str(stmt), dict(params or {})))
        return _OneResult([json.dumps(a) for a in answers])

    db.execute = execute
    return db


def test_queries_share_one_statement_with_their_binds_kept_apart():
    db = _session([[{"p": "2026-02"}], [{"d": "2026-03-01"}]])
    ran = batch.prefetch(db, [
        ("SELECT MAX(classification_period) AS p FROM abc WHERE principal = :principal", {"principal": "unilever"}),
        ("SELECT MAX(planning_cycle_date) AS d FROM lp WHERE principal = :principal", {"principal": "delmonte"}),
    ])
    assert ran == 2
    assert len(db.calls) == 1
    sql, params = db.calls[0]
    assert ":q0_principal" in sql and ":q1_principal" in sql
    assert params == {"q0_principal": "unilever", "q1_principal": "delmonte"}
    # Answered from the batch, with no further statement.
    assert batch.first(db, "SELECT MAX(classification_period) AS p FROM abc WHERE principal = :principal",
                       {"principal": "unilever"}) == {"p": "2026-02"}
    assert batch.scalar(db, "SELECT MAX(planning_cycle_date) AS d FROM lp WHERE principal = :principal",
                        {"principal": "delmonte"}) == datetime.date(2026, 3, 1)
    assert len(db.calls) == 1


def test_a_cast_is_not_mistaken_for_a_bind():
    """Renamed by SQLAlchemy text()'s own rule: ':name' is a bind, '::type' a cast."""
    db = _session([[{"n": 1}]])
    batch.prefetch(db, [("SELECT CAST(:x AS int) AS n, '2026'::text AS t", {"x": 1})])
    sql, params = db.calls[0]
    assert "CAST(:q0_x AS int)" in sql and "'2026'::text" in sql and params == {"q0_x": 1}


def test_extra_params_do_not_change_the_query_identity():
    """Callers pass extra params a query doesn't bind (e.g. current_cycle when the
    cycle filter is AND 1=0); the batch is still found."""
    db = _session([[{"c": 3}]])
    batch.prefetch(db, [("SELECT COUNT(*) AS c FROM t WHERE 1=0", {"current_cycle": None})])
    assert batch.scalar(db, "SELECT COUNT(*) AS c FROM t WHERE 1=0", {"current_cycle": "2026-03-01"}) == 3


def test_dates_and_timestamps_come_back_as_python_types():
    db = _session([[{"day": "2026-03-02", "at": "2026-10-04T12:03:59.86784+00:00", "period": "2026-02",
                     "n": 2.5, "flag": None}]])
    batch.prefetch(db, [("SELECT 1", {})])
    row = batch.first(db, "SELECT 1")
    assert row["day"] == datetime.date(2026, 3, 2)
    assert row["at"] == datetime.datetime(2026, 10, 4, 12, 3, 59, 867840, tzinfo=datetime.timezone.utc)
    assert row["period"] == "2026-02"  # a month stays text
    assert row["n"] == 2.5 and row["flag"] is None


def test_a_query_not_prefetched_runs_on_its_own():
    db = Session()
    seen = []

    class _R:
        def mappings(self):
            return self

        def all(self):
            return [{"x": 1}]

    db.execute = lambda stmt, params=None: seen.append(str(stmt)) or _R()
    assert batch.rows(db, "SELECT 1 AS x") == [{"x": 1}]
    assert seen == ["SELECT 1 AS x"]


def test_known_queries_are_not_run_twice_and_empty_results_are_kept():
    db = _session([[]])
    assert batch.prefetch(db, [("SELECT 1 WHERE false", {})]) == 1
    assert batch.prefetch(db, [("SELECT 1 WHERE false", {})]) == 0
    assert batch.first(db, "SELECT 1 WHERE false") is None
    assert batch.rows(db, "SELECT 1 WHERE false") == []
    assert len(db.calls) == 1


def test_a_fake_session_is_never_batched():
    """The tests' fakes match on each query's own text: prefetch leaves them alone."""
    class Fake:
        info: dict = {}

        def execute(self, stmt, params=None):
            raise AssertionError("prefetch must not reach a fake session")

    assert batch.prefetch(Fake(), [("SELECT 1", {})]) == 0
