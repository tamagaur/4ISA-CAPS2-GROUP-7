"""scripts/check.sh --optin must not be able to reach anything but the throwaway server (2026-11-03).

These tests touch no database: they prove the refusals, so the run that uses them is not the only evidence."""
import os
import socket
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

from scripts import check_helpers as ch
from scripts import optin_guard as g
from scripts import optin_run as run

LOCAL = "postgresql://postgres@127.0.0.1:55432/ssm_optin"


@pytest.mark.parametrize("url", [
    "postgresql://u:p@db.example.supabase.co:5432/postgres",   # a real host
    "postgresql://u:p@aws-0.pooler.example.com:6543/postgres",  # the pooler
    "postgresql://postgres@127.0.0.1:5432/postgres",           # a local server on another port
    "postgresql://postgres@example.com:55432/ssm_optin",       # the right port on another host
    "",
])
def test_anything_but_the_throwaway_server_is_refused(url):
    with pytest.raises(g.RefusedConnection):
        g.require_throwaway(url)


def test_the_throwaway_server_is_allowed():
    g.require_throwaway(LOCAL)


def test_a_guarded_psycopg2_connect_never_reaches_a_remote_host(monkeypatch, tmp_path):
    reached = []
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: reached.append((a, k)))
    log = tmp_path / "refused.log"
    monkeypatch.setenv(g.LOG_VAR, str(log))
    g._guard_psycopg2()
    with pytest.raises(g.RefusedConnection):
        psycopg2.connect("postgresql://u:p@db.example.supabase.co:5432/postgres")
    with pytest.raises(g.RefusedConnection):
        psycopg2.connect(host="db.example.supabase.co", port=5432, dbname="postgres")
    assert reached == []
    assert log.read_text(encoding="utf-8").count("db.example.supabase.co") == 2
    psycopg2.connect(LOCAL)
    psycopg2.connect(host="127.0.0.1", port=55432, dbname="ssm_optin")
    assert len(reached) == 2


def test_a_refused_attempt_never_writes_the_password(monkeypatch, tmp_path):
    log = tmp_path / "refused.log"
    monkeypatch.setenv(g.LOG_VAR, str(log))
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: None)
    g._guard_psycopg2()
    with pytest.raises(g.RefusedConnection) as e:
        psycopg2.connect("postgresql://u:hunter2@db.example.supabase.co:5432/postgres")
    assert "hunter2" not in log.read_text(encoding="utf-8") and "hunter2" not in str(e.value)


def test_a_python_socket_to_another_host_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv(g.LOG_VAR, str(tmp_path / "refused.log"))
    original = socket.socket.connect
    try:
        g._guard_sockets()
        s = socket.socket()
        try:
            with pytest.raises(g.RefusedConnection):
                s.connect(("smtp.example.com", 587))
        finally:
            s.close()
    finally:
        socket.socket.connect = original


