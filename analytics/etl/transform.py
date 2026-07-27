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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"

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
    unmapped_canonical = [c for c in cmap.canonical_to_raw if c not in out.columns]

    report = ColumnMapReport(
        doc_type=doc_type, mapped=mapped,
        unmapped_raw=unmapped_raw, unmapped_canonical=unmapped_canonical,
    )
    return out, report


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
    )


def filter_source_of_truth(df: pd.DataFrame, fact: str, principal: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> pd.DataFrame:
    """Keep only rows whose _sheet_role is the system of record for this
    fact/principal per DEC-04. Drops cross-check views (e.g. INVOICE REG
    when RAW DATA is present) so downstream never double-counts."""
    rule = load_source_of_truth(fact, principal, config_dir)
    if "_sheet_role" not in df.columns:
        raise KeyError("DataFrame missing '_sheet_role' — did this come from Extract staging?")
    return df[df["_sheet_role"].isin(rule.system_of_record_role)].copy()


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

    if discount_alias_table and "discount_rate_label" in mapped_df.columns:
        mapped_df = apply_alias_table(mapped_df, "discount_rate_label", discount_alias_table, config_dir)

    sku_split_report = None
    if rule.doc_type == "inventory" and "sku_description_raw" in mapped_df.columns:
        mapped_df, sku_split_report = split_sku_description(mapped_df)
        if "_period" in mapped_df.columns and "snapshot_date" not in mapped_df.columns:
            mapped_df["snapshot_date"] = mapped_df["_period"]

    deduped_df, dedup_report = dedup_facts(mapped_df, rule.natural_key, amount_col=amount_col)
    return deduped_df, {
        "doc_type": rule.doc_type,
        "column_map": map_report,
        "sku_split": sku_split_report,
        "dedup": dedup_report,
        "rows_in": len(df),
        "rows_after_sot_filter": len(sot_df),
        "rows_out": len(deduped_df),
    }
