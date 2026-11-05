"""scripts/demo_session.py - a labelled demonstration month on the database behind the pages, and the one command that undoes it (2026-11-05).

    python -m scripts.demo_session open   --by NAME [--target-public]      # snapshot every table, then open the window (see analytics/demo_session.py)
    python -m scripts.demo_session check-file --file F --month 2026-03     # would the demonstration loader take this file? writes nothing
    python -m scripts.demo_session load   --file F --month 2026-03         # the labelled loader: rows is_demo = true, _src_file = TAG
    python -m scripts.demo_session settle --by NAME [--target-public]      # accept the baseline plan's orders through decide_row (the Reorder page's own writer)
    python -m scripts.demo_session run    --file F --by NAME [--calendar-factor on]   # load, then the real monthly batch (scripts.run_month)
    python -m scripts.demo_session status [--json]                         # read only
    python -m scripts.demo_session undo   --yes [--target-public]          # put back every table and every definition; prove it; drop the snapshot

THE WHOLE POINT IS THAT UNDO IS PROVEN, NOT ASSUMED. undo runs one transaction that (1) puts back exactly the rows that differ, in every
table of app, public, mart and demo (scripts/demo_revert.py), (2) restores the demand view and mart.data_kind from the text saved when the
window opened, and (3) recomputes the fingerprint of every table AND of every view and function with its privileges, and rolls back
unless all of them equal the snapshot's. Only after the commit does it read the plan (rows and pieces must equal the baseline recorded at
open, and no later plan may exist) and run the pinned-figure check (scripts.snapshot_published_figures --verify). The snapshot is dropped only
when every one of those passed. A failure at any point keeps the snapshot and exits non-zero: nothing is hidden.

WHAT IS NOT PUT BACK (demo_revert.EXCLUDED_TABLES): app.audit_log (append-only by trigger), app.user_session, app.auth_token. Everything a person
saved while the window was open, decisions on the Reorder page included, is put back: that is what "exactly as it was" means.

THE GATES. open and undo write, so on any database that is not the local throwaway server they need --target-public AND a passing revert proof
(local/demo_revert_proof.json). open refuses when a session or a generated row is already there, when a fact table holds an is_demo row with no
fill_source (the widened mart.data_kind would count it), and when the connection cannot run the revert's own statements.

THE LOADER takes a CSV (sku_code, quantity_sold, net_amount; optional calendar_month, gsv, region). It writes only the month named, only for products
the sales history already knows, only when no real sales row exists for that month, and every row says is_demo = true. It is a demonstration loader,
never the real one: the real loader (scripts/run_canonical_load.py) refuses while a migration is pending, and writes is_demo = false.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analytics import demo_session as ds  # noqa: E402
from scripts import demo_rehearsal, demo_revert  # noqa: E402

PRINCIPAL = "unilever"
MONTH_DEFAULT = "2026-03"
RESULT_FILE = REPO / "local" / "demo_session_last_undo.json"          # git-ignored
FACT_TABLES = ("unilever_sku_demand_fact", "sales_fact", "inventory_fact", "sellout_fact", "salesreturn_fact", "purchase_fact")
PLAN_SQL = """SELECT count(*), coalesce(round(sum(lr.q_i)::numeric), 0) FROM lp_recommendation lr
               JOIN product_dimension pd ON pd.product_key = lr.product_key
               WHERE pd.principal = %(principal)s AND lr.planning_cycle_date = %(cycle)s AND lr.lp_run_key IS NOT NULL
                 AND lr.status IN ('pending', 'accepted', 'dismissed')"""
NEWEST_CYCLE_SQL = """SELECT max(lr.planning_cycle_date) FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
                      WHERE pd.principal = %(principal)s AND lr.lp_run_key IS NOT NULL"""
LATER_SQL = """SELECT count(*) FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
               WHERE pd.principal = %(principal)s AND lr.planning_cycle_date > %(cycle)s"""
KNOWN_SKUS_SQL = """SELECT DISTINCT ON (sku_code) sku_code, product_key, region, gsv FROM unilever_sku_demand_fact
                    WHERE is_demo = false ORDER BY sku_code, calendar_month DESC"""
INSERT_SQL = """INSERT INTO unilever_sku_demand_fact (product_key, sku_code, calendar_month, region, quantity_sold, net_amount, _src_file, _src_sheet,
                                                      is_demo, gsv, fill_source) VALUES %s"""


def target_name() -> str:
    """host/database of this run, so a result file left by another database is never shown as this one's."""
    from urllib.parse import urlparse
    u = urlparse(os.environ.get("SUPABASE_DB_URL") or "")
    return f"{u.hostname}/{u.path.lstrip('/')}"


