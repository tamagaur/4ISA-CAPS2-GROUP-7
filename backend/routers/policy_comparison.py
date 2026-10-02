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

Units (pieces), never pesos. reports/IMPLEMENTATION_PLAN_2026-09.md Phase 1
rules peso conversion out until an agreed cost per piece exists
(Product_Dimension.unit_price is 0/17,536 populated; Inventory_Fact's
unit_cost_per_case is per CASE, and dividing by pack_size — trusted since
backend/stock_units.py — is only the LP plan's placeholder so far). So
working_capital / capital_freed stay null with the reason. est_stockout_rate
is null too: ss_i covers the review + lead window (5 + 3 business days,
placeholders in analytics/optimization/lp_inputs.py) under a
daily-independence assumption still awaiting the adviser's ruling —
computing it now would state a risk the model hasn't settled.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, principal_clause
from backend.data_mode import PREVIEW, get_data_mode, forecast_source, lp_source, predictive_preview, preview_block
from backend.lp_cycle import CURRENT_CYCLE_CLAUSE, current_cycle
from backend.routers.dashboard import AVG_WEEKS_PER_MONTH, POLICY_WEEKS

router = APIRouter(prefix="/policy-comparison", tags=["policy-comparison"])

VALUATION_BLOCKED_REASON = (
    "Units only. No agreed cost per piece exists (Product_Dimension.unit_price is empty; "
    "the stock file's unit cost per case ÷ pack size is only a planning placeholder), so "
    "working capital isn't valued in pesos. Stockout exposure is left out until the safety stock's "
    "window (review + lead days, placeholders until SSM confirms them) and its daily-independence "
    "assumption are settled — see analytics/optimization/lp_inputs.py."
)


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
    rows = db.execute(
        text(f"""
            SELECT lr.planning_cycle_date, lr.ss_i, lr.rop_i, fr.forecast_value,
                   COALESCE(pd.sku_code, pd.category_path) AS sku_id, pd.product_name, pd.principal
            FROM {lp} lr
            JOIN Product_Dimension pd ON pd.product_key = lr.product_key
            JOIN {fc} fr
              ON fr.product_key = lr.product_key AND fr.forecast_date = lr.planning_cycle_date
            WHERE lr.status = 'pending'
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
    # Unrounded, so the totals match GET /dashboard exactly.
    lp_total = target_total = rule_total = 0.0
    for r in rows:
        lp_units = float(r["ss_i"])
        target_units = float(r["rop_i"])
        rule_units = POLICY_WEEKS * float(r["forecast_value"]) / AVG_WEEKS_PER_MONTH
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
            # Safety stock alone against the rule — a detail, not the headline.
            "lp_vs_rule_pct": round((rule_total - lp_total) / rule_total * 100, 1) if rule_total > 0 else None,
            "skus_lp_holds_less": sum(1 for i in items if i["difference_units"] > 0),
        },
        "items": items,
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
        payload["data_mode"] = preview_block(db, real_only=None if predictive_preview(mode) else ["items", "portfolio"])
    return payload
