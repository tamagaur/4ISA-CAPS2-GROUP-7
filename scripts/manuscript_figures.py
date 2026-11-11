"""
scripts/manuscript_figures.py - the Chapter 4 figure programme and the regenerated table data (2026-10-31).

    python -m scripts.manuscript_figures            # read-only on the live database; writes the files below

Every number comes from a query, a stored report or the pinned frozen rows, never typed in:
  live, read-only   GET /dashboard, /category-trends, /dashboard/yoy, /abc, /fsn, /recommendations,
                    /policy-comparison called in-process (scripts/smoke_api.py's pattern), and SQL on
                    mart.sales_month and unilever_sku_demand_fact_real inside BEGIN; SET TRANSACTION READ ONLY
  pinned            docs/published_snapshot_2026-10-24/*.csv (tracked, trimmed columns; hard rule 9 exception of 2026-10-23): the frozen rows behind
                    docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json (accuracy, MASE, error decomposition)
  stored reports    reports/model_bakeoff_unilever_tierA_allmetrics.csv (bake-off),
                    reports/experiment_artifacts/cells_all.csv (half-year block results)

Gate: each figure's data is compared with what the manuscript states (as corrected by
docs/CH4-5_EDITS_2026-10-22_corrected.md and its Tier B, docs/CH4-5_EDITS_2026-10-22.md). A figure that disagrees is
rendered but marked HELD in the manifest and the run exits 2: one of the two is wrong, and neither goes into the paper
until someone settles which.

Writes
  reports/figures/fig_<letter>_<name>.png          300 dpi, greyscale-safe
  reports/figures/FIGURES.md                       manifest: number map, placement, captions, sources, gate results
  docs/MANUSCRIPT_TABLE_DATA_2026-10-30.md         Tables 4.2.19, 4.2.20 and 4.2.4 as paste-ready markdown
"""
from __future__ import annotations

import json
import os
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts.report_target import report_path  # noqa: E402

FIG_DIR = REPO / "reports" / "figures"
MANIFEST = FIG_DIR / "FIGURES.md"
TABLE_DOC = REPO / "docs" / "MANUSCRIPT_TABLE_DATA_2026-10-30.md"
SNAP = REPO / "docs" / "published_snapshot_2026-10-24"
SNAP_JSON = REPO / "docs" / "PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json"
BAKEOFF = REPO / "reports" / "model_bakeoff_unilever_tierA_allmetrics.csv"
CELLS = REPO / "reports" / "experiment_artifacts" / "cells_all.csv"
WINDOW = ("2025-03", "2026-02")
DPI = 300

# Greyscale-safe palette: three lightness steps of one slate hue, so a black-and-white print still separates them;
# a second series also carries a hatch, so nothing is told apart by colour alone.
INK, DARK, MID, LIGHT, FAINT, RULE = "#1a1a1a", "#34465a", "#8a9bb0", "#d3dae2", "#f1f3f5", "#9a9a9a"


# --------------------------------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------------------------------
def connect():
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute("BEGIN")
    cur.execute("SET TRANSACTION READ ONLY")      # transaction-scoped, never session-level (standing rules)
    return conn, cur


def sql(cur, text: str, *args) -> pd.DataFrame:
    cur.execute(text, args)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


def api_get(paths: dict[str, str]) -> dict[str, dict]:
    """GET each route in-process against the live database, read-only (scripts/smoke_api.py's pattern)."""
    warnings.filterwarnings("ignore")
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    from fastapi.testclient import TestClient

    from analytics.config import long_read_db_url
    from backend import deps
    from backend.auth_utils import create_access_token
    from backend.deps import get_current_user, get_token_payload
    from backend.main import app

    deps._db_url = long_read_db_url
    app.dependency_overrides[get_current_user] = get_token_payload
    headers = {"Authorization": "Bearer " + create_access_token(
        user_id=1, email="figures@local", role="admin", full_name="Manuscript figures")}
    client = TestClient(app)
    out = {}
    for key, path in paths.items():
        r = client.get(path, headers=headers)
        if r.status_code != 200:
            raise SystemExit(f"GET {path} returned {r.status_code}: {r.text[:300]}")
        out[key] = r.json()
    return out


def load() -> dict:
    u, rng = "principal=unilever", f"start_period={WINDOW[0]}&end_period={WINDOW[1]}"
    d = {"api": api_get({
        "dashboard": f"/dashboard?{u}&{rng}",
        "category_trends": f"/category-trends?{u}",
        "yoy": f"/dashboard/yoy?{u}&{rng}",
        "abc": f"/abc?{u}",
        "fsn": f"/fsn?{u}",
        "recommendations": f"/recommendations?{u}",
        "policy": f"/policy-comparison?{u}",
    })}
    conn, cur = connect()
    try:
        d["sales_month_u"] = sql(cur, """
            SELECT period, products, pieces::float AS pieces, pesos::float AS pesos FROM mart.sales_month
            WHERE principal = 'unilever' AND data_kind = 'real' ORDER BY period""")
        d["sales_month_dm"] = sql(cur, """
            SELECT period, products AS categories, pesos::float AS pesos FROM mart.sales_month
            WHERE principal = 'delmonte' AND data_kind = 'real' ORDER BY period""")
        d["products_by_year_u"] = sql(cur, """
            SELECT left(period, 4) AS year, COUNT(DISTINCT product_key) AS products FROM mart.sales_mart_real
            WHERE principal = 'unilever' AND in_principal_total GROUP BY 1 ORDER BY 1""")
        d["abc_period"] = d["api"]["abc"]["classification_period"]
        from analytics.classification.orchestrate_abc import _calendar_window
        months12 = _calendar_window(d["abc_period"], 12)
        d["abc_months"] = months12
        d["demand_window"] = sql(cur, """
            SELECT product_key, calendar_month, net_amount::float AS net_amount
            FROM unilever_sku_demand_fact_real WHERE calendar_month = ANY(%s)""", months12)
        d["sku_category"] = sql(cur, """
            SELECT sku_code AS sku_id, category_path FROM product_dimension
            WHERE principal = 'unilever' AND grain = 'sku'""")
    finally:
        conn.rollback()
        conn.close()
    d["acc_rows"] = pd.read_csv(SNAP / "accuracy_as_served_rows.csv")
    d["money"] = pd.read_csv(SNAP / "demand_money.csv")
    d["mase"] = pd.read_csv(SNAP / "mase_rows.csv")
    d["dec"] = pd.read_csv(SNAP / "error_decomposition_row.csv")
    d["pinned"] = json.loads(SNAP_JSON.read_text(encoding="utf-8"))
    d["bakeoff"] = pd.read_csv(BAKEOFF)
    d["cells"] = pd.read_csv(CELLS)
    return d


# --------------------------------------------------------------------------------------------------------------
# Gate and manifest records
# --------------------------------------------------------------------------------------------------------------
@dataclass
class Fig:
    letter: str
    file: str
    title: str
    source: str
    period: str
    not_shown: str
    chart_note: str = ""                 # why the chart type differs from the one asked for, if it does
    checks: list = field(default_factory=list)

    def check(self, label: str, got, expected, tol: float = 0.0, basis: str = ""):
        ok = (abs(float(got) - float(expected)) <= tol) if isinstance(expected, (int, float)) else got == expected
        self.checks.append((label, got, expected, ok, basis))

    @property
    def held(self) -> bool:
        return not all(c[3] for c in self.checks)


def style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5,
        "axes.edgecolor": RULE, "axes.linewidth": 0.6, "axes.labelcolor": INK, "text.color": INK,
        "xtick.color": INK, "ytick.color": INK, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
        "legend.fontsize": 7.5, "hatch.linewidth": 0.6, "hatch.color": INK, "savefig.dpi": DPI,
        "figure.dpi": 100,
    })
    return plt


def ygrid(ax, axis="y"):
    ax.grid(axis=axis, color="#e4e4e4", linewidth=0.5)
    ax.set_axisbelow(True)


def footnote(fig, f: Fig) -> int:
    import textwrap
    width = int(fig.get_figwidth() * 23)          # about 23 characters per inch at 6 pt
    lines = (textwrap.wrap(f"Source: {f.source}. Period: {f.period}.", width)
             + textwrap.wrap(f"Not shown: {f.not_shown}.", width))
    fig.text(0.01, 0.008, "\n".join(lines), fontsize=6, color="#555555", ha="left", va="bottom")
    return len(lines)


def save(plt, fig, f: Fig, axis_room: float = 0.75, left: float | None = None, top: float = 0.93):
    """Footnote below the plot, sized to its own line count; axis_room = inches kept for tick labels and x label."""
    n = footnote(fig, f)
    h = fig.get_figheight()
    fig.subplots_adjust(bottom=(axis_room + 0.11 * n + 0.05) / h, top=top, **({"left": left} if left else {}))
    out = report_path(FIG_DIR / f.file)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor="white")
    plt.close(fig)
    return out


def mlabel(period: str) -> str:
    return pd.Period(period, freq="M").strftime("%b\n%Y")


def millions(x, _=None):
    return f"{x / 1e6:,.1f}"


# --------------------------------------------------------------------------------------------------------------
# Descriptive
# --------------------------------------------------------------------------------------------------------------
TABLE_4_2_2 = {  # manuscript Table 4.2.2: products, pieces, sales (PHP), stock at the next count (PHP)
    "2025-03": (674, 2980860, 33913905, 17097461), "2025-04": (665, 2604299, 33842385, 14311521),
    "2025-05": (732, 2950465, 36754602, 14352667), "2025-06": (708, 2749835, 36824032, 29876123),
    "2025-07": (708, 2175958, 28495632, 35169741), "2025-08": (716, 2440016, 32668408, 22809045),
    "2025-09": (774, 2164569, 35389246, 29825670), "2025-10": (768, 2216989, 35791064, 23952053),
    "2025-11": (754, 2115701, 33181824, 29965754), "2025-12": (687, 1350508, 19171732, 36277134),
    "2026-01": (770, 2565570, 37165964, 24339386), "2026-02": (779, 1766710, 27914344, 46576779),
}


def fig_a(plt, d) -> Fig:
    f = Fig("a", "fig_a_monthly_sales_stock.png", "Monthly Pieces Sold and Stock on Hand, Unilever",
            "mart.sales_month (real rows, pieces sold); GET /dashboard sales_vs_stock (stock on hand at the count "
            "taken after each month, last purchase price)", "March 2025 – February 2026",
            "stock in pieces; peso sales (Table 4.2.2); the 2 March 2026 count (₱46.6 M) is flagged as unusually "
            "high and SSM has not confirmed it; stock is counted at the Ilocos Sur warehouse while sales are La Union's",
            chart_note="Two panels on one month axis instead of one chart with two y-axes: pieces and pesos do not "
                       "share a scale, and a second axis makes the bar tops and the line appear to cross where "
                       "nothing meets.")
    sm = d["sales_month_u"].set_index("period").loc[WINDOW[0]:WINDOW[1]]
    svs = pd.DataFrame(d["api"]["dashboard"]["sales_vs_stock"]).set_index("period")
    months = list(sm.index)
    for m in months:
        prod, pcs, pesos, stock = TABLE_4_2_2[m]
        f.check(f"{m} products sold", int(sm.loc[m, "products"]), prod, basis="Table 4.2.2")
        f.check(f"{m} pieces sold", round(sm.loc[m, "pieces"]), pcs, basis="Table 4.2.2")
        f.check(f"{m} stock at next count (PHP)", round(svs.loc[m, "stock_on_hand"]), stock, basis="Table 4.2.2")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6.5, 4.8), sharex=True, gridspec_kw={"height_ratios": [1, 1]})
    x = np.arange(len(months))
    ax1.bar(x, sm["pieces"], width=0.62, color=MID, edgecolor=DARK, linewidth=0.5)
    ax1.yaxis.set_major_formatter(millions)
    ax1.set_ylabel("Pieces sold (millions)")
    ygrid(ax1)
    for i, v in enumerate(sm["pieces"]):
        ax1.text(i, v, f"{v / 1e6:.2f}", ha="center", va="bottom", fontsize=6.5)
    stock = svs.loc[months, "stock_on_hand"]
    ax2.plot(x, stock, color=DARK, linewidth=1.6, marker="o", markersize=4)
    ax2.yaxis.set_major_formatter(millions)
    ax2.set_ylabel("Stock on hand (₱ millions,\nlast purchase price)")
    ygrid(ax2)
    ax2.set_ylim(0, stock.max() * 1.18)
    last = len(months) - 1
    ax2.annotate("2 Mar 2026 count: ₱46.6 M,\nflagged unusually high,\nnot confirmed by SSM", (last, stock.iloc[-1]),
                 xytext=(last - 3.6, stock.iloc[-1] * 0.93), fontsize=6.5, arrowprops={"arrowstyle": "-", "lw": 0.6})
    ax2.set_xticks(x, [mlabel(m) for m in months])
    ax2.set_xlabel("Sales month (stock is the count taken at the start of the next month)")
    save(plt, fig, f)
    return f


