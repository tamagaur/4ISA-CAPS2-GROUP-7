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
    columns (leading underscore) pass through untouched. A raw header not
    found in the map is left as-is and reported — never dropped silently
    (anti-fabrication: an unrecognized column might carry real data)."""
    cmap = load_column_map(doc_type, config_dir)

    rename = {}
    mapped = {}
    unmapped_raw = []
    for col in df.columns:
        if col.startswith("_"):
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


def backfill_provenance_fields(df: pd.DataFrame, fields: tuple[str, ...] = ("principal", "region")) -> pd.DataFrame:
    """For each canonical field in `fields` not already produced by a
    raw-header column map (e.g. inventory_sign_off/sell_out have no raw
    "region" header at all — see config/source_of_truth.yaml's comments),
    copy it from the matching provenance column Extract always attaches
    (_<field>). Generalizes the existing snapshot_date-from-_period
    pattern in transform_fact() below instead of special-casing per
    doc_type.

    Every fact table in analytics/db/schema.sql declares a bare
    `principal TEXT NOT NULL` — Extract only ever produces `_principal`
    (provenance), and load.py's upsert intentionally skips underscore-
    prefixed columns, so without this the NOT NULL constraint fails at
    Load. Must run after apply_column_map (so a real mapped column is
    never overwritten) and before dedup_facts (natural keys reference the
    bare field names)."""
    out = df.copy()
    for field_name in fields:
        if field_name in out.columns:
            continue
        prov_col = f"_{field_name}"
        if prov_col in out.columns:
            out[field_name] = out[prov_col]
    return out


def reformat_calendar_month(df: pd.DataFrame, column: str = "calendar_month") -> pd.DataFrame:
    """Unilever's raw Calendar Month values are 'MM.YYYY' (e.g. '10.2025'),
    not the project's 'YYYY-MM' convention every other _period tag and
    Unilever_SKU_Demand_Fact.calendar_month use (config/column_maps/
    unilever_sku.yaml's own TRANSFORM TODO). Reuses
    extract._shared.MM_YYYY_RE rather than redefining the pattern. A
    value that doesn't match the expected shape is left as-is, not
    guessed at — surfaced downstream as an unparseable date, not silently
    dropped."""
    if column not in df.columns:
        return df
    out = df.copy()

    def _reformat(v):
        if pd.isna(v):
            return v
        m = MM_YYYY_RE.match(str(v).strip())
        if not m:
            return v
        month, year = m.groups()
        return f"{year}-{month}"

    out[column] = out[column].map(_reformat)
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

    sku_split_report = None
    if rule.doc_type == "inventory_sign_off" and "sku_description_raw" in mapped_df.columns:
        mapped_df, sku_split_report = split_sku_description(mapped_df)
        if "_period" in mapped_df.columns and "snapshot_date" not in mapped_df.columns:
            mapped_df["snapshot_date"] = mapped_df["_period"]

    numeric_coercion_report = None
    if rule.doc_type == "unilever_sku":
        mapped_df = reformat_calendar_month(mapped_df)
        mapped_df, unparseable_cols = coerce_numeric_columns(mapped_df, UNILEVER_SKU_NUMERIC_COLUMNS)
        numeric_coercion_report = {"unparseable_columns": unparseable_cols}

    deduped_df, dedup_report = dedup_facts(mapped_df, rule.natural_key, amount_col=amount_col)
    return deduped_df, {
        "doc_type": rule.doc_type,
        "column_map": map_report,
        "sku_split": sku_split_report,
        "numeric_coercion": numeric_coercion_report,
        "dedup": dedup_report,
        "rows_in": len(df),
        "rows_after_sot_filter": len(sot_df),
        "rows_out": len(deduped_df),
    }
