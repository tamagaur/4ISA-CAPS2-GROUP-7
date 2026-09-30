"""SUPERSEDED (2026-09-30) - batches 3-7 are now rules in the loader (scripts/run_canonical_load.py --slice: fix 3
derived_cost in transform, fix 4 RMR loader via config/source_of_truth.yaml, fixes 5-6 product_dimension fill-if-NULL
rules, fix 7 the "(2)" sheet quarantined at transform). Kept for --status and --rollback of the 2026-09-28 ledger run;
do not use it for new data.

scripts/apply_dm_fixes_to_public.py - the Del Monte data fixes of 2026-09-28, batch by batch. Same pattern as
scripts/apply_real_recovery_to_public.py (whose helpers it reuses): expected counts stated in code, scratch first,
backup + checksum, apply, verify both directions, ledger entry, rollback proven.

Batches (each its own transaction, recorded in <target>.etl_cutover_ledger under a run_id starting 'dm_fixes_'):
  1  etl_quarantine     the 37 rows of the byte-identical April-2023 sales-return copy     expect +37, 0 fact changes
  2  inventory_fact     Aug-2023 "-ACTUAL" sheets keyed on the sign-off block's code (G/I)  expect +172 Pangasinan, +12 Ilocos,
                        138 Ilocos rows re-keyed, 4 unchanged; etl_quarantine -184 (the 2 Total rows stay)
  3  inventory_fact     migration 0028; valuation = cost where valuation is NULL            expect 209, valuation_source 'derived_cost'
  4  salesreturn_fact   Oct/Nov 2025 RMR GS & BO lines, source = 'rmr'                        expect +224 / P1,439,087.79;
                        etl_quarantine +2 (lines with no Return Slip #)
  5  product_dimension  Del Monte pack_size from the price list CASE PACK, exact code match   expect 187
  6  product_dimension  Del Monte brand by the name first-token rule (delmonte_brand.csv)    expect 554 branded, 43 NULL
  7  sales_fact         the 564 'PANGASINAN SALES REGISTER (2)' rows filed under 2025-04 ->   expect 564 / P4,932,185.22 moved
                        etl_quarantine, not re-dated (suspected 2024-09 data, pending SSM)
Batches 1 and 2 come from the canonical loader's own code (run_canonical_load.known_duplicate_file_records, the shape-E
Transform), so a loader rebuild reproduces them. Batches 3-7 are applied here only; a loader rebuild does not repeat them.

Per batch:
  --rehearse SCHEMA  a scratch copy of the live tables (built once from public, server-side) -> backup of the
                     batch's tables -> apply + checks -> COMMIT -> undo from the change log -> every backed-up table's
                     md5 and identity sequence equal the backup's (proves the apply touched nothing outside its change
                     log) -> apply again + checks -> COMMIT -> ledger row.
  --target public    refused unless the rehearsal ledger has the batch done. Backup of the batch's tables; their md5
                     must equal the rehearsal's pre-batch backup (public and scratch start from the same rows); apply +
                     checks; the batch's tables equal the rehearsal's both directions (EXCEPT ALL on every column
                     except the table's own identity key and load timestamps); ledger row; COMMIT.
  --rollback DIR     undo one batch from the change log in its backup dir, then re-verify md5 against that backup.
Every run also fingerprints every fact, dimension and model table the batch does not write to, before and after.

CONNECTION ROUTE: the session pooler (the SUPABASE_DB_URL host on port 5432, session mode). The direct host is not
reachable from this machine and the transaction pooler (6543) is never used - apply_real_recovery_to_public.py:29-40.

  python -m scripts.apply_dm_fixes_to_public --rehearse ssm_dm_fixes --batch 1
  python -m scripts.apply_dm_fixes_to_public --target public --against ssm_dm_fixes --batch 1 --i-have-approval
  python -m scripts.apply_dm_fixes_to_public --rollback backups/dm_fixes_<ts>/b1 --i-have-approval
  python -m scripts.apply_dm_fixes_to_public --status --target public
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import psycopg2
from dotenv import dotenv_values

from scripts.apply_real_recovery_to_public import (LEDGER, LOAD_TIME, ensure_ledger, export_csv, identity_state,
                                                   ledger_rows, reset_sequences)
from scripts.apply_synth_v2_to_public import DIMENSIONS, FACTS, REAL_VIEWS, columns, one

REPO = Path(__file__).resolve().parent.parent
RUN_PREFIX = "dm_fixes_"
# copied into the scratch schema: everything a batch writes to or reads from
SCRATCH_TABLES = list(FACTS) + list(DIMENSIONS) + ["etl_quarantine", "schema_migrations", "date_dimension"]
# fingerprinted before and after every batch unless the batch writes to them; ABC read per method, never as a union
ISOLATION = ([(t, "TRUE") for t in list(FACTS) + list(DIMENSIONS) + ["etl_quarantine"]]
             + [("forecast_result", "TRUE"), ("sku_segment", "TRUE"), ("sku_traits", "TRUE"), ("lp_recommendation", "TRUE"),
                ("abc_classification", "method = 'single'"), ("abc_classification", "method IS DISTINCT FROM 'single'")])
IDENT = {**{t: k for t, (k, _) in FACTS.items()}, **{d: k for d, (k, _) in DIMENSIONS.items()}, "etl_quarantine": "quarantine_key"}
SKIP_COMPARE = LOAD_TIME | {"quarantined_at"}


# Per-transaction, never session-level: a session SET can outlive this client on a pooled backend and reach whoever
# is handed that backend next (the 2026-09-28 sign-in outage was a session-level READ ONLY doing exactly that).
TXN_SETTINGS = "SET LOCAL statement_timeout = 0; SET LOCAL idle_in_transaction_session_timeout = 0; SET LOCAL lock_timeout = '30s'"


class TxnSettingsCursor(psycopg2.extensions.cursor):
    """Issues TXN_SETTINGS as the first statement of every transaction the connection opens (the first statement
    after connect(), commit() or rollback()), so each batch runs with them and none of them outlives its transaction."""

    def _begin(self):
        conn = self.connection
        if not conn.autocommit and conn.info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            with conn.cursor(cursor_factory=psycopg2.extensions.cursor) as c:  # plain cursor: no recursion
                c.execute(TXN_SETTINGS)

    def execute(self, query, vars=None):
        self._begin()
        return super().execute(query, vars)

    def executemany(self, query, vars_list):
        self._begin()
        return super().executemany(query, vars_list)

    def copy_expert(self, sql, file, size=8192):
        self._begin()
        return super().copy_expert(sql, file, size)


def connect():
    env = dotenv_values(REPO / ".env")
    dsn = env["SUPABASE_DB_URL"].replace(":6543/", ":5432/")
    if ":5432/" not in dsn:
        sys.exit("refusing: could not derive the session-pooler URL (port 5432) from SUPABASE_DB_URL")
    conn = psycopg2.connect(dsn, connect_timeout=30, cursor_factory=TxnSettingsCursor)
    conn.autocommit = False
    return conn


def pk_of(cur, T: str, t: str) -> str:
    return one(cur, f"""SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = '{T}.{t}'::regclass AND i.indisprimary""")


def fingerprint(cur, T: str, t: str, where: str, cols: list[str] | None = None) -> list:
    """[rows, md5 over every matching row in primary-key order] - over the named columns when given, so a column a
    migration adds does not change the fingerprint of rows whose values did not change."""
    pk = pk_of(cur, T, t)
    row = "x::text" if cols is None else "ROW(" + ", ".join(f'x."{c}"' for c in cols) + ")::text"
    cur.execute(f"SELECT COUNT(*), md5(COALESCE(string_agg(md5({row}), '' ORDER BY x.{pk}), '')) FROM {T}.{t} x WHERE {where}")
    return list(cur.fetchone())


def isolation(cur, T: str, writes: list[str], cols: dict | None = None) -> dict:
    """{"table|where": [cols, fingerprint]} for every ISOLATION table the batch does not write to. `cols` pins the
    column list to the one taken before the batch (a migration may have added columns since)."""
    out = {}
    for t, w in ISOLATION:
        if t in writes or not one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"{T}.{t}",)):
            continue
        c = (cols or {}).get(f"{t}|{w}") or columns(cur, T, t)
        out[f"{t}|{w}"] = [c, fingerprint(cur, T, t, w, c)]
    return out


def build_scratch(cur, R: str) -> None:
    """Server-side copy of SCRATCH_TABLES, identity sequences mirrored to public's positions (LIKE ... INCLUDING
    IDENTITY starts at 1 and OVERRIDING SYSTEM VALUE never advances it - the 2026-09-15 incident class)."""
    if one(cur, "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (R,)):
        raise RuntimeError(f"schema {R} already exists - pick a new name (this script never drops a schema)")
    cur.execute(f"CREATE SCHEMA {R}")
    for t in SCRATCH_TABLES:
        cur.execute(f"CREATE TABLE {R}.{t} (LIKE public.{t} INCLUDING DEFAULTS INCLUDING IDENTITY INCLUDING INDEXES INCLUDING CONSTRAINTS)")
        cur.execute(f"INSERT INTO {R}.{t} OVERRIDING SYSTEM VALUE SELECT * FROM public.{t}")
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s AND is_identity = 'YES'", (R, t))
        for (col,) in cur.fetchall():
            cur.execute(f"SELECT last_value, is_called FROM {one(cur, 'SELECT pg_get_serial_sequence(%s, %s)', (f'public.{t}', col))}")
            last_value, is_called = cur.fetchone()
            cur.execute("SELECT setval(pg_get_serial_sequence(%s, %s), %s, %s)", (f"{R}.{t}", col, last_value, is_called))
    for v, t in zip(REAL_VIEWS, ["sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact", "unilever_sku_demand_fact"]):
        cur.execute(f"CREATE VIEW {R}.{v} AS SELECT * FROM {R}.{t} WHERE is_demo = false")


def export_rows(cur, T: str, t: str, cols: list[str]) -> bytes:
    r"""The table as CSV (NULL written as \N) in primary-key order, fetched as ordinary rows."""
    cur.execute(f"SELECT {', '.join(f'{c}::text' for c in cols)} FROM {T}.{t} ORDER BY {pk_of(cur, T, t)}")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    w.writerows([[r"\N" if v is None else v for v in r] for r in cur.fetchall()])
    return buf.getvalue().encode("utf-8")


EXPORT_TIMEOUT, EXPORT_ATTEMPTS = 120, 4


def export_to_file(T: str, t: str, cols: list[str], path: Path) -> bytes:
    """The offline CSV backup, taken in a child process with a time limit and retried on a fresh connection. Through
    the session pooler, multi-MB result sets stalled 5 times on 2026-09-28 (COPY and plain SELECT alike, 2-9 min
    each, the server finished and left idle in transaction, the client never receiving the data); the same fetch
    otherwise takes 1-3 s. The child's session reaps its own orphan (idle_in_transaction_session_timeout)."""
    for attempt in range(1, EXPORT_ATTEMPTS + 1):
        try:
            subprocess.run([sys.executable, "-m", "scripts.apply_dm_fixes_to_public", "--export", T, t, ",".join(cols), str(path)],
                           cwd=REPO, check=True, timeout=EXPORT_TIMEOUT, capture_output=True)
            return path.read_bytes()
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            err = (getattr(exc, "stderr", b"") or b"").decode("utf-8", "replace").strip().splitlines()[-1:]
            print(f"  backup export {T}.{t}: attempt {attempt} failed ({type(exc).__name__} {err}), retrying on a new connection")
    raise RuntimeError(f"backup export of {T}.{t} failed {EXPORT_ATTEMPTS} times")


