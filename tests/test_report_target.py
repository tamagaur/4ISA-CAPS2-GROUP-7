"""A run against a non-live database must not overwrite a tracked report (scripts/report_target.py)."""
from pathlib import Path

from scripts import report_target as rt


def test_local_database_redirects_to_git_ignored_local(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/ssm_local")
    tracked = rt.REPO / "reports" / "BASELINE_FORECAST_RUN.md"
    out = rt.report_path(tracked)
    assert out == rt.NONLIVE_DIR / "reports" / "BASELINE_FORECAST_RUN.md"
    assert rt.REPO / "local" in out.parents


def test_live_database_keeps_the_tracked_path(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@db.example.supabase.co:5432/postgres")
    tracked = rt.REPO / "docs" / "ACCURACY_AS_SERVED.md"
    assert rt.report_path(tracked) == tracked


def test_path_outside_repo_is_left_alone(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@localhost:55432/ssm_local")
    assert rt.report_path(tmp_path / "x.csv") == Path(tmp_path / "x.csv").resolve()
