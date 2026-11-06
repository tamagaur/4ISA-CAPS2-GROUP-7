"""
analytics.month_file - read a month's sales file and say WHICH MONTH IT IS FOR, from what is inside it (2026-11-06).

The period is never taken from the file's name. A person may call the file anything ("sales.csv", "Copy of final (2).xlsx"); the name plays no
part. The period is read, in this order, from
  1. a date column (calendar_month, month, period, date, invoice_date, ...): every dated row must fall in ONE calendar month, and where the values
     carry a day (2026-03-17) the first and last day are reported;
  2. otherwise a period written above the table (a title row such as "Unilever sales, March 2026" or "2026-03") in the first rows of the sheet.
A file that cannot be dated, whose rows are dated in more than one month, or whose dates cannot be read unambiguously is REFUSED, with the reason.

Supported formats: .csv (comma, semicolon or tab), .xlsx, .xls. The table's header row is found in the first 40 rows, so a title block above it is fine.
Columns are matched by name (aliases below): a product code, a quantity and a net amount are required; gsv, region and the date are optional.
One row per product per month. If the file carries a DAY, several rows of one product are daily sales and are summed; if it carries only a month,
a product listed twice is refused, because nothing says which row is right.

Pure reading: no database, no network, nothing written.
"""
from __future__ import annotations

import csv
import datetime
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_ROWS = 400_000
HEADER_SCAN_ROWS = 40
TITLE_SCAN_ROWS = 12
SUFFIXES = (".csv", ".xlsx", ".xls")

ALIASES = {
    "sku_code": {"sku_code", "sku", "skucode", "material", "material code", "materialcode", "item code", "itemcode", "product code", "productcode", "article", "article code"},
    "quantity_sold": {"quantity_sold", "quantity", "qty", "qty sold", "quantity sold", "pieces", "units", "units sold", "pcs"},
    "net_amount": {"net_amount", "net amount", "net sales", "net_sales", "net value", "sales amount", "amount", "net sales value", "net"},
    "date": {"calendar_month", "calendar month", "month", "period", "sales month", "sales period", "date", "invoice date", "invoice_date", "posting date",
             "document date", "doc date", "transaction date", "sale date", "sales date"},
    "gsv": {"gsv", "gross sales value", "gross sales"},
    "region": {"region", "area", "branch"},
}
MONTH_NAMES = {name: i for i, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
    ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december")), start=1) for name in names}
_MONTH_YEAR = re.compile(r"\b(" + "|".join(sorted(MONTH_NAMES, key=len, reverse=True)) + r")\.?[\s,\-/]+(20\d\d)\b", re.I)
_YEAR_MONTH = re.compile(r"\b(20\d\d)[-/.](0?[1-9]|1[0-2])(?![-/.]\d)(?!\d)")
_ISO_DAY = re.compile(r"^(20\d\d)[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])(?:[ T].*)?$")
_YEAR_MONTH_ONLY = re.compile(r"^(20\d\d)[-/.](0?[1-9]|1[0-2])$")
_SLASH_DAY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)$")
_MONTH_YEAR_ONLY = re.compile(r"^(" + "|".join(sorted(MONTH_NAMES, key=len, reverse=True)) + r")\.?[\s,\-/]+(20\d\d)$", re.I)


@dataclass
class MonthFile:
    ok: bool
    period: str | None = None                  # 'YYYY-MM', from the file's contents
    basis: str | None = None                   # how it was dated, in words
    first_day: str | None = None
    last_day: str | None = None
    rows: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    raw_rows: int = 0

    def message(self, limit: int = 4) -> str:
        if self.ok:
            return f"{len(self.rows)} products for {self.period}, dated by {self.basis}"
        shown = "; ".join(self.problems[:limit])
        return shown + (f" (and {len(self.problems) - limit} more)" if len(self.problems) > limit else "")


def _norm(cell) -> str:
    return re.sub(r"\s+", " ", str(cell if cell is not None else "")).strip().lower().replace("_", " ")


_ALIAS_LOOKUP = {name.replace("_", " "): key for key, names in ALIASES.items() for name in names}


