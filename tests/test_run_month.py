"""scripts/run_month.py: the gates, the order of the steps, stopping, resuming. The SQL and the real steps run in the
local rehearsal (reports/MONTHLY_BATCH_REHEARSAL_2026-11-02.md), not here."""
from __future__ import annotations

import argparse
import datetime

import pytest

from scripts import run_month as rm

MONTH = datetime.date(2026, 3, 1)
NONE_DONE = {"sales_loaded": True, "count_loaded": True, "abc_run": False, "forecast_next": False, "lp_next": False}
FACTS = {"latest_sales_month": "2026-03", "synthetic_rows": 0}


def test_a_month_holding_only_labelled_generated_rows_is_refused_and_says_why():
    facts = {"latest_sales_month": "2026-02", "synthetic_rows": 709}
    checks = {"sales_loaded": False, "abc_run": False}
    refusals = rm.preflight_refusals(datetime.date(2026, 3, 1), facts, checks, [], live=False)
    assert len(refusals) == 1 and "709 generated sales rows" in refusals[0] and "is_demo" in refusals[0]


def _args(**kw):
    base = {"month": MONTH, "calendar_factor": "on", "slice": [], "approved_by": None, "expect_month": None,
            "target_public": False, "close": False, "expect_plan_pieces": None, "file": []}
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
