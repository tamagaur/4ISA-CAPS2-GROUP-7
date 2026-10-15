"""
scripts/build_unilever_demo.py — Unilever's side of the labelled demonstration: real months copied at SKU grain and
the 2021-01..2022-12 back-cast, into schema `demo` (migrations 0052, 0053). CLAUDE.md hard rule 2.

    python -m scripts.build_unilever_demo               # compute + report, write nothing (default)
    python -m scripts.build_unilever_demo --write [--replace]

WHAT IT DOES NOT DO: it does not fill Unilever's in-span gaps. A month with no row is a real zero-sale month and is
rendered as 0 by the API (backend/series_gaps.py), never generated. The only generated Unilever months are the
2021-2022 back-cast, origin 'backcast', for SKUs whose first real month is 2023-01 and that have >= 3 months with
sales (analytics/demo/backcast.py).

READS: Unilever_SKU_Demand_Fact_Real only (one read-only transaction, direct URL). WRITES (--write): demo.run (one
run per principal, label 'demonstration_unilever'), demo.unilever_sku_sales, demo.backcast_excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analytics.config import long_read_db_url  # noqa: E402
from analytics.demo.backcast import backcast_series  # noqa: E402
from analytics.demo.dm_interpolate import GENERATOR_VERSION, JITTER_SCALE, SEED  # noqa: E402

LABEL = "demonstration_unilever"
APPROVED_BY, APPROVED_ON = "Kelvin", "2026-10-15"

SQL = """
    SELECT product_key, sku_code, calendar_month,
           CASE WHEN COUNT(*) FILTER (WHERE quantity_sold IS NULL) > 0 THEN NULL ELSE SUM(quantity_sold) END,
           SUM(net_amount)
    FROM Unilever_SKU_Demand_Fact_Real GROUP BY product_key, sku_code, calendar_month
"""


def read_inputs(db_url: str):
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SHOW transaction_read_only")
        assert cur.fetchone()[0] == "on"
        cur.execute(SQL)
        rows = cur.fetchall()
        cur.execute("ROLLBACK")
    finally:
        conn.close()
    return rows


def build(rows):
    qty: dict[int, dict] = defaultdict(dict)
    amt: dict[int, dict] = defaultdict(dict)
    sku: dict[int, str] = {}
    for pk, code, month, q, a in rows:
        qty[pk][month] = None if q is None else float(q)
        amt[pk][month] = None if a is None else float(a)
        sku[pk] = code
    series, excluded = [], []
    for pk in sorted(qty):
        for month in sorted(qty[pk]):
            series.append((pk, sku[pk], month, qty[pk][month], amt[pk][month], "real_copy"))
        bc = backcast_series(sku[pk], qty[pk], amt[pk], zero_months_in_span=True)
        if bc.excluded_reason:
            excluded.append((sku[pk], bc.excluded_reason, bc.real_months, bc.first_real))
        else:
            series += [(pk, sku[pk], p, q, a, "backcast") for p, q, a in bc.points]
    return series, excluded


def report(series, excluded, n_products) -> dict:
    by_reason = Counter(r.split(":")[0] if r.startswith("first real month") else r for _, r, _, _ in excluded)
    h = hashlib.sha256()
    for row in sorted(series, key=lambda r: (r[0], r[2])):
        h.update(repr(row).encode("utf-8"))
    return {
        "principal": "unilever", "grain": "sku", "skus_in_real_view": n_products,
        "skus_backcast": len({r[0] for r in series if r[5] == "backcast"}),
        "months_real": sum(1 for r in series if r[5] == "real_copy"),
        "months_interpolated": 0,  # in-span gaps are real zero-sale months: never filled
        "months_bridged": 0,
        "months_backcast": sum(1 for r in series if r[5] == "backcast"),
        "backcast_excluded": len(excluded),
        "backcast_excluded_by_reason": {("first real month after 2023-01" if k.startswith("first real month") else k): v
                                        for k, v in Counter(
                                            "first real month after 2023-01" if r.startswith("first real month") else r
                                            for _, r, _, _ in excluded).items()},
        "digest": h.hexdigest(),
    }


def write(db_url: str, rep: dict, series, excluded, replace: bool) -> int:
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("SHOW default_transaction_read_only")
        if cur.fetchone()[0] != "off":
            raise SystemExit("default_transaction_read_only is on; refusing to write")
        cur.execute("SELECT to_regclass('demo.unilever_sku_sales')")
        if cur.fetchone()[0] is None:
            raise SystemExit("demo.unilever_sku_sales is not there: apply migration 0053 first")
        cur.execute("SELECT run_id FROM demo.run WHERE label = %s", (LABEL,))
        old = cur.fetchone()
        if old and not replace:
            raise SystemExit(f"run {LABEL!r} exists (run_id {old[0]}); pass --replace")
        if old:
            cur.execute("DELETE FROM demo.run WHERE run_id = %s", (old[0],))
        cur.execute(
            """INSERT INTO demo.run (label, principal, seed, generator_version, jitter_scale, window_end, forecast_target,
                                     cost_ratio, cost_ratio_source, approved_by, approved_on, notes)
               VALUES (%s,'unilever',%s,%s,%s,'2026-02','n/a',0,'not used: no cost or forecast is built for Unilever',%s,%s,%s)
               RETURNING run_id""",
            (LABEL, SEED, GENERATOR_VERSION, JITTER_SCALE, APPROVED_BY, APPROVED_ON, json.dumps(rep)),
        )
        run_id = cur.fetchone()[0]
        execute_values(cur, "INSERT INTO demo.unilever_sku_sales (run_id, product_key, sku_code, period, quantity, net_amount, "
                            "origin) VALUES %s", [(run_id, *r) for r in series], page_size=1000)
        if excluded:
            execute_values(cur, "INSERT INTO demo.backcast_excluded (run_id, series_key, reason, real_months, "
                                "first_real_period) VALUES %s", [(run_id, *r) for r in excluded], page_size=1000)
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
    rows = read_inputs(db_url)
    series, excluded = build(rows)
    rep = report(series, excluded, len({r[0] for r in rows}))
    print(json.dumps(rep, indent=1))
    if args.write:
        print("[write] demo.run", write(db_url, rep, series, excluded, args.replace))
    else:
        print("[dry] nothing written (pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
