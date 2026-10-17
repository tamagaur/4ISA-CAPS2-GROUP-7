"""
backend.marts — the dashboard's reads from the `mart` schema (migration 0041).

Every peso, piece and count the dashboard shows for a date range comes from here: small
pre-summed tables refreshed after each load, fill, forecast and LP run (analytics/marts.py),
instead of the fact tables summed per request.

DATA KIND. Each mart row is 'real', 'filled' or 'generated' (mart.data_kind). Every KPI,
the Pareto ranking and forecast accuracy read real rows only — the *_real views, or
data_kind = 'real' in the one WHERE every query here builds through _kind_filter(). Charts
may also show filled rows, labelled as estimates; generated (synthetic placeholder) rows only
in preview mode, where Unilever's 2021-22 placeholder months already count as sales
(backend/data_mode.py: the rows the mart marks preview_placeholder).

Scope strings ('unilever' / 'delmonte') reach this module already allowlisted by
backend.principals.normalize_principal and are bound as parameters, never interpolated.
"""
from __future__ import annotations

import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.classification.abc import TIER_A_CUTOFF, TIER_B_CUTOFF
from backend import batch
from backend.data_mode import PREVIEW, REAL
from backend.demo_flag import demo_enabled

PRINCIPALS = ("unilever", "delmonte")

# Words a card prints for each stored basis code.
PESOS_BASIS_LABEL = {
    "vat_inclusive": "selling price, VAT-inclusive",
    "ex_vat": "selling price, ex-VAT",
    "vat_inclusive_recorded_with_tax": "selling price, VAT-inclusive (recorded with tax)",
    "last_purchase_price": "at last purchase price",
    "net_amount_as_recorded": "Net Amount as recorded in the returns file",
}


# COMPLETE MONTHS (2026-10-11). The dashboard's SALES count every row the database holds
# for a month, real, filled or generated, so a month SSM sent no file for is no longer a
# gap: Del Monte has real sales for 17 months and generated ones for 51 (mart.sales_month,
# read 2026-10-11). Asked for by Audrey and approved by Kelvin for the frontend, to see the
# design with the months complete while SSM's files are outstanding; the Technical Adviser
# is to be told. It applies to what the dashboard DISPLAYS: the sales cards, the sales
# line, range totals and the range's Pareto. Stock cards, forecast accuracy, class changes
# and the stored ABC, forecast and LP tables still read real rows only, and every payload
# says which months are not SSM's data (sales_vs_stock[].provenance,
# kpis.sales_cumulative.synthetic_months).
#
# OFF since 2026-10-15 (kelvin-etl a1b5465, approved by Kelvin, Sir Catubag informed;
# CLAUDE.md hard rule 2 and docs/DEMO_DATA.md): the filled and generated (synthetic_v2)
# sales rows are retired for display, and schema demo is the only display source for
# generated data, shown in preview with DM_DEMO_ENABLED on. The snapshot no longer even
# loads those rows (SNAPSHOT_SQL reads real sales only). Turning this back on would count
# the retired rows in the range Pareto and let demo rows into real mode: a team decision,
# not a code change.
COUNT_FILLED_AND_GENERATED = False
# A filled or generated month counts only up to the last month with real sales for either
# principal (Feb 2026 today). The generator also wrote months after it (to Aug/Sep 2026);
# those are not gaps in SSM's history but the months the forecasts are for, and counting
# them would show invented sales as the actuals of a forecast month.
_LAST_REAL_SALES_MONTH_SQL = "SELECT MAX(period) FROM mart.sales_month WHERE data_kind = 'real'"


def _kind_filter(mode: str, alias: str = "") -> str:
    """Real rows, plus the demonstration back-cast months in preview when DM_DEMO_ENABLED is on. The older
    synthetic_v2 rows are retired for display (2026-10-15); see sales_mart_relation(). With
    COUNT_FILLED_AND_GENERATED on (off since the same day), the retired filled and generated rows too."""
    a = f"{alias}." if alias else ""
    if COUNT_FILLED_AND_GENERATED:
        return (f"({a}data_kind = 'real' OR ({a}data_kind IN ('filled', 'generated') "
                f"AND {a}period <= ({_LAST_REAL_SALES_MONTH_SQL})))")
    if mode == PREVIEW and demo_enabled():
        return f"({a}data_kind = 'real' OR {a}preview_placeholder)"
    return f"{a}data_kind = 'real'"


_DEMO_SALES_MART = """(
    SELECT principal, level, product_key, category_path, period, data_kind, source_tag, in_principal_total,
           preview_placeholder, pieces, pieces_null_rows, pieces_unit_confirmed, pesos, pesos_basis, gsv, source_rows
    FROM mart.sales_mart WHERE data_kind <> 'generated'
    UNION ALL
    SELECT 'unilever'::text, 'product'::text, d.product_key, NULL::text, d.period, 'generated'::text,
           'demo_backcast'::text, true, true, d.quantity, 0, true, d.net_amount, 'demo_backcast'::text, NULL::numeric, 1
    FROM demo.unilever_sku_sales d
    WHERE d.origin = 'backcast' AND d.run_id = (SELECT MAX(run_id) FROM demo.run WHERE principal = 'unilever')
)"""


def sales_mart_relation(mode: str) -> str:
    """mart.sales_mart verbatim, except in preview with DM_DEMO_ENABLED on: the mart without its retired
    synthetic_v2 'generated' rows, plus demo.unilever_sku_sales' back-cast rows shaped as mart rows
    (preview_placeholder = true, so _kind_filter() picks them up)."""
    return _DEMO_SALES_MART if (mode == PREVIEW and demo_enabled()) else "mart.sales_mart"


def _scope_list(scope: str) -> list[str]:
    return list(PRINCIPALS) if scope == "all" else [scope]


def month_label(period: str | None) -> str | None:
    if not period:
        return None
    return datetime.date(int(period[:4]), int(period[5:7]), 1).strftime("%b %Y")


def range_label(start: str | None, end: str | None) -> str | None:
    if not start or not end:
        return None
    return month_label(start) if start == end else f"{month_label(start)} – {month_label(end)}"


def month_add(period: str, months: int) -> str:
    index = int(period[:4]) * 12 + int(period[5:7]) - 1 + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

REFRESH_PRESENT_SQL = "SELECT to_regclass('mart.refresh_log') IS NOT NULL AS present"
REFRESH_STATUS_SQL = "SELECT * FROM mart.refresh_status"
# Remembered once seen on the real database, like backend/lp_cycle.lp_run_present.
_REFRESH_PRESENT = {"value": False}


def present(db: Session) -> bool:
    """Whether migration 0041's marts exist (to_regclass, which never errors)."""
    if _REFRESH_PRESENT["value"]:
        return True
    row = batch.first(db, REFRESH_PRESENT_SQL)
    found = bool(row and row["present"])
    if found and isinstance(db, Session):
        _REFRESH_PRESENT["value"] = True
    return found


def present_known() -> bool:
    """True once present() has seen the marts (no lookup needed any more)."""
    return _REFRESH_PRESENT["value"]


