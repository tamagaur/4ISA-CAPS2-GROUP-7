"""
analytics.etl.extract.layout - what a raw file is, read from what is in it.

2026-09-30 (layout guard). A file's family used to be its file name alone
(profiling.profile_files.infer_doc_type): a renamed file was never found, a
file renamed into another family's pattern was parsed as that family, and a
header that moved was read as whatever sat at that position. Now:

  signature  config/column_maps/<doc_type>.yaml carries two reserved keys next
             to its aliases: `sheet_names:` (a regex over sheet names, or null
             for "any") and `required:` (alternative layouts, each a list of
             names the header row must ALL carry - a canonical field reached
             through that map's own aliases, or a raw header text).
  family     the one family with a sheet whose name matches its pattern and
             whose header row carries one of its layouts. The Del Monte
             invoice families share one ERP export template (identical
             headers), so where no sheet name decides, the families whose
             layouts the headers carry are the candidates and the file name
             chooses among those only. A name hint outside them, or no hint
             with more than one candidate, is unknown_layout; a sheet name
             that decides one family while the file name says another is
             layout_changed.
  header     the first row that carries a layout - verified by content, never
             "the row that scores most label-like" (profiling.detect).
  loaded     every sheet whose rows this family loads (source_of_truth.yaml
             system-of-record + cross-check roles; ssis: the SOH sheet) must
             carry a layout, or the file is layout_changed.
  month      the path's month when it names one (infer_period, unchanged);
             unilever_sku rows carry their own (Calendar Month); otherwise the
             invoice dates' most common month (invoice families only, a tie is
             no month); otherwise none. A file with no month is never matched
             to a slice.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from analytics.etl.extract._shared import REPO_ROOT, _to_date, infer_sheet_role
from profiling.detect import is_blank, trim_grid
from profiling.profile_files import infer_doc_type, infer_period, infer_principal_from_path
from profiling.reader import read_workbook

CONFIG_DIR = REPO_ROOT / "config"

# How far down a sheet identification looks for the header row. Bounds only how
# many extra rows a reformatted file may add above its header; the deepest real
# header in the 2026-09-30 corpus is row 11 (the Unilever SKU export).
HEAD_ROWS = 50

# Keys of a column map that are not columns (transform.load_column_map skips them).
RESERVED_KEYS = frozenset({"required", "sheet_names", "ignored"})
NUMERIC_LABEL_RE = re.compile(r"^-?[\d,]+(\.\d+)?$")

# file family (profiling.profile_files.infer_doc_type vocabulary) -> the column
# maps whose signatures identify it. SSIS workbooks are one family with two
# loadable shapes: the SOH sheet (ssis_soh) and RAW DATA (ssis_summary).
FAMILY_MAPS: dict[str, tuple[str, ...]] = {
    "sales_register": ("sales_register",),
    "purchase_order": ("purchase_order",),
    "sales_return": ("sales_return",),
    "rmr_gs_bo": ("rmr_gs_bo",),
    "sell_out": ("sell_out",),
    "inventory_sign_off": ("inventory_sign_off",),
    "unilever_sku": ("unilever_sku",),
    "ssis_summary": ("ssis_soh", "ssis_summary"),
}
# The only doc_type the SSIS family loads from (DEC-04: ssis_summary has no fact).
LOADED_MAP = {"ssis_summary": "ssis_soh"}
# Each family is one principal's (profiling.profile_files.infer_principal_from_path
# reads the principal from the FOLDER name - a moved file had none, and a
# sell-out sheet carries no principal evidence in its content either).
FAMILY_PRINCIPAL = {"sales_register": "delmonte", "purchase_order": "delmonte", "sales_return": "delmonte",
                    "rmr_gs_bo": "delmonte", "sell_out": "delmonte", "inventory_sign_off": "delmonte",
                    "unilever_sku": "unilever", "ssis_summary": "unilever"}
INVOICE_FAMILIES = frozenset({"sales_register", "purchase_order", "sales_return", "rmr_gs_bo"})
PER_ROW_MONTH_FAMILIES = frozenset({"unilever_sku"})
# SSIS workbooks are never matched to a slice by file month: ssis_soh.py's R1
# (on record) skips and records a workbook whose period cannot be read.
OWN_PERIOD_RULE = frozenset({"ssis_summary"})


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip()).lower()


@dataclass(frozen=True)
class Signature:
    doc_type: str
    aliases: dict[str, str]                   # normalized raw header -> canonical
    required: tuple[tuple[str, ...], ...]     # alternative layouts
    sheet_names: re.Pattern | None
    known_raw: frozenset[str] = frozenset()     # normalized `ignored:` + raw names in `required:`

    def resolved(self, labels: list[str]) -> set[str]:
        """Canonical fields the labels reach through the aliases, plus the
        labels themselves (normalized) so a layout may name a raw header."""
        out = {_norm(lab) for lab in labels}
        out |= {self.aliases[k] for k in out if k in self.aliases}
        return out

    def layout_of(self, labels: list[str]) -> tuple[str, ...] | None:
        have = self.resolved(labels)
        for layout in self.required:
            if all(_norm(n) in have or n in have for n in layout):
                return layout
        return None

    def unmapped(self, labels: list[str]) -> list[str]:
        """Named header cells the map neither aliases nor lists as ignored -
        a column this template never had. Blank-header placeholders and
        numbers (a value in the header row, not a name) are not names."""
        return [lab for lab in labels
                if not lab.startswith("__col") and not NUMERIC_LABEL_RE.match(lab)
                and _norm(lab) not in self.aliases and _norm(lab) not in self.known_raw]


@lru_cache(maxsize=None)
def aliases_of(doc_type: str, config_dir: Path = CONFIG_DIR) -> dict[str, str]:
    """normalized raw header -> canonical field, for any column map (with or
    without a layout signature)."""
    raw = yaml.safe_load((config_dir / "column_maps" / f"{doc_type}.yaml").read_text(encoding="utf-8")) or {}
    return {_norm(r): canonical for canonical, rs in raw.items() if canonical not in RESERVED_KEYS for r in rs}


@lru_cache(maxsize=None)
def load_signature(doc_type: str, config_dir: Path = CONFIG_DIR) -> Signature:
    raw = yaml.safe_load((config_dir / "column_maps" / f"{doc_type}.yaml").read_text(encoding="utf-8")) or {}
    required = raw.get("required")
    if not required:
        raise ValueError(f"column_maps/{doc_type}.yaml has no `required:` layouts")
    aliases = aliases_of(doc_type, config_dir)
    pattern = raw.get("sheet_names")
    known = {_norm(x) for x in raw.get("ignored") or []}
    known |= {_norm(n) for layout in required for n in layout if _norm(n) not in aliases.values()}
    return Signature(doc_type, aliases, tuple(tuple(layout) for layout in required),
                     re.compile(pattern, re.I) if pattern else None, frozenset(known))


@lru_cache(maxsize=None)
def loaded_roles(doc_type: str, config_dir: Path = CONFIG_DIR) -> frozenset[str]:
    """Sheet roles whose rows a doc_type's fact loads: system-of-record plus
    cross-check roles (cross-check rows can be rescued into the fact)."""
    roles: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("doc_type") == doc_type:
                for key in ("system_of_record_role", "cross_check_roles"):
                    v = node.get(key) or []
                    roles.update(v if isinstance(v, list) else [v])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(yaml.safe_load((config_dir / "source_of_truth.yaml").read_text(encoding="utf-8")))
    return frozenset(roles)


def header_labels(row: list) -> list[str]:
    """The same labels Extract gives a header row (_shared.extract_sheet)."""
    return [str(h).strip() if not is_blank(h) else f"__col{i}__" for i, h in enumerate(row)]


def find_header(grid: list[list], sig: Signature, limit: int | None = HEAD_ROWS) -> tuple[int, tuple[str, ...]] | None:
    """The header row: of the rows (among the first `limit`) carrying one of
    sig's layouts, the one whose named cells the aliases map most completely;
    on a tie the upper one, so no data row is ever taken for junk.

    Not simply the first: the September and December 2025 sales-return GS/BO
    sheets carry a stale copy of the older 16-column header two rows above the
    real one, which adds Total CAS / Total PCS and so shifts every amount two
    columns right. The stale row carries the layout too; the real row maps
    two more columns."""
    best = None
    for i, row in enumerate(grid[:limit] if limit else grid):
        if not row or all(is_blank(v) for v in row):
            continue
        labels = header_labels(row)
        layout = sig.layout_of(labels)
        if layout is None:
            continue
        mapped = sum(1 for lab in labels if _norm(lab) in sig.aliases)
        if best is None or mapped > best[0]:
            best = (mapped, i, layout)
    return (best[1], best[2]) if best else None


@dataclass(frozen=True)
class SheetLayout:
    sheet: str
    doc_type: str
    header_row: int                 # index into trim_grid(sheet rows)
    layout: tuple[str, ...]
    unmapped: tuple[str, ...]       # named header cells no alias knows


@dataclass
class FileLayout:
    path: Path
    hint: str                       # infer_doc_type(path): the file name's family, a hint only
    family: str | None = None
    month: str | None = None
    month_source: str = "none"      # path | rows | invoice_dates | none
    sheets: dict[str, SheetLayout] = field(default_factory=dict)   # the verified (loaded) sheets
    reason: str | None = None       # unknown_layout | layout_changed | month_unknown
    problem: str | None = None

    @property
    def ok(self) -> bool:
        return self.reason is None

    @property
    def principal(self) -> str | None:
        return FAMILY_PRINCIPAL.get(self.family) if self.family else None

    @property
    def unmapped(self) -> list[str]:
        return sorted({u for s in self.sheets.values() for u in s.unmapped})


def positional_problems(grid: list[list], row: int, sig: Signature, layout: tuple[str, ...]) -> list[str]:
    """A required field the map reads from a header-less column (__colN__ -
    sell_out's category, unilever_sku's product name) is read by position,
    and only after the header row itself was verified by its named columns.
    It must then hold text: numbers there mean a different column moved into
    that position."""
    out = []
    for i, lab in enumerate(header_labels(grid[row])):
        canonical = sig.aliases.get(_norm(lab)) if lab.startswith("__col") else None
        if canonical is None or canonical not in layout:
            continue
        vals = [r[i] for r in grid[row + 1:] if i < len(r) and not is_blank(r[i])]
        nums = [v for v in vals if (isinstance(v, (int, float)) and not isinstance(v, bool))
                or (isinstance(v, str) and NUMERIC_LABEL_RE.match(v.strip()))]
        if not vals or nums:
            out.append(f"column {i + 1} has no header and is read by position as {canonical}, but it holds "
                       + ("nothing" if not vals else f"numbers (e.g. {nums[0]!r})"))
    return out


def _closest(grids: dict[str, list[list]], family: str, config_dir: Path = CONFIG_DIR) -> str:
    """The sheet and header row nearest one of the family's layouts, and what it lacks."""
    sig = load_signature(LOADED_MAP.get(family, FAMILY_MAPS[family][0]), config_dir)
    best = None
    for name, grid in grids.items():
        for row in grid[:HEAD_ROWS]:
            if not row or all(is_blank(v) for v in row):
                continue
            have = sig.resolved(header_labels(row))
            for layout in sig.required:
                missing = [n for n in layout if _norm(n) not in have and n not in have]
                if best is None or len(missing) < len(best[1]):
                    best = (name, missing)
    return f"sheet {best[0]!r} lacks {best[1]}" if best else "no sheet has a header row"


