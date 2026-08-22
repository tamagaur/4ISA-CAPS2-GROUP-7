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


# ================================================================
# 5. Del Monte fine-grained sell_out bridge (2025-01..2026-08) — closes
# the "no category spans past 2024-12" gap (reports/COMPLETENESS_DISCOVERY.md
# §A/§E). The 42 fine-grained categories with full 48-month continuity
# (2021-01..2024-12, verified fresh against live sellout_fact before
# writing this list) never recur in real data after 2024-12 — real Del
# Monte sell_out switches to a disjoint 5-category coarse vocabulary
# starting 2025-01 (confirmed, not guessed — §A2/§A4 of that report).
# Those coarse 2025+ rows are real and untouched by this function; it
# ADDS a second, coexisting vocabulary for the same months. One row per
# (category, region, period), matching sellout_fact's own natural key
# (UNIQUE(category_path, region, _period)) — no conflict with the coarse
# rows, which use entirely different category_path strings.
#
# Unlike generate_del_monte_family()'s per-invoice resampling, sell_out
# is one-row-per-(category,region,period) at its natural key, so this
# generates exactly one target value per combination — derived from each
# (category, region)'s OWN 48-month trend + seasonality + residual noise,
# never a global average or a flat extrapolation of the 2024 mean
# (explicit instruction). sell_out's schema is minimal (no invoice-level
# fields like Town Display/Salesman to preserve realism for), so no
# literal row-template resampling step is needed the way sales_register/
# purchase_order require it — every generated number is grounded in that
# category's own real 2021-2024 history (which is itself built from the
# real 2023-2024 months plus Thea's original 2021-2022/era-filling
# synthetic months, the same 48-month corpus the roster itself is
# defined against), not invented or drawn from an unrelated pool.
# ================================================================

FINEGRAINED_BRIDGE_PERIODS = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 9)]

FINEGRAINED_BRIDGE_HISTORY_MONTHS = (
    [f"2021-{m:02d}" for m in range(1, 13)] + [f"2022-{m:02d}" for m in range(1, 13)]
    + [f"2023-{m:02d}" for m in range(1, 13)] + [f"2024-{m:02d}" for m in range(1, 13)]
)

# The 42 categories confirmed continuous 2021-01..2024-12 in live
# sellout_fact this session (reports/COMPLETENESS_DISCOVERY.md §A1) —
# excludes the 9 "False"/"False (n)" artifacts and the 5 coarse names,
# neither of which is part of this 48-month-continuous set anyway.
FINEGRAINED_BRIDGE_ROSTER = [
    "/TIDBITS/BASE", "/ORIGINAL TOMATO SAUCE/BASE", "/TOTAL 100% JUICES/ACE - BASE REGULAR",
    "/SWEET SPAG SAUCE/PROMO", "/TODAY'S/BASE", "/TOM PASTE/BASE", "/ACE/BASE",
    "/KETCHUPS/OTHER SAUCES - BASE", "/TOM SAUCE/ORIGINAL TOMATO SAUCE - BASE REGULAR",
    "/CRUSHED/BASE", "/ORIGINAL BLEND/BASE", "/CHUNKS/BASE", "/SLICED/BASE", "/TETRA/BASE",
    "/OTHER SAUCES/NPI", "/TOTAL 100% JUICES/FIBER - BASE REGULAR",
    "/TOTAL 100% JUICES/HEARTSMART - BASE REGULAR", "/STANDARD GRADE SOY SOUCE/BASE",
    "/MACARONI/BASE", "/GRO/FS/DAIRY", "/SPAG SAUCE/FILIPINO SPAG SAUCE - BASE",
    "/FILIPINO TOMATO SAUCE/BASE", "/FILIPINO SPAG SAUCE/PROMO",
    "/TOM SAUCE/FILIPINO TOMATO SAUCE - BASE REGULAR", "/RECIPE MIX/BASE", "/ACE/NPI",
    "/FIESTA/BASE", "/PASTA/SPAGHETTI PASTA - BASE", "/SPAG SAUCE/ITALIAN SPAG SAUCE - BASE REGULAR",
    "/FIBER/NPI", "/VINEGAR/BASE", "/MR MILK/NPI", "/HEARTSMART/NPI", "/SWEET SPAG SAUCE/BASE",
    "/SPAG SAUCE/GOURMET SPAG SAUCE - BASE REGULAR", "/FILIPINO SPAG SAUCE/BASE", "/TIPCO/BASE",
    "/TERIYAKI MARINADE/BASE", "/SWEET BLEND/BASE", "/SWEET SPICY/BASE", "/CHUNKS/NPI",
    "/TOTAL 100% JUICES/BONESMART - BASE REGULAR",
]

