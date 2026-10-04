"""tests/etl/test_ssis_soh_po_qty.py — "PO Qty" (in transit) in the Unilever
SOH transform (analytics/etl/transform_ssis_soh.parse_po_qty, migration 0042)."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from analytics.etl.transform_ssis_soh import parse_po_qty


def test_po_qty_splits_cases_and_pieces_and_blank_is_zero():
    cases, pieces, counts = parse_po_qty(pd.Series(["12/0", None, " 3 / 5 ", "", math.nan]))
    assert cases.tolist() == [12.0, 0.0, 3.0, 0.0, 0.0]
    assert pieces.tolist() == [0.0, 0.0, 5.0, 0.0, 0.0]
    assert counts == {"rows": 5, "parsed": 2, "blank_as_zero": 3}


def test_an_unparseable_po_qty_stops_the_load():
    with pytest.raises(ValueError, match="unparseable CS/PC"):
        parse_po_qty(pd.Series(["12/0", "12 cases"]))
