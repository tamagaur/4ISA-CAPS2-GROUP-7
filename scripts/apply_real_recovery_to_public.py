"""scripts/apply_real_recovery_to_public.py - bring the live REAL rows in line with a verified scratch build of the
canonical loader (2026-09-22 rebuild: completeness-audit fixes + Yuan's rulings D11, D12, H1, X1-X4). Same pattern
as scripts/apply_synth_v2_to_public.py, opposite subject: that script only ever touches is_demo = true rows; this
one only ever touches is_demo = false rows and never reads or writes a synthetic row.

What it changes in the target, and nothing else (every count is asserted; a different number aborts):
  schema  migrations 0024 etl_quarantine, 0025 purchase key + invoice_date, 0026 brand_source CHECK,
          0027 invoice quantity columns + sell-out tax flag (and the three _Real views that expose them)
  D12  Purchase_Fact      the 18 Sept-2025 purchases are QUARANTINED, not inserted              expect 0 inserted
  F3   Inventory_Fact     sheet 'ILO 090223': region pangasinan -> ilocos                          expect 6
                          + the Ilocos stock lines that were deduped against Pangasinan rows       expect 193
  F4   Sales_Fact         + invoices that exist only on the ONE PAGER sheet              expect 57 / 559,369.32
  H1   Sales_Fact         - the 14 FAKE BOOKING invoices (moved to etl_quarantine)     expect 14 / 2,903,959.74
                          the other 564 rows of that sheet keep _period 2025-04 (pending SSM)      expect 0 moved
  X3   Sales_Fact         quantity_cases / quantity_pieces                                         expect 1,888
  X4   SalesReturn_Fact   quantity_cases / quantity_pieces (bo_units stays NULL)                   expect 227
  X2   SellOut_Fact       net_amount from "Total With Tax" (120 NULL + 2 merged 0.00)              expect 122
                          net_amount_tax_inclusive on every real row                    expect 122 TRUE / 1,245 FALSE
  X1/D11 Product_Dimension (Unilever SKU) pack_size NULL -> SOH value                             expect 291
                          brand_source (342 NULL + 38 SOH label with no SOH row now)               expect 380
                          brand (BF -> BESTFOODS, the alias table)                                 expect 1
                          product_name (the LADY'S CHOICE pair: live already holds the clean name) expect 0
  F1   etl_quarantine     the scratch build's REAL excluded rows, incl. the 14 + 18 above
Missing Customer / Salesman / Product dimension rows that new real rows need are inserted first, on the same natural
keys scripts/run_canonical_load.py resolves on.

Run this yourself - writes to `public` need Yuan's explicit go. Requires SUPABASE_DIRECT_URL (port 5432).

  rehearse on a scratch copy of the live tables (writes only to the rehearsal schema):
      python -m scripts.apply_real_recovery_to_public --source ssm_synth_v2 --rehearse ssm_recovery_rehearsal
  the real cutover:
      python -m scripts.apply_real_recovery_to_public --source ssm_synth_v2 --target public --i-have-approval
  undo it (uses the change log the cutover wrote next to its backup):
      python -m scripts.apply_real_recovery_to_public --rollback backups/real_recovery_<timestamp> --i-have-approval
  Rollback restores every row and value; the schema objects of 0024/0026/0027 stay (additive, emptied), 0025 is
  reverted.

One transaction. Before COMMIT it checks, and rolls back on any failure:
  - every expected count above;
  - the REAL rows of all six fact tables now equal the scratch build's, row for row, both directions, on every
    column including the new ones (EXCEPT ALL, surrogate keys compared through their natural keys);
  - Unilever SKU product rows equal the scratch build's on name / pack / brand / brand_source / category;
    every other Product_Dimension row is unchanged;
  - the SYNTHETIC rows of every fact table are unchanged (fingerprinted on the pre-migration columns);
  - Forecast_Result, sku_segment, sku_traits and ABC_Classification are unchanged. ABC reads are pinned by method:
    method = 'single' and every other method are fingerprinted separately, never read as one union.

STATUS 2026-09-22: rewritten for the 2026-09-22 rebuild; rehearsed against a copy of public, never run on public.
"""
from __future__ import annotations

import argparse
import datetime
import getpass
import hashlib
import io
import json
import sys
from pathlib import Path

from scripts.apply_synth_v2_to_public import DIMENSIONS, FACTS, REAL_VIEWS, columns, connect, one

