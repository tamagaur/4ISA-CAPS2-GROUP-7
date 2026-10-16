"""
scripts/build_unilever_demo.py — Unilever's side of the labelled demonstration: real months copied at SKU grain,
the 2021-01..2022-12 back-cast, and a one-step MA3 forecast per SKU, into schema `demo` (migrations 0052, 0053,
0056). CLAUDE.md hard rule 2.

    python -m scripts.build_unilever_demo               # compute + report, write nothing (default)
    python -m scripts.build_unilever_demo --write [--replace]

WHAT IT DOES NOT DO: it does not fill Unilever's in-span gaps. A month with no row is a real zero-sale month and is
rendered as 0 by the API (backend/series_gaps.py), never generated. The only generated Unilever months are the
2021-2022 back-cast, origin 'backcast', for SKUs whose first real month is 2023-01 and that have >= 3 months with
sales (analytics/demo/backcast.py).

FORECAST (migration 0056, Kelvin 2026-10-16): the SAME one-step MA3 the Del Monte side uses
(analytics.demo.dm_interpolate.ma3_one_step), over each SKU's last 3 months up to its own last real month,
real-zero-filled in-span the same way backend/series_gaps.unilever_points does for the API. A SKU whose window has
fewer than 3 months is named and left out. A SINGLE blank-capture month (quantity NULL) inside the window
(Kelvin, 2026-10-16) is filled for the forecast only — the mean of the window's other two months — flagged
blank_capture_filled (migration 0057); the chart itself never shows it filled (demo.unilever_sku_sales is
untouched: a blank capture is "not zero, no value shown", not a gap to generate into). Two or more blanks in the
window still leave the SKU excluded. Reading only real_copy (plus real in-span zeros) months means this forecast
is expected to be close to the real Forecast_Result for the same SKU; build_dm_demo.py's report compares them.
Not wired into any endpoint: Unilever's real forecast already exists and nothing here replaces it.

SCOPE (Kelvin, 2026-10-16): pinned to Tier A as of the current cycle, the same set and basis the real path uses
(scripts/run_baseline_forecast.py:162-176 fetch_tier_a, analytics.params.abc_method) — this demo shows the real
system working with complete data, not a wider-scope system. A product that drops in/out of Tier A between
cycles is picked up the next time this is rerun; it does not track a frozen cohort.

READS: Unilever_SKU_Demand_Fact_Real joined to ABC_Classification (Tier A only) (one read-only transaction,
direct URL). WRITES (--write): demo.run (one run per principal, label 'demonstration_unilever'),
demo.unilever_sku_sales, demo.backcast_excluded, demo.unilever_sku_forecast.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analytics.config import long_read_db_url  # noqa: E402
from analytics.demo.backcast import backcast_series  # noqa: E402
from analytics.demo.dm_interpolate import GENERATOR_VERSION, JITTER_SCALE, SEED, ma3_one_step, next_month  # noqa: E402
from analytics.params import abc_method  # noqa: E402
from backend.series_gaps import unilever_points  # noqa: E402

LABEL = "demonstration_unilever"
APPROVED_BY, APPROVED_ON = "Kelvin", "2026-10-15"
PRINCIPAL = "unilever"

# Tier A scope (Kelvin, 2026-10-16): the real path (scripts/run_baseline_forecast.py:162-176 fetch_tier_a) only
# ever forecasts the ~189 Unilever Tier A SKUs. This demo exists to show that same system working with complete
# data, not a wider-scope system, so it is pinned to the same ABC_Classification tier='A' set at the same
# latest-usable classification_period (<= the real view's own max month), via analytics.params.abc_method().
ABC_PERIOD_SQL = """
    SELECT MAX(classification_period) FROM ABC_Classification
    WHERE principal = %s AND method = %s
      AND classification_period <= (SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real)
"""

SQL = """
    SELECT f.product_key, f.sku_code, f.calendar_month,
           CASE WHEN COUNT(*) FILTER (WHERE f.quantity_sold IS NULL) > 0 THEN NULL ELSE SUM(f.quantity_sold) END,
           SUM(f.net_amount)
    FROM Unilever_SKU_Demand_Fact_Real f
    JOIN ABC_Classification abc ON abc.product_key = f.product_key
        AND abc.principal = %s AND abc.method = %s AND abc.classification_period = %s AND abc.tier = 'A'
    GROUP BY f.product_key, f.sku_code, f.calendar_month
