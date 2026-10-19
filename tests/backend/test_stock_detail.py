"""backend.marts.stock_detail — the products behind the Inventory value and Stock
cover cards (2026-10-19). Each product's weekly sales use the portfolio's own months
and divisor, so the list's totals are the cards' figures; pesos above SSM's rule are
max(0, stock - policy weeks x weekly sales), product by product."""
from __future__ import annotations

import pytest

from backend import marts

WINDOW = [f"2025-{m:02d}" for m in range(3, 13)] + ["2026-01", "2026-02"]
WEEKS_PER_MONTH = 4.33


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def execute(self, stmt, params=None):
        sql = str(stmt)
        assert "WITH stock AS" in sql and "mart.inventory_mart_real" in sql and "mart.sales_mart" in sql
        assert "data_kind = 'real'" in sql and "level = 'product'" in sql, "real product-level sales only"
        self.params = params
        return FakeResult(self.rows)


def _row(key, pesos, sales, pieces=100.0):
    return {"product_key": key, "sku_code": f"SKU{key}", "product_name": f"Product {key}",
            "category_path": "CAT", "pesos": pesos, "pieces": pieces, "sales_pesos": sales}


@pytest.fixture
def monthly(monkeypatch):
    """Twelve months on record; the portfolio sold 1,200 a month across all products."""
    def fake_sales_by_period(db, periods, principal, mode="real"):
        return {p: 1_200.0 for p in periods}
    monkeypatch.setattr(marts, "sales_by_period", fake_sales_by_period)
    monkeypatch.setattr(marts, "count_dates", lambda db, periods, scope: {"2026-02": "2026-03-02"})


def test_each_products_cover_and_pesos_above_the_rule(monthly):
    # weekly = 12-month sales / 12 / 4.33
    db = FakeDB([
        _row(1, 2_000.0, 12 * 433.0),   # 433 a month -> 100 a week -> 20 weeks; above 3 wks: 2,000 - 300 = 1,700
        _row(2, 200.0, 12 * 433.0),     # 100 a week -> 2 weeks: within the rule, 0 above
        _row(3, 500.0, None),           # no sale in the window: all 500 is beyond the rule
    ])
    out = marts.stock_detail(db, "unilever", "2026-02", WINDOW, 3, WEEKS_PER_MONTH)
    items = {i["product_key"]: i for i in out["items"]}
    assert items[1]["weekly_sales"] == pytest.approx(100.0)
    assert items[1]["weeks_of_cover"] == pytest.approx(20.0)
    assert items[1]["above_rule_pesos"] == pytest.approx(1_700.0)
    assert items[2]["weeks_of_cover"] == pytest.approx(2.0)
    assert items[2]["above_rule_pesos"] == 0
    assert items[3]["weeks_of_cover"] is None and items[3]["no_sale_in_window"]
    assert items[3]["above_rule_pesos"] == pytest.approx(500.0)
    t = out["totals"]
    assert t["pesos"] == pytest.approx(2_700.0)
    assert t["above_rule_pesos"] == pytest.approx(2_200.0)
    assert t["above_rule_products"] == 2
    assert t["no_sale_products"] == 1
    # The card's cover: total stock over the PORTFOLIO's weekly sales (1,200 a month).
    assert t["weeks_of_cover"] == pytest.approx(2_700.0 / (1_200.0 / WEEKS_PER_MONTH), abs=0.01)
    assert out["months_used"] == 12
    assert out["sales_window"] == {"start": "2025-03", "end": "2026-02"}
    assert out["count_date"] == "2026-03-02"
    assert db.params["start"] == "2025-03" and db.params["end"] == "2026-02"


def test_net_returns_never_raise_the_pesos_above_the_rule(monthly):
    """A product whose returns exceed its sales has no weekly sales, not negative ones."""
    out = marts.stock_detail(FakeDB([_row(1, 300.0, -50.0)]), "unilever", "2026-02", WINDOW, 3, WEEKS_PER_MONTH)
    assert out["items"][0]["above_rule_pesos"] == pytest.approx(300.0)


def test_del_monte_lists_stock_without_cover(monthly):
    out = marts.stock_detail(FakeDB([_row(1, 900.0, None, pieces=None)]), "delmonte", "2025-12", WINDOW, 3,
                             WEEKS_PER_MONTH)
    assert out["items"][0]["pesos"] == 900.0
    assert out["items"][0]["weeks_of_cover"] is None and out["items"][0]["above_rule_pesos"] is None
    assert out["totals"]["above_rule_pesos"] is None
    assert "category" in out["cover_blocked_reason"]


def test_no_count_is_a_reason_not_a_zero(monthly):
    out = marts.stock_detail(FakeDB([]), "unilever", None, WINDOW, 3, WEEKS_PER_MONTH)
    assert out["totals"] is None and out["items"] == []
    assert out["blocked_reason"]


def test_without_items_keeps_the_totals(monthly):
    out = marts.stock_detail(FakeDB([_row(1, 2_000.0, 12 * 433.0)]), "unilever", "2026-02", WINDOW, 3,
                             WEEKS_PER_MONTH, with_items=False)
    assert out["items"] == []
    assert out["totals"]["above_rule_pesos"] == pytest.approx(1_700.0)
