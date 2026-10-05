"""
backend.batch — several read queries in ONE round trip to the database.

WHY (2026-10-04). Every statement costs a network round trip, ~0.1 s from the team's
machines to Supabase (Mumbai) and more from Render (Oregon), however little work the
database does for it. GET /dashboard issued 30 statements one after another (3.7-4.5 s,
reports/diagnostics/speed_cache_2026-10-04). Most are single-row lookups that don't
depend on each other.

HOW. prefetch() runs a list of (sql, params) as one statement: each query becomes a
scalar subquery that returns its rows as JSON text,

    SELECT (SELECT COALESCE(json_agg(q), '[]') FROM (<query 1>) q)::text AS r0,
           (SELECT COALESCE(json_agg(q), '[]') FROM (<query 2>) q)::text AS r1, ...

and the decoded rows are kept on the request's Session (Session.info) under the query's
text and parameters. The read helpers below (rows / first / scalar) answer from there
when the same query is asked for, and run it on its own otherwise. So a prefetch list
that drifts from what the code actually asks for costs speed, never correctness: the
query simply runs as it always did.

Each query's SQL is the one the helper runs on its own, unchanged; only its bind names
are prefixed (q0_, q1_, ...) so two queries can't collide.

JSON TYPES. Decoded rows match what psycopg2 returns, with two known differences, both
handled: numeric arrives as int/float instead of Decimal (every caller already converts
with float()/int(), and FastAPI serialises a Decimal the same way), and date/timestamp
columns arrive as ISO text, which _revive() turns back into date/datetime. Only top-level
column values are revived; jsonb columns come back as dicts either way.

Only a real SQLAlchemy Session is batched. The tests' fake sessions match on each
query's own text, so with them every query runs alone, exactly as before.
"""
from __future__ import annotations

import datetime
import json
import re
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

# SQLAlchemy text()'s own bind-parameter pattern (":name", not "::cast").
_BIND = re.compile(r"(?<![:\w\\]):(\w+)(?!:)")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}(:\d{2})?)?$")

_MEMO = "batch_memo"


def _freeze(value):
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    return value


def _key(sql: str, params: dict | None) -> tuple:
    """The query's identity: its text (whitespace-normalised) and the parameters it
    actually binds. Callers often pass extra params; they don't change the query."""
    used = set(_BIND.findall(sql))
    return " ".join(sql.split()), tuple(sorted((k, _freeze(v)) for k, v in (params or {}).items() if k in used))


def _revive(value):
    if isinstance(value, str):
        if _DATE.match(value):
            return datetime.date.fromisoformat(value)
        if _TIMESTAMP.match(value):
            return datetime.datetime.fromisoformat(value)
    return value


def _memo(db) -> dict | None:
    info = getattr(db, "info", None)
    if not isinstance(db, Session) or not isinstance(info, dict):
        return None
    return info.setdefault(_MEMO, {})


def prefetch(db, queries: Iterable[tuple[str, dict | None]]) -> int:
    """Run every query not already answered on this session, in one round trip.
    Returns how many were run (0 for a fake session or when all are known)."""
    memo = _memo(db)
    if memo is None:
        return 0
    todo: dict[tuple, tuple[str, dict]] = {}
    for sql, params in queries:
        key = _key(sql, params)
        if key not in memo and key not in todo:
            todo[key] = (sql, params or {})
    if not todo:
        return 0
    columns, bound = [], {}
    for i, (sql, params) in enumerate(todo.values()):
        prefix = f"q{i}_"
        used = set(_BIND.findall(sql))
        renamed = _BIND.sub(lambda m: f":{prefix}{m.group(1)}", sql)
        bound.update({prefix + k: v for k, v in params.items() if k in used})
        columns.append(f"(SELECT COALESCE(json_agg(q), '[]'::json) FROM ({renamed}) q)::text AS r{i}")
    row = db.execute(text("SELECT " + ",\n       ".join(columns)), bound).one()
    for key, raw in zip(todo, row):
        memo[key] = [{k: _revive(v) for k, v in r.items()} for r in json.loads(raw)]
    return len(todo)


def rows(db, sql: str, params: dict | None = None) -> list:
    """The query's rows (dicts when prefetched, RowMappings when run here)."""
    memo = _memo(db)
    if memo is not None:
        hit = memo.get(_key(sql, params))
        if hit is not None:
            return hit
    return db.execute(text(sql), params or {}).mappings().all()


def first(db, sql: str, params: dict | None = None):
    """The query's first row, or None."""
    memo = _memo(db)
    if memo is not None:
        hit = memo.get(_key(sql, params))
        if hit is not None:
            return hit[0] if hit else None
    return db.execute(text(sql), params or {}).mappings().first()


def scalar(db, sql: str, params: dict | None = None):
    """The query's first column of its first row, or None."""
    memo = _memo(db)
    if memo is not None:
        hit = memo.get(_key(sql, params))
        if hit is not None:
            return next(iter(hit[0].values())) if hit else None
    return db.execute(text(sql), params or {}).scalar()
