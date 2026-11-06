"""The labels a practice run's output carries, and that a real run's output does not (scripts/practice_artefacts.py runs the month itself)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend import practice_copy
from backend.routers import monthly_batch as mb
from scripts import cycle_feedback as cf
from scripts import local_pg, run_lp
from scripts import practice_artefacts as pa
from scripts import run_baseline_forecast as rbf
from scripts.report_target import PRACTICE_MARKER, is_practice_target


def test_a_file_needs_the_marker_near_its_start():
    assert pa.file_has_marker(f"# {PRACTICE_MARKER}\nrest".encode())
    assert not pa.file_has_marker(b"sku_code,forecast\n")
    assert not pa.file_has_marker(b"x" * pa.MARKER_WINDOW + PRACTICE_MARKER.encode())


def test_the_file_diff_finds_new_and_changed_files_only():
    before = {"same": (1, 1), "changed": (1, 1)}
    assert pa.changed_files(before, {"same": (1, 1), "changed": (1, 2), "new": (1, 1)}) == ["changed", "new"]


def test_a_data_route_answering_without_the_label_fails_the_check():
    label = {pa.LABEL_HEADER: "practice"}
    body = {"items": [], "practice_copy": {"not_a_result": True, "generated_months": [pa.MONTH]}}
    assert pa.route_verdict("/recommendations", 200, body) is not None
    assert pa.route_verdict("/recommendations", 200, {"items": []}, label) is not None    # the header alone is not enough
    assert pa.route_verdict("/recommendations", 200, body, label) is None
    assert pa.route_verdict("/recommendations", 409, {"code": "practice_copy_not_served"}) is None
    assert pa.route_verdict("/batch/status", 200, {"enabled": True, "practice_copy": body["practice_copy"]}, label) is not None
    assert pa.route_verdict("/batch/status", 200, {"practice_note": "x", "practice_copy": body["practice_copy"]}, label) is None
    assert pa.route_verdict("/health", 200, {"status": "ok"}) is None


def test_a_route_this_check_could_not_read_fails_rather_than_passing():
    assert "could not read" in pa.route_verdict("/dashboard/product-sales", 422, {"detail": []})


def test_routes_are_called_with_real_identifiers():
    assert pa.route_url("/forecast/{sku_id}", "21015692", 3) == "/forecast/21015692?principal=unilever"
    assert pa.route_url("/decomposition", "21015692", 3) == "/decomposition?sku=21015692"
    assert pa.route_url("/admin/users/{user_id}/permissions", "21015692", 3) == "/admin/users/3/permissions"
    assert pa.route_url("/recommendations/{recommendation_key}/history", "21015692", 3) == "/recommendations/1/history"


def test_without_the_connection_confirming_only_batch_and_health_answer(monkeypatch):
    monkeypatch.setattr(practice_copy, "confirmed", lambda: False)
    assert mb.practice_copy_refusal("/recommendations")["code"] == "practice_copy_not_served"
    assert mb.practice_copy_refusal("/batcher")["code"] == "practice_copy_not_served"
    assert mb.practice_copy_refusal("/status")["code"] == "practice_copy_not_served"
    assert mb.practice_copy_refusal("/batch/status") is None
    assert mb.practice_copy_refusal("/health") is None


def test_the_connection_confirming_opens_the_data_routes(monkeypatch):
    monkeypatch.setattr(practice_copy, "confirmed", lambda: True)
    assert mb.practice_copy_refusal("/recommendations") is None
    assert mb.practice_copy_refusal("/dashboard") is None


def test_a_url_that_names_the_copy_is_not_enough(monkeypatch):
    """The server, not the URL, has the last word: the same test as the forecast's exception."""
    monkeypatch.setattr(practice_copy, "_server_confirms", lambda url: False)
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/ssm_practice")
    assert practice_copy.names_practice_copy() and is_practice_target() and not practice_copy.confirmed()
    assert mb.practice_copy_refusal("/dashboard")["code"] == "practice_copy_not_served"


@pytest.mark.parametrize("url", ["postgresql://postgres@127.0.0.1:55432/ssm_local", "postgresql://u:p@db.example.supabase.co:5432/postgres", ""])
def test_every_other_database_never_asks(monkeypatch, url):
    def asked(_url):
        raise AssertionError("the deployed API must not connect or import anything for this")
    monkeypatch.setattr(practice_copy, "_server_confirms", asked)
    monkeypatch.setenv("SUPABASE_DB_URL", url)
    assert not practice_copy.confirmed() and not mb.on_practice_copy() and not is_practice_target()


