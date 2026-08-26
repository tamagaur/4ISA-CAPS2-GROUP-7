"""
analytics.etl.extract.ssis_soh — Unilever SOH (Stock on Hand) Extract driver.

Source: the SOH(<date>) sheet embedded inside SSIS Sales Summary Report
workbooks (data/raw/SSIS/**, data/raw/Unilever/**) — real, SKU-level
Unilever inventory. See reports/SOH_PROFILE.md for the discovery pass
this driver implements, and config/column_maps/ssis_soh.yaml for the full
column mapping and the CS/PC parse function documented alongside its
Python source (this module).

Unlike this repo's other Extract drivers (thin wrappers around
_shared.parse_doc_type_files), this one carries doc_type-specific
business logic directly, because the rulings for ssis_soh are themselves
Extract-stage decisions, not Transform-stage ones:

  R1  Scope: only snapshots from 2023-01 onward are in scope. Files whose
      reporting period (profiling.profile_files.infer_period) is before
      2023-01, or unparseable, are skipped entirely and counted.
  R2  Dedupe: data/raw/SSIS/ and data/raw/Unilever/ carry the same months
      twice for 2021, 2022, 2024, 2025 (SOH_PROFILE.md §c) — dedupe on
      the FINAL snapshot_date (post-R4). First file wins, in the
      deterministic sorted order _shared.select_source_files already
      produces (SSIS/ sorts before Unilever/ lexicographically, so SSIS/
      wins each duplicate pair — not a special case, just alphabetical
      order). Every skipped duplicate is logged with both paths.
  R3  2021-06-30 is explicitly rejected if it is ever seen post-R4
      correction — moot under R1 (that date is pre-2023 and never
      reaches this check), kept as an explicit guard per the ruling so a
      future scope change can't silently let the known two-conflicting-
      payloads date back in.
  R4  Date guard: the sheet-name date must land 1-45 days after the
      file's reporting period end. Outside that window, the period-
      derived date (period end + 1 day) is used instead and a warning is
      logged with both dates. General rule — not special-cased to the
      one 2025-12 file it happens to catch in the current corpus (its
      sheet name says "JANUARY 05, 2025", eleven months before its own
      December-2025 period end; the guard reclassifies it to
      2026-01-05).
  R5  snapshot_date = the (R4-validated) sheet-name date. _period = the
      file's reporting month.
  R6  Storage Location dropped (single-valued "SALE" everywhere,
      SOH_PROFILE.md §g) — never extracted into the output at all.
  R7  Price column: only "Last Purchase Price(GSV/CS)" should occur
      in-scope. "MOVING AVERAGE PRICE(CS)" (the pre-2023 era's column)
      appearing on an in-scope sheet raises immediately — that would
      mean R1's scope filter let a pre-2023-shaped file through, and
      silently coalescing the two price concepts would corrupt the
      number, not just the label.

Reuses _shared.py's primitives (trim_grid, detect_header, is_blank,
_force_text, provenance columns, write_staging_table) exactly as the
other drivers do — only the file/sheet selection and the column
mapping + CS/PC parsing are bespoke here.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from profiling.detect import detect_header, is_blank, trim_grid
from profiling.profile_files import infer_doc_type, infer_period
from profiling.reader import read_workbook

from analytics.etl._coerce import to_decimal, to_number
from analytics.etl.extract._shared import (
    PROVENANCE_COLUMNS,
    REPO_ROOT,
    RejectRecord,
    _force_text,
    select_source_files,
    write_staging_table,
)

DOC_TYPE = "ssis_soh"

# R1
MIN_PERIOD = "2023-01"

SOH_SHEET_RE = re.compile(r"\bSOH\b", re.I)

# R7 — the confirmed pre-2023-era header; must never appear in-scope.
MOVING_AVG_PRICE_HEADER = "MOVING AVERAGE PRICE(CS)"

# R3
REJECTED_SNAPSHOT_DATES = frozenset({date(2021, 6, 30)})

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
_SNAPSHOT_TOKEN_RE = re.compile(r"[A-Z]+\s*(\d{1,2})\s*,?\s*(\d{4})")


def parse_snapshot_date(sheet_name: str) -> date | None:
    """Best-effort date out of a "SOH(<date>)" sheet name. Handles the
    real corpus's inconsistent punctuation/spacing (e.g. "MARCH1,2022",
    "Oct. 30, 2021", "MARCH 02, 2026") by normalizing separators first.
    Returns None if the token doesn't resolve to a real calendar date
    (caller must not guess a date for a sheet that doesn't parse)."""
    tok = re.sub(r"\bSOH\b", "", sheet_name, flags=re.I)
    tok = tok.strip(" ()").upper().replace(".", " ").replace(",", " ")
    tok = re.sub(r"\s+", " ", tok).strip()
    m = re.match(r"([A-Z]+)\s*(\d{1,2})\s*(\d{4})", tok)
    if not m:
        return None
    mon_txt, day_txt, yr_txt = m.groups()
    month = _MONTHS.get(mon_txt[:4]) or _MONTHS.get(mon_txt[:3])
    if month is None:
        return None
    try:
        return date(int(yr_txt), month, int(day_txt))
    except ValueError:
        return None


def period_end_date(period: str) -> date:
    """"YYYY-MM" -> that month's last calendar day."""
    year, month = (int(p) for p in period.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


CS_PC_RE = re.compile(r"(-?\d+)\s*/\s*(-?\d+)")


def parse_cs_pc(raw) -> tuple[int | None, int | None]:
    """Splits a "<cases>/<pieces>" cell (e.g. "117/1") into (cases,
    pieces). Blank -> (None, None). A non-blank value that doesn't match
    the confirmed format raises — every in-scope sheet has been verified
    to follow this format (reports/SOH_PROFILE.md §d), so a mismatch is
    new evidence to investigate, not a case to silently paper over."""
    if is_blank(raw):
        return None, None
    m = CS_PC_RE.fullmatch(str(raw).strip())
    if not m:
        raise ValueError(f"unparseable CS/PC quantity: {raw!r}")
    return int(m.group(1)), int(m.group(2))


def combine_total_units(cases: int | None, pieces: int | None, pack_size) -> int | None:
    """Cases + pieces combined into one total-units figure via PACK SIZE.
    None (not 0) whenever either side of the combination is missing —
    a fabricated combination is worse than a flagged gap."""
    if cases is None and pieces is None:
        return None
    if pack_size is None:
        return None
    try:
        pack_size_int = int(pack_size)
    except (TypeError, ValueError):
        return None
    return (cases or 0) * pack_size_int + (pieces or 0)


# Confirmed 14-column list minus Storage Location (R6, dropped entirely).
# raw header -> canonical field name. Kept in sync with
# config/column_maps/ssis_soh.yaml by hand — that file is the reviewable
# doc, this dict is the executable copy.
HEADER_TO_CANONICAL = {
    "Article No": "sku_code",
    "Article Description": "article_description",
    "PACK SIZE": "pack_size",
    "Stock Quantity (CS/PC)": "stock_quantity_raw",
    "Stock Value": "stock_value",
    "PO Qty": "po_qty_raw",
    "Open SO Quantity": "open_so_quantity_raw",
    "Balance Quantity": "balance_quantity_raw",
    "Last Purchase Price(GSV/CS)": "last_purchase_price_gsv_per_cs",
    "Status": "status",
    "CATEGORY DESC": "category_desc",
    "Blocked Stock(CS/PC)": "blocked_stock_raw",
    "Batch": "batch",
}


@dataclass
class SkipRecord:
    src_file: str
    reason: str
    detail: str = ""


@dataclass
class DuplicateRecord:
    src_file: str
    winning_file: str
    snapshot_date: str


@dataclass
class WarnRecord:
    src_file: str
    src_sheet: str
    message: str


@dataclass
class SohExtractResult:
    dfs: list = field(default_factory=list)  # list of (DataFrame, src_file, src_sheet, snapshot_date)
    r1_skipped: list[SkipRecord] = field(default_factory=list)
    r2_duplicates: list[DuplicateRecord] = field(default_factory=list)
    r3_rejected: list[SkipRecord] = field(default_factory=list)
    r4_warnings: list[WarnRecord] = field(default_factory=list)
    other_skipped: list[SkipRecord] = field(default_factory=list)
    file_rejects: list[RejectRecord] = field(default_factory=list)
    in_scope_file_count: int = 0


def _extract_soh_sheet(
    rel_path: str, abs_path: Path, sheet, period: str,
) -> tuple[pd.DataFrame | None, date | None, str | None, WarnRecord | None]:
    """Returns (df, final_snapshot_date, reject_reason, warn_record).
    df is None iff reject_reason is set."""
    trimmed = trim_grid(sheet.rows)
    hd = detect_header(trimmed)
    if hd.header_row_index < 0 or not trimmed:
        return None, None, "no detectable header", None

    header_row = trimmed[hd.header_row_index]
    data_rows = trimmed[hd.header_row_index + 1:]
    if not data_rows:
        return None, None, "header detected but no data rows", None

    header_labels = [
        str(h).strip() if not is_blank(h) else f"__col{i}__"
        for i, h in enumerate(header_row)
    ]

    # R7 — fail loud, do not silently coalesce with Last Purchase Price.
    if MOVING_AVG_PRICE_HEADER in header_labels:
        raise RuntimeError(
            f"R7 violation: {rel_path!r} sheet {sheet.name!r} (period {period}, "
            f"in-scope under R1) carries the pre-2023-era "
            f"'{MOVING_AVG_PRICE_HEADER}' column instead of "
            f"'Last Purchase Price(GSV/CS)'. This means either R1's scope "
            f"filter has a bug or a pre-2023-shaped file was misclassified as "
            f"in-scope — investigate before proceeding; do not coalesce the "
            f"two price columns."
        )

    raw_snapshot_date = parse_snapshot_date(sheet.name)
    if raw_snapshot_date is None:
        return None, None, f"unparsable snapshot date in sheet name {sheet.name!r}", None

    # R3 (dead code under R1 — kept explicit per the ruling).
    if raw_snapshot_date in REJECTED_SNAPSHOT_DATES:
        return None, None, f"R3: explicitly rejected snapshot date {raw_snapshot_date}", None

    # R4 date guard.
    p_end = period_end_date(period)
    delta_days = (raw_snapshot_date - p_end).days
    warn = None
    if 1 <= delta_days <= 45:
        final_date = raw_snapshot_date
    else:
        final_date = p_end + timedelta(days=1)
        warn = WarnRecord(
            rel_path, sheet.name,
            f"R4 date guard: sheet-name date {raw_snapshot_date} is {delta_days} days "
            f"from period end {p_end} (outside the 1-45 day window) — using "
            f"period-derived date {final_date} instead.",
        )
        # A period-derived date could itself land on the rejected R3 date —
        # check again rather than assume R3 only ever applies pre-correction.
        if final_date in REJECTED_SNAPSHOT_DATES:
            return None, None, f"R3: explicitly rejected snapshot date {final_date} (period-derived)", warn

    columns: dict[str, list] = {}
    idx_by_header = {h: i for i, h in enumerate(header_labels)}

    def raw_col(header: str) -> list:
        i = idx_by_header.get(header)
        if i is None:
            return [None] * len(data_rows)
        return [r[i] if i < len(r) else None for r in data_rows]

    sku_vals = raw_col("Article No")
    columns["sku_code"] = [None if is_blank(v) else _force_text(v) for v in sku_vals]
    columns["article_description"] = [None if is_blank(v) else str(v).strip() for v in raw_col("Article Description")]

    pack_size_raw = raw_col("PACK SIZE")
    pack_size_vals = [None if is_blank(v) else to_number(v) for v in pack_size_raw]
    columns["pack_size"] = pack_size_vals

    stock_qty_raw = raw_col("Stock Quantity (CS/PC)")
    stock_cases, stock_pieces, stock_total = [], [], []
    for v, ps in zip(stock_qty_raw, pack_size_vals):
        c, p = parse_cs_pc(v)
        stock_cases.append(c)
        stock_pieces.append(p)
        stock_total.append(combine_total_units(c, p, ps))
    columns["stock_quantity_raw"] = [None if is_blank(v) else str(v).strip() for v in stock_qty_raw]
    columns["stock_qty_cases"] = stock_cases
    columns["stock_qty_pieces"] = stock_pieces
    columns["stock_qty_total_units"] = stock_total

    def decimal_col(header: str) -> list:
        return [to_decimal(v) if not is_blank(v) else None for v in raw_col(header)]

    columns["stock_value"] = decimal_col("Stock Value")
    columns["po_qty_raw"] = [None if is_blank(v) else str(v).strip() for v in raw_col("PO Qty")]
    columns["open_so_quantity_raw"] = [None if is_blank(v) else str(v).strip() for v in raw_col("Open SO Quantity")]
    columns["balance_quantity_raw"] = [None if is_blank(v) else str(v).strip() for v in raw_col("Balance Quantity")]
    columns["last_purchase_price_gsv_per_cs"] = decimal_col("Last Purchase Price(GSV/CS)")
    columns["status"] = [None if is_blank(v) else str(v).strip() for v in raw_col("Status")]
    columns["category_desc"] = [None if is_blank(v) else str(v).strip() for v in raw_col("CATEGORY DESC")]

    blocked_raw = raw_col("Blocked Stock(CS/PC)")
    blocked_cases, blocked_pieces, blocked_total = [], [], []
    for v, ps in zip(blocked_raw, pack_size_vals):
        c, p = parse_cs_pc(v)
        blocked_cases.append(c)
        blocked_pieces.append(p)
        blocked_total.append(combine_total_units(c, p, ps))
    columns["blocked_stock_raw"] = [None if is_blank(v) else str(v).strip() for v in blocked_raw]
    columns["blocked_stock_cases"] = blocked_cases
    columns["blocked_stock_pieces"] = blocked_pieces
    columns["blocked_stock_total_units"] = blocked_total

    columns["batch"] = [None if is_blank(v) else str(v).strip() for v in raw_col("Batch")]

    n = len(data_rows)
    df = pd.DataFrame(columns)

    # R5
    df["snapshot_date"] = final_date
    df["snapshot_date_source"] = "sheet_name" if warn is None else "period_derived"

    # Provenance — same columns/semantics as every other doc_type
    # (_shared.PROVENANCE_COLUMNS), values chosen the same way _shared.py
    # would for this shape of source:
    df["_src_file"] = rel_path
    df["_src_sheet"] = sheet.name
    df["_header_row"] = hd.header_row_index
    df["_row_ordinal"] = list(range(n))
    # infer_principal_from_path resolves "ambiguous" for data/raw/SSIS/**
    # (no "unilever"/"del monte" token in that path) even though this
    # entire doc_type is confirmed Unilever-only by source (task brief,
    # reports/SOH_PROFILE.md) — hardcoded rather than trusting a path
    # heuristic known to be wrong for this specific source tree.
    df["_principal"] = "unilever"
    df["_region"] = "unknown"  # Storage Location (dropped, R6) was the
                                 # only per-row location signal and it was
                                 # single-valued ("SALE"), not a region.
    df["_period"] = period
    df["_doc_type"] = DOC_TYPE
    df["_sheet_role"] = "data"
    df["_grain"] = "sku"
    # No demonstrated reliable totals-row column for this doc_type
    # (never checked — out of scope for this ruling) — unverified, same
    # treatment as inventory_sign_off.
    df["_checksum_status"] = "unverified"
    df["_checksum_column"] = None
    df["_checksum_expected"] = None
    df["_checksum_got"] = None
    df["_checksum_diff"] = None

    assert list(df.columns)[-len(PROVENANCE_COLUMNS):] == PROVENANCE_COLUMNS, (
        "provenance columns drifted from _shared.PROVENANCE_COLUMNS"
    )

    return df, final_date, None, warn


def parse_ssis_soh(raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> SohExtractResult:
    raw_dir = raw_dir or (repo_root / "data" / "raw")
    result = SohExtractResult()

    candidate_files = [
        f for f in select_source_files(raw_dir)
        if infer_doc_type(f) == "ssis_summary"
    ]

    in_scope: list[tuple[Path, str]] = []
    for f in candidate_files:
        rel = f.relative_to(repo_root).as_posix()
        period = infer_period(f)
        if period is None:
            result.r1_skipped.append(SkipRecord(rel, "R1: unparseable reporting period"))
            continue
        if period < MIN_PERIOD:
            result.r1_skipped.append(SkipRecord(rel, "R1: pre-2023 file", f"period={period}"))
            continue
        in_scope.append((f, period))

    result.in_scope_file_count = len(in_scope)

    seen_snapshots: dict[date, str] = {}  # snapshot_date -> winning rel path

    for f, period in in_scope:
        rel = f.relative_to(repo_root).as_posix()
        wb = read_workbook(f, full_read=True)
        if wb.error and not wb.sheets:
            result.file_rejects.append(RejectRecord(rel, None, "file unreadable", wb.error or "unknown error"))
            continue

        matches = [s for s in wb.sheets if SOH_SHEET_RE.search(s.name)]
        if not matches:
            result.other_skipped.append(SkipRecord(rel, "no SOH sheet found in in-scope file"))
            continue
        if len(matches) > 1:
            result.r4_warnings.append(WarnRecord(
                rel, matches[0].name,
                f"{len(matches)} sheets matched SOH in one workbook — using the first "
                f"({matches[0].name!r}); others: {[s.name for s in matches[1:]]}",
            ))
        sheet = matches[0]

        df, final_date, reject_reason, warn = _extract_soh_sheet(rel, f, sheet, period)
        if warn is not None:
            result.r4_warnings.append(warn)
        if reject_reason is not None:
            result.r3_rejected.append(SkipRecord(rel, reject_reason))
            continue
        assert df is not None and final_date is not None

        if final_date in seen_snapshots:
            result.r2_duplicates.append(DuplicateRecord(rel, seen_snapshots[final_date], final_date.isoformat()))
            continue
        seen_snapshots[final_date] = rel

        result.dfs.append((df, rel, sheet.name, final_date))

    return result