"""


def read_inputs(db_url: str):
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SHOW transaction_read_only")
        assert cur.fetchone()[0] == "on"
        cur.execute(ABC_PERIOD_SQL, (PRINCIPAL, abc_method(PRINCIPAL)))
        row = cur.fetchone()
        if not row or row[0] is None:
            raise SystemExit("No usable Tier A classification_period found for Unilever.")
        abc_period = row[0]
        cur.execute(SQL, (PRINCIPAL, abc_method(PRINCIPAL), abc_period))
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
    series, excluded, forecasts, forecast_excluded = [], [], [], []
    for pk in sorted(qty):
        for month in sorted(qty[pk]):
            series.append((pk, sku[pk], month, qty[pk][month], amt[pk][month], "real_copy"))
        bc = backcast_series(sku[pk], qty[pk], amt[pk], zero_months_in_span=True)
        if bc.excluded_reason:
            excluded.append((sku[pk], bc.excluded_reason, bc.real_months, bc.first_real))
        else:
            series += [(pk, sku[pk], p, q, a, "backcast") for p, q, a in bc.points]
        # One-step MA3 over the real series only (real_copy + real zeros in-span), the same window the API renders
        # (backend/series_gaps.unilever_points): last 3 months up to this SKU's own last real month.
        last3 = unilever_points(qty[pk])[-3:]
        if len(last3) < 3:
            forecast_excluded.append((sku[pk], f"{len(last3)} real month(s); 3 needed for MA3", len(last3)))
            continue
        quantities = [p["quantity"] for p in last3]
        blanks = [i for i, q in enumerate(quantities) if q is None]
        blank_filled = False
        if len(blanks) == 1:
            # One blank-capture month in the averaging window (Kelvin, 2026-10-16): filled for THIS FORECAST ONLY,
            # as the mean of the window's other two real/zero months — never written back to demo.unilever_sku_sales,
            # so the chart still shows it blank (REASON_BLANK_CAPTURE: "not zero, no value is shown or filled in").
            others = [q for i, q in enumerate(quantities) if i != blanks[0]]
            quantities[blanks[0]] = statistics.fmean(others)
            blank_filled = True
        elif blanks:
            forecast_excluded.append((sku[pk], "more than one blank-capture month in the last 3 real months",
                                      len(last3)))
            continue
        last_period = last3[-1]["period"]
        forecasts.append((pk, sku[pk], next_month(last_period), round(ma3_one_step(quantities), 2), "ma3",
                          len(last3), blank_filled))
    return series, excluded, forecasts, forecast_excluded


def report(series, excluded, forecasts, forecast_excluded, n_products) -> dict:
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
        "forecast_rows": len(forecasts), "forecast_excluded": len(forecast_excluded),
        "forecast_blank_filled": sum(1 for r in forecasts if r[6]),
        "forecast_excluded_by_reason": dict(Counter(r for _, r, _ in forecast_excluded)),
        "forecast_note": ("one-step MA3 over each SKU's own last 3 real months (real_copy + real in-span zeros, "
                          "one blank-capture month filled for this average only); not wired into any endpoint, "
                          "Unilever's real Forecast_Result is unaffected"),
        "digest": h.hexdigest(),
    }


def write(db_url: str, rep: dict, series, excluded, forecasts, replace: bool) -> int:
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("SHOW default_transaction_read_only")
        if cur.fetchone()[0] != "off":
            raise SystemExit("default_transaction_read_only is on; refusing to write")
        cur.execute("SELECT to_regclass('demo.unilever_sku_forecast')")
        if cur.fetchone()[0] is None:
            raise SystemExit("demo.unilever_sku_forecast is not there: apply migration 0056 first")
        cur.execute("SELECT run_id FROM demo.run WHERE label = %s", (LABEL,))
        old = cur.fetchone()
        if old and not replace:
            raise SystemExit(f"run {LABEL!r} exists (run_id {old[0]}); pass --replace")
        if old:
            cur.execute("DELETE FROM demo.run WHERE run_id = %s", (old[0],))
        forecast_target = max(r[2] for r in forecasts) if forecasts else "n/a"
        cur.execute(
            """INSERT INTO demo.run (label, principal, seed, generator_version, jitter_scale, window_end, forecast_target,
                                     cost_ratio, cost_ratio_source, approved_by, approved_on, notes)
               VALUES (%s,'unilever',%s,%s,%s,'2026-02',%s,0,'not used: Unilever cost is never generated',%s,%s,%s)
               RETURNING run_id""",
            (LABEL, SEED, GENERATOR_VERSION, JITTER_SCALE, forecast_target, APPROVED_BY, APPROVED_ON, json.dumps(rep)),
        )
        run_id = cur.fetchone()[0]
        execute_values(cur, "INSERT INTO demo.unilever_sku_sales (run_id, product_key, sku_code, period, quantity, net_amount, "
                            "origin) VALUES %s", [(run_id, *r) for r in series], page_size=1000)
        if excluded:
            execute_values(cur, "INSERT INTO demo.backcast_excluded (run_id, series_key, reason, real_months, "
                                "first_real_period) VALUES %s", [(run_id, *r) for r in excluded], page_size=1000)
        if forecasts:
            execute_values(cur, "INSERT INTO demo.unilever_sku_forecast (run_id, product_key, sku_code, forecast_period, "
                                "forecast_quantity, method, history_months, blank_capture_filled) VALUES %s",
                           [(run_id, *r) for r in forecasts], page_size=1000)
        conn.commit()
        return run_id
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def compare_to_real_forecast(db_url: str, forecasts) -> dict:
    """How close the demo forecast is to the real one for the same SKU (Kelvin, 2026-10-16: 'report the actual
    difference rather than assuming it'). Reads Forecast_Result (real path; only run_baseline_forecast's real
    writes ever touch it) at each product's own latest forecast_date; does not write anything.

    Forecast_Result only has a row for the ~189 Tier A SKUs (analytics.params.abc_method), and the real deployed
    choice is per-SKU, not always MA3 (2026-09-21 routing: short-lived SKUs get MA3, medium TSB, long an
    XGBoost+MA3 average — model_params.method says which). This demo always uses plain MA3, so the two are only
    expected to be close where the real row ALSO used 'ma3'; split the comparison by that so a routing difference
    is not misread as a demo-generation bug."""
    if not forecasts:
        return {"compared": 0}
    import statistics as _stats

    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(
            "SELECT DISTINCT ON (product_key) product_key, forecast_date, forecast_value, model_params "
            "FROM Forecast_Result ORDER BY product_key, forecast_date DESC"
        )
        real = {pk: (fd.isoformat()[:7], float(fv), (mp or {}).get("method") if isinstance(mp, dict) else None)
                for pk, fd, fv, mp in cur.fetchall()}
        cur.execute("ROLLBACK")
    finally:
        conn.close()

    buckets: dict[str, list[tuple[float, float, bool]]] = {"ma3": [], "other_method": []}
    for pk, _sku, period, qty, _m, _h, _bf in forecasts:
        if pk not in real:
            continue
        real_period, real_value, real_method = real[pk]
        bucket = "ma3" if real_method == "ma3" else "other_method"
        buckets[bucket].append((qty, real_value, real_period == period))

    def summarize(rows):
        if not rows:
            return {"compared": 0}
        diffs = [abs(q - v) for q, v, _ in rows]
        pct = [abs(q - v) / abs(v) * 100 for q, v, _ in rows if v]
        return {
            "compared": len(rows), "same_forecast_period": sum(1 for *_, sp in rows if sp),
            "median_abs_diff": round(_stats.median(diffs), 4), "max_abs_diff": round(max(diffs), 4),
            "median_pct_diff": round(_stats.median(pct), 4) if pct else None,
        }

    return {"vs_real_ma3_rows": summarize(buckets["ma3"]), "vs_real_other_method_rows": summarize(buckets["other_method"])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()
    db_url = long_read_db_url()
    rows = read_inputs(db_url)
    series, excluded, forecasts, forecast_excluded = build(rows)
    rep = report(series, excluded, forecasts, forecast_excluded, len({r[0] for r in rows}))
    rep["vs_real_forecast_result"] = compare_to_real_forecast(db_url, forecasts)
    print(json.dumps(rep, indent=1))
    if args.write:
        print("[write] demo.run", write(db_url, rep, series, excluded, forecasts, args.replace))
    else:
        print("[dry] nothing written (pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