def status(db: Session) -> dict:
    """When the marts were last rebuilt and whether a source changed since
    (mart.refresh_status). present=False on a database without migration 0041."""
    if not present(db):
        return {"present": False, "refreshed_at": None, "trigger": None, "stale": None, "stale_reason": None}
    row = batch.first(db, REFRESH_STATUS_SQL) or {}
    changed = [
        name for name, key in (("a data load", "latest_load"), ("a fill run", "latest_fill"),
                               ("a forecast run", "latest_forecast"), ("an LP run", "latest_lp_run"))
        if row.get(key) is not None and row.get("refreshed_at") is not None and row[key] > row["refreshed_at"]
    ]
    refreshed = row.get("refreshed_at")
    return {
        "present": True,
        "refreshed_at": refreshed.isoformat() if hasattr(refreshed, "isoformat") else refreshed,
        "trigger": row.get("trigger"),
        "stale": bool(row.get("stale")) if row.get("stale") is not None else None,
        "stale_reason": (f"{', '.join(changed)} finished after the last refresh" if changed
                         else "the marts have never been refreshed" if refreshed is None else None),
    }


# ---------------------------------------------------------------------------
# The month-level marts, read ONCE per request
# ---------------------------------------------------------------------------
# Every month-level figure on the dashboard (sales, stock counts, purchases, estimated
# receipts, returns: about 900 rows for both principals and every month) comes from this
# one statement, kept on the request's session (Session.info) and answered in memory.
# One round trip instead of ~25: each query costs the network round trip, ~0.12 s from
# the team's machines to Supabase, however small it is (measured 2026-10-04).
# Only 'real' rows are read here. 'generated' (synthetic_v2) and 'filled' sales rows (synthetic_category_split,
# synthetic_v2_gap) are retired for display (2026-10-15): schema demo is the single display source. Nothing deleted.
SNAPSHOT_SQL = """
    SELECT 'sales' AS src, principal, period, data_kind, NULL AS source_tag, NULL AS flow,
           pesos, pieces, any_recorded_with_tax AS recorded_with_tax, preview_placeholder AS placeholder,
           NULL::date AS first_date, NULL::date AS last_date, NULL::int AS negative_rows, NULL::bigint AS products
    FROM mart.sales_month WHERE data_kind = 'real'
    UNION ALL
    SELECT 'stock', principal, period, data_kind, NULL, NULL, pesos, pieces, NULL, NULL,
           first_count_date, count_date, NULL, products
    FROM mart.inventory_count
    UNION ALL
    SELECT 'flow', principal, period, data_kind, source_tag, flow, pesos, pieces, NULL, NULL,
           NULL, NULL, negative_rows, products
    FROM mart.flow_month
"""


_SNAPSHOT_DEMO_ROWS = """
    UNION ALL
    SELECT 'sales', 'unilever', period, 'generated', NULL, NULL, SUM(net_amount), SUM(quantity), NULL::boolean, true,
           NULL::date, NULL::date, NULL::int, NULL::bigint
    FROM demo.unilever_sku_sales
    WHERE origin = 'backcast' AND run_id = (SELECT MAX(run_id) FROM demo.run WHERE principal = 'unilever')
    GROUP BY period
"""


def snapshot_sql() -> str:
    """SNAPSHOT_SQL verbatim, plus the demonstration back-cast months (as preview placeholders) when DM_DEMO_ENABLED
    is on. Real-mode readers never see them: _kinds() shows a placeholder row only in preview."""
    return SNAPSHOT_SQL + _SNAPSHOT_DEMO_ROWS if demo_enabled() else SNAPSHOT_SQL


class _Snapshot:
    def __init__(self, rows):
        self.sales: dict[tuple, dict] = {}
        self.stock: dict[tuple, dict] = {}
        self.flows: dict[tuple, list[dict]] = {}
        for r in rows:
            key = (r["principal"], r["period"], r["data_kind"])
            if r["src"] == "sales":
                self.sales[key] = dict(r)
            elif r["src"] == "stock":
                self.stock[key] = dict(r)
            else:
                self.flows.setdefault((r["principal"], r["period"], r["flow"]), []).append(dict(r))


def _snapshot(db: Session) -> _Snapshot:
    info = getattr(db, "info", None)
    if isinstance(info, dict) and "mart_snapshot" in info:
        return info["mart_snapshot"]
    snap = _Snapshot(batch.rows(db, snapshot_sql()))
    if isinstance(info, dict):
        info["mart_snapshot"] = snap
    return snap


def _f(value) -> float | None:
    return float(value) if value is not None else None


def _sum(values) -> float | None:
    """SQL SUM: None when there is nothing non-null to add."""
    present = [float(v) for v in values if v is not None]
    return sum(present) if present else None


def _last_real_sales_month(db: Session) -> str | None:
    """_LAST_REAL_SALES_MONTH_SQL in memory: the last month either principal has real sales."""
    months = [k[1] for k in _snapshot(db).sales if k[2] == "real"]
    return max(months) if months else None


def _kinds(mode: str, row: dict, last_real: str | None = None) -> bool:
    """_kind_filter in memory. `last_real` is _last_real_sales_month()."""
    if row["data_kind"] == "real":
        return True
    if COUNT_FILLED_AND_GENERATED:
        return last_real is not None and row["period"] <= last_real
    return mode == PREVIEW and bool(row.get("placeholder"))


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------

def latest_sales_period(db: Session, principal: str) -> str | None:
    """The most recent month with real sales for one principal."""
    months = [k[1] for k in _snapshot(db).sales if k[0] == principal and k[2] == "real"]
    return max(months) if months else None


def _sales_rows(db: Session, principal: str, period: str, mode: str) -> list[dict]:
    snap = _snapshot(db)
    real = snap.sales.get((principal, period, "real"))
    if real is not None and real["pesos"] is not None:
        # Real data always wins (DEC-31): a month SSM has figures for is never topped up.
        return [real]
    rows = [real] + [snap.sales.get((principal, period, kind)) for kind in ("filled", "generated")]
    last_real = _last_real_sales_month(db)
    return [r for r in rows if r is not None and _kinds(mode, r, last_real)]


def sales_by_period(db: Session, periods: list[str], principal: str, mode: str = REAL) -> dict[str, float | None]:
    """Pesos per month for ONE principal: real rows (plus preview placeholders)."""
    return {p: _sum(r["pesos"] for r in _sales_rows(db, principal, p, mode)) for p in periods}


def sales_sources_by_period(db: Session, periods: list[str], principal: str, mode: str = REAL) -> dict[str, list[str]]:
    """The data kinds behind each month's sales for ONE principal, among the rows
    sales_by_period counts: ['real'], ['generated'], ['filled', 'real'], ... A month
    with no row is left out. What a card or chart needs to say a figure is not SSM's."""
    out = {}
    for p in periods:
        kinds = sorted(r["data_kind"] for r in _sales_rows(db, principal, p, mode) if r["pesos"] is not None)
        if kinds:
            out[p] = kinds
    return out


def pieces_by_period(db: Session, periods: list[str], principal: str, mode: str = REAL) -> dict[str, float | None]:
    """Pieces per month, Unilever only: Del Monte's sell-out quantity unit is
    unconfirmed (DEC-31 facts), so its pieces are never summed into a KPI."""
    if principal != "unilever":
        return {p: None for p in periods}
    return {p: _sum(r["pieces"] for r in _sales_rows(db, principal, p, mode)) for p in periods}


