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

Usage: python scripts/generate_synthetic_backfill.py [--dry-run] [--unilever-only] [--seasonal-residuals]
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
from analytics.params import DEAD_SKU_MONTHS  # noqa: E402

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
# 1. unilever_sku backfill v2 — 2021-01..2022-12, 2026-03..2026-08
# ================================================================
#
# PURPOSE (locked 2026-09-21): these rows are a PLACEHOLDER for 2021-22 data
# SSM has not delivered. v2 exists for existence-correctness only: v1 gave a
# SKU rows in every backfill month at its all-time presence rate, so 695 SKUs
# whose first real row is in 2024 or later carried 4,408 invented pre-2023
# rows. Nothing here is tuned against a forecast metric, and no synthetic
# value is ever adjusted to improve one. Success means: (a) the files can be
# replaced by real 2021-22 files with no code change (same names, columns and
# dtypes as v1, which the loader already reads), (b) every row is
# is_demo=true, (c) nothing reading a _Real view can see any of it.
#
# EXISTENCE comes from the 2021-22 SSIS SOH sheets, used ONLY as a witness
# that a SKU was listed (data/processed/soh_witness_2021_2022.parquet, built
# by scripts/profile_soh_witness.py; period = the FILE's period). Stock
# quantities are never read, and absence from a sheet is not evidence that a
# SKU did not exist - it only means there is no witness to justify a row.
#
# VALUE = anchor x residual, both from the SKU's own real history:
#   anchor    median of its first 3 positive real months (its level at debut;
#             no launch ramp - the measured ramp's IQR straddled 1.0 at every
#             month since debut)
#   residual  a real month divided by that SKU's own local median (the
#             window from 6 months before to 5 months after, needing 6+
#             positive months) - i.e. how far a month sits from the SKU's
#             level at the time. A SKU with fewer than 6 residuals gets no
#             synthetic rows: there is not enough of its own history to draw
#             from, and borrowing another SKU's would be inventing it.

UNILEVER_BACKFILL_PERIODS = (
    [f"2021-{m:02d}" for m in range(1, 13)]
    + [f"2022-{m:02d}" for m in range(1, 13)]
    + [f"2026-{m:02d}" for m in range(3, 9)]
)
PRE_REAL_END = "2022-12"
FIRST_REAL_PERIOD = "2023-01"
WITNESS_PATH = REPO_ROOT / "data" / "processed" / "soh_witness_2021_2022.parquet"

MIN_RESIDUALS = 6                 # D6
RESIDUAL_WINDOW = (-6, 5)         # months around a month that define its local median
ANCHOR_MONTHS = 3                 # D2
ANCHOR_FALLBACK_WINDOW = 6        # D2 fallback: positive months within the first 6 from debut
POOL_TRIM = (5, 95)               # percentiles; one untrimmed residual reached 86.4
# analytics.params. Its tail-sum predicate below mirrors the runner's rule as
# it was when the live synthetic v2 was generated; left as is so a rerun
# reproduces that data (the runner now uses fsn.no_sale_in_last_months).
DEAD_TAIL_MONTHS = DEAD_SKU_MONTHS

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
    """Every REAL staged unilever_sku row. staging/unilever_sku/ also holds
    materialised copies of this script's own SYNTH__ output (the canonical
    load reads them from there), so rows flagged is_demo are dropped - without
    that, a re-run would profile its own previous output as if it were real."""
    frames = []
    for f in sorted(REAL_STAGING_DIR.glob("unilever_sku/*.parquet")):
        df = pd.read_parquet(f)
        if "is_demo" in df.columns:
            df = df[~df["is_demo"].fillna(False).astype(bool)]
        if len(df):
            frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _months(start: str, end: str) -> list[str]:
    return [str(p) for p in pd.period_range(start, end, freq="M")] if start <= end else []


