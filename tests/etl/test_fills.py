"""DEC-31 fill step (scripts/fill_missing.py) - the parts that need no database.

The database guardrails (real views unchanged, real data wins, idempotence, split totals, a new stock month) are in
tests/etl/test_fills_db.py, run against a rehearsal schema (scripts/rehearse_fills.py)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

import scripts.build_synthetic_v2_clean_pool as gen
from scripts import fill_missing as fm
from scripts import load_slices as ls
from scripts.run_canonical_load import MIGRATIONS_DIR

MIGRATION = (MIGRATIONS_DIR / "0038_data_fills.sql").read_text(encoding="utf-8")
OPENING_MIGRATION = MIGRATIONS_DIR / "0040_derived_receipt_opening_flag.sql"

# Del Monte months with a real return rate (real sales AND real returns), public 2026-10-02 (read-only).
DM_RATE_MONTHS = ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05", "2023-06", "2023-08", "2023-09", "2023-11", "2023-12",
                  "2024-01", "2024-02", "2025-03", "2025-04", "2025-06", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]


def test_the_window_ends_at_the_last_complete_month():
    assert fm.last_complete_month(datetime(2026, 10, 2, tzinfo=timezone.utc)) == "2026-09"
    assert fm.last_complete_month(datetime(2027, 1, 1, tzinfo=timezone.utc)) == "2026-12"
    assert fm.month_list("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert fm.month_list("2026-03", "2026-02") == []


def test_unilever_returns_use_del_montes_own_month_else_a_nearest_month_of_year():
    ul = fm.month_list("2021-01", "2026-08")
    plan = fm.rate_months(ul, DM_RATE_MONTHS)
    assert len(plan) == 68
    assert sum(1 for m, r in plan.items() if m == r) == 20                     # 20 own-rate months, 48 borrowed
    assert all(r in DM_RATE_MONTHS for r in plan.values())
    for m, r in plan.items():                                                  # a borrowed month is a nearest month-of-year one
        if m != r:
            assert r in gen.nearest_moy(m, sorted(DM_RATE_MONTHS))
    # pinned draws (the dry run of 2026-10-02): seeded, so a re-run borrows the same months
    assert {m: plan[m] for m in ("2021-01", "2021-02", "2026-07", "2026-08")} == {
        "2021-01": "2024-01", "2021-02": "2023-02", "2026-07": "2023-08", "2026-08": "2025-08"}
    assert fm.rate_months(ul, DM_RATE_MONTHS) == plan


def test_the_category_map_placeholders_are_empty_so_the_split_is_principal_level():
    assert fm.read_mapping(fm.SKU_CATEGORY_MAP, "sku_code", "category") == {}
    assert fm.read_mapping(fm.CATEGORY_ROLLUP, "category_path", "category") == {}
    assert fm.SKU_CATEGORY_MAP.read_text(encoding="utf-8").splitlines()[0] == "sku_code,category,reviewed_by,reviewed_at"


def test_a_reviewed_map_is_read_without_blank_rows(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("sku_code,category,reviewed_by,reviewed_at\nDM1,FRUITS,Thea,2026-10-05\n,BEVERAGE,,\nDM2, ,,\n", encoding="utf-8")
    assert fm.read_mapping(p, "sku_code", "category") == {"DM1": "FRUITS"}


class FakeCursor:
    """Every pool query sees one real month (2025-09) of 3 rows; every INSERT reports 3 rows. Records the SQL."""

    def __init__(self):
        self.sql, self.rowcount, self._r = [], 0, []

    def execute(self, sql, args=None):
        self.sql.append(sql)
        s = " ".join(sql.split())
        if s.startswith("INSERT"):
            self.rowcount = 3
        elif "SELECT _period, COUNT(*)" in s:
            self._r = [("2025-09", 3)]
        elif "SELECT DISTINCT _period" in s:
            self._r = [("2025-09",)]
        else:
            self._r = [(3,)]

    def fetchall(self):
        return self._r


@pytest.mark.parametrize("key", sorted(gen.GAP_WRITERS))
def test_every_gap_writer_reads_and_writes_only_the_schema_it_is_given(key):
    """The bug class caught in the 2026-10-02 dry run: a writer whose loop reassigns `pool` rendered
    FROM ['2023-09'].purchase_fact_real. Every statement must name the given schema and no other."""
    cur = FakeCursor()
    gen.GAP_WRITERS[key](cur, ["2026-09"], target="scr", pool="scr")
    assert cur.sql
    for sql in cur.sql:
        assert not re.search(r"\{(pool|target|V2|pool_schema)\}", sql), sql          # an unrendered f-string field
        assert not re.search(r"\[\s*'\d{4}-\d{2}'", sql), sql                         # a Python month list as a schema
        assert "public." not in sql and gen.V2 not in sql, sql
        schemas = set(re.findall(r"\b([a-z_0-9]+)\.[a-z_]+(?:_fact|_real|_dimension)\b", sql))
        assert schemas <= {"scr"}, (schemas, sql)


def test_unilever_demand_gaps_are_left_missing():
    assert ("unilever", "unilever_sku_demand_fact") not in gen.GAP_WRITERS            # D4 (2026-10-02)
    assert set(gen.GAP_WRITERS) == {("delmonte", t) for t in ("sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact",
                                                              "inventory_fact")} | {("unilever", "inventory_fact")}


def test_the_template_month_writers_shift_unilever_snapshots_by_whole_months():
    cur = FakeCursor()
    gen._uni_inventory_months(cur, ["2026-09"], target="scr", pool="scr")
    insert = next(s for s in cur.sql if s.lstrip().startswith("INSERT"))
    assert "make_interval(months => %(shift)s)" in insert
    assert gen.template_month("2026-09", ["2023-09", "2025-08", "2025-09"]) == "2025-09"


def _cov(table, month, real, sites, principal="delmonte", expected=ls.SITES):
    return {"principal": principal, "table_name": table, "month": month, "real_rows": real, "real_sites": list(sites),
            "expected_sites": list(expected)}


def test_a_missing_branch_beside_a_real_branch_is_a_fill_target():
    rows = [
        _cov("inventory_fact", "2023-02", 200, ["ilocos"]),                     # H2: Pangasinan missing
        _cov("inventory_fact", "2023-03", 292, ["ilocos", "pangasinan"]),       # complete
        _cov("sales_fact", "2024-05", 0, []),                                   # no real rows: the whole-cell rule's job
        _cov("purchase_fact", "2025-09", 3, []),                                # real rows of no known branch: never guessed
        _cov("salesreturn_fact", "2025-06", 5, ["pangasinan"]),                 # Ilocos once held real rows
        _cov("sellout_fact", "2026-10", 5, ["ilocos"]),                         # after the window
        _cov("inventory_fact", "2023-02", 700, [], principal="unilever", expected=()),
    ]
    once = {("delmonte", "salesreturn_fact", "2025-06", "ilocos")}
    assert fm.branch_targets(rows, once, "2021-01", "2026-09") == [("delmonte", "inventory_fact", "2023-02", "pangasinan")]


def test_a_missing_branch_copies_its_previous_real_month_else_the_next():
    """H2 (Yuan, 2026-10-03): the branch's own count carried forward; the next one only when it has none before."""
    assert fm.adjacent_month(["2023-01", "2023-03", "2024-02"], "2023-02") == "2023-01"
    assert fm.adjacent_month(["2023-03", "2024-02"], "2023-02") == "2023-03"
    assert fm.adjacent_month(["2022-11", "2023-03"], "2023-02") == "2022-11"     # carried forward, not the nearer next
    assert fm.adjacent_month(["2023-02"], "2023-02") is None                       # never the month itself
    assert fm.adjacent_month([], "2023-02") is None


