"""
scripts/convert_synthetic_to_staging.py — Phase 2 of the synthetic-staging
conversion (see reports/SYNTHETIC_STAGING_CONVERSION.md).

Converts the 374 raw .xlsx files in data/raw/Synthetic Data/ (already
carrying Extract's own 15 PROVENANCE_COLUMNS baked into row 1, plus a
16th is_demo column - see reports/SYNTHETIC_DATA_AUDIT.md) into Parquet.

READ-ONLY on data/raw/. Writes ONLY to staging_synthetic/ - never
staging/. Nothing here is merged into the real pipeline by this script;
that is a separate, later, human decision.

Usage: python scripts/convert_synthetic_to_staging.py
"""
from __future__ import annotations

import decimal
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analytics.etl.extract._shared import PROVENANCE_COLUMNS, sanitize_filename  # noqa: E402
from analytics.etl.transform import _SKU_CODE_RE  # noqa: E402

RAW_SYNTH_DIR = REPO_ROOT / "data" / "raw" / "Synthetic Data"
OUT_DIR = REPO_ROOT / "staging_synthetic"

# Explicit prefix map - NOT profiling/profile_files.py's DOC_TYPE_PATTERNS
# regex. That regex misclassifies these exact filenames: "sale[s]?\s*regist"
# and "sell\s*out" both require whitespace between the two words via \s*,
# but "SALES_REGISTER_..." / "SELL_OUT_..." have an underscore there, and
# \s doesn't match "_" (it's a word character) - same root-cause class of
# bug as the PANG_ region-inference fix earlier this session. Confirmed
# directly: infer_doc_type(Path("SALES_REGISTER_2021-01_ILOCOS.xlsx")) and
# infer_doc_type(Path("SELL_OUT_2021-01_ILOCOS.xlsx")) both return
# "unknown". INVENTORY_SIGN_OFF_*/PURCHASE_ORDER_* happen to still match
# (their patterns have a plain substring alternative - "inventory" and
# "purchase" - with no \s in the way), so only 2 of 4 prefixes are
# actually broken by this bug. Reported as a separate finding in
# reports/SYNTHETIC_STAGING_CONVERSION.md; NOT fixed here or in
# profile_files.py, per instruction.
DOC_TYPE_PREFIX_MAP = {
    "SALES_REGISTER": "sales_register",
    "SELL_OUT": "sell_out",
    "INVENTORY_SIGN_OFF": "inventory_sign_off",
    "PURCHASE_ORDER": "purchase_order",
}

# source_of_truth.yaml's real system_of_record_role for all four doc_types
# here, for delmonte - all "data" (config/source_of_truth.yaml:59,133,146,177).
# Set explicitly rather than trusting the baked-in _sheet_role value, per
# instruction - even though every one of the 374 files' baked-in value was
# independently confirmed to already be "data" (see prior turn's item 2
# finding), trust-and-pass-through was rejected as the mechanism.
SYSTEM_OF_RECORD_ROLE = {
    "sales_register": "data",
    "sell_out": "data",
    "inventory_sign_off": "data",
    "purchase_order": "data",
}

FILENAME_RE = re.compile(
    r"^(?P<prefix>[A-Z_]+?)_(?P<period>\d{4}-\d{2})_(?P<region>[A-Z]+)\.xlsx$"
)

# Real Shape B's numeric-fragment convention (derived from real staged
# data in Phase 1b, not invented): __col0__ is the trailing digit run of
# the combined string's leading alphanumeric code token, e.g.
# "9DBL58403 DM 100% ..." -> code "9DBL58403" -> trailing digits "58403".
# Verified against 2,072/2,097 real Shape B rows in this session's Phase
# 1b investigation.
TRAILING_DIGITS_RE = re.compile(r"(\d+)$")

# Real per-period presence of purchase_order's Town Display/Branch Code,
# verified directly against every real staging/purchase_order/*.parquet
# file (Phase 3b) - not assumed. Real data: absent entirely 2023-09/11/12,
# present 2024-01 onward, EXCEPT one real anomaly - 2025-09 Ilocos has
# both columns present but 100% NULL (27/27 rows) - a genuine one-off
# source gap, same class as inventory_sign_off's Shape D. Real null rate
# among rows where the column exists: 27/414 = 6.52%, entirely from that
# one file. Messier than a clean cutover, confirmed - not synthesized
# here (a single one-off 100%-null file, like inventory's Shape D, isn't
# a recurring template to replicate); the presence/absence cutover at
# 2024-01 IS clean and is what's applied.
PURCHASE_ORDER_TOWN_BRANCH_CUTOVER = "2024-01"

# sell_out's real "CASE" column (Phase 3c) was investigated and
# deliberately NOT added to synthetic output. It is not a per-row
# conversion of Product Quantity (ratio across the 20 real non-null rows
# ranges 0.0-1.24, no fixed relationship) - it's a CONSTANT keyed to a
# completely different, coarse 5-category vocabulary ("Total", "FRUITS",
# "CULINARY", "BEVERAGE", "INNOVATION") that appears in exactly 4/34 real
# files (20/1573 real rows, 98.73% real null rate) and never overlaps
# with the fine-grained category_path vocabulary
# (e.g. "/DISPENSER JUICE/DISPENSER JUICE") every synthetic row and the
# other 30/34 real files actually use. Populating it on synthetic rows
# would mean inventing a relationship between two structurally
# incompatible real shapes - real data's own 98.73% null rate is the
# correct target, and the current 100% absence already achieves that
# (arguably more faithfully than adding a column that would then need
# its own near-total-null treatment).