def estimated_sales_by_period(db: Session, periods: list[str], principal: str, mode: str = REAL) -> dict[str, dict]:
    """Non-real sales per month for ONE principal, for a chart's estimated points. RETIRED 2026-10-15: the filled
    (synthetic_category_split, synthetic_v2_gap) and generated (synthetic_v2) sales rows are no longer served;
    schema demo is the single display source for anything generated, and a chart draws it from there. Returns {}.
    The signature stays so every caller keeps working."""
    return {}


def tax_inclusive_months(db: Session) -> set[str]:
    """Del Monte months whose real sell-out pesos were recorded with tax (X2 rule)."""
    return {k[1] for k, r in _snapshot(db).sales.items()
            if k[0] == "delmonte" and k[2] == "real" and r.get("recorded_with_tax")}


def net_sales_total(db: Session, start: str, end: str, principal: str, mode: str = REAL) -> float | None:
    """The range's net sales for one principal (returns included), the KPI's own sum."""
    months = sorted({k[1] for k in _snapshot(db).sales if k[0] == principal and start <= k[1] <= end})
    return _sum(r["pesos"] for m in months for r in _sales_rows(db, principal, m, mode))


def sales_month_span(db: Session, scope: str) -> tuple[str, str] | None:
    """The first and last month with a sales row of any kind (real, filled or
    generated) for the scope's principals. Only where to look: which of those
    rows count as sales is still _sales_rows' rule, month by month."""
    wanted = _scope_list(scope)
    months = [k[1] for k in _snapshot(db).sales if k[0] in wanted]
    return (min(months), max(months)) if months else None


# ---------------------------------------------------------------------------
# Flows: purchases, estimated receipts, returns
# ---------------------------------------------------------------------------

def flow_by_period(db: Session, periods: list[str], principal: str, flow: str) -> dict[str, dict]:
    """{period: {real, estimated, estimated_kind, estimated_source, negative_rows, products}}
    for ONE principal. real = real rows' pesos; estimated = filled rows' pesos — except
    'returns', whose only non-real source is the retired synthetic fill (salesreturn_fact's
    fill_source is always one of synthetic_v2 / synthetic_v2_gap / synthetic_rate_transfer /
    synthetic_branch_adjacent — every value its CHECK constraint allows; there is no
    legitimate derived-returns estimate like estimated_receipts has). Retired 2026-10-16
    (rule 2, B1): returns never surfaces an estimate, real mode or preview."""
    snap = _snapshot(db)
    out = {}
    for p in periods:
        slot = {"real": None, "estimated": None, "estimated_kind": None, "estimated_source": None,
                "negative_rows": None, "products": None}
        for r in snap.flows.get((principal, p, flow), []):
            value = _f(r["pesos"])
            if r["data_kind"] == "real":
                slot["real"] = value if slot["real"] is None or value is None else slot["real"] + value
            elif flow != "returns" and r["data_kind"] == "filled" and value is not None:
                slot["estimated"] = (slot["estimated"] or 0.0) + value
                slot["estimated_kind"] = "filled"
                slot["estimated_source"] = r["source_tag"]
                slot["negative_rows"] = (slot["negative_rows"] or 0) + int(r["negative_rows"] or 0)
                if r["products"] is not None:
                    slot["products"] = (slot["products"] or 0) + int(r["products"])
        out[p] = slot
    return out


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------

def stock_period_at_or_before(db: Session, end: str | None, scope: str) -> str | None:
    """The latest real stock count whose month is on or before `end` (any month when
    `end` is None), within the scope: the stock at the range's end."""
    months = [k[1] for k in _snapshot(db).stock
              if k[2] == "real" and (scope == "all" or k[0] == scope) and (end is None or k[1] <= end)]
    return max(months) if months else None


def _real_stock(db: Session, principal: str, period: str | None) -> dict | None:
    return _snapshot(db).stock.get((principal, period, "real")) if period is not None else None


def stock_by_period(db: Session, periods: list[str], principal: str) -> dict[str, float | None]:
    """Real stock pesos (at last purchase price) per count month, ONE principal."""
    return {p: _f((_real_stock(db, principal, p) or {}).get("pesos")) for p in periods}


def neighbour_counts(db: Session, period: str, principal: str) -> list[float]:
    """The real stock pesos of the counts just before and just after `period` for one
    principal (whichever exist): what an unusual count is judged against."""
    months = sorted(k[1] for k, r in _snapshot(db).stock.items()
                    if k[0] == principal and k[2] == "real" and r["pesos"] is not None)
    before = [m for m in months if m < period]
    after = [m for m in months if m > period]
    picked = ([before[-1]] if before else []) + ([after[0]] if after else [])
    return [float(_real_stock(db, principal, m)["pesos"]) for m in picked]


def stock_pieces_at(db: Session, period: str | None, principal: str) -> float | None:
    """Real stock in pieces at one count, Unilever only (Del Monte: no pack size)."""
    if period is None or principal != "unilever":
        return None
    return _f((_real_stock(db, "unilever", period) or {}).get("pieces"))


def estimated_stock_by_period(db: Session, periods: list[str], principal: str, mode: str = REAL) -> dict[str, dict]:
    """Non-real stock pesos per count month for ONE principal, for the chart's estimated
    points. RETIRED 2026-10-16 (rule 2, B1): mart.inventory_mart's filled/generated rows all
    come from is_demo=true inventory_fact rows (synthetic_v2, synthetic_v2_gap,
    synthetic_branch_adjacent — every fill_source inventory_fact allows) — the retired
    synthetic family, never served, real mode or preview. schema demo is the single display
    source for anything generated, and this chart series has no demo stock analog wired in.
    Returns {}. The signature stays so every caller keeps working."""
    return {}


def stock_coverage(db: Session, period: str | None, scope: str) -> list[str]:
    """Principals with a real stock valuation at `period`, within the scope."""
    if period is None:
        return []
    return sorted(who for who in PRINCIPALS
                  if (scope == "all" or who == scope) and (_real_stock(db, who, period) or {}).get("pesos") is not None)


def count_dates(db: Session, periods: list[str], scope: str) -> dict[str, str]:
    """The day each real count was taken, keyed by its month, when every principal in
    scope counted that month on one day (Unilever states it; Del Monte's is not loaded,
    so a month holding a Del Monte count gets no date). Display only."""
    out: dict[str, str] = {}
    for period in [p for p in periods if p]:
        group = [r for who in _scope_list(scope) if (r := _real_stock(db, who, period)) is not None]
        days = {(r["first_date"], r["last_date"]) for r in group}
        if len(days) == 1:
            first, last = days.pop()
            if first is not None and first == last:
                out[period] = last.isoformat() if hasattr(last, "isoformat") else str(last)[:10]
    return out


def stock_pieces_by_product(db: Session, period: str | None, product_keys: list[int]) -> dict[int, float | None]:
    """Real stock in pieces per product at one count (NULL when unusable pack size).
    A product missing from the dict has no row in that count."""
    if period is None or not product_keys:
        return {}
    rows = batch.rows(db, *stock_pieces_query(period, product_keys))
    return {int(r["product_key"]): (float(r["pieces"]) if r["pieces"] is not None else None) for r in rows}


