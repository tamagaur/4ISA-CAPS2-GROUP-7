"""scripts/check_helpers.py env names every missing variable and fails (KNOWN_ISSUES B2: the fix had no test)."""
from __future__ import annotations

import sys
import types

import scripts.check_helpers as ch


def _no_dotenv(monkeypatch):
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))


def test_missing_variables_are_named_and_fail(monkeypatch, capsys):
    _no_dotenv(monkeypatch)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    assert ch.cmd_env() == 1
    out = capsys.readouterr().out
    assert "SUPABASE_DB_URL" in out and "SUPABASE_KEY" in out and out.startswith("FAIL")


def test_a_placeholder_value_counts_as_missing(monkeypatch, capsys):
    _no_dotenv(monkeypatch)
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://<user>:<password>@host/db")
    monkeypatch.setenv("SUPABASE_KEY", "k")
    assert ch.cmd_env() == 1
    assert "SUPABASE_DB_URL" in capsys.readouterr().out


def test_an_unreachable_database_fails_instead_of_passing(monkeypatch, capsys):
    _no_dotenv(monkeypatch)
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u@127.0.0.1:1/none")
    monkeypatch.setenv("SUPABASE_KEY", "k")

    def refuse(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=refuse))
    assert ch.cmd_env(full=True) == 1
    assert "not reachable" in capsys.readouterr().out


def test_jwt_secret_is_not_required_any_more(monkeypatch):
    assert "JWT_SECRET_KEY" not in ch.REQUIRED + ch.REQUIRED_FULL
