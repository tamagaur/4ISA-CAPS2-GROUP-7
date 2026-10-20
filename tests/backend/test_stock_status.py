"""tests/backend/test_stock_status.py — item 9: one stock-status rule
(backend/stock_status.py) for every screen, and GET /inventory/current on it."""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from backend import auth_utils
from backend.deps import get_current_user, get_db
from backend.main import app
from backend.stock_status import (
    COUNT_OMITS_ZERO_STOCK, CRITICAL, IN_STOCK, LOW, NO_DATA, NO_ROP, PLANNED, URGENCY, URGENCY_RANK, URGENT,
    stock_status,
)


@pytest.mark.parametrize("stock, expected", [
    (0.0, CRITICAL), (49.9, CRITICAL),   # below SS
    (50.0, LOW), (99.9, LOW),            # SS <= stock < T
    (100.0, IN_STOCK), (500.0, IN_STOCK),  # at or above the target
])
def test_the_boundaries_are_ss_and_the_target(stock, expected):
    assert stock_status(stock, 50.0, 100.0) == expected


def test_no_stock_row_is_no_data_whatever_the_plan():
    assert stock_status(None, 50.0, 100.0, has_stock_row=False) == NO_DATA
    assert stock_status(None, None, None, has_stock_row=False) == NO_DATA
    assert stock_status(None, 50.0, 100.0) == NO_DATA  # no row inferred from no pieces


def test_a_stock_row_without_a_plan_is_no_rop():
    assert stock_status(10.0, None, None) == NO_ROP
    # Del Monte: stock on file in cases (no pack size, so no pieces) and no LP row.
    assert stock_status(None, None, None, has_stock_row=True) == NO_ROP


def test_a_planned_row_without_pieces_is_no_data():
    assert stock_status(None, 50.0, 100.0, has_stock_row=True) == NO_DATA



def test_the_labels_are_the_ones_the_frontend_reads():
    """Audrey's names (2026-10-01): frontend/src reads 'IN STOCK' and 'NO ROP';
    params consolidation's 'OK' / 'NOT PLANNED' were renamed at the merge."""
    assert (CRITICAL, LOW, IN_STOCK, NO_ROP, NO_DATA) == ("CRITICAL", "LOW", "IN STOCK", "NO ROP", "NO DATA")


def test_urgency_is_the_same_rule_under_the_reorder_pages_names():
    assert URGENCY == {CRITICAL: "CRITICAL", LOW: "URGENT", IN_STOCK: "PLANNED", NO_DATA: "NO DATA"}
    assert (URGENT, PLANNED) == ("URGENT", "PLANNED")
    assert sorted(URGENCY_RANK, key=URGENCY_RANK.get) == ["CRITICAL", "URGENT", "PLANNED"]


def test_only_unilevers_count_omits_zero_stock_items():
    """Checked 2026-10-02: no Unilever SOH row ever reads 0/0; Del Monte's
    inventory files list Quantity-0 rows (backend/stock_status.py)."""
    assert COUNT_OMITS_ZERO_STOCK == {"unilever"}

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
        {"sku_code": "A", "principal": "unilever", "product_name": "a", "current_stock": 10.0, "current_stock_cases": 1.0, "ss_i": 50.0, "rop_i": 100.0},
        {"sku_code": "B", "principal": "unilever", "product_name": "b", "current_stock": 150.0, "current_stock_cases": 6.0, "ss_i": 50.0, "rop_i": 100.0},
        {"sku_code": "C", "principal": "unilever", "product_name": "c", "current_stock": 150.0, "current_stock_cases": 6.0, "ss_i": None, "rop_i": None},
        {"sku_code": "D", "principal": "unilever", "product_name": "d", "current_stock": None, "current_stock_cases": 3.0, "ss_i": 50.0, "rop_i": 100.0},
        {"sku_code": "E", "principal": "delmonte", "product_name": "e", "current_stock": None, "current_stock_cases": 12.0, "ss_i": None, "rop_i": None},
    ])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="staff", full_name="Staff"))
    with TestClient(app) as c:
        body = c.get("/inventory/current?principal=unilever").json()
    assert {r["sku"]: r["status"] for r in body} == {"A": CRITICAL, "B": IN_STOCK, "C": NO_ROP, "D": NO_DATA, "E": NO_ROP}
    # Pieces where the pack size allows; Del Monte (no pieces) keeps its stock in cases.
    assert {r["sku"]: (r["currentStock"], r["unit"]) for r in body} == {
        "A": (10.0, "pieces"), "B": (150.0, "pieces"), "C": (150.0, "pieces"), "D": (3.0, "cases"), "E": (12.0, "cases"),
    }
    main_sql = next(sql for sql, _ in session.calls if "inventory_fact_real" in sql)
    assert "latest_period" in main_sql and "SUM(i.quantity_on_hand)" not in main_sql


def test_inventory_current_serves_no_received_or_dispatched_zeros():
    """BE-6: receivedMts / dispatchedMts were hardcoded 0 (no per-SKU receipts exist). They are gone,
    not zero: a zero here would read as 'nothing was received'."""
    session = _InventorySession([
        {"sku_code": "A", "principal": "unilever", "product_name": "a", "current_stock": 10.0,
         "current_stock_cases": 1.0, "ss_i": 50.0, "rop_i": 100.0}])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="staff", full_name="Staff"))
    with TestClient(app) as c:
        (row,) = c.get("/inventory/current?principal=unilever").json()
    assert "receivedMts" not in row and "dispatchedMts" not in row


class _MovementSession:
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        if "FROM purchase_fact_real" in sql:
            return _Result([
                {"date": datetime.date(2025, 5, 2), "ref": "P1", "principal": "delmonte", "units_received": 120, "net_amount": 5000},
                {"date": datetime.date(2025, 5, 1), "ref": "P2", "principal": "delmonte", "units_received": None, "net_amount": 800}])
        if "FROM sales_fact_real" in sql:
            return _Result([{"date": datetime.date(2025, 5, 3), "ref": "S1", "principal": "delmonte", "net_amount": 9000}])
        raise AssertionError(f"Unexpected query: {sql}")

    def close(self):
        pass


def test_inventory_movement_keeps_units_and_pesos_apart_and_never_turns_unknown_into_zero():
    """BE-6: qty used to be units for purchases and PESOS for sales, an unknown units_received became 0,
    and every row said sku 'N/A' / product 'Assorted Items'."""
    session = _MovementSession()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: auth_utils.decode_access_token(
        auth_utils.create_access_token(user_id=1, email="staff@ssmcapstone.com", role="staff", full_name="Staff"))
    with TestClient(app) as c:
        body = c.get("/inventory/movement?principal=delmonte").json()
    assert [r["ref"] for r in body] == ["S1", "P1", "P2"], "newest first"
    by_ref = {r["ref"]: r for r in body}
    assert by_ref["P1"]["quantity"] == 120.0 and by_ref["P1"]["quantity_unit"] == "units"
    assert by_ref["P2"]["quantity"] is None, "an unrecorded units_received is unknown, not 0"
    assert by_ref["S1"]["quantity"] is None and by_ref["S1"]["quantity_unit"] is None, "sales carry no units"
    assert by_ref["S1"]["amount_pesos"] == 9000.0
    assert all(r["sku"] is None and r["product"] is None and "qty" not in r for r in body)
    assert all("ORDER BY invoice_date DESC" in sql for sql in session.calls), "LIMIT 50 takes the newest, not arbitrary rows"
