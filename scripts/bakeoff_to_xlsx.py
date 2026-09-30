"""
scripts.bakeoff_to_xlsx - render the model bake-off as a multi-sheet .xlsx.

One sheet per model (per-SKU MAPE / WAPE / sMAPE / MASE / MAE / RMSE + SKU
code + product name), red fill where a value fails its threshold (MAPE >=
0.20, MASE >= 1.00; the others have no threshold so are never highlighted),
plus a Summary sheet and a Legend. Rolling-origin 1-step backtest, last 6
real months, real Tier A. Reuses the model fns from scripts.model_bakeoff;
metrics and the "unstable" MAPE label come from
analytics.forecasting.diagnostic_metrics, same as scripts/archive/forecast_viewer.

Usage:  python -m scripts.bakeoff_to_xlsx [out_dir]     (default: reports/)
"""
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

warnings.simplefilter("ignore")
load_dotenv()

import scripts.model_bakeoff as mb   # reuse the 17 model fns
from analytics.forecasting.diagnostic_metrics import (
    is_mape_unstable, mape, mase, naive_scale, smape, wape,
)

REPORTS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), os.pardir, "reports")
OUT = os.path.join(REPORTS, "model_bakeoff_unilever_tierA.xlsx")
from analytics.params import MASE_GATE  # noqa: E402
MAPE_GATE = 0.20  # this workbook's red-cell threshold only; no pipeline gate uses MAPE since 2026-09-21
TEST_H = 6

# sheet order: naive, SBA, MA3 first, then the rest
SHEET_ORDER = ["naive", "sba_a3", "ma3", "sba", "theta", "ses", "ma6", "croston", "tsb",
               "holt", "holt_damped", "hw_add12", "snaive12", "mean", "drift",
               "sarima_plain", "sarima_seasonal"]
LABEL = {"naive": "Naive", "sba_a3": "SBA (a=0.3)", "sba": "SBA (a=0.1)", "ma3": "MA3", "ma6": "MA6",
         "theta": "Theta", "ses": "SES", "croston": "Croston", "tsb": "TSB", "holt": "Holt",
         "holt_damped": "Holt damped", "hw_add12": "Holt-Winters add", "snaive12": "Seasonal naive",
         "mean": "Mean", "drift": "Drift", "sarima_plain": "SARIMA(1,1,1)", "sarima_seasonal": "SARIMA seasonal"}

# ---- data ----
last = None
for d in (os.environ.get("SUPABASE_DB_URL"), os.environ.get("SUPABASE_DIRECT_URL")):
    try:
        c = psycopg2.connect(d, connect_timeout=15); c.set_session(readonly=True); break
    except Exception as e:
        last = e; c = None
if c is None: raise last
cur = c.cursor()
cur.execute("SELECT product_key, calendar_month, COALESCE(quantity_sold,0) FROM unilever_sku_demand_fact_real ORDER BY 1,2")
raw = pd.DataFrame(cur.fetchall(), columns=["pk", "m", "q"]); raw["q"] = raw["q"].astype(float)
cur.execute("""SELECT ac.product_key, pd.sku_code, pd.product_name
               FROM abc_classification ac JOIN product_dimension pd ON pd.product_key = ac.product_key
               WHERE ac.principal='unilever' AND ac.classification_period='2026-02' AND ac.tier='A'
                 AND ac.method='single'""")
meta = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
c.close()

def series(g):
    s = pd.Series(g["q"].to_numpy(float), index=pd.to_datetime(g["m"] + "-01")).sort_index()
    return s.resample("MS").asfreq().fillna(0.0)
S = {pk: series(g) for pk, g in raw.groupby("pk")}

METRICS = ("mape", "wape", "smape", "mase", "mae", "rmse")


def mape_text(value, unstable, min_abs):
    """Same rule and wording as the viewer's mapeTxt(): an unstable holdout
    prints the measured minimum |actual| instead of a 4-digit percentage."""
    if pd.isna(value):
        return None
    return f"unstable (min actual = {min_abs:,.0f})" if unstable else round(value, 3)


def backtest(x):
    n = len(x)
    origins = list(range(max(12, n - TEST_H), n))
    if len(origins) < 3:
        return None
    actual = np.array([x[t] for t in origins])
    scale = naive_scale(x[:origins[0]])
    unstable, min_abs = is_mape_unstable(actual)
    res = {"_check": dict(unstable=unstable, min_abs=min_abs)}
    for name in SHEET_ORDER:
        fn = mb.MODELS[name]
        preds = np.array([fn(x[:t]) for t in origins], float)
        if name in mb.GUARDED:              # same divergence guard as model_bakeoff
            preds = np.where(preds > np.array([x[:t].max() for t in origins]), np.nan, preds)
        preds = np.where(np.isfinite(preds), np.maximum(0, preds), np.nan)
        if not np.isfinite(preds).all():
            res[name] = dict.fromkeys(METRICS, np.nan)
            continue
        err = actual - preds
        res[name] = dict(mape=mape(actual, preds), wape=wape(actual, preds), smape=smape(actual, preds),
                         mase=mase(actual, preds, scale),
                         mae=float(np.abs(err).mean()), rmse=float(np.sqrt((err ** 2).mean())))
    return res

