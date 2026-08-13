"""analytics.etl._coerce — shared numeric-coercion primitives.

Extracted 2026-08 (Transform reconciliation, story #16) from
analytics/etl/extract/_shared.py, where this logic was written once for
Extract's totals-row checksum and column-typing pass. Transform needs the
exact same comma-stripping / decimal-quantizing behavior for the
unilever_sku column map's flagged numeric-coercion TODOs (config/column_maps/
unilever_sku.yaml) — importing from here instead of writing a second copy
avoids letting type-fidelity logic drift between stages, which is exactly
the failure class DEC-07 was about (three vocabularies of the same concept
drifting apart because each stage had its own copy).

Both analytics/etl/extract/_shared.py and analytics/etl/transform.py import
from this module; neither defines these primitives locally anymore.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

NUMERIC_CELL_RE = re.compile(r"^-?[\d,]+\.?\d*$")

# Source currency is centavo-denominated; quantizing corrects float
# representation artifacts (e.g. 6619.859999999999 from openpyxl) back to
# the value's real precision rather than inventing new precision.
MONEY_QUANT = Decimal("0.01")


def to_decimal(v) -> Decimal | None:
    s = v.strip().replace(",", "") if isinstance(v, str) else str(v)
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return d.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def to_number(v):
    """Best-effort real int/float — handles both native numeric values and
    comma-formatted numeric strings (e.g. "1.08", "154", "24,190"). Returns
    the original value unchanged if it isn't parseable rather than
    fabricating a result."""
    if not isinstance(v, str):
        return v
    s = v.strip().replace(",", "")
    try:
        return int(s) if re.fullmatch(r"-?\d+", s) else float(s)
    except ValueError:
        return v