# inventory_sign_off's real "in PCS" (Phase 3d): a real conversion IS
# derivable - in PCS = in Cases * PKG, confirmed on 1,193/1,211 (98.5%)
# real rows carrying all three columns. But real presence itself is
# narrow: only 8/41 real files, all within 2023-08 through 2024-01
# (matches column_maps/inventory_sign_off.yaml's own note: "confirmed
# header, most 2023 exports") - real overall null rate across all 7,019
# real rows is 82.62%. Applying the formula outside that real presence
# window would give synthetic a 0% null rate against a real 82.62% one -
# exactly the "own tell" the instruction warned about. Formula is
# applied only within the same real presence window.
INVENTORY_IN_PCS_REAL_PERIODS = {"2023-08", "2023-09", "2023-12", "2024-01"}

# Real cutover month for inventory_sign_off Shape A -> Shape B (Phase 1b,
# ignoring the August-2023 one-off anomaly, which is a real one-time
# report-template swap, not a recurring shape - not synthesized here,
# per instruction).
SHAPE_B_CUTOVER_PERIOD = "2025-03"

# sell_out negative Product Quantity (Phase 3b) - the 33 real negative
# values themselves, from staging/sell_out/*.parquet, excluding "Total"
# banner rows (never eligible - a summary-row aggregate shouldn't
# independently roll negative). Injected magnitudes are sampled from
# this exact real list (with replacement), never a fitted/parametric
# distribution, so every injected value is one an SSM export actually
# reported. Real rate among non-Total rows: 33/1539 = 2.1442%.
REAL_SELL_OUT_NEGATIVE_VALUES = [
    -8.5, -6.95833, -4.70833, -2.5, -2.0, -2.0, -1.625, -1.16667, -1.125, -1.0,
    -1.0, -0.875, -0.78, -0.65, -0.5, -0.5, -0.41667, -0.29167, -0.27778, -0.25,
    -0.25, -0.25, -0.20833, -0.15, -0.125, -0.125, -0.125, -0.08333, -0.08333,
    -0.08333, -0.08333, -0.041666666666666664, -0.041666666666666664,
]
REAL_SELL_OUT_NEGATIVE_RATE = 33 / 1539

# Net Amount duplicate clustering (Phase 3c). The 44.14% figure quoted in
# the ruling could NOT be reproduced from real data under any definition
# tried against staging/sales_register/*.parquet: standard rows-basis
# (value repeats elsewhere / all non-null rows) = 52.5316% (9,815/18,684);
# string-exact instead of numeric-coerced = same, 52.5316%; denominator =
# all rows including null Net Amount = 41.2101%; ilocos-only = 25.4934%;
# pangasinan-only = 58.1902%. None match 44.14%. Using the standard
# rows-basis definition (52.5316%) as the real target instead, since it's
# the one I can directly cite and reproduce - flagged prominently in the
# report rather than silently substituted.
REAL_NET_AMOUNT_DUP_RATE_ROWS_BASIS = 9815 / 18684  # 52.5316%, see note above

# Calibrated by empirical search (not a formula - collision rate from
# resampling into a fixed real pool depends on draw count vs pool size
# and has no closed form worth deriving here): replacing 62% of
# synthetic sales_register Net Amount values with values drawn (with
# replacement) from the real pool lands the achieved synthetic dup rate
# at 52.865% against the 33,438-row real synthetic corpus - closest of
# the fractions tried (0.60->50.91%, 0.61->51.82%, 0.62->52.87%,
# 0.63->53.71%), gap +0.33pp. Not tuned further per instruction not to
# chase exact precision.
NET_AMOUNT_RESAMPLE_FRACTION = 0.62

# Real per-doc_type Parquet column order/dtype, as characterized directly
# against staging/*/*.parquet in Phase 0 (reports/STAGING_CONTRACT.md).
# Business-column sets are the DE-DUPED UNION across ALL real eras for
# each doc_type (e.g. sales_register's real corpus spans a 13-column era
# and a 15-column era) - a single synthetic file only ever has one era's
# columns, and this order is used to place whichever of these columns
# that file actually has; columns the file lacks are simply absent, never
# fabricated.
REAL_BUSINESS_COLUMNS = {
    "sales_register": [
        "Invoice Date", "Salesman", "Town Display", "Branch Code", "Customer Name",
        "Invoice Num", "REFNBR", "Untaxed Amount", "Discount Rate", "Discount Amount",
        "Tax", "Net Amount", "Balance", "Posted", "Return Slip #",
    ],
    "purchase_order": [
        "Invoice Date", "Salesman", "Town Display", "Branch Code", "Customer Name",
        "Invoice Num", "REFNBR", "Untaxed Amount", "Discount Rate", "Discount Amount",
        "Tax", "Net Amount", "Balance", "Posted", "Return Slip #",
    ],
    "sell_out": ["__col0__", "Total Without Tax", "Product Quantity", "CASE"],
    "inventory_sign_off": [
        "__col0__", "__col1__", "Quantity", "Cost", "Valuation", "Valuation with VAT",
        "CAS", "PCS", "PKG", "in PCS", "in Cases",
    ],
}

