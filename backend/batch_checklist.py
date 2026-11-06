"""
backend.batch_checklist - the Data Management page's Monthly Processing Checklist and run result (2026-11-04).

Pure: no database, no child process, no analytics import. It turns what the scripts already report (scripts/batch_status.py, the
loader's dry run, the job) into words a person can act on, and decides nothing the scripts do not: run_month's refusals stay the
rule, and scripts.run_month checks them again when it starts. The page shows this and works out none of it.

ONLY NINE THINGS ARE CHECKED, and each comes from a check that already existed, except the reorder decisions, which are new
(run_month.decisions_refusal). close_cycle.CHECKS is deliberately NOT turned into pass or fail here: before a normal run the ABC, the
forecast and the plan are false by design, so those flags are shown as progress (`progress`), not as failures.
"""
from __future__ import annotations

import re

PASSED, FAILED, WARNING, NOT_CHECKED = "passed", "failed", "warning", "not_checked"

# The loader's reason codes (scripts/load_slices.py), in words for the person holding the file.
REASONS = {
    "layout_changed": ("The file's layout is not the one expected.", "Check it is the right report, then upload it again."),
    "missing_file": ("No file was found for this month and table.", "Upload the file for this month."),
    "shrink_guard": ("This file would remove most of the rows already held for the month.", "Check the file is complete, then upload it again."),
    "shrink_allowed": ("This file removes many of the rows already held for the month.", "Check the file is complete."),
    "validation_failed": ("Figures in this file fall outside what earlier months allow.", "Check the file with whoever sent it, then upload it again."),
    "validation_warning": ("Some figures look unusual compared with earlier months.", "Read the detail and decide whether the file is right."),
    "unmapped_column": ("The file has columns the system does not read.", "Check that nothing needed is in them."),
    "key_conflict_other_slice": ("Some rows belong to another month or table already loaded.", "Check the file covers only this month."),
    "partial_month": ("The file covers only part of the month.", "Upload the full month's file."),
    "period_not_allowed": ("This kind of file is not accepted for this month.", "Check the month, then upload the right file."),
    "row_balance": ("The row counts did not add up.", "Run the check again. If it repeats, keep the technical log."),
    "fingerprint_unsigned": ("This file has not been approved yet.", "Approve the file."),
    "error": ("This file could not be read.", "Check the file and upload it again. The technical log has the cause."),
}
UNKNOWN_REASON = ("This file did not pass the checks.", "Check the file and upload it again. The technical log has the cause.")
# Only these details are written for people. An `error` detail can carry an exception's own text, so it stays in the technical log.
SHOWN_DETAILS = {"layout_changed", "missing_file", "shrink_guard", "validation_failed", "validation_warning", "unmapped_column",
                 "key_conflict_other_slice", "partial_month"}
TABLES = {"unilever_sku_demand_fact": "Sales per product", "inventory_fact": "Stock count"}