# real 2.1442% (33/1,539 non-"Total" rows) — the figure this project has
# actually measured and documented (reports/SYNTHETIC_STAGING_CONVERSION.md
# §3b), reused as-is via inject_sell_out_negatives(). The instruction
# citing "2.0979%" doesn't match anything measured in this repo; using
# the documented, already-tested real rate rather than a figure that
# doesn't trace to a source, flagged here rather than silently chasing it.
#
# The instruction's "Net Amount duplicate clustering (52.53%)" is a
# different family's metric — that 52.5316% figure (and
# inject_net_amount_duplicates()'s real pool) is measured specifically
# from staging/sales_register/*.parquet's "Net Amount" column
# (reports/SYNTHETIC_STAGING_CONVERSION.md §3c) and has never been
# measured for sell_out's money field ("Total Without Tax"/"Total With
# Tax" — real files use both column names across eras). Applying
# sales_register's real pool/rate to sell_out would inject invoice-scale
# values into a category-aggregate field — not a preservation of a real
# pattern, an error. Measured sell_out's OWN real duplicate rate instead
# (live sellout_fact, is_demo=false, clean category_path): 153/1,345 =
# 11.3755%. Used that instead, via a sell_out-specific pool/injector
# below — flagged as a substitution, not silently applied as if 52.53%
# were correct for this family.
SELLOUT_OWN_DUP_RATE = 153 / 1345  # 11.3755%, measured live this session — see note above
SELLOUT_DUP_RESAMPLE_FRACTION = 0.11  # not micro-calibrated, same "not tuned further" precedent as NET_AMOUNT_RESAMPLE_FRACTION


def _sell_out_amount_column(df: pd.DataFrame) -> pd.Series:
    """Real sell_out files use either 'Total Without Tax' or 'Total With
    Tax' depending on era (both seen directly in staging/sell_out/*.parquet
    this session) - coalesce whichever is present into one numeric Series,
    never assuming a single real column name."""
    if "Total Without Tax" in df.columns:
        return pd.to_numeric(df["Total Without Tax"], errors="coerce")
    if "Total With Tax" in df.columns:
        return pd.to_numeric(df["Total With Tax"], errors="coerce")
    return pd.Series([pd.NA] * len(df), index=df.index)


_SELLOUT_DUP_POOL_CACHE: list | None = None


def _derive_sellout_dup_pool() -> list:
    """Real sell_out amount pool for the duplicate-clustering injection -
    every non-null value from real (data/raw/Del Monte-sourced) staged
    rows, natural frequency preserved, same resampling-not-fabricating
    design as derive_net_amount_pool()."""
    global _SELLOUT_DUP_POOL_CACHE
    if _SELLOUT_DUP_POOL_CACHE is not None:
        return _SELLOUT_DUP_POOL_CACHE
    files = sorted(REAL_STAGING_DIR.glob("sell_out/*.parquet"))
    pool = []
    for f in files:
        df = pd.read_parquet(f)
        if not df["_src_file"].iloc[0].startswith("data/raw/Del Monte"):
            continue
        pool.extend(_sell_out_amount_column(df).dropna().tolist())
    _SELLOUT_DUP_POOL_CACHE = pool
    return pool


