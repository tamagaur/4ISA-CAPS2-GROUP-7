"""
SIMULATION - real + 2021-22 placeholder data; not served, not used in the LP or in accuracy claims.

Question (for the TA): what happens if the 2021-22 placeholder history is added?

SCOPE: Del Monte has no product-level sales, so it is not forecast. The product-level
simulation is Unilever-only; Del Monte gets a category-level and coverage view.

Read-only: one READ ONLY transaction, rolled back. Nothing is written to the database and
nothing here feeds Forecast_Result, the LP or the paper's accuracy figures.

A. Unilever, Tier A as of 2026-02 (ABC 'single', 132 SKUs)
   REAL        real rows 2023-01..2026-02 (Unilever_SKU_Demand_Fact_Real) - the live run; must
               reproduce public.forecast_result (132/132 rows, stored MASE) or the script stops.
   SIMULATION  the same rows PLUS the is_demo rows dated 2021-01..2022-12 (base table, the only
               place they live). The 2026-03..08 placeholder gap rows are excluded.
   Same router, same settings (analytics/forecasting/router.py, Tier A training pool, XGBoost
   nthread=1, seed 20260921), run twice. Both runs are scored on the SAME months and the SAME
   scale: the common window 2025-09..2026-02 with the lag-1 naive scale of the REAL months
   before 2025-09, or - for SKUs the common window cannot score - the stored 20% split of the
   REAL series and its REAL training scale. Each run holds its own served bin fixed.
B. Del Monte, category level, descriptive: months of real vs placeholder data per table;
   whole-window category revenue shares and ABC tiers, real only vs real + 2021-22; and a
   month-of-year sales index with and without the 2021-22 placeholder years.

    .venv/Scripts/python.exe reports/simulation/synthetic_2026-10/run_simulation.py [--cache FILE]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "reports", "diagnostics", "fit_diagnosis_2026-10"))

import run_fit_diagnosis as F  # noqa: E402  (the shared real-data harness)
from analytics.classification.abc import classify_abc  # noqa: E402
from analytics.forecasting.diagnostic_metrics import mase  # noqa: E402

LABEL = "SIMULATION — real + 2021–22 placeholder data; not served, not used in the LP or in accuracy claims"
SCOPE = ("Del Monte has no product-level sales, so it is not forecast. Product-level simulation and fit "
         "diagnosis are Unilever-only; Del Monte gets the category-level and coverage view.")
DM_TABLES = ("sales_fact", "sellout_fact", "purchase_fact", "salesreturn_fact", "inventory_fact")


# --------------------------------------------------------------------------- #
# Loading (one read-only transaction)
# --------------------------------------------------------------------------- #
def load_all(cur) -> dict:
    out = F.load_inputs(cur, with_placeholder_2021_22=True)
    dm = {}
    for t in DM_TABLES:
        cur.execute(f"SELECT is_demo, _period, count(*) FROM {t} WHERE principal = 'delmonte' GROUP BY 1, 2 ORDER BY 2")
        dm[t] = pd.DataFrame(cur.fetchall(), columns=["is_demo", "period", "rows"])
    # category revenue, ABC's own source (SellOut_Fact, net_amount per category product row);
    # real rows from every month, placeholder rows from 2021-22 only
    cur.execute("""
        SELECT COALESCE(product_key::text, 'path:' || category_path) AS cat, min(category_path) AS category_path,
               is_demo, sum(net_amount)::float AS revenue
        FROM sellout_fact
        WHERE principal = 'delmonte' AND (is_demo = false OR _period BETWEEN '2021-01' AND '2022-12')
        GROUP BY 1, 3""")
    dm["category_revenue"] = pd.DataFrame(cur.fetchall(), columns=["cat", "category_path", "is_demo", "revenue"])
    for t in ("sales_fact", "sellout_fact"):
        cur.execute(f"""
            SELECT _period, is_demo, sum(net_amount)::float FROM {t}
            WHERE principal = 'delmonte' AND (is_demo = false OR _period BETWEEN '2021-01' AND '2022-12')
            GROUP BY 1, 2 ORDER BY 1""")
        dm[f"monthly_{t}"] = pd.DataFrame(cur.fetchall(), columns=["period", "is_demo", "net_amount"])
    cur.execute("""
        SELECT is_demo, _period >= '2025-01' AS from_2025, category_path, sum(net_amount)::float
        FROM sellout_fact
        WHERE principal = 'delmonte' AND (is_demo = false OR _period BETWEEN '2021-01' AND '2022-12')
        GROUP BY 1, 2, 3""")
    dm["category_vocab"] = pd.DataFrame(cur.fetchall(), columns=["is_demo", "from_2025", "category_path", "revenue"])
    out["delmonte"] = dm
    return out


# --------------------------------------------------------------------------- #
# A. Unilever
# --------------------------------------------------------------------------- #
def unilever(inp: dict) -> tuple[pd.DataFrame, dict]:
    keys = [int(k) for k in inp["tier_a"]["product_key"]]
    recs_r, ser_r, fc_r = F.run_cohort(inp["demand"], keys)
    bad = F.check_against_live(recs_r, inp["live"])
    n_ok = sum(r["status"] == "ok" for r in recs_r.values())
    check = {"rows": len(recs_r), "rows_matching": len(recs_r) - len({b[0] for b in bad}), "ok_rows_mase_checked": n_ok,
             "mismatches": bad}
    if bad:
        return pd.DataFrame(), check
    hold = F.verdict_holdouts(recs_r, ser_r)
    sc_r = F.score_holdouts(recs_r, ser_r, fc_r, hold)

    ph = inp["placeholder"][inp["placeholder"]["product_key"].isin(keys)]
    demand_sim = pd.concat([inp["demand"], ph], ignore_index=True).sort_values(["product_key", "calendar_month"])
    recs_s, ser_s, fc_s = F.run_cohort(demand_sim, keys, allow_placeholder=True, score_pipeline=False)
    hold_s = {k: h for k, h in hold.items() if recs_s[k]["status"] == "ok"}
    sc_s = F.score_holdouts(recs_s, ser_s, fc_s, hold_s, allow_placeholder=True)

    names = inp["tier_a"].set_index("product_key")
    live = inp["live"].set_index("product_key")
    rows = []
    for k in keys:
        r, s = recs_r[k], recs_s[k]
        h = hold.get(k)
        m_r = m_s = np.nan
        if h is not None:
            m_r = mase(sc_r[k]["actual"].to_numpy(), sc_r[k]["value"].to_numpy(), h["scale"])
            if k in sc_s:
                m_s = mase(sc_s[k]["actual"].to_numpy(), sc_s[k]["value"].to_numpy(), h["scale"])
        v_r, v_s = F.verdict(m_r), F.verdict(m_s)
        d = np.round(m_s, 4) - np.round(m_r, 4)
        rows.append({
            "label": LABEL, "scope": F.SCOPE_NOTE,
            "product_key": k, "sku_code": names.loc[k, "sku_code"], "product_name": names.loc[k, "product_name"],
            "placeholder_months_2021_22": s["placeholder_months"],
            "history_months_real": r["months_span"], "history_months_sim": s["months_span"],
            "sales_months_real": r["sales_months"], "sales_months_sim": s["sales_months"],
            "status_real": r["status"], "status_sim": s["status"],
            "bin_real": r["bin"], "bin_sim": s["bin"], "model_real": r["method"], "model_sim": s["method"],
            "forecast_2026_03_real": round(r["forecast"], 2), "forecast_2026_03_sim": round(s["forecast"], 2),
            "forecast_change_pct": (round(100 * (s["forecast"] - r["forecast"]) / r["forecast"], 1)
                                    if r["forecast"] else None),
            "score_source": None if h is None else h["source"], "score_months": None if h is None else len(h["months"]),
            "score_first_month": None if h is None else h["months"][0].strftime("%Y-%m"),
            "mase_real": None if not np.isfinite(m_r) else round(m_r, 4),
            "mase_sim": None if not np.isfinite(m_s) else round(m_s, 4),
            "verdict_real": v_r, "verdict_sim": v_s,
            "bin_changed": r["bin"] != s["bin"], "model_changed": r["method"] != s["method"],
            "verdict_changed": (v_r != v_s) if (v_r and v_s) else None,
            "mase_direction": (None if not (np.isfinite(m_r) and np.isfinite(m_s))
                               else "better" if d < 0 else "worse" if d > 0 else "same"),
            "live_forecast_value": float(live.loc[k, "forecast_value"]),
            "live_mase_stored": None if pd.isna(live.loc[k, "mase"]) else float(live.loc[k, "mase"]),
            "real_reproduces_live": True,
        })
    return pd.DataFrame(rows), check


def pick_examples(df: pd.DataFrame) -> list:
    c = df[df["mase_real"].notna() & df["mase_sim"].notna()].copy()
    c["delta"] = c["mase_sim"] - c["mase_real"]
    picks, used = [], set()

    def add(tag, row):
        if row is not None and row["product_key"] not in used:
            used.add(row["product_key"])
            picks.append((tag, row))

    add("biggest improvement", c.sort_values("delta").iloc[0])
    add("biggest worsening", c.sort_values("delta", ascending=False).iloc[0])
    bc = c[c["bin_changed"] & ~c["product_key"].isin(used)]
    if len(bc):
        vc = bc[bc["verdict_changed"] == True]  # noqa: E712
        pool = vc if len(vc) else bc
        add("bin change", pool.loc[pool["delta"].abs().sort_values(ascending=False).index[0]])
    vp = c[(c["verdict_changed"] == True) & (c["placeholder_months_2021_22"] > 0)  # noqa: E712
           & ~c["product_key"].isin(used)]
    if len(vp):
        add("verdict change, with placeholder months", vp.loc[vp["delta"].abs().sort_values(ascending=False).index[0]])
    same = c[~c["bin_changed"] & ~c["model_changed"] & (c["verdict_changed"] == False)  # noqa: E712
             & ~c["product_key"].isin(used)].copy()
    if len(same):
        same["absd"] = same["delta"].abs()
        add("does not change", same.sort_values(["absd", "placeholder_months_2021_22"], ascending=[True, False]).iloc[0])
    return picks


def example_line(tag: str, r) -> str:
    def side(b, m, f, v, mase_v):
        return f"{b} bin / {m}, MASE {mase_v:.2f} ({v}), March forecast {f:,.0f}"
    ph = int(r["placeholder_months_2021_22"])
    why = ("no placeholder rows of its own - it moves only because the shared XGBoost model is trained on the "
           "bigger pool" if ph == 0 else
           f"{ph} placeholder months added; sales months {int(r['sales_months_real'])} -> {int(r['sales_months_sim'])}")
    return (f"- **{tag}** - `{r['sku_code']}` {r['product_name']}: REAL "
            f"{side(r['bin_real'], r['model_real'], r['forecast_2026_03_real'], r['verdict_real'], r['mase_real'])}"
            f" -> SIM {side(r['bin_sim'], r['model_sim'], r['forecast_2026_03_sim'], r['verdict_sim'], r['mase_sim'])}"
            f" ({why}; scored on {r['score_source']}, {int(r['score_months'])} months).")


# --------------------------------------------------------------------------- #
# B. Del Monte
# --------------------------------------------------------------------------- #
def delmonte(dm: dict) -> tuple[pd.DataFrame, dict]:
    rows, info = [], {}

    def add(section, item, metric, real, sim, note=""):
        rows.append({"label": LABEL, "scope": "Del Monte category level - no product-level sales, not forecast",
                     "section": section, "item": item, "metric": metric, "real_only": real,
                     "real_plus_placeholder_2021_22": sim, "note": note})

    # 1. months of real vs placeholder data per table
    cov = []
    for t in DM_TABLES:
        d = dm[t]
        real = sorted(d.loc[~d.is_demo, "period"])
        ph = d.loc[d.is_demo, "period"]
        p2122 = sorted(p for p in ph if "2021-01" <= p <= "2022-12")
        pgap = sorted(p for p in ph if "2023-01" <= p <= "2026-02")
        pfwd = sorted(p for p in ph if p >= "2026-03")
        overlap = sorted(set(real) & set(ph))
        note = (f"real {real[0] if real else '-'}..{real[-1] if real else '-'}; placeholder also fills "
                f"{len(pgap)} gap months 2023-01..2026-02 and {len(pfwd)} months 2026-03+ (neither used here); "
                f"months with both real and placeholder rows: {len(overlap)}")
        add("months_by_table", t, "months with rows", len(real), len(real) + len(p2122), note)
        cov.append({"table": t, "real": len(real), "ph_2021_22": len(p2122), "ph_gap": len(pgap), "ph_fwd": len(pfwd),
                    "overlap": len(overlap), "first_real": real[0] if real else None, "last_real": real[-1] if real else None})
    info["coverage"] = pd.DataFrame(cov)

    # 2. whole-window category revenue shares + ABC tiers (classify_abc, same cut points as live)
    cr = dm["category_revenue"]
    paths = cr.groupby("cat")["category_path"].first()
    tot_r = cr[~cr.is_demo].groupby("cat")["revenue"].sum()
    tot_s = cr.groupby("cat")["revenue"].sum()

    def abc(tot):
        pos = tot[tot > 0]
        res = classify_abc(pd.DataFrame({"sku_id": pos.index, "total_revenue": pos.values}))
        return res.set_index("sku_id"), int((tot <= 0).sum())

    a_r, ex_r = abc(tot_r)
    a_s, ex_s = abc(tot_s)
    cats = sorted(set(a_r.index) | set(a_s.index), key=lambda c: -(a_s["revenue_share"].get(c, 0) or 0))
    only_ph = [c for c in cats if c not in tot_r.index]
    for c in cats:
        nr = "category present only in 2021-22 placeholder rows" if c in only_ph else ""
        add("category_abc", paths[c], "revenue share (whole window)",
            None if c not in a_r.index else round(float(a_r.loc[c, "revenue_share"]), 5),
            None if c not in a_s.index else round(float(a_s.loc[c, "revenue_share"]), 5), nr)
        add("category_abc", paths[c], "ABC tier (whole window)",
            a_r["tier"].get(c), a_s["tier"].get(c), nr)
    both = [c for c in cats if c in a_r.index and c in a_s.index]
    tier_changes = [(paths[c], a_r.loc[c, "tier"], a_s.loc[c, "tier"]) for c in both if a_r.loc[c, "tier"] != a_s.loc[c, "tier"]]
    info["abc"] = {
        "cats_real": len(a_r), "cats_sim": len(a_s), "only_placeholder": len(only_ph),
        "tiers_real": a_r["tier"].value_counts().to_dict(), "tiers_sim": a_s["tier"].value_counts().to_dict(),
        "tier_changes": tier_changes, "excluded_nonpositive": (ex_r, ex_s),
        "share_shift_median_pp": float(np.median([abs(a_s.loc[c, "revenue_share"] - a_r.loc[c, "revenue_share"]) * 100
                                                  for c in both])) if both else None,
        "top5_real": [(paths[c], round(float(a_r.loc[c, "revenue_share"]) * 100, 1)) for c in a_r.index[:5]],
        "top5_sim": [(paths[c], round(float(a_s.loc[c, "revenue_share"]) * 100, 1)) for c in a_s.index[:5]],
    }

    # which category vocabulary the placeholder rows use (the January 2025 taxonomy break)
    v = dm["category_vocab"]
    pre = set(v.loc[~v.is_demo & ~v.from_2025, "category_path"])
    post = set(v.loc[~v.is_demo & v.from_2025, "category_path"])
    phr = v[v.is_demo].groupby("category_path")["revenue"].sum()
    info["vocab"] = {"ph_cats": len(phr), "ph_in_pre": int(phr.index.isin(pre).sum()),
                     "ph_in_post": int(phr.index.isin(post).sum()),
                     "ph_rev_share_pre": float(phr[phr.index.isin(pre)].sum() / phr.sum()),
                     "real_pre": len(pre), "real_post": len(post), "real_overlap": len(pre & post)}

    # 3. month-of-year index = mean of that month's totals across the years present / mean of all monthly totals
    info["index"] = {}
    for t in ("sales_fact", "sellout_fact"):
        m = dm[f"monthly_{t}"].groupby(["period", "is_demo"])["net_amount"].sum().unstack(fill_value=np.nan)
        real = m.get(False, pd.Series(dtype=float)).dropna()
        sim = real.add(m.get(True, pd.Series(dtype=float)).dropna(), fill_value=0).dropna()

        def idx(series):
            s = pd.Series(series.values, index=pd.to_datetime(series.index + "-01"))
            by = s.groupby(s.index.month)
            return (by.mean() / s.mean()), by.size()

        ir, nr = idx(real)
        isim, ns = idx(sim)
        for mo in range(1, 13):
            add("month_of_year_index", f"{t} net_amount, month {mo:02d}", "index (1.00 = average month)",
                None if mo not in ir.index else round(float(ir[mo]), 3),
                None if mo not in isim.index else round(float(isim[mo]), 3),
                f"years with data: {int(nr.get(mo, 0))} real / {int(ns.get(mo, 0))} with placeholder")
        both_m = [mo for mo in range(1, 13) if mo in ir.index and mo in isim.index]
        diffs = {mo: float(isim[mo] - ir[mo]) for mo in both_m}
        info["index"][t] = {
            "real_months": len(real), "sim_months": len(sim),
            "months_missing_real": [mo for mo in range(1, 13) if mo not in ir.index],
            "peak_real": int(ir.idxmax()), "peak_sim": int(isim.idxmax()),
            "trough_real": int(ir.idxmin()), "trough_sim": int(isim.idxmin()),
            "max_abs_shift": max(abs(v) for v in diffs.values()) if diffs else None,
            "max_shift_month": max(diffs, key=lambda mo: abs(diffs[mo])) if diffs else None,
            "median_abs_shift": float(np.median([abs(v) for v in diffs.values()])) if diffs else None,
        }
    return pd.DataFrame(rows), info


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def md_table(ct: pd.DataFrame) -> str:
    """A crosstab as a markdown table (no tabulate dependency)."""
    head = "| REAL \\ SIM | " + " | ".join(str(c) for c in ct.columns) + " |"
    rule = "|---" * (len(ct.columns) + 1) + "|"
    body = ["| " + str(i) + " | " + " | ".join(str(int(v)) for v in row) + " |" for i, row in zip(ct.index, ct.to_numpy())]
    return "\n".join([head, rule, *body])


def write_reports(u: pd.DataFrame, check: dict, picks: list, dmf: pd.DataFrame, info: dict) -> dict:
    u.to_csv(os.path.join(HERE, "unilever_per_sku.csv"), index=False)
    dmf.to_csv(os.path.join(HERE, "delmonte_category.csv"), index=False)
    c = u[u["mase_real"].notna() & u["mase_sim"].notna()]
    vt = pd.crosstab(c["verdict_real"], c["verdict_sim"]).reindex(index=["fit", "borderline", "not fit"],
                                                                   columns=["fit", "borderline", "not fit"], fill_value=0)
    bt = pd.crosstab(u["bin_real"], u["bin_sim"])
    with_ph = int((u["placeholder_months_2021_22"] > 0).sum())
    fchg = u[u["forecast_change_pct"].notna() & (u["status_real"] == "ok")]
    s = {
        "with_ph": with_ph, "bin_changed": int(u["bin_changed"].sum()), "model_changed": int(u["model_changed"].sum()),
        "verdict_changed": int((c["verdict_changed"] == True).sum()), "scored": len(c),  # noqa: E712
        "better": int((c["mase_direction"] == "better").sum()), "worse": int((c["mase_direction"] == "worse").sum()),
        "same": int((c["mase_direction"] == "same").sum()),
        "median_real": float(c["mase_real"].median()), "median_sim": float(c["mase_sim"].median()),
        "verdicts_real": c["verdict_real"].value_counts().to_dict(), "verdicts_sim": c["verdict_sim"].value_counts().to_dict(),
        "status_changed": int((u["status_real"] != u["status_sim"]).sum()),
        "fc_changed": int((fchg["forecast_change_pct"].abs() > 0).sum()),
        "fc_median_abs_pct": float(fchg["forecast_change_pct"].abs().median()),
        "units_real": float(u["forecast_2026_03_real"].sum()), "units_sim": float(u["forecast_2026_03_sim"].sum()),
        "common": int((c["score_source"] == "common").sum()),
    }
    ab, cov = info["abc"], info["coverage"]
    L = [f"# {LABEL}", "", f"**Scope.** {SCOPE}", "",
         "Read-only run, 2026-10-02 (`run_simulation.py` beside this file). Nothing here is served, written to "
         "`forecast_result`, used by the LP, or usable as an accuracy claim: the 2021-22 rows are placeholder "
         "data (`is_demo = true`) standing in for files SSM has not delivered.", "",
         "## A. Unilever - Tier A as of 2026-02 (132 SKUs)", "",
         "| check | result |", "|---|---|",
         f"| REAL run reproduces live `forecast_result` (2026-03-01): status, method, forecast_value | "
         f"{check['rows_matching']}/{check['rows']} |",
         f"| REAL run reproduces stored MASE (`ok` rows) | {check['ok_rows_mase_checked']}/{check['ok_rows_mase_checked']} |",
         "",
         f"Placeholder rows used: 2021-01..2022-12 only, for {with_ph} of the 132 SKUs (the 2026-03..08 gap rows "
         "are excluded). Same router and settings in both runs. Both runs are scored on the same months and "
         f"the same scale: common window 2025-09..2026-02 for {s['common']} SKUs, the stored 20% split for "
         f"{s['scored'] - s['common']} short-bin SKUs the common window cannot score; MASE scale always from the "
         "REAL months. Verdict: fit < 0.9 <= borderline < 1.1 <= not fit (reports/diagnostics/README.md).", "",
         "| measure | REAL | SIMULATION |", "|---|---|---|",
         f"| median MASE ({s['scored']} scored SKUs) | {s['median_real']:.3f} | {s['median_sim']:.3f} |",
         f"| fit / borderline / not fit | {s['verdicts_real'].get('fit', 0)} / {s['verdicts_real'].get('borderline', 0)} / "
         f"{s['verdicts_real'].get('not fit', 0)} | {s['verdicts_sim'].get('fit', 0)} / "
         f"{s['verdicts_sim'].get('borderline', 0)} / {s['verdicts_sim'].get('not fit', 0)} |",
         f"| total 2026-03 forecast, units (132 SKUs) | {s['units_real']:,.0f} | {s['units_sim']:,.0f} |", "",
         "| change (REAL -> SIM) | SKUs |", "|---|---|",
         f"| bin changes | {s['bin_changed']} of 132 |", f"| served model changes | {s['model_changed']} of 132 |",
         f"| verdict changes | {s['verdict_changed']} of {s['scored']} |",
         f"| MASE better / worse / same (4 dp) | {s['better']} / {s['worse']} / {s['same']} |",
         f"| status changes (insufficient / ok) | {s['status_changed']} |",
         f"| 2026-03 forecast changes (ok SKUs) | {s['fc_changed']}, median abs change {s['fc_median_abs_pct']:.1f}% |", "",
         "Bin, REAL (rows) x SIMULATION (columns):", "", md_table(bt), "",
         "Verdict, REAL (rows) x SIMULATION (columns):", "", md_table(vt), "",
         "Where the change comes from (scored SKUs, REAL bin x whether the SKU has placeholder rows):", "",
         "| REAL bin | placeholder rows | SKUs | MASE better / worse / same | median MASE REAL -> SIM |",
         "|---|---|---|---|---|"]
    for (b, has), g in c.assign(has=c["placeholder_months_2021_22"] > 0).groupby(["bin_real", "has"]):
        L.append(f"| {b} | {'yes' if has else 'no'} | {len(g)} | {int((g.mase_direction == 'better').sum())} / "
                 f"{int((g.mase_direction == 'worse').sum())} / {int((g.mase_direction == 'same').sum())} | "
                 f"{g.mase_real.median():.3f} -> {g.mase_sim.median():.3f} |")
    moved = c[c["mase_direction"] != "same"]
    L += ["", f"**What changes, in one line:** the MASE moves only for SKUs served by XGBoost+MA3 "
          f"({len(moved)} SKUs move, all served by {' / '.join(sorted(moved['model_real'].unique()))}), because the global XGBoost model trains on every Tier A "
          "series, so placeholder rows change it for all long-bin SKUs, including those with no placeholder rows of "
          "their own. MA3 and TSB use only the SKU's own history, and none of their SKUs gets placeholder rows, "
          "so they are unchanged.", "",
          "Examples: `examples.md`. Per SKU: `unilever_per_sku.csv`.", "",
         "## B. Del Monte - category level, descriptive", "",
         "No product-level sales exist for Del Monte, so nothing is forecast; this is coverage and category "
         "revenue only. Real rows are `is_demo = false`; placeholder rows dated 2021-22 are the only ones added.", "",
         "| table | real months | real range | + placeholder 2021-22 | placeholder gap months 2023-01..2026-02 (not used) | placeholder 2026-03+ (not used) |",
         "|---|---|---|---|---|---|"]
    for r in cov.itertuples():
        L.append(f"| {r.table} | {r.real} | {r.first_real}..{r.last_real} | {r.ph_2021_22} | {r.ph_gap} | {r.ph_fwd} |")
    L += ["", "**Category revenue shares and ABC tiers** (whole window, SellOut_Fact net_amount, `classify_abc`'s "
          "0.80/0.95 cut points). The live Del Monte ABC is computed one month at a time (method `single`), so "
          "adding 2021-22 cannot change any 2023+ period's tier; the whole-window view below is where it shows.", "",
          "| measure | real only | real + 2021-22 |", "|---|---|---|",
          f"| categories with positive revenue | {ab['cats_real']} | {ab['cats_sim']} |",
          f"| tiers A / B / C | {ab['tiers_real'].get('A', 0)} / {ab['tiers_real'].get('B', 0)} / {ab['tiers_real'].get('C', 0)} | "
          f"{ab['tiers_sim'].get('A', 0)} / {ab['tiers_sim'].get('B', 0)} / {ab['tiers_sim'].get('C', 0)} |",
          f"| top 5 categories (share %) | {'; '.join(f'{p} {v}' for p, v in ab['top5_real'])} | "
          f"{'; '.join(f'{p} {v}' for p, v in ab['top5_sim'])} |", "",
          f"Categories present only in the placeholder rows: {ab['only_placeholder']}. Categories in both whose "
          f"tier changes: {len(ab['tier_changes'])}. Median absolute share shift: {ab['share_shift_median_pp']:.2f} "
          f"percentage points. Excluded for non-positive total revenue: {ab['excluded_nonpositive'][0]} (real) / "
          f"{ab['excluded_nonpositive'][1]} (with placeholder).", "",
          "**Month-of-year index** (mean of that month's totals over the years present / mean of all monthly totals):", "",
          "| source | months real | months with 2021-22 | month-of-year missing in real | peak (real -> with) | trough (real -> with) | largest shift |",
          "|---|---|---|---|---|---|---|"]
    for t, v in info["index"].items():
        L.append(f"| {t} net_amount | {v['real_months']} | {v['sim_months']} | {v['months_missing_real'] or 'none'} | "
                 f"{v['peak_real']:02d} -> {v['peak_sim']:02d} | {v['trough_real']:02d} -> {v['trough_sim']:02d} | "
                 f"{v['max_abs_shift']:.2f} (month {v['max_shift_month']:02d}) |")
    si, so, vo = info["index"]["sales_fact"], info["index"]["sellout_fact"], info["vocab"]
    L += ["", f"**What changes, in one line:** category shares and tiers move ({len(ab['tier_changes'])} tiers change, "
          f"A {ab['tiers_real'].get('A', 0)} -> {ab['tiers_sim'].get('A', 0)}), because {vo['ph_in_pre']} of the "
          f"{vo['ph_cats']} placeholder categories ({vo['ph_rev_share_pre']:.1%} of their revenue) carry pre-2025 "
          f"category names and {vo['ph_in_post']} carry 2025+ names. Real data has {vo['real_pre']} pre-2025 names and "
          f"{vo['real_post']} from 2025 ({vo['real_overlap']} shared: the January 2025 taxonomy break, still awaiting "
          "the adviser's ruling), so whole-window weight shifts toward the old names. The sales-register index barely moves (median shift "
          f"{si['median_abs_shift']:.2f}): its placeholder rows are real rows resampled from the nearest month-of-year "
          "(scripts/build_synthetic_v2_clean_pool.py, dm_sales), so they repeat the real pattern and add no seasonal "
          f"evidence. The sell-out index moves more (largest shift {so['max_abs_shift']:.2f}, month "
          f"{so['max_shift_month']:02d}) because sell-out has only {so['real_months']} real months.",
          "", "Per category / month: `delmonte_category.csv`.", ""]
    with open(os.path.join(HERE, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    E = [f"# Examples - {LABEL}", "", f"**Scope.** {SCOPE}", "",
         "One line per product. MASE on the same months and scale in both runs; never an accuracy claim.", ""]
    E += [example_line(tag, r) for tag, r in picks]
    if not u["bin_changed"].any():
        lo = int(u.loc[u["placeholder_months_2021_22"] > 0, "sales_months_real"].min())
        E.append(f"- **bin change** - none: 0 of 132 products change bin. All {with_ph} products that receive "
                 f"placeholder rows already have {lo}+ real sales months, so they are in the long bin with or without them.")
    with open(os.path.join(HERE, "examples.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(E) + "\n")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="optional pickle of the loaded rows (read if present, else written)")
    inp = F.cached_inputs(ap.parse_args().cache, load_all)
    print(LABEL)
    print(f"[{SCOPE}]")
    u, check = unilever(inp)
    print(f"REAL vs live forecast_result: {check['rows_matching']}/{check['rows']} rows; stored MASE on "
          f"{check['ok_rows_mase_checked']} ok rows; mismatches={len(check['mismatches'])}")
    if check["mismatches"]:
        for b in check["mismatches"][:20]:
            print("   MISMATCH", b)
        sys.exit("STOP: the REAL run does not reproduce live forecast_result")
    picks = pick_examples(u)
    dmf, info = delmonte(inp["delmonte"])
    s = write_reports(u, check, picks, dmf, info)
    print(s)
    print(info["coverage"].to_string(index=False))
    print({k: v for k, v in info["abc"].items()})
    print(info["index"])
    print(info["vocab"])
    for tag, r in picks:
        print(example_line(tag, r))


if __name__ == "__main__":
    main()