def server_fingerprint(cur, T: str, t: str, cols: list[str]) -> list:
    """[rows, md5 over the named columns of every row in primary-key order], computed on the server - the rollback
    proof compares this, so it never moves the table across the pooler."""
    row = "ROW(" + ", ".join(f'x."{c}"' for c in cols) + ")::text"
    cur.execute(f"SELECT COUNT(*), md5(COALESCE(string_agg(md5({row}), '' ORDER BY x.{pk_of(cur, T, t)}), '')) FROM {T}.{t} x")
    return list(cur.fetchone())


def csv_md5_without(path: Path, drop: set[str]) -> str:
    """md5 of a backup CSV with the `drop` columns removed - public and the rehearsal stamp their own now() into
    etl_quarantine.quarantined_at, so the full-file md5 of the two can never match once a batch has inserted rows."""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    keep = [i for i, c in enumerate(rows[0]) if c not in drop]
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([[r[i] for i in keep] for r in rows])
    return hashlib.md5(buf.getvalue().encode("utf-8")).hexdigest()


def verify_backup(cur, T: str, manifest: dict, proof: list) -> None:
    """Every backed-up table: content equal to the backup's (server fingerprint; batch 1's COPY-era backups by CSV
    md5), columns added since hold no value, identity sequences equal."""
    for t, m in manifest["tables"].items():
        if "fingerprint" in m:
            got = server_fingerprint(cur, T, t, m["columns"])
            proof.append((f"{t} rows + md5 equal the backup's", got, m["fingerprint"], got == m["fingerprint"]))
        else:
            export = export_rows if manifest.get("format") == "rows_v1" else export_csv
            got = hashlib.md5(export(cur, T, t, m["columns"])).hexdigest()
            proof.append((f"{t} md5 equals the backup's", got, m["md5"], got == m["md5"]))
        extra = [c for c in columns(cur, T, t) if c not in m["columns"]]
        if extra:
            n = one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE " + " OR ".join(f"{c} IS NOT NULL" for c in extra))
            proof.append((f"{t} columns added after the backup {extra} hold no value", n, 0, n == 0))
        state = identity_state(cur, T, t)
        proof.append((f"{t} identity sequences equal the backup's", state, m["identity"], state == m["identity"]))


