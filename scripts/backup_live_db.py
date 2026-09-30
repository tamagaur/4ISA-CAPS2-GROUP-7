"""
scripts/backup_live_db.py — full, verified-restorable dump of every base
table in the live `public` schema, before the Phase 1 cutover.

No pg_dump/psql available in this environment (checked: not on PATH), so
this dumps programmatically: full row data to Parquet (one file per table,
preserves Decimal/date/bool types via pyarrow) + a DDL snapshot reflected
directly from the LIVE catalog (not schema.sql, which the Phase 0 audit
already found drifts from live's real ad-hoc-evolved structure — reflecting
the actual live table is the honest source of truth for a backup).

Writes:
  backups/live_backup_<timestamp>/
    manifest.json          - per-table row count + a numeric checksum, and
                             what was left out ("excluded": credentials, see
                             EXCLUDED_TABLES / EXCLUDED_COLUMNS)
    <table>.parquet         - one per base table, full data except credentials
    ddl_snapshot.json       - reflected column/type/constraint info per table

Other schemas: create_backup(engine, schema="ssm_synth_v2") dumps any schema
the same way. scripts/backup_everything.py uses it for every schema of ours
and adds the full table structure (views, indexes, keys, permissions), which
ddl_snapshot.json does not hold.

Usage:
    python -m scripts.backup_live_db            # create the backup
    python -m scripts.backup_live_db --verify PATH   # restore-test an
                                                        existing backup dir
                                                        into a throwaway
                                                        schema, then drop it
"""
from __future__ import annotations

import argparse
import decimal
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB

from analytics.config import get_settings

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_ROOT = REPO_ROOT / "backups"

# Credentials never go into a backup (security audit 2026-09-30, finding 5): a
# backup is an unencrypted copy on a laptop. users keeps every column except
# password_hash, so a restored account comes back "invite pending" (NULL
# password_hash, allowed since migration 0031) and its owner sets a new
# password through a reset link. auth_token (sha256 of one-time invite/reset
# links, dead within 48 hours) is left out whole. manifest.json lists both
# under "excluded", so a check that compares the backup with the live tables
# can tell a deliberate gap from a missing file.
EXCLUDED_TABLES = {
    "auth_token": "one-time invite/reset link hashes; expire within 48 hours, nothing to restore",
}
EXCLUDED_COLUMNS = {
    "users": {"password_hash": "credential; a restored account sets a new password through a reset link"},
}


def _p(msg: str) -> None:
    print(msg, flush=True)


def _list_base_tables(conn, schema: str = "public") -> list[str]:
    rows = conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = :schema AND table_type='BASE TABLE' ORDER BY table_name"
    ), {"schema": schema}).fetchall()
    return [r[0] for r in rows]


def _qcol(name: str) -> str:
    # Quoted column name; a colon is escaped so text() doesn't read it as a bind param.
    return '"' + name.replace('"', '""').replace(":", "\\:") + '"'


def _tables_to_dump(tables: list[str]) -> tuple[list[str], dict[str, str]]:
    """(tables to dump, {table left out: why})."""
    return (
        [t for t in tables if t not in EXCLUDED_TABLES],
        {t: EXCLUDED_TABLES[t] for t in tables if t in EXCLUDED_TABLES},
    )


def _select_list(table: str, columns: list[dict], json_as_text: bool) -> tuple[str, dict[str, str]]:
    """The SELECT list for one table, and {column left out: why}. '*' when no
    column is left out or recast."""
    drop = EXCLUDED_COLUMNS.get(table, {})
    left_out = {c["name"]: drop[c["name"]] for c in columns if c["name"] in drop}
    if not left_out and not json_as_text:
        return "*", {}
    return ", ".join(
        f"{_qcol(c['name'])}::text AS {_qcol(c['name'])}"
        if json_as_text and str(c["type"]).upper() in ("JSON", "JSONB") else _qcol(c["name"])
        for c in columns
        if c["name"] not in drop
    ), left_out


