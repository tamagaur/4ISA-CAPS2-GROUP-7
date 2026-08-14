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

import json
import random
from dataclasses import dataclass
from pathlib import Path

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
    manifest_path: Path | None = None,
    transform_dir: Path | None = None,
) -> LoadResult:
    """Upsert df into table_name on natural_key using
    INSERT ... ON CONFLICT (natural_key) DO UPDATE. Raises if the
    resulting row count doesn't match rows attempted - per the Step 9
    checkpoint, a silent count mismatch is treated as a bug, not logged
    and ignored.

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
