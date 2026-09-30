"""
Evidence inputs: ONE read-only transaction against the _Real views (plus
ABC_Classification / Product_Dimension, which hold no is_demo rows), written to
reports/evidence/inputs/. Every chart script reads these files, never the DB
(charts 6 and 8-10 reuse the viewer's and run_lp's own read-only fetches).

Expected (stated before running): Tier A 2026-02 single = 132 SKUs; their series
2023-01..2026-02 = 3,087 rows (final_fit.py:77-78) and 0 duplicate SKU-months.
NULL quantities: exactly ONE, product_key 150 / SKU 64861486, 2025-12 (net PHP 2.89),
counted as 0 like the bake-off (_common.KNOWN_NULLS; corrected 2026-09-30 - the
first run expected 0, a figure taken from the transforms experiment's printout,
not from final_fit.py, which prints the count with no expectation). Any other
NULL stops the run. No expected figure is on record for the ABC latest-period
rows or the Del Monte region x month grid: reported as found.
"""
import _common as C  # noqa: F401  (thread pins first)
import os

import pandas as pd

Q = {
    "tierA": """SELECT a.product_key, p.sku_code, p.product_name, a.revenue_share, a.cumulative_share
                FROM abc_classification a JOIN product_dimension p USING (product_key)
                WHERE a.principal = 'unilever' AND a.classification_period = '2026-02' AND a.method = 'single'
                  AND a.tier = 'A' ORDER BY a.product_key""",
    "series": """SELECT d.product_key, d.calendar_month, d.quantity_sold, d.net_amount
                 FROM unilever_sku_demand_fact_real d
                 WHERE d.product_key = ANY(%(pks)s) AND d.calendar_month BETWEEN '2023-01' AND '2026-02'
                 ORDER BY 1, 2""",
    "abc_latest": """WITH per AS (                                   -- latest period of the 'single' method, per principal;
                        SELECT principal, MAX(classification_period) AS period  -- every method present at that period
                        FROM abc_classification WHERE method = 'single' GROUP BY 1)
                     SELECT a.principal, a.method, a.classification_period, a.product_key, a.tier,
                            a.revenue_share, a.cumulative_share, a.boundary_flag,
                            p.grain, p.sku_code, p.category_path, p.product_name
                     FROM abc_classification a
                     JOIN per ON per.principal = a.principal AND per.period = a.classification_period
                     JOIN product_dimension p ON p.product_key = a.product_key
                     ORDER BY 1, 2, a.cumulative_share""",
    "abc_periods": """SELECT principal, method, MAX(classification_period), COUNT(DISTINCT classification_period)
                      FROM abc_classification GROUP BY 1, 2 ORDER BY 1, 2""",
    # Del Monte has no branch field: branch_code is outlet-level ("Branch Code"/"Outlet",
    # config/column_maps/sales_register.yaml:89-91). region holds the branch
    # (pangasinan / ilocos) in 2023 rows and a town name from 2024 (three header
    # vocabularies, sales_register.yaml:30-33). Both are kept as found.
    "dm_region_month": """SELECT region, to_char(invoice_date, 'YYYY-MM') AS month,
                                 SUM(net_amount) AS net_amount, COUNT(*) AS invoices
                          FROM sales_fact_real WHERE principal = 'delmonte'
                          GROUP BY 1, 2 ORDER BY 1, 2""",
    "dm_null_dates": "SELECT COUNT(*) FROM sales_fact_real WHERE principal = 'delmonte' AND invoice_date IS NULL",
    "ul_month": """SELECT calendar_month AS month, SUM(net_amount) AS net_amount, COUNT(*) AS rows,
                          COUNT(net_amount) AS rows_with_amount
                   FROM unilever_sku_demand_fact_real GROUP BY 1 ORDER BY 1""",
}


