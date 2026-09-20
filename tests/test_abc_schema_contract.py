"""tests/test_abc_schema_contract.py — the ORM model must describe the live
ABC_Classification table.

analytics/db/models.py still declared the pre-0017 two-column natural key and
omitted three columns that exist in the database (boundary_flag from migration
0002, method and run_id from 0017). scripts/restore_abc_purge.py's ON CONFLICT
target had the same pre-0017 shape, which no longer matches any unique index.

Hits the live DB for the reflection comparison, so it skips when
SUPABASE_DB_URL is unset. READ-ONLY: reflection and information_schema only.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from analytics.db.models import ABCClassification

load_dotenv()

REPO = Path(__file__).resolve().parents[1]
LIVE_UNIQUE_KEY = ("product_key", "classification_period", "method")

pytestmark = pytest.mark.skipif(
    not os.environ.get("SUPABASE_DB_URL"),
    reason="live DB not configured (SUPABASE_DB_URL unset)",
)


@pytest.fixture(scope="module")
def live_columns():
    psycopg2 = pytest.importorskip("psycopg2")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'abc_classification'"
        )
        cols = {r[0] for r in cur.fetchall()}
    conn.rollback()
    conn.close()
    return cols


@pytest.fixture(scope="module")
def live_unique_keys():
    psycopg2 = pytest.importorskip("psycopg2")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute(
            """
            -- string_agg, not array_agg: psycopg2 hands a PG array back as a
            -- raw '{a,b,c}' string unless the type is registered, which would
            -- make tuple() iterate it character by character.
            SELECT tc.constraint_name,
                   string_agg(kcu.column_name, ',' ORDER BY kcu.ordinal_position)
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = tc.constraint_name
            WHERE tc.table_name = 'abc_classification'
              AND tc.constraint_type = 'UNIQUE'
            GROUP BY tc.constraint_name
            """
        )
        keys = {name: tuple(cols.split(',')) for name, cols in cur.fetchall()}
    conn.rollback()
    conn.close()
    return keys


def test_model_declares_every_live_column(live_columns):
    modelled = {c.name for c in ABCClassification.__table__.columns}

    assert live_columns - modelled == set(), (
        f"live columns missing from the ORM model: {sorted(live_columns - modelled)}"
    )


def test_model_declares_no_phantom_columns(live_columns):
    modelled = {c.name for c in ABCClassification.__table__.columns}

    assert modelled - live_columns == set(), (
        f"ORM declares columns the table does not have: {sorted(modelled - live_columns)}"
    )


def test_model_unique_constraint_matches_live(live_unique_keys):
    modelled = {
        tuple(c.name for c in con.columns)
        for con in ABCClassification.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }

    assert LIVE_UNIQUE_KEY in modelled
    assert LIVE_UNIQUE_KEY in set(live_unique_keys.values())


def test_restore_script_conflict_target_matches_live_key():
    """A DO NOTHING against a non-existent index raises, it does not no-op."""
    source = io.open(REPO / "scripts/restore_abc_purge.py", encoding="utf-8").read()

    assert "ON CONFLICT (product_key, classification_period, method)" in source
    assert "ON CONFLICT (product_key, classification_period) DO NOTHING" not in source
