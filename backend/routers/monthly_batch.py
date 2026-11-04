"""
backend.routers.monthly_batch — /batch, the Data Management page's monthly batch (2026-11-02).

LOCAL ONLY FOR NOW. backend/main.py mounts these routes only when MONTHLY_BATCH_ENABLED is on AND the database is the
throwaway local one (scripts/local_pg.py), so the deployed API does not have them and the page stays as it was. The routes
check again per request: GET /batch/status says {"enabled": false} and the rest refuse with 409 batch_local_only. No route passes --target-public, so scripts.run_month could not write to
live even if this check were wrong. Every step runs on ssm_practice, a copy of the local database (step_env): that is where
generated sales live, labelled is_demo = true, so the database behind the pages holds none. Turning this on for live is a separate decision: it would also have to solve where
uploaded files live on the server.

It runs scripts, it does not reimplement them. A write is one child process of scripts.run_month, whose gates, order and
refusals all still apply, and the status and feedback are read by scripts.batch_status and scripts.cycle_feedback. This
keeps the boundary in backend/main.py: this process never imports the analytics package.

One job at a time, held in this process's memory. A restart forgets the log but not the work: run_month skips what is
already in the database.
"""
from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from backend.api_errors import ApiError
from backend.auth_utils import TokenPayload
from backend.permissions import require_permission

REPO = Path(__file__).resolve().parents[2]
UPLOADS = REPO / "local" / "monthly_batch" / "uploads"   # git-ignored: raw files hold per-product sales (hard rule 9)
THROWAWAY = ("127.0.0.1", 55432)                         # scripts/local_pg.py
PRACTICE_DB = "ssm_practice"                             # scripts/local_pg.py practice
MONTH = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
ALLOWED_SUFFIXES = {".xlsx", ".xls", ".csv"}             # what the page's dropzone accepts
MAX_UPLOAD_BYTES = 100 * 1024 * 1024                     # the largest raw file on record is 34.7 MB (SSIS Jan 2021)
SLICES = {"sales": "unilever:unilever_sku_demand_fact:{month}", "count": "unilever:inventory_fact:{month}"}
PRACTICE_MONTH = "2026-03"                               # the only month scripts/local_pipeline_qa.py synth generates
LOG_LINES = 400
SCRIPT_TIMEOUT_S = 120

LOCAL_ONLY = "The monthly batch only runs on the local practice database for now."
# On every /batch answer that holds a figure. The job log can lose its first lines to LOG_LINES, so the log's own marker is not enough.
PRACTICE_NOTE = "Read from the practice copy (ssm_practice), whose sales may be generated. Practice, not a result."

router = APIRouter(prefix="/batch", tags=["monthly-batch"])


def enabled() -> bool:
    if os.environ.get("MONTHLY_BATCH_ENABLED", "").strip().lower() != "true":
        return False
    url = urlparse(os.environ.get("SUPABASE_DB_URL") or "")
    return (url.hostname, url.port) == THROWAWAY


def require_local() -> None:
    if not enabled():
        raise ApiError(409, LOCAL_ONLY, code="batch_local_only")


def step_env() -> dict:
    """A step's environment: the practice database, on the throwaway server only. This process stays on the pages' database."""
    require_local()
    url = urlparse(os.environ["SUPABASE_DB_URL"])._replace(path=f"/{PRACTICE_DB}").geturl()
    return {**os.environ, "SUPABASE_DB_URL": url, "SUPABASE_DIRECT_URL": url, "DATABASE_URL": url, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}


def on_practice_copy() -> bool:
    return urlparse(os.environ.get("SUPABASE_DB_URL") or "").path == f"/{PRACTICE_DB}"


def practice_copy_refusal(path: str) -> dict | None:
    """The 409 body for a request an API running on ssm_practice must not answer, else None. The data routes have no way to say their
    figures rest on generated sales, and no page reads that copy (the pages' process stays on ssm_local, step_env), so they answer
    nothing there. /batch says what it is (PRACTICE_NOTE); /health holds no figure."""
    if path == "/health" or path == "/batch" or path.startswith("/batch/"):
        return None
    return {"detail": f"This API is connected to {PRACTICE_DB}, which holds generated sales. Its figures are not served.", "code": "practice_copy_not_served"}


