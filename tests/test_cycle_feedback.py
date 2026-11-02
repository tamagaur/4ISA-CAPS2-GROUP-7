"""scripts/cycle_feedback.py: the scoring and the blocked states. The SQL runs in the local rehearsal."""
from __future__ import annotations

from scripts import cycle_feedback as cf


def _row(sku, forecast, actual, blanks=0, has_row=True):
    return {"sku_code": sku, "forecast": forecast, "actual": actual, "blanks": blanks, "has_row": has_row}


def test_no_sales_for_the_month_is_blocked_never_zero():
    result = cf.score([_row("A", 100.0, None, has_row=False)], month_loaded=False)
    assert result["status"] == "blocked" and "not loaded" in result["reason"]
    assert "wape" not in result


def test_a_product_with_no_row_in_a_loaded_month_counts_as_zero_sales():
    result = cf.score([_row("A", 100.0, None, has_row=False), _row("B", 100.0, 100.0)], month_loaded=True)
    assert result["scored"] == 2 and result["no_sale"] == 1 and result["actual"] == 100.0


def test_a_blank_quantity_is_excluded_not_read_as_zero():
    result = cf.score([_row("A", 100.0, None, blanks=1), _row("B", 100.0, 100.0)], month_loaded=True)
    assert result["scored"] == 1 and result["excluded_blank"] == 1 and result["forecast"] == 100.0


def test_wape_and_bias_are_weighted_by_pieces():
    result = cf.score([_row("A", 150.0, 100.0), _row("B", 50.0, 100.0)], month_loaded=True)
    assert result["wape"] == 0.5 and result["bias"] == 0.0
    assert result["over"] == 1 and result["under"] == 1


def test_no_actual_sales_at_all_gives_no_ratio_rather_than_a_number():
    result = cf.score([_row("A", 100.0, None, has_row=False)], month_loaded=True)
    assert result["wape"] is None and result["bias"] is None


def test_decisions_separate_overrides_from_plain_accepts_and_count_the_reasons():
    rows = [
        {"status": "accepted", "q_i": 100.0, "decided_q_i": None, "decision_reason": None, "in_plan": True},
        {"status": "accepted", "q_i": 100.0, "decided_q_i": 60.0, "decision_reason": "Truck is full", "in_plan": True},
        {"status": "dismissed", "q_i": 50.0, "decided_q_i": None, "decision_reason": "Overstocked now", "in_plan": True},
        {"status": "dismissed", "q_i": 50.0, "decided_q_i": None, "decision_reason": "Overstocked now", "in_plan": True},
        {"status": "pending", "q_i": 10.0, "decided_q_i": None, "decision_reason": None, "in_plan": True},
        {"status": "accepted", "q_i": 1331.24, "decided_q_i": None, "decision_reason": None, "in_plan": False},
    ]
    result = cf.summarize_decisions(rows)
    assert result["accepted"] == 2 and result["dismissed"] == 2 and result["pending"] == 1 and result["outside_plan"] == 1
    assert result["overrides"] == 1 and result["override_change_pieces"] == -40.0
    assert result["reasons"] == [("Overstocked now", 2), ("Truck is full", 1)]


def test_a_synthetic_month_is_labelled_on_every_report():
    lines = cf.render({"cycle": "2026-03", "synthetic_rows": 709, "forecast": cf.score([], month_loaded=True),
                       "decisions": cf.summarize_decisions([]), "receipts": []})
    assert "SYNTHETIC" in lines[0]


def test_a_real_month_carries_no_synthetic_label():
    lines = cf.render({"cycle": "2026-03", "synthetic_rows": 0, "forecast": cf.score([], month_loaded=True),
                       "decisions": cf.summarize_decisions([]), "receipts": []})
    assert not any("SYNTHETIC" in line for line in lines)


def test_nothing_in_this_report_writes():
    import pathlib
    source = pathlib.Path(cf.__file__).read_text(encoding="utf-8")
    for word in ("INSERT INTO", "UPDATE ", "DELETE FROM", ".commit("):
        assert word not in source


def test_generated_rows_are_counted_on_the_base_table():
    # Labelled is_demo = true, they never pass the _Real views: a count through a view would read 0 and drop the label.
    assert "_Real" not in cf.SYNTHETIC_SQL and "unilever_sku_demand_fact" in cf.SYNTHETIC_SQL
