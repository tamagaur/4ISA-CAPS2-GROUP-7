"""
scripts/check_upload.py - will the loader read this file? Answers before the run, from what is in the file. Read-only.

    python -m scripts.check_upload --kind sales|count --month YYYY-MM --file PATH     # prints one JSON line

It holds no list of columns of its own. The columns, sheet names and header normalisation (case and repeated whitespace, nothing
looser) are the loader's: analytics/etl/extract/layout.py and config/column_maps/*.yaml. A looser check here would pass a file the
loader then refuses during the run. Only the two kinds the Data Management panel takes; docs/RAW_FILE_REQUIREMENTS.md has all of them.

It checks headers, sheet names, the file's month, and the one thing the loader reads from a sales file's name: its branch. With no
"La Union" in the name every row is excluded (region is NOT NULL), which on a new month is no rows at all (dry runs, 2026-11-04).
It does not read the rows: the loader's own checks on values (a number that does
not parse, an unknown product share, a price outside its band) still run during the run, and whether a sales file holds any row for this
month is only found then.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from analytics.etl.extract import layout as lay  # noqa: E402
from profiling.detect import is_blank, trim_grid  # noqa: E402
from profiling.profile_files import infer_regions  # noqa: E402
from profiling.reader import read_workbook  # noqa: E402

FAMILY = {"sales": "unilever_sku", "count": "ssis_summary"}      # layout.FAMILY_MAPS
DOC_TYPE = {"sales": "unilever_sku", "count": "ssis_soh"}        # the column map each one loads through
FAMILY_WORDS = {"unilever_sku": "a Unilever sales-per-SKU file", "ssis_summary": "an SSIS workbook", "sales_register": "a Del Monte sales register",
                "purchase_order": "a Del Monte purchase file", "sales_return": "a Del Monte returns file", "rmr_gs_bo": "a Del Monte RMR file",
                "sell_out": "a Del Monte sell-out file", "inventory_sign_off": "a Del Monte inventory sign-off"}


def column_words(doc_type: str) -> dict[str, str]:
    """canonical field -> what the file must have, in the file's own words: the map's first spelling."""
    raw = yaml.safe_load((lay.CONFIG_DIR / "column_maps" / f"{doc_type}.yaml").read_text(encoding="utf-8")) or {}
    out = {}
    for canonical, spellings in raw.items():
        if canonical in lay.RESERVED_KEYS or not spellings:
            continue
        first = str(spellings[0])
        if first.startswith("__col"):
            out[canonical] = f"{canonical.replace('_', ' ')} (column {int(first.strip('_col')) + 1}, which has no header)"
        else:
            out[canonical] = " ".join(first.split())
    return out


def missing_columns(grids: dict[str, list[list]], sig, words: dict[str, str]) -> tuple[str | None, list[str]]:
    """The sheet and header row nearest a layout, and what it lacks, in the file's words."""
    best = None
    for name, grid in grids.items():
        for row in grid[:lay.HEAD_ROWS]:
            if not row or all(is_blank(v) for v in row):
                continue
            have = sig.resolved(lay.header_labels(row))
            for layout in sig.required:
                lacks = [n for n in layout if lay._norm(n) not in have and n not in have]
                if best is None or len(lacks) < len(best[1]):
                    best = (name, lacks)
    if best is None:
        return None, [words.get(n, n) for n in sig.required[0]]
    return best[0], [words.get(n, n) for n in best[1]]


def _result(ok: bool, message: str | None = None, **more) -> dict:
    return {"ok": ok, "message": message, "missing": [], "month": None, "month_source": None, "unmapped": [], "format": None, **more}


def check(path: Path, kind: str, month: str) -> dict:
    doc_type = DOC_TYPE[kind]
    wb = read_workbook(path, max_rows=lay.HEAD_ROWS)
    if wb.error and not wb.sheets:
        return _result(False, f"{path.name} could not be opened as a spreadsheet: {wb.error}", format=wb.real_format)
    fmt = wb.real_format
    grids = {s.name: trim_grid(s.rows) for s in wb.sheets}
    sig = lay.load_signature(doc_type)
    named = {n: g for n, g in grids.items() if sig.sheet_names is None or sig.sheet_names.search(n.strip())}

    if not named:
        if fmt == "csv":
            return _result(False, "A stock count has to stay a workbook: the loader reads it from a sheet named SOH(<date>), and a .csv has no "
                                  "sheet name. Send the .xlsx or .xls.", missing=["a sheet named SOH(<date>)"], format=fmt)
        return _result(False, f"{path.name} has no sheet named SOH(<date>), which is where the loader reads the stock count from. "
                              f"Its sheets: {', '.join(grids) or 'none'}.", missing=["a sheet named SOH(<date>)"], format=fmt)

    if not any(lay.find_header(g, sig) for g in named.values()):
        sheet, lacks = missing_columns(named, sig, column_words(doc_type))
        other = lay.identify(path, sheets=wb.sheets, real_format=fmt)
        looks = f" It looks like {FAMILY_WORDS[other.family]}." if other.family and other.family != FAMILY[kind] else ""
        where = f"sheet {sheet!r}" if sheet and len(named) > 1 else "the header row"
        return _result(False, f"{path.name} is missing columns the loader needs. Not found in {where}: {', '.join(lacks)}.{looks}",
                       missing=lacks, format=fmt)

    fl = lay.identify(path, sheets=wb.sheets, real_format=fmt)
    if not fl.ok:
        return _result(False, f"{path.name} would be refused: {fl.problem}", format=fmt)
    if fl.family != FAMILY[kind]:
        return _result(False, f"{path.name} is {FAMILY_WORDS.get(fl.family, fl.family)}, not what this slot takes.", format=fmt)

    seen = {"month": fl.month, "month_source": fl.month_source, "unmapped": fl.unmapped, "format": fmt}
    if kind == "sales" and "la_union" not in infer_regions(path):
        return _result(False, f"{path.name} does not say La Union in its name, and the loader takes the branch from the file name: it would load no "
                              "rows. Name it like UnileverLaUnionSalesperSKU.xls.", missing=["La Union in the file name"], **seen)
    if kind == "count" and fl.month is None:
        return _result(False, f"{path.name} does not say its month, and a stock count takes its month only from the file name: the loader would "
                              "skip it. Name it like SSIS MARCH 2026.xlsx.", **seen)
    if fl.month not in (None, month):
        return _result(False, f"{path.name} says it is {fl.month}, and this is the {month} batch.", **seen)
    return _result(True, **seen)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", required=True, choices=sorted(FAMILY))
    ap.add_argument("--month", required=True)
    ap.add_argument("--file", required=True, type=Path)
    args = ap.parse_args()
    print(json.dumps(check(args.file, args.kind, args.month)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