def load_witness(path: Path = WITNESS_PATH) -> tuple[pd.DataFrame, dict]:
    """(sku, period) existence pairs, plus how much adjacent files overlap.

    Every file counts as a genuine snapshot of its own period, including
    2021-07, whose SOH sheet is labelled "SOH(JUNE 30, 2021)". A rule that
    discarded July as a duplicate of June (93.5% of its articles are also in
    June) was tried and withdrawn 2026-09-21: adjacent months share a median
    95.1% of their articles (16 of 17 pairs at 85% or more, 12 of 17 at
    93.5% or more), and July's stock values match June's for 24.2% of shared
    articles against a median 23.5% - an ordinary consecutive month, not a
    copy. The overlap summary is returned so a dry run shows it."""
    w = pd.read_parquet(path)[["sku", "period"]].astype(str).drop_duplicates()
    periods = sorted(w.period.unique())
    by_period = {p: set(w.loc[w.period == p, "sku"]) for p in periods}
    adjacent = [len(by_period[a] & by_period[b]) / len(by_period[b]) for a, b in zip(periods, periods[1:])
                if (pd.Period(b, freq="M") - pd.Period(a, freq="M")).n == 1]
    report = {"files": len(periods), "adjacent_pairs": len(adjacent),
              "adjacent_overlap_median": round(float(np.median(adjacent)), 4) if adjacent else None,
              "adjacent_overlap_min": round(float(min(adjacent)), 4) if adjacent else None, "files_discarded": 0}
    return w.reset_index(drop=True), report


def _residuals(months: list[str], qty: np.ndarray) -> list[tuple[str, float]]:
    """(month, q / local median) for each positive month whose window holds 6+ positive months."""
    idx = pd.PeriodIndex(months, freq="M")
    pos = qty > 0
    out = []
    for i in np.nonzero(pos)[0]:
        lo, hi = idx[i] + RESIDUAL_WINDOW[0], idx[i] + RESIDUAL_WINDOW[1]
        window = qty[pos & (idx >= lo) & (idx <= hi)]
        if len(window) >= MIN_RESIDUALS:
            out.append((months[i], float(qty[i] / np.median(window))))
    return out


def derive_sku_profile(real_df: pd.DataFrame, witness: pd.DataFrame) -> dict:
    """Everything generation needs, per real SKU, from that SKU's own real
    rows plus the existence witness. No value here comes from another SKU."""
    df = real_df.copy()
    df["_q"] = pd.to_numeric(df[QTY_PC_COL], errors="coerce")
    last_real = df["_period"].max()
    w = witness.groupby("sku").period.agg(["min", "max"])
    last_witness = witness.period.max()

    profile = {}
    for sku, g0 in df.groupby(PRODUCT_COL):
        g = g0.dropna(subset=["_q"]).sort_values("_period")
        by_month = g.groupby("_period")["_q"].sum()
        months, qty = list(by_month.index), by_month.to_numpy(dtype=float)
        pos_months = [m for m, q in zip(months, qty) if q > 0]
        desc, pack = g0[DESC_COL].mode(), g0[PACK_SIZE_COL].mode()
        p = {
            "description": desc.iloc[0] if not desc.empty else None, "pack_size": pack.iloc[0] if not pack.empty else None,
            "witness_first": w.loc[sku, "min"] if sku in w.index else None, "witness_last": w.loc[sku, "max"] if sku in w.index else None,
            "debut": pos_months[0] if pos_months else None, "last_row": months[-1] if months else None,
            "returns_dominated": bool(qty.sum() <= 0), "anchor": None, "anchor_rung": "none",
        }
        # D2 anchor ladder
        pos_q = [q for q in qty if q > 0]
        if len(pos_q) >= ANCHOR_MONTHS:
            p["anchor"], p["anchor_rung"] = float(np.median(pos_q[:ANCHOR_MONTHS])), "first_3_positive"
        elif pos_months:
            horizon = str(pd.Period(p["debut"], freq="M") + (ANCHOR_FALLBACK_WINDOW - 1))
            early = [q for m, q in zip(months, qty) if q > 0 and m <= horizon]
            if early:
                p["anchor"], p["anchor_rung"] = float(np.median(early)), "positives_in_first_6"

        res = _residuals(months, qty)
        p["n_residuals"] = len(res)
        if res:
            vals = np.array([r for _, r in res])
            lo, hi = np.percentile(vals, POOL_TRIM)
            p["pool"] = [(m, r) for m, r in res if lo <= r <= hi]
        else:
            p["pool"] = []

        # active window = debut .. last real row; months inside it are positive, negative or absent
        if p["debut"]:
            span = len(_months(p["debut"], p["last_row"]))
            in_win = [(m, q) for m, q in zip(months, qty) if m >= p["debut"]]
            p["presence_rate"] = sum(q > 0 for _, q in in_win) / span
            p["negative_rate"] = sum(q < 0 for _, q in in_win) / span
        else:
            p["presence_rate"] = p["negative_rate"] = 0.0
        p["negative_values"] = [float(q) for q in qty if q < 0]
        p["min_positive"], p["max_qty"] = (float(min(pos_q)), float(max(pos_q))) if pos_q else (None, None)

        # dead = scripts/run_baseline_forecast.py:309-318's rule (no positive sum in the last 6 months), evaluated on the
        # series zero-filled THROUGH the last real month. The runner's own series stops at the SKU's last row, so there a
        # SKU that simply stopped appearing never reads as dead; for a forward placeholder that would invent a live SKU.
        full = pd.Series(0.0, index=_months(months[0], last_real)) if months else pd.Series(dtype=float)
        for m, q in zip(months, qty):
            full[m] = q
        p["dead"] = bool(len(full) >= DEAD_TAIL_MONTHS and full.iloc[-DEAD_TAIL_MONTHS:].sum() <= 0) or not months
        own = full.loc[:months[-1]] if months else full            # what the runner's build_series() sees
        p["dead_by_runner_series"] = bool(len(own) >= DEAD_TAIL_MONTHS and own.iloc[-DEAD_TAIL_MONTHS:].sum() <= 0)

        per_piece = g[g["_q"] > 0]
        for key, col in (("cs_per_pc", QTY_CS_COL), ("gsv_per_pc", GSV_COL), ("amt_per_pc", AMT_COL)):
            ratio = (pd.to_numeric(per_piece[col], errors="coerce") / per_piece["_q"]).replace([np.inf, -np.inf], np.nan).dropna()
            p[key] = float(ratio.median()) if len(ratio) else None

        # existence window before the real era
        p["pre_window"] = []
        if p["witness_first"] is not None:
            relisted_after_gap = p["witness_last"] < last_witness and (p["debut"] is None or p["debut"] > FIRST_REAL_PERIOD)
            end = p["witness_last"] if relisted_after_gap else PRE_REAL_END     # gone-then-relisted: stop, no bridging
            p["pre_window"] = _months(p["witness_first"], min(end, PRE_REAL_END))

        if p["returns_dominated"]:
            p["excluded"] = "returns_dominated"
        elif p["anchor"] is None:
            p["excluded"] = "no_anchor"
        elif p["n_residuals"] < MIN_RESIDUALS or not p["pool"]:
            p["excluded"] = "fewer_than_6_residuals"
        else:
            p["excluded"] = None
        profile[sku] = p
    return profile


