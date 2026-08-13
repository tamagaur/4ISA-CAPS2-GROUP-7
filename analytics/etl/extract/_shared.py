"""Shared Extract-stage core (ARCHITECTURE.md §6).

Generic over any (file, sheet) pair — doc-type-agnostic. Per-doc-type
modules (sales_register.py, etc.) select which files to hand to this core;
this module never renames columns, dedups, or resolves grain (Transform's
job) — it only reads faithfully, types with fidelity, tags provenance, and
checksums against the totals row.

Reuses the discovery pass's format-sniffing/detection primitives
(profiling.reader, profiling.detect, profiling.profile_files) rather than
duplicating them — those were reviewed and are the source of truth for how
this raw data actually looks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from profiling.detect import (
    contains_magnolia,
    detect_header,
    infer_dtype,
    infer_grain,
    infer_principal_from_content,
    is_blank,
    trim_grid,
)
from profiling.profile_files import (
    MM_DD_YYYY_RE,
    REGION_PATTERNS,
    infer_doc_type,
    infer_period,
    infer_principal_from_path,
    sanitize_filename,
)
from profiling.reader import WorkbookRead, read_workbook

from analytics.etl._coerce import MONEY_QUANT, NUMERIC_CELL_RE, to_decimal, to_number

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

PROVENANCE_COLUMNS = [
    "_src_file", "_src_sheet", "_header_row", "_row_ordinal", "_principal",
    "_region", "_period", "_doc_type", "_sheet_role", "_grain",
    "_checksum_status", "_checksum_column", "_checksum_expected", "_checksum_got", "_checksum_diff",
]

# ARCHITECTURE.md §6.4 step 5 — identifier/code columns that must never be
# coerced to a number (that would silently strip a leading zero, which the
# architecture calls out as "a bug, not a nuance"). "product" is the
# Unilever SKU workbook's SKU-code column (confirmed 8-digit numeric
# identifier) — anchored exact match so it doesn't catch Sell Out's
# distinct "Product Quantity" column, which is a real quantity.
TEXT_OVERRIDE_RE = re.compile(
    r"^(branch code|refnbr|reference\s*#|invoice num|outlet|product)$", re.I
)

# Some identifier columns have no header text at all to anchor a name-based
# override — ARCHITECTURE.md §6.3: Inventory Sign-Off's SKU code is
# "embedded in col 0", header-less. Position-based, scoped strictly to
# this doc_type: column 0 is Invoice Date in Sales Register, a genuinely
# different field, so this must never apply generically. Confirmed by
# evidence: this column round-trips as native Excel floats in some sheets
# (e.g. a bare SKU code with no description text alongside it), which
# would otherwise silently turn an identifier into a number.
FORCE_TEXT_COLUMN_INDEX: dict[str, set[int]] = {
    "inventory_sign_off": {0},
}

# Numeric columns that are currency vs. quantity read very similarly (both
# plain numbers) — distinguish by name. Deliberately conservative: only
# columns whose dtype is already "numeric" (per detect.infer_dtype) and
# whose name matches a money hint (and not a quantity hint) are coerced to
# Decimal; everything else numeric stays a plain number, unclassified as
# money without evidence.
MONEY_NAME_RE = re.compile(
    r"amount|amnt|\btax\b|balance|valuation|\bvalue\b|\bcost\b|gross|\bprice\b|\bgsv\b|\bniv\b",
    re.I,
)
QUANTITY_NAME_RE = re.compile(
    r"\bqty\b|quantity|\bcas\b|\bpcs\b|\bpkg\b|\bcases\b|\bpieces\b", re.I
)

# NUMERIC_CELL_RE, MONEY_QUANT moved to analytics/etl/_coerce.py (2026-08,
# shared with Transform — see that module's docstring). Re-imported above
# rather than redefined here.


def select_source_files(raw_dir: Path) -> list[Path]:
    """All .xlsx/.xls/.csv under raw_dir, excluding lock files (~$*) and
    non-tabular formats. Sorted for deterministic iteration order."""
    files = sorted(raw_dir.rglob("*"))
    return [
        f for f in files
        if f.is_file()
        and f.name != ".gitkeep"
        and not f.name.startswith("~$")
        and f.suffix.lower() in {".xlsx", ".xls", ".csv"}
    ]


CALENDAR_MONTH_COL_RE = re.compile(r"calendar\s*month", re.I)
MM_YYYY_RE = re.compile(r"^(\d{2})\.(20\d{2})$")


def row_periods_from_calendar_month(header_labels: list[str], columns: dict[str, list]) -> list[str] | None:
    """The Unilever SKU workbook stages ~3 years of monthly data in one
    sheet (2023-01 .. 2026-02), each row carrying its own "Calendar Month"
    cell (e.g. "01.2023") — a single sheet-level _period tag would flatten
    that away. Returns one period per row when every row's Calendar Month
    value parses cleanly, else None (falls back to the sheet-level tag)."""
    for col_name in header_labels:
        if not CALENDAR_MONTH_COL_RE.search(col_name):
            continue
        raw_vals = columns.get(col_name, [])
        periods = []
        for v in raw_vals:
            if v is None:
                periods.append("unknown")
                continue
            m = MM_YYYY_RE.match(str(v).strip())
            if not m:
                return None  # unparsable value — don't guess, fall back
            month, year = m.groups()
            periods.append(f"{year}-{month}")
        return periods
    return None


def infer_sheet_period(path: Path, sheet_name: str) -> str:
    """Daily-report workbooks carry one sheet per day, named MM.DD.YYYY
    (e.g. "07.08.2025") — that's a stronger period signal than the parent
    file's own filename (which just says "DAILY SALES REPORT 07.31.2025",
    the report's generation date, not this particular sheet's date).
    Reuses profile_files.MM_DD_YYYY_RE rather than a second copy."""
    m = MM_DD_YYYY_RE.search(sheet_name or "")
    if m:
        month, _day, year = m.groups()
        return f"{year}-{month}"
    return infer_period(path) or "unknown"


DAILY_REPORT_RE = re.compile(r"daily\s*sales\s*report|daily\s*report", re.I)

# Investigated 2026-08 (Transform reconciliation, story #16 prerequisite):
# the current corpus has zero files matching the true daily-report naming
# convention this regex targets ("DAILY SALES REPORT MM.DD.YYYY.xlsx" with
# per-day sheets). The files under data/raw/Del Monte/DAILY REPORT - .../
# are ordinary monthly Sales Register/RMR files someone filed under an
# inconsistently-named folder — DAILY_REPORT_RE correctly does not match
# their filenames, so daily_sales_report staging 0 rows in a real Extract
# run is expected, permanent behavior given this corpus, not a driver bug.
# Do not re-investigate this as a mystery; re-open only if a file matching
# the real convention actually shows up in data/raw/.


def refine_doc_type(path: Path, doc_type: str) -> str:
    """profiling.profile_files.DOC_TYPE_PATTERNS (frozen, already reviewed
    discovery-pass output) tags both the monthly Sales Register and daily
    reports as "sales_register" — they overlap (dailies sum to the
    monthly; DEC-04 makes the monthly file the system-of-record). Extract
    needs to tell them apart so Transform has a dedup hook, without
    touching that frozen classification. Tag only — do not dedup/drop."""
    if doc_type == "sales_register" and DAILY_REPORT_RE.search(path.name):
        return "daily_sales_report"
    return doc_type


def infer_sheet_region(path: Path, sheet_name: str) -> str:
    """Region tokens live in sheet names when a file splits by region
    (PANGASINAN/ILOCOS sheets in one workbook); fall back to the file path
    otherwise. Reuses REGION_PATTERNS rather than a second copy."""
    for region, pattern in REGION_PATTERNS:
        if pattern.search(sheet_name or ""):
            return region
    for region, pattern in REGION_PATTERNS:
        if pattern.search(str(path)):
            return region
    return "unknown"


SHEET_ROLE_PATTERNS = [
    ("raw_data", re.compile(r"raw\s*data", re.I)),
    ("per_customer_summary", re.compile(r"per\s*customer", re.I)),
    ("invoice_reg", re.compile(r"invoice\s*reg", re.I)),
    # RMR GS/BO workbooks: "ONE PAGER" = GS ∪ BO (a dedup trap — Transform
    # must pick one, not sum both) — checked before the standalone gs/bo
    # patterns below so a "... ONE PAGER" sheet isn't misclassified.
    ("one_pager", re.compile(r"one\s*pager", re.I)),
    # Index/cover sheets (e.g. "SCHEDULE" — observed inside daily/monthly
    # sales report workbooks, a per-day rollup with grain=summary, not
    # transactional rows) get their own role so they aren't mistaken for
    # ordinary "data".
    ("schedule", re.compile(r"schedule|\bindex\b|\bcover\b", re.I)),
    # RMR sheets named e.g. "PANG GS" / "ILOCOS BO" — same short codes
    # "Return Type" itself uses (GS/BO), kept consistent rather than
    # inventing new vocabulary.
    ("gs", re.compile(r"\bgs\b", re.I)),
    ("bo", re.compile(r"\bbo\b", re.I)),
]
_SCRATCH_NAME_RE = re.compile(r"^sheet\s*\d*$", re.I)


def infer_sheet_role(sheet_name: str, synthetic_name: bool = False) -> str:
    """ARCHITECTURE.md §5.2 sheet-role vocabulary. Extract tags the role;
    it does not decide which role is authoritative (that's DEC-04/Transform).

    synthetic_name=True for MHTML/CSV sources: profiling.reader always
    names their single sheet "sheet1" (there's no real per-sheet concept in
    those formats), which would otherwise collide with the "Sheet1/Sheet2"
    leftover-tab pattern used to catch genuine scratch tabs in multi-sheet
    Excel workbooks — for MHTML/CSV that lone sheet IS the entire dataset,
    never a leftover."""
    name = (sheet_name or "").strip()
    if not synthetic_name and (not name or _SCRATCH_NAME_RE.match(name)):
        return "scratch"
    for role, pattern in SHEET_ROLE_PATTERNS:
        if pattern.search(name):
            return role
    return "data"


def classify_column(name: str, values: list) -> str:
    """Returns one of: text_code | decimal | date | numeric | text."""
    norm = re.sub(r"\s+", " ", str(name).strip())
    if TEXT_OVERRIDE_RE.match(norm):
        return "text_code"
    dtype = infer_dtype(values)
    if dtype != "numeric":
        # MHTML/CSV sources (e.g. the Unilever SKU workbook) report every
        # cell as text, so a real money/quantity value shows up as a
        # comma-formatted string ("6,619.86") rather than a native
        # int/float — infer_dtype only recognizes the latter. Only trust a
        # numeric-looking string here when the column NAME already signals
        # money or quantity; an unnamed numeric-looking string (e.g. a
        # "01.2023"-style Calendar Month cell, which also matches the
        # digits-and-dots shape) stays text rather than risk silently
        # miscoercing something that only looks numeric.
        non_blank = [v for v in values if not is_blank(v)]
        looks_numeric_strings = non_blank and all(
            isinstance(v, str) and NUMERIC_CELL_RE.match(v.strip()) for v in non_blank
        )
        if looks_numeric_strings and (MONEY_NAME_RE.search(norm) or QUANTITY_NAME_RE.search(norm)):
            dtype = "numeric"
    if dtype == "numeric":
        if MONEY_NAME_RE.search(norm) and not QUANTITY_NAME_RE.search(norm):
            return "decimal"
        return "numeric"
    if dtype in ("datetime", "date-string"):
        return "date"
    return "text"


def _force_text(v):
    """str(v) for a float that's a whole number (e.g. Excel storing a bare
    SKU code as 9012345.0) would inject a spurious ".0" — never seen in
    the source cell, so never inventable here either."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return None  # unparsable — signals a fallback to text for the whole column


