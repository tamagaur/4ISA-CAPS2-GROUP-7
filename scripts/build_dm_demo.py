"""
scripts/build_dm_demo.py — build the labelled Del Monte demonstration series, parameters and forecast
into schema `demo` (migration 0052). CLAUDE.md hard rule 2, approved by Kelvin 2026-10-15.

    python -m scripts.build_dm_demo               # compute + report, write nothing (default)
    python -m scripts.build_dm_demo --write       # insert one demo.run and its rows (needs 0052 applied)
    python -m scripts.build_dm_demo --write --replace   # replace the run with the same label

READS (one read-only transaction, SET TRANSACTION READ ONLY, rolled back; the direct URL, since this is a
long read — analytics.config.long_read_db_url):
  SellOut_Fact_Real        real Del Monte category sales (the _Real view; never the base table)
  Unilever_SKU_Demand_Fact_Real + Product_Dimension.unit_cost   the cost-to-price ratio
  Product_Dimension        lead_time_days / lead_time_source, COPIED
WRITES (only with --write): demo.run, demo.dm_category_sales, demo.dm_category_param, demo.dm_forecast,
  demo.dm_excluded. Nothing in public. Unilever is not built: its gaps are real zero-sale months.

Method: analytics/demo/dm_interpolate.py (between two real months, seeded jitter from the series' own CV, no
extrapolation, MA3 minimum). Window: per category, its own real span, capped at 2025-12 (real Del Monte sales
end there); the forecast is the one month after it, 2026-01. The demonstration never calls evaluate_sku or
backtest and stores no error metric.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analytics.config import long_read_db_url  # noqa: E402
from analytics.demo.dm_interpolate import (  # noqa: E402
    GENERATOR_VERSION, JITTER_SCALE, MIN_MONTHS, SEED, fill_series, ma3_one_step, next_month,
)

LABEL = "demonstration"
WINDOW_END = "2025-12"
APPROVED_BY, APPROVED_ON = "Kelvin", "2026-10-15"

SELLOUT_SQL = """
    SELECT category_path, MIN(product_key), _period, SUM(quantity), SUM(net_amount)
    FROM SellOut_Fact_Real
    WHERE _period <= %s
    GROUP BY category_path, _period
"""
COST_RATIO_SQL = """
    WITH px AS (
        SELECT product_key, SUM(net_amount) / NULLIF(SUM(quantity_sold), 0) AS price
        FROM Unilever_SKU_Demand_Fact_Real WHERE quantity_sold > 0 AND net_amount > 0 GROUP BY product_key),
    r AS (
        SELECT p.unit_cost / px.price AS ratio
        FROM Product_Dimension p JOIN px USING (product_key)
        WHERE p.principal = 'unilever' AND p.unit_cost > 0 AND px.price > 0)
    SELECT COUNT(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY ratio) FROM r
"""
LEAD_SQL = """
    SELECT product_key, lead_time_days, lead_time_source FROM Product_Dimension
    WHERE principal = 'delmonte' AND grain = 'category'