def generate_sku_series(sku: str, p: dict, seasonal_residuals: bool = False) -> list[dict]:
    """Synthetic rows for one SKU: its witnessed pre-2023 months, plus 2026-03..08 if it is not dead.
    Each (sku, month) has its own seeded generator, so a row never depends on which other rows exist."""
    if p["excluded"]:
        return []
    forward = [] if p["dead"] else [m for m in UNILEVER_BACKFILL_PERIODS if m > PRE_REAL_END]
    rows = []
    for period in p["pre_window"] + forward:
        rng = _seed_for("unilever_sku_v2", sku, period)
        u = rng.random()
        if u < p["presence_rate"]:
            pool = p["pool"]
            if seasonal_residuals:
                same_month = [x for x in pool if x[0][5:7] == period[5:7]]
                pool = same_month if len(same_month) >= 2 else pool
            residual = pool[int(rng.integers(0, len(pool)))][1]
            qty = float(np.clip(round(p["anchor"] * residual), p["min_positive"], p["max_qty"]))
        elif p["negative_values"] and u < p["presence_rate"] + p["negative_rate"]:
            qty = p["negative_values"][int(rng.integers(0, len(p["negative_values"])))]
        else:
            continue
        year, month_num = period.split("-")
        rows.append({
            CAL_MONTH_COL: f"{month_num}.{year}", PRODUCT_COL: sku, DESC_COL: p["description"], PACK_SIZE_COL: p["pack_size"],
            QTY_CS_COL: None if p["cs_per_pc"] is None else round(qty * p["cs_per_pc"], 3), QTY_PC_COL: qty,
            GSV_COL: None if p["gsv_per_pc"] is None else round(qty * p["gsv_per_pc"], 2),
            AMT_COL: None if p["amt_per_pc"] is None else round(qty * p["amt_per_pc"], 2),
            "_src_file": f"GENERATED_BACKFILL_unilever_sku_{period}",  # no real source file
            "_src_sheet": "sheet1", "_header_row": 11, "_row_ordinal": 0, "_principal": "unilever", "_region": "la_union",
            "_period": period, "_doc_type": "unilever_sku", "_sheet_role": "data", "_grain": "monthly-sku",
            "_checksum_status": "unverified", "_checksum_column": None, "_checksum_expected": None,
            "_checksum_got": None, "_checksum_diff": None, "is_demo": True,
        })
    return rows