def stock_pieces_query(period: str, product_keys: list[int]) -> tuple[str, dict]:
    return """
        SELECT product_key, pieces FROM mart.inventory_mart_real
        WHERE period = :period AND product_key = ANY(:keys)
    """, {"period": period, "keys": product_keys}


def stock_status_by_product(db: Session, period: str | None, product_keys: list[int]) -> dict[int, tuple[bool, bool]]:
    """{product_key: (any_active, any_inactive)} at one real count."""
    if period is None or not product_keys:
        return {}
    rows = batch.rows(db, *stock_status_query(period, product_keys))
    return {int(r["product_key"]): (bool(r["any_active"]), bool(r["any_inactive"])) for r in rows}


def stock_status_query(period: str, product_keys: list[int]) -> tuple[str, dict]:
    return """
        SELECT product_key, any_active, any_inactive FROM mart.inventory_mart_real
        WHERE period = :period AND product_key = ANY(:keys)
    """, {"period": period, "keys": product_keys}


# ---------------------------------------------------------------------------
# Pareto over a range
# ---------------------------------------------------------------------------

# The ABC run's rules (analytics/classification/orchestrate_abc.py, 'single'), applied to
# the range's months per product instead of one month's: a month where returns exceeded
# sales counts as 0 (orchestrate_abc.py:208, the run's rule for a window of several months;
# Yuan, 2026-10-05: one revenue rule everywhere, so this and class_changes() agree), and a
# product is ranked when what is left is above 0; an explicit blank peso amount
# anywhere in the range leaves it out, as the run does; ties go to the lower product_key
# (classify_abc's sku_id order); class A while the running share is <= the A cutoff, B
# while <= the B cutoff, else C. Del Monte ranks product categories (DEC-03).
PARETO_SQL = """
    WITH rev AS (
        SELECT s.product_key, SUM(GREATEST(s.pesos, 0)) AS revenue, SUM(s.pieces) AS pieces,
               COUNT(*) AS months_with_sales
        FROM {sales_mart} s
        WHERE s.principal = :principal AND s.in_principal_total
          AND s.period BETWEEN :start AND :end AND {kind}
        GROUP BY s.product_key
        HAVING bool_and(s.pesos IS NOT NULL) AND SUM(GREATEST(s.pesos, 0)) > 0
    ),
    ranked AS (
        SELECT rev.*,
               ROW_NUMBER() OVER (ORDER BY revenue DESC, product_key) AS rank,
               revenue / SUM(revenue) OVER () AS share,
               SUM(revenue) OVER (ORDER BY revenue DESC, product_key ROWS UNBOUNDED PRECEDING)
                   / SUM(revenue) OVER () AS cumulative_share
        FROM rev
    )
    SELECT r.rank, r.product_key, pd.sku_code, pd.product_name, pd.category_path, pd.brand,
           r.revenue, r.pieces, r.months_with_sales, r.share, r.cumulative_share,
           CASE WHEN r.cumulative_share <= :a THEN 'A' WHEN r.cumulative_share <= :b THEN 'B' ELSE 'C' END AS class
    FROM ranked r
    LEFT JOIN product_dimension pd ON pd.product_key = r.product_key
    ORDER BY r.rank
"""


def pareto(db: Session, start: str, end: str, principal: str, mode: str = REAL) -> list[dict]:
    """Every product (Del Monte: category) ranked on its sales over start..end, a month
    where returns exceeded sales counted as 0."""
    rows = batch.rows(db, *pareto_query(start, end, principal, mode))
    return [
        {
            "rank": int(r["rank"]),
            "product_key": int(r["product_key"]),
            "sku_id": r["sku_code"],
            "product_name": r["product_name"],
            "category_path": r["category_path"],
            "brand": r["brand"],
            "principal": principal,
            "class": r["class"],
            "revenue": round(float(r["revenue"]), 2),
            "pieces": float(r["pieces"]) if r["pieces"] is not None and principal == "unilever" else None,
            "months_with_sales": int(r["months_with_sales"]),
            "share": float(r["share"]),
            "cumulative_share": float(r["cumulative_share"]),
        }
        for r in rows
    ]


def pareto_query(start: str, end: str, principal: str, mode: str = REAL) -> tuple[str, dict]:
    return (PARETO_SQL.format(kind=_kind_filter(mode, "s"), sales_mart=sales_mart_relation(mode)),
            {"principal": principal, "start": start, "end": end, "a": TIER_A_CUTOFF, "b": TIER_B_CUTOFF})


def pareto_blocked_reason(db: Session, start: str, end: str, principal: str, mode: str = REAL) -> str:
    """Why pareto() ranked nothing for one principal over the range (B3, 2026-10-16): two
    different causes that used to share one wrong message ('no product sold more than it
    took back'). No real sales row at all in the range means Del Monte wasn't collected, or
    Unilever genuinely sold nothing; rows present but every one net-sold <= 0 means returns
    matched or exceeded sales everywhere — the original wording, kept for that case only."""
    label = range_label(start, end)
    sql = f"""
        SELECT EXISTS (
            SELECT 1 FROM {sales_mart_relation(mode)} s
            WHERE s.principal = :principal AND s.in_principal_total
              AND s.period BETWEEN :start AND :end AND {_kind_filter(mode, 's')}
        ) AS present
    """
    row = batch.first(db, sql, {"principal": principal, "start": start, "end": end})
    if not (row and row["present"]):
        return (f"No {principal} sales were collected in {label}." if principal == "delmonte"
                else f"No {principal} product sold anything in {label}.")
    return f"No {principal} product sold more than it took back in {label}."


# Why chosen products have no rank in either of two ranges: months on file and blank
# amounts, for the side of a class change where pareto() has no row for the product.
RANGE_REVENUE_SQL = """
    SELECT s.product_key,
           COUNT(*) FILTER (WHERE s.period BETWEEN :start AND :end) AS months,
           COALESCE(bool_or(s.pesos IS NULL) FILTER (WHERE s.period BETWEEN :start AND :end), false) AS has_blank,
           COUNT(*) FILTER (WHERE s.period BETWEEN :cstart AND :cend) AS compare_months,
           COALESCE(bool_or(s.pesos IS NULL) FILTER (WHERE s.period BETWEEN :cstart AND :cend), false) AS compare_has_blank
    FROM mart.sales_mart_real s
    WHERE s.principal = :principal AND s.in_principal_total AND s.product_key = ANY(:keys)
      AND (s.period BETWEEN :start AND :end OR s.period BETWEEN :cstart AND :cend)
    GROUP BY s.product_key
"""


def _unranked_side(row: dict | None, prefix: str, principal: str, principal_collected: bool) -> tuple[float | None, str]:
    """(revenue, why it has no class) for a product pareto() did not rank in a range.
    months == 0 can mean two different things: Unilever genuinely sold nothing (0.0 is
    correct), or — Del Monte's 2024-03..2025-02 taxonomy-break gap — nothing was collected
    for the WHOLE principal that range, so 0.0 would be fabricated (the product's real
    revenue, wherever it is ranked, would then read as 100% growth/decline). `not_collected`
    only fires when `principal_collected` says the principal has no real month at all in
    this range; a Del Monte category simply missing from an otherwise-reported range is
    still a real, counted zero."""
    months = int(row[f"{prefix}months"] or 0) if row else 0
    if months == 0:
        if principal == "delmonte" and not principal_collected:
            return None, "not_collected"
        return 0.0, "no sales in the range"
    if row[f"{prefix}has_blank"]:
        return None, "a month with a blank sales amount, so it is not ranked"
    return 0.0, "returns matched or exceeded sales in every month it has, so it is not ranked"


