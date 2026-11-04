"""scripts/run_month.py: the gates, the order of the steps, stopping, resuming. The SQL and the real steps run in the
local rehearsal (reports/MONTHLY_BATCH_REHEARSAL_2026-11-02.md), not here."""
from __future__ import annotations

import argparse
import datetime

import pytest

from scripts import run_month as rm

MONTH = datetime.date(2026, 3, 1)
NONE_DONE = {"sales_loaded": True, "count_loaded": True, "abc_run": False, "forecast_next": False, "lp_next": False}
NO_OPEN = {"cycle": "2026-03", "actionable_pending": 0, "zero_quantity_pending": 0, "decided": 0, "historical_pending": 0, "later_pending": 0,
           "open_quantity_changes": 0, "open_dismissal_requests": 0, "open_requests": 0}
FACTS = {"latest_sales_month": "2026-03", "synthetic_rows": 0, "decisions": NO_OPEN}


def test_a_month_holding_only_labelled_generated_rows_is_refused_and_says_why():
    facts = {"latest_sales_month": "2026-02", "synthetic_rows": 709, "decisions": NO_OPEN}
    checks = {"sales_loaded": False, "abc_run": False}
    refusals = rm.preflight_refusals(datetime.date(2026, 3, 1), facts, checks, [], live=False)
    assert len(refusals) == 1 and "709 generated sales rows" in refusals[0] and "is_demo" in refusals[0]


def _args(**kw):
    base = {"month": MONTH, "calendar_factor": "on", "slice": [], "approved_by": None, "expect_month": None,
            "target_public": False, "close": False, "expect_plan_pieces": None, "file": [], "check_files": False, "check_files_report": None}
    return argparse.Namespace(**{**base, **kw})


# ---- the gate -------------------------------------------------------------------------------------------------------

def test_no_approval_means_a_dry_run():
    assert rm.gate_errors(_args(), live=True) == []
    assert rm.is_write(_args()) is False


@pytest.mark.parametrize("kw", [{"approved_by": "Kelvin"}, {"expect_month": MONTH}])
def test_a_write_needs_both_the_name_and_the_month(kw):
    assert "BOTH" in rm.gate_errors(_args(**kw), live=False)[0]


def test_a_write_refuses_a_month_nobody_named():
    errors = rm.gate_errors(_args(approved_by="Kelvin", expect_month=datetime.date(2026, 4, 1)), live=False)
    assert "is not --month" in errors[0]


def test_writing_to_live_needs_target_public_and_local_does_not():
    args = _args(approved_by="Kelvin", expect_month=MONTH)
    assert "--target-public" in rm.gate_errors(args, live=True)[0]
    assert rm.gate_errors(args, live=False) == []
    assert rm.gate_errors(_args(approved_by="Kelvin", expect_month=MONTH, target_public=True), live=True) == []


def test_a_close_needs_the_plan_total_the_person_saw():
    args = _args(approved_by="Kelvin", expect_month=MONTH, close=True)
    assert "--expect-plan-pieces" in rm.gate_errors(args, live=False)[0]


def test_the_calendar_factor_has_no_default():
    with pytest.raises(SystemExit):
        rm.build_parser().parse_args(["--month", "2026-03"])
    assert rm.build_parser().parse_args(["--month", "2026-03", "--calendar-factor", "off"]).calendar_factor == "off"


# ---- the refusals before anything runs ------------------------------------------------------------------------------

def test_a_clean_month_is_not_refused():
    assert rm.preflight_refusals(MONTH, FACTS, NONE_DONE, [], live=True) == []


def test_no_sales_and_nothing_to_load_is_refused():
    checks = {**NONE_DONE, "sales_loaded": False}
    assert "not loaded" in rm.preflight_refusals(MONTH, {**FACTS, "latest_sales_month": "2026-02"}, checks, [], live=False)[0]


def test_no_sales_is_not_refused_when_a_slice_will_load_them():
    checks = {**NONE_DONE, "sales_loaded": False}
    assert rm.preflight_refusals(MONTH, {**FACTS, "latest_sales_month": "2026-02"}, checks, ["unilever:unilever_sku_demand_fact:2026-03"], live=False) == []


def test_a_later_month_already_loaded_is_refused():
    assert "2026-04" in rm.preflight_refusals(MONTH, {**FACTS, "latest_sales_month": "2026-04"}, NONE_DONE, [], live=False)[0]


