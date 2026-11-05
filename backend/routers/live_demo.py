"""
backend.routers.live_demo - /live-demo, the Data Management page's demonstration month on the database the pages read, and its UNDO (2026-11-05).

NOT ON THE DEPLOYED API. backend/main.py mounts these routes only when enabled() says so, so the deployed service keeps its pinned route count
(docs/CHAPTER4_CODE_FIGURES.json). enabled() needs, together:
  LIVE_DEMO_ENABLED=true                         said on purpose, in the environment of a process started by a person
  no RENDER variable                             never on the hosted service, which could not hold the uploaded file anyway
  a database on this machine (the rehearsal copy), OR for any other database ALL OF
    LIVE_DEMO_CONFIRM_HOST equal to the URL's host (so a stray flag cannot aim it at a database nobody named),
    local/demo_revert_proof.json with passed = true (scripts/demo_revert_proof.py: a month run and reverted on a restored copy), and
    local/demo_session_rehearsal.json for THIS code (scripts/demo_rehearsal.py: a whole month run and undone on a restored copy by this very tool).
Every route also asks require_permission("upload.run") (admin) and checks enabled() again.

It runs scripts/demo_session.py, it does not reimplement it: one child process per button (open, run, undo), one at a time, and the page reads
the stages reached (an allow-list of lines), never raw output. The sales file is a CSV kept in the git-ignored local/ folder (hard rule 9).
Everything the window does and the undo that ends it are in scripts/demo_session.py and analytics/demo_session.py: read their headers.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from backend import response_cache
from backend.api_errors import ApiError
from backend.auth_utils import TokenPayload
from backend.permissions import require_permission
from backend.routers import monthly_batch as mb
from scripts import demo_rehearsal

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
UPLOADS = REPO / "local" / "live_demo" / "uploads"
LAST_UNDO = REPO / "local" / "demo_session_last_undo.json"
PROOF_FILE = REPO / "local" / "demo_revert_proof.json"
MONTH = "2026-03"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
SCRIPT_TIMEOUT_S = 120
SHOWN = re.compile(r"^(\[(open|load|run|settle|undo|abc|forecast|lp|marts|review)\]|REFUSED|  plan \d{4}-\d{2}:|REVIEW BEFORE)")
router = APIRouter(prefix="/live-demo", tags=["live-demo"])


def _db_host() -> str:
    return urlparse(os.environ.get("SUPABASE_DB_URL") or "").hostname or ""


def _proof_passed() -> bool:
    try:
        return json.loads(PROOF_FILE.read_text(encoding="utf-8")).get("passed") is True
    except (OSError, ValueError):
        return False


def gates() -> tuple[bool, str]:
    """(passed, why not): the revert proof and a rehearsal of this very code, both made on this machine."""
    if not _proof_passed():
        return False, "no passing revert proof (local/demo_revert_proof.json)"
    return demo_rehearsal.ok()


def enabled() -> bool:
    if os.environ.get("LIVE_DEMO_ENABLED", "").strip().lower() != "true" or os.environ.get("RENDER"):
        return False
    host = _db_host()
    if not host:
        return False
    if host in LOCAL_HOSTS:
        return True
    return os.environ.get("LIVE_DEMO_CONFIRM_HOST", "") == host and gates()[0]


def require_enabled() -> None:
    if not enabled():
        raise ApiError(409, "The live demonstration is not switched on for this server.", code="live_demo_off")


def target_label() -> str:
    return "a local rehearsal copy of the database" if _db_host() in LOCAL_HOSTS else "the real database"


def _env() -> dict:
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}


def _script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "scripts.demo_session", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=SCRIPT_TIMEOUT_S, env=_env())


def read_state() -> dict:
    done = _script("status", "--json")
    if done.returncode != 0:
        raise ApiError(502, "The demonstration's state could not be read.", code="live_demo_status_failed")
    return json.loads(done.stdout.strip().splitlines()[-1])


class DemoJob(mb.Job):
    """The same one-job-at-a-time child process as the monthly batch, with a different environment and only the allow-listed lines shown."""

    def state(self) -> dict:
        with self._lock:
            shown = [ln for ln in self.lines if SHOWN.match(ln)]
            return {"id": self.id, "status": self.status, "kind": self.kind, "exit_code": self.exit_code, "started_at": self.started_at,
                    "finished_at": self.finished_at, "lines": shown[-60:]}


JOB = DemoJob(env_factory=_env, marker="DEMONSTRATION ON GENERATED SALES, NOT A RESULT")


def _uploaded() -> dict | None:
    files = sorted(UPLOADS.glob("*")) if UPLOADS.is_dir() else []
    return {"name": files[0].name, "bytes": files[0].stat().st_size} if files else None


def _target_name() -> str:
    u = urlparse(os.environ.get("SUPABASE_DB_URL") or "")
    return f"{u.hostname}/{u.path.lstrip('/')}"


def _last_undo() -> dict | None:
    """The newest undo's result, only when it was made on THIS database: a file left by another one is not this one's proof."""
    try:
        found = json.loads(LAST_UNDO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if found.get("target") == _target_name() else None


def _approver(user: TokenPayload) -> str:
    return user.email or f"user {user.user_id}"


def _after(action_done: str, action_failed: str, user: TokenPayload):
    def finish(job) -> None:
        mb.audit_event(action_done if job.status == "done" else action_failed, f"Live demonstration, job {job.id}, exit code {job.exit_code}", user)
        response_cache.invalidate()   # the step wrote from another process, and the pages read this database
    return finish


class UndoBody(BaseModel):
    confirm: bool


class RunBody(BaseModel):
    calendar_factor: str = "on"


@router.get("/status")
def status(_user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    if not enabled():
        return {"enabled": False}
    state = read_state()
    return {"enabled": True, "target": target_label(), "month": MONTH, "state": state, "file": _uploaded(), "job": JOB.state(),
            "last_undo": _last_undo(), "gates": dict(zip(("passed", "why_not"), gates()))}


@router.get("/job")
def job(_user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_enabled()
    return JOB.state()


def _refuse_while_running() -> None:
    if JOB.state()["status"] == "running":
        raise ApiError(409, "A step is already running. Wait for it to finish.", code="batch_busy")


@router.post("/start", status_code=202)
def start(user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_enabled()
    _refuse_while_running()
    if read_state()["session"]:
        raise ApiError(409, "A demonstration is already open. Undo it first.", code="live_demo_already_open")
    JOB.start("open", [sys.executable, "-m", "scripts.demo_session", "open", "--by", _approver(user), "--target-public"], MONTH,
              _after("Live Demonstration Opened", "Live Demonstration Open Failed", user))
    mb.audit_event("Live Demonstration Open Started", f"On {target_label()}: every table is copied, then the demonstration window opens", user)
    return {"started": "open"}


@router.post("/file", status_code=201)
def upload(file: UploadFile = File(...), user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_enabled()
    _refuse_while_running()
    state = read_state()
    if not state["open"]:
        raise ApiError(409, "Start the demonstration first: a file is checked against the open window.", code="live_demo_not_open")
    if state["generated_rows"]:
        raise ApiError(409, "The demonstration month has already been loaded.", code="live_demo_already_loaded")
    name = re.sub(r"[^\w.\- ()]", "_", re.split(r"[\\/]", file.filename or "")[-1]).strip(". ")
    if Path(name).suffix.lower() != ".csv":
        raise ApiError(400, "The demonstration loader takes a .csv file: sku_code, quantity_sold, net_amount.", code="batch_bad_file_type")
    holding = UPLOADS.parent / ".checking"
    shutil.rmtree(holding, ignore_errors=True)
    holding.mkdir(parents=True)
    try:
        held, written = holding / name, 0
        with open(held, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise ApiError(413, "That file is larger than the 20 MB limit.", code="batch_file_too_large")
                out.write(chunk)
        done = _script("check-file", "--file", str(held), "--month", MONTH)
        if done.returncode != 0:
            raise ApiError(502, "The file could not be checked.", code="live_demo_check_failed")
        checked = json.loads(done.stdout.strip().splitlines()[-1])
        if not checked["ok"]:
            raise ApiError(422, checked["message"], code="batch_file_not_usable")
        shutil.rmtree(UPLOADS, ignore_errors=True)
        UPLOADS.mkdir(parents=True)
        held.replace(UPLOADS / name)
    finally:
        shutil.rmtree(holding, ignore_errors=True)
    mb.audit_event("Live Demonstration File Accepted", f"{name}: {checked['rows']} generated rows for {MONTH}, not yet loaded", user)
    return {"name": name, "bytes": written, "check": checked}


@router.post("/settle", status_code=202)
def settle(user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    """Accepts the baseline plan's orders through decide_row, labelled, so the run is not refused for want of decisions. The Reorder page stays the real way."""
    require_enabled()
    _refuse_while_running()
    if not read_state()["open"]:
        raise ApiError(409, "Start the demonstration first.", code="live_demo_not_open")
    JOB.start("settle", [sys.executable, "-m", "scripts.demo_session", "settle", "--by", _approver(user), "--target-public"], MONTH,
              _after("Live Demonstration Orders Accepted", "Live Demonstration Order Acceptance Failed", user))
    mb.audit_event("Live Demonstration Order Acceptance Started", "The pending orders of the baseline plan are accepted through the Reorder page's own writer", user)
    return {"started": "settle"}


