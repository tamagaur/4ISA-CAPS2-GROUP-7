"""
backend.routers.monthly_batch — /batch, the Data Management page's monthly batch (2026-11-02).

LOCAL ONLY FOR NOW. backend/main.py mounts these routes only when MONTHLY_BATCH_ENABLED is on AND the database is the
throwaway local one (scripts/local_pg.py), so the deployed API does not have them and the page stays as it was. The routes
check again per request: GET /batch/status says {"enabled": false} and the rest refuse with 409 batch_local_only. No route passes --target-public, so scripts.run_month could not write to
live even if this check were wrong. Every step runs on ssm_practice, a copy of the local database (step_env): that is where
generated sales live, labelled is_demo = true. scripts/local_app.py runs this process on that copy too, so the pages show what a
closed month did, each answer labelled (backend/practice_copy.py); no other database holds those rows. Turning this on for live is a
separate decision: it would also have to solve where uploaded files live on the server.

It runs scripts, it does not reimplement them. A write is one child process of scripts.run_month, whose gates, order and
refusals all still apply, and the status and feedback are read by scripts.batch_status and scripts.cycle_feedback. This
keeps the boundary in backend/main.py: these routes never import the analytics package to run a step.

One job at a time, held in this process's memory. A restart forgets the job but not the work: run_month skips what is
already in the database. Each job's whole output goes to a file under local/monthly_batch/logs (git-ignored); the API gives the
page the stages reached (backend/batch_checklist.parse_steps), never the raw output, which can carry internals.

THE CHECKS BEFORE A RUN (2026-11-04, provisional, for Yuan's review: docs/MONTHLY_BATCH_REVIEW.md). GET /batch/checklist says where
the month stands. POST /batch/validate carries the Reorder page's decisions onto the practice copy (scripts.
replay_practice_decisions, through decide_row) and checks any waiting file with the loader's dry run (run_month --check-files).
POST /batch/signoff records a person's approval of a checked file (analytics.etl.transform_signoff, the same command as by hand).
POST /batch/run does the same replay and asks the checklist again, whatever the page believes, and answers 409 if anything blocks.
scripts.run_month then applies its own refusals when it starts, so nothing here is the only guard.
"""
from __future__ import annotations

import collections
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlparse

import shutil

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from backend import audit, batch_checklist, practice_copy, response_cache
from backend.api_errors import ApiError
from backend.auth_utils import TokenPayload
from backend.deps import get_db
from backend.practice_copy import PRACTICE_NOTE
from backend.permissions import require_permission

REPO = Path(__file__).resolve().parents[2]
UPLOADS = REPO / "local" / "monthly_batch" / "uploads"   # git-ignored: raw files hold per-product sales (hard rule 9)
VALIDATIONS = REPO / "local" / "monthly_batch" / "validation"   # git-ignored: what the last validation found, per month
LOGS = REPO / "local" / "monthly_batch" / "logs"         # git-ignored: each job's whole output
THROWAWAY = ("127.0.0.1", 55432)                         # scripts/local_pg.py
PRACTICE_DB = practice_copy.PRACTICE_DB
MONTH = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
ALLOWED_SUFFIXES = {".xlsx", ".xls", ".csv"}             # what the page's dropzone accepts
MAX_UPLOAD_BYTES = 100 * 1024 * 1024                     # the largest raw file on record is 34.7 MB (SSIS Jan 2021)
SLICES = {"sales": "unilever:unilever_sku_demand_fact:{month}", "count": "unilever:inventory_fact:{month}"}
PRACTICE_MONTH = "2026-03"                               # the only month scripts/local_pipeline_qa.py synth generates
LOG_LINES = 400
SCRIPT_TIMEOUT_S = 120
PAGES_URL_ENV = "BATCH_PAGES_DB_URL"                     # scripts/replay_practice_decisions.py
RUN_KEY = re.compile(r"^[A-Za-z0-9_-]+$")                # the loader's own run keys
_CONNECTION = re.compile(r"\b[a-z]+(?:\+[a-z0-9]+)?://\S+", re.I)
logger = logging.getLogger(__name__)

