"""scripts/fill_missing.py - the fill step (DEC-31, 2026-10-02, Yuan; supersedes DEC-29's "never fill").

Every principal x table x month in the fill window (2021-01 .. the last complete month) that has no real rows is
filled, by this one step, after every load: scripts/load_slices.run (run_canonical_load --slice / --all-slices),
the synthetic generator (build_synthetic_v2_clean_pool --write), or by hand. Each fill carries its own source tag:

  1 derived_stock_balance    Unilever receipts per SKU x month = closing - opening stock + sold, real inputs only.
                             derived_receipt_fact. Signed balance kept; receipt = max(balance, 0); a negative
                             balance is flagged 'negative_balance'. Unilever files omit zero rows, so a product
                             missing from a count that was taken has 0 on hand (migration 0040): missing from the
                             previous count -> opening 0, opening_flag (H3); missing from this month's count -> closing 0,
                             closing_flag (the reverse case); an assumed-zero opening from a count in
                             POSSIBLY_PARTIAL_COUNTS also gets count_flag. No count taken that month or the month
                             before, or a NULL quantity: no row (unknown is not zero).
  2 synthetic_rate_transfer  Unilever returns = Unilever sales x Del Monte's real return rate (returns / sales,
                             pesos) of the same month, else of a nearest month-of-year real month (the generator's
                             own nearest_moy + seeded rng). One row per month. salesreturn_fact, is_demo, preview.
  3 synthetic_category_split Del Monte product sales = a month's REAL sell-out total x each SKU's share of stock
                             (its average real stock value; SKUs in the month's real snapshot, else the nearest
                             month-of-year snapshot). Totals equal the real totals to the centavo (largest remainder).
                             sku_demand_fill, is_demo, preview only. Principal level until a reviewed SKU -> category
                             map exists (config/alias_tables/delmonte_sku_category.csv), then category level.
  4 synthetic_v2_gap         a cell with no rows at all: the synthetic v2 generator's own month writers and seeds
                             (scripts/build_synthetic_v2_clean_pool.GAP_WRITERS). A Unilever demand gap stays missing.
  4b synthetic_branch_adjacent  H2: a Del Monte branch missing from a month that has real rows for the other branch
                             gets a copy of its own adjacent real month - the latest before, carried forward, else the
                             first after - dates moved, documents renumbered, source tag ending _<site>.

Real data wins
  - A cell with real rows is never filled, except a missing branch of it (4b); a cell or branch that ever held real
    rows (etl_load_event) is never filled again.
  - The sweep removes every demo row from a cell that has real rows - except the gap fill of a branch that has none
    (4b) - and the derived receipts of a month with real purchases. The loader also removes them inside the loading
    transaction (load_slices.write_slice).
Idempotent
  - 1-3 are pure functions of real rows: recomputed into a temp table and diffed in SQL; only differing rows are
    deleted / inserted. 4 fills only empty cells and never redraws a filled one. A second run writes nothing:
    no fact row, no etl_load_event, no etl_coverage row, no audit_log row.
One transaction for the whole step. An etl_load_event (source 'fill_missing') per changed cell.

  python -m scripts.fill_missing --schema ssm_fills                  fill a scratch schema
  python -m scripts.fill_missing --schema ssm_fills --dry-run        the same, rolled back
  python -m scripts.fill_missing --schema public --target-public     public (only after 0032/0033/0036/0037/0038/0040)
"""
from __future__ import annotations

import argparse
import csv
import getpass
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[1]
FILL_START = "2021-01"
TAG = "GENERATED_BACKFILL_"           # the generator's provenance prefix (analytics.etl.transform.SYNTHETIC_SOURCE_RE)
EVENT_SOURCE = "fill_missing"         # etl_load_event.source of every fill event
AUDIT_ACTOR = "system:etl_loader"
DERIVED, RATE, SPLIT, GAP = "derived_stock_balance", "synthetic_rate_transfer", "synthetic_category_split", "synthetic_v2_gap"
FACT_TABLES = ("sales_fact", "purchase_fact", "salesreturn_fact", "sellout_fact", "inventory_fact", "unilever_sku_demand_fact")
REQUIRED = ("derived_receipt_fact", "sku_demand_fill", "etl_coverage", "etl_load_event")  # migrations 0033 + 0038 (+ 0040's column)
SKU_CATEGORY_MAP = REPO_ROOT / "config" / "alias_tables" / "delmonte_sku_category.csv"
CATEGORY_ROLLUP = REPO_ROOT / "config" / "alias_tables" / "delmonte_sellout_category_rollup.csv"

DERIVED_COLS = ("product_key", "opening_pieces", "closing_pieces", "sold_pieces", "balance_pieces", "receipt_pieces",
                "unit_cost_per_piece", "receipt_value", "flag", "opening_flag", "closing_flag", "count_flag")
# Migration 0040 (Yuan, 2026-10-03). Unilever files omit zero rows, so a product missing from a count that was taken
# has 0 on hand (backend/stock_status.py): at the start of a month (H3) or at its end (the reverse case).
OPENING_ASSUMED_ZERO = "opening_assumed_0_not_in_count"
CLOSING_ASSUMED_ZERO = "closing_assumed_0_not_in_count"
AFTER_PARTIAL = "after_possibly_partial_count"
# Unilever counts on record as possibly partial; an assumed-zero opening taken from one is flagged AFTER_PARTIAL.
# The list and its evidence live in analytics.params (the data marts read the same list).
from analytics.params import POSSIBLY_PARTIAL_COUNTS  # noqa: E402
BRANCH = "synthetic_branch_adjacent"                      # H2: a missing branch copies its adjacent real month
SITE_RE = r"_(ilocos|pangasinan)$"                        # a fill row's branch: the end of its source tag (H2)
FACT_KEYS = {"sales_fact": "sales_key", "purchase_fact": "purchase_key", "salesreturn_fact": "return_key",
             "sellout_fact": "sellout_key", "inventory_fact": "inventory_key"}
# Columns a copied row cannot keep: the document numbers its unique key is built on (renumbered per month and branch).
RENUMBER = {"sales_fact": {"invoice_num": "GEN-BR/"}, "purchase_fact": {"invoice_num": "GEN-BR-BILL/"},
            "salesreturn_fact": {"return_slip_num": "GEN-BR-RS/", "invoice_num": "GEN-BR-INV/"}}
