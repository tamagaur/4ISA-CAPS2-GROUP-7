"""GET /dashboard forecast_accuracy.entry_test: MASE beside the two WAPEs on the error card (2026-11-10)."""
from __future__ import annotations

from backend.practice_copy import STORED_ACCURACY_KEYS, withhold_accuracy
from backend.routers.dashboard import _entry_test, _forecast_counts_query


def test_entry_test_reads_the_plan_gate_on_unilever_ok_rows():
    sql, params = _forecast_counts_query("all", "real")
    assert "pd.principal = 'unilever' AND fr.status = 'ok' AND fr.mase < :mase_gate" in sql
    assert params["mase_gate"] == 1.0


def test_entry_test_shape():
    row = {"entry_scored": 175, "entry_passed": 110, "entry_median": 0.8731, "entry_forecast_date": "2026-03-01"}
    e = _entry_test(row)
    assert (e["mase_scored"], e["mase_passed"], e["mase_gate"], e["median_mase"]) == (175, 110, 1.0, 0.873)
    assert "entry test" in e["measure"]


def test_no_scored_forecast_gives_none():
    assert _entry_test({"entry_scored": 0}) is None


def test_practice_copy_withholds_the_entry_test():
    assert {"median_mase", "mase_passed", "mase_scored"} <= set(STORED_ACCURACY_KEYS)
    body = {"forecast_accuracy": {"entry_test": {"forecast_date": "2026-04-01", "mase_scored": 175, "mase_passed": 110,
                                                 "mase_gate": 1.0, "median_mase": 0.87}}}
    out = withhold_accuracy(body, ["2026-03"], path="/other")
    e = out["forecast_accuracy"]["entry_test"]
    assert e["median_mase"] is None and e["mase_passed"] is None and e["mase_scored"] is None
    assert e["mase_gate"] == 1.0 and e["accuracy_withheld"]


def test_the_accuracy_route_the_card_reads_carries_the_entry_test(monkeypatch):
    """The card moved to SKU Forecast and reads GET /dashboard/accuracy (ba0396d), not GET /dashboard."""
    import backend.routers.dashboard_range as dr
    row = {"entry_scored": 175, "entry_passed": 110, "entry_median": 0.823, "entry_forecast_date": "2026-03-01"}
    seen = []
    monkeypatch.setattr(dr.batch, "first", lambda db, sql, params: seen.append(sql) or row)
    e = dr._range_entry_test(object())
    assert (e["mase_passed"], e["mase_scored"]) == (110, 175)
    assert "Forecast_Result" in seen[0] and "fr.status = 'ok'" in seen[0]
    src = __import__("inspect").getsource(dr.get_range_accuracy)
    assert src.count('summary["entry_test"] = _range_entry_test(db)') == 2     # summary and detail paths