def _refuse(fl: FileLayout, reason: str, problem: str) -> FileLayout:
    fl.reason, fl.problem = reason, problem
    return fl


def identify(path: Path, sheets=None, real_format: str | None = None, config_dir: Path = CONFIG_DIR) -> FileLayout:
    """Identify one raw file by content. `sheets` (profiling.reader SheetGrid
    list) and its `real_format` may be passed when the caller has already read
    the file; otherwise only the first HEAD_ROWS rows of each sheet are read."""
    fl = FileLayout(path=path, hint=infer_doc_type(path))
    if sheets is None:
        wb = read_workbook(path, max_rows=HEAD_ROWS)
        if wb.error and not wb.sheets:
            return _refuse(fl, "unknown_layout", f"unreadable: {wb.error}")
        sheets, real_format = wb.sheets, wb.real_format
    synthetic = real_format in ("mhtml", "csv")
    grids = {s.name: trim_grid(s.rows) for s in sheets}

    strong: set[str] = set()
    compatible: set[str] = set()
    for family, maps in FAMILY_MAPS.items():
        for doc_type in maps:
            sig = load_signature(doc_type, config_dir)
            for name, grid in grids.items():
                if find_header(grid, sig) is None:
                    continue
                compatible.add(family)
                if sig.sheet_names is None or sig.sheet_names.search(name.strip()):
                    strong.add(family)

    if len(strong) == 1:
        family = next(iter(strong))
        if fl.hint not in ("unknown", family):
            return _refuse(fl, "layout_changed", f"the file name says {fl.hint}, its sheets say {family}")
    elif len(strong) > 1:
        if fl.hint in strong:
            family = fl.hint
        else:
            return _refuse(fl, "unknown_layout", f"sheets match more than one family: {sorted(strong)}")
    elif fl.hint in compatible:
        family = fl.hint
    elif len(compatible) == 1 and fl.hint == "unknown":
        family = next(iter(compatible))
    elif fl.hint in FAMILY_MAPS:
        return _refuse(fl, "layout_changed", f"the file name says {fl.hint}, but no sheet carries its required "
                                             f"headers - {_closest(grids, fl.hint, config_dir)}")
    elif compatible:
        return _refuse(fl, "unknown_layout", f"headers fit {sorted(compatible)} and no sheet name or file name decides")
    else:
        return _refuse(fl, "unknown_layout", "no sheet carries any family's required headers")
    fl.family = family
    folder = infer_principal_from_path(path)
    if folder not in ("ambiguous", FAMILY_PRINCIPAL[family]):
        return _refuse(fl, "layout_changed", f"the path says {folder}, the content is {family} ({FAMILY_PRINCIPAL[family]})")

    # every loaded sheet must carry a layout of the loading map
    doc_type = LOADED_MAP.get(family, FAMILY_MAPS[family][0])
    sig, roles = load_signature(doc_type, config_dir), loaded_roles(doc_type, config_dir)
    for name, grid in grids.items():
        if not grid:
            continue
        if family in LOADED_MAP:
            if not (sig.sheet_names and sig.sheet_names.search(name.strip())):
                continue
        elif infer_sheet_role(name, synthetic_name=synthetic) not in roles:
            continue
        found = find_header(grid, sig)
        if found is None:
            return _refuse(fl, "layout_changed", f"sheet {name!r}: no header row carries any of {doc_type}'s "
                                                 f"required layouts {[list(x) for x in sig.required]}")
        row, layout = found
        shape = positional_problems(grid, row, sig, layout)
        if shape:
            return _refuse(fl, "layout_changed", f"sheet {name!r}: " + "; ".join(shape))
        fl.sheets[name] = SheetLayout(name, doc_type, row, layout, tuple(sig.unmapped(header_labels(grid[row]))))

    period = infer_period(path)
    if period:
        fl.month, fl.month_source = period, "path"
    elif family in PER_ROW_MONTH_FAMILIES:
        fl.month_source = "rows"
    elif family in INVOICE_FAMILIES:
        month = invoice_month(path, fl, config_dir)
        if month is None:
            return _refuse(fl, "month_unknown", "no month in the file name and the invoice dates give no single month")
        fl.month, fl.month_source = month, "invoice_dates"
    elif family not in OWN_PERIOD_RULE:
        return _refuse(fl, "month_unknown", "no month in the file name, and this family has no dates to take one from")
    return fl


