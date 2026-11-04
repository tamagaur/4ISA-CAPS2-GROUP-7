"""The label a practice-copy answer carries in its own body (backend/practice_copy.py), and that the deployed API never mounts it."""
from __future__ import annotations

import gzip
import json

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from backend import practice_copy as pc
from scripts.local_pipeline_qa import TAG
from scripts.practice_artefacts import accuracy_figure, body_label_problem, reads_as_real

MARCH = ["2026-03"]


def test_the_tag_is_the_one_the_generator_writes():
    assert pc.GENERATED_TAG == TAG


def test_a_generated_row_stops_reading_as_real_and_the_count_follows():
    body = {"principal": "unilever", "estimated_rows": 0, "rows": [
        {"period": "2026-02", "data_kind": "real", "estimated": False},
        {"period": "2026-03", "data_kind": "real", "estimated": False},
    ]}
    assert reads_as_real(body, "2026-03")
    out = pc.label_payload(body, MARCH)
    assert out["rows"][0] == {"period": "2026-02", "data_kind": "real", "estimated": False}
    assert out["rows"][1] == {"period": "2026-03", "data_kind": pc.GENERATED_KIND, "estimated": True, "generated_sales_month": True}
    assert out["estimated_rows"] == 1
    assert body_label_problem(out) is None


def test_a_point_with_no_kind_field_is_labelled_too():
    out = pc.label_payload({"actuals": [{"period": "2026-03", "quantity": 5, "reason": None}]}, MARCH)
    assert out["actuals"][0]["generated_sales_month"] is True


def test_what_is_dated_after_the_month_says_it_rests_on_it():
    out = pc.label_payload({"items": [{"planning_cycle_date": "2026-04-01", "q_i": 9}, {"planning_cycle_date": "2026-03-01", "q_i": 9}]}, MARCH)
    assert out["items"][0]["rests_on_generated_sales"] is True and "generated_sales_month" not in out["items"][0]
    assert out["items"][1]["generated_sales_month"] is True


def test_a_plan_row_tied_to_the_month_and_dated_after_it_says_both():
    out = pc.label_payload({"items": [{"planning_cycle_date": "2026-04-01", "tier_period": "2026-03"}]}, MARCH)
    assert out["items"][0]["rests_on_generated_sales"] is True and out["items"][0]["generated_sales_month"] is True


def test_a_range_says_it_holds_the_month_only_when_it_does():
    out = pc.label_payload({"in": {"synthetic_months": [], "start_period": "2025-04", "end_period": "2026-03"},
                            "before": {"synthetic_months": [], "start_period": "2024-04", "end_period": "2025-03"}}, MARCH)
    assert out["in"]["synthetic_months"] == MARCH and out["before"]["synthetic_months"] == []


def test_del_monte_is_not_marked_with_unilevers_month_but_the_answer_is_still_labelled():
    out = pc.label_payload({"principal": "delmonte", "rows": [{"period": "2026-03", "data_kind": "real", "estimated": False}]}, MARCH)
    assert out["rows"][0] == {"period": "2026-03", "data_kind": "real", "estimated": False}
    assert out["practice_copy"]["generated_months"] == MARCH and out["practice_copy"]["not_a_result"] is True


def test_an_array_answer_carries_the_label_on_each_element():
    out = pc.label_payload([{"sku": "1"}, {"sku": "2"}], MARCH)
    assert all(x["practice_copy"] == {"not_a_result": True, "generated_months": MARCH} for x in out)
    assert body_label_problem(out) is None


def test_months_that_cannot_be_read_say_so_rather_than_saying_none():
    label = pc.label_payload({}, None)["practice_copy"]
    assert label["generated_months"] is None and "could not be read" in label["note"] and label["not_a_result"] is True
    assert "not name" in body_label_problem(pc.label_payload({}, None))


def test_the_check_fails_a_body_without_the_label_or_with_a_real_row():
    assert "no practice_copy" in body_label_problem({"items": []})
    assert "no practice_copy" in body_label_problem([{"sku": "1"}])
    bad = {"practice_copy": {"not_a_result": True, "generated_months": MARCH}, "rows": [{"month": "2026-03", "estimated": False}]}
    assert "reads as real" in body_label_problem(bad)


