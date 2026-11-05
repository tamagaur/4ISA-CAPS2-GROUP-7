"""backend/routers/monthly_batch.py: local-only, permission-gated, and it only ever starts scripts.run_month. The real
steps run in the rehearsal (reports/MONTHLY_BATCH_REHEARSAL_2026-11-02.md), never here."""
from __future__ import annotations

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api_errors import ApiError, api_error_handler
from backend.auth_utils import TokenPayload
from backend.deps import get_current_user, get_db
from backend.main import app as deployed_app
from backend.routers import monthly_batch as mb

LOCAL = "postgresql://postgres@127.0.0.1:55432/ssm_local"
LIVE = "postgresql://user:pw@aws-0.pooler.supabase.com:6543/postgres"

# backend/main.py mounts the router only on the local database, so the routes are tested on their own app.
app = FastAPI()
app.add_exception_handler(ApiError, api_error_handler)
app.include_router(mb.router)


def _user(perms=("upload.run",)):
    return TokenPayload(user_id=1, email="planner@ssmcapstone.com", role="staff", full_name="Planner", session_id="s",
                        permissions=frozenset(perms))


@pytest.fixture
def started(monkeypatch, tmp_path):
    """The batch switched on, on the local database; job starts are recorded, not run."""
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    monkeypatch.setattr(mb, "UPLOADS", tmp_path)
    calls = []
    monkeypatch.setattr(mb.JOB, "start", lambda kind, cmd, *a, **k: calls.append((kind, cmd)))
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status())
    monkeypatch.setattr(mb, "replay_decisions", lambda month: {})
    monkeypatch.setattr(mb, "check_file", lambda path, kind, month: {"ok": True})
    return calls


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = _user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _run_body(**kw):
    return {"month": "2026-03", "calendar_factor": "on", **kw}


def _status(**over):
    """What scripts/batch_status.py reports: a month with sales in, nothing left to decide, and nothing run yet."""
    checks = {"sales_loaded": True, "count_loaded": True, "abc_run": False, "forecast_next": False, "lp_next": False, **over.pop("checks", {})}
    return {"month": "2026-03", "next_month": "2026-04", "checks": checks, "cycle_state": "open", "synthetic_rows": 0,
            "latest_sales_month": "2026-03", "decisions": {"cycle": "2026-03", "actionable_pending": 0, "open_requests": 0},
            "preflight": [], "next_plan": {"rows": 0}, "plan": {"rows": 109}, "signoff": None, "replay": None, "close_missing": [], **over}


def _checked_and_approved(monkeypatch):
    """The waiting files have a finished, clean file check, and a person has approved them."""
    monkeypatch.setattr(mb, "read_validation", lambda month: {
        "hashes": mb.file_hashes(month), "file_check": {"completed": True, "events": [], "run_key": "key_1"}})
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status(signoff={"signed": True, "by": "someone"}))


@pytest.fixture(autouse=True)
def quiet_side_effects(monkeypatch, tmp_path_factory):
    """No test writes to the repo's local/ folder or tries to reach a database for an audit entry."""
    monkeypatch.setattr(mb, "LOGS", tmp_path_factory.mktemp("logs"))
    monkeypatch.setattr(mb, "VALIDATIONS", tmp_path_factory.mktemp("validation"))
    entries = []
    monkeypatch.setattr(mb, "audit_event", lambda action, details, user: entries.append((action, details, user.email)))
    return entries


# ---- local only ------------------------------------------------------------------------------------------------------

def test_the_deployed_api_does_not_have_the_routes():
    assert not [r.path for r in deployed_app.routes if getattr(r, "path", "").startswith("/batch")]


def test_off_by_default(monkeypatch, client):
    monkeypatch.delenv("MONTHLY_BATCH_ENABLED", raising=False)
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    assert client.get("/batch/status").json() == {"enabled": False}


def test_the_flag_alone_does_not_enable_it_on_the_live_database(monkeypatch, client):
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LIVE)
    assert client.get("/batch/status").json() == {"enabled": False}


