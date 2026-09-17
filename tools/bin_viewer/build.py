"""
tools/bin_viewer/build.py — regenerate the Phase 2 Bin Viewer (dev tool,
reports/BINNING_ROUND1_2026-09.md).

Read-only against the DB. Produces two files next to this script:
  bin_data.json   — the data payload (bins, SKUs, traits, monthly quantity)
  bin_viewer.html — template.html with bin_data.json inlined; self-contained,
                    open it by double-clicking, no server needed.

No credentials appear in either output file — this script only ever reads
already-computed sku_traits/sku_segment rows plus the demand series used
for the sparklines; the DB URL never leaves the process environment.

Usage (from the repo root, with .env holding SUPABASE_DIRECT_URL or
SUPABASE_DB_URL):
    python tools/bin_viewer/build.py --schema ssm_binning_phase2   # scratch, before the public write
    python tools/bin_viewer/build.py                               # public, after the write gate
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

import psycopg2
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

DEMAND_START, DEMAND_END = "2023-01", "2026-02"

# Rule text shown on a bin node — describes the SCHEME's cutoff, never a
# single SKU's bin_reason (a per-SKU reason string is not the rule).
SCHEME_BIN_RULES = {
    "length_v1": {
        "insufficient": "< 3 months with sales",
        "short": "3–11 months with sales",
        "long": "≥ 12 months with sales",
    },
}


def _build_length_v1_graph(cohort_size: int, bin_counts: dict) -> dict:
    """KNIME-style node graph for length_v1's two sequential gates. Counts
    come from the real bin_counts this build actually computed, never
    hardcoded, so a stale graph can't silently drift from the data."""
    insufficient = bin_counts.get("insufficient", 0)
    short = bin_counts.get("short", 0)
    long_ = bin_counts.get("long", 0)
    eligible = short + long_

    nodes = [
        {"id": "source", "type": "source", "label": "Tier A cohort",
         "sublabel": "2026-02", "count": cohort_size},
        {"id": "gate1", "type": "gate", "label": "≥ 3 months\nwith sales?",
         "rule": "history_months >= 3", "pass": eligible, "fail": insufficient},
        {"id": "bin_insufficient", "type": "bin", "bin": "insufficient",
         "label": "Insufficient", "count": insufficient},
        {"id": "gate2", "type": "gate", "label": "≥ 12 months?",
         "rule": "history_months >= 12", "pass": long_, "fail": short},
        {"id": "bin_short", "type": "bin", "bin": "short", "label": "Short", "count": short},
        {"id": "bin_long", "type": "bin", "bin": "long", "label": "Long", "count": long_},
    ]
    edges = [
        {"from": "source", "to": "gate1", "count": cohort_size},
        {"from": "gate1", "to": "bin_insufficient", "label": "no", "count": insufficient},
        {"from": "gate1", "to": "gate2", "label": "yes", "count": eligible},
        {"from": "gate2", "to": "bin_short", "label": "no", "count": short},
        {"from": "gate2", "to": "bin_long", "label": "yes", "count": long_},
    ]
    return {"nodes": nodes, "edges": edges}


SCHEME_GRAPH_BUILDERS = {
    "length_v1": _build_length_v1_graph,
}


def connect():
    load_dotenv(os.path.join(REPO, ".env"))
    dsn = os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"]
    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def qualify(table: str, schema: str | None) -> str:
    return f"{schema}.{table}" if schema else table