def test_the_child_environment_names_only_the_throwaway_database(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("SUPABASE_DB_URL=postgresql://u:p@remote:5432/x\nSUPABASE_DIRECT_URL=postgresql://u:p@remote:5432/x\n"
                      "SMTP_HOST=smtp.example.com\nSMTP_PASSWORD=secret\nSOME_FUTURE_URL=https://remote.example.com\n"
                      "JWT_SECRET_KEY=keep-me\nJWT_ALGORITHM=HS256\n", encoding="utf-8")
    env = run.child_env(LOCAL, dotenv)
    assert env["SUPABASE_DB_URL"] == env["SUPABASE_DIRECT_URL"] == env["DATABASE_URL"] == LOCAL
    # A key set empty here stays empty: load_dotenv(override=False) never fills a key that is already set.
    assert env["SMTP_HOST"] == env["SMTP_PASSWORD"] == env["SOME_FUTURE_URL"] == ""
    assert env.get("JWT_ALGORITHM") != ""   # no destination in it, so it is left for .env to provide


def test_the_command_covers_exactly_the_eighteen_on_the_list():
    covered = ch.covered_by_optin()
    assert len(covered) == 18
    assert sum(n.startswith("tests.etl.test_fills_db::") for n in covered) == 17
    assert "tests.etl.test_rollover_scratch::test_rollover_on_a_scratch_schema_with_a_synthetic_march" in covered
    assert set(ch.load_allowed()) - set(covered) == {
        "tests.etl.test_layout_regression::test_content_identification_reproduces_todays_family_and_month_for_every_file",
        "tests.etl.test_extract::test_parse_unilever_sku_against_real_file",
        "tests.backend.test_policy_comparison::test_pesos_reproduce_the_lp_logic_check_totals"}


def _case(suite, name, kind=None):
    from xml.etree import ElementTree as ET
    tc = ET.SubElement(suite, "testcase", classname="t.mod", name=name)
    if kind:
        ET.SubElement(tc, kind, message="why")


def _junit(tmp_path, cases):
    from xml.etree import ElementTree as ET
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for name, kind in cases:
        _case(suite, name, kind)
    p = tmp_path / "r.xml"
    ET.ElementTree(root).write(p)
    return p


def test_every_listed_test_must_have_passed(tmp_path):
    want = ["t.mod::a", "t.mod::b"]
    outcomes, ok = run.read_outcomes(_junit(tmp_path, [("a", None), ("b", None)]), want)
    assert ok and outcomes == {"t.mod::a": "PASS", "t.mod::b": "PASS"}


@pytest.mark.parametrize("cases", [
    [("a", None), ("b", "failure")],     # one failed
    [("a", None), ("b", "error")],       # one errored
    [("a", None), ("b", "skipped")],     # skipped is not passed
    [("a", None)],                       # one never ran
    [("a", None), ("b", None), ("c", None)],   # one the list does not name
])
def test_anything_short_of_every_listed_test_passing_fails(tmp_path, cases):
    assert run.read_outcomes(_junit(tmp_path, cases), ["t.mod::a", "t.mod::b"])[1] is False


def _fake_server(monkeypatch, tmp_path, restore, dropped=True):
    """run() against a fake server; returns the seed and the list of databases it dropped. Nothing connects to anything."""
    from scripts import local_pg
    drops = []

    def drop(db):
        drops.append(db)
        return dropped

    monkeypatch.setenv(g.LOG_VAR, str(tmp_path / "refused.log"))     # run() sets this in os.environ; monkeypatch puts it back
    monkeypatch.setattr(run.optin_guard, "install", lambda: None)
    monkeypatch.setattr(run, "child_env", lambda url: {"SUPABASE_DB_URL": url})
    for name, value in {"is_up": lambda: True, "start": lambda: None, "stop": lambda: None, "restore": restore, "drop_database": drop}.items():
        monkeypatch.setattr(local_pg, name, value)
    (tmp_path / "structure").mkdir()
    return tmp_path, drops


def test_the_database_is_dropped_when_the_run_fails(monkeypatch, tmp_path):
    seed, drops = _fake_server(monkeypatch, tmp_path, lambda seed, db: ["a table did not load"])
    assert run.run(seed, keep=False) == 1
    assert drops == [run.OPTIN_DB]


def test_the_database_is_dropped_when_a_step_raises(monkeypatch, tmp_path):
    def boom(seed, db):
        raise RuntimeError("the restore fell over")
    seed, drops = _fake_server(monkeypatch, tmp_path, boom)
    with pytest.raises(RuntimeError):
        run.run(seed, keep=False)
    assert drops == [run.OPTIN_DB]


def test_a_database_that_could_not_be_dropped_fails_the_run(monkeypatch, tmp_path):
    seed, drops = _fake_server(monkeypatch, tmp_path, lambda seed, db: [], dropped=False)
    monkeypatch.setattr(run, "_guarded", lambda *a: 0)
    monkeypatch.setattr(run, "_server_says", lambda env: ((55432, run.OPTIN_DB), run.SEED_PLAN))
    monkeypatch.setattr(run, "read_outcomes", lambda *a: ({}, True))
    with pytest.raises(SystemExit, match="could not drop"):
        run.run(seed, keep=False)
    assert drops == [run.OPTIN_DB]


def test_the_rollover_script_run_directly_refuses_anything_but_the_throwaway_server():
    """In a child process: main() loads the repo's .env into its environment before the refusal."""
    done = subprocess.run([sys.executable, "-m", "scripts.rollover_scratch_test"], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ, "SUPABASE_DB_URL": "postgresql://u:p@db.example.com:6543/postgres"})
    assert done.returncode != 0
    assert "REFUSED by scripts/optin_guard.py" in done.stderr and "db.example.com:6543" in done.stderr
    assert "rollover scratch test, schema" not in done.stdout       # it stopped before the first check