def backup(cur, T: str, tables: list[str], out_dir: Path, batch_id: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"target": T, "batch": batch_id, "format": "rows_v1",
                "taken_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "tables": {}}
    for t in tables:
        cols = columns(cur, T, t)
        fp = server_fingerprint(cur, T, t, cols)
        data = export_to_file(T, t, cols, out_dir / f"{t}.csv")
        if sum(1 for _ in csv.reader(io.StringIO(data.decode("utf-8")))) - 1 != fp[0] or server_fingerprint(cur, T, t, cols) != fp:
            raise RuntimeError(f"{T}.{t} changed while it was being backed up, or the CSV is short")
        manifest["tables"][t] = {"rows": fp[0], "fingerprint": fp, "md5": hashlib.md5(data).hexdigest(),
                                 "columns": cols, "identity": identity_state(cur, T, t)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def undo(cur, T: str, log: dict) -> None:
    """Reverses a batch's change log: inserted fact rows, then inserted dimension rows, then updated values, then
    deleted rows re-inserted with their original keys. Schema objects a batch's migration added stay (additive);
    its schema_migrations row goes."""
    ins = log.get("inserted", {})
    for t in sorted(ins, key=lambda t: t in DIMENSIONS):
        cur.execute(f"DELETE FROM {T}.{t} WHERE {IDENT[t]} = ANY(%s)", (ins[t],))
        if cur.rowcount != len(ins[t]):
            raise RuntimeError(f"undo {t}: deleted {cur.rowcount}, change log has {len(ins[t])}")
    for t, entry in log.get("updated", {}).items():
        if entry.get("unique_col"):  # the batch permuted a unique column: park every logged row first
            c = entry["unique_col"]
            cur.execute(f"UPDATE {T}.{t} SET {c} = {c} || '~undo' WHERE {entry['key']} = ANY(%s)", ([r[0] for r in entry["old"]],))
        for r in entry["old"]:
            cur.execute(f"UPDATE {T}.{t} SET {', '.join(f'{c} = %s' for c in entry['cols'])} WHERE {entry['key']} = %s", (*r[1:], r[0]))
    for t, rows in log.get("deleted", {}).items():
        if isinstance(rows, dict) and "restore_from_backup" in rows:
            restore_rows_from_backup(cur, T, Path(log["backup_dir"]), t, rows)
            continue
        if rows:
            cols = list(rows[0])
            cur.execute(f"""INSERT INTO {T}.{t} ({', '.join(cols)}) OVERRIDING SYSTEM VALUE
                            SELECT {', '.join(cols)} FROM json_populate_recordset(NULL::{T}.{t}, %s::json)""", (json.dumps(rows),))
    if log.get("migrations_applied"):
        cur.execute(f"DELETE FROM {T}.schema_migrations WHERE filename = ANY(%s)", (log["migrations_applied"],))


def restore_rows_from_backup(cur, T: str, backup_dir: Path, t: str, entry: dict) -> None:
    """Re-inserts deleted rows from the batch's own CSV backup (an upload - the pooler stalls large downloads, so a
    batch that deletes thousands of rows logs {"restore_from_backup": <where>, "rows": n[, "key", "keys"]} instead of
    returning the rows). Original keys kept (OVERRIDING SYSTEM VALUE); the count must match the log."""
    m = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))["tables"][t]
    cols = ", ".join(m["columns"])
    cur.execute(f"CREATE TEMP TABLE bk_restore (LIKE {T}.{t}) ON COMMIT DROP")
    with open(backup_dir / f"{t}.csv", encoding="utf-8", newline="") as fh:
        cur.copy_expert(f"COPY bk_restore ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\\N')", fh)
    where = entry["restore_from_backup"]
    if entry.get("keys") is not None:
        cur.execute(f"INSERT INTO {T}.{t} ({cols}) OVERRIDING SYSTEM VALUE SELECT {cols} FROM bk_restore "
                    f"WHERE ({where}) AND {entry['key']} = ANY(%s)", (entry["keys"],))
    else:
        cur.execute(f"INSERT INTO {T}.{t} ({cols}) OVERRIDING SYSTEM VALUE SELECT {cols} FROM bk_restore WHERE {where}")
    if cur.rowcount != entry["rows"]:
        raise RuntimeError(f"restore {t}: re-inserted {cur.rowcount} rows from the backup, the change log has {entry['rows']}")
    cur.execute("DROP TABLE bk_restore")


def compare(cur, A: str, B: str, t: str) -> list[int]:
    """[rows only in A, rows only in B] on every column both share except the identity key and load timestamps."""
    cols = [c for c in columns(cur, A, t) if c in columns(cur, B, t) and c != IDENT.get(t) and c not in SKIP_COMPARE]
    a, b = (f"SELECT {', '.join(cols)} FROM {s}.{t}" for s in (A, B))
    return [one(cur, f"SELECT COUNT(*) FROM ({a} EXCEPT ALL {b}) x"), one(cur, f"SELECT COUNT(*) FROM ({b} EXCEPT ALL {a}) x")]


# --- the batches: fn(cur, T, check, log) -> (expected, applied); every write is recorded in `log` ----------------

def b1_duplicate_return_file(cur, T, check, log):
    from scripts.run_canonical_load import known_duplicate_file_records
    rule = "extract_known_duplicate_file[sales_return]"
    check("B1 rows of this rule already quarantined", one(cur, f"SELECT COUNT(*) FROM {T}.etl_quarantine WHERE rule = %s", (rule,)), 0)
    records = known_duplicate_file_records()
    keys = []
    for r in records:
        cur.execute(f"""INSERT INTO {T}.etl_quarantine (run_id, table_name, rule, reason, _src_file, _src_sheet, _row_ordinal, is_demo, raw_values)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING quarantine_key""",
                    ("dm_fixes_2026-09-28/b1", r["table_name"], r["rule"], r["reason"], r["_src_file"], r["_src_sheet"],
                     r["_row_ordinal"], r["is_demo"], r["raw_values"]))
        keys.append(cur.fetchone()[0])
    log["inserted"]["etl_quarantine"] = keys
    new = f"SELECT * FROM {T}.etl_quarantine WHERE quarantine_key = ANY(%s)"
    check("B1 rows per sheet", dict(sorted((s, n) for s, n in _rows(cur, f"SELECT _src_sheet, COUNT(*) FROM ({new}) q GROUP BY 1", (keys,)))),
          {"ILOCOS SALES RETURN": 13, "PANGASINAN SALE RETURN": 24})
    check("B1 net_amount of the quarantined rows", one(cur, f"SELECT SUM((raw_values->>'net_amount')::numeric)::text FROM ({new}) q", (keys,)), "98575.85")
    # every quarantined row has exactly one loaded twin from the original file, and every loaded row of it has one
    twins = f"""SELECT COUNT(DISTINCT s.return_key) FROM ({new}) q JOIN {T}.salesreturn_fact s ON NOT s.is_demo
                AND s._src_file = replace(q._src_file, ' (1).xlsx', '.xlsx') AND s._src_sheet = q._src_sheet
                AND s.return_slip_num = q.raw_values->>'return_slip_num' AND s.invoice_num = q.raw_values->>'invoice_num'
                AND s.region = q.raw_values->>'region' AND s.net_amount = (q.raw_values->>'net_amount')::numeric"""
    check("B1 quarantined rows with a loaded twin in the original file", one(cur, twins, (keys,)), 37)
    check("B1 loaded rows of the original file", one(cur, f"SELECT COUNT(*) FROM {T}.salesreturn_fact WHERE NOT is_demo AND _src_file = %s",
                                                     ("data/raw/Del Monte/MONTHLY REPORT - APRIL 2023/PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN.xlsx",)), 37)
    return 37, len(keys)


AUG23_SIGNOFF = "data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx"
AUG23_SHEETS = {"PANGASINAN-ACTUAL": "PANGASINAN-ACTUAL", "ILOCOS-ACTUAL ": "ILOCOS-ACTUAL_"}  # sheet -> staged parquet stem