@pytest.mark.parametrize("url", [LIVE, "postgresql://postgres@127.0.0.1:5432/x", ""])
def test_no_write_route_runs_outside_the_throwaway_database(monkeypatch, client, url):
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", url)
    started = []
    monkeypatch.setattr(mb.JOB, "start", lambda kind, cmd, *a, **k: started.append(cmd))
    for path, body in (("/batch/run", _run_body()), ("/batch/close", _run_body(expect_plan_pieces=1)),
                       ("/batch/practice-month", {"month": "2026-03"}), ("/batch/validate", {"month": "2026-03"}),
                       ("/batch/signoff", {"month": "2026-03"})):
        res = client.post(path, json=body)
        assert res.status_code == 409 and res.json()["code"] == "batch_local_only"
    assert started == []


def test_every_step_runs_on_the_practice_database_and_the_pages_stay_on_theirs(monkeypatch):
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    env = mb.step_env()
    assert env["SUPABASE_DB_URL"] == env["SUPABASE_DIRECT_URL"] == env["DATABASE_URL"] == "postgresql://postgres@127.0.0.1:55432/ssm_practice"


def test_no_step_can_be_pointed_anywhere_else(monkeypatch):
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LIVE)
    with pytest.raises(ApiError):
        mb.step_env()


# ---- the permission --------------------------------------------------------------------------------------------------

def test_without_the_permission_it_is_refused(started):
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: _user(perms=("dashboard.view",))
    try:
        res = TestClient(app).post("/batch/run", json=_run_body())
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 403 and started == []


# ---- what gets run ---------------------------------------------------------------------------------------------------

def test_a_run_starts_run_month_with_the_signed_in_user_as_approver(started, client):
    assert client.post("/batch/run", json=_run_body()).status_code == 202
    kind, cmd = started[0]
    assert kind == "plan" and cmd[1:3] == ["-m", "scripts.run_month"]
    assert cmd[cmd.index("--approved-by") + 1] == "planner@ssmcapstone.com"
    assert cmd[cmd.index("--expect-month") + 1] == "2026-03"
    assert cmd[cmd.index("--calendar-factor") + 1] == "on"


def test_no_route_ever_passes_target_public(started, client):
    client.post("/batch/run", json=_run_body())
    client.post("/batch/close", json=_run_body(expect_plan_pieces=5))
    assert all("--target-public" not in cmd for _, cmd in started)


def test_the_calendar_factor_must_be_stated(started, client):
    assert client.post("/batch/run", json={"month": "2026-03"}).status_code == 422
    assert client.post("/batch/run", json=_run_body(calendar_factor="maybe")).status_code == 422
    assert started == []


def test_a_badly_formed_month_is_refused(started, client):
    assert client.post("/batch/run", json=_run_body(month="2026-3; rm")).status_code == 422
    assert started == []


def test_uploaded_files_become_slices_and_files(started, client, monkeypatch):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    client.post("/batch/files", data={"month": "2026-03", "kind": "count"},
                files={"file": ("count.xlsx", io.BytesIO(b"y"), "application/octet-stream")})
    _checked_and_approved(monkeypatch)
    assert client.post("/batch/run", json=_run_body()).status_code == 202
    _, cmd = started[0]
    assert cmd[1:3] == ["-m", "scripts.practice_signed_load"] and cmd[cmd.index("--pressed-by") + 1] == "planner@ssmcapstone.com"
    cut = cmd.index("--")
    assert cmd[cut + 1:cut + 3] == ["-m", "scripts.run_month"]
    month = cmd[cut + 1:]
    slices = [month[i + 1] for i, a in enumerate(month) if a == "--slice"]
    files = [month[i + 1] for i, a in enumerate(month) if a == "--file"]
    assert "--approved-by" not in cmd[:cut] and "--slice" not in cmd[:cut] and "--file" not in cmd[:cut]
    assert slices == ["unilever:unilever_sku_demand_fact:2026-03", "unilever:inventory_fact:2026-03"]
    assert [f.rsplit("sales", 1)[-1] if "sales.xls" in f else f.rsplit("count", 1)[-1] for f in files] == [".xls", ".xlsx"]


