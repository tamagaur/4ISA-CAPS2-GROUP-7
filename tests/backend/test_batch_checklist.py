"""backend/batch_checklist.py: what each check says, that the pipeline's own flags are never read as failures, and that nothing is
called complete until the job exited 0 and the plan exists. Pure: no database, no child process."""
from __future__ import annotations

import pytest

from backend import batch_checklist as bc

HASHES = {"sales": {"name": "sales.xls", "sha256": "abc"}}
FILES = {"sales": {"name": "sales.xls", "bytes": 1}}
IDLE = {"status": "idle"}


def _status(**over):
    """Nothing run yet, which is the normal state before a month's run."""
    checks = {"sales_loaded": True, "count_loaded": True, "abc_run": False, "forecast_next": False, "lp_next": False, **over.pop("checks", {})}
    return {"month": "2026-03", "next_month": "2026-04", "checks": checks, "cycle_state": "open", "synthetic_rows": 0, "latest_sales_month": "2026-03",
            "decisions": {"cycle": "2026-03", "actionable_pending": 0, "open_requests": 0}, "preflight": [], "next_plan": {"rows": 0},
            "signoff": None, "replay": None, **over}


def _build(status=None, files=None, validation=None, hashes=None, job=None):
    return bc.build_checklist(status or _status(), files or {}, validation, hashes or {}, job or IDLE)


def _by_id(checklist, check_id):
    return next(c for c in checklist["checks"] if c["id"] == check_id)


def _clean_check(**over):
    return {"hashes": HASHES, "file_check": {"completed": True, "events": [], "run_key": "k", **over}}


# ---- the nine checks, and the blocking or warning distinction ----------------------------------------------------------

def test_there_are_the_nine_checks_in_order():
    assert [c["id"] for c in _build()["checks"]] == ["sales_available", "latest_month", "not_already_run", "decisions_settled", "files_valid",
                                                     "file_approved", "no_other_job", "stock_count", "generated_sales"]


def test_every_check_has_the_fields_the_page_shows():
    for check in _build()["checks"]:
        assert set(check) == {"id", "name", "status", "message", "action", "action_id", "blocking", "details"}
        assert check["status"] in ("passed", "failed", "warning", "not_checked") and check["name"] and check["message"]


def test_a_normal_month_before_its_run_has_no_failure():
    """The ABC, forecast and plan flags are false here by design. Marking them failed would show four failures on every good month."""
    checklist = _build()
    assert checklist["can_run"] is True and checklist["summary"]["failed"] == 0 and checklist["summary"]["not_checked"] == 0


def test_the_pipeline_flags_are_progress_not_checks():
    checklist = _build()
    assert {p["id"]: p["done"] for p in checklist["progress"]} == {"sales_loaded": True, "count_loaded": True, "abc_run": False, "forecast_next": False, "lp_next": False}
    assert not {"abc_run", "forecast_next", "lp_next"} & {c["id"] for c in checklist["checks"]}


def test_no_sales_and_no_file_fails_and_blocks():
    checklist = _build(_status(checks={"sales_loaded": False}))
    check = _by_id(checklist, "sales_available")
    assert check["status"] == "failed" and check["blocking"] and check["action_id"] == "upload" and checklist["can_run"] is False


def test_a_waiting_sales_file_counts_as_sales():
    assert _by_id(_build(_status(checks={"sales_loaded": False}), FILES, None, HASHES), "sales_available")["status"] == "passed"


def test_a_month_that_is_not_the_latest_fails():
    status = _status(latest_sales_month="2026-04", preflight=[{"code": "not_latest_month", "message": "x"}])
    assert _by_id(_build(status), "latest_month")["status"] == "failed"


def test_a_finished_month_fails_the_already_run_check():
    checklist = _build(_status(checks={"abc_run": True, "forecast_next": True, "lp_next": True}))
    assert _by_id(checklist, "not_already_run")["status"] == "failed" and checklist["can_run"] is False