def b2_signoff_block_codes(cur, T, check, log):
    """The fixed Transform (shape E, analytics/etl/transform.py) keys the two August-2023 "-ACTUAL" sheets on the
    sign-off block's own code (G / I), the block every loaded value comes from. Rows are the loader's: the whole
    inventory_sign_off family through transform_fact(), projected onto inventory_fact's columns, product_key
    resolved as resolve_delmonte_inventory_product_key() does (Del Monte SKU row with the same sku_code)."""
    import pandas as pd
    from analytics.etl import transform
    from scripts.run_canonical_load import STAGING_DIR
    staged = sorted((STAGING_DIR / "inventory_sign_off").glob("*.parquet"))
    raw = pd.concat([pd.read_parquet(f) for f in staged], ignore_index=True)
    new, _ = transform.transform_fact(raw[raw["_principal"] == "delmonte"], "inventory", "delmonte", transform.DEFAULT_CONFIG_DIR,
                                      amount_col="quantity_on_hand")
    new = new[(new["is_demo"] != True) & (new["_src_file"] == AUG23_SIGNOFF) & new["_src_sheet"].isin(list(AUG23_SHEETS))]  # noqa: E712
    check("B2 shape-E rows with a code, per sheet", new.groupby("_src_sheet")["sku_code"].count().to_dict(),
          {"ILOCOS-ACTUAL ": 154, "PANGASINAN-ACTUAL": 172})
    # the code the old Transform read for each Ilocos row: the count block's __col1__ (shape B split)
    ilo = pd.read_parquet(STAGING_DIR / "inventory_sign_off" / f"DELMONTE_INVENTORY_SIGN_OFF_PANGASINAN_ILOCOS__AUGUST_2023__{AUG23_SHEETS['ILOCOS-ACTUAL ']}.parquet")
    old_code = {int(o): m.group(1) for o, v in zip(ilo["_row_ordinal"], ilo["__col1__"]) if isinstance(v, str)
                and (m := transform._SKU_CODE_RE.match(v)) and any(ch.isdigit() for ch in m.group(1))}
    cols = [c for c in columns(cur, T, "inventory_fact") if c in new.columns and c != "inventory_key"]
    cur.execute(f"CREATE TEMP TABLE b2_rows ON COMMIT DROP AS SELECT *, NULL::bigint AS _row_ordinal, NULL::text AS old_code FROM {T}.inventory_fact WITH NO DATA")
    for r in new.to_dict("records"):
        vals = [None if pd.isna(r[c]) else r[c] for c in cols]
        o = int(r["_row_ordinal"])
        cur.execute(f"INSERT INTO b2_rows ({', '.join(cols)}, _row_ordinal, old_code) VALUES ({', '.join(['%s'] * (len(cols) + 2))})",
                    (*vals, o, old_code.get(o) if r["_src_sheet"] == "ILOCOS-ACTUAL " else None))
    cur.execute(f"""UPDATE b2_rows b SET product_key = pd.product_key FROM {T}.product_dimension pd
                    WHERE pd.principal = 'delmonte' AND pd.grain = 'sku' AND pd.sku_code = b.sku_code""")
    check("B2 rows without a Del Monte SKU product", one(cur, "SELECT COUNT(*) FROM b2_rows WHERE product_key IS NULL"), 0)
    check("B2 target codes already used by another row at the same snapshot/region (incl. synthetic)",
          one(cur, f"""SELECT COUNT(*) FROM b2_rows b JOIN {T}.inventory_fact f ON f.sku_code = b.sku_code AND f.snapshot_date = b.snapshot_date
                       AND f.region IS NOT DISTINCT FROM b.region AND NOT (f._src_file = b._src_file AND f._src_sheet = b._src_sheet)"""), 0)
    # the live rows of the two sheets, matched to their source row by the code the old Transform gave them;
    # quantity and cost must agree too, or the match is not the same source row
    live = f"SELECT * FROM {T}.inventory_fact WHERE NOT is_demo AND _src_file = '{AUG23_SIGNOFF}' AND _src_sheet IN ('PANGASINAN-ACTUAL', 'ILOCOS-ACTUAL ')"
    check("B2 live rows of the two sheets before", one(cur, f"SELECT COUNT(*) FROM ({live}) l"), 142)
    pairs = f"""SELECT l.inventory_key, l.sku_code AS old, b.sku_code AS new, l.product_key AS old_pk, b.product_key AS new_pk
                FROM ({live}) l JOIN b2_rows b ON b._src_sheet = l._src_sheet AND b.old_code = l.sku_code
                 AND b.quantity_on_hand = l.quantity_on_hand AND b.cost IS NOT DISTINCT FROM l.cost"""
    rekey = _rows(cur, f"SELECT * FROM ({pairs}) p WHERE old <> new ORDER BY inventory_key")
    check("B2 live Ilocos rows matched to a source row", one(cur, f"SELECT COUNT(*) FROM ({pairs}) p"), 142)
    check("B2 live Ilocos rows keeping their code", one(cur, f"SELECT COUNT(*) FROM ({pairs}) p WHERE old = new"), 4)
    keys = [r[0] for r in rekey]
    log["updated"]["inventory_fact"] = {"key": "inventory_key", "cols": ["sku_code", "product_key"], "unique_col": "sku_code",
                                        "old": [[k, old, old_pk] for k, old, _, old_pk, _ in rekey]}
    cur.execute(f"UPDATE {T}.inventory_fact SET sku_code = sku_code || '~rekey' WHERE inventory_key = ANY(%s)", (keys,))
    for k, _, new_code, _, new_pk in rekey:
        cur.execute(f"UPDATE {T}.inventory_fact SET sku_code = %s, product_key = %s WHERE inventory_key = %s", (new_code, new_pk, k))
    check("B2 Ilocos rows re-keyed to the column-G code", len(keys), 138)
    cur.execute(f"""INSERT INTO {T}.inventory_fact ({', '.join(cols)}, product_key)
                    SELECT {', '.join('b.' + c for c in cols)}, b.product_key FROM b2_rows b
                    WHERE NOT EXISTS (SELECT 1 FROM {T}.inventory_fact f WHERE NOT f.is_demo AND f._src_file = b._src_file
                                      AND f._src_sheet = b._src_sheet AND f.sku_code = b.sku_code)
                    ORDER BY b._src_sheet, b._row_ordinal RETURNING inventory_key, _src_sheet""")
    ins = cur.fetchall()
    log["inserted"]["inventory_fact"] = [k for k, _ in ins]
    check("B2 rows inserted per sheet", {s: sum(1 for _, x in ins if x == s) for s in sorted({x for _, x in ins})},
          {"ILOCOS-ACTUAL ": 12, "PANGASINAN-ACTUAL": 172})
    # the rows these sheets now hold equal the fixed Transform's rows, every column, both directions
    both = ", ".join(cols + ["product_key"])
    check("B2 the two sheets' live rows vs the fixed Transform's rows, rows only in each",
          [one(cur, f"SELECT COUNT(*) FROM (SELECT {both} FROM ({live}) l EXCEPT ALL SELECT {both} FROM b2_rows) x"),
           one(cur, f"SELECT COUNT(*) FROM (SELECT {both} FROM b2_rows EXCEPT ALL SELECT {both} FROM ({live}) l) x")], [0, 0])
    check("B2 cost of the two sheets' rows", dict(_rows(cur, f"SELECT _src_sheet, SUM(cost)::text FROM ({live}) l GROUP BY 1 ORDER BY 1")),
          {"ILOCOS-ACTUAL ": "2625357.17", "PANGASINAN-ACTUAL": "5626419.47"})
    # quarantine: every row that now has a code leaves; the two Total rows (_row_ordinal 0) stay
    cur.execute(f"""DELETE FROM {T}.etl_quarantine q USING b2_rows b WHERE NOT q.is_demo AND q.table_name = 'inventory_fact'
                    AND q.rule = '_drop_uninsertable_quarantined_rows' AND q._src_file = b._src_file AND q._src_sheet = b._src_sheet
                    AND q._row_ordinal = b._row_ordinal AND (q.raw_values->>'cost')::numeric = b.cost RETURNING row_to_json(q)::text""")
    gone = [json.loads(r[0]) for r in cur.fetchall()]
    log["deleted"]["etl_quarantine"] = gone
    check("B2 quarantine rows removed", len(gone), 184)
    check("B2 quarantine rows left for the two sheets (the Total rows)",
          _rows(cur, f"""SELECT _src_sheet, _row_ordinal FROM {T}.etl_quarantine WHERE _src_file = %s AND _src_sheet IN ('PANGASINAN-ACTUAL', 'ILOCOS-ACTUAL ')
                         ORDER BY 1""", (AUG23_SIGNOFF,)), [("ILOCOS-ACTUAL ", 0), ("PANGASINAN-ACTUAL", 0)])
    check("B2 duplicate (sku_code, snapshot_date, region) keys, all inventory rows",
          one(cur, f"SELECT COUNT(*) FROM (SELECT 1 FROM {T}.inventory_fact GROUP BY sku_code, snapshot_date, region HAVING COUNT(*) > 1) x"), 0)
    check("B2 duplicate (sku_code, _period, region) keys, real Del Monte rows",
          one(cur, f"""SELECT COUNT(*) FROM (SELECT 1 FROM {T}.inventory_fact WHERE NOT is_demo AND principal = 'delmonte'
                       GROUP BY sku_code, _period, region HAVING COUNT(*) > 1) x"""), 0)
    check("B2 real Del Monte inventory rows after", one(cur, f"SELECT COUNT(*) FROM {T}.inventory_fact WHERE NOT is_demo AND principal = 'delmonte'"), 5541)
    cur.execute("DROP TABLE b2_rows")
    return 138 + 184 + 184, len(keys) + len(ins) + len(gone)


