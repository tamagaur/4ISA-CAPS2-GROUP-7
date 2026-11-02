"""analytics/forecasting/practice_switch.py: the forecast accepts labelled rows on the practice copy and nowhere else, and
nothing outside the connection can change that."""
from __future__ import annotations

import ast
import inspect
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics.forecasting import practice_switch as ps
from analytics.forecasting import router

REPO = Path(__file__).resolve().parents[2]
PRACTICE = ("127.0.0.1", 55432, "ssm_practice")
LABELLED = pd.DataFrame({"calendar_month": ["2026-03"], "quantity": [1.0], "is_demo": [True]})
REAL = pd.DataFrame({"calendar_month": ["2026-02"], "quantity": [1.0], "is_demo": [False]})

NOT_PRACTICE = [
    # (what libpq connected to, what the server reports)
    pytest.param(("aws-0.pooler.supabase.com", 6543, "postgres"), ("10.0.0.5", 5432, "postgres"), id="live-pooler"),
    pytest.param(("db.supabase.co", 5432, "postgres"), ("10.0.0.5", 5432, "postgres"), id="live-direct"),
    pytest.param(("127.0.0.1", 55432, "ssm_local"), ("127.0.0.1", 55432, "ssm_local"), id="the-database-behind-the-pages"),
    pytest.param(("127.0.0.1", 5432, "ssm_practice"), ("127.0.0.1", 5432, "ssm_practice"), id="another-local-server"),
    pytest.param(("localhost", 55432, "ssm_practice"), ("127.0.0.1", 55432, "ssm_practice"), id="not-named-127.0.0.1"),
    pytest.param(("127.0.0.1", 55432, "ssm_practice"), ("10.0.0.5", 5432, "postgres"), id="tunnel-to-another-server"),
    pytest.param(("127.0.0.1", 55432, "ssm_practice"), ("10.0.0.5", 55432, "ssm_practice"), id="tunnel-same-port-and-name"),
    pytest.param(("127.0.0.1", 55432, "ssm_practice"), (None, None, "ssm_practice"), id="server-on-a-unix-socket"),
    pytest.param(("evil.example", 5432, "postgres"), ("127.0.0.1", 55432, "ssm_practice"), id="server-claims-client-does-not"),
]


class FakeCursor:
    def __init__(self, client, server, count=709):
        self.connection = SimpleNamespace(info=SimpleNamespace(host=client[0], port=client[1], dbname=client[2]))
        self.server, self.count = server, count
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def fetchone(self):
        return self.server if self.executed[-1] == ps.SERVER_IDENTITY_SQL else (self.count,)


@pytest.fixture(autouse=True)
def _restore_stdout(monkeypatch):
    monkeypatch.setattr(sys, "stdout", sys.stdout)


def test_it_fires_on_the_practice_copy_and_logs_the_database_and_the_row_count(caplog):
    with caplog.at_level("WARNING"):
        assert ps.labelled_rows_permitted(FakeCursor(PRACTICE, PRACTICE), LABELLED) is True
    assert "709" in caplog.text and "ssm_practice" in caplog.text and "127.0.0.1:55432" in caplog.text


@pytest.mark.parametrize("client, server", NOT_PRACTICE)
def test_it_cannot_fire_anywhere_else(client, server, caplog):
    with caplog.at_level("WARNING"):
        assert ps.labelled_rows_permitted(FakeCursor(client, server), LABELLED) is False
    assert "PRACTICE SWITCH" not in caplog.text


@pytest.mark.parametrize("client, server", NOT_PRACTICE)
def test_the_outside_world_cannot_turn_it_on(client, server, monkeypatch):
    for name in ("PRACTICE_SWITCH", "ALLOW_PLACEHOLDER", "ALLOW_LABELLED_ROWS", "MONTHLY_BATCH_ENABLED", "APP_ENV", "DEBUG"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/ssm_practice")
    monkeypatch.setenv("LOCAL_PG_URL", "postgresql://postgres@127.0.0.1:55432/ssm_practice")
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", "55432")
    assert ps.labelled_rows_permitted(FakeCursor(client, server), LABELLED) is False


def test_the_module_reads_nothing_but_the_connection():
    tree = ast.parse(Path(ps.__file__).read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported == {"__future__", "io", "logging", "sys"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"environ", "getenv", "argv", "open", "dotenv_values", "get_settings", "read_text"}


def test_neither_function_takes_an_argument_that_could_say_yes():
    assert list(inspect.signature(ps.is_practice_database).parameters) == ["cur"]
    assert list(inspect.signature(ps.labelled_rows_permitted).parameters) == ["cur", "demand"]


def test_a_real_run_never_asks_the_database_and_stays_refused_if_labelled():
    cur = FakeCursor(PRACTICE, PRACTICE)
    assert ps.labelled_rows_permitted(cur, REAL) is False and cur.executed == []
    assert ps.labelled_rows_permitted(cur, REAL.drop(columns="is_demo")) is False and cur.executed == []


def test_the_guard_still_refuses_labelled_rows_without_the_switch():
    with pytest.raises(ValueError, match="is_demo"):
        router.assert_real_rows(LABELLED, allow_placeholder=ps.labelled_rows_permitted(FakeCursor(*NOT_PRACTICE[0].values), LABELLED))
    router.assert_real_rows(LABELLED, allow_placeholder=ps.labelled_rows_permitted(FakeCursor(PRACTICE, PRACTICE), LABELLED))


def test_every_line_a_permitted_run_prints_carries_the_label(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    ps.labelled_rows_permitted(FakeCursor(PRACTICE, PRACTICE), LABELLED)
    ps.labelled_rows_permitted(FakeCursor(PRACTICE, PRACTICE), LABELLED)       # the write path asks again: one label, not two
    print("MASE 0.91")
    print("MAPE", "34.0%")
    lines = out.getvalue().splitlines()
    assert lines == [ps.OUTPUT_LABEL + "MASE 0.91", ps.OUTPUT_LABEL + "MAPE 34.0%"]


def test_the_runner_takes_its_allow_placeholder_from_the_switch_only():
    tree = ast.parse((REPO / "scripts/run_baseline_forecast.py").read_text(encoding="utf-8"))
    passed = [n.value for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "allow_placeholder"]
    assert passed and all(isinstance(v, ast.Name) for v in passed)
    assert {v.id for v in passed} == {"labelled", "allow_placeholder"}
    assigned = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "labelled" for t in n.targets)]
    assert assigned and all(isinstance(v, ast.Call) and v.func.id == "labelled_rows_permitted" for v in assigned)
    served = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "served_forecasts")
    assert served.args.defaults[-1].value is False       # served_forecasts defaults to refusing


def test_only_this_module_names_the_practice_database_for_the_forecast():
    for path in ("analytics/forecasting/router.py", "analytics/forecasting/global_model.py", "scripts/run_baseline_forecast.py"):
        source = (REPO / path).read_text(encoding="utf-8")
        assert "55432" not in source and "ssm_practice" not in source
