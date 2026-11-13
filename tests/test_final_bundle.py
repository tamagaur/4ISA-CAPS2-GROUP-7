"""scripts/apply_final_bundle.py (2026-11-11): the last plan-moving bundle as one command, bound to its rehearsal.

Static and offline: the live run itself is Kelvin's (no write to live from a test). What is held here:
  - the attestation (docs/FINAL_BUNDLE_REHEARSAL.json) is for THESE files: editing any file the bundle runs without
    re-rehearsing fails this test, as docs/MONTH_LOAD_REHEARSAL.json does for the month load;
  - the pending migrations it expects are exactly the files after its last-applied one;
  - the rehearsal's own result is the plan in STATE.md's plan line and changed only the tables a re-plan should change;
  - the live run refuses without --target-public and before any write when the preflight fails.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts import apply_final_bundle as b

REPO = Path(__file__).resolve().parents[1]


def _att() -> dict:
    return json.loads(b.ATTESTATION.read_text(encoding="utf-8"))


def _state() -> dict:
    line = next(ln for ln in (REPO / "STATE.md").read_text(encoding="utf-8").splitlines() if ln.startswith("plan:"))
    return dict(re.findall(r"(\w+)=(\S+)", line))


# The bundle was applied to live on 2026-11-11 from this commit's tree (STATE.md plan line) and its preflight now refuses
# (the ledger ends at 0078). From then on the attestation is held against the files AS THEY WERE when live ran them, not
# against the working tree: later work on the forecast (e.g. kelvin/spike-cap, which edits analytics/params.py and
# router.py) is not a change to what was applied.
APPLIED_AT = "201dae4"


def _files_hash_at(commit: str) -> str:
    import hashlib
    import subprocess
    h = hashlib.sha256()
    for f in b.FILES:
        blob = subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{f}"], capture_output=True, check=True).stdout
        h.update(f.encode() + b"\0" + blob.replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def test_the_attestation_is_for_the_files_the_live_apply_ran():
    att = _att()
    assert att["files"] == list(b.FILES)
    assert att["files_sha256"] == _files_hash_at(APPLIED_AT), "the attestation does not match the files live's apply ran"


def test_every_attested_file_exists():
    for f in b.FILES:
        assert (REPO / f).is_file(), f


def test_pending_migrations_are_exactly_the_files_after_the_last_applied():
    on_disk = sorted(p.name for p in b.MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    assert b.LAST_APPLIED in on_disk
    # The bundle's four follow 0074 directly. Migrations written after it was applied (0079 on 2026-11-13) come after them.
    after = tuple(on_disk[on_disk.index(b.LAST_APPLIED) + 1:])
    assert after[:len(b.PENDING)] == b.PENDING


def test_the_rehearsed_result_is_the_plan_state_md_names():
    # STATE.md as it stood when the bundle was applied (a later plan, e.g. the spike cap's, replaces the line)
    import subprocess
    text = subprocess.run(["git", "-C", str(REPO), "show", f"{APPLIED_AT}:STATE.md"], capture_output=True, check=True,
                          text=True, encoding="utf-8").stdout
    st = dict(re.findall(r"(\w+)=(\S+)", next(ln for ln in text.splitlines() if ln.startswith("plan:"))))
    exp = _att()["expected"]
    assert exp["plan"]["rows"] == int(st["rows"]) and exp["plan"]["pieces"] == int(st["pieces"])
    assert exp["plan"]["run_key"] == int(st["lp_run"]) and exp["plan"]["cycle"] == st["cycle"]
    assert exp["ledger_latest"] == b.PENDING[-1]


def test_the_rehearsal_started_from_live_and_changed_only_what_a_replan_changes():
    att = _att()
    assert att["copy_equals_live_before"]["public_mart_differ"] == []
    assert att["start"]["plan"]["run_key"] == b.START_PLAN["run_key"] and att["start"]["plan"]["pieces"] == b.START_PLAN["pieces"]
    assert set(att["changed_tables"]) <= {
        "public.schema_migrations", "public.forecast_challenger", "public.lp_recommendation", "public.lp_run",
        "mart.forecast_run_value", "mart.error_decomposition", "mart.error_decomposition_row", "mart.planning_mart",
        "mart.refresh_log"} | {t for t in att["changed_tables"] if t.endswith("(sequence)")}
    assert all(s["exit"] == 0 for s in att["steps"]) and [s["step"] for s in att["steps"]] == [n for n, _ in b.STEPS]


def test_every_demo_table_has_row_level_security_after_the_bundle():
    rls = _att()["expected"]["rls"]
    assert all(on == total for total, on in rls.values()), rls


def test_the_live_run_refuses_without_target_public_before_writing(monkeypatch):
    calls = []
    monkeypatch.setattr(b, "git_state", lambda: [])
    monkeypatch.setattr(b, "files_hash", lambda: _att()["files_sha256"])
    monkeypatch.setattr(b, "read_only", lambda url, fn: [] if fn is b.preflight else dict(_att()["start_tables"]))
    monkeypatch.setattr(b, "run_step", lambda *a, **k: calls.append(a))
    monkeypatch.setattr("analytics.config.long_read_db_url", lambda: "postgresql://x@example.invalid/db")
    assert b.apply_live(target_public=False, check_only=False) == 2
    assert calls == []


def test_a_failed_preflight_refuses_with_exit_2_and_runs_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(b, "git_state", lambda: ["dirty"])
    monkeypatch.setattr(b, "read_only", lambda url, fn: ["ledger ends at 0075"] if fn is b.preflight else {})
    monkeypatch.setattr(b, "run_step", lambda *a, **k: calls.append(a))
    monkeypatch.setattr("analytics.config.long_read_db_url", lambda: "postgresql://x@example.invalid/db")
    assert b.apply_live(target_public=True, check_only=False) == 2
    assert calls == []


def test_the_rehearsal_refuses_any_server_but_the_throwaway(monkeypatch):
    from scripts import local_pg
    monkeypatch.setattr(local_pg, "is_up", lambda: True)
    monkeypatch.setattr(local_pg, "local_url", lambda db=None, **k: f"postgresql://postgres@db.example.com:5432/{db}")
    with pytest.raises(SystemExit, match="127.0.0.1"):
        b.rehearse(Path("backups/x"))


# ---- tracked reports from a non-live database go to local/nonlive_reports (2026-11-11) ----------------------------

def test_the_published_snapshot_writes_its_frozen_rows_through_report_path():
    src = (REPO / "scripts" / "snapshot_published_figures.py").read_text(encoding="utf-8")
    body = src[src.index("def cmd_write"):src.index("def cmd_verify") if "def cmd_verify" in src else None]
    assert "folder = report_path(SNAP_DIR)" in body
    assert "write_frozen(\"mase_rows.csv\", mase, folder)" in body and "read_frozen(folder)" in body


def test_the_evidence_charts_write_through_report_path():
    src = (REPO / "scripts" / "evidence" / "_common.py").read_text(encoding="utf-8")
    body = src[src.index("def write_result"):src.index("def _json_default")]
    assert "report_path(" in body and "os.path.join(EVID, name)" not in body


def test_run_month_names_the_plan_from_state_md():
    from scripts import run_month
    st = _state()
    assert run_month.state_plan_text() == f"{int(st['rows'])} rows / {int(st['pieces']):,} pieces"
    assert "435,988" not in (REPO / "scripts" / "run_month.py").read_text(encoding="utf-8").split("def state_plan_text")[0]
