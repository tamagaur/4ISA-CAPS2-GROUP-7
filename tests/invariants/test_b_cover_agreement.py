"""(b) Weeks of cover agrees between the stored mart inputs and what the endpoints compute from them.

NOTE ON THE NAME: the brief names `marts.stock_detail`; no such function exists in this repo (grep, 2026-10-28).
The cover figures actually served are (1) the per-SKU `days_of_cover` on /recommendations (recommendations._cover,
stock in pieces over average monthly quantity_sold) and (2) the portfolio `kpis.weeks_of_cover` on
the Dashboard (fed by backend.marts.stock_pieces_at / pieces_by_period). These two tests pin each to its own mart
inputs. Both are pieces over pieces since D3 (2026-10-28); before it the per-SKU figure was stock cost over sales price.

Guards against: the freeze-package 1a bug - cover was stock valued at purchase cost over sales valued at selling
price, which understated it by the margin (3.0285 -> 3.1321 weeks once both were in pieces). A basis slip between
the stock side and the sales side moves the figure with no error anywhere.
"""
import pytest

from backend import marts
from analytics.params import DAYS_PER_MONTH as AVG_DAYS_PER_MONTH, WEEKS_PER_MONTH as AVG_WEEKS_PER_MONTH  # the single source, not the endpoints own alias


def test_sku_days_of_cover_reproduces_from_pieces(plan, sql):
    """Per-SKU cover is pieces over pieces (D3, 2026-10-28): the row's own stock in pieces over the product's average
    monthly quantity_sold for the SKU_COVER_HISTORY_MONTHS months at or before the cycle's opening count."""
    from analytics.params import SKU_COVER_HISTORY_MONTHS
    from backend.stock_units import opening_period
    avg = {r["sku_id"]: r["avg_monthly_pieces"] for r in sql(
        f"""SELECT pd.sku_code AS sku_id, SUM(d.quantity_sold) / (SELECT COUNT(*) FROM (
                SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real WHERE calendar_month <= :p
                ORDER BY calendar_month DESC LIMIT {SKU_COVER_HISTORY_MONTHS}) w) AS avg_monthly_pieces
            FROM unilever_sku_demand_fact_real d JOIN product_dimension pd ON pd.product_key = d.product_key
            WHERE d.calendar_month IN (SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
                WHERE calendar_month <= :p ORDER BY calendar_month DESC LIMIT {SKU_COVER_HISTORY_MONTHS})
            GROUP BY pd.sku_code""", p=opening_period(plan["planning_cycle_date"]))}
    checked = 0
    for item in plan["items"]:
        if item["days_of_cover"] is None:
            continue
        stock = 0.0 if item["stock_not_in_count"] else float(item["current_stock"])
        expected = stock / (float(avg[item["sku_id"]]) / AVG_DAYS_PER_MONTH)
        assert item["days_of_cover"] == pytest.approx(expected, abs=0.051), item["sku_id"]
        checked += 1
    assert checked > 0, "no recommendation carried a days_of_cover: nothing was compared"


def test_dashboard_weeks_of_cover_is_pieces_over_pieces_for_its_stated_window(get, db):
    card = get("/dashboard?principal=unilever")["kpis"]["weeks_of_cover"]
    assert card["value"] is not None, f"weeks_of_cover blocked: {card['blocked_reason']}"
    assert card["basis"] == "pieces", "Unilever cover must be pieces over pieces (stock cost vs sales price mix-up)"
    start, end = card["sales_window"]["start"], card["sales_window"]["end"]
    months = []
    y, m = int(start[:4]), int(start[5:7])
    while f"{y:04d}-{m:02d}" <= end:
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    sales = [v for v in marts.pieces_by_period(db, months, "unilever").values() if v is not None]
    assert len(sales) == card["months_used"]
    stock = marts.stock_pieces_at(db, card["stock_period"], "unilever")
    expected = stock / ((sum(sales) / len(sales)) / AVG_WEEKS_PER_MONTH)
    assert card["value"] == pytest.approx(expected, abs=0.006)