def test_the_close_carries_the_total_the_person_saw(started, client):
    assert client.post("/batch/close", json=_run_body(expect_plan_pieces=1213146)).status_code == 202
    kind, cmd = started[0]
    assert kind == "close" and "--close" in cmd
    assert cmd[cmd.index("--expect-plan-pieces") + 1] == "1213146"


def test_a_close_with_no_total_is_refused(started, client):
    assert client.post("/batch/close", json=_run_body()).status_code == 422
    assert started == []


def test_practice_sales_exist_only_for_the_month_the_generator_makes(started, client):
    assert client.post("/batch/practice-month", json={"month": "2026-04"}).status_code == 400
    assert client.post("/batch/practice-month", json={"month": "2026-03"}).status_code == 202
    assert started[0][1][1:] == ["scripts/local_pipeline_qa.py", "synth"]


# ---- uploads ---------------------------------------------------------------------------------------------------------

def test_a_file_the_loader_would_refuse_is_named_and_leaves_the_slot_as_it_was(started, client, monkeypatch, tmp_path):
    send = lambda name: client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},  # noqa: E731
                                    files={"file": (name, io.BytesIO(b"x"), "application/octet-stream")})
    assert send("good.xls").status_code == 201
    monkeypatch.setattr(mb, "check_file", lambda path, kind, month: {"ok": False, "message": "bad.xls is missing columns the loader needs: GSV."})
    res = send("bad.xls")
    assert res.status_code == 422 and "GSV" in res.json()["detail"] and res.json()["code"] == "batch_file_not_usable"
    assert mb.uploaded_files("2026-03")["sales"]["name"] == "good.xls"
    assert [p.name for p in (tmp_path / "2026-03").iterdir()] == ["sales"]    # nothing left behind


def test_the_check_reads_the_file_under_its_own_name_before_it_is_kept(started, client, monkeypatch):
    seen = []
    monkeypatch.setattr(mb, "check_file", lambda path, kind, month: (seen.append((path.name, path.read_bytes(), kind, month)), {"ok": True})[1])
    res = client.post("/batch/files", data={"month": "2026-03", "kind": "count"},
                      files={"file": ("SSIS MARCH 2026.xlsx", io.BytesIO(b"y"), "application/octet-stream")})
    assert res.status_code == 201 and seen == [("SSIS MARCH 2026.xlsx", b"y", "count", "2026-03")]



def test_an_unsupported_file_type_is_refused(started, client):
    res = client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                      files={"file": ("run.exe", io.BytesIO(b"x"), "application/octet-stream")})
    assert res.status_code == 400


def test_an_unknown_kind_is_refused(started, client):
    res = client.post("/batch/files", data={"month": "2026-03", "kind": "secrets"},
                      files={"file": ("a.xls", io.BytesIO(b"x"), "application/octet-stream")})
    assert res.status_code == 400


def test_a_path_in_the_file_name_cannot_leave_the_upload_folder(started, client, tmp_path):
    res = client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                      files={"file": ("..\\..\\evil.xls", io.BytesIO(b"x"), "application/octet-stream")})
    assert res.status_code == 201
    saved = list(tmp_path.rglob("*.xls"))
    assert len(saved) == 1 and tmp_path in saved[0].parents and ".." not in saved[0].name


def test_a_new_file_replaces_the_old_one_for_that_kind(started, client, tmp_path):
    for name in ("first.xls", "second.xls"):
        client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                    files={"file": (name, io.BytesIO(b"x"), "application/octet-stream")})
    assert [p.name for p in tmp_path.rglob("*.xls")] == ["second.xls"]


# ---- the job ---------------------------------------------------------------------------------------------------------

def test_a_second_job_is_refused_while_one_runs():
    job = mb.Job()
    with job._lock:
        job.status = "running"
    with pytest.raises(mb.ApiError) as err:
        job.start("plan", ["x"])
    assert err.value.status_code == 409


def test_a_job_records_its_output_and_exit_code(monkeypatch):
    import sys
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    job = mb.Job()
    job.start("plan", [sys.executable, "-c", "print('hello'); raise SystemExit(3)"])
    job.thread.join(30)
    state = job.state()
    assert state["status"] == "failed" and state["exit_code"] == 3 and "hello" in job.lines