REPO = Path(__file__).resolve().parent.parent
MIGRATIONS = ["0024_etl_quarantine.sql", "0025_purchase_fact_key_invoice_date.sql",
              "0026_brand_source_demand_first_token_rule.sql", "0027_invoice_quantities_and_sellout_tax_flag.sql"]
ILO_SHEET = "ILO 090223"
ONE_PAGER = "ONE PAGER"
FAKE_BOOKING_SHEET = "PANGASINAN SALES REGISTER (2)"
EXPECTED = {
    "purchase_to_insert": 0,
    "inventory_region_corrected": 6, "inventory_inserted": 193,
    "sales_inserted": 57, "sales_inserted_net": "559369.32",
    "sales_fake_booking_deleted": 14, "sales_fake_booking_net": "2903959.74", "sales_period_moved": 0,
    "sales_quantities_set": 1888, "salesreturn_quantities_set": 227,
    "sellout_net_amount_changed": 122, "sellout_flag_true": 122, "sellout_flag_false": 1245,
    "product_pack_size": 291, "product_brand_source": 380, "product_brand": 1, "product_product_name": 0, "product_category_path": 0,
}
LOAD_TIME = {"loaded_at", "created_at", "updated_at", "ingested_at"}
NEW_COLUMNS = {"sales_fact": ["quantity_cases", "quantity_pieces"], "salesreturn_fact": ["quantity_cases", "quantity_pieces"],
               "sellout_fact": ["net_amount_tax_inclusive"]}
# the live unique key of each fact whose real rows get a column-level update
FACT_KEY = {"sales_fact": ["invoice_num", "principal", "region"],
            "salesreturn_fact": ["return_slip_num", "principal", "region", "invoice_num"],
            "sellout_fact": ["category_path", "region", "_period"]}
PRODUCT_COLUMNS = ["product_name", "pack_size", "brand", "brand_source", "category_path"]
UNILEVER_SKU = "principal = 'unilever' AND grain = 'sku'"
BACKUP_TABLES = ["sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact",
                 "product_dimension", "customer_dimension", "salesman_dimension"]
# ABC_Classification is fingerprinted per method - never as the union of 'single' and 't3m' (tests/test_abc_reader_pinning.py)
ISOLATION = [("forecast_result", "TRUE"), ("sku_segment", "TRUE"), ("sku_traits", "TRUE"),
             ("abc_classification", "method = 'single'"), ("abc_classification", "method IS DISTINCT FROM 'single'")]
REHEARSAL_TABLES = list(FACTS) + list(DIMENSIONS) + sorted({t for t, _ in ISOLATION}) + [
    "lp_recommendation", "date_dimension", "schema_migrations"]
DIM_KEY = {"product_dimension": "product_key", "customer_dimension": "customer_key", "salesman_dimension": "salesman_key"}
NATURAL = {"product_dimension": ["principal", "grain", "sku_code", "category_path"], "customer_dimension": ["customer_name", "region", "principal"],
           "salesman_dimension": ["salesman_name"], "supplier_dimension": ["supplier_name"]}


def fingerprint(cur, schema: str, table: str, where: str, cols: list[str]) -> tuple:
    """(rows, md5 over the named columns of every matching row, in primary-key order). Explicit columns so adding a
    column (migration 0027) does not change the fingerprint of rows whose values did not change."""
    cur.execute(f"""SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = '{schema}.{table}'::regclass AND i.indisprimary""")
    pk = ", ".join(r[0] for r in cur.fetchall())
    row = "ROW(" + ", ".join(f'x."{c}"' for c in cols) + ")::text"
    cur.execute(f"SELECT COUNT(*), md5(COALESCE(string_agg(md5({row}), '' ORDER BY {pk}), '')) FROM {schema}.{table} x WHERE {where}")
    return tuple(cur.fetchone())


def real_select(cur, S: str, T: str, schema: str, table: str) -> str:
    """The real rows of `table` in `schema`, on every column S and T share, surrogate keys replaced by natural keys."""
    ident, fks = FACTS[table]
    t_cols = columns(cur, T, table)
    common = [c for c in columns(cur, S, table) if c in t_cols and c != ident and c not in LOAD_TIME]
    parts, joins = [], []
    for c in common:
        if c in fks:
            a = f"d_{c}"
            joins.append(f"LEFT JOIN {schema}.{fks[c]} {a} ON {a}.{c} = f.{c}")
            parts += [f"{a}.{n} AS {c}__{n}" for n in NATURAL[fks[c]]]
        else:
            parts.append(f"f.{c}")
    return f"SELECT {', '.join(parts)} FROM {schema}.{table} f {' '.join(joins)} WHERE NOT f.is_demo"