RATE_COLS = ("return_slip_num", "invoice_num", "net_amount", "quantity_pieces", "_src_file")
SPLIT_COLS = ("product_key", "sku_code", "split_level", "category_path", "stock_share", "quantity", "net_amount")


# --- months -------------------------------------------------------------------------------------------------------
def _ym(m: str) -> tuple[int, int]:
    return int(m[:4]), int(m[5:7])


def last_complete_month(now: datetime | None = None) -> str:
    """The fill window's end (D5): the month before the current UTC month - a month in progress is never filled."""
    now = now or datetime.now(timezone.utc)
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    return f"{y}-{m:02d}"


def month_list(start: str, end: str) -> list[str]:
    (y, m), out = _ym(start), []
    while f"{y}-{m:02d}" <= end:
        out.append(f"{y}-{m:02d}")
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


# --- bookkeeping --------------------------------------------------------------------------------------------------
@dataclass
class Cell:
    added: int = 0
    removed: int = 0
    swept: int = 0          # demo rows removed from a cell that has real rows
    notes: list = field(default_factory=list)


class Changes(dict):
    def cell(self, principal: str, table: str, month: str) -> Cell:
        return self.setdefault((principal, table, month), Cell())

    def tally(self, rows, attr: str, principal: str, table: str, note: str | None = None) -> int:
        n_total = 0
        for m, n in rows:
            c = self.cell(principal, table, m)
            setattr(c, attr, getattr(c, attr) + n)
            if note:
                c.notes.append(note)
            n_total += n
        return n_total

    def changed(self) -> dict:
        return {k: c for k, c in self.items() if c.added or c.removed or c.swept}


def _all(conn: Connection, sql: str, params: dict | None = None) -> list:
    return conn.execute(text(sql), params or {}).all()


# --- branches (H2) ------------------------------------------------------------------------------------------------
def branch_of_tag(src_file: str | None) -> str | None:
    """The branch a fill row was written for, from its source tag (the writers end it with _<site>); None for a
    whole-month row. The SQL twin is SITE_RE."""
    m = re.search(SITE_RE, src_file or "")
    return m.group(1) if m else None


def branch_targets(cov_rows: list[dict], once_real: set, start: str, end: str) -> list[tuple[str, str, str, str]]:
    """(principal, table, month, site): a branch missing from a month that has real rows for another branch (H2,
    Yuan 2026-10-03) - filled like a gap month, for that branch only. Never a branch that once held real rows, never
    a month whose real rows name no branch (which branch is missing is then unknown), never outside the window."""
    out = []
    for r in cov_rows:
        if not r["expected_sites"] or not r["real_rows"] or not r["real_sites"] or not start <= r["month"] <= end:
            continue
        for site in r["expected_sites"]:
            if site not in r["real_sites"] and (r["principal"], r["table_name"], r["month"], site) not in once_real:
                out.append((r["principal"], r["table_name"], r["month"], site))
    return sorted(out)


def adjacent_month(real_months: list[str], month: str) -> str | None:
    """The real month a missing branch copies (H2, Yuan 2026-10-03): the branch's latest real month before `month`,
    carried forward; its first real month after only when it has none before; None when it has no other."""
    before = [m for m in real_months if m < month]
    after = [m for m in real_months if m > month]
    return max(before) if before else (min(after) if after else None)


def branch_copy_sql(table: str, cols: list[tuple[str, str]]) -> str:
    """INSERT ... SELECT copying one branch's real rows of month :t into month :m as a branch fill: the same rows
    and amounts, dates moved by :shift months, the document numbers its unique key is built on renumbered per
    month and branch (:mark), tagged :tag with source :src. cols = [(column, data_type)] in table order. A sales
    row's branch is its workbook's (:files / :sheets, load_slices.lineage); every other table's is `region`."""
    key, renumber = FACT_KEYS[table], RENUMBER.get(table, {})
    fixed = {"_period": ":m", "is_demo": "true", "fill_source": ":tag", "_src_file": ":src", "_src_sheet": "'GENERATED'"}
    names, exprs = [], []
    for c, typ in cols:
        if c == key:
            continue
        names.append(c)
        if c in fixed:
            exprs.append(fixed[c])
        elif c in renumber:
            exprs.append(f"'{renumber[c]}' || :m || '/' || :mark || lpad(row_number() OVER (ORDER BY r.{key})::text, 4, '0')")
        elif typ == "date":
            exprs.append(f"(r.{c} + make_interval(months => :shift))::date")
        else:
            exprs.append(f"r.{c}")
    branch = ("(r._src_file, r._src_sheet) IN (SELECT * FROM unnest(CAST(:files AS text[]), CAST(:sheets AS text[])))"
              if table == "sales_fact" else "r.region = :site")
    return (f"INSERT INTO {table} ({', '.join(names)})\n"
            f"SELECT {', '.join(exprs)}\n"
            f"FROM {table} r WHERE NOT r.is_demo AND r.principal = :p AND r._period = :t AND {branch}")


def once_real_branches(conn: Connection) -> set[tuple[str, str, str, str]]:
    """(principal, table, month, site) a real load of that one branch ever wrote rows to (etl_load_event)."""
    return {tuple(r) for r in _all(conn, """SELECT DISTINCT principal, table_name, month, site FROM etl_load_event
                                            WHERE site IS NOT NULL AND NOT dry_run AND status <> 'refused'
                                              AND real_rows_after > 0 AND source <> :src""", {"src": EVENT_SOURCE})}


