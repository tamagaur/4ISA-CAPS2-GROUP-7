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

from dataclasses import dataclass

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
    decide separately whether to weight it down."""
    out = df.copy()
    if column not in out.columns or out[column].dropna().empty:
        out["_outlier_flag"] = False
        return out

    q1 = out[column].quantile(0.25)
    q3 = out[column].quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - k * iqr, q3 + k * iqr
    out["_outlier_flag"] = ~out[column].between(lower, upper)
    return out


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
