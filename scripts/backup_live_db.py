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
    manifest.json          - per-table row count + a numeric checksum
    <table>.parquet         - one per base table, full data
    ddl_snapshot.json       - reflected column/type/constraint info per table

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


def _p(msg: str) -> None:
    print(msg, flush=True)


def _list_base_tables(conn) -> list[str]:
    rows = conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
    )).fetchall()
    return [r[0] for r in rows]


def create_backup(engine) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = BACKUP_ROOT / f"live_backup_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict = {"created_utc": ts, "schema": "public", "tables": {}}

    insp = inspect(engine)

    with engine.connect() as conn:
        tables = _list_base_tables(conn)
        _p(f"Dumping {len(tables)} base tables from public -> {out_dir}")

        for t in tables:
            pk_cols = set(insp.get_pk_constraint(t, schema="public").get("constrained_columns", []))
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
            rows = conn.execute(text(f'SELECT * FROM public."{t}"')).mappings().all()
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
            cols = insp.get_columns(t, schema="public")
            pk = insp.get_pk_constraint(t, schema="public")
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


def verify_restore(engine, backup_dir: Path, verify_schema: str = "ssm_backup_verify") -> bool:
    """Restores the backup into a throwaway schema (never public, never
    ssm_canonical), confirms row counts AND checksums match the manifest
    exactly, then drops the throwaway schema. This is the actual proof the
    backup is restorable - not just that files exist."""
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
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{verify_schema}" CASCADE'))
        _p(f"Throwaway verify schema '{verify_schema}' dropped - nothing left behind.")

    _p(f"\nVERIFY RESULT: {'PASS - every table restores to the exact row count and checksum' if ok else 'FAIL - see mismatches above'}")
    return ok


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