def fig_b(plt, d) -> Fig:
    f = Fig("b", "fig_b_annual_value_volume.png", "Annual Sales Value and Volume, Unilever (Index, 2023 = 100)",
            "mart.sales_month (real rows), the same totals as GET /dashboard annual_sales", "2023 – 2025 (complete years)",
            "January–February 2026 (two months only, not a comparable year); prices and product mix behind the "
            "value-volume gap; pesos are selling price, VAT-inclusive",
            chart_note="Indexed to 2023 = 100 rather than pesos and pieces side by side on one axis: the two have no "
                       "common unit, and the question is whether each moved, which an index shows directly.")
    sm = d["sales_month_u"].assign(year=lambda t: t.period.str[:4])
    yr = sm.groupby("year").agg(months=("period", "count"), pieces=("pieces", "sum"), pesos=("pesos", "sum"))
    expected = {"2023": (384841053.64, 33284208), "2024": (387302339.20, 33748183), "2025": (393416242.63, 29523549)}
    api_years = {str(y["year"]): y["sales"] for y in d["api"]["dashboard"]["annual_sales"]["years"]}
    for y, (pes, pcs) in expected.items():
        f.check(f"{y} sales (PHP)", round(yr.loc[y, "pesos"], 2), pes, tol=0.005, basis="Table 4.2.3")
        f.check(f"{y} sales, GET /dashboard (PHP)", round(api_years[y], 2), pes, tol=0.005, basis="Table 4.2.3")
        f.check(f"{y} pieces", round(yr.loc[y, "pieces"]), pcs, basis="Table 4.2.3")
        f.check(f"{y} months", int(yr.loc[y, "months"]), 12, basis="Table 4.2.3")
    years = list(expected)
    pes_idx = [100 * yr.loc[y, "pesos"] / yr.loc["2023", "pesos"] for y in years]
    pcs_idx = [100 * yr.loc[y, "pieces"] / yr.loc["2023", "pieces"] for y in years]
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    x = np.arange(len(years))
    w = 0.36
    b1 = ax.bar(x - w / 2, pes_idx, w, color=DARK, label="Sales value (pesos)")
    b2 = ax.bar(x + w / 2, pcs_idx, w, color=LIGHT, edgecolor=DARK, hatch="////", linewidth=0.5,
                label="Sales volume (pieces)")
    for bar, y in zip(b1, years):
        ax.text(bar.get_x() + w / 2, bar.get_height() + 1, f"{bar.get_height():.1f}\n₱{yr.loc[y, 'pesos'] / 1e6:,.1f} M",
                ha="center", va="bottom", fontsize=6.5)
    for bar, y in zip(b2, years):
        ax.text(bar.get_x() + w / 2, bar.get_height() + 1, f"{bar.get_height():.1f}\n{yr.loc[y, 'pieces'] / 1e6:,.1f} M pcs",
                ha="center", va="bottom", fontsize=6.5)
    ax.axhline(100, color=RULE, linewidth=0.7, linestyle="--")
    ax.set_ylim(0, 125)
    ax.set_xticks(x, years)
    ax.set_xlabel("Calendar year (12 months each)")
    ax.set_ylabel("Index, 2023 = 100")
    ax.legend(loc="lower right", ncol=2, bbox_to_anchor=(1, 1.0))
    ygrid(ax)
    save(plt, fig, f)
    return f


CATEGORY_LABEL = {"DEODORANTS & FRAGRANCES": "Deodorants & Fragrances", "HOME & HYGIENE": "Home & Hygiene"}


def cat_name(c: str) -> str:
    return CATEGORY_LABEL.get(c, c.title())


TABLE_4_2_4_SALES = {  # manuscript Table 4.2.4, Sales (PHP)
    "COOKING AIDS": 97376426, "HAIR CARE": 90239263, "FABRIC CLEANING": 79765275, "CONDIMENTS": 61050507,
    "DEODORANTS & FRAGRANCES": 24298824, "FABRIC ENHANCERS": 14277793, "SKIN CARE": 9849363, "ORAL CARE": 7276253,
    "SKIN CLEANSING": 4980783, "HOME & HYGIENE": 2050280, "OTHER FOODS": 732264, "UNCLASSIFIED": 705354,
    "MINI MEALS": 50790, "SCRATCH COOKING AIDS": 167, "DRESSINGS": 2323,
}


def category_table(d) -> pd.DataFrame:
    cats = pd.DataFrame(d["api"]["category_trends"]["principals"][0]["categories"])
    cats["revenue"] = cats.revenue_last_12.fillna(0.0)
    cats["share"] = cats.revenue / cats.revenue.sum()
    return cats.sort_values("revenue", ascending=False).reset_index(drop=True)


def fig_c(plt, d) -> Fig:
    f = Fig("c", "fig_c_sales_by_category.png", "Sales by Category, Unilever",
            "GET /category-trends (revenue over the last 12 observed months; a negative month counts as 0)",
            "March 2025 – February 2026",
            "year-over-year change and trend (Table 4.2.4); categories under 0.1% of revenue have bars too short to "
            "see and are read from their labels; Other Nutrition sold nothing in the window")
    cats = category_table(d)
    for c, v in TABLE_4_2_4_SALES.items():
        got = cats.set_index("category").loc[c, "revenue"]
        f.check(f"{c} sales (PHP)", round(got), v, basis="Table 4.2.4")
    f.check("categories", len(cats), 16, basis="Category Trends route (Table 4.2.4 lists 15)")
    top4 = cats.head(4).share.sum()
    f.check("top four categories' share", round(100 * top4, 1), 83.6, basis="§4.2.1.1.3 prose")
    fig, ax = plt.subplots(figsize=(6.5, 4.6))
    y = np.arange(len(cats))[::-1]
    ax.barh(y, cats.revenue, height=0.66, color=MID, edgecolor=DARK, linewidth=0.5)
    for yi, (_, r) in zip(y, cats.iterrows()):
        pct = f"{100 * r.share:.2f}%" if r.share >= 0.0001 else "< 0.01%"
        lab = (f"₱{r.revenue / 1e6:,.1f} M · {100 * r.share:.1f}%" if r.revenue >= 1e6 else
               f"₱{r.revenue:,.0f} · {pct}" if r.revenue > 0 else "₱0 · no sale in the window")
        ax.text(r.revenue + cats.revenue.max() * 0.01, yi, lab, va="center", fontsize=6.8)
    ax.set_yticks(y, [cat_name(c) for c in cats.category])
    ax.xaxis.set_major_formatter(millions)
    ax.set_xlim(0, cats.revenue.max() * 1.28)
    ax.set_xlabel("Sales, ₱ millions (selling price, VAT-inclusive) · label: sales and share of revenue")
    ygrid(ax, "x")
    save(plt, fig, f, axis_room=0.6, left=0.27)
    return f


def abc_frame(d) -> pd.DataFrame:
    """Per-product 12-month revenue by the classifier's own rule (orchestrate_abc._window_revenue), joined to the
    stored t12m_new class; checked against the stored 4-decimal shares."""
    from analytics.classification.orchestrate_abc import _window_revenue
    rev, _blank = _window_revenue(d["demand_window"], d["abc_months"])
    rev = rev.rename(columns={"sku_id": "product_key"}).sort_values("total_revenue", ascending=False)
    items = pd.DataFrame(d["api"]["abc"]["items"])[["product_key", "tier", "revenue_share", "cumulative_share"]]
    x = items.merge(rev, on="product_key", how="left")
    x["share_calc"] = x.total_revenue / rev.total_revenue.sum()
    x = x.sort_values("total_revenue", ascending=False, na_position="last").reset_index(drop=True)
    x["cum"] = x.total_revenue.fillna(0).cumsum() / rev.total_revenue.sum()
    x["rank"] = np.arange(1, len(x) + 1)
    return x


def fig_d(plt, d) -> Fig:
    abc = d["api"]["abc"]
    pc = abc["pareto_check"]
    f = Fig("d", "fig_d_abc_pareto.png", "ABC Pareto Curve, Unilever (Tier A as of 2026-02, basis t12m_new)",
            "unilever_sku_demand_fact_real, revenue by the classifier's rule (analytics/classification/orchestrate_abc."
            "_window_revenue); class from GET /abc (abc_classification, method t12m_new)",
            f"{d['abc_months'][0]} – {d['abc_months'][-1]} (12 months to the classification period 2026-02)",
            "products with no positive revenue in the window (not ranked); the new-product rule's 3-month ranking "
            "(a Class A product added as new sits at its 12-month rank); the Pareto check applies at the top 20% only")
    x = abc_frame(d)
    summ = {t["tier"]: t for t in abc["tier_summary"]}
    for t, n, share in (("A", 189, 81.0), ("B", 230, 14.0), ("C", 672, 4.6)):
        f.check(f"Class {t} products", summ[t]["sku_count"], n, basis="Table 4.2.5")
        f.check(f"Class {t} share of revenue (%)", round(100 * summ[t]["revenue_share_total"], 1), share,
                basis="Table 4.2.5")
    f.check("products ranked", len(x), 1091, basis="Table 4.2.5")
    f.check("top 20% count", pc["top_count"], 219, basis="§4.2.1.1.4 prose")
    f.check("top 20% share (%)", round(100 * pc["revenue_share"], 1), 84.4, basis="§4.2.1.1.4 prose")
    stored = x.dropna(subset=["revenue_share", "share_calc"])
    f.check("recomputed shares equal stored 4-decimal shares (rows differing)",
            int((abs(stored.share_calc.round(4) - stored.revenue_share.astype(float)) > 0.00005).sum()), 0,
            basis="abc_classification.revenue_share")
    added = int(((x.tier == "A") & (x.cum > 0.8 + 1e-9)).sum())
    fig, ax = plt.subplots(figsize=(6.5, 3.9))
    shade = {"A": DARK, "B": MID, "C": LIGHT}
    for t in "ABC":
        s = x[x.tier == t]
        ax.bar(s["rank"], s.total_revenue.fillna(0), width=1.0, color=shade[t], linewidth=0,
               label=f"Class {t}: {summ[t]['sku_count']} products, {100 * summ[t]['revenue_share_total']:.1f}% of revenue")
    ax.yaxis.set_major_formatter(millions)
    ax.set_ylabel("Revenue per product (₱ millions)")
    ax.set_xlabel("Products ranked by 12-month revenue (rank 1 = highest)")
    ax.set_xlim(0, len(x) + 1)
    ax2 = ax.twinx()
    ax2.spines["right"].set_visible(True)
    ax2.axhspan(75, 85, color=FAINT, zorder=0)
    ax2.plot(x["rank"], 100 * x.cum, color=INK, linewidth=1.3, label="Cumulative share of revenue")
    ax2.axhline(80, color=INK, linewidth=0.7, linestyle="--")
    ax2.axvline(pc["top_count"], color=INK, linewidth=0.7, linestyle=":")
    ax2.set_ylim(0, 102)
    ax2.set_ylabel("Cumulative share of revenue (%)")
    ax2.text(len(x) * 0.99, 80.8, "80% (Class A cut-off)", ha="right", va="bottom", fontsize=6.5)
    ax2.text(len(x) * 0.99, 75.6, "Pareto check band, 75–85%", ha="right", va="bottom", fontsize=6.5, color="#555555")
    ax2.annotate(f"Top 20% = {pc['top_count']} products,\n{100 * pc['revenue_share']:.1f}% of revenue (check passes)",
                 (pc["top_count"], 100 * pc["revenue_share"]), xytext=(pc["top_count"] + 120, 52), fontsize=6.5,
                 arrowprops={"arrowstyle": "-", "lw": 0.6})
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="center right", bbox_to_anchor=(1.0, 0.32))
    f.not_shown += f"; {added} Class A products sit beyond the 80% line because the new-product rule added them"
    save(plt, fig, f)
    return f


