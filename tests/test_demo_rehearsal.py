"""scripts/demo_rehearsal.py: the attestation counts only for the code it ran, only when every step was exact, only when made on a restored copy."""
from __future__ import annotations

import json

from scripts import demo_rehearsal as dr

STEPS = {name: {"exact": True} for name in dr.STEPS}


def test_the_record_counts_only_for_the_code_it_ran(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "PROOF", tmp_path / "rehearsal.json")
    assert dr.ok()[0] is False and "no rehearsal" in dr.ok()[1]
    dr.write("127.0.0.1/ssm_rehearsal", STEPS, (109, 435988), "full_backup_x")
    assert dr.ok() == (True, "")
    monkeypatch.setattr(dr, "code_hash", lambda: "a different file set")      # any edit to the files that make the load and rollback changes the hash
    passed, why = dr.ok()
    assert passed is False and "rehearse it again" in why


def test_a_record_not_passed_or_made_off_a_restored_copy_or_missing_a_step_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "rehearsal.json"
    monkeypatch.setattr(dr, "PROOF", path)
    good = {"passed": True, "code_hash": dr.code_hash(), "target": "127.0.0.1/ssm_rehearsal", "steps": STEPS}
    inexact = {**STEPS, dr.STEPS[-1]: {"exact": False}}
    missing = {k: v for k, v in STEPS.items() if k != dr.STEPS[0]}
    for change, fragment in (({"passed": False}, "did not pass"), ({"target": "aws-0.pooler.supabase.com/postgres"}, "not made on a restored copy"),
                             ({"steps": inexact}, "every step exact"), ({"steps": missing}, "every step exact")):
        path.write_text(json.dumps({**good, **change}))
        assert dr.ok()[0] is False and fragment in dr.ok()[1]
    path.write_text(json.dumps(good))
    assert dr.ok()[0] is True


def test_every_file_the_hash_covers_exists():
    for name in dr.FILES:
        assert (dr.REPO / name).is_file(), name


def test_the_steps_are_the_ones_the_driver_runs():
    import re
    from pathlib import Path
    src = Path(dr.REPO / "scripts" / "month_load_rehearsal.py").read_text(encoding="utf-8")
    for name in dr.STEPS:
        assert re.search(rf'"{name}"', src), name