def test_synthetic_sales_on_live_are_refused_and_local_is_allowed():
    facts = {**FACTS, "synthetic_rows": 709}
    assert "synthetic" in rm.preflight_refusals(MONTH, facts, NONE_DONE, [], live=True)[0]
    assert rm.preflight_refusals(MONTH, facts, NONE_DONE, [], live=False) == []


def test_loading_again_after_the_abc_ran_is_refused():
    checks = {**NONE_DONE, "abc_run": True}
    assert "already" in rm.preflight_refusals(MONTH, FACTS, checks, ["unilever:unilever_sku_demand_fact:2026-03"], live=False)[0]


# ---- the steps ------------------------------------------------------------------------------------------------------

def test_the_steps_run_load_abc_forecast_lp_in_that_order():
    assert [s.name for s in rm.plan_steps(_args(slice=["a:b:2026-03"]), py="py")] == ["load", "abc", "forecast", "lp"]
    assert [s.name for s in rm.plan_steps(_args(), py="py")] == ["abc", "forecast", "lp"]


@pytest.mark.parametrize("choice,present", [("on", True), ("off", False)])
def test_the_forecast_uses_the_stated_calendar_factor(choice, present):
    forecast = next(s for s in rm.plan_steps(_args(calendar_factor=choice), py="py") if s.name == "forecast")
    assert ("--calendar-factor" in forecast.cmd) is present
    assert "--write" in forecast.cmd


def test_the_abc_step_reads_the_tier_a_basis_setting():
    from analytics.params import abc_method
    abc = next(s for s in rm.plan_steps(_args(), py="py") if s.name == "abc")
    assert abc.cmd[abc.cmd.index("--method") + 1] == abc_method("unilever")
    assert abc.cmd[abc.cmd.index("--period") + 1] == "2026-03"


def _steps():
    return [rm.Step("abc", ["abc"], "abc_run"), rm.Step("forecast", ["forecast"], "forecast_next"), rm.Step("lp", ["lp"], "lp_next")]


def test_all_steps_run_and_each_is_checked():
    done, ran = dict(NONE_DONE), []

    def runner(cmd):
        ran.append(cmd[0])
        done[{"abc": "abc_run", "forecast": "forecast_next", "lp": "lp_next"}[cmd[0]]] = True
        return 0

    assert rm.run_steps(_steps(), runner, lambda: done, out=lambda _: None) == 0
    assert ran == ["abc", "forecast", "lp"]


def test_a_failed_step_stops_the_run_with_its_exit_code():
    ran = []

    def runner(cmd):
        ran.append(cmd[0])
        return 7 if cmd[0] == "forecast" else 0

    done = {**NONE_DONE, "abc_run": True}
    assert rm.run_steps(_steps(), runner, lambda: done, out=lambda _: None) == 7
    assert ran == ["forecast"]


def test_a_rerun_skips_the_steps_already_done():
    ran = []
    done = {**NONE_DONE, "abc_run": True, "forecast_next": True, "lp_next": True}
    assert rm.run_steps(_steps(), lambda c: ran.append(c) or 0, lambda: done, out=lambda _: None) == 0
    assert ran == []


def test_a_step_that_exits_zero_without_doing_its_job_stops_the_run():
    lines = []
    assert rm.run_steps(_steps()[:1], lambda c: 0, lambda: dict(NONE_DONE), out=lines.append) == 2
    assert any("abc" in line and "did not" in line for line in lines)


# ---- the pause before the close -------------------------------------------------------------------------------------

def test_the_comparison_shows_both_plans_and_the_ratio():
    text = "\n".join(rm.plan_comparison(MONTH, {"rows": 109, "ordering": 73, "pieces": 435988.0},
                                        {"rows": 121, "ordering": 110, "pieces": 1213168.0, "opening_basis": "count"}))
    assert "435,988" in text and "1,213,168" in text and "2.78" in text and "count" in text


def test_the_comparison_survives_an_empty_old_plan():
    assert "n/a" in "\n".join(rm.plan_comparison(MONTH, {"rows": 0, "ordering": 0, "pieces": 0.0},
                                                 {"rows": 5, "ordering": 1, "pieces": 10.0, "opening_basis": "projected"}))