def fig_e(plt, d) -> Fig:
    f = Fig("e", "fig_e_fsn_by_abc.png", "FSN Movement by ABC Class, Unilever (Tier A as of 2026-02)",
            "GET /fsn (movement over the latest 12 observed months) joined to GET /abc (class, t12m_new)",
            "March 2025 – February 2026",
            "products with no ABC class (none in this period); movement in pieces or pesos; the ADI value behind each label")
    abc = pd.DataFrame(d["api"]["abc"]["items"])[["product_key", "tier"]]
    fsn = pd.DataFrame(d["api"]["fsn"]["items"])[["product_key", "fsn"]]
    j = abc.merge(fsn, on="product_key", how="left")
    ct = pd.crosstab(j.tier, j.fsn).reindex(columns=["F", "S", "N"], fill_value=0)
    expected = {"A": (164, 20, 5), "B": (190, 24, 16), "C": (265, 307, 100)}
    for t, vals in expected.items():
        for k, v in zip("FSN", vals):
            f.check(f"Class {t} {k}", int(ct.loc[t, k]), v, basis="Table 4.2.7")
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    labels = {"F": "Fast-moving", "S": "Slow-moving", "N": "Non-moving"}
    look = {"F": (DARK, None), "S": (MID, "////"), "N": (LIGHT, "xxxx")}
    x = np.arange(3)
    bottom = np.zeros(3)
    tot = ct.loc[["A", "B", "C"]].sum(axis=1).to_numpy()
    side_y = [-1e9] * 3                      # last label placed beside each bar, to keep side labels apart
    for k in "FSN":
        vals = ct.loc[["A", "B", "C"], k].to_numpy()
        col, hat = look[k]
        ax.bar(x, vals, 0.55, bottom=bottom, color=col, hatch=hat, edgecolor=INK if hat else col, linewidth=0.4,
               label=labels[k])
        for i, v in enumerate(vals):
            text = f"{labels[k].split('-')[0]} {v} ({100 * v / tot[i]:.0f}%)"
            if v >= 60:
                ax.text(i, bottom[i] + v / 2, f"{v} ({100 * v / tot[i]:.0f}%)", ha="center", va="center", fontsize=6.8,
                        color="white" if k == "F" else INK,
                        bbox=None if k == "F" else {"facecolor": "white", "edgecolor": "none", "pad": 0.6})
            elif v:
                yv = max(bottom[i] + v / 2, side_y[i] + 26)
                side_y[i] = yv
                ax.annotate(text, (i + 0.275, bottom[i] + v / 2), xytext=(i + 0.34, yv), va="center", fontsize=6.6,
                            arrowprops={"arrowstyle": "-", "lw": 0.5})
        bottom += vals
    for i, t in enumerate(bottom):
        ax.text(i, t + 8, f"{int(t)} products", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x, ["Class A", "Class B", "Class C"])
    ax.set_ylabel("Products")
    ax.set_xlabel("ABC class")
    ax.legend(loc="upper left")
    ygrid(ax)
    save(plt, fig, f)
    return f


TABLE_4_2_10 = {
    "2023-01": 6134828, "2023-02": 7183065, "2023-03": 8197749, "2023-04": 7633625, "2023-05": 7001997,
    "2023-06": 6659934, "2023-08": 7727320, "2023-09": 9083690, "2023-11": 11017181, "2024-01": 15462409,
    "2024-02": 5850797, "2025-03": 7141101, "2025-04": 8891943, "2025-06": 10847270, "2025-08": 7898602,
    "2025-09": 7806453, "2025-12": 22134296,
}


def fig_f(plt, d) -> Fig:
    f = Fig("f", "fig_f_delmonte_monthly.png", "Monthly Sales, Del Monte (months not collected shown as gaps)",
            "mart.sales_month (Del Monte, real rows; from SellOut_Fact_Real)", "January 2023 – December 2025",
            "the 19 uncollected months as any value (they are gaps, not zero sales); categories or products; pesos are "
            "selling price, ex-VAT; months before and after the January 2025 taxonomy change use different category lists")
    dm = d["sales_month_dm"].set_index("period")
    for m, v in TABLE_4_2_10.items():
        f.check(f"{m} sales (PHP)", round(dm.loc[m, "pesos"]) if m in dm.index else -1, v, basis="Table 4.2.10")
    f.check("collected months", len(dm), 17, basis="Table 4.2.10")
    f.check("total (PHP)", round(dm.pesos.sum()), 156672259, basis="Table 4.2.10")
    months = [str(p) for p in pd.period_range("2023-01", "2025-12", freq="M")]
    fig, ax = plt.subplots(figsize=(6.5, 3.7))
    top = dm.pesos.max() * 1.12
    x = np.arange(len(months))
    for i, m in enumerate(months):
        if m in dm.index:
            ax.bar(i, dm.loc[m, "pesos"], 0.7, color=MID, edgecolor=DARK, linewidth=0.5)
        else:
            ax.bar(i, top, 0.92, color="white", edgecolor=RULE, hatch="....", linewidth=0.3, zorder=0)
    runs, start = [], None
    for i, m in enumerate(months + ["end"]):
        missing = m != "end" and m not in dm.index
        if missing and start is None:
            start = i
        if not missing and start is not None:
            runs.append((start, i - 1))
            start = None
    for a, b in runs:
        mid = (a + b) / 2
        txt = "not collected" if a == b else f"not collected\n({b - a + 1} months)"
        ax.text(mid, top * 0.5, txt, rotation=90 if a == b else 0, ha="center", va="center", fontsize=6,
                color="#555555", bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.5})
    brk = months.index("2025-01")
    ax.axvline(brk - 0.5, color=INK, linewidth=0.8, linestyle="--")
    ax.text(brk - 0.4, top * 1.01, "Jan 2025: category list changed (82 paths → 5)", fontsize=6.3, va="bottom")
    ax.yaxis.set_major_formatter(millions)
    ax.set_ylim(0, top * 1.08)
    ax.set_ylabel("Sales (₱ millions, ex-VAT)")
    ax.set_xticks(x[::3], [mlabel(m) for m in months[::3]])
    ax.set_xlabel("Month (17 of 36 collected; hatched columns are months with no data)")
    import matplotlib.patches as mpatches
    ax.legend(handles=[mpatches.Patch(facecolor=MID, edgecolor=DARK, label="Sales, collected month"),
                       mpatches.Patch(facecolor="white", edgecolor=RULE, hatch="....",
                                      label="Not collected: no data, not zero sales")],
              loc="lower left", bbox_to_anchor=(0, 1.06), ncol=2)
    save(plt, fig, f, top=0.85)
    return f


# --------------------------------------------------------------------------------------------------------------
# Predictive
# --------------------------------------------------------------------------------------------------------------
BAKEOFF_NAMES = {
    "hw_add12": "Holt-Winters additive", "sba_a3": "SBA (α = 0.3)", "theta": "Theta", "sarima_plain": "ARIMA(1,1,1)",
    "tsb": "TSB", "ma3": "MA3", "ses": "SES", "ma6": "MA6", "holt": "Holt", "holt_damped": "Damped Holt",
    "sba": "SBA (α = 0.1)", "croston": "Croston", "snaive12": "Seasonal naive (12)",
    "sarima_seasonal": "SARIMA(1,1,1)(0,1,1)12", "mean": "Mean", "naive": "Naive", "drift": "Drift",
}
TABLE_4_2_13 = {"hw_add12": (0.741, 62), "sba_a3": (0.788, 89), "theta": (0.792, 89), "sarima_plain": (0.804, 89),
                "tsb": (0.815, 89), "ma3": (0.819, 89), "ses": (0.821, 89), "ma6": (0.836, 89), "holt": (0.841, 89),
                "holt_damped": (0.854, 89), "sba": (0.875, 89), "croston": (0.910, 89), "snaive12": (0.953, 89),
                "sarima_seasonal": (0.989, 49), "mean": (1.014, 89), "naive": (1.081, 89), "drift": (1.097, 89)}


def fig_g(plt, d) -> Fig:
    f = Fig("g", "fig_g_bakeoff_mase.png", "Forecasting Model Bake-off: Median MASE of 17 Candidates, Unilever Tier A",
            "reports/model_bakeoff_unilever_tierA_allmetrics.csv (reports/MODEL_BAKEOFF_UNILEVER.md, 1 September 2026; "
            "rolling one step ahead, last 6 months, 89 evaluable products)", "last 6 months of history at the bake-off",
            "a like-for-like ranking: Holt-Winters ran on 62 products and SARIMA on 49 (they need 24 and 28 months), so "
            "their medians are over different, easier product sets; spread across products; MAPE and sMAPE; any "
            "significance test (no candidate beat MA3 at p < 0.05)")
    b = d["bakeoff"]
    e = b[b.evaluable == True]  # noqa: E712  (the CSV's own boolean column)
    rows = []
    for k, name in BAKEOFF_NAMES.items():
        s = e[f"{k}_mase"].dropna()
        rows.append((k, name, float(s.median()), len(s)))
        f.check(f"{name} median MASE", round(float(s.median()), 3), TABLE_4_2_13[k][0], tol=0.0005, basis="Table 4.2.13")
        f.check(f"{name} products", len(s), TABLE_4_2_13[k][1], basis="Table 4.2.13")
    r = pd.DataFrame(rows, columns=["key", "name", "mase", "n"]).sort_values("mase").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(6.5, 4.6))
    y = np.arange(len(r))[::-1]
    for yi, row in zip(y, r.itertuples()):
        is_ma3, partial = row.key == "ma3", row.n < 89
        ax.barh(yi, row.mase, 0.66, color=DARK if is_ma3 else (LIGHT if partial else MID),
                hatch="////" if partial else None, edgecolor=INK if partial else (DARK if is_ma3 else MID), linewidth=0.4)
        ax.text(row.mase + 0.01, yi, f"{row.mase:.3f}  (n = {row.n})" + ("  ← fewer products" if partial else ""),
                va="center", fontsize=6.8, fontweight="bold" if is_ma3 else "normal", zorder=3,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.4})
    ax.axvline(1.0, color=INK, linewidth=0.7, linestyle="--")
    ax.text(1.0, len(r) - 0.2, " MASE = 1: no better than naive", fontsize=6.5, va="bottom")
    ax.set_yticks(y, r.name)
    for lab in ax.get_yticklabels():
        if lab.get_text() == "MA3":
            lab.set_fontweight("bold")
    ax.set_xlim(0, 1.42)
    ax.set_ylim(-0.7, len(r) + 0.6)
    ax.set_xlabel("Median MASE across products (lower is better; below 1 beats repeating last month)")
    import matplotlib.patches as mpatches
    ax.legend(handles=[mpatches.Patch(color=DARK, label="MA3, the deployed baseline"),
                       mpatches.Patch(color=MID, label="Other candidate, all 89 products"),
                       mpatches.Patch(facecolor=LIGHT, hatch="////", edgecolor=INK,
                                      label="Fewer products (not like-for-like)")],
              loc="lower left", bbox_to_anchor=(-0.35, 1.01), ncol=3, fontsize=6.8)
    ygrid(ax, "x")
    save(plt, fig, f, axis_room=0.55, left=0.27, top=0.9)
    return f


