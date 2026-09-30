"""tests/backend/test_stock_status.py — item 9: one stock-status rule
(backend/stock_status.py) for every screen, and GET /inventory/current on it."""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.stock_status import CRITICAL, LOW, NO_DATA, NO_TARGET, OK, stock_status


@pytest.mark.parametrize("stock, expected", [
    (0.0, CRITICAL), (49.9, CRITICAL),   # below SS
    (50.0, LOW), (99.9, LOW),            # SS <= stock < T
    (100.0, OK), (500.0, OK),            # at or above the target
])
def test_the_boundaries_are_ss_and_the_target(stock, expected):
    assert stock_status(stock, 50.0, 100.0) == expected


def test_no_stock_figure_or_no_lp_row_is_said_not_guessed():
    assert stock_status(None, 50.0, 100.0) == NO_DATA
    assert stock_status(10.0, None, None) == NO_TARGET


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-do-not-use-in-prod")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "1")
    yield
    app.dependency_overrides.clear()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _InventorySession:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, dict(params or {})))
        if "MAX(lr.planning_cycle_date) AS d" in sql:
            return _Result([{"d": datetime.date(2026, 3, 1)}])
        if "FROM lp_recommendation" in sql and "inventory_fact_real" in sql:
            return _Result(self.rows)
        raise AssertionError(f"Unexpected query: {sql}")

    def close(self):
        pass


def test_inventory_current_is_the_latest_snapshot_in_pieces_on_the_shared_rule():
    session = _InventorySession([
        {"sku_code": "A", "principal": "unilever", "product_name": "a", "current_stock": 10.0, "ss_i": 50.0, "rop_i": 100.0},
        {"sku_code": "B", "principal": "unilever", "product_name": "b", "current_stock": 150.0, "ss_i": 50.0, "rop_i": 100.0},
        {"sku_code": "C", "principal": "unilever", "product_name": "c", "current_stock": 150.0, "ss_i": None, "rop_i": None},
        {"sku_code": "D", "principal": "unilever", "product_name": "d", "current_stock": None, "ss_i": 50.0, "rop_i": 100.0},
    ])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="staff", full_name="Staff"))
    with TestClient(app) as c:
        body = c.get("/inventory/current?principal=unilever").json()
    assert {r["sku"]: r["status"] for r in body} == {"A": CRITICAL, "B": OK, "C": NO_TARGET, "D": NO_DATA}
    assert all(r["unit"] == "pieces" for r in body)
    main_sql = next(sql for sql, _ in session.calls if "inventory_fact_real" in sql)
    assert "latest_period" in main_sql and "SUM(i.quantity_on_hand)" not in main_sql