"""


def read_inputs(db_url: str):
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SHOW transaction_read_only")
        assert cur.fetchone()[0] == "on", "read transaction is not read-only"
        cur.execute(SELLOUT_SQL, (WINDOW_END,))
        sales = cur.fetchall()
        cur.execute(COST_RATIO_SQL)
        n_ratio, ratio = cur.fetchone()
        cur.execute(LEAD_SQL)
        lead = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        cur.execute("ROLLBACK")
    finally:
        conn.close()
    return sales, int(n_ratio), float(ratio), lead


def build(sales, ratio: float, n_ratio: int, lead: dict):
    qty: dict[str, dict[str, float]] = defaultdict(dict)
    amt: dict[str, dict[str, float | None]] = defaultdict(dict)
    pkey: dict[str, int] = {}
    for cat, pk, period, q, a in sales:
        qty[cat][period] = float(q) if q is not None else None
        amt[cat][period] = float(a) if a is not None else None
        pkey[cat] = pk
    results = {c: fill_series(c, qty[c], amt[c], SEED, WINDOW_END) for c in sorted(qty)}
    series, params, forecasts, excluded = [], [], [], []
    for c, r in results.items():
        if r.excluded_reason:
            excluded.append((c, r.excluded_reason, r.real_months, r.first_real, r.last_real))
            continue
        series += [(c, pkey[c], p.period, p.quantity, p.net_amount, p.origin) for p in r.points]
        real_q = {p.period: p.quantity for p in r.points if p.origin == "real_copy"}
        real_pairs = [(p.net_amount, p.quantity) for p in r.points
                      if p.origin == "real_copy" and p.net_amount and p.quantity and p.net_amount > 0 and p.quantity > 0]
        price = (sum(a for a, _ in real_pairs) / sum(q for _, q in real_pairs)) if real_pairs else None
        cost = None if price is None else price * ratio
        days, src = lead.get(pkey[c], (None, None))
        active = r.last_real == WINDOW_END
        params.append((c, pkey[c], None if price is None else round(price, 4), None if cost is None else round(cost, 4),
                       days, src, r.first_real, r.last_real, r.real_months, r.interpolated_months,
                       "ok" if active else "series_ended_before_window_end"))
        if active:
            vals = [p.quantity for p in r.points]
            last3 = r.points[-3:]
            forecasts.append((c, pkey[c], next_month(WINDOW_END), round(ma3_one_step(vals), 2), "ma3", len(r.points),
                              sum(1 for p in last3 if p.origin == "interpolated")))
    return results, series, params, forecasts, excluded


def digest(series) -> str:
    h = hashlib.sha256()
    for row in sorted(series, key=lambda r: (r[0], r[2])):
        h.update(repr(row).encode("utf-8"))
    return h.hexdigest()


def report(results, series, params, forecasts, excluded, ratio, n_ratio) -> dict:
    ok = {c: r for c, r in results.items() if not r.excluded_reason}
    fills = [f for r in ok.values() for f in r.fills]
    runs = sorted(f.anchoring_run for f in fills)
    rep = {
        "principal": "delmonte",
        "categories_in_real_view": len(results), "categories_covered": len(ok), "categories_excluded": len(excluded),
        "months_real": sum(r.real_months for r in ok.values()),
        "months_interpolated": sum(r.interpolated_months for r in ok.values()),
        "fill_blocks": len(fills),
        "anchoring_real_run_longest": max(runs) if runs else None,
        "anchoring_real_run_median": statistics.median(runs) if runs else None,
        "anchoring_real_run_shortest": min(runs) if runs else None,
        "forecast_rows": len(forecasts),
        "series_ended_before_window_end": sum(1 for p in params if p[-1] != "ok"),
        "excluded": [{"category": c, "reason": why, "real_months": n} for c, why, n, _, _ in excluded],
        "cost_ratio": round(ratio, 6), "cost_ratio_n_products": n_ratio,
        "digest": digest(series),
        "unilever": {"covered": 0, "reason": "excluded by decision 2026-10-15: gaps are real zero-sale months"},
    }
    return rep


def write(db_url: str, rep: dict, series, params, forecasts, excluded, replace: bool) -> int:
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("SHOW default_transaction_read_only")
        if cur.fetchone()[0] != "off":
            raise SystemExit("default_transaction_read_only is on for this connection; refusing to write")
        cur.execute("SELECT to_regclass('demo.run')")
        if cur.fetchone()[0] is None:
            raise SystemExit("schema demo is not there: apply migration 0052 first")
        cur.execute("SELECT run_id FROM demo.run WHERE label = %s", (LABEL,))
        old = cur.fetchone()
        if old and not replace:
            raise SystemExit(f"run {LABEL!r} exists (run_id {old[0]}); pass --replace")
        if old:
            cur.execute("DELETE FROM demo.run WHERE run_id = %s", (old[0],))
        source = (f"median over {rep['cost_ratio_n_products']} Unilever products of Product_Dimension.unit_cost "
                  "(latest inventory_fact_real unit_cost_per_case / pack_size, migration 0045) divided by the product's "
                  "real SUM(net_amount)/SUM(quantity_sold) over Unilever_SKU_Demand_Fact_Real (months with both > 0). "
                  "VAT basis of the two sides is not confirmed (UNVERIFIED).")
        cur.execute(
            """INSERT INTO demo.run (label, principal, seed, generator_version, jitter_scale, window_end, forecast_target,
                                     cost_ratio, cost_ratio_source, approved_by, approved_on, notes)
               VALUES (%s,'delmonte',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING run_id""",
            (LABEL, SEED, GENERATOR_VERSION, JITTER_SCALE, WINDOW_END, next_month(WINDOW_END), rep["cost_ratio"],
             source, APPROVED_BY, APPROVED_ON, json.dumps({k: v for k, v in rep.items() if k != "unilever"} |
                                                          {"unilever": rep["unilever"]})),
        )
        run_id = cur.fetchone()[0]
        execute_values(cur, "INSERT INTO demo.dm_category_sales (run_id, category_path, product_key, period, quantity, "
                            "net_amount, origin) VALUES %s", [(run_id, *r) for r in series], page_size=500)
        execute_values(cur, "INSERT INTO demo.dm_category_param (run_id, category_path, product_key, unit_price, unit_cost, "
                            "lead_time_days, lead_time_source, first_real_period, last_real_period, real_months, "
                            "interpolated_months, forecast_status) VALUES %s", [(run_id, *r) for r in params])
        if forecasts:
            execute_values(cur, "INSERT INTO demo.dm_forecast (run_id, category_path, product_key, forecast_period, "
                                "forecast_quantity, method, history_months, interpolated_in_window) VALUES %s",
                           [(run_id, *r) for r in forecasts])
        if excluded:
            execute_values(cur, "INSERT INTO demo.dm_excluded (run_id, category_path, reason, real_months, "
                                "first_real_period, last_real_period) VALUES %s", [(run_id, *r) for r in excluded])
        conn.commit()
        return run_id
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()
    db_url = long_read_db_url()
    sales, n_ratio, ratio, lead = read_inputs(db_url)
    results, series, params, forecasts, excluded = build(sales, ratio, n_ratio, lead)
    rep = report(results, series, params, forecasts, excluded, ratio, n_ratio)
    print(json.dumps(rep, indent=1, default=str))
    if args.write:
        print("[write] demo.run", write(db_url, rep, series, params, forecasts, excluded, args.replace))
    else:
        print("[dry] nothing written (pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