def _client(monkeypatch):
    monkeypatch.setattr(pc, "generated_months", lambda url=None: MARCH)
    app = FastAPI()

    @app.get("/big")
    def big():
        return {"rows": [{"period": "2026-03", "data_kind": "real", "pad": "x" * 5000}]}

    @app.get("/list")
    def as_list():
        return [{"sku": "1"}]

    @app.get("/text")
    def text():
        return PlainTextResponse("not json")

    @app.get("/refused", status_code=409)
    def refused():
        return {"detail": "no"}

    app.add_middleware(pc.PracticeBodyLabel)
    app.add_middleware(GZipMiddleware, minimum_size=1000)   # the order backend/main.py registers them
    return TestClient(app)


def test_the_label_is_written_inside_gzip_and_the_length_is_right(monkeypatch):
    res = _client(monkeypatch).get("/big", headers={"Accept-Encoding": "gzip"})
    assert res.headers["content-encoding"] == "gzip"
    assert res.json()["rows"][0]["data_kind"] == pc.GENERATED_KIND and "practice_copy" in res.json()


def test_the_length_header_matches_the_rewritten_body(monkeypatch):
    res = _client(monkeypatch).get("/list", headers={"Accept-Encoding": "identity"})
    assert int(res.headers["content-length"]) == len(res.content)
    assert json.loads(res.content)[0]["practice_copy"]["not_a_result"] is True