def real_diff(cur, S: str, T: str) -> dict:
    out = {}
    for t in FACTS:
        a, b = real_select(cur, S, T, T, t), real_select(cur, S, T, S, t)
        out[t] = (one(cur, f"SELECT COUNT(*) FROM ({a} EXCEPT ALL {b}) x"), one(cur, f"SELECT COUNT(*) FROM ({b} EXCEPT ALL {a}) x"))
    return out


def backup(cur, T: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"target": T, "taken_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "tables": {}}
    for t in BACKUP_TABLES:
        buf = io.StringIO()
        cur.copy_expert(f"COPY (SELECT * FROM {T}.{t} ORDER BY 1) TO STDOUT WITH (FORMAT csv, HEADER true)", buf)
        data = buf.getvalue().encode("utf-8")
        (out_dir / f"{t}.csv").write_bytes(data)
        manifest["tables"][t] = {"rows": one(cur, f"SELECT COUNT(*) FROM {T}.{t}"), "md5": hashlib.md5(data).hexdigest()}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def build_rehearsal(cur, R: str) -> None:
    cur.execute(f"DROP SCHEMA IF EXISTS {R} CASCADE")
    cur.execute(f"CREATE SCHEMA {R}")
    for t in REHEARSAL_TABLES:
        cur.execute(f"CREATE TABLE {R}.{t} (LIKE public.{t} INCLUDING DEFAULTS INCLUDING IDENTITY INCLUDING INDEXES INCLUDING CONSTRAINTS)")
        cur.execute(f"INSERT INTO {R}.{t} OVERRIDING SYSTEM VALUE SELECT * FROM public.{t}")
        # LIKE ... INCLUDING IDENTITY starts a NEW sequence at 1, and OVERRIDING SYSTEM VALUE never advances it - the
        # 2026-09-15 incident class. Mirror public's sequence position so the copy behaves as public will.
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s AND is_identity = 'YES'", (R, t))
        for (col,) in cur.fetchall():
            live = one(cur, "SELECT pg_get_serial_sequence(%s, %s)", (f"public.{t}", col))
            cur.execute(f"SELECT last_value, is_called FROM {live}")
            last_value, is_called = cur.fetchone()
            cur.execute("SELECT setval(pg_get_serial_sequence(%s, %s), %s, %s)", (f"{R}.{t}", col, last_value, is_called))
    # 0025 and 0026 drop a constraint BY NAME. LIKE re-creates constraints under the names public has - verified
    # here rather than assumed, or the rehearsal would not exercise the statements the live run will.
    for table, name in (("purchase_fact", "purchase_fact_invoice_num_principal_region_key"),
                        ("product_dimension", "product_dimension_brand_source_check")):
        if not one(cur, """SELECT COUNT(*) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace
                           WHERE n.nspname = %s AND t.relname = %s AND c.conname = %s""", (R, table, name)):
            raise RuntimeError(f"rehearsal {table} does not carry the live constraint name {name}")
    for v, t in zip(REAL_VIEWS, ["sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact", "unilever_sku_demand_fact"]):
        cur.execute(f"CREATE VIEW {R}.{v} AS SELECT * FROM {R}.{t} WHERE is_demo = false")


def apply_migrations(cur, T: str, log: dict) -> None:
    """Same ledger discipline as run_canonical_load.ensure_scratch_schema: checksum of the raw bytes, recorded in the
    same transaction as the apply; an already-recorded file is skipped, an edited one aborts."""
    from scripts.run_canonical_load import _strip_sql_file
    cur.execute(f"SET LOCAL search_path TO {T}, public")
    for name in MIGRATIONS:
        path = REPO / "analytics" / "db" / "migrations" / name
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        cur.execute(f"SELECT checksum FROM {T}.schema_migrations WHERE filename = %s", (name,))
        hit = cur.fetchone()
        if hit:
            if hit[0] and hit[0] != checksum:
                raise RuntimeError(f"{name} is recorded in {T}.schema_migrations with a different checksum")
            print(f"  migration {name}: already applied, skipped")
            continue
        cur.execute(_strip_sql_file(path.read_text(encoding="utf-8")).replace("%", "%%"))
        cur.execute(f"INSERT INTO {T}.schema_migrations (filename, checksum, applied_at, applied_by, target_schema) VALUES (%s, %s, now(), %s, %s)",
                    (name, checksum, getpass.getuser(), T))
        log["migrations_applied"].append(name)
        print(f"  migration {name}: applied")
    cur.execute("SET LOCAL search_path TO public")


def insert_missing_dimension_rows(cur, S: str, T: str, dim: str, needed_sql: str, log: dict) -> int:
    """Inserts the source dimension rows selected by `needed_sql` (source keys) that have no natural-key match in T."""
    key, match = DIM_KEY[dim], DIMENSIONS[dim][1]
    shared = [c for c in columns(cur, T, dim) if c in columns(cur, S, dim) and c != key and c not in LOAD_TIME]
    cur.execute(f"""INSERT INTO {T}.{dim} ({', '.join(shared)})
                    SELECT {', '.join('s.' + c for c in shared)} FROM {S}.{dim} s
                    WHERE s.{key} IN ({needed_sql}) AND NOT EXISTS (SELECT 1 FROM {T}.{dim} t WHERE {match})
                    RETURNING {key}""")
    keys = [r[0] for r in cur.fetchall()]
    log["inserted"].setdefault(dim, []).extend(keys)
    return len(keys)


def insert_fact_rows(cur, S: str, T: str, table: str, where_source: str, log: dict) -> int:
    """Copies the real source rows selected by `where_source` (alias s) into T, surrogate keys remapped by natural key.
    Aborts if a row's dimension match is missing - the dimension inserts above must already have run."""
    ident, fks = FACTS[table]
    cols = [c for c in columns(cur, T, table) if c in columns(cur, S, table) and c != ident and c not in LOAD_TIME]
    select, joins, guards = [], [], []
    for c in cols:
        if c in fks:
            dim = fks[c]; key, match = DIMENSIONS[dim]
            a = f"m_{c}"
            joins.append(f"LEFT JOIN {S}.{dim} sd_{c} ON sd_{c}.{key} = s.{c} "
                         f"LEFT JOIN LATERAL (SELECT t.{key} FROM {T}.{dim} t, (SELECT sd_{c}.*) s WHERE {match} LIMIT 1) {a} ON TRUE")
            select.append(f"CASE WHEN s.{c} IS NULL THEN NULL ELSE {a}.{key} END")
            guards.append(f"(s.{c} IS NOT NULL AND {a}.{key} IS NULL)")
        else:
            select.append(f"s.{c}")
    base = f"FROM {S}.{table} s {' '.join(joins)} WHERE NOT s.is_demo AND ({where_source})"
    if guards:
        orphans = one(cur, f"SELECT COUNT(*) {base} AND ({' OR '.join(guards)})")
        if orphans:
            raise RuntimeError(f"{table}: {orphans} source rows have no dimension match in {T}")
    cur.execute(f"INSERT INTO {T}.{table} ({', '.join(cols)}) SELECT {', '.join(select)} {base} RETURNING {ident}")
    keys = [r[0] for r in cur.fetchall()]
    log["inserted"].setdefault(table, []).extend(keys)
    return len(keys)


def key_join(table: str) -> str:
    return " AND ".join(f"s.{k} IS NOT DISTINCT FROM p.{k}" for k in FACT_KEY[table])


def update_fact_columns(cur, S: str, T: str, table: str, cols: list[str], log: dict, only_changed: bool = True) -> int:
    """Sets `cols` on real target rows from the real source row with the same live key. Old values are logged."""
    ident = FACTS[table][0]
    changed = " OR ".join(f"p.{c} IS DISTINCT FROM s.{c}" for c in cols) if only_changed else "TRUE"
    cur.execute(f"""SELECT p.{ident}, {', '.join('p.' + c for c in cols)} FROM {T}.{table} p JOIN {S}.{table} s ON {key_join(table)}
                    WHERE NOT p.is_demo AND NOT s.is_demo AND ({changed})""")
    old = cur.fetchall()
    cur.execute(f"""UPDATE {T}.{table} p SET {', '.join(f'{c} = s.{c}' for c in cols)} FROM {S}.{table} s
                    WHERE {key_join(table)} AND NOT p.is_demo AND NOT s.is_demo AND ({changed})""")
    if cur.rowcount != len(old):
        raise RuntimeError(f"{table}: updated {cur.rowcount} rows, selected {len(old)} - the key is not unique")
    log["updated"][f"{table}:{','.join(cols)}"] = {"key": ident, "old": [[str(r[0])] + [None if v is None else str(v) for v in r[1:]] for r in old]}
    return cur.rowcount


def cutover(cur, S: str, T: str, checks: list, log: dict) -> None:
    def check(name, got, want):
        ok = str(got) == str(want)
        checks.append((name, got, want, ok))
        print(f"  {'ok ' if ok else 'FAIL'} {name}: {got} (expected {want})")

    pre_columns = {t: columns(cur, T, t) for t in list(FACTS) + ["product_dimension"]}
    demo_before = {t: fingerprint(cur, T, t, "is_demo", pre_columns[t]) for t in FACTS}
    isolation_before = {(t, w): fingerprint(cur, T, t, w, columns(cur, T, t)) for t, w in ISOLATION}
    max_product_key = one(cur, f"SELECT COALESCE(MAX(product_key), 0) FROM {T}.product_dimension")
    other_products_before = fingerprint(cur, T, "product_dimension", f"NOT ({UNILEVER_SKU})", pre_columns["product_dimension"])
    log["pre_diff"] = real_diff(cur, S, T)
    print(f"  real-row diff before (target-only, source-only): {log['pre_diff']}")

    apply_migrations(cur, T, log)

    # D12 - purchase: the 18 are quarantined in the source build, so nothing is inserted
    check("D12 purchase rows to insert", one(cur, f"""SELECT COUNT(*) FROM {S}.purchase_fact s WHERE NOT s.is_demo AND NOT EXISTS (
        SELECT 1 FROM {T}.purchase_fact p WHERE NOT p.is_demo AND p.invoice_num = s.invoice_num AND p.principal = s.principal
        AND p.region IS NOT DISTINCT FROM s.region AND p.invoice_date IS NOT DISTINCT FROM s.invoice_date)"""), EXPECTED["purchase_to_insert"])

    # F3 - inventory: correct the 6 live rows first, so the 193 inserts cannot collide with them
    cur.execute(f"""UPDATE {T}.inventory_fact SET region = 'ilocos' WHERE NOT is_demo AND principal = 'delmonte' AND _src_sheet = %s
                    AND region = 'pangasinan' RETURNING inventory_key""", (ILO_SHEET,))
    keys = [r[0] for r in cur.fetchall()]
    log["updated"]["inventory_fact.region"] = {"keys": keys, "old": "pangasinan", "new": "ilocos"}
    check("F3 inventory rows re-tagged pangasinan -> ilocos", len(keys), EXPECTED["inventory_region_corrected"])
    where_inv = f"""s.principal = 'delmonte' AND s._src_sheet = '{ILO_SHEET}' AND NOT EXISTS (SELECT 1 FROM {T}.inventory_fact p WHERE NOT p.is_demo
        AND p.sku_code = s.sku_code AND p.snapshot_date = s.snapshot_date AND p.region IS NOT DISTINCT FROM s.region)"""
    nd = insert_missing_dimension_rows(cur, S, T, "product_dimension", f"SELECT s.product_key FROM {S}.inventory_fact s WHERE NOT s.is_demo AND {where_inv}", log)
    print(f"  product_dimension rows inserted for F3: {nd}")
    check("F3 inventory rows inserted", insert_fact_rows(cur, S, T, "inventory_fact", where_inv, log), EXPECTED["inventory_inserted"])

    # H1 - the 14 FAKE BOOKING invoices leave the fact table (the source build holds them in etl_quarantine)
    fake = f"""SELECT raw_values->>'invoice_num' FROM {S}.etl_quarantine WHERE NOT is_demo AND table_name = 'sales_fact'
               AND rule = 'flag_source_quarantine' AND reason = 'source remark: FAKE BOOKING'"""
    cur.execute(f"""DELETE FROM {T}.sales_fact p WHERE NOT p.is_demo AND p._src_sheet = %s AND p.invoice_num IN ({fake})
                    AND NOT EXISTS (SELECT 1 FROM {S}.sales_fact s WHERE NOT s.is_demo AND {key_join('sales_fact')})
                    RETURNING row_to_json(p)::text""", (FAKE_BOOKING_SHEET,))
    deleted = [json.loads(r[0]) for r in cur.fetchall()]
    log["deleted"]["sales_fact"] = deleted
    check("H1 FAKE BOOKING rows deleted", len(deleted), EXPECTED["sales_fake_booking_deleted"])
    check("H1 FAKE BOOKING net amount", f"{sum(float(r['net_amount']) for r in deleted):.2f}", EXPECTED["sales_fake_booking_net"])

    # F4 - sales
    where_sales = f"""s._src_sheet = '{ONE_PAGER}' AND NOT EXISTS (SELECT 1 FROM {T}.sales_fact p WHERE NOT p.is_demo AND p.invoice_num = s.invoice_num
        AND p.principal = s.principal AND p.region IS NOT DISTINCT FROM s.region)"""
    for dim, fk in (("customer_dimension", "customer_key"), ("salesman_dimension", "salesman_key")):
        nd = insert_missing_dimension_rows(cur, S, T, dim, f"SELECT s.{fk} FROM {S}.sales_fact s WHERE NOT s.is_demo AND {where_sales}", log)
        print(f"  {dim} rows inserted for F4: {nd}")
    check("F4 sales rows inserted", insert_fact_rows(cur, S, T, "sales_fact", where_sales, log), EXPECTED["sales_inserted"])
    check("F4 net amount of the inserted rows", one(cur, f"SELECT COALESCE(SUM(net_amount), 0)::text FROM {T}.sales_fact WHERE sales_key = ANY(%s)",
                                                     (log["inserted"].get("sales_fact", []),)), EXPECTED["sales_inserted_net"])

    # H1 - nothing changes month (F5 is exempted for the FAKE BOOKING sheet, and moves no other row)
    check("H1 sales rows whose _period differs from the source", one(cur, f"""SELECT COUNT(*) FROM {T}.sales_fact p JOIN {S}.sales_fact s ON {key_join('sales_fact')}
        WHERE NOT p.is_demo AND NOT s.is_demo AND p._period IS DISTINCT FROM s._period"""), EXPECTED["sales_period_moved"])

    # X3 / X4 / X2 - the 0027 columns and the sell-out amounts
    check("X3 sales rows given quantity_cases/pieces", update_fact_columns(cur, S, T, "sales_fact", NEW_COLUMNS["sales_fact"], log),
          EXPECTED["sales_quantities_set"])
    check("X4 sales return rows given quantity_cases/pieces", update_fact_columns(cur, S, T, "salesreturn_fact", NEW_COLUMNS["salesreturn_fact"], log),
          EXPECTED["salesreturn_quantities_set"])
    check("X2 sell-out net_amount changed", update_fact_columns(cur, S, T, "sellout_fact", ["net_amount"], log), EXPECTED["sellout_net_amount_changed"])
    update_fact_columns(cur, S, T, "sellout_fact", NEW_COLUMNS["sellout_fact"], log)
    check("X2 real sell-out rows flagged tax-inclusive", one(cur, f"SELECT COUNT(*) FROM {T}.sellout_fact WHERE NOT is_demo AND net_amount_tax_inclusive"),
          EXPECTED["sellout_flag_true"])
    check("X2 real sell-out rows flagged tax-exclusive", one(cur, f"SELECT COUNT(*) FROM {T}.sellout_fact WHERE NOT is_demo AND NOT net_amount_tax_inclusive"),
          EXPECTED["sellout_flag_false"])

    # X1 / D11 - Unilever SKU product details: every column set to the source's value where it differs
    for col in PRODUCT_COLUMNS:
        cur.execute(f"""SELECT p.product_key, p.{col} FROM {T}.product_dimension p JOIN {S}.product_dimension s USING (principal, grain, sku_code)
                        WHERE p.principal = 'unilever' AND p.grain = 'sku' AND p.{col} IS DISTINCT FROM s.{col}""")
        old = cur.fetchall()
        cur.execute(f"""UPDATE {T}.product_dimension p SET {col} = s.{col} FROM {S}.product_dimension s
                        WHERE p.principal = 'unilever' AND p.grain = 'sku' AND s.principal = p.principal AND s.grain = p.grain
                          AND s.sku_code = p.sku_code AND p.{col} IS DISTINCT FROM s.{col}""")
        log["updated"][f"product_dimension.{col}"] = {"old": [[k, v] for k, v in old]}
        check(f"X1/D11 Unilever SKU {col} changed", cur.rowcount, EXPECTED[f"product_{col}"])
    if "pack_size" in PRODUCT_COLUMNS:
        check("X1 pack_size values overwritten (was non-NULL)", sum(1 for _, v in log["updated"]["product_dimension.pack_size"]["old"] if v is not None), 0)

    # F1 - quarantine rows for the real data
    shared = [c for c in columns(cur, S, "etl_quarantine") if c != "quarantine_key"]
    cur.execute(f"INSERT INTO {T}.etl_quarantine ({', '.join(shared)}) SELECT {', '.join(shared)} FROM {S}.etl_quarantine WHERE NOT is_demo")
    copied = cur.rowcount
    cur.execute(f"SELECT DISTINCT run_id FROM {S}.etl_quarantine WHERE NOT is_demo")
    log["quarantine_run_ids"] = [r[0] for r in cur.fetchall()]
    check("F1 real quarantine rows copied", copied, one(cur, f"SELECT COUNT(*) FROM {S}.etl_quarantine WHERE NOT is_demo"))

    # proof
    log["post_diff"] = real_diff(cur, S, T)
    for t, (a, b) in log["post_diff"].items():
        check(f"{t}: real rows target-only / source-only after", (a, b), (0, 0))
        check(f"{t}: synthetic rows untouched", fingerprint(cur, T, t, "is_demo", pre_columns[t]), demo_before[t])
    uni = f"SELECT sku_code, {', '.join(PRODUCT_COLUMNS)} FROM {{s}}.product_dimension WHERE {UNILEVER_SKU}"
    check("Unilever SKU products target vs source, both ways",
          (one(cur, f"SELECT COUNT(*) FROM ({uni.format(s=T)} EXCEPT ALL {uni.format(s=S)}) x"),
           one(cur, f"SELECT COUNT(*) FROM ({uni.format(s=S)} EXCEPT ALL {uni.format(s=T)}) x")), (0, 0))
    check("other Product_Dimension rows untouched",
          fingerprint(cur, T, "product_dimension", f"NOT ({UNILEVER_SKU}) AND product_key <= {max_product_key}", pre_columns["product_dimension"]),
          other_products_before)
    for (t, w), before in isolation_before.items():
        check(f"{t} [{w}]: untouched", fingerprint(cur, T, t, w, columns(cur, T, t)), before)
    for t, keys in log["inserted"].items():
        if t in FACTS and "net_amount" in columns(cur, T, t):
            check(f"{t}: inserted rows with NULL or NaN net_amount",
                  one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE {FACTS[t][0]} = ANY(%s) AND (net_amount IS NULL OR net_amount = 'NaN')", (keys,)), 0)
        if t in FACTS:
            check(f"{t}: inserted rows with _period 'unknown' or is_demo",
                  one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE {FACTS[t][0]} = ANY(%s) AND (_period = 'unknown' OR is_demo)", (keys,)), 0)


def rollback_from(cur, backup_dir: Path, checks: list) -> None:
    log = json.loads((backup_dir / "changes.json").read_text(encoding="utf-8"))
    T = log["target"]
    for t in ("sales_fact", "inventory_fact", "purchase_fact"):  # facts before the dimension rows they reference
        keys = log["inserted"].get(t, [])
        cur.execute(f"DELETE FROM {T}.{t} WHERE {FACTS[t][0]} = ANY(%s) AND NOT is_demo", (keys,))
        checks.append((f"{t} inserted rows removed", cur.rowcount, len(keys), cur.rowcount == len(keys)))
    for dim, key in DIM_KEY.items():
        keys = log["inserted"].get(dim, [])
        cur.execute(f"DELETE FROM {T}.{dim} WHERE {key} = ANY(%s)", (keys,))
        checks.append((f"{dim} inserted rows removed", cur.rowcount, len(keys), cur.rowcount == len(keys)))
    for t, rows in log["deleted"].items():
        cols = [c for c in rows[0] if c not in NEW_COLUMNS.get(t, [])] if rows else []
        if rows:
            cur.execute(f"""INSERT INTO {T}.{t} ({', '.join(cols)}) OVERRIDING SYSTEM VALUE
                            SELECT {', '.join(cols)} FROM json_populate_recordset(NULL::{T}.{t}, %s::json)""", (json.dumps(rows),))
        checks.append((f"{t} deleted rows restored", cur.rowcount if rows else 0, len(rows), (cur.rowcount if rows else 0) == len(rows)))
    u = log["updated"]
    cur.execute(f"UPDATE {T}.inventory_fact SET region = %s WHERE inventory_key = ANY(%s)", (u["inventory_fact.region"]["old"], u["inventory_fact.region"]["keys"]))
    for name, entry in u.items():
        if ":" in name:  # fact column updates: restore the old value by surrogate key
            table, cols = name.split(":"); cols = cols.split(",")
            for r in entry["old"]:
                cur.execute(f"UPDATE {T}.{table} SET {', '.join(f'{c} = %s' for c in cols)} WHERE {entry['key']} = %s", (*r[1:], int(r[0])))
        elif name.startswith("product_dimension."):
            col = name.split(".", 1)[1]
            for k, v in entry["old"]:
                cur.execute(f"UPDATE {T}.product_dimension SET {col} = %s WHERE product_key = %s", (v, k))
    cur.execute(f"DELETE FROM {T}.etl_quarantine WHERE run_id = ANY(%s)", (log.get("quarantine_run_ids", []),))
    if "0025_purchase_fact_key_invoice_date.sql" in log["migrations_applied"]:
        cur.execute(f"ALTER TABLE {T}.purchase_fact DROP CONSTRAINT IF EXISTS purchase_fact_invoice_num_principal_region_invoice_date_key")
        cur.execute(f"ALTER TABLE {T}.purchase_fact ADD CONSTRAINT purchase_fact_invoice_num_principal_region_key UNIQUE (invoice_num, principal, region)")
        cur.execute(f"DELETE FROM {T}.schema_migrations WHERE filename = '0025_purchase_fact_key_invoice_date.sql'")
    # 0024 / 0026 / 0027 are additive and stay: etl_quarantine emptied of this run's rows, the wider brand_source CHECK,
    # and the 0027 columns, every value of which was NULL before the cutover and is restored to NULL above.
    for t, m in json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))["tables"].items():
        n = one(cur, f"SELECT COUNT(*) FROM {T}.{t}")
        checks.append((f"{t} row count back to the backup's", n, m["rows"], n == m["rows"]))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="ssm_synth_v2", help="verified scratch schema built by run_canonical_load (2026-09-22 rebuild)")
    p.add_argument("--target", default=None, help="'public' for the real cutover")
    p.add_argument("--rehearse", default=None, metavar="SCHEMA", help="build a scratch copy of the live tables and run the cutover against it")
    p.add_argument("--rollback", default=None, metavar="BACKUP_DIR", help="undo a cutover from the change log it wrote")
    p.add_argument("--i-have-approval", action="store_true", help="required for anything that writes to public")
    args = p.parse_args()
    if sum(bool(x) for x in (args.target, args.rehearse, args.rollback)) != 1:
        p.error("pass exactly one of --target public, --rehearse SCHEMA, --rollback BACKUP_DIR")
    if args.target and args.target != "public":
        p.error("--target only accepts 'public'; use --rehearse for anything else")
    if args.rehearse and (args.rehearse == "public" or args.rehearse == args.source):
        p.error("--rehearse needs its own scratch schema name")

    conn = connect()
    cur = conn.cursor()
    checks: list = []
    try:
        if args.rollback:
            backup_dir = Path(args.rollback)
            target = json.loads((backup_dir / "changes.json").read_text(encoding="utf-8"))["target"]
            if target == "public" and not args.i_have_approval:
                sys.exit("refusing: a rollback of public needs --i-have-approval")
            rollback_from(cur, backup_dir, checks)
        else:
            T = args.target or args.rehearse
            if T == "public" and not args.i_have_approval:
                sys.exit("refusing: writing to public needs --i-have-approval")
            if args.rehearse:
                build_rehearsal(cur, T)
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_dir = REPO / "backups" / f"real_recovery_{'rehearsal_' if args.rehearse else ''}{ts}"
            backup(cur, T, backup_dir)
            log = {"target": T, "source": args.source, "migrations_applied": [], "inserted": {}, "updated": {}, "deleted": {}}
            print(f"backup: {backup_dir}\nexpected: {EXPECTED}")
            cutover(cur, args.source, T, checks, log)
            (backup_dir / "changes.json").write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")
        failed = [c for c in checks if not c[3]]
        if failed:
            conn.rollback()
            print(f"\nROLLED BACK - {len(failed)} check(s) failed:")
            for name, got, want, _ in failed:
                print(f"  {name}: got {got}, expected {want}")
            return 1
        conn.commit()
        print(f"\nCOMMITTED - {len(checks)} checks passed.")
        if not args.rollback:
            print(f"undo with: python -m scripts.apply_real_recovery_to_public --rollback {backup_dir.relative_to(REPO).as_posix()} --i-have-approval")
        return 0
    except Exception:
        conn.rollback()
        print("\nROLLED BACK - exception, nothing written.")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