PRINCIPAL_MONTHS_SQL = """
    SELECT COUNT(DISTINCT period) AS months FROM mart.sales_mart_real
    WHERE principal = :principal AND in_principal_total AND period BETWEEN :start AND :end
"""


def principal_collected(db: Session, principal: str, start: str, end: str) -> bool:
    """Whether at least one real sales row exists for the principal anywhere in the range —
    distinguishes 'nothing was collected' from 'rows exist but nobody net-sold' (B2, 2026-10-16)."""
    row = batch.first(db, PRINCIPAL_MONTHS_SQL, {"principal": principal, "start": start, "end": end})
    return bool(row and row["months"])


def class_changes(db: Session, start: str, end: str, compare_start: str, compare_end: str, principal: str) -> dict:
    """Products (Del Monte: categories) that entered or left Class A between the compare range
    and start..end, each range ranked by pareto() on real rows, so revenue is the range's
    sales with each returns-heavy month counted as 0. A product not ranked in a range has
    class None and the reason in its *_note."""
    batch.prefetch(db, [pareto_query(start, end, principal), pareto_query(compare_start, compare_end, principal)])
    now = {r["product_key"]: r for r in pareto(db, start, end, principal)}
    before = {r["product_key"]: r for r in pareto(db, compare_start, compare_end, principal)}
    a_now = {k for k, r in now.items() if r["class"] == "A"}
    a_before = {k for k, r in before.items() if r["class"] == "A"}
    entered, left = a_now - a_before, a_before - a_now
    unranked = sorted({k for k in entered if k not in before} | {k for k in left if k not in now})
    sums = {}
    now_collected = before_collected = True
    if unranked:
        sums = {int(r["product_key"]): r for r in db.execute(text(RANGE_REVENUE_SQL), {
            "principal": principal, "keys": unranked, "start": start, "end": end,
            "cstart": compare_start, "cend": compare_end}).mappings().all()}
        if principal == "delmonte":
            now_collected = principal_collected(db, principal, start, end)
            before_collected = principal_collected(db, principal, compare_start, compare_end)

    def item(key: int, change: str) -> dict:
        n, b = now.get(key), before.get(key)
        ref = n or b
        revenue, note = (n["revenue"], None) if n else _unranked_side(sums.get(key), "", principal, now_collected)
        compare_revenue, compare_note = (b["revenue"], None) if b else _unranked_side(
            sums.get(key), "compare_", principal, before_collected)
        both = revenue is not None and compare_revenue is not None
        return {
            "change": change, "product_key": key, "sku_id": ref["sku_id"], "product_name": ref["product_name"],
            "category_path": ref["category_path"],
            "class": n["class"] if n else None, "compare_class": b["class"] if b else None,
            "rank": n["rank"] if n else None, "compare_rank": b["rank"] if b else None,
            "revenue": revenue, "compare_revenue": compare_revenue,
            "change_pesos": round(revenue - compare_revenue, 2) if both else None,
            "change_pct": (round((revenue - compare_revenue) / compare_revenue * 100, 1)
                           if both and compare_revenue > 0 else None),
            "class_note": note, "compare_class_note": compare_note,
        }

    entered_items = sorted((item(k, "entered") for k in entered), key=lambda i: (-(i["revenue"] or 0), i["product_key"]))
    left_items = sorted((item(k, "left") for k in left), key=lambda i: (-(i["compare_revenue"] or 0), i["product_key"]))

    def total(items: list[dict], field: str) -> float | None:
        """None when any item's side is unknown (not_collected or a blank-capture month,
        both carried as revenue None) rather than summing it as a fabricated 0 (B2, 2026-10-16:
        a Del Monte range with nothing collected used to total ₱0, which read as a real zero
        rather than 'nothing to add up')."""
        if any(i[field] is None for i in items):
            return None
        return round(sum(i[field] or 0.0 for i in items), 2)

    def total_reason(items: list[dict], field: str, note_field: str) -> str | None:
        reasons = {i[note_field] for i in items if i[field] is None}
        if not reasons:
            return None
        return reasons.pop() if len(reasons) == 1 else "mixed: " + "; ".join(sorted(reasons))

    return {
        "principal": principal,
        "grain": "category" if principal == "delmonte" else "sku",
        "revenue_rule": ("Each range's sales added up month by month; a month where returns exceeded sales "
                         "counts as 0 (the ABC run's rule for several months)."),
        "class_a_count": len(a_now), "compare_class_a_count": len(a_before),
        "stayed_count": len(a_now & a_before),
        "entered_count": len(entered_items), "left_count": len(left_items),
        "entered_revenue": total(entered_items, "revenue"),
        "entered_revenue_reason": total_reason(entered_items, "revenue", "class_note"),
        "entered_compare_revenue": total(entered_items, "compare_revenue"),
        "entered_compare_revenue_reason": total_reason(entered_items, "compare_revenue", "compare_class_note"),
        "left_revenue": total(left_items, "revenue"),
        "left_revenue_reason": total_reason(left_items, "revenue", "class_note"),
        "left_compare_revenue": total(left_items, "compare_revenue"),
        "left_compare_revenue_reason": total_reason(left_items, "compare_revenue", "compare_class_note"),
        "entered": entered_items, "left": left_items,
    }


def _null_side_reason(principal: str, first: str | None, last: str | None, win_start: str, win_end: str,
                      principal_months) -> str | None:
    """Why a year-over-year side has no real month (backend/series_gaps.py vocabulary).
    Unilever: inside the product's own first..last sale months the product sold nothing (no_sale, a real zero);
    outside them it was not on sale (outside_product_lifespan). Del Monte has no product lifespan: no category
    reported anything in the window (not_collected) or only this one is absent (category_absent)."""
    if principal == "delmonte":
        return "not_collected" if not principal_months else "category_absent"
    if first is None or last is None:
        return None
    return "outside_product_lifespan" if (last < win_start or first > win_end) else "no_sale"


