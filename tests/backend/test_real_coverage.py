"""GET /data-mode's coverage (2026-10-20): each principal's first and latest month of
REAL sales, which the frontend's date filter treats as "today". Pure: the one query's
rows are stubbed."""
from backend import marts


def _stub(monkeypatch, rows):
    monkeypatch.setattr(marts.batch, "rows", lambda db, sql, params=None: rows)


def test_each_principal_keeps_its_own_latest_month(monkeypatch):
    _stub(monkeypatch, [
        {"principal": "delmonte", "first": "2023-01", "latest": "2025-12"},
        {"principal": "unilever", "first": "2023-01", "latest": "2026-02"},
    ])
    out = marts.real_coverage(None)
    assert out["latest_data_period_by_principal"] == {"delmonte": "2025-12", "unilever": "2026-02"}
    assert out["latest_data_period"] == "2026-02"
    assert out["first_data_period"] == "2023-01"


def test_an_unknown_principal_is_left_out(monkeypatch):
    _stub(monkeypatch, [
        {"principal": "unilever", "first": "2023-01", "latest": "2026-02"},
        {"principal": "magnolia", "first": "2020-01", "latest": "2027-01"},
    ])
    out = marts.real_coverage(None)
    assert out["latest_data_period_by_principal"] == {"unilever": "2026-02"}
    assert out["latest_data_period"] == "2026-02" and out["first_data_period"] == "2023-01"


def test_nothing_loaded_is_none_not_a_made_up_month(monkeypatch):
    _stub(monkeypatch, [])
    assert marts.real_coverage(None) == {
        "first_data_period": None, "latest_data_period": None, "latest_data_period_by_principal": {},
    }


def test_the_query_reads_real_rows_only():
    assert "data_kind = 'real'" in marts.REAL_COVERAGE_SQL
