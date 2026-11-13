"""analytics/demo_session.py, scripts/demo_session.py, scripts/demo_revert.py and scripts/demo_rehearsal.py: the gates of loading a month and rolling it back,
with no database.

What each protects: the window widens exactly one view and one function and refuses a definition it does not know; the forecast's guard opens only when
the DATABASE says the widened view is in force; checkpoints are named by month and found by their schemas, not by anything in memory; the load writes only
labelled rows, only for the month in the file, in the order the file's month allows; a write off this machine's throwaway server needs an attestation of
THIS code; a rollback restores the checkpoint, checks every table, view and function against it, and keeps the checkpoints if anything differs.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics import demo_session as ds
from analytics.forecasting import practice_switch as ps
from scripts import demo_rehearsal, demo_revert, demo_session as cli, report_target

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


class ViewCursor:
    """Answers the one question the witness asks: what the demand view's definition is."""

    def __init__(self, view=LIVE_VIEW):
        self.view, self.last = view, None

    def execute(self, sql, params=None):
        self.last = (sql, params)

    def fetchone(self):
        sql = self.last[0]
        if "pg_get_viewdef" in sql:
            return (self.view,)
        raise AssertionError(sql)


def test_the_witness_is_the_widened_view_in_force_in_the_connections_own_database():
    widened = ds.admitting_view_sql(LIVE_VIEW).split(" AS ", 1)[1]
    assert ds.permits_labelled_rows(ViewCursor(widened)) is True
    assert ds.permits_labelled_rows(ViewCursor(LIVE_VIEW)) is False


class ForecastCursor(ViewCursor):
    """A cursor of a database that is not the practice copy, holding generated rows."""

    def __init__(self, view, foreign=0):
        super().__init__(view)
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


def test_the_forecast_guard_opens_on_a_non_practice_database_only_while_the_database_says_so(caplog):
    widened = ds.admitting_view_sql(LIVE_VIEW).split(" AS ", 1)[1]
    with caplog.at_level("WARNING"):
        assert ps.labelled_rows_permitted(ForecastCursor(widened), LABELLED) is True
    said = " ".join(caplog.messages).lower()
    assert "loaded month" in said and "demonstration" not in said and "practice" not in said
    assert ps.labelled_rows_permitted(ForecastCursor(LIVE_VIEW), LABELLED) is False                  # window not in force: refused as it always was
    assert ps.labelled_rows_permitted(ForecastCursor(widened, foreign=3), LABELLED) is False         # a generated row with some other tag


def test_the_forecast_guard_never_asks_for_a_run_with_no_labelled_row():
    cur = ForecastCursor(LIVE_VIEW)
    assert ps.labelled_rows_permitted(cur, pd.DataFrame({"is_demo": [False]})) is False and cur.last is None


# ---- checkpoints are named by month and found by their schemas

def test_a_checkpoint_is_named_by_its_month():
    assert ds.month_tag("2026-03") == "m202603"
    assert ds.checkpoint_schema("2026-03") == "demo_revert_m202603" == demo_revert.snap_schema(ds.month_tag("2026-03"))
    assert ds.checkpoint_schema("2026-03") not in ds.SCHEMAS           # it lies outside what a snapshot copies
    with pytest.raises(ValueError):
        ds.month_tag("March")


def test_the_month_after():
    assert ds.next_month("2026-03") == "2026-04" and ds.next_month("2026-12") == "2027-01"


class RegistryCursor:
    def __init__(self, schemas, sessions):
        self.schemas, self.sessions, self.last = schemas, sessions, None

    def execute(self, sql, params=None):
        self.last = (sql, params)

    def fetchall(self):
        return [(s,) for s in self.schemas]

    def fetchone(self):
        sql, params = self.last
        if "to_regclass" in sql:
            return (params[0].strip('"').split('"')[0] in self.sessions,)
        schema = sql.split('FROM "')[1].split('"')[0]
        row = self.sessions[schema]
        return tuple(row.get(c) for c in ds.SESSION_COLUMNS)


def test_the_registry_is_the_schemas_oldest_month_first_and_an_unreadable_one_is_reported():
    cur = RegistryCursor(["demo_revert_m202604", "demo_revert_m202603", "demo_revert_m202605"],
                         {"demo_revert_m202603": {"state": "loaded", "month": "2026-03"}, "demo_revert_m202604": {"state": "taken", "month": "2026-04"}})
    found = ds.checkpoints(cur)
    assert [c["month"] for c in found] == ["2026-03", "2026-04", "2026-05"]
    assert [c["state"] for c in found] == ["loaded", "taken", "unreadable"]


def test_the_history_is_bounded_and_the_oldest_goes_only_after_a_new_month_loaded():
    assert ds.MAX_CHECKPOINTS == 2
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert "while len(cps) > ds.MAX_CHECKPOINTS" in src and "cps.pop(0)" in src
    assert src.index("while len(cps) > ds.MAX_CHECKPOINTS") > src.index('mark(conn, month, state="loaded"')      # released AFTER the new month loaded, never before


# ---- a snapshot copies what a month can change and fingerprints everything

def test_the_tables_a_sales_month_never_touches_are_fingerprinted_not_copied():
    assert {"public.sales_fact", "public.inventory_fact"} <= demo_revert.UNCOPIED
    assert not {"public.lp_recommendation", "public.unilever_sku_demand_fact", "public.forecast_result", "app.users"} & demo_revert.UNCOPIED
    src = Path(demo_revert.__file__).read_text(encoding="utf-8")
    assert "if key not in copied:" in src and "compare(cur, manifest)" in src          # an uncopied table is still compared, so a change refuses the revert


