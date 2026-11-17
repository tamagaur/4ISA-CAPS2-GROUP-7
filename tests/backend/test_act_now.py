"""backend/act_now.py: one Act Now list, stock-outs first (adviser feedback, 2026-11-17).

The cases mirror frontend/src/utils/reorderView.test.js's actNowGroups tests, so the Dashboard and the
Reorder page count the same products."""
from backend.act_now import act_now_groups, act_now_sort_key


def _row(sku, urgency="PLANNED", out=False, status="pending", q_i=10.0, priority=0.0):
    return {"sku_id": sku, "urgency": urgency, "stock_not_in_count": out, "status": status, "q_i": q_i,
            "plan_q_i": None, "priority_score": priority}


def _np(sku, reason, out=True):
    return {"sku_id": sku, "reason": reason, "stock_not_in_count": out}


def test_out_of_stock_and_below_target_are_one_list_with_no_product_counted_twice():
    rows = [
        _row("A", "CRITICAL", out=True),   # out of stock AND below target: counted once, as out of stock
        _row("B", "CRITICAL"),
        _row("C", "URGENT"),
        _row("D", "PLANNED", out=True),    # out of stock with a target of 0: still Act Now
        _row("E", "PLANNED"),              # neither
    ]
    groups = act_now_groups(rows)
    assert groups == {"out_of_stock": 2, "below_target": 2, "check_manually": 0, "confirm": 0,
                      "out_of_stock_no_order": 0, "total": 4}


def test_a_stock_out_with_nothing_to_order_is_counted_beside_the_total_not_in_it():
    rows = [_row("A", "CRITICAL", out=True), _row("B", "PLANNED", out=True, q_i=0.0), _row("C", "CRITICAL")]
    groups = act_now_groups(rows)
    assert (groups["out_of_stock"], groups["below_target"], groups["out_of_stock_no_order"], groups["total"]) == (1, 1, 1, 2)


def test_decided_rows_and_rows_ordering_nothing_leave_the_list():
    rows = [
        _row("A", "CRITICAL", status="accepted"),
        _row("B", "CRITICAL", out=True, status="dismissed"),
        _row("C", "URGENT", q_i=0.0),
        _row("D", "URGENT"),
    ]
    assert act_now_groups(rows)["total"] == 1


def test_out_of_stock_outside_the_plan_joins_unless_it_may_be_discontinued():
    rows = [_row("A", "CRITICAL")]
    not_planned = [
        _np("X", "mase_gate"),
        _np("Y", "insufficient_data"),
        _np("Y", "insufficient_data"),      # listed twice: counted once
        _np("A", "mase_gate"),              # also in the plan: left to the plan
        _np("Z", "dead"),                   # no sale in 6 months: confirm with SSM, outside the total
        _np("W", "mase_gate", out=False),   # in stock: not Act Now
    ]
    groups = act_now_groups(rows, not_planned)
    assert groups == {"out_of_stock": 0, "below_target": 1, "check_manually": 2, "confirm": 1,
                      "out_of_stock_no_order": 0, "total": 3}


def test_stock_outs_outrank_low_stock_then_urgency_then_priority():
    rows = [
        _row("critical-high", "CRITICAL", priority=9.0),
        _row("urgent-out", "URGENT", out=True, priority=0.1),
        _row("critical-out", "CRITICAL", out=True, priority=0.5),
        _row("planned", "PLANNED", priority=99.0),
        _row("critical-low", "CRITICAL", priority=1.0),
        _row("out-nothing-to-order", "PLANNED", out=True, q_i=0.0),  # never ahead of a real order
    ]
    order = [r["sku_id"] for r in sorted(rows, key=act_now_sort_key)]
    assert order == ["critical-out", "urgent-out", "critical-high", "critical-low", "planned", "out-nothing-to-order"]