COLS = {"inventory_fact": [("inventory_key", "bigint"), ("product_key", "bigint"), ("sku_code", "text"), ("snapshot_date", "date"),
                           ("principal", "text"), ("region", "text"), ("quantity_on_hand", "numeric"), ("_src_file", "text"),
                           ("_src_sheet", "text"), ("is_demo", "boolean"), ("_period", "text"), ("valuation", "numeric"),
                           ("fill_source", "text")],
        "salesreturn_fact": [("return_key", "bigint"), ("return_slip_num", "text"), ("invoice_num", "text"),
                             ("return_date", "date"), ("principal", "text"), ("region", "text"), ("net_amount", "numeric"),
                             ("_src_file", "text"), ("_src_sheet", "text"), ("_period", "text"), ("is_demo", "boolean"),
                             ("invoice_date", "date"), ("fill_source", "text")],
        "sales_fact": [("sales_key", "bigint"), ("invoice_num", "text"), ("invoice_date", "date"), ("principal", "text"),
                       ("region", "text"), ("net_amount", "numeric"), ("_src_file", "text"), ("_src_sheet", "text"),
                       ("_period", "text"), ("is_demo", "boolean"), ("fill_source", "text")]}


def _select_list(sql):
    return " ".join(sql.split())


def test_a_branch_copy_moves_the_month_and_its_dates_and_keeps_the_counts():
    sql = _select_list(fm.branch_copy_sql("inventory_fact", COLS["inventory_fact"]))
    assert "inventory_key" not in sql.split("SELECT", 1)[0]                     # the identity key is never copied
    for expr in (":m", "true", ":tag", ":src", "'GENERATED'", "(r.snapshot_date + make_interval(months => :shift))::date",
                 "r.quantity_on_hand", "r.valuation", "r.sku_code"):
        assert expr in sql, expr
    assert "FROM inventory_fact r WHERE NOT r.is_demo AND r.principal = :p AND r._period = :t AND r.region = :site" in sql


