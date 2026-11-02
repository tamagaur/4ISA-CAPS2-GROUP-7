"""
scripts/rollover_scratch_test.py - prove the rollover mechanics on a SCRATCH schema with a synthetic March 2026
(docs/ROLLOVER_DESIGN.md, section e), then drop the schema. Nothing generated reaches public, mart or any result.

    python -m scripts.rollover_scratch_test            # build ssm_rollover_test, run every check, drop it
    python -m scripts.rollover_scratch_test --keep     # leave the scratch schema for inspection (drop it yourself)

What is synthetic. ONLY March 2026 per-SKU sales, generated into the scratch schema's copy of unilever_sku_demand_fact
(seeded, a deterministic factor 0.8 to 1.2 of each product's own February), tagged _src_file = 'rollover_test_synthetic'.
The 6 Apr 2026 stock count is REAL and already loaded. Three April-cycle scaffold rows (an ABC row, forecast rows, plan
rows with an lp_run) are copied in the scratch schema only so close_cycle's "the pipeline has run" checks can pass.
Rows flagged is_demo never pass the _Real views, so they could not exercise the real code path: the real code runs on the
scratch schema, where the isolation is the schema boundary and is proved, not assumed:

  ISOLATION CHECKS (all must hold, or the run fails and says which)
   1  the scratch schema name starts ssm_ and is exactly ssm_rollover_test
   2  no migration is pending on public, and none about to be applied to scratch names app., public. or mart.
      (the hard guard in scripts/run_canonical_load.assert_scratch_migrations_safe, which also refuses the build itself)
   3  public (and mart, app) row counts and content hashes of 17 tables are identical before and after
   4  no row of any table in public, mart, app or demo contains the string rollover_test
   5  the planning mart and the mart refresh are never reached (planning_mart switched off, refresh_marts raises if called)
   6  the live plan still reads 109 rows and 435,988 pieces afterwards
   7  the scratch schema is dropped afterwards and is gone
Every statement of the scenario runs with search_path set to the scratch schema ALONE (transaction-local): a table that is
missing there fails loudly instead of falling back to public.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SCHEMA = "ssm_rollover_test"
TAG = "rollover_test"
CYCLE = datetime.date(2026, 3, 1)
NEXT_CYCLE = datetime.date(2026, 4, 1)
EXPECTED_PLAN = (109, 435988.0)    # rows, pieces: the live plan, nothing decided (the hard constraint of 2026-10-24)
# A restored backup older than the live plan reads a different (correct for its date) plan: scripts/local_pg.py runs set
# ROLLOVER_EXPECTED_PLAN="rows,pieces" to say so. The default, and every run against live, stays the line above.
if os.environ.get("ROLLOVER_EXPECTED_PLAN"):
    _r, _p = os.environ["ROLLOVER_EXPECTED_PLAN"].split(",")
    EXPECTED_PLAN = (int(_r), float(_p))

PUBLIC_FINGERPRINT_TABLES = (
    "lp_recommendation", "lp_run", "expected_receipt", "planning_cycle", "lp_quantity_change", "lp_decision_reversal",
    "lp_direct_apply_grant", "forecast_result", "inventory_fact", "unilever_sku_demand_fact", "abc_classification",
    "derived_receipt_fact", "schema_migrations", "product_dimension", "mart.planning_mart", "mart.refresh_log", "app.audit_log",
)

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        raise AssertionError(f"{name}: {detail}")


def fetch(cur, sql, params=None):
    cur.execute(sql, params or {})
    return cur.fetchall()


def fingerprints(conn) -> dict:
    """Row count and an order-independent content hash of each table, read-only, in public/app/mart."""
    out = {}
    cur = conn.cursor()
    cur.execute("BEGIN")
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute("SET LOCAL statement_timeout = '120s'")
    for t in PUBLIC_FINGERPRINT_TABLES:
        cur.execute(f"SELECT COUNT(*), COALESCE(SUM(hashtext(x::text)::numeric), 0) FROM {t} x")
        n, h = cur.fetchone()
        out[t] = (int(n), str(h))
    conn.rollback()
    return out


def tag_scan(conn) -> list[str]:
    """Tables in public, mart, app and demo that contain the scratch tag anywhere in any row."""
    cur = conn.cursor()
    cur.execute("BEGIN")
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute("SET LOCAL statement_timeout = '600s'")
    cur.execute("SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind IN ('r','p') AND n.nspname IN ('public','mart','app','demo') ORDER BY 1, 2")
    tables = cur.fetchall()
    hits = []
    for schema, table in tables:
        cur.execute(f'SELECT EXISTS (SELECT 1 FROM "{schema}"."{table}" x WHERE x::text LIKE %s)', (f"%{TAG}%",))
        if cur.fetchone()[0]:
            hits.append(f"{schema}.{table}")
    conn.rollback()
    return hits


def plan_figures() -> tuple[int, float]:
    """The live plan as GET /recommendations serves it: rows and pieces (read-only)."""
    from fastapi.encoders import jsonable_encoder
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from backend import deps, planning_mart, response_cache
    from backend.data_mode import REAL
    from backend.routers import recommendations as rec
    previous = planning_mart._STATE["schema"]
    planning_mart.use_schema(None)
    response_cache.invalidate()     # a cached answer would make the before/after comparison meaningless
    try:
        with Session(deps._get_engine()) as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            try:
                r = rec.get_recommendations(status=None, cycle="current", from_date=None, to_date=None, principal=None,
                                            mode=REAL, db=db, current_user=None)
                items = jsonable_encoder(r)["items"]
            finally:
                db.rollback()
    finally:
        # put back what it was, NEVER force 'mart': forcing it switched the planning mart on in the middle of the scenario
        # and the decisions made on the scratch copy were copied into the LIVE mart.planning_mart (first runs, 2026-10-24)
        planning_mart.use_schema(previous)
    return len(items), round(sum(i["q_i"] for i in items), 2)


# ---------------------------------------------------------------------------------------------------------------
def main(keep: bool = False) -> int:
    import psycopg2
    from dotenv import load_dotenv
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    load_dotenv(REPO / ".env")
    os.environ.setdefault("JWT_SECRET_KEY", "scratch-test-only-secret")
    os.environ.setdefault("JWT_ALGORITHM", "HS256")
    os.environ.setdefault("JWT_EXPIRY_HOURS", "1")
    os.environ["DM_DEMO_ENABLED"] = ""
    url = os.environ["SUPABASE_DB_URL"]

    from analytics import marts as analytics_marts
    from analytics import receipt_settlement
    from backend import auth_utils, deps, planning_mart
    from backend.routers import recommendations as rec
    from backend.routers import reorder_approval as ra
    from backend.schemas.recommendations import QuantityChangeRequest, RecommendationDecision, ReverseRequest
    from scripts import close_cycle as cc
    from scripts import rehearse_fills
    from scripts import run_canonical_load as rcl

    print(f"== rollover scratch test, schema {SCHEMA} ==")
    check("1 scratch schema name", SCHEMA == "ssm_rollover_test" and SCHEMA.startswith("ssm_"))
    engine = deps._get_engine()
    pg = psycopg2.connect(url)

    # 5: nothing may reach the marts. The planning mart is switched off, the refresh raises if anything calls it.
    planning_mart.use_schema(None)
    refreshed = []

    def no_refresh(*a, **k):
        refreshed.append(a)
        raise AssertionError("a mart refresh was called from the scratch test")
    real_refresh = {n: getattr(analytics_marts, n) for n in dir(analytics_marts) if n.startswith("refresh_")}
    for n in real_refresh:
        setattr(analytics_marts, n, no_refresh)

    admin = _user(auth_utils, 2, "admin@scratch.test", "admin")
    planner = _user(auth_utils, 1, "planner@scratch.test", "staff")
    granted = _user(auth_utils, 3, "trusted@scratch.test", "staff")
    built = False
    try:
        # ---- 2: pre-flight and the hard guard -------------------------------------------------------------------
        pending = rcl.pending_migrations(engine, "public")
        check("2 no migration pending on public", pending == [], str(pending))
        rcl.assert_scratch_migrations_safe([rcl.MIGRATIONS_DIR / n for n in pending], SCHEMA)
        check("2 hard guard passes for an empty pending list and refuses a migration naming app./public.", _guard_refuses(rcl))
        before = fingerprints(pg)
        check("3 baseline fingerprints taken", len(before) == len(PUBLIC_FINGERPRINT_TABLES))
        n_rows, pieces = plan_figures()
        check("6 the live plan before", (n_rows, round(pieces, 2)) == EXPECTED_PLAN, f"{n_rows} rows, {pieces:,.0f} pieces")

        # ---- build ------------------------------------------------------------------------------------------------
        with engine.connect() as c:
            if c.execute(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name = :s"), {"s": SCHEMA}).scalar():
                raise SystemExit(f"{SCHEMA} already exists: drop it first (this test never reuses a scratch schema)")
        rehearse_fills.build(engine, SCHEMA)
        built = True
        cur_ok = scratch_tx(pg)
        with cur_ok as cur:
            check("build cloned the ledger tables", all(fetch(cur, "SELECT to_regclass(%s) IS NOT NULL", (t,))[0][0] for t in
                  ("expected_receipt", "planning_cycle", "lp_recommendation", "inventory_fact", "stock_opening_v")))

        # ---- synthetic March 2026 sales, scratch only --------------------------------------------------------------
        with scratch_tx(pg, write=True) as cur:
            cur.execute("SELECT count(*) FROM unilever_sku_demand_fact WHERE calendar_month = '2026-03' AND is_demo = false")
            if cur.fetchone()[0]:
                raise SystemExit("REAL March 2026 sales exist: this test is for the month before they load, and must not run over them")
            # the table already holds the retired is_demo synthetic_v2 rows for 2026-03 (never read by a _Real view): in this
            # scratch copy they are replaced by this test's own synthetic month, so the (sku_code, month) key is free
            cur.execute("DELETE FROM unilever_sku_demand_fact WHERE calendar_month = '2026-03' AND is_demo = true")
            cur.execute("""
                INSERT INTO unilever_sku_demand_fact (product_key, sku_code, calendar_month, region, quantity_sold, net_amount,
                                                      _src_file, _src_sheet, is_demo, gsv, fill_source)
                SELECT product_key, sku_code, '2026-03', region,
                       GREATEST(round(quantity_sold * (0.8 + 0.4 * ((abs(hashtext(sku_code || '2026-03')) %% 1000) / 1000.0))), 0),
                       net_amount * (0.8 + 0.4 * ((abs(hashtext(sku_code || '2026-03')) %% 1000) / 1000.0)),
                       %(tag)s, %(tag)s, false, gsv, NULL
                FROM unilever_sku_demand_fact WHERE calendar_month = '2026-02' AND is_demo = false AND quantity_sold > 0""",
                        {"tag": "rollover_test_synthetic"})
            made = cur.rowcount
        check("synthetic March sales generated in scratch", made > 500, f"{made} product rows")
        with scratch_tx(pg) as cur:
            real_march = fetch(cur, "SELECT count(*) FROM unilever_sku_demand_fact WHERE calendar_month = '2026-03' "
                                    "AND _src_file <> 'rollover_test_synthetic'")[0][0]
        check("no real March sales existed to be mixed with", real_march == 0)

        # ---- decisions on the March plan -----------------------------------------------------------------------------
        with scratch_tx(pg) as cur:
            cand = fetch(cur, """
                SELECT lr.recommendation_key, lr.product_key, lr.q_i, pd.pack_size::numeric
                FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
                WHERE lr.planning_cycle_date = %(c)s AND lr.status = 'pending' AND lr.lp_run_key IS NOT NULL AND lr.q_i > 0
                  AND pd.principal = 'unilever' AND pd.pack_size ~ '^[0-9]+(\\.[0-9]+)?$' AND pd.pack_size::numeric > 0
                ORDER BY lr.recommendation_key""", {"c": CYCLE})
        check("plan rows to decide", len(cand) >= 12, f"{len(cand)}")
        (k_plain, k_direct, k_grant, k_appr, k_dismiss, k_s1, k_s2, k_s3, k_x) = [c[0] for c in cand[:9]]
        q = {c[0]: float(c[2]) for c in cand}
        pack = {c[0]: float(c[3]) for c in cand}
        pk_of = {c[0]: c[1] for c in cand}

        def call(fn, *a, **kw):
            # the planning mart is a LIVE schema: it must be off for every call, or decide() copies scratch decisions into it
            assert planning_mart._STATE["schema"] is None, "planning mart is on: scratch decisions would reach the live mart"
            with scratch_session(engine) as db:
                return fn(db, *a, **kw)

        def patch(key, user, **body):
            return call(lambda db: rec.update_recommendation(key, RecommendationDecision(reviewed=True, **body), db=db, current_user=user))

        patch(k_plain, admin, status="accepted")
        patch(k_direct, admin, status="accepted", decided_quantity=q[k_direct] + pack[k_direct])
        with scratch_tx(pg, write=True) as cur:
            cur.execute("INSERT INTO lp_direct_apply_grant (user_id, granted_by) VALUES (%s, 'scratch')", (granted.user_id,))
        out = call(lambda db: ra.change_quantity(k_grant, QuantityChangeRequest(quantity=q[k_grant] + 2 * pack[k_grant], reviewed=True, reason="direct apply (scratch test)"),
                                                  type("R", (), {"status_code": 200})(), db=db, current_user=granted))
        check("a granted user's change applied at once", out.outcome == "applied")
        held = call(lambda db: ra.change_quantity(k_appr, QuantityChangeRequest(quantity=q[k_appr] + 3 * pack[k_appr], reviewed=True, reason="held for approval (scratch test)"),
                                                   type("R", (), {"status_code": 200})(), db=db, current_user=planner))
        check("a planner's change is held", held.outcome == "held")
        with scratch_tx(pg) as cur:
            check("no receipt before approval", fetch(cur, "SELECT count(*) FROM expected_receipt WHERE recommendation_key = %s", (k_appr,))[0][0] == 0)
        call(lambda db: ra.approve_change(held.change.change_key, None, db=db, admin=admin))
        patch(k_dismiss, admin, status="dismissed", reason="not needed (scratch test)")

        def receipts(cur, key):
            return fetch(cur, "SELECT pieces, state, voided_by_decision, lead_time_source, expected_on, "
                              "(SELECT COALESCE(decided_q_i, q_i) FROM lp_recommendation WHERE recommendation_key = %(k)s), "
                              "(SELECT decided_at::date FROM lp_recommendation WHERE recommendation_key = %(k)s) "
                              "FROM expected_receipt WHERE recommendation_key = %(k)s ORDER BY receipt_id", {"k": key})

        with scratch_tx(pg) as cur:
            for label, key, want in (("plain accept", k_plain, q[k_plain]), ("direct apply (PATCH)", k_direct, q[k_direct] + pack[k_direct]),
                                     ("direct apply (granted user)", k_grant, q[k_grant] + 2 * pack[k_grant]),
                                     ("approved change", k_appr, q[k_appr] + 3 * pack[k_appr])):
                rows = receipts(cur, key)
                check(f"receipt follows the decided quantity: {label}", len(rows) == 1 and float(rows[0][0]) == want
                      and float(rows[0][0]) == float(rows[0][5]) and rows[0][1] == "expected", f"{rows}")
                check(f"expected_on = decision date + lead time: {label}",
                      (rows[0][4] - rows[0][6]).days == 3, f"{rows[0][4]} - {rows[0][6]}")
            check("a dismissal writes no receipt", receipts(cur, k_dismiss) == [])
        call(lambda db: ra.reverse_decision(k_plain, ReverseRequest(reason="wrong product (scratch test)"), db=db, admin=admin))
        with scratch_tx(pg) as cur:
            rows = receipts(cur, k_plain)
            check("a reversal voids the receipt (kept, not deleted)", len(rows) == 1 and rows[0][1] == "cancelled" and rows[0][2] == "reversed", f"{rows}")
        patch(k_plain, admin, status="accepted", decided_quantity=q[k_plain] + 4 * pack[k_plain])
        with scratch_tx(pg) as cur:
            rows = receipts(cur, k_plain)
            live = [r for r in rows if r[1] == "expected"]
            check("accepting again gives a new live receipt at the new quantity, the old one kept cancelled",
                  len(rows) == 2 and len(live) == 1 and float(live[0][0]) == q[k_plain] + 4 * pack[k_plain], f"{rows}")

        # two accepted orders whose expected_on falls BEFORE the 6 Apr count (decided 30 Mar, expected 2 Apr) and one after (4 Apr -> 7 Apr)
        for key, when in ((k_s1, datetime.datetime(2026, 3, 30, 10)), (k_s2, datetime.datetime(2026, 3, 30, 11)),
                          (k_s3, datetime.datetime(2026, 4, 4, 9))):
            def decide(db, key=key, when=when):
                present = rec._present(db)
                rec.decide_row(db, present, key=key, status="accepted", reason=None, decided_quantity=None,
                               decided_by="scratch", decided_at=when)
                db.commit()
            call(decide)

        # ---- the opening view: projected, then count basis, checked by hand -------------------------------------------
        with scratch_tx(pg) as cur:
            c_feb = fetch(cur, "SELECT MAX(snapshot_date) FROM inventory_fact WHERE principal='unilever' AND _period='2026-02'")[0][0]
            c_mar = fetch(cur, "SELECT MAX(snapshot_date) FROM inventory_fact WHERE principal='unilever' AND _period='2026-03'")[0][0]
        check("the real 6 Apr count is loaded (the opening count of April)", c_mar == datetime.date(2026, 4, 6), str(c_mar))
        pick = [pk_of[k] for k in (k_direct, k_grant, k_appr, k_s1, k_s2, k_s3)]

        def hand(cur, product_key, period, count_date, sales_deducted):
            stock = fetch(cur, """SELECT CASE WHEN pd.pack_size ~ '^[0-9]+(\\.[0-9]+)?$' THEN SUM(i.quantity_on_hand) * pd.pack_size::numeric
                                         + COALESCE(SUM(i.quantity_pieces), 0) END
                                  FROM inventory_fact i JOIN product_dimension pd ON pd.product_key = i.product_key
                                  WHERE i.principal='unilever' AND i._period = %s AND i.product_key = %s GROUP BY pd.pack_size""",
                          (period, product_key))
            base = float(stock[0][0]) if stock and stock[0][0] is not None else 0.0
            rc = fetch(cur, """SELECT COALESCE(SUM(er.pieces), 0) FROM expected_receipt er JOIN lp_recommendation lr
                               ON lr.recommendation_key = er.recommendation_key
                               WHERE er.product_key = %s AND er.state = 'expected' AND er.expected_on > %s
                                 AND lr.planning_cycle_date < %s""", (product_key, count_date, NEXT_CYCLE))[0][0]
            sold = 0.0
            if sales_deducted:
                s = fetch(cur, "SELECT COALESCE(GREATEST(SUM(quantity_sold), 0), 0) FROM unilever_sku_demand_fact "
                               "WHERE product_key = %s AND calendar_month = '2026-03' AND is_demo = false", (product_key,))
                sold = float(s[0][0])
            return max(base + float(rc) - sold, 0.0), base, float(rc), sold

        pg.rollback()
        cur = pg.cursor()
        cur.execute("BEGIN")
        cur.execute("SELECT set_config('search_path', %s, true)", (SCHEMA,))
        cur.execute("DELETE FROM inventory_fact WHERE principal = 'unilever' AND _period = '2026-03'")   # scratch only, rolled back below
        rows = fetch(cur, "SELECT product_key, opening_basis, count_period, opening_pieces, expected_receipt_pieces, sales_basis "
                          "FROM stock_opening_v WHERE cycle = %s AND product_key = ANY(%s)", (NEXT_CYCLE, pick))
        check("with the March count removed, April's opening is PROJECTED from the February count",
              rows and all(r[1] == "projected" and r[2] == "2026-02" and r[5] == "actual" for r in rows), f"{rows}")
        for r in rows:
            want, base, rc, sold = hand(cur, r[0], "2026-02", c_feb, True)
            check(f"projected opening by hand, product {r[0]}", abs(float(r[3]) - want) < 1e-6,
                  f"view {float(r[3]):.2f}, hand {want:.2f} = {base:.0f} + {rc:.0f} on the way - {sold:.0f} sold")
        pg.rollback()
        with scratch_tx(pg) as cur:
            rows = fetch(cur, "SELECT product_key, opening_basis, count_period, opening_pieces, expected_receipt_pieces "
                              "FROM stock_opening_v WHERE cycle = %s AND product_key = ANY(%s)", (NEXT_CYCLE, pick))
            check("with the real count, April's opening is the COUNT plus receipts still on the way",
                  rows and all(r[1] == "count" and r[2] == "2026-03" for r in rows))
            for r in rows:
                want, base, rc, _ = hand(cur, r[0], "2026-03", c_mar, False)
                check(f"count-basis opening by hand, product {r[0]}", abs(float(r[3]) - want) < 1e-6,
                      f"view {float(r[3]):.2f}, hand {want:.2f} = {base:.0f} + {rc:.0f} on the way")
            sett = {pk_of[k_s1], pk_of[k_s2]}
            inside = fetch(cur, "SELECT product_key, expected_receipt_pieces FROM stock_opening_v WHERE cycle = %s AND product_key = ANY(%s)",
                           (NEXT_CYCLE, list(sett)))
            check("receipts expected before the count date are inside the count, never added again",
                  all(float(p) == 0.0 for _, p in inside), f"{inside}")
            after = fetch(cur, "SELECT expected_receipt_pieces FROM stock_opening_v WHERE cycle = %s AND product_key = %s", (NEXT_CYCLE, pk_of[k_s3]))
            check("a receipt expected after the count date is still on the way", float(after[0][0]) > 0)

        # ---- settlement: independent expectation, then a rolled-back write, then idempotence ------------------------
        with scratch_tx(pg) as cur:
            expect = {}
            for k in (k_s1, k_s2):
                p = pk_of[k]
                closing = hand(cur, p, "2026-03", c_mar, False)[1]
                opening = hand(cur, p, "2026-02", c_feb, False)[1]
                sold = hand(cur, p, "2026-02", c_feb, True)[3]
                expect[p] = closing - opening + sold
            dry = receipt_settlement.settle(cur, "2026-03", write=False)
        check("settlement dry run finds exactly the receipts expected on or before the count date",
              dry["settles"] == 2, f"{dry}")
        cur = pg.cursor()
        cur.execute("BEGIN")
        cur.execute("SELECT set_config('search_path', %s, true)", (SCHEMA,))
        wrote = receipt_settlement.settle(cur, "2026-03", write=True)
        got = {r[0]: r[1:] for r in fetch(cur, "SELECT product_key, state, settled_by_count_date, not_visible_in_count, stock_change_pieces "
                                               "FROM expected_receipt WHERE state = 'arrived_in_count'")}
        for p, implied in expect.items():
            state, d, nv, change = got[p]
            check(f"settled and flagged as the identity says, product {p}", d == c_mar and abs(float(change) - implied) < 1e-6
                  and nv == (implied <= 0), f"implied receipts {implied:.0f}, not_visible {nv}")
        again = receipt_settlement.settle(cur, "2026-03", write=True)
        check("a second settlement settles nothing", again["settles"] == 0, str(again))
        still = fetch(cur, "SELECT count(*) FROM expected_receipt WHERE state = 'expected' AND expected_on > %s", (c_mar,))[0][0]
        check("receipts expected after the count stay expected", still >= 5, f"{still}")
        pg.rollback()       # the real settlement is done by the close below, so that reopening can be shown to undo it

        # ---- the April plan scaffold, then the close ------------------------------------------------------------------
        with scratch_tx(pg, write=True) as cur:
            cur.execute("""INSERT INTO abc_classification (product_key, principal, classification_period, tier, revenue_share,
                           cumulative_share, computed_at, boundary_flag, method, run_id, added_as_new)
                           SELECT product_key, principal, '2026-03', tier, revenue_share, cumulative_share, now(), boundary_flag,
                                  method, 'rollover_test', added_as_new FROM abc_classification
                           WHERE classification_period = '2026-02' AND principal = 'unilever' AND method = %s
                           ORDER BY product_key LIMIT 3""", (cc.cycle_params(CYCLE)["method"],))
            cur.execute("""INSERT INTO forecast_result (product_key, forecast_date, forecast_value, confidence_lower, confidence_upper, mape,
                           model_params, generated_at, mase, status)
                           SELECT product_key, '2026-04-01', forecast_value, confidence_lower, confidence_upper, mape,
                                  '{"scaffold": "rollover_test"}'::jsonb, now(), mase, status
                           FROM forecast_result WHERE forecast_date = '2026-03-01' LIMIT 3""")
            cur.execute("""INSERT INTO lp_run (planning_cycle_date, principal_scope, inputs, model, code_version)
                           SELECT '2026-04-01', principal_scope, '{"scaffold": "rollover_test"}'::jsonb, model, 'rollover_test'
                           FROM lp_run ORDER BY run_key DESC LIMIT 1 RETURNING run_key""")
            run_key = cur.fetchone()[0]
            cur.execute("""INSERT INTO lp_recommendation (product_key, planning_cycle_date, q_i, rop_i, ss_i, status, generated_at, lp_run_key)
                           SELECT product_key, '2026-04-01', q_i, rop_i, ss_i, 'pending', now(), %s FROM lp_recommendation
                           WHERE planning_cycle_date = '2026-03-01' AND lp_run_key IS NOT NULL LIMIT 3""", (run_key,))

        params = cc.cycle_params(CYCLE)
        snap_sql = ("SELECT recommendation_key, status, decided_q_i, decision_reason, decided_by, decided_at, q_i FROM lp_recommendation "
                    "WHERE planning_cycle_date = %s ORDER BY recommendation_key")
        with scratch_tx(pg) as cur:
            decisions_before = fetch(cur, snap_sql, (CYCLE,))
            n_decided = sum(1 for r in decisions_before if r[1] != "pending")
        check("decisions exist to survive the close", n_decided >= 8, f"{n_decided}")
        out = []
        dry = cc.close(pg, SCHEMA, params, "rollover-test", write=False, out=out.append)
        check("a dry run closes nothing", dry["action"] == "dry_run" and not dry["changed"])

        # a step fails midway: the cycle is left closing with the finished steps recorded, and reopen recovers it
        boom = {"n": 0}
        real_settle = receipt_settlement.settle

        def failing_settle(cur, period, write=False):
            boom["n"] += 1
            raise RuntimeError("simulated connection loss")
        cc.receipt_settlement.settle = failing_settle
        try:
            cc.close(pg, SCHEMA, params, "rollover-test", write=True, out=lambda *_: None)
            check("a failing step raises", False)
        except RuntimeError:
            pass
        finally:
            cc.receipt_settlement.settle = real_settle
        with scratch_tx(pg) as cur:
            row = fetch(cur, "SELECT state, steps_done FROM planning_cycle WHERE principal='unilever' AND cycle=%s", (CYCLE,))[0]
            closed_rows = fetch(cur, "SELECT count(*) FROM lp_recommendation WHERE planning_cycle_date=%s AND closed_at IS NOT NULL", (CYCLE,))[0][0]
        check("a failed close leaves the cycle 'closing', nothing half-written", row[0] == "closing" and list(row[1]) == [] and closed_rows == 0, str(row))
        re = cc.reopen(pg, SCHEMA, params, "rollover-test", write=True, out=lambda *_: None)
        with scratch_tx(pg) as cur:
            row = fetch(cur, "SELECT state, reopen_count FROM planning_cycle WHERE principal='unilever' AND cycle=%s", (CYCLE,))[0]
        check("a half-closed cycle is recovered by one command (reopen)", re["action"] == "reopened" and row == ("open", 1), str(row))

        res = cc.close(pg, SCHEMA, params, "rollover-test", write=True, out=lambda *_: None)
        check("the close completes", res["action"] == "closed" and res["changed"])
        with scratch_tx(pg) as cur:
            decisions_after = fetch(cur, snap_sql, (CYCLE,))
            closed_rows = fetch(cur, "SELECT count(*) FROM lp_recommendation WHERE planning_cycle_date=%s AND closed_at IS NOT NULL", (CYCLE,))[0][0]
            cyc = fetch(cur, "SELECT state, steps_done, closed_by FROM planning_cycle WHERE principal='unilever' AND cycle=%s", (CYCLE,))[0]
            arrived = fetch(cur, "SELECT count(*) FROM expected_receipt WHERE state = 'arrived_in_count'")[0][0]
            total_rows = fetch(cur, "SELECT count(*) FROM lp_recommendation WHERE planning_cycle_date=%s", (CYCLE,))[0][0]
        check("decided rows are closed, not deleted or changed", decisions_after == decisions_before and closed_rows == total_rows,
              f"{total_rows} rows, all closed, decisions identical")
        check("the cycle is recorded closed with both steps", cyc[0] == "closed" and list(cyc[1]) == list(cc.STEPS) and cyc[2] == "rollover-test", str(cyc))
        check("the close settled the receipts expected on or before the count date", arrived >= 2, f"{arrived}")

        def state_fp(cur):
            return [fetch(cur, f"SELECT COUNT(*), COALESCE(SUM(hashtext(x::text)::numeric), 0) FROM {t} x")[0]
                    for t in ("expected_receipt", "lp_recommendation", "planning_cycle", "audit_log")]
        with scratch_tx(pg) as cur:
            fp1 = state_fp(cur)
        twice = cc.close(pg, SCHEMA, params, "someone-else", write=True, out=lambda *_: None)
        with scratch_tx(pg) as cur:
            fp2 = state_fp(cur)
        check("running the close twice changes nothing the second time", twice["action"] == "already_closed" and fp1 == fp2)

        cc.reopen(pg, SCHEMA, params, "rollover-test", write=True, out=lambda *_: None)
        with scratch_tx(pg) as cur:
            back = fetch(cur, "SELECT count(*) FROM expected_receipt WHERE state = 'arrived_in_count'")[0][0]
            reopened = fetch(cur, "SELECT count(*) FROM lp_recommendation WHERE planning_cycle_date=%s AND closed_at IS NOT NULL", (CYCLE,))[0][0]
            decisions_reopened = fetch(cur, snap_sql, (CYCLE,))
            cleared = fetch(cur, "SELECT count(*) FROM expected_receipt WHERE state = 'expected' AND settled_at IS NOT NULL")[0][0]
        check("a reopen undoes the close without a restore: receipts back to expected, plan rows open, decisions intact",
              back == 0 and reopened == 0 and decisions_reopened == decisions_before and cleared == 0, f"{back=} {reopened=} {cleared=}")
        res = cc.close(pg, SCHEMA, params, "rollover-test", write=True, out=lambda *_: None)
        with scratch_tx(pg) as cur:
            arrived2 = fetch(cur, "SELECT count(*) FROM expected_receipt WHERE state = 'arrived_in_count'")[0][0]
        check("closing again after a reopen reaches the same result", res["action"] == "closed" and arrived2 == arrived)

        # ---- the unified signal ---------------------------------------------------------------------------------------
        with scratch_session(engine) as db:
            from backend.routers import inventory as inv
            sig = inv.get_receipt_signals(limit=10, months=3, db=db, current_user=None)
        check("the not-visible signal is exposed", sig["available"] and sig["totals"]["settled"] == arrived2, str(sig["totals"]))
        check("no mart refresh was called", refreshed == [])

        # ---- isolation ---------------------------------------------------------------------------------------------------
        after = fingerprints(pg)
        check("3 public, mart and app are identical before and after", after == before,
              str({t: (before[t], after[t]) for t in before if before[t] != after[t]}))
        hits = tag_scan(pg)
        check("4 no table in public, mart, app or demo contains the scratch tag", hits == [], str(hits))
        n_rows2, pieces2 = plan_figures()
        check("6 the live plan is unchanged", (n_rows2, round(pieces2, 2)) == EXPECTED_PLAN, f"{n_rows2} rows, {pieces2:,.0f} pieces")
    finally:
        for n, f in real_refresh.items():
            setattr(analytics_marts, n, f)
        planning_mart.use_schema("mart")
        try:
            pg.rollback()
        except Exception:
            pass
        if built and not keep:
            with engine.begin() as conn:
                assert SCHEMA == "ssm_rollover_test"
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
            with engine.connect() as conn:
                gone = conn.execute(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name = :s"), {"s": SCHEMA}).scalar() == 0
            print(f"  [{'PASS' if gone else 'FAIL'}] 7 the scratch schema is dropped and gone")
            checks.append(("7 scratch schema dropped", gone, ""))
        pg.close()
    failed = [c for c in checks if not c[1]]
    print(f"== {len(checks) - len(failed)} of {len(checks)} checks passed ==")
    return 1 if failed else 0


def _user(auth_utils, user_id, email, role):
    return auth_utils.decode_access_token(auth_utils.create_access_token(
        user_id=user_id, email=email, role=role, full_name=email.split("@")[0]))


def scratch_session(engine):
    """A SQLAlchemy Session whose EVERY transaction starts on the scratch schema alone. The endpoints commit and then read
    again (approve_change re-reads the change after its commit), so one SET LOCAL at the start is not enough: without this
    the second transaction of a call would resolve to public."""
    import contextlib

    from sqlalchemy import event, text
    from sqlalchemy.orm import Session

    @contextlib.contextmanager
    def _open():
        db = Session(engine)
        event.listen(db, "after_begin", lambda session, transaction, connection: connection.execute(
            text("SELECT set_config('search_path', :s, true)"), {"s": SCHEMA}))
        try:
            yield db
        finally:
            db.close()
    return _open()


class scratch_tx:
    """A transaction on the scratch schema ALONE (transaction-local search_path): rolled back unless write=True."""
    def __init__(self, conn, write: bool = False):
        self.conn, self.write = conn, write

    def __enter__(self):
        self.conn.rollback()
        self.cur = self.conn.cursor()
        self.cur.execute("BEGIN")
        self.cur.execute("SELECT set_config('search_path', %s, true)", (SCHEMA,))
        if not self.write:
            self.cur.execute("SET TRANSACTION READ ONLY")
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None and self.write:
            self.conn.commit()
        else:
            self.conn.rollback()
        return False


def _guard_refuses(rcl) -> bool:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "0999_probe.sql"
        f.write_text("ALTER TABLE app.users ADD COLUMN probe TEXT;\n", encoding="utf-8")
        try:
            rcl.assert_scratch_migrations_safe([f], SCHEMA)
        except SystemExit as exc:
            return "REFUSED" in str(exc)
    return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true", help="leave the scratch schema in place (drop it yourself afterwards)")
    sys.exit(main(keep=ap.parse_args().keep))