# --- real wins ----------------------------------------------------------------------------------------------------
def sweep_real_wins(conn: Connection, changes: Changes, keep: list[tuple[str, str, str, str]] = ()) -> int:
    """Every demo row in a cell that has real rows goes (covers the loader's per-workbook-month delete missing a
    sales row whose invoice month differs), and every derived receipt of a month with real purchases. Except a gap
    fill: H2's branch copies are swept on their own rule - each lives exactly as long as its branch is in `keep`
    (branch_targets: no real rows of its own, never had any, beside a real branch)."""
    total = 0
    for t in FACT_TABLES:
        if t == "unilever_sku_demand_fact":
            sql = ("WITH gone AS (DELETE FROM unilever_sku_demand_fact d WHERE d.is_demo AND EXISTS (SELECT 1 FROM "
                   "unilever_sku_demand_fact r WHERE NOT r.is_demo AND r.calendar_month = d.calendar_month) "
                   "RETURNING 'unilever'::text AS p, d.calendar_month AS m) SELECT p, m, count(*) FROM gone GROUP BY 1, 2")
            params = {}
        else:
            kept = [k for k in keep if k[1] == t]
            sql = (f"WITH gone AS (DELETE FROM {t} d WHERE d.is_demo AND (EXISTS (SELECT 1 FROM {t} r WHERE NOT r.is_demo "
                   f"AND r.principal = d.principal AND r._period = d._period) AND d.fill_source IS DISTINCT FROM '{BRANCH}' "
                   f"OR d.fill_source = '{BRANCH}' AND (d.principal, d._period, COALESCE(substring(d._src_file from '{SITE_RE}'), '')) "
                   f"NOT IN (SELECT * FROM unnest(CAST(:kp AS text[]), CAST(:km AS text[]), CAST(:ks AS text[])))) "
                   f"RETURNING d.principal AS p, d._period AS m) SELECT p, m, count(*) FROM gone GROUP BY 1, 2")
            params = {"kp": [k[0] for k in kept], "km": [k[2] for k in kept], "ks": [k[3] for k in kept]}
        for p, m, n in _all(conn, sql, params):
            changes.cell(p, t, m).swept += n
            total += n
    for p, m, n in _all(conn, "WITH gone AS (DELETE FROM derived_receipt_fact d WHERE EXISTS (SELECT 1 FROM purchase_fact r "
                              "WHERE NOT r.is_demo AND r.principal = d.principal AND r._period = d._period) "
                              "RETURNING d.principal AS p, d._period AS m) SELECT p, m, count(*) FROM gone GROUP BY 1, 2"):
        changes.cell(p, "derived_receipt_fact", m).removed += n
        total += n
    return total


def real_cells(conn: Connection) -> set[tuple[str, str, str]]:
    """(principal, table, month) cells that hold real rows now, or ever did (a real load in etl_load_event)."""
    cells = set()
    for t in FACT_TABLES:
        if t == "unilever_sku_demand_fact":
            cells |= {("unilever", t, m) for (m,) in _all(conn, f"SELECT DISTINCT calendar_month FROM {t} WHERE NOT is_demo")}
        else:
            cells |= {(p, t, m) for p, m in _all(conn, f"SELECT DISTINCT principal, _period FROM {t} WHERE NOT is_demo")}
    cells |= {tuple(r) for r in _all(conn, """SELECT DISTINCT principal, table_name, month FROM etl_load_event
                                              WHERE NOT dry_run AND status <> 'refused' AND real_rows_after > 0
                                                AND source <> :src""", {"src": EVENT_SOURCE})}
    return cells


# --- diff helper --------------------------------------------------------------------------------------------------
def _apply_diff(conn: Connection, target: str, temp: str, scope: str, key: tuple[str, ...], cols: tuple[str, ...],
                insert_cols: str, insert_select: str, params: dict) -> tuple[list, list]:
    """Delete target rows (within `scope`) that have no identical row in `temp`, then insert temp rows whose key
    is not in the target. Returns ([(month, n removed)], [(month, n added)]). Unchanged rows are never touched."""
    same_key = " AND ".join(f"t.{k} = d.{k}" for k in key)
    same_val = f"({', '.join('t.' + c for c in cols)}) IS NOT DISTINCT FROM ({', '.join('d.' + c for c in cols)})"
    gone = _all(conn, f"""WITH gone AS (DELETE FROM {target} d WHERE {scope} AND NOT EXISTS (
                              SELECT 1 FROM {temp} t WHERE {same_key} AND {same_val}) RETURNING d._period)
                          SELECT _period, count(*) FROM gone GROUP BY 1""", params)
    added = _all(conn, f"""WITH ins AS (INSERT INTO {target} ({insert_cols}) {insert_select}
                               WHERE NOT EXISTS (SELECT 1 FROM {target} d WHERE {scope} AND {same_key}) RETURNING _period)
                           SELECT _period, count(*) FROM ins GROUP BY 1""", params)
    return gone, added


