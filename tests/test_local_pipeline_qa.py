"""scripts/local_pipeline_qa.py synth: generated sales are labelled, and go only into the practice database."""
from __future__ import annotations

import pytest

from scripts import local_pipeline_qa as qa
from scripts import local_pg

PRACTICE = "postgresql://postgres@127.0.0.1:55432/ssm_practice"


@pytest.mark.parametrize("url", ["postgresql://user:pw@aws-0.pooler.supabase.com:6543/postgres",
                                 "postgresql://postgres@127.0.0.1:5432/ssm_practice",
                                 "postgresql://postgres@127.0.0.1:55432/ssm_local"])
def test_synth_refuses_every_database_but_the_practice_one(monkeypatch, url):
    monkeypatch.setenv("SUPABASE_DB_URL", url)
    monkeypatch.setattr(qa, "connect", lambda: pytest.fail("it connected"))
    with pytest.raises(SystemExit):
        qa.synth()


class _Cursor:
    rowcount = 709

    def __init__(self):
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchone(self):
        return (0,)


class _Conn(_Cursor):
    def __init__(self):
        super().__init__()
        self.cur = _Cursor()

    def cursor(self):
        return self.cur


def _synth(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", PRACTICE)
    conn = _Conn()
    monkeypatch.setattr(qa, "connect", lambda: conn)
    qa.synth()
    return conn.cur.sql


def test_every_generated_row_is_labelled_demo(monkeypatch):
    insert = next(s for s in _synth(monkeypatch) if "INSERT INTO unilever_sku_demand_fact" in s)
    assert "%(tag)s, %(tag)s, true, gsv, NULL" in insert


def test_generating_them_leaves_the_real_view_strict(monkeypatch):
    assert not [s for s in _synth(monkeypatch) if "VIEW" in s]


def test_the_practice_url_only_changes_the_database_name(monkeypatch):
    monkeypatch.setenv("LOCAL_PG_URL", "postgresql://postgres@127.0.0.1:55432/ssm_local")
    assert local_pg.local_url(practice=True) == PRACTICE
    assert local_pg.local_url() == "postgresql://postgres@127.0.0.1:55432/ssm_local"


def test_the_practice_url_still_refuses_another_server(monkeypatch):
    monkeypatch.setenv("LOCAL_PG_URL", "postgresql://user:pw@aws-0.pooler.supabase.com:6543/postgres")
    with pytest.raises(SystemExit):
        local_pg.local_url(practice=True)


def test_the_practice_view_admits_the_generated_tag_and_keeps_its_label():
    sql = " ".join(local_pg.PRACTICE_VIEW_SQL.split())
    assert sql.startswith("CREATE OR REPLACE VIEW public.unilever_sku_demand_fact_real AS")
    assert f"WHERE is_demo = false OR (is_demo = true AND _src_file = '{qa.TAG}')" in sql   # not the retired backfill rows
    assert " is_demo, " in sql.split(" FROM ")[0]                                             # the guard still sees the label


def test_the_practice_view_goes_only_into_the_practice_copy(monkeypatch):
    calls = []
    monkeypatch.setattr(local_pg, "_psql", lambda db, sql=None, file=None: (calls.append((db, sql)), type("R", (), {"returncode": 0, "stderr": ""})())[1])
    local_pg.make_practice()
    assert [db for db, sql in calls if sql == local_pg.PRACTICE_VIEW_SQL] == ["ssm_practice"]


def test_a_practice_copy_whose_view_cannot_open_is_refused(monkeypatch):
    def fake(db, sql=None, file=None):
        return type("R", (), {"returncode": 1 if sql == local_pg.PRACTICE_VIEW_SQL else 0, "stderr": "column mismatch"})()
    monkeypatch.setattr(local_pg, "_psql", fake)
    with pytest.raises(SystemExit, match="column mismatch"):
        local_pg.make_practice()