def say(step: str, text: str) -> None:
    print(f"[{step}] {text}", flush=True)


def connect(url_env: str = "SUPABASE_DB_URL"):
    conn, is_local = demo_revert.connect(url_env)
    return conn, is_local


def plan_figures(cur, cycle) -> tuple[int, int]:
    cur.execute(PLAN_SQL, {"principal": PRINCIPAL, "cycle": cycle})
    rows, pieces = cur.fetchone()
    return int(rows), int(pieces)


# ---------------------------------------------------------------------------------------------------------------- open

def require_rehearsed(is_local: bool) -> None:
    """A database that is not on this machine needs a rehearsal of THIS code on a restored copy (scripts/demo_rehearsal.py) as well as the revert proof."""
    if is_local:
        return
    passed, why = demo_rehearsal.ok()
    if not passed:
        raise SystemExit(f"REFUSED: {why}")


def open_session(conn, by: str, is_local: bool, target_public: bool) -> None:
    demo_revert.require_write_allowed(is_local, target_public)
    require_rehearsed(is_local)
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    problems = []
    if ds.session_row(cur) is not None:
        problems.append("a demonstration session is already recorded in this database: undo it first")
    if ds.swap_in_force(cur):
        problems.append("the demand view already admits generated rows: this database is not in its original state")
    cur.execute("SELECT count(*) FROM unilever_sku_demand_fact WHERE is_demo AND _src_file = %s", (ds.TAG,))
    if cur.fetchone()[0]:
        problems.append("generated demonstration rows are already in the sales table")
    for table in FACT_TABLES:
        cur.execute(f"SELECT count(*) FROM {table} WHERE is_demo AND fill_source IS NULL")
        if cur.fetchone()[0]:
            problems.append(f"{table} holds is_demo rows with no fill_source, which the widened mart.data_kind would count as real")
    cur.execute(NEWEST_CYCLE_SQL, {"principal": PRINCIPAL})
    cycle = cur.fetchone()[0]
    baseline = plan_figures(cur, cycle) if cycle else (0, 0)
    defs = ds.read_definitions(cur)
    ds.admitting_view_sql(defs["view"]), ds.admitting_function_sql(defs["function"])      # refuses a definition it does not know
    fingerprint = ds.definitions_fingerprint(cur)
    conn.rollback()
    if problems:
        raise SystemExit("REFUSED: " + "; ".join(problems))
    say("open", f"baseline: plan {cycle:%Y-%m} = {baseline[0]} rows, {baseline[1]:,} pieces; {fingerprint[1]} views and functions fingerprinted")
    say("open", "copying every table of app, public, mart and demo into the snapshot schema ...")
    manifest = demo_revert.take_snapshot(conn, ds.SESSION_TAG)
    say("open", f"snapshot {ds.SNAP_SCHEMA}: {len(manifest)} tables, {sum(n for n, _ in manifest.values()):,} rows")
    cur = conn.cursor()
    try:
        cur.execute("SET LOCAL statement_timeout = 0")
        cur.execute(f'CREATE TABLE "{ds.SNAP_SCHEMA}"._definitions (name text PRIMARY KEY, ddl text NOT NULL)')
        cur.execute(f'INSERT INTO "{ds.SNAP_SCHEMA}"._definitions VALUES (%s, %s), (%s, %s)',
                    ("view", defs["view"], "function", defs["function"]))
        cur.execute(f'''CREATE TABLE "{ds.SNAP_SCHEMA}"._session (state text NOT NULL, opened_at timestamptz NOT NULL, opened_by text NOT NULL,
                        baseline_rows int NOT NULL, baseline_pieces bigint NOT NULL, baseline_cycle text NOT NULL, defs_fingerprint text NOT NULL)''')
        cur.execute(f'INSERT INTO "{ds.SNAP_SCHEMA}"._session VALUES (%s, now(), %s, %s, %s, %s, %s)',
                    ("open", by, baseline[0], baseline[1], f"{cycle:%Y-%m-%d}", fingerprint[0]))
        cur.execute(ds.admitting_view_sql(defs["view"]))
        cur.execute(ds.admitting_function_sql(defs["function"]))
        if not ds.permits_labelled_rows(cur):
            raise RuntimeError("the window did not open: the view does not admit the tag after the swap")
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - nothing of the window may survive a failed open
        conn.rollback()
        cur = conn.cursor()
        cur.execute(f'DROP SCHEMA IF EXISTS "{ds.SNAP_SCHEMA}" CASCADE')
        conn.commit()
        raise SystemExit(f"REFUSED: the window did not open ({exc}); the snapshot was dropped, nothing else changed")
    say("open", "OPEN. Generated rows tagged " + ds.TAG + " are admitted by the demand view and the marts until undo. Nothing was loaded yet.")