def test_a_closed_month_fails_the_already_run_check():
    assert _by_id(_build(_status(cycle_state="closed")), "not_already_run")["status"] == "failed"


def test_a_run_that_stopped_partway_can_go_on():
    check = _by_id(_build(_status(checks={"abc_run": True})), "not_already_run")
    assert check["status"] == "passed" and "skipped" in check["message"]


def test_a_failed_run_with_the_plan_written_can_finish():
    job = {"status": "failed", "kind": "plan", "month": "2026-03"}
    assert _build(_status(checks={"abc_run": True, "lp_next": True}), job=job)["can_run"] is True


def test_another_job_running_blocks():
    checklist = _build(job={"status": "running", "kind": "plan"})
    assert _by_id(checklist, "no_other_job")["status"] == "failed" and checklist["can_run"] is False and checklist["status"] == "running"


def test_no_stock_count_is_a_warning_that_does_not_block():
    checklist = _build(_status(checks={"count_loaded": False}))
    check = _by_id(checklist, "stock_count")
    assert check["status"] == "warning" and check["blocking"] is False and checklist["can_run"] is True
    assert "cannot be closed" in check["message"]


def test_a_waiting_count_file_counts_as_a_count():
    files = {"count": {"name": "c.xlsx", "bytes": 1}}
    assert _by_id(_build(_status(checks={"count_loaded": False}), files), "stock_count")["status"] == "passed"


def test_generated_sales_are_a_warning_that_does_not_block():
    checklist = _build(_status(synthetic_rows=709))
    check = _by_id(checklist, "generated_sales")
    assert check["status"] == "warning" and check["blocking"] is False and "709" in check["message"] and checklist["can_run"] is True


def test_generated_sales_on_live_fail():
    status = _status(synthetic_rows=9, preflight=[{"code": "synthetic_on_live", "message": "x"}])
    check = _by_id(_build(status), "generated_sales")
    assert check["status"] == "failed" and check["blocking"]


def test_the_counts_are_worked_out_from_the_checks():
    checklist = _build(_status(checks={"sales_loaded": False, "count_loaded": False}, synthetic_rows=5))
    assert checklist["summary"] == {"passed": 6, "failed": 1, "warning": 2, "not_checked": 0}


# ---- reorder decisions -------------------------------------------------------------------------------------------------

def test_open_decisions_fail_with_the_real_counts():
    status = _status(decisions={"cycle": "2026-03", "actionable_pending": 12, "open_requests": 2, "open_quantity_changes": 1, "open_dismissal_requests": 1})
    checklist = _build(status)
    check = _by_id(checklist, "decisions_settled")
    assert check["status"] == "failed" and "12 recommendations await" in check["message"] and "2 staff requests await" in check["message"]
    assert check["action_id"] == "review_recommendations" and checklist["can_run"] is False
    assert checklist["decisions"]["unresolved"] == 12 and checklist["decisions"]["staff_requests"] == 2


def test_rows_nobody_can_act_on_pass_and_are_mentioned():
    status = _status(decisions={"actionable_pending": 0, "open_requests": 0, "zero_quantity_pending": 36, "historical_pending": 179, "decided": 73})
    check = _by_id(_build(status), "decisions_settled")
    assert check["status"] == "passed" and "215" in check["message"]


def test_once_the_next_plan_exists_this_check_no_longer_applies():
    status = _status(checks={"lp_next": True}, decisions={"actionable_pending": 9, "open_requests": 0})
    assert _by_id(_build(status), "decisions_settled")["status"] == "passed"


def _replay(**over):
    return {"to_apply": 0, "to_reverse": 0, "mismatched": 0, "missing": 0, "only_in_practice": 0, "refused": [],
            "pages": {"actionable_pending": 0, "open_requests": 0}, **over}