# --- 1 derived Unilever receipts ----------------------------------------------------------------------------------
def derive_unilever_receipts(conn: Connection, run_id: str, start: str, end: str, occupied: set, changes: Changes) -> dict:
    retired = sorted(m for p, t, m in occupied if (p, t) == ("unilever", "purchase_fact"))
    # Inputs as analyzed temp tables: as CTEs the planner guessed 1 row for 27k and nested-looped (86 s).
    for t in ("_fill_derived", "_fill_u_stock", "_fill_u_sold", "_fill_u_counted"):
        conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
    conn.execute(text("""
        CREATE TEMP TABLE _fill_u_stock ON COMMIT DROP AS   -- one SOH row per SKU per snapshot; pieces = cases x pack + loose pieces
        SELECT i.product_key, i.sku_code, i._period,
               to_char(to_date(i._period || '-01', 'YYYY-MM-DD') - interval '1 month', 'YYYY-MM') AS prev_period,
               to_char(to_date(i._period || '-01', 'YYYY-MM-DD') + interval '1 month', 'YYYY-MM') AS next_period,
               SUM(i.quantity_on_hand * k.pack + i.quantity_pieces) AS pieces,
               MAX(i.unit_cost_per_case / k.pack) AS cpp,
               bool_or(i.quantity_on_hand IS NULL OR i.quantity_pieces IS NULL) AS has_null
        FROM inventory_fact_real i
        JOIN (SELECT product_key, NULLIF(substring(pack_size from '^([0-9]+)')::numeric, 0) AS pack
              FROM product_dimension WHERE principal = 'unilever') k ON k.product_key = i.product_key AND k.pack IS NOT NULL
        WHERE i.principal = 'unilever' AND i._period ~ '^[0-9]{4}-[0-9]{2}$'
        GROUP BY 1, 2, 3"""))
    conn.execute(text("""
        CREATE TEMP TABLE _fill_u_sold ON COMMIT DROP AS
        SELECT sku_code, calendar_month AS _period, SUM(quantity_sold) AS q, bool_or(quantity_sold IS NULL) AS has_null
        FROM unilever_sku_demand_fact_real GROUP BY 1, 2"""))
    conn.execute(text("""
        CREATE TEMP TABLE _fill_u_counted ON COMMIT DROP AS   -- every product in every real count, pack size or not
        SELECT DISTINCT sku_code, _period FROM inventory_fact_real WHERE principal = 'unilever' AND _period ~ '^[0-9]{4}-[0-9]{2}$'"""))
    conn.execute(text("ANALYZE _fill_u_stock"))
    conn.execute(text("ANALYZE _fill_u_sold"))
    conn.execute(text("ANALYZE _fill_u_counted"))
    conn.execute(text("""
        CREATE TEMP TABLE _fill_derived ON COMMIT DROP AS
        WITH bal AS (
            SELECT c.product_key, c.sku_code, c._period, COALESCE(o.pieces, 0) AS opening_pieces, c.pieces AS closing_pieces,
                   COALESCE(s.q, 0) AS sold_pieces, c.pieces - COALESCE(o.pieces, 0) + COALESCE(s.q, 0) AS balance_pieces,
                   COALESCE(c.cpp, o.cpp) AS cpp,
                   CASE WHEN o.sku_code IS NULL THEN :assumed_open END AS opening_flag, NULL::text AS closing_flag,
                   CASE WHEN o.sku_code IS NULL AND c.prev_period = ANY(CAST(:partial AS text[])) THEN :after_partial END AS count_flag
            FROM _fill_u_stock c
            LEFT JOIN _fill_u_stock o ON o.sku_code = c.sku_code AND o._period = c.prev_period
            LEFT JOIN _fill_u_sold s ON s.sku_code = c.sku_code AND s._period = c._period
            WHERE c._period BETWEEN :start AND :end AND c._period <> ALL(CAST(:retired AS text[]))
              AND c._period IN (SELECT DISTINCT _period FROM _fill_u_sold)   -- a month with real sales at all
              AND NOT c.has_null AND NOT COALESCE(o.has_null, false) AND NOT COALESCE(s.has_null, false)
              -- H3 (2026-10-03): opening = the previous count; a product missing from a count that WAS taken has 0 on
              -- hand (Unilever files omit zero rows, backend/stock_status.py). No previous count at all: unknown, no row.
              AND (o.sku_code IS NOT NULL OR (c.prev_period IN (SELECT DISTINCT _period FROM _fill_u_counted)
                                              AND NOT EXISTS (SELECT 1 FROM _fill_u_counted k
                                                              WHERE k.sku_code = c.sku_code AND k._period = c.prev_period)))
            UNION ALL
            -- the reverse case (Yuan, 2026-10-03): in the previous count, missing from this month's count (a count
            -- that was taken) -> closing stock 0. A month with real sales, as above.
            SELECT o.product_key, o.sku_code, o.next_period, o.pieces, 0, COALESCE(s.q, 0), COALESCE(s.q, 0) - o.pieces, o.cpp,
                   NULL::text, :assumed_close, NULL::text
            FROM _fill_u_stock o
            LEFT JOIN _fill_u_sold s ON s.sku_code = o.sku_code AND s._period = o.next_period
            WHERE o.next_period BETWEEN :start AND :end AND o.next_period <> ALL(CAST(:retired AS text[]))
              AND o.next_period IN (SELECT DISTINCT _period FROM _fill_u_sold)
              AND o.next_period IN (SELECT DISTINCT _period FROM _fill_u_counted)
              AND NOT EXISTS (SELECT 1 FROM _fill_u_counted k WHERE k.sku_code = o.sku_code AND k._period = o.next_period)
              AND NOT o.has_null AND NOT COALESCE(s.has_null, false))
        SELECT 'unilever'::text AS principal, product_key, sku_code, _period, opening_pieces, closing_pieces, sold_pieces,
               balance_pieces, GREATEST(balance_pieces, 0) AS receipt_pieces, round(cpp, 6) AS unit_cost_per_piece,
               round(GREATEST(balance_pieces, 0) * cpp, 2) AS receipt_value,
               CASE WHEN balance_pieces < 0 THEN 'negative_balance' END AS flag, opening_flag, closing_flag, count_flag
        FROM bal"""), {"start": start, "end": end, "retired": retired, "assumed_open": OPENING_ASSUMED_ZERO,
                       "assumed_close": CLOSING_ASSUMED_ZERO, "after_partial": AFTER_PARTIAL, "partial": list(POSSIBLY_PARTIAL_COUNTS)})
    conn.execute(text("ANALYZE _fill_derived"))
    cols = ", ".join(DERIVED_COLS)
    gone, added = _apply_diff(
        conn, "derived_receipt_fact", "_fill_derived", "d.principal = 'unilever'", ("sku_code", "_period"), DERIVED_COLS,
        f"principal, sku_code, _period, {cols}, run_id",
        f"SELECT t.principal, t.sku_code, t._period, {', '.join('t.' + c for c in DERIVED_COLS)}, :run_id FROM _fill_derived t",
        {"run_id": run_id})
    changes.tally(gone, "removed", "unilever", "derived_receipt_fact")
    changes.tally(added, "added", "unilever", "derived_receipt_fact", DERIVED)
    (n, neg, months, zo, zo_neg, zc, zc_neg, partial), = _all(conn, """SELECT count(*), count(*) FILTER (WHERE flag IS NOT NULL),
        count(DISTINCT _period), count(*) FILTER (WHERE opening_flag IS NOT NULL), count(*) FILTER (WHERE opening_flag IS NOT NULL
        AND flag IS NOT NULL), count(*) FILTER (WHERE closing_flag IS NOT NULL), count(*) FILTER (WHERE closing_flag IS NOT NULL
        AND flag IS NOT NULL), count(*) FILTER (WHERE count_flag IS NOT NULL) FROM _fill_derived""")
    return {"target_rows": n, "negative_balance": neg, "months": months, "opening_assumed_zero": zo,
            "opening_assumed_zero_negative": zo_neg, "closing_assumed_zero": zc, "closing_assumed_zero_negative": zc_neg,
            "after_possibly_partial_count": partial, "removed": sum(x for _, x in gone), "added": sum(x for _, x in added)}


