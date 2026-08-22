"""Header detection, trimming, grain inference, and principal inference.

Pure functions over raw cell grids (list[list[Any]]) produced by reader.py.
No I/O here — profile_files.py owns reading/writing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any

MAX_HEADER_SCAN_ROWS = 15


def is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


GAP_RUN = 3  # consecutive fully-blank columns treated as a real gap


def trim_grid(rows: list[list[Any]]) -> list[list[Any]]:
    """Drop fully-empty trailing rows and trailing "phantom" columns.

    A real table's columns are contiguous, even when individual columns are
    naturally sparse (e.g. "Return Slip #" — populated for maybe 1% of
    invoices, but still a real column right next to the rest of the
    header). A phantom column looks different: it sits past a real gap
    (several fully-blank columns in a row) and has almost no content of its
    own. So: walk columns left to right, tracking the last column that
    extends a contiguous "real" block; once GAP_RUN blank columns pass,
    only let a later column re-extend that block if it has more than a
    single stray non-blank cell — one lone cell after a gap is a
    print-layout artifact (observed: RMR GS/BO files repeat a title banner
    every 8th column out to ~col 490, once each, only in the title row),
    not real data.
    """
    # Trim trailing empty rows
    trimmed = list(rows)
    while trimmed and all(is_blank(v) for v in trimmed[-1]):
        trimmed.pop()

    if not trimmed:
        return trimmed

    max_cols = max(len(r) for r in trimmed)
    non_blank_row_counts = [0] * max_cols
    for r in trimmed:
        for i, v in enumerate(r):
            if not is_blank(v):
                non_blank_row_counts[i] += 1

    last_real_col = -1
    blank_run = 0
    for i in range(max_cols):
        count = non_blank_row_counts[i]
        if count == 0:
            blank_run += 1
            continue
        if blank_run >= GAP_RUN and count <= 1:
            continue  # isolated straggler past a real gap — not real data
        last_real_col = i
        blank_run = 0

    if last_real_col == -1:
        return []
    return [list(r[: last_real_col + 1]) + [None] * max(0, last_real_col + 1 - len(r)) for r in trimmed]


_NUMERIC_STRING_RE = re.compile(r"^-?[\d,]+\.?\d*$")


def _looks_like_label(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s:
        return False
    if len(s) > 60:  # sentence-like text, not a column label
        return False
    # Some sources (CSV/MHTML) carry every cell as a string, so a purely
    # numeric-looking data value ("144", "6,619.86") would otherwise pass
    # as a plausible header label. Exclude those.
    if _NUMERIC_STRING_RE.match(s):
        return False
    return True


@dataclass
class HeaderDetection:
    header_row_index: int
    confidence: float
    junk_ranges: list[tuple[int, int]]


def detect_header(rows: list[list[Any]]) -> HeaderDetection:
    """Scan the first N rows; pick the row that maximizes label-like,
    non-null, mostly-unique string cells. Rows above it are junk_ranges."""
    if not rows:
        return HeaderDetection(header_row_index=-1, confidence=0.0, junk_ranges=[])

    scan_n = min(MAX_HEADER_SCAN_ROWS, len(rows))
    best_idx, best_score = 0, -1.0
    for i in range(scan_n):
        row = rows[i]
        if not row:
            continue
        non_blank = [v for v in row if not is_blank(v)]
        if not non_blank:
            continue
        label_like = [v for v in non_blank if _looks_like_label(v)]
        uniqueness = len(set(str(v).strip().lower() for v in label_like)) / max(1, len(label_like))
        density = len(non_blank) / max(1, len(row))
        label_ratio = len(label_like) / max(1, len(non_blank))
        score = label_ratio * uniqueness * density * len(label_like)
        if score > best_score:
            best_score = score
            best_idx = i

    max_possible = max(len(r) for r in rows[:scan_n] if r) or 1
    confidence = min(1.0, best_score / max_possible) if best_score > 0 else 0.0
    junk_ranges = [(0, best_idx - 1)] if best_idx > 0 else []
    return HeaderDetection(header_row_index=best_idx, confidence=round(confidence, 3), junk_ranges=junk_ranges)


def infer_dtype(values: list[Any]) -> str:
    non_blank = [v for v in values if not is_blank(v)]
    if not non_blank:
        return "empty"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_blank):
        return "numeric"
    if all(isinstance(v, (datetime, date)) for v in non_blank):
        return "datetime"
    date_like = re.compile(r"^\d{4}-\d{2}-\d{2}")
    if all(isinstance(v, str) and date_like.match(v.strip()) for v in non_blank[:20]):
        return "date-string"
    return "text"


SKU_RE = re.compile(r"^\s*\d?[A-Z]{2,4}\d{4,6}\b")
INVOICE_RE = re.compile(r"INV/\d{4}/\d+")
CATEGORY_RE = re.compile(r"^\s{2,}\S|^/")


def infer_grain(header_row: list[Any], data_rows: list[list[Any]]) -> str:
    # Some sources (MHTML exports) embed literal \r\n / repeated whitespace
    # inside header labels ("Calendar\r\n  Month") — collapse before matching.
    header_norm = [
        re.sub(r"\s+", " ", str(h).strip().lower()) if h is not None else ""
        for h in header_row
    ]

    if any("calendar month" in h for h in header_norm) and any("product" in h for h in header_norm) and any(
        "pack size" in h for h in header_norm
    ):
        return "monthly-sku"

    if any("invoice num" in h for h in header_norm) or any("invoice date" in h for h in header_norm):
        # confirm via first column / invoice num column values
        try:
            inv_col = next(i for i, h in enumerate(header_norm) if "invoice num" in h)
            sample = [r[inv_col] for r in data_rows[:20] if len(r) > inv_col]
            if any(isinstance(v, str) and INVOICE_RE.search(v) for v in sample):
                return "invoice"
        except StopIteration:
            pass
        return "invoice"

    first_col_vals = [r[0] for r in data_rows[:20] if r]
    if any(isinstance(v, str) and SKU_RE.match(v) for v in first_col_vals):
        return "sku"
    if any(isinstance(v, str) and CATEGORY_RE.match(v) for v in first_col_vals):
        return "category"

    if any("quantity" in h and "cost" in header_norm for h in header_norm):
        return "inventory"

    if not header_row:
        return "unknown"
    return "summary" if len(data_rows) > 0 else "unknown"


REFNBR_PREFIX_PRINCIPAL = {
    "DMP": "delmonte", "DMIS": "delmonte", "TDM": "delmonte", "SDM": "delmonte",
    "RMR": "delmonte", "PO": "delmonte", "BILL": "delmonte", "ODM": "delmonte",
    "FG": "delmonte", "CH": "delmonte",
}

UNILEVER_VOCAB = {"gsv", "niv", "tpr", "ssis", "calendar month", "pack size"}
DELMONTE_VOCAB = {"refnbr", "untaxed amount", "return slip #"}


def infer_principal_from_content(header_row: list[Any], data_rows: list[list[Any]]) -> tuple[str, list[str]]:
    """Returns (principal, evidence_notes). principal in {unilever, delmonte, ambiguous}."""
    evidence = []
    header_norm = " ".join(str(h).strip().lower() for h in header_row if h is not None)

    votes = {"unilever": 0, "delmonte": 0}
    for term in UNILEVER_VOCAB:
        if term in header_norm:
            votes["unilever"] += 1
            evidence.append(f"header contains '{term}'")
    for term in DELMONTE_VOCAB:
        if term in header_norm:
            votes["delmonte"] += 1
            evidence.append(f"header contains '{term}'")

    # REFNBR prefix scan on first ~30 data rows, any column
    refnbr_col = None
    header_lower = [str(h).strip().lower() if h is not None else "" for h in header_row]
    if "refnbr" in header_lower:
        refnbr_col = header_lower.index("refnbr")
    if refnbr_col is not None:
        for r in data_rows[:30]:
            if len(r) > refnbr_col and isinstance(r[refnbr_col], str):
                val = r[refnbr_col].strip()
                for prefix, principal in REFNBR_PREFIX_PRINCIPAL.items():
                    if val.startswith(prefix):
                        votes[principal] += 1
                        evidence.append(f"REFNBR '{val}' matches prefix '{prefix}' -> {principal}")
                        break

    if votes["unilever"] == 0 and votes["delmonte"] == 0:
        return "ambiguous", ["no principal vocabulary or REFNBR prefix matched"]
    if votes["unilever"] > 0 and votes["delmonte"] == 0:
        return "unilever", evidence
    if votes["delmonte"] > 0 and votes["unilever"] == 0:
        return "delmonte", evidence
    return "ambiguous", evidence + ["both unilever and delmonte signals present"]


def contains_magnolia(rows: list[list[Any]], limit: int = 200) -> bool:
    for r in rows[:limit]:
        for v in r:
            if isinstance(v, str) and "magnolia" in v.lower():
                return True
    return False
