"""analytics/demo_session.py, scripts/demo_session.py and backend/routers/live_demo.py: the gates of the live demonstration, with no database.

What each protects: the window widens exactly one view and one function and refuses a definition it does not know; the forecast's guard
opens for a session only when the DATABASE says one is open and in force; the loader refuses what it must; the route set is off by default and
needs a person's switch, a named host and a passing revert proof; and a demonstration never writes a tracked report.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics import demo_session as ds
from analytics.forecasting import practice_switch as ps
from scripts import demo_revert, demo_session as cli, report_target

LIVE_VIEW = ("SELECT demand_key,\n    product_key,\n    sku_code,\n    calendar_month,\n    region,\n    quantity_sold,\n    net_amount,\n"
             "    _src_file,\n    _src_sheet,\n    is_demo,\n    gsv\n   FROM unilever_sku_demand_fact\n  WHERE is_demo = false")
LIVE_FUNCTION = ("CREATE OR REPLACE FUNCTION mart.data_kind(p_is_demo boolean, p_fill_source text)\n RETURNS text\n LANGUAGE sql\n IMMUTABLE\nAS $function$\n"
                 "    SELECT CASE\n        WHEN p_is_demo IS NOT TRUE THEN 'real'\n        WHEN p_fill_source IS NULL OR p_fill_source = 'synthetic_v2' THEN 'generated'\n"
                 "        ELSE 'filled'\n    END\n$function$\n")
LABELLED = pd.DataFrame({"calendar_month": ["2026-03"], "quantity": [1.0], "is_demo": [True]})


def test_the_window_widens_the_one_clause_and_nothing_else():
    sql = ds.admitting_view_sql(LIVE_VIEW)
    assert sql.startswith("CREATE OR REPLACE VIEW public.unilever_sku_demand_fact_real AS ")
    assert sql.endswith(f"WHERE is_demo = false OR (is_demo = true AND _src_file = '{ds.TAG}'::text)")
    assert sql.replace(ds.ADMITTING, ds.REAL_ONLY) == ds.restoring_view_sql(LIVE_VIEW)      # undoing the one clause gives the original back


def test_a_view_it_does_not_know_is_refused_not_guessed():
    for odd in (LIVE_VIEW.replace("is_demo = false", "true"), LIVE_VIEW + "\n  WHERE is_demo = false"):
        with pytest.raises(RuntimeError, match="does not end in"):
            ds.admitting_view_sql(odd)
    with pytest.raises(RuntimeError, match="not the definition"):
        ds.admitting_function_sql(LIVE_FUNCTION.replace("synthetic_v2", "something_else"))


def test_the_function_counts_only_a_row_with_no_fill_source_and_keeps_the_retired_family_generated():
    sql = ds.admitting_function_sql(LIVE_FUNCTION)
    assert "WHEN p_fill_source IS NULL THEN 'real' WHEN p_fill_source = 'synthetic_v2' THEN 'generated' ELSE 'filled'" in sql


class SessionCursor:
    """Answers the questions the witness asks."""

    def __init__(self, state=None, view=LIVE_VIEW):
        self.state, self.view, self.last = state, view, None

    def execute(self, sql, params=None):
        self.last = (sql, params)

    def fetchone(self):
        sql = self.last[0]
        if "to_regclass" in sql:
            return (self.state is not None,)
        if sql == ds.SESSION_SQL:
            return None if self.state is None else (self.state, None, "x", 109, 435988, "2026-03-01", "f")
        if "pg_get_viewdef" in sql:
            return (self.view,)
        raise AssertionError(sql)


def test_the_witness_needs_an_open_session_and_the_widened_view_in_force():
    widened = ds.admitting_view_sql(LIVE_VIEW).split(" AS ", 1)[1]
    assert ds.permits_labelled_rows(SessionCursor("open", widened)) is True
    assert ds.permits_labelled_rows(SessionCursor("open", LIVE_VIEW)) is False        # open, but the window is not in force
    assert ds.permits_labelled_rows(SessionCursor(None, widened)) is False            # the view is wide, but no session is recorded
    assert ds.permits_labelled_rows(SessionCursor("closing", widened)) is False


class ForecastCursor(SessionCursor):
    """A cursor of a database that is not the practice copy, holding generated rows."""

    def __init__(self, state, view, foreign=0):
        super().__init__(state, view)
        self.connection = SimpleNamespace(info=SimpleNamespace(host="aws-0.pooler.supabase.com", port=6543, dbname="postgres"))
        self.foreign = foreign

    def fetchone(self):
        sql = self.last[0]
        if sql == ps.SERVER_IDENTITY_SQL:
            return ("10.0.0.5", 6543, "postgres")
        if "IS DISTINCT FROM" in sql:
            return (self.foreign,)
        if sql == ps.LABELLED_ROWS_SQL:
            return (709,)
        return super().fetchone()


def test_the_forecast_guard_opens_for_a_session_on_a_non_practice_database_only_while_the_database_says_so(caplog):
    widened = ds.admitting_view_sql(LIVE_VIEW).split(" AS ", 1)[1]
    with caplog.at_level("WARNING"):
        assert ps.labelled_rows_permitted(ForecastCursor("open", widened), LABELLED) is True
    assert "open demonstration session" in caplog.text
    assert ps.labelled_rows_permitted(ForecastCursor(None, LIVE_VIEW), LABELLED) is False       # no session: refused as it always was
    assert ps.labelled_rows_permitted(ForecastCursor("open", LIVE_VIEW), LABELLED) is False      # session without the window
    assert ps.labelled_rows_permitted(ForecastCursor("open", widened, foreign=3), LABELLED) is False   # a generated row with some other tag


def test_the_forecast_guard_never_asks_a_session_for_a_run_with_no_labelled_row():
    cur = ForecastCursor("open", LIVE_VIEW)
    assert ps.labelled_rows_permitted(cur, pd.DataFrame({"is_demo": [False]})) is False and cur.last is None


# ---- the loader's file rules

def write(tmp_path, text):
    p = tmp_path / "f.csv"
    p.write_text(text, encoding="utf-8")
    return p


def test_the_file_needs_its_columns_and_refuses_what_is_wrong_per_line(tmp_path):
    rows, problems = cli.read_demo_file(write(tmp_path, "sku,qty\n1,2\n"), "2026-03")
    assert rows == [] and "no column sku_code" in problems[0]
    text = ("sku_code,calendar_month,quantity_sold,net_amount\n"
            "A,2026-03,5,10.5\nA,2026-03,6,11\nB,2026-04,1,1\nC,2026-03,x,1\nD,2026-03,-1,1\nE,2026-03,2,3\n,2026-03,1,1\n")
    rows, problems = cli.read_demo_file(write(tmp_path, text), "2026-03")
    assert [r["sku_code"] for r in rows] == ["A", "E"]
    joined = " | ".join(problems)
    for expected in ("A appears twice", "B is for 2026-04", "C has a quantity", "D has a negative", "no sku_code"):
        assert expected in joined


def test_an_empty_file_is_refused(tmp_path):
    assert cli.read_demo_file(write(tmp_path, "sku_code,quantity_sold,net_amount\n"), "2026-03")[1] == ["the file has no rows"]


def test_the_loader_writes_only_labelled_rows_and_only_through_an_open_window():
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert "ds.TAG, ds.TAG, True" in src                       # _src_file, _src_sheet, is_demo = true
    assert "no demonstration session is open in this database" in src


# ---- the gates

def test_a_write_off_the_throwaway_server_needs_the_flag_and_a_passing_proof(tmp_path):
    proof = tmp_path / "proof.json"
    with pytest.raises(SystemExit, match="--target-public"):
        demo_revert.require_write_allowed(False, False, proof)
    with pytest.raises(SystemExit, match="no passing revert proof"):
        demo_revert.require_write_allowed(False, True, proof)
    proof.write_text(json.dumps({"passed": False}))
    with pytest.raises(SystemExit):
        demo_revert.require_write_allowed(False, True, proof)
    proof.write_text(json.dumps({"passed": True}))
    demo_revert.require_write_allowed(False, True, proof)


def test_the_routes_are_off_unless_a_person_switches_them_on_and_name_the_host(monkeypatch, tmp_path):
    from backend.routers import live_demo
    live = "postgresql://u:p@aws-0-ap.pooler.supabase.com:6543/postgres"
    proof = tmp_path / "proof.json"
    monkeypatch.setattr(live_demo, "PROOF_FILE", proof)
    rehearsed = {"ok": True}
    monkeypatch.setattr(live_demo.demo_rehearsal, "ok", lambda: (rehearsed["ok"], "" if rehearsed["ok"] else "changed"))
    for name in ("LIVE_DEMO_ENABLED", "LIVE_DEMO_CONFIRM_HOST", "RENDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPABASE_DB_URL", live)
    assert live_demo.enabled() is False                                   # no switch
    monkeypatch.setenv("LIVE_DEMO_ENABLED", "true")
    assert live_demo.enabled() is False                                   # a switch, but no named host and no proof
    monkeypatch.setenv("LIVE_DEMO_CONFIRM_HOST", "some-other-host")
    proof.write_text(json.dumps({"passed": True}))
    assert live_demo.enabled() is False                                   # a host that is not this one's
    monkeypatch.setenv("LIVE_DEMO_CONFIRM_HOST", "aws-0-ap.pooler.supabase.com")
    proof.write_text(json.dumps({"passed": False}))
    assert live_demo.enabled() is False                                   # the proof did not pass
    proof.write_text(json.dumps({"passed": True}))
    assert live_demo.enabled() is True
    rehearsed["ok"] = False
    assert live_demo.enabled() is False                                   # the code changed after its rehearsal
    rehearsed["ok"] = True
    monkeypatch.setenv("RENDER", "true")
    assert live_demo.enabled() is False                                   # never on the hosted service
    monkeypatch.delenv("RENDER")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/ssm_rehearsal")
    assert live_demo.enabled() is True                                    # a database on this machine needs no proof


def test_the_deployed_api_does_not_have_the_routes():
    import os
    from backend.main import app
    if os.environ.get("LIVE_DEMO_ENABLED"):
        pytest.skip("this process switched the demonstration on")
    assert not [r for r in app.routes if getattr(r, "path", "").startswith("/live-demo")]


def test_the_card_shows_only_the_lines_a_person_may_read():
    from backend.routers.live_demo import SHOWN
    shown = ["[undo] 1/4 done", "[load] 709 generated sales rows", "[abc] running", "REFUSED: 73 reorder", "  plan 2026-04: 121 rows, 110 ordering",
             "[marts] refreshed"]
    hidden = ["INFO: MASE 0.84", "postgresql://u:p@host/db", "Traceback (most recent call last):"]
    assert all(SHOWN.match(x) for x in shown)
    assert not any(SHOWN.match(x) for x in hidden)


def test_a_demonstration_writes_no_tracked_report(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@aws-0.pooler.supabase.com:6543/postgres")
    monkeypatch.delenv(report_target.DEMO_SESSION_ENV, raising=False)
    tracked = report_target.REPO / "docs" / "X.md"
    assert report_target.report_path(tracked) == tracked.resolve()
    monkeypatch.setenv(report_target.DEMO_SESSION_ENV, "live_demo")
    assert report_target.writes_tracked_reports() is False
    assert report_target.is_practice_target() is True                       # its output is labelled practice
    assert "nonlive_reports" in str(report_target.report_path(tracked))


def test_the_session_snapshot_schema_is_the_one_demo_revert_names_and_lies_outside_what_it_copies():
    assert demo_revert.snap_schema(ds.SESSION_TAG) == ds.SNAP_SCHEMA
    assert ds.SNAP_SCHEMA not in ds.SCHEMAS


def test_revert_never_reassigns_the_hook_it_was_given():
    """Found in the first browser rehearsal: a loop variable named like the hook shadowed it, so the definitions were never put back while undo said
    they were. The hook's name must be assigned nowhere inside revert, and undo must check the definitions again after the commit."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(demo_revert.revert)).body[0]
    assigned = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert "after_tables" not in assigned
    assert "definitions_fingerprint" in inspect.getsource(cli.undo_session).split("failures = []")[0]