def test_a_refusal_and_a_non_json_answer_pass_through_untouched(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/refused").json() == {"detail": "no"}
    assert client.get("/text").text == "not json"


def test_gzip_really_wraps_it_in_the_app():
    """An outer position would hand the labeller compressed bytes."""
    assert gzip.compress(b"x")[:2] == b"\x1f\x8b"
    from backend import main
    source = open(main.__file__, encoding="utf-8").read()
    assert source.index("app.add_middleware(PracticeBodyLabel)") < source.index("app.add_middleware(GZipMiddleware")


def test_the_deployed_api_does_not_mount_it():
    """This test process's URL does not name the copy, which is the deployed API's position."""
    from backend.main import app
    assert not any(m.cls is pc.PracticeBodyLabel for m in app.user_middleware)


# ---- accuracy withheld (hard rule 2) ------------------------------------------------------------------------------------------------

def _card(start="2025-04", end="2026-03"):
    return {"start_period": start, "end_period": end, "coverage": ["unilever"], "products": 239, "company_total": {"value": 0.109},
            "typical_product_weighted": {"value": 0.463}, "wape_pieces": 0.463, "total_wape_pesos": 0.109,
            "by_month": [{"month": "2026-03", "wape_pieces": 0.5}], "over_forecast_runs": {"count": 3, "items": [{"sku_id": "1"}]}}


def test_a_range_reaching_the_month_loses_its_figures_and_says_why_as_del_montes_card_does():
    out = pc.label_payload({"forecast_accuracy": _card(), "lp": {"rows": 121}}, MARCH, "/dashboard")
    card = out["forecast_accuracy"]
    assert card["blocked_reason"].startswith("Forecast error withheld") and "2026-03" in card["blocked_reason"]
    assert card["company_total"]["value"] is None and card.get("wape_pieces") is None and card["by_month"] == [] and card["products"] == 0
    assert card["over_forecast_runs"]["items"] == [] and card["accuracy_withheld"] is True
    assert out["lp"] == {"rows": 121} and accuracy_figure(out) is None


def test_a_range_ending_before_the_month_keeps_the_real_figures():
    out = pc.label_payload({"forecast_accuracy": _card("2025-03", "2026-02")}, MARCH, "/dashboard")
    assert out["forecast_accuracy"]["company_total"]["value"] == 0.109 and "blocked_reason" not in out["forecast_accuracy"]


def test_the_accuracy_route_at_every_level_is_withheld_with_no_rows():
    out = pc.label_payload({**_card(), "level": "product", "rows": [{"sku_code": "1", "month": "2026-03", "miss_pieces": 4}]}, MARCH, "/dashboard/accuracy")
    assert out["rows"] == [] and out["level"] == "product" and out["blocked_reason"] and accuracy_figure(out) is None


def test_the_decomposition_routes_are_withheld_and_del_montes_own_reason_is_left_alone():
    body = {"available": True, "coverage": ["unilever"], "period_start": "2025-04", "period_end": "2026-03", "totals": {"error_pieces": 9}}
    for path in ("/dashboard/error-decomposition", "/dashboard/error-decomposition/aggregate", "/dashboard/error-decomposition/concentration",
                 "/dashboard/error-decomposition/product/1"):
        out = pc.label_payload(dict(body), MARCH, path)
        assert out["available"] is False and "totals" not in out and out["blocked_reason"].startswith("Forecast error withheld")
    before = {"available": True, "period_start": "2025-03", "period_end": "2026-02", "totals": {"error_pieces": 9}}
    assert pc.label_payload(dict(before), MARCH, "/dashboard/error-decomposition")["totals"] == {"error_pieces": 9}
    mine = {"available": False, "blocked_reason": "No product-level forecasts exist for Del Monte", "period_end": "2026-03"}
    assert pc.label_payload(dict(mine), MARCH, "/dashboard/error-decomposition")["blocked_reason"] == mine["blocked_reason"]


def test_stored_figures_on_or_after_the_month_go_older_ones_stay():
    params = {"method": "ma3", "wape": 0.2, "holdout_metrics_served": {"mase": 0.4}, "holdout_metrics_all_methods": {}, "oracle_method": "naive", "run": {"written_at": "x"}}
    body = {"forecast": [
        {"forecast_date": "2026-02-01", "mase": 0.5, "mape": 20.0, "confidence_lower": 1.0, "confidence_upper": 2.0, "model_params": dict(params)},
        {"forecast_date": "2026-03-01", "mase": 0.5, "mape": 20.0, "confidence_lower": 1.0, "confidence_upper": 2.0, "model_params": dict(params)},
        {"forecast_date": "2026-04-01", "forecast_value": 9.0, "mase": 0.4, "mape": 20.0, "confidence_lower": 1.0, "confidence_upper": 2.0, "model_params": dict(params)}]}
    out = pc.label_payload(body, MARCH, "/forecast/1")
    old, march, april = out["forecast"]
    assert old["mase"] == 0.5 and old["model_params"]["wape"] == 0.2 and "accuracy_withheld" not in old
    for row in (march, april):
        assert row["mase"] is None and row["mape"] is None and row["confidence_lower"] is None and row["accuracy_withheld"]
        assert row["model_params"] == {"method": "ma3", "run": {"written_at": "x"}}
    assert april["forecast_value"] == 9.0 and accuracy_figure(out) is None


def test_undated_counts_and_a_figure_in_a_sentence_go_and_the_threshold_stays():
    out = pc.label_payload({"forecast": {"evaluated_count": 185, "unreliable_count": 64, "total_count": 191, "mase_gate": 1.0},
                            "items": [{"no_target_reason": "Not planned: forecast accuracy check not passed (MASE 2.54)", "product_name": "DOMEX 24(15% OFF)"}]}, MARCH, "/dashboard")
    assert out["forecast"]["evaluated_count"] is None and out["forecast"]["total_count"] == 191 and out["forecast"]["mase_gate"] == 1.0
    assert "2.54" not in out["items"][0]["no_target_reason"] and out["items"][0]["product_name"] == "DOMEX 24(15% OFF)"
    assert accuracy_figure(out) is None


def test_del_monte_has_no_figure_on_the_generated_month_and_is_left_alone():
    body = {"principal": "delmonte", "rows": [{"period": "2026-03", "mase": 0.7}]}
    assert pc.label_payload(body, MARCH, "/x")["rows"][0]["mase"] == 0.7


def test_no_generated_month_withholds_nothing_and_unreadable_months_withhold_everything():
    assert pc.label_payload({"forecast_accuracy": _card(), "x": {"mase": 0.4}}, [], "/dashboard")["x"]["mase"] == 0.4
    out = pc.label_payload({"forecast_accuracy": _card("2024-01", "2024-12"), "x": {"forecast_date": "2024-01-01", "mase": 0.4}}, None, "/dashboard")
    assert out["forecast_accuracy"]["accuracy_withheld"] is True and out["x"]["mase"] is None


def test_the_checker_catches_what_the_withholding_would_miss():
    assert accuracy_figure({"typical_product_weighted": {"value": 0.46}}) == "typical_product_weighted"
    assert accuracy_figure({"forecast": [{"forecast_date": "2026-04-01", "mase": 0.4}]}) == "mase"
    assert accuracy_figure({"reason": "not passed (MASE 2.54)"}) == "MASE in a sentence"
    assert accuracy_figure({"end_period": "2026-02", "wape_pieces": 0.3}) is None
    assert "accuracy figure" in body_label_problem({"practice_copy": {"not_a_result": True, "generated_months": MARCH}, "mase": 0.4})


def test_a_plan_is_closed_only_when_every_row_and_the_cycle_say_so():
    assert pc.plan_state_of(121, 0, None) == "run"
    assert pc.plan_state_of(121, 121, "closed") == "closed"
    assert pc.plan_state_of(121, 60, "closing") == "closing"
    assert pc.plan_state_of(121, 60, "closed") == "run"
    assert pc.plan_state_of(0, 0, "closed") == "run"


def test_an_uploaded_month_is_withheld_with_its_own_reason_and_is_not_called_generated():
    out = pc.label_payload({"forecast_accuracy": _card(), "rows": [{"period": "2026-03", "data_kind": "real", "estimated": False}]}, [], "/dashboard", MARCH)
    reason = out["forecast_accuracy"]["blocked_reason"]
    assert "uploaded file" in reason and "generated" not in reason and out["forecast_accuracy"]["company_total"]["value"] is None
    assert out["rows"][0] == {"period": "2026-03", "data_kind": "real", "estimated": False}
    assert out["practice_copy"]["generated_months"] == []


def test_a_range_before_an_uploaded_month_keeps_its_figures_and_both_kinds_are_named():
    out = pc.label_payload({"forecast_accuracy": _card("2025-03", "2026-02")}, [], "/dashboard", MARCH)
    assert out["forecast_accuracy"]["company_total"]["value"] == 0.109
    both = pc.accuracy_withheld_reason(["2026-03"], ["2026-04"])
    assert "2026-03 on this practice copy are generated" in both and "2026-04 on this practice copy came from an uploaded file" in both
    assert "before 2026-03" in both


def test_unreadable_uploads_withhold_everything():
    assert pc.label_payload({"x": {"forecast_date": "2024-01-01", "mase": 0.4}}, [], "/x", None)["x"]["mase"] is None


def test_the_prefix_is_the_folder_the_panel_keeps_uploads_in():
    from backend.routers import monthly_batch
    assert monthly_batch.UPLOADS.as_posix().endswith(pc.UPLOAD_SRC_PREFIX.rstrip("/"))


def test_the_job_log_loses_its_error_lines_and_keeps_the_rest():
    log = ("[computed on generated sales] MASE median                              0.9\n[computed on generated sales] MASE<1.0 pass count   93/183\n"
           "[lp] running\nWARNING: DOMEX 24(15% OFF) (unilever): not in the opening stock count (2026-03)\n")
    assert accuracy_figure({"log": log}) == "a forecast error figure in the job log"
    out = pc.label_payload({"job": {"status": "done", "log": log}}, MARCH, "/batch/status")
    kept = out["job"]["log"].split("\n")
    assert kept[0] == kept[1] == pc.LOG_LINE_WITHHELD and kept[2] == "[lp] running" and "DOMEX" in kept[3]
    assert accuracy_figure(out) is None
    assert pc.label_payload({"log": log}, [], "/batch/job")["log"] == log


def test_every_kind_of_error_line_the_forecast_prints_goes():
    lines = ["  MAE median    12.0   13.0   14.0", "  RMSE/MAE ratio (median)    1.2", "  outright wins (oracle-based)    3   4   5", "  gap rule vs oracle : +3.1 pp",
             "  smooth (42)      1       2       3         4       5", "      -> oracle_method=naive   rule_method=sba"]
    assert all(pc._withhold_log(line) == pc.LOG_LINE_WITHHELD for line in lines)
    for keep in ("  forecastable (status='ok') .................. 175", "[lp] running", "  dead_sku .................................. 5"):
        assert pc._withhold_log(keep) == keep


def test_the_rule_in_words_is_not_read_as_a_figure():
    assert accuracy_figure({"reason_text": "no smaller than the average change (MASE 1 or more), so the plan does not use it"}) is None