def test_a_step_refused_outside_the_local_database_ends_the_job(monkeypatch):
    import sys
    monkeypatch.delenv("MONTHLY_BATCH_ENABLED", raising=False)
    monkeypatch.setenv("SUPABASE_DB_URL", LIVE)
    job = mb.Job()
    job.start("plan", [sys.executable, "-c", "print('ran')"])
    job.thread.join(30)
    state = job.state()
    assert state["status"] == "failed" and "ran" not in job.lines


# ---- resuming after a failure, and switching between a file and practice sales ---------------------------------------

def test_a_rerun_after_the_abc_ran_does_not_load_the_file_again(started, client, monkeypatch):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status(checks={"abc_run": True}))
    assert client.post("/batch/run", json=_run_body()).status_code == 202
    assert "--slice" not in started[0][1] and "--file" not in started[0][1]


def test_a_new_file_is_refused_once_the_abc_has_run(started, client, monkeypatch):
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status(checks={"abc_run": True}))
    res = client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                      files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    assert res.status_code == 409 and res.json()["code"] == "batch_already_ran"


def test_practice_sales_replace_an_uploaded_sales_file(started, client, tmp_path):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    client.post("/batch/practice-month", json={"month": "2026-03"})
    assert list(tmp_path.rglob("*.xls")) == []


# ---- the checklist ---------------------------------------------------------------------------------------------------

def test_the_checklist_is_local_only_and_needs_the_permission(monkeypatch, client):
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LIVE)
    res = client.get("/batch/checklist")
    assert res.status_code == 409 and res.json()["code"] == "batch_local_only"
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    app.dependency_overrides[get_current_user] = lambda: _user(perms=("dashboard.view",))
    assert client.get("/batch/checklist").status_code == 403


def test_the_checklist_comes_from_what_the_scripts_report(started, client):
    body = client.get("/batch/checklist?month=2026-03").json()
    assert body["practice_note"] and body["processing_month"] == "2026-03" and body["can_run"] is True
    assert [c["id"] for c in body["checks"]] == ["sales_available", "latest_month", "not_already_run", "decisions_settled", "files_valid",
                                                 "file_approved", "no_other_job", "stock_count", "generated_sales"]


def test_the_checklist_names_the_month_in_play_when_none_is_given(started, client):
    assert client.get("/batch/checklist").json()["processing_month"] == "2026-03"


def test_the_checklist_only_reads(started, client, monkeypatch):
    def replay(month):
        raise AssertionError("a GET must not write")
    monkeypatch.setattr(mb, "replay_decisions", replay)
    assert client.get("/batch/checklist").status_code == 200 and started == []


def test_the_answers_say_what_they_are_for_the_artefact_check(started, client):
    # The X-Practice-Copy header and the body's practice_copy block are the middleware's (tests/test_practice_artefacts.py); the route's own part is the note.
    for path in ("/batch/status", "/batch/checklist", "/batch/job"):
        res = client.get(path)
        assert res.status_code == 200 and res.json().get("practice_note"), path


def test_the_practice_marker_matches_the_one_the_scripts_use():
    from scripts.report_target import PRACTICE_MARKER
    assert mb.PRACTICE_MARKER == PRACTICE_MARKER


# ---- validating ------------------------------------------------------------------------------------------------------

def test_validating_with_no_file_replays_the_decisions_and_starts_no_job(started, client, monkeypatch, quiet_side_effects):
    calls = []
    monkeypatch.setattr(mb, "replay_decisions", lambda month: calls.append(month) or {"applied": 4, "reversed": 1})
    res = client.post("/batch/validate", json={"month": "2026-03"})
    assert res.status_code == 202 and res.json()["started"] is None and calls == ["2026-03"] and started == []
    assert quiet_side_effects[-1][0] == "Monthly Batch Validation Passed" and "4 decision(s)" in quiet_side_effects[-1][1]
    assert client.get("/batch/checklist").json()["validated"] is True


