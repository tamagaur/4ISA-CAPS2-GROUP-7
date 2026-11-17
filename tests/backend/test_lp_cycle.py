"""
tests/backend/test_lp_cycle.py — backend/lp_cycle.py's anchors resolve under
the same principal scope as the rows they anchor.

principal_clause (backend/principals.py) reads a principal case-insensitively,
so 'Unilever' and 'unilever' scope the rows identically. The LP-cycle anchors
used to bind the raw string, so a capitalised principal filtered the rows
correctly while its cycle resolved to nothing — against commit fd4dded's rule
that anchors and rows share one scope.
"""
from __future__ import annotations

import datetime

import pytest

from backend import lp_cycle


class _CaptureDB:
    def __init__(self):
        self.params: dict | None = None

    def execute(self, stmt, params=None):
        self.params = dict(params or {})

        class _Result:
            def mappings(self):
                return self

            def first(self):
                return {"d": None}

            def scalar(self):
                return 0

        return _Result()


@pytest.mark.parametrize("raw", ["Unilever", " unilever ", "UNILEVER"])
def test_the_cycle_anchor_reads_the_principal_like_the_rows_do(raw):
    db = _CaptureDB()
    lp_cycle.current_cycle(db, raw)
    assert db.params["principal"] == "unilever"
    lp_cycle.superseded_count(db, datetime.date(2026, 3, 1), raw)
    assert db.params["principal"] == "unilever"


@pytest.mark.parametrize("raw", [None, "", "all", "ALL", " All "])
def test_all_or_blank_means_no_principal_filter(raw):
    db = _CaptureDB()
    lp_cycle.current_cycle(db, raw)
    assert "principal" not in db.params


def test_every_current_cycle_subquery_of_the_decision_routes_applies_the_plan_rule():
    """The decision, approval and request routes find "the principal's current cycle" in SQL of their own. Each such
    subquery must apply the plan rule (lp_cycle.PLAN_STATUS_SQL on alias l2), or a decided row no LP run produced could
    make a cycle current for writes that every page treats as not current (found 2026-11-17)."""
    import re
    from pathlib import Path

    from backend.lp_cycle import PLAN_STATUS_SQL_L2
    repo = Path(__file__).resolve().parents[2]
    rule = " ".join(PLAN_STATUS_SQL_L2.strip("()").split())
    seen = 0
    for name in ("recommendations.py", "reorder_approval.py", "reorder_requests.py"):
        src = (repo / "backend" / "routers" / name).read_text(encoding="utf-8")
        for m in re.finditer(r"SELECT MAX\(l2\.planning_cycle_date\) FROM lp_recommendation l2(.*?)\)\s*(AS current_cycle|\"\"\"|$)",
                             src, re.S | re.M):
            seen += 1
            body = " ".join(m.group(1).split())
            assert rule.replace("(", "").replace(")", "") in body.replace("(", "").replace(")", ""), (name, body)
    assert seen >= 6, seen
