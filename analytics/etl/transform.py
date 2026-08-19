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
from pathlib import Path

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


@dataclass
class DedupReport:
    input_rows: int
    output_rows: int
    duplicate_groups: int
    conflicting_groups: list[dict]   # same key, differing non-key values — needs a human look


def dedup_facts(df: pd.DataFrame, natural_key: list[str], amount_col: str | None = None) -> tuple[pd.DataFrame, DedupReport]:
    """Dedup on the confirmed natural key. Anti-fabrication: if two rows
    share a key but disagree on amount_col, we do NOT silently pick one —
    both are kept and the conflict is reported for a human decision."""
    missing = [k for k in natural_key if k not in df.columns]
    if missing:
        raise KeyError(f"Natural key column(s) missing from DataFrame: {missing}")

    input_rows = len(df)
    grouped = df.groupby(natural_key, dropna=False)

    conflicts = []
    keep_idx = []
    for key_vals, group in grouped:
        if len(group) == 1:
            keep_idx.append(group.index[0])
            continue
        if amount_col and amount_col in group.columns and group[amount_col].nunique(dropna=False) > 1:
            conflicts.append({
                "key": key_vals if isinstance(key_vals, tuple) else (key_vals,),
                "row_count": len(group),
                "distinct_values": group[amount_col].unique().tolist(),
            })
            keep_idx.extend(group.index.tolist())  # keep all — flagged, not resolved
        else:
            keep_idx.append(group.index[0])  # true duplicate, safe to collapse

    out = df.loc[sorted(keep_idx)].reset_index(drop=True)
    report = DedupReport(
        input_rows=input_rows,
        output_rows=len(out),
        duplicate_groups=sum(1 for _, g in grouped if len(g) > 1),
        conflicting_groups=conflicts,
    )
    return out, report


@dataclass
class TotalRowExclusionReport:
    input_rows: int
    excluded: int


def exclude_sell_out_total_rows(df: pd.DataFrame, column: str = "category_path") -> tuple[pd.DataFrame, TotalRowExclusionReport]:
    """Drop Sell Out's per-file "Total" summary row before dedup. Every
    real sell_out file has one (confirmed: 34/34 real sheets, 100%) - it's
    a category_path value of "Total" (case/whitespace variants seen in
    real data), not a real category, and if it reaches SellOut_Fact every
    aggregate over category_path double-counts (the row's own amount is
    the sum of every other row in the same file). Matched case-insensitive
    and trimmed rather than an exact string, since real headers/values in
    this corpus are inconsistently cased and padded elsewhere too (see
    column_maps/sell_out.yaml's own note on __col0__ needing a strip).

    Raises KeyError if `column` is absent rather than silently passing
    the frame through: a missing category_path means Total rows can't be
    identified at all, and letting that through unflagged is exactly the
    failure mode this function exists to prevent - the caller must know
    a Total row may have reached SellOut_Fact and doubled every
    aggregate, not discover it later from a wrong dashboard number."""
    if column not in df.columns:
        raise KeyError(
            f"exclude_sell_out_total_rows: '{column}' column not found - Total rows cannot be "
            f"excluded, and if this frame reaches SellOut_Fact, every category_path aggregate "
            f"will double-count (each file's Total row sums every other row in that file)."
        )
    is_total = df[column].astype(str).str.strip().str.upper() == "TOTAL"
    out = df.loc[~is_total].copy()
    return out, TotalRowExclusionReport(input_rows=len(df), excluded=int(is_total.sum()))


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
    mapped_df, map_report = apply_column_map(sot_df, rule.doc_type, config_dir)
    mapped_df = backfill_provenance_fields(mapped_df)

    if discount_alias_table and "discount_rate_label" in mapped_df.columns:
        mapped_df = apply_alias_table(mapped_df, "discount_rate_label", discount_alias_table, config_dir)

    total_row_exclusion_report = None
    if rule.doc_type == "sell_out":
        mapped_df, total_row_exclusion_report = exclude_sell_out_total_rows(mapped_df)

    sku_split_report = None
    if rule.doc_type == "inventory_sign_off" and "sku_description_raw" in mapped_df.columns:
        mapped_df, sku_split_report = split_sku_description(mapped_df)

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

    deduped_df, dedup_report = dedup_facts(mapped_df, rule.natural_key, amount_col=amount_col)
    return deduped_df, {
        "doc_type": rule.doc_type,
        "column_map": map_report,
        "total_row_exclusion": total_row_exclusion_report,
        "sku_split": sku_split_report,
        "date_reformat": date_reformat_report,
        "quantity_reconciliation": quantity_report,
        "numeric_coercion": numeric_coercion_report,
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
