"""
analytics.etl.transform — Transform stage (ARCHITECTURE.md §4, §7).

Owns exactly what Extract explicitly does NOT (ARCHITECTURE.md §6.7):
  - Rename / map vocab A/B/C -> canonical fields         (apply_column_map)
  - Choose source-of-truth per fact, drop cross-checks   (filter_source_of_truth)
  - Dedup on the confirmed natural key                   (dedup_facts)
  - Standardize drifting text labels (e.g. discount)     (apply_alias_table)

Config-driven per ARCHITECTURE.md principle #2: mappings live in
config/column_maps/*.yaml and config/alias_tables/*.csv, not hardcoded
per-file logic. This module is generic over any staged (file, sheet)
DataFrame carrying the provenance columns Extract attaches
(ARCHITECTURE.md §6.5): _src_file, _src_sheet, _principal, _region,
_period, _doc_type, _sheet_role, _grain, plus checksum columns.

Anti-fabrication (ARCHITECTURE.md principle #1) applies here too:
this module never fills, imputes, or guesses a value. Rows that can't
be confidently mapped or deduped are routed to a conflicts/ambiguous
report, not silently resolved.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from analytics.etl._coerce import to_decimal
from analytics.etl.extract._shared import MM_YYYY_RE

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"

# config/column_maps/unilever_sku.yaml flags these four fields as raw
# comma-separated / decimal-string TEXT that needs coercion before use
# (its own "TRANSFORM TODO" comments) - apply_column_map only renames
# headers, it never touches cell values. Kept as an explicit list (not
# config-driven) because this is currently the only doc_type needing it;
# revisit if a second doc_type needs the same treatment.
UNILEVER_SKU_NUMERIC_COLUMNS = [
    "sale_quantity_cases", "sale_quantity_pieces", "gsv", "net_amount_inc_tax",
]

# Found 2026-09-14 (Phase 1d, first real canonical load): inventory_sign_off
# (Del Monte) numeric columns were never run through coerce_numeric_columns()
# at all - unlike unilever_sku above, quantity_on_hand/cost/valuation/
# valuation_with_vat passed through raw, whatever dtype Extract produced.
# Surfaced as a real (is_demo=false) load failure: MARCH_2023_INVENTORY_
# SANSAN_PANGASINAN&ILOCOS.xlsx, "PANGASINAN INVENTORY SIGNOFF" sheet, rows
# 93-94 etc (9 rows total) have the literal Excel boolean FALSE - not a
# formula error introduced by this pipeline, confirmed present in the raw
# file itself via openpyxl - in their Valuation/Valuation with VAT cells.
# _coerce_numeric() (used elsewhere in this module, e.g. quantity_pieces
# below) would silently turn Python bool False into 0.0 (bool is an int
# subclass) - that is fabrication, not correction: a broken source cell is
# not evidence the true valuation was zero. coerce_numeric_columns() (via
# to_decimal()) is the correct tool here: Decimal(str(False)) raises and
# is caught, yielding null, not a guessed number - same principle already
# applied to unilever_sku above.
DELMONTE_INVENTORY_NUMERIC_COLUMNS = [
    "quantity_on_hand", "cost", "valuation", "valuation_with_vat",
]

PROVENANCE_COLUMNS = [
    "_src_file", "_src_sheet", "_header_row", "_row_ordinal", "_principal",
    "_region", "_period", "_doc_type", "_sheet_role", "_grain",
    "_checksum_status", "_checksum_column", "_checksum_expected", "_checksum_got", "_checksum_diff",
]


def _normalize_header(name: str) -> str:
    """Case/whitespace-insensitive key for matching raw headers to config
    entries. Does NOT change the actual column name written out — only
    used to look up which canonical field a raw header belongs to."""
    return re.sub(r"\s+", " ", str(name).strip()).lower()


@dataclass
class ColumnMap:
    """A loaded column_maps/<doc_type>.yaml, indexed for fast lookup."""
    doc_type: str
    canonical_to_raw: dict[str, list[str]]
    raw_to_canonical: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        for canonical, raw_variants in self.canonical_to_raw.items():
            for raw in raw_variants:
                key = _normalize_header(raw)
                if key in self.raw_to_canonical and self.raw_to_canonical[key] != canonical:
                    raise ValueError(
                        f"column_maps/{self.doc_type}.yaml: raw header '{raw}' maps to "
                        f"both '{self.raw_to_canonical[key]}' and '{canonical}' — ambiguous map."
                    )
                self.raw_to_canonical[key] = canonical


def load_column_map(doc_type: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> ColumnMap:
    path = config_dir / "column_maps" / f"{doc_type}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No column map for doc_type='{doc_type}' at {path}. "
            f"Add config/column_maps/{doc_type}.yaml before transforming this doc_type."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ColumnMap(doc_type=doc_type, canonical_to_raw=raw)


@dataclass
class ColumnMapReport:
    doc_type: str
    mapped: dict[str, str]           # raw header -> canonical field, actually applied
    unmapped_raw: list[str]          # raw headers present in df but not in the map
    unmapped_canonical: list[str]    # canonical fields in the map but absent from df
    # 2026-08 fix (backlog story #11 regression): rows where more than one
    # raw-vocab variant of the same canonical field was simultaneously
    # non-null - see _coalesce_duplicate_columns. Empty in the normal case
    # (one file/sheet at a time); a real conflict here means two different
    # real values were fighting for the same canonical field on the same
    # row, and the first (leftmost) one silently won - never expected in
    # practice (each real file uses exactly one vocabulary), so any entry
    # here is worth a human look, not something this function resolves.
    duplicate_column_conflicts: list[dict] = field(default_factory=list)


def _coalesce_duplicate_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """When a batch spans more than one raw-header vocabulary for the same
    canonical field (e.g. Sales Register's "Invoice Num"/"REFNBR"/
    "REFERENCE #" all -> invoice_num), apply_column_map's rename produces
    one real column per vocab variant with duplicate labels - each file
    only ever populates its own vocabulary's column, leaving the others
    NaN for that file's rows (pd.concat upstream produces the union of
    all raw columns across files). Renaming them all to one canonical
    name creates duplicate-labeled columns, which breaks any groupby/
    dedup downstream (confirmed: real staging/sales_register/*.parquet
    combined across 2023-2025 crashes dedup_facts with "Grouper for
    'invoice_num' not 1-dimensional" before this fix).

    Coalesces by taking, per row, the first non-null value across the
    duplicate-named columns - since each row comes from exactly one
    source file with exactly one active vocabulary, at most one of the
    duplicate columns should ever be non-null for a given row. This is
    resolving a rename-induced artifact, not guessing between two real
    differing values - but if a row DOES have more than one non-null
    value in the group (never observed, but not something to silently
    paper over if it ever happens), that row is reported as a conflict,
    matching dedup_facts' existing anti-fabrication pattern."""
    if not df.columns.duplicated().any():
        return df, []

    out = df.copy()
    conflicts: list[dict] = []
    for dup_name in out.columns[out.columns.duplicated()].unique():
        dup_block = out.loc[:, out.columns == dup_name]
        non_null_counts = dup_block.notna().sum(axis=1)
        conflicting = int((non_null_counts > 1).sum())
        if conflicting:
            conflicts.append({"canonical": dup_name, "conflicting_row_count": conflicting})
        coalesced = dup_block.bfill(axis=1).iloc[:, 0]
        out = out.loc[:, out.columns != dup_name]
        out[dup_name] = coalesced
    return out, conflicts


def apply_column_map(
    df: pd.DataFrame, doc_type: str, config_dir: Path = DEFAULT_CONFIG_DIR
) -> tuple[pd.DataFrame, ColumnMapReport]:
    """Rename raw headers to canonical fields for one doc_type. Provenance
    columns (the exact names in PROVENANCE_COLUMNS) pass through untouched.
    A raw header not found in the map is left as-is and reported — never
    dropped silently (anti-fabrication: an unrecognized column might carry
    real data).

    Skip is by exact membership in PROVENANCE_COLUMNS, not a leading-"_"
    prefix check: Extract's own placeholder names for genuinely unlabeled
    columns (e.g. "__col0__", "__col1__" - see extract/_shared.py's
    header-recovery) also start with "_", but they carry real business
    data, not provenance. A prefix check silently excluded them from
    mapping entirely - config/column_maps/sell_out.yaml's category_path
    (mapped from "__col0__") and inventory_sign_off.yaml's
    sku_description_raw (mapped from "__col1__") could never actually be
    renamed, which blocked SellOut_Fact and Inventory_Fact's sku_code key
    completely. Confirmed via a real transform_driver run before this fix:
    34/34 real sell_out sheets and 41/41 blocked inventory sheets, both
    citing their natural key column as missing after this function ran."""
    cmap = load_column_map(doc_type, config_dir)

    rename = {}
    mapped = {}
    unmapped_raw = []
    for col in df.columns:
        if col in PROVENANCE_COLUMNS:
            continue
        key = _normalize_header(col)
        if key in cmap.raw_to_canonical:
            canonical = cmap.raw_to_canonical[key]
            rename[col] = canonical
            mapped[col] = canonical
        else:
            unmapped_raw.append(col)

    out = df.rename(columns=rename)
    out, duplicate_column_conflicts = _coalesce_duplicate_columns(out)
    unmapped_canonical = [c for c in cmap.canonical_to_raw if c not in out.columns]

    report = ColumnMapReport(
        doc_type=doc_type, mapped=mapped,
        unmapped_raw=unmapped_raw, unmapped_canonical=unmapped_canonical,
        duplicate_column_conflicts=duplicate_column_conflicts,
    )
    return out, report


# Extract's own "I couldn't infer this" placeholders per provenance field
# (extract/_shared.py: infer_sheet_region returns "unknown" when neither
# sheet name nor file path matches a region pattern; principal inference
# returns "ambiguous" when path and content both fail to disambiguate —
# confirmed present in real staged data via `_principal` value counts).
# These are sentinels, not real values — copying one into the bare column
# would fabricate a region/principal that was never actually determined.
_PROVENANCE_PLACEHOLDER_VALUES = {
    "region": {"unknown"},
    "principal": {"ambiguous"},
}


def coerce_is_demo_column(df: pd.DataFrame) -> pd.DataFrame:
    """Coerces `is_demo` to a real boolean, in place of whatever raw type
    the source cell produced. Found 2026-09-14 (Phase 1 step 5, discovered
    while investigating an extract-vs-transform row-count reconciliation
    mismatch that led to a full fresh Extract re-run): every real cell
    checked in `data/raw/Synthetic Data/PURCHASE_ORDER_*.xlsx` and
    `.../INVENTORY_SIGN_OFF_*.xlsx` carries the literal STRING `"True"`,
    not a real Excel boolean — confirmed via direct staged-parquet dtype
    inspection, only two forms found across both families:
    `('True', str)` and `(np.True_, bool)`, no `False` variant at all
    (consistent with the established convention that `is_demo` is only
    ever present as a column on synthetic rows — real rows lack it
    entirely, never carry an explicit False).

    THIS WAS SILENTLY BREAKING every `df['is_demo'] != True` /
    `df['is_demo'] == True` filter used throughout this codebase and its
    scratchpad analyses: pandas/Python `'True' != True` is `True` (they are
    different types), so string-typed synthetic rows were being counted as
    REAL by every such filter — confirmed: 1,909 synthetic
    `purchase_order` rows and 14,662 synthetic `inventory_sign_off` rows
    (exactly half of each family's synthetic volume — the other half
    already had a real bool) were silently misclassified as real data
    before this fix. `sales_register` and `sell_out`'s synthetic rows were
    NOT affected (checked: uniformly real bool `True` in both).

    Applied here, in Transform, right after apply_column_map() and before
    anything reads `is_demo` for real/demo classification — not patched at
    each call site, so no analysis (in this codebase or a scratchpad
    script) can silently reproduce this bug by filtering before this
    function runs.

    SECOND FIX, same function, found 2026-09-14 (Phase 1 step 5d, the first
    real, non-dry-run load): rows with a genuinely ABSENT/null `is_demo`
    cell (real rows, by the documented convention this docstring already
    states above — "real rows lack it entirely") were left as pandas `NA`
    rather than filled `False`. That is correct for the `is_demo != True`
    filtering this module's callers already do (NA reads as "not True"
    there either way, so no analysis result changes), but it broke the
    canonical load the first time real+demo rows shared one INSERT batch:
    `load_to_supabase()` includes `is_demo` in that batch's column list
    (because SOME rows in it are True/False), so every row - including the
    NA ones - gets an EXPLICIT `is_demo=NULL` sent to Postgres, which
    violates `is_demo BOOLEAN NOT NULL DEFAULT false` (an explicit NULL
    always overrides a column DEFAULT; DEFAULT only applies when a column
    is omitted from the INSERT entirely, which is what the "real rows omit
    is_demo, the DEFAULT handles it" convention assumed - true for a
    single-family, single-demo-status batch, false once real and demo rows
    from the SAME family load together). Filling NA with `False` here
    states the ALREADY-DOCUMENTED fact (absent = real = not demo)
    explicitly instead of leaving it implicit - not a new judgment call,
    not fabrication of an unknown value, just making a known fact
    insertable. `caught via the actual first real-load attempt against
    unilever_sku_demand_fact - NotNullViolation on a real 2023-01 La Union
    row (sku_code 20292808), not a hypothetical."""
    if "is_demo" not in df.columns:
        return df
    out = df.copy()
    col = out["is_demo"]
    is_true = col.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    out["is_demo"] = False
    out.loc[is_true, "is_demo"] = True
    return out


def backfill_provenance_fields(df: pd.DataFrame, fields: tuple[str, ...] = ("principal", "region")) -> pd.DataFrame:
    """For each canonical field in `fields`, fill any row where the real
    mapped column is missing entirely or NULL on that row from the
    matching provenance column Extract always attaches (_<field>) —
    except where the provenance value is itself a "couldn't determine
    this" placeholder (see _PROVENANCE_PLACEHOLDER_VALUES), which is left
    NULL rather than copied. Generalizes the existing
    snapshot_date-from-_period pattern in transform_fact() below instead
    of special-casing per doc_type.

    Every fact table in analytics/db/schema.sql declares a bare
    `principal TEXT NOT NULL` — Extract only ever produces `_principal`
    (provenance), and load.py's upsert intentionally skips underscore-
    prefixed columns, so without this the NOT NULL constraint fails at
    Load. A real mapped column's own non-null values are never
    overwritten — only its per-row nulls are filled. Must run after
    apply_column_map (so real values always win) and before dedup_facts
    (natural keys reference the bare field names).

    Per-row fallback (not just whole-column) matters in practice: real
    Sales_Fact data has region blank in ~38% of rows because the raw
    source cell itself ("Town Display"/"AREA") is blank, while Extract's
    own `_region` provenance tag is 0% null for the same rows and
    recovers most of the gap — see DATABASE_ARCHITECTURE.md's
    natural-key null-rate note."""
    out = df.copy()
    for field_name in fields:
        prov_col = f"_{field_name}"
        if prov_col not in out.columns:
            continue
        prov_values = out[prov_col]
        placeholders = _PROVENANCE_PLACEHOLDER_VALUES.get(field_name)
        if placeholders:
            prov_values = prov_values.where(~prov_values.isin(placeholders), None)
        if field_name not in out.columns:
            out[field_name] = prov_values
        else:
            out[field_name] = out[field_name].where(out[field_name].notna(), prov_values)
    return out


def coerce_numeric_columns(df: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Parses each named column via the shared to_decimal() helper
    (analytics.etl._coerce — the same comma-stripping/decimal-quantizing
    logic Extract's checksum pass already uses, reused rather than
    duplicated so the two stages can't drift apart on what "numeric"
    means). Never drops a row: a cell that fails to parse becomes null
    (not zero, not guessed), and that column's name is returned in the
    second tuple element for the QC report — never a silent failure."""
    out = df.copy()
    unparseable_columns: list[str] = []
    for col in columns:
        if col not in out.columns:
            continue
        original_null = out[col].isna()
        parsed = out[col].map(lambda v: None if pd.isna(v) else to_decimal(v))
        newly_null = parsed.isna() & ~original_null
        if newly_null.any():
            unparseable_columns.append(col)
        out[col] = parsed
    return out, unparseable_columns


def load_alias_table(name: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> dict[str, str]:
    """Load a two-column raw_label,canonical_label CSV into a lookup dict."""
    path = config_dir / "alias_tables" / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"No alias table '{name}' at {path}.")
    table: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            table[_normalize_header(row["raw_label"])] = row["canonical_label"]
    return table


def apply_alias_table(
    df: pd.DataFrame, column: str, alias_name: str, config_dir: Path = DEFAULT_CONFIG_DIR
) -> pd.DataFrame:
    """Standardize a free-text label column (e.g. discount_rate_label) via
    an alias table. Values not found in the table are left untouched and
    should be surfaced in QC — never guessed at."""
    if column not in df.columns:
        return df
    table = load_alias_table(alias_name, config_dir)
    out = df.copy()
    out[column] = out[column].map(
        lambda v: table.get(_normalize_header(v), v) if pd.notna(v) else v
    )
    return out


# Matches the leading SKU-code token in inventory_signoff's unsplit
# "sku_description_raw" cells, e.g. "9DMR56831 DM QUICK N EASY MECHADO
# SAUCE (Royce)" -> code="9DMR56831". Tested against ~480 real samples
# pulled from profiling/sheet_profiles/*INVENTOR*.json: correctly splits
# the "code + name" rows and correctly REFUSES to match bare numeric IDs
# (the unrelated 2025-era leading ID column, e.g. "58740") and bare
# codes with no name text (e.g. "9DMS03748") rather than guessing at
# them - those come back as unmatched, per anti-fabrication.
_SKU_CODE_RE = re.compile(r"^\s*([A-Z0-9]{4,})\s+(.+?)\s*$")


@dataclass
class SkuSplitReport:
    input_rows: int
    matched: int
    unmatched: int


def split_sku_description(
    df: pd.DataFrame, column: str = "sku_description_raw",
    code_col: str = "sku_code", name_col: str = "product_name",
) -> tuple[pd.DataFrame, SkuSplitReport]:
    """Split inventory_signoff's combined 'SKU code + product name' cell
    into sku_code / product_name. A cell that doesn't match the expected
    shape (bare numeric ID, bare code with no name, blank, etc.) is left
    as null in both output columns and counted in the report - never
    guessed at (ARCHITECTURE.md principle #1)."""
    out = df.copy()
    if column not in out.columns:
        out[code_col] = pd.NA
        out[name_col] = pd.NA
        return out, SkuSplitReport(input_rows=len(out), matched=0, unmatched=0)

    codes, names, matched = [], [], 0
    for val in out[column]:
        if pd.isna(val):
            codes.append(pd.NA)
            names.append(pd.NA)
            continue
        m = _SKU_CODE_RE.match(str(val))
        if m and any(ch.isdigit() for ch in m.group(1)):
            codes.append(m.group(1))
            names.append(m.group(2))
            matched += 1
        else:
            codes.append(pd.NA)
            names.append(pd.NA)

    out[code_col] = codes
    out[name_col] = names
    report = SkuSplitReport(input_rows=len(out), matched=matched, unmatched=len(out) - matched)
    return out, report


# Real inventory_sign_off data has FOUR shapes, not the two documented in
# column_maps/inventory_sign_off.yaml's original comment (found 2026-08,
# Phase 1b of the synthetic-staging-conversion audit - see
# reports/SYNTHETIC_STAGING_CONVERSION.md for the full derivation against
# all 41 real staged files):
#   A (25/41 files) - __col0__ only, combined "CODE DESCRIPTION" string.
#   B (13/41 files) - __col0__ is a redundant bare-numeric SKU suffix;
#     __col1__ carries the real combined "CODE DESCRIPTION" string.
#   C (2/41 files)  - real labeled "ITEM CODE"/"ITEM DESCRIPTION" headers,
#     no split needed at all.
#   D (1/41 files)  - one real file (August 2023, Pangasinan "ACTUAL"
#     export) where __col1__ has real description text but the alpha SKU
#     prefix is absent from the source entirely (confirmed 173/173 rows) -
#     not a parsing failure, the code genuinely isn't in this file.
# A single column-map YAML alias list can't route __col0__ vs __col1__ vs
# "ITEM CODE" to sku_description_raw conditionally per sheet - adding
# __col0__ as a second alias for sku_description_raw would make Shape B
# rows (which have BOTH __col0__ and __col1__ non-null at once) hit
# _coalesce_duplicate_columns()'s first-non-null-wins behavior and silently
# take __col0__'s bare numeric fragment over __col1__'s real combined
# string, while also flooding duplicate_column_conflicts with false
# positives for every Shape B row. Dispatch happens here instead, in code,
# per (src_file, src_sheet) sheet - not per file, since the real 2025-era
# workbooks carry a third "Sheet1" (Shape A) alongside two region-named
# sheets (Shape B) in the very same file.
_INVENTORY_SKU_PREFIX_RE = re.compile(r"^\s*9D[A-Z]{2}\d{4,6}\s")


def _classify_inventory_sku_shape(group: pd.DataFrame) -> str:
    """Classify one (src_file, src_sheet) sheet's real inventory_sign_off
    shape from its own data - never from filename/period, so this stays
    correct if a future real file breaks the date-era pattern observed so
    far. Called AFTER apply_column_map(), not on raw Extract output:
    column_maps/inventory_sign_off.yaml already renames __col1__ to
    sku_description_raw (that alias is Shape B/D's only working path
    today), so by this point __col1__ no longer exists under that name -
    checking for sku_description_raw's presence is what actually detects
    B/D, not a raw "__col1__" column lookup. __col0__ is never renamed by
    the YAML (deliberately, see the note above route_inventory_sku_shapes)
    so it's still __col0__ here, unlike __col1__.

    Shape C wins if present (self-describing, unambiguous). Shape B vs D
    is distinguished by content: both have real sku_description_raw
    values (from __col1__), but D's rows never carry the alpha SKU-code
    prefix anywhere in that sheet."""
    if "ITEM CODE" in group.columns and group["ITEM CODE"].notna().any():
        return "C"
    has_col1_mapped = "sku_description_raw" in group.columns and group["sku_description_raw"].notna().any()
    if has_col1_mapped:
        candidates = group["sku_description_raw"].dropna().astype(str)
        candidates = candidates[~candidates.str.strip().str.upper().isin({"TOTAL", "DESCRIPTION"})]
        if candidates.empty:
            return "B"
        match_rate = candidates.apply(lambda v: bool(_INVENTORY_SKU_PREFIX_RE.match(v))).mean()
        return "B" if match_rate > 0.5 else "D"
    if "__col0__" in group.columns and group["__col0__"].notna().any():
        return "A"
    return "UNKNOWN"


@dataclass
class InventoryShapeRoutingReport:
    shape_counts: dict          # rows per detected shape, e.g. {"A": 612, "B": 1885, ...}
    shape_a_routed: int         # rows where __col0__ was copied into sku_description_raw


def route_inventory_sku_shapes(df: pd.DataFrame) -> tuple[pd.DataFrame, InventoryShapeRoutingReport]:
    """Template-version-aware dispatch for inventory_sign_off's combined
    SKU-code+description cell (the fix column_maps/inventory_sign_off.yaml's
    own comment names but leaves undone: "branch on column count or
    presence of __col1__"). Must run before split_sku_description() so
    Shape A rows have a populated sku_description_raw to split at all -
    previously only Shape B's __col1__ was ever routed there (via the
    YAML), so Shape A (25/41 real files, 92/92 synthetic files) produced
    sku_code=NULL for every row even though the regex that could split it
    already existed and already worked."""
    out = df.copy()
    if not {"_src_file", "_src_sheet"}.issubset(out.columns):
        out["_inventory_sku_shape"] = "UNKNOWN"
        return out, InventoryShapeRoutingReport(shape_counts={}, shape_a_routed=0)

    shape_by_row = pd.Series("UNKNOWN", index=out.index, dtype=object)
    for _, idx in out.groupby(["_src_file", "_src_sheet"], dropna=False).groups.items():
        shape_by_row.loc[idx] = _classify_inventory_sku_shape(out.loc[idx])
    out["_inventory_sku_shape"] = shape_by_row

    shape_a_routed = 0
    mask_a = shape_by_row == "A"
    if "__col0__" in out.columns and mask_a.any():
        if "sku_description_raw" not in out.columns:
            out["sku_description_raw"] = pd.NA
        out.loc[mask_a, "sku_description_raw"] = out.loc[mask_a, "__col0__"]
        shape_a_routed = int(mask_a.sum())

    return out, InventoryShapeRoutingReport(
        shape_counts=shape_by_row.value_counts().to_dict(),
        shape_a_routed=shape_a_routed,
    )


@dataclass
class DateReformatReport:
    input_rows: int
    reformatted: int
    unparsable: int


def reformat_calendar_month(
    df: pd.DataFrame, column: str = "calendar_month",
) -> tuple[pd.DataFrame, DateReformatReport]:
    """Reformats unilever_sku's raw 'MM.YYYY' calendar_month cells (e.g.
    "01.2023") into the project's 'YYYY-MM' period-key convention
    (DEC-12), matching Unilever_SKU_Demand_Fact.calendar_month's declared
    format and natural key. Extract's own row_periods_from_calendar_month()
    (extract/_shared.py) already parses this same raw value into the
    internal _period provenance column per row — this reuses the identical
    MM_YYYY_RE pattern rather than a second copy, but operates on the
    visible, column-mapped business field instead.

    A cell that doesn't match 'MM.YYYY' is left as null and counted, never
    guessed (ARCHITECTURE.md principle #1)."""
    out = df.copy()
    if column not in out.columns:
        return out, DateReformatReport(input_rows=len(out), reformatted=0, unparsable=0)

    reformatted, unparsable = 0, 0
    values = []
    for v in out[column]:
        if pd.isna(v):
            values.append(pd.NA)
            continue
        m = MM_YYYY_RE.match(str(v).strip())
        if m:
            month, year = m.groups()
            values.append(f"{year}-{month}")
            reformatted += 1
        else:
            values.append(pd.NA)
            unparsable += 1

    out[column] = values
    report = DateReformatReport(input_rows=len(out), reformatted=reformatted, unparsable=unparsable)
    return out, report


def _snapshot_date_from_period(period):
    """Inventory_Fact.snapshot_date (DEC-12): these exports are monthly —
    there is no real day-of-month anywhere in the source, so this returns
    a documented SYNTHETIC first-of-month marker, not a reported date.
    Extract's explicit "unknown" sentinel (unparseable _period) returns
    None rather than fabricating a date from it."""
    if period is None or (isinstance(period, float) and pd.isna(period)) or period == "unknown":
        return None
    try:
        return pd.Period(period, freq="M").start_time.date()
    except ValueError:
        return None


def _coerce_numeric(v):
    """Best-effort float for a quantity/pack_size cell that may arrive as
    a comma-formatted string (e.g. "24,190") rather than a native number —
    Extract's own coercion (extract/_shared.py::_to_number) only fires for
    string cells whose COLUMN NAME matches its money/quantity regexes, and
    "Pack Size" matches neither, so it can still reach here as text.
    Returns None (never guesses) if the cell isn't a real number."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class QuantityReconciliationReport:
    """QC cross-check output for normalize_quantities() — never used to
    pick a value, only to surface disagreement for a human look, same
    anti-fabrication stance as DedupReport.conflicting_groups."""
    input_rows: int
    checked_rows: int          # rows where both the trusted and cross-check values were present
    mismatched: list[dict]     # rows where they disagreed beyond tolerance


def normalize_quantities(
    df: pd.DataFrame, doc_type: str, tolerance: float = 0.01,
) -> tuple[pd.DataFrame, QuantityReconciliationReport | None]:
    """Normalize quantity fields to a comparable unit (pieces) per
    principal (units-of-measure story, ARCHITECTURE.md DEC-11).

    unilever_sku: quantity_sold is set from the reported
    sale_quantity_pieces column directly — sale_quantity_cases x pack_size
    is only ~84%-consistent with it on real data (profiled evidence), so
    it is never used to override the reported figure, only to flag
    disagreement for review.

    inventory_sign_off: quantity_pieces is set from the reported pieces
    (PCS) column directly. cases/packages (CAS/PKG) are deliberately NOT
    converted — no confirmed pack_size exists anywhere in Del Monte's
    files, so a conversion here would be fabricated, not derived.

    Any other doc_type is a no-op passthrough.
    """
    if doc_type == "unilever_sku":
        out = df.copy()
        pieces = out["sale_quantity_pieces"].map(_coerce_numeric) if "sale_quantity_pieces" in out.columns else pd.Series([None] * len(out), index=out.index)
        cases = out["sale_quantity_cases"].map(_coerce_numeric) if "sale_quantity_cases" in out.columns else pd.Series([None] * len(out), index=out.index)
        pack_size = out["pack_size"].map(_coerce_numeric) if "pack_size" in out.columns else pd.Series([None] * len(out), index=out.index)

        out["quantity_sold"] = pieces

        mismatched = []
        checked_rows = 0
        for idx in out.index:
            p, c, ps = pieces.get(idx), cases.get(idx), pack_size.get(idx)
            if p is None or c is None or ps is None:
                continue
            checked_rows += 1
            expected = c * ps
            denom = max(abs(p), abs(expected), 1.0)
            if abs(expected - p) / denom > tolerance:
                mismatched.append({
                    "row": idx, "reported_pieces": p, "cases": c,
                    "pack_size": ps, "expected_pieces": expected,
                })

        report = QuantityReconciliationReport(
            input_rows=len(out), checked_rows=checked_rows, mismatched=mismatched,
        )
        return out, report

    if doc_type == "inventory_sign_off":
        out = df.copy()
        if "pieces" in out.columns:
            out["quantity_pieces"] = out["pieces"].map(_coerce_numeric)
        else:
            out["quantity_pieces"] = None
        return out, None

    return df, None


@dataclass
class SourceOfTruthRule:
    doc_type: str
    system_of_record_role: list[str]
    cross_check_roles: list[str]
    natural_key: list[str] | None   # None = deliberately unconfirmed, see source_of_truth.yaml
    # Other _doc_type values (not _sheet_role values — cross_check_roles is
    # scoped to roles *within* doc_type above) that are a demoted duplicate
    # view of this same fact, e.g. daily_sales_report vs sales_register —
    # both carry _sheet_role="data", so cross_check_roles can't express the
    # distinction. NOT YET enforced by filter_source_of_truth (T4 scope,
    # building the Transform driver) — parsed here so it isn't silently
    # dropped by callers that read it directly off the rule.
    cross_check_doc_types: list[str] = field(default_factory=list)
    # Cross-check sheet roles whose rows are kept when their natural key
    # appears on NO system-of-record sheet (2026-09-21, completeness audit
    # F4): the Oct/Nov 2025 sales registers carry 57 invoices (net
    # 559,369.32) only on the "ONE PAGER" sheet. Dropping the whole role as
    # a duplicate view lost them. See rescue_cross_check_orphans().
    orphan_rescue_roles: list[str] = field(default_factory=list)


def load_source_of_truth(fact: str, principal: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> SourceOfTruthRule:
    path = config_dir / "source_of_truth.yaml"
    rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if fact not in rules:
        raise KeyError(f"No source_of_truth rule for fact='{fact}' in {path}")
    fact_rules = rules[fact]
    entry = fact_rules.get(principal) or fact_rules.get("both")
    if entry is None:
        raise KeyError(f"No source_of_truth rule for fact='{fact}', principal='{principal}' in {path}")
    role = entry["system_of_record_role"]
    role = role if isinstance(role, list) else [role]
    return SourceOfTruthRule(
        doc_type=entry["doc_type"],
        system_of_record_role=role,
        cross_check_roles=entry.get("cross_check_roles", []),
        natural_key=entry.get("natural_key"),  # may be None - see anti-fabrication note below
        cross_check_doc_types=entry.get("cross_check_doc_types", []),
        orphan_rescue_roles=entry.get("orphan_rescue_roles", []),
    )


def filter_source_of_truth(df: pd.DataFrame, fact: str, principal: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> pd.DataFrame:
    """Keep only rows whose _sheet_role is the system of record for this
    fact/principal per DEC-04. Drops cross-check views (e.g. INVOICE REG
    when RAW DATA is present) so downstream never double-counts.

    Also drops cross_check_doc_types rows (2026-08, Transform
    reconciliation story #16) — a different _doc_type that is a demoted
    duplicate view of this same fact (e.g. daily_sales_report vs
    sales_register, both carrying _sheet_role="data", so the role check
    alone can't tell them apart). Previously parsed onto SourceOfTruthRule
    but never enforced here, per that field's own docstring — closing
    that gap now, before it's a live double-count instead of a documented
    one (see the _shared.py note: no daily_sales_report rows exist in the
    current corpus, so this had zero observable effect until now, but the
    guard must exist for when real ones show up)."""
    rule = load_source_of_truth(fact, principal, config_dir)
    if "_sheet_role" not in df.columns:
        raise KeyError("DataFrame missing '_sheet_role' — did this come from Extract staging?")
    out = df
    if rule.cross_check_doc_types and "_doc_type" in out.columns:
        out = out[~out["_doc_type"].isin(rule.cross_check_doc_types)]
    return out[out["_sheet_role"].isin(rule.system_of_record_role)].copy()


def rescue_cross_check_orphans(
    df: pd.DataFrame, sot_df: pd.DataFrame, rule: SourceOfTruthRule, config_dir: Path = DEFAULT_CONFIG_DIR,
) -> tuple[pd.DataFrame, dict]:
    """Adds back the rows of rule.orphan_rescue_roles sheets whose natural key
    is fully non-null and present on no system-of-record sheet. A cross-check
    view is only a duplicate for the keys it shares with the system of
    record; a key that exists nowhere else is real data with one source.
    Returns the RAW rows (sot_df + rescued), so the rescued rows go through
    the same column map, footer checks and dedup as every other row."""
    report = {"roles": rule.orphan_rescue_roles, "candidate_rows": 0, "rescued_rows": 0}
    if not rule.orphan_rescue_roles or "_sheet_role" not in df.columns:
        return sot_df, report
    candidates = df[df["_sheet_role"].isin(rule.orphan_rescue_roles)]
    if rule.cross_check_doc_types and "_doc_type" in candidates.columns:
        candidates = candidates[~candidates["_doc_type"].isin(rule.cross_check_doc_types)]
    report["candidate_rows"] = len(candidates)
    if candidates.empty:
        return sot_df, report

    def _keys(raw: pd.DataFrame) -> pd.DataFrame:
        mapped, _ = apply_column_map(raw, rule.doc_type, config_dir)
        mapped = backfill_provenance_fields(mapped)
        missing = [k for k in rule.natural_key if k not in mapped.columns]
        if missing:
            raise KeyError(f"Natural key column(s) missing after column map: {missing}")
        return mapped[rule.natural_key]

    def _as_tuples(keys: pd.DataFrame) -> pd.Series:
        return keys.astype(str).apply(lambda r: tuple(v.strip() for v in r), axis=1)

    sot_keys = _keys(sot_df)
    known = set(_as_tuples(sot_keys[sot_keys.notna().all(axis=1)]))
    cand_keys = _keys(candidates)
    resolvable = cand_keys.notna().all(axis=1)
    orphan_mask = resolvable & ~_as_tuples(cand_keys).isin(known)
    rescued = candidates.loc[orphan_mask[orphan_mask].index]
    report["rescued_rows"] = len(rescued)
    if rescued.empty:
        return sot_df, report
    return pd.concat([sot_df, rescued]), report


# Sheets that keep the WORKBOOK's _period (H1, Yuan 2026-09-22). This hidden
# sheet holds 578 September-2024 invoices copied into six 2025 workbooks; public
# reports them under April 2025 and they stay there, pending SSM, until SSM says
# what the sheet is. 14 of them carry the remark FAKE BOOKING and are
# quarantined instead (flag_source_quarantine below).
PERIOD_FROM_INVOICE_DATE_EXEMPT_SHEETS = {"PANGASINAN SALES REGISTER (2)"}


def period_from_invoice_date(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Sets _period to the invoice's own month (2026-09-21, completeness audit
    F5). _period arrives as the month of the WORKBOOK a row was read from,
    which is not always the month of the invoice. Rows whose invoice_date
    does not parse keep the workbook's _period - never a guessed month - and
    so does every row of a sheet in PERIOD_FROM_INVOICE_DATE_EXEMPT_SHEETS."""
    report = {"rows": len(df), "period_changed": 0, "unparseable_invoice_date": 0, "exempt_sheet_rows": 0}
    if "invoice_date" not in df.columns or "_period" not in df.columns or df.empty:
        return df, report
    parsed = pd.to_datetime(df["invoice_date"], errors="coerce")
    invoice_month = parsed.dt.strftime("%Y-%m")
    exempt = (df["_src_sheet"].isin(PERIOD_FROM_INVOICE_DATE_EXEMPT_SHEETS) if "_src_sheet" in df.columns
              else pd.Series(False, index=df.index))
    report["exempt_sheet_rows"] = int(exempt.sum())
    use = parsed.notna() & ~exempt
    changed = use & (invoice_month != df["_period"])
    report["period_changed"] = int(changed.sum())
    report["unparseable_invoice_date"] = int(parsed.isna().sum())
    out = df.copy()
    out.loc[use, "_period"] = invoice_month[use]
    return out, report


QUARANTINE_REASON_COLUMN = "_quarantine_reason"

# Source rows Yuan ruled must not load. Transform only MARKS them
# (QUARANTINE_REASON_COLUMN); scripts/run_canonical_load.py removes the marked
# rows after dedup and writes them to etl_quarantine with their raw values.
#   H1 (2026-09-22): the 14 invoices remarked FAKE BOOKING on the hidden
#       "PANGASINAN SALES REGISTER (2)" sheet (2,903,959.74).
#   D12 (2026-09-22): the 18 September-2025 purchases whose Tax and Net Amount
#       cells are August's (untaxed + tax != net). Limited to 2025-09: 14 real
#       2024-01 rows fail the same arithmetic and are an open item, not ruled on.
FAKE_BOOKING_SHEET = "PANGASINAN SALES REGISTER (2)"


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


def flag_source_quarantine(df: pd.DataFrame, doc_type: str) -> tuple[pd.DataFrame, dict]:
    out = df.copy()
    reason = pd.Series(None, index=out.index, dtype=object)
    real = (out["is_demo"] != True) if "is_demo" in out.columns else pd.Series(True, index=out.index)  # noqa: E712
    if doc_type == "sales_register" and "REMARKS" in out.columns and "_src_sheet" in out.columns:
        fake = real & (out["_src_sheet"] == FAKE_BOOKING_SHEET) & (
            out["REMARKS"].astype("string").str.strip().str.upper() == "FAKE BOOKING")
        reason[fake.fillna(False).astype(bool)] = "source remark: FAKE BOOKING"
    elif doc_type == "purchase_order" and "_period" in out.columns:
        stale = real & (out["_period"] == "2025-09") & (
            (_num(out, "untaxed_amount") + _num(out, "tax_amount") - _num(out, "net_amount")).abs() > 0.01)
        reason[stale.fillna(False).astype(bool)] = "stale cells: untaxed + tax != net; Net Amount copied from August"
    out[QUARANTINE_REASON_COLUMN] = reason
    return out, {"marked": int(reason.notna().sum())}


def flag_sellout_tax_inclusive(raw_df: pd.DataFrame) -> pd.Series:
    """X2 (2026-09-22). Read BEFORE the column map, which coalesces both
    amount headers into net_amount: TRUE where the row's only amount is
    "Total With Tax" (the August 2023 sheets have no other), FALSE where
    "Total Without Tax" is present, NULL where neither is."""
    def col(name):
        hits = [c for c in raw_df.columns if _normalize_header(c) == name]
        return raw_df[hits[0]] if hits else pd.Series(np.nan, index=raw_df.index)
    without_tax, with_tax = col("total without tax"), col("total with tax")
    flag = pd.Series(None, index=raw_df.index, dtype=object)
    flag[without_tax.isna() & with_tax.notna()] = True
    flag[without_tax.notna()] = False
    return flag


# X3/X4 (2026-09-22): invoice totals, never combined (no SKU, no pack size).
INVOICE_QUANTITY_COLUMNS = ["quantity_cases", "quantity_pieces"]


@dataclass
class DedupReport:
    input_rows: int
    output_rows: int
    duplicate_groups: int
    conflicting_groups: list[dict]   # same key, differing non-key values — needs a human look
    quarantined: list[dict] = field(default_factory=list)
    # rows with a null natural-key column, reported individually — never
    # grouped with each other. See dedup_facts()'s docstring.


def _canonical_cell(value):
    """One comparable form per cell, so the same number read as 60764.48,
    Decimal('60764.48') or '60764.48 ' is not mistaken for a disagreement."""
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal, np.number)):
        return round(float(value), 6)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).isoformat()
    text_value = str(value).strip()
    try:
        return round(float(text_value), 6)
    except ValueError:
        return text_value


def natural_key_series(df: pd.DataFrame, natural_key: list[str]) -> list[pd.Series]:
    """The key columns as groupby keys, with every date-like cell as a
    pd.Timestamp. Needed once a date joined a natural key (purchase,
    migration 0025): real files give invoice_date as Timestamp, the synthetic
    ones as datetime.date, and pandas can neither sort nor equate the two -
    the same day would split into two groups, or the groupby would raise.
    Callers must pass sort=False (a key column may still mix text and dates)."""
    def _cell(value):
        if isinstance(value, (datetime, date)) and not isinstance(value, pd.Timestamp):
            return pd.Timestamp(value)
        return value
    return [df[c].map(_cell) if df[c].dtype == object else df[c] for c in natural_key]


def dedup_facts(df: pd.DataFrame, natural_key: list[str], amount_col: str | None = None) -> tuple[pd.DataFrame, DedupReport]:
    """Dedup on the confirmed natural key. Anti-fabrication: if two rows
    share a key but disagree on ANY business column, we do NOT silently pick
    one — every distinct row is kept and the conflict is reported for a
    human decision.

    Every business column, not just amount_col (2026-09-21, completeness
    audit F2/F3): comparing the key plus one amount dropped 18 real
    September-2025 purchases that reuse an August bill number and net amount
    but carry a different date, PO and untaxed amount, and 193 real Del Monte
    stock lines whose quantity_on_hand was null on both sides - null equal
    to null was counted as agreement while the case counts differed. A row
    is a duplicate only when every column that is not provenance (no leading
    underscore) matches; nulls match only when everything else does too.

    Null-key quarantine (2026-09-11, Phase 1 step 2a/2b): pandas'
    groupby(natural_key, dropna=False) treats every row with a fully-null
    key as ONE group — the opposite of Postgres' own UNIQUE semantics,
    where NULL <> NULL means every null-key row is already distinct. Left
    alone, this silently (mis)groups unrelated rows as if they shared an
    identity — confirmed on real data: 173 distinct unparseable
    inventory_sign_off rows collapsed into one reported "conflict" (all
    genuinely different stock lines, see reports/PHASE1_EXECUTION_PLAN_2026-09.md),
    and 591 sales_register rows with a null invoice_num did the same once
    footer-row noise was cleaned up.

    So: a row is only ever grouped with another row if EVERY natural-key
    column is non-null on both (`resolvable_mask` below — same concept and
    name as load.py's build_dimension_key_frame(), applied one stage
    earlier in anti-fabrication terms). A row with any null key column is
    NEVER grouped with any other row, resolvable or not — it is reported
    individually in DedupReport.quarantined, with which key column(s) were
    null and its row identity (_src_file/_src_sheet/_row_ordinal when
    present). Matching resolve_dimension_fk's existing "flag, never drop"
    posture, quarantined rows are NOT removed from the returned DataFrame
    — they may carry real, useful data (e.g. a genuine return missing only
    its slip number) and a caller/loader may still choose to load them
    with a NULL key; this function's job is to make sure they are never
    silently miscounted as a same-key duplicate or conflict, not to decide
    whether they ship."""
    missing = [k for k in natural_key if k not in df.columns]
    if missing:
        raise KeyError(f"Natural key column(s) missing from DataFrame: {missing}")

    input_rows = len(df)
    resolvable_mask = df[natural_key].notna().all(axis=1)
    resolvable = df.loc[resolvable_mask]
    unresolvable = df.loc[~resolvable_mask]

    id_cols = [c for c in ("_src_file", "_src_sheet", "_row_ordinal") if c in df.columns]
    quarantined = []
    for idx, row in unresolvable.iterrows():
        null_cols = [k for k in natural_key if pd.isna(row[k])]
        entry = {"null_key_columns": null_cols}
        for c in id_cols:
            entry[c] = row[c]
        quarantined.append(entry)

    grouped = resolvable.groupby(natural_key_series(resolvable, natural_key), dropna=False, sort=False) if not resolvable.empty else []

    business_cols = [c for c in df.columns if not str(c).startswith("_") and c not in natural_key]
    conflicts = []
    keep_idx = list(unresolvable.index)  # quarantined rows: kept in output, never grouped
    for key_vals, group in grouped:
        if len(group) == 1:
            keep_idx.append(group.index[0])
            continue
        canonical = group[business_cols].apply(lambda col: col.map(_canonical_cell))
        distinct = canonical.drop_duplicates()
        keep_idx.extend(distinct.index.tolist())  # first copy of each distinct row
        if len(distinct) > 1:  # flagged, not resolved
            differing = [c for c in business_cols if canonical[c].nunique(dropna=False) > 1]
            conflicts.append({
                "key": key_vals if isinstance(key_vals, tuple) else (key_vals,),
                "row_count": len(group),
                "distinct_rows": len(distinct),
                "differing_columns": differing,
                "distinct_values": group[amount_col].unique().tolist() if amount_col and amount_col in group.columns else [],
            })

    out = df.loc[sorted(keep_idx)].reset_index(drop=True)
    report = DedupReport(
        input_rows=input_rows,
        output_rows=len(out),
        duplicate_groups=sum(1 for _, g in grouped if len(g) > 1) if not resolvable.empty else 0,
        conflicting_groups=conflicts,
        quarantined=quarantined,
    )
    return out, report


@dataclass
class TotalRowExclusionReport:
    input_rows: int
    excluded: int


@dataclass
class FooterRowCheck:
    """One rule inside exclude_footer_rows()'s check list. Three shapes:
      - column + token [+ mode="eq"|"contains"]: row is junk if `column`'s
        value equals (mode="eq") or contains (mode="contains") `token`,
        case-insensitive and whitespace-trimmed either way.
      - all_null=[...]: row is junk if EVERY listed column is null on that
        row — a joint check across columns, not a per-column match. For a
        row with no signal to match on beyond "there is nothing here".
      - non_numeric="col": row is junk if `col` has a non-null value that
        fails float() parsing — text sitting where a number belongs (added
        2026-09-14, sales_register's signature-block name/role-title rows,
        e.g. net_amount="ABRAHAM TABIAN"). Deliberately narrower than an
        all_null check on the same rows would be: those rows also have
        invoice_date/invoice_num both null, but at least one REAL row in
        the same corpus has that same null pattern with a genuinely numeric
        net_amount (a differently-shaped subtotal row, not confirmed junk,
        not excluded) - checked before choosing this signal instead."""
    column: str | None = None
    token: str | None = None
    mode: str = "eq"
    all_null: list[str] | None = None
    non_numeric: str | None = None


def exclude_footer_rows(
    df: pd.DataFrame, checks: list[FooterRowCheck], label: str, required: bool = True,
) -> tuple[pd.DataFrame, TotalRowExclusionReport]:
    """Shared TOTAL/header/section-marker/blank-row exclusion for staged
    fact frames — one function instead of the same fix applied separately
    per family. Consolidated 2026-09-11 (Phase 1 step 2e): the same defect
    (a per-sheet non-data row reaching the fact table, corrupting a dedup
    key or a reported column) was found and fixed independently in
    sell_out, sales_register, and sales_return — three near-identical
    functions — then found a 4th time in inventory_sign_off before being
    consolidated. See SELL_OUT_FOOTER_CHECKS / SALES_REGISTER_FOOTER_CHECKS
    / SALES_RETURN_FOOTER_CHECKS / INVENTORY_SIGN_OFF_FOOTER_CHECKS below
    for each family's specific, real-data-verified rule
    (reports/PHASE1_EXECUTION_PLAN_2026-09.md has the row counts and
    examples behind each one).

    A check whose column(s) happen to be absent from `df` is simply
    skipped, not an error. Separately, `required` controls what happens
    when NONE of the columns referenced by ANY check are present at all:
      - required=True (default, sell_out's and sales_return's shape): raise
        KeyError - these columns are load-bearing for identifying junk rows
        in that family (sell_out's category_path is its one discriminating
        column; sales_return's four columns cover every real row shape), so
        their total absence signals a real mapping failure, not a
        legitimately thin frame. Anti-silent-failure: a caller must know
        footer rows may have reached the fact table unflagged, not discover
        it later from an inflated row count or a corrupted key column.
      - required=False (sales_register's shape): pass the frame through
        unchanged instead of raising - invoice_date/customer_name/
        tax_amount are ordinary attribute columns, and a frame can
        legitimately be missing all three (e.g. a partial/synthetic
        vocab-B frame carrying only REFERENCE #/AMOUNT/Area,
        tests/etl/test_transform_driver.py's fixture) without anything
        being broken. Confirmed 2026-09-11: an earlier version raised
        unconditionally here and broke that fixture.
    `label` names which check-list this was called with, so a raised error
    still says something specific and actionable."""
    referenced_cols: set[str] = set()
    for c in checks:
        if c.column:
            referenced_cols.add(c.column)
        if c.all_null:
            referenced_cols.update(c.all_null)
        if c.non_numeric:
            referenced_cols.add(c.non_numeric)
    if not any(col in df.columns for col in referenced_cols):
        if not required:
            return df.copy(), TotalRowExclusionReport(input_rows=len(df), excluded=0)
        raise KeyError(
            f"exclude_footer_rows({label}): none of {sorted(referenced_cols)} found - "
            f"footer/header/blank rows cannot be identified, and if this frame reaches "
            f"the fact table, they will corrupt a dedup key or a reported column."
        )
    is_junk = pd.Series(False, index=df.index)
    for c in checks:
        if c.all_null:
            cols = [col for col in c.all_null if col in df.columns]
            if len(cols) == len(c.all_null):
                is_junk |= df[cols].isna().all(axis=1)
        elif c.non_numeric:
            if c.non_numeric in df.columns:
                col = df[c.non_numeric]
                numeric_ok = pd.to_numeric(col, errors="coerce").notna()
                is_junk |= col.notna() & ~numeric_ok
        elif c.column in df.columns:
            vals = df[c.column].astype(str).str.strip().str.upper()
            tok = c.token.upper()
            is_junk |= vals.eq(tok) if c.mode == "eq" else vals.str.contains(tok, na=False)
    out = df.loc[~is_junk].copy()
    return out, TotalRowExclusionReport(input_rows=len(df), excluded=int(is_junk.sum()))


# Per-family check lists — each verified against real staged data before use
# (reports/PHASE1_EXECUTION_PLAN_2026-09.md, Phase 1 steps 2b/2c/2e).

SELL_OUT_FOOTER_CHECKS = [
    # Every real sell_out file has one (confirmed: 34/34 real sheets,
    # 100%) - a category_path value of "Total" (case/whitespace variants
    # seen in real data), not a real category. If it reaches SellOut_Fact,
    # every aggregate over category_path double-counts (the row's own
    # amount is the sum of every other row in the same file).
    FooterRowCheck(column="category_path", token="TOTAL", mode="eq"),
]

# SSM's own Del Monte Sell Out template's leading category column
# (__col0__ -> category_path) holds the literal text "False" or
# "False  (N)" (a running occurrence-count suffix) instead of a real
# category label, for an unknown subset of rows per sheet. Confirmed
# 2026-09-14 (Phase 1d full sweep, item 40a) via raw Excel inspection
# (data/raw/Del Monte/MONTHLY REPORT - FEBRUARY 2024/2024 FEBRUARY SELL
# OUT.xlsx, ILOCOS_SELL OUT sheet, rows 64+) that this is genuinely baked
# into the source file - a broken formula/lookup in SSM's template, not a
# pipeline defect. Distinct from a footer/TOTAL row: the net_amount/
# quantity values on these rows are real, non-zero figures that look like
# genuine transactions, just missing a recoverable category identity.
_SELLOUT_SOURCE_DEFECT_CATEGORY_RE = re.compile(r"^False(\s+\(\d+\))?$")


def relabel_sellout_source_defect_categories(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Yuan's ruling (2026-09-14): same treatment as Unilever's 380 no-SOH-
    match SKUs - category_path becomes the literal string 'UNCLASSIFIED',
    revenue preserved, never dropped. But the natural key is
    (category_path, region, _period) - schema.sql's own UNIQUE constraint
    - so relabeling multiple distinct junk rows to the same 'UNCLASSIFIED'
    string can make several of them share one key within a single
    (region, _period). Treating that as a dedup_facts() conflict (flag,
    drop) would silently lose real revenue - exactly item 36's failure
    mode, inverted: this is the same legitimate "we don't know which
    category" bucket, not a genuine disagreement between two different
    real facts. The only revenue-preserving treatment is to SUM
    net_amount/quantity across the relabeled rows sharing a
    (region, _period, is_demo) group before dedup_facts ever sees them -
    real and demo are summed separately (is_demo isn't part of the DB's
    actual natural key, but never blending real and demo figures together
    is a harder rule than the schema enforces, kept anyway)."""
    if "category_path" not in df.columns:
        return df, 0
    is_defect = df["category_path"].apply(
        lambda v: isinstance(v, str) and bool(_SELLOUT_SOURCE_DEFECT_CATEGORY_RE.match(v.strip()))
    )
    n = int(is_defect.sum())
    if n == 0:
        return df, 0

    defect_rows = df.loc[is_defect].copy()
    other_rows = df.loc[~is_defect].copy()
    defect_rows["category_path"] = "UNCLASSIFIED"

    group_cols = [c for c in ["category_path", "region", "_period", "is_demo"] if c in defect_rows.columns]
    sum_cols = [c for c in ["net_amount", "quantity", "quantity_cases"] if c in defect_rows.columns]
    other_cols = [c for c in defect_rows.columns if c not in group_cols and c not in sum_cols]

    # net_amount/quantity arrive as a genuinely mixed float/str/Decimal
    # object column (confirmed 2026-09-14, this function's first real run:
    # pandas' groupby-sum on an object column containing strings does
    # Python string CONCATENATION, not numeric addition - "15871.97" +
    # "36578.41" became the literal text "15871.9736578.41", which then
    # failed the INSERT with a Postgres numeric-parse error, not a silent
    # wrong number). Explicit numeric coercion first, matching how the
    # rest of this module treats money columns (to_decimal/coerce_numeric_
    # columns) - errors="raise" via the assert below, not "coerce", because
    # a genuinely unparseable value here would be a NEW, different defect
    # worth stopping on, not silently zeroing revenue out from under a sum.
    for c in sum_cols:
        coerced = pd.to_numeric(defect_rows[c], errors="coerce")
        bad = coerced.isna() & defect_rows[c].notna()
        if bad.any():
            raise ValueError(
                f"relabel_sellout_source_defect_categories: {int(bad.sum())} rows in "
                f"'{c}' didn't coerce to a number - {defect_rows.loc[bad, c].tolist()[:5]} "
                f"- not summing over an unparseable value silently."
            )
        defect_rows[c] = coerced

    agg = {c: "sum" for c in sum_cols}
    agg.update({c: "first" for c in other_cols})
    merged = defect_rows.groupby(group_cols, as_index=False).agg(agg)
    # sum(min_count=1) semantics (2026-09-22): a group whose values are ALL
    # missing is NULL, not 0. Plain "sum" turned the two August 2023 merged
    # rows' missing revenue into a stated 0.00 - a number nobody measured.
    # Masked after the fact so every non-empty group keeps the exact same sum.
    present = defect_rows.groupby(group_cols, as_index=False)[sum_cols].count()
    for c in sum_cols:
        merged.loc[present[c].to_numpy() == 0, c] = np.nan
    # Provenance: this row no longer traces to one real file/sheet - say so
    # explicitly rather than leaving the first-merged row's original
    # _src_file/_src_sheet, which would misleadingly look like a single-
    # source row.
    if "_src_file" in merged.columns:
        merged["_src_file"] = "AGGREGATED_source_file_defect_category"
    if "_src_sheet" in merged.columns:
        merged["_src_sheet"] = merged["region"].astype(str) + " " + merged["_period"].astype(str)

    print(f"  [sell_out] {n} rows had an unrecoverable category_path ('False'/'False (N)', "
          f"a confirmed source-file defect - see this function's docstring), relabeled to "
          f"'UNCLASSIFIED' and merged into {len(merged)} rows by summing "
          f"{sum_cols} per (region, _period, is_demo) - revenue preserved, never dropped")
    return pd.concat([other_rows, merged], ignore_index=True), n


SALES_REGISTER_FOOTER_CHECKS = [
    # Confirmed 2026-09-11: every daily sheet's footer stages as 1-3 extra
    # rows depending on vocab. invoice_date == "TOTAL" is a per-sheet
    # subtotal (Salesman/Customer Name blank, invoice_num null, a
    # line-item COUNT landed in the `region` column - which is what
    # surfaced these as spurious dedup conflicts under keys like
    # (NaN, 'delmonte', '13')). The other three are a 3-cell signature
    # line from the sheet's sign-off block ("Prepared by:"/"Checked by:"/
    # "Noted by:"), staged as one more data row per sheet. Verified: 177
    # rows across the full corpus (163 real + 14 demo, of 56,968 mapped
    # rows total for Del Monte).
    #
    # Each token is checked against exactly ONE specific column, never
    # cross-producted against all three - checking "TOTAL" as a substring
    # against customer_name would wrongly exclude a real customer named
    # "TOTAL ABANAO..." (confirmed present: 21 real rows; caught before
    # this shipped).
    FooterRowCheck(column="invoice_date", token="TOTAL", mode="eq"),
    FooterRowCheck(column="invoice_date", token="PREPARED BY", mode="contains"),
    FooterRowCheck(column="customer_name", token="CHECKED BY", mode="contains"),
    FooterRowCheck(column="tax_amount", token="NOTED BY", mode="contains"),
    # Found 2026-09-14 (first real, non-dry-run load - this specific
    # month's sheets weren't in the sample that found the checks above):
    # the "Prepared by:/Checked by:/Noted by:" LABEL row (caught above) is
    # followed by TWO more rows in the same signature block that the label
    # check can't catch - the actual people's names under each label (e.g.
    # salesman="ELYSSA L. MASON", customer_name="MYRA FE DOMINGO",
    # net_amount="ABRAHAM TABIAN"), then a role-title row right after it
    # (salesman="ENCODER", customer_name="RECEIVABLE",
    # net_amount="ADMINHEAD"). Confirmed 79 real rows (158 incl. the
    # role-title row) across every sheet of one November 2025 file.
    #
    # NOT caught with an all_null(invoice_date, invoice_num) check, even
    # though every one of these rows has both null - tested that first and
    # found it would ALSO exclude one confirmed-real row (net_amount
    # 172,283.33, a differently-shaped subtotal row with no invoice
    # identity but real aggregate figures) that has no `token` to
    # distinguish it from genuine junk. non_numeric is narrower and safe:
    # only rows where net_amount holds unparseable text (a name, a role
    # title) are excluded; a real row's net_amount is always numeric.
    FooterRowCheck(non_numeric="net_amount"),
]

SALES_RETURN_FOOTER_CHECKS = [
    # 1. A second, unstripped header row - this runs AFTER apply_column_map
    # (see transform_fact), so "Return Type" has already been renamed to
    # canonical `return_type` by then. Checking all three of
    # return_type/return_slip_num/invoice_num (not just one) is deliberate
    # redundancy: a BUG in an earlier version checked the pre-rename raw
    # column name "Return Type", which no longer existed by that point and
    # silently did nothing, letting all 7 real header rows leak through as
    # a false dedup "collision" (caught 2026-09-11 while testing
    # schema.sql's COALESCE proposal against real data, item 21).
    FooterRowCheck(column="return_type", token="RETURN TYPE", mode="eq"),
    FooterRowCheck(column="return_slip_num", token="RETURN SLIP #", mode="eq"),
    FooterRowCheck(column="invoice_num", token="INVOICE NUM", mode="eq"),
    # 2. Section-marker rows from the pre-2025 `data`-shaped sheets: the
    # raw "Invoice Date" column (deliberately NOT mapped by
    # column_maps/sales_return.yaml) literally equal to "Good Stock" or
    # "Bad Stock" (marking where that sub-listing starts inside a combined
    # sheet, not a return). No return_slip_num, no invoice_num, no
    # net_amount - genuinely no data, not a row with a missing key.
    FooterRowCheck(column="Invoice Date", token="GOOD STOCK", mode="eq"),
    FooterRowCheck(column="Invoice Date", token="BAD STOCK", mode="eq"),
    # 3. Fully-blank rows: return_slip_num, invoice_num, AND net_amount
    # ALL null on the same row (found 2026-09-11, item 21/22, testing the
    # return_type key change: exactly 3 real rows, all ILOCOS BO,
    # April/June/March 2025 - every field null, not just the key).
    # Requiring all three null (not any one) keeps this from ever
    # excluding a real return that's merely missing its slip number, which
    # dedup_facts()'s quarantine handles on its own.
    FooterRowCheck(all_null=["return_slip_num", "invoice_num", "net_amount"]),
]

INVENTORY_SIGN_OFF_FOOTER_CHECKS = [
    # Added 2026-09-11 (Phase 1 step 2e), the 4th family with this defect.
    # sku_description_raw == "Total" is a per-sheet TOTAL/footer row - the
    # single largest chunk of the real "unmatched" sku_code_status bucket
    # (previously misread as evidence of an uncovered header shape,
    # ARCHITECTURE.md:196 - verified stale, see that file), but NOT all of
    # it: of 46 real unmatched rows, only 29 are "Total". Must run AFTER
    # route_inventory_sku_shapes()/split_sku_description() populate
    # sku_description_raw for BOTH eras (2023's __col0__ and 2025's
    # __col1__ converge on this canonical name only after that step) - see
    # the call site in transform_fact(), not immediately after
    # backfill_provenance_fields() like the other three families.
    FooterRowCheck(column="sku_description_raw", token="TOTAL", mode="eq"),
    # "#REF!" - a broken Excel formula reference (2 real rows). Confirmed
    # genuinely no data: no quantity_on_hand/cost/valuation on either row,
    # only cases/packages/pieces - unlike the remaining 15 unmatched rows
    # below, safe to treat as pure junk.
    FooterRowCheck(column="sku_description_raw", token="#REF!", mode="eq"),
    # 7 section-header rows (2026-09-17, column-gap audit's DM product_dimension
    # recon): sku_description_raw is a bare category label ("QUICK N EASY",
    # "KIKKOMAN", "CONTADINA", "MR. MILK YOGHURT", "VINA MILK", "PROMO PACK",
    # "NEW PRODUCTS"), all from ONE file/sheet (AUGUST 2023 inventory sign-off,
    # "ACTUAL 090423"). _SKU_CODE_RE requires "CODE<space>NAME" and correctly
    # refuses to split a single all-caps token with no trailing name, so these
    # land in sku_code with product_name=NULL. Deliberately NOT a plain
    # all_null=[quantity_on_hand, cases] check: that sheet has 209 OTHER real
    # rows (real product names, real `pieces` counts) that also have
    # quantity_on_hand/cases both null - this file reports pieces, not
    # quantity_on_hand, for that sheet, and an all_null check on just those two
    # columns would have silently dropped all 209 of them (verified before
    # writing this: exactly 210 rows match quantity_on_hand+cases null, 209 of
    # which have real product_name text). Joint on all THREE columns instead -
    # verified exact: 7 rows match all-three-null, no more, no less.
    FooterRowCheck(all_null=["quantity_on_hand", "cases", "product_name"]),
    # NOT included, deliberately - 15 real rows remain "unmatched" after
    # the two checks above (12 with sku_description_raw=NULL, 1
    # "DESCRIPTION" - an unstripped-header-style artifact, 2 "WH/Stock" /
    # "IS-WH/Stock"). Checked before deciding: unlike "Total"/"#REF!",
    # every one of these 15 carries REAL quantity_on_hand/cost/valuation
    # data (one is 2,535 cases / ~2.6M valuation - large enough to look
    # like a section subtotal, not a per-SKU line). Excluding them without
    # confirming what they are risks silently dropping real inventory
    # data, the exact anti-fabrication failure this function exists to
    # prevent in the other direction. Left as sku_code_status='unmatched'
    # - flagged, not guessed at. See
    # reports/PHASE1_EXECUTION_PLAN_2026-09.md for the raw rows.
]


def transform_fact(
    df: pd.DataFrame, fact: str, principal: str, config_dir: Path = DEFAULT_CONFIG_DIR,
    amount_col: str | None = None, discount_alias_table: str | None = "discount_rate_labels",
) -> tuple[pd.DataFrame, dict]:
    """Convenience pipeline: source-of-truth filter -> column map ->
    alias-standardize discount labels -> dedup.

    doc_type is no longer a separate caller-supplied argument - it is
    read from the source_of_truth.yaml rule for (fact, principal), so
    there is exactly one place that pairing is declared (previously a
    caller could pass a doc_type that didn't match the rule's, and nothing
    checked that). Returns the transformed DataFrame plus a combined
    report dict for QC.

    Raises ValueError if the rule's natural_key is None (deliberately
    unconfirmed - see source_of_truth.yaml) rather than deduping on a
    fabricated key.
    """
    rule = load_source_of_truth(fact, principal, config_dir)
    if rule.natural_key is None:
        raise ValueError(
            f"source_of_truth.yaml has natural_key=null for fact='{fact}', principal='{principal}' "
            f"(doc_type='{rule.doc_type}') - this fact/principal is flagged as unconfirmed against "
            f"real data, not a config gap. See the comment on that entry before proceeding; "
            f"transform_fact() will not guess a key."
        )

    sot_df = filter_source_of_truth(df, fact, principal, config_dir)
    sot_df, orphan_rescue_report = rescue_cross_check_orphans(df, sot_df, rule, config_dir)
    mapped_df, map_report = apply_column_map(sot_df, rule.doc_type, config_dir)
    mapped_df = coerce_is_demo_column(mapped_df)
    mapped_df = backfill_provenance_fields(mapped_df)
    if rule.doc_type == "sell_out":
        mapped_df["net_amount_tax_inclusive"] = flag_sellout_tax_inclusive(sot_df)

    if discount_alias_table and "discount_rate_label" in mapped_df.columns:
        mapped_df = apply_alias_table(mapped_df, "discount_rate_label", discount_alias_table, config_dir)

    total_row_exclusion_report = None
    period_report = None
    if rule.doc_type == "sell_out":
        mapped_df, total_row_exclusion_report = exclude_footer_rows(mapped_df, SELL_OUT_FOOTER_CHECKS, "sell_out")
        # Must run AFTER backfill_provenance_fields() above (needs real
        # region/_period/is_demo to group by) and AFTER the footer-row
        # exclusion (a "False"-labeled row is a real, non-footer row -
        # excluding it here first would be wrong), BEFORE dedup_facts()
        # below (so the merged rows go through the normal dedup/conflict
        # machinery like any other row, not a special case).
        mapped_df, _ = relabel_sellout_source_defect_categories(mapped_df)
    elif rule.doc_type == "sales_register":
        mapped_df, total_row_exclusion_report = exclude_footer_rows(
            mapped_df, SALES_REGISTER_FOOTER_CHECKS, "sales_register", required=False,
        )
        mapped_df, period_report = period_from_invoice_date(mapped_df)
    elif rule.doc_type == "sales_return":
        mapped_df, total_row_exclusion_report = exclude_footer_rows(mapped_df, SALES_RETURN_FOOTER_CHECKS, "sales_return")

    sku_split_report = None
    sku_shape_report = None
    if rule.doc_type == "inventory_sign_off":
        mapped_df, sku_shape_report = route_inventory_sku_shapes(mapped_df)
        if "sku_description_raw" in mapped_df.columns:
            mapped_df, sku_split_report = split_sku_description(mapped_df)

        # Shape C (real "ITEM CODE"/"ITEM DESCRIPTION" headers): direct
        # copy, no regex needed. Must run AFTER split_sku_description()
        # above, since that function blanket-fills sku_code/product_name
        # for every row from sku_description_raw - which Shape C rows
        # never have (their code/name were never combined into one cell).
        if "ITEM CODE" in mapped_df.columns:
            mask_c = mapped_df["_inventory_sku_shape"] == "C"
            if mask_c.any():
                if "sku_code" not in mapped_df.columns:
                    mapped_df["sku_code"] = pd.NA
                if "product_name" not in mapped_df.columns:
                    mapped_df["product_name"] = pd.NA
                mapped_df.loc[mask_c, "sku_code"] = mapped_df.loc[mask_c, "ITEM CODE"]
                if "ITEM DESCRIPTION" in mapped_df.columns:
                    mapped_df.loc[mask_c, "product_name"] = mapped_df.loc[mask_c, "ITEM DESCRIPTION"]

        # Footer-row exclusion runs HERE, not immediately after
        # backfill_provenance_fields() like the other three families -
        # sku_description_raw only converges to one canonical name (across
        # both the 2023 __col0__ and 2025 __col1__ eras) after
        # split_sku_description() above has run. Excluding before
        # sku_code_status is assigned below means a footer row never gets
        # mislabeled "unmatched" (a real source-data-gap signal) in the
        # first place - it's simply gone.
        if "sku_description_raw" in mapped_df.columns:
            mapped_df, total_row_exclusion_report = exclude_footer_rows(
                mapped_df, INVENTORY_SIGN_OFF_FOOTER_CHECKS, "inventory_sign_off",
            )

        # sku_code_status: makes a Shape D row (the source itself never
        # carries the alpha SKU prefix - confirmed 173/173 real rows in
        # the one real file this affects) distinguishable from an ordinary
        # regex refusal (banner/corrupt rows like "Total"/"#REF!", now
        # excluded above rather than reaching this classification at all)
        # or a Shape C direct match - all three otherwise collapse to the
        # same "sku_code is null" signal, which would hide a real
        # source-data gap behind the same label as an unremarkable
        # banner-row skip.
        if "sku_code" in mapped_df.columns:
            status = pd.Series("unmatched", index=mapped_df.index, dtype=object)
            status[mapped_df["sku_code"].notna()] = "matched"
            status[mapped_df["_inventory_sku_shape"] == "C"] = "direct"
            status[mapped_df["_inventory_sku_shape"] == "D"] = "source_gap"
            mapped_df["sku_code_status"] = status

    date_reformat_report = None
    if rule.doc_type == "unilever_sku" and "calendar_month" in mapped_df.columns:
        mapped_df, date_reformat_report = reformat_calendar_month(mapped_df)

    if rule.doc_type == "inventory_sign_off" and "_period" in mapped_df.columns and "snapshot_date" not in mapped_df.columns:
        mapped_df["snapshot_date"] = mapped_df["_period"].map(_snapshot_date_from_period)

    mapped_df, quantity_report = normalize_quantities(mapped_df, rule.doc_type)

    # calendar_month is already reformatted above (date_reformat_report) -
    # do not call reformat_calendar_month() a second time here, it would
    # silently re-run against already-'YYYY-MM' values for no benefit.
    numeric_coercion_report = None
    if rule.doc_type == "unilever_sku":
        mapped_df, unparseable_cols = coerce_numeric_columns(mapped_df, UNILEVER_SKU_NUMERIC_COLUMNS)
        numeric_coercion_report = {"unparseable_columns": unparseable_cols}
    elif rule.doc_type == "inventory_sign_off":
        mapped_df, unparseable_cols = coerce_numeric_columns(mapped_df, DELMONTE_INVENTORY_NUMERIC_COLUMNS)
        numeric_coercion_report = {"unparseable_columns": unparseable_cols}
    elif rule.doc_type in ("sales_register", "sales_return"):
        mapped_df, unparseable_cols = coerce_numeric_columns(mapped_df, INVOICE_QUANTITY_COLUMNS)
        numeric_coercion_report = {"unparseable_columns": unparseable_cols}

    mapped_df, source_quarantine_report = flag_source_quarantine(mapped_df, rule.doc_type)

    deduped_df, dedup_report = dedup_facts(mapped_df, rule.natural_key, amount_col=amount_col)
    return deduped_df, {
        "doc_type": rule.doc_type,
        "column_map": map_report,
        "total_row_exclusion": total_row_exclusion_report,
        "orphan_rescue": orphan_rescue_report,
        "period_from_invoice_date": period_report,
        "sku_split": sku_split_report,
        "sku_shape_routing": sku_shape_report,
        "date_reformat": date_reformat_report,
        "quantity_reconciliation": quantity_report,
        "numeric_coercion": numeric_coercion_report,
        "source_quarantine": source_quarantine_report,
        "dedup": dedup_report,
        "rows_in": len(df),
        "rows_after_sot_filter": len(sot_df),
        "rows_out": len(deduped_df),
        # Pre-dedup, post-column-map frame (still carries _src_file/_src_sheet
        # provenance) - exposed so callers needing per-sheet traceability
        # (e.g. transform_driver.py's Transform-stage QC manifest) can map a
        # dedup conflict's natural-key values back to the source sheet(s)
        # that produced it, without reimplementing this pipeline themselves.
        "mapped_df": mapped_df,
    }