def test_validating_a_file_runs_the_check_and_never_a_load(started, client):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    res = client.post("/batch/validate", json={"month": "2026-03"})
    assert res.json()["started"] == "validate"
    kind, cmd = started[0]
    assert kind == "validate" and "--check-files" in cmd and cmd[1:3] == ["-m", "scripts.run_month"]
    assert "--approved-by" not in cmd and "--target-public" not in cmd and "--close" not in cmd
    assert cmd[cmd.index("--slice") + 1] == "unilever:unilever_sku_demand_fact:2026-03"


def test_validation_failing_is_audited_with_what_failed(started, client, monkeypatch, quiet_side_effects):
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status(decisions={"actionable_pending": 2, "open_requests": 0}))
    client.post("/batch/validate", json={"month": "2026-03"})
    assert quiet_side_effects[-1][0] == "Monthly Batch Validation Failed" and "Reorder decisions settled" in quiet_side_effects[-1][1]


def test_validating_while_a_job_runs_is_refused(started, client, monkeypatch):
    monkeypatch.setattr(mb.JOB, "state", lambda: {"status": "running", "kind": "plan"})
    res = client.post("/batch/validate", json={"month": "2026-03"})
    assert res.status_code == 409 and res.json()["code"] == "batch_busy"


# ---- the run asks everything again -----------------------------------------------------------------------------------

def test_open_decisions_refuse_the_run_with_the_counts(started, client, monkeypatch, quiet_side_effects):
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status(decisions={"actionable_pending": 3, "open_requests": 1}))
    res = client.post("/batch/run", json=_run_body())
    body = res.json()
    assert res.status_code == 409 and body["code"] == "batch_checks_failed" and started == []
    assert body["decisions"]["unresolved"] == 3 and body["decisions"]["staff_requests"] == 1
    assert [c["id"] for c in body["checks"]] == ["decisions_settled"]
    assert quiet_side_effects[-1][0] == "Monthly Batch Run Refused"


def test_the_run_replays_the_decisions_before_it_asks(started, client, monkeypatch):
    order = []
    monkeypatch.setattr(mb, "replay_decisions", lambda month: order.append("replay") or {})
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: order.append("status") or _status())
    assert client.post("/batch/run", json=_run_body()).status_code == 202
    assert order[0] == "replay" and "status" in order


def test_a_file_never_checked_refuses_the_run(started, client):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    res = client.post("/batch/run", json=_run_body())
    assert res.status_code == 409 and "Files valid" in res.json()["detail"] and started == []


def test_a_file_changed_after_its_check_refuses_the_run(started, client, monkeypatch):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"first"), "application/octet-stream")})
    _checked_and_approved(monkeypatch)
    checked = mb.read_validation("2026-03")
    monkeypatch.setattr(mb, "read_validation", lambda month: checked)
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"second"), "application/octet-stream")})
    res = client.post("/batch/run", json=_run_body())
    assert res.status_code == 409 and "Files valid" in res.json()["detail"] and started == []


def test_a_decision_undone_after_validation_refuses_the_run(started, client, monkeypatch):
    client.post("/batch/validate", json={"month": "2026-03"})
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status(decisions={"actionable_pending": 1, "open_requests": 0}))
    assert client.post("/batch/run", json=_run_body()).status_code == 409 and started == []


def test_a_finished_month_is_not_run_twice(started, client, monkeypatch):
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status(checks={"abc_run": True, "forecast_next": True, "lp_next": True}))
    res = client.post("/batch/run", json=_run_body())
    assert res.status_code == 409 and "Monthly run not already completed" in res.json()["detail"] and started == []


def test_a_run_that_stopped_after_writing_the_plan_can_finish(started, client, monkeypatch):
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status(checks={"abc_run": True, "forecast_next": True, "lp_next": True}))
    monkeypatch.setattr(mb.JOB, "state", lambda: {"id": "j", "status": "failed", "kind": "plan", "month": "2026-03", "failed_stage": "marts"})
    assert client.post("/batch/run", json=_run_body()).status_code == 202


