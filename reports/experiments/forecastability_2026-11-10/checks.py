"""
reports/experiments/forecastability_2026-11-10/checks.py - the three checks that decide whether a company-wide level
correction is the right fix at all (2026-11-10). BACKTEST ONLY: reads the throwaway copy ssm_challenger
(127.0.0.1:55432, a restore of backups/full_backup_20261104T175951Z) in one READ ONLY transaction, writes one JSON of
aggregates. Refuses any other database.

    SUPABASE_DB_URL=postgresql://postgres@127.0.0.1:55432/ssm_challenger \
    PYTHONPATH=<a folder holding holidays 0.108> python reports/experiments/forecastability_2026-11-10/checks.py

1. PACK MIX. Unilever_SKU_Demand_Fact_Real, every real row with a quantity (all products, not only Tier A).
   - Price: each SKU's peso per piece, matched SKUs, period B over period A (value-weighted and quantiles).
   - Constant-price value Q = sum_i q_i x p_i, p_i = the SKU's median monthly peso per piece over its whole real history.
     With prices flat inside each SKU, Q moves only with what is bought: the standard quantity index.
   - Pieces P = sum q. u = Q / P = average constant value per piece. ln(P_B/P_A) = ln(Q_B/Q_A) - ln(u_B/u_A).
   - u = sum_f s_f u_f over families f (s_f = family share of pieces). Midpoint shift-share:
       between families (customers moving between products)    sum_f (s_fB - s_fA) x (u_fA + u_fB)/2
       within families  (customers moving between pack sizes)  sum_f (s_fA + s_fB)/2 x (u_fB - u_fA)
     apportioned to ln(u_B/u_A) in proportion. A family present in one period only keeps its one u_f.
   - Two family keys, both reported: COARSE = brand x category_path; FINE = brand x category x the first two words of
     the name once sizes, pack/format words and promo words are dropped and common abbreviations expanded (heuristic).
   - Content check inside FINE families whose packs all parse to one unit (G or ML): pieces vs grams/ml.
   Periods: YoY Sep 2024-Feb 2025 -> Sep 2025-Feb 2026 (same calendar months), the step Mar-Jun 2025 -> Jul 2025-Feb 2026,
   and FY2024 -> FY2025.
2. STOCK-OUTS. mart.accuracy_mart run 11 (the as-served backtest, calendar-adjusted = forecast_challenger backtest):
   product-months with direction 'over', with possibly_stock_limited (migration 0043: opening or closing count 0 or
   under 1 week of average sales), and the strict subset whose closing count is zero.
3. DECEMBER WORKING DAYS. Philippine public holidays (regular + special non-working) from the `holidays` package,
   version recorded in the output. Mon-Sat and Mon-Fri both counted (SSM's trading days are not on record).
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2

OUT = Path(__file__).resolve().parent

PERIODS = {
    "yoy Sep24-Feb25 -> Sep25-Feb26": (("2024-09", "2025-02"), ("2025-09", "2026-02")),
    "step Mar-Jun25 -> Jul25-Feb26": (("2025-03", "2025-06"), ("2025-07", "2026-02")),
    "FY2024 -> FY2025": (("2024-01", "2024-12"), ("2025-01", "2025-12")),
}

# Pack/format/promo words dropped from the FINE family key; abbreviations expanded first.
ABBR = {"MNTHL": "MENTHOL", "FRSH": "FRESH", "BLOSSM": "BLOSSOM", "KRTN": "KERATIN", "KRATIN": "KERATIN",
        "STRT": "STRAIGHT", "ST": "STRAIGHT", "HF": "HAIRFALL", "HFALL": "HAIRFALL", "RBOND": "REBOND",
        "PWD": "POWDER", "ACBLCH": "ACTIVEBLEACH", "CUBES": "CUBE", "ROSEFRSH": "ROSE FRESH",
        "SUNFRESH": "SUN FRESH", "SPRT": "SPORT", "MYNS": "MAYONNAISE", "DRSG": "DRESSING"}
DROP = {"BN", "BLN", "SINGLES", "SNGLS", "PANTRY", "SAVERS", "SACH", "SCH", "STR", "SOL", "PCH", "POU", "MP", "DUO",
        "DUA", "DUA2", "PROMO", "PRMO", "PRM", "N", "HL", "NEW", "L", "S", "SIX", "ATL", "DOY", "DISPENSERS", "RLN",
        "RL", "ULP", "TKR", "RO", "HC", "TMT", "CP", "SH", "STD", "HS", "3C", "+", "X"}


def url() -> str:
    u = os.environ.get("SUPABASE_DB_URL", "")
    p = urlparse(u)
    if p.hostname not in ("127.0.0.1", "localhost") or p.port != 55432:
        sys.exit("refusing: this backtest reads only the throwaway copy on 127.0.0.1:55432")
    return u


def fine_key(name: str, brand: str, cat: str) -> str:
    n = re.sub(r"[​]", "", name.upper())
    toks = []
    for t in re.split(r"\s+", n):
        if not t or re.search(r"\d", t):
            continue
        for w in ABBR.get(t, t).split():
            toks.append(w)
    b = brand.upper().replace("CREAMSILK", "CREAM SILK").replace("CLOSEUP", "CLOSE UP").split()
    while toks and b and toks[0] in (b[0], "CLOSEUP", "CREAMSILK"):
        toks.pop(0)
        if b and toks and toks[0] in b[1:]:
            toks.pop(0)
        b = []
    toks = [t for t in toks if t not in DROP]
    return f"{brand}|{cat}|{' '.join(toks[:2])}"


def content(name: str) -> tuple[float, str] | None:
    """Content of one piece from the trailing size of the name: '24X12X11G' -> (11, 'G'), '6X1.6L' -> (1600, 'ML'),
    '4X3.6KG' -> (3600, 'G'). Bundles '(6+1)' and doubled '(66G+66G)' are left unparsed (None)."""
    n = name.upper().replace("​", "")
    if "+" in n and re.search(r"\(\d+G\+\d+G\)|\(\d+\+\d+\)", n):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(KG|G|ML|L)\s*$", n)
    if not m:
        return None
    v, unit = float(m.group(1)), m.group(2)
    if unit == "KG":
        return v * 1000, "G"
    if unit == "L":
        return v * 1000, "ML"
    return v, unit


def read(u: str):
    conn = psycopg2.connect(u)
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute("""SELECT d.product_key, left(d.calendar_month, 7), SUM(d.quantity_sold), SUM(d.net_amount),
                          p.product_name, COALESCE(p.brand, '?'), COALESCE(p.category_path, 'UNCLASSIFIED'), p.sku_code
                   FROM unilever_sku_demand_fact_real d JOIN product_dimension p USING (product_key)
                   WHERE d.quantity_sold IS NOT NULL GROUP BY 1, 2, 5, 6, 7, 8""")
    sku = pd.DataFrame(cur.fetchall(), columns=["k", "m", "q", "v", "name", "brand", "cat", "sku"]).astype({"q": float, "v": float})
    cur.execute("""SELECT a.month, a.product_key, a.direction, a.possibly_stock_limited, a.stock_limited_reason,
                          a.forecast_pieces, a.actual_pieces
                   FROM mart.accuracy_mart a WHERE a.run_id = 11""")
    acc = pd.DataFrame(cur.fetchall(), columns=["month", "k", "direction", "limited", "reason", "f", "a"])
    cur.execute("SELECT DISTINCT run_label FROM mart.accuracy_mart WHERE run_id = 11")
    label = cur.fetchone()[0]
    cur.execute("""SELECT DISTINCT product_key FROM lp_recommendation WHERE planning_cycle_date = '2026-03-01'
                   AND lp_run_key = (SELECT MAX(lp_run_key) FROM lp_recommendation WHERE planning_cycle_date = '2026-03-01')""")
    planned = {int(r[0]) for r in cur.fetchall()}
    conn.rollback()
    conn.close()
    return sku, acc, label, planned


def in_period(m: pd.Series, p: tuple[str, str]) -> pd.Series:
    return (m >= p[0]) & (m <= p[1])


def pack_mix(sku: pd.DataFrame) -> dict:
    ok = (sku.q > 0) & (sku.v > 0)
    price = (sku[ok].v / sku[ok].q).groupby(sku[ok].k).median()
    sku = sku.assign(p=sku.k.map(price)).dropna(subset=["p"])
    sku["Q"] = sku.q * sku.p
    meta = sku.drop_duplicates("k").set_index("k")
    meta["fine"] = [fine_key(n, b, c) for n, b, c in zip(meta.name, meta.brand, meta.cat)]
    meta["coarse"] = meta.brand + "|" + meta.cat
    cnt = [content(n) for n in meta.name]
    meta["c"] = [x[0] if x else np.nan for x in cnt]
    meta["unit"] = [x[1] if x else None for x in cnt]
    sku = sku.join(meta[["fine", "coarse", "c", "unit"]], on="k")
    out = {"base_price": "each SKU's median monthly peso per piece over its real history",
           "families": {"coarse": int(meta.coarse.nunique()), "fine": int(meta.fine.nunique())}}
    for pname, (A, B) in PERIODS.items():
        a, b = sku[in_period(sku.m, A)], sku[in_period(sku.m, B)]
        # Prices inside each SKU, matched SKUs.
        ga = a.groupby("k")[["q", "v"]].sum()
        gb = b.groupby("k")[["q", "v"]].sum()
        J = ga.join(gb, lsuffix="A", rsuffix="B", how="inner")
        J = J[(J.qA > 0) & (J.qB > 0) & (J.vA > 0) & (J.vB > 0)]
        r = (J.vB / J.qB) / (J.vA / J.qA)
        price = {"matched_skus": int(len(J)), "value_weighted_price_ratio": round(float(J.vB.sum() / (J.qB * J.vA / J.qA).sum()), 4),
                 "median": round(float(r.median()), 4), "p05": round(float(r.quantile(.05)), 4), "p95": round(float(r.quantile(.95)), 4)}
        months_a, months_b = a.m.nunique(), b.m.nunique()
        PA, PB = a.q.sum() / months_a, b.q.sum() / months_b
        QA, QB = a.Q.sum() / months_a, b.Q.sum() / months_b
        VA, VB = a.v.sum() / months_a, b.v.sum() / months_b
        dlnP, dlnQ = np.log(PB / PA), np.log(QB / QA)
        dlnu = dlnQ - dlnP
        res = {"months": [int(months_a), int(months_b)],
               "pieces_per_month": [round(PA), round(PB)], "pesos_per_month": [round(VA), round(VB)],
               "constant_price_value_per_month": [round(QA), round(QB)],
               "pct_change": {"pieces": round(100 * (PB / PA - 1), 1), "pesos": round(100 * (VB / VA - 1), 1),
                              "constant_price_value": round(100 * (QB / QA - 1), 1)},
               "price_inside_sku": price, "log_points": {"pieces": round(float(dlnP), 4), "real_value": round(float(dlnQ), 4),
                                                         "mix_total": round(float(-dlnu), 4)}}
        for key in ("coarse", "fine"):
            fa = a.groupby(key)[["q", "Q"]].sum() / months_a
            fb = b.groupby(key)[["q", "Q"]].sum() / months_b
            F = fa.join(fb, lsuffix="A", rsuffix="B", how="outer").fillna(0.0)
            F["sA"], F["sB"] = F.qA / F.qA.sum(), F.qB / F.qB.sum()
            F["uA"] = np.where(F.qA > 0, F.QA / F.qA.replace(0, np.nan), np.nan)
            F["uB"] = np.where(F.qB > 0, F.QB / F.qB.replace(0, np.nan), np.nan)
            F["uA"] = F.uA.fillna(F.uB)
            F["uB"] = F.uB.fillna(F.uA)
            between = float(((F.sB - F.sA) * (F.uA + F.uB) / 2).sum())
            within = float(((F.sA + F.sB) / 2 * (F.uB - F.uA)).sum())
            du = between + within
            # Share of the piece decline (in log points, -dlnP) taken by each part.
            res[f"decomposition_{key}"] = {
                "real_value_decline_share": round(float(dlnQ / dlnP), 3),
                "between_family_mix_share": round(float((dlnu * between / du) / -dlnP), 3),
                "within_family_pack_mix_share": round(float((dlnu * within / du) / -dlnP), 3)}
        # Content inside FINE families whose packs all parse to one unit: pieces vs content.
        single = meta.groupby("fine").filter(lambda g: g.unit.notna().all() and g.unit.nunique() == 1 and len(g) >= 2).fine.unique()
        s_a = a[a.fine.isin(single)].assign(C=lambda x: x.q * x.c)
        s_b = b[b.fine.isin(single)].assign(C=lambda x: x.q * x.c)
        res["content_in_parsed_multi_pack_families"] = {
            "families": int(len(single)),
            "share_of_period_A_pieces": round(float(s_a.q.sum() / a.q.sum()), 3),
            "pieces_pct": round(100 * ((s_b.q.sum() / months_b) / (s_a.q.sum() / months_a) - 1), 1),
            "content_pct": round(100 * ((s_b.C.sum() / months_b) / (s_a.C.sum() / months_a) - 1), 1),
            "constant_price_value_pct": round(100 * ((s_b.Q.sum() / months_b) / (s_a.Q.sum() / months_a) - 1), 1)}
        out[pname] = res
    # The families the brief names, period yoy.
    A, B = PERIODS["yoy Sep24-Feb25 -> Sep25-Feb26"]
    named = {"Knorr Sinigang (67749041, 67749043, 67749045)": meta.sku.isin(["67749041", "67749043", "67749045"]),
             "Knorr cubes (KNORR, name has CUBE)": (meta.brand == "KNORR") & meta.name.str.contains("CUBE"),
             "Surf powder (SURF, name has POWDER)": (meta.brand == "SURF") & meta.name.str.contains("POWDER"),
             "Surf fabcon Blossom Fresh": (meta.brand == "SURF") & meta.name.str.contains("FABCON BLOSSOM")}
    nf, per_code = {}, {}
    for label, mask in named.items():
        ks = set(meta.index[mask])
        a, b = sku[in_period(sku.m, A) & sku.k.isin(ks)], sku[in_period(sku.m, B) & sku.k.isin(ks)]
        rows = []
        for k in sorted(ks):
            qa, qb = a[a.k == k].q.sum() / 6, b[b.k == k].q.sum() / 6
            if qa or qb:
                rows.append({"sku": meta.at[k, "sku"], "name": meta.at[k, "name"], "pieces_per_month": [round(qa), round(qb)]})
        ca, cb = (a.q * a.c).sum(), (b.q * b.c).sum()
        nf[label] = {"codes_selling": len(rows), "pieces_pct": round(100 * (b.q.sum() / a.q.sum() - 1), 1) if a.q.sum() else None,
                     "constant_price_value_pct": round(100 * (b.Q.sum() / a.Q.sum() - 1), 1) if a.Q.sum() else None,
                     "content_pct_parsed_codes": round(100 * (cb / ca - 1), 1) if ca else None}
        per_code[label] = rows
    out["named_families_yoy"] = nf
    # Per-code pieces are per-product sales: git-ignored local/ only (hard rule 9).
    (OUT.parents[2] / "local" / "forecastability_named_families_2026-11-10.json").write_text(
        json.dumps(per_code, indent=1), encoding="utf-8")
    # Monthly company series for the README: pieces, pesos, constant-price value, value per piece.
    mon = sku.groupby("m")[["q", "v", "Q"]].sum()
    out["monthly"] = {m: {"pieces": round(r.q), "pesos": round(r.v), "constant_price_value": round(r.Q),
                          "constant_value_per_piece": round(r.Q / r.q, 2)} for m, r in mon.iterrows()}
    return out


def stockouts(acc: pd.DataFrame, label: str, planned: set) -> dict:
    out = {"run": label, "flag": "possibly_stock_limited (0043): opening or closing count 0 or under 1 week of average sales",
           "caveat": "stock counts and SKU sales may not cover the same branch (Ilocos Sur counts vs La Union sales, UNVERIFIED, memory lp-logic-check)"}
    for w, (a, b) in {"main 2025-09..2026-02": ("2025-09", "2026-02"), "earlier 2024-01..2025-08": ("2024-01", "2025-08")}.items():
        d = acc[(acc.month >= a) & (acc.month <= b)]
        res = {}
        for sname, s in {"all": d, "planned": d[d.k.isin(planned)]}.items():
            over = s[s.direction == "over"]
            under = s[s.direction == "under"]
            closing0 = over.reason.fillna("").str.contains("closing zero")
            res[sname] = {"product_months": int(len(s)), "over": int(len(over)),
                          "over_flagged": int(over.limited.sum()),
                          "over_flagged_pct": round(100 * over.limited.mean(), 1),
                          "over_closing_count_zero": int(closing0.sum()),
                          "over_excess_pieces": round(float((over.f - over.a).sum())),
                          "over_excess_pieces_in_flagged_months": round(float((over.f - over.a)[over.limited.astype(bool)].sum())),
                          "over_excess_pieces_closing_zero": round(float((over.f - over.a)[closing0].sum())),
                          "under_flagged_pct": round(100 * under.limited.mean(), 1)}
        out[w] = res
    return out


def working_days(holidays_mod, sales: dict) -> dict:
    out = {"source": f"holidays {holidays_mod.__version__}, holidays.PH(categories=('public',)): regular + special non-working days"}
    rows = {}
    for y in (2023, 2024, 2025):
        ph = holidays_mod.PH(years=y, categories=("public",))
        for mth in (9, 10, 11, 12):
            d0 = date(y, mth, 1)
            d1 = date(y + (mth == 12), mth % 12 + 1, 1)
            days = [d0 + timedelta(i) for i in range((d1 - d0).days)]
            rows[f"{y}-{mth:02d}"] = {"mon_sat": sum(d.weekday() < 6 and d not in ph for d in days),
                                      "mon_fri": sum(d.weekday() < 5 and d not in ph for d in days),
                                      "holidays_on_mon_sat": sorted(str(d) for d in days if d in ph and d.weekday() < 6)}
    out["months"] = rows
    out["december_vs_prior3"] = {}
    for y in (2023, 2024, 2025):
        prior = [f"{y}-{m:02d}" for m in (9, 10, 11)]
        dec = f"{y}-12"
        r = {}
        for basis in ("mon_sat", "mon_fri"):
            wd = rows[dec][basis] / np.mean([rows[p][basis] for p in prior])
            r[f"working_days_ratio_{basis}"] = round(float(wd), 3)
        s = sales[dec] / np.mean([sales[p] for p in prior])
        r["pieces_ratio"] = round(float(s), 3)
        r["pieces_per_working_day_ratio_mon_sat"] = round(float(s / r["working_days_ratio_mon_sat"]), 3)
        r["pieces_per_working_day_ratio_mon_fri"] = round(float(s / r["working_days_ratio_mon_fri"]), 3)
        out["december_vs_prior3"][str(y)] = r
    return out


def main() -> int:
    import holidays  # noqa: PLC0415 - only this check needs it; the version is recorded
    sku, acc, label, planned = read(url())
    res = {"pack_mix": pack_mix(sku), "stockouts": stockouts(acc, label, planned)}
    pieces = sku.groupby("m").q.sum().to_dict()
    res["working_days"] = working_days(holidays, pieces)
    (OUT / "results_checks.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    view = {k: v for k, v in res["pack_mix"].items() if k != "monthly"}
    print(json.dumps({"pack_mix": view, "stockouts": res["stockouts"],
                      "working_days": res["working_days"]["december_vs_prior3"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
