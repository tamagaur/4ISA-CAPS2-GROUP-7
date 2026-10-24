"""The shape of the settlement SQL (analytics/receipt_settlement.py). Its behaviour on real rows is proved in
tests/etl/test_rollover_scratch.py (scratch schema)."""
from __future__ import annotations

import re

from analytics import receipt_settlement as rs

NORM = lambda s: " ".join(s.split())


def test_only_a_count_dated_on_or_after_expected_on_settles_a_receipt():
    sql = NORM(rs.SETTLE_SQL)
    assert "er.state = 'expected' AND er.expected_on <= cnt.d" in sql      # the candidate rule
    assert "SET state = 'arrived_in_count'" in sql and "settled_by_count_date = (SELECT d FROM cnt)" in sql


def test_nothing_is_corrected_or_deleted():
    for sql in (rs.SETTLE_SQL, rs.RETEST_SQL):
        assert not re.search(r"\b(DELETE|INSERT|TRUNCATE|DROP)\b", sql, re.I)
        assert re.findall(r"UPDATE (\w+)", sql) == ["expected_receipt"]        # the only table it writes
    assert re.search(r"\bUPDATE\b", rs.SELECT_SQL) is None                      # the dry run reads


def test_not_visible_is_only_claimed_where_the_month_could_be_tested():
    sql = NORM(rs.SETTLE_SQL)
    assert "not_visible_in_count = CASE WHEN ev.tested THEN ev.implied_receipts <= 0 ELSE false END" in sql
    assert "stock_change_pieces = CASE WHEN ev.tested THEN ev.implied_receipts END" in sql
    ev = NORM(rs.EVIDENCE_CTE)
    # tested needs the month's sales loaded AND a previous count that was taken
    assert "sl.loaded AND pt.taken" in ev
    # the implied receipts are derived_receipt_fact's definition: closing - opening + sold
    assert "COALESCE(cur.pieces, 0) - COALESCE(old.pieces, 0) + COALESCE(s.q, 0) AS implied_receipts" in ev


def test_a_settled_receipt_is_retested_once_and_only_when_untested():
    sql = NORM(rs.RETEST_SQL)
    assert "er.stock_change_pieces IS NULL" in sql and "er.settled_by_period = %(p)s" in sql
    assert "AND ev.tested" in sql