def test_on_the_local_setup_the_reorder_pages_own_database_is_the_source():
    status = _status(replay=_replay(pages={"actionable_pending": 4, "open_requests": 1}), decisions={"actionable_pending": 0, "open_requests": 0})
    checklist = _build(status)
    assert _by_id(checklist, "decisions_settled")["status"] == "failed" and checklist["decisions"]["unresolved"] == 4


def test_decisions_not_yet_carried_over_are_not_checked_and_still_block():
    status = _status(replay=_replay(to_apply=3), decisions={"actionable_pending": 3, "open_requests": 0})
    checklist = _build(status)
    check = _by_id(checklist, "decisions_settled")
    assert check["status"] == "not_checked" and check["action_id"] == "validate" and checklist["can_run"] is False


@pytest.mark.parametrize("stuck", [{"mismatched": 1}, {"missing": 2}, {"only_in_practice": 1}, {"refused": [{"recommendation_key": 1, "why": "x"}]}])
def test_decisions_that_cannot_be_carried_over_fail_and_block(stuck):
    checklist = _build(_status(replay=_replay(**stuck)))
    assert _by_id(checklist, "decisions_settled")["status"] == "failed" and checklist["can_run"] is False


def test_everything_carried_over_passes():
    status = _status(replay=_replay(already=73, pages={"actionable_pending": 0, "open_requests": 0, "zero_quantity_pending": 36}))
    assert _by_id(_build(status), "decisions_settled")["status"] == "passed"


# ---- files and approval --------------------------------------------------------------------------------------------------

def test_no_waiting_file_needs_no_check_or_approval():
    checklist = _build()
    assert _by_id(checklist, "files_valid")["status"] == "passed" and _by_id(checklist, "file_approved")["status"] == "passed"


def test_a_file_not_yet_checked_blocks():
    checklist = _build(None, FILES, None, HASHES)
    check = _by_id(checklist, "files_valid")
    assert check["status"] == "not_checked" and check["blocking"] and check["action_id"] == "validate" and checklist["can_run"] is False


def test_a_file_changed_after_its_check_needs_a_new_one():
    validation = {"hashes": {"sales": {"name": "sales.xls", "sha256": "old"}}, "file_check": {"completed": True, "events": []}}
    check = _by_id(_build(None, FILES, validation, HASHES), "files_valid")
    assert check["status"] == "not_checked" and "changed" in check["message"]


def test_a_check_being_run_is_not_a_result():
    job = {"status": "running", "kind": "validate"}
    assert _by_id(_build(None, FILES, _clean_check(), HASHES, job), "files_valid")["status"] == "not_checked"


def test_a_check_that_did_not_finish_fails():
    validation = {"hashes": HASHES, "file_check": {"completed": False}}
    assert _by_id(_build(None, FILES, validation, HASHES), "files_valid")["status"] == "failed"
    assert _by_id(_build(None, FILES, {"hashes": HASHES}, HASHES), "files_valid")["status"] == "failed"


def test_a_refused_file_fails_with_details_and_cannot_be_approved():
    events = [{"status": "refused", "reason": "validation_failed", "slice": "unilever:unilever_sku_demand_fact:2026-03", "files": ["sales.xls"], "detail": "peso total: far outside"}]
    checklist = _build(None, FILES, _clean_check(events=events), HASHES)
    check = _by_id(checklist, "files_valid")
    assert check["status"] == "failed" and check["blocking"] and check["action_id"] == "upload"
    assert check["details"] == [{"file": "sales.xls", "table": "Sales per product", "severity": "failed", "action": bc.REASONS["validation_failed"][1],
                                 "reason": bc.REASONS["validation_failed"][0], "detail": "peso total: far outside"}]
    approved = _by_id(checklist, "file_approved")
    assert approved["status"] == "not_checked" and approved["action_id"] is None


