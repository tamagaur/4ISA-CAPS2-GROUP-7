"""
analytics.etl.clean — Data cleaning and feature engineering.

Phase 3B (CLAUDE.md Step 8 — Checkpoint: outlier detection run; schema validation passed):
  Operations:
    - Remove duplicate invoices                (delegates to transform.dedup_facts upstream)
    - Standardize product codes across principals
    - Fix unit measure inconsistencies
    - Compute holding cost features
    - Compute Bad Order rate per SKU: BO_rate = (BO units / units received) x 100
  Output: Cleaned DataFrame ready for load.py.

Anti-fabrication (ARCHITECTURE.md principle #1): outliers are FLAGGED,
never dropped, and any feature this module cannot honestly compute from
present columns is left null with a reason, never estimated.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

REQUIRED_OUTPUT_COLUMNS = [
    # "principal" (bare) not "_principal" — transform.backfill_provenance_fields
    # (2026-08) now populates the real canonical column before clean_pipeline
    # ever sees the frame; checking the stale provenance name here would let
    # validate_output_schema "pass" on output actually missing the column
    # every fact table's schema.sql NOT NULL constraint requires.
    "invoice_num", "net_amount", "principal", "_period", "_outlier_flag",
]


@dataclass
class SchemaValidationResult:
    ok: bool
    missing_columns: list[str]


def validate_output_schema(df: pd.DataFrame, required: list[str] = REQUIRED_OUTPUT_COLUMNS) -> SchemaValidationResult:
    missing = [c for c in required if c not in df.columns]
    return SchemaValidationResult(ok=not missing, missing_columns=missing)


def flag_iqr_outliers(df: pd.DataFrame, column: str, k: float = 1.5) -> pd.DataFrame:
    """IQR-based outlier detection. Flags rows in `_outlier_flag`, never
    drops them - ARCHITECTURE.md principle #1 forbids silent data loss.
    A flagged row still ships downstream; forecasting/classification
    decide separately whether to weight it down.

    Coerces to numeric via pd.to_numeric() before computing quantiles -
    real parquet-sourced money/quantity columns round-trip as
    decimal.Decimal, and numpy's quantile interpolation can't multiply a
    Decimal by the float `k` (confirmed: crashed transform_driver.py the
    first time this function was wired into the real path, having
    previously had zero real callers - see flag_quantity_issues() above,
    which already does this same coercion for the same reason)."""
    out = df.copy()
    if column not in out.columns or out[column].dropna().empty:
        out["_outlier_flag"] = False
        return out

    values = pd.to_numeric(out[column], errors="coerce")
    if values.dropna().empty:
        out["_outlier_flag"] = False
        return out

    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - k * iqr, q3 + k * iqr
    out["_outlier_flag"] = ~values.between(lower, upper)
    return out


@dataclass
class QuantityIssueReport:
    """DEC-15: zero, negative, and IQR-outlier quantities are FLAGGED for
    a human to review, never dropped or clamped - this project already
    documents negatives as real (returns/adjustments) across several facts
    (e.g. SellOut_Fact.quantity, SalesReturnFact.bo_units); the gap this
    closes is making them VISIBLE, not changing how they're stored. A
    value can land in more than one bucket (e.g. negative AND an IQR
    outlier) - the buckets are independent, not mutually exclusive."""
    column: str
    total_rows: int
    zero_count: int
    negative_count: int
    outlier_count: int
    zero_rows: list[dict] = field(default_factory=list)
    negative_rows: list[dict] = field(default_factory=list)
    outlier_rows: list[dict] = field(default_factory=list)


def flag_quantity_issues(df: pd.DataFrame, column: str, k: float = 1.5) -> QuantityIssueReport:
    """Pure report - never mutates or returns a modified DataFrame, since
    this is surfaced through Transform-stage QC tooling (transform_driver.py's
    manifest + transform_signoff.py's sign-off checklist), not persisted as
    a loaded column. Reuses flag_iqr_outliers() for the outlier half rather
    than duplicating the IQR math; that function already returns a fresh
    copy, so calling it here can't leak an _outlier_flag column back onto
    the caller's DataFrame."""
    if column not in df.columns:
        return QuantityIssueReport(column=column, total_rows=len(df), zero_count=0, negative_count=0, outlier_count=0)

    outlier_df = flag_iqr_outliers(df, column, k=k)
    values = pd.to_numeric(df[column], errors="coerce")
    zero_mask = values == 0
    negative_mask = values < 0
    outlier_mask = outlier_df["_outlier_flag"]

    id_cols = [c for c in ("_src_file", "_src_sheet") if c in df.columns] + [column]

    def _rows(mask: pd.Series) -> list[dict]:
        return df.loc[mask.fillna(False), id_cols].to_dict(orient="records")

    return QuantityIssueReport(
        column=column,
        total_rows=len(df),
        zero_count=int(zero_mask.sum()),
        negative_count=int(negative_mask.sum()),
        outlier_count=int(outlier_mask.sum()),
        zero_rows=_rows(zero_mask),
        negative_rows=_rows(negative_mask),
        outlier_rows=_rows(outlier_mask),
    )


def standardize_product_code(df: pd.DataFrame, column: str = "branch_code") -> pd.DataFrame:
    """Preserve leading zeros as TEXT (ARCHITECTURE.md §6.3 type trap) and
    strip incidental whitespace. Extract already typed these as text; this
    is a defensive pass in case Transform received a looser-typed source."""
    if column not in df.columns:
        return df
    out = df.copy()
    out[column] = out[column].astype(str).str.strip()
    return out


def compute_bo_rate(df: pd.DataFrame, bo_units_col: str = "bo_units", received_units_col: str = "units_received") -> pd.DataFrame:
    """BO_rate = (BO units / units received) x 100, per SKU/row.
    Left null (not zero, not dropped) where units_received is 0 or missing
    - a computed 0% would misreport "no bad orders" when the truth is
    "we don't know", which is exactly the fabrication this project bans."""
    out = df.copy()
    if bo_units_col not in out.columns or received_units_col not in out.columns:
        out["bo_rate"] = pd.NA
        return out

    received = out[received_units_col]
    safe = received.where(received > 0)
    out["bo_rate"] = (out[bo_units_col] / safe) * 100
    return out


def clean_pipeline(raw_df: pd.DataFrame, amount_col: str = "net_amount") -> tuple[pd.DataFrame, SchemaValidationResult]:
    """Full clean step. Expects raw_df has already been through
    transform.transform_fact (mapped to canonical fields, deduped,
    source-of-truth filtered) - this stage adds features and flags, it
    does not re-decide identity or source-of-truth."""
    df = standardize_product_code(raw_df)
    if amount_col in df.columns:
        df = flag_iqr_outliers(df, amount_col)
    else:
        df = df.assign(_outlier_flag=False)
    df = compute_bo_rate(df)

    result = validate_output_schema(df)
    return df, result
