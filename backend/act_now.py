"""The Act Now list: every top seller that needs someone now, in one list (adviser feedback, 2026-11-17).

Stock-outs outrank low stock. A product missing from the opening stock count (stock_not_in_count, read as 0
on hand, as the LP reads it) is out of stock and comes before a product that is only below its target stock.

The groups are the Reorder page's own (frontend/src/utils/reorderView.js actNowGroups), so GET /dashboard and
the Reorder page count the same products. Change both together; tests/backend/test_act_now.py pins this side
and reorderView.test.js the other. Every SKU is in one group only:
  out_of_stock     in the plan, out of stock, awaiting a decision
  below_target     in the plan, below target stock (CRITICAL or URGENT), not out of stock, awaiting a decision
  check_manually   not in the plan because no forecast can be trusted for it yet, and out of stock
  confirm          not in the plan for any other reason (no sale in 6 months), and out of stock: maybe
                   discontinued, so outside the total
  out_of_stock_no_order  in the plan and out of stock, but the plan orders 0 (no demand forecast): outside the
                   total, like confirm. Dashboard only; the Reorder page's card does not list it yet.
total = out_of_stock + below_target + check_manually. Nothing here is a fixed number: every count is a
len() over the rows passed in.
"""
from __future__ import annotations

from backend.stock_status import CRITICAL, URGENT
from backend.routers.recommendations import whole_units

BELOW_TARGET_URGENCIES = frozenset({CRITICAL, URGENT})
CHECK_MANUALLY_REASONS = frozenset({"mase_gate", "insufficient_data"})


def _get(item, key, default=None):
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def awaits_decision(item) -> bool:
    """Pending and orders something: the plan quantity (accepted, else the plan's) is at least one piece."""
    return _get(item, "status") == "pending" and orders_something(item)


def is_act_now(item) -> bool:
    return bool(_get(item, "stock_not_in_count")) or _get(item, "urgency") in BELOW_TARGET_URGENCIES


def orders_something(item) -> bool:
    qty = _get(item, "plan_q_i")
    if qty is None:
        qty = _get(item, "q_i")
    return (whole_units(qty) if qty is not None else 0) > 0


def act_now_sort_key(item) -> tuple:
    """Rows with an order first, then out of stock, then urgency, then priority (revenue share x units short).

    A stock-out with nothing to order (target stock 0: no demand forecast) goes after every row that orders,
    so it never pushes a real order out of the Dashboard's top five; it is counted in act_now instead."""
    from backend.stock_status import URGENCY_RANK
    return (0 if orders_something(item) else 1, 0 if _get(item, "stock_not_in_count") else 1,
            URGENCY_RANK.get(_get(item, "urgency"), 99), -(_get(item, "priority_score") or 0))


def act_now_groups(plan_items, not_planned_items=()) -> dict:
    """Counts per group (see the module docstring), from the plan rows and GET /recommendations' not_planned."""
    pending = [it for it in plan_items if is_act_now(it) and awaits_decision(it)]
    planned = {str(_get(it, "sku_id")) for it in plan_items}
    seen: set[str] = set()
    outside = []
    for it in not_planned_items or ():
        sku = str(_get(it, "sku_id"))
        if not _get(it, "stock_not_in_count") or sku in planned or sku in seen:
            continue
        seen.add(sku)
        outside.append(it)
    out_of_stock = sum(1 for it in pending if _get(it, "stock_not_in_count"))
    below_target = len(pending) - out_of_stock
    check_manually = sum(1 for it in outside if _get(it, "reason") in CHECK_MANUALLY_REASONS)
    confirm = len(outside) - check_manually
    # In the plan and out of stock, but ordering nothing (target stock 0: no demand forecast). Nothing to
    # decide, so outside the total, like confirm; shown beside it so no stock-out goes unmentioned.
    no_order = sum(1 for it in plan_items
                   if _get(it, "stock_not_in_count") and _get(it, "status") == "pending" and not orders_something(it))
    return {
        "out_of_stock": out_of_stock,
        "below_target": below_target,
        "check_manually": check_manually,
        "confirm": confirm,
        "out_of_stock_no_order": no_order,
        "total": out_of_stock + below_target + check_manually,
    }
