"""
scripts/generate_synthetic_backfill.py — additional synthetic coverage-gap
backfill (see chat instructions, session continuing
reports/SYNTHETIC_STAGING_CONVERSION.md). Adviser-sanctioned synthetic
data, same standing rules as the rest of this session.

Unlike scripts/convert_synthetic_to_staging.py (which converts EXISTING
raw synthetic .xlsx files), this script GENERATES new rows for periods
that have no raw synthetic file at all, using distributions/rosters/
conventions derived directly from real staged data. Writes only to
staging_synthetic/ - never staging/. Read-only on staging/.

Usage: python scripts/generate_synthetic_backfill.py
"""
from __future__ import annotations

import decimal
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analytics.etl.extract._shared import PROVENANCE_COLUMNS  # noqa: E402

REAL_STAGING_DIR = REPO_ROOT / "staging"
OUT_DIR = REPO_ROOT / "staging_synthetic"


def normalize_mixed_dtype_columns(df: pd.DataFrame, exclude: set = frozenset()) -> pd.DataFrame:
    """Real staged data repeatedly mixes decimal.Decimal, float, and str
    within the same column across different files/periods/eras (found
    three times this session: sales_register/purchase_order's money
    columns, sell_out's Total Without Tax, inventory_sign_off's Cost/
    Valuation/etc.) - resampling rows at random from real data naturally
    inherits that real mix, but pyarrow refuses to write a truly
    mixed-type column. Rather than continue enumerating specific column
    names as each one surfaces a crash, this scans every object-dtype
    column for a real Decimal/float/str mix and normalizes those (only
    those - text columns like Customer Name are untouched, they're
    already uniformly str) to a single consistent string representation.
    `exclude` is for columns already handled by a more specific function
    (e.g. Invoice Num, which is fully regenerated, not resampled)."""
    out = df.copy()
    for col in out.columns:
        if col in exclude or col.startswith("_") or out[col].dtype != object:
            continue
        non_null = out[col].dropna()
        if non_null.empty:
            continue
        types_seen = set(non_null.apply(type))
        numeric_types = {decimal.Decimal, float, int}
        if types_seen & numeric_types and len(types_seen) > 1 and types_seen <= (numeric_types | {str}):
            out[col] = out[col].apply(lambda v: None if pd.isna(v) else (str(v) if isinstance(v, str) else f"{float(v):.2f}"))
    return out


def _seed_for(*parts: str) -> np.random.Generator:
    key = "|".join(parts)
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    return np.random.default_rng(seed)


# ================================================================
# 1. unilever_sku backfill — 2021-01..2022-12, 2026-03..2026-08
# ================================================================

UNILEVER_BACKFILL_PERIODS = (
    [f"2021-{m:02d}" for m in range(1, 13)]
    + [f"2022-{m:02d}" for m in range(1, 13)]
    + [f"2026-{m:02d}" for m in range(3, 9)]
)

CAL_MONTH_COL = "Calendar\r\n  Month"
PRODUCT_COL = "Product"
DESC_COL = "__col2__"
PACK_SIZE_COL = "Pack Size"
QTY_CS_COL = "Sale Quantity in\r\n  Aggr.CS"
QTY_PC_COL = "Sale Quantity in\r\n  Aggr.PC"
GSV_COL = "GSV"
AMT_COL = "Total Sales Amt\r\n  Inc. Tax"
NUMERIC_COLS = [QTY_CS_COL, QTY_PC_COL, GSV_COL, AMT_COL]


