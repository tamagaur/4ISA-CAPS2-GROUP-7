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
    monkeypatch.setattr(mb.JOB, "start", lambda kind, cmd: calls.append((kind, cmd)))
    monkeypatch.setattr(mb, "read_status", lambda month=None: {"month": "2026-03", "checks": {}})
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
    monkeypatch.setattr(mb.JOB, "start", lambda kind, cmd: started.append(cmd))
    for path, body in (("/batch/run", _run_body()), ("/batch/close", _run_body(expect_plan_pieces=1)),
                       ("/batch/practice-month", {"month": "2026-03"})):
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


def test_uploaded_files_become_slices_and_files(started, client):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    client.post("/batch/files", data={"month": "2026-03", "kind": "count"},
                files={"file": ("count.xlsx", io.BytesIO(b"y"), "application/octet-stream")})
    client.post("/batch/run", json=_run_body())
    _, cmd = started[0]
    assert cmd[1:3] == ["-m", "scripts.practice_signed_load"] and cmd[cmd.index("--approved-by") + 1] == "planner@ssmcapstone.com"
    cut = cmd.index("--")
    assert cmd[cut + 1:cut + 3] == ["-m", "scripts.run_month"]
    month = cmd[cut + 1:]
    slices = [month[i + 1] for i, a in enumerate(month) if a == "--slice"]
    files = [month[i + 1] for i, a in enumerate(month) if a == "--file"]
    assert [a for a in cmd[:cut] if a == "--slice"] == ["--slice", "--slice"] and [a for a in cmd[:cut] if a == "--file"] == ["--file", "--file"]
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
    assert state["status"] == "failed" and state["exit_code"] == 3 and "hello" in state["log"]


def test_a_step_refused_outside_the_local_database_ends_the_job(monkeypatch):
    import sys
    monkeypatch.delenv("MONTHLY_BATCH_ENABLED", raising=False)
    monkeypatch.setenv("SUPABASE_DB_URL", LIVE)
    job = mb.Job()
    job.start("plan", [sys.executable, "-c", "print('ran')"])
    job.thread.join(30)
    state = job.state()
    assert state["status"] == "failed" and "ran" not in state["log"]


# ---- resuming after a failure, and switching between a file and practice sales ---------------------------------------

def test_a_rerun_after_the_abc_ran_does_not_load_the_file_again(started, client, monkeypatch):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    monkeypatch.setattr(mb, "read_status", lambda month=None: {"month": "2026-03", "checks": {"abc_run": True}})
    client.post("/batch/run", json=_run_body())
    assert "--slice" not in started[0][1] and "--file" not in started[0][1]


def test_a_new_file_is_refused_once_the_abc_has_run(started, client, monkeypatch):
    monkeypatch.setattr(mb, "read_status", lambda month=None: {"month": "2026-03", "checks": {"abc_run": True}})
    res = client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                      files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    assert res.status_code == 409 and res.json()["code"] == "batch_already_ran"


def test_practice_sales_replace_an_uploaded_sales_file(started, client, tmp_path):
    client.post("/batch/files", data={"month": "2026-03", "kind": "sales"},
                files={"file": ("sales.xls", io.BytesIO(b"x"), "application/octet-stream")})
    client.post("/batch/practice-month", json={"month": "2026-03"})
    assert list(tmp_path.rglob("*.xls")) == []