def test_revert_never_reassigns_the_hook_it_was_given():
    """Found in the first browser rehearsal: a loop variable named like the hook shadowed it, so the definitions were never put back while the revert
    said they were. The hook's name must be assigned nowhere inside revert, and the rollback must check the definitions again after the commit."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(demo_revert.revert)).body[0]
    assigned = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert "after_tables" not in assigned
    assert "definitions_fingerprint" in inspect.getsource(cli.rollback_month).split("failures = []")[0]


# ---- the loader

def test_the_loader_writes_only_labelled_rows_and_the_window_opens_with_the_checkpoint():
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert "ds.TAG, ds.TAG, True" in src                       # _src_file, _src_sheet, is_demo = true
    assert src.index("take_checkpoint(conn, month") < src.index("write_rows(conn, rows, month)")      # a way back exists before any row is written
    assert src.index("accept_waiting(args.by") < src.index("write_rows(conn, rows, month)")


def test_a_month_that_did_not_finish_is_finished_or_rolled_back_before_another_starts():
    cur = RegistryCursor(["demo_revert_m202603"], {"demo_revert_m202603": {"state": "failed", "month": "2026-03"}})
    assert cli.expected_month(cur) == "2026-03"


# ---- the gate

def test_a_write_off_the_throwaway_server_needs_the_flag_and_an_attestation_of_this_code(monkeypatch):
    cli.gate(True, False)                                                                  # this machine's server: always
    with pytest.raises(SystemExit, match="--target-public"):
        cli.gate(False, False)
    monkeypatch.setattr(demo_rehearsal, "ok", lambda: (False, "the load and rollback code changed after its rehearsal"))
    with pytest.raises(SystemExit, match="changed after its rehearsal"):
        cli.gate(False, True)
    monkeypatch.setattr(demo_rehearsal, "ok", lambda: (True, ""))
    cli.gate(False, True)


def test_the_attestation_counts_only_for_the_code_it_was_made_on_and_covers_every_step(monkeypatch, tmp_path):
    proof = tmp_path / "rehearsal.json"
    monkeypatch.setattr(demo_rehearsal, "PROOF", proof)
    assert demo_rehearsal.ok()[0] is False and "no rehearsal" in demo_rehearsal.ok()[1]
    steps = {name: {"exact": True} for name in demo_rehearsal.STEPS}
    demo_rehearsal.write("127.0.0.1/ssm_rehearsal", steps, (109, 435988), "backup")
    assert demo_rehearsal.ok() == (True, "")
    record = json.loads(proof.read_text(encoding="utf-8"))
    proof.write_text(json.dumps({**record, "code_hash": "0" * 64}), encoding="utf-8")
    assert "changed after its rehearsal" in demo_rehearsal.ok()[1]
    proof.write_text(json.dumps({**record, "target": "aws-0.pooler.supabase.com/postgres"}), encoding="utf-8")
    assert "not made on a restored copy" in demo_rehearsal.ok()[1]
    proof.write_text(json.dumps({**record, "steps": {**steps, "rollback_first": {"exact": False}}}), encoding="utf-8")
    assert "every step exact" in demo_rehearsal.ok()[1]


def test_the_attestation_is_committed_so_a_hosted_server_has_it_without_a_terminal():
    assert demo_rehearsal.PROOF == demo_rehearsal.REPO / "docs" / "MONTH_LOAD_REHEARSAL.json"
    assert "docs/MONTH_LOAD_REHEARSAL.json" not in (demo_rehearsal.REPO / ".gitignore").read_text(encoding="utf-8")


def test_the_attested_files_include_everything_that_writes():
    for name in ("scripts/demo_session.py", "scripts/demo_revert.py", "analytics/demo_session.py", "analytics/month_file.py", "scripts/run_month.py"):
        assert name in demo_rehearsal.FILES


def test_the_attested_files_include_what_a_load_runs():
    """A load runs ABC, the forecast and the LP (scripts/run_month.py). The 2026-11-11 attestation stayed valid after the calendar
    factor moved to product grain (2026-11-13) because none of that code was hashed."""
    for name in ("analytics/params.py", "analytics/forecasting/calendar.py", "analytics/forecasting/router.py",
                 "scripts/run_baseline_forecast.py", "scripts/run_lp.py", "analytics/optimization/lp.py",
                 "analytics/classification/orchestrate_abc.py"):
        assert name in demo_rehearsal.FILES
    for name in demo_rehearsal.FILES:
        assert (demo_rehearsal.REPO / name).is_file(), name


def test_a_load_writes_no_tracked_report(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@aws-0.pooler.supabase.com:6543/postgres")
    monkeypatch.delenv(report_target.DEMO_SESSION_ENV, raising=False)
    tracked = report_target.REPO / "docs" / "X.md"
    assert report_target.report_path(tracked) == tracked.resolve()
    monkeypatch.setenv(report_target.DEMO_SESSION_ENV, "month_load")
    assert report_target.writes_tracked_reports() is False
    assert "nonlive_reports" in str(report_target.report_path(tracked))
    assert "SSM_DEMO_SESSION" in Path(cli.__file__).read_text(encoding="utf-8")
