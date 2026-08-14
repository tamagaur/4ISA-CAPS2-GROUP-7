"""
analytics.db.seed_date_dim — Populate the date_dimension table.

Generates one row per calendar day and upserts into date_dimension via the
same idempotent upsert path as everything else (analytics.etl.load) -
no bespoke INSERT logic duplicated here.

Column set matches analytics/db/models.py / schema.sql exactly:
  date_key (PK, the date itself - no separate surrogate + full_date pair;
            see note below), day_of_week, day_name, week_of_year, month,
  month_name, quarter, year, is_weekend, fiscal_period.

NOTE ON SCOPE (deviation from this file's original TODO comment, flagged
not silently changed): the original stub described date_key as a PK plus
a separate full_date column. schema.sql instead made date_key itself a
DATE (the natural key IS the date - no surrogate needed for a calendar
table), so there's no separate full_date column to populate. If that's
wrong for how the rest of the team expects to join against this table,
raise it before relying on it downstream.

fiscal_period is left NULL for every row - ARCHITECTURE.md principle #1
(anti-fabrication): SSM's fiscal calendar alignment is not confirmed
anywhere in the source data, so this column stays null rather than
guessing a fiscal quarter. Confirm with Yuan, then backfill for real
via a separate, explicit update - not by inventing a rule here.

Default range: 2021-01-01 through 2026-12-31. Covers the full ~5-year
source corpus (data/raw/ spans 2021-2025) plus the Unilever La Union
file's known extent into 2026-02, with headroom for the SARIMA forecast
horizon. Re-run with --end to extend further later; this is additive
(upsert), never destructive.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import create_engine

from analytics.etl.load import LoadResult, load_to_supabase

DATE_DIMENSION_COLUMNS = [
    "date_key", "day_of_week", "day_name", "week_of_year",
    "month", "month_name", "quarter", "year", "is_weekend", "fiscal_period",
]

DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-12-31"


@dataclass
class DateRangeValidationResult:
    ok: bool
    row_count: int
    expected_row_count: int
    duplicate_dates: list[str]


def generate_date_range(start: str = DEFAULT_START, end: str = DEFAULT_END) -> pd.DataFrame:
    """Pure function of (start, end) - deterministic, no wall-clock or
    random input, so re-running produces byte-identical rows (matches
    the Extract stage's determinism rule, ARCHITECTURE.md principle #4).

    One row per calendar day (not just business days - Date_Dimension is
    a general calendar; is_weekend flags weekends for whoever needs to
    filter them, it doesn't exclude them).
    """
    dates = pd.date_range(start=start, end=end, freq="D")

    df = pd.DataFrame({
        "date_key": dates.date,
        "day_of_week": dates.dayofweek + 1,          # ISO: 1=Mon .. 7=Sun
        "day_name": dates.day_name(),
        "week_of_year": dates.isocalendar().week.values,
        "month": dates.month,
        "month_name": dates.month_name(),
        "quarter": dates.quarter,
        "year": dates.year,
        "is_weekend": dates.dayofweek.isin([5, 6]),   # Sat=5, Sun=6 (0-indexed Monday=0)
    })
    df["fiscal_period"] = None   # left null - see module docstring, not a guess

    return df[DATE_DIMENSION_COLUMNS]


def validate_date_range(df: pd.DataFrame, start: str, end: str) -> DateRangeValidationResult:
    """Checkpoint from the original TODO: 'temporal hierarchy intact'.
    Confirms no gaps and no duplicate dates before this ever reaches the
    database - a cheap, deterministic sanity check, not a data quality
    judgment call."""
    expected = pd.date_range(start=start, end=end, freq="D")
    expected_count = len(expected)

    dupes = df["date_key"][df["date_key"].duplicated()].astype(str).tolist()
    ok = (len(df) == expected_count) and not dupes

    return DateRangeValidationResult(
        ok=ok,
        row_count=len(df),
        expected_row_count=expected_count,
        duplicate_dates=dupes,
    )


def upsert_date_dimension(engine, start: str = DEFAULT_START, end: str = DEFAULT_END) -> tuple[LoadResult, DateRangeValidationResult]:
    """Generate the full calendar range and upsert it into date_dimension
    on date_key. Safe to re-run (upsert, not insert) and safe to call
    again later with a later `end` to extend the horizon - it will not
    touch or duplicate existing rows outside the new range."""
    df = generate_date_range(start, end)
    validation = validate_date_range(df, start, end)
    if not validation.ok:
        raise ValueError(
            f"generate_date_range produced an invalid calendar: "
            f"expected {validation.expected_row_count} rows, got {validation.row_count}, "
            f"duplicates={validation.duplicate_dates[:5]}"
        )

    result = load_to_supabase(df, "date_dimension", engine, natural_key=["date_key"])
    return result, validation


def _build_engine_from_env():
    """Reads SUPABASE_DB_URL directly from the environment for now.
    analytics/config.py is still a TODO stub (Phase 3A) - once it's
    implemented, swap this for analytics.config.Settings so there's one
    place that loads/validates .env, not two."""
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        print(
            "SUPABASE_DB_URL is not set. Copy .env.example to .env, fill in your "
            "real Supabase connection string, and make sure it's loaded into the "
            "environment before running this script (e.g. `export $(cat .env | xargs)` "
            "or via python-dotenv once analytics/config.py is implemented).",
            file=sys.stderr,
        )
        sys.exit(1)
    return create_engine(db_url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed date_dimension with one row per calendar day.")
    parser.add_argument("--start", default=DEFAULT_START, help=f"Start date, inclusive (default: {DEFAULT_START})")
    parser.add_argument("--end", default=DEFAULT_END, help=f"End date, inclusive (default: {DEFAULT_END})")
    args = parser.parse_args()

    engine = _build_engine_from_env()
    result, validation = upsert_date_dimension(engine, start=args.start, end=args.end)

    print(f"Generated {validation.row_count} calendar days ({args.start} .. {args.end}).")
    print(f"Upserted {result.rows_upserted}/{result.rows_attempted} rows into date_dimension.")
    if result.spot_check_sample:
        print("Spot-check sample:")
        for row in result.spot_check_sample[:3]:
            print(f"  {row}")


if __name__ == "__main__":
    main()