def load_real_unilever_sku() -> pd.DataFrame:
    files = sorted(REAL_STAGING_DIR.glob("unilever_sku/*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def derive_unilever_seasonality(real_df: pd.DataFrame) -> dict:
    """Real total PC-quantity by calendar month-of-year, normalized to a
    multiplier around 1.0 - derived from all 38 real months (2023-01
    through 2026-02), not invented."""
    month_num = real_df["_period"].str[5:7]
    qty = pd.to_numeric(real_df[QTY_PC_COL], errors="coerce")
    totals = qty.groupby(month_num).sum()
    return (totals / totals.mean()).to_dict()


def derive_unilever_sku_roster(real_df: pd.DataFrame) -> dict:
    """Per real SKU (1,807 distinct Product codes - the exact real
    roster, never invented): static attributes (description, pack size)
    plus every real historical row's numeric-field tuple, plus its real
    presence rate across the 38 real months. Backfill/forward generation
    draws SKU identity and quantity/GSV/amount magnitudes only from this -
    no SKU code and no numeric value that didn't really occur."""
    roster = {}
    n_real_months = real_df["_period"].nunique()
    for sku, group in real_df.groupby(PRODUCT_COL):
        roster[sku] = {
            "description": group[DESC_COL].mode().iloc[0] if not group[DESC_COL].mode().empty else group[DESC_COL].iloc[0],
            "pack_size": group[PACK_SIZE_COL].mode().iloc[0] if not group[PACK_SIZE_COL].mode().empty else group[PACK_SIZE_COL].iloc[0],
            "presence_rate": len(group) / n_real_months,
            "real_rows": group[NUMERIC_COLS].to_dict(orient="records"),
        }
    return roster


def generate_unilever_sku_period(roster: dict, seasonal: dict, period: str) -> pd.DataFrame:
    year, month_num = period.split("-")
    scale = seasonal.get(month_num, 1.0)
    rng = _seed_for("unilever_sku", period)

    records = []
    for sku, info in roster.items():
        if rng.random() >= info["presence_rate"]:
            continue  # real per-SKU absence rate, not every SKU appears every month
        real_row = info["real_rows"][int(rng.integers(0, len(info["real_rows"])))]
        rec = {
            CAL_MONTH_COL: f"{month_num}.{year}",
            PRODUCT_COL: sku,
            DESC_COL: info["description"],
            PACK_SIZE_COL: info["pack_size"],
        }
        for col in NUMERIC_COLS:
            val = real_row[col]
            # real values round-trip as decimal.Decimal; coerce to float
            # before scaling (same class of bug as clean.flag_iqr_outliers
            # earlier this session).
            rec[col] = (float(val) * scale) if pd.notna(val) else val
        rec.update({
            "_src_file": f"GENERATED_BACKFILL_unilever_sku_{period}",  # no real source file - see report note
            "_src_sheet": "sheet1",
            "_header_row": 11,
            "_row_ordinal": len(records),
            "_principal": "unilever",
            "_region": "la_union",
            "_period": period,
            "_doc_type": "unilever_sku",
            "_sheet_role": "data",
            "_grain": "monthly-sku",
            "_checksum_status": "unverified",
            "_checksum_column": None,
            "_checksum_expected": None,
            "_checksum_got": None,
            "_checksum_diff": None,
            "is_demo": True,
        })
        records.append(rec)
    return pd.DataFrame(records)


def run_unilever_sku_backfill() -> dict:
    real_df = load_real_unilever_sku()
    seasonal = derive_unilever_seasonality(real_df)
    roster = derive_unilever_sku_roster(real_df)

    out_dir = OUT_DIR / "unilever_sku"
    out_dir.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    for period in UNILEVER_BACKFILL_PERIODS:
        df = generate_unilever_sku_period(roster, seasonal, period)
        # match real column order exactly
        real_cols = [CAL_MONTH_COL, PRODUCT_COL, DESC_COL, PACK_SIZE_COL, QTY_CS_COL, QTY_PC_COL, GSV_COL, AMT_COL]
        ordered = real_cols + [c for c in PROVENANCE_COLUMNS if c in df.columns] + ["is_demo"]
        df = df[ordered]
        out_path = out_dir / f"SYNTH__UNILEVER_SKU_{period}.parquet"
        df.to_parquet(out_path, index=False, engine="pyarrow")
        total_rows += len(df)

    return {
        "family": "unilever_sku",
        "periods": len(UNILEVER_BACKFILL_PERIODS),
        "total_rows": total_rows,
        "real_sku_count": len(roster),
        "seasonal_index": seasonal,
    }


# ================================================================
# 2. Del Monte families backfill — 2026-04..2026-08, all 4 families
# ================================================================

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from convert_synthetic_to_staging import (  # noqa: E402
    assign_town_branch, inject_net_amount_duplicates, inject_sell_out_negatives,
)

DELMONTE_BACKFILL_PERIODS = [f"2026-{m:02d}" for m in range(4, 9)]
DELMONTE_TEMPLATE_YEAR_PREFIX = "2025"  # resample pool: all real 2025 rows (most recent full real era)
REGIONS = ["ilocos", "pangasinan"]

FAMILY_BUSINESS_COLS = {
    "sales_register": ["Invoice Date", "Salesman", "Town Display", "Branch Code", "Customer Name",
                        "Invoice Num", "REFNBR", "Untaxed Amount", "Discount Rate", "Discount Amount",
                        "Tax", "Net Amount", "Balance", "Posted", "Return Slip #"],
    "purchase_order": ["Invoice Date", "Salesman", "Town Display", "Branch Code", "Customer Name",
                        "Invoice Num", "REFNBR", "Untaxed Amount", "Discount Rate", "Discount Amount",
                        "Tax", "Net Amount", "Balance", "Posted", "Return Slip #"],
    "sell_out": ["__col0__", "Total Without Tax", "Product Quantity"],
    "inventory_sign_off": ["__col0__", "__col1__", "Quantity", "Cost", "Valuation", "Valuation with VAT",
                            "CAS", "PCS"],
}
# Invoice-numbered families only - regenerated fresh per period/region to
# avoid literal duplicate invoice identifiers across time (everything
# else in the row is a real resampled value).
INVOICE_FAMILIES = {"sales_register", "purchase_order"}


def load_real_family_template(family: str) -> pd.DataFrame:
    files = sorted(REAL_STAGING_DIR.glob(f"{family}/*.parquet"))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    return df[df["_period"].str.startswith(DELMONTE_TEMPLATE_YEAR_PREFIX)]


def real_row_count_pool(family: str, region: str) -> list[int]:
    files = sorted(REAL_STAGING_DIR.glob(f"{family}/*.parquet"))
    counts = []
    for f in files:
        meta = pd.read_parquet(f, columns=["_period", "_region"])
        if meta["_period"].iloc[0].startswith(DELMONTE_TEMPLATE_YEAR_PREFIX) and meta["_region"].iloc[0] == region:
            counts.append(len(meta))
    return counts or [30]


def generate_del_monte_family(family: str) -> dict:
    real_df = load_real_family_template(family)
    business_cols = FAMILY_BUSINESS_COLS[family]
    out_dir = OUT_DIR / family
    out_dir.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    files_written = 0
    for period in DELMONTE_BACKFILL_PERIODS:
        year, month_num = period.split("-")
        for region in REGIONS:
            rng = _seed_for(family, period, region)
            pool = real_df[real_df["_region"] == region]
            if pool.empty:
                continue
            row_counts = real_row_count_pool(family, region)
            n = int(rng.choice(row_counts))
            sample_idx = rng.integers(0, len(pool), size=n)
            rows = pool.iloc[sample_idx][business_cols].reset_index(drop=True).copy()

            if family in INVOICE_FAMILIES:
                # Fresh sequential invoice numbers/dates for this period -
                # everything else in the row (Customer Name, Salesman,
                # amounts, REFNBR) is a real resampled value. Month
                # encoded into the number space (month*1000+i) so numbers
                # stay globally unique per (family, region, year) across
                # ALL 5 backfill months, not just within one file - a
                # per-file-reset counter would let e.g. 2026-04 Ilocos and
                # 2026-05 Ilocos both mint "INV/2026/4000", a real
                # collision on natural_key=[invoice_num, principal,
                # region] (no period component) that dedup_facts()
                # correctly flags as a conflict and excludes from load -
                # caught via the promoted-row count dropping unexpectedly
                # after the first end-to-end Transform run.
                day = 1 + (np.arange(n) % 28)
                rows["Invoice Date"] = pd.to_datetime({"year": int(year), "month": int(month_num), "day": day})
                rows["Invoice Num"] = [f"INV/{year}/{900000 + int(month_num) * 1000 + i}" for i in range(n)]

            # Real Town Display / Branch Code co-occurrence (sales_register/purchase_order)
            if "Town Display" in rows.columns:
                rows = assign_town_branch(rows, region, seed_key=f"{family}_{period}_{region}")
                if family in INVOICE_FAMILIES:
                    rows = _normalize_money_dtype(rows)

            if family == "sell_out" and "Total Without Tax" in rows.columns:
                rows["Total Without Tax"] = rows["Total Without Tax"].apply(_to_money_str)
            if "Product Quantity" in rows.columns:
                rows["Product Quantity"] = pd.to_numeric(rows["Product Quantity"], errors="coerce").astype("float64")

            for col in PROVENANCE_COLUMNS:
                if col == "_src_file":
                    rows[col] = f"GENERATED_BACKFILL_{family}_{period}_{region}"
                elif col == "_src_sheet":
                    rows[col] = f"{region.upper()} {family.upper().replace('_', ' ')}"
                elif col == "_header_row":
                    rows[col] = int(pool["_header_row"].mode().iloc[0]) if "_header_row" in pool.columns else 1
                elif col == "_row_ordinal":
                    rows[col] = np.arange(n)
                elif col == "_principal":
                    rows[col] = "delmonte"
                elif col == "_region":
                    rows[col] = region
                elif col == "_period":
                    rows[col] = period
                elif col == "_doc_type":
                    rows[col] = family
                elif col == "_sheet_role":
                    rows[col] = "data"
                elif col == "_grain":
                    rows[col] = pool["_grain"].mode().iloc[0] if "_grain" in pool.columns and not pool["_grain"].mode().empty else None
                elif col.startswith("_checksum"):
                    rows[col] = None
            rows["is_demo"] = True

            if family == "sell_out":
                rows, n_neg = inject_sell_out_negatives(rows, seed_key=f"{family}_{period}_{region}")
            if family == "sales_register":
                rows, n_dup = inject_net_amount_duplicates(rows, seed_key=f"{family}_{period}_{region}")

            rows = normalize_mixed_dtype_columns(rows, exclude={"Invoice Num", "Return Slip #"})
            out_path = out_dir / f"SYNTH__{family.upper()}_{period}_{region.upper()}.parquet"
            rows.to_parquet(out_path, index=False, engine="pyarrow")
            total_rows += len(rows)
            files_written += 1

    return {"family": family, "files_written": files_written, "total_rows": total_rows}


# ================================================================
# 3. sales_return backfill — same span as the other 4 families
# (2026-04..2026-08). Driver confirmed to exist (analytics/etl/extract/
# sales_return.py, wired into driver.py's FAMILY_PARSERS) - the
# DEL_MONTE_DEMO_DATA_SPEC.md claim of "no driver" is stale. Real 2025
# corpus is GS/BO split (Shape C) - generate both roles per period/
# region, matching real structure. Note: source_of_truth.yaml still has
# no fact entry for doc_type=sales_return (B5 gap, deferred earlier this
# session) - these rows will currently classify "demoted" at Transform,
# same as real sales_return rows do today. Generated anyway per
# instruction (Extract-level staging is real and driver-backed); not a
# wasted-work case in the sense the instruction worried about.
# ================================================================

SALES_RETURN_BUSINESS_COLS = [
    "Invoice Date", "Salesman", "Town Display", "Branch Code", "Customer Name",
    "Invoice Num", "REFNBR", "Untaxed Amount", "Discount Rate", "Discount Amount",
    "Tax", "Net Amount", "Balance", "Posted", "Return Slip #", "Return Type",
]

_MONEY_COLS_TO_NORMALIZE = ["Untaxed Amount", "Discount Amount", "Tax", "Net Amount", "Balance"]


def _to_money_str(v):
    if pd.isna(v):
        return None
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        # Real data artifact: a repeated/merged header row occasionally
        # lands as a literal data value (e.g. the literal string
        # "Untaxed Amount" in a real row) - same class of real corruption
        # found earlier this session (inventory Shape B's literal "SKU"/
        # "DESCRIPTION" data row). Not a number to coerce; drop to null
        # rather than crash or fabricate a value.
        return None


def _normalize_money_dtype(rows: pd.DataFrame) -> pd.DataFrame:
    """Real sales_return/rmr_gs_bo data genuinely mixes decimal.Decimal
    and str within the same money column across different real files/
    periods (confirmed: staging/sales_return's Untaxed Amount is
    407 Decimal / 209 str / 19 None in the 2025 pool alone) - resampling
    rows at random naturally inherits that real mix, but a Parquet
    column can't be mixed-type. Normalizes to str (lossless from
    Decimal, matches the more common convention across this project's
    other money columns) rather than picking one row's type arbitrarily."""
    out = rows.copy()
    for col in _MONEY_COLS_TO_NORMALIZE:
        if col in out.columns:
            out[col] = out[col].apply(_to_money_str)
    return out


def generate_sales_return() -> dict:
    files = sorted(REAL_STAGING_DIR.glob("sales_return/*.parquet"))
    real_df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    real_2025 = real_df[real_df["_period"].str.startswith("2025")]

    out_dir = OUT_DIR / "sales_return"
    out_dir.mkdir(parents=True, exist_ok=True)
    total_rows = 0
    files_written = 0

    for period in DELMONTE_BACKFILL_PERIODS:
        year, month_num = period.split("-")
        for region in REGIONS:
            for role in ("gs", "bo"):
                rng = _seed_for("sales_return", period, region, role)
                pool = real_2025[(real_2025["_region"] == region) & (real_2025["_sheet_role"] == role)]
                if pool.empty:
                    continue
                row_count_pool = real_2025[(real_2025["_region"] == region) & (real_2025["_sheet_role"] == role)].groupby("_src_file").size().tolist() or [10]
                n = int(rng.choice(row_count_pool))
                sample_idx = rng.integers(0, len(pool), size=n)
                rows = pool.iloc[sample_idx][SALES_RETURN_BUSINESS_COLS].reset_index(drop=True).copy()

                day = 1 + (np.arange(n) % 28)
                rows["Invoice Date"] = pd.to_datetime({"year": int(year), "month": int(month_num), "day": day})
                rows["Invoice Num"] = [f"INV/{year}/{900000 + int(month_num) * 1000 + i}" for i in range(n)]
                # natural_key for sales_return is [return_slip_num, principal,
                # region, return_type] - NOT invoice_num. Return Slip # must
                # be regenerated fresh per period for the same reason Invoice
                # Num is above: resampling real historical values directly
                # here (as SALES_RETURN_BUSINESS_COLS did) would let the same
                # real return_slip_num appear in multiple generated months
                # for the same region/return_type, a real collision.
                rows["Return Slip #"] = [f"RS/{year}/{900000 + int(month_num) * 1000 + i}" for i in range(n)]

                rows = assign_town_branch(rows, region, seed_key=f"sales_return_{period}_{region}_{role}")
                rows = _normalize_money_dtype(rows)

                rows["_src_file"] = f"GENERATED_BACKFILL_sales_return_{period}_{region}_{role}"
                rows["_src_sheet"] = f"{region.upper()} {role.upper()}"
                rows["_header_row"] = int(pool["_header_row"].mode().iloc[0])
                rows["_row_ordinal"] = np.arange(n)
                rows["_principal"] = "delmonte"
                rows["_region"] = region
                rows["_period"] = period
                rows["_doc_type"] = "sales_return"
                rows["_sheet_role"] = role
                rows["_grain"] = "invoice"
                for c in ["_checksum_status", "_checksum_column", "_checksum_expected", "_checksum_got", "_checksum_diff"]:
                    rows[c] = None
                rows["is_demo"] = True

                rows = normalize_mixed_dtype_columns(rows, exclude={"Invoice Num", "Return Slip #"})
                out_path = out_dir / f"SYNTH__SALES_RETURN_{period}_{region.upper()}_{role.upper()}.parquet"
                rows.to_parquet(out_path, index=False, engine="pyarrow")
                total_rows += len(rows)
                files_written += 1

    return {"family": "sales_return", "files_written": files_written, "total_rows": total_rows}


# ================================================================
# 4. rmr_gs_bo backfill — 2025-12..2026-08 only (real convention starts
# Oct 2025; backfilling before Oct 2025 would invent a file convention
# that didn't exist at SSM yet, per instruction). Real coverage is
# Oct-Nov 2025 - generate Dec 2025 through Aug 2026 (9 months).
# Value-based only - bo_units has no source column anywhere in this
# family, never populated (matches real: schema.sql's SalesReturn_Fact.
# bo_units comment - "always NULL for real data ... no source column
# exists").
# ================================================================

RMR_GS_BO_BACKFILL_PERIODS = ["2025-12"] + [f"2026-{m:02d}" for m in range(1, 9)]
RMR_GS_BO_BUSINESS_COLS = [
    "Invoice Date", "Salesman", "Town Display", "Customer Name", "Untaxed Amount",
    "Discount Amount", "Tax", "Net Amount", "Balance", "Return Slip #", "Return Type",
]


def generate_rmr_gs_bo() -> dict:
    files = sorted(REAL_STAGING_DIR.glob("rmr_gs_bo/*.parquet"))
    real_df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)  # real Oct-Nov 2025 only

    out_dir = OUT_DIR / "rmr_gs_bo"
    out_dir.mkdir(parents=True, exist_ok=True)
    total_rows = 0
    files_written = 0

    for period in RMR_GS_BO_BACKFILL_PERIODS:
        year, month_num = period.split("-")
        for region in REGIONS:
            for role in ("gs", "bo"):
                rng = _seed_for("rmr_gs_bo", period, region, role)
                pool = real_df[(real_df["_region"] == region) & (real_df["_sheet_role"] == role)]
                if pool.empty:
                    continue
                avail_cols = [c for c in RMR_GS_BO_BUSINESS_COLS if c in pool.columns]
                row_count_pool = pool.groupby("_src_file").size().tolist() or [15]
                n = int(rng.choice(row_count_pool))
                sample_idx = rng.integers(0, len(pool), size=n)
                rows = pool.iloc[sample_idx][avail_cols].reset_index(drop=True).copy()

                day = 1 + (np.arange(n) % 28)
                rows["Invoice Date"] = pd.to_datetime({"year": int(year), "month": int(month_num), "day": day})
                rows = _normalize_money_dtype(rows)

                rows["_src_file"] = f"GENERATED_BACKFILL_rmr_gs_bo_{period}_{region}_{role}"
                rows["_src_sheet"] = f"{region.upper()} {role.upper()}"
                rows["_header_row"] = int(pool["_header_row"].mode().iloc[0])
                rows["_row_ordinal"] = np.arange(n)
                rows["_principal"] = "delmonte"
                rows["_region"] = region
                rows["_period"] = period
                rows["_doc_type"] = "rmr_gs_bo"
                rows["_sheet_role"] = role
                rows["_grain"] = "invoice"
                for c in ["_checksum_status", "_checksum_column", "_checksum_expected", "_checksum_got", "_checksum_diff"]:
                    rows[c] = None
                rows["is_demo"] = True
                # bo_units: never populated, real data has no source column for it either
                # (nothing to set - not a mapped raw column in this family at all).

                rows = normalize_mixed_dtype_columns(rows)
                out_path = out_dir / f"SYNTH__RMR_GS_BO_{period}_{region.upper()}_{role.upper()}.parquet"
                rows.to_parquet(out_path, index=False, engine="pyarrow")
                total_rows += len(rows)
                files_written += 1

    return {"family": "rmr_gs_bo", "files_written": files_written, "total_rows": total_rows}


if __name__ == "__main__":
    result = run_unilever_sku_backfill()
    print(result)
    print()
    for fam in ["sales_register", "purchase_order", "sell_out", "inventory_sign_off"]:
        print(generate_del_monte_family(fam))
    print(generate_sales_return())
    print(generate_rmr_gs_bo())