def coerce_column(name: str, values: list) -> tuple[list, str]:
    """Coerces the whole column to one pyarrow-safe type. A single stray
    unparsable value in an otherwise-numeric/date column would otherwise
    produce a mixed Decimal/date + str object column, which pyarrow
    cannot serialize — rather than partially coerce (which both breaks
    parquet writing and fabricates nothing extra), fall back the entire
    column to text so every real value is preserved verbatim."""
    kind = classify_column(name, values)
    non_blank = [v for v in values if not is_blank(v)]

    if kind == "decimal" and any(to_decimal(v) is None for v in non_blank):
        kind = "text"
    elif kind == "date" and any(_to_date(v) is None for v in non_blank):
        kind = "text"

    out = []
    for v in values:
        if is_blank(v):
            out.append(None)
            continue
        if kind == "text_code":
            out.append(_force_text(v))
        elif kind == "decimal":
            out.append(to_decimal(v))
        elif kind == "date":
            out.append(_to_date(v))
        elif kind == "numeric":
            out.append(to_number(v))
        else:
            out.append(_force_text(v))
    return out, kind


@dataclass
class ChecksumOutcome:
    src_file: str
    src_sheet: str
    column: str
    status: str  # pass | mismatch | unverified
    expected: float | None
    actual: float
    diff: float | None
    tolerance: float | None