MIGRATION_0028 = "0028_value_source_rmr_returns_dm_brand_rule.sql"


def apply_migration(cur, T: str, name: str, log: dict) -> None:
    """Same ledger discipline as apply_real_recovery_to_public.apply_migrations: sha256 of the raw file recorded in
    the same transaction; an already-recorded file is skipped, an edited one aborts."""
    from scripts.run_canonical_load import _strip_sql_file
    path = REPO / "analytics" / "db" / "migrations" / name
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    hit = _rows(cur, f"SELECT checksum FROM {T}.schema_migrations WHERE filename = %s", (name,))
    if hit:
        if hit[0][0] != checksum:
            raise RuntimeError(f"{name} is recorded in {T}.schema_migrations with a different checksum")
        return
    cur.execute(f"SET LOCAL search_path TO {T}, public")
    cur.execute(_strip_sql_file(path.read_text(encoding="utf-8")))
    cur.execute("SET LOCAL search_path TO public")
    cur.execute(f"INSERT INTO {T}.schema_migrations (filename, checksum, applied_at, applied_by, target_schema) VALUES (%s, %s, now(), %s, %s)",
                (name, checksum, "apply_dm_fixes_to_public", T))
    log["migrations_applied"].append(name)


def b3_valuation_from_cost(cur, T, check, log):
    apply_migration(cur, T, MIGRATION_0028, log)
    check("B3 migration 0028 recorded", one(cur, f"SELECT COUNT(*) FROM {T}.schema_migrations WHERE filename = %s", (MIGRATION_0028,)), 1)
    check("B3 real Del Monte rows carrying both valuation and cost where they differ",
          one(cur, f"SELECT COUNT(*) FROM {T}.inventory_fact WHERE NOT is_demo AND principal = 'delmonte' AND valuation <> cost"), 0)
    rows = _rows(cur, f"""SELECT inventory_key, valuation, valuation_source FROM {T}.inventory_fact
                          WHERE valuation IS NULL AND cost IS NOT NULL ORDER BY inventory_key""")
    keys = [r[0] for r in rows]
    check("B3 target rows that are real Del Monte", one(cur, f"SELECT COUNT(*) FROM {T}.inventory_fact WHERE inventory_key = ANY(%s) AND NOT is_demo AND principal = 'delmonte'", (keys,)), 209)
    log["updated"]["inventory_fact"] = {"key": "inventory_key", "cols": ["valuation", "valuation_source"], "old": [list(r) for r in rows]}
    cur.execute(f"UPDATE {T}.inventory_fact SET valuation = cost, valuation_source = 'derived_cost' WHERE inventory_key = ANY(%s)", (keys,))
    n = cur.rowcount
    check("B3 valuation of the derived rows", one(cur, f"SELECT SUM(valuation)::text FROM {T}.inventory_fact WHERE inventory_key = ANY(%s)", (keys,)), "3279006.23")
    check("B3 derived rows per sheet", dict(_rows(cur, f"""SELECT _src_sheet, COUNT(*) FROM {T}.inventory_fact WHERE valuation_source = 'derived_cost'
                                                            GROUP BY 1 ORDER BY 1""")), {"ILOCOS INVENTORY SIGNOFF": 200, "PANGASINAN INVENTORY SIGNOFF": 9})
    check("B3 rows still with cost but no valuation", one(cur, f"SELECT COUNT(*) FROM {T}.inventory_fact WHERE valuation IS NULL AND cost IS NOT NULL"), 0)
    return 209, n


RMR_PERIODS = ("2025-10", "2025-11")


def rmr_return_lines():
    """The GS and BO sheets of the real Oct/Nov 2025 RMR GS & BO exports (the ONE PAGER is their union, not loaded),
    through rmr_gs_bo's column map. A line is a row with a parsable Invoice Date and a numeric Net Amount - the rest
    are each sheet's TOTAL, 'Prepared by' and signature rows. Returns (lines with a Return Slip #, lines without)."""
    import pandas as pd
    from analytics.etl import transform
    from scripts.run_canonical_load import STAGING_DIR
    files = [f for f in sorted((STAGING_DIR / "rmr_gs_bo").glob("*.parquet")) if not f.name.startswith("SYNTH")]
    raw = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    raw = raw[raw["_period"].isin(RMR_PERIODS) & raw["_sheet_role"].isin(["gs", "bo"])]
    mapped, _ = transform.apply_column_map(raw, "rmr_gs_bo", transform.DEFAULT_CONFIG_DIR)
    amount = pd.to_numeric(mapped["net_amount"], errors="coerce")
    date = pd.to_datetime(mapped["invoice_date"], errors="coerce")
    lines = mapped[amount.notna() & date.notna()].copy()
    lines["net_amount"], lines["invoice_date"] = amount[lines.index], date[lines.index].dt.date
    return lines[lines["return_slip_num"].notna()], lines[lines["return_slip_num"].isna()]