def product_yoy(db: Session, start: str, end: str, principal: str) -> list[dict]:
    """Per product (Del Monte: category), real net sales over start..end against the same
    months a year earlier. A side with no real month in range is None, never 0."""
    prior_start, prior_end = month_add(start, -12), month_add(end, -12)
    rows = db.execute(text("""
        WITH cur AS (
            SELECT product_key, SUM(pesos) AS pesos, SUM(pieces) AS pieces, COUNT(*) AS months
            FROM mart.sales_mart_real
            WHERE principal = :principal AND in_principal_total AND period BETWEEN :start AND :end
            GROUP BY product_key
        ), prev AS (
            SELECT product_key, SUM(pesos) AS pesos, SUM(pieces) AS pieces, COUNT(*) AS months
            FROM mart.sales_mart_real
            WHERE principal = :principal AND in_principal_total AND period BETWEEN :pstart AND :pend
            GROUP BY product_key
        ), span AS (
            SELECT product_key, MIN(period) AS first_period, MAX(period) AS last_period
            FROM mart.sales_mart_real WHERE principal = :principal AND in_principal_total GROUP BY product_key
        )
        SELECT COALESCE(c.product_key, p.product_key) AS product_key, pd.sku_code, pd.product_name,
               pd.category_path, c.pesos AS pesos, c.pieces AS pieces, c.months AS months,
               p.pesos AS prior_pesos, p.pieces AS prior_pieces, p.months AS prior_months,
               sp.first_period, sp.last_period,
               (SELECT COUNT(DISTINCT period) FROM mart.sales_mart_real
                 WHERE principal = :principal AND in_principal_total AND period BETWEEN :start AND :end) AS principal_months,
               (SELECT COUNT(DISTINCT period) FROM mart.sales_mart_real
                 WHERE principal = :principal AND in_principal_total AND period BETWEEN :pstart AND :pend) AS principal_prior_months
        FROM cur c FULL OUTER JOIN prev p ON p.product_key = c.product_key
        LEFT JOIN span sp ON sp.product_key = COALESCE(c.product_key, p.product_key)
        LEFT JOIN product_dimension pd ON pd.product_key = COALESCE(c.product_key, p.product_key)
        ORDER BY c.pesos DESC NULLS LAST, COALESCE(c.product_key, p.product_key)
    """), {"principal": principal, "start": start, "end": end, "pstart": prior_start, "pend": prior_end}).mappings().all()
    out = []
    for r in rows:
        cur, prior = r["pesos"], r["prior_pesos"]
        item_reasons = {}
        if cur is None:
            reason = _null_side_reason(principal, r.get("first_period"), r.get("last_period"), start, end,
                                       r.get("principal_months"))
            if reason:
                item_reasons["pesos_reason"] = reason
        if prior is None:
            reason = _null_side_reason(principal, r.get("first_period"), r.get("last_period"), prior_start, prior_end,
                                       r.get("principal_prior_months"))
            if reason:
                item_reasons["prior_pesos_reason"] = reason
        out.append({**item_reasons,
            "product_key": int(r["product_key"]), "sku_id": r["sku_code"], "product_name": r["product_name"],
            "category_path": r["category_path"],
            "pesos": float(cur) if cur is not None else None,
            "prior_pesos": float(prior) if prior is not None else None,
            "pieces": float(r["pieces"]) if r["pieces"] is not None and principal == "unilever" else None,
            "prior_pieces": float(r["prior_pieces"]) if r["prior_pieces"] is not None and principal == "unilever" else None,
            "months": int(r["months"] or 0), "prior_months": int(r["prior_months"] or 0),
            "change_pct": (round((float(cur) - float(prior)) / abs(float(prior)) * 100, 2)
                           if cur is not None and prior is not None and float(prior) != 0 else None),
        })
    return out


def product_sales(db: Session, start: str, end: str, principal: str, mode: str = REAL) -> list[dict]:
    """Product x month rows for a chart, real and filled (generated too in preview), each
    with its data_kind: Del Monte's product split (DEC-31, filled) is served here only."""
    # Real rows only, plus the demonstration back-cast rows in preview when DM_DEMO_ENABLED is on. The DEC-31 Del
    # Monte product split ('filled') and the synthetic_v2 rows are retired for display (2026-10-15), here and below.
    kinds = ["real", "generated"] if (mode == PREVIEW and demo_enabled()) else ["real"]
    rows = db.execute(text(f"""
        SELECT s.product_key, pd.sku_code, pd.product_name, s.level, s.period, s.data_kind, s.source_tag,
               s.pesos, s.pieces, s.pieces_unit_confirmed, s.pesos_basis
        FROM {sales_mart_relation(mode)} s
        LEFT JOIN product_dimension pd ON pd.product_key = s.product_key
        WHERE s.principal = :principal AND s.level = 'product' AND s.period BETWEEN :start AND :end
          AND s.data_kind = ANY(:kinds)
        ORDER BY s.product_key, s.period
    """), {"principal": principal, "start": start, "end": end, "kinds": kinds}).mappings().all()
    return [
        {
            "product_key": int(r["product_key"]), "sku_id": r["sku_code"], "product_name": r["product_name"],
            "period": r["period"], "data_kind": r["data_kind"], "source": r["source_tag"],
            "estimated": r["data_kind"] != "real",
            "pesos": float(r["pesos"]) if r["pesos"] is not None else None,
            "pieces": float(r["pieces"]) if r["pieces"] is not None and r["pieces_unit_confirmed"] else None,
            "pesos_basis": PESOS_BASIS_LABEL.get(r["pesos_basis"], r["pesos_basis"]),
        }
        for r in rows if r["data_kind"] in kinds
    ]


# ---------------------------------------------------------------------------
# Idle stock
# ---------------------------------------------------------------------------

def idle_stock(db: Session, count_period: str | None, limit: int | None = None) -> dict:
    """Unilever products in the count at `count_period` with no piece sold in the
    DEAD_SKU_MONTHS (6) sales months up to it, valued at last purchase price."""
    empty = {"count_period": count_period, "count_date": None, "window_start": None, "window_end": None,
             "window_months": None, "products": 0, "products_with_value": 0, "pesos": None,
             "never_sold": 0, "items": [], "blocked_reason": None}
    if count_period is None:
        return {**empty, "blocked_reason": "No real Unilever stock count on or before the range's end."}
    head = batch.first(db, *idle_head_query(count_period))
    if not head or not head["products"]:
        has_count = _real_stock(db, "unilever", count_period) is not None
        reason = (None if has_count else f"No real Unilever stock count for {month_label(count_period)}.")
        return {**empty, "blocked_reason": reason or (
            f"Either no product in the {month_label(count_period)} count went 6 sales months without a sale, or "
            "the 6 months before it are not all in the sales file.")}
    items = batch.rows(db, *idle_items_query(count_period, limit))
    day = head["count_date"]
    return {
        "count_period": count_period,
        "count_date": day.isoformat() if hasattr(day, "isoformat") else day,
        "window_start": head["window_start"], "window_end": head["window_end"],
        "window_months": int(head["window_months"]),
        "products": int(head["products"]), "products_with_value": int(head["products_with_value"]),
        "pesos": round(float(head["pesos"]), 2) if head["pesos"] is not None else None,
        "pesos_basis": PESOS_BASIS_LABEL["last_purchase_price"],
        "never_sold": int(head["never_sold"]),
        "items": [
            {"product_key": int(r["product_key"]), "sku_id": r["sku_code"], "product_name": r["product_name"],
             "category_path": r["category_path"],
             "pesos": round(float(r["pesos"]), 2) if r["pesos"] is not None else None,
             "pieces": float(r["pieces"]) if r["pieces"] is not None else None,
             "cases": float(r["cases"]) if r["cases"] is not None else None,
             "last_sale_period": r["last_sale_period"], "never_sold": bool(r["never_sold"])}
            for r in items
        ],
        "blocked_reason": None,
    }


def idle_head_query(count_period: str) -> tuple[str, dict]:
    return """
        SELECT MIN(count_date) AS count_date, MIN(window_start) AS window_start, MIN(window_end) AS window_end,
               MIN(window_months) AS window_months, COUNT(*) AS products,
               COUNT(*) FILTER (WHERE pesos > 0) AS products_with_value, SUM(pesos) AS pesos,
               COUNT(*) FILTER (WHERE never_sold) AS never_sold
        FROM mart.idle_stock WHERE count_period = :period
    """, {"period": count_period}