def _parse_totals_cell(cell) -> Decimal | None:
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return Decimal(str(cell))
    if isinstance(cell, str) and NUMERIC_CELL_RE.match(cell.strip()):
        return Decimal(cell.strip().replace(",", ""))
    return None


def find_totals_row(trimmed_grid: list[list], junk_ranges: list[tuple[int, int]]) -> list | None:
    """The totals row isn't reliably "exactly one row above the header" —
    some layouts stack a title row above it too (header on row 2). Scan
    every row across the whole junk range and pick the one with the most
    numeric-parseable cells; None if nothing in the range looks numeric."""
    best_row, best_count = None, 0
    for start, end in junk_ranges:
        for idx in range(max(start, 0), min(end, len(trimmed_grid) - 1) + 1):
            row = trimmed_grid[idx]
            count = sum(1 for c in row if _parse_totals_cell(c) is not None)
            if count > best_count:
                best_count, best_row = count, row
    return best_row


def totals_row_checksum(
    trimmed_grid: list[list],
    junk_ranges: list[tuple[int, int]],
    header_labels: list[str],
    coerced_columns: dict[str, list],
    kinds: dict[str, str],
    src_file: str,
    src_sheet: str,
) -> list[ChecksumOutcome]:
    """ARCHITECTURE.md §6.4 step 6 / DEC-05, corrected per
    SSM_EXTRACT_FIX_AND_REVIEW_PROMPT.md: the totals row is a
    reconciliation *signal*, never a validation gate. Every decimal
    column gets an explicit outcome — pass/mismatch when a comparable
    total exists, unverified when it doesn't (no totals row, or that
    column has no numeric cell in it) — but nothing here causes a
    sheet to be dropped; that's decided by the caller, which now
    always stages regardless of this result."""
    decimal_cols = [c for c in header_labels if kinds.get(c) == "decimal"]
    if not decimal_cols:
        return []
    totals_row = find_totals_row(trimmed_grid, junk_ranges)

    outcomes = []
    for i, col_name in enumerate(header_labels):
        if kinds.get(col_name) != "decimal":
            continue
        actual = sum(
            (v for v in coerced_columns[col_name] if isinstance(v, Decimal)),
            Decimal("0"),
        )
        expected = _parse_totals_cell(totals_row[i]) if totals_row is not None and i < len(totals_row) else None
        if expected is None:
            outcomes.append(ChecksumOutcome(src_file, src_sheet, col_name, "unverified", None, float(actual), None, None))
            continue
        tolerance = max(MONEY_QUANT, abs(expected) * Decimal("0.001"))
        diff = abs(actual - expected)
        status = "pass" if diff <= tolerance else "mismatch"
        outcomes.append(ChecksumOutcome(
            src_file, src_sheet, col_name, status,
            float(expected), float(actual), float(diff), float(tolerance),
        ))
    return outcomes