def test_the_close_refuses_when_the_plan_is_not_the_one_the_person_saw():
    assert rm.close_refusal(1213168, 1213168.4) is None
    assert "1,213,168" in rm.close_refusal(1213168, 900000.0)


def test_the_count_line_compares_the_newest_count_with_the_median_of_the_earlier_ones():
    rows = [("2026-03", "2026-04-06", 300.0), ("2026-02", "2026-03-02", 200.0), ("2026-01", "2026-02-02", 100.0), ("2025-12", "2026-01-05", 100.0)]
    text = "\n".join(rm.count_lines(rows))
    assert "2026-03" in text and "3.00" in text


def test_no_count_on_record_says_so():
    assert "no stock count" in rm.count_lines([])[0]


def test_our_own_output_is_flushed_before_a_child_prints(monkeypatch):
    order = []

    class _Out:
        def write(self, _):
            return 0

        def flush(self):
            order.append("flush")

    class _Done:
        returncode = 0

    def fake_run(cmd, cwd):
        order.append("child")
        return _Done()

    monkeypatch.setattr(rm.sys, "stdout", _Out())
    monkeypatch.setattr(rm.subprocess, "run", fake_run)
    assert rm._runner(["x"]) == 0
    assert order == ["flush", "child"]


# ---- the month in play, and the raw files -----------------------------------------------------------------------------

def test_the_month_in_play_is_the_newest_plan_when_the_one_before_is_settled():
    assert rm.pick_month(datetime.date(2026, 3, 1), prior_has_plan=False, prior_closed=False) == datetime.date(2026, 3, 1)
    assert rm.pick_month(datetime.date(2026, 4, 1), prior_has_plan=True, prior_closed=True) == datetime.date(2026, 4, 1)


def test_the_month_in_play_stays_on_the_old_one_until_it_is_closed():
    assert rm.pick_month(datetime.date(2026, 4, 1), prior_has_plan=True, prior_closed=False) == datetime.date(2026, 3, 1)


def test_named_files_go_to_the_loader():
    load = rm.plan_steps(_args(slice=["a:b:2026-03"], file=["local/x.xls"]), py="py")[0]
    assert load.cmd[load.cmd.index("--file") + 1] == "local/x.xls"


def test_a_file_with_no_slice_is_refused():
    assert "--slice" in rm.gate_errors(_args(file=["x.xls"]), live=False)[0]


def test_the_load_step_starts_the_loader_as_a_module():
    """Run as a file it cannot import the analytics package (found clicking through the page, 2026-11-02)."""
    load = rm.plan_steps(_args(slice=["a:b:2026-03"]), py="py")[0]
    assert load.cmd[1:3] == ["-m", "scripts.run_canonical_load"]


# ---- reorder decisions: the month's plan must be settled before the next one is made --------------------------------

def _facts_with(**counts):
    decisions = {**NO_OPEN, **counts}
    decisions["open_requests"] = decisions["open_quantity_changes"] + decisions["open_dismissal_requests"]
    return {**FACTS, "decisions": decisions}


def test_a_row_someone_can_still_decide_stops_the_run_and_says_how_many():
    refusals = rm.preflight_refusals(MONTH, _facts_with(actionable_pending=5), NONE_DONE, [], live=False)
    assert len(refusals) == 1 and "5 reorder recommendation(s)" in refusals[0] and "2026-03" in refusals[0]


@pytest.mark.parametrize("request_kind", ["open_quantity_changes", "open_dismissal_requests"])
def test_an_open_staff_request_alone_stops_the_run(request_kind):
    refusals = rm.preflight_refusals(MONTH, _facts_with(**{request_kind: 1}), NONE_DONE, [], live=False)
    assert len(refusals) == 1 and "1 staff request(s)" in refusals[0]


@pytest.mark.parametrize("counts", [{"zero_quantity_pending": 36}, {"historical_pending": 179}, {"later_pending": 4}, {"decided": 73},
                                    {"zero_quantity_pending": 36, "historical_pending": 179, "decided": 73}])
def test_rows_nobody_can_act_on_never_stop_the_run(counts):
    assert rm.preflight_refusals(MONTH, _facts_with(**counts), NONE_DONE, [], live=False) == []


def test_the_refusal_applies_on_live_and_on_the_practice_copy_alike():
    for live in (True, False):
        assert rm.preflight_refusals(MONTH, _facts_with(actionable_pending=1), NONE_DONE, [], live=live)


