"""QA check 3 (2026-10-03): recompute the four headline numbers from the raw
extract with separate code: csv module and exact Decimal arithmetic, no
pandas, nothing imported from run_tier_a_basis.py.

Rules, restated from the README rather than reused from the analysis:
a month with net_amount < 0 counts as 0; a product with a blank net_amount in
the window is left out of that window; products with 0 revenue get no class;
rank by revenue descending, product_key ascending on ties; Class A while the
running share is <= 80%. First real sale = first month with quantity_sold > 0.

    python qa_independent_recompute.py --extract <dir>
"""
import argparse
import csv
from decimal import Decimal
from pathlib import Path

EXPECTED = {  # as printed in README.md
    "today_tier_a_feb_2026": 132,
    "class_a_12m_mar_2025_feb_2026": 175,
    "rule1_list": 189,
    "left_out_12m_by_today_php_millions_2dp": Decimal("126.80"),
    "left_out_12m_by_today_pct_1dp": Decimal("32.3"),
}


def months(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def revenue(rows, window: set[str]) -> dict[int, Decimal]:
    rev: dict[int, Decimal] = {}
    blank: set[int] = set()
    for r in rows:
        if r["calendar_month"] not in window:
            continue
        pk = int(r["product_key"])
        if r["net_amount"] == "":
            blank.add(pk)
            continue
        rev[pk] = rev.get(pk, Decimal(0)) + max(Decimal(r["net_amount"]), Decimal(0))
    return {pk: v for pk, v in rev.items() if pk not in blank and v > 0}


def class_a(rev: dict[int, Decimal]) -> set[int]:
    total = sum(rev.values())
    running, a = Decimal(0), set()
    for pk, v in sorted(rev.items(), key=lambda kv: (-kv[1], kv[0])):
        running += v
        if running / total <= Decimal("0.80"):
            a.add(pk)
    return a


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True, type=Path)
    with open(ap.parse_args().extract / "demand_real.csv", newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if "2023-01" <= r["calendar_month"] <= "2026-02"]

    w12 = set(months("2025-03", "2026-02"))
    today = class_a(revenue(rows, {"2026-02"}))
    rev12 = revenue(rows, w12)
    a12 = class_a(rev12)
    a3 = class_a(revenue(rows, set(months("2025-12", "2026-02"))))
    first_sale: dict[int, str] = {}
    for r in rows:
        if r["quantity_sold"] != "" and Decimal(r["quantity_sold"]) > 0:
            pk = int(r["product_key"])
            first_sale[pk] = min(first_sale.get(pk, "9999-99"), r["calendar_month"])
    rule1 = a12 | {pk for pk in a3 if "2025-03" <= first_sale.get(pk, "9999-99") <= "2026-02"}
    total12 = sum(rev12.values())
    left_out = total12 - sum(v for pk, v in rev12.items() if pk in today)

    got = {
        "today_tier_a_feb_2026": len(today),
        "class_a_12m_mar_2025_feb_2026": len(a12),
        "rule1_list": len(rule1),
        "left_out_12m_by_today_php_millions_2dp": (left_out / 10**6).quantize(Decimal("0.01")),
        "left_out_12m_by_today_pct_1dp": (100 * left_out / total12).quantize(Decimal("0.1")),
    }
    print(f"left out, exact: PHP {left_out:,.2f} of PHP {total12:,.2f} ({100 * left_out / total12:.4f}%)")
    ok = True
    for k, v in got.items():
        match = v == EXPECTED[k]
        ok &= match
        print(f"{'MATCH' if match else 'MISMATCH':8}  {k}: recomputed {v}, README {EXPECTED[k]}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