TABLE_4_2_18 = {  # forecast, actual, WAPE %, direction, surplus PHP, shortage PHP
    "2025-03": (2603372, 2778221, 20.3, "under", 3376570, 3851955),
    "2025-04": (2381632, 2414740, 22.1, "under", 2486130, 4944467),
    "2025-05": (2626451, 2716507, 22.0, "under", 2911738, 3752116),
    "2025-06": (2694583, 2410537, 37.1, "over", 5365124, 4403057),
    "2025-07": (2365326, 1810204, 46.9, "over", 7375371, 1509676),
    "2025-08": (2125154, 2020695, 41.4, "over", 3848422, 4247026),
    "2025-09": (2341533, 1858820, 40.0, "over", 5252297, 5056550),
    "2025-10": (1988739, 1998704, 41.7, "under", 4291229, 7385082),
    "2025-11": (2082199, 1887211, 32.4, "over", 4944624, 3907377),
    "2025-12": (1810379, 1257232, 58.3, "over", 9967556, 1931876),
    "2026-01": (2274480, 2263527, 46.4, "over", 7527223, 4485523),
    "2026-02": (1887478, 1601138, 35.2, "over", 6421262, 2481131),
}


def monthly_accuracy(d) -> pd.DataFrame:
    """Table 4.2.18 from the frozen as-served rows (calendar-adjusted run), scored as the dashboard's accuracy card
    scores it (backend/marts.accuracy_summary_from over mart.accuracy_mart): actual = net pieces sold (a month whose
    returns exceed sales stays negative), price per piece = the product's pesos over pieces across all its scored
    months, NULL when either sum is not positive (migration 0043)."""
    r = d["acc_rows"]
    c = r[r.run == "as_served_calendar"].merge(d["money"], on=["product_key", "month"], how="left")
    c["act"] = c.quantity_raw.fillna(0.0)
    g = c.assign(p=c.net_amount.fillna(0.0)).groupby("product_key")
    sp, sq = g.p.sum(), g.act.sum()
    price = (sp / sq).where((sp > 0) & (sq > 0))
    c["price"] = c.product_key.map(price)
    w = c[(c.month >= WINDOW[0]) & (c.month <= WINDOW[1])].copy()
    w["abs"] = (w.value - w.act).abs()
    w["sur"] = (w.value - w.act).clip(lower=0) * w.price
    w["sho"] = (w.act - w.value).clip(lower=0) * w.price
    m = w.groupby("month").agg(products=("product_key", "nunique"), forecast=("value", "sum"), actual=("act", "sum"),
                               abs=("abs", "sum"), surplus=("sur", "sum"), shortage=("sho", "sum"))
    m["wape"] = 100 * m["abs"] / m.actual
    m["direction"] = np.where(m.forecast > m.actual, "over", "under")
    return m


def check_monthly(f: Fig, m: pd.DataFrame, cols: tuple[str, ...]):
    for mo, (fc, ac, wape, dirn, sur, sho) in TABLE_4_2_18.items():
        exp = {"forecast": fc, "actual": ac, "wape": wape, "direction": dirn, "surplus": sur, "shortage": sho}
        for col in cols:
            got = m.loc[mo, col]
            if col == "wape":
                f.check(f"{mo} WAPE (%)", round(got, 1), wape, basis="Table 4.2.18")
            elif col == "direction":
                f.check(f"{mo} direction", got, dirn, basis="Table 4.2.18")
            else:  # whole units; the table's per-cell rounding can differ by 1 from the rounded sum
                f.check(f"{mo} {col}", round(got), exp[col], tol=1, basis="Table 4.2.18")


ACC_SOURCE = ("docs/published_snapshot_2026-10-24 frozen as-served rows (calendar-adjusted run; pinned by "
              "docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json), scored as GET /dashboard forecast_accuracy scores them")


def fig_h(plt, d) -> Fig:
    f = Fig("h", "fig_h_forecast_vs_actual.png", "Forecast against Actual Pieces by Month, Unilever (as-served backtest)",
            ACC_SOURCE, "March 2025 – February 2026",
            "live performance (this is a backtest: each month forecast from the months before it); per-product error, "
            "which is far larger than the total's (median product WAPE about 40%); products not forecast that month")
    m = monthly_accuracy(d)
    check_monthly(f, m, ("forecast", "actual", "direction"))
    over = m.direction.eq("over")
    f.check("over-forecast months", int(over.sum()), 8, basis="edit list item 7")
    fig, ax = plt.subplots(figsize=(6.5, 3.7))
    x = np.arange(len(m))
    for i, o in enumerate(over):
        if o:
            ax.axvspan(i - 0.5, i + 0.5, color=FAINT, zorder=0)
    ax.plot(x, m.actual, color=INK, linewidth=1.6, marker="o", markersize=4, label="Actual pieces sold (net of returns)")
    ax.plot(x, m.forecast, color=DARK, linewidth=1.4, linestyle="--", marker="s", markersize=3.6, markerfacecolor="white",
            label="Forecast (as served, calendar-adjusted)")
    for i, o in enumerate(over):
        if o:
            ax.text(i, m[["actual", "forecast"]].max().max() * 1.07, "▲ over", ha="center", fontsize=6)
    ax.yaxis.set_major_formatter(millions)
    ax.set_ylim(0, m[["actual", "forecast"]].max().max() * 1.15)
    ax.set_ylabel("Pieces (millions)")
    ax.set_xticks(x, [mlabel(p) for p in m.index])
    ax.set_xlabel(f"Month (shaded = forecast above actual: {int(over.sum())} of 12 months)")
    ax.legend(loc="lower left")
    ygrid(ax)
    save(plt, fig, f)
    return f


def fig_i(plt, d) -> Fig:
    f = Fig("i", "fig_i_monthly_wape.png", "Monthly WAPE in Pieces, Unilever (as-served backtest)", ACC_SOURCE,
            "March 2025 – February 2026",
            "live performance (a backtest); the median product WAPE (35.49% for this window, a different measure); "
            "error in pesos; months before March 2025")
    m = monthly_accuracy(d)
    check_monthly(f, m, ("wape",))
    med = float(np.median(m.wape))
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    x = np.arange(len(m))
    ax.plot(x, m.wape, color=DARK, linewidth=1.6, marker="o", markersize=4)
    for i, v in enumerate(m.wape):
        below = i > 0 and v < m.wape.iloc[i - 1] and i < len(m) - 1 and v < m.wape.iloc[i + 1]
        ax.text(i, v - 2.2 if below else v + 1.6, f"{v:.1f}%", ha="center", va="top" if below else "bottom",
                fontsize=6.5)
    ax.axhline(med, color=INK, linewidth=0.8, linestyle="--")
    ax.text(-0.3, med + 1.2, f"Median of the 12 monthly values: {med:.1f}%", ha="left", va="bottom", fontsize=6.8)
    ax.set_ylim(0, max(m.wape) * 1.18)
    ax.set_ylabel("WAPE, pieces (%)\nΣ|forecast − actual| ÷ Σ actual")
    ax.set_xticks(x, [mlabel(p) for p in m.index])
    ax.set_xlabel("Month")
    ygrid(ax)
    save(plt, fig, f)
    return f


def fig_j(plt, d) -> Fig:
    f = Fig("j", "fig_j_surplus_shortage.png", "Surplus against Shortage by Month, Unilever (as-served backtest, pesos)",
            ACC_SOURCE, "March 2025 – February 2026",
            "observed stockouts or overstock (these are forecast misses valued at each product's average selling price, "
            "not stock outcomes); live performance; products with no price (net pesos or pieces not positive)")
    m = monthly_accuracy(d)
    check_monthly(f, m, ("surplus", "shortage"))
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    x = np.arange(len(m))
    ax.bar(x, m.surplus, 0.62, color=DARK, label="Surplus: forecast above actual (over-forecast)")
    ax.bar(x, -m.shortage, 0.62, color=LIGHT, hatch="////", edgecolor=INK, linewidth=0.4,
           label="Shortage: actual above forecast (under-forecast)")
    lim = max(m.surplus.max(), m.shortage.max()) * 1.25
    ax.set_ylim(-lim, lim)
    ax.axhline(0, color=INK, linewidth=0.8)
    for i, (s, h) in enumerate(zip(m.surplus, m.shortage)):
        ax.text(i, s + lim * 0.02, f"{s / 1e6:.1f}", ha="center", va="bottom", fontsize=6.3)
        ax.text(i, -h - lim * 0.02, f"{h / 1e6:.1f}", ha="center", va="top", fontsize=6.3)
    ax.yaxis.set_major_formatter(lambda v, _: f"{abs(v) / 1e6:,.0f}")
    ax.set_ylabel("₱ millions (selling price, VAT-incl.)\n↑ surplus   ↓ shortage")
    ax.set_xticks(x, [mlabel(p) for p in m.index])
    ax.set_xlabel("Month")
    ax.legend(loc="upper left", ncol=1)
    ygrid(ax)
    save(plt, fig, f)
    return f


def fig_k(plt, d) -> Fig:
    f = Fig("k", "fig_k_mase_distribution.png", "MASE Distribution of the 175 Forecast Products, Unilever Tier A "
            "(as of 2026-02)", "Forecast_Result for March 2026, status ok (frozen in docs/published_snapshot_2026-10-24/"
            "mase_rows.csv; pinned figure 'MASE < 1 for 109 of 175')", "forecast month March 2026 (served model's "
            "rolling one-step holdout, DEC-25)",
            "the 9 insufficient-data and 5 dead Tier A products (no MASE); which model served each product; the size "
            "of each product's sales")
    mm = d["mase"]
    ok = mm[(mm.status == "ok") & mm.mase.notna()].mase.astype(float)
    passed, failed = int((ok < 1).sum()), int((ok >= 1).sum())
    f.check("products with a MASE", len(ok), 175, basis="Table 4.2.15 / pinned")
    f.check("MASE below 1", passed, 109, basis="Table 4.2.15 / pinned")
    f.check("median MASE", round(float(ok.median()), 3), 0.827, tol=0.0005, basis="§4.2.2.1.3 / pinned")
    cap = 3.0
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    edges = np.arange(0, cap + 0.1001, 0.1)
    vals = ok.clip(upper=cap + 0.05)
    counts, _ = np.histogram(vals, bins=np.append(edges, cap + 0.1))
    for i, c in enumerate(counts):
        lo = edges[i] if i < len(edges) else cap
        below = lo < 1.0 - 1e-9
        ax.bar(lo + 0.05, c, 0.1, color=DARK if below else LIGHT, hatch=None if below else "////",
               edgecolor="white" if below else INK, linewidth=0.4)
    over = int((ok > cap).sum())
    top = counts.max() * 1.35
    ax.set_ylim(0, top)
    from matplotlib.ticker import MaxNLocator
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.axvline(1.0, color=INK, linewidth=1.0, linestyle="--")
    ax.text(0.97, top * 0.98, f"Pass: MASE < 1\n{passed} of {len(ok)} products", ha="right", va="top", fontsize=7)
    ax.text(1.03, top * 0.98, f"Fail: MASE ≥ 1\n{failed} of {len(ok)} products", ha="left", va="top", fontsize=7)
    med = float(ok.median())
    ax.plot([med, med], [0, top * 0.8], color=INK, linewidth=0.6, linestyle=":")
    ax.text(med, top * 0.8, f"median\n{med:.3f}", ha="center", va="bottom", fontsize=6.3)
    ax.set_xlim(0, cap + 0.15)
    ax.set_xticks(list(np.arange(0, cap + 0.01, 0.5)), [f"{t:.1f}" for t in np.arange(0, cap, 0.5)] + [f"≥ {cap:.1f}"])
    ax.set_xlabel(f"MASE (bins of 0.1; the last bin holds the {over} products above {cap:.1f}, max {ok.max():.2f})")
    ax.set_ylabel("Products")
    ygrid(ax)
    save(plt, fig, f)
    return f