LOCAL_ONLY = "The monthly batch only runs on the local practice database for now."
PRACTICE_MARKER = "PRACTICE RUN ON GENERATED SALES, NOT A RESULT"   # scripts/report_target.PRACTICE_MARKER: every file a practice run writes says it

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
    """A step's environment: the practice database, on the throwaway server only."""
    require_local()
    url = urlparse(os.environ["SUPABASE_DB_URL"])._replace(path=f"/{PRACTICE_DB}").geturl()
    return {**os.environ, "SUPABASE_DB_URL": url, "SUPABASE_DIRECT_URL": url, "DATABASE_URL": url, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1",
            PAGES_URL_ENV: os.environ["SUPABASE_DB_URL"]}


def on_practice_copy() -> bool:
    return practice_copy.names_practice_copy()


def practice_copy_refusal(path: str) -> dict | None:
    """The 409 body for a request an API whose URL names ssm_practice must not answer, else None. Confirmed by the connection itself
    (backend/practice_copy.py), it answers everything, each answer labelled. Not confirmed, only /batch (which says what it is) and
    /health (no figure) answer."""
    if practice_copy.confirmed() or path == "/health" or path == "/batch" or path.startswith("/batch/"):
        return None
    return {"detail": f"This API is connected to {PRACTICE_DB}, which holds generated sales. Its figures are not served.", "code": "practice_copy_not_served"}


class Job:
    """The one running child process, its output and how it ended."""

    def __init__(self, env_factory: Callable[[], dict] | None = None, marker: str | None = None) -> None:
        self._env_factory = env_factory      # the live demonstration (backend/routers/live_demo.py) runs its steps on the database it is connected to
        self._marker = marker
        self._lock = threading.Lock()
        self.status = "idle"
        self.kind = None
        self.id = None
        self.month = None
        self.exit_code = None
        self.started_at = None
        self.finished_at = None
        self.lines = collections.deque(maxlen=LOG_LINES)
        self.thread = None

    def start(self, kind: str, cmd: list[str], month: str | None = None, on_finish: Callable[["Job"], None] | None = None) -> None:
        with self._lock:
            if self.status == "running":
                raise ApiError(409, "A batch step is already running. Wait for it to finish.", code="batch_busy")
            self.status, self.kind, self.exit_code = "running", kind, None
            self.id, self.month = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), month
            self.started_at, self.finished_at = datetime.now(timezone.utc).isoformat(), None
            self.lines.clear()
        self.thread = threading.Thread(target=self._run, args=(cmd, on_finish), daemon=True)
        self.thread.start()

    def _log_file(self):
        """The job's whole output, in the git-ignored folder. A log that cannot be written never stops the job."""
        try:
            LOGS.mkdir(parents=True, exist_ok=True)
            log = open(LOGS / f"{self.id}_{self.kind}.log", "w", encoding="utf-8")
            log.write(f"{PRACTICE_MARKER}\n{self._marker or PRACTICE_NOTE}\njob {self.id}, {self.kind}, month {self.month}\n\n")
            return log
        except OSError as exc:
            logger.warning("monthly batch: could not open the job log: %s", exc)
            return None

    def _run(self, cmd: list[str], on_finish) -> None:
        code = 1
        log = self._log_file()

        def record(line: str) -> None:
            line = _CONNECTION.sub("[connection hidden]", line)
            self.lines.append(line)
            if log:
                log.write(line + "\n")
                log.flush()

        try:
            proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", env=(self._env_factory or step_env)())
            for line in proc.stdout:
                record(line.rstrip())
            code = proc.wait()
        except (OSError, ApiError) as exc:
            record(f"could not start the step: {exc}")
        if log:
            log.write(f"\nexit code {code}\n")
            log.close()
        with self._lock:
            self.status = "done" if code == 0 else "failed"
            self.exit_code = code
            self.finished_at = datetime.now(timezone.utc).isoformat()
        response_cache.invalidate()    # the step wrote from another process, and the pages read this copy
        if on_finish:
            try:
                on_finish(self)
            except Exception as exc:  # noqa: BLE001 - the job has ended; a failure to record it must not hide that
                logger.warning("monthly batch: could not record the end of job %s: %s", self.id, exc)

    def state(self) -> dict:
        with self._lock:
            steps, failed_stage = batch_checklist.parse_steps(list(self.lines))
            return {"practice_note": PRACTICE_NOTE, "id": self.id, "status": self.status, "kind": self.kind, "month": self.month,
                    "exit_code": self.exit_code, "started_at": self.started_at, "finished_at": self.finished_at,
                    "steps": steps, "failed_stage": failed_stage}