def fetch(schema: str | None, principal: str, cohort_period: str, abc_method: str, scheme: str):
    conn = connect()
    cur = conn.cursor()

    traits_table = qualify("sku_traits", schema)
    segment_table = qualify("sku_segment", schema)

    cur.execute(f"""
        SELECT DISTINCT scheme FROM {segment_table}
        WHERE principal = %s AND cohort_period = %s AND abc_method = %s
        ORDER BY scheme
    """, (principal, cohort_period, abc_method))
    schemes = [r[0] for r in cur.fetchall()] or [scheme]

    cur.execute(f"""
        SELECT s.product_key, s.sku_code, s.bin, s.bin_reason, s.run_id,
               t.history_months, t.first_sale_period, t.longest_run, t.trend,
               t.cv, t.restart_flag, t.stability_group, t.revenue_share_2026_02
        FROM {segment_table} s
        JOIN {traits_table} t
          ON t.product_key = s.product_key AND t.cohort_period = s.cohort_period
        WHERE s.principal = %s AND s.cohort_period = %s AND s.abc_method = %s AND s.scheme = %s
        ORDER BY s.product_key ASC
    """, (principal, cohort_period, abc_method, scheme))
    rows = cur.fetchall()
    if not rows:
        sys.exit(f"No sku_segment rows found for principal={principal!r} cohort_period={cohort_period!r} "
                  f"abc_method={abc_method!r} scheme={scheme!r} in schema={schema or 'public'!r}. "
                  f"Run analytics/segmentation/orchestrate_segment.py first.")

    product_keys = [r[0] for r in rows]
    run_id = rows[0][4]

    prod_table = qualify("product_dimension", None)  # dimension always lives in public
    cur.execute(f"""
        SELECT product_key, product_name FROM {prod_table}
        WHERE principal = %s AND product_key = ANY(%s)
    """, (principal, product_keys))
    names = {pk: name for pk, name in cur.fetchall()}

    cur.execute(f"""
        SELECT product_key, calendar_month, quantity_sold
        FROM unilever_sku_demand_fact_real
        WHERE product_key = ANY(%s) AND calendar_month BETWEEN %s AND %s
    """, (product_keys, DEMAND_START, DEMAND_END))
    demand_rows = cur.fetchall()
    conn.close()

    import pandas as pd
    periods = [str(p) for p in pd.period_range(DEMAND_START, DEMAND_END, freq="M")]
    series_map = {pk: {p: 0.0 for p in periods} for pk in product_keys}
    for pk, period, qty in demand_rows:
        if pk in series_map and period in series_map[pk]:
            series_map[pk][period] = max(float(qty), 0.0) if qty is not None else 0.0

    skus = []
    bin_counts: dict[str, int] = {}
    for (pk, sku_code, bin_name, bin_reason, _run_id, history_months, first_sale_period,
         longest_run, trend, cv, restart_flag, stability_group, revenue_share) in rows:
        bin_counts[bin_name] = bin_counts.get(bin_name, 0) + 1
        skus.append({
            "product_key": pk,
            "sku_code": sku_code,
            "product_name": names.get(pk),
            "bin": bin_name,
            "bin_reason": bin_reason,
            "history_months": history_months,
            "first_sale_period": first_sale_period,
            "longest_run": longest_run,
            "trend": trend,
            "cv": round(float(cv), 4) if cv is not None else None,
            "restart_flag": bool(restart_flag),
            "stability_group": stability_group,
            "revenue_share": round(float(revenue_share), 4) if revenue_share is not None else None,
            "monthly": [round(series_map[pk][p], 1) for p in periods],
        })

    bin_rules = SCHEME_BIN_RULES.get(scheme, {})
    graph_builder = SCHEME_GRAPH_BUILDERS.get(scheme)
    graph = graph_builder(len(skus), bin_counts) if graph_builder else None

    payload = {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "principal": principal,
        "cohort_period": cohort_period,
        "abc_method": abc_method,
        "scheme": scheme,
        "schemes": schemes,
        "run_id": run_id,
        "periods": periods,
        "summary": {
            "total": len(skus),
            "per_bin": bin_counts,
        },
        "bin_rules": bin_rules,
        "graph": graph,
        "skus": skus,
    }
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", default=None, help="Source schema (default: public).")
    ap.add_argument("--principal", default="unilever")
    ap.add_argument("--cohort-period", default="2026-02")
    ap.add_argument("--abc-method", default="single")
    ap.add_argument("--scheme", default="length_v1")
    args = ap.parse_args()

    payload = fetch(args.schema, args.principal, args.cohort_period, args.abc_method, args.scheme)

    data_str = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    if "</script" in data_str.lower():
        sys.exit("payload contains a </script> sequence — cannot inline safely")

    with open(os.path.join(HERE, "bin_data.json"), "w", encoding="utf-8") as fh:
        fh.write(data_str)

    template_path = os.path.join(HERE, "template.html")
    template = open(template_path, encoding="utf-8").read()
    if "__BIN_DATA__" not in template:
        sys.exit("template.html is missing the __BIN_DATA__ placeholder")
    with open(os.path.join(HERE, "bin_viewer.html"), "w", encoding="utf-8") as fh:
        fh.write(template.replace("__BIN_DATA__", data_str))

    print(f"wrote bin_data.json + bin_viewer.html — {payload['summary']['total']} SKUs, "
          f"bins={payload['summary']['per_bin']}, schema={args.schema or 'public'}")


if __name__ == "__main__":
    main()
