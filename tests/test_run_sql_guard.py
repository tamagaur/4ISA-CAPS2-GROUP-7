"""tests/test_run_sql_guard.py — scripts/run_sql.py refuses writes to public.

Rule (security audit 2026-09-30): public is written only by numbered
migrations through the ledgered runner. run_sql.py is read-only by default and
writes only a --scratch schema. No database: a fake connection records what
would be sent and plays back what the backstop queries would return.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import psycopg2
import pytest
from psycopg2.extensions import (
    TRANSACTION_STATUS_IDLE,
    TRANSACTION_STATUS_INERROR,
    TRANSACTION_STATUS_INTRANS,
)

from scripts import run_sql
from scripts.run_sql import Refused, refusal


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self.rowcount = 0
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        conn = self.conn
        conn.sent.append(sql)
        self.description, self._rows = None, []
        stmt = sql.strip()
        if stmt == "BEGIN":
            conn.info.transaction_status = TRANSACTION_STATUS_INTRANS
        elif stmt in ("COMMIT", "ROLLBACK"):
            conn.info.transaction_status = TRANSACTION_STATUS_IDLE
        elif "pg_current_xact_id_if_assigned" in stmt:
            self._rows = [(hit,) for hit in conn.public_writes]
        elif "count(*) FROM pg_class" in stmt:
            self._rows = [conn.object_counts.pop(0)]
        elif stmt == conn.fails:
            conn.info.transaction_status = TRANSACTION_STATUS_INERROR
            raise psycopg2.ProgrammingError("relation does not exist")
        elif stmt == conn.ends_transaction:
            conn.info.transaction_status = TRANSACTION_STATUS_IDLE

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return self._rows

    def fetchmany(self, n):
        return self._rows[:n]


class FakeConn:
    def __init__(self, public_writes=(), object_counts=((24, 0, 30), (24, 0, 30)), fails=None, ends_transaction=None):
        self.sent: list[str] = []
        self.autocommit = False
        self.info = SimpleNamespace(transaction_status=TRANSACTION_STATUS_IDLE)
        self.public_writes = list(public_writes)
        self.object_counts = list(object_counts)
        self.fails = fails
        self.ends_transaction = ends_transaction

    def cursor(self):
        return FakeCursor(self)


def quiet(_line):
    pass


# --- what is refused before anything is sent ------------------------------

@pytest.mark.parametrize("stmt", [
    "COMMIT",
    "begin",
    "  END",
    "/* sneaky */ COMMIT",
    "ROLLBACK",
    "START TRANSACTION READ WRITE",
    "SET search_path TO public",
    "SET statement_timeout = 0",
    "SET SESSION default_transaction_read_only = off",
    "RESET ALL",
    "SELECT set_config('search_path', 'public', false)",
    "DISCARD ALL",
])
def test_refused_in_both_modes(stmt):
    assert refusal(stmt, scratch=False)
    assert refusal(stmt, scratch=True)


@pytest.mark.parametrize("stmt", [
    "SELECT * FROM public.sales_fact",
    "SELECT 'COMMIT', 'SET x' FROM t",
    "SET LOCAL statement_timeout = '5s'",
    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
    "SET LOCAL ROLE anon",  # read-only probes of the Data API roles
    "UPDATE public.users SET role = 'admin'",  # read-only mode: the database refuses it
])
def test_allowed_read_only(stmt):
    assert refusal(stmt, scratch=False) is None


@pytest.mark.parametrize("stmt", [
    "INSERT INTO public.t VALUES (1)",
    "UPDATE public.t SET a = 1",
    'UPDATE "public".t SET a = 1',
    "DELETE FROM public.t",
    'DELETE FROM ONLY "public".t WHERE a = 1',
    "TRUNCATE public.t",
    "CREATE TABLE public.t (a int)",
    "ALTER TABLE public.t ADD COLUMN b int",
    "CREATE INDEX ix ON public.t (a)",
    "DROP SCHEMA public CASCADE",
    "COPY public.t FROM STDIN",
    "SELECT public.some_function()",
    "GRANT SELECT ON t TO anon",
    "REVOKE ALL ON t FROM anon",
    "CREATE ROLE api LOGIN",
    "ALTER USER postgres SET idle_in_transaction_session_timeout = 0",
    "SET LOCAL ROLE anon",
    "SET LOCAL search_path TO public",
    "ALTER DEFAULT PRIVILEGES REVOKE ALL ON TABLES FROM anon",
    "ALTER DATABASE postgres SET x = 1",
])
def test_refused_in_scratch(stmt):
    assert refusal(stmt, scratch=True)


@pytest.mark.parametrize("stmt", [
    "CREATE TABLE sales_copy AS SELECT * FROM public.sales_fact",
    "INSERT INTO t SELECT a FROM public.x JOIN public.y USING (k)",
    "UPDATE t SET a = x.a FROM public.x WHERE t.k = x.k",
    "CREATE TABLE public_copy (a int)",
    "SELECT * FROM t -- copied from public.t",
    "ALTER TABLE users ADD COLUMN role_note text",
    "DELETE FROM t WHERE k IN (SELECT k FROM public.x)",
])
def test_allowed_in_scratch(stmt):
    assert refusal(stmt, scratch=True) is None


@pytest.mark.parametrize("name", ["public", "PUBLIC", "pg_temp", "auth", "storage", "information_schema", "ssm x", "a;drop", ""])
def test_scratch_schema_name_refused(name):
    with pytest.raises(Refused):
        run_sql.check_scratch_schema(name)


def test_scratch_schema_name_accepted():
    run_sql.check_scratch_schema("ssm_load_rehearsal")


def test_a_refused_statement_stops_the_whole_file_before_anything_is_sent():
    conn = FakeConn()
    with pytest.raises(Refused, match="statement 2"):
        run_sql.run(conn, ["SELECT 1", "COMMIT", "SELECT 2"], out=quiet)
    assert conn.sent == []


# --- the transaction envelope ---------------------------------------------

def test_read_only_run_is_one_read_only_transaction_rolled_back():
    conn = FakeConn()
    assert run_sql.run(conn, ["SELECT 1", "SELECT 2"], out=quiet) is False
    assert conn.autocommit is True  # client-side flag only; nothing session-level is sent
    assert conn.sent == ["BEGIN", "SET TRANSACTION READ ONLY", "SELECT 1", "SELECT 2", "ROLLBACK"]


def test_scratch_run_commits_only_after_the_public_check():
    conn = FakeConn()
    assert run_sql.run(conn, ["CREATE TABLE t (a int)"], scratch="ssm_x", out=quiet) is True
    assert conn.sent[:2] == ["BEGIN", 'SET LOCAL search_path TO "ssm_x"']
    assert conn.sent[-1] == "COMMIT"
    check = next(i for i, s in enumerate(conn.sent) if "pg_current_xact_id_if_assigned" in s)
    assert check < len(conn.sent) - 1


def test_scratch_run_rolls_back_when_public_rows_were_written():
    conn = FakeConn(public_writes=["rows written in public.users"])
    with pytest.raises(Refused, match="public.users"):
        run_sql.run(conn, ["SELECT write_through_a_function()"], scratch="ssm_x", out=quiet)
    assert "COMMIT" not in conn.sent
    assert conn.sent[-1] == "ROLLBACK"


def test_scratch_run_rolls_back_when_a_public_object_was_dropped():
    conn = FakeConn(object_counts=[(24, 0, 30), (23, 0, 29)])
    with pytest.raises(Refused, match="1 public relations dropped"):
        run_sql.run(conn, ["SELECT drop_through_a_function()"], scratch="ssm_x", out=quiet)
    assert "COMMIT" not in conn.sent
    assert conn.sent[-1] == "ROLLBACK"


def test_a_statement_that_ends_the_transaction_stops_the_run():
    """Belt and braces for the refusals: if a statement still ended the
    transaction, the rest of the file must not run outside it."""
    conn = FakeConn(ends_transaction="CALL something_that_commits()")
    with pytest.raises(Refused, match="ended the transaction"):
        run_sql.run(conn, ["CALL something_that_commits()", "SELECT 2"], out=quiet)
    assert "SELECT 2" not in conn.sent
    assert conn.sent[-1] == "CALL something_that_commits()"  # nothing left to roll back


def test_a_database_error_rolls_back_and_is_raised():
    conn = FakeConn(fails="SELECT * FROM missing")
    with pytest.raises(psycopg2.ProgrammingError):
        run_sql.run(conn, ["SELECT * FROM missing"], scratch="ssm_x", out=quiet)
    assert conn.sent[-1] == "ROLLBACK"
    assert "COMMIT" not in conn.sent


# --- file handling ---------------------------------------------------------

def test_comment_lines_are_dropped_before_splitting():
    """2026-09-18: splitting first dropped the statement after a comment block."""
    raw = "-- header\nCREATE SCHEMA s;\n-- a note\n-- another\nCREATE TABLE s.t (a int);\n"
    assert run_sql.split_statements(raw) == ["CREATE SCHEMA s", "CREATE TABLE s.t (a int)"]


def test_never_uses_session_level_read_only():
    """set_session(readonly=True) leaks default_transaction_read_only onto
    the pooler's shared server connections (security audit 2026-09-30 #1)."""
    assert "set_session" not in Path(run_sql.__file__).read_text(encoding="utf-8")