# SSM_EXTRACT_CHECKSUM_REFINE_PROMPT.md: the totals row isn't a generic
# "sum everything" row — each doc family's totals row reliably reconciles
# to ONE specific column (confirmed against real files: Purchase Order's
# Untaxed Amount reconciles to the cent in 21/22 sheets, while its Net
# Amount/Balance cells are frequently stale; Sales Register's Net Amount
# is the reliable one). A doc_type with no entry here has no demonstrated
# reliable column at all (e.g. Inventory Sign-Off's Cost/Valuation aren't
# line-item sums — one sheet's stray numeric totals-row cell produced a
# nonsensical negative "expected" when blindly compared) — never checksum
# those; always unverified.
CANONICAL_CHECKSUM_COLUMN: dict[str, str] = {
    "sales_register": "Net Amount",
    "daily_sales_report": "Net Amount",
    "purchase_order": "Untaxed Amount",
    "rmr_gs_bo": "Net Amount",
}


def aggregate_checksum(
    outcomes: list[ChecksumOutcome], doc_type: str
) -> tuple[str, str | None, float | None, float | None, float | None]:
    """Sheet-level checksum verdict, aligned to doc_type's canonical money
    column only — never "whichever column happens to mismatch worst".
    Returns (status, compared_column, expected, actual, diff). All
    per-column outcomes (including non-canonical ones) still live in the
    full checksums list for transparency; this just decides what drives
    the sheet's headline status in the manifest/QC report."""
    canonical_col = CANONICAL_CHECKSUM_COLUMN.get(doc_type)
    if canonical_col is None:
        return "unverified", None, None, None, None
    for o in outcomes:
        if o.column == canonical_col:
            return o.status, o.column, o.expected, o.actual, o.diff
    return "unverified", canonical_col, None, None, None


