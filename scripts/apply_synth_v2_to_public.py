"""scripts/apply_synth_v2_to_public.py - replace the synthetic (is_demo=true) rows in the live fact tables with
the v2 placeholder rows from a verified scratch build, and remove the Del Monte Product_Dimension rows that no
real data vouches for. Follows the pattern of scripts/apply_dm_fix_to_public.py.

REAL ROWS ARE NEVER TOUCHED. Every DELETE here carries `is_demo = true`; the Product_Dimension cleanup only
removes rows that, after the demo replacement, are referenced by nothing at all.

Run this yourself - writes to `public` need Yuan's explicit go. Requires SUPABASE_DIRECT_URL (port 5432): the
pooled URL is refused.

  rehearse on a scratch copy of the live tables (writes only to the rehearsal schema):
      python -m scripts.apply_synth_v2_to_public --source ssm_synth_v2 --rehearse ssm_cutover_rehearsal
  the real cutover:
      python -m scripts.apply_synth_v2_to_public --source ssm_synth_v2 --target public --i-have-approval
  undo it (restores every synthetic row and every deleted product row from the backup taken by the cutover):
      python -m scripts.apply_synth_v2_to_public --rollback backups/synth_v2_cutover_<timestamp> --i-have-approval

One transaction. Before COMMIT it checks, and rolls back on any failure:
  - the fingerprint of the REAL rows of every fact table is unchanged;
  - Forecast_Result, ABC_Classification, sku_segment and sku_traits are byte-for-byte unchanged (the proof that
    synthetic data cannot reach a forecast, a tier or a bin);
  - every _Real view returns the same number of rows as before;
  - every source demo row found its product / customer / salesman / supplier in the target (no orphan, and no
    dimension row is invented here);
  - demo row counts equal the source schema's, table by table;
  - 0 rows with _period = 'unknown', 0 NULL net_amount, every inserted row is_demo = true;
  - exactly the expected number of Product_Dimension rows were removed, and none of them had a real row.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent

# fact table -> (identity column, {fk column: dimension table})
FACTS = {
    "unilever_sku_demand_fact": ("demand_key", {"product_key": "product_dimension"}),
    "sales_fact": ("sales_key", {"customer_key": "customer_dimension", "salesman_key": "salesman_dimension"}),
    "purchase_fact": ("purchase_key", {"supplier_key": "supplier_dimension"}),
    "salesreturn_fact": ("return_key", {}),
    "sellout_fact": ("sellout_key", {"product_key": "product_dimension"}),
    "inventory_fact": ("inventory_key", {"product_key": "product_dimension"}),
}
# dimension -> (key column, SQL joining source dimension row `s` to target dimension row `t` on its NATURAL key -
# the same keys scripts/run_canonical_load.py resolves on)
DIMENSIONS = {
    "product_dimension": ("product_key", "t.principal = s.principal AND t.grain = s.grain AND t.sku_code IS NOT DISTINCT FROM s.sku_code "
                                         "AND (s.grain = 'sku' OR t.category_path IS NOT DISTINCT FROM s.category_path)"),
    "customer_dimension": ("customer_key", "t.customer_name IS NOT DISTINCT FROM s.customer_name AND t.region IS NOT DISTINCT FROM s.region "
                                           "AND t.principal IS NOT DISTINCT FROM s.principal"),
    "salesman_dimension": ("salesman_key", "t.salesman_name IS NOT DISTINCT FROM s.salesman_name"),
    "supplier_dimension": ("supplier_key", "t.supplier_name IS NOT DISTINCT FROM s.supplier_name"),
}
ISOLATION = ["forecast_result", "abc_classification", "sku_segment", "sku_traits"]
REAL_VIEWS = ["sales_fact_real", "purchase_fact_real", "salesreturn_fact_real", "sellout_fact_real", "inventory_fact_real",
              "unilever_sku_demand_fact_real"]
# Del Monte SKU-grain products that nothing references once the v1 demo inventory rows are gone
ORPHAN_PRODUCTS = """SELECT pd.product_key FROM {T}.product_dimension pd
    WHERE pd.principal = 'delmonte' AND pd.grain = 'sku'
      AND NOT EXISTS (SELECT 1 FROM {T}.inventory_fact x WHERE x.product_key = pd.product_key)
      AND NOT EXISTS (SELECT 1 FROM {T}.sellout_fact x WHERE x.product_key = pd.product_key)
      AND NOT EXISTS (SELECT 1 FROM {T}.unilever_sku_demand_fact x WHERE x.product_key = pd.product_key)
      AND NOT EXISTS (SELECT 1 FROM {T}.abc_classification x WHERE x.product_key = pd.product_key AND x.method = 'single')
      AND NOT EXISTS (SELECT 1 FROM {T}.forecast_result x WHERE x.product_key = pd.product_key)
      AND NOT EXISTS (SELECT 1 FROM {T}.lp_recommendation x WHERE x.product_key = pd.product_key)
      AND NOT EXISTS (SELECT 1 FROM {T}.sku_traits x WHERE x.product_key = pd.product_key)
      AND NOT EXISTS (SELECT 1 FROM {T}.sku_segment x WHERE x.product_key = pd.product_key)"""
REHEARSAL_TABLES = list(FACTS) + list(DIMENSIONS) + ISOLATION + ["lp_recommendation", "date_dimension"]


def connect():
    load_dotenv(REPO / ".env")
    dsn = os.environ["SUPABASE_DIRECT_URL"]
    if urlparse(dsn).port != 5432:
        sys.exit("refusing: SUPABASE_DIRECT_URL is not the direct connection (port 5432)")
    conn = psycopg2.connect(dsn, options="-c statement_timeout=0")
    conn.autocommit = False
    return conn


def one(cur, sql, args=None):
    cur.execute(sql, args)
    return cur.fetchone()[0]


def columns(cur, schema, table):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position", (schema, table))
    return [r[0] for r in cur.fetchall()]


def fingerprint(cur, schema, table, where="TRUE"):
    """(rows, md5 over every column of every matching row, in primary-key order)."""
    cur.execute(f"""SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = '{schema}.{table}'::regclass AND i.indisprimary""")
    pk = ", ".join(r[0] for r in cur.fetchall())
    cur.execute(f"SELECT COUNT(*), md5(COALESCE(string_agg(md5(x::text), '' ORDER BY {pk}), '')) FROM {schema}.{table} x WHERE {where}")
    return tuple(cur.fetchone())


def snapshot(cur, T):
    snap = {f"real:{t}": fingerprint(cur, T, t, "NOT is_demo") for t in FACTS}
    snap.update({f"isolation:{t}": fingerprint(cur, T, t) for t in ISOLATION})
    for v in REAL_VIEWS:
        if one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{T}.{v}",)):
            snap[f"view:{v}"] = (one(cur, f"SELECT COUNT(*) FROM {T}.{v}"), None)
    return snap


def backup(cur, T, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"target": T, "taken_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "tables": {}}
    for t in list(FACTS) + ["product_dimension"]:
        buf = io.StringIO()
        cur.copy_expert(f"COPY (SELECT * FROM {T}.{t} ORDER BY 1) TO STDOUT WITH (FORMAT csv, HEADER true)", buf)
        data = buf.getvalue().encode("utf-8")
        (out_dir / f"{t}.csv").write_bytes(data)
        manifest["tables"][t] = {"rows": data.count(b"\n") - 1, "md5": hashlib.md5(data).hexdigest(), "columns": columns(cur, T, t)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def build_rehearsal(cur, R):
    """A scratch copy of the live tables this script touches or checks - same keys, same rows."""
    cur.execute(f"DROP SCHEMA IF EXISTS {R} CASCADE")
    cur.execute(f"CREATE SCHEMA {R}")
    for t in REHEARSAL_TABLES:
        cur.execute(f"CREATE TABLE {R}.{t} (LIKE public.{t} INCLUDING DEFAULTS INCLUDING IDENTITY INCLUDING INDEXES)")
        cur.execute(f"INSERT INTO {R}.{t} OVERRIDING SYSTEM VALUE SELECT * FROM public.{t}")
    for v, t in zip(REAL_VIEWS, ["sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact", "unilever_sku_demand_fact"]):
        cur.execute(f"CREATE VIEW {R}.{v} AS SELECT * FROM {R}.{t} WHERE is_demo = false")


def cutover(cur, S, T, checks: list):
    def check(name, got, want):
        ok = got == want
        checks.append(ok)
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f"   (expected {want})"))

    before = snapshot(cur, T)
    expected_orphans_now = one(cur, f"SELECT COUNT(*) FROM ({ORPHAN_PRODUCTS.format(T=T)}) o")
    for t, (ident, fks) in FACTS.items():
        v1 = one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE is_demo")
        src = one(cur, f"SELECT COUNT(*) FROM {S}.{t} WHERE is_demo")
        cur.execute(f"DELETE FROM {T}.{t} WHERE is_demo = true")
        deleted = cur.rowcount
        cols = [c for c in columns(cur, T, t) if c != ident and c in columns(cur, S, t)]
        select, joins, orphan_tests = [], [], []
        for c in cols:
            if c in fks:
                dim = fks[c]; key, on = DIMENSIONS[dim]; a = f"s_{c}"; b = f"t_{c}"
                joins.append(f"LEFT JOIN {S}.{dim} {a} ON {a}.{key} = f.{c} "
                             f"LEFT JOIN {T}.{dim} {b} ON {on.replace('t.', b + '.').replace('s.', a + '.')}")
                select.append(f"{b}.{key}")
                orphan_tests.append(f"(f.{c} IS NOT NULL AND {b}.{key} IS NULL)")
            else:
                select.append(f"f.{c}")
        base = f"FROM {S}.{t} f {' '.join(joins)} WHERE f.is_demo = true"
        orphans = one(cur, f"SELECT COUNT(*) {base} AND ({' OR '.join(orphan_tests)})") if orphan_tests else 0
        cur.execute(f"INSERT INTO {T}.{t} ({', '.join(cols)}) SELECT {', '.join(select)} {base}")
        print(f"{t}: demo v1 {v1} -> deleted {deleted}, inserted {cur.rowcount} (source {src})")
        check(f"{t}: every v1 demo row deleted", deleted, v1)
        check(f"{t}: demo rows now equal the source", one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE is_demo"), src)
        check(f"{t}: source demo rows with no matching dimension row in the target", orphans, 0)

    orphan_keys = ORPHAN_PRODUCTS.format(T=T)
    n_orphans = one(cur, f"SELECT COUNT(*) FROM ({orphan_keys}) o")
    cur.execute(f"DELETE FROM {T}.product_dimension WHERE product_key IN ({orphan_keys})")
    print(f"product_dimension: {cur.rowcount} Del Monte SKU rows with no reference anywhere removed "
          f"({expected_orphans_now} were already unreferenced before the demo replacement)")
    check("product_dimension rows removed equals the orphan count", cur.rowcount, n_orphans)
    check("Del Monte SKU-grain products left without a real inventory row",
          one(cur, f"""SELECT COUNT(*) FROM {T}.product_dimension pd WHERE principal = 'delmonte' AND grain = 'sku'
                       AND NOT EXISTS (SELECT 1 FROM {T}.inventory_fact i WHERE i.product_key = pd.product_key AND NOT i.is_demo)"""), 0)

    after = snapshot(cur, T)
    for k in before:
        check(f"unchanged - {k}", after[k], before[k])
    for t in FACTS:
        if "_period" in columns(cur, T, t):
            check(f"{t}: _period = 'unknown'", one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE _period = 'unknown'"), 0)
        if "net_amount" in columns(cur, T, t):
            check(f"{t}: NULL net_amount", one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE net_amount IS NULL"), 0)
    return n_orphans


def rollback_from(cur, backup_dir: Path, checks: list):
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    T = manifest["target"]
    for t, meta in manifest["tables"].items():
        raw = (backup_dir / f"{t}.csv").read_bytes()
        assert hashlib.md5(raw).hexdigest() == meta["md5"], f"{t}.csv does not match its recorded md5"
        cur.execute(f"CREATE TEMP TABLE bk_{t} (LIKE {T}.{t}) ON COMMIT DROP")
        cur.copy_expert(f"COPY bk_{t} FROM STDIN WITH (FORMAT csv, HEADER true)", io.StringIO(raw.decode("utf-8")))
    key = "product_key"
    cur.execute(f"INSERT INTO {T}.product_dimension OVERRIDING SYSTEM VALUE SELECT b.* FROM bk_product_dimension b "
                f"WHERE NOT EXISTS (SELECT 1 FROM {T}.product_dimension p WHERE p.{key} = b.{key})")
    print(f"product_dimension: {cur.rowcount} rows restored")
    for t in FACTS:
        cur.execute(f"DELETE FROM {T}.{t} WHERE is_demo = true")
        cur.execute(f"INSERT INTO {T}.{t} OVERRIDING SYSTEM VALUE SELECT * FROM bk_{t} WHERE is_demo = true")
        print(f"{t}: {cur.rowcount} v1 demo rows restored")
    for t, meta in manifest["tables"].items():
        buf = io.StringIO()
        cur.copy_expert(f"COPY (SELECT * FROM {T}.{t} ORDER BY 1) TO STDOUT WITH (FORMAT csv, HEADER true)", buf)
        ok = hashlib.md5(buf.getvalue().encode("utf-8")).hexdigest() == meta["md5"]
        checks.append(ok)
        print(f"  {'ok  ' if ok else 'FAIL'} {t} reproduces its pre-cutover md5")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="ssm_synth_v2", help="verified scratch schema holding the v2 demo rows")
    p.add_argument("--target", default=None, help="'public' for the real cutover")
    p.add_argument("--rehearse", default=None, metavar="SCHEMA", help="build a scratch copy of the live tables and run the cutover against it")
    p.add_argument("--rollback", default=None, metavar="BACKUP_DIR", help="restore from a backup this script took")
    p.add_argument("--i-have-approval", action="store_true", help="required for anything that writes to public")
    args = p.parse_args()

    conn = connect(); cur = conn.cursor(); checks: list = []
    try:
        if args.rollback:
            bdir = Path(args.rollback)
            target = json.loads((bdir / "manifest.json").read_text(encoding="utf-8"))["target"]
            if target == "public" and not args.i_have_approval:
                sys.exit("refusing: rolling back public needs --i-have-approval")
            rollback_from(cur, bdir, checks)
        else:
            if bool(args.target) == bool(args.rehearse):
                sys.exit("give exactly one of --target public or --rehearse <schema>")
            if args.rehearse:
                if args.rehearse == "public":
                    sys.exit("refusing: a rehearsal schema cannot be public")
                T = args.rehearse
                print(f"building rehearsal copy of the live tables in {T} ...")
                build_rehearsal(cur, T); conn.commit()
            else:
                T = args.target
                if T != "public" or not args.i_have_approval:
                    sys.exit("refusing: the only live target is public, and it needs --i-have-approval")
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            bdir = REPO / "backups" / f"synth_v2_cutover_{ts}{'' if T == 'public' else '_rehearsal'}"
            m = backup(cur, T, bdir)
            print(f"backup -> {bdir}: " + ", ".join(f"{t} {v['rows']}" for t, v in m["tables"].items()))
            cutover(cur, args.source, T, checks)
            print(f"\nrollback command:  python -m scripts.apply_synth_v2_to_public --rollback {bdir.relative_to(REPO).as_posix()}"
                  + (" --i-have-approval" if T == "public" else ""))
        if checks and all(checks):
            conn.commit(); print(f"\nALL {len(checks)} CHECKS PASSED - COMMITTED")
            return 0
        conn.rollback(); print(f"\n{checks.count(False)} CHECK(S) FAILED - ROLLED BACK, nothing changed")
        return 2
    except BaseException:
        conn.rollback(); print("\nEXCEPTION - ROLLED BACK, nothing changed")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