def plan_unilever_sku_backfill(profile: dict, seasonal_residuals: bool = False) -> tuple[pd.DataFrame, dict]:
    """All v2 rows plus the per-rule counts the dry run prints. Writes nothing."""
    rows = [r for sku in sorted(profile) for r in generate_sku_series(sku, profile[sku], seasonal_residuals)]
    cols = [CAL_MONTH_COL, PRODUCT_COL, DESC_COL, PACK_SIZE_COL, QTY_CS_COL, QTY_PC_COL, GSV_COL, AMT_COL]
    out = pd.DataFrame(rows)
    if len(out):  # match the real column order exactly, as v1 did
        out = out[cols + [c for c in PROVENANCE_COLUMNS if c in out.columns] + ["is_demo"]]
    P = profile.values()
    witnessed = [p for p in P if p["witness_first"] is not None]
    pre = out[out["_period"] <= PRE_REAL_END] if len(out) else out
    counts = {
        "real_skus": len(profile), "witnessed": len(witnessed), "unwitnessed_no_pre_rows": len(profile) - len(witnessed),
        "anchor_first_3_positive": sum(p["anchor_rung"] == "first_3_positive" for p in P),
        "anchor_positives_in_first_6": sum(p["anchor_rung"] == "positives_in_first_6" for p in P),
        "anchor_none": sum(p["anchor_rung"] == "none" for p in P),
        "witnessed_excluded_returns_dominated": sum(p["excluded"] == "returns_dominated" for p in witnessed),
        "witnessed_excluded_no_anchor": sum(p["excluded"] == "no_anchor" for p in witnessed),
        "witnessed_excluded_fewer_than_6_residuals": sum(p["excluded"] == "fewer_than_6_residuals" for p in witnessed),
        "witnessed_eligible": sum(p["excluded"] is None for p in witnessed),
        "witnessed_gone_then_relisted": sum(bool(p["pre_window"]) and p["pre_window"][-1] < PRE_REAL_END for p in witnessed),
        "dead": sum(p["dead"] for p in P), "dead_by_runner_series": sum(p["dead_by_runner_series"] for p in P),
        "forward_eligible": sum(p["excluded"] is None and not p["dead"] for p in P),
        "pre_2023_skus": int(pre[PRODUCT_COL].nunique()) if len(out) else 0, "pre_2023_rows": int(len(pre)),
        "forward_skus": int(out.loc[out["_period"] > PRE_REAL_END, PRODUCT_COL].nunique()) if len(out) else 0,
        "forward_rows": int((out["_period"] > PRE_REAL_END).sum()) if len(out) else 0, "total_rows": int(len(out)),
    }
    return out, counts


def run_unilever_sku_backfill(dry_run: bool = False, seasonal_residuals: bool = False) -> dict:
    real_df = load_real_unilever_sku()
    witness, july = load_witness()
    profile = derive_sku_profile(real_df, witness)
    out, counts = plan_unilever_sku_backfill(profile, seasonal_residuals)
    excluded = {reason: sorted(s for s, p in profile.items() if p["excluded"] == reason and p["witness_first"] is not None)
                for reason in ("returns_dominated", "no_anchor", "fewer_than_6_residuals")}
    result = {"family": "unilever_sku", "version": 2, "dry_run": dry_run, "seasonal_residuals": seasonal_residuals,
              "witness_files": july, **counts, "excluded_witnessed_skus": excluded}
    if dry_run:
        return result

    out_dir = OUT_DIR / "unilever_sku"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for period in UNILEVER_BACKFILL_PERIODS:
        path = out_dir / f"SYNTH__UNILEVER_SKU_{period}.parquet"      # loader contract: unchanged naming
        df = out[out["_period"] == period].reset_index(drop=True) if len(out) else out
        if df.empty:
            path.unlink(missing_ok=True)                                # never leave a stale v1 file standing in for "no rows"
            continue
        df["_row_ordinal"] = range(len(df))
        df.to_parquet(path, index=False, engine="pyarrow")
        written += 1
    result["files_written"] = written
    return result


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