# Real dtype targets for the numeric business columns Phase 0 documented
# (everything else - money/text fields - stays whatever pandas.read_excel
# infers, matching real data's own "object" dtype for those columns).
NUMERIC_DTYPE_TARGETS = {
    "sell_out": {"Product Quantity": "float64"},
    "inventory_sign_off": {
        "Quantity": "float64", "CAS": "float64", "PCS": "float64",
        "PKG": "float64", "in PCS": "float64", "in Cases": "float64",
    },
}


# staging/ path for deriving the real Town Display / Branch Code
# co-occurrence map (Phase 3a ruling) - read once, cached.
REAL_STAGING_DIR = REPO_ROOT / "staging"
_TOWN_BRANCH_MAP_CACHE: dict | None = None


def _read_real_staged(family: str) -> pd.DataFrame:
    """Every REAL staged row of a family. staging/<family>/ also holds copies of synthetic output, and a "real"
    pool that includes them makes this script's output depend on whichever synthetic copies happen to be
    present - synthetic breeding synthetic. Found 2026-09-21: the town/branch map, the salesman remap and the
    Net Amount pool all read the whole folder."""
    frames = []
    for f in sorted(REAL_STAGING_DIR.glob(f"{family}/*.parquet")):
        df = pd.read_parquet(f)
        if "is_demo" in df.columns:
            df = df[~df["is_demo"].fillna(False).astype(str).str.lower().isin(["true", "1"])]
        if len(df):
            frames.append(df)
    return pd.concat(frames, ignore_index=True)


def derive_town_branch_map() -> dict:
    """Real (Town Display, Branch Code) co-occurrence, scoped by region -
    derived from staging/sales_register/*.parquet only, never invented.
    Checked: only 2 of 87 real Town Display values ("SAN NICOLAS",
    "SANTA MARIA") appear in both regions (plausibly the same common
    Filipino place name existing in both provinces independently, not a
    data error) - real Town Display/Branch Code pairs are otherwise
    cleanly region-specific, so sampling scoped by region is safe and
    doesn't need to be broken down further. Weight = real row count for
    that exact pair, so the assigned distribution mirrors which
    branches are actually busy in real data rather than spreading rows
    uniformly across all 1,351 real pairs."""
    global _TOWN_BRANCH_MAP_CACHE
    if _TOWN_BRANCH_MAP_CACHE is not None:
        return _TOWN_BRANCH_MAP_CACHE

    df = _read_real_staged("sales_register")
    sub = df[["Town Display", "Branch Code", "_region"]].dropna(subset=["Town Display", "Branch Code"])

    result = {}
    for region, group in sub.groupby("_region"):
        pairs = group.groupby(["Town Display", "Branch Code"]).size().reset_index(name="weight")
        result[region] = {
            "pairs": list(zip(pairs["Town Display"], pairs["Branch Code"])),
            "weights": pairs["weight"].tolist(),
            "real_row_count": int(len(group)),
        }
    _TOWN_BRANCH_MAP_CACHE = result
    return result


def assign_town_branch(df: pd.DataFrame, region: str, seed_key: str) -> pd.DataFrame:
    """Deterministically assigns each row a real (Town Display, Branch
    Code) pair, sampled with replacement from that region's real
    co-occurrence weights (Phase 3a). Seeded from a stable hash of
    seed_key (the source filename) rather than a global sequential RNG,
    so output is reproducible regardless of file-processing order."""
    out = df.copy()
    town_map = derive_town_branch_map()
    if region not in town_map or not town_map[region]["pairs"]:
        return out  # no real data for this region - leave columns absent, never invent a pair

    pairs = town_map[region]["pairs"]
    weights = np.array(town_map[region]["weights"], dtype=float)
    probs = weights / weights.sum()

    seed = int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    choice_idx = rng.choice(len(pairs), size=len(out), p=probs)

    out["Town Display"] = [pairs[i][0] for i in choice_idx]
    out["Branch Code"] = [pairs[i][1] for i in choice_idx]
    return out


_SALESMAN_REMAP_CACHE: dict | None = None


