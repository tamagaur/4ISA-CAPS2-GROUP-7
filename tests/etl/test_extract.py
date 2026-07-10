"""
tests/etl/test_extract.py — Tests for the Extract stage (ARCHITECTURE.md §6).

Phase 1+2 scope: shared core (analytics/etl/extract/_shared.py) + all 6
doc-family drivers (sales_register, unilever_sku, inventory_signoff,
sell_out, purchase_order, bo_rmr_gs).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from analytics.etl.extract._shared import (
    REPO_ROOT,
    ChecksumOutcome,
    aggregate_checksum,
    classify_column,
    coerce_column,
    find_totals_row,
    infer_sheet_period,
    infer_sheet_region,
    infer_sheet_role,
    refine_doc_type,
    row_periods_from_calendar_month,
    select_source_files,
    totals_row_checksum,
)
from analytics.etl.extract._qc import generate_qc_report
from analytics.etl.extract.bo_rmr_gs import parse_bo_rmr_gs
from analytics.etl.extract.inventory_signoff import parse_inventory_signoff
from analytics.etl.extract.purchase_order import parse_purchase_order
from analytics.etl.extract.sales_register import parse_sales_register
from analytics.etl.extract.sell_out import parse_sell_out
from analytics.etl.extract.unilever_sku import parse_unilever_sku


# --- coerce_column / classify_column: type fidelity ---------------------

def test_text_override_preserves_leading_zeros():
    coerced, kind = coerce_column("Branch Code", ["00123", "096", "68"])
    assert kind == "text_code"
    assert coerced == ["00123", "096", "68"]


def test_text_override_matches_reference_hash_variant():
    # "REFERENCE #" observed with/without internal spacing across vocab B files
    assert classify_column("REFERENCE #", ["ABC123"]) == "text_code"
    assert classify_column("REFERENCE#", ["ABC123"]) == "text_code"


def test_money_column_coerces_to_decimal():
    coerced, kind = coerce_column("Net Amount", [6619.86, 100.0, None])
    assert kind == "decimal"
    assert coerced[0] == Decimal("6619.86")
    assert coerced[1] == Decimal("100.00")
    assert coerced[2] is None


def test_money_column_quantizes_float_representation_noise():
    coerced, _ = coerce_column("Untaxed Amount", [6619.859999999999])
    assert coerced[0] == Decimal("6619.86")


def test_quantity_column_not_misclassified_as_money():
    # "Total CAS" contains "total" but is a case count, not currency
    assert classify_column("Total CAS", [12, 5, 3]) == "numeric"


def test_blank_values_become_none_not_fabricated():
    coerced, _ = coerce_column("Discount Amount", [None, "", 5.0])
    assert coerced[0] is None
    assert coerced[1] is None
    assert coerced[2] == Decimal("5.00")


# --- sheet role / region tagging -----------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("RAW DATA", "raw_data"),
    ("SALES PER CUSTOMER", "per_customer_summary"),
    ("INVOICE REG", "invoice_reg"),
    ("PANG ONE PAGER", "one_pager"),
    ("Sheet1", "scratch"),
    ("Sheet4", "scratch"),
    ("", "scratch"),
    ("PANGASINAN SALES REGISTER", "data"),
])
def test_sheet_role_inference(name, expected):
    assert infer_sheet_role(name) == expected


def test_sheet_region_prefers_sheet_name_over_path():
    path = Path("data/raw/SANSAN MARKETING_Del Monte/2024 FEBRUARY SALES REGISTER.xlsx")
    assert infer_sheet_region(path, "ILOCOS SALES REGISTER") == "ilocos"
    assert infer_sheet_region(path, "PANGASINAN SALES REGISTER") == "pangasinan"


# --- checksum: informational three-state, never a staging gate -----------

def test_checksum_passes_within_tolerance():
    header_labels = ["Net Amount"]
    trimmed = [[1000.00], header_labels, [100.0], [900.0]]
    coerced = {"Net Amount": [Decimal("100.00"), Decimal("900.00")]}
    kinds = {"Net Amount": "decimal"}
    outcomes = totals_row_checksum(trimmed, [(0, 0)], header_labels, coerced, kinds, "f.xlsx", "sheet1")
    assert len(outcomes) == 1
    assert outcomes[0].status == "pass"


def test_checksum_catches_synthetic_mismatch_but_does_not_reject():
    header_labels = ["Net Amount"]
    trimmed = [[1000.00], header_labels, [100.0], [850.0]]
    coerced = {"Net Amount": [Decimal("100.00"), Decimal("850.00")]}
    kinds = {"Net Amount": "decimal"}
    outcomes = totals_row_checksum(trimmed, [(0, 0)], header_labels, coerced, kinds, "f.xlsx", "sheet1")
    assert len(outcomes) == 1
    assert outcomes[0].status == "mismatch"
    assert outcomes[0].diff == pytest.approx(50.0)


def test_checksum_unverified_when_no_totals_row():
    # empty junk_ranges: nothing above the header to compare against
    header_labels = ["Net Amount"]
    coerced = {"Net Amount": [Decimal("100.00")]}
    kinds = {"Net Amount": "decimal"}
    outcomes = totals_row_checksum([header_labels, [100.0]], [], header_labels, coerced, kinds, "f.xlsx", "sheet1")
    assert len(outcomes) == 1
    assert outcomes[0].status == "unverified"
    assert outcomes[0].expected is None


def test_find_totals_row_scans_whole_junk_range_not_just_one_row_above():
    # title row (non-numeric) stacked above the real totals row — header on row 2
    grid = [["MONTHLY REPORT"], [1000.00], ["Net Amount"], [400.0], [600.0]]
    totals = find_totals_row(grid, [(0, 1)])
    assert totals == [1000.00]


def test_aggregate_checksum_aligns_to_canonical_column_not_worst_mismatch():
    # SSM_EXTRACT_CHECKSUM_REFINE_PROMPT.md: Purchase Order's canonical
    # column is Untaxed Amount — a Tax or Net Amount mismatch on the same
    # sheet must not flip the sheet's headline verdict.
    outcomes = [
        ChecksumOutcome("f.xlsx", "sheet1", "Net Amount", "mismatch", 200.0, 250.0, 50.0, 1.0),
        ChecksumOutcome("f.xlsx", "sheet1", "Untaxed Amount", "pass", 100.0, 100.0, 0.0, 1.0),
    ]
    status, column, expected, got, diff = aggregate_checksum(outcomes, "purchase_order")
    assert status == "pass"
    assert column == "Untaxed Amount"


def test_aggregate_checksum_uses_sales_register_canonical_column():
    outcomes = [
        ChecksumOutcome("f.xlsx", "sheet1", "Untaxed Amount", "pass", 100.0, 100.0, 0.0, 1.0),
        ChecksumOutcome("f.xlsx", "sheet1", "Net Amount", "mismatch", 200.0, 250.0, 50.0, 1.0),
    ]
    status, column, expected, got, diff = aggregate_checksum(outcomes, "sales_register")
    assert status == "mismatch"
    assert column == "Net Amount"
    assert diff == pytest.approx(50.0)


def test_aggregate_checksum_unverified_when_doc_type_has_no_canonical_column():
    # Inventory Sign-Off's Cost/Valuation aren't line-item sums — never
    # checksum-validate them, even if a numeric-looking cell happens to
    # be present (real case: a stray totals-row cell produced a
    # nonsensical negative "expected" when blindly compared).
    outcomes = [ChecksumOutcome("f.xlsx", "sheet1", "Cost", "mismatch", -9883.47, 128108.38, 138000.0, 1.0)]
    status, column, expected, got, diff = aggregate_checksum(outcomes, "inventory_sign_off")
    assert status == "unverified"
    assert expected is None


def test_aggregate_checksum_unverified_when_canonical_column_absent_from_sheet():
    # Vocab-variant sheet without the literal "Net Amount" column — don't
    # guess an equivalent column, just report unverified.
    outcomes = [ChecksumOutcome("f.xlsx", "sheet1", "NET VALUE", "pass", 100.0, 100.0, 0.0, 1.0)]
    status, column, expected, got, diff = aggregate_checksum(outcomes, "sales_register")
    assert status == "unverified"
    assert column == "Net Amount"  # names the column that was sought, for legibility
    assert expected is None


def test_aggregate_checksum_unverified_when_no_columns():
    assert aggregate_checksum([], "inventory_sign_off") == ("unverified", None, None, None, None)


# --- Phase 2 tagging fixes ------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("SCHEDULE", "schedule"),
    ("INDEX", "schedule"),
    ("PANG GS", "gs"),
    ("ILOCOS BO", "bo"),
    ("PANG ONE PAGER", "one_pager"),  # checked before gs/bo — no false "bo" match
])
def test_sheet_role_new_patterns(name, expected):
    assert infer_sheet_role(name) == expected


def test_sheet_role_synthetic_name_bypasses_scratch_pattern():
    # MHTML/CSV readers always name their single sheet "sheet1" — that's
    # the whole dataset, never a leftover Excel tab.
    assert infer_sheet_role("sheet1", synthetic_name=True) == "data"
    assert infer_sheet_role("sheet1", synthetic_name=False) == "scratch"


def test_refine_doc_type_splits_daily_from_monthly():
    daily = Path("data/raw/SANSAN MARKETING_Del Monte/DAILY SALES REPORT 07.31.2025.xlsx")
    monthly = Path("data/raw/SANSAN MARKETING_Del Monte/2024 JANUARY SALES REGISTER.xlsx")
    assert refine_doc_type(daily, "sales_register") == "daily_sales_report"
    assert refine_doc_type(monthly, "sales_register") == "sales_register"
    assert refine_doc_type(monthly, "purchase_order") == "purchase_order"  # untouched, wrong base type


def test_infer_sheet_period_from_sheet_name_date():
    path = Path("data/raw/SANSAN MARKETING_Del Monte/DAILY SALES REPORT 08.30.2025.xlsx")
    assert infer_sheet_period(path, "08.06.2025") == "2025-08"


def test_infer_sheet_period_falls_back_to_filename():
    path = Path("data/raw/SANSAN MARKETING_Del Monte/DAILY SALES REPORT 08.30.2025.xlsx")
    assert infer_sheet_period(path, "SCHEDULE") == "2025-08"


def test_row_periods_from_calendar_month_derives_per_row():
    header = ["Calendar\r\n  Month", "Product"]
    columns = {"Calendar\r\n  Month": ["01.2023", "09.2023", None], "Product": ["1", "2", "3"]}
    periods = row_periods_from_calendar_month(header, columns)
    assert periods == ["2023-01", "2023-09", "unknown"]


def test_row_periods_from_calendar_month_none_when_no_such_column():
    assert row_periods_from_calendar_month(["Invoice Date"], {"Invoice Date": ["2024-01-01"]}) is None


def test_numeric_string_upgrade_is_name_gated():
    # MHTML/CSV sources report numbers as strings — only upgrade to
    # numeric/decimal when the column NAME signals money/quantity, so an
    # unrelated numeric-looking string (e.g. a month code) stays text.
    assert classify_column("GSV", ["6,619.86", "100.00"]) == "decimal"
    assert classify_column("Sale Quantity in Aggr.PC", ["154", "119"]) == "numeric"
    assert classify_column("Calendar Month", ["01.2023", "09.2023"]) == "text"


def test_force_text_avoids_spurious_float_suffix():
    coerced, kind = coerce_column("Product", [20292808.0, "20292809"])
    assert kind == "text_code"
    assert coerced == ["20292808", "20292809"]


# --- file selection ---------------------------------------------------

def test_select_source_files_excludes_lock_files_and_non_data(tmp_path):
    (tmp_path / "report.xlsx").write_bytes(b"PK\x03\x04")
    (tmp_path / "~$report.xlsx").write_bytes(b"PK\x03\x04")
    (tmp_path / "notes.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / ".gitkeep").write_text("")

    selected = select_source_files(tmp_path)
    names = {f.name for f in selected}
    assert names == {"report.xlsx"}


# --- QC report is deterministic (no timestamps/randomness) ---------------

def test_qc_report_is_deterministic():
    text1 = generate_qc_report("sales_register", [], [])
    text2 = generate_qc_report("sales_register", [], [])
    assert text1 == text2
    assert "Generated:" not in text1  # no wall-clock timestamp in the report


# --- integration: real files under data/raw/ ------------------------------

RAW_DIR = REPO_ROOT / "data" / "raw"


@pytest.mark.skipif(not RAW_DIR.exists() or not any(RAW_DIR.rglob("*.xlsx")), reason="data/raw/ not available")
def test_parse_sales_register_against_real_files():
    result = parse_sales_register()
    assert result.dfs, "expected at least one staged Sales Register sheet"
    df, outcome = result.dfs[0]
    assert isinstance(df, pd.DataFrame)
    assert outcome.status == "staged"
    for col in ("_src_file", "_src_sheet", "_principal", "_region", "_doc_type", "_grain",
                "_checksum_status", "_checksum_expected", "_checksum_got", "_checksum_diff"):
        assert col in df.columns
    # Extract never renames — at least one non-provenance (raw) column must
    # survive under its original source header text.
    raw_columns = [c for c in df.columns if not c.startswith("_")]
    assert raw_columns

    # A checksum mismatch must never cause a reject — every rejected sheet
    # in this run must be for an unreadable/no-header/magnolia reason, not
    # a checksum figure (SSM_EXTRACT_FIX_AND_REVIEW_PROMPT.md Part A).
    for o in result.outcomes:
        if o.status == "rejected":
            assert "checksum" not in (o.reason or "").lower()

    # At least one mismatch sheet should exist in this corpus (confirmed
    # against real files) and must be staged, not dropped.
    mismatches = [o for _, o in result.dfs if o.checksum_status == "mismatch"]
    assert mismatches, "expected at least one staged mismatch sheet in the real corpus"


@pytest.mark.skipif(not RAW_DIR.exists(), reason="data/raw/ not available")
def test_parse_unilever_sku_against_real_file():
    result = parse_unilever_sku()
    assert len(result.dfs) == 1, "the whole MHTML workbook is one staged sheet"
    df, outcome = result.dfs[0]
    assert outcome.principal == "unilever"
    assert outcome.region == "la_union"
    assert outcome.grain == "monthly-sku"
    assert outcome.sheet_role == "data"  # not "scratch" — synthetic MHTML sheet name
    assert len(df) > 20000  # ~24.9k rows documented
    # SKU code (the "Product" column) must survive as TEXT, never a number.
    assert df["Product"].dtype == object or str(df["Product"].dtype) == "str"
    assert all(isinstance(v, str) for v in df["Product"].dropna().head(50))
    # Per-row period derived from each row's own Calendar Month cell — not
    # a single sheet-wide value collapsing 3+ years into one tag.
    assert df["_period"].nunique() > 1
    assert ".." in outcome.period  # manifest-level range summary


@pytest.mark.skipif(not RAW_DIR.exists(), reason="data/raw/ not available")
def test_parse_inventory_signoff_against_real_files():
    result = parse_inventory_signoff()
    assert result.dfs, "expected at least one staged Inventory Sign-Off sheet"
    for df, outcome in result.dfs:
        assert outcome.doc_type == "inventory_sign_off"
        # The header-less SKU-code column (col 0) must never be a float —
        # that's the leading-zero/identifier-as-number risk this family
        # specifically calls out.
        if "__col0__" in df.columns:
            assert df["__col0__"].dtype != "float64"


@pytest.mark.skipif(not RAW_DIR.exists(), reason="data/raw/ not available")
def test_parse_sell_out_against_real_files():
    result = parse_sell_out()
    assert result.dfs, "expected at least one staged Sell Out sheet"
    for _, outcome in result.dfs:
        assert outcome.doc_type == "sell_out"
        assert outcome.grain == "category"


@pytest.mark.skipif(not RAW_DIR.exists(), reason="data/raw/ not available")
def test_parse_purchase_order_against_real_files():
    result = parse_purchase_order()
    assert result.dfs, "expected at least one staged Purchase Order sheet"
    for _, outcome in result.dfs:
        assert outcome.doc_type == "purchase_order"
        assert outcome.grain == "invoice"


@pytest.mark.skipif(not RAW_DIR.exists(), reason="data/raw/ not available")
def test_parse_bo_rmr_gs_against_real_files():
    result = parse_bo_rmr_gs()
    assert result.dfs, "expected at least one staged RMR GS/BO sheet"
    roles_seen = {outcome.sheet_role for _, outcome in result.dfs}
    # ONE PAGER = GS ∪ BO is a dedup trap — Extract must tag all three
    # roles distinctly so Transform can tell them apart, not collapse
    # everything to generic "data".
    assert {"one_pager", "gs", "bo"} <= roles_seen
    for _, outcome in result.dfs:
        assert outcome.status == "staged"  # none of these three roles get dropped here


def test_all_six_families_produce_zero_unaccounted_when_combined():
    """Sheet accountability QC gate, exercised directly (not just via the
    driver script): every scanned sheet across all families is either
    staged or explicitly rejected — never silently missing."""
    if not RAW_DIR.exists():
        pytest.skip("data/raw/ not available")
    all_outcomes = []
    for parse_fn in (
        parse_sales_register, parse_unilever_sku, parse_inventory_signoff,
        parse_sell_out, parse_purchase_order, parse_bo_rmr_gs,
    ):
        all_outcomes.extend(parse_fn().outcomes)
    staged = sum(1 for o in all_outcomes if o.status == "staged")
    rejected = sum(1 for o in all_outcomes if o.status == "rejected")
    assert staged + rejected == len(all_outcomes)
    assert len(all_outcomes) > 0