def b4_rmr_returns(cur, T, check, log):
    from scripts.run_canonical_load import _json_safe_row
    lines, no_slip = rmr_return_lines()
    check("B4 real return rows already in Oct/Nov 2025", one(cur, f"SELECT COUNT(*) FROM {T}.salesreturn_fact WHERE NOT is_demo AND _period = ANY(%s)", (list(RMR_PERIODS),)), 0)
    check("B4 RMR slips already in salesreturn_fact", one(cur, f"SELECT COUNT(*) FROM {T}.salesreturn_fact WHERE return_slip_num = ANY(%s)", (list(lines["return_slip_num"]),)), 0)
    check("B4 lines whose Return Type differs from their sheet (GS/BO)", int((lines["return_type"].str.upper() != lines["_sheet_role"].str.upper()).sum()), 0)
    check("B4 lines whose invoice month differs from the export month", int((lines["invoice_date"].map(lambda x: x.strftime("%Y-%m")) != lines["_period"]).sum()), 0)
    keys = []
    for r in lines.to_dict("records"):
        cur.execute(f"""INSERT INTO {T}.salesreturn_fact (return_slip_num, invoice_num, return_type, return_date, principal, region, net_amount,
                            bo_units, _src_file, _src_sheet, _period, is_demo, quantity_cases, quantity_pieces, source, _row_ordinal, invoice_date, customer_name)
                        VALUES (%s, NULL, %s, NULL, 'delmonte', %s, %s, NULL, %s, %s, %s, false, NULL, NULL, 'rmr', %s, %s, %s) RETURNING return_key""",
                    (r["return_slip_num"], r["return_type"].upper(), r["_region"], r["net_amount"], r["_src_file"], r["_src_sheet"], r["_period"],
                     int(r["_row_ordinal"]), r["invoice_date"], r["customer_name"]))
        keys.append(cur.fetchone()[0])
    log["inserted"]["salesreturn_fact"] = keys
    new = f"SELECT * FROM {T}.salesreturn_fact WHERE return_key = ANY(%s)"
    check("B4 RMR lines inserted", len(keys), 224)
    check("B4 net_amount of the inserted lines", one(cur, f"SELECT SUM(net_amount)::text FROM ({new}) x", (keys,)), "1439087.79")
    check("B4 inserted lines per month / type", {f"{p} {t}": n for p, t, n in _rows(cur, f"SELECT _period, return_type, COUNT(*) FROM ({new}) x GROUP BY 1, 2 ORDER BY 1, 2", (keys,))},
          {"2025-10 BO": 64, "2025-10 GS": 72, "2025-11 BO": 20, "2025-11 GS": 68})
    check("B4 inserted lines per region", dict(_rows(cur, f"SELECT region, COUNT(*) FROM ({new}) x GROUP BY 1 ORDER BY 1", (keys,))),
          {"ilocos": int((lines["_region"] == "ilocos").sum()), "pangasinan": int((lines["_region"] == "pangasinan").sum())})
    check("B4 duplicate RMR line keys", one(cur, f"""SELECT COUNT(*) FROM (SELECT 1 FROM {T}.salesreturn_fact WHERE source = 'rmr'
                                                     GROUP BY _src_file, _src_sheet, _row_ordinal, invoice_date, customer_name, net_amount HAVING COUNT(*) > 1) x"""), 0)
    q = []
    for _, r in no_slip.iterrows():
        cur.execute(f"""INSERT INTO {T}.etl_quarantine (run_id, table_name, rule, reason, _src_file, _src_sheet, _row_ordinal, is_demo, raw_values)
                        VALUES ('dm_fixes_2026-09-28/b4', 'salesreturn_fact', 'rmr_line_without_return_slip', %s, %s, %s, %s, false, %s::jsonb)
                        RETURNING quarantine_key""",
                    ("RMR GS & BO line with no Return Slip #: the dedupe rule against a later sales-return file keys on the slip "
                     "(migration 0028), so the line is held rather than loaded; it also appears on the export's ONE PAGER",
                     r["_src_file"], r["_src_sheet"], int(r["_row_ordinal"]), _json_safe_row(r)))
        q.append(cur.fetchone()[0])
    log["inserted"]["etl_quarantine"] = q
    check("B4 RMR lines without a Return Slip # quarantined", len(q), 2)
    check("B4 net_amount of the quarantined lines", f"{no_slip['net_amount'].sum():.2f}", "1203.60")
    return 226, len(keys) + len(q)


def b5_pack_size(cur, T, check, log):
    """CASE PACK from the price list (the 'Sheet1' of the 2025 inventory workbooks, six identical copies), on
    EXACT sku_code = PRODUCT/ SKU CODE text matches only - no 5-digit-core matching."""
    import pandas as pd
    from scripts.run_canonical_load import STAGING_DIR, _pack_size_text
    copies = [pd.read_parquet(f) for f in sorted((STAGING_DIR / "inventory_sign_off").glob("2025_*__Sheet1.parquet"))]
    lists = [dict(zip(c["PRODUCT/ SKU CODE"].astype(str).str.strip(), c["CASE PACK"])) for c in copies]
    check("B5 price-list copies, all identical on code -> CASE PACK", [len(copies), all(x == lists[0] for x in lists)], [6, True])
    price = {k: _pack_size_text(v) for k, v in lists[0].items()}
    rows = _rows(cur, f"""SELECT product_key, sku_code, pack_size FROM {T}.product_dimension
                          WHERE principal = 'delmonte' AND grain = 'sku' AND sku_code = ANY(%s) ORDER BY product_key""", (list(price),))
    check("B5 Del Monte SKUs whose sku_code equals a price-list code exactly", len(rows), 187)
    check("B5 of those, pack_size already set (would be overwritten)", sum(1 for r in rows if r[2] is not None), 0)
    log["updated"]["product_dimension"] = {"key": "product_key", "cols": ["pack_size"], "old": [[k, p] for k, _, p in rows]}
    n = 0
    for k, code, _ in rows:
        cur.execute(f"UPDATE {T}.product_dimension SET pack_size = %s WHERE product_key = %s", (price[code], k))
        n += cur.rowcount
    got = dict(sorted(_rows(cur, f"SELECT pack_size, COUNT(*) FROM {T}.product_dimension WHERE product_key = ANY(%s) GROUP BY 1",
                            ([r[0] for r in rows],))))
    want = pd.Series([price[c] for _, c, _ in rows]).value_counts().sort_index().to_dict()
    check("B5 pack sizes set, by value", got, dict(sorted(want.items())))
    check("B5 updated rows referenced by real inventory", one(cur, f"""SELECT COUNT(*) FROM {T}.product_dimension p WHERE p.product_key = ANY(%s)
        AND EXISTS (SELECT 1 FROM {T}.inventory_fact f WHERE f.product_key = p.product_key AND NOT f.is_demo)""", ([r[0] for r in rows],)), 187)
    return 187, n


DM_BRAND_ALIAS = REPO / "config" / "alias_tables" / "delmonte_brand.csv"
_DM_BRAND_SKIP = __import__("re").compile(r"^(?:[0-9A-Z]{3,4}\d{5}|\d+|-)$")
DM_BRAND_EXPECTED = {"CONTADINA": 6, "DEL MONTE": 457, "FIT 'N RIGHT": 40, "KIKKOMAN": 30, "MM": 6, "QNE": 1, "SIGNATURE": 1, "TODAY'S": 13}


def dm_brand(name: str, alias: dict) -> str | None:
    """First word of the product name, uppercased; an embedded SKU code, bare number or '-' ahead of the name is
    skipped. Through config/alias_tables/delmonte_brand.csv: a blank canonical is a descriptive word (brand NULL)."""
    for word in (name or "").upper().split():
        if not _DM_BRAND_SKIP.match(word):
            return alias.get(word, word) or None
    return None


def b6_dm_brand(cur, T, check, log):
    import csv as _csv
    with open(DM_BRAND_ALIAS, encoding="utf-8", newline="") as fh:
        alias = {r["raw"]: r["canonical"] for r in _csv.DictReader(fh)}
    rows = _rows(cur, f"""SELECT p.product_key, p.product_name, p.brand, p.brand_source FROM {T}.product_dimension p
                          WHERE p.principal = 'delmonte' AND p.grain = 'sku'
                            AND EXISTS (SELECT 1 FROM {T}.inventory_fact f WHERE f.product_key = p.product_key AND NOT f.is_demo)
                          ORDER BY p.product_key""")
    check("B6 real Del Monte SKUs in scope", len(rows), 597)
    check("B6 of those, brand or brand_source already set", sum(1 for r in rows if r[2] is not None or r[3] is not None), 0)
    target = [(k, dm_brand(name, alias)) for k, name, _, _ in rows]
    target = [(k, b) for k, b in target if b]
    log["updated"]["product_dimension"] = {"key": "product_key", "cols": ["brand", "brand_source"],
                                           "old": [[k, b, s] for k, _, b, s in rows if k in {x for x, _ in target}]}
    n = 0
    for k, b in target:
        cur.execute(f"UPDATE {T}.product_dimension SET brand = %s, brand_source = 'dm_name_first_token_rule' WHERE product_key = %s", (b, k))
        n += cur.rowcount
    keys = [r[0] for r in rows]
    check("B6 brands set, per brand", dict(_rows(cur, f"""SELECT brand, COUNT(*) FROM {T}.product_dimension WHERE product_key = ANY(%s)
                                                           AND brand IS NOT NULL GROUP BY 1 ORDER BY 1""", (keys,))), DM_BRAND_EXPECTED)
    check("B6 SKUs left without a brand (descriptive first word)", one(cur, f"SELECT COUNT(*) FROM {T}.product_dimension WHERE product_key = ANY(%s) AND brand IS NULL", (keys,)), 43)
    check("B6 brand_source on the branded rows", dict(_rows(cur, f"""SELECT brand_source, COUNT(*) FROM {T}.product_dimension
                                                                      WHERE product_key = ANY(%s) GROUP BY 1 ORDER BY 1 NULLS LAST""", (keys,))),
          {"dm_name_first_token_rule": 554, None: 43})
    return 554, n