def _alias_key(cell) -> str | None:
    return _ALIAS_LOOKUP.get(_norm(cell))


def read_cells(path: Path) -> tuple[list[list], str | None]:
    """(rows of raw cells, problem). The whole first sheet that holds a table, or the CSV."""
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        return [], f"{path.suffix or 'this'} files are not read here: send a .csv, .xlsx or .xls file"
    try:
        if suffix == ".csv":
            text = path.read_bytes().decode("utf-8-sig")
            dialect = csv.excel
            try:
                dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
            except csv.Error:
                pass
            return [list(r) for r in csv.reader(io.StringIO(text), dialect)][:MAX_ROWS], None
        import pandas as pd
        sheets = pd.read_excel(path, header=None, sheet_name=None, dtype=object)
        for frame in sheets.values():
            rows = frame.where(frame.notna(), None).values.tolist()
            if rows and header_row(rows[:HEADER_SCAN_ROWS]) is not None:
                return rows[:MAX_ROWS], None
        return [], "no sheet of the workbook holds a table with a product code, a quantity and a net amount"
    except UnicodeDecodeError:
        return [], "the CSV is not UTF-8 text: save it again as CSV UTF-8"
    except Exception as exc:  # noqa: BLE001 - a corrupt or password-protected workbook is a refusal with a reason, not a crash
        return [], f"the file could not be read as {suffix[1:].upper()} ({type(exc).__name__})"


def header_row(rows: list[list]) -> int | None:
    for i, row in enumerate(rows):
        keys = {_alias_key(c) for c in row}
        if {"sku_code", "quantity_sold", "net_amount"} <= keys:
            return i
    return None


def _ymd(value) -> tuple[int, int, int | None] | None | str:
    """(year, month, day or None) for one date cell; None for blank; 'ambiguous' / 'unreadable' for text that cannot be read safely."""
    if value is None or (isinstance(value, float) and value != value) or str(value).strip() == "":
        return None
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.year, value.month, value.day
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):   # pandas Timestamp
        return value.year, value.month, value.day
    text = str(value).strip()
    if (found := _ISO_DAY.match(text)):
        return int(found[1]), int(found[2]), int(found[3])
    if (found := _YEAR_MONTH_ONLY.match(text)):
        return int(found[1]), int(found[2]), None
    if (found := _MONTH_YEAR_ONLY.match(text)):
        return int(found[2]), MONTH_NAMES[found[1].lower()], None
    if (found := _SLASH_DAY.match(text)):
        a, b, year = int(found[1]), int(found[2]), int(found[3])
        if a > 12 >= b:
            return year, b, a
        if b > 12 >= a:
            return year, a, b
        return "ambiguous" if a != b else (year, a, b)
    return "unreadable"


def title_period(rows: list[list]) -> tuple[str | None, str | None]:
    """A period written above the table: ('YYYY-MM', where) or (None, problem)."""
    found: dict[str, str] = {}
    for n, row in enumerate(rows[:TITLE_SCAN_ROWS], start=1):
        for cell in row:
            text = str(cell) if cell is not None else ""
            for m in _MONTH_YEAR.finditer(text):
                found.setdefault(f"{int(m[2])}-{MONTH_NAMES[m[1].lower()]:02d}", f"“{text.strip()[:60]}” in row {n}")
            for m in _YEAR_MONTH.finditer(text):
                found.setdefault(f"{int(m[1])}-{int(m[2]):02d}", f"“{text.strip()[:60]}” in row {n}")
    if len(found) == 1:
        period, where = next(iter(found.items()))
        return period, where
    if len(found) > 1:
        return None, f"the title rows name more than one month ({', '.join(sorted(found))})"
    return None, None


