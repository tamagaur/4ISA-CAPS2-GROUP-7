"""scripts/apply_calendar_grain.py (2026-11-12): the calendar factor at product grain put live as one command, bound to its rehearsal.

Static and offline (the live run is Kelvin's). Held here: the attestation is for THESE files; its result is the plan STATE.md
names; the rehearsal started from live and changed only what the steps write; the live run refuses before any write without
--target-public or when the preflight fails; the rehearsal refuses any server but the throwaway one."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from analytics import params
from scripts import apply_calendar_grain as s

REPO = Path(__file__).resolve().parents[1]


def _att() -> dict:
    return json.loads(s.ATTESTATION.read_text(encoding="utf-8"))


def _state() -> dict:
    line = next(ln for ln in (REPO / "STATE.md").read_text(encoding="utf-8").splitlines() if ln.startswith("plan:"))
    return dict(re.findall(r"(\w+)=(\S+)", line))


def test_the_switches_it_applies_are_on():
    assert params.CALENDAR_GRAIN == "product" and params.DECEMBER_DIP_RULE is True


# Applied to live on 2026-11-13 from this commit's tree (STATE.md); its preflight now refuses (lp_run 10 is the newest plan and the
# product-calendar runs are stored). From then on the attestation is held against the files AS THEY WERE when live ran them, not
# against the working tree: later edits to an attested file (e.g. scripts/backtest_forecast_run.py's run-7 note) change nothing
# that was applied.
APPLIED_AT = "163b42f"


def _files_hash_at(commit: str) -> str:
    import hashlib
    import subprocess
    h = hashlib.sha256()
    for f in s.FILES:
        blob = subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{f}"], capture_output=True, check=True).stdout
        h.update(f.encode() + b"\0" + blob.replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def test_the_attestation_is_for_the_files_the_live_apply_ran():
    att = _att()
    assert att["files"] == list(s.FILES)
    assert att["files_sha256"] == _files_hash_at(APPLIED_AT), "the attestation does not match the files live's apply ran"


def test_the_rehearsed_result_is_the_plan_state_md_names():
    exp, st = _att()["expected"], _state()
    assert exp["plan"]["rows"] == int(st["rows"]) and exp["plan"]["pieces"] == int(st["pieces"])
    assert exp["plan"]["run_key"] == int(st["lp_run"]) and exp["plan"]["cycle"] == st["cycle"]


def test_the_rehearsal_started_from_live_and_changed_only_what_its_steps_write():
    att = _att()
    assert att["copy_equals_live_before"]["public_mart_differ"] == []
    assert {k: att["start"]["plan"][k] for k in s.START_PLAN} == s.START_PLAN
    assert set(att["changed_tables"]) <= {
        "public.forecast_result", "public.review_flag", "public.lp_recommendation", "public.lp_run", "mart.forecast_run", "mart.forecast_run_value",
        "mart.accuracy_mart", "mart.error_decomposition", "mart.error_decomposition_row", "mart.planning_mart",
        "mart.refresh_log", "mart.flow_month", "mart.idle_stock", "mart.sales_mart", "mart.sales_month", "mart.inventory_mart",
        "mart.inventory_count"} | {t for t in att["changed_tables"] if t.endswith("(sequence)")}
    assert [x["step"] for x in att["steps"]] == [n for n, _ in s.STEPS] and all(x["exit"] == 0 for x in att["steps"])
    for k in s.UNCHANGED_KEYS:
        assert att["start"][k] == att["expected"][k], k
    # the marts may be served after it: the review flags were re-scored on the new forecast (planning_stale false)
    assert att["expected"]["refresh_status"] == {"planning_stale": False, "stale": False}
    labels = [r[0] for r in att["expected"]["grain_runs"]]
    assert len(labels) == 4 and all(", product calendar" in lab for lab in labels)


def test_the_card_default_is_a_run_the_apply_writes():
    from backend.marts import DEFAULT_BACKTEST_LABEL
    assert DEFAULT_BACKTEST_LABEL in [r[0] for r in _att()["expected"]["grain_runs"]]


def test_the_live_run_refuses_without_target_public_before_writing(monkeypatch):
    calls = []
    monkeypatch.setattr(s.fb, "git_state", lambda: [])
    monkeypatch.setattr(s, "files_hash", lambda: _att()["files_sha256"])
    monkeypatch.setattr(s.fb, "read_only", lambda url, fn: [] if fn is s.preflight else dict(_att()["start_tables"]))
    monkeypatch.setattr(s, "run_step", lambda *a, **k: calls.append(a))
    monkeypatch.setattr("analytics.config.long_read_db_url", lambda: "postgresql://x@example.invalid/db")
    assert s.apply_live(target_public=False, check_only=False) == 2
    assert calls == []


def test_a_failed_preflight_refuses_with_exit_2_and_runs_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(s.fb, "git_state", lambda: ["dirty"])
    monkeypatch.setattr(s.fb, "read_only", lambda url, fn: ["newest plan is lp_run 10"] if fn is s.preflight else {})
    monkeypatch.setattr(s, "run_step", lambda *a, **k: calls.append(a))
    monkeypatch.setattr("analytics.config.long_read_db_url", lambda: "postgresql://x@example.invalid/db")
    assert s.apply_live(target_public=True, check_only=False) == 2
    assert calls == []


def test_the_rehearsal_refuses_any_server_but_the_throwaway(monkeypatch):
    from scripts import local_pg
    monkeypatch.setattr(local_pg, "is_up", lambda: True)
    monkeypatch.setattr(local_pg, "local_url", lambda db=None, **k: f"postgresql://postgres@db.example.com:5432/{db}")
    with pytest.raises(SystemExit, match="127.0.0.1"):
        s.rehearse(Path("backups/x"))
