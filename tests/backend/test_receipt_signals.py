"""GET /inventory/receipt-signals: receipts a count settled that the count gives no sign of (migration 0069)."""
from __future__ import annotations

import datetime

from backend.routers import inventory as inv


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0] if self.rows else None


class _DB:
    def __init__(self, present=True):
        self.present = present

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "to_regclass('expected_receipt')" in sql:
            return _Result([self.present])
        if "GROUP BY settled_by_period" in sql:
            return _Result([
                {"period": "2026-03", "settled": 10, "not_visible": 2, "untested": 0, "pieces": 1000, "not_visible_pieces": 150},
                {"period": "2026-04", "settled": 4, "not_visible": 0, "untested": 4, "pieces": 400, "not_visible_pieces": 0}])
        if "er.not_visible_in_count ORDER" in sql or "AND er.not_visible_in_count" in sql:
            return _Result([{"receipt_id": 5, "sku_code": "U-1", "product_name": "One", "pieces": 100,
                             "settled_by_period": "2026-03", "settled_by_count_date": datetime.date(2026, 4, 6),
                             "expected_on": datetime.date(2026, 4, 2), "implied_receipts_in_count": -20}])
        if "state = 'expected'" in sql and "overdue" in sql:
            return _Result([{"receipts": 3, "pieces": 300, "overdue": 1}])
        if "FROM derived_receipt_fact" in sql:
            return _Result([{"period": "2026-02", "products": 852, "negative_balance": 175}])
        raise AssertionError(sql)


def _call(db):
    return inv.get_receipt_signals(limit=25, months=12, db=db, current_user=None)


def test_the_accumulation_is_visible_next_to_the_derived_receipts_check():
    out = _call(_DB())
    assert out["totals"] == {"settled": 14, "tested": 10, "not_visible": 2, "not_visible_share": 0.2}
    march, april = out["by_period"]
    assert march["not_visible_share"] == 0.2 and april["not_visible_share"] is None   # April is untested, not clean
    assert out["not_visible_receipts"][0]["implied_receipts_in_count"] == -20.0
    assert out["derived_receipts"][0]["negative_share"] == round(175 / 852, 4)
    assert out["open_receipts"] == {"receipts": 3, "pieces": 300.0, "overdue": 1}


def test_it_says_so_where_the_ledger_is_not_built():
    out = _call(_DB(present=False))
    assert out["available"] is False and "0069" in out["blocked_reason"]