def test_once_the_next_plan_exists_a_rerun_and_a_close_go_on():
    """Those rows can no longer be decided, so a refusal there could never clear."""
    checks = {**NONE_DONE, "abc_run": True, "forecast_next": True, "lp_next": True}
    assert rm.preflight_refusals(MONTH, _facts_with(actionable_pending=5, open_quantity_changes=1), checks, [], live=False) == []


def test_a_resumed_run_still_stops_while_the_plan_is_unwritten():
    checks = {**NONE_DONE, "abc_run": True, "forecast_next": True}
    assert rm.preflight_refusals(MONTH, _facts_with(actionable_pending=1), checks, [], live=False)


def test_each_refusal_keeps_a_code_for_the_checklist():
    items = rm.preflight_items(MONTH, {**_facts_with(actionable_pending=1), "latest_sales_month": "2026-04"}, NONE_DONE, [], live=False)
    assert [code for code, _ in items] == ["not_latest_month", "decisions_open"]


class _Cursor:
    """Answers the decision counts, and says which request tables exist."""

    def __init__(self, tables=("lp_quantity_change", "lp_dismissal_request")):
        self.tables, self.sql, self.answer = tables, [], None

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if "to_regclass" in sql:
            self.answer = (params[0] in self.tables,)
        elif "lp_quantity_change" in sql:
            self.answer = (2,)
        elif "lp_dismissal_request" in sql:
            self.answer = (3,)
        else:
            self.answer = (7, 36, 1, 179, 4)

    def fetchone(self):
        return self.answer


def test_the_counts_are_read_from_the_records_and_sorted_by_who_can_act():
    params = {"cycle": MONTH, "principal": "unilever"}
    assert rm.read_decisions(_Cursor(), params) == {
        "cycle": "2026-03", "actionable_pending": 7, "zero_quantity_pending": 36, "decided": 1, "historical_pending": 179, "later_pending": 4,
        "open_quantity_changes": 2, "open_dismissal_requests": 3, "open_requests": 5}


def test_a_copy_without_the_request_tables_has_no_open_request():
    decisions = rm.read_decisions(_Cursor(tables=()), {"cycle": MONTH, "principal": "unilever"})
    assert decisions["open_requests"] == 0 and decisions["actionable_pending"] == 7


def test_the_actionable_count_needs_this_month_pending_and_a_positive_quantity():
    first = rm.DECISION_COUNTS_SQL.split("COUNT(*)")[1]
    assert "planning_cycle_date = %(cycle)s" in first and "status = 'pending'" in first and "q_i > 0" in first
    assert "pd.principal = %(principal)s" in rm.DECISION_COUNTS_SQL


# ---- checking files -------------------------------------------------------------------------------------------------

def test_a_file_check_runs_the_loaders_own_dry_run_on_the_same_inputs():
    args = _args(check_files=True, slice=["a:b:2026-03"], file=["local/x.xls"])
    cmd = rm.check_files_cmd(args, py="py")
    assert cmd[1:3] == ["-m", "scripts.run_canonical_load"] and "--dry-run" in cmd
    assert cmd[cmd.index("--slice") + 1] == "a:b:2026-03" and cmd[cmd.index("--file") + 1] == "local/x.xls"


def test_a_file_check_needs_a_slice_and_takes_no_approval():
    assert "--slice" in rm.gate_errors(_args(check_files=True), live=False)[0]
    assert "only checks" in rm.gate_errors(_args(check_files=True, slice=["a"], approved_by="K", expect_month=MONTH), live=False)[0]
    assert "only checks" in rm.gate_errors(_args(check_files=True, slice=["a"], close=True), live=False)[0]
    assert rm.gate_errors(_args(check_files=True, slice=["a"]), live=False) == []


def test_a_file_check_on_live_must_say_so():
    assert "--target-public" in rm.gate_errors(_args(check_files=True, slice=["a"]), live=True)[0]


def test_the_loaders_output_gives_the_run_and_the_manifest():
    found = rm.parse_loader_output(["noise", "[manifest] run key unilever_abc_123: 2 staged sheet(s), fingerprint sha256:ff", "1 slice(s), 0 refused. run_id=20260101T000000Z-ab  (DRY RUN - only etl_load_event rows written)"])
    assert found == {"run_id": "20260101T000000Z-ab", "run_key": "unilever_abc_123", "fingerprint": "sha256:ff"}


