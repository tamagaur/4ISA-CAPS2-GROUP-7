"""scripts/demo_revert.py: the gate that keeps it off live without a proof, and its static rules. The revert itself is proven on a restored
copy by scripts/demo_revert_proof.py (needs the throwaway server; its result is local/demo_revert_proof.json), not here."""
import json

import pytest

from scripts import demo_revert as dr


def test_the_throwaway_server_is_always_allowed(tmp_path):
    dr.require_write_allowed(True, False, tmp_path / "none.json")


def test_any_other_database_needs_the_flag(tmp_path):
    with pytest.raises(SystemExit, match="--target-public"):
        dr.require_write_allowed(False, False, tmp_path / "none.json")


def test_any_other_database_needs_a_passing_proof(tmp_path):
    proof = tmp_path / "proof.json"
    with pytest.raises(SystemExit, match="no passing revert proof"):
        dr.require_write_allowed(False, True, proof)
    proof.write_text(json.dumps({"passed": False}), encoding="utf-8")
    with pytest.raises(SystemExit, match="no passing revert proof"):
        dr.require_write_allowed(False, True, proof)
    proof.write_text(json.dumps({"passed": True}), encoding="utf-8")
    dr.require_write_allowed(False, True, proof)


@pytest.mark.parametrize("tag", ["", "A", "a-b", "a b", "x" * 31, "a;drop"])
def test_a_tag_cannot_carry_sql(tag):
    with pytest.raises(SystemExit):
        dr.snap_schema(tag)


def test_evidence_tables_are_the_only_exclusions():
    assert dr.EXCLUDED_TABLES == {"app.audit_log", "app.user_session", "app.auth_token"}


def test_the_schemas_covered_are_all_the_ones_the_app_writes():
    assert set(dr.SCHEMAS) == {"app", "public", "mart", "demo"}