H1_SHEET = "PANGASINAN SALES REGISTER (2)"


def b7_hold_sheet2_april(cur, T, check, log):
    """The kept rows of the April-2025 workbook's 'PANGASINAN SALES REGISTER (2)' sheet leave sales_fact for
    etl_quarantine, NOT re-dated: every invoice on it is dated 2024-09-03..2024-09-30, so it is suspected to be
    September-2024 data filed under 2025-04, pending SSM. raw_values is the row as loaded, with the customer and
    salesman names in place of their surrogate keys."""
    where = f"NOT s.is_demo AND s.principal = 'delmonte' AND s._src_sheet = '{H1_SHEET}' AND s._period = '2025-04'"
    april = f"SELECT COUNT(*)::text || ' / ' || SUM(net_amount)::text FROM {T}.sales_fact WHERE NOT is_demo AND principal = 'delmonte' AND _period = '2025-04'"
    check("B7 real Del Monte sales 2025-04 before", one(cur, april), "1526 / 14632089.75")
    check("B7 invoice dates on the sheet", [str(x) for x in _rows(cur, f"SELECT MIN(invoice_date), MAX(invoice_date) FROM {T}.sales_fact s WHERE {where}")[0]],
          ["2024-09-03", "2024-09-30"])
    cur.execute(f"""INSERT INTO {T}.etl_quarantine (run_id, table_name, rule, reason, _src_file, _src_sheet, _row_ordinal, is_demo, raw_values)
                    SELECT 'dm_fixes_2026-09-28/b7', 'sales_fact', 'hold_pending_ssm[sales_register]',
                           'sheet ''{H1_SHEET}'' of the April-2025 workbook: every invoice dated 2024-09-03..2024-09-30 - suspected September-2024 '
                           || 'data filed under 2025-04, awaiting SSM; not re-dated', s._src_file, s._src_sheet, NULL, false,
                           (to_jsonb(s) - 'sales_key' - 'customer_key' - 'salesman_key')
                             || jsonb_build_object('customer_name', c.customer_name, 'salesman_name', m.salesman_name)
                    FROM {T}.sales_fact s LEFT JOIN {T}.customer_dimension c ON c.customer_key = s.customer_key
                    LEFT JOIN {T}.salesman_dimension m ON m.salesman_key = s.salesman_key
                    WHERE {where} ORDER BY s.sales_key RETURNING quarantine_key""")
    log["inserted"]["etl_quarantine"] = [r[0] for r in cur.fetchall()]
    cur.execute(f"DELETE FROM {T}.sales_fact s WHERE {where} RETURNING row_to_json(s)::text")
    gone = [json.loads(r[0]) for r in cur.fetchall()]
    log["deleted"]["sales_fact"] = gone
    check("B7 rows moved to etl_quarantine", [len(log["inserted"]["etl_quarantine"]), len(gone)], [564, 564])
    check("B7 net_amount moved", f"{sum(float(r['net_amount']) for r in gone):.2f}", "4932185.22")
    check("B7 real Del Monte sales 2025-04 after", one(cur, april), "962 / 9699904.53")
    check("B7 rows of the sheet left in sales_fact (any period)", one(cur, f"SELECT COUNT(*) FROM {T}.sales_fact WHERE NOT is_demo AND _src_sheet = %s", (H1_SHEET,)), 0)
    return 564 + 564, len(gone) + len(log["inserted"]["etl_quarantine"])


def _rows(cur, sql, args=None):
    cur.execute(sql, args)
    return cur.fetchall()


BATCHES = {
    1: ("quarantine record: April-2023 duplicate sales-return file", ["etl_quarantine"], b1_duplicate_return_file),
    2: ("Aug-2023 sign-off sheets keyed on the sign-off block's code (col G/I)", ["inventory_fact", "etl_quarantine"], b2_signoff_block_codes),
    3: ("migration 0028; valuation = cost where valuation is NULL (valuation_source = 'derived_cost')", ["inventory_fact"], b3_valuation_from_cost),
    4: ("Oct/Nov 2025 RMR GS & BO return lines into salesreturn_fact (source = 'rmr')", ["salesreturn_fact", "etl_quarantine"], b4_rmr_returns),
    5: ("Del Monte pack_size from the price list CASE PACK, exact code matches", ["product_dimension"], b5_pack_size),
    6: ("Del Monte brand / brand_source by the name first-token rule", ["product_dimension"], b6_dm_brand),
    7: ("hold the 564 'PANGASINAN SALES REGISTER (2)' rows filed under 2025-04", ["sales_fact", "etl_quarantine"], b7_hold_sheet2_april),
}


# --- runner -------------------------------------------------------------------------------------------------

