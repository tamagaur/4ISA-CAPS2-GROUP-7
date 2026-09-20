"""scripts/run_sql.py — minimal .sql runner. Reads DATABASE_URL (or
SUPABASE_DB_URL/SUPABASE_DIRECT_URL) from .env, runs the given file inside
one transaction, prints each statement's row count, commits at the end.
Usage: python scripts/run_sql.py <path.sql>
"""
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()

path = sys.argv[1]
url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DIRECT_URL") or os.environ.get("SUPABASE_DB_URL")
# SUPABASE_DB_URL connects read-only (verified 2026-09-18: `show
# transaction_read_only` -> on) — SUPABASE_DIRECT_URL is the writable one.
raw = open(path, encoding="utf-8").read()
# Strip whole comment lines BEFORE splitting on ';' — splitting first and
# then dropping chunks whose first line starts with '--' silently drops
# real statements that happen to follow a comment block before the next
# ';' (found 2026-09-18: it dropped this file's CREATE SCHEMA and backup
# CREATE TABLE, causing a "schema does not exist" error with no trace).
sql = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("--"))

conn = psycopg2.connect(url)
try:
    with conn.cursor() as cur:
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            cur.execute(stmt)
            print(f"[{cur.rowcount} rows] {stmt.splitlines()[0][:80]}")
    conn.commit()
    print("COMMITTED")
except Exception:
    conn.rollback()
    print("ROLLED BACK")
    raise
finally:
    conn.close()