JOB = Job()


def _script_json(*args: str) -> dict:
    """A read-only script's JSON answer. Its own process, so this one never imports analytics."""
    done = subprocess.run([sys.executable, "-m", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=SCRIPT_TIMEOUT_S, env=step_env())
    if done.returncode != 0:
        raise ApiError(502, "The batch status could not be read.", code="batch_status_failed")
    return json.loads(done.stdout.strip().splitlines()[-1])


def read_status(month: str | None = None, slices: tuple[str, ...] = (), run_key: str | None = None) -> dict:
    args = ["--month", month] if month else []
    for spec in slices:
        args += ["--slice", spec]
    return _script_json("scripts.batch_status", *args, *(["--run-key", run_key] if run_key else []))


def replay_decisions(month: str) -> dict:
    """Carries the Reorder page's decisions onto the practice copy, through decide_row. Safe to call again: nothing is applied twice."""
    return _script_json("scripts.replay_practice_decisions", "--cycle", month, "--write", "--json")


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


def check_file(path: Path, kind: str, month: str) -> dict:
    """Will the loader read this file? scripts/check_upload.py decides, by the loader's own rules, in its own process."""
    return _script_json("scripts.check_upload", "--kind", kind, "--month", month, "--file", str(path))
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_hashes(month: str) -> dict:
    """{kind: {name, sha256}} for the files there now, so a check on record can be told from a check of something else."""
    out = {}
    for kind in SLICES:
        folder = _month_folder(month, kind)
        files = sorted(folder.iterdir()) if folder.is_dir() else []
        if files:
            out[kind] = {"name": files[0].name, "sha256": _sha256(files[0])}
    return out


def _validation_path(month: str) -> Path:
    return VALIDATIONS / f"{month}.json"


def _file_check_path(month: str) -> Path:
    return VALIDATIONS / f"{month}.files.json"


def read_validation(month: str) -> dict | None:
    """What the last validation of this month recorded, with the loader's report when it has written one."""
    path = _validation_path(month)
    if not path.is_file():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    report = _file_check_path(month)
    if record.get("expects_file_check") and report.is_file():
        record["file_check"] = json.loads(report.read_text(encoding="utf-8"))
    return record


def write_validation(month: str, record: dict) -> None:
    VALIDATIONS.mkdir(parents=True, exist_ok=True)
    _file_check_path(month).unlink(missing_ok=True)
    _validation_path(month).write_text(json.dumps({"marker": PRACTICE_MARKER, **record}, indent=2, default=str), encoding="utf-8")


def _load_args(month: str, checks: dict) -> list[str]:
    """--slice and --file for the waiting files, as a run would pass them. Once the ABC has run, run_month refuses to load again, rightly."""
    args = []
    if checks.get("abc_run"):
        return args
    for kind in SLICES:
        folder = _month_folder(month, kind)
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            args += ["--slice", SLICES[kind].format(month=month), "--file", str(path)]
    return args


def _waiting_slices(month: str) -> tuple[str, ...]:
    return tuple(SLICES[kind].format(month=month) for kind in SLICES if uploaded_files(month).get(kind))


def _run_key(validation: dict | None) -> str | None:
    key = ((validation or {}).get("file_check") or {}).get("run_key")
    return key if key and RUN_KEY.match(key) else None


def checklist_for(month: str | None = None, replay: dict | None = None) -> tuple[dict, dict]:
    """(checklist, status), read fresh. The month, when not named, is the one run_month says is in play."""
    if month is None:
        month = read_status()["month"]
    validation = read_validation(month)
    status = read_status(month, _waiting_slices(month), _run_key(validation))
    # A replay just run on this request is fresher than its comparison, and it reports what would not carry over.
    if replay and status.get("replay") and replay.get("refused"):
        status["replay"]["refused"] = replay["refused"]
    job = JOB.state()
    checklist = batch_checklist.build_checklist(status, uploaded_files(month), validation, file_hashes(month), job)
    return {"practice_note": PRACTICE_NOTE, **checklist, "result": batch_checklist.run_result(status, job), "job": job}, status


def audit_event(action: str, details: str, user: TokenPayload) -> None:
    """One entry on the pages' database, in its own transaction. A failure to write it is logged and never stops the batch."""
    session = get_db()
    try:
        db = next(session)
        audit.record(db, action, details, actor=user)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("monthly batch: could not write the audit entry %r: %s", action, exc)
    finally:
        session.close()


def _failed_names(checklist: dict) -> str:
    return ", ".join(c["name"] for c in checklist["checks"] if c["blocking"] and c["status"] in ("failed", "not_checked"))


def _finish_audit(action_done: str, action_failed: str, month: str, user: TokenPayload) -> Callable[[Job], None]:
    def finish(job: Job) -> None:
        if job.status == "done":
            audit_event(action_done, f"Month {month}, job {job.id}", user)
        else:
            _, stage = batch_checklist.parse_steps(list(job.lines))
            audit_event(action_failed, f"Month {month}, job {job.id}, exit code {job.exit_code}" + (f", stopped at {stage}" if stage else ""), user)
    return finish


def _finish_run_audit(month: str, user: TokenPayload) -> Callable[[Job], None]:
    """Who, which month, how it ended and the run it wrote. Read after the job, so the run id is the one that exists."""
    def finish(job: Job) -> None:
        if job.status != "done":
            _finish_audit("", "Monthly Batch Run Failed", month, user)(job)
            return
        try:
            plan = read_status(month).get("next_plan") or {}
        except (ApiError, OSError, ValueError, subprocess.SubprocessError):
            plan = {}
        audit_event("Monthly Batch Run Completed",
                    f"Month {month}, job {job.id}, LP run {plan.get('run_key')}, {plan.get('rows')} rows, {round(plan.get('pieces') or 0):,} pieces", user)
    return finish


def _finish_validation_audit(month: str, user: TokenPayload) -> Callable[[Job], None]:
    def finish(job: Job) -> None:
        report = (read_validation(month) or {}).get("file_check") or {}
        refused = [e for e in report.get("events") or [] if e.get("status") == "refused"]
        if job.status != "done" or refused or not report.get("completed"):
            audit_event("Monthly Batch Validation Failed",
                        f"Month {month}, job {job.id}: {len(refused)} refused file or table check(s)" + ("" if report.get("completed") else ", the check did not finish"), user)
        else:
            audit_event("Monthly Batch Validation Passed", f"Month {month}, job {job.id}: the file checks found nothing that stops a load", user)
    return finish


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


def _refuse_while_running() -> None:
    if JOB.state()["status"] == "running":
        raise ApiError(409, "A batch step is already running. Wait for it to finish.", code="batch_busy")


@router.get("/status")
def status(month: str | None = Query(default=None, pattern=MONTH),
           _user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    if not enabled():
        return {"enabled": False}
    current = read_status(month)
    job = JOB.state()
    return {"enabled": True, "practice_note": PRACTICE_NOTE, **current, "files": uploaded_files(current["month"]), "practice_month": PRACTICE_MONTH,
            "job": job, "result": batch_checklist.run_result(current, job)}


@router.get("/checklist")
def checklist(month: str | None = Query(default=None, pattern=MONTH), _user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    """Where the month stands, check by check, read fresh. Reads only: the decisions are carried over by POST /batch/validate."""
    require_local()
    return checklist_for(month)[0]


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
    _refuse_while_running()
    if kind not in SLICES:
        raise ApiError(400, "A file is either the month's sales or its stock count.", code="batch_bad_kind")
    # A browser may send a whole path, with either separator. Only the last part is kept.
    name = re.sub(r"[^\w.\- ()]", "_", re.split(r"[\\/]", file.filename or "")[-1]).strip(". ")
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ApiError(400, "Only .xlsx, .xls and .csv files are accepted.", code="batch_bad_file_type")
    if read_status(month)["checks"].get("abc_run"):
        raise ApiError(409, "This month has already been run, so a new file would not reach the forecast or the plan.", code="batch_already_ran")
    # Checked before it replaces anything: a file the loader would refuse leaves the slot as it was. Kept beside its final
    # folder and under its own name, because the loader reads a month from the name and the folders above it.
    holding = UPLOADS / month / f".checking-{kind}"
    shutil.rmtree(holding, ignore_errors=True)
    holding.mkdir(parents=True)
    try:
        held, written = holding / name, 0
        with open(held, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise ApiError(413, "That file is larger than the 100 MB limit.", code="batch_file_too_large")
                out.write(chunk)
        checked = check_file(held, kind, month)
        if not checked["ok"]:
            raise ApiError(422, checked["message"], code="batch_file_not_usable")
        folder = _month_folder(month, kind)
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.iterdir():
            old.unlink()
        held.replace(folder / name)
    finally:
        shutil.rmtree(holding, ignore_errors=True)
    return {"kind": kind, "name": name, "bytes": written, "check": checked}


@router.post("/validate", status_code=202)
def validate(body: PracticeBody, user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    """Carries the decisions over, and checks any waiting file with the loader's dry run. Loads nothing. The checklist then says
    what it found: started says whether a file check is running first."""
    require_local()
    _refuse_while_running()
    replay = replay_decisions(body.month)
    status = read_status(body.month)
    load_args = _load_args(body.month, status["checks"])
    record = {"month": body.month, "validated_at": datetime.now(timezone.utc).isoformat(), "by": _approver(user),
              "hashes": file_hashes(body.month), "expects_file_check": bool(load_args), "replay": replay}
    write_validation(body.month, record)
    applied = f"{replay.get('applied', 0)} decision(s) carried onto the practice copy, {replay.get('reversed', 0)} reversed"
    if load_args:
        # The calendar factor plays no part in a file check; run_month asks for it on every call.
        cmd = [sys.executable, "-m", "scripts.run_month", "--month", body.month, "--calendar-factor", "on", "--check-files",
               *load_args, "--check-files-report", str(_file_check_path(body.month))]
        JOB.start("validate", cmd, body.month, _finish_validation_audit(body.month, user))
        audit_event("Monthly Batch Validation Started", f"Month {body.month}: {applied}; files {', '.join(e['name'] for e in record['hashes'].values())}", user)
        return {"practice_note": PRACTICE_NOTE, "started": "validate", "replay": replay}
    current, _ = checklist_for(body.month, replay)
    failing = _failed_names(current)
    audit_event("Monthly Batch Validation Failed" if failing else "Monthly Batch Validation Passed",
                f"Month {body.month}: {applied}" + (f"; not passed: {failing}" if failing else ""), user)
    return {"practice_note": PRACTICE_NOTE, "started": None, "replay": replay}


@router.post("/signoff")
def signoff(body: PracticeBody, user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    """A named person's approval of a checked file: the loader's own sign-off command, on the manifest the check wrote. Refused for a
    file that was not checked, changed since, or did not pass. The loader then checks the approval against the file when it loads."""
    require_local()
    _refuse_while_running()
    validation = read_validation(body.month)
    report = (validation or {}).get("file_check")
    hashes = file_hashes(body.month)
    if not hashes or not report or not report.get("completed"):
        raise ApiError(409, "Run validation first: there is no finished file check to approve.", code="batch_not_validated")
    if not batch_checklist.validation_is_current(validation, hashes):
        raise ApiError(409, "A file changed after it was checked. Run validation again.", code="batch_validation_stale")
    if any(e.get("status") == "refused" for e in report.get("events") or []):
        raise ApiError(409, "A file with problems cannot be approved. Fix the file and run validation again.", code="batch_files_invalid")
    run_key = _run_key(validation)
    if not run_key:
        raise ApiError(409, "Run validation first: there is no finished file check to approve.", code="batch_not_validated")
    by = _approver(user)
    done = subprocess.run([sys.executable, "-m", "analytics.etl.transform_signoff", "--transform-dir", f"transform/slices/{run_key}",
                           "--decision", "approved", "--by", by, "--notes", f"Approved on the Data Management page for {body.month}"],
                          cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=SCRIPT_TIMEOUT_S, env=step_env())
    if done.returncode != 0:
        logger.warning("monthly batch: the sign-off command exited %s", done.returncode)
        raise ApiError(502, "The approval could not be recorded. Run validation again and retry.", code="batch_signoff_failed")
    audit_event("Monthly Batch File Approved", f"Month {body.month}: {', '.join(e['name'] for e in hashes.values())}", user)
    return {"practice_note": PRACTICE_NOTE, "signed": True, "by": by, "files": [e["name"] for e in hashes.values()]}


@router.post("/practice-month", status_code=202)
def practice_month(body: PracticeBody, _user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_local()
    if body.month != PRACTICE_MONTH:
        raise ApiError(400, f"Practice sales can only be generated for {PRACTICE_MONTH}.", code="batch_no_practice_month")
    for old in _month_folder(body.month, "sales").glob("*"):
        old.unlink()    # the practice sales replace it: a run would otherwise load the file over them
    JOB.start("practice", [sys.executable, "scripts/local_pipeline_qa.py", "synth"], body.month)
    return {"started": "practice"}


@router.post("/run", status_code=202)
def run(body: RunBody, user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    """Asks every check again, whatever the page last saw: a validation on record is not permission. scripts.run_month then applies
    its own refusals when it starts."""
    require_local()
    _refuse_while_running()
    replay = replay_decisions(body.month)
    current, status = checklist_for(body.month, replay)
    if not current["can_run"]:
        failing = _failed_names(current)
        audit_event("Monthly Batch Run Refused", f"Month {body.month}: {failing}", user)
        raise ApiError(409, f"This month cannot run yet: {failing}.", code="batch_checks_failed",
                       checks=[c for c in current["checks"] if c["blocking"] and c["status"] in ("failed", "not_checked")],
                       decisions=current["decisions"])
    # A rerun after the ABC ran resumes the steps after it. run_month refuses to load again at that point, rightly.
    # A load needs a signed manifest; on the copy the system signs it, and says so (scripts/practice_signed_load.py).
    load_args = _load_args(body.month, status["checks"])
    cmd = _month_args(body, user)
    if load_args:
        cmd = [sys.executable, "-m", "scripts.practice_signed_load", "--pressed-by", _approver(user), "--", *cmd[1:], *load_args]
    JOB.start("plan", cmd, body.month, _finish_run_audit(body.month, user))
    audit_event("Monthly Batch Run Started", f"Month {body.month}, job {JOB.state()['id']}, calendar factor {body.calendar_factor}", user)
    return {"started": "plan"}


@router.post("/close", status_code=202)
def close(body: CloseBody, user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_local()
    JOB.start("close", _month_args(body, user) + ["--close", "--expect-plan-pieces", str(body.expect_plan_pieces)], body.month,
              _finish_audit("Monthly Batch Close Completed", "Monthly Batch Close Failed", body.month, user))
    audit_event("Monthly Batch Close Started", f"Month {body.month}, job {JOB.state()['id']}", user)
    return {"started": "close"}