def derive_salesman_remap() -> dict:
    """Deterministic invented->real salesman name remap (Phase 3a).
    Loads the 33 real distinct Salesman names from
    staging/sales_register/*.parquet only. Checked region-scoping first,
    same as Town Display: 30/33 real names appear in exactly one region,
    3 ("ADMIN SALES", "ELYSSA L. MASON", "ENCODER") appear in both.
    Synthetic data's 9 distinct names are ALREADY internally
    region-scoped one-name-per-region (checked directly) except
    "OFFICE SALES", which is both real AND already appears in both
    regions in synthetic data too - left untouched, it's not invented.
    The other 8 invented names are mapped 1:1 onto that same region's
    real single-region roster, sorted alphabetically on both sides for
    a fully deterministic (non-random) assignment."""
    global _SALESMAN_REMAP_CACHE
    if _SALESMAN_REMAP_CACHE is not None:
        return _SALESMAN_REMAP_CACHE

    df = _read_real_staged("sales_register")
    real = df[["Salesman", "_region"]].dropna(subset=["Salesman"])
    region_of = real.groupby("Salesman")["_region"].agg(lambda s: sorted(set(s)))
    real_single_region = {
        region: sorted(n for n, r in region_of.items() if r == [region])
        for region in ("ilocos", "pangasinan")
    }

    synth_files = sorted(RAW_SYNTH_DIR.glob("SALES_REGISTER_*.xlsx"))
    synth_region_of: dict[str, set[str]] = {}
    for f in synth_files:
        parsed = parse_filename(f.name)
        if parsed is None:
            continue
        _, _, region = parsed
        d = pd.read_excel(f, sheet_name=0, header=0, usecols=["Salesman"])
        for name in d["Salesman"].dropna().unique():
            synth_region_of.setdefault(name, set()).add(region)

    real_name_set = set(region_of.index)
    invented_by_region: dict[str, list[str]] = {"ilocos": [], "pangasinan": []}
    for name, regions in synth_region_of.items():
        if name in real_name_set:
            continue  # already real, e.g. "OFFICE SALES" - not remapped
        if len(regions) == 1:
            invented_by_region[next(iter(regions))].append(name)
        else:
            invented_by_region.setdefault("both", []).append(name)  # none observed, but never silently drop

    remap = {}
    for region, invented_names in invented_by_region.items():
        candidates = real_single_region.get(region, [])
        for i, name in enumerate(sorted(invented_names)):
            if i < len(candidates):
                remap[name] = candidates[i]
            else:
                remap[name] = None  # more invented names than real candidates - flagged, not guessed

    _SALESMAN_REMAP_CACHE = remap
    return remap


_NET_AMOUNT_POOL_CACHE: list | None = None


def derive_net_amount_pool() -> list:
    """Full real Net Amount multiset (every non-null value, natural
    frequency preserved) from staging/sales_register/*.parquet - Phase
    3c's resampling source. Not just the repeated-value subset: sampling
    from the full pool (weighted by its own natural frequency, since it's
    a plain list with duplicates) lets real duplication structure emerge
    from the same collision dynamics real data itself produced, rather
    than hand-constructing a frequency-of-frequency distribution."""
    global _NET_AMOUNT_POOL_CACHE
    if _NET_AMOUNT_POOL_CACHE is not None:
        return _NET_AMOUNT_POOL_CACHE
    df = _read_real_staged("sales_register")
    _NET_AMOUNT_POOL_CACHE = pd.to_numeric(df["Net Amount"], errors="coerce").dropna().tolist()
    return _NET_AMOUNT_POOL_CACHE


def inject_net_amount_duplicates(df: pd.DataFrame, seed_key: str) -> tuple[pd.DataFrame, int]:
    """Overwrites NET_AMOUNT_RESAMPLE_FRACTION of rows' Net Amount with
    values drawn (with replacement) from the real pool (Phase 3c).
    Row count is unchanged - values are overwritten in place, never
    added/removed. Deterministic per-file seed, same pattern as the
    other Phase 3 injections."""
    out = df.copy()
    if "Net Amount" not in out.columns:
        return out, 0
    pool = derive_net_amount_pool()
    n = int(round(len(out) * NET_AMOUNT_RESAMPLE_FRACTION))
    if n == 0:
        return out, 0
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    chosen_idx = rng.choice(out.index, size=n, replace=False)
    sampled = rng.choice(pool, size=n)

    # pandas.read_excel() auto-parses numeric-looking cells to plain
    # float, but this isn't uniform across all 86 files (confirmed: the
    # first file's Net Amount column is 244/244 float; assigning a
    # formatted-string replacement there produced a str/float-mixed
    # column pyarrow's to_parquet() correctly refused to write). A
    # third case showed up when this function was reused to inject into
    # rows resampled directly from real staged data (generate_synthetic_
    # backfill.py, 2026-08): real Net Amount round-trips as
    # decimal.Decimal, which pyarrow also refuses to mix with plain
    # float in one column. Detect each frame's own existing type from
    # its untouched values and match it, rather than assuming one of
    # two conventions.
    existing_non_null = out["Net Amount"].dropna()
    str_like = int(existing_non_null.apply(lambda v: isinstance(v, str)).sum())
    decimal_like = int(existing_non_null.apply(lambda v: isinstance(v, decimal.Decimal)).sum())
    if len(existing_non_null) and str_like / len(existing_non_null) > 0.5:
        out.loc[chosen_idx, "Net Amount"] = [f"{v:.2f}" for v in sampled]
    elif len(existing_non_null) and decimal_like / len(existing_non_null) > 0.5:
        out.loc[chosen_idx, "Net Amount"] = [decimal.Decimal(str(round(float(v), 2))) for v in sampled]
    else:
        out.loc[chosen_idx, "Net Amount"] = sampled
    return out, n


def inject_sell_out_negatives(df: pd.DataFrame, seed_key: str) -> tuple[pd.DataFrame, int]:
    """Deterministically flips ~2.14% of non-Total rows' Product Quantity
    negative (Phase 3b), magnitude sampled with replacement from the 33
    real observed negative values - not a fitted distribution. "Total"
    banner rows are excluded from both the eligible pool and the rate's
    denominator, matching how the real rate was computed."""
    out = df.copy()
    if "Product Quantity" not in out.columns or "__col0__" not in out.columns:
        return out, 0
    eligible = out.index[out["__col0__"].astype(str).str.strip().str.upper() != "TOTAL"]
    if len(eligible) == 0:
        return out, 0

    seed = int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    n_negative = int(round(len(eligible) * REAL_SELL_OUT_NEGATIVE_RATE))
    if n_negative == 0:
        return out, 0
    chosen_idx = rng.choice(eligible, size=n_negative, replace=False)
    magnitudes = rng.choice(REAL_SELL_OUT_NEGATIVE_VALUES, size=n_negative)
    out.loc[chosen_idx, "Product Quantity"] = magnitudes
    return out, n_negative


