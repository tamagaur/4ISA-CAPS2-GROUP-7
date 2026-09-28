"""scripts/apply_synth_v2_cutover.py - the synthetic v2 cutover, batch by batch. Every synthetic row in public
(is_demo = true: the v1 rows and the Unilever placeholder) is replaced by ssm_synth_v2's, one fact table per batch;
then the Del Monte SKU products that nothing references any more are removed. Same logic as
scripts/apply_synth_v2_to_public.cutover() (which does all of it in one transaction), run through
apply_dm_fixes_to_public's batch runner: scratch rehearsal with the rollback proven, backup in a timed child
process, public equal to the rehearsal both directions, resumable ledger (run_id prefix 'synth_v2_cutover_').

REAL ROWS ARE NEVER WRITTEN: every DELETE carries is_demo = true, and each batch compares the table's real-row
fingerprint before and after. Foreign keys of the inserted rows are mapped by natural key into the target's own
dimension rows (apply_synth_v2_to_public.DIMENSIONS); a row with no match aborts the batch.

  python -m scripts.apply_synth_v2_cutover --baseline public                     real-row checksums + coverage, saved
  python -m scripts.apply_synth_v2_cutover --rehearse ssm_dm_fixes --batch N
  python -m scripts.apply_synth_v2_cutover --target public --against ssm_dm_fixes --batch N --i-have-approval
  python -m scripts.apply_synth_v2_cutover --verify public --baseline-file backups/<file>.json
  python -m scripts.apply_synth_v2_cutover --rollback backups/synth_v2_cutover_<ts>/b<N>_<ts> --i-have-approval
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from scripts.apply_dm_fixes_to_public import REPO, connect, fingerprint, rollback, run_batch
from scripts.apply_synth_v2_to_public import DIMENSIONS, FACTS, ORPHAN_PRODUCTS, columns, one
from scripts.build_synthetic_v2_clean_pool import ALL_MONTHS, MONTHS_2122, SYNTH_SRC, month_counts

SOURCE = "ssm_synth_v2"
PREFIX = "synth_v2_cutover_"
AGG = "AGGREGATED_source_file_defect_category"  # the loader's sell-out defect merge; is_demo inherited
# (synthetic rows removed from public, synthetic rows added from v2) - measured 2026-09-28 before any write
EXPECTED = {"unilever_sku_demand_fact": (19669, 12243), "sales_fact": (35162, 43843), "purchase_fact": (2263, 2221),
            "salesreturn_fact": (250, 2222), "sellout_fact": (6293, 4631), "inventory_fact": (15734, 15852 + 8292)}
EXPECTED_PRODUCTS_REMOVED = 14530
MODEL_TABLES = ["forecast_result", "abc_classification", "lp_recommendation", "sku_traits", "sku_segment"]


def replace_demo(table: str):
    ident, fks = FACTS[table]

    def fn(cur, T, check, log):
        removed_exp, added_exp = EXPECTED[table]
        pre_cols = columns(cur, T, table)
        real_before = fingerprint(cur, T, table, "NOT is_demo", pre_cols)
        check(f"{table}: source synthetic rows", one(cur, f"SELECT COUNT(*) FROM {SOURCE}.{table} WHERE is_demo"), added_exp)
        cols = [c for c in pre_cols if c != ident and c in columns(cur, SOURCE, table)]
        select, joins, orphan_tests = [], [], []
        for c in cols:
            if c in fks:
                dim = fks[c]; key, on = DIMENSIONS[dim]; a, b = f"s_{c}", f"t_{c}"
                joins.append(f"LEFT JOIN {SOURCE}.{dim} {a} ON {a}.{key} = f.{c} "
                             f"LEFT JOIN {T}.{dim} {b} ON {on.replace('t.', b + '.').replace('s.', a + '.')}")
                select.append(f"{b}.{key}")
                orphan_tests.append(f"(f.{c} IS NOT NULL AND {b}.{key} IS NULL)")
            else:
                select.append(f"f.{c}")
        base = f"FROM {SOURCE}.{table} f {' '.join(joins)} WHERE f.is_demo"
        check(f"{table}: source synthetic rows with no dimension match in {T}",
              one(cur, f"SELECT COUNT(*) {base} AND ({' OR '.join(orphan_tests)})") if orphan_tests else 0, 0)
        # no RETURNING of the deleted rows: the undo re-inserts them from this batch's CSV backup (upload, not download)
        cur.execute(f"DELETE FROM {T}.{table} WHERE is_demo")
        n_deleted = cur.rowcount
        log["deleted"][table] = {"restore_from_backup": "is_demo", "rows": n_deleted}
        cur.execute(f"INSERT INTO {T}.{table} ({', '.join(cols)}) SELECT {', '.join(select)} {base} RETURNING {ident}")
        log["inserted"][table] = [r[0] for r in cur.fetchall()]
        check(f"{table}: synthetic rows removed", n_deleted, removed_exp)
        check(f"{table}: synthetic rows added", len(log["inserted"][table]), added_exp)
        check(f"{table}: real rows unchanged (fingerprint)", fingerprint(cur, T, table, "NOT is_demo", pre_cols), real_before)
        new = f"SELECT * FROM {T}.{table} WHERE {ident} = ANY(%s)"
        check(f"{table}: added rows not is_demo, or not from a synthetic source",
              one(cur, f"SELECT COUNT(*) FROM ({new}) x WHERE NOT is_demo OR ((_src_file IS NULL OR _src_file !~ %s) AND _src_file IS DISTINCT FROM %s)",
                  (log["inserted"][table], SYNTH_SRC, AGG)), 0)
        if "_period" in pre_cols:
            check(f"{table}: rows with _period 'unknown'", one(cur, f"SELECT COUNT(*) FROM {T}.{table} WHERE _period = 'unknown'"), 0)
        if "net_amount" in pre_cols:
            check(f"{table}: added rows with NULL net_amount", one(cur, f"SELECT COUNT(*) FROM ({new}) x WHERE net_amount IS NULL",
                                                                (log["inserted"][table],)), 0)
        return removed_exp + added_exp, n_deleted + len(log["inserted"][table])
    return fn


def remove_orphan_products(cur, T, check, log):
    cur.execute(f"""DELETE FROM {T}.product_dimension p WHERE p.product_key IN ({ORPHAN_PRODUCTS.format(T=T)})
                    RETURNING p.product_key, p.principal, p.grain""")
    gone = cur.fetchall()
    log["deleted"]["product_dimension"] = {"restore_from_backup": "TRUE", "key": "product_key", "keys": [k for k, _, _ in gone], "rows": len(gone)}
    check("product rows removed (Del Monte SKU rows nothing references)", len(gone), EXPECTED_PRODUCTS_REMOVED)
    check("removed rows that are not Del Monte SKU rows", sum(1 for _, p, g in gone if (p, g) != ("delmonte", "sku")), 0)
    check("Del Monte SKU products left", one(cur, f"SELECT COUNT(*) FROM {T}.product_dimension WHERE principal = 'delmonte' AND grain = 'sku'"), 597)
    check("Del Monte SKU products left without a real inventory row",
          one(cur, f"""SELECT COUNT(*) FROM {T}.product_dimension pd WHERE principal = 'delmonte' AND grain = 'sku'
                       AND NOT EXISTS (SELECT 1 FROM {T}.inventory_fact i WHERE i.product_key = pd.product_key AND NOT i.is_demo)"""), 0)
    return EXPECTED_PRODUCTS_REMOVED, len(gone)


BATCHES = {i + 1: (f"synthetic rows of {t}: public v1 / placeholder -> ssm_synth_v2", [t], replace_demo(t)) for i, t in enumerate(FACTS)}
BATCHES[len(FACTS) + 1] = ("remove the Del Monte SKU products nothing references", ["product_dimension"], remove_orphan_products)


# --- baseline / verify: real-row checksums, model tables, coverage ----------------------------------------------
GRID = [("delmonte", t, "_period") for t in ("sales_fact", "salesreturn_fact", "sellout_fact", "inventory_fact", "purchase_fact")] + [
    ("unilever", "unilever_sku_demand_fact", "calendar_month"), ("unilever", "inventory_fact", "_period")]


def state(cur, T: str) -> dict:
    out = {"real": {}, "dims": {}, "models": {}, "coverage": {}}
    for t in FACTS:
        for principal in (["unilever"] if t == "unilever_sku_demand_fact" else ["delmonte", "unilever"]):
            where = "NOT is_demo" if t == "unilever_sku_demand_fact" else f"NOT is_demo AND principal = '{principal}'"
            out["real"][f"{t}|{principal}"] = fingerprint(cur, T, t, where, columns(cur, T, t))
    for d in ("customer_dimension", "salesman_dimension", "supplier_dimension"):
        out["dims"][d] = fingerprint(cur, T, d, "TRUE", columns(cur, T, d))
    out["dims"]["product_dimension kept (not Del Monte SKU, or Del Monte SKU with real inventory)"] = fingerprint(
        cur, T, "product_dimension", f"""NOT (principal = 'delmonte' AND grain = 'sku') OR product_key IN
        (SELECT product_key FROM {T}.inventory_fact WHERE NOT is_demo AND product_key IS NOT NULL)""", columns(cur, T, "product_dimension"))
    for t in MODEL_TABLES:
        wheres = ["method = 'single'", "method IS DISTINCT FROM 'single'"] if t == "abc_classification" else ["TRUE"]
        for w in wheres:
            out["models"][f"{t}|{w}"] = fingerprint(cur, T, t, w, columns(cur, T, t))
    out["models"]["router input: unilever_sku_demand_fact_real"] = one(cur, f"""SELECT md5(string_agg(md5(x::text), '' ORDER BY demand_key))
                                                                          FROM {T}.unilever_sku_demand_fact_real x""")
    for principal, t, m in GRID:
        c = month_counts(cur, T, principal, t, m)
        out["coverage"][f"{principal}|{t}"] = {mm: c.get(mm, [0, 0]) for mm in ALL_MONTHS + ["unknown"]}
    return out


def verify(cur, T: str, base: dict) -> list:
    now, res = state(cur, T), []
    for section in ("real", "dims", "models"):
        for k, v in base[section].items():
            res.append((f"{section}: {k} unchanged", now[section][k], v))
    for k, months in now["coverage"].items():
        before = base["coverage"][k]
        res.append((f"{k}: synthetic rows in a real table-month", sum(d for m, (r, d) in months.items() if r and d), 0))
        res.append((f"{k}: table-months covered before that are empty now",
                    [m for m in ALL_MONTHS if sum(before[m]) and not sum(months[m])], []))
        res.append((f"{k}: N table-months in 2021-01..2022-12", [m for m in MONTHS_2122 if not sum(months[m])], []))
        res.append((f"{k}: rows with _period 'unknown'", sum(months["unknown"]), 0))
    for t in FACTS:
        res.append((f"{t}: synthetic-source rows flagged real", one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE NOT is_demo AND _src_file ~ %s", (SYNTH_SRC,)), 0))
        res.append((f"{t}: synthetic rows without a synthetic source",
                    one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE is_demo AND (_src_file IS NULL OR _src_file !~ %s) AND _src_file IS DISTINCT FROM %s",
                        (SYNTH_SRC, AGG)), 0))
    return res


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target"); p.add_argument("--rehearse"); p.add_argument("--against"); p.add_argument("--batch", type=int)
    p.add_argument("--baseline", metavar="SCHEMA"); p.add_argument("--verify", metavar="SCHEMA"); p.add_argument("--baseline-file")
    p.add_argument("--rollback"); p.add_argument("--i-have-approval", action="store_true")
    args = p.parse_args()
    conn = connect(); cur = conn.cursor()
    try:
        if args.baseline:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out = REPO / "backups" / f"synth_v2_cutover_baseline_{args.baseline}_{ts}.json"
            out.write_text(json.dumps(state(cur, args.baseline), indent=1, default=str), encoding="utf-8")
            conn.rollback(); print(f"baseline of {args.baseline} -> {out.relative_to(REPO).as_posix()}")
            return 0
        if args.verify:
            base = json.loads(Path(args.baseline_file).read_text(encoding="utf-8"))
            failed = 0
            for name, got, want in verify(cur, args.verify, base):
                ok = json.dumps(got, default=str) == json.dumps(want, default=str)
                failed += not ok
                if not ok or name.startswith("models"):
                    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f" (expected {want})"))
            print(f"verify {args.verify}: {'ALL PASS' if not failed else f'{failed} FAILED'}")
            conn.rollback()
            return 1 if failed else 0
        if args.rollback:
            if json.loads((Path(args.rollback) / "manifest.json").read_text(encoding="utf-8"))["target"] == "public" and not args.i_have_approval:
                sys.exit("refusing: a rollback on public needs --i-have-approval")
            return rollback(conn, cur, Path(args.rollback))
        if args.batch not in BATCHES:
            p.error(f"--batch must be one of {sorted(BATCHES)}")
        if args.rehearse:
            if args.rehearse in ("public", SOURCE, "ssm_pm_cleanup"):
                p.error("--rehearse needs a scratch copy of public")
            missing = [t for t in MODEL_TABLES if not one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{args.rehearse}.{t}",))]
            for t in missing:  # the orphan-product query reads them; copied once, read only
                cur.execute(f"CREATE TABLE {args.rehearse}.{t} (LIKE public.{t} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)")
                cur.execute(f"INSERT INTO {args.rehearse}.{t} SELECT * FROM public.{t}")
            conn.commit()
            return run_batch(conn, cur, args.rehearse, args.batch, True, None, BATCHES, PREFIX)
        if args.target != "public" or not args.against or not args.i_have_approval:
            p.error("--target public needs --against SCHEMA and --i-have-approval")
        return run_batch(conn, cur, "public", args.batch, False, args.against, BATCHES, PREFIX)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
