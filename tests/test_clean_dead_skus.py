"""tests/test_clean_dead_skus.py — scripts/clean_dead_skus.py judges every
active product with a demand row, including one that never sold."""
from __future__ import annotations

from scripts.clean_dead_skus import CANDIDATES_QUERY, is_dead_sku


def test_a_returns_only_sku_is_dead():
    """Only returns (or zero) rows: no positive sale ever, so the LEFT JOIN
    gives last_sale_month NULL — dead, not skipped (the 272 of 2026-09-30)."""
    assert is_dead_sku(None, "2026-02")


def test_last_sale_outside_the_six_calendar_months_is_dead():
    # Sold 2025-08, returns only since: 2025-09..2026-02 has no sale (the 49).
    assert is_dead_sku("2025-08", "2026-02")


def test_a_sale_inside_the_window_is_alive():
    assert not is_dead_sku("2025-09", "2026-02")
    assert not is_dead_sku("2026-02", "2026-02")


def test_the_query_keeps_products_that_never_sold():
    sql = " ".join(CANDIDATES_QUERY.split())
    assert "LEFT JOIN last_sales s ON s.product_key = r.product_key" in sql
    # The sales filter only shapes last_sale_month; it never narrows the products.
    assert sql.count("quantity_sold > 0") == 1 and "FROM products_with_rows r" in sql


# ---- the gate (2026-10-21): dry run by default, approval tied to the printed count ---------------------------

import pytest  # noqa: E402

from scripts import clean_dead_skus as cds  # noqa: E402


class _Cursor:
    def __init__(self, log):
        self.log, self._rows = log, []

    def execute(self, sql, params=None):
        self.log.append(" ".join(sql.split()))
        s = " ".join(sql.split())
        if s.startswith("SELECT MAX(calendar_month)"):
            self._rows = [("2026-02",)]
        elif "WITH products_with_rows" in s:
            self._rows = [(1, "10000001", None), (2, "10000002", "2025-01"), (3, "10000003", "2026-02")]
        elif s.startswith("SELECT MAX(ac.classification_period)"):
            self._rows = [("2026-02",)]
        elif s.startswith("SELECT COUNT(*) FROM abc_classification"):
            self._rows = [(1,)]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self):
        self.log, self.commits = [], 0

    def cursor(self):
        return _Cursor(self.log)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


@pytest.fixture
def conn(monkeypatch):
    c = _Conn()
    monkeypatch.setattr(cds.psycopg2, "connect", lambda *a, **k: c)
    monkeypatch.setattr(cds, "load_dotenv", lambda *a, **k: None)
    return c


def _wrote(c):
    return any(q.startswith("UPDATE") for q in c.log) or c.commits > 0


def test_with_no_arguments_it_is_a_dry_run_that_writes_nothing(conn, capsys):
    assert cds.main([]) == 0
    out = capsys.readouterr().out
    assert "WOULD DISABLE 2 Unilever SKUs" in out and "Tier A" in out and "DRY RUN" in out
    assert not _wrote(conn)
    assert "SET TRANSACTION READ ONLY" in conn.log  # transaction-scoped, never session-level


def test_approval_without_the_count_is_still_a_dry_run(conn):
    cds.main(["--approved-by", "Yuan"])
    assert not _wrote(conn)


def test_the_count_without_an_approver_is_still_a_dry_run(conn):
    cds.main(["--expect-disable", "2"])
    assert not _wrote(conn)


def test_an_approval_for_a_different_count_is_refused(conn, capsys):
    cds.main(["--approved-by", "Yuan", "--expect-disable", "837"])
    assert not _wrote(conn) and "REFUSED" in capsys.readouterr().out


def test_an_approval_of_exactly_this_list_writes(conn):
    assert cds.clean_dead_skus("Yuan", 2) == 2
    assert any(q.startswith("UPDATE Product_Dimension SET status = 'DISABLED'") for q in conn.log) and conn.commits == 1


def test_the_tier_a_check_reads_the_basis_through_abc_method_sql_not_a_literal(conn):
    cds.main([])
    tier_sql = " ".join(q for q in conn.log if "abc_classification" in q)
    assert "method = CASE ac.principal" in tier_sql and "method = 'single'" not in tier_sql
