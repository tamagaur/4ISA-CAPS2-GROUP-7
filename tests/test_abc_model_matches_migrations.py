"""Offline twin of tests/test_abc_schema_contract.py: the ORM model must carry what
migration 0044 put on abc_classification (the live column added_as_new and the
't12m_new' value in the method check). Needs no database."""
from pathlib import Path

from analytics.db.models import ABCClassification

MIGRATION = Path(__file__).resolve().parents[1] / "analytics/db/migrations/0044_tier_a_basis_t12m_new.sql"


def test_model_has_added_as_new_column():
    column = ABCClassification.__table__.columns["added_as_new"]
    assert column.nullable is False
    assert "added_as_new boolean NOT NULL DEFAULT false" in MIGRATION.read_text(encoding="utf-8")


def test_method_check_allows_every_method_migration_0044_allows():
    check = next(c for c in ABCClassification.__table__.constraints
                 if getattr(c, "name", None) == "ck_abc_classification_method")
    text = str(check.sqltext)
    for method in ("single", "t3m", "t12m_new"):
        assert f"'{method}'" in text
    assert "CHECK (method IN ('single', 't3m', 't12m_new'))" in MIGRATION.read_text(encoding="utf-8")