def test_a_warning_on_a_file_does_not_block_but_approval_still_does():
    events = [{"status": "warning", "reason": "validation_warning", "slice": "x", "files": ["sales.xls"], "detail": "unusual"}]
    checklist = _build(None, FILES, _clean_check(events=events), HASHES)
    assert _by_id(checklist, "files_valid")["status"] == "warning" and _by_id(checklist, "files_valid")["blocking"] is False
    assert _by_id(checklist, "file_approved")["action_id"] == "approve" and checklist["can_run"] is False


def test_an_approved_clean_file_can_run():
    status = _status(signoff={"signed": True, "by": "planner@ssm"})
    checklist = _build(status, FILES, _clean_check(), HASHES)
    assert _by_id(checklist, "file_approved")["status"] == "passed" and "planner@ssm" in _by_id(checklist, "file_approved")["message"]
    assert checklist["can_run"] is True and checklist["workflow"] == "ready_to_run"


def test_an_approval_the_loader_no_longer_accepts_does_not_count():
    status = _status(signoff={"signed": False, "reason": "the recorded sign-off is for a different manifest"})
    assert _by_id(_build(status, FILES, _clean_check(), HASHES), "file_approved")["status"] == "failed"


def test_an_error_keeps_its_technical_text_off_the_page():
    events = [{"status": "refused", "reason": "error", "slice": "x", "files": ["sales.xls"], "detail": "prepare failed: KeyError: secret_column"}]
    detail = _by_id(_build(None, FILES, _clean_check(events=events), HASHES), "files_valid")["details"][0]
    assert detail["detail"] is None and "secret_column" not in str(detail)


@pytest.mark.parametrize("text,gone,kept", [
    ("see postgresql://u:pw@host:5432/db for it", "u:pw", "see"),
    (r"C:\Users\Someone\repo\local\sales.xls: bad", "Someone", "sales.xls"),
    ("/home/someone/repo/local/sales.xls: bad", "someone", "sales.xls"),
])
def test_details_lose_anything_internal(text, gone, kept):
    out = bc.plain_text(text)
    assert gone not in out and kept in out


def test_an_unknown_reason_still_says_something_true():
    detail = bc.event_details([{"status": "refused", "reason": "brand_new_code", "slice": "file:x.xls", "files": None, "detail": "raw"}])[0]
    assert detail["reason"] == bc.UNKNOWN_REASON[0] and detail["file"] == "x.xls" and detail["detail"] is None


def test_the_approval_dialog_shows_what_the_check_found():
    events = [{"status": "loaded", "slice": "unilever:unilever_sku_demand_fact:2026-03", "real_rows_before": 0, "real_rows_after": 700}]
    summary = _build(None, FILES, _clean_check(events=events), HASHES)["file_check"]
    assert summary["files"] == ["sales.xls"] and summary["slices"] == [{"table": "Sales per product", "status": "loaded", "rows_before": 0, "rows_after": 700}]


# ---- where the month stands ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status,files,validation,hashes,job,expected", [
    (_status(checks={"sales_loaded": False}), {}, None, {}, IDLE, "not_uploaded"),
    (_status(), {}, None, {}, IDLE, "ready_for_validation"),
    (_status(checks={"sales_loaded": False}), FILES, None, HASHES, IDLE, "ready_for_validation"),
    (_status(decisions={"actionable_pending": 2, "open_requests": 0}), {}, {"hashes": {}}, {}, IDLE, "action_required"),
    (_status(), {}, {"hashes": {}}, {}, IDLE, "ready_to_run"),
    (_status(), {}, None, {}, {"status": "running", "kind": "validate"}, "validating"),
    (_status(), {}, None, {}, {"status": "running", "kind": "plan"}, "processing"),
    (_status(), {}, {"hashes": {}}, {}, {"status": "failed", "kind": "plan", "month": "2026-03"}, "failed"),
    (_status(checks={"lp_next": True}), {}, None, {}, {"status": "done", "kind": "plan", "month": "2026-03"}, "completed"),
    (_status(checks={"lp_next": True}), {}, None, {}, IDLE, "awaiting_review"),
    (_status(cycle_state="closed"), {}, None, {}, IDLE, "closed"),
])
def test_the_workflow_state(status, files, validation, hashes, job, expected):
    assert _build(status, files, validation, hashes, job)["workflow"] == expected