BIN_TITLE = {"short": "Short history (3–11 sales months)", "medium": "Medium (12–23)", "long": "Long (24+)"}
SERVED = {"medium": "tsb", "long": "ens_xgb_ma3@A"}


def fig_l(plt, d) -> Fig:
    f = Fig("l", "fig_l_block_results.png", "Half-Year Block Results of 36 Challengers against MA3, by History Bin",
            "reports/experiment_artifacts/cells_all.csv (scripts/candidate_followup_2026-09-22/cells_all.py: rolling "
            "one step ahead, per-product WAPE, bootstrap 95% interval over 1,000 resamples, two-condition rule)",
            "five half-year blocks, October 2023 – February 2026",
            "the size of any win or loss; blocks where a bin had fewer than 5 products to compare (not testable, "
            "drawn as outlined); the 17-model bake-off (a separate test); MA3 itself (the baseline every bar is "
            "measured against)")
    c = d["cells"]
    f.check("candidates per bin", int(c.groupby("bin").model.nunique().min()), 36, basis="edit list item 5")
    tsb = c[(c.bin == "medium") & (c.model == "tsb")].iloc[0]
    def wtl(r):  # r["T"], never r.T: on a pandas Series .T is the transpose
        return f"{r['W']}/{r['T']}/{r['L']}"

    f.check("TSB (medium) W/T/L, testable", f"{wtl(tsb)}, {tsb['testable']}", "0/4/0, 4",
            basis="§4.2.2.1.2: 'TSB tied in all 4 blocks where it could be tested'")
    xg = c[(c.bin == "long") & (c.model == "ens_xgb_ma3@A")].iloc[0]
    f.check("XGBoost + MA3 average (long, @A) W/T/L", wtl(xg), "0/4/1",
            basis="§4.2.2.1.2 and Table 4.2.16: '0 wins, 4 ties, 1 loss' (DEC-26, 2026-09-21)")
    order = sorted(c.model.unique(), key=lambda m: (m.split("@")[0], m))
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 7.6), sharey=True)
    y = np.arange(len(order))[::-1]
    for ax, b in zip(axes, ["short", "medium", "long"]):
        s = c[c.bin == b].set_index("model").reindex(order)
        nt = 5 - s.testable
        left = np.zeros(len(order))
        for col, colr, hat, lab in (("W", DARK, None, "Win"), ("T", MID, None, "Tie"),
                                    ("L", INK, "xxxx", "Loss"), ("NT", "white", None, "Not testable")):
            v = (nt if col == "NT" else s[col]).to_numpy(dtype=float)
            ax.barh(y, v, left=left, height=0.72, color=colr, hatch=hat,
                    edgecolor=RULE if col == "NT" else "white", linewidth=0.5, label=lab)
            left += v
        if b in SERVED:  # the served model's row outlined, and named in the panel title
            yi = y[order.index(SERVED[b])]
            from matplotlib.patches import Rectangle
            ax.add_patch(Rectangle((0, yi - 0.5), 5, 1.0, fill=False, edgecolor=INK, linewidth=1.4, zorder=4,
                                   clip_on=False))
        title = BIN_TITLE[b] + (f"\nserved: {SERVED[b]} (outlined)" if b in SERVED else "\nserved: MA3 itself")
        ax.set_title(title, fontsize=7)
        ax.set_xlim(0, 5)
        ax.set_xticks(range(6))
        ax.set_xlabel("Half-year blocks")
    axes[0].set_yticks(y, order, fontsize=6)
    for lab in axes[0].get_yticklabels():
        if lab.get_text() in SERVED.values():
            lab.set_fontweight("bold")
    axes[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=4)
    fig.subplots_adjust(wspace=0.12, left=0.2)
    save(plt, fig, f)
    return f


# --------------------------------------------------------------------------------------------------------------
# Prescriptive
# --------------------------------------------------------------------------------------------------------------
# The plan the manuscript's Tables 4.2.19 / 4.2.20 print: lp_run 9, cycle 2026-03 (scripts/apply_final_bundle.py: safety
# stock follows the level for zero-forecast products too). Measured 2026-11-11 on the rehearsal copy (a restore of live's
# backup of that day plus the bundle) with this file's own plan_items, urgency_table and category_plan; the bundle checks live
# equals it row for row. Were lp_run 8's (110 / 69 / 381,484 / 462,133 / 1,184,313: Critical 16 / 16 / 65,388 / 24,747.12,
# Planned 88, Cooking Aids 20 / 15 / 37,926) and before that lp_run 6's (109 / 73 / 435,988 / 557,612 / 1,217,634).
# PLAN_TOTALS[0] and [2] must equal STATE.md's plan line (tests/test_plan_pins_follow_state.py).
TIER_B_URGENCY = {"CRITICAL": (14, 14, 62604, 21973.18, 31801.07), "URGENT": (6, 6, 67300, 18652.56, 63011.03),
                  "PLANNED": (90, 47, 248796, 418733.73, 1089501.29)}
TIER_B_CATEGORY = {"HAIR CARE": (29, 19, 138516), "FABRIC CLEANING": (25, 12, 86122), "DEODORANTS & FRAGRANCES": (13, 11, 58248),
                   "FABRIC ENHANCERS": (8, 7, 50040), "COOKING AIDS": (20, 13, 35142),
                   "CONDIMENTS": (7, 3, 9288), "ORAL CARE": (4, 1, 912), "SKIN CLEANSING": (4, 1, 432)}
PLAN_TOTALS = (110, 67, 378700, 459359, 1184313)


def _state_plan() -> tuple[int, int]:
    """(rows, pieces) from STATE.md's plan line, which tests/invariants/test_a_plan_agreement.py holds equal to live."""
    line = next(ln for ln in (REPO / "STATE.md").read_text(encoding="utf-8").splitlines() if ln.startswith("plan:"))
    got = dict(re.findall(r"(\w+)=(\S+)", line))
    return int(got["rows"]), int(got["pieces"])


def _state_lp_run() -> int:
    """The plan's lp_run from STATE.md's plan line. The figure sources and the table text named a literal lp_run 6 and
    109 items until 2026-11-11, two re-plans after both stopped being true."""
    line = next(ln for ln in (REPO / "STATE.md").read_text(encoding="utf-8").splitlines() if ln.startswith("plan:"))
    return int(dict(re.findall(r"(\w+)=(\S+)", line))["lp_run"])


def plan_items(d) -> pd.DataFrame:
    rec = d["api"]["recommendations"]
    it = pd.DataFrame(rec["items"])
    it = it[~it.outside_plan.fillna(False).astype(bool)]
    it = it.merge(d["sku_category"], on="sku_id", how="left")
    for col in ("plan_q_i", "ss_i", "forecast_units", "rop_i"):
        it[col] = it[col].astype(float)
    return it


def urgency_table(it) -> pd.DataFrame:
    g = it.groupby(it.urgency.str.upper()).agg(products=("sku_id", "count"), ordering=("plan_q_i", lambda s: int((s > 0).sum())),
                                               order=("plan_q_i", "sum"), ss=("ss_i", "sum"), forecast=("forecast_units", "sum"))
    return g.reindex(["CRITICAL", "URGENT", "PLANNED"])


def category_plan(it) -> pd.DataFrame:
    g = it.groupby("category_path").agg(products=("sku_id", "count"), ordering=("plan_q_i", lambda s: int((s > 0).sum())),
                                        order=("plan_q_i", "sum"))
    return g.sort_values("order", ascending=False)


def check_plan(f: Fig, it):
    u = urgency_table(it)
    f.check("plan rows", len(it), PLAN_TOTALS[0], basis="plan invariant / STATE.md")
    f.check("rows ordering > 0", int((it.plan_q_i > 0).sum()), PLAN_TOTALS[1], basis="plan invariant")
    f.check("order pieces", round(it.plan_q_i.sum()), PLAN_TOTALS[2], basis="plan invariant")
    f.check("safety stock (pieces)", round(it.ss_i.sum()), PLAN_TOTALS[3], basis="edit list item 9")
    f.check("forecast (pieces)", round(it.forecast_units.sum()), PLAN_TOTALS[4], basis="edit list item 9")
    for k, (n, o, q, ss, fc) in TIER_B_URGENCY.items():
        f.check(f"{k} products", int(u.loc[k, "products"]), n, basis="Tier B, B-a")
        f.check(f"{k} ordering", int(u.loc[k, "ordering"]), o, basis="Tier B, B-a")
        f.check(f"{k} order pieces", round(u.loc[k, "order"]), q, basis="Tier B, B-a")
        f.check(f"{k} safety stock", round(u.loc[k, "ss"], 2), ss, tol=0.005, basis="Tier B, B-a")
        f.check(f"{k} forecast", round(u.loc[k, "forecast"], 2), fc, tol=0.005, basis="Tier B, B-a")
    return u


def fig_m(plt, d) -> Fig:
    f = Fig("m", "fig_m_plan_by_urgency.png", "Order Plan by Urgency, Unilever (cycle March 2026)",
            f"GET /recommendations (lp_recommendation, lp_run {_state_lp_run()}; rows outside the plan excluded)",
            "planning cycle March 2026 (stock count 2 March 2026; Tier A as of 2026-02)",
            "safety stock and forecast per urgency (Table 4.2.19); peso value of the orders; whether SSM placed them "
            "(no decision is recorded in this cycle); cost inputs are set from SSM's records and not confirmed by SSM",
            chart_note="Two panels instead of one grouped bar: product counts (tens) and order pieces (hundreds of "
                       "thousands) on one axis would flatten the counts to nothing.")
    it = plan_items(d)
    u = check_plan(f, it)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.5, 3.5), gridspec_kw={"width_ratios": [1.1, 1]})
    x = np.arange(3)
    names = ["Critical", "Urgent", "Planned"]
    w = 0.36
    b1 = a1.bar(x - w / 2, u.products, w, color=MID, edgecolor=DARK, linewidth=0.5, label="Products in plan")
    b2 = a1.bar(x + w / 2, u.ordering, w, color=DARK, label="Ordering more than 0")
    for bars in (b1, b2):
        for bar in bars:
            a1.text(bar.get_x() + w / 2, bar.get_height() + 1, f"{int(bar.get_height())}", ha="center", fontsize=6.8)
    a1.set_xticks(x, names)
    a1.set_ylabel("Products")
    a1.set_title("Products", fontsize=8)
    a1.legend(loc="upper left")
    ygrid(a1)
    bars = a2.bar(x, u.order, 0.55, color=LIGHT, hatch="////", edgecolor=INK, linewidth=0.4)
    for bar in bars:
        a2.text(bar.get_x() + 0.275, bar.get_height() * 1.01, f"{bar.get_height():,.0f}", ha="center", fontsize=6.8)
    a2.set_xticks(x, names)
    a2.yaxis.set_major_formatter(lambda v, _: f"{v / 1e3:,.0f}")
    a2.set_ylabel("Order (thousand pieces, whole case packs)")
    a2.set_title(f"Order pieces (total {u.order.sum():,.0f})", fontsize=8)
    ygrid(a2)
    fig.subplots_adjust(wspace=0.35)
    save(plt, fig, f)
    return f


