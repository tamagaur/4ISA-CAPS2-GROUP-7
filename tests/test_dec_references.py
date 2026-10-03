"""tests/test_dec_references.py — item 12: code cites the DEC that decides
what it does (ARCHITECTURE.md's register), not a neighbouring number.

DEC-15 is quantity flagging (DEC-13 is Product_Demand_View), DEC-11 is the
pieces unit (DEC-09 is FK-resolution timing), DEC-14 is the reject-rate gate
(DEC-12 is period keys). analytics/etl/load.py, transform_signoff.py and
ARCHITECTURE.md are deferred until session 5's uncommitted edits to them land.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("rel, wrong, right", [
    ("analytics/etl/clean.py", "DEC-13", "DEC-15"),
    ("analytics/etl/transform_driver.py", "DEC-13", "DEC-15"),
    ("analytics/etl/transform_driver.py", "DEC-09", "DEC-11"),
    ("analytics/classification/orchestrate_abc.py", "DEC-13", "DEC-15"),
    ("tests/etl/test_transform_driver.py", "DEC-13", "DEC-15"),
    ("tests/etl/test_load.py", "DEC-12", "DEC-14"),
])
def test_cites_the_deciding_dec(rel, wrong, right):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert wrong not in text and right in text


def test_orm_mape_precision_matches_schema_sql():
    from analytics.db.models import ForecastResult

    assert (ForecastResult.__table__.c.mape.type.precision, ForecastResult.__table__.c.mape.type.scale) == (10, 3)
    assert "mape                        NUMERIC(10,3)" in (REPO / "analytics/db/schema.sql").read_text(encoding="utf-8")