# --- 2 synthetic Unilever returns ---------------------------------------------------------------------------------
DM_RATE_SQL = """SELECT s._period, r.amt / s.amt AS rate
                 FROM (SELECT _period, SUM(net_amount) AS amt FROM sales_fact_real WHERE principal = 'delmonte' GROUP BY 1) s
                 JOIN (SELECT _period, SUM(net_amount) AS amt FROM salesreturn_fact_real WHERE principal = 'delmonte'
                       GROUP BY 1) r USING (_period)
                 WHERE s.amt > 0 AND r.amt IS NOT NULL"""


def rate_months(ul_months: list[str], rate_periods: list[str]) -> dict[str, str]:
    """Unilever month -> the Del Monte month whose real return rate it uses: the same month when Del Monte has a
    real rate for it, else one of the nearest month-of-year real months, drawn with the generator's seeded rng."""
    from scripts.build_synthetic_v2_clean_pool import nearest_moy, rng
    real = sorted(rate_periods)
    out = {}
    for m in ul_months:
        if m in real:
            out[m] = m
        else:
            pool = nearest_moy(m, real)
            out[m] = pool[int(rng("ul_returns", m).integers(len(pool)))]
    return out


def transfer_unilever_returns(conn: Connection, start: str, end: str, occupied: set, changes: Changes) -> dict:
    rate_periods = [m for m, _ in _all(conn, DM_RATE_SQL)]
    ul = [m for (m,) in _all(conn, "SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact "
                                   "WHERE calendar_month BETWEEN :s AND :e ORDER BY 1", {"s": start, "e": end})]
    months = [m for m in ul if ("unilever", "salesreturn_fact", m) not in occupied]
    plan = rate_months(months, rate_periods) if rate_periods else {}   # no real rate: nothing to transfer, never a made-up rate
    conn.execute(text("DROP TABLE IF EXISTS _fill_ul_returns"))
    conn.execute(text(f"""
        CREATE TEMP TABLE _fill_ul_returns ON COMMIT DROP AS
        SELECT v.m AS _period, v.rm AS rate_month, x.rate,
               'FILL-UL-RS/' || v.m AS return_slip_num, 'FILL-UL-INV/' || v.m AS invoice_num,
               round(u.amt * x.rate, 2) AS net_amount, round(u.qty * x.rate) AS quantity_pieces,
               :tag || 'synthetic_rate_transfer_' || v.m || '_rate_' || v.rm AS _src_file
        FROM unnest(CAST(:ms AS text[]), CAST(:rms AS text[])) AS v(m, rm)
        JOIN (SELECT calendar_month, SUM(net_amount) AS amt, SUM(quantity_sold) AS qty FROM unilever_sku_demand_fact
              GROUP BY 1) u ON u.calendar_month = v.m
        JOIN ({DM_RATE_SQL}) x ON x._period = v.rm"""),
        {"ms": list(plan), "rms": [plan[m] for m in plan], "tag": TAG})
    conn.execute(text("ANALYZE _fill_ul_returns"))
    scope = f"d.principal = 'unilever' AND d.fill_source = '{RATE}'"
    gone, added = _apply_diff(
        conn, "salesreturn_fact", "_fill_ul_returns", scope, ("_period",), RATE_COLS,
        "return_slip_num, invoice_num, return_type, return_date, principal, region, net_amount, bo_units, is_demo, _src_file, "
        "_src_sheet, _period, quantity_cases, quantity_pieces, source, fill_source",
        f"SELECT t.return_slip_num, t.invoice_num, NULL, NULL, 'unilever', 'la_union', t.net_amount, NULL, true, t._src_file, "
        f"'GENERATED', t._period, NULL, t.quantity_pieces, NULL, '{RATE}' FROM _fill_ul_returns t", {})
    changes.tally(gone, "removed", "unilever", "salesreturn_fact")
    changes.tally(added, "added", "unilever", "salesreturn_fact", RATE)
    own = sum(1 for m, r in plan.items() if m == r)
    return {"target_rows": len(plan), "own_rate": own, "nearest_month_rate": len(plan) - own,
            "removed": sum(x for _, x in gone), "added": sum(x for _, x in added)}


# --- 3 Del Monte product sales (preview) --------------------------------------------------------------------------
def read_mapping(path: Path, key: str, value: str) -> dict[str, str]:
    """A reviewed CSV map (header row; blank or missing file = empty map)."""
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {r[key].strip(): r[value].strip() for r in csv.DictReader(f) if (r.get(key) or "").strip() and (r.get(value) or "").strip()}