def fig_n(plt, d) -> Fig:
    f = Fig("n", "fig_n_plan_by_category.png", "Order Plan by Category, Unilever (cycle March 2026)",
            f"GET /recommendations (lp_run {_state_lp_run()}) joined to product_dimension.category_path on sku_code",
            "planning cycle March 2026", "categories with no planned product (Skin Care and the other 9 Unilever "
            "categories have none this cycle); peso value of the orders; products with a zero order (in the labels only)")
    it = plan_items(d)
    cp = category_plan(it)
    f.check("categories", len(cp), 8, basis="edit list item 10")
    for k, (n, o, q) in TIER_B_CATEGORY.items():
        f.check(f"{k} products / ordering / pieces", (int(cp.loc[k, "products"]), int(cp.loc[k, "ordering"]),
                                                       round(cp.loc[k, "order"])), (n, o, q), basis="Tier B, B-b")
    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    y = np.arange(len(cp))[::-1]
    ax.barh(y, cp.order, 0.64, color=MID, edgecolor=DARK, linewidth=0.5)
    for yi, (cat, r) in zip(y, cp.iterrows()):
        ax.text(r.order + cp.order.max() * 0.01, yi,
                f"{r.order:,.0f} pcs · {int(r.ordering)} of {int(r.products)} ordering",
                va="center", fontsize=6.8)
    ax.set_yticks(y, [cat_name(c) for c in cp.index])
    ax.set_xlim(0, cp.order.max() * 1.42)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v / 1e3:,.0f}")
    ax.set_xlabel("Order (thousand pieces, whole case packs)")
    ygrid(ax, "x")
    save(plt, fig, f, axis_room=0.55, left=0.27)
    return f


def fig_o_values(pesos: dict) -> dict:
    """fig_o's bars, every one from the one row of GET /policy-comparison it draws. The other reading is for the source note only."""
    row, other = pesos["readings"]["rule_read_as_peak"], pesos["readings"]["rule_read_as_average"]
    return {"row": row["label"],
            "plan": [row["average"]["lp_stock_pesos"], row["peak"]["lp_stock_pesos"]],
            "rule": [row["average"]["rule_stock_pesos"], row["peak"]["rule_stock_pesos"]],
            "pct": [row["average"]["pct_vs_rule"], row["peak"]["pct_vs_rule"]],
            "other_label": other["label"], "other_pct": [other["average"]["pct_vs_rule"], other["peak"]["pct_vs_rule"]]}


def fig_o(plt, d) -> Fig:
    pol = d["api"]["policy"]
    v = fig_o_values(pol["pesos"])
    f = Fig("o", "fig_o_plan_vs_rule.png", f"Per-Product Plan against the 3-Week Rule ({_state_plan()[0]} products, cycle March 2026)",
            "GET /policy-comparison (portfolio and pesos blocks; lp_recommendation ss_i, rop_i, forecast; prices are "
            "the last purchase price per piece from the stock file)", "planning cycle March 2026",
            "the safety-stock comparison (the rule has no separate safety stock, so it is not comparable: edit list "
            "item 13); capital freed (none is claimed). The peso panel's bars are one row of GET /policy-comparison, "
            f"the {v['row']}: 3 weeks is the stock right after a delivery, and its average is half a weekly order lower. "
            f"On the other reading, the {v['other_label']}, the plan's average is {v['other_pct'][0]:+.1f}% and its peak "
            f"{v['other_pct'][1]:+.1f}%. Weekly ordering is assumed, not implemented; SSM has not confirmed the prices, "
            "its weekly ordering or which reading applies",
            chart_note="Two panels: target stock is in pieces and average and peak stock are in pesos.")
    pf, pe = pol["portfolio"], pol["pesos"]
    as_average, as_peak = pe["readings"]["rule_read_as_average"], pe["readings"]["rule_read_as_peak"]
    f.check("target stock, plan (pieces)", round(pf["lp_target_stock_units"]), 1005661, basis="Table 4.2.22")
    f.check("target stock, rule (pieces)", round(pf["rule_stock_units"]), 840092, basis="Table 4.2.22")
    f.check("target vs rule (%)", round(100 * (pf["lp_target_stock_units"] / pf["rule_stock_units"] - 1), 1), 19.7,
            basis="Table 4.2.22")
    f.check("average stock, plan (PHP)", round(as_peak["average"]["lp_stock_pesos"]), 7496532, basis="rule_read_as_peak")
    f.check("average stock, rule (PHP)", round(as_peak["average"]["rule_stock_pesos"]), 8066830, basis="rule_read_as_peak")
    f.check("average vs rule (%)", as_peak["average"]["pct_vs_rule"], -7.1, basis="rule_read_as_peak")
    f.check("peak stock, plan (PHP)", round(as_peak["peak"]["lp_stock_pesos"]), 11045937, basis="rule_read_as_peak")
    f.check("peak stock, rule (PHP)", round(as_peak["peak"]["rule_stock_pesos"]), 9680196, basis="rule_read_as_peak")
    f.check("peak vs rule (%)", as_peak["peak"]["pct_vs_rule"], 14.1, basis="rule_read_as_peak")
    f.check("the other reading's average vs rule (%), source note only", as_average["average"]["pct_vs_rule"], -22.6, basis="rule_read_as_average")
    f.check("the other reading's peak vs rule (%), source note only", as_average["peak"]["pct_vs_rule"], -2.2, basis="rule_read_as_average")
    f.check("products holding less than the rule", pf["skus_lp_holds_less"], 56, basis="Table 4.2.22")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.5, 3.7), gridspec_kw={"width_ratios": [0.7, 1.3]})
    w = 0.36
    a1.bar([-w / 2], [pf["lp_target_stock_units"]], w, color=DARK, label="DSD plan")
    a1.bar([w / 2], [pf["rule_stock_units"]], w, color=LIGHT, hatch="////", edgecolor=INK, linewidth=0.4,
           label="3-week rule")
    a1.text(-w / 2, pf["lp_target_stock_units"] * 1.01, f"{pf['lp_target_stock_units']:,.0f}\n(+19.7%)", ha="center",
            fontsize=6.5)
    a1.text(w / 2, pf["rule_stock_units"] * 1.01, f"{pf['rule_stock_units']:,.0f}", ha="center", fontsize=6.5)
    a1.set_xticks([0], ["Target stock"])
    a1.set_xlim(-0.6, 0.6)
    a1.set_ylim(0, pf["lp_target_stock_units"] * 1.2)
    a1.yaxis.set_major_formatter(lambda v, _: f"{v / 1e3:,.0f}")
    a1.set_ylabel("Thousand pieces")
    a1.set_title("Pieces", fontsize=8)
    ygrid(a1)
    x = np.arange(2)
    plan, rule = v["plan"], v["rule"]
    a2.bar(x - w / 2, plan, w, color=DARK, label="DSD plan")
    a2.bar(x + w / 2, rule, w, color=LIGHT, hatch="////", edgecolor=INK, linewidth=0.4,
           label="3-week rule, read as a peak")
    for i, (p, r, pct) in enumerate(zip(plan, rule, v["pct"])):
        a2.text(i - w / 2, p * 1.01, f"₱{p / 1e6:.2f} M\n({pct:+.1f}%)", ha="center", fontsize=6.5)
        a2.text(i + w / 2, r * 1.01, f"₱{r / 1e6:.2f} M", ha="center", fontsize=6.5)
    a2.set_xticks(x, ["Average stock", "Peak stock (after delivery)"])
    a2.set_ylim(0, max(plan + rule) * 1.22)
    a2.yaxis.set_major_formatter(millions)
    a2.set_ylabel("₱ millions (last purchase price)")
    a2.set_title("Pesos, rule read as a peak", fontsize=8)
    h, lab = a2.get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", bbox_to_anchor=(0.5, 0.21), ncol=2, fontsize=6.5)
    ygrid(a2)
    fig.subplots_adjust(wspace=0.4)
    save(plt, fig, f, axis_room=0.9)
    return f


DEC_SOURCE = ("docs/published_snapshot_2026-10-24/error_decomposition_row.csv (frozen mart.error_decomposition_row, "
              "Tier A, calendar-adjusted as-served backtest; pinned by docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json)")


def tier_a_dec(d) -> pd.DataFrame:
    return d["dec"][d["dec"].tier == "A"]


def dec_period(a: pd.DataFrame) -> str:
    """The months the frozen rows actually score (docs/ACCURACY_AS_SERVED.md names a window from 2023-10, but the
    first scored month in these rows is 2024-01)."""
    lo, hi = (pd.Period(a.month.min(), freq="M"), pd.Period(a.month.max(), freq="M"))
    return f"{lo.strftime('%B %Y')} – {hi.strftime('%B %Y')} ({a.month.nunique()} scored months)"


def fig_p(plt, d) -> Fig:
    pin = d["pinned"]
    f = Fig("p", "fig_p_error_decomposition.png", "Forecast Error Decomposition by Month, Unilever Tier A (pieces)",
            DEC_SOURCE, dec_period(tier_a_dec(d)) + ", 4,370 Tier A product-months",
            "Tier B and C products (Tier A only); pesos (the split is in pieces; the pesos beyond safety stock, "
            "₱38,187,551, are a separate figure); observed stockouts (a miss beyond safety stock is potential "
            "exposure, not a recorded stockout); live performance (a backtest)")
    a = tier_a_dec(d)
    pinned_a = {k.rsplit(".", 1)[1]: v for k, v in _flatten(pin) if ".error_decomposition.A." in f".{k}"}
    f.check("product-months", len(a), 4370, basis="pinned")
    for col in ("over_pieces", "absorbed_pieces", "beyond_pieces"):
        f.check(f"{col} total", round(a[col].fillna(0).sum()), round(pinned_a.get(col, -1)), basis="pinned JSON")
    f.check("over / absorbed / beyond as published", tuple(round(a[c].fillna(0).sum()) for c in
                                                           ("over_pieces", "absorbed_pieces", "beyond_pieces")),
            (12242746, 4847983, 2669295), basis="docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.md")
    f.check("months beyond safety stock", int(a.exceeds_safety_stock.fillna(False).astype(bool).sum()), 749,
            basis="STATE.md headline")
    f.check("pesos beyond safety stock", round(a.beyond_pesos.fillna(0).sum()), 38187551, basis="pinned")
    m = a.groupby("month")[["over_pieces", "absorbed_pieces", "beyond_pieces"]].sum()
    fig, ax = plt.subplots(figsize=(6.5, 3.9))
    x = np.arange(len(m))
    tot = {c: a[c].fillna(0).sum() for c in m.columns}
    looks = (("over_pieces", LIGHT, "////", "Over-buying (forecast above actual)"),
             ("absorbed_pieces", MID, None, "Under-forecast absorbed by safety stock"),
             ("beyond_pieces", DARK, None, "Under-forecast beyond safety stock"))
    bottom = np.zeros(len(m))
    for col, colr, hat, lab in looks:
        ax.bar(x, m[col], 0.75, bottom=bottom, color=colr, hatch=hat, edgecolor=INK if hat else "white", linewidth=0.4,
               label=f"{lab}: {tot[col]:,.0f} pcs")
        bottom += m[col].to_numpy()
    ax.yaxis.set_major_formatter(lambda v, _: f"{v / 1e3:,.0f}")
    ax.set_ylabel("Forecast error (thousand pieces)")
    ax.set_xticks(x[::3], [mlabel(p) for p in m.index[::3]])
    ax.set_xlabel("Month (Tier A at the time of each forecast)")
    ax.legend(loc="upper left", fontsize=6.8)
    ax.set_ylim(0, bottom.max() * 1.32)
    ygrid(ax)
    save(plt, fig, f)
    return f