rows = []
t0 = time.time()
pks = list(meta)
for i, pk in enumerate(pks):
    s = S.get(pk)
    if s is None:
        continue
    x = s.to_numpy(float)
    sku, name = meta[pk]
    if len(x) < 14:
        rows.append(dict(pk=pk, sku=sku, name=name, months=len(x), nonzero=int((s > 0).sum()), evaluable=False))
        continue
    r = backtest(x)
    rec = dict(pk=pk, sku=sku, name=name, months=len(x), nonzero=int((s > 0).sum()), evaluable=r is not None)
    if r:
        chk = r.pop("_check")
        rec["mape_unstable"] = chk["unstable"]; rec["min_abs_actual"] = chk["min_abs"]
        for mdl, d in r.items():
            for k in METRICS:
                rec[f"{mdl}_{k}"] = d[k]
    rows.append(rec)
    if (i + 1) % 20 == 0:
        print(f"  {i+1}/{len(pks)}  ({time.time()-t0:.0f}s)")
df = pd.DataFrame(rows)
df.to_csv(os.path.join(REPORTS, "model_bakeoff_unilever_tierA_allmetrics.csv"), index=False)
print("computed; building workbook")

# ---- workbook ----
red = PatternFill("solid", fgColor="F4C7C3"); red_font = Font(color="9C1B1B")
hdr_fill = PatternFill("solid", fgColor="1F3864"); hdr_font = Font(color="FFFFFF", bold=True)
grey = Font(color="808080")
thin = Side(style="thin", color="D9D9D9"); border = Border(left=thin, right=thin, top=thin, bottom=thin)

wb = Workbook()
wb.remove(wb.active)

ev = df[df.evaluable].copy()
ins = df[~df.evaluable].sort_values("months")

# Summary sheet
sm = wb.create_sheet("Summary")
sm.append(["Model", "MAPE median (stable SKUs)", "WAPE median", "sMAPE median", "MASE median", "MAE median",
           "RMSE median", "MAPE<0.20", "MASE<1.0", "beats naive (MASE)"])
for j in range(1, 11):
    sm.cell(row=1, column=j).fill = hdr_fill; sm.cell(row=1, column=j).font = hdr_font
nv_mase = ev["naive_mase"]
for mdl in SHEET_ORDER:
    mp = ev[f"{mdl}_mape"].where(~ev["mape_unstable"].astype(bool)); ms = ev[f"{mdl}_mase"]
    pair = pd.DataFrame({"a": ms, "b": nv_mase}).dropna()
    beat = (pair.a < pair.b).mean() * 100 if len(pair) else np.nan
    sm.append([LABEL[mdl], round(mp.median(), 3), round(ev[f"{mdl}_wape"].median(), 3),
               round(ev[f"{mdl}_smape"].median(), 3), round(ms.median(), 3),
               round(ev[f"{mdl}_mae"].median(), 0), round(ev[f"{mdl}_rmse"].median(), 0),
               f"{int((mp < MAPE_GATE).sum())}/{mp.notna().sum()}",
               f"{int((ms < MASE_GATE).sum())}/{ms.notna().sum()}",
               f"{beat:.0f}%"])
for j, w in enumerate([18, 24, 13, 13, 13, 13, 13, 12, 12, 16], 1):
    sm.column_dimensions[get_column_letter(j)].width = w
sm.freeze_panes = "A2"