# ---- the stages a job reached --------------------------------------------------------------------------------------------

def test_stages_come_from_what_run_month_prints():
    steps, failed = bc.parse_steps(["[abc] already done, skipped", "[forecast] running", "[lp] running", "noise"])
    assert steps == [{"stage": "abc", "label": "ABC classification", "state": "skipped"},
                     {"stage": "forecast", "label": "Forecast", "state": "done"}, {"stage": "lp", "label": "Order plan", "state": "running"}]
    assert failed is None


@pytest.mark.parametrize("line,stage", [
    ("[lp] exited 2: batch stopped. Fix it and run the same command again; finished steps are skipped.", "lp"),
    ("[abc] exited 0 but did not do its work (abc_run is still false): batch stopped", "abc"),
    ("[marts] did not refresh: batch stopped. Run the same command again.", "marts"),
    ("REFUSED: 3 reorder recommendation(s) of the 2026-03 plan still await a decision", "preflight"),
])
def test_where_a_job_stopped(line, stage):
    assert bc.parse_steps([line])[1] == stage


# ---- how the run ended ---------------------------------------------------------------------------------------------------

JOB = {"id": "j1", "kind": "plan", "month": "2026-03", "started_at": "s", "finished_at": "f"}
PLAN = {"rows": 121, "run_key": 7}


def test_complete_needs_exit_zero_and_the_plan():
    result = bc.run_result(_status(checks={"lp_next": True}, next_plan=PLAN), {**JOB, "status": "done", "exit_code": 0})
    assert result["state"] == "completed" and result["run_id"] == 7 and result["finished_at"] == "f" and result["month"] == "2026-03"


def test_a_started_job_is_not_a_finished_one():
    assert bc.run_result(_status(checks={"lp_next": True}, next_plan=PLAN), {**JOB, "status": "running"})["state"] == "processing"


def test_exit_zero_with_no_plan_is_a_failure():
    assert bc.run_result(_status(next_plan={"rows": 0}), {**JOB, "status": "done", "exit_code": 0})["state"] == "failed"


def test_a_plan_with_a_failed_job_is_not_complete():
    result = bc.run_result(_status(checks={"lp_next": True}, next_plan=PLAN), {**JOB, "status": "failed", "exit_code": 1, "failed_stage": "marts"})
    assert result["state"] == "failed" and result["failed_stage"] == "Dashboard tables" and result["action"]


@pytest.mark.parametrize("stage", ["preflight", "load", "abc", "forecast", "lp", "marts", None, "unknown"])
def test_a_failure_always_has_plain_words_and_a_next_step(stage):
    result = bc.run_result(_status(), {**JOB, "status": "failed", "exit_code": 1, "failed_stage": stage})
    assert result["state"] == "failed" and result["message"] and result["action"] and result["failed_stage"]


def test_another_months_job_says_nothing_about_this_month():
    assert bc.run_result(_status(), {**JOB, "month": "2026-02", "status": "done", "exit_code": 0}) is None


def test_a_validation_job_is_not_a_run_result():
    assert bc.run_result(_status(), {**JOB, "kind": "validate", "status": "done", "exit_code": 0}) is None


@pytest.mark.parametrize("kind", ["close", "practice"])
def test_a_failed_close_or_practice_job_says_so_and_a_good_one_says_nothing(kind):
    assert bc.run_result(_status(), {**JOB, "kind": kind, "status": "failed", "exit_code": 2})["state"] == "failed"
    assert bc.run_result(_status(), {**JOB, "kind": kind, "status": "done", "exit_code": 0}) is None


def test_no_job_says_nothing():
    assert bc.run_result(_status(), {"status": "idle"}) is None