def fig_q(plt, d) -> Fig:
    f = Fig("q", "fig_q_exposure_concentration.png", "Concentration of Exposure beyond Safety Stock, Unilever Tier A",
            DEC_SOURCE, dec_period(tier_a_dec(d)), "Tier B and C products; products with no miss beyond safety "
            "stock (not ranked); observed stockouts (exposure is potential, not recorded); pieces")
    a = tier_a_dec(d)
    p = a.groupby("product_key").beyond_pesos.sum()
    p = p[p > 0].sort_values(ascending=False)
    f.check("pesos beyond safety stock", round(p.sum()), 38187551, basis="pinned")
    cum = p.cumsum() / p.sum()
    n50, n80 = int((cum < 0.5).sum() + 1), int((cum < 0.8).sum() + 1)
    rank = np.arange(1, len(p) + 1)
    fig, ax = plt.subplots(figsize=(6.5, 3.7))
    ax.bar(rank, p.to_numpy(), width=1.0, color=MID, linewidth=0)
    ax.yaxis.set_major_formatter(millions)
    ax.set_ylabel("Pesos beyond safety stock per product\n(₱ millions, average selling price)")
    ax.set_xlabel(f"Tier A products ranked by pesos beyond safety stock ({len(p)} with any exposure)")
    ax.set_xlim(0, len(p) + 1)
    ax2 = ax.twinx()
    ax2.spines["right"].set_visible(True)
    ax2.plot(rank, 100 * cum.to_numpy(), color=INK, linewidth=1.3)
    ax2.set_ylim(0, 102)
    ax2.set_ylabel("Cumulative share of the ₱38.2 M (%)")
    for n, lvl in ((n50, 50), (n80, 80)):
        ax2.plot([0, n, n], [lvl, lvl, 0], color=INK, linewidth=0.7, linestyle="--")
        ax2.text(n + len(p) * 0.015, lvl - 6, f"{lvl}% reached by {n} products ({100 * n / len(p):.0f}%)",
                 fontsize=6.8)
    f.chart_note = (f"{n50} products carry half and {n80} carry 80% of the ₱{p.sum():,.0f} beyond safety stock "
                    f"({len(p)} products have any).")
    save(plt, fig, f)
    return f


def _flatten(dct, prefix=""):
    for k, v in dct.items():
        if isinstance(v, dict):
            yield from _flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


# --------------------------------------------------------------------------------------------------------------
# Numbering map (Chapter 4; Chapter 5 has no figures). In order of appearance; None = an existing screenshot.
# --------------------------------------------------------------------------------------------------------------
SEQUENCE = [
    ("old", "4.2.1", "Key Performance Indicators, Unilever (Dashboard)"),
    ("old", "4.2.2", "Monthly Sales versus Stock on Hand, Unilever (Dashboard)"),
    ("new", "a", "§4.2.1.1.2, after Table 4.2.2, before the paragraph beginning \"Monthly sales ranged from a low…\""),
    ("old", "4.2.3", "Year-over-Year Monthly Sales, Unilever (Dashboard)"),
    ("new", "b", "§4.2.1.1.2, after Table 4.2.3, before the paragraph beginning \"Sales grew by less than 2% a year…\""),
    ("old", "4.2.4", "Sales by Category, Unilever (Category Trends page)"),
    ("new", "c", "§4.2.1.1.3, after Table 4.2.4 and its Note, before \"Four categories, Cooking Aids (24.8%)…\""),
    ("old", "4.2.5", "ABC Classification and Pareto Curve, Unilever (ABC Classification page)"),
    ("new", "d", "§4.2.1.1.4, after Table 4.2.5, before \"As of February 2026, 1,091 Unilever products were ranked…\""),
    ("old", "4.2.6", "Products Entering and Leaving Class A, Unilever (Dashboard)"),
    ("old", "4.2.7", "FSN Classification, Unilever (ABC Classification page)"),
    ("new", "e", "§4.2.1.1.6, after Table 4.2.7, before \"Of 1,091 products, 619 (56.7%) were Fast-moving…\""),
    ("old", "4.2.8", "Demand Pattern Panel of a Tier A Product (SKU Forecast page)"),
    ("old", "4.2.9", "Idle Stock and Stock Above Policy, Unilever (Dashboard)"),
    ("old", "4.2.10", "Key Performance Indicators, Del Monte (Dashboard)"),
    ("new", "f", "§4.2.1.2.1, after Table 4.2.10, before \"Real Del Monte sales total ₱156.7 million…\""),
    ("old", "4.2.11", "Category Sales, Del Monte (Category Trends page)"),
    ("old", "4.2.12", "Del Monte Data Gaps as Labelled on the Dashboard"),
    ("new", "g", "§4.2.2.1.1, after Table 4.2.13, before \"No model reached a median MAPE below 20%…\""),
    ("old", "4.2.13", "Portfolio Forecast for March 2026, Unilever (Dashboard)"),
    ("old", "4.2.14", "One-Month-Ahead Forecast of a Tier A Product (SKU Forecast page)"),
    ("new", "k", "§4.2.2.1.3, after the paragraph beginning \"All 189 Tier A products as of February 2026 were "
                 "processed…\" (it follows Table 4.2.15), before \"The pass rate differs by model…\""),
    ("old", "4.2.15", "Del Monte Category Forecast, Labelled as Synthetic (SKU Forecast page, synthetic data on)"),
    ("new", "l", "§4.2.2.3.2, after Table 4.2.16, before \"In every comparison, the simple MA3 was as good…\""),
    ("old", "4.2.16", "Forecast Accuracy Card, Unilever, March 2025 – February 2026 (Dashboard)"),
    ("new", "h", "§4.2.2.3.3, after Table 4.2.18, before \"The dashboard card shows the same backtest…\""),
    ("new", "i", "§4.2.2.3.3, directly after the forecast-against-actual figure"),
    ("new", "j", "§4.2.2.3.3, directly after the monthly WAPE figure"),
    ("new", "p", "§4.2.3.1.1, after the paragraph beginning \"The monthly standard deviation of demand is scaled "
                 "down…\" (end of the section); needs a new sentence, see the cross-reference table"),
    ("new", "q", "§4.2.3.1.1, directly after the error-decomposition figure"),
    ("old", "4.2.17", "Order Plan for March 2026, Unilever (Reorder Recommendations page)"),
    ("new", "m", "§4.2.3.1.2, after Table 4.2.19, before \"Of the 110 rows in the cycle…\" (that paragraph is itself "
                 "rewritten by edit list item 9)"),
    ("new", "n", "§4.2.3.1.3, after Table 4.2.20, before Table 4.2.21"),
    ("new", "o", "§4.2.3.1.4, after Table 4.2.22, before \"For the 109 planned products, the per-product target stock…\""),
    ("old", "4.2.18", "Dismissing a Recommendation with a Reason (Reorder Recommendations page)"),
]


def numbering(figs: dict[str, Fig]):
    """(new number, old number or letter, title, placement) in order of appearance."""
    out = []
    for i, (kind, ref, text) in enumerate(SEQUENCE, start=1):
        new = f"4.2.{i}"
        if kind == "old":
            out.append((new, ref, text, None))
        else:
            out.append((new, ref, figs[ref].title, text))
    return out


def write_manifest(figs: dict[str, Fig]):
    nm = numbering(figs)
    lines = [
        "# Chapter 4 figures: programme output, numbering map and gate (generated)",
        "",
        "Generated by `python -m scripts.manuscript_figures`; do not edit by hand. Every figure is re-runnable from that "
        "script; each caption names its source, its period and what it does not show.",
        "",
        "## Numbering scheme",
        "",
        "Figures keep the chapter's section-level scheme (Figure 4.2.N within §4.2, Figure 4.3.N within §4.3) and are "
        "numbered in order of appearance, so each new figure is inserted where it belongs and the screenshots after it "
        "shift. Appending the new figures as 4.2.19 onward would number them out of order of appearance. Tables keep "
        "their numbers. §4.3 gains no figure, so Figures 4.3.1–4.3.13 are unchanged; Chapter 5 has no figures.",
        "",
        "## Map, Chapter 4 §4.2 (old → new)",
        "",
        "| New | Old | Figure | Placement (new figures only) | Gate |",
        "|---|---|---|---|---|",
    ]
    for new, ref, title, place in nm:
        if place is None:
            lines.append(f"| Figure {new} | Figure {ref} | {title} (screenshot) | unchanged position | n/a |")
        else:
            gate = "**HELD**" if figs[ref].held else "pass"
            lines.append(f"| Figure {new} | new ({ref}) | {title} | {place} | {gate} |")
    lines += ["", "Figures 4.3.1 – 4.3.13: unchanged (old = new). Chapter 5: no figures, before or after.", "",
              "## Cross-references that change", "",
              "No paragraph of Chapter 4 or 5 cites a Figure 4.2.x by number (searched the full text of "
              "`4ISA_GROUP7_Ch4-5_Rebuilt_2026-10-30.docx`); the one numbered citation, \"Figure 4.3.3 shows the use "
              "cases\" (§4.3.1.4), does not move. What changes is each screenshot's caption and the List of Figures:",
              "", "| Location | Current wording | New wording |", "|---|---|---|"]
    for new, ref, title, place in nm:
        if place is None and ref != new:
            lines.append(f"| Caption and List of Figures | Figure {ref} {title} | Figure {new} {title} |")
    lines += ["| Caption and List of Figures | Figure 4.2.1, 4.2.2 | unchanged |"]
    adds = {"a": "\"(Figure {n})\" after \"…stayed between ₱28 million and ₱37 million in most months\"",
            "b": "\"(Table 4.2.3, Figure {n})\" in place of \"(Table 4.2.3)\" at the end of \"Annual sales were steady…\"",
            "c": "\"(Figure {n})\" after \"…earn 83.6% of Unilever sales\"",
            "d": "\"(Figure {n})\" after \"…inside the 75% to 85% band\"",
            "e": "\"(Figure {n})\" after \"…121 (11.1%) Non-moving\"",
            "f": "\"(Figure {n})\" after \"…over 17 collected months\"",
            "g": "\"(Figure {n})\" after \"…Holt-Winters had the best median but ran on only 62 products because it "
                 "needs 24 months\"",
            "k": "\"(Figure {n})\" after \"…109 passed the quality gate (MASE below 1), with a median MASE of 0.827\"",
            "l": "\"(Figure {n})\" after \"…the blocks\" in §4.2.2.3.2's \"For each history segment…\" sentence — HELD, "
                 "see the gate",
            "h": "\"(Figures {n}, {n1} and {n2})\" after \"The monthly table shows when the error was largest\"",
            "p": "new sentence at the end of §4.2.3.1.1: \"Figure {n} splits the backtest's forecast error for Tier A "
                 "into over-buying (12,242,746 pieces), under-forecast absorbed by safety stock (4,847,983) and "
                 "under-forecast beyond it (2,669,295); demand exceeded the forecast by more than the safety stock in "
                 "749 of 4,370 product-months (17.14%), worth ₱38,187,551 at average selling price, and Figure {nq} "
                 "shows how few products carry most of it.\"",
            "m": "\"(Figure {n})\" after the first sentence of the rewritten urgency paragraph",
            "n": "\"(Table 4.2.20, Figure {n})\" in place of the first mention of the category orders",
            "o": "\"(Figure {n})\" after \"…or 3.59 weeks of sales\""}
    num = {ref: new for new, ref, _, place in nm if place is not None}
    lines += ["", "**Citations to add for the new figures** (none exists yet; wording is a suggestion):", "",
              "| Figure | Add |", "|---|---|"]
    for ref, text in adds.items():
        lines.append(f"| Figure {num[ref]} | " + text.format(n=num[ref], n1=num.get("i"), n2=num.get("j"),
                                                                 nq=num.get("q")) + " |")
    lines += ["", "## Captions and gate results", ""]
    for new, ref, title, place in nm:
        if place is None:
            continue
        f = figs[ref]
        fails = [c for c in f.checks if not c[3]]
        lines += [f"### Figure {new} {f.title} ({'HELD' if f.held else 'gate: pass'})", "",
                  f"File: `reports/figures/{f.file}`", "",
                  f"Caption: Figure {new} {f.title}. Source: {f.source}. Period: {f.period}. "
                  f"Not shown: {f.not_shown}.", ""]
        if f.chart_note:
            lines += [f"Chart note: {f.chart_note}", ""]
        lines.append(f"Gate: {len(f.checks) - len(fails)} of {len(f.checks)} checks agree with the manuscript or "
                     "the edit list.")
        for label, got, exp, _, basis in fails:
            lines.append(f"- **Disagrees:** {label}: data gives `{got}`, {basis} states `{exp}`.")
        lines.append("")
    out = report_path(MANIFEST)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# --------------------------------------------------------------------------------------------------------------