def idle_items_query(count_period: str, limit: int | None = None) -> tuple[str, dict]:
    return f"""
        SELECT i.product_key, pd.sku_code, pd.product_name, pd.category_path, i.pesos, i.pieces, i.cases,
               i.last_sale_period, i.never_sold
        FROM mart.idle_stock i LEFT JOIN product_dimension pd ON pd.product_key = i.product_key
        WHERE i.count_period = :period
        ORDER BY i.pesos DESC NULLS LAST, i.product_key
        {'LIMIT :limit' if limit else ''}
    """, {"period": count_period, **({"limit": limit} if limit else {})}


# ---------------------------------------------------------------------------
# Forecast accuracy
# ---------------------------------------------------------------------------

# The backtest the error card shows by default: the at-the-time cohort, the figure the
# team quotes (decision 2026-10-03; scripts/backtest_forecast_run.py).
DEFAULT_BACKTEST_LABEL = "backtest 2023-10..2026-02, Tier A the month before each month"


def accuracy_runs(db: Session) -> list[dict]:
    rows = db.execute(text("""
        SELECT r.run_id, r.kind, r.label, r.cohort, r.window_start, r.window_end, r.created_at,
               r.source_generated_at, COUNT(v.*) AS rows
        FROM mart.forecast_run r LEFT JOIN mart.forecast_run_value v ON v.run_id = r.run_id
        GROUP BY r.run_id ORDER BY r.run_id
    """)).mappings().all()
    return [
        {"run_id": int(r["run_id"]), "forecast_source": r["kind"], "label": r["label"], "cohort": r["cohort"],
         "window_start": r["window_start"], "window_end": r["window_end"], "rows": int(r["rows"]),
         "default": r["label"] == DEFAULT_BACKTEST_LABEL}
        for r in rows
    ]


def accuracy_rows(db: Session, start: str, end: str, run_id: int | None = None) -> list[dict]:
    """Scored product-months (actual known) in start..end. With no run_id: each month from
    the default backtest when it covers the month, else from the newest stored run that
    forecast it — so the card never mixes two forecasts for one month."""
    return [dict(r) for r in batch.rows(db, *accuracy_rows_query(start, end, run_id))]


def accuracy_rows_query(start: str, end: str, run_id: int | None = None) -> tuple[str, dict]:
    if run_id is not None:
        return f"""
            SELECT a.*, pd.sku_code, pd.product_name
            FROM mart.accuracy_mart a LEFT JOIN product_dimension pd ON pd.product_key = a.product_key
            WHERE a.run_id = :run_id AND a.month BETWEEN :start AND :end AND a.actual_pieces IS NOT NULL
                  AND a.forecast_pieces IS NOT NULL
            ORDER BY a.product_key, a.month
        """, {"run_id": run_id, "start": start, "end": end}
    # The run_id each month resolves to (the default backtest when it covers the month,
    # else the newest stored run that forecast it) is the SAME for every row of that
    # month, so it is resolved ONCE per DISTINCT month in range here, not re-evaluated as
    # a correlated subplan per row of accuracy_mart (2026-10-11 recon: that subplan cost
    # ~90,500 of this query's ~91,000 total planner cost, re-running across every stored
    # run's rows in the month range because accuracy_mart_month's index is (run_id, month)
    # and the old WHERE had no run_id to seek on). month_run is bounded by the number of
    # months in the range (at most a few dozen), not by accuracy_mart's row count.
    return f"""
        WITH months AS (
            SELECT DISTINCT month FROM mart.accuracy_mart WHERE month BETWEEN :start AND :end
        ),
        month_run AS (
            SELECT m.month,
                   CASE WHEN EXISTS (SELECT 1 FROM mart.accuracy_mart b
                                     JOIN mart.forecast_run r ON r.run_id = b.run_id
                                     WHERE r.label = :default_label AND b.month = m.month)
                        THEN (SELECT run_id FROM mart.forecast_run WHERE label = :default_label)
                        ELSE (SELECT MAX(s.run_id) FROM mart.accuracy_mart s
                              WHERE s.forecast_source = 'stored_run' AND s.month = m.month
                                AND s.actual_pieces IS NOT NULL)
                   END AS run_id
            FROM months m
        )
        SELECT a.*, pd.sku_code, pd.product_name
        FROM mart.accuracy_mart a
        JOIN month_run mr ON mr.month = a.month AND mr.run_id = a.run_id
        LEFT JOIN product_dimension pd ON pd.product_key = a.product_key
        WHERE a.month BETWEEN :start AND :end AND a.actual_pieces IS NOT NULL
              AND a.forecast_pieces IS NOT NULL
        ORDER BY a.product_key, a.month
    """, {"default_label": DEFAULT_BACKTEST_LABEL, "start": start, "end": end}


def _wape(abs_miss: float, actual: float) -> float | None:
    return round(abs_miss / actual, 6) if actual > 0 else None


def _num(row: dict, key: str) -> float | None:
    return float(row[key]) if row.get(key) is not None else None


# The over-forecast half of DEC-33's review rule, applied to the selected range: a product
# over-forecast `review_months` (REVIEW_OVER_RUN_MONTHS) months or more in a row as of its last
# scored month in the range. The plan's own flag for the cycle is review_flag (GET /recommendations).
# The two headline error figures, always returned together and always under these names
# (Yuan, 2026-10-05): the same forecasts read 9.9% or 29.6% on the default backtest depending
# on which is meant, so neither is ever called just "the total" or "the accuracy".
ACCURACY_LABELS = {
    "company_total": (
        "Company total: every product's forecast and sales are added up first, month by month, then "
        "compared in pesos. Misses on different products cancel out, so this is the smaller figure."),
    "typical_product_weighted": (
        "Typical product, weighted by sales: each product's own miss in pieces, with bigger sellers "
        "counting more. Nothing cancels out, so this is what a planner sees product by product."),
}


def accuracy_headlines(company_total: float | None, typical_product_weighted: float | None) -> dict:
    """Both headline figures with their plain labels; value is a share of sales (0.099 = 9.9%)."""
    return {
        "company_total": {
            "value": company_total, "label": ACCURACY_LABELS["company_total"],
            "measure": "sum over months of |forecast pesos - actual pesos| / actual pesos",
            "unit": "pesos at selling price, VAT-inclusive"},
        "typical_product_weighted": {
            "value": typical_product_weighted, "label": ACCURACY_LABELS["typical_product_weighted"],
            "measure": "sum over product-months of |forecast - actual| / actual",
            "unit": "pieces"},
    }


OVER_RUN_RULE = ("over-forecast {n}+ months in a row as of the product's last scored month in the range "
                 "(the over-forecast part of DEC-33, on this range's forecasts)")