# ---------------------------------------------------------------------------------------------------------------- the file

def read_demo_file(path: Path, month: str) -> tuple[list[dict], list[str]]:
    """(rows, problems). Nothing is written. The rule is the loader's own in spirit: unknown products are refused, not skipped."""
    problems, rows = [], []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"the file could not be read as UTF-8 text: {exc}"]
    reader = csv.DictReader(text.splitlines())
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in ("sku_code", "quantity_sold", "net_amount") if c not in header]
    if missing:
        return [], [f"the file has no column {', '.join(missing)} (needs sku_code, quantity_sold, net_amount; optional calendar_month, gsv, region)"]
    seen = set()
    for n, raw in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        sku = row.get("sku_code", "")
        if not sku:
            problems.append(f"line {n}: no sku_code")
            continue
        if sku in seen:
            problems.append(f"line {n}: {sku} appears twice")
            continue
        seen.add(sku)
        if row.get("calendar_month") and row["calendar_month"][:7] != month:
            problems.append(f"line {n}: {sku} is for {row['calendar_month']}, not {month}")
            continue
        try:
            qty, net = float(row["quantity_sold"]), float(row["net_amount"])
            gsv = float(row["gsv"]) if row.get("gsv") else None
        except ValueError:
            problems.append(f"line {n}: {sku} has a quantity, amount or gsv that is not a number")
            continue
        if qty < 0 or net < 0:
            problems.append(f"line {n}: {sku} has a negative quantity or amount")
            continue
        rows.append({"sku_code": sku, "quantity_sold": qty, "net_amount": net, "gsv": gsv, "region": row.get("region") or None})
    if not rows and not problems:
        problems.append("the file has no rows")
    return rows, problems


def check_file(conn, path: Path, month: str) -> tuple[list[dict], dict, list[str]]:
    """The file's rows joined to the products the history knows. Read only."""
    rows, problems = read_demo_file(path, month)
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute(KNOWN_SKUS_SQL)
    known = {sku: (key, region, gsv) for sku, key, region, gsv in cur.fetchall()}
    cur.execute("""SELECT count(*) FILTER (WHERE NOT is_demo), count(*) FILTER (WHERE is_demo AND _src_file = %s)
                   FROM unilever_sku_demand_fact WHERE calendar_month = %s""", (ds.TAG, month))
    real_in_month, demo_in_month = cur.fetchone()
    cur.execute("SELECT max(calendar_month) FROM unilever_sku_demand_fact WHERE NOT is_demo")
    latest_real = cur.fetchone()[0]
    conn.rollback()
    if real_in_month:
        problems.append(f"{real_in_month} real sales rows already exist for {month}: a demonstration never writes over real sales")
    if demo_in_month:
        problems.append(f"{demo_in_month} generated rows already exist for {month}")
    unknown = [r["sku_code"] for r in rows if r["sku_code"] not in known]
    if unknown:
        problems.append(f"{len(unknown)} product(s) in the file are not in the sales history (first: {', '.join(unknown[:3])})")
    expected = (datetime.date.fromisoformat(f"{latest_real}-01") if isinstance(latest_real, str) else latest_real)
    if expected and f"{(expected.replace(day=28) + datetime.timedelta(days=4)):%Y-%m}" != month:
        problems.append(f"{month} is not the month after the latest real sales month ({expected:%Y-%m})")
    return rows, known, problems


