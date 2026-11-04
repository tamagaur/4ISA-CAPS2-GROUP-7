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
from scripts.practice_artefacts import body_label_problem, reads_as_real

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