# The steps run_month prints (scripts/run_month.py plan_steps), in the order they run.
STAGES = (("load", "Load the files"), ("abc", "ABC classification"), ("forecast", "Forecast"), ("lp", "Order plan"), ("marts", "Dashboard tables"))
STAGE_NAMES = dict(STAGES)
_STEP = re.compile(r"^\[(load|abc|forecast|lp|marts)\] (.*)$")
_CONNECTION = re.compile(r"\b[a-z]+(?:\+[a-z0-9]+)?://\S+", re.I)
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:[\\/][^\s:;,'\"]+")
_UNIX_PATH = re.compile(r"(?<![\w.])/(?:[\w.\- ]+/)+([\w.\- ]+)")


def _count(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def plain_text(text: str | None, limit: int = 300) -> str:
    """A loader detail with anything internal taken out: connection strings go, and a path keeps only its file name."""
    out = _CONNECTION.sub("[hidden]", text or "")
    out = _WINDOWS_PATH.sub(lambda m: re.split(r"[\\/]", m.group(0))[-1], out)
    out = _UNIX_PATH.sub(lambda m: m.group(1), out)
    return out.strip()[:limit]


def _check(check_id: str, name: str, status: str, message: str, *, blocking: bool = True, action: str | None = None,
           action_id: str | None = None, details: list[dict] | None = None) -> dict:
    return {"id": check_id, "name": name, "status": status, "message": message, "action": action, "action_id": action_id,
            "blocking": blocking, "details": details or []}


def event_details(events: list[dict]) -> list[dict]:
    """The loader's findings for the expandable list: only what it recorded, and no row-level detail, which a dry run does not keep."""
    out = []
    for event in events:
        if event.get("status") not in ("refused", "warning"):
            continue
        reason = event.get("reason")
        message, action = REASONS.get(reason, UNKNOWN_REASON)
        slice_key = event.get("slice") or ""
        table = next((label for name, label in TABLES.items() if name in slice_key), None)
        files = event.get("files") or []
        if not files and slice_key.startswith("file:"):
            files = [slice_key[len("file:"):]]
        out.append({"file": ", ".join(files) or None, "table": table, "severity": "failed" if event["status"] == "refused" else "warning",
                    "reason": message, "action": action,
                    "detail": plain_text(event.get("detail")) if reason in SHOWN_DETAILS else None})
    return out


def validation_is_current(validation: dict | None, hashes: dict) -> bool:
    """The check on record is for exactly the files there now: another file, or a changed one, has not been checked."""
    return bool(validation) and validation.get("hashes") == hashes


def _file_checks(status: dict, files: dict, validation: dict | None, hashes: dict, job: dict) -> list[dict]:
    """Files valid, and file approved. Both pass with nothing to do when no file is waiting to load."""
    if status["checks"].get("abc_run") or not files:
        reason = "The files were loaded by the earlier run." if status["checks"].get("abc_run") and files else "No file is waiting to load."
        return [_check("files_valid", "Files valid", PASSED, reason), _check("file_approved", "File approved", PASSED, "No file needs approval.")]
    upload = "Upload the file again"
    validate = ("Run validation", "validate")
    if job.get("status") == "running" and job.get("kind") == "validate":
        return [_check("files_valid", "Files valid", NOT_CHECKED, "The files are being checked now."),
                _check("file_approved", "File approved", NOT_CHECKED, "Waiting for the file check.")]
    if not validation_is_current(validation, hashes):
        changed = bool(validation)
        return [_check("files_valid", "Files valid", NOT_CHECKED,
                       "A file changed after it was checked, so the check no longer counts." if changed else "The files have not been checked yet.",
                       action=validate[0], action_id=validate[1]),
                _check("file_approved", "File approved", NOT_CHECKED, "Waiting for the file check.")]
    report = validation.get("file_check")
    if not report or not report.get("completed"):
        return [_check("files_valid", "Files valid", FAILED, "The file check did not finish, so nothing can be said about the files.",
                       action=validate[0], action_id=validate[1]),
                _check("file_approved", "File approved", NOT_CHECKED, "Waiting for the file check.")]
    details = event_details(report.get("events") or [])
    refused = [d for d in details if d["severity"] == "failed"]
    if refused:
        return [_check("files_valid", "Files valid", FAILED, f"{_count(len(refused), 'problem stops', 'problems stop')} these files from loading.",
                       action=upload, action_id="upload", details=details),
                _check("file_approved", "File approved", NOT_CHECKED, "A file with problems cannot be approved.")]
    if details:
        valid = _check("files_valid", "Files valid", WARNING, f"The files can load, with {_count(len(details), 'thing', 'things')} to read first.",
                       blocking=False, details=details)
    else:
        valid = _check("files_valid", "Files valid", PASSED, "The checks found no problem with these files.")
    signoff = status.get("signoff") or {}
    if signoff.get("signed"):
        approved = _check("file_approved", "File approved", PASSED, f"Approved by {signoff.get('by') or 'a named person'}.")
    else:
        approved = _check("file_approved", "File approved", FAILED, "A person must approve this file before it can load.",
                          action="Approve the file", action_id="approve")
    return [valid, approved]


def _decisions_check(status: dict) -> dict:
    name = "Reorder decisions settled"
    decisions = status.get("decisions") or {}
    replay = status.get("replay")
    if status["checks"].get("lp_next"):
        return _check("decisions_settled", name, PASSED, "The next plan already exists, so this month's rows can no longer be decided.")
    # On the local setup the Reorder page's own database is the source of the decisions; the practice copy follows it.
    source = (replay or {}).get("pages") or decisions
    pending, requests = source.get("actionable_pending", 0), source.get("open_requests", 0)
    if pending or requests:
        parts = []
        if pending:
            parts.append(f"{_count(pending, 'recommendation awaits', 'recommendations await')} a decision")
        if requests:
            parts.append(f"{_count(requests, 'staff request awaits', 'staff requests await')} an admin")
        return _check("decisions_settled", name, FAILED, f"{' and '.join(parts)}.", action="Review Recommendations", action_id="review_recommendations")
    if replay:
        stuck = replay.get("mismatched", 0) + replay.get("missing", 0) + replay.get("only_in_practice", 0) + len(replay.get("refused") or [])
        if stuck:
            return _check("decisions_settled", name, FAILED,
                          f"{_count(stuck, 'decision', 'decisions')} could not be carried onto the practice copy because the rows no longer match.",
                          action="Have the practice copy re-made, then run validation again.")
        if replay.get("to_apply") or replay.get("to_reverse") or decisions.get("actionable_pending"):
            waiting = (replay.get("to_apply") or 0) + (replay.get("to_reverse") or 0)
            return _check("decisions_settled", name, NOT_CHECKED,
                          f"{_count(waiting, 'decision', 'decisions')} from the Reorder page not on the practice copy yet.",
                          action="Run validation", action_id="validate")
    elif decisions.get("actionable_pending"):
        return _check("decisions_settled", name, FAILED, f"{_count(decisions['actionable_pending'], 'recommendation awaits', 'recommendations await')} a decision.",
                      action="Review Recommendations", action_id="review_recommendations")
    left_out = source.get("zero_quantity_pending", 0) + source.get("historical_pending", 0)
    tail = f" {_count(left_out, 'other pending row orders', 'other pending rows order')} nothing or belong to older plans, and do not count." if left_out else ""
    return _check("decisions_settled", name, PASSED, f"Every recommendation that orders something has a decision.{tail}")


def can_resume(status: dict, job: dict) -> bool:
    """A plan run that stopped after writing the plan (the marts did not refresh) is finished by running it again."""
    return bool(status["checks"].get("lp_next")) and job.get("kind") == "plan" and job.get("status") == "failed" and job.get("month") == status.get("month")


def build_checks(status: dict, files: dict, validation: dict | None, hashes: dict, job: dict) -> list[dict]:
    checks, month, next_month = status["checks"], status["month"], status.get("next_month") or "the next month"
    codes = {item["code"]: item["message"] for item in status.get("preflight") or []}
    out = []

    if checks.get("sales_loaded"):
        out.append(_check("sales_available", "Sales available", PASSED, f"{month} sales are in the database."))
    elif "sales" in files:
        out.append(_check("sales_available", "Sales available", PASSED, f"The sales file {files['sales']['name']} is ready to load."))
    else:
        out.append(_check("sales_available", "Sales available", FAILED, f"There are no {month} sales yet.",
                          action="Upload the sales file", action_id="upload"))

    if "not_latest_month" in codes:
        out.append(_check("latest_month", "Latest processing month", FAILED,
                          f"Sales for {status.get('latest_sales_month')} are already loaded, so {month} is not the latest month."))
    else:
        out.append(_check("latest_month", "Latest processing month", PASSED, f"{month} is the latest month to process."))

    if status.get("cycle_state") == "closed":
        out.append(_check("not_already_run", "Monthly run not already completed", FAILED, f"{month} is already closed."))
    elif checks.get("lp_next") and not can_resume(status, job):
        out.append(_check("not_already_run", "Monthly run not already completed", FAILED,
                          f"The {next_month} plan already exists, so there is nothing to run. Review it and close the month.", action="Review the plan"))
    elif "already_ran" in codes:
        out.append(_check("not_already_run", "Monthly run not already completed", FAILED,
                          "The month has already started, so a new file would not reach the forecast or the plan."))
    elif checks.get("abc_run") or can_resume(status, job):
        out.append(_check("not_already_run", "Monthly run not already completed", PASSED, "An earlier run stopped partway. Finished steps will be skipped."))
    else:
        out.append(_check("not_already_run", "Monthly run not already completed", PASSED, "This month has not been run yet."))

    out.append(_decisions_check(status))
    out += _file_checks(status, files, validation, hashes, job)

    if job.get("status") == "running":
        out.append(_check("no_other_job", "No other job running", FAILED, "A batch step is running. Wait for it to finish."))
    else:
        out.append(_check("no_other_job", "No other job running", PASSED, "Nothing else is running."))

    if checks.get("count_loaded"):
        out.append(_check("stock_count", "Stock count present", PASSED, f"The {month} stock count is in the database.", blocking=False))
    elif "count" in files:
        out.append(_check("stock_count", "Stock count present", PASSED, f"The stock count file {files['count']['name']} is ready to load.", blocking=False))
    else:
        out.append(_check("stock_count", "Stock count present", WARNING,
                          f"There is no {month} stock count. The plan can start from projected stock, but the month cannot be closed until a count is loaded.",
                          blocking=False, action="Upload the stock count", action_id="upload"))

    if "synthetic_on_live" in codes:
        out.append(_check("generated_sales", "Generated sales present", FAILED, f"{status.get('synthetic_rows')} generated sales rows are on the live database."))
    elif "only_generated_sales" in codes:
        out.append(_check("generated_sales", "Generated sales present", FAILED,
                          f"{month} holds only generated sales rows, and this database leaves them out."))
    elif status.get("synthetic_rows"):
        out.append(_check("generated_sales", "Generated sales present", WARNING,
                          f"{status['synthetic_rows']:,} sales rows this month are generated practice data, so nothing here is a real result.", blocking=False))
    else:
        out.append(_check("generated_sales", "Generated sales present", PASSED, "No generated sales rows this month.", blocking=False))
    return out


def progress(status: dict) -> list[dict]:
    """The pipeline's own flags (close_cycle.CHECKS), as progress: not done yet is the normal state before a run, not a failure."""
    checks = status["checks"]
    return [{"id": key, "name": name, "done": bool(checks.get(key))} for key, name in (
        ("sales_loaded", "Sales loaded"), ("count_loaded", "Stock count loaded"), ("abc_run", "ABC run"),
        ("forecast_next", "Forecast written"), ("lp_next", "Plan written"))]


def workflow_state(status: dict, files: dict, validation: dict | None, hashes: dict, job: dict, checks: list[dict]) -> str:
    """Where the month stands, for the page's status label."""
    running = job.get("status") == "running"
    if running:
        return "validating" if job.get("kind") == "validate" else "processing"
    if status.get("cycle_state") == "closed":
        return "closed"
    if job.get("kind") == "plan" and job.get("month") == status.get("month"):
        if job.get("status") == "failed":
            return "failed"
        if job.get("status") == "done" and status["checks"].get("lp_next"):
            return "completed"
    if status["checks"].get("lp_next"):
        return "awaiting_review"
    if not (status["checks"].get("sales_loaded") or "sales" in files):
        return "not_uploaded"
    if not validation_is_current(validation, hashes):
        return "ready_for_validation"
    return "action_required" if any(c["blocking"] and c["status"] in (FAILED, NOT_CHECKED) for c in checks) else "ready_to_run"


def build_checklist(status: dict, files: dict, validation: dict | None, hashes: dict, job: dict) -> dict:
    checks = build_checks(status, files, validation, hashes, job)
    blockers = [c for c in checks if c["blocking"] and c["status"] in (FAILED, NOT_CHECKED)]
    state = workflow_state(status, files, validation, hashes, job, checks)
    decisions = status.get("decisions") or {}
    source = (status.get("replay") or {}).get("pages") or decisions
    return {
        "processing_month": status["month"],
        "next_month": status.get("next_month"),
        "status": "running" if job.get("status") == "running" else "blocked" if blockers else "ready",
        "workflow": state,
        "can_run": not blockers,
        "validated": validation_is_current(validation, hashes),
        "validated_at": (validation or {}).get("validated_at"),
        "summary": {key: sum(1 for c in checks if c["status"] == key) for key in (PASSED, FAILED, WARNING, NOT_CHECKED)},
        "checks": checks,
        "progress": progress(status),
        "decisions": {
            "cycle": decisions.get("cycle") or status["month"],
            "unresolved": source.get("actionable_pending", 0),
            "staff_requests": source.get("open_requests", 0),
            "open_quantity_changes": source.get("open_quantity_changes", 0),
            "open_dismissal_requests": source.get("open_dismissal_requests", 0),
            "zero_quantity": source.get("zero_quantity_pending", 0),
            "historical": source.get("historical_pending", 0),
            "decided": source.get("decided", 0),
        },
        "file_check": _file_summary(validation, hashes),
    }


# Months loaded onto the live system (backend/routers/monthly_batch.py, mode "live") are not closed and not counted, and a person does not approve a file by
# hand: the checks that belong to those steps are left out, and orders that wait for a decision are offered for acceptance as part of the run.
LOADED_MONTH_LEAVES_OUT = {"file_approved", "stock_count", "generated_sales"}


def for_loaded_month(checklist: dict) -> dict:
    """The checklist of a month that is loaded rather than closed. Waiting orders no longer block (the run accepts them when the person says so); a staff
    request still does, because nothing here can settle it."""
    decisions = checklist["decisions"]
    checks = []
    for check in checklist["checks"]:
        if check["id"] in LOADED_MONTH_LEAVES_OUT:
            continue
        if check["id"] == "decisions_settled" and check["status"] == FAILED and decisions["unresolved"] and not decisions["staff_requests"]:
            check = _check("decisions_settled", check["name"], WARNING,
                           f"{_count(decisions['unresolved'], 'order', 'orders')} of the {decisions['cycle']} plan {'has' if decisions['unresolved'] == 1 else 'have'} no decision yet. "
                           "Decide them on the Reorder page, or accept them at the recommended quantity when you run the month.",
                           blocking=False, action="Review Recommendations", action_id="review_recommendations")
        checks.append(check)
    blockers = [c for c in checks if c["blocking"] and c["status"] in (FAILED, NOT_CHECKED)]
    workflow = checklist["workflow"]
    if workflow == "action_required" and not blockers:
        workflow = "ready_to_run"
    elif workflow == "ready_to_run" and blockers:
        workflow = "action_required"
    return {**checklist, "checks": checks, "can_run": not blockers, "workflow": workflow,
            "status": "running" if checklist["status"] == "running" else "blocked" if blockers else "ready",
            "summary": {key: sum(1 for c in checks if c["status"] == key) for key in (PASSED, FAILED, WARNING, NOT_CHECKED)}}


def _file_summary(validation: dict | None, hashes: dict) -> dict | None:
    """What the approval dialog shows: the files and what loading them would do, from the loader's dry run."""
    report = (validation or {}).get("file_check")
    if not report or not validation_is_current(validation, hashes):
        return None
    return {"files": [entry["name"] for entry in hashes.values()], "checked_at": report.get("checked_at"),
            "slices": [{"table": next((label for name, label in TABLES.items() if name in (e.get("slice") or "")), e.get("slice")),
                        "status": e.get("status"), "rows_before": e.get("real_rows_before"), "rows_after": e.get("real_rows_after")}
                       for e in report.get("events") or []]}


def parse_steps(lines: list[str]) -> tuple[list[dict], str | None]:
    """The stages a job reached, from the lines run_month prints, and the one it stopped at. Never a percentage: nothing reports one."""
    seen: dict[str, str] = {}
    failed = None
    for line in lines:
        if line.startswith("REFUSED:"):
            failed = failed or "preflight"
            continue
        match = _STEP.match(line)
        if not match:
            continue
        stage, text = match.group(1), match.group(2)
        if text.startswith("running"):
            seen[stage] = "running"
        elif text.startswith("already done"):
            seen[stage] = "skipped"
        elif text.startswith(("exited", "did not")):
            seen[stage] = "stopped"
            failed = stage
    order = [name for name, _ in STAGES if name in seen]
    for name in order[:-1]:
        if seen[name] == "running":
            seen[name] = "done"
    return [{"stage": name, "label": STAGE_NAMES[name], "state": seen[name]} for name in order], failed


_FAILURES = {
    "preflight": ("Checks before the run", "The run stopped before changing anything, because a check did not pass.", "Run validation and resolve what it shows."),
    "load": ("Loading the files", "The files could not be loaded.", "Run validation to see what the files need, then run again."),
    "abc": ("ABC classification", "The classification step stopped.", "Run again: finished steps are skipped. If it repeats, keep the technical log."),
    "forecast": ("Forecast", "The forecast step stopped.", "Run again: finished steps are skipped. If it repeats, keep the technical log."),
    "lp": ("Order plan", "The order plan step stopped.", "Run again: finished steps are skipped. If it repeats, keep the technical log."),
    "marts": ("Dashboard tables", "The plan was written, but the dashboard tables did not refresh.", "Run again: finished steps are skipped."),
}
_UNKNOWN_FAILURE = ("Processing", "The run stopped before it finished.", "Run again: finished steps are skipped. If it repeats, keep the technical log.")
_OTHER_FAILURES = {
    "close": ("Closing the month", "The month could not be closed.", "Read the plan again, then retry. If it repeats, keep the technical log."),
    "practice": ("Generating practice sales", "The practice sales could not be generated.", "Try again. If it repeats, keep the technical log."),
}


def run_result(status: dict, job: dict) -> dict | None:
    """How the month's run ended, for the result banner. Complete only when the job exited 0 and the plan it should write exists:
    a started job is not a finished one, and a job that reports success with no plan has failed."""
    if job.get("month") != status.get("month") or job.get("kind") not in ("plan", "close", "practice"):
        return None
    base = {"month": status["month"], "kind": job["kind"], "started_at": job.get("started_at"), "finished_at": job.get("finished_at"), "job_id": job.get("id")}
    if job.get("status") == "running":
        return {**base, "state": "processing"}
    if job["kind"] != "plan":
        if job.get("status") != "failed":
            return None
        stage, message, action = _OTHER_FAILURES[job["kind"]]
        return {**base, "state": "failed", "failed_stage": stage, "message": message, "action": action}
    plan = status.get("next_plan") or {}
    if job.get("status") == "done" and job.get("exit_code") == 0 and status["checks"].get("lp_next") and plan.get("rows"):
        return {**base, "state": "completed", "run_id": plan.get("run_key"), "plan_rows": plan.get("rows")}
    if job.get("status") in ("done", "failed"):
        stage, message, action = _FAILURES.get(job.get("failed_stage"), _UNKNOWN_FAILURE)
        return {**base, "state": "failed", "failed_stage": stage, "message": message, "action": action}
    return None