def test_the_copy_only_kind_rule_keeps_the_retired_family_out():
    sql = " ".join(local_pg.PRACTICE_KIND_SQL.split())
    assert "WHEN p_is_demo IS NOT TRUE OR p_fill_source IS NULL THEN 'real'" in sql
    assert "WHEN p_fill_source = 'synthetic_v2' THEN 'generated'" in sql


def test_no_migration_or_mart_reader_carries_the_practice_kind_rule():
    repo = Path(__file__).resolve().parents[1]
    for path in sorted((repo / "analytics/db/migrations").glob("*.sql")):
        assert "p_is_demo IS NOT TRUE OR p_fill_source IS NULL" not in path.read_text(encoding="utf-8"), path.name
    assert "practice_copy" not in (repo / "backend/marts.py").read_text(encoding="utf-8")


def test_the_row_label_goes_only_into_the_practice_copy(monkeypatch):
    calls = []
    monkeypatch.setattr(local_pg, "_psql", lambda db, sql=None, file=None: (calls.append((db, sql)), type("R", (), {"returncode": 0, "stderr": ""})())[1])
    local_pg.make_practice()
    assert [db for db, sql in calls if sql == local_pg.PRACTICE_ROW_LABEL_SQL] == ["ssm_practice"]
    assert [db for db, sql in calls if sql == local_pg.PRACTICE_KIND_SQL] == ["ssm_practice"]
    sql = " ".join(local_pg.PRACTICE_ROW_LABEL_SQL.split())
    assert "BEFORE INSERT OR UPDATE" in sql and "ADD COLUMN practice_run text" in sql
    assert "DEFAULT" not in sql   # the rows the copy started with stay NULL: they are real


def test_the_feedback_says_so_when_the_generated_rows_are_only_in_the_history(tmp_path, monkeypatch):
    report = {"cycle": "2026-04", "synthetic_rows": 0, "generated_rows": 709, "receipts": [],
              "forecast": cf.score([], True, 709),
              "decisions": cf.summarize_decisions([])}
    lines = cf.render(report)
    assert PRACTICE_MARKER in lines[0]
    monkeypatch.setattr(cf, "REPO", tmp_path)
    path = cf.save(report, [], lines, live=False)
    assert PRACTICE_MARKER in path.read_text(encoding="utf-8").splitlines()[0]
    assert PRACTICE_MARKER in path.with_suffix(".csv").read_text(encoding="utf-8").splitlines()[0]


def test_real_feedback_carries_no_marker(tmp_path, monkeypatch):
    report = {"cycle": "2026-02", "synthetic_rows": 0, "generated_rows": 0, "receipts": [],
              "forecast": cf.score([], True, 0), "decisions": cf.summarize_decisions([])}
    lines = cf.render(report)
    monkeypatch.setattr(cf, "REPO", tmp_path)
    path = cf.save(report, [], lines, live=True)
    assert PRACTICE_MARKER not in path.read_text(encoding="utf-8")
    assert PRACTICE_MARKER not in path.with_suffix(".csv").read_text(encoding="utf-8")


def test_the_forecast_markdown_opens_with_the_marker_only_when_labelled():
    assert pa.file_has_marker(rbf._md_opening(True)[0].encode())
    assert rbf._md_opening(False) == []


def test_lp_files_are_labelled_on_the_practice_copy_only(monkeypatch):
    df = pd.DataFrame({"sku": ["1"]})
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/ssm_practice")
    assert run_lp._practice_labelled(df)["practice_marker"].tolist() == [PRACTICE_MARKER]
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@db.example.supabase.co:5432/postgres")
    assert list(run_lp._practice_labelled(df).columns) == ["sku"]


def test_settling_decisions_refuses_any_database_but_the_practice_copy(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://user:pw@aws-0.pooler.supabase.com:6543/postgres")
    assert pa.settle_decisions() == 2
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/ssm_local")
    assert pa.settle_decisions() == 2


def test_the_practice_run_settles_its_decisions_before_the_month():
    """run_month refuses a month with open decisions, and this check goes through the same door."""
    source = Path(pa.__file__).read_text(encoding="utf-8")
    assert source.index('"--settle-decisions"],') < source.index('[py, "-m", "scripts.run_month", *month]')
