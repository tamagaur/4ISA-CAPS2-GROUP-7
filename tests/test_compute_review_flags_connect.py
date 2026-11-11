"""scripts.compute_review_flags.connect reads SUPABASE_DB_URL only: a local run cannot fall through to live (2026-11-10)."""
from __future__ import annotations

import pytest

import scripts.compute_review_flags as crf


def test_connects_to_supabase_db_url_even_when_others_are_set(monkeypatch):
    seen = []
    monkeypatch.setattr(crf, "load_dotenv", lambda **k: None)
    monkeypatch.setattr(crf.psycopg2, "connect", lambda url: seen.append(url) or "conn")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/local_copy")
    monkeypatch.setenv("SUPABASE_DIRECT_URL", "postgresql://live-direct")
    monkeypatch.setenv("DATABASE_URL", "postgresql://live-other")
    assert crf.connect() == "conn"
    assert seen == ["postgresql://postgres@127.0.0.1:55432/local_copy"]


def test_a_failed_connection_stops_instead_of_trying_another_database(monkeypatch):
    seen = []

    def fail(url):
        seen.append(url)
        raise crf.psycopg2.OperationalError("refused")

    monkeypatch.setattr(crf, "load_dotenv", lambda **k: None)
    monkeypatch.setattr(crf.psycopg2, "connect", fail)
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/local_copy")
    monkeypatch.setenv("SUPABASE_DIRECT_URL", "postgresql://live-direct")
    with pytest.raises(crf.psycopg2.OperationalError):
        crf.connect()
    assert seen == ["postgresql://postgres@127.0.0.1:55432/local_copy"]


def test_no_url_stops(monkeypatch):
    monkeypatch.setattr(crf, "load_dotenv", lambda **k: None)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setenv("SUPABASE_DIRECT_URL", "postgresql://live-direct")
    with pytest.raises(SystemExit):
        crf.connect()