def load_rows(conn, path: Path, month: str) -> int:
    cur = conn.cursor()
    if not (ds.session_row(cur) or {}).get("state") == "open" or not ds.swap_in_force(cur):
        conn.rollback()
        raise SystemExit("REFUSED: no demonstration session is open in this database: nothing was loaded")
    conn.rollback()
    rows, known, problems = check_file(conn, path, month)
    if problems:
        raise SystemExit("REFUSED: " + "; ".join(problems[:6]) + (f" (and {len(problems) - 6} more)" if len(problems) > 6 else ""))
    from psycopg2.extras import execute_values
    cur = conn.cursor()
    values = []
    for r in rows:
        key, region, gsv = known[r["sku_code"]]
        values.append((key, r["sku_code"], month, r["region"] or region, r["quantity_sold"], r["net_amount"], ds.TAG, ds.TAG, True,
                       r["gsv"] if r["gsv"] is not None else gsv, None))
    # The retired synthetic_v2 backfill (is_demo, fill_source set, read by nothing) holds the same (sku_code, month) keys: the table's unique key lets
    # one row per product and month exist. Those rows go for the window, as the practice copy's synth does, and undo puts every one back.
    cur.execute("DELETE FROM unilever_sku_demand_fact WHERE calendar_month = %s AND is_demo AND fill_source IS NOT NULL", (month,))
    retired = cur.rowcount
    if retired:
        say("load", f"{retired} retired synthetic_v2 backfill rows for {month} set aside for the window (undo puts them back)")
    execute_values(cur, INSERT_SQL, values)
    cur.execute("SELECT count(*) FROM unilever_sku_demand_fact_real WHERE calendar_month = %s AND is_demo", (month,))
    seen = cur.fetchone()[0]
    if seen != len(values):
        conn.rollback()
        raise SystemExit(f"REFUSED: {len(values)} rows written but the demand view shows {seen}: nothing was loaded")
    conn.commit()
    say("load", f"{len(values)} generated sales rows for {month}, every one is_demo = true and _src_file = {ds.TAG}; not real data, never a result")
    return len(values)


# ---------------------------------------------------------------------------------------------------------------- run

