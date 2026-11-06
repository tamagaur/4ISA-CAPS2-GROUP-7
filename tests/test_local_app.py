"""scripts/local_app.py: the local sign-in shortcut must not be able to work anywhere but the throwaway database."""
from __future__ import annotations

import jwt
import pytest

from scripts import local_app as la


@pytest.mark.parametrize("url", ["postgresql://u:p@aws-0.pooler.supabase.com:6543/postgres",
                                 "postgresql://postgres@127.0.0.1:5432/ssm_local", ""])
def test_it_refuses_anything_but_the_throwaway_database(url):
    with pytest.raises(SystemExit):
        la.require_throwaway(url)


def test_it_accepts_the_throwaway_database():
    assert la.require_throwaway("postgresql://postgres@127.0.0.1:55432/ssm_local") is None


def test_each_run_signs_with_its_own_secret():
    assert la.new_secret() != la.new_secret()


def test_the_child_environment_never_keeps_the_live_url_or_secret():
    env = la.child_env({"SUPABASE_DB_URL": "live", "SUPABASE_DIRECT_URL": "live", "JWT_SECRET_KEY": "live-secret", "PATH": "p"},
                       "postgresql://postgres@127.0.0.1:55432/ssm_local", "local-secret")
    assert env["SUPABASE_DB_URL"] == env["SUPABASE_DIRECT_URL"] == "postgresql://postgres@127.0.0.1:55432/ssm_local"
    assert env["JWT_SECRET_KEY"] == "local-secret" and env["MONTHLY_BATCH_ENABLED"] == "true" and env["PATH"] == "p"


def test_a_reset_clears_files_left_in_the_slots(monkeypatch, tmp_path):
    (tmp_path / "2026-03" / "count").mkdir(parents=True)
    (tmp_path / "2026-03" / "count" / "SSIS MARCH 2026.xlsx").write_bytes(b"x")
    monkeypatch.setattr(la, "UPLOADS", tmp_path)
    monkeypatch.setattr(la.subprocess, "run", lambda *a, **k: None)
    la.reset("backup", {})
    assert not tmp_path.exists()


def test_the_uploads_folder_is_the_one_the_panel_writes():
    from backend.routers import monthly_batch as mb
    assert la.UPLOADS == mb.UPLOADS


def test_the_pages_read_the_practice_copy_on_the_throwaway_server():
    assert la.practice_url(la.LOCAL_URL) == "postgresql://postgres@127.0.0.1:55432/ssm_practice"
    la.require_throwaway(la.practice_url(la.LOCAL_URL))


def test_a_token_from_this_run_fails_against_any_other_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "local-secret-long-enough-for-hs256-signing")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    token = la.mint_token(1, "a@b.c", "admin", "A", "sid")
    assert jwt.decode(token, "local-secret-long-enough-for-hs256-signing", algorithms=["HS256"])["sub"] == "1"
    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(token, "the-live-secret-is-something-else-entirely", algorithms=["HS256"])


def test_the_browser_snippet_sets_the_two_keys_the_frontend_reads():
    text = la.browser_snippet("TOKEN", "admin")
    assert "dsd_access_token" in text and "TOKEN" in text and "dsd_role" in text
