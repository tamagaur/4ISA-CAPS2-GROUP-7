"""A panel Run with uploaded files: the system signs, on the practice copy and nowhere else, one read, and the record says what happened."""
from __future__ import annotations

import json

from scripts import load_slices, practice_signed_load as psl

ARGS = ["--pressed-by", "kelvin@x", "--", "-m", "scripts.run_month", "--month", "2026-03", "--slice", "unilever:inventory_fact:2026-03", "--file", "local/x.xlsx"]
MANIFEST_LINE = "[manifest] run key KEY: 41 staged sheet(s), fingerprint sha256:abc\n"


def test_it_refuses_any_database_but_the_practice_copy(monkeypatch):
    monkeypatch.setattr(psl, "on_practice_copy", lambda: False)
    monkeypatch.setattr(psl, "tee", lambda cmd: (_ for _ in ()).throw(AssertionError("nothing may run")))
    assert psl.main(ARGS) == 2


def _record(monkeypatch, tmp_path, rc=0, signed=True):
    monkeypatch.setattr(psl, "REPO", tmp_path)
    monkeypatch.setattr(psl, "on_practice_copy", lambda: True)
    folder = tmp_path / "transform" / "slices" / "KEY"
    folder.mkdir(parents=True)
    calls = []

    def tee(cmd):
        calls.append(cmd)
        if signed:
            (folder / "_signoff.json").write_text(json.dumps({"decided_by": psl.SYSTEM_SIGNER, "manifest_fingerprint": "sha256:abc"}))
        return rc, MANIFEST_LINE

    monkeypatch.setattr(psl, "tee", tee)
    return calls, folder


def test_there_is_one_run_no_dry_run_and_it_carries_the_flag(monkeypatch, tmp_path):
    calls, _ = _record(monkeypatch, tmp_path)
    assert psl.main(ARGS) == 0
    assert len(calls) == 1 and "--dry-run" not in calls[0]
    assert calls[0][1:3] == ["-m", "scripts.run_month"] and calls[0][-1] == psl.AUTO_FLAG


def test_the_gate_cannot_find_it_afterwards_and_the_record_says_what_happened(monkeypatch, tmp_path):
    _, folder = _record(monkeypatch, tmp_path)
    psl.main(ARGS)
    assert not (folder / "_signoff.json").exists()
    head = (folder / psl.KEPT_RECORD).read_text()
    assert psl.PRACTICE_MARKER in head[:400]
    record = json.loads(head)
    assert record["decided_by"] == psl.SYSTEM_SIGNER and record["run_pressed_by"] == "kelvin@x"
    assert "no person reviewed" in record["_what_happened"]


def test_a_failed_load_still_moves_the_sign_off_and_returns_its_code(monkeypatch, tmp_path):
    _, folder = _record(monkeypatch, tmp_path, rc=3)
    assert psl.main(ARGS) == 3
    assert not (folder / "_signoff.json").exists() and (folder / psl.KEPT_RECORD).exists()


def test_the_signer_is_never_a_person_and_says_what_it_is():
    assert psl.SYSTEM_SIGNER.startswith("system:") and "practice copy" in psl.SYSTEM_SIGNER and "no review" in psl.SYSTEM_SIGNER


def test_the_loader_refuses_the_flag_off_the_copy_before_it_touches_anything(monkeypatch):
    monkeypatch.setattr(psl, "on_practice_copy", lambda: False)
    try:
        load_slices.practice_auto_sign_allowed(True)
    except SystemExit as stop:
        assert "practice copy" in str(stop)
    else:
        raise AssertionError("the flag was accepted off the copy")
    assert load_slices.practice_auto_sign_allowed(False) is False


def test_the_run_key_is_read_from_the_loaders_own_line():
    assert psl.run_key_of("x\n[manifest] run key abc_123: 41 staged sheet(s), fingerprint sha256:f\n") == "abc_123"
    assert psl.run_key_of("nothing here") is None