def test_a_branch_copy_renumbers_the_documents_its_unique_key_is_built_on():
    sql = _select_list(fm.branch_copy_sql("salesreturn_fact", COLS["salesreturn_fact"]))
    for expr in ("'GEN-BR-RS/' || :m || '/' || :mark || lpad(row_number() OVER (ORDER BY r.return_key)::text, 4, '0')",
                 "'GEN-BR-INV/' || :m || '/' || :mark || lpad(row_number() OVER (ORDER BY r.return_key)::text, 4, '0')",
                 "(r.return_date + make_interval(months => :shift))::date", "(r.invoice_date + make_interval(months => :shift))::date"):
        assert expr in sql, expr
    sales = _select_list(fm.branch_copy_sql("sales_fact", COLS["sales_fact"]))
    assert "r.region = :site" not in sales                                       # a sales row's branch is its workbook's
    assert "(r._src_file, r._src_sheet) IN (SELECT * FROM unnest(CAST(:files AS text[]), CAST(:sheets AS text[])))" in sales


def test_the_possibly_partial_counts_are_the_months_on_record():
    assert fm.POSSIBLY_PARTIAL_COUNTS == ("2025-05",)


def test_0040_flags_assumed_zero_counts_and_allows_the_branch_tag():
    """H3 + the reverse case + H2 (Yuan, 2026-10-03). Unilever files omit zero rows, so a product missing from a count
    that was taken has 0 on hand; each assumption is a flag only its own zero can carry. The negative-balance rule
    and its constraint are untouched; the _Real views are not touched."""
    sql = "\n".join(l for l in OPENING_MIGRATION.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))
    for col in ("opening_flag", "closing_flag", "count_flag"):
        assert f"ALTER TABLE derived_receipt_fact ADD COLUMN IF NOT EXISTS {col} TEXT" in sql
    assert f"CHECK (opening_flag IS NULL OR (opening_flag = '{fm.OPENING_ASSUMED_ZERO}' AND opening_pieces = 0))" in sql
    assert f"CHECK (closing_flag IS NULL OR (closing_flag = '{fm.CLOSING_ASSUMED_ZERO}' AND closing_pieces = 0))" in sql
    assert f"CHECK (count_flag IS NULL OR (count_flag = '{fm.AFTER_PARTIAL}' AND opening_flag IS NOT NULL))" in sql
    assert (fm.OPENING_ASSUMED_ZERO, fm.CLOSING_ASSUMED_ZERO, fm.AFTER_PARTIAL) == (
        "opening_assumed_0_not_in_count", "closing_assumed_0_not_in_count", "after_possibly_partial_count")
    for col in ("opening_flag", "closing_flag", "count_flag"):
        assert col in fm.DERIVED_COLS
    for t in ("sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact"):
        assert f"ALTER TABLE {t} DROP CONSTRAINT IF EXISTS {t}_fill_source_check" in sql
        assert re.search(rf"ALTER TABLE {t} ADD CONSTRAINT {t}_fill_source_check CHECK \(\s*fill_source IS NULL OR \(is_demo AND "
                         rf"fill_source IN \([^)]*'{fm.BRANCH}'\)\)\)", sql), t
    assert "unilever_sku_demand_fact" not in sql
    assert "flag_matches_balance" not in sql and not re.search(r"\bVIEW\b", sql, re.I)


