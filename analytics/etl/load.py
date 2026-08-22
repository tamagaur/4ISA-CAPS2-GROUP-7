"""
analytics.etl.load - Load cleaned data to Supabase via SQLAlchemy.

Phase 3B (CLAUDE.md Step 9 - Checkpoint: row counts match source files; no silent data loss):
  Pattern: upsert (INSERT ... ON CONFLICT DO UPDATE) - no silent overwrites.
  Strategy: batch inserts for performance.
  Post-load: spot-check 10 random SKUs manually (surfaced as a report, not automated).

NOTE: this module assumes the target table already exists in Postgres/
Supabase (analytics/db/schema.sql). That DDL was reviewed against real
data and fixed 2026-08 (still never executed against a live database as
of this writing) - load_to_supabase() will raise a clear ProgrammingError
from the driver if the table is missing, it does not create tables
itself (that is db/schema.sql's job).

DEC-09 (2026-08, DECIDED): dimension FK resolution happens here, in Load,
not in Transform - see resolve_dimension_fk() and load_to_supabase()'s
dimension_fks argument. Transform stays DB-free; this is the only stage
that opens a connection to resolve/create a dimension row before the
fact row that references it gets upserted.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, MetaData, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert


@dataclass
class DimensionFKSpec:
    """Describes how to resolve one FK column on a fact DataFrame against
    one dimension table before the fact itself is upserted.

    df_to_dimension_columns: dimension natural-key column -> df column
      name, for natural-key parts that come from the fact's own data
      (e.g. {"sku_code": "sku_code", "principal": "principal"}).
    static_values: dimension natural-key column -> literal value, for
      parts that are constant for every row in this call rather than a
      real df column (e.g. {"grain": "sku"} when loading a fact that's
      entirely SKU-grain - grain isn't a column Transform produces, it's
      a property of which fact is being loaded).
    Every column in dimension_natural_key must appear in exactly one of
    these two maps - never fabricate a third source for it.
    """
    fk_column: str
    dimension_table: str
    dimension_pk: str
    dimension_natural_key: list[str]
    df_to_dimension_columns: dict[str, str] = field(default_factory=dict)
    static_values: dict = field(default_factory=dict)


@dataclass
class DimensionResolutionReport:
    fk_column: str
    dimension_table: str
    distinct_keys_seen: int
    rows_inserted: int
    rows_unresolved: int   # natural key had a null part - fk left NULL, never fabricated


def build_dimension_key_frame(df: pd.DataFrame, spec: DimensionFKSpec) -> tuple[pd.DataFrame, pd.Series]:
    """Pure helper, no DB access — builds the dimension natural-key frame
    for df per spec, and the per-row mask of which rows have every
    REAL (df-sourced) natural-key part present. Split out from
    resolve_dimension_fk() so the anti-fabrication null-handling logic
    is testable without a live database, matching this codebase's
    existing split between pure logic and DB-touching functions (e.g.
    transform.dedup_facts vs this module's upsert).

    Only df_to_dimension_columns-sourced nulls make a row unresolvable -
    a static_values null (e.g. Product_Dimension.category_path for a
    SKU-grain row, which is legitimately always NULL by the dimension's
    own design, per schema.sql's comment on that table) is a deliberate,
    known constant, not missing data, and must not be flagged the same
    way real missing per-row data is."""
    missing_sources = [
        col for col in spec.dimension_natural_key
        if col not in spec.df_to_dimension_columns and col not in spec.static_values
    ]
    if missing_sources:
        raise KeyError(
            f"DimensionFKSpec for '{spec.fk_column}': natural-key column(s) {missing_sources} "
            f"have no source - add to df_to_dimension_columns or static_values, never left implicit."
        )

    key_df = pd.DataFrame(index=df.index)
    for dim_col in spec.dimension_natural_key:
        if dim_col in spec.static_values:
            key_df[dim_col] = spec.static_values[dim_col]
        else:
            df_col = spec.df_to_dimension_columns[dim_col]
            if df_col not in df.columns:
                raise KeyError(f"df_to_dimension_columns maps '{dim_col}' -> '{df_col}', but '{df_col}' isn't in df")
            key_df[dim_col] = df[df_col]

    real_key_cols = [c for c in spec.dimension_natural_key if c in spec.df_to_dimension_columns]
    resolvable_mask = key_df[real_key_cols].notna().all(axis=1) if real_key_cols else pd.Series(True, index=df.index)
    return key_df, resolvable_mask


def resolve_dimension_fk(
    df: pd.DataFrame, engine: Engine, spec: DimensionFKSpec,
) -> tuple[pd.DataFrame, DimensionResolutionReport]:
    """Look up (or insert, if genuinely new) the dimension row matching
    each df row's natural key, and attach its surrogate key as
    spec.fk_column. This is the Load-time half of DEC-09.

    A row whose natural key has ANY null part is left with fk_column =
    NULL rather than guessed at or matched to an existing "closest" row
    - anti-fabrication principle #1. Never inserts a dimension row with
    a null natural-key part either, for the same reason.

    Existing dimension rows are matched, never duplicated: this issues
    an INSERT ... ON CONFLICT DO NOTHING against the dimension table's
    own natural-key UNIQUE constraint, so re-running is idempotent
    (matches this module's existing upsert discipline)."""
    key_df, resolvable_mask = build_dimension_key_frame(df, spec)
    distinct_keys = key_df[resolvable_mask].drop_duplicates().reset_index(drop=True)

    metadata = MetaData()
    dim_table = Table(spec.dimension_table, metadata, autoload_with=engine)

    rows_inserted = 0
    if not distinct_keys.empty:
        records = distinct_keys.to_dict(orient="records")
        with engine.begin() as conn:
            stmt = pg_insert(dim_table).values(records)
            stmt = stmt.on_conflict_do_nothing(index_elements=spec.dimension_natural_key)
            result = conn.execute(stmt)
            rows_inserted = result.rowcount if result.rowcount and result.rowcount > 0 else 0

        # Re-select rather than trust RETURNING here: ON CONFLICT DO
        # NOTHING doesn't return the pre-existing rows it skipped, and we
        # need the pk for every distinct key seen, not just the new ones.
        select_cols = [dim_table.c[spec.dimension_pk]] + [dim_table.c[c] for c in spec.dimension_natural_key]
        with engine.connect() as conn:
            existing = pd.DataFrame(
                conn.execute(select(*select_cols)).fetchall(),
                columns=[spec.dimension_pk] + spec.dimension_natural_key,
            )
        key_to_pk = existing.merge(distinct_keys, on=spec.dimension_natural_key, how="inner")
        key_to_pk = key_to_pk.drop_duplicates(subset=spec.dimension_natural_key)

        merged = key_df.merge(key_to_pk, on=spec.dimension_natural_key, how="left")
        fk_values = merged[spec.dimension_pk]
    else:
        fk_values = pd.Series([None] * len(df), index=df.index)

    out = df.copy()
    out[spec.fk_column] = fk_values.values

    report = DimensionResolutionReport(
        fk_column=spec.fk_column,
        dimension_table=spec.dimension_table,
        distinct_keys_seen=len(distinct_keys),
        rows_inserted=rows_inserted,
        rows_unresolved=int((~resolvable_mask).sum()),
    )
    return out, report


@dataclass
class LoadResult:
    table_name: str
    rows_attempted: int
    rows_upserted: int
    spot_check_sample: list[dict]
    dimension_resolutions: list[DimensionResolutionReport] = field(default_factory=list)


@dataclass
class RejectRateGateResult:
    staged: int
    rejected: int
    reject_rate: float
    threshold: float
    passed: bool


# ARCHITECTURE.md DEC-12: no panel/adviser requirement specifies a
# reject-rate threshold anywhere in the capstone manuscript - this is a
# TEAM DEFAULT, not a sourced business number (same honesty standard as
# DEC-08's EOQ entry). Chosen against the real observed baseline (0
# rejects across the full 161-file corpus, per ARCHITECTURE.md status) -
# it is a circuit breaker for something going structurally wrong (a bad
# supplier export, a misconfigured raw_dir), not a tolerance expected to
# be approached in normal operation. Revise here (and in DEC-12) if the
# adviser/panel later specifies a different number.
REJECT_RATE_THRESHOLD = 0.02


def compute_reject_rate(manifest: dict, threshold: float = REJECT_RATE_THRESHOLD) -> RejectRateGateResult:
    """Reject rate = rejected / (staged + rejected), counting only
    Extract's sheet/file-level rejects - staging/_manifest.json's "reject"
    list (unreadable files, no detectable header/data, Magnolia-quarantined
    content; see extract/_shared.py::build_manifest). Checksum mismatches
    are deliberately excluded from this count - extract/_qc.py already
    documents those as informational, never a staging/Load gate, and this
    story doesn't reopen that decision."""
    staged = len(manifest.get("staged", []))
    rejected = len(manifest.get("reject", []))
    total = staged + rejected
    reject_rate = (rejected / total) if total else 0.0
    return RejectRateGateResult(
        staged=staged, rejected=rejected, reject_rate=reject_rate,
        threshold=threshold, passed=reject_rate <= threshold,
    )


def check_reject_rate_gate(manifest_path: Path, threshold: float = REJECT_RATE_THRESHOLD) -> RejectRateGateResult:
    """Blocks Load when Extract's reject rate crosses `threshold`
    (ARCHITECTURE.md DEC-12) - raises rather than silently proceeding,
    matching transform_fact()'s natural_key=None guard elsewhere in this
    pipeline. Bad data must not reach the warehouse just because most of a
    batch happened to parse."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = compute_reject_rate(manifest, threshold=threshold)
    if not result.passed:
        raise RuntimeError(
            f"Reject-rate gate failed: {result.rejected}/{result.staged + result.rejected} "
            f"sheets/files rejected ({result.reject_rate:.1%}), exceeding the {threshold:.0%} "
            f"threshold (ARCHITECTURE.md DEC-12). Load refuses to run - fix the underlying "
            f"data/extraction problem before retrying; do not raise the threshold just to "
            f"make this pass."
        )
    return result


@dataclass
class SignoffGateResult:
    decision: str
    decided_by: str
    decided_at: str


def check_signoff_gate(transform_dir: Path) -> SignoffGateResult:
    """Blocks Load unless a person has explicitly recorded a decision on
    the CURRENT transform manifest (transform_signoff.py — the "M2
    sign-off checklist" story). Raises rather than proceeding on a missing
    sign-off, a "rejected" decision, or a stale one (its
    manifest_fingerprint doesn't match transform_dir/_manifest.json
    anymore, e.g. Transform was re-run since the sign-off was recorded) —
    an absent or outdated approval is not treated as an implicit yes."""
    from analytics.etl.transform_signoff import compute_manifest_fingerprint

    manifest_path = transform_dir / "_manifest.json"
    signoff_path = transform_dir / "_signoff.json"

    if not signoff_path.exists():
        raise RuntimeError(
            f"Sign-off gate failed: no {signoff_path} found. Load refuses to run — a person "
            f"must record an explicit decision first: python -m analytics.etl.transform_signoff "
            f"--decision approved --by \"<name>\"."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    signoff = json.loads(signoff_path.read_text(encoding="utf-8"))

    current_fingerprint = compute_manifest_fingerprint(manifest)
    if signoff.get("manifest_fingerprint") != current_fingerprint:
        raise RuntimeError(
            f"Sign-off gate failed: {signoff_path} is stale — its manifest_fingerprint doesn't "
            f"match the current {manifest_path} (Transform was likely re-run since sign-off). "
            f"A fresh decision is required, not a carried-over approval for different results."
        )

    if signoff.get("decision") != "approved":
        raise RuntimeError(
            f"Sign-off gate failed: recorded decision is {signoff.get('decision')!r}, not "
            f"'approved' (by {signoff.get('decided_by')!r} at {signoff.get('decided_at')!r}). "
            f"Load refuses to run on an explicit rejection."
        )

    return SignoffGateResult(
        decision=signoff["decision"], decided_by=signoff.get("decided_by"), decided_at=signoff.get("decided_at"),
    )


def load_to_supabase(
    df: pd.DataFrame,
    table_name: str,
    engine: Engine,
    natural_key: list[str],
    batch_size: int = 500,
    dimension_fks: list[DimensionFKSpec] | None = None,
    manifest_path: Path | None = None,
    transform_dir: Path | None = None,
) -> LoadResult:
    """Upsert df into table_name on natural_key using
    INSERT ... ON CONFLICT (natural_key) DO UPDATE. Raises if the
    resulting row count doesn't match rows attempted - per the Step 9
    checkpoint, a silent count mismatch is treated as a bug, not logged
    and ignored.

    dimension_fks (DEC-09, 2026-08): resolved via resolve_dimension_fk()
    BEFORE the fact upsert below, so tables with a NOT NULL FK (e.g.
    Unilever_SKU_Demand_Fact.product_key) can actually load - a caller
    can't defer this to a later backfill pass for those tables, the DB
    would reject the insert. Order matters: each spec's fk_column is
    added to df in sequence, so a later spec could in principle depend
    on an earlier one's resolved column (none currently do).

    Batches to keep statement size reasonable on large loads (per-SKU
    Unilever series or years of Del Monte invoices can be sizeable).

    manifest_path: when given, enforces the reject-rate gate
    (check_reject_rate_gate(), ARCHITECTURE.md DEC-12) before anything is
    written - Load refuses to run at all if Extract's reject rate crossed
    the threshold. Optional and skipped by default (not a hardcoded path)
    so existing callers/tests that don't pass one are unaffected; any real
    Load orchestration should pass staging/_manifest.json.

    transform_dir: when given, enforces the M2 sign-off gate
    (check_signoff_gate() — a person must have explicitly recorded an
    "approved" decision on the current transform/_manifest.json via
    transform_signoff.py). Also optional/opt-in, independent of
    manifest_path — both gates check different stages and can be used
    together or separately.
    """
    if manifest_path is not None:
        check_reject_rate_gate(manifest_path)
    if transform_dir is not None:
        check_signoff_gate(transform_dir)

    if df.empty:
        return LoadResult(table_name=table_name, rows_attempted=0, rows_upserted=0, spot_check_sample=[])

    missing_key_cols = [k for k in natural_key if k not in df.columns]
    if missing_key_cols:
        raise KeyError(f"natural_key column(s) {missing_key_cols} not present in DataFrame for table '{table_name}'")

    dimension_resolutions: list[DimensionResolutionReport] = []
    for spec in dimension_fks or []:
        df, dim_report = resolve_dimension_fk(df, engine, spec)
        dimension_resolutions.append(dim_report)

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
        dimension_resolutions=dimension_resolutions,
    )
