"""scripts/demo_session.py - load a month of sales that did not come from SSM, run the real monthly batch on it, and roll any loaded month back (2026-11-06).

    python -m scripts.demo_session status [--json]                                  # read only: which months are loaded, what each can roll back to
    python -m scripts.demo_session check-file --file F [--json]                     # which month is this file for (from its contents), would it load? writes nothing
    python -m scripts.demo_session load --file F --by NAME [--calendar-factor on] [--accept-waiting] [--target-public]
    python -m scripts.demo_session rollback --month YYYY-MM --by NAME --yes [--target-public]

LOAD does, in one command and in this order: (1) reads the file and its month, refuses what cannot load; (2) takes a CHECKPOINT of the system as it is
(analytics/demo_session.py); (3) optionally accepts the orders of the plan that still wait for a decision, because the monthly batch refuses to plan the
next month while one waits; (4) writes the file's rows labelled is_demo = true, _src_file = TAG; (5) runs scripts.run_month (ABC, forecast, safety stock,
order plan, marts); (6) records what the load produced. A month can follow a month: after March loads, April loads on top of it, each with its own checkpoint.

ROLLBACK of a month restores the checkpoint taken before that month loaded, which also removes every month loaded after it. It is ONE transaction that
puts back exactly the rows that differ in every table of app, public, mart and demo (scripts/demo_revert.py), restores the demand view and mart.data_kind
from the text saved in the checkpoint, and fingerprints EVERY table (copied or not) and EVERY view and function against the checkpoint's; it rolls back
unless all of them match. After the commit it reads the order plan (rows and pieces must equal what the checkpoint recorded, and no later plan may
exist) and, when this returns the system to its original state, runs the pinned-figure check (scripts.snapshot_published_figures --verify). The
checkpoints are dropped only if all of that passed. A failure keeps them and exits non-zero: nothing is hidden.

WHAT IS NOT PUT BACK (demo_revert.EXCLUDED_TABLES): app.audit_log (append-only by trigger), app.user_session, app.auth_token. Everything else a person saved
after the checkpoint, decisions on the Reorder page included, is put back: that is what "exactly as it was" means.

THE GATE. On a database that is not this machine's throwaway server, load and rollback need --target-public AND an attestation for THIS code
(docs/MONTH_LOAD_REHEARSAL.json, written by scripts/month_load_rehearsal.py only after load, load, rollback, rollback restored a restored copy exactly at
every step). The attestation carries a hash of the files that make the load and the rollback: editing one invalidates it. It is committed, so a
hosted server running this commit has it without a terminal; nothing depends on an environment variable.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analytics import demo_session as ds  # noqa: E402
from analytics.month_file import read_month_file  # noqa: E402
from scripts import demo_rehearsal, demo_revert  # noqa: E402

PRINCIPAL = "unilever"
RESULT_FILE = REPO / "local" / "month_rollback_last.json"          # git-ignored
FACT_TABLES = ("unilever_sku_demand_fact", "sales_fact", "inventory_fact", "sellout_fact", "salesreturn_fact", "purchase_fact")
PLAN_SQL = """SELECT count(*), coalesce(round(sum(lr.q_i)::numeric), 0) FROM lp_recommendation lr
               JOIN product_dimension pd ON pd.product_key = lr.product_key
               WHERE pd.principal = %(principal)s AND lr.planning_cycle_date = %(cycle)s AND lr.lp_run_key IS NOT NULL
                 AND lr.status IN ('pending', 'accepted', 'dismissed')"""
NEWEST_CYCLE_SQL = """SELECT max(lr.planning_cycle_date) FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
                      WHERE pd.principal = %(principal)s AND lr.lp_run_key IS NOT NULL"""
LATER_SQL = """SELECT count(*) FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
               WHERE pd.principal = %(principal)s AND lr.planning_cycle_date > %(cycle)s"""
WAITING_SQL = """SELECT count(*) FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
                 WHERE pd.principal = %(principal)s AND lr.planning_cycle_date = %(cycle)s AND lr.lp_run_key IS NOT NULL
                   AND lr.status = 'pending' AND lr.q_i > 0 AND lr.closed_at IS NULL"""
LATEST_SALES_SQL = f"""SELECT max(calendar_month) FROM unilever_sku_demand_fact WHERE NOT is_demo OR (is_demo AND _src_file = '{ds.TAG}')"""
KNOWN_SKUS_SQL = """SELECT DISTINCT ON (sku_code) sku_code, product_key, region, gsv FROM unilever_sku_demand_fact
                    WHERE is_demo = false ORDER BY sku_code, calendar_month DESC"""
INSERT_SQL = """INSERT INTO unilever_sku_demand_fact (product_key, sku_code, calendar_month, region, quantity_sold, net_amount, _src_file, _src_sheet,
                                                      is_demo, gsv, fill_source) VALUES %s"""
SESSION_DDL = """CREATE TABLE "{schema}"._session (
    state text NOT NULL, month text NOT NULL, taken_at timestamptz NOT NULL, taken_by text NOT NULL, baseline_cycle text NOT NULL,
    baseline_rows int NOT NULL, baseline_pieces bigint NOT NULL, defs_fingerprint text NOT NULL,
    loaded_at timestamptz, loaded_by text, file_name text, file_basis text, sales_rows int, plan_cycle text, plan_rows int, plan_pieces bigint, note text)"""


def target_name() -> str:
    """host/database of this run, so a result file left by another database is never shown as this one's."""
    u = urlparse(os.environ.get("SUPABASE_DB_URL") or "")
    return f"{u.hostname}/{u.path.lstrip('/')}"