def invoice_month(path: Path, fl: FileLayout, config_dir: Path = CONFIG_DIR) -> str | None:
    """Most common YYYY-MM among the verified sheets' invoice dates (full read).
    A tie between months is no month."""
    wb = read_workbook(path, full_read=True)
    counts: Counter = Counter()
    for s in wb.sheets:
        sl = fl.sheets.get(s.name)
        if sl is None:
            continue
        grid = trim_grid(s.rows)
        sig = load_signature(sl.doc_type, config_dir)
        labels = header_labels(grid[sl.header_row])
        # sales_return.yaml maps no invoice_date (its fact keys on the slip), so
        # the raw "Invoice Date" header counts too.
        cols = [i for i, lab in enumerate(labels)
                if sig.aliases.get(_norm(lab)) == "invoice_date" or _norm(lab) == "invoice date"]
        for r in grid[sl.header_row + 1:]:
            for i in cols[:1]:
                d = _to_date(r[i]) if i < len(r) and not is_blank(r[i]) else None
                if d is not None:
                    counts[f"{d.year:04d}-{d.month:02d}"] += 1
    top = counts.most_common(2)
    if not top or (len(top) == 2 and top[0][1] == top[1][1]):
        return None
    return top[0][0]


def to_json(fl: FileLayout) -> dict:
    return {"hint": fl.hint, "family": fl.family, "month": fl.month, "month_source": fl.month_source,
            "reason": fl.reason, "problem": fl.problem,
            "sheets": {n: [s.doc_type, s.header_row, list(s.layout), list(s.unmapped)] for n, s in fl.sheets.items()}}


def from_json(path: Path, d: dict) -> FileLayout:
    fl = FileLayout(path=path, hint=d["hint"], family=d["family"], month=d["month"], month_source=d["month_source"],
                    reason=d["reason"], problem=d["problem"])
    fl.sheets = {n: SheetLayout(n, v[0], v[1], tuple(v[2]), tuple(v[3])) for n, v in d["sheets"].items()}
    return fl


def config_fingerprint(config_dir: Path = CONFIG_DIR) -> str:
    """Changes whenever anything identification reads changes (a cache key)."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted((config_dir / "column_maps").glob("*.yaml")) + [config_dir / "source_of_truth.yaml", Path(__file__)]:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]