def inject_sellout_amount_duplicates(df: pd.DataFrame, seed_key: str) -> tuple[pd.DataFrame, int]:
    """sell_out-specific analog of inject_net_amount_duplicates() (that
    function's real pool/rate is sales_register-specific — see the
    module-level note above). Overwrites SELLOUT_DUP_RESAMPLE_FRACTION of
    rows' 'Total Without Tax' with values drawn (with replacement) from
    the real sell_out pool. Row count unchanged."""
    pool = _derive_sellout_dup_pool()
    if not pool:
        return df, 0
    out = df.copy()
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    n_replace = int(round(len(out) * SELLOUT_DUP_RESAMPLE_FRACTION))
    if n_replace == 0:
        return out, 0
    replace_idx = rng.choice(out.index, size=n_replace, replace=False)
    replacement_vals = rng.choice(pool, size=n_replace)
    out.loc[replace_idx, "Total Without Tax"] = [f"{v:.2f}" for v in replacement_vals]
    return out, n_replace


def _fit_trend_seasonality(series_by_period: dict, months: list) -> dict:
    """OLS trend (degree-1 polyfit) + multiplicative month-of-year
    seasonal index + residual std, derived from THIS category/region's
    own history only — no global average (explicit instruction). Gaps
    (a month this category+region genuinely has no row for) are skipped,
    not zero-filled, so a real absence doesn't drag the fit toward zero."""
    idx = [i for i, m in enumerate(months) if m in series_by_period]
    if len(idx) < 6:
        vals = list(series_by_period.values())
        mean_val = float(np.mean(vals)) if vals else 0.0
        return {"slope": 0.0, "intercept": mean_val, "seasonal": {m: 1.0 for m in range(1, 13)}, "resid_std": 0.0}

    y = np.array([series_by_period[months[i]] for i in idx], dtype=float)
    x = np.array(idx, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    trend_pred = slope * x + intercept

    cal_month = np.array([int(months[i].split("-")[1]) for i in idx])
    seasonal = {}
    detrended = np.divide(y, trend_pred, out=np.ones_like(y), where=trend_pred != 0)
    for cm in range(1, 13):
        mask = cal_month == cm
        seasonal[cm] = float(np.mean(detrended[mask])) if mask.any() else 1.0
    seasonal_mean = np.mean(list(seasonal.values()))
    if seasonal_mean > 0:
        seasonal = {k: v / seasonal_mean for k, v in seasonal.items()}

    seasonal_pred = trend_pred * np.array([seasonal[cm] for cm in cal_month])
    resid_std = float(np.std(y - seasonal_pred))
    return {"slope": float(slope), "intercept": float(intercept), "seasonal": seasonal, "resid_std": resid_std}


def _load_sell_out_full_history() -> pd.DataFrame:
    """Every staged sell_out row (real + Thea's original synthetic +
    this session's earlier 2026-04..08 backfill) - category/region/period
    plus both numeric fields as float, amount column coalesced per
    _sell_out_amount_column(). Source for each category's OWN 48-month
    trend/seasonality/variance - deliberately the full corpus, not the
    real-only subset, matching how the 42-category roster itself was
    defined (48-month continuity across real+Thea-synthetic combined)."""
    files = sorted(REAL_STAGING_DIR.glob("sell_out/*.parquet"))
    frames = []
    for f in files:
        df = pd.read_parquet(f)
        amount = _sell_out_amount_column(df)
        frames.append(pd.DataFrame({
            "category": df["__col0__"].astype(str).str.strip(),
            "region": df["_region"],
            "period": df["_period"],
            "amount": amount,
            "quantity": pd.to_numeric(df["Product Quantity"], errors="coerce"),
        }))
    return pd.concat(frames, ignore_index=True)


def generate_delmonte_finegrained_bridge() -> dict:
    full_history = _load_sell_out_full_history()

    out_dir = OUT_DIR / "sell_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    fits: dict = {}
    for cat in FINEGRAINED_BRIDGE_ROSTER:
        for region in REGIONS:
            sub = full_history[(full_history["category"] == cat) & (full_history["region"] == region)]
            amt_by_period = sub.groupby("period")["amount"].sum().to_dict()
            qty_by_period = sub.groupby("period")["quantity"].sum().to_dict()
            fits[(cat, region)] = {
                "amt": _fit_trend_seasonality(amt_by_period, FINEGRAINED_BRIDGE_HISTORY_MONTHS),
                "qty": _fit_trend_seasonality(qty_by_period, FINEGRAINED_BRIDGE_HISTORY_MONTHS),
            }

    total_rows = 0
    files_written = 0
    total_neg = 0
    total_dup = 0
    for period_offset, period in enumerate(FINEGRAINED_BRIDGE_PERIODS):
        month_index = 48 + period_offset  # continues the 0..47 history index
        cal_month = int(period.split("-")[1])
        for region in REGIONS:
            rng = _seed_for("finegrained_bridge", period, region)
            records = []
            for cat in FINEGRAINED_BRIDGE_ROSTER:
                amt_fit = fits[(cat, region)]["amt"]
                qty_fit = fits[(cat, region)]["qty"]

                amt_trend = amt_fit["slope"] * month_index + amt_fit["intercept"]
                amt_target = amt_trend * amt_fit["seasonal"].get(cal_month, 1.0)
                if amt_fit["resid_std"] > 0:
                    amt_target += rng.normal(0, amt_fit["resid_std"])
                # Revenue never goes negative in the established real
                # convention - only Product Quantity does (see
                # REAL_SELL_OUT_NEGATIVE_VALUES / inject_sell_out_negatives()
                # above, which only ever touches Product Quantity). Clip
                # here so trend+noise can't organically manufacture a
                # negative-revenue phenomenon that has no real precedent.
                amt_target = max(0.0, amt_target)

                qty_trend = qty_fit["slope"] * month_index + qty_fit["intercept"]
                qty_target = qty_trend * qty_fit["seasonal"].get(cal_month, 1.0)
                if qty_fit["resid_std"] > 0:
                    qty_target += rng.normal(0, qty_fit["resid_std"])
                # Clip to non-negative for the same reason - negative
                # quantity is a real, but rare (2.14%), phenomenon
                # introduced ONLY by inject_sell_out_negatives() below at
                # its calibrated real rate, never by uncontrolled noise.
                qty_target = max(0.0, qty_target)

                records.append({"__col0__": cat, "Total Without Tax": f"{amt_target:.2f}", "Product Quantity": float(qty_target)})

            rows = pd.DataFrame(records)
            n = len(rows)

            for col in PROVENANCE_COLUMNS:
                if col == "_src_file":
                    rows[col] = f"GENERATED_BACKFILL_finegrained_bridge_{period}_{region}"
                elif col == "_src_sheet":
                    rows[col] = f"{region.upper()} SELL OUT FINEGRAINED BRIDGE"
                elif col == "_header_row":
                    rows[col] = 1
                elif col == "_row_ordinal":
                    rows[col] = np.arange(n)
                elif col == "_principal":
                    rows[col] = "delmonte"
                elif col == "_region":
                    rows[col] = region
                elif col == "_period":
                    rows[col] = period
                elif col == "_doc_type":
                    rows[col] = "sell_out"
                elif col == "_sheet_role":
                    rows[col] = "data"
                elif col == "_grain":
                    rows[col] = "category"
                elif col.startswith("_checksum"):
                    rows[col] = None
            rows["is_demo"] = True

            rows, n_neg = inject_sell_out_negatives(rows, seed_key=f"finegrained_bridge_{period}_{region}")
            rows, n_dup = inject_sellout_amount_duplicates(rows, seed_key=f"finegrained_bridge_{period}_{region}")
            total_neg += n_neg
            total_dup += n_dup

            rows["Product Quantity"] = pd.to_numeric(rows["Product Quantity"], errors="coerce").astype("float64")
            rows = normalize_mixed_dtype_columns(rows)
            out_path = out_dir / f"SYNTH__SELL_OUT_FINEGRAINED_BRIDGE_{period}_{region.upper()}.parquet"
            rows.to_parquet(out_path, index=False, engine="pyarrow")
            total_rows += len(rows)
            files_written += 1

    return {
        "family": "sell_out_finegrained_bridge", "files_written": files_written, "total_rows": total_rows,
        "categories": len(FINEGRAINED_BRIDGE_ROSTER), "negative_injected": total_neg, "dup_injected": total_dup,
    }


if __name__ == "__main__":
    result = run_unilever_sku_backfill()
    print(result)
    print()
    for fam in ["sales_register", "purchase_order", "sell_out", "inventory_sign_off"]:
        print(generate_del_monte_family(fam))
    print(generate_sales_return())
    print(generate_rmr_gs_bo())
    print(generate_delmonte_finegrained_bridge())