def run_batch(conn, cur, T: str, batch_id: int, rehearse: bool, against: str | None,
              batches: dict | None = None, prefix: str | None = None) -> int:
    """`batches` / `prefix`: another runner's batch list and ledger run_id prefix (scripts/apply_synth_v2_cutover.py);
    default this module's."""
    batches, prefix = batches or BATCHES, prefix or RUN_PREFIX
    description, writes, fn = batches[batch_id]
    ensure_ledger(conn, cur, T)
    mine = [r for r in ledger_rows(cur, T) if r["run_id"].startswith(prefix)]
    run_id = max((r["run_id"] for r in mine), default=None) or \
        f"{prefix}{'rehearsal_' if rehearse else ''}{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    done = {r["batch_id"] for r in mine if r["run_id"] == run_id and r["status"] == "done"}
    if batch_id in done:
        print(f"batch {batch_id} already done on {run_id}, skipped")
        return 0
    if [b for b in batches if b < batch_id and b not in done]:
        sys.exit(f"refusing batch {batch_id}: earlier batches not done on {run_id}")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = REPO / "backups" / run_id / f"b{batch_id}_{stamp}"
    if not rehearse:
        rehearsed = [r for r in ledger_rows(cur, against) if r["run_id"].startswith(prefix) and r["batch_id"] == batch_id and r["status"] == "done"]
        if not rehearsed:
            sys.exit(f"refusing: batch {batch_id} has not been rehearsed on {against}")
        scratch_backup = Path(rehearsed[-1]["change_log"]["backup_dir"])
    tables = writes + (["schema_migrations"] if "schema_migrations" not in writes else [])
    manifest = backup(cur, T, tables, backup_dir, batch_id)
    conn.commit()
    checks: list = []

    def check(name, got, want):
        checks.append([name, str(got), str(want), str(got) == str(want)])

    def raise_if_failed():
        failed = [c for c in checks if not c[3]]
        if failed:
            raise RuntimeError("; ".join(f"{n}: got {g}, expected {w}" for n, g, w, _ in failed))

    if not rehearse:
        # same columns as compare(): surrogate keys can differ (a failed attempt still advances a sequence)
        for t in writes:
            drop = SKIP_COMPARE | {IDENT[t]}
            check(f"{t} before the batch: md5 equals the rehearsal's pre-batch md5 (identity key and load timestamps excluded)",
                  csv_md5_without(backup_dir / f"{t}.csv", drop), csv_md5_without(scratch_backup / f"{t}.csv", drop))

    def apply() -> dict:
        log = {"inserted": {}, "updated": {}, "deleted": {}, "migrations_applied": [], "backup_dir": str(backup_dir)}
        before = isolation(cur, T, writes)
        expected, applied = fn(cur, T, check, log)
        check(f"batch {batch_id} rows applied", applied, expected)
        after = isolation(cur, T, writes, {k: c for k, (c, _) in before.items()})
        for k, (c, fp) in before.items():
            check(f"{k}: untouched", after[k][1], fp)
            t, w = k.split("|", 1)
            added = [x for x in columns(cur, T, t) if x not in c]
            if added:
                check(f"{t} [{w}]: columns added by this batch {added} hold no value",
                      one(cur, f"SELECT COUNT(*) FROM {T}.{t} WHERE ({w}) AND (" + " OR ".join(f"{x} IS NOT NULL" for x in added) + ")"), 0)
        log["_expected"], log["_applied"] = expected, applied
        return log

    started = datetime.datetime.now(datetime.timezone.utc)
    try:
        raise_if_failed()  # a failed pre-check stops before the batch writes anything
        log = apply()
        raise_if_failed()
        if rehearse:
            conn.commit()
            undo(cur, T, log)
            proof: list = []
            reset_sequences(cur, T, manifest, proof)
            verify_backup(cur, T, manifest, proof)
            for name, got, want, ok in proof:
                checks.append([f"rollback proof: {name}", str(got), str(want), ok])
            conn.commit()
            log = apply()
        else:
            for t in writes:
                check(f"{t}: public vs {against}, rows only in each", compare(cur, T, against, t), [0, 0])
        raise_if_failed()
    except Exception as exc:
        conn.rollback()
        print(f"batch {batch_id} {description}: FAILED, rolled back - {exc}")
        cur.execute(f"""INSERT INTO {T}.{LEDGER} (run_id, target_schema, batch_id, description, table_name, started_at, finished_at, status, change_log)
                        VALUES (%s, %s, %s, %s, %s, %s, now(), 'failed', %s) ON CONFLICT (run_id, batch_id) DO UPDATE
                        SET status = 'failed', finished_at = now(), change_log = EXCLUDED.change_log""",
                    (run_id, T, batch_id, description, ",".join(writes), started, json.dumps({"error": str(exc), "_checks": checks}, default=str)))
        conn.commit()
        return 1
    log["_checks"], log["backup_dir"] = checks, str(backup_dir)
    # the full undo log goes to disk BEFORE the commit; the ledger keeps it too, except that a deleted-row list over
    # 1,000 rows is replaced there by its count and md5 (rollback() reads changes.json)
    (backup_dir / "changes.json").write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")
    ledger_log = {**log, "deleted": {t: v if len(v) <= 1000 else {"rows": len(v), "md5": hashlib.md5(json.dumps(v, default=str).encode()).hexdigest(),
                                                                   "full_list": "changes.json"} for t, v in log["deleted"].items()}}
    after_md5 = hashlib.md5(json.dumps({t: fingerprint(cur, T, t, "TRUE") for t in writes}).encode()).hexdigest()
    cur.execute(f"""INSERT INTO {T}.{LEDGER} (run_id, target_schema, batch_id, description, table_name, expected_rows, applied_rows,
                    checksum_before, checksum_after, started_at, finished_at, status, change_log)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), 'done', %s) ON CONFLICT (run_id, batch_id) DO UPDATE
                    SET expected_rows = EXCLUDED.expected_rows, applied_rows = EXCLUDED.applied_rows, checksum_before = EXCLUDED.checksum_before,
                        checksum_after = EXCLUDED.checksum_after, finished_at = now(), status = 'done', change_log = EXCLUDED.change_log""",
                (run_id, T, batch_id, description, ",".join(writes), log["_expected"], log["_applied"],
                 "|".join(f"{t}:{m['md5']}" for t, m in manifest["tables"].items()), after_md5, started, json.dumps(ledger_log, default=str)))
    conn.commit()
    for name, got, want, _ in checks:
        print(f"  ok  {name}: {got}")
    print(f"batch {batch_id} {description}: {log['_applied']}/{log['_expected']} rows, {len(checks)} checks ok, committed ({run_id})")
    return 0


def rollback(conn, cur, backup_dir: Path) -> int:
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    log = json.loads((backup_dir / "changes.json").read_text(encoding="utf-8"))
    T, proof = manifest["target"], []
    undo(cur, T, log)
    reset_sequences(cur, T, manifest, proof)
    verify_backup(cur, T, manifest, proof)
    failed = [p for p in proof if not p[3]]
    if failed:
        conn.rollback()
        print(f"ROLLED BACK the undo - {failed}")
        return 1
    cur.execute(f"DELETE FROM {T}.{LEDGER} WHERE run_id = %s AND batch_id = %s", (backup_dir.parent.name, manifest["batch"]))
    conn.commit()
    print(f"undone: batch {manifest['batch']} on {T}, {len(proof)} checks ok")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", default=None, help="'public'")
    p.add_argument("--rehearse", default=None, metavar="SCHEMA", help="scratch schema (built from public on first use)")
    p.add_argument("--against", default=None, metavar="SCHEMA", help="--target public: the rehearsal schema to verify against")
    p.add_argument("--batch", type=int, default=None)
    p.add_argument("--rollback", default=None, metavar="BACKUP_DIR")
    p.add_argument("--status", action="store_true")
    p.add_argument("--i-have-approval", action="store_true")
    p.add_argument("--export", nargs=4, default=None, metavar=("SCHEMA", "TABLE", "COLS", "OUT"), help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.export:  # child of export_to_file(): one table to one CSV file, nothing else
        T, t, cols, out = args.export
        conn = connect()
        cur = conn.cursor()
        cur.execute("SET LOCAL idle_in_transaction_session_timeout = '60s'")  # this transaction only; overrides TXN_SETTINGS' 0
        Path(out).write_bytes(export_rows(cur, T, t, cols.split(",")))
        conn.close()
        return 0
    conn = connect()
    cur = conn.cursor()
    try:
        if args.status:
            for r in ledger_rows(cur, args.target or args.rehearse):
                if r["run_id"].startswith(RUN_PREFIX):
                    print(f"  {r['run_id']}  batch {r['batch_id']}  {r['status']:<7} rows {r['applied_rows']}/{r['expected_rows']}  {r['description']}")
            return 0
        if args.rollback:
            if json.loads((Path(args.rollback) / "manifest.json").read_text(encoding="utf-8"))["target"] == "public" and not args.i_have_approval:
                sys.exit("refusing: a rollback on public needs --i-have-approval")
            return rollback(conn, cur, Path(args.rollback))
        if args.batch not in BATCHES:
            p.error(f"--batch must be one of {sorted(BATCHES)}")
        if args.rehearse:
            if args.rehearse in ("public", "ssm_synth_v2", "ssm_pm_cleanup"):
                p.error("--rehearse needs its own new scratch schema")
            if not one(cur, "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (args.rehearse,)):
                build_scratch(cur, args.rehearse)
                conn.commit()
                print(f"scratch schema {args.rehearse}: built from public")
            return run_batch(conn, cur, args.rehearse, args.batch, True, None)
        if args.target != "public" or not args.against or not args.i_have_approval:
            p.error("--target public needs --against SCHEMA and --i-have-approval")
        return run_batch(conn, cur, "public", args.batch, False, args.against)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
