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
