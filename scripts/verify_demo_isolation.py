"""
scripts/verify_demo_isolation.py — prove the demonstration schema did not reach the real path.

    python -m scripts.verify_demo_isolation snapshot OUT.json     # before the build
    python -m scripts.verify_demo_isolation compare BEFORE.json   # after: prints the verification table, exit 1 on any difference

For every relation the real forecast, accuracy, ABC and LP paths read — the six _Real views, the two real marts, and
the forecast / LP / ABC tables — it records, in one read-only transaction run in the database (no rows pulled out):
the row count and a content fingerprint (SUM of hashtext of each row's text). `compare` fails if either moved, if any
_Real view carries an is_demo row, or if any generated (interpolated) demo month exists in SellOut_Fact_Real.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analytics.config import long_read_db_url  # noqa: E402

REL = [
    "public.sales_fact_real", "public.purchase_fact_real", "public.inventory_fact_real", "public.sellout_fact_real",
    "public.unilever_sku_demand_fact_real", "public.salesreturn_fact_real",
    "mart.sales_mart_real", "mart.inventory_mart_real",
    "public.forecast_result", "public.abc_classification", "public.lp_run", "public.lp_recommendation",
    "mart.forecast_run", "mart.forecast_run_value", "mart.accuracy_mart", "mart.planning_mart",
]


def snapshot(db_url: str) -> dict:
    conn = psycopg2.connect(db_url, connect_timeout=20)
    out: dict = {}
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        for rel in REL:
            cur.execute("SELECT to_regclass(%s)", (rel,))
            if cur.fetchone()[0] is None:
                out[rel] = {"missing": True}
                continue
            cur.execute(f"SELECT COUNT(*), COALESCE(SUM(hashtext(t::text)::bigint), 0) FROM {rel} t")
            n, fp = cur.fetchone()
            entry = {"rows": int(n), "fingerprint": int(fp)}
            schema, name = rel.split(".")
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name='is_demo'",
                        (schema, name))
            if cur.fetchone():
                cur.execute(f"SELECT COUNT(*) FROM {rel} WHERE is_demo")
                entry["is_demo_rows"] = int(cur.fetchone()[0])
            out[rel] = entry
        cur.execute("SELECT to_regclass('demo.dm_category_sales')")
        if cur.fetchone()[0] is not None:
            cur.execute("""SELECT COUNT(*) FROM demo.dm_category_sales d
                           JOIN public.sellout_fact_real s ON s.category_path = d.category_path AND s._period = d.period
                           WHERE d.origin = 'interpolated'""")
            out["interpolated_months_present_in_sellout_fact_real"] = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM demo.dm_category_sales WHERE origin = 'interpolated'")
            out["interpolated_months_in_demo"] = int(cur.fetchone()[0])
        cur.execute("ROLLBACK")
    finally:
        conn.close()
    return out


def compare(before: dict, after: dict) -> int:
    bad = 0
    print(f"{'relation':<42}{'rows before':>12}{'rows after':>12}{'same rows':>11}{'is_demo rows':>14}")
    for rel in REL:
        b, a = before.get(rel, {}), after.get(rel, {})
        if a.get("missing") or b.get("missing"):
            print(f"{rel:<42}{'(not present)':>49}")
            continue
        same = b.get("rows") == a.get("rows") and b.get("fingerprint") == a.get("fingerprint")
        demo = a.get("is_demo_rows")
        real_view = rel.endswith("_real")
        ok = same and (not real_view or not demo)
        bad += 0 if ok else 1
        print(f"{rel:<42}{b['rows']:>12}{a['rows']:>12}{('yes' if same else 'NO'):>11}{('-' if demo is None else demo):>14}")
    leak = after.get("interpolated_months_present_in_sellout_fact_real")
    print(f"generated months found in SellOut_Fact_Real: {leak} of {after.get('interpolated_months_in_demo')}")
    bad += 1 if leak else 0
    print("RESULT:", "PASS: nothing generated reached the real path" if bad == 0 else f"FAIL: {bad} difference(s)")
    return 1 if bad else 0


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"snapshot", "compare"}:
        print(__doc__)
        return 2
    snap = snapshot(long_read_db_url())
    if sys.argv[1] == "snapshot":
        Path(sys.argv[2]).write_text(json.dumps(snap, indent=1), encoding="utf-8")
        print(f"snapshot of {len(REL)} relations written to {sys.argv[2]}")
        return 0
    return compare(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")), snap)


if __name__ == "__main__":
    sys.exit(main())