@router.post("/run", status_code=202)
def run(body: RunBody, user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_enabled()
    _refuse_while_running()
    if body.calendar_factor not in ("on", "off"):
        raise ApiError(400, "calendar_factor is on or off.", code="batch_bad_request")
    state = read_state()
    uploaded = _uploaded()
    if not state["open"]:
        raise ApiError(409, "Start the demonstration first.", code="live_demo_not_open")
    if not uploaded and not state["generated_rows"]:
        raise ApiError(409, "Upload the March sales file first.", code="live_demo_no_file")
    waiting = (state.get("baseline_plan_decisions") or {}).get("waiting", 0)
    newest = state.get("newest_cycle")
    baseline_cycle = (state.get("session") or {}).get("baseline", {}).get("cycle")
    if waiting and newest == baseline_cycle:
        raise ApiError(409, f"{waiting} orders of the {baseline_cycle} plan still await a decision. Accept or dismiss them on the Reorder page, then run. "
                            "(Undo puts those decisions back too.)", code="batch_checks_failed", decisions=state["baseline_plan_decisions"])
    cmd = [sys.executable, "-m", "scripts.demo_session", "run", "--by", _approver(user), "--calendar-factor", body.calendar_factor, "--target-public"]
    cmd += ["--file", str(UPLOADS / uploaded["name"])] if uploaded else ["--file", str(REPO / "local" / "demo" / "demo_march_sales.csv")]
    JOB.start("run", cmd, MONTH, _after("Live Demonstration Run Completed", "Live Demonstration Run Failed", user))
    mb.audit_event("Live Demonstration Run Started", f"Month {MONTH}, calendar factor {body.calendar_factor}, job {JOB.state()['id']}", user)
    return {"started": "run"}


@router.post("/undo", status_code=202)
def undo(body: UndoBody, user: TokenPayload = Depends(require_permission("upload.run"))) -> dict:
    require_enabled()
    _refuse_while_running()
    if not body.confirm:
        raise ApiError(400, "Undo must be confirmed.", code="live_demo_unconfirmed")
    if not read_state()["session"]:
        raise ApiError(409, "No demonstration is open: there is nothing to undo.", code="live_demo_not_open")
    mb.audit_event("Live Demonstration Undo Started", "Every table and definition is put back and checked", user)
    JOB.start("undo", [sys.executable, "-m", "scripts.demo_session", "undo", "--yes", "--target-public"], MONTH,
              _after("Live Demonstration Undone", "Live Demonstration Undo Failed", user))
    shutil.rmtree(UPLOADS, ignore_errors=True)
    return {"started": "undo"}
