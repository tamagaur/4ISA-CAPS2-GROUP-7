"""scripts/build_synthetic_v2_clean_pool.py - synthetic blocks in the scratch schema ssm_synth_v2, resampled from
CLEAN pools: the REAL rows in public after the Del Monte fixes, read through the _Real views (structurally
is_demo = false), never from staging/. That excludes by construction the FAKE BOOKING invoices (removed), the
"(2)" sheet (held in etl_quarantine), every quarantined row, the pre-re-key Aug-2023 values and the price-list
sheets (never loaded). Del Monte inventory also drops the 203 numeric count-sheet codes (2023-08 only).

WRITES ONLY TO ssm_synth_v2; public is only read. Every row it writes is is_demo = true with a GENERATED_BACKFILL_*
_src_file (the provenance analytics.etl.transform.SYNTHETIC_SOURCE_RE recognises). Resampling runs on the server:
a month's draw is ORDER BY md5(<block>|<month>[|<site>]|<row key>) LIMIT n, and n comes from a seeded generator,
so a re-run writes the same rows.

Blocks
  dm_sales       REGENERATE every month v2 holds Del Monte synthetic sales today (the converted block and the
                 2026-04..08 forward block): same months, invoice grain, new values. n = a real monthly row total
                 of the nearest month-of-year; rows = real rows of those months, without replacement; a synthetic
                 invoice number per row; the day of month kept (clipped to the month).
  dm_inventory   every month public holds v1-only synthetic Del Monte inventory (and v2 at most 1 stray row):
                 per site, the SKU set of the real snapshot with the nearest month-of-year (then nearest year),
                 alphanumeric real codes only; each SKU's values from one of its own real rows at that site,
                 same month-of-year first. snapshot_date = first of the month (the real Del Monte convention).
  dm_returns     2021-01..2022-12, per site: n = a real monthly count of the nearest month-of-year, rows from the
                 monthly sales-return files (source IS NULL; the RMR lines have a different shape) of those months;
                 synthetic slip and invoice numbers; return_date NULL as on every real row.
  uni_inventory  2021-01..2022-12: each SKU of the v2 2021-22 demand placeholder, for the months between its first
                 and last placeholder month, gets its real 2023 row of the same month-of-year (no 2023 row, no
                 synthetic row); snapshot_date shifted back by the year difference. Same columns as real rows.
  dm_inventory_forward, dm_purchases_forward
                 the 2026-04..08 forward blocks generate_synthetic_backfill.py wrote from staging pools (inventory pool
                 42% price-list rows; purchases pool held the 18 quarantined Sept-2025 lines), regenerated the same way
                 from the clean pools: same months, same grain.
Not generated here (decided 2026-09-28): anything in 2026-09, Del Monte returns in 2023+ gap months, Del Monte
purchases 2025-09, Unilever purchases or returns.

  python -m scripts.build_synthetic_v2_clean_pool --pools            pool sizes, writes nothing
  python -m scripts.build_synthetic_v2_clean_pool --write BLOCK ...  one transaction per block
  python -m scripts.build_synthetic_v2_clean_pool --checks           the simulated cutover (public real + v2 synthetic)
"""
from __future__ import annotations

import argparse
import hashlib
import sys

import numpy as np

from scripts.apply_dm_fixes_to_public import connect

V2 = "ssm_synth_v2"
MONTHS_2122 = [f"{y}-{m:02d}" for y in (2021, 2022) for m in range(1, 13)]
SITES = ("ilocos", "pangasinan")
TAG = "GENERATED_BACKFILL_"
SYNTH_SRC = r"^(data[/\\]raw[/\\]Synthetic Data[/\\]|GENERATED_BACKFILL_)"
ALPHA = r"sku_code !~ '^[0-9]+$'"


def rows(cur, sql, args=None):
    cur.execute(sql, args)
    return cur.fetchall()


def rng(*parts: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16))


def _ym(p: str) -> tuple[int, int]:
    return int(p[:4]), int(p[5:7])


def _moy_distance(a: str, b: str) -> int:
    d = abs(_ym(a)[1] - _ym(b)[1])
    return min(d, 12 - d)