def test_coverage_knows_derived_and_the_new_pairs():
    assert ls.coverage_status(0, 0, set(), (), derived=37) == "derived"
    assert ls.coverage_status(5, 0, set(), (), derived=37) == "real"                    # real always wins
    assert ls.coverage_status(0, 4, set(), ()) == "synthetic"
    for pair in (("unilever", "purchase_fact"), ("unilever", "salesreturn_fact"), ("delmonte", "sku_demand_fill")):
        assert pair in ls.COVERAGE
    assert ls.DERIVED_FOR == {("unilever", "purchase_fact"): "derived_receipt_fact"}


def test_0038_keeps_the_real_views_and_tags_every_fill():
    sql = "\n".join(l for l in MIGRATION.splitlines() if not l.strip().startswith("--"))
    assert not re.search(r"\b(CREATE|ALTER|DROP|REPLACE)\s+(OR\s+REPLACE\s+)?VIEW\b", sql, re.I)  # the _Real views are not touched
    for t in fm.FACT_TABLES:
        assert f"ALTER TABLE {t}" in sql and f"{t}_fill_source_check" in sql
        assert re.search(rf"UPDATE {t}\s+SET fill_source = 'synthetic_v2' WHERE is_demo AND fill_source IS NULL", sql)
    assert "fill_source IS NULL OR (is_demo AND fill_source IN ('synthetic_v2', 'synthetic_v2_gap', 'synthetic_rate_transfer'))" in sql
    for tag in (fm.DERIVED, fm.SPLIT):
        assert f"CHECK (fill_source = '{tag}')" in sql
    assert "CHECK (status IN ('real', 'derived', 'synthetic', 'partial', 'missing'))" in sql
    for t in ("derived_receipt_fact", "sku_demand_fill"):
        assert f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" in sql
    assert "0032 -> 0033 -> 0036 -> 0037 -> 0038" in MIGRATION


def test_the_loader_runs_the_fill_step_after_a_load_unless_told_not_to():
    src = (ls.REPO_ROOT / "scripts" / "load_slices.py").read_text(encoding="utf-8")
    run_body = src[src.index("def run(engine"):]
    assert "if not ctx.dry_run and not getattr(args, \"no_fill\", False):" in run_body
    assert "fill_missing.run_step(" in run_body and "allow_public=ctx.target_public" in run_body
    write_body = src[src.index("def write_slice("):src.index("def write_slice(") + 6000]
    assert "remove_derived(conn, fam.principal, fam.table, sl.month)" in write_body


def test_public_is_refused_without_the_explicit_flag():
    with pytest.raises(ValueError, match="refused"):
        fm.run_step(engine=None, schema="public")