# Regenerated table data
# --------------------------------------------------------------------------------------------------------------
def fmt_pct(v: float) -> str:
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.1f}%"


def peso(v: float) -> str:
    return f"{'−' if v < 0 else ''}₱{abs(v):,.0f}"


def write_tables(d) -> tuple[Path, list[str]]:
    it = plan_items(d)
    u = urgency_table(it)
    totals = (len(it), int((it.plan_q_i > 0).sum()), round(it.plan_q_i.sum()), round(it.ss_i.sum()),
              round(it.forecast_units.sum()))
    problems = [] if totals == PLAN_TOTALS else [f"Table 4.2.19 totals {totals} != required {PLAN_TOTALS}"]
    rule = {"CRITICAL": "Stock below safety stock", "URGENT": "Stock below target stock",
            "PLANNED": "Stock at or above target"}
    rows19 = [f"| {k.title()} | {rule[k]} | {int(r.products)} | {int(r.ordering)} | {r.order:,.0f} | {r.ss:,.0f} | "
              f"{r.forecast:,.0f} |" for k, r in u.iterrows()]
    cp = category_plan(it)
    cats_total = (int(cp.products.sum()), int(cp.ordering.sum()), round(cp.order.sum()))
    if cats_total != PLAN_TOTALS[:3]:
        problems.append(f"Table 4.2.20 totals {cats_total} != {PLAN_TOTALS[:3]}")
    if "SKIN CARE" in cp.index:
        problems.append("Table 4.2.20 has a Skin Care row")
    rows20 = [f"| {cat_name(c)} | {int(r.products)} | {int(r.ordering)} | {r.order:,.0f} |" for c, r in cp.iterrows()]

    cats = category_table(d)
    y = pd.DataFrame(d["api"]["yoy"]["principals"][0]["rows"])
    y["category_path"] = y.category_path.fillna("UNCLASSIFIED")
    matched = y[(y.months > 0) & (y.prior_months > 0)].groupby("category_path")[["pesos", "prior_pesos"]].sum()
    allp = y.groupby("category_path")[["pesos", "prior_pesos"]].sum()
    nmatch = y[(y.months > 0) & (y.prior_months > 0)].groupby("category_path").size()
    expected_yoy = {"COOKING AIDS": 1.5, "HAIR CARE": -9.4, "FABRIC CLEANING": -10.6, "FABRIC ENHANCERS": -55.1,
                    "CONDIMENTS": 7.6, "DEODORANTS & FRAGRANCES": 4.2, "SKIN CARE": 11.6, "ORAL CARE": -19.6,
                    "SKIN CLEANSING": 12.1, "HOME & HYGIENE": -3.6, "OTHER FOODS": 25.8, "UNCLASSIFIED": -23.0,
                    "MINI MEALS": 339.6, "SCRATCH COOKING AIDS": -100.6, "DRESSINGS": -100.5}
    trend = {"growing": "Growing", "declining": "Declining", "flat": "Flat"}
    rows4, neg4, na4 = [], [], []
    for _, r in cats.iterrows():
        c = r.category
        if c in matched.index and matched.loc[c, "prior_pesos"] > 0:
            v = 100 * (matched.loc[c, "pesos"] / matched.loc[c, "prior_pesos"] - 1)
            if c in expected_yoy and round(v, 1) != expected_yoy[c]:
                problems.append(f"Table 4.2.4 {c}: matched YoY {v:.1f}% != edit list {expected_yoy[c]}%")
            cell = fmt_pct(v) if v > -100 else "−100% or worse²"
            if v <= -100:
                neg4.append(f"{cat_name(c)} {fmt_pct(v)} on {int(nmatch[c])} matched products "
                            f"({peso(matched.loc[c, 'pesos'])} against {peso(matched.loc[c, 'prior_pesos'])})")
        else:
            cell = "n/a³"
            now, before = (allp.loc[c, "pesos"], allp.loc[c, "prior_pesos"]) if c in allp.index else (0.0, 0.0)
            na4.append(f"{cat_name(c)}: no product sold in both years, so there is no matched change; on all products "
                       f"its net sales were {peso(now)} against {peso(before)} the year before")
        tr = trend.get(r.get("direction"), r.get("label") or "n/a")
        sales = f"{r.revenue:,.0f}"
        share = f"{100 * r.share:.1f}%"
        rows4.append(f"| {cat_name(c)} | {sales} | {share} | {cell} | {tr} |")
    if len(rows4) != 16:
        problems.append(f"Table 4.2.4 has {len(rows4)} rows, not 16")

    plan_meta = d["api"]["recommendations"]
    text = f"""# Manuscript table data, Chapter 4 (regenerated 2026-10-31, file dated to the rebuilt draft of 2026-10-30)

Generated by `python -m scripts.manuscript_figures` (read-only against the live database); do not edit by hand.
Replaces the three tables flagged "[REGENERATE — see consolidated edit list]" in
`4ISA_GROUP7_Ch4-5_Rebuilt_2026-10-30.docx`. Each table names its query. Every value was compared with
`docs/CH4-5_EDITS_2026-10-22_corrected.md` and its Tier B (`docs/CH4-5_EDITS_2026-10-22.md`):
{"no disagreement." if not problems else "**disagreements: " + "; ".join(problems) + "**"}

## Table 4.2.19 Order Plan by Urgency, Unilever (cycle March 2026)

| Urgency | Rule | Products | Ordering more than 0 | Order (pieces) | Safety stock (pieces) | Forecast (pieces) |
|---|---|---|---|---|---|---|
{chr(10).join(rows19)}
| **Total** | | **{totals[0]}** | **{totals[1]}** | **{totals[2]:,}** | **{totals[3]:,}** | **{totals[4]:,}** |

Note: Order quantities are whole case packs, so the order column adds up exactly. Safety stock and forecast are stored
to two decimals and shown rounded; each total is the rounded sum of the unrounded rows, so the displayed rows can
differ from it by 1 (forecast rows add to {sum(round(v) for v in u.forecast):,}).

Query: `GET /recommendations?principal=unilever` (cycle {plan_meta['planning_cycle_date']}, `lp_recommendation` of
`lp_run` {_state_lp_run()}, rows with `outside_plan` excluded), grouped by `urgency`; Products = rows, Ordering = rows with
`plan_q_i > 0`, Order = Σ `plan_q_i`, Safety stock = Σ `ss_i`, Forecast = Σ `forecast_units`. Stock count
{plan_meta['stock_count_date']}; Tier A as of {plan_meta['abc_period']} (`t12m_new`).

## Table 4.2.20 Order Plan by Category, Unilever (cycle March 2026)

| Category | Products in plan | Ordering more than 0 | Order (pieces) |
|---|---|---|---|
{chr(10).join(rows20)}
| **Total** | **{cats_total[0]}** | **{cats_total[1]}** | **{cats_total[2]:,}** |

Eight categories: Skin Care is not in the plan (its only row was the run-less accepted recommendation 4, which is
outside the plan).

Query: the same {totals[0]} items, joined to `product_dimension.category_path` on `sku_code` (Unilever, grain `sku`), grouped
by category, ordered by order pieces.

## Table 4.2.4 Sales by Category, Unilever (March 2025 – February 2026)

| Category | Sales (PHP) | Share | Year-over-year change (same products)¹ | Trend (24 months) |
|---|---|---|---|---|
{chr(10).join(rows4)}

¹ Matched products: only products with a sales row in both March 2025 – February 2026 and March 2024 – February 2025,
net pesos at selling price, VAT-inclusive.
² {'; '.join(neg4) or 'none'}. Returns exceeded sales in the later year, so the change is not a meaningful growth
rate.
³ {'; '.join(na4) or 'none'}.

Rows are in descending order of sales, so Dressings (₱2,323) now precedes Scratch Cooking Aids (₱167); the rebuilt
draft had them the other way round. The sixteenth row, Other Nutrition, sold nothing in the window and was missing
from the draft.

Query: Sales and Trend: `GET /category-trends?principal=unilever` (`revenue_last_12`, a negative month counted as 0;
Theil–Sen direction over 24 months, Mann–Kendall p < 0.05). Share: each category's sales over the sixteen categories'
total. Year-over-year: `GET /dashboard/yoy?principal=unilever&start_period=2025-03&end_period=2026-02` rows
(`mart.sales_mart_real`), summed per `category_path` over products with `months > 0` and `prior_months > 0`.
"""
    out = report_path(TABLE_DOC)
    out.write_text(text, encoding="utf-8")
    return out, problems


# --------------------------------------------------------------------------------------------------------------
def main() -> int:
    plt = style()
    print("loading (live read-only GETs and SQL, frozen rows, stored reports) ...")
    d = load()
    figs = {}
    for fn in (fig_a, fig_b, fig_c, fig_d, fig_e, fig_f, fig_g, fig_h, fig_i, fig_j, fig_k, fig_l, fig_m, fig_n,
               fig_o, fig_p, fig_q):
        f = fn(plt, d)
        figs[f.letter] = f
        print(f"  {f.letter}  {'HELD' if f.held else 'pass'}  {len(f.checks):3d} checks  {f.file}")
        for label, got, exp, ok, basis in f.checks:
            if not ok:
                print(f"       disagrees: {label}: data {got!r}, {basis} {exp!r}")
    man = write_manifest(figs)
    tab, problems = write_tables(d)
    print(f"wrote {man}\nwrote {tab}")
    for p in problems:
        print(f"  TABLE GATE: {p}")
    held = [f.letter for f in figs.values() if f.held]
    if problems or held:
        print(f"GATE: {len(held)} figure(s) held {held}; {len(problems)} table problem(s). Exit 2.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