def say(step: str, text: str) -> None:
    print(f"[{step}] {text}", flush=True)


def connect(url_env: str = "SUPABASE_DB_URL"):
    return demo_revert.connect(url_env)


def plan_figures(cur, cycle) -> tuple[int, int]:
    cur.execute(PLAN_SQL, {"principal": PRINCIPAL, "cycle": cycle})
    rows, pieces = cur.fetchone()
    return int(rows), int(pieces)


def gate(is_local: bool, target_public: bool) -> None:
    """A database that is not on this machine needs the flag and an attestation of THIS code (scripts/demo_rehearsal.py)."""
    if is_local:
        return
    if not target_public:
        raise SystemExit("REFUSED: this is not the local throwaway server; pass --target-public")
    passed, why = demo_rehearsal.ok()
    if not passed:
        raise SystemExit(f"REFUSED: {why}")


# ---------------------------------------------------------------------------------------------------------------- the file

def expected_month(cur) -> str | None:
    """The month a file must be for: the one after the latest month of sales, real or loaded with the label. A month that was started and did not
    finish (its rollback point exists, its state is not 'loaded') comes first: it is finished or rolled back before another can start."""
    unfinished = [c["month"] for c in ds.checkpoints(cur) if c.get("state") in ("taken", "failed")]
    if unfinished:
        return unfinished[-1]
    cur.execute(LATEST_SALES_SQL)
    latest = cur.fetchone()[0]
    return ds.next_month(str(latest)[:7]) if latest else None


