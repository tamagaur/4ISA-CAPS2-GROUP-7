"""Tier A basis check (2026-10-03): offline, over pull_extract.py's CSVs.

Does the Tier A list (80% of revenue, ranked on Feb 2026 alone) match the
products that matter over longer periods? Real Unilever SKU sales only:
unilever_sku_demand_fact_real (is_demo = false), Jan 2023 - Feb 2026.

Revenue rules follow the live tier table (analytics/classification/
orchestrate_abc.py), so the 1-month and 3-month lists reproduce what is live:
  - a month where returns exceeded sales counts as 0, per month, before the
    window is summed (_fetch_unilever_sku_revenue_t3m's per-month clamp);
  - a blank (NULL) net_amount anywhere in the window drops that product from
    that window (t3m's BOOL_OR(excluded_null));
  - a product with 0 revenue in the window gets no tier (_split_zero_revenue);
  - ranking: revenue descending, product_key ascending on ties (classify_abc).
sensitivity.csv shows what changes if either of the first two rules is swapped.

§7 (new-product rule) needs only the main pull; §8 (impact preview: router
bins, stock file, today's forecasts) also needs `pull_extract.py --only followup`.

    python run_tier_a_basis.py --extract <dir> [--lp-plan <plan csv>]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from analytics.classification.abc import TIER_A_CUTOFF, TIER_B_CUTOFF  # noqa: E402
from analytics.classification.fsn import no_sale_in_last_months  # noqa: E402
from analytics.etl.granularity import business_days_in_month  # noqa: E402
from analytics.forecasting.global_model import from_first_sale  # noqa: E402
from analytics.forecasting.router import LIVE_MODEL, bin_at  # noqa: E402
from analytics.params import (  # noqa: E402
    DEAD_SKU_MONTHS, MIN_MONTHS_WITH_SALES, PLACEHOLDERS, SERVICE_LEVEL_PCT, SERVICE_Z,
)
from scripts.run_baseline_forecast import build_series  # noqa: E402

LATEST = "2026-02"
REAL_START = "2023-01"
BASES = {"1m": 1, "3m": 3, "12m": 12, "24m": 24, "full": None}
BASIS_LABEL = {"1m": "latest month", "3m": "last 3 months", "12m": "last 12 months",
               "24m": "last 24 months", "full": "full real history"}
CHURN_MONTHS = pd.period_range("2025-01", LATEST, freq="M").strftime("%Y-%m").tolist()
SS_WINDOW_DAYS = PLACEHOLDERS["review_days"] + PLACEHOLDERS["lead_days"]
# Percentages are stored at 4 decimals so the README rounds them only once
# (a 2-decimal 21.75 would print as 21.8 where the exact 21.7498 is 21.7).
PCT_DP = 4
TIER_Z = {"A": float(norm.ppf(0.95)), "B": SERVICE_Z, "C": float(norm.ppf(0.85))}
TIER_PCT = {"A": 95, "B": SERVICE_LEVEL_PCT, "C": 85}
# Client data (project rule: no per-product sales or prices in git). Per-product tables are written in full to the
# git-ignored local/ folder; the committed copy beside this script drops the columns matching CLIENT_COLUMNS.
# Aggregate tables (basis_summary.csv, safety_stock_summary.csv, ...) are not per-product and are written whole.
LOCAL = HERE / "local"
CLIENT_COLUMNS = re.compile(r"^(revenue_php_.*|change_php|cost_per_piece_php|.*_value_php)$")


def publish(df: pd.DataFrame, name: str, index: bool = True) -> None:
    """Full table to local/ (not committed); the same table minus CLIENT_COLUMNS beside this script."""
    LOCAL.mkdir(exist_ok=True)
    df.to_csv(LOCAL / name, index=index)
    df.drop(columns=[c for c in df.columns if CLIENT_COLUMNS.search(c)]).to_csv(HERE / name, index=index)


def months_ending(end: str, n: int | None) -> list[str]:
    start = REAL_START if n is None else (pd.Period(end, "M") - (n - 1)).strftime("%Y-%m")
    return pd.period_range(start, end, freq="M").strftime("%Y-%m").tolist()


def window_revenue(d: pd.DataFrame, months: list[str], clamp: str = "month",
                   blank: str = "drop") -> tuple[pd.Series, set]:
    """product_key -> revenue (pesos) over `months`, zeros removed.
    clamp='month' (live t3m) zeroes each negative month; 'total' sums the raw
    net then zeroes a negative total. blank='drop' (live t3m) removes a
    product with any NULL month; 'skip' just leaves that month out."""
    sub = d[d["calendar_month"].isin(months)]
    blank_pks = set(sub.loc[sub["net_amount"].isna(), "product_key"])
    if blank == "drop":
        sub = sub[~sub["product_key"].isin(blank_pks)]
    sub = sub.dropna(subset=["net_amount"])
    net = sub["net_amount"].clip(lower=0) if clamp == "month" else sub["net_amount"]
    rev = net.groupby(sub["product_key"]).sum()
    if clamp == "total":
        rev = rev.clip(lower=0)
    return rev[rev > 0], blank_pks


def classify(rev: pd.Series) -> pd.DataFrame:
    """classify_abc()'s ranking and cut points, over a product_key -> revenue series."""
    out = rev.rename("revenue").rename_axis("product_key").reset_index()
    out = out.sort_values(["revenue", "product_key"], ascending=[False, True], kind="mergesort")
    out["share"] = out["revenue"] / out["revenue"].sum()
    out["cum_share"] = out["share"].cumsum()
    out["rank"] = np.arange(1, len(out) + 1)
    out["tier"] = np.where(out["cum_share"] <= TIER_A_CUTOFF, "A",
                           np.where(out["cum_share"] <= TIER_B_CUTOFF, "B", "C"))
    return out.set_index("product_key")