def test_a_run_while_another_runs_is_refused(started, client, monkeypatch):
    monkeypatch.setattr(mb.JOB, "state", lambda: {"status": "running", "kind": "validate"})
    res = client.post("/batch/run", json=_run_body())
    assert res.status_code == 409 and res.json()["code"] == "batch_busy" and started == []


def test_uploading_while_a_job_runs_is_refused(started, client, monkeypatch):
    monkeypatch.setattr(mb.JOB, "state", lambda: {"status": "running", "kind": "plan"})
    res = client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                      files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    assert res.status_code == 409 and res.json()["code"] == "batch_busy"


def test_a_run_and_a_close_are_audited_with_who_and_which_month(started, client, quiet_side_effects):
    client.post("/batch/run", json=_run_body())
    client.post("/batch/close", json=_run_body(expect_plan_pieces=5))
    actions = [(a, who) for a, _, who in quiet_side_effects]
    assert ("Monthly Batch Run Started", "planner@ssmcapstone.com") in actions and ("Monthly Batch Close Started", "planner@ssmcapstone.com") in actions
    assert all("2026-03" in d for _, d, _ in quiet_side_effects)


def test_a_finished_run_is_audited_once_with_its_run_id(monkeypatch, quiet_side_effects):
    monkeypatch.setattr(mb, "read_status", lambda month=None, *a, **k: _status(next_plan={"rows": 121, "pieces": 10.0, "run_key": 9}))
    job = mb.Job()
    job.status, job.id = "done", "j1"
    mb._finish_run_audit("2026-03", _user())(job)
    assert [a for a, _, _ in quiet_side_effects] == ["Monthly Batch Run Completed"] and "LP run 9" in quiet_side_effects[0][1]


def test_a_failed_run_is_audited_with_where_it_stopped(quiet_side_effects):
    job = mb.Job()
    job.status, job.id, job.exit_code = "failed", "j1", 2
    job.lines.append("[forecast] exited 2: batch stopped. Fix it and run the same command again; finished steps are skipped.")
    mb._finish_run_audit("2026-03", _user())(job)
    assert quiet_side_effects[0][0] == "Monthly Batch Run Failed" and "stopped at forecast" in quiet_side_effects[0][1]


# ---- approving a file -------------------------------------------------------------------------------------------------

def _uploaded(client):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})


def _sign_recorder(monkeypatch, returncode=0):
    calls = []

    class Done:
        pass

    def fake(cmd, **kw):
        calls.append(cmd)
        done = Done()
        done.returncode = returncode
        return done

    monkeypatch.setattr(mb.subprocess, "run", fake)
    return calls


def test_a_checked_clean_file_is_approved_with_the_loaders_own_command(started, client, monkeypatch, quiet_side_effects):
    _uploaded(client)
    monkeypatch.setattr(mb, "read_validation", lambda month: {"hashes": mb.file_hashes(month), "file_check": {"completed": True, "events": [], "run_key": "key_1"}})
    calls = _sign_recorder(monkeypatch)
    res = client.post("/batch/signoff", json={"month": "2026-03"})
    assert res.status_code == 200 and res.json()["by"] == "planner@ssmcapstone.com"
    cmd = calls[0]
    assert cmd[1:3] == ["-m", "analytics.etl.transform_signoff"] and cmd[cmd.index("--decision") + 1] == "approved"
    assert cmd[cmd.index("--transform-dir") + 1] == "transform/slices/key_1" and cmd[cmd.index("--by") + 1] == "planner@ssmcapstone.com"
    assert quiet_side_effects[-1][0] == "Monthly Batch File Approved"


def test_approval_with_no_check_on_record_is_refused(started, client, monkeypatch):
    _uploaded(client)
    calls = _sign_recorder(monkeypatch)
    res = client.post("/batch/signoff", json={"month": "2026-03"})
    assert res.status_code == 409 and res.json()["code"] == "batch_not_validated" and calls == []


