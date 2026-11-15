"""scripts/mape_floor.py - the "perfect average level" floor for the card's MAPE, on Chapter 3's basis. READ ONLY (2026-11-15).

    python -m scripts.mape_floor [--json]

The floor is an ORACLE, not a forecast: it forecasts every month of a product with the product's own true mean over the scored
window (it uses the future). It answers "how much of the typical product's percentage miss no level forecast can remove".
It is scored on exactly the rows the Forecast-error card scores (backend.marts.accuracy_rows_query: the run each month resolves to),
with exactly the card's MAPE functions (backend.marts.accuracy_aggregates / mape_summary), so the served MAPE and the floor are the
same measure on the same product-months:

  Chapter 3 basis       no month set apart (the card's headline).
  stock-limited basis   months flagged stock-limited (absent from the month-end count, backend.stock_signal) set apart.
                        Two floors there: the level is the mean of ALL scored months (the one level the product really had) or of
                        the months that count (the best level a measure that sees only those months could be given).

Pooled WAPE of the same oracle is printed for continuity with reports/experiments/error_hunt_2026-11-10 (its WAPE floor).
Aggregates only (no per-product figure: hard rule 9). Reads in READ ONLY transactions; writes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

WINDOWS = (("2025-03", "2026-02"), ("2025-09", "2026-02"), ("2024-01", "2025-08"))


def _rows(start: str, end: str) -> list[dict]:
    import psycopg2
    import psycopg2.extras
    from backend import marts, stock_signal
    sql, params = marts.accuracy_rows_query(start, end, None)
    sql = re.sub(r"(?<![:\w]):(\w+)", r"%(\1)s", sql)
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")      # transaction-scoped (hard rule 7)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.rollback()
    finally:
        conn.close()
    return stock_signal.apply_to_rows(rows)


def _median(v: list[float]) -> float | None:
    v = sorted(v)
    n = len(v)
    return None if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2)


def _floor(rows: list[dict], keep) -> dict:
    """The oracle's MAPE (median over products of mean |L - a| / a over months with a > 0 that `keep` passes), with L the product's
    mean over all scored months ("all") or over the months kept ("kept"); and pooled WAPE over the kept months."""
    by: dict[int, list[dict]] = {}
    for r in rows:
        by.setdefault(int(r["product_key"]), []).append(r)
    out = {}
    for name in ("all", "kept"):
        apes, abs_sum, act_sum = [], 0.0, 0.0
        for rs in by.values():
            kept = [r for r in rs if keep(r)]
            pool = rs if name == "all" else kept
            if not pool:
                continue
            level = sum(float(r["actual_pieces"]) for r in pool) / len(pool)
            terms = [abs(level - float(r["actual_pieces"])) / float(r["actual_pieces"]) for r in kept if float(r["actual_pieces"]) > 0]
            if terms:
                apes.append(sum(terms) / len(terms))
            abs_sum += sum(abs(level - float(r["actual_pieces"])) for r in kept)
            act_sum += sum(float(r["actual_pieces"]) for r in kept)
        out[name] = {"mape": _median(apes), "products": len(apes), "pooled_wape": (abs_sum / act_sum) if act_sum else None}
    return out


def measure(start: str, end: str) -> dict:
    from backend import marts, stock_signal
    rows = _rows(start, end)
    agg = marts.accuracy_aggregates(rows)
    served = marts.mape_summary(agg["products"])
    flagged = lambda r: stock_signal.zero_stock_row(r, stock_signal.MAPE_VARIANT_APART)   # noqa: E731
    ch3 = _floor(rows, lambda r: True)
    sl = _floor(rows, lambda r: not flagged(r))
    return {
        "product_months": len(rows), "products": len({r["product_key"] for r in rows}),
        "served": {"chapter3_mape": served["value"], "chapter3_products": served["products"],
                   "stock_limited_mape": served["stock_limited_variant"]["value"],
                   "stock_limited_products": served["stock_limited_variant"]["products"],
                   "months_set_apart": served["stock_limited_variant"]["months_set_apart"]},
        "floor_chapter3_basis": {"level_all_months": ch3["all"], "note": "no month set apart: level over all months = level over kept"},
        "floor_stock_limited_basis": {"level_all_months": sl["all"], "level_kept_months": sl["kept"]},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    result = {f"{a}..{b}": measure(a, b) for a, b in WINDOWS}
    print(json.dumps(result, indent=1, default=str) if args.json else
          "\n".join(f"{k}: {json.dumps(v, default=str)}" for k, v in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