def class_a(d, end, basis, **kw) -> tuple[pd.DataFrame, set]:
    cls = classify(window_revenue(d, months_ending(end, BASES[basis]), **kw)[0])
    return cls, set(cls.index[cls["tier"] == "A"])


def first_sale_months(d: pd.DataFrame, col: str) -> pd.Series:
    """product_key -> first month with `col` > 0 (the runner's first_sale_month
    uses quantity, run_baseline_forecast.py:347-350)."""
    sold = d[d[col] > 0]
    return sold.groupby("product_key")["calendar_month"].min()


def rule1_list(d, end, first_sale) -> tuple[set, set, pd.DataFrame, pd.DataFrame]:
    """README §7: the 12-month Class A, plus products first sold within those
    12 months that are Class A on the 3-month basis. Returns (list, added,
    12-month classes, 3-month classes)."""
    c12, a12 = class_a(d, end, "12m")
    c3, a3 = class_a(d, end, "3m")
    start = months_ending(end, 12)[0]
    added = {pk for pk in a3 - a12 if start <= first_sale.get(pk, "9999-99") <= end}
    return a12 | added, added, c12, c3


def runner_status(rows: pd.DataFrame, end: str) -> tuple[str, str | None, int, int]:
    """What run_baseline_forecast.py would do with this product for the month
    after `end`, using its own series builder and gates (lines 330-375):
    (status, router bin or None, sales months, months span)."""
    sku = pd.DataFrame({"calendar_month": rows["calendar_month"],
                        "quantity": rows["quantity_sold"].fillna(0.0), "is_demo": False})
    series = build_series(sku)
    span, sales = int(len(series)), int((series > 0).sum())
    if sales < MIN_MONTHS_WITH_SALES:
        return "insufficient_data", None, sales, span
    if span >= DEAD_SKU_MONTHS and no_sale_in_last_months(series.index.strftime("%Y-%m"), series.to_numpy(), end):
        return "dead_sku", None, sales, span
    trimmed = from_first_sale(series)
    return "ok", bin_at(trimmed if len(trimmed) else series)[0], sales, span


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True, type=Path)
    ap.add_argument("--lp-plan", type=Path, help="an LP dry-run plan CSV, to cross-check safety stock")
    args = ap.parse_args()
    x = args.extract
    d = pd.read_csv(x / "demand_real.csv", dtype={"sku_code": str})
    d = d[(d["calendar_month"] >= REAL_START) & (d["calendar_month"] <= LATEST)]
    prod = pd.read_csv(x / "product_dim.csv", dtype={"sku_code": str}).set_index("product_key")
    live = pd.read_csv(x / "abc_live.csv")
    cost = pd.read_csv(x / "unit_cost.csv")
    out = HERE
    log: list[str] = []
    checks: list[dict] = []  # the run's self-checks, kept in checks.csv as well as printed

    def check(name: str, value, out_of=None, note: str = "") -> None:
        checks.append({"check": name, "value": value, "out_of": out_of, "note": note})

    def name_cols(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.insert(0, "sku_code", prod.loc[df.index, "sku_code"].values)
        df.insert(0, "product_name", prod.loc[df.index, "product_name"].values)
        return df

    # Months with sales (net > 0), real history 2023-01..2026-02.
    pos = d[d["net_amount"] > 0]
    hist = pd.DataFrame({
        "months_with_sales_2023_01_to_2026_02": pos.groupby("product_key")["calendar_month"].nunique(),
        "first_month_with_sales": pos.groupby("product_key")["calendar_month"].min(),
        "last_month_with_sales": pos.groupby("product_key")["calendar_month"].max(),
        "months_with_sales_last_12": pos[pos["calendar_month"].isin(months_ending(LATEST, 12))]
                                     .groupby("product_key")["calendar_month"].nunique(),
    })
    hist["months_with_sales_last_12"] = hist["months_with_sales_last_12"].fillna(0).astype(int)

    # ---- 0. Reproduction check against the live tier table ---------------- #
    rep = []
    for (period, method), g in live.groupby(["classification_period", "method"]):
        mine = classify(window_revenue(d, months_ending(period, 1 if method == "single" else 3))[0])
        joined = g.set_index("product_key")[["tier"]].join(mine[["tier"]], how="outer", lsuffix="_live", rsuffix="_mine")
        rep.append({
            "period": period, "method": method, "live_ranked": len(g), "recomputed_ranked": len(mine),
            "live_tier_a": int((g["tier"] == "A").sum()), "recomputed_tier_a": int((mine["tier"] == "A").sum()),
            "products_with_different_tier": int((joined["tier_live"] != joined["tier_mine"]).sum()),
        })
    rep = pd.DataFrame(rep)
    rep.to_csv(out / "reproduction_check.csv", index=False)
    log.append(f"reproduction: {len(rep)} period x method runs, "
               f"{int((rep['products_with_different_tier'] == 0).sum())} match exactly")
    check("reproduction_runs_matching_live", int((rep["products_with_different_tier"] == 0).sum()), len(rep),
          f"single + t3m, {rep['period'].min()}..{rep['period'].max()}")

    # ---- 1. Class A lists per basis, ending Feb 2026 ---------------------- #
    cls, A, summary = {}, {}, []
    for b in BASES:
        months = months_ending(LATEST, BASES[b])
        rev, blank_pks = window_revenue(d, months)
        cls[b] = classify(rev)
        A[b] = set(cls[b].index[cls[b]["tier"] == "A"])
        c = cls[b]
        summary.append({
            "basis": b, "basis_label": BASIS_LABEL[b], "window_start": months[0], "window_end": months[-1],
            "months": len(months), "products_ranked": len(c),
            "class_a": len(A[b]), "class_b": int((c["tier"] == "B").sum()), "class_c": int((c["tier"] == "C").sum()),
            "total_revenue_php": round(c["revenue"].sum(), 2),
            "class_a_revenue_php": round(c.loc[c["tier"] == "A", "revenue"].sum(), 2),
            "class_a_revenue_pct": round(100 * c.loc[c["tier"] == "A", "share"].sum(), PCT_DP),
            "products_dropped_for_blank_revenue": len(blank_pks),
        })
    summary = pd.DataFrame(summary)
    summary.to_csv(out / "basis_summary.csv", index=False)

    live_a = set(live.query("classification_period == @LATEST and method == 'single' and tier == 'A'")["product_key"])
    assert live_a == A["1m"], "recomputed Feb 2026 Class A does not equal live Tier A"
    assert set(live.query("classification_period == @LATEST and method == 't3m' and tier == 'A'")["product_key"]) == A["3m"]

    wide = pd.concat({b: cls[b][["revenue", "rank", "tier"]] for b in BASES}, axis=1)
    wide.columns = [f"{col}_{b}" if col != "revenue" else f"revenue_php_{b}" for b, col in wide.columns]
    wide = wide.join(hist, how="left")
    for b in BASES:
        wide[f"tier_{b}"] = wide[f"tier_{b}"].fillna("-")
    wide = name_cols(wide.sort_values(["rank_full", "rank_12m"]))
    wide.index.name = "product_key"
    publish(wide, "tiers_by_basis.csv")

    # ---- 2. Overlap, products missing, revenue left out ------------------- #
    ov = []
    for bx in BASES:
        for by in BASES:
            both = len(A[bx] & A[by])
            ov.append({"basis_x": bx, "basis_y": by, "class_a_x": len(A[bx]), "class_a_y": len(A[by]),
                       "in_both": both, "jaccard_pct": round(100 * both / len(A[bx] | A[by]), PCT_DP),
                       "pct_of_x_also_in_y": round(100 * both / len(A[bx]), PCT_DP)})
    pd.DataFrame(ov).to_csv(out / "overlap_matrix.csv", index=False)

    def tier_on(pk, c, months):
        if pk in c.index:
            return c.at[pk, "tier"]
        rows = d[(d["product_key"] == pk) & d["calendar_month"].isin(months)]
        if rows.empty:
            return "no sales row"
        if rows["net_amount"].isna().any():
            return "blank revenue"
        return "returns >= sales"

    missing = sorted((A["12m"] | A["24m"]) - A["1m"])
    miss = pd.DataFrame(index=pd.Index(missing, name="product_key"))
    miss["in_12m_class_a"] = [pk in A["12m"] for pk in missing]
    miss["in_24m_class_a"] = [pk in A["24m"] for pk in missing]
    for b in ("12m", "24m", "1m"):
        miss[f"revenue_php_{b}"] = cls[b]["revenue"].reindex(missing).fillna(0).round(2)
        miss[f"rank_{b}"] = cls[b]["rank"].reindex(missing)
    miss["tier_2026_02"] = [tier_on(pk, cls["1m"], [LATEST]) for pk in missing]
    miss = miss.join(hist).sort_values("revenue_php_12m", ascending=False)
    publish(name_cols(miss), "missing_from_current_tier_a.csv")

    extra = sorted(A["1m"] - (A["12m"] | A["24m"]))
    ex = pd.DataFrame(index=pd.Index(extra, name="product_key"))
    for b in ("1m", "12m", "24m"):
        ex[f"revenue_php_{b}"] = cls[b]["revenue"].reindex(extra).fillna(0).round(2)
        ex[f"rank_{b}"] = cls[b]["rank"].reindex(extra)
        ex[f"tier_{b}"] = cls[b]["tier"].reindex(extra).fillna("-")
    ex = ex.join(hist).sort_values("revenue_php_1m", ascending=False)
    publish(name_cols(ex), "current_tier_a_not_in_12m_or_24m.csv")

    lo = []
    for b in BASES:
        for w in BASES:
            c = cls[w]
            covered = c.loc[c.index.isin(A[b]), "revenue"].sum()
            total = c["revenue"].sum()
            lo.append({"planning_list": b, "list_size": len(A[b]), "revenue_measured_over": w,
                       "window": f"{months_ending(LATEST, BASES[w])[0]}..{LATEST}",
                       "total_revenue_php": round(total, 2), "covered_php": round(covered, 2),
                       "left_out_php": round(total - covered, 2),
                       "left_out_pct": round(100 * (total - covered) / total, PCT_DP)})
    lo = pd.DataFrame(lo)
    lo.to_csv(out / "revenue_left_out.csv", index=False)

    # ---- 3. Monthly churn, Jan 2025 - Feb 2026 ---------------------------- #
    # "12m+new" is §7's rule; its revenue shares are of the 12-month window.
    first_sale = first_sale_months(d, "quantity_sold")

    def list_at(m: str, b: str) -> tuple[pd.DataFrame, set]:
        if b == "12m+new":
            lst, _, c12, _ = rule1_list(d, m, first_sale)
            return c12, lst
        return class_a(d, m, b)

    ch, members, freq = [], [], {}
    for b in ("1m", "3m", "12m", "12m+new", "24m"):
        prev_m = (pd.Period(CHURN_MONTHS[0], "M") - 1).strftime("%Y-%m")
        prev_c, prev_a = list_at(prev_m, b)
        counts: dict[int, int] = {}
        for m in CHURN_MONTHS:
            c, a = list_at(m, b)
            entered, left = a - prev_a, prev_a - a
            for pk in a:
                counts[pk] = counts.get(pk, 0) + 1
            ch.append({"basis": b, "month": m, "class_a": len(a), "previous_class_a": len(prev_a),
                       "stayed": len(a & prev_a), "entered": len(entered), "left": len(left),
                       "entered_pct_of_list": round(100 * len(entered) / len(a), PCT_DP),
                       "left_pct_of_previous": round(100 * len(left) / len(prev_a), PCT_DP),
                       "jaccard_pct": round(100 * len(a & prev_a) / len(a | prev_a), PCT_DP),
                       "entered_revenue_pct": round(100 * c.loc[list(entered), "share"].sum(), PCT_DP),
                       "left_revenue_pct_previous": round(100 * prev_c.loc[list(left), "share"].sum(), PCT_DP)})
            if b == "1m":
                for change, pks in (("entered", entered), ("left", left)):
                    for pk in pks:
                        members.append({
                            "month": m, "change": change, "product_name": prod.at[pk, "product_name"],
                            "sku_code": prod.at[pk, "sku_code"], "product_key": pk,
                            "revenue_php_this_month": round(float(c["revenue"].get(pk, 0)), 2),
                            "tier_this_month": tier_on(pk, c, [m]),
                            "revenue_php_previous_month": round(float(prev_c["revenue"].get(pk, 0)), 2),
                            "tier_previous_month": tier_on(pk, prev_c, [prev_m])})
            prev_m, prev_c, prev_a = m, c, a
        freq[b] = pd.Series(counts)
    ch = pd.DataFrame(ch)
    ch.to_csv(out / "monthly_churn.csv", index=False)
    publish(pd.DataFrame(members).sort_values(["month", "change", "revenue_php_this_month"],
                                              ascending=[True, True, False]),
            "monthly_churn_members_1m.csv", index=False)
    fq = pd.DataFrame({f"months_in_class_a_{b}": s for b, s in freq.items()}).fillna(0).astype(int)
    fq["in_current_tier_a"] = fq.index.isin(A["1m"])
    fq["in_12m_class_a_2026_02"] = fq.index.isin(A["12m"])
    fq.index.name = "product_key"
    name_cols(fq.sort_values(["months_in_class_a_1m", "months_in_class_a_12m"], ascending=False)) \
        .to_csv(out / "class_a_frequency_2025_01_to_2026_02.csv")
    churn_avg = ch.groupby("basis")[["class_a", "entered", "left", "entered_pct_of_list",
                                     "left_pct_of_previous", "jaccard_pct", "entered_revenue_pct"]].mean().round(PCT_DP)
    churn_avg.to_csv(out / "monthly_churn_average.csv")

    # ---- 4. Calendar 2025 vs calendar 2024 -------------------------------- #
    cy = {}
    for y in ("2024", "2025"):
        rev, blank_pks = window_revenue(d, months_ending(f"{y}-12", 12))
        cy[y] = (classify(rev), blank_pks)
    a24 = set(cy["2024"][0].index[cy["2024"][0]["tier"] == "A"])
    a25 = set(cy["2025"][0].index[cy["2025"][0]["tier"] == "A"])
    rows = []
    for change, pks in (("entered", a25 - a24), ("left", a24 - a25), ("stayed", a24 & a25)):
        for pk in pks:
            r = {"change": change, "product_name": prod.at[pk, "product_name"], "sku_code": prod.at[pk, "sku_code"],
                 "product_key": pk}
            for y in ("2024", "2025"):
                c, blank_pks = cy[y]
                r[f"revenue_php_{y}"] = round(float(c["revenue"].get(pk, 0)), 2)
                r[f"rank_{y}"] = c["rank"].get(pk)
                r[f"tier_{y}"] = c["tier"].get(pk, "blank revenue" if pk in blank_pks else "no sales")
                r[f"months_with_sales_{y}"] = int(pos[(pos["product_key"] == pk) & pos["calendar_month"].str.startswith(y)]
                                                  ["calendar_month"].nunique())
            r["change_php"] = round(r["revenue_php_2025"] - r["revenue_php_2024"], 2)
            r["change_pct"] = round(100 * r["change_php"] / r["revenue_php_2024"], PCT_DP) if r["revenue_php_2024"] else None
            rows.append(r)
    cal = pd.DataFrame(rows)
    # Biggest movers first: entered by largest gain, left by largest drop.
    cal["_o"] = cal["change"].map({"entered": 0, "left": 1, "stayed": 2})
    cal["_k"] = np.where(cal["change"] == "left", cal["change_php"], -cal["change_php"])
    cal = cal.sort_values(["_o", "_k"]).drop(columns=["_o", "_k"])
    publish(cal, "calendar_2025_vs_2024.csv", index=False)

    # ---- 5. Safety stock, tiered vs flat, on the 12-month basis ----------- #
    # run_lp.py's formula: sigma_monthly over the product's real months (std,
    # ddof=1; a blank quantity counts as 0 as fetch_demand_history does),
    # / sqrt(average weekdays in those months), x sqrt(review + lead days), x Z.
    latest_cost = cost.sort_values("_period").groupby("product_key").tail(1).set_index("product_key")
    ss = []
    for pk, r in cls["12m"].iterrows():
        q = d.loc[d["product_key"] == pk, ["calendar_month", "quantity_sold"]]
        row = {"product_key": pk, "tier_12m": r["tier"], "revenue_php_12m": round(r["revenue"], 2),
               "months_used": len(q)}
        if len(q) < 2:
            row["status"] = f"insufficient data ({len(q)} month)"
        else:
            sigma_m = float(q["quantity_sold"].fillna(0).std(ddof=1))
            bdays = np.mean([len(business_days_in_month(p)) for p in q["calendar_month"].unique()])
            sigma_d = sigma_m / math.sqrt(bdays)
            row.update(status="ok", sigma_monthly_pieces=round(sigma_m, 3), sigma_daily_pieces=round(sigma_d, 3),
                       ss_flat_pieces=SERVICE_Z * sigma_d * math.sqrt(SS_WINDOW_DAYS),
                       z_tiered=round(TIER_Z[r["tier"]], 4), service_level_tiered_pct=TIER_PCT[r["tier"]],
                       ss_tiered_pieces=TIER_Z[r["tier"]] * sigma_d * math.sqrt(SS_WINDOW_DAYS))
        pack = pd.to_numeric(prod.at[pk, "pack_size"], errors="coerce")
        if pk in latest_cost.index and pack and pack > 0:
            row["cost_per_piece_php"] = latest_cost.at[pk, "cost_per_case"] / pack
            row["cost_period"] = latest_cost.at[pk, "_period"]
        ss.append(row)
    ss = pd.DataFrame(ss).set_index("product_key")
    ss["ss_flat_value_php"] = ss["ss_flat_pieces"] * ss["cost_per_piece_php"]
    ss["ss_tiered_value_php"] = ss["ss_tiered_pieces"] * ss["cost_per_piece_php"]
    ss["difference_value_php"] = ss["ss_tiered_value_php"] - ss["ss_flat_value_php"]
    placeholder = PLACEHOLDERS["default_procurement_cost_per_unit"]
    for col in ("ss_flat_pieces", "ss_tiered_pieces", "cost_per_piece_php", "ss_flat_value_php",
                "ss_tiered_value_php", "difference_value_php"):
        ss[col] = ss[col].round(4 if col == "cost_per_piece_php" else 2)
    publish(name_cols(ss.sort_values("revenue_php_12m", ascending=False)), "safety_stock_by_sku.csv")

    def ss_summary(g: pd.DataFrame, label: str) -> dict:
        ok = g[g["status"] == "ok"]
        costed = ok[ok["cost_per_piece_php"].notna()]
        nocost = ok[ok["cost_per_piece_php"].isna()]
        return {
            "tier_12m": label, "products": len(g), "products_insufficient_data": int((g["status"] != "ok").sum()),
            "products_with_stock_file_cost": len(costed), "products_without_cost": len(nocost),
            "service_level_flat_pct": SERVICE_LEVEL_PCT,
            "service_level_tiered_pct": TIER_PCT.get(label, "A95/B90/C85"),
            "ss_flat_pieces": round(ok["ss_flat_pieces"].sum(), 0),
            "ss_tiered_pieces": round(ok["ss_tiered_pieces"].sum(), 0),
            "ss_flat_value_php": round(costed["ss_flat_value_php"].sum(), 0),
            "ss_tiered_value_php": round(costed["ss_tiered_value_php"].sum(), 0),
            "difference_value_php": round(costed["difference_value_php"].sum(), 0),
            "difference_pct": round(100 * costed["difference_value_php"].sum() / costed["ss_flat_value_php"].sum(), PCT_DP)
                              if len(costed) else None,
            "no_cost_products_flat_value_at_placeholder_php": round(nocost["ss_flat_pieces"].sum() * placeholder, 0),
            "no_cost_products_tiered_value_at_placeholder_php": round(nocost["ss_tiered_pieces"].sum() * placeholder, 0),
        }
    sss = pd.DataFrame([ss_summary(ss[ss["tier_12m"] == t], t) for t in ("A", "B", "C")] + [ss_summary(ss, "all")])
    sss.to_csv(out / "safety_stock_summary.csv", index=False)

    if args.lp_plan and args.lp_plan.exists():
        plan = pd.read_csv(args.lp_plan).set_index("product_key")
        j = plan[["safety_stock", "cost_per_piece"]].join(ss[["ss_flat_pieces", "cost_per_piece_php"]], how="inner")
        log.append(f"LP plan cross-check ({args.lp_plan.name}): {len(j)} products, max |SS diff| = "
                   f"{(j['safety_stock'] - j['ss_flat_pieces']).abs().max():.2f} pieces, max |cost diff| = "
                   f"{(j['cost_per_piece'] - j['cost_per_piece_php']).abs().max():.4f} PHP/piece")
        check("lp_plan_products_compared", len(j), note=args.lp_plan.name)
        check("lp_plan_max_abs_ss_diff_pieces", round(float((j["safety_stock"] - j["ss_flat_pieces"]).abs().max()), 2),
              note="flat 90% safety stock vs the plan's safety_stock")
        check("lp_plan_max_abs_cost_diff_php_per_piece",
              round(float((j["cost_per_piece"] - j["cost_per_piece_php"]).abs().max()), 4))

    # ---- Sensitivity: the two revenue rules -------------------------------- #
    sens = []
    for b in BASES:
        for clamp, blank in (("total", "drop"), ("month", "skip")):
            alt = classify(window_revenue(d, months_ending(LATEST, BASES[b]), clamp=clamp, blank=blank)[0])
            alt_a = set(alt.index[alt["tier"] == "A"])
            diff = sorted(alt_a ^ A[b])
            sens.append({"basis": b, "variant": f"negatives={'net over window' if clamp == 'total' else 'per month'}, "
                                                f"blank={'drop product' if blank == 'drop' else 'skip month'}",
                         "class_a_primary": len(A[b]), "class_a_variant": len(alt_a), "products_that_change": len(diff),
                         "changed": "; ".join(f"{prod.at[pk, 'product_name']} ({prod.at[pk, 'sku_code']})" for pk in diff)})
    for y in ("2024", "2025"):
        prim = a24 if y == "2024" else a25
        for clamp, blank in (("total", "drop"), ("month", "skip")):
            alt = classify(window_revenue(d, months_ending(f"{y}-12", 12), clamp=clamp, blank=blank)[0])
            alt_a = set(alt.index[alt["tier"] == "A"])
            diff = sorted(alt_a ^ prim)
            sens.append({"basis": f"calendar {y}", "variant": f"negatives={'net over window' if clamp == 'total' else 'per month'}, "
                                                             f"blank={'drop product' if blank == 'drop' else 'skip month'}",
                         "class_a_primary": len(prim), "class_a_variant": len(alt_a), "products_that_change": len(diff),
                         "changed": "; ".join(f"{prod.at[pk, 'product_name']} ({prod.at[pk, 'sku_code']})" for pk in diff)})
    pd.DataFrame(sens).to_csv(out / "sensitivity.csv", index=False)

    # ---- 7. New-product rule: 12-month Class A + new 3-month Class A ------ #
    r1, r1_added, _, c3 = rule1_list(d, LATEST, first_sale)
    alt_added = rule1_list(d, LATEST, first_sale_months(d, "net_amount"))[1]
    log.append(f"rule 1: first sale by net_amount > 0 instead of quantity > 0 changes the added set by "
               f"{len(alt_added ^ r1_added)} product(s)")
    check("rule1_added_products_changed_if_first_sale_by_pesos", len(alt_added ^ r1_added))
    add = pd.DataFrame(index=pd.Index(sorted(r1_added), name="product_key"))
    add["first_sale_month"] = first_sale.reindex(add.index)
    for b in ("3m", "12m", "1m"):
        add[f"revenue_php_{b}"] = cls[b]["revenue"].reindex(add.index).fillna(0).round(2)
        add[f"rank_{b}"] = cls[b]["rank"].reindex(add.index)
        add[f"tier_{b}"] = cls[b]["tier"].reindex(add.index).fillna("-")
    add["in_current_tier_a"] = add.index.isin(A["1m"])
    add = add.join(hist).sort_values("revenue_php_3m", ascending=False)
    publish(name_cols(add), "rule1_added_products.csv")
    r1_rows = []
    for name, lst in (("latest month (today)", A["1m"]), ("12m", A["12m"]), ("12m+new", r1)):
        for w in ("1m", "3m", "12m", "24m"):
            c = cls[w]
            total, covered = c["revenue"].sum(), c.loc[c.index.isin(lst), "revenue"].sum()
            r1_rows.append({"planning_list": name, "list_size": len(lst), "revenue_measured_over": w,
                            "window": f"{months_ending(LATEST, BASES[w])[0]}..{LATEST}",
                            "total_revenue_php": round(total, 2), "left_out_php": round(total - covered, 2),
                            "left_out_pct": round(100 * (total - covered) / total, PCT_DP)})
    r1_lo = pd.DataFrame(r1_rows)
    r1_lo.to_csv(out / "rule1_revenue_left_out.csv", index=False)

    # ---- 8. Impact preview of a 12-month basis (counts only) -------------- #
    lists = {"latest month (today)": A["1m"], "12m": A["12m"], "12m+new": r1}
    impact_rows, impact_summary = [], []
    stock_file, fc_file = x / "stock_2026_03.csv", x / "forecast_latest.csv"
    if stock_file.exists() and fc_file.exists():
        stock = pd.read_csv(stock_file).set_index("product_key").fillna(0)
        fc = pd.read_csv(fc_file).set_index("product_key")
        fc_params = fc["model_params"].map(json.loads)
        universe = sorted(set().union(*lists.values()))
        by_pk = {k: g for k, g in d.groupby("product_key")}
        for pk in universe:
            status, bin_, sales, span = runner_status(by_pk[pk], LATEST)
            in_stock = pk in stock.index
            stock_units = float(stock.at[pk, "cases"] or 0) + float(stock.at[pk, "loose_pieces"] or 0) if in_stock else None
            impact_rows.append({
                "product_key": pk, **{f"in_{k}": pk in v for k, v in lists.items()},
                "sales_months_to_2026_02": sales, "months_span": span, "runner_status": status,
                "router_bin": bin_ if bin_ else ("insufficient" if status == "insufficient_data" else "-"),
                "served_model": LIVE_MODEL.get(bin_, "-") if bin_ else "-",
                "in_stock_file_2026_03": in_stock, "stock_above_zero_2026_03": bool(in_stock and stock_units > 0),
                "forecast_today_status": fc.at[pk, "status"] if pk in fc.index else "no forecast row",
                "forecast_today_bin": fc_params[pk].get("bin", "-") if pk in fc.index else "-",
                "forecast_today_sales_months": (fc_params[pk].get("sales_months", fc_params[pk].get("months_with_sales"))
                                                if pk in fc.index else None),
            })
        imp = pd.DataFrame(impact_rows).set_index("product_key")
        today = imp[imp["forecast_today_status"] != "no forecast row"]
        log.append(f"impact check vs today's 132 forecasts: status matches {int((today['runner_status'] == today['forecast_today_status']).sum())}"
                   f"/{len(today)}, bin matches {int((today.loc[today['runner_status'] == 'ok', 'router_bin'] == today.loc[today['runner_status'] == 'ok', 'forecast_today_bin']).sum())}"
                   f"/{int((today['runner_status'] == 'ok').sum())}, sales months match "
                   f"{int((today['sales_months_to_2026_02'] == today['forecast_today_sales_months']).sum())}/{len(today)}")
        today_ok = today[today["runner_status"] == "ok"]
        check("impact_status_matches_todays_forecast", int((today["runner_status"] == today["forecast_today_status"]).sum()), len(today))
        check("impact_bin_matches_todays_forecast", int((today_ok["router_bin"] == today_ok["forecast_today_bin"]).sum()), len(today_ok))
        check("impact_sales_months_match_todays_forecast",
              int((today["sales_months_to_2026_02"] == today["forecast_today_sales_months"]).sum()), len(today))
        name_cols(imp.join(hist[["first_month_with_sales", "last_month_with_sales"]])).to_csv(out / "impact_preview_by_product.csv")
        for k in lists:
            g = imp[imp[f"in_{k}"]]
            ok = g["runner_status"] == "ok"
            no_fc = g["forecast_today_status"] != "ok"
            impact_summary.append({
                "list": k, "products": len(g),
                "history_under_3_months": int((g["sales_months_to_2026_02"] < MIN_MONTHS_WITH_SALES).sum()),
                "history_3_11_months": int(g["sales_months_to_2026_02"].between(3, 11).sum()),
                "history_12_23_months": int(g["sales_months_to_2026_02"].between(12, 23).sum()),
                "history_24_plus_months": int((g["sales_months_to_2026_02"] >= 24).sum()),
                "runner_insufficient_data": int((g["runner_status"] == "insufficient_data").sum()),
                "runner_dead_sku": int((g["runner_status"] == "dead_sku").sum()),
                "runner_ok_short_ma3": int((ok & (g["router_bin"] == "short")).sum()),
                "runner_ok_medium_tsb": int((ok & (g["router_bin"] == "medium")).sum()),
                "runner_ok_long_xgb_ma3": int((ok & (g["router_bin"] == "long")).sum()),
                "in_stock_file_2026_03": int(g["in_stock_file_2026_03"].sum()),
                "stock_above_zero_2026_03": int(g["stock_above_zero_2026_03"].sum()),
                "forecast_ok_today": int((~no_fc).sum()),
                "in_stock_file_no_forecast_today": int((g["in_stock_file_2026_03"] & no_fc).sum()),
                "of_which_no_forecast_row": int((g["in_stock_file_2026_03"] & (g["forecast_today_status"] == "no forecast row")).sum()),
                "of_which_forecast_not_ok": int((g["in_stock_file_2026_03"] & no_fc & (g["forecast_today_status"] != "no forecast row")).sum()),
            })
        pd.DataFrame(impact_summary).to_csv(out / "impact_preview_summary.csv", index=False)
    else:
        log.append("impact preview skipped: run pull_extract.py --only followup first")

    # ---- Extract profile: the aggregate facts the README quotes ------------ #
    # Aggregates only (counts, totals, shares); no source rows.
    prof: list[dict] = []

    def fact(key, value, unit, period="", source=""):
        prof.append({"key": key, "value": value, "unit": unit, "period": period, "source": source})

    meta = json.loads((x / "extract_meta.json").read_text())
    fact("snapshot_main_utc", meta["pulled_at_utc"], "timestamp", source="extract_meta.json")
    for _, r in pd.read_csv(x / "base_counts.csv").iterrows():
        tag = "real" if not r["is_demo"] else f"generated_{r['fill_source']}"
        fact(f"base_table_{tag}_rows", int(r["rows"]), "rows", f"{r['first_month']}..{r['last_month']}", "base_counts")
        fact(f"base_table_{tag}_products", int(r["products"]), "products", f"{r['first_month']}..{r['last_month']}", "base_counts")
    fact("real_rows_used", len(d), "product-months", f"{REAL_START}..{LATEST}", "demand_real")
    fact("real_products_used", d["product_key"].nunique(), "products", f"{REAL_START}..{LATEST}", "demand_real")
    fact("real_months", d["calendar_month"].nunique(), "months", f"{d['calendar_month'].min()}..{d['calendar_month'].max()}", "demand_real")
    fact("real_regions", ";".join(sorted(d["region"].unique())), "region", source="demand_real")
    fact("real_net_amount_total", round(d["net_amount"].sum(), 2), "PHP", f"{REAL_START}..{LATEST}", "demand_real")
    fact("real_negative_net_months", int((d["net_amount"] < 0).sum()), "product-months", f"{REAL_START}..{LATEST}", "demand_real")
    for _, r in d[d["net_amount"].isna()].iterrows():
        fact(f"blank_net_amount_{r['sku_code']}", r["calendar_month"], "month",
             source=f"demand_real: {prod.at[r['product_key'], 'product_name']}")
    monthly_net = d.groupby("calendar_month")["net_amount"].sum()
    for m, v in monthly_net.items():
        fact(f"net_total_{m}", round(v, 2), "PHP", m, "demand_real (net of returns)")
    fact("net_monthly_average_2025", round(monthly_net[[m for m in monthly_net.index if m.startswith("2025")]].mean(), 2),
         "PHP per month", "2025-01..2025-12", "demand_real (net of returns)")
    for m in CHURN_MONTHS:
        s = d.loc[d["calendar_month"] == m, "net_amount"].clip(lower=0).dropna().sort_values(ascending=False)
        fact(f"top10_share_pct_{m}", round(100 * s.iloc[:10].sum() / s.sum(), PCT_DP), "% of month revenue", m,
             "demand_real (negative months as 0)")
    fact("unilever_products_in_master", len(prod), "products", "", "product_dim")
    fact("unilever_products_with_supersedes", int(prod["supersedes_product_key"].notna().sum()), "products", "", "product_dim")
    sold = prod.loc[prod.index.isin(d["product_key"])]
    norm_name = sold["product_name"].str.upper().str.split().str.join(" ")
    codes_per_name = sold.groupby(norm_name).size()
    fact("names_with_more_than_one_code", int((codes_per_name > 1).sum()), "names", f"{REAL_START}..{LATEST}", "product_dim x demand_real")
    fact("codes_under_shared_names", int(codes_per_name[codes_per_name > 1].sum()), "codes", f"{REAL_START}..{LATEST}", "product_dim x demand_real")
    current_names = set(norm_name[norm_name.index.isin(A["1m"])])
    fact("missing_with_exact_name_twin_in_current_tier_a", int(norm_name.reindex(missing).isin(current_names).sum()),
         "products", "", "missing_from_current_tier_a x product_dim")
    if stock_file.exists() and fc_file.exists():
        fmeta = json.loads((x / "extract_meta_followup.json").read_text())
        fact("snapshot_followup_utc", fmeta["pulled_at_utc"], "timestamp", source="extract_meta_followup.json")
        fp = pd.read_csv(x / "demand_fingerprint.csv").iloc[0]
        same = (int(fp["rows"]) == len(d) and int(fp["products"]) == d["product_key"].nunique()
                and abs(float(fp["net_amount"]) - d["net_amount"].sum()) < 0.005)
        check("sales_unchanged_between_snapshots", same, note=f"{int(fp['rows'])} rows, PHP {float(fp['net_amount']):,.2f}")
        sp = pd.read_csv(x / "stock_periods.csv")
        fact("stock_latest_period", sp["_period"].max(), "month", "", "stock_periods")
        fact("stock_products_latest_period", int(sp.loc[sp["_period"] == sp["_period"].max(), "products"].iloc[0]),
             "products", sp["_period"].max(), "stock_periods")
        for _, r in pd.read_csv(x / "forecast_dates.csv").iterrows():
            if r["forecast_date"] == fc["forecast_date"].max():
                fact(f"forecast_rows_{r['status']}", int(r["rows"]), "rows", r["forecast_date"], "forecast_dates")
                fact(f"forecast_generated_{r['status']}", str(r["last_generated"])[:10], "date", r["forecast_date"], "forecast_dates")
    pd.DataFrame(prof).to_csv(out / "extract_profile.csv", index=False)
    pd.DataFrame(checks).to_csv(out / "checks.csv", index=False)

    # ---- Console digest (the README is written from these files) ---------- #
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    print("\n".join(log))
    print(summary.to_string(index=False))
    print(pd.DataFrame(ov).pivot(index="basis_x", columns="basis_y", values="in_both").loc[list(BASES), list(BASES)])
    print(pd.DataFrame(ov).pivot(index="basis_x", columns="basis_y", values="pct_of_x_also_in_y").loc[list(BASES), list(BASES)])
    print(f"missing from current Tier A: {len(missing)}  (12m only {int((miss.in_12m_class_a & ~miss.in_24m_class_a).sum())}, "
          f"24m only {int((~miss.in_12m_class_a & miss.in_24m_class_a).sum())}, both {int((miss.in_12m_class_a & miss.in_24m_class_a).sum())})")
    print(f"current Tier A not in 12m or 24m Class A: {len(extra)}")
    print(lo.pivot(index="planning_list", columns="revenue_measured_over", values="left_out_pct").loc[list(BASES), list(BASES)])
    print(lo.pivot(index="planning_list", columns="revenue_measured_over", values="left_out_php").loc[list(BASES), list(BASES)])
    print(churn_avg)
    print(ch[ch.basis == "1m"].to_string(index=False))
    print(f"calendar: 2024 A {len(a24)}, 2025 A {len(a25)}, stayed {len(a24 & a25)}, entered {len(a25 - a24)}, left {len(a24 - a25)}")
    print(sss.to_string(index=False))
    print(pd.DataFrame(sens)[["basis", "variant", "class_a_primary", "class_a_variant", "products_that_change"]].to_string(index=False))
    print(f"rule 1: list {len(r1)}, added {len(r1_added)}, of the 20 today-only products captured "
          f"{len(r1_added & set(extra))}")
    print(r1_lo.to_string(index=False))
    print(ch[ch.basis == "12m+new"].to_string(index=False))
    if impact_summary:
        print(pd.DataFrame(impact_summary).T.to_string())


if __name__ == "__main__":
    main()