class Job:
    """The one running child process, its output and how it ended."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.status = "idle"
        self.kind = None
        self.exit_code = None
        self.started_at = None
        self.finished_at = None
        self.lines = collections.deque(maxlen=LOG_LINES)
        self.thread = None

    def start(self, kind: str, cmd: list[str]) -> None:
        with self._lock:
            if self.status == "running":
                raise ApiError(409, "A batch step is already running. Wait for it to finish.", code="batch_busy")
            self.status, self.kind, self.exit_code = "running", kind, None
            self.started_at, self.finished_at = datetime.now(timezone.utc).isoformat(), None
            self.lines.clear()
        self.thread = threading.Thread(target=self._run, args=(cmd,), daemon=True)
        self.thread.start()

    def _run(self, cmd: list[str]) -> None:
        code = 1
        try:
            proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", env=step_env())
            for line in proc.stdout:
                self.lines.append(line.rstrip())
            code = proc.wait()
        except (OSError, ApiError) as exc:
            self.lines.append(f"could not start the step: {exc}")
        with self._lock:
            self.status = "done" if code == 0 else "failed"
            self.exit_code = code
            self.finished_at = datetime.now(timezone.utc).isoformat()

    def state(self) -> dict:
        with self._lock:
            return {"practice_note": PRACTICE_NOTE, "status": self.status, "kind": self.kind, "exit_code": self.exit_code, "started_at": self.started_at,
                    "finished_at": self.finished_at, "log": "\n".join(self.lines)}


JOB = Job()


def _script_json(*args: str) -> dict:
    """A read-only script's JSON answer. Its own process, so this one never imports analytics."""
    done = subprocess.run([sys.executable, "-m", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=SCRIPT_TIMEOUT_S, env=step_env())
    if done.returncode != 0:
        raise ApiError(502, "The batch status could not be read.", code="batch_status_failed")
    return json.loads(done.stdout.strip().splitlines()[-1])


def read_status(month: str | None = None) -> dict:
    return _script_json("scripts.batch_status", *(["--month", month] if month else []))


def _month_folder(month: str, kind: str) -> Path:
    return UPLOADS / month / kind


def uploaded_files(month: str) -> dict:
    out = {}
    for kind in SLICES:
        folder = _month_folder(month, kind)
        files = sorted(folder.iterdir()) if folder.is_dir() else []
        if files:
            out[kind] = {"name": files[0].name, "bytes": files[0].stat().st_size}
    return out


def _approver(user: TokenPayload) -> str:
    return user.email or f"user {user.user_id}"


class RunBody(BaseModel):
    month: str = Field(pattern=MONTH)
    calendar_factor: Literal["on", "off"]


class CloseBody(RunBody):
    expect_plan_pieces: int = Field(ge=0)


class PracticeBody(BaseModel):
    month: str = Field(pattern=MONTH)


def _month_args(body: RunBody, user: TokenPayload) -> list[str]:
    return [sys.executable, "-m", "scripts.run_month", "--month", body.month, "--calendar-factor", body.calendar_factor,
            "--approved-by", _approver(user), "--expect-month", body.month]


@router.get("/status")
def status(month: str | None = Query(default=None, pattern=MONTH),
           _user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    if not enabled():
        return {"enabled": False}
    current = read_status(month)
    return {"enabled": True, "practice_note": PRACTICE_NOTE, **current, "files": uploaded_files(current["month"]), "practice_month": PRACTICE_MONTH, "job": JOB.state()}


@router.get("/job")
def job(_user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_local()
    return JOB.state()


@router.get("/feedback")
def feedback(cycle: str = Query(pattern=MONTH), _user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_local()
    return {"practice_note": PRACTICE_NOTE, **_script_json("scripts.cycle_feedback", "--cycle", cycle, "--json")}


@router.post("/files", status_code=201)
def upload_file(month: str = Form(pattern=MONTH), kind: str = Form(), file: UploadFile = File(...),
                _user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_local()
    if kind not in SLICES:
        raise ApiError(400, "A file is either the month's sales or its stock count.", code="batch_bad_kind")
    # A browser may send a whole path, with either separator. Only the last part is kept.
    name = re.sub(r"[^\w.\- ()]", "_", re.split(r"[\\/]", file.filename or "")[-1]).strip(". ")
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ApiError(400, "Only .xlsx, .xls and .csv files are accepted.", code="batch_bad_file_type")
    if read_status(month)["checks"].get("abc_run"):
        raise ApiError(409, "This month has already been run, so a new file would not reach the forecast or the plan.", code="batch_already_ran")
    folder = _month_folder(month, kind)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():
        old.unlink()
    target, written = folder / name, 0
    with open(target, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                out.close()
                target.unlink()
                raise ApiError(413, "That file is larger than the 100 MB limit.", code="batch_file_too_large")
            out.write(chunk)
    return {"kind": kind, "name": name, "bytes": written}


@router.post("/practice-month", status_code=202)
def practice_month(body: PracticeBody, _user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_local()
    if body.month != PRACTICE_MONTH:
        raise ApiError(400, f"Practice sales can only be generated for {PRACTICE_MONTH}.", code="batch_no_practice_month")
    for old in _month_folder(body.month, "sales").glob("*"):
        old.unlink()    # the practice sales replace it: a run would otherwise load the file over them
    JOB.start("practice", [sys.executable, "scripts/local_pipeline_qa.py", "synth"])
    return {"started": "practice"}


@router.post("/run", status_code=202)
def run(body: RunBody, user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_local()
    cmd = _month_args(body, user)
    # A rerun after the ABC ran resumes the steps after it. run_month refuses to load again at that point, rightly.
    kinds = () if read_status(body.month)["checks"].get("abc_run") else SLICES
    for kind in kinds:
        folder = _month_folder(body.month, kind)
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            cmd += ["--slice", SLICES[kind].format(month=body.month), "--file", str(path)]
    JOB.start("plan", cmd)
    return {"started": "plan"}


@router.post("/close", status_code=202)
def close(body: CloseBody, user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_local()
    JOB.start("close", _month_args(body, user) + ["--close", "--expect-plan-pieces", str(body.expect_plan_pieces)])
    return {"started": "close"}
