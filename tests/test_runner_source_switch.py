"""Guard: --principal / --source on run_baseline_forecast and run_lp (2026-10-15).

With --source omitted both runners take exactly the path they always took: the real Unilever run, reading the _Real
views and, with --write, writing Forecast_Result / lp_run / lp_recommendation. The demonstration path is reachable
only by asking for it, never writes those tables, and run_lp refuses it. The live counterpart of this test is
scripts/verify_demo_isolation.py: forecast_result, lp_run, lp_recommendation and mart.accuracy_mart row counts and
content fingerprints are identical before and after.
"""
import sys

import pytest

import scripts.run_baseline_forecast as rbf
import scripts.run_lp as rlp


class Reached(Exception):
    """Raised by the stand-in for the database connection: the run got as far as opening one."""


def _boom(*_a, **_k):
    raise Reached()


def _no_demo(*_a, **_k):
    raise AssertionError("the demonstration path was reached")


def test_defaults_are_the_real_unilever_report_only_run():
    a = rbf.build_parser().parse_args([])
    assert (a.principal, a.source, a.write) == ("unilever", "real", False)
    b = rlp.build_parser().parse_args([])
    assert b.source == "real" and b.principal == "both" and b.dry_run is False


def test_default_forecast_invocation_goes_to_the_real_path_and_never_the_demo(monkeypatch):
    monkeypatch.setattr(rbf, "_run_demo", _no_demo)
    monkeypatch.setattr(rbf, "connect", _boom)
    monkeypatch.setattr(sys, "argv", ["run_baseline_forecast.py"])
    with pytest.raises(Reached):
        rbf.main()


def test_write_flag_alone_still_means_the_real_forecast_result_upsert(monkeypatch):
    monkeypatch.setattr(rbf, "_run_demo", _no_demo)
    monkeypatch.setattr(rbf, "connect", _boom)
    monkeypatch.setattr(sys, "argv", ["run_baseline_forecast.py", "--write"])
    with pytest.raises(Reached):
        rbf.main()


def test_del_monte_without_the_demo_source_is_refused_before_any_connection(monkeypatch):
    monkeypatch.setattr(rbf, "connect", _boom)
    monkeypatch.setattr(sys, "argv", ["run_baseline_forecast.py", "--principal", "delmonte"])
    with pytest.raises(SystemExit):
        rbf.main()


def test_demo_source_runs_the_demo_builder_and_never_opens_the_real_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(rbf, "connect", _boom)
    monkeypatch.setattr(rbf, "_run_demo", lambda principal, write: seen.setdefault("args", (principal, write)) or 0)
    monkeypatch.setattr(sys, "argv", ["run_baseline_forecast.py", "--principal", "delmonte", "--source", "demo"])
    rbf.main()
    assert seen == {"args": ("delmonte", False)}  # report-only unless --write: the demonstration builder also defaults to a dry run


def test_demo_source_for_unilever_runs_the_unilever_demo_builder(monkeypatch):
    seen = {}
    monkeypatch.setattr(rbf, "connect", _boom)
    monkeypatch.setattr(rbf, "_run_demo", lambda principal, write: seen.setdefault("args", (principal, write)) or 0)
    monkeypatch.setattr(sys, "argv", ["run_baseline_forecast.py", "--source", "demo"])
    rbf.main()
    assert seen == {"args": ("unilever", False)}


def test_default_lp_invocation_opens_the_real_path(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@localhost:1/db")
    monkeypatch.setattr(rlp.psycopg2, "connect", _boom)
    monkeypatch.setattr(sys, "argv", ["run_lp.py", "--dry-run"])
    with pytest.raises(Reached):
        rlp.main()


def test_lp_demo_source_is_refused_before_any_connection_for_the_default_principal(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@localhost:1/db")
    monkeypatch.setattr(rlp.psycopg2, "connect", _boom)
    monkeypatch.setattr(sys, "argv", ["run_lp.py", "--source", "demo"])
    with pytest.raises(SystemExit) as e:
        rlp.main()
    assert "no order plan" in str(e.value)


def test_lp_demo_source_is_refused_for_both_principals(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@localhost:1/db")
    monkeypatch.setattr(rlp.psycopg2, "connect", _boom)
    monkeypatch.setattr(sys, "argv", ["run_lp.py", "--source", "demo", "--principal", "both"])
    with pytest.raises(SystemExit) as e:
        rlp.main()
    assert "no order plan" in str(e.value)


def test_lp_demo_source_for_delmonte_runs_the_demo_builder_and_never_opens_the_real_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(rlp.psycopg2, "connect", _boom)
    monkeypatch.setattr(rlp, "_run_demo_lp", lambda write: seen.setdefault("write", write) or 0)
    monkeypatch.setattr(sys, "argv", ["run_lp.py", "--source", "demo", "--principal", "delmonte"])
    rlp.main()
    assert seen == {"write": False}  # report-only unless --write


def test_lp_demo_source_for_unilever_runs_its_own_demo_builder_and_never_opens_the_real_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(rlp.psycopg2, "connect", _boom)
    monkeypatch.setattr(rlp, "_run_demo_lp_unilever", lambda write: seen.setdefault("write", write) or 0)
    monkeypatch.setattr(sys, "argv", ["run_lp.py", "--source", "demo", "--principal", "unilever"])
    rlp.main()
    assert seen == {"write": False}  # report-only unless --write
