"""
backend.routers.policy_comparison — GET /policy-comparison

API_CONTRACTS.md PR4, in units: per SKU, the LP's target stock (and the
safety stock inside it) against SSM's own stock policy — keep three weeks of sales in stock (client meeting,
Sep 2026), applied here as 3 weeks of each SKU's forecast — plus a
portfolio roll-up. The rows are the same ones
GET /dashboard's policy_comparison sums (dashboard.py) — every product in the
latest pending LP planning cycle that also has a Forecast_Result for that
month. Keep the two queries in step.

  rule_stock_units        = POLICY_WEEKS x forecast / AVG_WEEKS_PER_MONTH
                            (also as rule_safety_stock_units, its old name)
  lp_target_stock_units   = LP_Recommendation.rop_i — the order-up-to
                            target T_i since the 2026-09-30 run
  lp_safety_stock_units   = LP_Recommendation.ss_i

The rule's 3 weeks is a target for ALL stock, so target vs rule is the
like-for-like comparison; safety stock alone is kept as a detail.

Pesos (2026-10-05, PENDING SSM CONFIRMATION): the `pesos` block values the same
rows at each product's last purchase price per piece (backend/stock_units.
last_purchase_price_sql — the stock file's unit cost per case ÷ pack size, the
price the LP plan itself uses). SSM has not confirmed that price as its
purchase cost, nor the weekly-order assumption, so the block carries
status = "pending_ssm_confirmation" and the page must show that label.

  plan average = ss_i + half of one weekly order (one order covers review_days
                 of demand: w x review_days / 5 / 2). The weekly order is SSM's
                 stated practice, assumed here; no code splits the plan into one.
  plan peak    = rop_i, the order-up-to target, the level right after a delivery
  rule         = POLICY_WEEKS x weekly forecast, at the same price

The plan cycles between an average and a peak, so the rule must too. SSM has not
said which of the two its 3 weeks is, so `readings` gives both, each complete:

  rule_read_as_average  the rule's average = 3 weeks, its peak = 3 weeks + half an order
  rule_read_as_peak     the rule's average = 3 weeks - half an order, its peak = 3 weeks

Before 2026-11-03 this block returned the plan's average and peak against one flat
3 weeks: a pair taken from two readings (-22.6% and +14.1% on cycle 2026-03, where the
consistent pairs are -22.6 / -2.2 and -7.1 / +14.1). Nothing returns that pair now.

reports/diagnostics/lp_logic_check_2026-10-03 section 4 is the check these
reproduce (cycle 2026-03, 73 products: rule_read_as_average's average 28.1% less,
rule_read_as_peak's peak PHP 706,464 more). A product with no price is left out of
the peso sums and counted in skus_without_price — never given a default price.

working_capital / capital_freed stay null: neither figure is claimed (read as a
peak, the targets' peak is ABOVE the rule's). est_stockout_rate is null too: ss_i
covers the review + lead window (5 + 3 business days, placeholders in
analytics/params.py) under a daily-independence assumption still awaiting the
adviser's ruling — computing it now would state a risk the model hasn't settled.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, principal_clause
from backend.data_mode import PREVIEW, get_data_mode, forecast_source, lp_source, predictive_preview, preview_block
from backend.lp_cycle import CURRENT_CYCLE_CLAUSE, PLAN_STATUS_SQL, current_cycle
from backend.routers.dashboard import AVG_WEEKS_PER_MONTH, POLICY_WEEKS
from backend.stock_units import last_purchase_price_sql
from analytics.params import BUSINESS_DAYS_PER_WEEK, PLACEHOLDERS

router = APIRouter(prefix="/policy-comparison", tags=["policy-comparison"])

VALUATION_BLOCKED_REASON = (
    "No working-capital or capital-freed figure is claimed. The pesos block values both policies at "
    "each product's last purchase price (the stock file's unit cost per case ÷ pack size), a team decision "
    "(DEC-44); not confirmed by SSM; with the 3 weeks read as a peak, the per-product targets peak above the rule, not below. "
    "Stockout exposure is left out until the safety stock's "
    "window (review + lead days, stated assumptions, DEC-44, not confirmed by SSM) and its daily-independence "
    "assumption are settled — see analytics/params.py."
)

PESOS_STATUS = "pending_ssm_confirmation"
PESOS_STATUS_LABEL = (
    "Pending SSM confirmation: the price per piece (last purchase price from the stock file) and the "
    "weekly-order assumption have not been confirmed by SSM."
)
PESOS_PRICE_BASIS = "last purchase price per piece (stock file's unit cost per case ÷ pack size), without VAT"

# One purchase order covers this many weeks of demand, if SSM orders weekly as it says (review_days is a
# placeholder, and no code splits the plan into weekly orders).
ORDER_WEEKS = PLACEHOLDERS["review_days"] / BUSINESS_DAYS_PER_WEEK


def _vs_rule(lp_pesos: float, rule_pesos: float, label: str, definition: str) -> dict:
    """One side of the peso comparison. difference_pesos and pct_vs_rule are per-product
    policy minus rule: negative = it holds less than the 3-week rule."""
    diff = lp_pesos - rule_pesos
    return {
        "label": label,
        "definition": definition,
        "lp_stock_pesos": round(lp_pesos, 2),
        "rule_stock_pesos": round(rule_pesos, 2),
        "difference_pesos": round(diff, 2),
        "pct_vs_rule": round(diff / rule_pesos * 100, 1) if rule_pesos > 0 else None,
        "direction": "less" if diff < 0 else "more" if diff > 0 else "same",
    }


def pesos_comparison(rows: list[dict]) -> dict:
    """The peso block from per-product rows of ss_units, target_units, weekly_units,
    rule_units and price (None = no last purchase price). Arithmetic only, no database."""
    priced = [r for r in rows if r["price"] is not None]
    rule = sum(r["price"] * r["rule_units"] for r in priced)
    peak = sum(r["price"] * r["target_units"] for r in priced)
    average = sum(r["price"] * (r["ss_units"] + r["weekly_units"] * ORDER_WEEKS / 2) for r in priced)
    half_order = sum(r["price"] * r["weekly_units"] * ORDER_WEEKS / 2 for r in priced)
    block = {
        "status": PESOS_STATUS,
        "status_label": PESOS_STATUS_LABEL,
        "price_basis": PESOS_PRICE_BASIS,
        "sku_count": len(priced),
        "skus_without_price": len(rows) - len(priced),
        "rule_weeks": POLICY_WEEKS,
        "review_days": PLACEHOLDERS["review_days"],
        "inputs_are_placeholders": True,
        "readings": None,
        "blocked_reason": None,
    }
    if not priced or rule <= 0:
        block["blocked_reason"] = ("No product in the comparison has a last purchase price, "
                                   "so nothing is valued in pesos.")
        return block
    plan_average = "Per-product safety stock plus half of one weekly order (weekly ordering is assumed, not implemented)"
    plan_peak = "Per-product order-up-to targets"
    block["readings"] = {
        "rule_read_as_average": {
            "label": "rule read as an average",
            "definition": "The 3 weeks is the stock the rule holds on average, so its peak is 3 weeks plus half a weekly order.",
            "average": _vs_rule(average, rule, "Average stock on hand", f"{plan_average}, against 3 weeks of forecast sales."),
            "peak": _vs_rule(peak, rule + half_order, "Peak stock (right after a delivery)",
                             f"{plan_peak}, against 3 weeks of forecast sales plus half a weekly order."),
        },
        "rule_read_as_peak": {
            "label": "rule read as a peak",
            "definition": "The 3 weeks is the stock the rule holds right after a delivery, so its average is 3 weeks minus half a weekly order.",
            "average": _vs_rule(average, rule - half_order, "Average stock on hand",
                                f"{plan_average}, against 3 weeks of forecast sales minus half a weekly order."),
            "peak": _vs_rule(peak, rule, "Peak stock (right after a delivery)", f"{plan_peak}, against 3 weeks of forecast sales."),
        },
    }
    return block


@router.get("")
def get_policy_comparison(
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("lp.view")),
) -> dict:
    scope_sql, scope_params = principal_clause(principal, "pd.principal")
    # The LP's current cycle, resolved under the SAME scope as the rows
    # (backend/lp_cycle.py). The MAX() subquery this replaces was unscoped,
    # so a principal with no rows in the newest cycle silently compared
    # against another principal's cycle.
    cycle = current_cycle(db, principal, mode)
    cycle_clause = CURRENT_CYCLE_CLAUSE if cycle is not None else " AND 1=0"
    lp, lp_params = lp_source(mode)
    fc, fc_params = forecast_source(mode)
    price_expr, price_join = last_purchase_price_sql("pd")
    rows = db.execute(
        text(f"""
            SELECT lr.planning_cycle_date, lr.ss_i, lr.rop_i, fr.forecast_value,
                   COALESCE(pd.sku_code, pd.category_path) AS sku_id, pd.product_name, pd.principal,
                   {price_expr} AS price_per_piece
            FROM {lp} lr
            JOIN Product_Dimension pd ON pd.product_key = lr.product_key
            JOIN {fc} fr
              ON fr.product_key = lr.product_key AND fr.forecast_date = lr.planning_cycle_date
            {price_join}
            WHERE {PLAN_STATUS_SQL}
              {cycle_clause}
              {scope_sql}
        """),
        {**scope_params, "current_cycle": cycle, **lp_params, **fc_params},
    ).mappings().all()
    rows = [
        r for r in rows
        if r["forecast_value"] is not None and r["ss_i"] is not None and r["rop_i"] is not None
    ]

    items = []
    peso_rows = []
    # Unrounded, so the totals match GET /dashboard exactly.
    lp_total = target_total = rule_total = 0.0
    for r in rows:
        lp_units = float(r["ss_i"])
        target_units = float(r["rop_i"])
        weekly_units = float(r["forecast_value"]) / AVG_WEEKS_PER_MONTH
        rule_units = POLICY_WEEKS * weekly_units
        average_units = lp_units + weekly_units * ORDER_WEEKS / 2
        price = float(r["price_per_piece"]) if r.get("price_per_piece") is not None else None
        peso_rows.append({"ss_units": lp_units, "target_units": target_units, "weekly_units": weekly_units,
                          "rule_units": rule_units, "price": price})
        lp_total += lp_units
        target_total += target_units
        rule_total += rule_units
        items.append({
            "sku_id": r["sku_id"],
            "product_name": r["product_name"],
            "principal": r["principal"],
            "forecast_units": round(float(r["forecast_value"]), 2),
            "lp_target_stock_units": round(target_units, 2),
            "lp_safety_stock_units": round(lp_units, 2),
            "rule_stock_units": round(rule_units, 2),
            "rule_safety_stock_units": round(rule_units, 2),
            # Positive: the LP's target holds less stock than the rule for
            # this SKU (target vs rule, the like-for-like pair).
            "difference_units": round(rule_units - target_units, 2),
            # Pesos at last purchase price (pending SSM confirmation); null without a price.
            "lp_average_stock_units": round(average_units, 2),
            "price_per_piece": round(price, 4) if price is not None else None,
            "lp_average_stock_pesos": round(price * average_units, 2) if price is not None else None,
            "lp_peak_stock_pesos": round(price * target_units, 2) if price is not None else None,
            "rule_stock_pesos": round(price * rule_units, 2) if price is not None else None,
        })
    items.sort(key=lambda i: i["difference_units"], reverse=True)

    cycle = rows[0]["planning_cycle_date"] if rows else None
    payload = {
        "cycle_date": cycle.isoformat() if hasattr(cycle, "isoformat") else cycle,
        "rule_weeks": POLICY_WEEKS,
        "portfolio": {
            "sku_count": len(items),
            "lp_target_stock_units": round(target_total, 2) if items else None,
            "lp_safety_stock_units": round(lp_total, 2) if items else None,
            "rule_stock_units": round(rule_total, 2) if items else None,
            "rule_safety_stock_units": round(rule_total, 2) if items else None,
            "target_vs_rule_pct": round((rule_total - target_total) / rule_total * 100, 1) if rule_total > 0 else None,
            "skus_lp_holds_less": sum(1 for i in items if i["difference_units"] > 0),
        },
        "items": items,
        "pesos": pesos_comparison(peso_rows),
        "working_capital": None,
        "capital_freed": None,
        "est_stockout_rate": None,
        "valuation_blocked_reason": VALUATION_BLOCKED_REASON,
        "blocked_reason": None if items else (
            "No pending LP_Recommendation in scope has a Forecast_Result for its own planning-cycle "
            "month, so the two policies can't be compared."
        ),
    }
    if mode == PREVIEW:
        payload["data_mode"] = preview_block(db, real_only=None if predictive_preview(mode) else ["items", "portfolio", "pesos"])
    return payload