def add_model_sheet(mdl):
    ws = wb.create_sheet(LABEL[mdl][:31])
    cols = ["#", "SKU", "product name", "months", "nz", "MAPE", "MASE", "MAE", "RMSE", "WAPE", "sMAPE"]
    for j, cn in enumerate(cols, 1):
        c = ws.cell(row=1, column=j, value=cn); c.fill = hdr_fill; c.font = hdr_font
        c.alignment = Alignment(horizontal="center"); c.border = border
    sub = ev.sort_values(f"{mdl}_mape", na_position="last").reset_index(drop=True)
    r = 2
    for i, row in sub.iterrows():
        mp, ms = row[f"{mdl}_mape"], row[f"{mdl}_mase"]
        unstable = bool(row["mape_unstable"])
        vals = [i + 1, str(row["sku"]), row["name"] or "", int(row["months"]), int(row["nonzero"]),
                mape_text(mp, unstable, row["min_abs_actual"]), None if pd.isna(ms) else round(ms, 3),
                None if pd.isna(row[f"{mdl}_mae"]) else round(row[f"{mdl}_mae"], 0),
                None if pd.isna(row[f"{mdl}_rmse"]) else round(row[f"{mdl}_rmse"], 0),
                None if pd.isna(row[f"{mdl}_wape"]) else round(row[f"{mdl}_wape"], 3),
                None if pd.isna(row[f"{mdl}_smape"]) else round(row[f"{mdl}_smape"], 3)]
        for j, v in enumerate(vals, 1):
            cc = ws.cell(row=r, column=j, value=v); cc.border = border
            cc.alignment = Alignment(horizontal="left" if j in (2, 3) else "center")
        ws.cell(row=r, column=6).number_format = "0.000"
        ws.cell(row=r, column=7).number_format = "0.000"
        ws.cell(row=r, column=8).number_format = "#,##0"
        ws.cell(row=r, column=9).number_format = "#,##0"
        ws.cell(row=r, column=10).number_format = "0.000"
        ws.cell(row=r, column=11).number_format = "0.000"
        if pd.notna(mp) and mp >= MAPE_GATE and not unstable:
            ws.cell(row=r, column=6).fill = red; ws.cell(row=r, column=6).font = red_font
        if pd.notna(ms) and ms >= MASE_GATE:
            ws.cell(row=r, column=7).fill = red; ws.cell(row=r, column=7).font = red_font
        r += 1
    r += 1
    ws.cell(row=r, column=1, value=f"Not evaluable — under 14 months ({len(ins)} SKUs)").font = Font(italic=True, bold=True)
    r += 1
    for _, row in ins.iterrows():
        for j, v in enumerate([len(sub) + 1, str(row["sku"]), row["name"] or "",
                               int(row["months"]), int(row["nonzero"]), "insufficient history"], 1):
            ws.cell(row=r, column=j, value=v).font = grey
        r += 1
    for j, w in enumerate([5, 12, 42, 9, 6, 30, 9, 11, 11, 9, 9], 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:K{1 + len(sub)}"

for mdl in SHEET_ORDER:
    add_model_sheet(mdl)

# Legend sheet
lg = wb.create_sheet("Legend")
for row in [
    ["Metric", "Threshold (pass)", "Direction", "Range", "Notes"],
    ["MAPE", "< 0.20", "lower = better", "0 -> infinity", "Project gate. <0.10 excellent, 0.20-0.50 ok, >0.50 poor. Explodes when actual demand ~ 0."],
    ["MAPE 'unstable'", "(label, not a value)", "-", "-", "Shown instead of a percentage when an actual is <= 0 or the smallest |actual| is under 10% of the mean |actual| (diagnostic_metrics.is_mape_unstable). Same text as the forecast viewer."],
    ["WAPE", "(no fixed threshold)", "lower = better", "0 -> infinity", "Sum|error| / Sum|actual|, negative actuals included. Stable where MAPE is not."],
    ["sMAPE", "(no fixed threshold)", "lower = better", "0 -> 2", "Symmetric % error, negative actuals included."],
    ["MASE", "< 1.00", "lower = better", "0 -> infinity", "Error vs naive 'repeat last month'. =1 tied, >1 worse than naive, <0.5 strong."],
    ["MAE", "(no fixed threshold)", "lower = better", "0 -> infinity", "Mean absolute error in UNITS. Scale-dependent - judge vs this SKU's monthly volume."],
    ["RMSE", "(no fixed threshold)", "lower = better", "0 -> infinity", "Like MAE, squares errors first, so always >= MAE. RMSE/MAE >>1 = a few big misses."],
    [], ["Colour key"],
    ["red cell", "value fails its threshold (MAPE >= 0.20 or MASE >= 1.00)"],
    ["no fill", "meets threshold, or metric has no threshold (MAE / RMSE)"],
    [], ["Backtest", "rolling-origin, 1-step-ahead, last 6 real months, model refit at each origin"],
    ["Cohort", "real Tier A = tier 'A' in ABC_Classification 2026-02 (Unilever, _Real view). 89 evaluable, 43 under 14 months."],
    ["Sheets", "one per model, ordered Naive, SBA(0.3), MA3, then the rest by the main bake-off ranking."],
]:
    lg.append(row)
lg.cell(row=1, column=1).fill = hdr_fill
for j in range(1, 6):
    lg.cell(row=1, column=j).fill = hdr_fill; lg.cell(row=1, column=j).font = hdr_font
lg.cell(row=8, column=1).fill = red
for j, w in enumerate([12, 60, 16, 16, 95], 1):
    lg.column_dimensions[get_column_letter(j)].width = w

wb.save(OUT)
print(f"wrote {OUT}  ({len(wb.sheetnames)} sheets: {wb.sheetnames})")
