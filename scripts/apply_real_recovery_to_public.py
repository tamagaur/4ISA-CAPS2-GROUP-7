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

CONNECTION ROUTE, documented deviation from the "direct URL only" rule (2026-09-23, Yuan informed):
  db.<ref>.supabase.co publishes an AAAA record and no A record, and this machine has no global IPv6 route, so
  getaddrinfo fails outright - the direct URL cannot be used from here at all. Measured the same day:
    direct 5432              DNS FAILED (AAAA-only, no IPv6 route)
    session pooler 5432      IPv4, connects, session mode      <- use this
    transaction pooler 6543  IPv4, connects, transaction mode  <- must NOT be used
  Session mode is the only workable substitute: this script needs one long-lived transaction per batch, session
  GUCs, CREATE TEMP TABLE ... ON COMMIT DROP (restore_from) and COPY ... TO STDOUT. Transaction mode gives none of
  those back reliably, which is what the "never 6543" rule is about; session mode on 5432 keeps every one of them.
  Trade-off accepted: a pooled hop adds a drop risk mid-statement (seen twice on 2026-09-23 during a 6-minute
  COPY). Batch mode is the mitigation - a dropped connection costs one batch, not the run. The statement timeout is
  set per session by connect() below, never through the libpq startup options, which the pooler drops.

  rehearse on a scratch copy of the live tables (writes only to the rehearsal schema):
      python -m scripts.apply_real_recovery_to_public --source ssm_synth_v2 --rehearse ssm_recovery_rehearsal --rebuild
  the real cutover, one batch at a time (the default: it runs ONE batch, then pauses and prints the resume line):
      python -m scripts.apply_real_recovery_to_public --source ssm_synth_v2 --target public --i-have-approval
      ... --target public --i-have-approval --from 5            resume at batch 5
      ... --target public --i-have-approval --batch 7           run exactly batch 7
      ... --target public --i-have-approval --max-batches 12    run up to 12 batches without pausing
      ... --target public --dry-run --batch 3                   run batch 3 and ROLL IT BACK
      ... --target public --status                              the ledger: what ran, what is left
  everything in one transaction instead (the pre-batch behaviour, same 42 checks):
      python -m scripts.apply_real_recovery_to_public --source ssm_synth_v2 --target public --i-have-approval --one-shot
  undo it (uses the change log the cutover wrote next to its backup):
      python -m scripts.apply_real_recovery_to_public --rollback backups/real_recovery_<timestamp> --i-have-approval
  full restore from the backup instead (independent of the change log; every touched table, row for row):
      python -m scripts.apply_real_recovery_to_public --restore backups/real_recovery_<timestamp> --i-have-approval
  Rollback and restore both end by re-hashing every backed-up table against the backup's md5 and resetting the
  identity sequences to the backup's positions, and both work from whatever stage the batches stopped at - they also
  clear that run's rows from the cutover ledger, so the next run starts clean. The schema objects of 0024/0026/0027 stay (additive, empty / NULL);
  0025 is reverted.

Batches. The work is split into 12 independent batches (1 migrations, 2-4 quarantine, 5 sales inserts, 6-8 the
0027 columns and sell-out amounts, 9 inventory, 10-11 Unilever SKU product details, 12 verification), each one
internally complete and each in its own transaction, each recorded in <target>.etl_cutover_ledger (batch_id,
description, table_name, expected_rows, applied_rows, checksum_before/after, started_at, finished_at, status,
change_log). A batch verifies its own expected count and its OWN rows' checksums before its COMMIT - never a
whole-table hash, which is taken exactly twice per run (baseline at the start, batch 12 at the end). It rolls
itself back on any mismatch; a
batch the ledger already records as done is skipped; a batch whose set is larger than 2,000 rows is written 2,000
rows per statement inside that batch's transaction. Batch 12 checks, and any failure rolls that batch back:
  - every expected count above;
  - the REAL rows of all six fact tables now equal the scratch build's, row for row, both directions, on every
    column including the new ones (EXCEPT ALL, surrogate keys compared through their natural keys);
  - Unilever SKU product rows equal the scratch build's on name / pack / brand / brand_source / category;
    every other Product_Dimension row is unchanged;
  - the SYNTHETIC rows of every fact table are unchanged (fingerprinted on the pre-migration columns);
  - Forecast_Result, sku_segment, sku_traits and ABC_Classification are unchanged. ABC reads are pinned by method:
    method = 'single' and every other method are fingerprinted separately, never read as one union.

STATUS 2026-09-23: batch mode added; rehearsed against a copy of public one-shot and batch by batch, never run on public.
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

from scripts.apply_synth_v2_to_public import DIMENSIONS, FACTS, REAL_VIEWS, columns, one
from scripts.apply_synth_v2_to_public import connect as _connect_direct

REPO = Path(__file__).resolve().parent.parent


def connect():
    """apply_synth_v2_to_public.connect() asks for statement_timeout=0 through the libpq startup `options`. A direct
    connection honours it; a pooler (Supavisor) silently DROPS it and the session keeps the database default of
    2min, which kills migration 0027 and the long COPY of the backup. Setting it on the session works on both, so
    it is set here explicitly rather than trusted to the handshake - verified 2026-09-23: startup options gave
    '2min' on both pooler ports, SET gave '0'."""
    conn = _connect_direct()
    cur = conn.cursor()
    cur.execute("SET statement_timeout = 0")
    cur.execute("SET idle_in_transaction_session_timeout = 0")
    cur.execute("SET lock_timeout = '30s'")
    conn.commit()
    return conn
MIGRATIONS = ["0024_etl_quarantine.sql", "0025_purchase_fact_key_invoice_date.sql",
              "0026_brand_source_demand_first_token_rule.sql", "0027_invoice_quantities_and_sellout_tax_flag.sql"]
ILO_SHEET = "ILO 090223"
ONE_PAGER = "ONE PAGER"
FAKE_BOOKING_SHEET = "PANGASINAN SALES REGISTER (2)"
# the two quarantine slices that get their own batch; everything else real in etl_quarantine is the remainder
FAKE_BOOKING_PRED = ("table_name = 'sales_fact' AND rule = 'flag_source_quarantine' "
                     "AND reason = 'source remark: FAKE BOOKING'")