DRY_RUN = False        # set by --dry-run: every generator below computes its rows but writes no file
POOL_REPORT: dict = {}  # family -> what load_real_family_template() dropped, printed by the dry run


def _is_demo(df: pd.DataFrame) -> pd.Series:
    """True for synthetic rows. staging/<family>/ also holds materialised copies of synthetic output
    (SYNTH__ files, and the raw synthetic xlsx staged by Extract), some with is_demo as the string 'True'."""
    if "is_demo" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["is_demo"].fillna(False).astype(str).str.lower().isin(["true", "1"])


def load_real_family_template(family: str) -> pd.DataFrame:
    """The 2025 resample pool: REAL rows only, and for the invoice families only rows whose Net Amount is a
    number.

    Two defects fixed 2026-09-21. (1) The pool read every parquet under staging/<family>/, which includes
    synthetic copies, so synthetic rows were being resampled into new synthetic rows. (2) The pool is read by
    the RAW column names in FAMILY_BUSINESS_COLS, and 5,007 of the 14,682 real 2025 sales_register rows have
    nothing under the raw "Net Amount" header: 2,224 sit on ONE PAGER cross-check sheets, 2,316 are the
    Oct-Nov 2025 files, which use a different header vocabulary (AMOUNT / NET VALUE / REFERENCE #), and 467
    are footer, signature-block and blank lines. None of this is a defect in the real data - Transform maps
    the second vocabulary (config/column_maps/sales_register.yaml) and those months load in full - but
    resampling such a row here yields a synthetic row with no Net Amount, which the loader can only drop
    (scripts/run_canonical_load.py _drop_rows_violating_other_not_null: 197 at the first real load). There is
    no correct Net Amount to invent, so the row is left out of the pool rather than filled. Consequence,
    stated: the pool holds no Oct-Nov 2025 rows."""
    files = sorted(REAL_STAGING_DIR.glob(f"{family}/*.parquet"))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df[df["_period"].str.startswith(DELMONTE_TEMPLATE_YEAR_PREFIX)]
    demo = _is_demo(df)
    report = {"rows_2025": int(len(df)), "dropped_is_demo": int(demo.sum())}
    df = df[~demo]
    if "Net Amount" in df.columns and family in INVOICE_FAMILIES:
        bad = pd.to_numeric(df["Net Amount"], errors="coerce").isna()
        report["dropped_real_rows_without_net_amount"] = int(bad.sum())
        df = df[~bad]
    report["pool_rows"] = int(len(df))
    POOL_REPORT[family] = report
    return df