def test_nothing_recognised_in_the_output_is_nothing_found():
    assert rm.parse_loader_output(["Traceback"]) == {"run_id": None, "run_key": None, "fingerprint": None}


class _Proc:
    def __init__(self, lines, code):
        self.stdout, self.code = lines, code

    def wait(self):
        return self.code


def _check_run(monkeypatch, tmp_path, lines, code, events=()):
    sample = tmp_path / "x.xls"
    sample.write_bytes(b"data")
    report = tmp_path / "report.json"
    monkeypatch.setattr(rm.subprocess, "Popen", lambda *a, **k: _Proc(lines, code))
    monkeypatch.setattr(rm, "_read", lambda fn: list(events))
    args = _args(check_files=True, slice=["a"], file=[str(sample)], check_files_report=str(report))
    return rm.run_check_files(args, {}), report


def test_a_refused_file_is_a_finding_and_the_check_itself_succeeds(monkeypatch, tmp_path):
    import json
    code, report = _check_run(monkeypatch, tmp_path, ["run_id=r1\n"], 1, [{"status": "refused", "reason": "layout_changed"}])
    body = json.loads(report.read_text(encoding="utf-8"))
    assert code == 0 and body["completed"] is True and body["events"][0]["reason"] == "layout_changed"
    assert body["files"][0]["name"] == "x.xls" and len(body["files"][0]["sha256"]) == 64


def test_a_loader_that_recorded_nothing_fails_the_check(monkeypatch, tmp_path):
    import json
    code, report = _check_run(monkeypatch, tmp_path, ["Traceback\n"], 1)
    assert code == 1 and json.loads(report.read_text(encoding="utf-8"))["completed"] is False


def test_a_practice_file_check_report_says_what_it_is(monkeypatch, tmp_path):
    from scripts.practice_artefacts import file_has_marker
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/ssm_practice")
    _, report = _check_run(monkeypatch, tmp_path, ["run_id=r1\n"], 0)
    assert file_has_marker(report.read_bytes())


# ---- the checks run again when the month actually starts --------------------------------------------------------------

def _main(monkeypatch, argv, facts):
    monkeypatch.setattr(rm.sys, "argv", ["run_month", *argv])
    monkeypatch.setattr(rm, "is_live_target", lambda: False)
    monkeypatch.setattr(rm, "_status", lambda params: {"checks": dict(NONE_DONE), "cycle_row": None})
    monkeypatch.setattr(rm, "_facts", lambda params: {"generated_rows": 0, **facts})
    monkeypatch.setattr(rm.close_cycle, "describe", lambda status, params: [])
    ran = []
    monkeypatch.setattr(rm, "run_plan_stage", lambda args, params: ran.append("plan") or 0)
    monkeypatch.setattr(rm, "run_close_stage", lambda args, params: ran.append("close") or 0)
    monkeypatch.setattr(rm, "run_check_files", lambda args, params: ran.append("check") or 0)
    return rm.main(), ran


WRITE = ["--month", "2026-03", "--calendar-factor", "on", "--approved-by", "Kelvin", "--expect-month", "2026-03"]


def test_a_write_run_refuses_at_its_own_start_and_runs_no_step(monkeypatch):
    code, ran = _main(monkeypatch, WRITE, _facts_with(actionable_pending=3))
    assert code == 2 and ran == []


def test_a_settled_month_starts(monkeypatch):
    code, ran = _main(monkeypatch, WRITE, _facts_with(decided=73, zero_quantity_pending=36, historical_pending=179))
    assert code == 0 and ran == ["plan"]


def test_a_dry_run_says_refused_too(monkeypatch):
    code, ran = _main(monkeypatch, ["--month", "2026-03", "--calendar-factor", "on"], _facts_with(actionable_pending=3))
    assert code == 2 and ran == []


def test_a_file_check_still_runs_when_a_run_would_be_refused(monkeypatch):
    """The person wants every problem at once, and checking a file loads nothing."""
    code, ran = _main(monkeypatch, ["--month", "2026-03", "--calendar-factor", "on", "--check-files", "--slice", "a"], _facts_with(actionable_pending=3))
    assert code == 0 and ran == ["check"]
