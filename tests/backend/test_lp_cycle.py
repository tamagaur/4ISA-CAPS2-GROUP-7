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
