"""tests/test_backup_credentials.py — backups hold no credentials.

Security audit 2026-09-30, finding 5: users.parquet in six snapshots held the
bcrypt hashes of both live accounts. create_backup now leaves out
users.password_hash and the whole auth_token table, and records both in
manifest.json so backup_everything's live comparison does not report them as
missing. No database: create_backup runs against a fake engine and writes real
parquet files to a temp folder.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts import backup_everything, backup_live_db

COLUMNS = {
    "users": [
        {"name": "user_id", "type": "BIGINT", "nullable": False},
        {"name": "email", "type": "TEXT", "nullable": False},
        {"name": "password_hash", "type": "TEXT", "nullable": True},
        {"name": "full_name", "type": "TEXT", "nullable": False},
        {"name": "role", "type": "TEXT", "nullable": False},
    ],
    "auth_token": [
        {"name": "token_key", "type": "BIGINT", "nullable": False},
        {"name": "token_hash", "type": "TEXT", "nullable": False},
    ],
    "etl_quarantine": [
        {"name": "quarantine_key", "type": "BIGINT", "nullable": False},
        {"name": "raw_values", "type": "JSONB", "nullable": True},
    ],
}
ROWS = {
    "users": [{"user_id": 1, "email": "a@x.com", "password_hash": "$2b$12$secret", "full_name": "A", "role": "admin"}],
    "auth_token": [{"token_key": 1, "token_hash": "ab" * 32}],
    "etl_quarantine": [{"quarantine_key": 1, "raw_values": '{"a": 1}'}],
}


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeConn:
    def __init__(self, sent):
        self.sent = sent

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sent.append(sql)
        if "information_schema.tables" in sql:
            return FakeResult([(t,) for t in sorted(COLUMNS)])
        select, table = sql.removeprefix("SELECT ").split(' FROM "public".')
        table = table.strip('"')
        if select == "*":
            return FakeResult(ROWS[table])
        names = [part.split(" AS ")[-1].strip().strip('"') for part in select.split(", ")]
        return FakeResult([{n: row[n] for n in names} for row in ROWS[table]])


class FakeEngine:
    def __init__(self):
        self.sent: list[str] = []

    def connect(self):
        return FakeConn(self.sent)


class FakeInspector:
    def get_pk_constraint(self, table, schema):
        return {"constrained_columns": [COLUMNS[table][0]["name"]]}

    def get_columns(self, table, schema):
        return COLUMNS[table]


@pytest.fixture
def backup(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_live_db, "inspect", lambda engine: FakeInspector())
    engine = FakeEngine()
    out = backup_live_db.create_backup(engine, tmp_path / "b", json_as_text=True)
    return out, engine


def test_users_file_has_no_password_hash(backup):
    out, engine = backup
    users = pd.read_parquet(out / "users.parquet")
    assert list(users.columns) == ["user_id", "email", "full_name", "role"]
    assert not any("password_hash" in sql for sql in engine.sent if sql.startswith("SELECT"))


def test_auth_token_is_not_read_or_written(backup):
    out, engine = backup
    assert not (out / "auth_token.parquet").exists()
    assert not any('"auth_token"' in sql for sql in engine.sent)
    assert "auth_token" not in json.loads((out / "ddl_snapshot.json").read_text(encoding="utf-8"))


def test_manifest_records_what_was_left_out(backup):
    out, _ = backup
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["tables"]) == {"users", "etl_quarantine"}
    assert set(manifest["excluded"]["tables"]) == {"auth_token"}
    assert set(manifest["excluded"]["columns"]) == {"users"}
    assert set(manifest["excluded"]["columns"]["users"]) == {"password_hash"}


def test_other_tables_are_unchanged(backup):
    """json_as_text still casts JSON columns; nothing else is dropped."""
    out, engine = backup
    q = pd.read_parquet(out / "etl_quarantine.parquet")
    assert q["raw_values"].tolist() == ['{"a": 1}']
    assert any('"raw_values"::text AS "raw_values"' in sql for sql in engine.sent)


def test_a_left_out_table_is_not_reported_missing(backup):
    out, _ = backup
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert backup_everything._not_backed_up(["auth_token", "users", "etl_quarantine"], manifest) == []
    # A table with neither a file nor a recorded reason is still a problem.
    assert backup_everything._not_backed_up(["users", "sales_fact"], manifest) == ["sales_fact"]


def test_plain_tables_still_select_star():
    assert backup_live_db._select_list("sales_fact", [{"name": "a", "type": "INTEGER"}], json_as_text=False) == ("*", {})