def run_batch(args) -> int:
    conn, _ = connect()
    try:
        load_rows(conn, Path(args.file), args.month) if not _march_loaded(conn, args.month) else say("load", f"{args.month} is already loaded")
    finally:
        conn.close()
    env = {**os.environ, "SSM_DEMO_SESSION": ds.SESSION_TAG, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    cmd = [sys.executable, "-m", "scripts.run_month", "--month", args.month, "--calendar-factor", args.calendar_factor,
           "--approved-by", args.by, "--expect-month", args.month, "--target-public"]
    say("run", "the monthly batch: ABC, forecast, safety stock and plan, marts, review")
    return subprocess.run(cmd, cwd=REPO, env=env).returncode


def _march_loaded(conn, month: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM unilever_sku_demand_fact WHERE is_demo AND _src_file = %s AND calendar_month = %s", (ds.TAG, month))
    n = cur.fetchone()[0]
    conn.rollback()
    return bool(n)


# ---------------------------------------------------------------------------------------------------------------- settle

SETTLE_REASON = "Accepted for the live demonstration at the recommended quantity; Undo puts it back."


def settle_orders(conn, by: str) -> int:
    """Accepts every pending ordering row of the baseline plan, through recommendations.decide_row: the one place a decision is written, with its guards,
    its planning-mart copy and its receipt ledger (what scripts/practice_artefacts --settle-decisions does on the practice copy). run_month refuses to
    plan the next month while such a row waits, and a person accepting 73 orders one by one, 27 of them flagged for review, is no demonstration. This is the
    explicit, labelled shortcut; the Reorder page stays the way to decide them for real. Only while a session is open; Undo puts every one back."""
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    row = ds.session_row(cur)
    conn.rollback()
    if not row or row["state"] != "open":
        raise SystemExit("REFUSED: no demonstration session is open in this database: no order was accepted")
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from backend import audit
    from backend.routers import recommendations as rec
    engine = create_engine(os.environ["SUPABASE_DB_URL"])
    accepted = refused = 0
    with Session(engine) as db:
        keys = [r[0] for r in db.execute(text(
            "SELECT recommendation_key FROM lp_recommendation WHERE planning_cycle_date = :cycle AND status = 'pending' AND q_i > 0 AND closed_at IS NULL"),
            {"cycle": row["baseline_cycle"]}).all()]
        present = rec._present(db)
        db.rollback()
        for key in keys:
            try:
                rec.decide_row(db, present, key=key, status="accepted", reason=SETTLE_REASON, decided_quantity=None, decided_by=f"demonstration ({by})")
                db.commit()
                accepted += 1
            except Exception as exc:  # noqa: BLE001 - a row the real guards refuse stays pending, and is said so
                db.rollback()
                refused += 1
                print(f"  row {key} left pending: {getattr(exc, 'detail', exc)}", flush=True)
        audit.record(db, "Live Demonstration Orders Accepted", f"{accepted} orders of the {row['baseline_cycle'][:7]} plan accepted at their recommended quantity for the demonstration; "
                     f"{refused} left pending. Undo puts them back.", email=by, name=None, role="demonstration")
        db.commit()
    say("settle", f"{accepted} orders of the {row['baseline_cycle'][:7]} plan accepted through decide_row" + (f", {refused} left pending" if refused else ""))
    return 1 if refused else 0


# ---------------------------------------------------------------------------------------------------------------- status

def status(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    row = ds.session_row(cur)
    out = {"open": bool(row and row["state"] == "open"), "session": None, "generated_rows": 0, "plan": None, "newest_cycle": None}
    cur.execute("SELECT count(*) FROM unilever_sku_demand_fact WHERE is_demo AND _src_file = %s", (ds.TAG,))
    out["generated_rows"] = int(cur.fetchone()[0])
    cur.execute(NEWEST_CYCLE_SQL, {"principal": PRINCIPAL})
    cycle = cur.fetchone()[0]
    if cycle:
        out["newest_cycle"] = f"{cycle:%Y-%m}"
        out["plan"] = dict(zip(("rows", "pieces"), plan_figures(cur, cycle)))
    if row:
        out["session"] = {"state": row["state"], "opened_at": row["opened_at"].isoformat(), "opened_by": row["opened_by"],
                          "baseline": {"cycle": row["baseline_cycle"][:7], "rows": row["baseline_rows"], "pieces": row["baseline_pieces"]}}
        cur.execute("""SELECT count(*) FILTER (WHERE lr.status = 'pending' AND lr.closed_at IS NULL AND lr.q_i > 0),
                              count(*) FILTER (WHERE lr.status IN ('accepted', 'dismissed'))
                       FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
                       WHERE pd.principal = %s AND lr.planning_cycle_date = %s""", (PRINCIPAL, row["baseline_cycle"]))
        waiting, decided = cur.fetchone()
        out["baseline_plan_decisions"] = {"waiting": int(waiting), "decided": int(decided)}
    conn.rollback()
    return out


# ---------------------------------------------------------------------------------------------------------------- undo

def undo_session(conn, is_local: bool, target_public: bool) -> int:
    demo_revert.require_write_allowed(is_local, target_public)
    require_rehearsed(is_local)
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    row = ds.session_row(cur)
    conn.rollback()
    if row is None:
        raise SystemExit("REFUSED: no demonstration session is recorded in this database: nothing to undo")
    saved = {}

    def restore_definitions(cur) -> list[str]:
        cur.execute(f'SELECT name, ddl FROM "{ds.SNAP_SCHEMA}"._definitions')
        saved.update(dict(cur.fetchall()))
        cur.execute(ds.restoring_view_sql(saved["view"]))
        cur.execute(saved["function"])
        digest, n = ds.definitions_fingerprint(cur)
        return [] if digest == row["defs_fingerprint"] else [f"the views and functions ({n} of them) do not fingerprint as they did at open"]

    say("undo", "1/4 putting back every table and both definitions, in one transaction; it rolls back unless every fingerprint equals the snapshot's ...")
    touched = demo_revert.revert(conn, ds.SESSION_TAG, after_tables=restore_definitions)
    for line in touched:
        print("  " + line, flush=True)
    say("undo", f"1/4 done: {len(touched)} table(s) changed back; every table and every view and function equals what it was")
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cycle = datetime.date.fromisoformat(row["baseline_cycle"])
    now = plan_figures(cur, cycle)
    cur.execute(LATER_SQL, {"principal": PRINCIPAL, "cycle": cycle})
    later = cur.fetchone()[0]
    # Read again after the commit, on its own: the window must be shut and every view and function must fingerprint as it did at open.
    digest, n_defs = ds.definitions_fingerprint(cur)
    window_shut = not ds.swap_in_force(cur)
    conn.rollback()
    base = (row["baseline_rows"], row["baseline_pieces"])
    failures = []
    if digest != row["defs_fingerprint"] or not window_shut:
        failures.append(f"after the commit the {n_defs} views and functions do not fingerprint as they did at open, or the window is still in force")
    if now != base:
        failures.append(f"plan {cycle:%Y-%m} reads {now[0]} rows / {now[1]:,} pieces, not the baseline {base[0]} / {base[1]:,}")
    if later:
        failures.append(f"{later} plan rows of a later cycle survived")
    say("undo", f"2/4 plan {cycle:%Y-%m}: {now[0]} rows, {now[1]:,} pieces (baseline {base[0]} / {base[1]:,}); later cycles: {later}")
    say("undo", "3/4 the pinned figures (scripts.snapshot_published_figures --verify) ...")
    pins = subprocess.run([sys.executable, "-m", "scripts.snapshot_published_figures", "--verify"], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ, "PYTHONUTF8": "1"})
    tail = [ln for ln in (pins.stdout + pins.stderr).strip().splitlines() if ln.strip()][-3:]
    if pins.returncode != 0:
        failures.append("the pinned figures do not reproduce")
    say("undo", "3/4 " + ("pinned figures reproduce: " if pins.returncode == 0 else "PINNED FIGURES DO NOT REPRODUCE: ") + " | ".join(tail))
    result = {"when": datetime.datetime.now(datetime.timezone.utc).isoformat(), "target": target_name(), "passed": not failures, "failures": failures,
              "baseline": list(base), "after": list(now), "tables_changed_back": touched, "pins_exit": pins.returncode}
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    if failures:
        say("undo", "NOT FINISHED: " + "; ".join(failures) + ". The snapshot is kept. Nothing was dropped.")
        return 1
    cur = conn.cursor()
    cur.execute(f'DROP SCHEMA "{ds.SNAP_SCHEMA}" CASCADE')
    conn.commit()
    if is_local:
        notrun = demo_rehearsal.month_really_ran(touched)
        if notrun:
            say("undo", "no rehearsal recorded: this month did not change " + ", ".join(notrun) + ", so it was not a whole month")
        else:
            demo_rehearsal.write(target_name(), base, now, touched)
            say("undo", "rehearsal recorded: a whole month ran on this copy and was undone exactly (scripts/demo_rehearsal.py)")
    say("undo", f"4/4 UNDONE AND PROVEN: plan {cycle:%Y-%m} = {now[0]} rows, {now[1]:,} pieces; every table, view and function equals what it was; snapshot dropped")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["open", "status", "check-file", "load", "run", "settle", "undo"])
    ap.add_argument("--by", default="demo")
    ap.add_argument("--file")
    ap.add_argument("--month", default=MONTH_DEFAULT)
    ap.add_argument("--calendar-factor", default="on", choices=["on", "off"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--target-public", action="store_true", help="allow a write to a database that is not the local throwaway server")
    ap.add_argument("--url-env", default="SUPABASE_DB_URL")
    args = ap.parse_args(argv)
    conn, is_local = connect(args.url_env)
    try:
        if args.cmd == "status":
            out = status(conn)
            print(json.dumps(out, default=str) if args.json else json.dumps(out, indent=2, default=str))
            return 0
        if args.cmd == "check-file":
            if not args.file:
                raise SystemExit("--file is required")
            rows, _, problems = check_file(conn, Path(args.file), args.month)
            out = {"ok": not problems, "rows": len(rows), "problems": problems,
                   "message": "; ".join(problems[:4]) if problems else f"{len(rows)} rows for {args.month}: the demonstration loader will take this file"}
            print(json.dumps(out))
            return 0
        if args.cmd in ("load", "run", "settle", "open", "undo"):
            demo_revert.require_write_allowed(is_local, args.target_public)
            require_rehearsed(is_local)
        if args.cmd == "open":
            open_session(conn, args.by, is_local, args.target_public)
        elif args.cmd == "load":
            if not args.file:
                raise SystemExit("--file is required")
            load_rows(conn, Path(args.file), args.month)
        elif args.cmd == "settle":
            return settle_orders(conn, args.by)
        elif args.cmd == "run":
            if not args.file:
                raise SystemExit("--file is required")
            conn.close()
            return run_batch(args)
        elif args.cmd == "undo":
            if not args.yes:
                raise SystemExit("undo needs --yes")
            return undo_session(conn, is_local, args.target_public)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