def split_delmonte_sales(conn: Connection, run_id: str, start: str, end: str, changes: Changes,
                         sku_map: dict[str, str] | None = None, rollup: dict[str, str] | None = None) -> dict:
    from scripts.build_synthetic_v2_clean_pool import template_month
    sku_map = read_mapping(SKU_CATEGORY_MAP, "sku_code", "category") if sku_map is None else sku_map
    rollup = read_mapping(CATEGORY_ROLLUP, "category_path", "category") if rollup is None else rollup
    months = [m for (m,) in _all(conn, "SELECT DISTINCT _period FROM sellout_fact_real WHERE principal = 'delmonte' "
                                       "AND _period BETWEEN :s AND :e ORDER BY 1", {"s": start, "e": end})]
    snaps = [m for (m,) in _all(conn, "SELECT DISTINCT _period FROM inventory_fact_real WHERE principal = 'delmonte' "
                                      "AND valuation IS NOT NULL ORDER BY 1")]
    if not snaps:
        months = []                                  # no stock to weight by: nothing to split
    templates = {m: (m if m in snaps else template_month(m, snaps)) for m in months}
    levels = {m: "principal" for m in months}
    if sku_map:                                       # option (a): category level where every category has a mapped SKU
        groups = _all(conn, """
            SELECT f._period, COALESCE(r.category, f.category_path) FROM sellout_fact_real f
            LEFT JOIN unnest(CAST(:rp AS text[]), CAST(:rc AS text[])) AS r(category_path, category) ON r.category_path = f.category_path
            WHERE f.principal = 'delmonte' AND f._period = ANY(CAST(:ms AS text[])) GROUP BY 1, 2""",
                      {"rp": list(rollup), "rc": list(rollup.values()), "ms": months})
        # a SKU counts only if the split below can weight it: in the template snapshot, average stock value > 0
        mapped = {(m, sku_map[s]) for m, s in _all(conn, """
            SELECT p.m, i.sku_code FROM unnest(CAST(:ms AS text[]), CAST(:ts AS text[])) AS p(m, tm)
            JOIN inventory_fact_real i ON i.principal = 'delmonte' AND i._period = p.tm AND i.valuation IS NOT NULL
                                      AND i.product_key IS NOT NULL
            JOIN (SELECT product_key, sku_code FROM (SELECT product_key, sku_code, _period, SUM(valuation) AS v
                        FROM inventory_fact_real WHERE principal = 'delmonte' AND valuation IS NOT NULL AND product_key IS NOT NULL
                        GROUP BY 1, 2, 3) x GROUP BY 1, 2 HAVING AVG(v) > 0) w
              ON w.product_key = i.product_key AND w.sku_code = i.sku_code
            GROUP BY 1, 2""", {"ms": months, "ts": [templates[m] for m in months]}) if s in sku_map}
        for m in months:
            need = {g for mm, g in groups if mm == m}
            levels[m] = "category" if need and all((m, g) in mapped for g in need) else "principal"
    for t in ("_fill_dm_split", "_fill_dm_snap"):
        conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
    conn.execute(text("""
        CREATE TEMP TABLE _fill_dm_snap ON COMMIT DROP AS   -- a SKU's stock value per real snapshot, both sites summed
        SELECT product_key, sku_code, _period, SUM(valuation) AS v
        FROM inventory_fact_real WHERE principal = 'delmonte' AND valuation IS NOT NULL AND product_key IS NOT NULL
        GROUP BY 1, 2, 3"""))
    conn.execute(text("ANALYZE _fill_dm_snap"))
    conn.execute(text("""
        CREATE TEMP TABLE _fill_dm_split ON COMMIT DROP AS
        WITH snap AS (SELECT * FROM _fill_dm_snap),
        weight AS (SELECT product_key, sku_code, AVG(v) AS w FROM snap GROUP BY 1, 2 HAVING AVG(v) > 0),
        plan AS (SELECT * FROM unnest(CAST(:ms AS text[]), CAST(:ts AS text[]), CAST(:ls AS text[])) AS p(m, tm, lvl)),
        skumap AS (SELECT * FROM unnest(CAST(:mk AS text[]), CAST(:mc AS text[])) AS x(sku_code, category)),
        rollup AS (SELECT * FROM unnest(CAST(:rp AS text[]), CAST(:rc AS text[])) AS x(category_path, category)),
        active AS (
            SELECT p.m, w.product_key, w.sku_code, w.w, CASE WHEN p.lvl = 'category' THEN sm.category END AS grp
            FROM plan p
            JOIN (SELECT DISTINCT product_key, sku_code, _period FROM snap) s ON s._period = p.tm
            JOIN weight w ON w.product_key = s.product_key AND w.sku_code = s.sku_code
            LEFT JOIN skumap sm ON sm.sku_code = w.sku_code
            WHERE p.lvl = 'principal' OR sm.category IS NOT NULL),
        tot AS (
            SELECT p.m, CASE WHEN p.lvl = 'category' THEN COALESCE(r.category, f.category_path) END AS grp,
                   SUM(f.net_amount) AS amt, SUM(f.quantity) AS qty
            FROM plan p JOIN sellout_fact_real f ON f.principal = 'delmonte' AND f._period = p.m
            LEFT JOIN rollup r ON r.category_path = f.category_path
            GROUP BY 1, 2),
        shares AS (SELECT a.*, a.w / SUM(a.w) OVER (PARTITION BY a.m, a.grp) AS share FROM active a),
        alloc AS (   -- centavo units (sell-out amounts and quantities have scale 2): largest remainder
            SELECT s.m, s.product_key, s.sku_code, s.grp, s.share,
                   t.amt * 100 AS amt_u, floor(t.amt * 100 * s.share) AS amt_base,
                   t.amt * 100 * s.share - floor(t.amt * 100 * s.share) AS amt_rem,
                   t.qty * 100 AS qty_u, floor(t.qty * 100 * s.share) AS qty_base,
                   t.qty * 100 * s.share - floor(t.qty * 100 * s.share) AS qty_rem
            FROM shares s JOIN tot t ON t.m = s.m AND t.grp IS NOT DISTINCT FROM s.grp),
        ranked AS (
            SELECT a.*,
                   a.amt_u - SUM(a.amt_base) OVER (PARTITION BY a.m, a.grp) AS amt_left,
                   row_number() OVER (PARTITION BY a.m, a.grp ORDER BY a.amt_rem DESC, a.product_key) AS amt_rank,
                   a.qty_u - SUM(a.qty_base) OVER (PARTITION BY a.m, a.grp) AS qty_left,
                   row_number() OVER (PARTITION BY a.m, a.grp ORDER BY a.qty_rem DESC, a.product_key) AS qty_rank
            FROM alloc a)
        SELECT m AS _period, product_key, sku_code, CASE WHEN grp IS NULL THEN 'principal' ELSE 'category' END AS split_level,
               grp AS category_path, share AS stock_share,
               (qty_base + CASE WHEN qty_rank <= qty_left THEN 1 ELSE 0 END) / 100 AS quantity,
               (amt_base + CASE WHEN amt_rank <= amt_left THEN 1 ELSE 0 END) / 100 AS net_amount
        FROM ranked"""),
        {"ms": months, "ts": [templates[m] for m in months], "ls": [levels[m] for m in months],
         "mk": list(sku_map), "mc": list(sku_map.values()), "rp": list(rollup), "rc": list(rollup.values())})
    conn.execute(text("ANALYZE _fill_dm_split"))
    cols = ", ".join(SPLIT_COLS)
    gone, added = _apply_diff(
        conn, "sku_demand_fill", "_fill_dm_split", "TRUE", ("product_key", "_period"), SPLIT_COLS,
        f"principal, _period, {cols}, run_id",
        f"SELECT 'delmonte', t._period, {', '.join('t.' + c for c in SPLIT_COLS)}, :run_id FROM _fill_dm_split t",
        {"run_id": run_id})
    changes.tally(gone, "removed", "delmonte", "sku_demand_fill")
    changes.tally(added, "added", "delmonte", "sku_demand_fill", SPLIT)
    # The rule the split exists to keep: every month's total equals the real sell-out total, amount and quantity.
    off = _all(conn, """
        SELECT coalesce(t.m, s.m), t.amt, s.amt, t.qty, s.qty
        FROM (SELECT _period AS m, SUM(net_amount) AS amt, SUM(quantity) AS qty FROM sellout_fact_real
              WHERE principal = 'delmonte' AND _period = ANY(CAST(:ms AS text[])) GROUP BY 1) t
        FULL JOIN (SELECT _period AS m, SUM(net_amount) AS amt, SUM(quantity) AS qty FROM sku_demand_fill GROUP BY 1) s ON s.m = t.m
        WHERE (t.amt, t.qty) IS DISTINCT FROM (s.amt, s.qty)""", {"ms": months})
    if off:
        raise RuntimeError(f"Del Monte split totals differ from real sell-out totals: {off[:5]}")
    (n, skus, excluded), = _all(conn, """SELECT (SELECT count(*) FROM _fill_dm_split), (SELECT count(DISTINCT product_key) FROM _fill_dm_split),
        (SELECT count(*) FROM (SELECT product_key, sku_code FROM _fill_dm_snap GROUP BY 1, 2 HAVING AVG(v) <= 0) x)""")
    return {"target_rows": n, "months": len(months), "skus": skus, "skus_excluded_nonpositive_stock": excluded,
            "levels": {lvl: sum(1 for v in levels.values() if v == lvl) for lvl in ("principal", "category")},
            "removed": sum(x for _, x in gone), "added": sum(x for _, x in added)}


