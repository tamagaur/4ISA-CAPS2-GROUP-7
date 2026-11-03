"""fig_o draws one row of GET /policy-comparison: the rule read as a peak (2026-11-03). It used to draw the plan's average against
one reading of the rule and its peak against the other, a pair no API field returns."""
from scripts.manuscript_figures import fig_o_values


def _side(plan, rule, pct):
    return {"lp_stock_pesos": plan, "rule_stock_pesos": rule, "pct_vs_rule": pct}


PESOS = {"readings": {
    "rule_read_as_peak": {"label": "rule read as a peak", "average": _side(10.0, 20.0, -50.0), "peak": _side(30.0, 40.0, -25.0)},
    "rule_read_as_average": {"label": "rule read as an average", "average": _side(111.0, 222.0, -99.0), "peak": _side(333.0, 444.0, -88.0)},
}}


def test_both_bars_come_from_the_peak_row():
    v = fig_o_values(PESOS)
    assert v["plan"] == [10.0, 30.0] and v["rule"] == [20.0, 40.0] and v["pct"] == [-50.0, -25.0]


def test_the_other_reading_goes_to_the_note_only():
    v = fig_o_values(PESOS)
    assert v["other_pct"] == [-99.0, -88.0]
    assert not {111.0, 222.0, 333.0, 444.0} & set(v["plan"] + v["rule"])
