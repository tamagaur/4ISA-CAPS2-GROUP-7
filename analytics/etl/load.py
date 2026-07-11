"""
analytics.etl.load - Load cleaned data to Supabase via SQLAlchemy.

Phase 3B (CLAUDE.md Step 9 - Checkpoint: row counts match source files; no silent data loss):
  Pattern: upsert (INSERT ... ON CONFLICT DO UPDATE) - no silent overwrites.
  Strategy: batch inserts for performance.
  Post-load: spot-check 10 random SKUs manually (surfaced as a report, not automated).

NOTE: this module assumes the target table already exists in Postgres/
Supabase (analytics/db/schema.sql). That DDL is still a TODO stub as of
this writing (Phase 3A) - load_to_supabase() will raise a clear
ProgrammingError from the driver if the table is missing, it does not
create tables itself (that is db/schema.sql's job, reviewed separately).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import Engine, MetaData, Table, inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine as SAEngine


@dataclass
class LoadResult:
    table_name: str
    rows_attempted: int
    rows_upserted: int
    spot_check_sample: list[dict]


def load_to_supabase(
    df: pd.DataFrame,
    table_name: str,
    engine: Engine,
    natural_key: list[str],
    batch_size: int = 500,
) -> LoadResult:
    """Upsert df into table_name on natural_key using
    INSERT ... ON CONFLICT (natural_key) DO UPDATE. Raises if the
    resulting row count doesn't match rows attempted - per the Step 9
    checkpoint, a silent count mismatch is treated as a bug, not logged
    and ignored.

    Batches to keep statement size reasonable on large loads (per-SKU
    Unilever series or years of Del Monte invoices can be sizeable).
    """
    if df.empty:
        return LoadResult(table_name=table_name, rows_attempted=0, rows_upserted=0, spot_check_sample=[])

    missing_key_cols = [k for k in natural_key if k not in df.columns]
    if missing_key_cols:
        raise KeyError(f"natural_key column(s) {missing_key_cols} not present in DataFrame for table '{table_name}'")

    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)

    table_columns = {c.name for c in table.columns}
    df_columns = [c for c in df.columns if c in table_columns]
    unknown_columns = [c for c in df.columns if c not in table_columns and not c.startswith("_")]
    if unknown_columns:
        raise ValueError(
            f"Columns {unknown_columns} in DataFrame are not present in table '{table_name}'. "
            f"Either the column map is wrong or the table DDL needs updating - this is not "
            f"silently dropped."
        )

    records = df[df_columns].where(pd.notnull(df[df_columns]), None).to_dict(orient="records")

    total_upserted = 0
    with engine.begin() as conn:
        for start in range(0, len(records), batch_size):
            batch = records[start:start + batch_size]
            stmt = pg_insert(table).values(batch)
            update_cols = {c: stmt.excluded[c] for c in df_columns if c not in natural_key}
            stmt = stmt.on_conflict_do_update(index_elements=natural_key, set_=update_cols)
            result = conn.execute(stmt)
            total_upserted += result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(batch)

    if total_upserted != len(records):
        raise RuntimeError(
            f"Row count mismatch loading '{table_name}': attempted {len(records)}, "
            f"driver reports {total_upserted} upserted. Per Step 9, this is a hard failure, "
            f"not a warning."
        )

    sample_n = min(10, len(records))
    spot_check_sample = random.sample(records, sample_n) if sample_n else []

    return LoadResult(
        table_name=table_name,
        rows_attempted=len(records),
        rows_upserted=total_upserted,
        spot_check_sample=spot_check_sample,
    )