# --- 4 synthetic v2 gap months ------------------------------------------------------------------------------------
def fill_gaps(conn: Connection, schema: str, start: str, end: str, occupied: set, changes: Changes) -> dict:
    from scripts.build_synthetic_v2_clean_pool import GAP_WRITERS
    window = month_list(start, end)
    cur = conn.connection.cursor()   # the DBAPI cursor of this same transaction: the writers take psycopg2 cursors
    out = {}
    for (principal, table), writer in GAP_WRITERS.items():
        have = {m for (m,) in _all(conn, f"SELECT DISTINCT _period FROM {table} WHERE principal = :p", {"p": principal})}
        months = [m for m in window if m not in have and (principal, table, m) not in occupied]
        if not months:
            continue
        writer(cur, months, target=schema, pool=schema)
        tagged = _all(conn, f"""WITH t AS (UPDATE {table} SET fill_source = '{GAP}' WHERE is_demo AND fill_source IS NULL
                                    AND principal = :p AND _period = ANY(CAST(:ms AS text[])) RETURNING _period)
                                SELECT _period, count(*) FROM t GROUP BY 1""", {"p": principal, "ms": months})
        out[f"{principal}.{table}"] = {"months": months, "rows": changes.tally(tagged, "added", principal, table, GAP)}
    return out


def _branch_months(conn: Connection, principal: str, table: str, site: str) -> tuple[list[str], list[tuple[str, str]]]:
    """The branch's real months, and (sales only) the workbooks that are that branch's (load_slices.lineage)."""
    if table != "sales_fact":
        return [m for (m,) in _all(conn, f"""SELECT DISTINCT _period FROM {table} WHERE NOT is_demo AND principal = :p
                                              AND region = :s AND _period ~ '^[0-9]{{4}}-[0-9]{{2}}$' ORDER BY 1""",
                                    {"p": principal, "s": site})], []
    from scripts.load_slices import lineage
    months, books = set(), set()
    for m, f, sh in _all(conn, "SELECT DISTINCT _period, _src_file, _src_sheet FROM sales_fact WHERE NOT is_demo AND principal = :p",
                         {"p": principal}):
        if lineage(f, sh)[1] == site:
            months.add(m)
            books.add((f, sh))
    return sorted(m for m in months if re.match(r"^\d{4}-\d{2}$", m or "")), sorted(books)


def fill_branch_gaps(conn: Connection, targets: list[tuple[str, str, str, str]], changes: Changes) -> dict:
    """H2 (Yuan, 2026-10-03): each branch_targets() branch gets its own adjacent real month copied in - the latest
    before, carried forward, else the first after (adjacent_month) - tagged synthetic_branch_adjacent, source tag
    naming the month copied and ending _<site>. Existing fills are not touched. A branch already holding the copy
    of the same month is left as it is (a second run writes nothing); a copy of another month is replaced."""
    out = {}
    for principal, table, month, site in targets:
        months, books = _branch_months(conn, principal, table, site)
        t = adjacent_month(months, month)
        if t is None:
            out[f"{principal}.{table}.{month}.{site}"] = {"from": None, "rows": 0}
            continue
        src = f"{TAG}branch_adjacent_{table}_{month}_from_{t}_{site}"
        held = _all(conn, f"""SELECT _src_file, count(*) FROM {table} WHERE principal = :p AND _period = :m AND fill_source = '{BRANCH}'
                                 AND substring(_src_file from '{SITE_RE}') = :s GROUP BY 1""", {"p": principal, "m": month, "s": site})
        if [f for f, _ in held] == [src]:
            continue
        if held:
            gone = conn.execute(text(f"""DELETE FROM {table} WHERE principal = :p AND _period = :m AND fill_source = '{BRANCH}'
                                         AND substring(_src_file from '{SITE_RE}') = :s"""), {"p": principal, "m": month, "s": site}).rowcount
            changes.tally([(month, gone)], "removed", principal, table)
        cols = _all(conn, """SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = current_schema()
                             AND table_name = :t AND is_generated = 'NEVER' ORDER BY ordinal_position""", {"t": table})
        (ty, tm), (my, mm) = _ym(t), _ym(month)
        n = conn.execute(text(branch_copy_sql(table, [tuple(c) for c in cols])), {
            "p": principal, "m": month, "t": t, "site": site, "shift": (my - ty) * 12 + (mm - tm), "tag": BRANCH, "src": src,
            "mark": site[0].upper(), "files": [f for f, _ in books], "sheets": [sh for _, sh in books]}).rowcount
        changes.tally([(month, n)], "added", principal, table, f"{BRANCH} ({site}, copy of {t})")
        out[f"{principal}.{table}.{month}.{site}"] = {"from": t, "rows": n}
    return out