def real_row_count_pool(family: str, region: str) -> list[int]:
    """Row counts of the REAL 2025 files for this region (synthetic copies in staging/ are skipped)."""
    files = sorted(REAL_STAGING_DIR.glob(f"{family}/*.parquet"))
    counts = []
    for f in files:
        meta = pd.read_parquet(f)
        if _is_demo(meta).any():
            continue
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
            if family == "sell_out":
                # natural key = (category_path, region, _period): one row per category. Drawing rows with
                # replacement put the same category in a file twice (46 rows in 19 keys), which the loader can
                # only resolve by discarding one. Categories are drawn WITHOUT replacement, then one real row
                # of each chosen category is taken.
                category = pool["__col0__"].astype(str).str.strip()
                distinct = sorted(category.unique())
                n = min(n, len(distinct))
                chosen = rng.choice(distinct, size=n, replace=False)
                sample_idx = [int(rng.choice(np.nonzero((category == c).to_numpy())[0])) for c in chosen]
            else:
                sample_idx = rng.integers(0, len(pool), size=n)
            rows = pool.iloc[sample_idx][business_cols].reset_index(drop=True).copy()
            if family == "sell_out" and rows["__col0__"].astype(str).str.strip().duplicated().any():
                raise ValueError(f"sell_out {period} {region}: duplicate category in one (region, period) - "
                                 "the (category_path, region, _period) key must be unique")

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
            if "Net Amount" in rows.columns and pd.to_numeric(rows["Net Amount"], errors="coerce").isna().any():
                raise ValueError(f"{family} {period} {region}: a generated row has no Net Amount")
            if not DRY_RUN:
                rows.to_parquet(out_path, index=False, engine="pyarrow")
            total_rows += len(rows)
            files_written += 1

    return {"family": family, "files_written": files_written, "total_rows": total_rows, "dry_run": DRY_RUN,
            "pool": POOL_REPORT.get(family)}


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
    real_df = real_df[~_is_demo(real_df)]  # staging/ also holds synthetic copies - never resample those
    real_2025_all = real_df[real_df["_period"].str.startswith("2025")]
    # Same guard load_real_family_template() applies to the invoice families (2026-09-21): the real sheets
    # carry header rows, Good/Bad Stock markers and blank lines that Transform excludes
    # (SALES_RETURN_FOOTER_CHECKS). Resampling one yields a synthetic return with no Net Amount - 6 such rows
    # reached the scratch load. There is no correct amount to invent, so those rows leave the pool. File row
    # counts below still come from the whole files, as they do for the invoice families.
    real_2025 = real_2025_all[pd.to_numeric(real_2025_all["Net Amount"], errors="coerce").notna()]
    POOL_REPORT["sales_return"] = {"rows_2025": int(len(real_2025_all)), "pool_rows": int(len(real_2025)),
                                   "dropped_real_rows_without_net_amount": int(len(real_2025_all) - len(real_2025))}

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
                row_count_pool = real_2025_all[(real_2025_all["_region"] == region) & (real_2025_all["_sheet_role"] == role)].groupby("_src_file").size().tolist() or [10]
                n = int(rng.choice(row_count_pool))
                sample_idx = rng.integers(0, len(pool), size=n)
                rows = pool.iloc[sample_idx][SALES_RETURN_BUSINESS_COLS].reset_index(drop=True).copy()
                if pd.to_numeric(rows["Net Amount"], errors="coerce").isna().any():
                    raise ValueError(f"sales_return {period} {region} {role}: a generated row has no Net Amount")

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
                if not DRY_RUN:
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
    real_df = real_df[~_is_demo(real_df)]  # staging/ also holds synthetic copies - never resample those

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
                if not DRY_RUN:
                    rows.to_parquet(out_path, index=False, engine="pyarrow")
                total_rows += len(rows)
                files_written += 1

    return {"family": "rmr_gs_bo", "files_written": files_written, "total_rows": total_rows}


# ================================================================
# 5. (retired 2026-09-21) Del Monte fine-grained sell_out bridge
#
# This section used to generate 2025-01..2026-08 sell-out rows for the 42
# pre-2025 fine-grained categories from a trend + month-of-year fit. It was
# retired at Gate C: the fit ran on history that included synthetic rows, and
# refitting on real rows only is not possible - real post-Jan-2025 sell-out
# covers 6 months (2025-03, 04, 06, 08, 09, 12), in a different, coarse
# category vocabulary (BEVERAGE / CULINARY / FRUITS / INNOVATION / DAIRY).
# The code is in git history (last present in c7ca212).
#
# LIMITATIONS of the Del Monte placeholder, stated for the TA explainer:
#   - Del Monte 2025 sell-out has 6 real months; missing months are not
#     filled, because the category vocabulary changed and 6 months cannot
#     support a fit.
#   - Del Monte has no stock-on-hand witness for 2021-22, so no claim can be
#     made about which products existed when. Del Monte placeholder rows are
#     therefore not launch-aware, unlike Unilever's.
# ================================================================


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print rows per family and per rule, write nothing")
    parser.add_argument("--delmonte-only", action="store_true", help="skip the unilever_sku backfill")
    parser.add_argument("--unilever-only", action="store_true", help="skip the Del Monte families")
    parser.add_argument("--seasonal-residuals", action="store_true", default=False,
                        help="draw a month's residual from the same calendar month when the SKU has 2+ such residuals. "
                             "OFF by default: seasonality is not detectable in 38 months of this data")
    args = parser.parse_args()

    DRY_RUN = args.dry_run
    if not args.delmonte_only:
        result = run_unilever_sku_backfill(dry_run=args.dry_run, seasonal_residuals=args.seasonal_residuals)
        listed = result.pop("excluded_witnessed_skus")
        print(json.dumps(result, indent=2, default=str))
        for reason, skus in listed.items():
            print(f"excluded witnessed SKUs - {reason}: {len(skus)}" + (f"  e.g. {skus[:8]}" if skus else ""))
    if args.unilever_only:
        sys.exit(0)
    print()
    for fam in ["sales_register", "purchase_order", "sell_out", "inventory_sign_off"]:
        print(generate_del_monte_family(fam))
    print(generate_sales_return())
    print(generate_rmr_gs_bo())
