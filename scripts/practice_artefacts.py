"""
scripts/practice_artefacts.py - list everything a practice month writes, and fail on anything that does not say what it is.

    python -m scripts.local_pg start
    python -m scripts.local_pg restore backups/<full_backup_...>     # ssm_local, the copy the practice copy is made from
    python -m scripts.practice_artefacts                             # about 5 minutes
    python -m scripts.practice_artefacts --settle-decisions          # (used by the above, on ssm_practice only)

A practice run's output was found unlabelled in three separate places before this existed, each fixed where it was found. This
looks for the class instead: it re-makes ssm_practice, fingerprints every file in the repo and every table, runs the month the way
docs say (generated sales, the plan's decisions, plan, close), fingerprints again, and checks each difference:

    file    PRACTICE_MARKER near its start
    row     practice_run filled (scripts/local_pg PRACTICE_ROW_LABEL_SQL), for every row ssm_local does not hold identically.
            A deleted row leaves nothing to mark, so deletions are counted and printed.
    route   every GET route of the real app, on ssm_practice: 409 practice_copy_not_served, or a /batch answer with practice_note,
            or /health

Exit 1 names what fails. Writes to ssm_practice and to the files the run itself writes, and nothing else: never live
(local_pg.local_url refuses any other server). Not part of scripts/check.sh: it needs the local Postgres and takes minutes.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import local_pg  # noqa: E402
from scripts.report_target import PRACTICE_MARKER, is_practice_target  # noqa: E402

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "pg_throwaway", "dist", ".pytest_cache", ".ruff_cache", "backups"}
SKIP_FILES = {"pg_throwaway.log"}   # the server's own log, no output of the run
MARKER_WINDOW = 400                 # bytes: a reader sees it first
MONTH = "2026-03"
OUR_SCHEMAS = "('public', 'mart', 'demo', 'app')"
ROW_HASH = "md5((to_jsonb(x) - 'practice_run')::text)"


def file_state() -> dict[str, tuple[int, int]]:
    out = {}
    for root, dirs, names in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name not in SKIP_FILES:
                path = Path(root) / name
                try:
                    st = path.stat()
                except OSError:
                    continue
                out[path.relative_to(REPO).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


def changed_files(before: dict, after: dict) -> list[str]:
    return sorted(k for k, v in after.items() if before.get(k) != v)


def file_has_marker(head: bytes) -> bool:
    return PRACTICE_MARKER.encode() in head[:MARKER_WINDOW]


def unmarked_files(names: list[str]) -> list[str]:
    bad = []
    for name in names:
        with open(REPO / name, "rb") as fh:
            if not file_has_marker(fh.read(MARKER_WINDOW)):
                bad.append(name)
    return bad


def _connect(practice: bool):
    import psycopg2
    return psycopg2.connect(local_pg.local_url(practice))


def table_names(cur) -> list[str]:
    cur.execute(f"""SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition AND n.nspname IN {OUR_SCHEMAS} ORDER BY 1""")
    return [r[0] for r in cur.fetchall()]


def table_state(cur) -> dict[str, tuple]:
    out = {}
    for table in table_names(cur):
        cur.execute(f"SELECT COUNT(*), COALESCE(SUM(hashtextextended({ROW_HASH}, 0)::numeric), 0)::text FROM {table} x")
        out[table] = tuple(cur.fetchone())
    return out


def row_report(table: str) -> dict:
    """Written (a row ssm_local does not hold identically), how many of those carry no label, and deleted."""
    practice, local = _connect(True), _connect(False)
    try:
        cur = practice.cursor()
        cur.execute(f"SELECT {ROW_HASH}, practice_run IS NOT NULL FROM {table} x")
        rows = cur.fetchall()
        cur = local.cursor()
        cur.execute(f"SELECT {ROW_HASH} FROM {table} x")
        started = {r[0] for r in cur.fetchall()}
    finally:
        practice.close()
        local.close()
    written = [(h, marked) for h, marked in rows if h not in started]
    return {"rows": len(rows), "written": len(written), "unmarked": sum(1 for _, marked in written if not marked),
            "deleted": len(started - {h for h, _ in rows})}


def route_verdict(path: str, status, body) -> str | None:
    """None when this answer says what it is, else why not."""
    if path == "/health":
        return None
    if path.startswith("/batch"):
        if status != 200:   # a request this check cannot fill in holds no figure
            return None
        return None if isinstance(body, dict) and body.get("practice_note") else "a /batch answer with no practice_note"
    if status == 409 and isinstance(body, dict) and body.get("code") == "practice_copy_not_served":
        return None
    return f"answered {status} on the practice copy"


def api_check() -> int:
    """Runs inside the practice connection (local_pg run --practice): every GET route of the real app."""
    os.environ["MONTHLY_BATCH_ENABLED"] = "true"
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    from backend.auth_utils import create_access_token
    from backend.deps import get_current_user, get_token_payload
    from backend.main import app

    app.dependency_overrides[get_current_user] = get_token_payload
    token = create_access_token(user_id=1, email="artefacts@local", role="admin", full_name="Artefacts")
    client = TestClient(app, raise_server_exceptions=False)
    paths = set()
    for route in app.routes:
        contexts = route.effective_route_contexts() if hasattr(route, "effective_route_contexts") else [route] if isinstance(route, APIRoute) else []
        paths |= {c.path for c in contexts if "GET" in c.methods and not c.path.startswith(("/docs", "/redoc", "/openapi"))}
    failures = []
    for path in sorted(paths):
        url = re.sub(r"\{\w+(:[^}]*)?\}", "1", path) + (f"?cycle={MONTH}" if path == "/batch/feedback" else "")
        res = client.get(url, headers={"Authorization": f"Bearer {token}"})
        try:
            body = res.json()
        except ValueError:
            body = None
        why = route_verdict(path, res.status_code, body)
        print(f"  {path}: {res.status_code}{'  ' + why if why else ''}")
        if why:
            failures.append(path)
    print(f"routes: {len(paths)} GET, {len(failures)} unlabelled")
    return 1 if failures else 0


def settle_decisions() -> int:
    """Runs inside the practice connection (local_pg run --practice): accepts this month's ordering rows as recommended, through
    decide_row, so a practice run meets run_month's refusal the way a real month does and its receipts are real. A check needs no
    person to review a plan; the runbook's walkthrough makes these decisions on the Reorder page instead. It is not a way round the
    refusal: it writes real decisions, and it refuses any database but the practice copy."""
    if not is_practice_target():
        print("REFUSED: --settle-decisions runs on ssm_practice only")
        return 2
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from backend.routers import recommendations as rec
    from scripts.replay_practice_decisions import accept_as_recommended
    engine = create_engine(os.environ["SUPABASE_DB_URL"])
    with Session(engine) as db:
        keys = [row[0] for row in db.execute(text(
            "SELECT recommendation_key FROM lp_recommendation WHERE planning_cycle_date = :cycle AND status = 'pending' AND q_i > 0 AND closed_at IS NULL"),
            {"cycle": f"{MONTH}-01"}).all()]
        present = rec._present(db)
        db.rollback()
        for key in keys:
            accept_as_recommended(db, present, key, "practice_artefacts")
            db.commit()
    print(f"decisions: {len(keys)} accepted as recommended, through decide_row")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--api-check"]:
        return api_check()
    if sys.argv[1:] == ["--settle-decisions"]:
        return settle_decisions()
    local_pg.make_practice()
    conn = _connect(True)
    before_tables = table_state(conn.cursor())
    conn.close()
    before_files = file_state()

    py = sys.executable
    month = ["--month", MONTH, "--calendar-factor", "on", "--approved-by", "practice_artefacts", "--expect-month", MONTH]
    for cmd in ([py, "scripts/local_pipeline_qa.py", "synth"], [py, "-m", "scripts.practice_artefacts", "--settle-decisions"],
                [py, "-m", "scripts.run_month", *month]):
        if local_pg.run(cmd, practice=True):
            sys.exit(f"the practice run stopped at: {' '.join(cmd[1:])}")
    conn = _connect(True)
    cur = conn.cursor()
    cur.execute("SELECT SUM(q_i) FROM lp_recommendation WHERE planning_cycle_date = '2026-04-01' AND lp_run_key IS NOT NULL")
    pieces = round(cur.fetchone()[0])
    conn.close()
    if local_pg.run([py, "-m", "scripts.run_month", *month, "--close", "--expect-plan-pieces", str(pieces)], practice=True):
        sys.exit("the practice close stopped")

    conn = _connect(True)
    after_tables = table_state(conn.cursor())
    conn.close()
    failures = []

    files = changed_files(before_files, file_state())
    bad_files = unmarked_files(files)
    print(f"\nFILES written or changed: {len(files)}")
    for name in files:
        print(f"  {'NO MARKER' if name in bad_files else 'marked   '}  {name}")
    failures += bad_files

    print("\nTABLES written or changed:")
    for table in sorted(t for t in after_tables if before_tables.get(t) != after_tables[t]):
        r = row_report(table)
        print(f"  {'NO MARKER' if r['unmarked'] else 'marked   '}  {table}: {r['rows']} rows, {r['written']} written ({r['unmarked']} unlabelled), {r['deleted']} deleted")
        if r["unmarked"]:
            failures.append(table)

    print("\nAPI:")
    if local_pg.run([py, "-m", "scripts.practice_artefacts", "--api-check"], practice=True):
        failures.append("api")

    print(f"\n{json.dumps({'unlabelled': failures})}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