def nearest_moy(target: str, months: list[str]) -> list[str]:
    """The real months whose month-of-year is closest to the target's (all of them on a tie)."""
    best = min(_moy_distance(target, m) for m in months)
    return sorted(m for m in months if _moy_distance(target, m) == best)


def template_month(target: str, months: list[str]) -> str:
    """One real month: nearest month-of-year, then nearest year, then the later year."""
    return min(months, key=lambda m: (_moy_distance(target, m), abs(_ym(m)[0] - _ym(target)[0]), -_ym(m)[0]))


# --- pools ----------------------------------------------------------------------------------------------------
POOLS = {  # (principal, table): SQL counting the clean pool the block resamples
    ("delmonte", "sales_fact"): "SELECT COUNT(*) FROM public.sales_fact_real WHERE principal = 'delmonte'",
    ("delmonte", "inventory_fact"): f"SELECT COUNT(*) FROM public.inventory_fact_real WHERE principal = 'delmonte' AND {ALPHA}",
    ("delmonte", "salesreturn_fact"): "SELECT COUNT(*) FROM public.salesreturn_fact_real WHERE principal = 'delmonte' AND source IS NULL",
    ("unilever", "inventory_fact"): "SELECT COUNT(*) FROM public.inventory_fact_real WHERE principal = 'unilever' AND _period ~ '^2023-'",
    ("delmonte", "purchase_fact"): "SELECT COUNT(*) FROM public.purchase_fact_real WHERE principal = 'delmonte'",
}


def pool_sizes(cur) -> dict:
    out = {k: rows(cur, sql)[0][0] for k, sql in POOLS.items()}
    out["price-list rows in the Del Monte inventory pool"] = rows(cur, "SELECT COUNT(*) FROM public.inventory_fact_real WHERE _src_sheet ILIKE 'sheet1'")[0][0]
    out["held '(2)' rows in the Del Monte sales pool"] = rows(cur, "SELECT COUNT(*) FROM public.sales_fact_real WHERE _src_sheet = 'PANGASINAN SALES REGISTER (2)'")[0][0]
    return out