def main():
    os.makedirs(C.INPUTS, exist_ok=True)
    out = {}
    with C.read_only() as (cur, via):
        cur.execute(Q["tierA"]); out["tierA"] = cur.fetchall()
        pks = [int(r[0]) for r in out["tierA"]]
        cur.execute(Q["series"], {"pks": pks}); out["series"] = cur.fetchall()
        for k in ("abc_latest", "abc_periods", "dm_region_month", "dm_null_dates", "ul_month"):
            cur.execute(Q[k]); out[k] = cur.fetchall()
    print(f"read via {via} (one READ ONLY transaction, rolled back)")

    t = pd.DataFrame(out["tierA"], columns=["pk", "sku_code", "product_name", "revenue_share", "cumulative_share"])
    s = pd.DataFrame(out["series"], columns=["pk", "month", "q", "net_amount"])
    s["q"] = pd.to_numeric(s.q, errors="coerce").astype(float)
    s["net_amount"] = pd.to_numeric(s.net_amount, errors="coerce").astype(float)
    nulls = {(int(r.pk), r.month) for r in s[s.q.isna()].itertuples()}
    print(f"tierA SKUs={len(t)} (expected 132) | series rows={len(s)} (expected 3087) SKUs={s.pk.nunique()} "
          f"NULL q={sorted(nulls)} (expected exactly {sorted(C.KNOWN_NULLS)}) "
          f"dup={int(s.duplicated(['pk', 'month']).sum())} (expected 0) "
          f"negative={int((s.q < 0).sum())} span={s.month.min()}..{s.month.max()}")
    if len(t) != 132 or len(s) != 3087 or nulls != C.KNOWN_NULLS or s.duplicated(["pk", "month"]).any():
        C.fail("extract", f"Tier A / series differ from the stated expectation (132 / 3087 / NULLs exactly "
                          f"{sorted(C.KNOWN_NULLS)} / 0 dup); NULLs found: {sorted(nulls)}")

    a = pd.DataFrame(out["abc_latest"], columns=["principal", "method", "period", "pk", "tier", "revenue_share",
                                                 "cumulative_share", "boundary_flag", "grain", "sku_code",
                                                 "category_path", "product_name"])
    for c in ("revenue_share", "cumulative_share"):
        a[c] = pd.to_numeric(a[c]).astype(float)
    print("abc periods (principal, method, latest, n periods):", out["abc_periods"])
    print("abc latest rows:", a.groupby(["principal", "method", "period"]).size().to_dict())

    dm = pd.DataFrame(out["dm_region_month"], columns=["region", "month", "net_amount", "invoices"])
    dm["net_amount"] = pd.to_numeric(dm.net_amount).astype(float)
    ul = pd.DataFrame(out["ul_month"], columns=["month", "net_amount", "rows", "rows_with_amount"])
    ul["net_amount"] = pd.to_numeric(ul.net_amount).astype(float)
    print(f"delmonte region x month cells={len(dm)} regions={dm.region.nunique()} "
          f"span={dm.month.min()}..{dm.month.max()} null invoice_date rows={out['dm_null_dates'][0][0]}")
    print(f"unilever months={len(ul)} span={ul.month.min()}..{ul.month.max()} "
          f"rows without net_amount={int((ul.rows - ul.rows_with_amount).sum())}")

    t.to_csv(os.path.join(C.INPUTS, "unilever_tierA_2026-02.csv"), index=False, lineterminator="\n")
    s.to_csv(os.path.join(C.INPUTS, "unilever_tierA_2026-02_series.csv"), index=False, lineterminator="\n")
    a.to_csv(os.path.join(C.INPUTS, "abc_latest.csv"), index=False, lineterminator="\n")
    dm.to_csv(os.path.join(C.INPUTS, "delmonte_sales_region_month.csv"), index=False, lineterminator="\n")
    ul.to_csv(os.path.join(C.INPUTS, "unilever_sales_month.csv"), index=False, lineterminator="\n")


if __name__ == "__main__":
    main()
