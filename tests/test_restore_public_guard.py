"""--restore of a backup whose target is public needs a second confirmation, and is refused before any connection
is opened (scripts/apply_real_recovery_to_public.py main()). The destructive one-off scripts are gone."""
import json
import sys
from pathlib import Path

import pytest

from scripts import apply_real_recovery_to_public as rec

REPO = Path(__file__).resolve().parent.parent


class Connected(Exception):
    pass


@pytest.fixture
def backup(tmp_path, monkeypatch):
    d = tmp_path / "real_recovery_20261021T000000Z"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"target": "public", "tables": {}}), encoding="utf-8")

    def no_connect():
        raise Connected

    monkeypatch.setattr(rec, "connect", no_connect)
    return d


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["apply_real_recovery_to_public", *argv])
    return rec.main()


def test_restore_of_public_refused_without_second_confirmation(backup, monkeypatch):
    with pytest.raises(SystemExit) as e:
        run(monkeypatch, "--restore", str(backup), "--i-have-approval")
    assert "refusing" in str(e.value)  # SystemExit(message), and connect() was never reached


def test_restore_of_public_refused_with_wrong_confirmation(backup, monkeypatch):
    with pytest.raises(SystemExit):
        run(monkeypatch, "--restore", str(backup), "--i-have-approval", "--confirm-restore-public", "other")


def test_restore_of_public_proceeds_with_the_backup_name(backup, monkeypatch):
    with pytest.raises(Connected):
        run(monkeypatch, "--restore", str(backup), "--i-have-approval", "--confirm-restore-public", backup.name)


def test_restore_of_a_scratch_backup_needs_no_second_confirmation(backup, monkeypatch):
    (backup / "manifest.json").write_text(json.dumps({"target": "ssm_recovery_rehearsal", "tables": {}}), encoding="utf-8")
    with pytest.raises(Connected):
        run(monkeypatch, "--restore", str(backup))


def test_destructive_one_off_scripts_are_gone():
    assert not (REPO / "scripts" / "delete_future_months.py").exists()
    assert not (REPO / "scripts" / "map_dm_sales_to_skus.py").exists()
    assert (REPO / "scripts" / "archive" / "map_dm_sales_to_skus.py").exists()