def test_approval_of_a_changed_file_is_refused(started, client, monkeypatch):
    _uploaded(client)
    monkeypatch.setattr(mb, "read_validation", lambda month: {"hashes": {"sales": {"name": "sales.xls", "sha256": "other"}}, "file_check": {"completed": True, "events": [], "run_key": "k"}})
    calls = _sign_recorder(monkeypatch)
    res = client.post("/batch/signoff", json={"month": "2026-03"})
    assert res.status_code == 409 and res.json()["code"] == "batch_validation_stale" and calls == []


def test_approval_of_a_file_with_problems_is_refused(started, client, monkeypatch):
    _uploaded(client)
    monkeypatch.setattr(mb, "read_validation", lambda month: {"hashes": mb.file_hashes(month), "file_check": {"completed": True, "run_key": "k", "events": [{"status": "refused", "reason": "layout_changed"}]}})
    calls = _sign_recorder(monkeypatch)
    res = client.post("/batch/signoff", json={"month": "2026-03"})
    assert res.status_code == 409 and res.json()["code"] == "batch_files_invalid" and calls == []


def test_an_unsafe_run_key_never_reaches_the_command(started, client, monkeypatch):
    _uploaded(client)
    monkeypatch.setattr(mb, "read_validation", lambda month: {"hashes": mb.file_hashes(month), "file_check": {"completed": True, "events": [], "run_key": "../../evil"}})
    calls = _sign_recorder(monkeypatch)
    assert client.post("/batch/signoff", json={"month": "2026-03"}).status_code == 409 and calls == []


def test_approval_that_cannot_be_recorded_says_so_without_internals(started, client, monkeypatch):
    _uploaded(client)
    monkeypatch.setattr(mb, "read_validation", lambda month: {"hashes": mb.file_hashes(month), "file_check": {"completed": True, "events": [], "run_key": "k"}})
    _sign_recorder(monkeypatch, returncode=1)
    res = client.post("/batch/signoff", json={"month": "2026-03"})
    assert res.status_code == 502 and res.json()["code"] == "batch_signoff_failed" and "transform" not in res.json()["detail"]


def test_approval_needs_the_permission(started, monkeypatch):
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: _user(perms=("dashboard.view",))
    try:
        for path in ("/batch/signoff", "/batch/validate"):
            assert TestClient(app).post(path, json={"month": "2026-03"}).status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---- the job's log and what the page sees of it -----------------------------------------------------------------------

def test_the_whole_output_goes_to_a_file_and_the_page_gets_only_the_stages(monkeypatch):
    import sys
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    script = ("print('[abc] running'); print('Traceback: secret at postgresql://u:pw@host/db'); "
              "print('[abc] exited 2: batch stopped. Fix it and run the same command again; finished steps are skipped.'); raise SystemExit(2)")
    job = mb.Job()
    job.start("plan", [sys.executable, "-c", script], "2026-03")
    job.thread.join(30)
    state = job.state()
    assert "log" not in state and "Traceback" not in str(state)
    assert state["failed_stage"] == "abc" and state["steps"] == [{"stage": "abc", "label": "ABC classification", "state": "stopped"}]
    saved = next(mb.LOGS.glob("*_plan.log")).read_text(encoding="utf-8")
    assert "Traceback" in saved and "u:pw" not in saved and mb.PRACTICE_MARKER in saved[:200] and "exit code 2" in saved


def test_the_end_of_a_job_is_reported_once(monkeypatch):
    import sys
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    ended = []
    job = mb.Job()
    job.start("plan", [sys.executable, "-c", "print('x')"], "2026-03", ended.append)
    job.thread.join(30)
    assert ended == [job] and job.state()["status"] == "done"


def test_a_failure_to_record_the_end_does_not_hide_how_the_job_ended(monkeypatch):
    import sys
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)

    def broken(_job):
        raise RuntimeError("no database")

    job = mb.Job()
    job.start("plan", [sys.executable, "-c", "print('x')"], "2026-03", broken)
    job.thread.join(30)
    assert job.state()["status"] == "done"


def test_steps_carry_the_pages_database_for_the_decision_replay(monkeypatch):
    monkeypatch.setenv("MONTHLY_BATCH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    assert mb.step_env()[mb.PAGES_URL_ENV] == LOCAL