# --- ledger -------------------------------------------------------------------------------------------------------
def record(conn: Connection, run_id: str, run_by: str, started: datetime, changes: Changes, trigger: str) -> dict:
    from scripts import load_slices as ls
    changed = changes.changed()
    if changed:
        keys = sorted(changed)
        conn.execute(text("""
            INSERT INTO etl_load_event (run_id, slice, principal, table_name, month, site, source, status, reason, detail, files,
                synthetic_rows_removed, fill_rows_added, fill_rows_removed, run_by, started_at)
            SELECT :run_id, v.principal || ':' || v.table_name || ':' || v.month || ':*:' || :src, v.principal, v.table_name,
                   v.month, NULL, :src, 'loaded', NULL, v.detail, '{}', v.swept, v.added, v.removed, :run_by, :started
            FROM unnest(CAST(:p AS text[]), CAST(:t AS text[]), CAST(:m AS text[]), CAST(:d AS text[]), CAST(:sw AS int[]),
                        CAST(:a AS int[]), CAST(:r AS int[])) AS v(principal, table_name, month, detail, swept, added, removed)"""),
            {"run_id": run_id, "src": EVENT_SOURCE, "run_by": run_by, "started": started,
             "p": [k[0] for k in keys], "t": [k[1] for k in keys], "m": [k[2] for k in keys],
             "d": [f"{trigger}; " + ", ".join(sorted(set(changed[k].notes))) for k in keys],
             "sw": [changed[k].swept for k in keys], "a": [changed[k].added for k in keys], "r": [changed[k].removed for k in keys]})
        conn.execute(text("INSERT INTO audit_log (user_email, user_name, role, action, details) VALUES (:e, :n, 'etl', 'data_fill', :d)"),
                     {"e": AUDIT_ACTOR, "n": run_by,
                      "d": f"fill_missing run_id={run_id} cells={len(changed)} added={sum(c.added for c in changed.values())} "
                           f"removed={sum(c.removed for c in changed.values())} swept={sum(c.swept for c in changed.values())} ({trigger})"})
    coverage_written = 0
    for principal, table in ls.COVERAGE:
        coverage_written += ls.upsert_coverage(conn, ls.coverage_rows(conn, principal, table, None), None, only_changed=True)
    return {"events": len(changed), "coverage_rows_written": coverage_written}


# --- the step -----------------------------------------------------------------------------------------------------
def fill(conn: Connection, schema: str, run_id: str, run_by: str, end: str, started: datetime, trigger: str) -> dict:
    missing = [t for t in REQUIRED if conn.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar() is None]
    if missing:
        raise RuntimeError(f"schema '{schema}' lacks {missing}: apply migrations 0033 and 0038 first")
    if not conn.execute(text("SELECT count(*) FROM pg_attribute WHERE attrelid = to_regclass('derived_receipt_fact') "
                             "AND attname = 'opening_flag' AND NOT attisdropped")).scalar():
        raise RuntimeError(f"schema '{schema}' lacks derived_receipt_fact.opening_flag: apply migration 0040 first")
    from scripts import load_slices as ls
    changes = Changes()
    out = {"run_id": run_id, "schema": schema, "window": [FILL_START, end]}
    cov = [r for p, t in ls.COVERAGE if p == "delmonte" and t in FACT_KEYS for r in ls.coverage_rows(conn, p, t, None)]
    branches = branch_targets(cov, once_real_branches(conn), FILL_START, end)
    out["swept"] = sweep_real_wins(conn, changes, keep=branches)
    occupied = real_cells(conn)
    out["1_derived_receipts"] = derive_unilever_receipts(conn, run_id, FILL_START, end, occupied, changes)
    out["2_unilever_returns"] = transfer_unilever_returns(conn, FILL_START, end, occupied, changes)
    out["3_delmonte_split"] = split_delmonte_sales(conn, run_id, FILL_START, end, changes)
    out["4_gaps"] = fill_gaps(conn, schema, FILL_START, end, occupied, changes)
    out["4b_branch_gaps"] = fill_branch_gaps(conn, branches, changes)
    out["ledger"] = record(conn, run_id, run_by, started, changes, trigger)
    out["cells_changed"] = len(changes.changed())
    return out


def run_step(engine: Engine, schema: str, run_by: str | None = None, trigger: str = "manual", end: str | None = None,
             dry_run: bool = False, allow_public: bool = False) -> dict:
    """The whole fill step in one transaction (rolled back on a dry run)."""
    from scripts import load_slices as ls
    from scripts.run_canonical_load import _require_scratch_schema
    _require_scratch_schema(schema, allow_public=allow_public)
    started = datetime.now(timezone.utc)
    run_id = f"fill-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            ls._scope(conn, schema)
            out = fill(conn, schema, run_id, run_by or getpass.getuser(), end or last_complete_month(), started, trigger)
            tx.rollback() if dry_run else tx.commit()
        except BaseException:
            tx.rollback()
            raise
    out["dry_run"] = dry_run
    print(f"[fill_missing] {'DRY RUN (rolled back) ' if dry_run else ''}{_summary(out)}")
    return out


def _summary(out: dict) -> str:
    gaps = {k: v["rows"] for k, v in out["4_gaps"].items()}
    return (f"run_id={out['run_id']} schema={out['schema']} window={out['window'][0]}..{out['window'][1]} swept={out['swept']} "
            f"derived={out['1_derived_receipts']} returns={out['2_unilever_returns']} split={out['3_delmonte_split']} "
            f"gaps={gaps} branch_gaps={out['4b_branch_gaps']} cells_changed={out['cells_changed']} ledger={out['ledger']}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schema", required=True, help="a scratch schema, or public together with --target-public")
    p.add_argument("--target-public", action="store_true", help="explicit-only: allow --schema public")
    p.add_argument("--end", default=None, help="last month to fill (default: the last complete month)")
    p.add_argument("--dry-run", action="store_true", help="run the whole step and roll it back")
    args = p.parse_args()
    if args.target_public != (args.schema == "public"):
        p.error("--target-public and --schema public go together")
    from analytics.config import get_settings
    engine = create_engine(get_settings().supabase_db_url)
    out = run_step(engine, args.schema, trigger="manual", end=args.end, dry_run=args.dry_run,
                   allow_public=args.target_public)
    # Run on its own (not from the loader, which refreshes after its own fill): rebuild
    # the dashboard's marts from the fills just written (migration 0041).
    if not args.dry_run:
        from analytics.marts import refresh_marts_engine
        refresh_marts_engine(engine, f"fill_missing run_id={out['run_id']}", schema=args.schema)
    return 0


if __name__ == "__main__":
    sys.exit(main())
