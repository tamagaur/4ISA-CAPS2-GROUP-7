"""Format-sniffing raw-file reader for the SSM ETL discovery pass.

Dispatches on magic bytes, never on file extension. Returns a raw cell
grid (list[list[Any]]) per sheet plus the detected real format. This
module performs no interpretation (no header detection, no dtype
inference) — that lives in profile_files.py.
"""
from __future__ import annotations

import email
import quopri
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl

try:
    import xlrd  # noqa: F401
    HAVE_XLRD = True
except ImportError:
    HAVE_XLRD = False


XLSX_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
PDF_MAGIC = b"%PDF"


@dataclass
class SheetGrid:
    name: str
    rows: list[list[Any]] = field(default_factory=list)  # raw, untrimmed
    truncated: bool = False


@dataclass
class WorkbookRead:
    real_format: str  # xlsx | xls-biff | mhtml | csv | pdf | unsupported
    sheets: list[SheetGrid] = field(default_factory=list)
    error: str | None = None


def sniff_format(path: Path) -> str:
    """Detect real format from magic bytes, ignoring the extension."""
    with open(path, "rb") as f:
        head = f.read(4096)

    if head.startswith(PDF_MAGIC):
        return "pdf"
    if head.startswith(XLSX_MAGIC):
        return "xlsx"
    if head.startswith(OLE_MAGIC):
        return "xls-biff"

    # MHTML web archives are ASCII/text at the start ("MIME-Version:",
    # "From:", or a multipart boundary declaration).
    try:
        text_head = head.decode("ascii", errors="ignore")
    except Exception:
        text_head = ""
    if "MIME-Version:" in text_head or text_head.lstrip().startswith("From:"):
        return "mhtml"

    # Fallback: plausible CSV/plain text if it decodes and has no
    # binary control characters beyond common whitespace.
    try:
        sample = head.removeprefix(b"\xef\xbb\xbf").decode("utf-8")   # Excel's "CSV UTF-8" starts with a byte-order mark
        if all(c.isprintable() or c in "\r\n\t" for c in sample):
            return "csv"
    except UnicodeDecodeError:
        pass

    return "unsupported"


# openpyxl's reported max_column/max_row can be wildly inflated by stale
# sheetDimension XML (observed up to 16384 cols on sheets with ~9 real
# columns) — iterating the full reported grid on such sheets is
# effectively an O(16384 * max_row) scan and can hang for minutes.
# Scan a bounded probe window first to find the real last non-empty
# column/row, then read only that bounded range.
PROBE_ROWS = 200
HARD_COL_CAP = 500


def _find_real_extent(ws) -> tuple[int, int]:
    """Probe the first PROBE_ROWS rows (over the full reported width) to
    find the true last non-empty column, and note there may be more rows
    below — returns (last_col, probe_row_count)."""
    last_col = 0
    row_count = 0
    for row in ws.iter_rows(min_row=1, max_row=PROBE_ROWS, values_only=True):
        row_count += 1
        capped = row[:HARD_COL_CAP] if len(row) > HARD_COL_CAP else row
        for i in range(len(capped) - 1, -1, -1):
            if capped[i] is not None and capped[i] != "":
                last_col = max(last_col, i + 1)
                break
    return last_col, row_count


# In read_only mode, openpyxl materializes one row object per row of the
# *declared* sheetDimension, not per row that actually holds data. When
# that declaration is a phantom 1,048,576 (observed on "SCHEDULE"-style
# ghost sheets with real data in ~10 rows), a plain iter_rows() walk is
# O(declared_max_row) instead of O(real_data_rows). Stream row-by-row and
# stop once we've seen a long run of fully-blank rows after real data.
BLANK_ROW_STREAK_LIMIT = 500

# Separately from the phantom-dimension pathology above, some sheets (observed:
# large multi-thousand-row SSIS exports) exhibit openpyxl read-only iteration
# that is linear for the first few thousand rows and then degrades sharply
# (500 rows in ~0.1s becoming 500 rows in ~18s past a certain point) for
# reasons not fully diagnosed (suspected: unbounded growth in an internal
# style/number-format lookup). A row-count cap would still land inside the
# slow zone on some files, so bound by wall-clock time instead: this is a
# discovery/profiling pass, not the production loader, and a partial read is
# disclosed via `truncated` rather than silently returned as complete.
import time as _time
READ_TIME_BUDGET_SECONDS = 20


def _stream_bounded_rows(ws, max_col: int, full_read: bool = False,
                         max_rows: int | None = None) -> tuple[list[list], bool]:
    rows: list[list] = []
    seen_data = False
    blank_streak = 0
    start = _time.monotonic()
    truncated = False
    for i, row in enumerate(ws.iter_rows(min_col=1, max_col=max_col, max_row=max_rows, values_only=True)):
        rows.append(list(row))
        if all(is_blank_cell(v) for v in row):
            if seen_data:
                blank_streak += 1
                if blank_streak >= BLANK_ROW_STREAK_LIMIT:
                    break
        else:
            seen_data = True
            blank_streak = 0
        # full_read (Extract stage) needs every row for its totals-row
        # checksum and completeness QC gates — a partial read would be a
        # silent data loss there, not a disclosed sample as it is for
        # profiling. Only the discovery pass's time budget applies below.
        if not full_read and _time.monotonic() - start > READ_TIME_BUDGET_SECONDS:
            truncated = True
            break
    return rows, truncated


