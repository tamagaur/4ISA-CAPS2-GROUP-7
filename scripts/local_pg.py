"""
scripts/local_pg.py - a throwaway local Postgres for destructive QA (never live).

    python -m scripts.local_pg start                  # initdb (once) + start on 127.0.0.1:55432
    python -m scripts.local_pg restore BACKUP_DIR     # create db, load structure/*.sql and data/**/*.parquet
    python -m scripts.local_pg practice               # (re)make ssm_practice, a copy of the local DB that no page reads
    python -m scripts.local_pg run -- CMD ARGS...     # run CMD with the local DB as its database
    python -m scripts.local_pg run --practice -- CMD  # the same, on ssm_practice (generated sales live only there)
    python -m scripts.local_pg stop

The connection lives in LOCAL_PG_URL, which no project code reads. `run` copies it into SUPABASE_DB_URL and
SUPABASE_DIRECT_URL for the CHILD process only (the repo's .env otherwise falls back to live), and refuses unless the
host is 127.0.0.1/localhost on the throwaway port. The data directory is local/pg_throwaway (git-ignored).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys
import time

import pandas as pd

pd_NA = pd.NA
from pathlib import Path
from urllib.parse import urlparse

from scripts.local_pipeline_qa import TAG  # noqa: E402
from scripts.report_target import PRACTICE_MARKER  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PGBIN = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
DATA = REPO / "local" / "pg_throwaway"
PORT = 55432
DB = "ssm_local"
PRACTICE_DB = "ssm_practice"
DEFAULT_URL = f"postgresql://postgres@127.0.0.1:{PORT}/{DB}"
# The practice copy's one difference from ssm_local: its demand view also admits the rows `local_pipeline_qa.py synth` generates,
# so ABC, forecast, LP and close run on them. The column list is the real view's, is_demo included, so the label stays in sight of
# analytics/forecasting/practice_switch and the guard behind it. Every other is_demo row (the retired backfill) stays out.
PRACTICE_VIEW_SQL = f"""
    CREATE OR REPLACE VIEW public.unilever_sku_demand_fact_real AS
    SELECT demand_key, product_key, sku_code, calendar_month, region, quantity_sold, net_amount, _src_file, _src_sheet, is_demo, gsv
    FROM public.unilever_sku_demand_fact
    WHERE is_demo = false OR (is_demo = true AND _src_file = '{TAG}')
"""
# Its second difference: every table gets a practice_run column, NULL on the rows the copy started with, and a trigger that stamps it
# on every row inserted or updated afterwards, so a row says where it came from whichever script wrote it and no writer has to know.
# The rows the run deletes leave no row to mark: scripts/practice_artefacts.py counts them. Only in this copy: never a migration.
PRACTICE_ROW_LABEL = "written on ssm_practice, which holds generated sales: practice, not a result"
PRACTICE_ROW_LABEL_SQL = f"""
    CREATE OR REPLACE FUNCTION public.practice_run_label() RETURNS trigger LANGUAGE plpgsql AS $f$
    BEGIN NEW.practice_run := '{PRACTICE_ROW_LABEL}'; RETURN NEW; END $f$;
    DO $d$ DECLARE t record; BEGIN
      FOR t IN SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition AND n.nspname IN ('public', 'mart', 'demo', 'app') LOOP
        EXECUTE format('ALTER TABLE %I.%I ADD COLUMN practice_run text', t.nspname, t.relname);
        EXECUTE format('CREATE TRIGGER practice_run_label BEFORE INSERT OR UPDATE ON %I.%I FOR EACH ROW EXECUTE FUNCTION public.practice_run_label()',
                       t.nspname, t.relname);
      END LOOP;
    END $d$;