def read_month_file(path: Path) -> MonthFile:
    """The file's rows and the month they are for. Never opens a database, never looks at the file's name."""
    cells, problem = read_cells(path)
    if problem:
        return MonthFile(False, problems=[problem])
    start = header_row(cells[:HEADER_SCAN_ROWS])
    if start is None:
        return MonthFile(False, raw_rows=len(cells), problems=[
            "the file has no table with a product code, a quantity and a net amount (columns like sku_code, quantity_sold, net_amount, found in the first 40 rows)"])
    columns: dict[str, int] = {}
    for idx, cell in enumerate(cells[start]):
        key = _alias_key(cell)
        if key and key not in columns:
            columns[key] = idx
    body = [r for r in cells[start + 1:] if any(c is not None and str(c).strip() for c in r)]
    out = MonthFile(False, raw_rows=len(body))
    # --- the period, from the contents
    months: dict[tuple[int, int], int] = {}
    days: list[datetime.date] = []
    unreadable = ambiguous = 0
    basis = None
    if "date" in columns:
        for r in body:
            got = _ymd(r[columns["date"]] if columns["date"] < len(r) else None)
            if got == "ambiguous":
                ambiguous += 1
            elif got == "unreadable":
                unreadable += 1
            elif got:
                months[(got[0], got[1])] = months.get((got[0], got[1]), 0) + 1
                if got[2]:
                    days.append(datetime.date(got[0], got[1], got[2]))
        label = str(cells[start][columns["date"]]).strip()
        if ambiguous:
            out.problems.append(f"{ambiguous} date(s) in “{label}” are like 03/04/2026, which could be March 4 or April 3: write dates as 2026-03-04")
        if unreadable:
            out.problems.append(f"{unreadable} value(s) in “{label}” are not dates the system can read (use 2026-03, 2026-03-17 or March 2026)")
        if len(months) > 1:
            listing = ", ".join(f"{y}-{m:02d} ({n} rows)" for (y, m), n in sorted(months.items()))
            out.problems.append(f"the file is dated in more than one month: {listing}. A file covers one month")
        elif len(months) == 1 and not ambiguous and not unreadable:
            (y, m), = months
            out.period = f"{y}-{m:02d}"
            basis = f"its “{label}” column"
    if out.period is None and not out.problems:
        period, where = title_period(cells[:start] if start else cells)
        if period:
            out.period, basis = period, where
        elif where:
            out.problems.append(where)
    if out.period is None and not out.problems:
        out.problems.append("the file cannot be dated: it has no date or month column and no month written above the table. "
                            "A file's month is read from what is inside it, never from its name")
    if out.problems:
        return out
    out.basis = basis
    if days:
        out.first_day, out.last_day = min(days).isoformat(), max(days).isoformat()
    # --- the rows
    daily = bool(days)
    seen: dict[str, dict] = {}
    for n, r in enumerate(body, start=start + 2):
        def cell(key):
            i = columns.get(key)
            return r[i] if i is not None and i < len(r) else None
        sku = str(cell("sku_code") or "").strip()
        if sku.endswith(".0") and sku[:-2].isdigit():   # an Excel number that was a code
            sku = sku[:-2]
        if not sku:
            out.problems.append(f"row {n}: no product code")
            continue
        try:
            qty, net = float(str(cell("quantity_sold")).replace(",", "")), float(str(cell("net_amount")).replace(",", ""))
            gsv = float(str(cell("gsv")).replace(",", "")) if cell("gsv") not in (None, "") else None
        except ValueError:
            out.problems.append(f"row {n}: {sku} has a quantity, amount or gsv that is not a number")
            continue
        if qty < 0 or net < 0:
            out.problems.append(f"row {n}: {sku} has a negative quantity or amount")
            continue
        region = str(cell("region")).strip() if cell("region") not in (None, "") else None
        if sku in seen:
            if not daily:
                out.problems.append(f"row {n}: {sku} appears twice in a file that carries only a month")
                continue
            prior = seen[sku]
            prior["quantity_sold"] += qty
            prior["net_amount"] += net
            if gsv is not None:
                prior["gsv"] = (prior["gsv"] or 0.0) + gsv
            continue
        seen[sku] = {"sku_code": sku, "quantity_sold": qty, "net_amount": net, "gsv": gsv, "region": region}
    out.rows = list(seen.values())
    if not out.rows and not out.problems:
        out.problems.append("the file has no sales rows")
    out.ok = not out.problems
    return out