def check_file(conn, path: Path) -> dict:
    """What the file is for and whether it can load. Read only. The month is read from the file's contents; the name is never consulted."""
    mf = read_month_file(path)
    problems = list(mf.problems)
    out = {"ok": False, "period": mf.period, "basis": mf.basis, "first_day": mf.first_day, "last_day": mf.last_day, "rows": len(mf.rows),
           "expected_month": None, "resume": False, "problems": problems}
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    expected = expected_month(cur)
    out["expected_month"] = expected
    cps = {c["month"]: c for c in ds.checkpoints(cur)}
    if mf.ok:
        period = mf.period
        half = cps.get(period)
        resume = bool(half and half.get("state") in ("taken", "failed"))
        out["resume"] = resume
        if resume:
            pass        # a load that stopped partway: the same file finishes it
        elif half and half.get("state") == "loaded":
            problems.append(f"{period} is already loaded. Roll it back first if it has to be loaded again")
        elif expected and period != expected:
            unfinished = [m for m, c in cps.items() if c.get("state") in ("taken", "failed")]
            if unfinished:
                problems.append(f"{unfinished[-1]} was started and has not finished: run it again with its own file, or roll it back, before another month")
            elif period < expected:
                problems.append(f"this file is for {period}, which is already in the system (the next month is {expected})")
            else:
                problems.append(f"this file is for {period}, but {expected} has not been loaded yet. Load {expected} first")
        if not resume:
            cur.execute("SELECT count(*) FILTER (WHERE NOT is_demo), count(*) FILTER (WHERE is_demo AND _src_file = %s) FROM unilever_sku_demand_fact WHERE calendar_month = %s",
                        (ds.TAG, period))
            real, loaded = cur.fetchone()
            if real:
                problems.append(f"{real} real sales rows already exist for {period}: a generated file never writes over real sales")
            if loaded and not (half and half.get("state") == "loaded"):
                problems.append(f"{loaded} generated rows already exist for {period}")
        if not resume:
            # The plan this month writes opens from the stock count of the month itself, or (projected from it) of the month before: scripts/run_lp.opening_counts.
            # With neither in the system the plan step refuses AFTER the sales were written, so it is refused here, before anything is.
            prev = f"{int(period[:4]) - (period[5:] == '01')}-{(int(period[5:]) - 2) % 12 + 1:02d}"
            cur.execute("SELECT count(*) FROM inventory_fact_real WHERE principal = %s AND _period = ANY(%s)", (PRINCIPAL, [period, prev]))
            if not cur.fetchone()[0]:
                problems.append(f"the {ds.next_month(period)} plan opens from the stock count of {period} (or, projected from it, of {prev}) and neither is in the system, "
                                f"so {period} cannot be planned. Load that month's stock count first")
        cur.execute(KNOWN_SKUS_SQL)
        known = {sku for sku, *_ in cur.fetchall()}
        unknown = [r["sku_code"] for r in mf.rows if r["sku_code"] not in known]
        if unknown:
            problems.append(f"{len(unknown)} product(s) in the file are not in the sales history (first: {', '.join(unknown[:3])})")
    conn.rollback()
    out["ok"] = mf.ok and not problems
    out["message"] = (f"{len(mf.rows)} products for {mf.period}" + (f", read from {mf.basis}" if mf.basis else "")) if out["ok"] else "; ".join(problems[:4])
    out["_rows"] = mf.rows
    return out


# ---------------------------------------------------------------------------------------------------------------- load

def take_checkpoint(conn, month: str, by: str, cycle, baseline: tuple[int, int]) -> None:
    """Copy what a month can change, save both definitions, and open the labelled-row window. ONE transaction: a checkpoint exists whole or not at all."""
    cur = conn.cursor()
    cur.execute("SET LOCAL statement_timeout = 0")
    defs = ds.read_definitions(cur)
    in_force = ds.swap_in_force(cur)
    if not in_force:
        ds.admitting_view_sql(defs["view"]), ds.admitting_function_sql(defs["function"])      # refuses a definition it does not know
    fingerprint = ds.definitions_fingerprint(cur)
    schema = ds.checkpoint_schema(month)
    manifest = demo_revert.take_snapshot(conn, ds.month_tag(month), uncopied=demo_revert.UNCOPIED, commit=False)
    cur.execute(f'CREATE TABLE "{schema}"._definitions (name text PRIMARY KEY, ddl text NOT NULL)')
    cur.execute(f'INSERT INTO "{schema}"._definitions VALUES (%s, %s), (%s, %s)', ("view", defs["view"], "function", defs["function"]))
    cur.execute(SESSION_DDL.format(schema=schema))
    cur.execute(f'INSERT INTO "{schema}"._session (state, month, taken_at, taken_by, baseline_cycle, baseline_rows, baseline_pieces, defs_fingerprint) '
                "VALUES ('taken', %s, now(), %s, %s, %s, %s, %s)", (month, by, f"{cycle:%Y-%m-%d}", baseline[0], baseline[1], fingerprint[0]))
    if not in_force:
        cur.execute(ds.admitting_view_sql(defs["view"]))
        cur.execute(ds.admitting_function_sql(defs["function"]))
    if not ds.permits_labelled_rows(cur):
        raise RuntimeError("the window did not open: the demand view does not admit the label after the change")
    conn.commit()
    copied = sum(1 for k in manifest if k not in demo_revert.UNCOPIED)
    say("load", f"rollback point saved: {copied} tables copied, {len(manifest)} fingerprinted ({schema})")