@dataclass
class SheetOutcome:
    src_file: str
    src_sheet: str
    status: str  # staged | rejected
    row_count: int
    reason: str | None = None
    principal: str | None = None
    region: str | None = None
    period: str | None = None
    doc_type: str | None = None
    sheet_role: str | None = None
    grain: str | None = None
    columns: list[str] | None = None
    checksum_status: str | None = None  # pass | mismatch | unverified (staged sheets only)
    checksum_column: str | None = None  # which column drove the verdict (e.g. "Net Amount")
    checksum_expected: float | None = None
    checksum_got: float | None = None
    checksum_diff: float | None = None


@dataclass
class RejectRecord:
    src_file: str
    src_sheet: str | None
    reason: str
    evidence: str


def extract_sheet(rel_path: str, abs_path: Path, sheet, doc_type: str, real_format: str = "xlsx"):
    """Returns (DataFrame | None, SheetOutcome, list[ChecksumOutcome]).

    staging/_rejects/ is reserved for: unreadable (handled by the caller,
    process_file), no detectable header/data, or Magnolia content — never
    a checksum mismatch. A checksum mismatch is staged with its status
    recorded, not dropped (see SSM_EXTRACT_FIX_AND_REVIEW_PROMPT.md Part A)."""
    trimmed = trim_grid(sheet.rows)
    hd = detect_header(trimmed)
    if hd.header_row_index < 0 or not trimmed:
        return None, SheetOutcome(rel_path, sheet.name, "rejected", 0, "no detectable header"), []

    header_row = trimmed[hd.header_row_index]
    data_rows = trimmed[hd.header_row_index + 1:]
    if not data_rows:
        return None, SheetOutcome(rel_path, sheet.name, "rejected", 0, "header detected but no data rows"), []

    if contains_magnolia(trimmed):
        return None, SheetOutcome(
            rel_path, sheet.name, "rejected", len(data_rows),
            "Magnolia content detected — quarantined, permanently out of scope",
        ), []

    header_labels = [
        str(h).strip() if not is_blank(h) else f"__col{i}__"
        for i, h in enumerate(header_row)
    ]

    force_text_cols = FORCE_TEXT_COLUMN_INDEX.get(doc_type, set())
    columns: dict[str, list] = {}
    kinds: dict[str, str] = {}
    for i, col_name in enumerate(header_labels):
        col_vals = [r[i] if i < len(r) else None for r in data_rows]
        if i in force_text_cols:
            coerced = [None if is_blank(v) else _force_text(v) for v in col_vals]
            kind = "text_code"
        else:
            coerced, kind = coerce_column(col_name, col_vals)
        columns[col_name] = coerced
        kinds[col_name] = kind

    doc_type = refine_doc_type(abs_path, doc_type)

    # Only compute a totals-row comparison at all when this doc_type has a
    # demonstrated reliable checksum column — forcing a comparison against
    # a family with no such column (e.g. Inventory Sign-Off's Cost/
    # Valuation, which aren't line-item sums) produced a nonsensical
    # negative "expected" on real data. See SSM_EXTRACT_CHECKSUM_REFINE_PROMPT.md.
    if doc_type in CANONICAL_CHECKSUM_COLUMN:
        checksums = totals_row_checksum(
            trimmed, hd.junk_ranges, header_labels, columns, kinds, rel_path, sheet.name
        )
    else:
        checksums = []
    checksum_status, checksum_column, checksum_expected, checksum_got, checksum_diff = aggregate_checksum(
        checksums, doc_type
    )

    path_principal = infer_principal_from_path(abs_path)
    content_principal, _evidence = infer_principal_from_content(header_row, data_rows)
    principal = path_principal if path_principal != "ambiguous" else content_principal
    region = infer_sheet_region(abs_path, sheet.name)
    sheet_role = infer_sheet_role(sheet.name, synthetic_name=real_format in ("mhtml", "csv"))
    grain = infer_grain(header_row, data_rows)

    row_periods = row_periods_from_calendar_month(header_labels, columns)
    if row_periods is not None:
        period_col = row_periods
        distinct = sorted(set(row_periods) - {"unknown"})
        period_for_manifest = f"{distinct[0]}..{distinct[-1]}" if distinct else "unknown"
    else:
        period_col = infer_sheet_period(abs_path, sheet.name)
        period_for_manifest = period_col

    n = len(data_rows)
    df = pd.DataFrame(columns)
    df["_src_file"] = rel_path
    df["_src_sheet"] = sheet.name
    df["_header_row"] = hd.header_row_index
    df["_row_ordinal"] = list(range(n))
    df["_principal"] = principal
    df["_region"] = region
    df["_period"] = period_col
    df["_doc_type"] = doc_type
    df["_sheet_role"] = sheet_role
    df["_grain"] = grain
    df["_checksum_status"] = checksum_status
    df["_checksum_column"] = checksum_column
    df["_checksum_expected"] = checksum_expected
    df["_checksum_got"] = checksum_got
    df["_checksum_diff"] = checksum_diff

    outcome = SheetOutcome(
        rel_path, sheet.name, "staged", n, None,
        principal=principal, region=region, period=period_for_manifest, doc_type=doc_type,
        sheet_role=sheet_role, grain=grain, columns=list(columns.keys()),
        checksum_status=checksum_status, checksum_column=checksum_column,
        checksum_expected=checksum_expected, checksum_got=checksum_got, checksum_diff=checksum_diff,
    )
    return df, outcome, checksums


