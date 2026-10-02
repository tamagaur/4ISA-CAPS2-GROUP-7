"""tests/etl/test_load_slices.py - the slice loader's pure rules (2026-09-30). No database.

Covers: the ledger's two checksum forms, slice specs, the shrink guard, coverage statuses, 0028's RMR dedupe
decision, fixes 3 and 7 as transform rules, the orphan-rescue known keys, and the migrations 0032/0033 shape.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analytics.etl.transform import (
    FAKE_BOOKING_SHEET,
    HOLD_PENDING_SSM_RULE,
    QUARANTINE_REASON_COLUMN,
    QUARANTINE_RULE_COLUMN,
    derive_valuation_from_cost,
    flag_source_quarantine,
    load_source_of_truth,
    rescue_cross_check_orphans,
)
from scripts import load_slices as ls
from scripts.run_canonical_load import MIGRATIONS_DIR, dm_brand, migration_checksums

REPO = Path(__file__).resolve().parents[2]


# --- migration ledger ---------------------------------------------------------------------------------------------

def test_checksum_forms_cover_an_lf_and_a_crlf_copy_of_the_same_file(tmp_path):
    lf = b"-- x\nSELECT 1;\n"
    for body in (lf, lf.replace(b"\n", b"\r\n")):
        f = tmp_path / "0099_x.sql"
        f.write_bytes(body)
        forms = migration_checksums(f)
        assert hashlib.sha256(lf).hexdigest() in forms
        assert hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest() in forms


def test_an_edit_beyond_line_endings_matches_neither_form(tmp_path):
    f = tmp_path / "0099_x.sql"
    f.write_bytes(b"SELECT 2;\n")
    assert hashlib.sha256(b"SELECT 1;\n").hexdigest() not in migration_checksums(f)


def test_the_six_crlf_seeded_ledger_rows_still_verify_against_the_lf_working_copy():
    """0019 seeded these from a CRLF checkout; public stores exactly these values (read 2026-09-30)."""
    seeds = dict(line.split("', '") for line in (
        l.strip().lstrip("('").rstrip("'),") for l in (MIGRATIONS_DIR / "0019_schema_migrations.sql").read_text(encoding="utf-8").splitlines()
        if l.strip().startswith("('0")))
    for name in ("0001_add_is_demo.sql", "0002_add_boundary_flag.sql", "0002_add_sku_management_fields.sql",
                 "0003_add_audit_log.sql", "0012_sellout_source_defect_category.sql",
                 "0013_product_dimension_nulls_not_distinct.sql"):
        assert seeds[name] == migration_checksums(MIGRATIONS_DIR / name)[1], name
    assert seeds["0004_add_valuation.sql"] == migration_checksums(MIGRATIONS_DIR / "0004_add_valuation.sql")[0]


def test_every_sql_file_is_pinned_to_lf():
    assert "*.sql text eol=lf" in (REPO / ".gitattributes").read_text(encoding="utf-8")


# --- slice specs --------------------------------------------------------------------------------------------------

def test_slice_specs_resolve_to_one_family():
    assert ls.parse_spec("delmonte:sales_fact:2025-12").key == "delmonte:sales_fact:2025-12:*:sales_register"
    assert ls.parse_spec("delmonte:sales_fact:2025-11:pangasinan").site == "pangasinan"
    assert ls.parse_spec("delmonte:salesreturn_fact:2025-10:*:rmr").family.key == "rmr_gs_bo"
    assert ls.parse_spec("delmonte:salesreturn_fact:2025-10").family.key == "sales_return"
    assert ls.parse_spec("delmonte:inventory_fact:2025-12").family.key == "inventory_sign_off"
    assert ls.parse_spec("unilever:inventory_fact:2026-01").family.key == "ssis_soh"
    assert ls.parse_spec("unilever:unilever_sku_demand_fact:2026-02").family.month_col == "calendar_month"


@pytest.mark.parametrize("spec", [
    "delmonte:sales_fact:2025-1", "delmonte:sales_fact", "unilever:sales_fact:2025-12",
    "unilever:unilever_sku_demand_fact:2026-02:ilocos", "delmonte:sales_fact:2025-12:la_union",
])
def test_bad_slice_specs_are_refused(spec):
    with pytest.raises(ValueError):
        ls.parse_spec(spec)


def test_rmr_periods_come_from_source_of_truth_not_code():
    assert ls.rmr_allowed_periods() == ["2025-10", "2025-11"]
    assert ls.rmr_roles() == ["gs", "bo"]


# --- guards and statuses ------------------------------------------------------------------------------------------

def test_shrink_guard_refuses_more_than_a_five_percent_drop():
    assert ls.would_shrink(1000, 949)
    assert not ls.would_shrink(1000, 950)
    assert not ls.would_shrink(0, 0)  # a gap month (nothing real yet) never refuses
    assert ls.would_shrink(934, 467)  # test F's half file


def test_coverage_statuses():
    both = ("ilocos", "pangasinan")
    assert ls.coverage_status(10, 0, {"ilocos", "pangasinan"}, both) == "real"
    assert ls.coverage_status(10, 0, {"pangasinan"}, both) == "partial"
    assert ls.coverage_status(0, 5, set(), both) == "synthetic"
    assert ls.coverage_status(0, 0, set(), both) == "missing"
    assert ls.coverage_status(3, 0, set(), ()) == "real"  # Unilever SOH has no branch


def test_sales_rows_take_their_slice_from_lineage_not_region():
    df = pd.DataFrame({"_src_file": ["data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/2025 PANG. NOVEMBER SALES REGISTER.xlsx"],
                       "_src_sheet": ["1103"], "region": ["AGOO"], "_period": ["2025-10"]})
    got = ls.row_slices(ls.FAMILIES[1], df).iloc[0]
    assert (got["month"], got["site"]) == ("2025-11", "pangasinan")


# --- fix 4: 0028's dedupe rule ------------------------------------------------------------------------------------

def test_rmr_dedupe_deletes_agreeing_rmr_rows_and_holds_both_sides_of_a_disagreement():
    rmr = pd.DataFrame({"return_key": [1, 2, 3], "principal": "delmonte", "region": ["pangasinan"] * 3,
                        "return_slip_num": ["RS1", "RS2", "RS3"], "return_type": ["GS", "bo", "GS"],
                        "net_amount": [100.0, 50.0, 9.0]})
    sr = pd.DataFrame({"return_key": [11, 12], "principal": "delmonte", "region": ["pangasinan"] * 2,
                       "return_slip_num": ["RS1", "RS2"], "return_type": ["GS", "BO"], "net_amount": [100.004, 49.0]})
    delete, mismatch = ls.rmr_dedupe_decisions(rmr, sr)
    assert delete == [1]
    assert mismatch == [(2, 12)]  # RS3 has no sales-return match: it stays


def test_rmr_dedupe_is_a_no_op_without_a_sales_return_file():
    assert ls.rmr_dedupe_decisions(pd.DataFrame(), pd.DataFrame()) == ([], [])


# --- fixes 3, 6, 7 as rules ---------------------------------------------------------------------------------------

def test_fix3_valuation_from_cost_only_where_the_sheet_has_none():
    df = pd.DataFrame({"valuation": [np.nan, 5.0, np.nan], "cost": [7.0, 5.0, np.nan]})
    out, n = derive_valuation_from_cost(df)
    assert n == 1
    assert out["valuation"].tolist()[:2] == [7.0, 5.0] and pd.isna(out["valuation"].iloc[2])
    assert out["valuation_source"].tolist() == ["derived_cost", None, None]


def test_fix7_the_hidden_sheet_is_held_except_its_fake_bookings():
    df = pd.DataFrame({"_src_sheet": [FAKE_BOOKING_SHEET, FAKE_BOOKING_SHEET, "PANGASINAN SALES REGISTER"],
                       "REMARKS": ["FAKE BOOKING", None, None], "is_demo": [False] * 3})
    out, report = flag_source_quarantine(df, "sales_register")
    assert out[QUARANTINE_REASON_COLUMN].tolist()[0] == "source remark: FAKE BOOKING"
    rules = out[QUARANTINE_RULE_COLUMN]
    assert rules.iloc[1] == HOLD_PENDING_SSM_RULE and pd.isna(rules.iloc[0]) and pd.isna(rules.iloc[2])
    assert pd.isna(out[QUARANTINE_REASON_COLUMN].iloc[2])
    assert report == {"marked": 2, "held": 1}


def test_fix6_brand_first_token_rule():
    alias = {"DMV": "DEL MONTE", "FRESH": ""}
    assert dm_brand("DMR55625 DMV PINEAPPLE", alias) == "DEL MONTE"
    assert dm_brand("FRESH CUT", alias) is None
    assert dm_brand(None, alias) is None


# --- orphan rescue across slices ----------------------------------------------------------------------------------

def test_a_one_pager_row_already_loaded_by_another_slice_is_not_rescued():
    rule = load_source_of_truth("sales", "delmonte")
    raw = pd.DataFrame({
        "Invoice Num": ["INV-1", "INV-2"], "Town Display": ["AGOO", "AGOO"], "_sheet_role": ["one_pager", "one_pager"],
        "_doc_type": ["sales_register"] * 2, "_principal": ["delmonte"] * 2, "_region": ["pangasinan"] * 2,
    })
    sot = raw.iloc[0:0]
    _, alone = rescue_cross_check_orphans(raw, sot, rule)
    _, with_known = rescue_cross_check_orphans(raw, sot, rule, extra_known_keys={("INV-1", "delmonte", "AGOO")})
    assert alone["rescued_rows"] - with_known["rescued_rows"] == 1


# --- migrations 0032 / 0033 ---------------------------------------------------------------------------------------

def test_0032_keys_one_quarantine_row_per_source_row():
    sql = (MIGRATIONS_DIR / "0032_etl_quarantine_source_row_key.sql").read_text(encoding="utf-8")
    assert "UNIQUE INDEX IF NOT EXISTS uq_etl_quarantine_source_row" in sql
    assert "(table_name, _src_file, _src_sheet, _row_ordinal)" in sql


def test_0033_tables_keep_rls_on_and_revoke_the_api_roles():
    sql = (MIGRATIONS_DIR / "0033_etl_load_event_and_coverage.sql").read_text(encoding="utf-8")
    for needle in ("ALTER TABLE etl_load_event ENABLE ROW LEVEL SECURITY", "ALTER TABLE etl_coverage ENABLE ROW LEVEL SECURITY",
                   "ARRAY['anon', 'authenticated']", "'loaded', 'refused', 'partial', 'warning'",
                   "'real', 'synthetic', 'partial', 'missing'", "files                   TEXT[]"):
        assert needle in sql, needle
    assert "CREATE POLICY" not in sql


def test_every_reason_the_loader_writes_is_allowed_by_0033():
    sql = (MIGRATIONS_DIR / "0033_etl_load_event_and_coverage.sql").read_text(encoding="utf-8")
    src = (REPO / "scripts/load_slices.py").read_text(encoding="utf-8")
    import re
    # 2026-09-30 layout guard: file problems pass their reason through
    # (Refused(fl.reason ...)), and warnings are written as reasons too.
    layout_guard = {"unknown_layout", "layout_changed", "month_unknown", "validation_failed", "validation_warning",
                    "unmapped_column"}
    for reason in (set(re.findall(r'Refused\("([a-z_]+)"', src)) | layout_guard
                   | {"partial_month", "shrink_allowed", "key_conflict_other_slice", "error"}):
        assert f"'{reason}'" in sql, reason


def test_0033_allows_a_file_event_to_leave_what_the_file_does_not_say_null():
    sql = (MIGRATIONS_DIR / "0033_etl_load_event_and_coverage.sql").read_text(encoding="utf-8")
    assert "slice LIKE 'file:%' OR (principal IS NOT NULL AND table_name IS NOT NULL AND month IS NOT NULL)" in sql
    assert "principal               TEXT CHECK" in sql


# --- layout guard (2026-09-30) -------------------------------------------------------------------------------------

def _fake_layouts(monkeypatch, layouts: dict):
    monkeypatch.setattr(ls, "layout_of", lambda f: layouts[f])


def test_a_file_with_no_month_is_never_matched_to_a_slice(monkeypatch):
    from analytics.etl.extract.layout import FileLayout
    dec, none = Path("dec.xlsx"), Path("none.xlsx")
    _fake_layouts(monkeypatch, {dec: FileLayout(dec, "sell_out", "sell_out", "2025-12", "path"),
                                none: FileLayout(none, "unknown", "sell_out", None, "none")})
    sell_out = ls.parse_spec("delmonte:sellout_fact:2025-12").family
    assert ls.slice_files([dec, none], sell_out, "2025-12") == [dec]
    assert ls.slice_files([dec, none], sell_out, "2025-11") == []


def test_unilever_rows_carry_their_own_month_so_its_file_serves_every_slice(monkeypatch):
    from analytics.etl.extract.layout import FileLayout
    f = Path("lu.xls")
    _fake_layouts(monkeypatch, {f: FileLayout(f, "unilever_sku", "unilever_sku", None, "rows")})
    fam = ls.parse_spec("unilever:unilever_sku_demand_fact:2026-02").family
    assert ls.slice_files([f], fam, "2026-02") == [f] and ls.slice_files([f], fam, "2024-07") == [f]


def test_warnings_make_a_loaded_slice_a_warning_and_never_hide_another_reason():
    ev = {"status": "loaded", "reason": None, "detail": None}
    ls._apply_warnings(ev, [("unmapped_column", "x.xlsx: Truck Plate"), ("validation_warning", "peso: 3.9x")])
    assert (ev["status"], ev["reason"]) == ("warning", "unmapped_column") and "peso" in ev["detail"]
    ev = {"status": "partial", "reason": "partial_month", "detail": "no real rows for branch(es): ilocos"}
    ls._apply_warnings(ev, [("unmapped_column", "x.xlsx: Truck Plate")])
    assert (ev["status"], ev["reason"]) == ("partial", "partial_month") and "Truck Plate" in ev["detail"]


def test_the_loader_no_longer_selects_files_by_name():
    src = (REPO / "scripts/load_slices.py").read_text(encoding="utf-8")
    assert "infer_doc_type" not in src


def test_events_store_file_names_never_paths():
    ev = ls.new_event(ls.RunContext(None, "s", "r", "u", False, False, False, Path(".")),
                      ls.parse_spec("delmonte:sales_fact:2025-12"),
                      ["data/raw/Del Monte/MONTHLY REPORT - DECEMBER 2025/2025 DECEMBER SALES REGISTER.xlsx"],
                      pd.Timestamp.now(tz="UTC"))
    assert ev["files"] == ["2025 DECEMBER SALES REGISTER.xlsx"]


def test_each_statement_gets_only_the_parameters_it_names():
    params = {"m": "2025-12", "owned": ["a"], "site": "ilocos", "mx": 1}
    assert ls._bind("x = :m AND y = ANY(CAST(:owned AS text[]))", params) == {"m": "2025-12", "owned": ["a"]}
    assert ls._bind("q = :qpairs", {"qpairs": [], "qords": None}) == {"qpairs": []}
