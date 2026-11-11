"""analytics.config.long_read_db_url: SUPABASE_DIRECT_URL only as another route to the database SUPABASE_DB_URL names.
Until 2026-11-11 it always won when set, so a process told SUPABASE_DB_URL=<a local copy> read live (.env's direct URL)."""
from __future__ import annotations

import pytest

import analytics.config as cfg

LIVE_POOLER = "postgresql://postgres.ref:pw@aws-0-x.pooler.supabase.com:6543/postgres"
LIVE_SESSION = "postgresql://postgres.ref:pw@aws-0-x.pooler.supabase.com:5432/postgres"
LOCAL = "postgresql://postgres@127.0.0.1:55432/ssm_challenger"


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    monkeypatch.setattr(cfg, "_load_env_file", lambda *a, **k: None)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def test_direct_url_is_used_for_the_same_database(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", LIVE_POOLER)
    monkeypatch.setenv("SUPABASE_DIRECT_URL", LIVE_SESSION)
    assert cfg.long_read_db_url() == LIVE_SESSION


def test_a_local_copy_is_never_replaced_by_the_live_direct_url(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    monkeypatch.setenv("SUPABASE_DIRECT_URL", LIVE_SESSION)
    assert cfg.long_read_db_url() == LOCAL
    assert "different database" in capsys.readouterr().err


def test_no_direct_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL)
    monkeypatch.delenv("SUPABASE_DIRECT_URL", raising=False)
    assert cfg.long_read_db_url() == LOCAL


def test_missing_db_url_fails_even_with_a_direct_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setenv("SUPABASE_KEY", "k")
    monkeypatch.setenv("SUPABASE_DIRECT_URL", LIVE_SESSION)
    with pytest.raises(cfg.MissingConfigError):
        cfg.long_read_db_url()


@pytest.mark.parametrize("a,b,same", [
    (LIVE_POOLER, LIVE_SESSION, True),
    (LIVE_POOLER, LOCAL, False),
    ("postgresql://u@h:5432/a", "postgresql://u@h:5432/b", False),
    ("postgresql://u@h:5432/a", "postgresql://v@h:5432/a", False),
])
def test_same_database(a, b, same):
    assert cfg.same_database(a, b) is same