# D12: the 18 stale Sept-2025 purchase lines. purchase_fact has 45 real quarantine rows in all - the other 27
# are _drop_uninsertable_quarantined_rows and travel with the remainder batch.
PURCHASE_PRED = "table_name = 'purchase_fact' AND rule = 'flag_source_quarantine'"
CHUNK = 2000  # a batch larger than this is written CHUNK rows per statement, inside the batch's own transaction
EXPECTED = {
    "purchase_to_insert": 0, "quarantine_purchases": 18,
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
# every table the cutover writes to (etl_quarantine is created by it: recorded as absent, restored to empty)
BACKUP_TABLES = ["sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact",
                 "product_dimension", "customer_dimension", "salesman_dimension", "schema_migrations", "etl_quarantine"]
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


def export_csv(cur, T: str, t: str, cols: list[str]) -> bytes:
    """The table on an EXPLICIT column list in primary-key order, so the checksum of an unchanged table stays the
    same after a migration adds a column."""
    buf = io.StringIO()
    cur.copy_expert(f"COPY (SELECT {', '.join(cols)} FROM {T}.{t} ORDER BY 1) TO STDOUT WITH (FORMAT csv, HEADER true)", buf)
    return buf.getvalue().encode("utf-8")


def identity_state(cur, T: str, t: str) -> dict:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s AND is_identity = 'YES'", (T, t))
    state = {}
    for (col,) in cur.fetchall():
        cur.execute(f"SELECT last_value, is_called FROM {one(cur, 'SELECT pg_get_serial_sequence(%s, %s)', (f'{T}.{t}', col))}")
        state[col] = list(cur.fetchone())
    return state


def backup(cur, T: str, out_dir: Path) -> None:
    """Full backup of every table the cutover writes to: data (CSV), column list, row count, md5, identity-sequence
    positions. `--restore <dir>` puts all of it back; `--verify-backup <dir>` re-reads and re-hashes the files."""
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"target": T, "taken_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "tables": {}}
    for t in BACKUP_TABLES:
        if not one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{T}.{t}",)):
            manifest["tables"][t] = {"absent": True}
            continue
        cols = columns(cur, T, t)
        data = export_csv(cur, T, t, cols)
        (out_dir / f"{t}.csv").write_bytes(data)
        manifest["tables"][t] = {"rows": one(cur, f"SELECT COUNT(*) FROM {T}.{t}"), "md5": hashlib.md5(data).hexdigest(),
                                 "columns": cols, "identity": identity_state(cur, T, t)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def reset_sequences(cur, T: str, manifest: dict, checks: list) -> None:
    """Identity sequences back to the backup's positions - refused for a table whose current max key is above the
    saved position (a row written after the backup would then collide)."""
    for t, m in manifest["tables"].items():
        for col, (last_value, is_called) in m.get("identity", {}).items():
            current_max = one(cur, f"SELECT COALESCE(MAX({col}), 0) FROM {T}.{t}")
            ok = current_max <= last_value
            checks.append((f"{t}.{col} max key {current_max} <= saved sequence {last_value}", ok, True, ok))
            if ok:
                cur.execute("SELECT setval(pg_get_serial_sequence(%s, %s), %s, %s)", (f"{T}.{t}", col, last_value, is_called))


def verify_against_backup(cur, T: str, backup_dir: Path, manifest: dict, checks: list) -> None:
    for t, m in manifest["tables"].items():
        if m.get("absent"):
            present = one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{T}.{t}",))
            n = one(cur, f"SELECT COUNT(*) FROM {T}.{t}") if present else 0
            checks.append((f"{t} (absent at backup) holds no rows", n, 0, n == 0))
            continue
        got = hashlib.md5(export_csv(cur, T, t, m["columns"])).hexdigest()
        checks.append((f"{t} md5 equals the backup's", got, m["md5"], got == m["md5"]))
        extra = [c for c in columns(cur, T, t) if c not in m["columns"]]
        if extra:
            nonnull = one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE " + " OR ".join(f"{c} IS NOT NULL" for c in extra))
            checks.append((f"{t} columns added after the backup {extra} hold no value", nonnull, 0, nonnull == 0))
        state = identity_state(cur, T, t)
        checks.append((f"{t} identity sequences equal the backup's", state, m["identity"], state == m["identity"]))


def revert_purchase_key(cur, T: str) -> None:
    cur.execute(f"ALTER TABLE {T}.purchase_fact DROP CONSTRAINT IF EXISTS purchase_fact_invoice_num_principal_region_invoice_date_key")
    cur.execute(f"""ALTER TABLE {T}.purchase_fact DROP CONSTRAINT IF EXISTS purchase_fact_invoice_num_principal_region_key""")
    cur.execute(f"ALTER TABLE {T}.purchase_fact ADD CONSTRAINT purchase_fact_invoice_num_principal_region_key UNIQUE (invoice_num, principal, region)")


def restore_from(cur, backup_dir: Path, checks: list) -> None:
    """Puts every backed-up table back to the backup, row for row, by primary key: rows the backup does not have are
    deleted, rows it has are re-inserted with their original keys, changed rows are overwritten. Columns a migration
    added after the backup go back to NULL. No TRUNCATE, no DROP of a table; migration 0025's key is reverted, the
    additive objects of 0024/0026/0027 stay (empty / NULL)."""
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    T = manifest["target"]
    for name, m in manifest["tables"].items():
        if not m.get("absent") and hashlib.md5((backup_dir / f"{name}.csv").read_bytes()).hexdigest() != m["md5"]:
            raise RuntimeError(f"{name}.csv does not match its manifest md5 - backup damaged, nothing restored")
    order = ["sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact", "etl_quarantine",
             "customer_dimension", "salesman_dimension", "product_dimension", "schema_migrations"]
    for t in order:
        m = manifest["tables"][t]
        if m.get("absent"):
            if one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{T}.{t}",)):
                cur.execute(f"DELETE FROM {T}.{t}")
            continue
        pk = one(cur, f"""SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                          WHERE i.indrelid = '{T}.{t}'::regclass AND i.indisprimary""")
        cols = m["columns"]
        cur.execute(f"CREATE TEMP TABLE bk (LIKE {T}.{t}) ON COMMIT DROP")
        with open(backup_dir / f"{t}.csv", encoding="utf-8") as fh:
            cur.copy_expert(f"COPY bk ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, HEADER true)", fh)
        cur.execute(f"DELETE FROM {T}.{t} x WHERE NOT EXISTS (SELECT 1 FROM bk WHERE bk.{pk} = x.{pk})")
        deleted = cur.rowcount
        every = columns(cur, T, t)
        cur.execute(f"""UPDATE {T}.{t} x SET {', '.join(f'{c} = bk.{c}' for c in every if c != pk)} FROM bk
                        WHERE bk.{pk} = x.{pk} AND ROW({', '.join('x.' + c for c in every)}) IS DISTINCT FROM ROW({', '.join('bk.' + c for c in every)})""")
        updated = cur.rowcount
        cur.execute(f"""INSERT INTO {T}.{t} ({', '.join(every)}) OVERRIDING SYSTEM VALUE
                        SELECT {', '.join('bk.' + c for c in every)} FROM bk WHERE NOT EXISTS (SELECT 1 FROM {T}.{t} x WHERE x.{pk} = bk.{pk})""")
        print(f"  restore {t}: deleted {deleted}, updated {updated}, re-inserted {cur.rowcount}")
        cur.execute("DROP TABLE bk")
    if one(cur, """SELECT COUNT(*) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace
                   WHERE n.nspname = %s AND t.relname = 'purchase_fact' AND c.conname = 'purchase_fact_invoice_num_principal_region_invoice_date_key'""", (T,)):
        revert_purchase_key(cur, T)
    reset_sequences(cur, T, manifest, checks)
    verify_against_backup(cur, T, backup_dir, manifest, checks)


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
    keys = []
    if one(cur, f"SELECT COUNT(*) {base}") > CHUNK:
        cur.execute(f"SELECT s.{ident} {base} ORDER BY s.{ident}")
        for part in chunks([r[0] for r in cur.fetchall()]):
            cur.execute(f"INSERT INTO {T}.{table} ({', '.join(cols)}) SELECT {', '.join(select)} {base} "
                        f"AND s.{ident} = ANY(%s) RETURNING {ident}", (part,))
            keys += [r[0] for r in cur.fetchall()]
    else:
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
    updated = 0
    for part in chunks([r[0] for r in old]):
        cur.execute(f"""UPDATE {T}.{table} p SET {', '.join(f'{c} = s.{c}' for c in cols)} FROM {S}.{table} s
                        WHERE {key_join(table)} AND NOT p.is_demo AND NOT s.is_demo AND ({changed})
                          AND p.{ident} = ANY(%s)""", (part,))
        updated += cur.rowcount
    if updated != len(old):
        raise RuntimeError(f"{table}: updated {updated} rows, selected {len(old)} - the key is not unique")
    log["updated"][f"{table}:{','.join(cols)}"] = {"key": ident, "old": [[str(r[0])] + [None if v is None else str(v) for v in r[1:]] for r in old]}
    return updated


def rollback_from(cur, backup_dir: Path, checks: list) -> None:
    log = json.loads((backup_dir / "changes.json").read_text(encoding="utf-8"))
    T = log["target"]
    log.setdefault("inserted", {}); log.setdefault("deleted", {}); log.setdefault("updated", {})
    log.setdefault("migrations_applied", [])
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
    if "inventory_fact.region" in u:  # batch 9 may not have run
        cur.execute(f"UPDATE {T}.inventory_fact SET region = %s WHERE inventory_key = ANY(%s)",
                    (u["inventory_fact.region"]["old"], u["inventory_fact.region"]["keys"]))
    for name, entry in u.items():
        if name == "inventory_fact.region":
            continue
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
        revert_purchase_key(cur, T)
    # The ledger goes back to the backup's rows. 0024 / 0026 / 0027 are additive and their objects stay: etl_quarantine
    # (emptied of this run's rows), the wider brand_source CHECK, and the 0027 columns, every value of which was NULL
    # before the cutover and is NULL again. A later re-apply re-runs those three files; all are idempotent.
    cur.execute(f"DELETE FROM {T}.schema_migrations WHERE filename = ANY(%s)", (log["migrations_applied"],))
    for t in NEW_COLUMNS:
        if "0027_invoice_quantities_and_sellout_tax_flag.sql" not in log["migrations_applied"]:
            continue
        cur.execute(f"UPDATE {T}.{t} SET {', '.join(f'{c} = NULL' for c in NEW_COLUMNS[t])} WHERE "
                    + " OR ".join(f"{c} IS NOT NULL" for c in NEW_COLUMNS[t]))
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    reset_sequences(cur, T, manifest, checks)
    verify_against_backup(cur, T, backup_dir, manifest, checks)


# ---------------------------------------------------------------------------------------------------------------
# Batch mode. The work above is split into independent batches, each one internally complete, each in its own
# transaction, each recorded in <target>.etl_cutover_ledger. A run can be stopped after any batch and resumed later;
# re-running a batch the ledger already records as done is a no-op. The one-shot path runs the same batch list in a
# single transaction, so both paths produce the identical 42 checks.
# ---------------------------------------------------------------------------------------------------------------
LEDGER = "etl_cutover_ledger"


def chunks(xs: list, n: int = CHUNK):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def copy_quarantine(cur, S: str, T: str, predicate: str, log: dict) -> int:
    """Copies the real source quarantine rows matching `predicate` into T, CHUNK rows per statement."""
    shared = [c for c in columns(cur, S, "etl_quarantine") if c != "quarantine_key"]
    cur.execute(f"SELECT quarantine_key FROM {S}.etl_quarantine WHERE NOT is_demo AND ({predicate}) ORDER BY quarantine_key")
    keys = [r[0] for r in cur.fetchall()]
    copied = 0
    for part in chunks(keys):
        cur.execute(f"INSERT INTO {T}.etl_quarantine ({', '.join(shared)}) SELECT {', '.join(shared)} "
                    f"FROM {S}.etl_quarantine WHERE quarantine_key = ANY(%s)", (part,))
        copied += cur.rowcount
    if keys:
        cur.execute(f"SELECT DISTINCT run_id FROM {S}.etl_quarantine WHERE quarantine_key = ANY(%s)", (keys,))
        for (r,) in cur.fetchall():
            if r not in log["quarantine_run_ids"]:
                log["quarantine_run_ids"].append(r)
    return copied


def capture_baseline(cur, S: str, T: str) -> dict:
    """Everything the final verification compares against, read before the first batch writes anything. Persisted in
    the ledger (batch 0) so a resumed run verifies against the state the run actually started from."""
    pre_columns = {t: columns(cur, T, t) for t in list(FACTS) + ["product_dimension"]}
    return {
        "pre_columns": pre_columns,
        "demo_before": {t: list(fingerprint(cur, T, t, "is_demo", pre_columns[t])) for t in FACTS},
        "isolation_before": {f"{t}|{w}": list(fingerprint(cur, T, t, w, columns(cur, T, t))) for t, w in ISOLATION},
        "max_product_key": one(cur, f"SELECT COALESCE(MAX(product_key), 0) FROM {T}.product_dimension"),
        "other_products_before": list(fingerprint(cur, T, "product_dimension", f"NOT ({UNILEVER_SKU})", pre_columns["product_dimension"])),
        "pre_diff": {t: list(v) for t, v in real_diff(cur, S, T).items()},
    }


# --- the batches ------------------------------------------------------------------------------------------------

def b_migrations(cur, S, T, ctx, check, log):
    apply_migrations(cur, T, log)
    return len(MIGRATIONS), one(cur, f"SELECT COUNT(*) FROM {T}.schema_migrations WHERE filename = ANY(%s)", (MIGRATIONS,))


def b_quarantine_fake_booking(cur, S, T, ctx, check, log):
    copied = copy_quarantine(cur, S, T, FAKE_BOOKING_PRED, log)
    if copied != EXPECTED["sales_fake_booking_deleted"]:
        raise RuntimeError(f"{copied} FAKE BOOKING quarantine rows in {S}, expected {EXPECTED['sales_fake_booking_deleted']}")
    fake = f"SELECT raw_values->>'invoice_num' FROM {S}.etl_quarantine WHERE NOT is_demo AND ({FAKE_BOOKING_PRED})"
    cur.execute(f"""DELETE FROM {T}.sales_fact p WHERE NOT p.is_demo AND p._src_sheet = %s AND p.invoice_num IN ({fake})
                    AND NOT EXISTS (SELECT 1 FROM {S}.sales_fact s WHERE NOT s.is_demo AND {key_join('sales_fact')})
                    RETURNING row_to_json(p)::text""", (FAKE_BOOKING_SHEET,))
    deleted = [json.loads(r[0]) for r in cur.fetchall()]
    log["deleted"]["sales_fact"] = deleted
    check("H1 FAKE BOOKING rows deleted", len(deleted), EXPECTED["sales_fake_booking_deleted"])
    check("H1 FAKE BOOKING net amount", f"{sum(float(r['net_amount']) for r in deleted):.2f}", EXPECTED["sales_fake_booking_net"])
    return EXPECTED["sales_fake_booking_deleted"], len(deleted)


def b_quarantine_purchases(cur, S, T, ctx, check, log):
    copied = copy_quarantine(cur, S, T, PURCHASE_PRED, log)
    # D12 - the 18 are quarantined in the source build, so nothing is inserted into purchase_fact
    check("D12 purchase rows to insert", one(cur, f"""SELECT COUNT(*) FROM {S}.purchase_fact s WHERE NOT s.is_demo AND NOT EXISTS (
        SELECT 1 FROM {T}.purchase_fact p WHERE NOT p.is_demo AND p.invoice_num = s.invoice_num AND p.principal = s.principal
        AND p.region IS NOT DISTINCT FROM s.region AND p.invoice_date IS NOT DISTINCT FROM s.invoice_date)"""), EXPECTED["purchase_to_insert"])
    return EXPECTED["quarantine_purchases"], copied


def b_quarantine_rest(cur, S, T, ctx, check, log):
    rest = f"NOT ({PURCHASE_PRED}) AND NOT ({FAKE_BOOKING_PRED})"
    expected = one(cur, f"SELECT COUNT(*) FROM {S}.etl_quarantine WHERE NOT is_demo AND ({rest})")
    copied = copy_quarantine(cur, S, T, rest, log)
    check("F1 real quarantine rows copied", one(cur, f"SELECT COUNT(*) FROM {T}.etl_quarantine"),
          one(cur, f"SELECT COUNT(*) FROM {S}.etl_quarantine WHERE NOT is_demo"))
    return expected, copied


def b_sales_one_pager(cur, S, T, ctx, check, log):
    where_sales = f"""s._src_sheet = '{ONE_PAGER}' AND NOT EXISTS (SELECT 1 FROM {T}.sales_fact p WHERE NOT p.is_demo AND p.invoice_num = s.invoice_num
        AND p.principal = s.principal AND p.region IS NOT DISTINCT FROM s.region)"""
    for dim, fk in (("customer_dimension", "customer_key"), ("salesman_dimension", "salesman_key")):
        nd = insert_missing_dimension_rows(cur, S, T, dim, f"SELECT s.{fk} FROM {S}.sales_fact s WHERE NOT s.is_demo AND {where_sales}", log)
        print(f"    {dim} rows inserted for F4: {nd}")
    inserted = insert_fact_rows(cur, S, T, "sales_fact", where_sales, log)
    check("F4 sales rows inserted", inserted, EXPECTED["sales_inserted"])
    check("F4 net amount of the inserted rows", one(cur, f"SELECT COALESCE(SUM(net_amount), 0)::text FROM {T}.sales_fact WHERE sales_key = ANY(%s)",
                                                     (log["inserted"].get("sales_fact", []),)), EXPECTED["sales_inserted_net"])
    # H1 - nothing changes month (F5 is exempted for the FAKE BOOKING sheet, and moves no other row)
    check("H1 sales rows whose _period differs from the source", one(cur, f"""SELECT COUNT(*) FROM {T}.sales_fact p JOIN {S}.sales_fact s ON {key_join('sales_fact')}
        WHERE NOT p.is_demo AND NOT s.is_demo AND p._period IS DISTINCT FROM s._period"""), EXPECTED["sales_period_moved"])
    return EXPECTED["sales_inserted"], inserted


def b_sales_quantities(cur, S, T, ctx, check, log):
    n = update_fact_columns(cur, S, T, "sales_fact", NEW_COLUMNS["sales_fact"], log)
    check("X3 sales rows given quantity_cases/pieces", n, EXPECTED["sales_quantities_set"])
    return EXPECTED["sales_quantities_set"], n


def b_return_quantities(cur, S, T, ctx, check, log):
    n = update_fact_columns(cur, S, T, "salesreturn_fact", NEW_COLUMNS["salesreturn_fact"], log)
    check("X4 sales return rows given quantity_cases/pieces", n, EXPECTED["salesreturn_quantities_set"])
    return EXPECTED["salesreturn_quantities_set"], n


def b_sellout(cur, S, T, ctx, check, log):
    n = update_fact_columns(cur, S, T, "sellout_fact", ["net_amount"], log)
    check("X2 sell-out net_amount changed", n, EXPECTED["sellout_net_amount_changed"])
    update_fact_columns(cur, S, T, "sellout_fact", NEW_COLUMNS["sellout_fact"], log)
    check("X2 real sell-out rows flagged tax-inclusive", one(cur, f"SELECT COUNT(*) FROM {T}.sellout_fact WHERE NOT is_demo AND net_amount_tax_inclusive"),
          EXPECTED["sellout_flag_true"])
    check("X2 real sell-out rows flagged tax-exclusive", one(cur, f"SELECT COUNT(*) FROM {T}.sellout_fact WHERE NOT is_demo AND NOT net_amount_tax_inclusive"),
          EXPECTED["sellout_flag_false"])
    return EXPECTED["sellout_net_amount_changed"], n


def b_inventory(cur, S, T, ctx, check, log):
    # F3 - correct the 6 live rows first, so the 193 inserts cannot collide with them
    cur.execute(f"""UPDATE {T}.inventory_fact SET region = 'ilocos' WHERE NOT is_demo AND principal = 'delmonte' AND _src_sheet = %s
                    AND region = 'pangasinan' RETURNING inventory_key""", (ILO_SHEET,))
    keys = [r[0] for r in cur.fetchall()]
    log["updated"]["inventory_fact.region"] = {"keys": keys, "old": "pangasinan", "new": "ilocos"}
    check("F3 inventory rows re-tagged pangasinan -> ilocos", len(keys), EXPECTED["inventory_region_corrected"])
    where_inv = f"""s.principal = 'delmonte' AND s._src_sheet = '{ILO_SHEET}' AND NOT EXISTS (SELECT 1 FROM {T}.inventory_fact p WHERE NOT p.is_demo
        AND p.sku_code = s.sku_code AND p.snapshot_date = s.snapshot_date AND p.region IS NOT DISTINCT FROM s.region)"""
    nd = insert_missing_dimension_rows(cur, S, T, "product_dimension", f"SELECT s.product_key FROM {S}.inventory_fact s WHERE NOT s.is_demo AND {where_inv}", log)
    print(f"    product_dimension rows inserted for F3: {nd}")
    inserted = insert_fact_rows(cur, S, T, "inventory_fact", where_inv, log)
    check("F3 inventory rows inserted", inserted, EXPECTED["inventory_inserted"])
    return EXPECTED["inventory_inserted"] + EXPECTED["inventory_region_corrected"], inserted + len(keys)


def update_product_column(cur, S: str, T: str, col: str, check, log: dict) -> int:
    cur.execute(f"""SELECT p.product_key, p.{col} FROM {T}.product_dimension p JOIN {S}.product_dimension s USING (principal, grain, sku_code)
                    WHERE p.principal = 'unilever' AND p.grain = 'sku' AND p.{col} IS DISTINCT FROM s.{col}""")
    old = cur.fetchall()
    n = 0
    for part in chunks([k for k, _ in old]):
        cur.execute(f"""UPDATE {T}.product_dimension p SET {col} = s.{col} FROM {S}.product_dimension s
                        WHERE p.product_key = ANY(%s) AND s.principal = p.principal AND s.grain = p.grain
                          AND s.sku_code = p.sku_code AND p.{col} IS DISTINCT FROM s.{col}""", (part,))
        n += cur.rowcount
    log["updated"][f"product_dimension.{col}"] = {"old": [[k, v] for k, v in old]}
    check(f"X1/D11 Unilever SKU {col} changed", n, EXPECTED[f"product_{col}"])
    return n


def b_product_pack_size(cur, S, T, ctx, check, log):
    n = sum(update_product_column(cur, S, T, col, check, log) for col in ("product_name", "pack_size", "category_path"))
    check("X1 pack_size values overwritten (was non-NULL)",
          sum(1 for _, v in log["updated"]["product_dimension.pack_size"]["old"] if v is not None), 0)
    return EXPECTED["product_pack_size"], n


def b_product_brand(cur, S, T, ctx, check, log):
    n = sum(update_product_column(cur, S, T, col, check, log) for col in ("brand_source", "brand"))
    return EXPECTED["product_brand_source"] + EXPECTED["product_brand"], n


def b_verify(cur, S, T, ctx, check, log):
    """Reads only. The same proof the one-shot ran before COMMIT, against the baseline the run started from.
    In batch mode `log` is only this batch's delta, so the inserted keys come from the merged run log in ctx."""
    merged = ctx.get("_merged") or log
    pre_columns, demo_before = ctx["pre_columns"], ctx["demo_before"]
    log["post_diff"] = {t: list(v) for t, v in real_diff(cur, S, T).items()}
    for t, (a, b) in log["post_diff"].items():
        check(f"{t}: real rows target-only / source-only after", [a, b], [0, 0])
        check(f"{t}: synthetic rows untouched", list(fingerprint(cur, T, t, "is_demo", pre_columns[t])), demo_before[t])
    uni = f"SELECT sku_code, {', '.join(PRODUCT_COLUMNS)} FROM {{s}}.product_dimension WHERE {UNILEVER_SKU}"
    check("Unilever SKU products target vs source, both ways",
          [one(cur, f"SELECT COUNT(*) FROM ({uni.format(s=T)} EXCEPT ALL {uni.format(s=S)}) x"),
           one(cur, f"SELECT COUNT(*) FROM ({uni.format(s=S)} EXCEPT ALL {uni.format(s=T)}) x")], [0, 0])
    check("other Product_Dimension rows untouched",
          list(fingerprint(cur, T, "product_dimension", f"NOT ({UNILEVER_SKU}) AND product_key <= {ctx['max_product_key']}", pre_columns["product_dimension"])),
          ctx["other_products_before"])
    for t, w in ISOLATION:
        check(f"{t} [{w}]: untouched", list(fingerprint(cur, T, t, w, columns(cur, T, t))), ctx["isolation_before"][f"{t}|{w}"])
    for t, keys in merged["inserted"].items():
        if t in FACTS and "net_amount" in columns(cur, T, t):
            check(f"{t}: inserted rows with NULL or NaN net_amount",
                  one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE {FACTS[t][0]} = ANY(%s) AND (net_amount IS NULL OR net_amount = 'NaN')", (keys,)), 0)
        if t in FACTS:
            check(f"{t}: inserted rows with _period 'unknown' or is_demo",
                  one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE {FACTS[t][0]} = ANY(%s) AND (_period = 'unknown' OR is_demo)", (keys,)), 0)
    return 0, 0


BATCHES = [
    (1,  "migrations 0024-0027",                                    "schema_migrations", b_migrations),
    (2,  "quarantine the FAKE BOOKING sales invoices",              "sales_fact",        b_quarantine_fake_booking),
    (3,  "quarantine the Sept-2025 purchases",                      "purchase_fact",     b_quarantine_purchases),
    (4,  "quarantine the remaining real excluded rows",             "etl_quarantine",    b_quarantine_rest),
    (5,  "insert the ONE PAGER invoices (+ missing dimension rows)", "sales_fact",       b_sales_one_pager),
    (6,  "sales quantity_cases / quantity_pieces",                  "sales_fact",        b_sales_quantities),
    (7,  "sales return quantity_cases / quantity_pieces",           "salesreturn_fact",  b_return_quantities),
    (8,  "sell-out net_amount + tax-inclusive flag",                "sellout_fact",      b_sellout),
    (9,  "inventory ILO 090223: re-tag + insert",                   "inventory_fact",    b_inventory),
    (10, "Unilever SKU pack_size / product_name / category_path",   "product_dimension", b_product_pack_size),
    (11, "Unilever SKU brand_source / brand",                       "product_dimension", b_product_brand),
    (12, "final verification (reads only)",                         "(verify)",          b_verify),
]
BATCH = {b[0]: b for b in BATCHES}
LAST_BATCH = BATCHES[-1][0]


def empty_log(T: str, S: str) -> dict:
    return {"target": T, "source": S, "migrations_applied": [], "inserted": {}, "updated": {}, "deleted": {}, "quarantine_run_ids": []}


def merge_log(into: dict, delta: dict) -> dict:
    into["migrations_applied"] += [m for m in delta.get("migrations_applied", []) if m not in into["migrations_applied"]]
    into["quarantine_run_ids"] += [r for r in delta.get("quarantine_run_ids", []) if r not in into["quarantine_run_ids"]]
    for section in ("inserted", "deleted"):
        for k, v in (delta.get(section) or {}).items():
            into[section].setdefault(k, []).extend(v)
    into["updated"].update(delta.get("updated") or {})
    for k in ("pre_diff", "post_diff"):
        if k in delta:
            into[k] = delta[k]
    return into


def cutover(cur, S: str, T: str, checks: list, log: dict) -> None:
    """One-shot: every batch in the caller's single transaction, same order, same checks."""
    def check(name, got, want):
        ok = str(got) == str(want)
        checks.append((name, got, want, ok))
        print(f"  {'ok ' if ok else 'FAIL'} {name}: {got} (expected {want})")

    ctx = capture_baseline(cur, S, T)
    log["pre_diff"] = ctx["pre_diff"]
    print(f"  real-row diff before (target-only, source-only): {log['pre_diff']}")
    for batch_id, description, table, fn in BATCHES:
        print(f"  -- batch {batch_id}: {description}")
        expected, applied = fn(cur, S, T, ctx, check, log)
        if batch_id != LAST_BATCH and str(expected) != str(applied):
            raise RuntimeError(f"batch {batch_id} ({table}): applied {applied} rows, expected {expected}")


# --- the ledger and the batch runner --------------------------------------------------------------------------

def ensure_ledger(conn, cur, T: str) -> None:
    """`table` is reserved in SQL, so the column is table_name. change_log carries the per-batch undo detail and is
    written in the same transaction as the batch itself - a file written after COMMIT could be lost."""
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {T}.{LEDGER} (
        ledger_key      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        run_id          text        NOT NULL,
        target_schema   text        NOT NULL,
        batch_id        integer     NOT NULL,
        description     text        NOT NULL,
        table_name      text        NOT NULL,
        expected_rows   bigint,
        applied_rows    bigint,
        checksum_before text,
        checksum_after  text,
        started_at      timestamptz NOT NULL,
        finished_at     timestamptz,
        status          text        NOT NULL,
        change_log      jsonb,
        UNIQUE (run_id, batch_id))""")
    conn.commit()


def ledger_rows(cur, T: str, run_id: str | None = None) -> list[dict]:
    if not one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{T}.{LEDGER}",)):
        return []
    where, args = "target_schema = %s", [T]
    if run_id:
        where, args = where + " AND run_id = %s", args + [run_id]
    cur.execute(f"""SELECT run_id, batch_id, description, table_name, expected_rows, applied_rows, checksum_before,
                           checksum_after, started_at, finished_at, status, change_log
                    FROM {T}.{LEDGER} WHERE {where} ORDER BY run_id, batch_id""", args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def batch_checksums(cur, T: str, delta: dict) -> tuple[str | None, str | None]:
    """Per-batch verification is SCOPED to the rows that batch touched - never a whole-table hash. A full-table
    fingerprint is taken twice per run only: capture_baseline() at the start and b_verify() after the last batch.
    Hashing every table on every batch is what made the run slow, and it proves nothing the run-level pair does not.
      before - md5 over the prior values the batch recorded for the rows it changed (NULL for a pure insert)
      after  - md5 over those same rows read back by key, as they now stand
    """
    before_parts, after_parts = [], []

    for table, keys in sorted((delta.get("inserted") or {}).items()):
        if not keys:
            continue
        ident = FACTS[table][0] if table in FACTS else DIM_KEY.get(table)
        if ident is None:
            continue
        cols = [c for c in columns(cur, T, table) if c not in LOAD_TIME]
        row = "ROW(" + ", ".join(f'x."{c}"' for c in cols) + ")::text"
        h = one(cur, f"SELECT md5(COALESCE(string_agg(md5({row}), '' ORDER BY md5({row})), '')) "
                     f"FROM {T}.{table} x WHERE x.{ident} = ANY(%s)", (keys,))
        after_parts.append(f"{table}+{len(keys)}:{h}")

    for table, rows in sorted((delta.get("deleted") or {}).items()):
        if rows:
            before_parts.append(f"{table}-{len(rows)}:{hashlib.md5(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()}")

    for name, entry in sorted((delta.get("updated") or {}).items()):
        old_rows = entry.get("old")
        if old_rows is None:
            continue
        before_parts.append(f"{name}~{len(old_rows)}:{hashlib.md5(json.dumps(old_rows, sort_keys=True, default=str).encode()).hexdigest()}")
        if ":" in name:                                  # fact column update: table:col,col
            table, cols = name.split(":", 1)
            ident, keys = entry["key"], [int(r[0]) for r in old_rows]
            sel = ", ".join(f'x."{c}"' for c in cols.split(","))
        elif name == "inventory_fact.region":
            table, ident, keys, sel = "inventory_fact", "inventory_key", entry["keys"], "x.region"
        else:                                            # product_dimension.<col>
            table, col = name.split(".", 1)
            ident, keys, sel = "product_key", [r[0] for r in old_rows], f'x."{col}"'
        if keys:
            h = one(cur, f"SELECT md5(COALESCE(string_agg(md5(ROW(x.{ident}, {sel})::text), '' ORDER BY x.{ident}), '')) "
                         f"FROM {T}.{table} x WHERE x.{ident} = ANY(%s)", (keys,))
            after_parts.append(f"{name}~{len(keys)}:{h}")

    return ("|".join(before_parts) or None), ("|".join(after_parts) or None)


def print_status(cur, T: str) -> int:
    rows = ledger_rows(cur, T)
    if not rows:
        print(f"no cutover ledger rows for {T}")
        return 0
    for r in rows:
        checks = len((r["change_log"] or {}).get("_checks", []))
        print(f"  {r['run_id']}  batch {r['batch_id']:>2}  {r['status']:<8} rows {r['applied_rows']}/{r['expected_rows']}"
              f"  checks {checks:<3} {r['table_name']:<18} {r['description']}")
    runs = {r["run_id"] for r in rows}
    for run in sorted(runs):
        mine = [r for r in rows if r["run_id"] == run]
        done = sorted(r["batch_id"] for r in mine if r["status"] == "done")
        print(f"  {run}: batches done {done}, remaining {[b for b, _, _, _ in BATCHES if b not in done]}, "
              f"{sum(len((r['change_log'] or {}).get('_checks', [])) for r in mine)} checks")
    return 0


def run_batches(conn, cur, S: str, T: str, args) -> int:
    ensure_ledger(conn, cur, T)
    rows = ledger_rows(cur, T)
    open_run = None
    for r in sorted((x for x in rows if x["batch_id"] == 0), key=lambda x: x["started_at"]):
        done = {x["batch_id"] for x in rows if x["run_id"] == r["run_id"] and x["status"] == "done"}
        if LAST_BATCH not in done:
            open_run = r

    if open_run:
        run_id, backup_dir = open_run["run_id"], REPO / "backups" / open_run["run_id"]
        ctx = open_run["change_log"]["baseline"]
        print(f"resuming run {run_id} (backup {backup_dir.name})")
    elif args.dry_run:
        run_id, backup_dir, ctx = "dry-run", None, capture_baseline(cur, S, T)
        print("dry run: no backup, no ledger row, every batch rolled back")
    else:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"real_recovery_{'rehearsal_' if args.rehearse else ''}{ts}"
        backup_dir = REPO / "backups" / run_id
        backup(cur, T, backup_dir)
        ctx = capture_baseline(cur, S, T)
        cur.execute(f"""INSERT INTO {T}.{LEDGER} (run_id, target_schema, batch_id, description, table_name, expected_rows,
                        applied_rows, started_at, finished_at, status, change_log)
                        VALUES (%s, %s, 0, 'baseline + full backup', '(all)', 0, 0, now(), now(), 'baseline', %s)""",
                    (run_id, T, json.dumps({"baseline": ctx, "source": S, "backup_dir": str(backup_dir)}, default=str)))
        conn.commit()
        print(f"run {run_id}: backup {backup_dir.name}, baseline captured, real-row diff before {ctx['pre_diff']}")

    rows = ledger_rows(cur, T, run_id)
    done = {r["batch_id"] for r in rows if r["status"] == "done"}
    log = empty_log(T, S)
    for r in sorted(rows, key=lambda x: x["batch_id"]):
        if r["batch_id"] and r["status"] == "done":
            merge_log(log, r["change_log"] or {})
    log["pre_diff"] = ctx["pre_diff"]
    ctx["_merged"] = log  # batch 12 verifies against the whole run, not just its own delta

    if args.batch is not None:
        todo, limit = [args.batch], 1
    else:
        start = args.from_batch or min((b for b, _, _, _ in BATCHES if b not in done), default=LAST_BATCH + 1)
        todo = [b for b, _, _, _ in BATCHES if b >= start]
        limit = args.max_batches or 1

    ran = 0
    for batch_id in todo:
        if batch_id not in BATCH:
            sys.exit(f"no such batch: {batch_id} (1-{LAST_BATCH})")
        _, description, table, fn = BATCH[batch_id]
        if batch_id in done:
            print(f"  batch {batch_id:>2} {description}: already applied on {run_id}, skipped")
            continue
        missing = [b for b, _, _, _ in BATCHES if b < batch_id and b not in done]
        if missing:
            sys.exit(f"refusing batch {batch_id}: batch(es) {missing} have not run yet")
        started = datetime.datetime.now(datetime.timezone.utc)
        delta, checks = empty_log(T, S), []
        delta["inserted"], delta["updated"], delta["deleted"] = {}, {}, {}

        def check(name, got, want, _c=checks):
            _c.append((name, got, want, str(got) == str(want)))

        try:
            expected, applied = fn(cur, S, T, ctx, check, delta)
            failed = [c for c in checks if not c[3]]
            if failed:
                raise RuntimeError("; ".join(f"{n}: got {g}, expected {w}" for n, g, w, _ in failed))
            if batch_id != LAST_BATCH and str(expected) != str(applied):
                raise RuntimeError(f"applied {applied} rows, expected {expected}")
        except Exception as exc:
            conn.rollback()
            print(f"  batch {batch_id:>2} {description}: FAILED, rolled back - {exc}")
            cur.execute(f"""INSERT INTO {T}.{LEDGER} (run_id, target_schema, batch_id, description, table_name,
                            started_at, finished_at, status, change_log) VALUES (%s, %s, %s, %s, %s, %s, now(), 'failed', %s)
                            ON CONFLICT (run_id, batch_id) DO UPDATE SET status = 'failed', finished_at = now(),
                            change_log = EXCLUDED.change_log""",
                        (run_id, T, batch_id, description, table, started, json.dumps({"error": str(exc)})))
            conn.commit()
            return 1
        delta["_checks"] = [[n, str(g), str(w)] for n, g, w, _ in checks]
        before, after = batch_checksums(cur, T, delta)
        if args.dry_run:
            conn.rollback()
            print(f"  batch {batch_id:>2} {description}: DRY RUN {applied}/{expected} rows, {len(checks)} check(s) ok, rolled back")
            ran += 1
            if ran >= limit:
                break
            continue
        cur.execute(f"""INSERT INTO {T}.{LEDGER} (run_id, target_schema, batch_id, description, table_name, expected_rows,
                        applied_rows, checksum_before, checksum_after, started_at, finished_at, status, change_log)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), 'done', %s)
                        ON CONFLICT (run_id, batch_id) DO UPDATE SET expected_rows = EXCLUDED.expected_rows,
                        applied_rows = EXCLUDED.applied_rows, checksum_before = EXCLUDED.checksum_before,
                        checksum_after = EXCLUDED.checksum_after, finished_at = now(), status = 'done',
                        change_log = EXCLUDED.change_log""",
                    (run_id, T, batch_id, description, table, expected, applied, before, after, started,
                     json.dumps(delta, default=str)))
        conn.commit()
        merge_log(log, delta)
        done.add(batch_id)
        (backup_dir / "changes.json").write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")
        print(f"  batch {batch_id:>2} {description}: {applied}/{expected} rows, {len(checks)} check(s) ok, committed")
        ran += 1
        if ran >= limit:
            break

    if args.dry_run:
        return 0
    remaining = [b for b, _, _, _ in BATCHES if b not in done]
    total_checks = sum(len((r["change_log"] or {}).get("_checks", [])) for r in ledger_rows(cur, T, run_id))
    flags = f"--rehearse {T}" if args.rehearse else "--target public --i-have-approval"
    if remaining:
        print(f"PAUSED after batch {max(done, default=0)} - {total_checks} check(s) so far, {len(remaining)} left: {remaining}\n"
              f"  resume: python -m scripts.apply_real_recovery_to_public --source {S} {flags} --from {remaining[0]}")
    else:
        print(f"RUN COMPLETE - {total_checks} checks passed across {LAST_BATCH} batches.\n"
              f"  undo with: python -m scripts.apply_real_recovery_to_public --rollback backups/{run_id} --i-have-approval")
    return 0


def clear_ledger_run(cur, T: str, backup_dir: Path) -> int:
    """A rollback or restore undoes the whole run, so its ledger rows go too - the next run starts clean."""
    if not one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{T}.{LEDGER}",)):
        return 0
    cur.execute(f"DELETE FROM {T}.{LEDGER} WHERE target_schema = %s AND run_id = %s", (T, backup_dir.name))
    return cur.rowcount


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="ssm_synth_v2", help="verified scratch schema built by run_canonical_load (2026-09-22 rebuild)")
    p.add_argument("--target", default=None, help="'public' for the real cutover")
    p.add_argument("--rehearse", default=None, metavar="SCHEMA", help="build a scratch copy of the live tables and run the cutover against it")
    p.add_argument("--rollback", default=None, metavar="BACKUP_DIR", help="undo a cutover from the change log it wrote")
    p.add_argument("--restore", default=None, metavar="BACKUP_DIR",
                   help="put every backed-up table back to the backup (full restore, independent of the change log)")
    p.add_argument("--i-have-approval", action="store_true", help="required for anything that writes to public")
    p.add_argument("--one-shot", action="store_true", help="every batch in a single transaction (the pre-batch behaviour)")
    p.add_argument("--batch", type=int, default=None, metavar="ID", help="run exactly this batch, then stop")
    p.add_argument("--from", dest="from_batch", type=int, default=None, metavar="ID", help="start at this batch")
    p.add_argument("--max-batches", type=int, default=None, metavar="N", help="run up to N batches before pausing (default 1)")
    p.add_argument("--dry-run", action="store_true", help="run each batch and ROLL IT BACK; writes no ledger row and takes no backup")
    p.add_argument("--status", action="store_true", help="print the cutover ledger for the target and exit")
    p.add_argument("--rebuild", action="store_true", help="--rehearse: drop and rebuild the rehearsal schema (loses its ledger)")
    args = p.parse_args()
    if args.status:
        if not (args.target or args.rehearse):
            p.error("--status needs --target public or --rehearse SCHEMA")
    elif sum(bool(x) for x in (args.target, args.rehearse, args.rollback, args.restore)) != 1:
        p.error("pass exactly one of --target public, --rehearse SCHEMA, --rollback BACKUP_DIR, --restore BACKUP_DIR")
    if args.target and args.target != "public":
        p.error("--target only accepts 'public'; use --rehearse for anything else")
    if args.rehearse and (args.rehearse == "public" or args.rehearse == args.source):
        p.error("--rehearse needs its own scratch schema name")
    if args.one_shot and (args.batch or args.from_batch or args.max_batches or args.dry_run):
        p.error("--one-shot runs everything in one transaction; it takes none of the batch flags")

    conn = connect()
    cur = conn.cursor()
    checks: list = []
    try:
        if args.status:
            return print_status(cur, args.target or args.rehearse)
        if args.rollback or args.restore:
            backup_dir = Path(args.rollback or args.restore)
            target = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))["target"]
            if target == "public" and not args.i_have_approval:
                sys.exit("refusing: a rollback or restore of public needs --i-have-approval")
            (rollback_from if args.rollback else restore_from)(cur, backup_dir, checks)
            n = clear_ledger_run(cur, target, backup_dir)
            print(f"  cutover ledger rows removed for {backup_dir.name}: {n}")
        else:
            T = args.target or args.rehearse
            if T == "public" and not args.i_have_approval:
                sys.exit("refusing: writing to public needs --i-have-approval")
            if args.rehearse:
                exists = one(cur, "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (T,))
                if args.rebuild or not exists:
                    build_rehearsal(cur, T)
                    conn.commit()
                    print(f"rehearsal schema {T}: {'rebuilt' if exists else 'built'} from public")
                else:
                    print(f"rehearsal schema {T}: reused (pass --rebuild to start over)")
            if not args.one_shot:
                return run_batches(conn, cur, args.source, T, args)
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_dir = REPO / "backups" / f"real_recovery_{'rehearsal_' if args.rehearse else ''}{ts}"
            backup(cur, T, backup_dir)
            log = empty_log(T, args.source)
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
        if not (args.rollback or args.restore):
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