def create_backup(
    engine, out_dir: Path | None = None, schema: str = "public", json_as_text: bool = False
) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if out_dir is None:
        out_dir = BACKUP_ROOT / f"live_backup_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict = {"created_utc": ts, "schema": schema, "tables": {}, "excluded": {"tables": {}, "columns": {}}}

    insp = inspect(engine)

    with engine.connect() as conn:
        tables, manifest["excluded"]["tables"] = _tables_to_dump(_list_base_tables(conn, schema))
        _p(f"Dumping {len(tables)} base tables from {schema} -> {out_dir}")
        if manifest["excluded"]["tables"]:
            _p(f"  left out (credentials): {', '.join(manifest['excluded']['tables'])}")

        for t in tables:
            pk_cols = set(insp.get_pk_constraint(t, schema=schema).get("constrained_columns", []))
            # NOT pd.read_sql() - found 2026-09-14, first real
            # verify-restore: its own numpy dtype inference upgrades an
            # all-Decimal NUMERIC column to float64 whenever every value
            # happens to be numeric-convertible - and IEEE NaN and true
            # NULL both collapse to the SAME np.nan sentinel once that
            # happens, before any code here even runs, permanently losing
            # the distinction between "this row's value is NaN" (a real,
            # non-null value some live rows genuinely have - see
            # PROJECT_STATE_2026-09.md's live-NaN items) and "this row's
            # value is missing." Building the DataFrame directly from raw
            # row mappings keeps each cell as the exact Python object
            # psycopg2 returned (Decimal('NaN') stays a Decimal, None stays
            # None) in an object-dtype column, so the Decimal-detection
            # string-cast below can actually see and preserve it.
            #
            # json_as_text: JSON/JSONB columns as the database's own text of
            # each value. Without this, psycopg2 parses them into dicts
            # (numbers become floats and can lose digits), pyarrow's struct
            # inference adds keys a row never had back as nulls, and the
            # string-cast fallback below writes Python reprs ({'a': None})
            # that are not valid JSON - found 2026-09-28 in
            # etl_quarantine.raw_values and etl_cutover_ledger.change_log.
            select, left_out = _select_list(t, insp.get_columns(t, schema=schema), json_as_text)
            if left_out:
                manifest["excluded"]["columns"][t] = left_out
                _p(f"  {t}: left out column(s) {', '.join(left_out)} (credentials)")
            rows = conn.execute(text(f'SELECT {select} FROM "{schema}"."{t}"')).mappings().all()
            df = pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()

            # Explicitly string-cast every Decimal-holding column BEFORE
            # the parquet write, always, not just on a pyarrow exception -
            # found 2026-09-14, first real verify-restore: pyarrow's
            # decimal128 Arrow type has no representation for NaN, so a
            # live Decimal('NaN') (a real, pre-existing value in a few
            # purchase_fact/sales_fact rows - see PROJECT_STATE_2026-09.md's
            # live-NaN items) silently became a plain NULL on the parquet
            # round-trip - no exception, no warning, just a quietly
            # different value than what's actually in live. A backup whose
            # restore doesn't match live byte-for-byte, including live's
            # own known defects, isn't a real backup - str(Decimal) faithfully
            # preserves "NaN" as literal text, decimal.Decimal(str) parses it
            # back exactly, and Postgres accepts a numeric-typed parameter
            # sent as text (already confirmed working elsewhere this session).
            for c in df.columns:
                if df[c].apply(lambda v: isinstance(v, decimal.Decimal)).any():
                    df[c] = df[c].apply(lambda v: str(v) if isinstance(v, decimal.Decimal) else v)

            path = out_dir / f"{t}.parquet"
            # Non-Decimal object columns still get a string fallback for
            # pyarrow if a column mixes incompatible python types (matches
            # this session's own findings about some money columns being
            # genuinely mixed float/str/Decimal, pre-existing in live) -
            # anything that fails gets a per-column string-cast fallback
            # rather than silently dropping the table from the backup.
            try:
                df.to_parquet(path, index=False, engine="pyarrow")
            except Exception as e:
                _p(f"  [{t}] pyarrow direct dump failed ({e}) - falling back "
                   f"to string-cast for object columns")
                safe = df.copy()
                for c in safe.columns:
                    if safe[c].dtype == object:
                        safe[c] = safe[c].astype(str).where(safe[c].notna(), None)
                safe.to_parquet(path, index=False, engine="pyarrow")

            row_count = len(df)
            # A numeric checksum per table (sum of the first non-PK numeric
            # column found, if any) - cheap way to verify restored data
            # matches real VALUES, not just row counts / identity
            # continuity (a PK-only checksum would only prove the IDs came
            # back, not that the money/quantity figures did).
            checksum_col = None
            checksum_val = None
            for c in df.columns:
                if c in pk_cols:
                    continue
                if pd.api.types.is_bool_dtype(df[c]):
                    # bool is numeric under pandas (is_numeric_dtype(bool)==True) and
                    # pd.to_numeric/.sum() happily coerces it locally, but Postgres's
                    # sum() has no bool overload - found 2026-09-17 when verify_restore's
                    # raw SQL SUM("is_demo") crashed with UndefinedFunction. Skip bool
                    # columns so the checksum column is always SQL-SUM-able.
                    continue
                if pd.api.types.is_numeric_dtype(df[c]) or df[c].apply(
                    lambda v: isinstance(v, (int, float))
                ).any():
                    try:
                        checksum_val = float(pd.to_numeric(df[c], errors="coerce").sum())
                        checksum_col = c
                        break
                    except Exception:
                        continue

            manifest["tables"][t] = {
                "row_count": row_count,
                "checksum_column": checksum_col,
                "checksum_value": checksum_val,
                "file": path.name,
            }
            _p(f"  {t}: {row_count} rows -> {path.name}"
               + (f" (checksum {checksum_col}={checksum_val:.2f})" if checksum_col else ""))

        # DDL snapshot via reflection - the actual live structure, not schema.sql
        _p("Reflecting live DDL (columns/types/nullability/PK) ...")
        insp = inspect(engine)
        ddl_snapshot = {}
        for t in tables:
            cols = insp.get_columns(t, schema=schema)
            pk = insp.get_pk_constraint(t, schema=schema)
            ddl_snapshot[t] = {
                "columns": [
                    {"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]}
                    for c in cols
                ],
                "primary_key": pk.get("constrained_columns", []),
            }
        (out_dir / "ddl_snapshot.json").write_text(
            json.dumps(ddl_snapshot, indent=2), encoding="utf-8"
        )

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _p(f"\nBackup complete: {out_dir}")
    _p(f"Total rows backed up: {sum(t['row_count'] for t in manifest['tables'].values())}")
    return out_dir


def verify_restore(engine, backup_dir: Path, verify_schema: str = "ssm_backup_verify", keep: bool = False) -> bool:
    """Restores the backup into a throwaway schema (never public, never
    ssm_canonical), confirms row counts AND checksums match the manifest
    exactly, then drops the throwaway schema (unless keep=True - e.g. to
    diagnose against a real restored copy afterward, 2026-09-15 cutover
    incident). This is the actual proof the backup is restorable - not
    just that files exist."""
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    ddl_snapshot = json.loads((backup_dir / "ddl_snapshot.json").read_text(encoding="utf-8"))

    _p(f"Verifying restore of {backup_dir.name} into throwaway schema '{verify_schema}' ...")
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{verify_schema}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{verify_schema}"'))

    verify_engine = engine.execution_options(schema_translate_map={None: verify_schema})

    ok = True
    try:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL search_path TO :s, public").bindparams(s=verify_schema))
            # Reflect the live public tables' real Table objects (types,
            # PKs) and recreate them under the verify schema via
            # schema_translate_map, so the restored structure matches what
            # was actually reflected off the live DB, not a guess.
            src_meta = MetaData()
            for t in manifest["tables"]:
                Table(t, src_meta, autoload_with=engine.execution_options(
                    schema_translate_map={verify_schema: "public"}
                ))
        src_meta.create_all(verify_engine, checkfirst=True)

        # Every *_key PK in this schema is GENERATED ALWAYS AS IDENTITY
        # (confirmed via schema.sql's own convention) - a plain INSERT
        # with an explicit PK value is rejected outright by Postgres
        # unless the column allows it. Restoring the EXACT original key
        # values (not fresh ones) matters here - FKs across tables
        # (e.g. Inventory_Fact.product_key -> Product_Dimension) must
        # still resolve correctly post-restore. Switch each identity PK
        # to GENERATED BY DEFAULT for this verify schema only (never
        # touches live), matching the standard pattern for restoring a
        # dump that must preserve identity values.
        for t in manifest["tables"]:
            pk_cols = ddl_snapshot[t]["primary_key"]
            for pk in pk_cols:
                # Not every PK is an identity column (e.g. Date_Dimension.
                # date_key is a real DATE value, not a generated sequence) -
                # try per-column, in its own transaction, and move on for
                # the ones that aren't identity-backed rather than assuming
                # every table's PK shape matches the *_key IDENTITY
                # convention most of this schema follows.
                try:
                    with engine.begin() as conn:
                        conn.execute(text(
                            f'ALTER TABLE "{verify_schema}"."{t}" '
                            f'ALTER COLUMN "{pk}" SET GENERATED BY DEFAULT'
                        ))
                except Exception:
                    pass

        # Insert in FK-dependency order (dimensions before the facts that
        # reference them) - found necessary 2026-09-14, first real run:
        # alphabetical order loaded abc_classification before
        # product_dimension and hit a real ForeignKeyViolation.
        # src_meta.sorted_tables is SQLAlchemy's own topological sort over
        # the reflected FK graph, the same ordering create_all() already
        # used successfully above.
        insert_order = [t.name for t in src_meta.sorted_tables if t.name in manifest["tables"]]

        for t in insert_order:
            info = manifest["tables"][t]
            path = backup_dir / info["file"]
            df = pd.read_parquet(path)
            if not df.empty:
                # JSONB columns (e.g. forecast_result.model_params) come
                # back from a SELECT as Python dict/list objects - psycopg2
                # can round-trip them on SELECT but "can't adapt type
                # 'dict'" on a plain INSERT without help. json.dumps them
                # to text and tell to_sql the target column is JSONB so it
                # casts the text back on insert, rather than silently
                # dropping the table from the restore.
                json_dtype = {}
                for c in df.columns:
                    if df[c].apply(lambda v: isinstance(v, (dict, list))).any():
                        df[c] = df[c].apply(lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v)
                        json_dtype[c] = JSONB
                df.to_sql(
                    t, verify_engine, if_exists="append", index=False, method="multi",
                    chunksize=1000, dtype=json_dtype or None,
                )

            with engine.connect() as conn:
                got = conn.execute(text(f'SELECT count(*) FROM "{verify_schema}"."{t}"')).scalar()
            expected = info["row_count"]
            status = "OK" if got == expected else "MISMATCH"
            if got != expected:
                ok = False
            _p(f"  {t}: expected {expected}, restored {got} -> {status}")

            if info["checksum_column"]:
                with engine.connect() as conn:
                    got_sum = conn.execute(text(
                        f'SELECT sum("{info["checksum_column"]}") FROM "{verify_schema}"."{t}"'
                    )).scalar()
                got_sum = float(got_sum) if got_sum is not None else None
                exp_sum = info["checksum_value"]
                close = got_sum is not None and exp_sum is not None and abs(got_sum - exp_sum) < 0.01
                if not close:
                    ok = False
                    _p(f"    checksum MISMATCH on {info['checksum_column']}: expected "
                       f"{exp_sum}, got {got_sum}")
    finally:
        if keep:
            _p(f"keep=True - leaving '{verify_schema}' in place (not dropped) for further use.")
        else:
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{verify_schema}" CASCADE'))
            _p(f"Throwaway verify schema '{verify_schema}' dropped - nothing left behind.")

    _p(f"\nVERIFY RESULT: {'PASS - every table restores to the exact row count and checksum' if ok else 'FAIL - see mismatches above'}")
    return ok


def restore_over_public(engine, backup_dir: Path) -> None:
    """2026-09-15 cutover-failure incident: restores the 6 canonical fact
    tables (full delete + re-insert, preserving original key values - see
    module docstring, nothing else in this schema FKs to them) and
    surgically removes ONLY the duplicate product_dimension rows the
    failed cutover run created (product_key NOT IN the backup's original
    set) - not a full delete+reinsert of product_dimension, on purpose:
    abc_classification/forecast_result/lp_recommendation already
    reference the ORIGINAL 17,536 rows' product_key values, which were
    never touched by the failed run (only new duplicate rows were
    inserted alongside them) - deleting and reinserting the whole table
    would risk a transient FK violation or a subtle key-reassignment bug
    for no benefit, when the original rows are already exactly correct
    and untouched. Every other table (customer_dimension,
    salesman_dimension, supplier_dimension, date_dimension,
    abc_classification, forecast_result, lp_recommendation, users,
    audit_log) is never touched - confirmed untouched by the failed run,
    nothing to restore there."""
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    ddl_snapshot = json.loads((backup_dir / "ddl_snapshot.json").read_text(encoding="utf-8"))

    fact_tables = [
        "sales_fact", "purchase_fact", "salesreturn_fact",
        "sellout_fact", "inventory_fact", "unilever_sku_demand_fact",
    ]

    _p(f"Restoring {backup_dir.name} over 'public' - {len(fact_tables)} fact tables "
       f"(full restore) + product_dimension (surgical duplicate removal only).")

    for t in fact_tables:
        pk_cols = ddl_snapshot[t]["primary_key"]
        for pk in pk_cols:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE public."{t}" ALTER COLUMN "{pk}" SET GENERATED BY DEFAULT'))
            except Exception:
                pass

        with engine.begin() as conn:
            before = conn.execute(text(f'SELECT count(*) FROM public."{t}"')).scalar()
            conn.execute(text(f'DELETE FROM public."{t}"'))
            _p(f"  {t}: deleted {before} existing (broken/partial) rows")

        df = pd.read_parquet(backup_dir / manifest["tables"][t]["file"])
        if not df.empty:
            json_dtype = {}
            for c in df.columns:
                if df[c].apply(lambda v: isinstance(v, (dict, list))).any():
                    df[c] = df[c].apply(lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v)
                    json_dtype[c] = JSONB
            df.to_sql(t, engine, schema="public", if_exists="append", index=False,
                      method="multi", chunksize=1000, dtype=json_dtype or None)

        for pk in pk_cols:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE public."{t}" ALTER COLUMN "{pk}" SET GENERATED ALWAYS'))
            except Exception:
                pass

        with engine.connect() as conn:
            got = conn.execute(text(f'SELECT count(*) FROM public."{t}"')).scalar()
        expected = manifest["tables"][t]["row_count"]
        _p(f"  {t}: restored {got} rows (backup had {expected}) -> "
           f"{'OK' if got == expected else 'MISMATCH'}")

    # product_dimension - surgical: remove only what the failed run added.
    orig_keys_df = pd.read_parquet(backup_dir / manifest["tables"]["product_dimension"]["file"])
    orig_keys = set(orig_keys_df["product_key"].tolist())
    with engine.connect() as conn:
        current_keys = set(r[0] for r in conn.execute(
            text('SELECT product_key FROM public.product_dimension')
        ).fetchall())
    duplicate_keys = current_keys - orig_keys
    _p(f"\nproduct_dimension: {len(current_keys)} rows currently, {len(orig_keys)} in the "
       f"original backup, {len(duplicate_keys)} duplicate/extra rows to remove")
    if duplicate_keys:
        with engine.begin() as conn:
            conn.execute(
                text('DELETE FROM public.product_dimension WHERE product_key = ANY(:keys)'),
                {"keys": list(duplicate_keys)},
            )
    with engine.connect() as conn:
        got = conn.execute(text('SELECT count(*) FROM public.product_dimension')).scalar()
    expected = manifest["tables"]["product_dimension"]["row_count"]
    _p(f"product_dimension: {got} rows after cleanup (backup had {expected}) -> "
       f"{'OK' if got == expected else 'MISMATCH'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", metavar="PATH", help="Verify-restore an existing backup dir instead of creating a new one")
    args = parser.parse_args()

    cfg = get_settings()
    engine = create_engine(cfg.supabase_db_url)

    if args.verify:
        ok = verify_restore(engine, Path(args.verify))
        return 0 if ok else 1

    out_dir = create_backup(engine)
    ok = verify_restore(engine, out_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
