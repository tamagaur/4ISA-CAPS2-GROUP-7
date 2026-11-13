"""scripts/score_stock_limited_rule.py - is the "possibly stock-limited" label informative? READ ONLY (2026-11-13).

    python -m scripts.score_stock_limited_rule [--json]

Scores today's rule (mart.accuracy_mart.possibly_stock_limited, migration 0043/0050) against the candidate in backend/stock_signal
("absent_at_close"), and the card's MAPE under each setting of backend/stock_signal.MAPE_APART. Writes nothing anywhere: the switches
are flipped in this process only, the database is read in READ ONLY transactions, and the card's figures are read through the API
in-process (FastAPI TestClient, the auth dependency overridden: no token, no secret).

The test of a label: a month whose sales were capped by an empty shelf should sell BELOW the product's usual level and be
over-forecast more often. "Sold vs average" = actual pieces / the mean monthly pieces of the 12 months before (the rule's own
yardstick, accuracy_mart.avg_monthly_pieces). Aggregates only (no per-product figure is printed: hard rule 9).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TIERS = {21: "A", 22: "B", 23: "C"}   # the card's default run and its Tier B / C counterfactual twins (2026-11-13)
WINDOWS = (("2025-03", "2026-02"), ("2025-09", "2026-02"), ("2024-01", "2025-08"))

GROUPS_SQL = """
WITH a AS (
  SELECT a.run_id, a.month, a.actual_pieces act, a.avg_monthly_pieces avg, a.direction, a.possibly_stock_limited cur,
         a.opening_pieces o, a.closing_pieces c, a.count_possibly_partial partial,
         CASE WHEN a.closing_pieces IS NULL OR a.count_possibly_partial THEN NULL ELSE a.closing_pieces = 0 END cand,
         LEAST(a.opening_pieces, a.closing_pieces) / NULLIF(a.avg_monthly_pieces * 12 / 52, 0) low_weeks
  FROM mart.accuracy_mart a WHERE a.run_id IN (21, 22, 23))
SELECT run_id,
  CASE WHEN o = 0 AND c = 0 THEN 'absent at both counts'
       WHEN c = 0 THEN 'absent at the closing count only'
       WHEN o = 0 THEN 'absent at the opening count only'
       WHEN cur THEN 'listed, below 1 week'
       WHEN cur IS FALSE THEN 'not flagged'
       ELSE 'unknown' END grp,
  count(*) n,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY act / avg) FILTER (WHERE avg > 0 AND act IS NOT NULL) sold_vs_avg,
  100.0 * count(*) FILTER (WHERE direction = 'over') / NULLIF(count(*) FILTER (WHERE direction IS NOT NULL), 0) pct_over
FROM a GROUP BY 1, 2 ORDER BY 1, 2
"""
RATES_SQL = """
SELECT run_id, count(*) n, count(*) FILTER (WHERE possibly_stock_limited) current_flagged,
       count(*) FILTER (WHERE closing_pieces = 0 AND NOT COALESCE(count_possibly_partial, false)) candidate_flagged,
       min(r_cur) min_month_pct_current, max(r_cur) max_month_pct_current, min(r_cand) min_month_pct_candidate, max(r_cand) max_month_pct_candidate
FROM mart.accuracy_mart a
JOIN (SELECT run_id rid, month m,
             100.0 * count(*) FILTER (WHERE possibly_stock_limited) / count(*) r_cur,
             100.0 * count(*) FILTER (WHERE closing_pieces = 0 AND NOT COALESCE(count_possibly_partial, false)) / count(*) r_cand
      FROM mart.accuracy_mart WHERE run_id IN (21, 22, 23) GROUP BY 1, 2) m ON m.rid = a.run_id AND m.m = a.month
WHERE a.run_id IN (21, 22, 23) GROUP BY 1 ORDER BY 1
"""
BANDS_SQL = """
SELECT CASE WHEN w < 0.1 THEN '0-0.1' WHEN w < 0.25 THEN '0.1-0.25' WHEN w < 0.5 THEN '0.25-0.5' WHEN w < 1 THEN '0.5-1'
            WHEN w < 2 THEN '1-2' WHEN w < 4 THEN '2-4' ELSE '4+' END weeks, count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY act / avg) sold_vs_avg,
       100.0 * count(*) FILTER (WHERE direction = 'over') / count(*) pct_over
FROM (SELECT actual_pieces act, avg_monthly_pieces avg, direction,
             LEAST(opening_pieces, closing_pieces) / (avg_monthly_pieces * 12 / 52) w
      FROM mart.accuracy_mart WHERE run_id = 21 AND opening_pieces > 0 AND closing_pieces > 0 AND avg_monthly_pieces > 0
        AND actual_pieces IS NOT NULL) x
GROUP BY 1 ORDER BY min(w)
"""


def read_only(sql: str) -> list[dict]:
    import psycopg2
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")      # transaction-scoped (hard rule 7)
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        out = [{k: (round(float(v), 3) if isinstance(v, float) or type(v).__name__ == "Decimal" else v) for k, v in zip(cols, r)}
               for r in cur.fetchall()]
        conn.rollback()
        return out
    finally:
        conn.close()


def card_under_each_setting() -> dict:
    """The card's MAPE and stock-limited count per window, under each switch setting, through the API in-process."""
    from fastapi.testclient import TestClient
    from backend import response_cache, stock_signal
    from backend.auth_utils import TokenPayload
    from backend.deps import get_current_user, get_token_payload
    from backend.main import app
    reader = TokenPayload(user_id=0, email="score@local", role="admin", full_name="Score")
    app.dependency_overrides[get_current_user] = lambda: reader
    app.dependency_overrides[get_token_payload] = lambda: reader
    client = TestClient(app)
    saved = (stock_signal.RULE, stock_signal.MAPE_APART)
    out = {}
    try:
        for rule, apart in ((stock_signal.CURRENT_RULE, "either_count"), (stock_signal.CANDIDATE_RULE, "closing_count"),
                            (stock_signal.CANDIDATE_RULE, "none")):
            stock_signal.RULE, stock_signal.MAPE_APART = rule, apart
            for start, end in WINDOWS:
                response_cache.invalidate()
                body = client.get(f"/dashboard/accuracy?principal=unilever&start_period={start}&period={end}").json()
                mape = body.get("mape") or {}
                out[f"{rule} / MAPE apart: {apart} / {start}..{end}"] = {
                    "mape": mape.get("value"), "mape_products": mape.get("products"),
                    "months_set_apart": mape.get("zero_stock_months_apart"),
                    "stock_limited_product_months": body.get("possibly_stock_limited"),
                    "company_total": (body.get("company_total") or {}).get("value"),
                    "typical_product_weighted": (body.get("typical_product_weighted") or {}).get("value")}
    finally:
        stock_signal.RULE, stock_signal.MAPE_APART = saved
        response_cache.invalidate()
        app.dependency_overrides.clear()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    result = {"rates": read_only(RATES_SQL), "groups": read_only(GROUPS_SQL), "tier_a_low_count_bands": read_only(BANDS_SQL),
              "card": card_under_each_setting()}
    for r in result["rates"] + result["groups"]:
        r["tier"] = TIERS.get(r.pop("run_id"))
    if args.json:
        print(json.dumps(result, indent=1, default=str))
        return 0
    for section, rows in result.items():
        print(f"== {section}")
        for r in (rows.items() if isinstance(rows, dict) else enumerate(rows)):
            print(" ", r[1] if not isinstance(rows, dict) else f"{r[0]}: {r[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