DRY_RUN = False                        # set by --dry-run: convert and count, write nothing
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
REAL_EVIDENCE_SKUS: set | None = None  # loaded once from the DB on first use; tests inject a set


def load_real_evidence_skus() -> set:
    """Del Monte SKU codes that REAL data vouches for: product_dimension rows (grain 'sku') that have at least
    one Inventory_Fact_Real row - 597 as of 2026-09-21, the set scripts/apply_dm_fix_to_public.py step 3
    upserted from the real inventory_sign_off files. Read-only. data/delmonte_real_skus.txt is NOT used: it
    lists 269 codes and predates that fix."""
    import os
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
    conn = psycopg2.connect(os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")  # transaction-scoped, never session-level (pooler leak)
            cur.execute("""SELECT DISTINCT pd.sku_code FROM product_dimension pd
                           JOIN inventory_fact_real i ON i.product_key = pd.product_key
                           WHERE pd.principal = 'delmonte' AND pd.grain = 'sku' AND pd.sku_code IS NOT NULL""")
            return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def restrict_inventory_to_real_evidence(df: pd.DataFrame, evidence: set) -> tuple[pd.DataFrame, dict]:
    """Drop synthetic inventory rows whose SKU code no real file has ever carried.

    The raw synthetic inventory xlsx invent their own SKU codes (14,5xx of them), and each one becomes a
    Product_Dimension row with no stock, tier or reorder point behind it. Del Monte has no SOH-style witness
    of what existed when, so no existence claim can be made for a SKU real data never shows; such rows are
    left out rather than loaded as products. The match is on the FULL code the loader would store: a
    trailing-digit match is not enough, because the loader would still create a product under the invented
    full code. Rows with no SKU-like code (banners, blanks) pass through for Transform to judge."""
    if "__col0__" not in df.columns:
        return df, {"excluded_rows": 0, "excluded_codes": []}
    code = df["__col0__"].map(lambda v: (_SKU_CODE_RE.match(str(v)) or [None, None])[1] if pd.notna(v) else None)
    has_code = code.notna() & code.astype(str).str.contains(r"\d", na=False)
    drop = has_code & ~code.isin(evidence)
    return df.loc[~drop].copy(), {"excluded_rows": int(drop.sum()), "excluded_codes": sorted(set(code[drop])),
                                  "kept_sku_rows": int((has_code & ~drop).sum())}


def parse_filename(name: str) -> tuple[str, str, str] | None:
    """(doc_type, period, region) from the filename alone - explicit
    prefix map, not profile_files.py's buggy regex."""
    m = FILENAME_RE.match(name)
    if not m:
        return None
    prefix = m.group("prefix")
    doc_type = DOC_TYPE_PREFIX_MAP.get(prefix)
    if doc_type is None:
        return None
    return doc_type, m.group("period"), m.group("region").lower()


def apply_inventory_shape_b(df: pd.DataFrame) -> pd.DataFrame:
    """Era-faithful reshape: for periods >= 2025-03, convert Shape A's
    single combined __col0__ into Shape B's real layout (bare-numeric
    __col0__ + combined-string __col1__). Rows whose __col0__ doesn't
    match the SKU-code pattern (banner rows, blanks) are left as-is in
    __col0__ with __col1__ null - never guessed at."""
    out = df.copy()
    if "__col0__" not in out.columns:
        return out
    out["__col1__"] = pd.NA
    new_col0 = []
    for val in out["__col0__"]:
        if pd.isna(val):
            new_col0.append(val)
            continue
        s = str(val)
        m = _SKU_CODE_RE.match(s)
        if not m or not any(ch.isdigit() for ch in m.group(1)):
            new_col0.append(val)  # banner/unmatched row - leave in __col0__, __col1__ stays null
            continue
        code = m.group(1)
        digits_m = TRAILING_DIGITS_RE.search(code)
        fragment = digits_m.group(1) if digits_m else code
        new_col0.append(fragment)
        out.loc[out["__col0__"] == val, "__col1__"] = s
    out["__col0__"] = new_col0
    return out


def convert_file(path: Path) -> dict | None:
    parsed = parse_filename(path.name)
    if parsed is None:
        return {"skipped": path.name, "reason": "filename doesn't match <PREFIX>_<YYYY-MM>_<REGION>.xlsx"}
    doc_type, period_from_name, region_from_name = parsed
    if not PERIOD_RE.match(period_from_name):
        # A row with no real month cannot be placed on the calendar, and 'unknown' is a legal TEXT value the
        # loader would accept (117 such purchase rows reached the live table through another path).
        return {"skipped": path.name, "reason": f"period '{period_from_name}' is not a YYYY-MM month - rejected, not staged"}

    df = pd.read_excel(path, sheet_name=0, header=0)
    real_sheet_name = pd.ExcelFile(path).sheet_names[0]

    schema_notes = []

    # --- repair provenance: _src_file / _period must agree and point at
    # a real, existing file (Phase 2b) ---
    real_src_file = f"data/raw/Synthetic Data/{path.name}"
    df["_src_file"] = real_src_file
    df["_period"] = period_from_name
    # _src_sheet: same wholesale-copy bug as _src_file (confirmed by the
    # prior diagnosis turn - baked-in values point at real anchor-row
    # sheet names like "ILOCOS SALES REGISTER" that don't match this
    # file's actual single sheet, e.g. "Sales Register"). Not explicitly
    # named in the instruction alongside _src_file/_period, but the same
    # repair logic applies for the same reason - Transform's
    # groupby(["_src_file","_src_sheet"]) needs this pair to be
    # self-consistent.
    df["_src_sheet"] = real_sheet_name
    if "_region" in df.columns and (df["_region"].astype(str).str.lower() != region_from_name).any():
        schema_notes.append(f"_region disagreed with filename for some rows - overwritten to '{region_from_name}'")
    df["_region"] = region_from_name

    # --- Invoice Num: repair cross-month collisions (found during the
    # coverage-backfill session, 2026-08). The original raw synthetic
    # files reset Invoice Num to "INV/YYYY/0001" every single month
    # ("INV/2021/0001" appears identically in 2021-01, 2021-02, 2021-06,
    # ... for the same region) - Sales_Fact/Purchase_Fact's real natural
    # key is [invoice_num, principal, region] with NO period component,
    # so this collided across the whole year, causing 45/68 sales_register
    # months and 56/68 purchase_order months to land in dedup_facts()'s
    # conflict bucket instead of loading. Renumbered here with month
    # encoded into the number space (month*1000 + row_ordinal), same
    # scheme already used for the new backfill's own generated invoice
    # numbers - confirmed max real rows-per-file (850) stays under 1000,
    # so no cross-month overflow. Every other field (Customer Name,
    # Salesman, amounts, dates) is untouched; only the identifier itself
    # was ever wrong.
    if doc_type in ("sales_register", "purchase_order") and "Invoice Num" in df.columns:
        year_num = period_from_name.split("-")[0]
        month_num_str = period_from_name.split("-")[1]
        # 900000 base offset (2026-08, second fix): the month*1000 scheme
        # alone still collided with REAL invoice numbers for
        # months/periods where real and synthetic data coexist - real
        # numbering isn't month-bucketed, it's one continuous counter
        # across the year (real Dec 2025 was already in the 5000s, which
        # sits inside my synthetic May encoding's own 5000-5999 range).
        # 900000+ is safely above any plausible real range while staying
        # a valid, obviously-synthetic-looking identifier.
        df["Invoice Num"] = [f"INV/{year_num}/{900000 + int(month_num_str) * 1000 + i}" for i in range(len(df))]

    # --- _sheet_role: set explicitly, don't trust baked-in (Phase 2's
    # decided requirement) ---
    baked_in_roles = set(df["_sheet_role"].dropna().unique().tolist()) if "_sheet_role" in df.columns else set()
    correct_role = SYSTEM_OF_RECORD_ROLE[doc_type]
    if baked_in_roles and baked_in_roles != {correct_role}:
        schema_notes.append(f"_sheet_role baked-in={sorted(baked_in_roles)} != set value '{correct_role}'")
    df["_sheet_role"] = correct_role
    df["_doc_type"] = doc_type

    # --- inventory_sign_off: only SKUs real data vouches for (before the shape step rewrites __col0__) ---
    evidence_report = None
    if doc_type == "inventory_sign_off":
        global REAL_EVIDENCE_SKUS
        if REAL_EVIDENCE_SKUS is None:
            REAL_EVIDENCE_SKUS = load_real_evidence_skus()
        df, evidence_report = restrict_inventory_to_real_evidence(df, REAL_EVIDENCE_SKUS)
        if evidence_report["excluded_rows"]:
            schema_notes.append(f"excluded {evidence_report['excluded_rows']} rows: SKU code has no real evidence")
        if evidence_report.get("kept_sku_rows", 0) == 0:
            stale = OUT_DIR / doc_type / f"SYNTH__{sanitize_filename(path.stem)}.parquet"
            if not DRY_RUN:
                stale.unlink(missing_ok=True)      # never leave the v1 file standing in for "no rows"
            return {"skipped": path.name, "reason": "inventory_sign_off: no SKU in this file has real evidence",
                    "evidence": evidence_report, "doc_type": doc_type}

    # --- era-faithful inventory_sign_off shape ---
    shape_applied = None
    if doc_type == "inventory_sign_off":
        if period_from_name >= SHAPE_B_CUTOVER_PERIOD:
            df = apply_inventory_shape_b(df)
            shape_applied = "B"
        else:
            shape_applied = "A"

        # --- "in PCS" (Phase 3d): derived formula (in Cases * PKG),
        # applied only within the real presence window - see
        # INVENTORY_IN_PCS_REAL_PERIODS's comment above. ---
        if period_from_name in INVENTORY_IN_PCS_REAL_PERIODS and {"PKG", "in Cases"}.issubset(df.columns):
            computed = df["in Cases"] * df["PKG"]
            df["in PCS"] = computed
            schema_notes.append(f"derived 'in PCS' = in Cases * PKG for {int(computed.notna().sum())} rows (real presence window)")

    # --- sell_out: inject negative Product Quantity at the real observed
    # rate (Phase 3b) ---
    if doc_type == "sell_out":
        df, n_negative = inject_sell_out_negatives(df, seed_key=path.name)
        if n_negative:
            schema_notes.append(f"injected {n_negative} negative Product Quantity rows (real rate, real magnitudes)")

    # --- sales_register: real Town Display / Branch Code, region-scoped
    # weighted real co-occurrence (Phase 3a ruling) - synthetic files
    # never had these columns at all, and NULL-filling geography
    # dimensions the dashboard groups by would give empty regional
    # tiles, defeating the demo's purpose. ---
    town_branch_notes = None
    if doc_type == "sales_register":
        before_cols = set(df.columns)
        df = assign_town_branch(df, region_from_name, seed_key=path.name)
        if "Town Display" not in before_cols:
            town_branch_notes = f"added Town Display/Branch Code from real {region_from_name} co-occurrence map ({len(df)} rows assigned)"

        # --- Salesman: remap invented names onto the real roster
        # (Phase 3a) ---
        if "Salesman" in df.columns:
            remap = derive_salesman_remap()
            unresolved = {v for v in remap.values() if v is None}
            if unresolved:
                schema_notes.append(f"salesman remap has unresolved (more invented names than real candidates): {sorted(k for k,v in remap.items() if v is None)}")
            replaced = df["Salesman"].isin([k for k, v in remap.items() if v is not None]).sum()
            df["Salesman"] = df["Salesman"].map(lambda n: remap.get(n, n) if remap.get(n) is not None else n)
            if replaced:
                schema_notes.append(f"remapped {int(replaced)} Salesman rows onto real names")

        # --- Net Amount: resample against the real value pool to
        # restore realistic duplicate clustering (Phase 3c) ---
        df, n_resampled = inject_net_amount_duplicates(df, seed_key=path.name)
        if n_resampled:
            schema_notes.append(f"resampled {n_resampled} Net Amount values from real pool (duplicate clustering)")

    # --- purchase_order: real per-period presence of Town Display /
    # Branch Code is NOT era-uniform (Phase 3b ruling - verified against
    # every real file, not assumed clean). Drop both columns for periods
    # before the real presence cutover; synthetic always had them. ---
    if doc_type == "purchase_order" and period_from_name < PURCHASE_ORDER_TOWN_BRANCH_CUTOVER:
        dropped = [c for c in ("Town Display", "Branch Code") if c in df.columns]
        if dropped:
            df = df.drop(columns=dropped)
            schema_notes.append(f"dropped {dropped} - real purchase_order has neither before {PURCHASE_ORDER_TOWN_BRANCH_CUTOVER}")

    # --- numeric dtype alignment (real Phase 0 dtypes) ---
    for col, target in NUMERIC_DTYPE_TARGETS.get(doc_type, {}).items():
        if col in df.columns:
            coerced = pd.to_numeric(df[col], errors="coerce")
            if coerced.isna().sum() != df[col].isna().sum():
                schema_notes.append(f"column '{col}': {coerced.isna().sum() - df[col].isna().sum()} values failed numeric coercion")
            df[col] = coerced.astype(target)

    # --- column order: real business columns (only the ones this file
    # actually has, in real order) + PROVENANCE_COLUMNS (exact real
    # order) + is_demo last ---
    real_order = REAL_BUSINESS_COLUMNS.get(doc_type, [])
    present_business = [c for c in real_order if c in df.columns]
    extra_business = [c for c in df.columns if c not in real_order and c not in PROVENANCE_COLUMNS and c != "is_demo" and c != "__col1__"]
    if "__col1__" in df.columns and "__col1__" not in present_business:
        present_business.append("__col1__")
    # Town Display/Branch Code's absence on pre-cutover purchase_order
    # files is the Phase 3b fix itself (already reported via the
    # "dropped" note above), not an unaddressed deviation - exclude from
    # this generic check so it isn't double-reported as a problem.
    known_intentional_absence = (
        {"Town Display", "Branch Code"}
        if doc_type == "purchase_order" and period_from_name < PURCHASE_ORDER_TOWN_BRANCH_CUTOVER
        else set()
    )
    # "in PCS" is handled explicitly above (Phase 3d, real-window-only
    # derivation) - its absence outside that window is intentional and
    # matches real data's own 82.62% null rate, same conceptual status
    # as __col1__'s shape-conditional presence, not an unaddressed gap.
    always_excluded_from_missing_check = {"__col1__", "in PCS"}
    missing_from_real = [
        c for c in real_order
        if c not in df.columns and c not in always_excluded_from_missing_check and c not in known_intentional_absence
    ]
    if missing_from_real:
        schema_notes.append(f"missing real business column(s): {missing_from_real}")
    if extra_business:
        schema_notes.append(f"extra/unexpected column(s) not in real schema: {extra_business}")
    if town_branch_notes:
        schema_notes.append(town_branch_notes)

    ordered_cols = present_business + [c for c in PROVENANCE_COLUMNS if c in df.columns] + (["is_demo"] if "is_demo" in df.columns else [])
    ordered_cols += [c for c in df.columns if c not in ordered_cols]  # never silently drop anything
    df = df[ordered_cols]

    # --- write Parquet ---
    out_dir = OUT_DIR / doc_type
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"SYNTH__{sanitize_filename(path.stem)}.parquet"
    out_path = out_dir / out_name
    if (df["_period"].astype(str) == "unknown").any() or not df["_period"].astype(str).map(lambda p: bool(PERIOD_RE.match(p))).all():
        return {"skipped": path.name, "reason": "a row carries a _period that is not a YYYY-MM month - rejected, not staged"}
    if not DRY_RUN:
        df.to_parquet(out_path, index=False, engine="pyarrow")

    checksum_status = df["_checksum_status"].iloc[0] if "_checksum_status" in df.columns and len(df) else "unverified"
    checksum_column = df["_checksum_column"].iloc[0] if "_checksum_column" in df.columns and len(df) else None
    checksum_expected = df["_checksum_expected"].iloc[0] if "_checksum_expected" in df.columns and len(df) else None
    checksum_got = df["_checksum_got"].iloc[0] if "_checksum_got" in df.columns and len(df) else None
    checksum_diff = df["_checksum_diff"].iloc[0] if "_checksum_diff" in df.columns and len(df) else None

    manifest_entry = {
        "src_file": real_src_file,
        "src_sheet": real_sheet_name,
        "doc_type": doc_type,
        "period": period_from_name,
        "principal": "delmonte",
        "region": region_from_name,
        "row_count": len(df),
        "sheet_role": correct_role,
        "grain": df["_grain"].iloc[0] if "_grain" in df.columns and len(df) else None,
        "checksum_status": None if pd.isna(checksum_status) else checksum_status,
        "checksum_column": None if pd.isna(checksum_column) else checksum_column,
        "checksum_expected": None if pd.isna(checksum_expected) else float(checksum_expected),
        "checksum_got": None if pd.isna(checksum_got) else float(checksum_got),
        "checksum_diff": None if pd.isna(checksum_diff) else float(checksum_diff),
        "columns": present_business,
    }

    return {
        "converted": path.name,
        "doc_type": doc_type,
        "row_count": len(df),
        "out_path": str(out_path.relative_to(REPO_ROOT)),
        "shape": shape_applied,
        "evidence": evidence_report,
        "schema_notes": schema_notes,
        "manifest_entry": manifest_entry,
    }


def main(argv=None):
    import argparse
    global DRY_RUN
    parser = argparse.ArgumentParser(description="Convert the raw synthetic xlsx into staging_synthetic/ parquet.")
    parser.add_argument("--dry-run", action="store_true", help="convert and count, write nothing")
    DRY_RUN = parser.parse_args(argv).dry_run

    files = sorted(RAW_SYNTH_DIR.glob("*.xlsx"))
    print(f"Found {len(files)} files in {RAW_SYNTH_DIR}" + ("  [DRY RUN - nothing is written]" if DRY_RUN else ""))

    converted, skipped = [], []
    for f in files:
        result = convert_file(f)
        if result is None:
            continue
        if "skipped" in result:
            skipped.append(result)
        else:
            converted.append(result)

    fragment = {"staged": [r["manifest_entry"] for r in converted],
                "reject": [{"file": s["skipped"], "reason": s["reason"]} for s in skipped]}
    if not DRY_RUN:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "_manifest_fragment.json").write_text(json.dumps(fragment, indent=2, sort_keys=True), encoding="utf-8")

    ev = [r["evidence"] for r in converted + skipped if r.get("evidence")]
    excluded_codes = set().union(*[set(e["excluded_codes"]) for e in ev]) if ev else set()
    print(f"inventory_sign_off real-evidence restriction: {sum(e['excluded_rows'] for e in ev)} rows excluded, "
          f"{len(excluded_codes)} distinct SKU codes with no real evidence, "
          f"{sum(e.get('kept_sku_rows', 0) for e in ev)} SKU rows kept "
          f"(evidence set: {len(REAL_EVIDENCE_SKUS or [])} codes)")

    by_doctype = Counter(r["doc_type"] for r in converted)
    rows_by_doctype = Counter()
    for r in converted:
        rows_by_doctype[r["doc_type"]] += r["row_count"]
    shape_dist = Counter(r["shape"] for r in converted if r["doc_type"] == "inventory_sign_off")

    print()
    print(f"Converted: {len(converted)} / {len(files)}")
    print(f"Skipped:   {len(skipped)}")
    for s in skipped:
        print(f"  SKIPPED {s['skipped']}: {s['reason']}")
    print()
    print("Files by doc_type:", dict(by_doctype))
    print("Rows by doc_type:", dict(rows_by_doctype))
    print("inventory_sign_off shape distribution (files):", dict(shape_dist))
    print()

    all_notes = [(r["converted"], r["schema_notes"]) for r in converted if r["schema_notes"]]
    note_counter = Counter()
    for _, notes in all_notes:
        for n in notes:
            # bucket by note "kind" (strip the specific value list) for a summary count
            kind = n.split(":")[0]
            note_counter[kind] += 1
    print("Schema-note counts (files affected, by note kind):")
    for kind, count in note_counter.most_common():
        print(f"  {kind}: {count} files")

    manifest_path = OUT_DIR / "_manifest_fragment.json"
    print()
    print("Manifest fragment NOT written (dry run)" if DRY_RUN else f"Manifest fragment written to {manifest_path.relative_to(REPO_ROOT)}")
    return converted, skipped


if __name__ == "__main__":
    main()