# --- blocks -----------------------------------------------------------------------------------------------------
def dm_sales(cur) -> dict:
    targets = [r[0] for r in rows(cur, f"SELECT DISTINCT _period FROM {V2}.sales_fact WHERE principal = 'delmonte' AND is_demo ORDER BY 1")]
    real = dict(rows(cur, "SELECT _period, COUNT(*) FROM public.sales_fact_real WHERE principal = 'delmonte' GROUP BY 1"))
    clash = sorted(set(targets) & set(real))
    if clash:
        raise RuntimeError(f"v2 synthetic sales months that are real in public: {clash}")
    before = rows(cur, f"SELECT COUNT(*) FROM {V2}.sales_fact WHERE principal = 'delmonte' AND is_demo")[0][0]
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {V2}.bk_20260928_dm_sales_demo AS
                    SELECT * FROM {V2}.sales_fact WHERE principal = 'delmonte' AND is_demo""")
    cur.execute(f"DELETE FROM {V2}.sales_fact WHERE principal = 'delmonte' AND is_demo")
    inserted = 0
    for m in targets:
        pool = nearest_moy(m, sorted(real))
        n = int(rng("dm_sales", m).choice([real[p] for p in pool]))
        y, mo = _ym(m)
        cur.execute(f"""
            INSERT INTO {V2}.sales_fact (invoice_num, invoice_date, principal, region, branch_code, customer_key, salesman_key,
                   untaxed_amount, discount_amount, discount_rate_label, tax_amount, net_amount, balance, _outlier_flag,
                   is_demo, _src_file, _src_sheet, _period, quantity_cases, quantity_pieces)
            SELECT 'GEN/' || %(m)s || '/' || lpad(row_number() OVER (ORDER BY r.h)::text, 5, '0'),
                   CASE WHEN r.invoice_date IS NOT NULL THEN make_date(%(y)s, %(mo)s, LEAST(EXTRACT(day FROM r.invoice_date)::int,
                             EXTRACT(day FROM make_date(%(y)s, %(mo)s, 1) + interval '1 month - 1 day')::int)) END,
                   'delmonte', r.region, r.branch_code, vc.customer_key, vs.salesman_key, r.untaxed_amount, r.discount_amount,
                   r.discount_rate_label, r.tax_amount, r.net_amount, r.balance, r._outlier_flag,
                   true, %(src)s, 'GENERATED', %(m)s, r.quantity_cases, r.quantity_pieces
            FROM (SELECT s.*, md5('dm_sales|' || %(m)s || '|' || s.sales_key) AS h FROM public.sales_fact_real s
                  WHERE s.principal = 'delmonte' AND s._period = ANY(%(pool)s) ORDER BY h LIMIT %(n)s) r
            JOIN public.customer_dimension pc ON pc.customer_key = r.customer_key
            JOIN {V2}.customer_dimension vc ON (vc.customer_name, vc.region, vc.principal) IS NOT DISTINCT FROM (pc.customer_name, pc.region, pc.principal)
            JOIN public.salesman_dimension ps ON ps.salesman_key = r.salesman_key
            JOIN {V2}.salesman_dimension vs ON vs.salesman_name IS NOT DISTINCT FROM ps.salesman_name""",
                    {"m": m, "y": y, "mo": mo, "pool": pool, "n": n, "src": f"{TAG}sales_register_{m}"})
        if cur.rowcount != n:
            raise RuntimeError(f"dm_sales {m}: inserted {cur.rowcount}, drew {n}")
        inserted += n
    return {"months": len(targets), "replaced": before, "inserted": inserted}


def dm_inventory(cur) -> dict:
    counts = rows(cur, f"""SELECT m, SUM(pub_demo), SUM(pub_real), SUM(v2_demo) FROM (
        SELECT _period m, COUNT(*) FILTER (WHERE is_demo) pub_demo, COUNT(*) FILTER (WHERE NOT is_demo) pub_real, 0 v2_demo
        FROM public.inventory_fact WHERE principal = 'delmonte' GROUP BY 1
        UNION ALL SELECT _period, 0, 0, COUNT(*) FROM {V2}.inventory_fact WHERE principal = 'delmonte' AND is_demo GROUP BY 1) x
        GROUP BY m ORDER BY m""")
    # P: public has v1 synthetic and no real rows, v2 has at most the 1 stray converted row
    targets = [m for m, pd_, pr, vd in counts if pd_ > 0 and pr == 0 and vd <= 1 and m != "unknown"]
    cur.execute(f"""DELETE FROM {V2}.inventory_fact WHERE principal = 'delmonte' AND is_demo AND _period = ANY(%s)
                    RETURNING sku_code, _period, region, _src_file""", (targets,))
    removed = cur.fetchall()
    return {"months": len(targets), "removed": removed, "inserted": _dm_inventory_months(cur, targets), "targets": targets}


FORWARD = [f"2026-{m:02d}" for m in range(4, 9)]  # the forward block generate_synthetic_backfill.py wrote from staging pools


def dm_inventory_forward(cur) -> dict:
    """The 2026-04..08 forward block, regenerated from the clean pool (same months, SKU x snapshot x site grain)."""
    stale = rows(cur, f"""SELECT COUNT(*) FROM {V2}.inventory_fact WHERE principal = 'delmonte' AND _period = ANY(%s)
                          AND NOT (is_demo AND _src_file ~ '^{TAG}inventory_sign_off_')""", (FORWARD,))[0][0]
    if stale:
        raise RuntimeError(f"dm_inventory_forward: {stale} rows in 2026-04..08 that are not generated synthetic rows")
    cur.execute(f"DELETE FROM {V2}.inventory_fact WHERE principal = 'delmonte' AND is_demo AND _period = ANY(%s)", (FORWARD,))
    return {"months": len(FORWARD), "replaced": cur.rowcount, "inserted": _dm_inventory_months(cur, FORWARD)}


def _dm_inventory_months(cur, targets: list[str]) -> int:
    real = {site: [r[0] for r in rows(cur, f"""SELECT DISTINCT _period FROM public.inventory_fact_real
                   WHERE principal = 'delmonte' AND region = %s AND {ALPHA} ORDER BY 1""", (site,))] for site in SITES}
    inserted = 0
    for m in targets:
        for site in SITES:
            t = template_month(m, real[site])
            cur.execute(f"""
                INSERT INTO {V2}.inventory_fact (product_key, sku_code, snapshot_date, _period, principal, region, quantity_on_hand,
                       quantity_pieces, is_demo, _src_file, _src_sheet, valuation, cost, unit_cost_per_case, blocked_qty_cases,
                       blocked_qty_pieces, stock_status, days_offset, demand_period)
                SELECT vp.product_key, x.sku_code, (%(m)s || '-01')::date, %(m)s, 'delmonte', %(site)s, x.quantity_on_hand,
                       x.quantity_pieces, true, %(src)s, 'GENERATED', x.valuation, x.cost, x.unit_cost_per_case, x.blocked_qty_cases,
                       x.blocked_qty_pieces, x.stock_status, x.days_offset, x.demand_period
                FROM (SELECT DISTINCT sku_code FROM public.inventory_fact_real
                      WHERE principal = 'delmonte' AND region = %(site)s AND _period = %(t)s AND {ALPHA}) k
                CROSS JOIN LATERAL (
                      SELECT f.* FROM public.inventory_fact_real f
                      WHERE f.principal = 'delmonte' AND f.region = %(site)s AND f.sku_code = k.sku_code
                      ORDER BY (right(f._period, 2) = right(%(t)s, 2)) DESC,
                               md5('dm_inventory|' || %(m)s || '|' || %(site)s || '|' || f.inventory_key) LIMIT 1) x
                JOIN {V2}.product_dimension vp ON vp.principal = 'delmonte' AND vp.grain = 'sku' AND vp.sku_code = x.sku_code""",
                        {"m": m, "site": site, "t": t, "src": f"{TAG}inventory_sign_off_{m}_{site}"})
            got = cur.rowcount
            want = rows(cur, f"""SELECT COUNT(DISTINCT sku_code) FROM public.inventory_fact_real
                                 WHERE principal = 'delmonte' AND region = %s AND _period = %s AND {ALPHA}""", (site, t))[0][0]
            if got != want:
                raise RuntimeError(f"dm_inventory {m} {site}: inserted {got}, template {t} has {want} codes")
            inserted += got
    return inserted


def dm_purchases_forward(cur) -> dict:
    """The 2026-04..08 forward purchase block, regenerated from public's real purchases (the 18 quarantined Sept-2025
    lines are in etl_quarantine, not in the pool). Per site: n = a real monthly count of the nearest month-of-year,
    rows from those months without replacement, synthetic bill numbers, day of month kept (clipped). Real purchases
    carry no supplier (supplier_key NULL on every row), so neither do these."""
    stale = rows(cur, f"""SELECT COUNT(*) FROM {V2}.purchase_fact WHERE principal = 'delmonte' AND _period = ANY(%s)
                          AND NOT (is_demo AND _src_file ~ '^{TAG}purchase_order_')""", (FORWARD,))[0][0]
    if stale:
        raise RuntimeError(f"dm_purchases_forward: {stale} rows in 2026-04..08 that are not generated synthetic rows")
    cur.execute(f"DELETE FROM {V2}.purchase_fact WHERE principal = 'delmonte' AND is_demo AND _period = ANY(%s)", (FORWARD,))
    replaced, inserted = cur.rowcount, 0
    for site in SITES:
        real = dict(rows(cur, "SELECT _period, COUNT(*) FROM public.purchase_fact_real WHERE principal = 'delmonte' AND region = %s GROUP BY 1", (site,)))
        for m in FORWARD:
            pool = nearest_moy(m, sorted(real))
            n = int(rng("dm_purchases", m, site).choice([real[p] for p in pool]))
            y, mo = _ym(m)
            cur.execute(f"""
                INSERT INTO {V2}.purchase_fact (invoice_num, invoice_date, principal, region, supplier_key, net_amount, tax_amount,
                       units_received, is_demo, _src_file, _src_sheet, _period)
                SELECT 'GEN-BILL/' || %(m)s || '/' || %(s)s || lpad(row_number() OVER (ORDER BY r.h)::text, 4, '0'),
                       CASE WHEN r.invoice_date IS NOT NULL THEN make_date(%(y)s, %(mo)s, LEAST(EXTRACT(day FROM r.invoice_date)::int,
                            EXTRACT(day FROM make_date(%(y)s, %(mo)s, 1) + interval '1 month - 1 day')::int)) END,
                       'delmonte', %(site)s, vs.supplier_key, r.net_amount, r.tax_amount, r.units_received, true, %(src)s, 'GENERATED', %(m)s
                FROM (SELECT f.*, md5('dm_purchases|' || %(m)s || '|' || %(site)s || '|' || f.purchase_key) AS h
                      FROM public.purchase_fact_real f WHERE f.principal = 'delmonte' AND f.region = %(site)s AND f._period = ANY(%(pool)s)
                      ORDER BY h LIMIT %(n)s) r
                LEFT JOIN public.supplier_dimension ps ON ps.supplier_key = r.supplier_key
                LEFT JOIN {V2}.supplier_dimension vs ON vs.supplier_name = ps.supplier_name""",
                        {"m": m, "s": site[0].upper(), "site": site, "pool": pool, "n": n, "y": y, "mo": mo,
                         "src": f"{TAG}purchase_order_{m}_{site}"})
            if cur.rowcount != n:
                raise RuntimeError(f"dm_purchases_forward {m} {site}: inserted {cur.rowcount}, drew {n}")
            inserted += n
    return {"months": len(FORWARD), "replaced": replaced, "inserted": inserted}


def dm_returns(cur) -> dict:
    clash = rows(cur, f"""SELECT COUNT(*) FROM (SELECT _period FROM public.salesreturn_fact_real WHERE principal = 'delmonte'
                          UNION ALL SELECT _period FROM {V2}.salesreturn_fact WHERE principal = 'delmonte' AND is_demo
                          AND _src_file !~ '^{TAG}sales_return_20(21|22)-') x WHERE _period = ANY(%s)""", (MONTHS_2122,))[0][0]
    if clash:
        raise RuntimeError(f"dm_returns: {clash} rows already in 2021-22")
    cur.execute(f"DELETE FROM {V2}.salesreturn_fact WHERE principal = 'delmonte' AND is_demo AND _period = ANY(%s)", (MONTHS_2122,))
    inserted = 0
    for site in SITES:
        real = dict(rows(cur, """SELECT _period, COUNT(*) FROM public.salesreturn_fact_real
                                 WHERE principal = 'delmonte' AND source IS NULL AND region = %s GROUP BY 1""", (site,)))
        for m in MONTHS_2122:
            pool = nearest_moy(m, sorted(real))
            n = int(rng("dm_returns", m, site).choice([real[p] for p in pool]))
            s = site[0].upper()
            cur.execute(f"""
                INSERT INTO {V2}.salesreturn_fact (return_slip_num, invoice_num, return_type, return_date, principal, region, net_amount,
                       bo_units, is_demo, _src_file, _src_sheet, _period, quantity_cases, quantity_pieces)
                SELECT 'GEN-RS/' || %(m)s || '/' || %(s)s || lpad(row_number() OVER (ORDER BY r.h)::text, 4, '0'),
                       'GEN-INV/' || %(m)s || '/' || %(s)s || 'R' || lpad(row_number() OVER (ORDER BY r.h)::text, 4, '0'),
                       r.return_type, NULL, 'delmonte', %(site)s, r.net_amount, NULL, true, %(src)s, 'GENERATED', %(m)s,
                       r.quantity_cases, r.quantity_pieces
                FROM (SELECT f.*, md5('dm_returns|' || %(m)s || '|' || %(site)s || '|' || f.return_key) AS h
                      FROM public.salesreturn_fact_real f WHERE f.principal = 'delmonte' AND f.source IS NULL AND f.region = %(site)s
                        AND f._period = ANY(%(pool)s) ORDER BY h LIMIT %(n)s) r""",
                        {"m": m, "s": s, "site": site, "pool": pool, "n": n, "src": f"{TAG}sales_return_{m}_{site}"})
            if cur.rowcount != n:
                raise RuntimeError(f"dm_returns {m} {site}: inserted {cur.rowcount}, drew {n}")
            inserted += n
    return {"months": len(MONTHS_2122), "inserted": inserted}


def uni_inventory(cur) -> dict:
    existing = rows(cur, f"""SELECT COUNT(*) FROM {V2}.inventory_fact WHERE principal = 'unilever' AND _period = ANY(%s)
                             AND NOT (is_demo AND _src_file ~ '^{TAG}unilever_inventory_')""", (MONTHS_2122,))[0][0]
    if existing:
        raise RuntimeError(f"uni_inventory: {existing} non-generated rows already in 2021-22")
    cur.execute(f"DELETE FROM {V2}.inventory_fact WHERE principal = 'unilever' AND is_demo AND _period = ANY(%s)", (MONTHS_2122,))
    cur.execute(f"""
        INSERT INTO {V2}.inventory_fact (product_key, sku_code, snapshot_date, _period, principal, region, quantity_on_hand, quantity_pieces,
               is_demo, _src_file, _src_sheet, valuation, cost, unit_cost_per_case, blocked_qty_cases, blocked_qty_pieces, stock_status,
               days_offset, demand_period)
        SELECT vp.product_key, r.sku_code, (r.snapshot_date - make_interval(years => 2023 - left(g.m, 4)::int))::date, g.m, 'unilever',
               r.region, r.quantity_on_hand, r.quantity_pieces, true, '{TAG}unilever_inventory_' || g.m, 'GENERATED', r.valuation, r.cost,
               r.unit_cost_per_case, r.blocked_qty_cases, r.blocked_qty_pieces, r.stock_status, r.days_offset, r.demand_period
        FROM (SELECT sku_code, MIN(calendar_month) AS first_m, MAX(calendar_month) AS last_m FROM {V2}.unilever_sku_demand_fact
              WHERE is_demo AND calendar_month <= '2022-12' GROUP BY 1) s
        JOIN unnest(%s::text[]) AS g(m) ON g.m BETWEEN s.first_m AND s.last_m
        JOIN public.inventory_fact_real r ON r.principal = 'unilever' AND r.sku_code = s.sku_code AND r._period = '2023-' || right(g.m, 2)
        JOIN {V2}.product_dimension vp ON vp.principal = 'unilever' AND vp.grain = 'sku' AND vp.sku_code = r.sku_code""", (MONTHS_2122,))
    inserted = cur.rowcount
    skus = rows(cur, f"SELECT COUNT(DISTINCT sku_code) FROM {V2}.inventory_fact WHERE principal = 'unilever' AND is_demo AND _period = ANY(%s)", (MONTHS_2122,))[0][0]
    return {"months": len(MONTHS_2122), "inserted": inserted, "skus": skus}


BLOCKS = {"dm_sales": dm_sales, "dm_inventory": dm_inventory, "dm_returns": dm_returns, "uni_inventory": uni_inventory,
          "dm_inventory_forward": dm_inventory_forward, "dm_purchases_forward": dm_purchases_forward}


# --- the simulated cutover: public real rows + v2 synthetic rows (apply_synth_v2_to_public replaces every public
# synthetic row with v2's) ----------------------------------------------------------------------------------------
GRID = [  # (principal, table, month expression)
    ("delmonte", "sales_fact", "_period"), ("delmonte", "salesreturn_fact", "_period"), ("delmonte", "sellout_fact", "_period"),
    ("delmonte", "inventory_fact", "_period"), ("delmonte", "purchase_fact", "_period"),
    ("unilever", "unilever_sku_demand_fact", "calendar_month"), ("unilever", "inventory_fact", "_period"),
]
ALL_MONTHS = [f"{y}-{m:02d}" for y in range(2021, 2027) for m in range(1, 13) if f"{y}-{m:02d}" <= "2026-09"]
# apply_synth_v2_to_public.DIMENSIONS["product_dimension"], the natural key the cutover maps product_key on
PRODUCT_ON = ("p.principal = v.principal AND p.grain = v.grain AND p.sku_code IS NOT DISTINCT FROM v.sku_code "
              "AND (v.grain = 'sku' OR p.category_path IS NOT DISTINCT FROM v.category_path)")


def month_counts(cur, schema: str, principal: str, table: str, month: str) -> dict:
    where = "TRUE" if table == "unilever_sku_demand_fact" else f"principal = '{principal}'"
    out = {}
    for m, demo, n in rows(cur, f"SELECT {month}, is_demo, COUNT(*) FROM {schema}.{table} WHERE {where} GROUP BY 1, 2"):
        out.setdefault(m, [0, 0])[1 if demo else 0] += n
    return out


def simulate(cur) -> dict:
    grid = {}
    for principal, table, month in GRID:
        pub, v2 = month_counts(cur, "public", principal, table, month), month_counts(cur, V2, principal, table, month)
        cells = {}
        for m in ALL_MONTHS:
            real, pub_demo, v2_demo = pub.get(m, [0, 0])[0], pub.get(m, [0, 0])[1], v2.get(m, [0, 0])[1]
            after = "B" if real and v2_demo else "R" if real else "S" if v2_demo else "N"
            cells[m] = {"real": real, "pub_demo": pub_demo, "v2_demo": v2_demo, "after": after, "covered_today": bool(real or pub_demo)}
        grid[(principal, table)] = {"cells": cells, "unknown_pub_demo": pub.get("unknown", [0, 0])[1], "unknown_v2_demo": v2.get("unknown", [0, 0])[1]}
    return grid


def runs(cells: dict) -> list:
    out = []
    for m in ALL_MONTHS:
        c = cells[m]
        if out and out[-1][0] == c["after"]:
            out[-1][2] = m; out[-1][3] += c["real"] + c["v2_demo"]
        else:
            out.append([c["after"], m, m, c["real"] + c["v2_demo"]])
    return out


def checks(cur) -> list:
    grid = simulate(cur)
    res = []
    for (principal, table), g in grid.items():
        cells = g["cells"]
        res.append((f"{principal} {table}: synthetic rows in a REAL table-month after cutover",
                    sum(c["v2_demo"] for c in cells.values() if c["real"]), 0))
        res.append((f"{principal} {table}: table-months covered today that become N",
                    [m for m, c in cells.items() if c["covered_today"] and c["after"] == "N"], []))
        res.append((f"{principal} {table}: N table-months in 2021-01..2022-12",
                    [m for m in MONTHS_2122 if cells[m]["after"] == "N"], []))
        res.append((f"{principal} {table}: v2 synthetic rows with _period 'unknown'", g["unknown_v2_demo"], 0))
    so = grid[("delmonte", "sellout_fact")]["cells"]
    res.append(("the 504 v1 sell-out rows in real months: public synthetic rows there / v2 synthetic rows there",
                [sum(c["pub_demo"] for c in so.values() if c["real"]), sum(c["v2_demo"] for c in so.values() if c["real"])], [504, 0]))
    res.append(("the 117 purchase rows with _period 'unknown': in public (removed at cutover) / in v2",
                [grid[("delmonte", "purchase_fact")]["unknown_pub_demo"], grid[("delmonte", "purchase_fact")]["unknown_v2_demo"]], [117, 0]))
    facts = ["sales_fact", "salesreturn_fact", "sellout_fact", "inventory_fact", "purchase_fact", "unilever_sku_demand_fact"]
    real_flagged = sum(rows(cur, f"SELECT COUNT(*) FROM {V2}.{t} WHERE NOT is_demo AND _src_file ~ %s", (SYNTH_SRC,))[0][0] for t in facts)
    res.append(("v2 rows from a synthetic source flagged real", real_flagged, 0))
    res.append(("v2 GENERATED_BACKFILL_ rows not is_demo", sum(rows(cur, f"SELECT COUNT(*) FROM {V2}.{t} WHERE _src_file ~ '^{TAG}' AND NOT is_demo")[0][0] for t in facts), 0))
    # the loader's sell-out defect merge sums synthetic rows into one row per (region, period, is_demo) under this name
    agg = "AGGREGATED_source_file_defect_category"
    res.append(("v2 synthetic rows without a synthetic source (loader-merged sell-out rows excluded)",
                sum(rows(cur, f"SELECT COUNT(*) FROM {V2}.{t} WHERE is_demo AND (_src_file IS NULL OR _src_file !~ %s) AND _src_file <> %s",
                         (SYNTH_SRC, agg))[0][0] for t in facts), 0))
    res.append(("REPORT v2 loader-merged synthetic sell-out rows (_src_file AGGREGATED_..., is_demo inherited)",
                rows(cur, f"SELECT COUNT(*) FILTER (WHERE is_demo), COUNT(*) FILTER (WHERE NOT is_demo) FROM {V2}.sellout_fact WHERE _src_file = %s", (agg,))[0], None))
    # the cutover maps every FK by natural key into public; an unmatched key would abort it
    for t, fk, dim, key, on in [
            ("sales_fact", "customer_key", "customer_dimension", "customer_key", "(p.customer_name, p.region, p.principal) IS NOT DISTINCT FROM (v.customer_name, v.region, v.principal)"),
            ("sales_fact", "salesman_key", "salesman_dimension", "salesman_key", "p.salesman_name IS NOT DISTINCT FROM v.salesman_name"),
            ("inventory_fact", "product_key", "product_dimension", "product_key", PRODUCT_ON),
            ("sellout_fact", "product_key", "product_dimension", "product_key", PRODUCT_ON),
            ("unilever_sku_demand_fact", "product_key", "product_dimension", "product_key", PRODUCT_ON),
            ("purchase_fact", "supplier_key", "supplier_dimension", "supplier_key", "p.supplier_name IS NOT DISTINCT FROM v.supplier_name")]:
        n = rows(cur, f"""SELECT COUNT(*) FROM {V2}.{t} f JOIN {V2}.{dim} v ON v.{key} = f.{fk} WHERE f.is_demo
                          AND NOT EXISTS (SELECT 1 FROM public.{dim} p WHERE {on})""")[0][0]
        res.append((f"v2 synthetic {t}.{fk} with no public {dim} row (the cutover would abort)", n, 0))
    s = rows(cur, f"SELECT COUNT(*), COALESCE(SUM(net_amount), 0)::text FROM {V2}.sales_fact WHERE principal = 'delmonte' AND is_demo AND _period = '2024-09'")[0]
    res.append(("REPORT v2 synthetic Del Monte sales 2024-09 (remove if SSM confirms the '(2)' sheet is Sep-2024)", list(s), None))
    return res


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pools", action="store_true")
    p.add_argument("--write", nargs="+", choices=list(BLOCKS), default=None)
    p.add_argument("--checks", action="store_true")
    p.add_argument("--grid", action="store_true", help="print the simulated post-cutover grid as runs")
    args = p.parse_args()
    conn = connect()
    cur = conn.cursor()
    try:
        if args.pools:
            for k, v in pool_sizes(cur).items():
                print(f"  pool {k}: {v}")
        for block in args.write or []:
            result = BLOCKS[block](cur)
            conn.commit()
            print(f"  {block}: committed {({k: v for k, v in result.items() if k not in ('removed', 'targets')})}"
                  + (f" removed {result['removed']}" if result.get("removed") else ""))
        if args.checks:
            failed = 0
            for name, got, want in checks(cur):
                ok = want is None or str(got) == str(want)
                failed += not ok
                print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}")
            conn.rollback()
            return 1 if failed else 0
        if args.grid:
            for (principal, table), g in simulate(cur).items():
                print(f"  {principal} {table}: " + " | ".join(f"{a[2:]}{'..' + b[2:] if b != a else ''} {c} {n:,}" for c, a, b, n in runs(g["cells"])))
            conn.rollback()
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