"""


def local_url(practice: bool = False, db: str | None = None) -> str:
    url = os.environ.get("LOCAL_PG_URL", DEFAULT_URL)
    u = urlparse(url)
    if u.hostname not in ("127.0.0.1", "localhost") or u.port != PORT:
        sys.exit(f"REFUSED: LOCAL_PG_URL must be 127.0.0.1:{PORT}, got {u.hostname}:{u.port}")
    name = PRACTICE_DB if practice else db
    return u._replace(path=f"/{name}").geturl() if name else url


def _run(*cmd, **kw):
    return subprocess.run([str(c) for c in cmd], check=kw.pop("check", True), **kw)


def start() -> None:
    if not (DATA / "PG_VERSION").exists():
        _run(PGBIN / "initdb.exe", "-D", DATA, "-U", "postgres", "-A", "trust", "-E", "UTF8", stdout=subprocess.DEVNULL)
    if not (DATA / "server.crt").exists():   # the code under test connects with sslmode=require (backend/deps.py:71)
        _run("openssl", "req", "-new", "-x509", "-days", "30", "-nodes", "-subj", "/CN=localhost",
             "-out", DATA / "server.crt", "-keyout", DATA / "server.key", capture_output=True)
    opts = f"-p {PORT} -c listen_addresses=127.0.0.1 -c fsync=off -c synchronous_commit=off -c ssl=on"
    subprocess.Popen([str(PGBIN / "pg_ctl.exe"), "-D", str(DATA), "-o", opts, "-l", str(REPO / "local" / "pg_throwaway.log"), "start"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if _run(PGBIN / "pg_isready.exe", "-h", "127.0.0.1", "-p", PORT, check=False, stdout=subprocess.DEVNULL).returncode == 0:
            print(f"up on 127.0.0.1:{PORT}")
            return
        time.sleep(1)
    sys.exit("did not come up")


def stop() -> None:
    _run(PGBIN / "pg_ctl.exe", "-D", DATA, "-m", "fast", "stop", check=False)


def is_up() -> bool:
    return _run(PGBIN / "pg_isready.exe", "-h", "127.0.0.1", "-p", PORT, check=False, stdout=subprocess.DEVNULL).returncode == 0


def drop_database(db: str) -> bool:
    """True when the database is gone, including when it was never there. False when the server refused or could not be reached."""
    return _psql("postgres", f"DROP DATABASE IF EXISTS {db} WITH (FORCE)").returncode == 0


def _psql(db, sql=None, file=None):
    cmd = [PGBIN / "psql.exe", "-h", "127.0.0.1", "-p", PORT, "-U", "postgres", "-d", db, "-X", "-q"]
    cmd += ["-c", sql] if sql else ["-f", file]
    return _run(*cmd, capture_output=True, text=True, check=False)


def make_practice() -> None:
    """A fresh copy of the local database for the monthly batch. CREATE DATABASE ... TEMPLATE needs the source idle."""
    _psql("postgres", f"DROP DATABASE IF EXISTS {PRACTICE_DB} WITH (FORCE)")
    _psql("postgres", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{DB}'")
    r = _psql("postgres", f"CREATE DATABASE {PRACTICE_DB} TEMPLATE {DB}")
    if r.returncode != 0:
        sys.exit(f"could not make {PRACTICE_DB}: {r.stderr.strip()}")
    r = _psql(PRACTICE_DB, PRACTICE_VIEW_SQL)
    if r.returncode != 0:
        sys.exit(f"could not open {PRACTICE_DB}'s demand view to its generated rows: {r.stderr.strip()}")
    r = _psql(PRACTICE_DB, PRACTICE_ROW_LABEL_SQL)
    if r.returncode != 0:
        sys.exit(f"could not give {PRACTICE_DB}'s tables their practice_run label: {r.stderr.strip()}")
    print(f"{PRACTICE_DB} is a fresh copy of {DB}; its demand view also admits rows tagged {TAG}; every row written to it is stamped practice_run")


def _pg_array(v):
    if v is None or v is pd_NA:
        return None
    if isinstance(v, str):
        v = json.loads(v)
    return "{" + ",".join('"' + str(x).replace("\\", "\\\\").replace('"', '\\"') + '"' for x in v) + "}"


def restore(backup: Path, db: str = DB) -> list[str]:
    """Load a backup into `db`, replacing it. Returns the tables whose row count differs from the backup's manifest."""
    import pandas as pd
    import psycopg2
    t0 = time.time()
    if db == DB:
        _psql("postgres", f"DROP DATABASE IF EXISTS {PRACTICE_DB} WITH (FORCE)")   # a copy of what is being replaced
    _psql("postgres", f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
    _psql("postgres", f"CREATE DATABASE {db}")
    pre = ("DO $$ DECLARE r text; BEGIN FOREACH r IN ARRAY ARRAY['anon','authenticated','service_role','supabase_admin'] LOOP "
           "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=r) THEN EXECUTE format('CREATE ROLE %I', r); END IF; END LOOP; END $$;")
    _psql(db, pre)
    _psql(db, "CREATE SCHEMA IF NOT EXISTS extensions; CREATE SCHEMA IF NOT EXISTS vault; "
              "CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions; CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\" WITH SCHEMA extensions;")
    errors = []
    for pass_no in (1, 2):   # pass 2 creates what pass 1 could not (views over a schema loaded later); only its errors count
        for name in ("app", "public", "demo", "mart"):
            r = _psql(db, file=str(backup / "structure" / f"{name}.sql"))
            if pass_no == 2:
                errors += [f"{name}: {l}" for l in r.stderr.splitlines() if "ERROR" in l and "already exists" not in l and "multiple primary keys" not in l]
    print(f"structure loaded, {len(errors)} errors")
    for e in errors[:15]:
        print("  ", e)

    mismatches = []
    conn = psycopg2.connect(local_url(db=db))
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET session_replication_role = replica")   # local superuser only: skip FK/trigger checks while loading
    counts = {}
    for schema in ("public", "app", "demo", "mart"):
        manifest = json.loads((backup / "data" / schema / "manifest.json").read_text(encoding="utf-8"))
        for table, info in manifest["tables"].items():
            f = backup / "data" / schema / info["file"]
            df = pd.read_parquet(f).convert_dtypes()
            if df.empty:
                counts[f"{schema}.{table}"] = 0
                continue
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND is_generated='NEVER' "
                        "AND identity_generation='ALWAYS'", (schema, table))
            ident = [r[0] for r in cur.fetchall()]
            for c in ident:
                cur.execute(f'ALTER TABLE "{schema}"."{table}" ALTER COLUMN "{c}" SET GENERATED BY DEFAULT')
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND data_type='ARRAY'", (schema, table))
            for (c,) in cur.fetchall():
                df[c] = df[c].map(_pg_array)
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND is_generated='ALWAYS'", (schema, table))
            df = df.drop(columns=[c for (c,) in cur.fetchall() if c in df.columns])
            cols = [c for c in df.columns]
            buf = io.StringIO()
            df.to_csv(buf, index=False, header=False, quoting=csv.QUOTE_MINIMAL, na_rep="\\N")
            buf.seek(0)
            collist = ", ".join(f'"{c}"' for c in cols)
            cur.copy_expert(f"COPY \"{schema}\".\"{table}\" ({collist}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
            for c in ident:
                cur.execute(f'SELECT setval(pg_get_serial_sequence(%s, %s), GREATEST((SELECT COALESCE(MAX("{c}"),0) FROM "{schema}"."{table}"),1))',
                            (f'"{schema}"."{table}"', c))
                cur.execute(f'ALTER TABLE "{schema}"."{table}" ALTER COLUMN "{c}" SET GENERATED ALWAYS')
            cur.execute(f'SELECT count(*) FROM "{schema}"."{table}"')
            counts[f"{schema}.{table}"] = cur.fetchone()[0]
            exp = info["row_count"]
            if counts[f"{schema}.{table}"] != exp:
                print(f"  MISMATCH {schema}.{table}: loaded {counts[f'{schema}.{table}']} expected {exp}")
                mismatches.append(f"{schema}.{table}")
    conn.close()
    print(f"restored {len(counts)} tables, {sum(counts.values()):,} rows in {time.time() - t0:.1f}s")
    return mismatches


def run(cmd: list[str], practice: bool = False) -> int:
    url = local_url(practice)
    env = dict(os.environ, LOCAL_PG_URL=url, SUPABASE_DB_URL=url, SUPABASE_DIRECT_URL=url, SUPABASE_KEY="local-dummy",
               DATABASE_URL=url, PYTHONIOENCODING="utf-8", PYTHONPATH=str(REPO))
    # belt and braces: the child must resolve to the throwaway server before anything else runs
    chk = subprocess.run([sys.executable, "-c",
                          "from analytics.config import get_settings;from urllib.parse import urlparse;u=urlparse(get_settings().supabase_db_url);"
                          f"import sys;sys.exit(0 if (u.hostname,u.port)==('127.0.0.1',{PORT}) else 7)"], cwd=REPO, env=env)
    if chk.returncode != 0:
        sys.exit("REFUSED: child process would not resolve to the throwaway database")
    if practice:
        print(f"[{PRACTICE_MARKER}] on {PRACTICE_DB}: everything below runs on the practice copy", flush=True)
    return subprocess.call(cmd, cwd=REPO, env=env)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "start":
        start()
    elif a[0] == "stop":
        stop()
    elif a[0] == "restore":
        restore(Path(a[1]))
    elif a[0] == "practice":
        make_practice()
    elif a[0] == "run":
        head = a[1:a.index("--")] if "--" in a else []
        sys.exit(run(a[a.index("--") + 1:] if "--" in a else a[1:], practice="--practice" in head))
    elif a[0] == "url":
        print(local_url())