def is_blank_cell(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _read_xlsx(path: Path, full_read: bool = False, max_rows: int | None = None) -> WorkbookRead:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            last_col, probed = _find_real_extent(ws)
            last_col = max(last_col, 1)
            rows, truncated = _stream_bounded_rows(ws, last_col, full_read=full_read, max_rows=max_rows)
            sheets.append(SheetGrid(name=sheet_name, rows=rows, truncated=truncated))
        return WorkbookRead(real_format="xlsx", sheets=sheets)
    finally:
        wb.close()


def _read_xls_biff(path: Path) -> WorkbookRead:
    if not HAVE_XLRD:
        return WorkbookRead(
            real_format="xls-biff",
            error="xlrd not installed — cannot parse legacy BIFF .xls",
        )
    book = xlrd.open_workbook(str(path))
    sheets = []
    for sheet_name in book.sheet_names():
        sh = book.sheet_by_name(sheet_name)
        rows = [sh.row_values(r) for r in range(sh.nrows)]
        sheets.append(SheetGrid(name=sheet_name, rows=rows))
    return WorkbookRead(real_format="xls-biff", sheets=sheets)


def _extract_table_rows(table_el) -> list[list]:
    """Extract a raw cell grid from an lxml <table> element, expanding
    colspan (not rowspan — Excel MHTML exports don't merge vertically in
    the data body). Directly walking the parsed tree is far faster than
    pandas.read_html's BeautifulSoup-backed engine on large (~25k row)
    single-table documents."""
    rows = []
    for tr in table_el.findall(".//tr"):
        cells = []
        for cell in tr.findall("./td") + tr.findall("./th"):
            text = "".join(cell.itertext()).strip()
            colspan = int(cell.get("colspan", 1) or 1)
            cells.append(text if text else None)
            cells.extend([None] * (colspan - 1))
        rows.append(cells)
    return rows


def _read_mhtml(path: Path) -> WorkbookRead:
    from lxml import html as lxml_html

    with open(path, "rb") as f:
        raw = f.read()

    msg = email.message_from_bytes(raw)
    html_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=False)
                if part.get("Content-Transfer-Encoding", "").lower() == "quoted-printable":
                    decoded = quopri.decodestring(payload.encode("ascii", errors="ignore"))
                else:
                    decoded = payload.encode("utf-8", errors="ignore")
                charset = part.get_content_charset() or "utf-8"
                html_parts.append(decoded.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True) or b""
        html_parts.append(payload.decode("utf-8", errors="replace"))

    if not html_parts:
        return WorkbookRead(real_format="mhtml", error="no text/html MIME part found")

    # Take the largest HTML part — that's the actual sheet content;
    # smaller parts are typically embedded images/styles metadata.
    html = max(html_parts, key=len)

    try:
        tree = lxml_html.fromstring(html)
    except Exception as e:  # noqa: BLE001
        return WorkbookRead(real_format="mhtml", error=f"lxml failed to parse HTML: {type(e).__name__}: {e}")

    tables = tree.findall(".//table")
    if not tables:
        return WorkbookRead(real_format="mhtml", error="no <table> elements found in HTML")

    # Largest table by row count is the real data grid; MHTML exports
    # from Excel often carry small decorative tables too.
    table_rows = [(_extract_table_rows(t), t) for t in tables]
    rows, _ = max(table_rows, key=lambda tr: len(tr[0]))
    return WorkbookRead(real_format="mhtml", sheets=[SheetGrid(name="sheet1", rows=rows)])


def _read_csv(path: Path) -> WorkbookRead:
    import pandas as pd

    last_err = None
    for encoding in ("utf-8-sig", "latin1"):     # utf-8-sig reads plain UTF-8 too, and keeps Excel's byte-order mark out of the first header
        try:
            df = pd.read_csv(path, header=None, encoding=encoding, dtype=object)
            df = df.astype(object).where(df.notna(), None)   # a blank cell is None, as in every other reader (detect.is_blank)
            rows = [list(r) for r in df.itertuples(index=False, name=None)]
            return WorkbookRead(real_format="csv", sheets=[SheetGrid(name="sheet1", rows=rows)])
        except Exception as e:  # noqa: BLE001 - trying multiple encodings deliberately
            last_err = e
    return WorkbookRead(real_format="csv", error=f"could not decode as CSV: {last_err}")


def read_workbook(path: Path, full_read: bool = False, max_rows: int | None = None) -> WorkbookRead:
    """Read a raw file into sheet grids, dispatching on sniffed magic bytes.

    full_read=True disables the xlsx read-time budget (see
    _stream_bounded_rows) so every row is captured. Defaults to False so
    the discovery pass's behavior — and its already-reviewed, byte-identical
    output — is unchanged; the Extract stage passes full_read=True since it
    needs complete data for its totals-row checksum and accountability QC.
    xls-biff, mhtml, and csv readers already read every row regardless.

    max_rows (2026-09-30, layout identification) keeps only each sheet's
    first max_rows rows - a header read, not a data read. xlsx stops
    streaming there; the other formats are parsed whole and then cut.
    """
    wb = _read_workbook(path, full_read, max_rows)
    if max_rows is not None:
        for sheet in wb.sheets:
            sheet.rows = sheet.rows[:max_rows]
    return wb


def _read_workbook(path: Path, full_read: bool, max_rows: int | None = None) -> WorkbookRead:
    real_format = sniff_format(path)
    try:
        if real_format == "xlsx":
            return _read_xlsx(path, full_read=full_read, max_rows=max_rows)
        if real_format == "xls-biff":
            return _read_xls_biff(path)
        if real_format == "mhtml":
            return _read_mhtml(path)
        if real_format == "csv":
            return _read_csv(path)
        if real_format == "pdf":
            return WorkbookRead(real_format="pdf", error="PDF is not a tabular source; not profiled")
        return WorkbookRead(real_format="unsupported", error="unrecognized magic bytes")
    except Exception as e:  # noqa: BLE001 - discovery pass must never crash on one bad file
        return WorkbookRead(real_format=real_format, error=f"{type(e).__name__}: {e}")