def accuracy_summary(rows: list[dict], start: str, end: str, review_months: int, review_limit: int = 20) -> dict:
    """The forecast-error card for the scored rows of a range (accuracy_rows): pieces and
    pesos (selling price, VAT-inclusive), surplus against shortage, each month's direction
    (the colour chips), and the products to review before ordering: over-forecast
    `review_months` months or more in a row as of their last scored month in the range."""
    if not rows:
        return {"start_period": start, "end_period": end, "label": None, "months": [], "forecast_source": None,
                "run_labels": [], "products": 0, "product_months": 0, "by_month": [],
                **accuracy_headlines(None, None),
                "over_forecast_runs": {"run_months": review_months, "count": 0, "items": [], "rule": OVER_RUN_RULE.format(n=review_months)},
                "blocked_reason": (f"No scored forecasts for {range_label(start, end)}: no forecast "
                                   "with a real actual in these months.")}
    by_month: dict[str, dict] = {}
    by_product: dict[int, dict] = {}
    for r in rows:
        fc, act = float(r["forecast_pieces"]), float(r["actual_pieces"])
        m = by_month.setdefault(r["month"], {
            "period": r["month"], "products": 0, "forecast_pieces": 0.0, "actual_pieces": 0.0,
            "net_miss_pieces": 0.0, "abs_miss_pieces": 0.0, "net_miss_pesos": 0.0, "abs_miss_pesos": 0.0,
            "surplus_pesos": 0.0, "shortage_pesos": 0.0, "actual_pesos": 0.0, "sources": set()})
        m["products"] += 1
        m["forecast_pieces"] += fc
        m["actual_pieces"] += act
        m["net_miss_pieces"] += fc - act
        m["abs_miss_pieces"] += abs(fc - act)
        m["sources"].add(r["forecast_source"])
        price = _num(r, "price_per_piece")
        if price is not None:
            m["net_miss_pesos"] += (fc - act) * price
            m["abs_miss_pesos"] += abs(fc - act) * price
            m["surplus_pesos"] += max(fc - act, 0.0) * price
            m["shortage_pesos"] += max(act - fc, 0.0) * price
            m["actual_pesos"] += act * price
        p = by_product.setdefault(int(r["product_key"]), {"abs": 0.0, "act": 0.0, "last": None, "priced": False})
        p["abs"] += abs(fc - act)
        p["act"] += abs(act)
        p["priced"] = p["priced"] or price is not None
        p["last"] = r  # rows arrive ordered by product, then month
    months = sorted(by_month)
    keys = ("forecast_pieces", "actual_pieces", "net_miss_pieces", "abs_miss_pieces", "net_miss_pesos",
            "abs_miss_pesos", "surplus_pesos", "shortage_pesos", "actual_pesos")
    totals = {k: sum(by_month[mo][k] for mo in months) for k in keys}
    wapes = sorted(v["abs"] / v["act"] for v in by_product.values() if v["act"] > 0)
    median = None
    if wapes:
        n = len(wapes)
        median = wapes[n // 2] if n % 2 else (wapes[n // 2 - 1] + wapes[n // 2]) / 2
    review = []
    for key, v in by_product.items():
        last = v["last"]
        if last["direction"] == "over" and (last["run_length"] or 0) >= review_months:
            price = _num(last, "price_per_piece")
            miss = float(last["miss_pieces"])
            review.append({
                "product_key": key, "sku_id": last.get("sku_code"), "product_name": last.get("product_name"),
                "run_length": int(last["run_length"]), "last_month": last["month"],
                "surplus_pieces": round(miss, 2),
                "surplus_pesos": round(miss * price, 2) if price is not None else None,
                "possibly_stock_limited": last.get("possibly_stock_limited"),
            })
    review.sort(key=lambda it: -(it["surplus_pesos"] or 0))
    month_rows = []
    for mo in months:
        m = by_month[mo]
        net = m["net_miss_pieces"]
        month_rows.append({
            **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items() if k != "sources"},
            "direction": "over" if net > 0 else "under" if net < 0 else "exact",
            "forecast_source": "/".join(sorted(m["sources"])),
            "wape_pieces": _wape(m["abs_miss_pieces"], m["actual_pieces"]),
        })
    net = totals["net_miss_pieces"]
    pooled_wape = _wape(totals["abs_miss_pieces"], totals["actual_pieces"])
    month_total_wape = _wape(sum(abs(by_month[mo]["net_miss_pesos"]) for mo in months), totals["actual_pesos"])
    return {
        "start_period": start, "end_period": end, "label": range_label(months[0], months[-1]), "months": months,
        "forecast_source": "/".join(sorted({r["forecast_source"] for r in rows})),
        "run_labels": sorted({r["run_label"] for r in rows}),
        "products": len(by_product), "product_months": len(rows),
        **{k: round(v, 2) for k, v in totals.items()},
        "direction": "over" if net > 0 else "under" if net < 0 else "exact",
        # Pooled over every product-month; the median of each product's own; and the miss
        # of each month's total (over- and under-forecasts cancel inside a month).
        # company_total / typical_product_weighted are the labelled pair to show; wape_pieces
        # and total_wape_pesos are the same two numbers under their older names.
        **accuracy_headlines(month_total_wape, pooled_wape),
        "wape_pieces": pooled_wape,
        "median_product_wape": round(median, 6) if median is not None else None,
        "total_wape_pesos": month_total_wape,
        "surplus_share_of_miss_pesos": (round(totals["surplus_pesos"] / totals["abs_miss_pesos"], 6)
                                        if totals["abs_miss_pesos"] > 0 else None),
        "pesos_basis": "selling price, VAT-inclusive (each product's average over its scored months in the run)",
        "products_without_price": sum(1 for v in by_product.values() if not v["priced"]),
        "possibly_stock_limited": sum(1 for r in rows if r.get("possibly_stock_limited") is True),
        "possibly_stock_limited_unknown": sum(1 for r in rows if r["direction"] == "over"
                                              and r.get("possibly_stock_limited") is None),
        "by_month": month_rows,
        "over_forecast_runs": {"run_months": review_months, "count": len(review), "items": review[:review_limit],
                               "rule": OVER_RUN_RULE.format(n=review_months)},
        "blocked_reason": None,
    }


def accuracy_by_category(rows: list[dict]) -> list[dict]:
    """The same scored rows summed per product category, pieces and pesos."""
    cats: dict[str, dict] = {}
    for r in rows:
        name = r.get("category_path") or "UNCLASSIFIED"
        c = cats.setdefault(name, {"category_path": name, "keys": set(), "product_months": 0,
                                   "forecast_pieces": 0.0, "actual_pieces": 0.0, "net_miss_pieces": 0.0,
                                   "abs_miss_pieces": 0.0, "surplus_pesos": 0.0, "shortage_pesos": 0.0})
        fc, act = float(r["forecast_pieces"]), float(r["actual_pieces"])
        c["keys"].add(r["product_key"])
        c["product_months"] += 1
        c["forecast_pieces"] += fc
        c["actual_pieces"] += act
        c["net_miss_pieces"] += fc - act
        c["abs_miss_pieces"] += abs(fc - act)
        price = _num(r, "price_per_piece")
        if price is not None:
            c["surplus_pesos"] += max(fc - act, 0.0) * price
            c["shortage_pesos"] += max(act - fc, 0.0) * price
    out = [{**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items() if k != "keys"},
            "products": len(c["keys"]), "wape_pieces": _wape(c["abs_miss_pieces"], c["actual_pieces"])}
           for c in cats.values()]
    return sorted(out, key=lambda c: -(c["surplus_pesos"] + c["shortage_pesos"]))