def accept_waiting(by: str, cycle: str, month: str) -> int:
    """Accepts every pending ordering row of `cycle`, through recommendations.decide_row: the one place a decision is written, with its guards, its
    planning-mart copy and its receipt ledger. The monthly batch refuses to plan the next month while such a row waits. Rolling the month back puts
    every one of these back."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from backend import audit
    from backend.routers import recommendations as rec
    engine = create_engine(os.environ["SUPABASE_DB_URL"])
    accepted = refused = 0
    reason = f"Accepted at the recommended quantity when {month} sales were loaded."
    with Session(engine) as db:
        keys = [r[0] for r in db.execute(text(
            "SELECT recommendation_key FROM lp_recommendation WHERE planning_cycle_date = :cycle AND status = 'pending' AND q_i > 0 AND closed_at IS NULL"),
            {"cycle": cycle}).all()]
        present = rec._present(db)
        db.rollback()
        for key in keys:
            try:
                rec.decide_row(db, present, key=key, status="accepted", reason=reason, decided_quantity=None, decided_by=by)
                db.commit()
                accepted += 1
            except Exception as exc:  # noqa: BLE001 - a row the real guards refuse stays pending, and is said so
                db.rollback()
                refused += 1
                print(f"  row {key} left pending: {getattr(exc, 'detail', exc)}", flush=True)
        audit.record(db, "Waiting Orders Accepted", f"{accepted} orders of the {cycle[:7]} plan accepted at their recommended quantity while loading {month}; "
                     f"{refused} left pending.", email=by, name=None, role="admin")
        db.commit()
    say("load", f"{accepted} waiting orders of the {cycle[:7]} plan accepted at their recommended quantity" + (f", {refused} left pending" if refused else ""))
    return refused


def write_rows(conn, rows: list[dict], month: str) -> int:
    from psycopg2.extras import execute_values
    cur = conn.cursor()
    cur.execute(KNOWN_SKUS_SQL)
    known = {sku: (key, region, gsv) for sku, key, region, gsv in cur.fetchall()}
    values = []
    for r in rows:
        key, region, gsv = known[r["sku_code"]]
        values.append((key, r["sku_code"], month, r["region"] or region, r["quantity_sold"], r["net_amount"], ds.TAG, ds.TAG, True,
                       r["gsv"] if r["gsv"] is not None else gsv, None))
    # The retired synthetic_v2 backfill (is_demo, fill_source set, read by nothing) holds the same (sku_code, month) keys, and the table's unique key lets
    # one row per product and month exist. Those rows go for as long as the month is loaded; rolling it back puts every one of them back.
    cur.execute("DELETE FROM unilever_sku_demand_fact WHERE calendar_month = %s AND is_demo AND fill_source IS NOT NULL", (month,))
    retired = cur.rowcount
    execute_values(cur, INSERT_SQL, values)
    cur.execute("SELECT count(*) FROM unilever_sku_demand_fact_real WHERE calendar_month = %s AND is_demo", (month,))
    seen = cur.fetchone()[0]
    if seen != len(values):
        conn.rollback()
        raise SystemExit(f"REFUSED: {len(values)} rows written but the demand view shows {seen}: nothing was loaded")
    conn.commit()
    if retired:
        say("load", f"{retired} retired placeholder rows for {month} set aside while it is loaded (a rollback puts them back)")
    return len(values)


def mark(conn, month: str, **fields) -> None:
    cur = conn.cursor()
    sets = ", ".join(f"{k} = %s" for k in fields)
    cur.execute(f'UPDATE "{ds.checkpoint_schema(month)}"._session SET {sets}', tuple(fields.values()))
    conn.commit()


def load_month(args) -> int:
    conn, is_local = connect()
    try:
        gate(is_local, args.target_public)
        path = Path(args.file)
        checked = check_file(conn, path)
        if not checked["ok"]:
            raise SystemExit("REFUSED: " + checked["message"])
        rows, month, resume = checked.pop("_rows"), checked["period"], checked["resume"]
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cps = ds.checkpoints(cur)
        cycle = datetime.date.fromisoformat(f"{month}-01")
        cur.execute(NEWEST_CYCLE_SQL, {"principal": PRINCIPAL})
        newest = cur.fetchone()[0]
        if newest != cycle:
            conn.rollback()
            raise SystemExit(f"REFUSED: the newest order plan is {newest:%Y-%m}, not {month}: this database is not where {month} is next")
        cur.execute(WAITING_SQL, {"principal": PRINCIPAL, "cycle": cycle})
        waiting = int(cur.fetchone()[0])
        baseline = plan_figures(cur, cycle)
        conn.rollback()
        if waiting and not args.accept_waiting:
            raise SystemExit(f"REFUSED: {waiting} orders of the {month} plan still await a decision. Decide them on the Reorder page, or choose to accept them at the "
                             "recommended quantity as part of this load")
        say("load", f"running: {month} ({len(rows)} products, read from {checked['basis']}); the {month} plan is {baseline[0]} rows / {baseline[1]:,} pieces")
        if not resume:
            take_checkpoint(conn, month, args.by, cycle, baseline)
        else:
            say("load", f"{month} was started earlier: its rollback point is kept, the load continues")
        if waiting and accept_waiting(args.by, f"{cycle:%Y-%m-%d}", month):
            mark(conn, month, state="failed", note="some waiting orders could not be accepted")
            raise SystemExit("REFUSED: some waiting orders could not be accepted, so the month was not loaded. Roll it back, or decide them on the Reorder page")
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM unilever_sku_demand_fact WHERE is_demo AND _src_file = %s AND calendar_month = %s", (ds.TAG, month))
        have = cur.fetchone()[0]
        conn.rollback()
        if have:
            say("load", f"{have} sales rows for {month} are already written")
        else:
            n = write_rows(conn, rows, month)
            say("load", f"{n} sales rows for {month} written, every one is_demo = true and labelled {ds.TAG}: generated, not SSM's")
        mark(conn, month, state="taken", file_name=path.name if len(path.name) < 120 else path.name[:120], file_basis=checked["basis"], sales_rows=len(rows))
    finally:
        conn.close()
    env = {**os.environ, "SSM_DEMO_SESSION": "month_load", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    cmd = [sys.executable, "-m", "scripts.run_month", "--month", month, "--calendar-factor", args.calendar_factor,
           "--approved-by", args.by, "--expect-month", month, "--target-public"]
    rc = subprocess.run(cmd, cwd=REPO, env=env).returncode
    conn, _ = connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        plan_cycle = datetime.date.fromisoformat(f"{ds.next_month(month)}-01")
        rows_n, pieces = plan_figures(cur, plan_cycle)
        conn.rollback()
        if rc == 0 and rows_n:
            mark(conn, month, state="loaded", loaded_at=datetime.datetime.now(datetime.timezone.utc), loaded_by=args.by,
                 plan_cycle=f"{plan_cycle:%Y-%m-%d}", plan_rows=rows_n, plan_pieces=pieces)
            # Released only AFTER the new month loaded: a month that fails (a third month needs its own stock count, and the plan refuses without it) must never
            # cost the oldest rollback point. For that moment storage holds MAX_CHECKPOINTS + 1 copies; a checkpoint that does not fit fails whole, before any write.
            cps = ds.checkpoints(conn.cursor())
            conn.rollback()
            while len(cps) > ds.MAX_CHECKPOINTS:
                oldest = cps.pop(0)
                cur = conn.cursor()
                cur.execute(f'DROP SCHEMA "{oldest["schema"]}" CASCADE')
                conn.commit()
                say("load", f"rollback point for {oldest['month']} released: that month can no longer be rolled back, only the {ds.MAX_CHECKPOINTS} newest loads can")
            say("load", f"{month} is loaded: the {plan_cycle:%Y-%m} plan is {rows_n} rows, {pieces:,} pieces")
            return 0
        mark(conn, month, state="failed", note=f"the run exited {rc}")
        say("load", f"{month} did not finish (exit {rc}). Run it again to continue, or roll {month} back")
        return rc or 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------------------------- status

def status(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cps = ds.checkpoints(cur)
    out = {"window_in_force": ds.swap_in_force(cur), "expected_month": expected_month(cur), "loaded": [], "plan": None, "newest_cycle": None,
           "max_rollback_points": ds.MAX_CHECKPOINTS}
    counts = {m["month"]: m["rows"] for m in ds.loaded_months(cur)}
    cur.execute(NEWEST_CYCLE_SQL, {"principal": PRINCIPAL})
    cycle = cur.fetchone()[0]
    if cycle:
        out["newest_cycle"] = f"{cycle:%Y-%m}"
        out["plan"] = dict(zip(("rows", "pieces"), plan_figures(cur, cycle)))
    for c in cps:
        entry = {"month": c["month"], "state": c["state"], "taken_at": c.get("taken_at"), "taken_by": c.get("taken_by"), "loaded_at": c.get("loaded_at"),
                 "loaded_by": c.get("loaded_by"), "file_name": c.get("file_name"), "file_basis": c.get("file_basis"), "sales_rows": counts.get(c["month"], c.get("sales_rows")),
                 "plan": ({"cycle": str(c["plan_cycle"])[:7], "rows": c["plan_rows"], "pieces": c["plan_pieces"]} if c.get("plan_rows") is not None else None),
                 "restores_to": {"cycle": str(c.get("baseline_cycle"))[:7], "rows": c.get("baseline_rows"), "pieces": c.get("baseline_pieces")},
                 "note": c.get("note")}
        out["loaded"].append(entry)
    known = {e["month"] for e in out["loaded"]}
    out["loaded_without_rollback_point"] = [m for m in counts if m not in known]       # released by the history limit
    conn.rollback()
    return json.loads(json.dumps(out, default=str))


# ---------------------------------------------------------------------------------------------------------------- rollback

def rollback_month(conn, month: str, by: str, is_local: bool, target_public: bool) -> int:
    gate(is_local, target_public)
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cps = ds.checkpoints(cur)
    conn.rollback()
    chosen = next((c for c in cps if c["month"] == month), None)
    if chosen is None:
        raise SystemExit(f"REFUSED: there is no rollback point for {month}: it was never loaded, or it is older than the {ds.MAX_CHECKPOINTS} newest loads")
    if chosen["state"] == "unreadable":
        raise SystemExit(f"REFUSED: the rollback point for {month} cannot be read")
    later = [c for c in cps if c["month"] > month]
    tag = ds.month_tag(month)
    say("rollback", f"1/4 {month}: restoring every table and both definitions" + (f", which also removes {', '.join(c['month'] for c in later)}" if later else "")
        + "; one transaction, rolled back unless every fingerprint equals the checkpoint's")

    def restore_definitions(cur) -> list[str]:
        cur.execute(f'SELECT name, ddl FROM "{chosen["schema"]}"._definitions')
        saved = dict(cur.fetchall())
        cur.execute(ds.restoring_view_sql(saved["view"]))
        cur.execute(saved["function"])
        digest, n = ds.definitions_fingerprint(cur)
        return [] if digest == chosen["defs_fingerprint"] else [f"the views and functions ({n} of them) do not fingerprint as they did before {month} was loaded"]

    touched = demo_revert.revert(conn, tag, after_tables=restore_definitions)
    for line in touched:
        print("  " + line, flush=True)
    say("rollback", f"1/4 done: {len(touched)} table(s) put back; every table, view and function equals what it was")
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cycle = datetime.date.fromisoformat(str(chosen["baseline_cycle"])[:10])
    now = plan_figures(cur, cycle)
    cur.execute(LATER_SQL, {"principal": PRINCIPAL, "cycle": cycle})
    later_plans = cur.fetchone()[0]
    digest, n_defs = ds.definitions_fingerprint(cur)
    window_shut = not ds.swap_in_force(cur)
    conn.rollback()
    base = (chosen["baseline_rows"], chosen["baseline_pieces"])
    failures = []
    if digest != chosen["defs_fingerprint"]:
        failures.append(f"after the commit the {n_defs} views and functions do not fingerprint as they did before {month}")
    if now != base:
        failures.append(f"plan {cycle:%Y-%m} reads {now[0]} rows / {now[1]:,} pieces, not the {base[0]} / {base[1]:,} it was before {month}")
    if later_plans:
        failures.append(f"{later_plans} plan rows of a later cycle survived")
    say("rollback", f"2/4 plan {cycle:%Y-%m}: {now[0]} rows, {now[1]:,} pieces (before {month}: {base[0]} / {base[1]:,}); later plans: {later_plans}")
    pins_exit = None
    if window_shut:
        say("rollback", "3/4 back at the original state: the pinned figures (scripts.snapshot_published_figures --verify) ...")
        pins = subprocess.run([sys.executable, "-m", "scripts.snapshot_published_figures", "--verify"], cwd=REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env={**os.environ, "PYTHONUTF8": "1"})
        pins_exit = pins.returncode
        tail = [ln for ln in (pins.stdout + pins.stderr).strip().splitlines() if ln.strip()][-3:]
        if pins.returncode != 0:
            failures.append("the pinned figures do not reproduce")
        say("rollback", "3/4 " + ("pinned figures reproduce: " if pins.returncode == 0 else "PINNED FIGURES DO NOT REPRODUCE: ") + " | ".join(tail))
    else:
        say("rollback", "3/4 earlier months are still loaded, so the original pinned figures are checked when they are rolled back too")
    result = {"when": datetime.datetime.now(datetime.timezone.utc).isoformat(), "target": target_name(), "month": month, "by": by, "passed": not failures,
              "failures": failures, "restored_to": list(base), "after": list(now), "removed_months": [month] + [c["month"] for c in later],
              "tables_changed_back": touched, "pins_exit": pins_exit}
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    if failures:
        say("rollback", "NOT FINISHED: " + "; ".join(failures) + ". The rollback points are kept. Nothing was dropped.")
        return 1
    cur = conn.cursor()
    for c in [chosen, *later]:
        cur.execute(f'DROP SCHEMA "{c["schema"]}" CASCADE')
    conn.commit()
    say("rollback", f"4/4 ROLLED BACK AND PROVEN: {month} is no longer loaded; plan {cycle:%Y-%m} = {now[0]} rows, {now[1]:,} pieces; every table, view and function equals what it was")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["status", "check-file", "load", "rollback"])
    ap.add_argument("--by", default="system")
    ap.add_argument("--file")
    ap.add_argument("--month")
    ap.add_argument("--calendar-factor", default="on", choices=["on", "off"])
    ap.add_argument("--accept-waiting", action="store_true", help="accept the orders of the plan that still wait for a decision, as part of the load")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--target-public", action="store_true", help="allow a write to a database that is not the local throwaway server")
    ap.add_argument("--url-env", default="SUPABASE_DB_URL")
    args = ap.parse_args(argv)
    if args.cmd == "load":
        if not args.file:
            raise SystemExit("--file is required")
        return load_month(args)
    conn, is_local = connect(args.url_env)
    try:
        if args.cmd == "status":
            out = status(conn)
            print(json.dumps(out) if args.json else json.dumps(out, indent=2))
            return 0
        if args.cmd == "check-file":
            if not args.file:
                raise SystemExit("--file is required")
            out = check_file(conn, Path(args.file))
            out.pop("_rows")
            print(json.dumps(out))
            return 0
        if not args.yes or not args.month:
            raise SystemExit("rollback needs --month YYYY-MM and --yes")
        return rollback_month(conn, args.month, args.by, is_local, args.target_public)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