@dataclass
class FileExtractResult:
    dfs: list = field(default_factory=list)
    outcomes: list[SheetOutcome] = field(default_factory=list)
    checksums: list[ChecksumOutcome] = field(default_factory=list)
    file_reject: RejectRecord | None = None


def process_file(abs_path: Path, doc_type: str, repo_root: Path = REPO_ROOT) -> FileExtractResult:
    """result.dfs is a list of (DataFrame, SheetOutcome) pairs — one per
    staged sheet, kept paired so callers never have to zip two lists back
    together by position."""
    rel = abs_path.relative_to(repo_root).as_posix()
    wb: WorkbookRead = read_workbook(abs_path, full_read=True)
    if wb.error and not wb.sheets:
        return FileExtractResult(
            file_reject=RejectRecord(rel, None, "file unreadable", wb.error or "unknown error")
        )
    result = FileExtractResult()
    for sheet in wb.sheets:
        df, outcome, checksums = extract_sheet(rel, abs_path, sheet, doc_type, real_format=wb.real_format)
        result.outcomes.append(outcome)
        result.checksums.extend(checksums)
        if df is not None:
            result.dfs.append((df, outcome))
    return result


@dataclass
class ExtractRunResult:
    dfs: list = field(default_factory=list)  # list of (DataFrame, SheetOutcome)
    outcomes: list[SheetOutcome] = field(default_factory=list)
    checksums: list[ChecksumOutcome] = field(default_factory=list)
    file_rejects: list[RejectRecord] = field(default_factory=list)


