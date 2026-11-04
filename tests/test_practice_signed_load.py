"""A panel Run with uploaded files signs its manifest on the practice copy and nowhere else, and leaves no sign-off behind."""
from __future__ import annotations

from scripts import practice_signed_load as psl

ARGS = ["--approved-by", "kelvin@x", "--slice", "unilever:inventory_fact:2026-03", "--file", "local/x.xlsx",
        "--", "-m", "scripts.run_month", "--month", "2026-03"]


def test_it_refuses_any_database_but_the_practice_copy(monkeypatch):
    monkeypatch.setattr(psl, "on_practice_copy", lambda: False)
    monkeypatch.setattr(psl, "tee", lambda cmd: (_ for _ in ()).throw(AssertionError("nothing may run")))
    assert psl.main(ARGS) == 2


def _record(monkeypatch, tmp_path, dry_rc=0, month_rc=0):
    monkeypatch.setattr(psl, "REPO", tmp_path)
    monkeypatch.setattr(psl, "on_practice_copy", lambda: True)
    folder = tmp_path / "transform" / "slices" / "KEY"
    folder.mkdir(parents=True)
    calls = []

    def tee(cmd):
        calls.append(cmd)
        if "scripts.run_canonical_load" in cmd:
            return dry_rc, "[manifest] run key KEY: 41 staged sheet(s), fingerprint sha256:abc\n"
        if "analytics.etl.transform_signoff" in cmd:
            (folder / "_signoff.json").write_text("{}")
            return 0, ""
        assert (folder / "_signoff.json").exists()     # signed before the load
        return month_rc, ""

    monkeypatch.setattr(psl, "tee", tee)
    return calls, folder


def test_order_is_dry_run_sign_load_and_the_sign_off_is_gone_after(monkeypatch, tmp_path):
    calls, folder = _record(monkeypatch, tmp_path)
    assert psl.main(ARGS) == 0
    assert "--dry-run" in calls[0] and "--target-public" in calls[0] and "local/x.xlsx" in calls[0]
    sign = calls[1]
    assert sign[sign.index("--by") + 1] == "kelvin@x" and "Not a review" in sign[sign.index("--notes") + 1]
    assert calls[2][1:3] == ["-m", "scripts.run_month"]
    assert not (folder / "_signoff.json").exists()


def test_a_failed_load_still_removes_the_sign_off_and_returns_its_code(monkeypatch, tmp_path):
    _, folder = _record(monkeypatch, tmp_path, month_rc=3)
    assert psl.main(ARGS) == 3
    assert not (folder / "_signoff.json").exists()


def test_a_refused_dry_run_signs_nothing(monkeypatch, tmp_path):
    calls, folder = _record(monkeypatch, tmp_path, dry_rc=1)
    assert psl.main(ARGS) == 1
    assert len(calls) == 1 and not (folder / "_signoff.json").exists()


def test_the_run_key_is_read_from_the_loaders_own_line():
    assert psl.run_key_of("x\n[manifest] run key abc_123: 41 staged sheet(s), fingerprint sha256:f\n") == "abc_123"
    assert psl.run_key_of("nothing here") is None