def parse_doc_type_files(doc_type: str, raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> ExtractRunResult:
    """Generic per-family driver body: select every raw file whose
    filename resolves to doc_type (profiling.profile_files.infer_doc_type,
    frozen discovery-pass classification), run each through process_file.
    Each family module (sales_register.py, etc.) is just this call plus
    its own DOC_TYPE constant — no per-file logic here."""
    raw_dir = raw_dir or (repo_root / "data" / "raw")
    files = [f for f in select_source_files(raw_dir) if infer_doc_type(f) == doc_type]

    result = ExtractRunResult()
    for f in files:
        file_result = process_file(f, doc_type, repo_root=repo_root)
        result.outcomes.extend(file_result.outcomes)
        result.checksums.extend(file_result.checksums)
        if file_result.file_reject:
            result.file_rejects.append(file_result.file_reject)
        result.dfs.extend(file_result.dfs)
    return result


def write_staging_table(df: pd.DataFrame, doc_type: str, rel_path: str, sheet_name: str, staging_dir: Path) -> Path:
    out_dir = staging_dir / doc_type
    out_dir.mkdir(parents=True, exist_ok=True)
    file_stem = sanitize_filename(Path(rel_path).stem)
    sheet_stem = sanitize_filename(sheet_name)
    out_path = out_dir / f"{file_stem}__{sheet_stem}.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    return out_path


def write_reject(rejects_dir: Path, src_file: str, src_sheet: str | None, reason: str, evidence: str) -> Path:
    import json

    rejects_dir.mkdir(parents=True, exist_ok=True)
    stem = sanitize_filename(Path(src_file).stem)
    name = f"{stem}__{sanitize_filename(src_sheet)}.json" if src_sheet else f"{stem}.json"
    out_path = rejects_dir / name
    out_path.write_text(
        json.dumps({"src_file": src_file, "src_sheet": src_sheet, "reason": reason, "evidence": evidence}, indent=2),
        encoding="utf-8",
    )
    return out_path


def build_manifest(outcomes: list[SheetOutcome], file_rejects: list[RejectRecord]) -> dict:
    """staging/_manifest.json shape per SSM_EXTRACT_FIX_AND_REVIEW_PROMPT.md
    Part B — the sole input to analytics/etl/_review.py's HTML renderer."""
    staged = []
    rejects = []
    for o in outcomes:
        if o.status == "staged":
            staged.append({
                "src_file": o.src_file, "src_sheet": o.src_sheet,
                "principal": o.principal, "region": o.region, "period": o.period,
                "doc_type": o.doc_type, "sheet_role": o.sheet_role, "grain": o.grain,
                "row_count": o.row_count, "columns": o.columns or [],
                "checksum_status": o.checksum_status,
                "checksum_column": o.checksum_column,
                "checksum_expected": o.checksum_expected,
                "checksum_got": o.checksum_got,
                "checksum_diff": o.checksum_diff,
            })
        else:
            rejects.append({"src_file": o.src_file, "src_sheet": o.src_sheet, "reason": o.reason})
    for r in file_rejects:
        rejects.append({"src_file": r.src_file, "src_sheet": r.src_sheet, "reason": f"{r.reason}: {r.evidence}"})
    return {"staged": staged, "reject": rejects}


def save_manifest(manifest: dict, staging_dir: Path) -> Path:
    import json

    out_path = staging_dir / "_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
