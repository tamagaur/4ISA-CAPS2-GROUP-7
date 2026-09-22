"""
tools/dsd_dev_viewer/build.py - regenerate the DSD Dev Viewer (dev tool).

Replaces tools/bin_viewer (length_v1 bins only) and tools/routing_viewer
(combined_v1 per-bin refit, never the live router). One view of what is LIVE:

    Tier A (as of 2026-02, method 'single')
      -> combined_v1 bin (sku_segment)
      -> router bin      (forecast_result.model_params.bin, DEC-26 length_v2)
      -> served model    (model_params.method)
      -> backup          (model_params.backup_fired / backup_reason)

Nothing is refitted: every number is read from what the pipeline stored.
Read-only. One query per table, pulled once, embedded as JSON into
dsd_dev_viewer.html (self-contained, open by double-clicking).

Preview mode ("with 2021-22 placeholder") reads the output of
scripts/preview_router_synth.py: router_preview_synth.csv, series_synth.csv and
preview_summary.csv, copied into data/ at build time. The build stops if any is
missing. Placeholder months are never demand; the page labels them everywhere.

Usage (from the repo root, .env holding SUPABASE_DIRECT_URL or SUPABASE_DB_URL):
    python tools/dsd_dev_viewer/build.py [--preview-src <folder>]
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time

import psycopg2
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

PRINCIPAL, ABC_PERIOD, ABC_METHOD = "unilever", "2026-02", "single"
REAL_START = "2023-01"
COMBINED_ORDER = ["insufficient", "short", "medium", "long_down", "long_flat", "long_up"]
ROUTER_ORDER = ["insufficient", "short", "medium", "long"]
BACKUP_ORDER = ["not fired", "not applicable", "fired"]
# analytics/forecasting/router.py LIVE_MODEL, plus the runner's provisional path
# for the insufficient bin (scripts/run_baseline_forecast.py _write_forecast_result).
# The note is a COHORT statement (half-year block tests) - the page shows it on
# model nodes and the banner only, never against a single SKU.
MODEL_LABEL = {
    "ma3": ("MA3", "benchmark"),
    "tsb": ("TSB", "cohort: ties MA3"),
    "xgb_ma3_avg": ("XGBoost + MA3 avg", "cohort: ties MA3"),
    "provisional": ("Provisional avg", "not scored"),
}
CHALLENGERS = {"tsb", "xgb_ma3_avg"}
# Expected counts for the traffic lights, as stated by Yuan on 2026-09-22 for the
# live 2026-03 forecast. A node with no entry here has no expected count on record.
EXPECTED = {
    "tier_a": 132,
    "combined": {"insufficient": 13, "short": 30, "medium": 17, "long_down": 22, "long_flat": 36, "long_up": 14},
    "router": {"insufficient": 13, "short": 30, "medium": 17, "long": 72},
    "model": {"ma3": 30, "tsb": 17, "xgb_ma3_avg": 72, "provisional": 13},
    "backup": {"not fired": 89, "not applicable": 43, "fired": 0},
    "forecast_result": 132,
}

COHORT = """SELECT product_key FROM abc_classification
            WHERE principal = %(p)s AND classification_period = %(per)s AND tier = 'A' AND method = %(m)s"""

QUERIES = {
    "abc": """SELECT product_key, tier FROM abc_classification
              WHERE principal = %(p)s AND classification_period = %(per)s AND method = %(m)s""",
    "product": f"""SELECT product_key, sku_code, product_name FROM product_dimension
                   WHERE product_key IN ({COHORT})""",
    "segment": f"""SELECT product_key,
                          json_object_agg(scheme, json_build_object('bin', bin, 'reason', bin_reason))
                   FROM sku_segment
                   WHERE principal = %(p)s AND cohort_period = %(per)s AND abc_method = %(m)s
                     AND product_key IN ({COHORT})
                   GROUP BY product_key""",
    "traits": f"""SELECT product_key, history_months, first_sale_period, longest_run, trend, trend_slope,
                         trend_pvalue, cv, adi, restart_flag, stability_group, revenue_share_2026_02
                  FROM sku_traits
                  WHERE principal = %(p)s AND cohort_period = %(per)s AND abc_method = %(m)s
                    AND product_key IN ({COHORT})""",
    "forecast": f"""SELECT product_key, forecast_date::text, forecast_value, confidence_lower, confidence_upper,
                           mape, mase, status,
                           model_params->>'bin', model_params->>'method', model_params->>'ma3_value',
                           model_params->'holdout_metrics_served', model_params->>'backup_fired',
                           model_params->>'backup_reason', model_params->'components',
                           model_params->>'provisional', model_params->>'sales_months'
                    FROM forecast_result
                    WHERE forecast_date = (SELECT MAX(forecast_date) FROM forecast_result)
                      AND product_key IN ({COHORT})""",
    # One pass over the whole view: every SKU's row count (the Pipeline node's
    # rows in), and the monthly series for the Tier A cohort only.
    "demand": f"""SELECT product_key, SUM(n_rows)::int,
                         json_object_agg(calendar_month, qty) FILTER (
                             WHERE product_key IN ({COHORT}) AND calendar_month BETWEEN %(start)s AND %(per)s)
                  FROM (SELECT product_key, calendar_month, SUM(quantity_sold) AS qty, COUNT(*) AS n_rows
                        FROM unilever_sku_demand_fact_real
                        GROUP BY 1, 2) d
                  GROUP BY product_key""",
}


def _num(v, nd=4):
    return None if v is None else round(float(v), nd)


def fetch() -> tuple[dict, dict]:
    load_dotenv(os.path.join(REPO, ".env"))
    conn = psycopg2.connect(os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"])
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()
    params = {"p": PRINCIPAL, "per": ABC_PERIOD, "m": ABC_METHOD, "start": REAL_START}
    out, timing = {}, {}
    for name, sql in QUERIES.items():
        t = time.perf_counter()
        cur.execute(sql, params)
        out[name] = cur.fetchall()
        timing[name] = round(time.perf_counter() - t, 2)
    conn.close()
    return out, timing


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    res = []
    while (y, m) <= (ey, em):
        res.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return res


def recent_level_ratio(series: list[float]) -> float | None:
    """mean(last 3) / mean(last 12) of the SKU's modelling series. Display only,
    no threshold. None under 12 months or when the 12-month mean is not positive."""
    if len(series) < 12:
        return None
    m12 = sum(series[-12:]) / 12
    return None if m12 <= 0 else sum(series[-3:]) / 3 / m12


def ma3_same_holdout(monthly: list, periods: list[str]) -> tuple[float | None, int]:
    """MA3's MASE on the same rolling one-step holdout the served model was
    scored on. Reuses the pipeline's own pieces, no reimplementation:
      series  first row -> last row, gaps zero-filled (run_baseline_forecast.build_series)
      split   analytics.forecasting.sarima.train_holdout_split (last 20%)
      MA3     analytics.forecasting.router.rolling_one_step, column "ma3"
              (router.ma3_value from the first sale, floored at zero)
      metric  diagnostic_metrics.mase with naive_scale(train)
    Pure computation on the rows already pulled; no DB access."""
    import numpy as np
    import pandas as pd
    from analytics.forecasting.diagnostic_metrics import mase, naive_scale
    from analytics.forecasting.router import rolling_one_step
    from analytics.forecasting.sarima import HOLDOUT_FRACTION, train_holdout_split
    present = [i for i, v in enumerate(monthly) if v is not None]
    if not present:
        return None, 0
    idx = pd.to_datetime([periods[i] + "-01" for i in range(present[0], present[-1] + 1)])
    series = pd.Series([monthly[i] or 0.0 for i in range(present[0], present[-1] + 1)], index=idx, dtype=float)
    train, holdout = train_holdout_split(series, holdout_fraction=HOLDOUT_FRACTION)
    scored = rolling_one_step(series, list(holdout.index), None, force_bin="short")
    m = mase(scored["actual"].to_numpy(), scored["ma3"].to_numpy(), naive_scale(train.to_numpy(dtype=float)))
    return (None if not np.isfinite(m) else m), len(scored)


def assemble(raw: dict) -> dict:
    tiers = {r[0]: r[1] for r in raw["abc"]}
    cohort = sorted(pk for pk, t in tiers.items() if t == "A")
    product = {r[0]: r[1:] for r in raw["product"]}
    segment = {r[0]: r[1] for r in raw["segment"]}
    traits = {r[0]: r[1:] for r in raw["traits"]}
    forecast = {r[0]: r[1:] for r in raw["forecast"]}
    view_rows = {r[0]: r[1] for r in raw["demand"]}
    demand = {r[0]: r[2] for r in raw["demand"] if r[2] is not None}
    periods = months(REAL_START, ABC_PERIOD)

    skus, problems = [], []
    for pk in cohort:
        code, name = product.get(pk, (None, None))
        seg = segment.get(pk, {})
        tr = traits.get(pk)
        fc = forecast.get(pk)
        if tr is None:
            problems.append(f"{pk}: no sku_traits row")
        if fc is None:
            problems.append(f"{pk}: no forecast_result row")
        (fdate, fval, lo, hi, mape, mase, status, rbin, method, ma3, served, fired, reason, comps, prov,
         smonths) = fc if fc else (None,) * 16
        if status == "insufficient_data":
            rbin, method = rbin or "insufficient", "provisional"
        served = served or {}
        dm = demand.get(pk, {})
        monthly = [None if dm.get(p) is None else _num(dm[p], 1) for p in periods]
        # a row whose quantity is NULL: the pipeline's fetch_demand fillna(0) counts it as 0
        null_months = [i for i, p in enumerate(periods) if p in dm and dm[p] is None]
        present = sorted({i for i, v in enumerate(monthly) if v is not None} | set(null_months))
        first_i, last_i = (present[0], present[-1]) if present else (None, None)
        # The modelling series: first row -> last row, gaps zero-filled
        # (scripts/run_baseline_forecast.py build_series). Its holdout is the last
        # holdout_months of that span (analytics/forecasting/sarima.py train_holdout_split).
        model_series = [monthly[i] or 0.0 for i in range(first_i, last_i + 1)] if present else []
        h = served.get("months")
        holdout = [last_i - h + 1, last_i] if h and present else None
        fval_n, ma3_n = _num(fval, 3), _num(ma3, 3)
        rlr = recent_level_ratio(model_series)
        ma3_mase, ma3_hmonths = ma3_same_holdout(monthly, periods) if status == "ok" else (None, 0)
        if status == "ok" and ma3_hmonths != h:
            problems.append(f"{pk}: MA3 holdout {ma3_hmonths} months vs served {h}")
        skus.append({
            "pk": pk, "code": code, "name": name,
            "combined": (seg.get("combined_v1") or {}).get("bin"),
            "bin_reason": (seg.get("combined_v1") or {}).get("reason"),
            "schemes": {k: v["bin"] for k, v in seg.items()},
            "router_bin": rbin, "method": method, "status": status,
            "forecast_date": fdate, "served": fval_n, "lo": _num(lo, 3), "hi": _num(hi, 3),
            "ma3": ma3_n, "components": comps,
            "gap": None if fval_n is None or not ma3_n else round((fval_n - ma3_n) / ma3_n, 4),
            "rlr": None if rlr is None else round(rlr, 3),
            "mase": _num(mase), "ma3_mase": _num(ma3_mase), "mape": _num(mape), "wape": _num(served.get("wape")),
            "ma3_wape": _num(served.get("ma3_wape")), "holdout_months": h, "holdout": holdout,
            "backup": ("fired" if fired == "true" else "not fired") if method in CHALLENGERS else "not applicable",
            "backup_reason": reason,
            "provisional": prov == "true", "sales_months": int(smonths) if smonths else None,
            "view_rows": view_rows.get(pk, 0), "first_i": first_i, "last_i": last_i,
            "gap_months": sum(1 for i in range(first_i, last_i + 1) if monthly[i] is None and i not in null_months) if present else 0,
            "null_months": null_months,
            "neg_months": sum(1 for v in monthly if v is not None and v < 0),
            "traits": None if tr is None else {
                "history_months": tr[0], "first_sale": tr[1], "longest_run": tr[2], "trend": tr[3],
                "trend_slope": _num(tr[4]), "trend_pvalue": _num(tr[5]), "cv": _num(tr[6]), "adi": _num(tr[7]),
                "restart_flag": tr[8], "stability_group": tr[9], "revenue_share": _num(tr[10], 5)},
            "monthly": monthly,
        })

    def count(key, order):
        c = {k: 0 for k in order}
        for s in skus:
            c[s[key]] = c.get(s[key], 0) + 1
        return c

    edges = {}
    for s in skus:
        for a, b in ((("src", "Tier A"), ("combined", s["combined"])),
                     (("combined", s["combined"]), ("router", s["router_bin"])),
                     (("router", s["router_bin"]), ("model", s["method"])),
                     (("model", s["method"]), ("backup", s["backup"]))):
            k = f"{a[0]}:{a[1]}|{b[0]}:{b[1]}"
            edges[k] = edges.get(k, 0) + 1

    tier_counts = {}
    for t in tiers.values():
        tier_counts[t] = tier_counts.get(t, 0) + 1
    return {
        "meta": {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                 "cohort": f"Tier A as of {ABC_PERIOD}, method '{ABC_METHOD}'", "principal": PRINCIPAL,
                 "n": len(cohort), "forecast_date": next((s["forecast_date"] for s in skus if s["forecast_date"]), None),
                 "problems": problems,
                 "view_rows": sum(view_rows.values()), "view_skus": len(view_rows),
                 "abc_classified": len(tiers), "abc_tiers": tier_counts},
        "periods": periods, "combined_order": COMBINED_ORDER, "router_order": ROUTER_ORDER,
        "backup_order": BACKUP_ORDER, "model_label": MODEL_LABEL, "expected": EXPECTED,
        "counts": {"combined": count("combined", COMBINED_ORDER), "router": count("router_bin", ROUTER_ORDER),
                   "model": count("method", list(MODEL_LABEL)), "backup": count("backup", BACKUP_ORDER),
                   "status": count("status", [])},
        "edges": [{"from": k.split("|")[0], "to": k.split("|")[1], "n": v} for k, v in sorted(edges.items())],
        "skus": skus,
    }


# --------------------------------------------------------------------------- #
# Preview mode: "with 2021-22 placeholder" (what-if, never evidence)
# --------------------------------------------------------------------------- #
PREVIEW_FILES = ("router_preview_synth.csv", "series_synth.csv", "preview_summary.csv")
# scripts/preview_router_synth.py's output. Override with --preview-src or
# DSD_PREVIEW_SRC; the files are copied into data/ at build time.
DEFAULT_PREVIEW_SRC = os.environ.get("DSD_PREVIEW_SRC", os.path.join(REPO, "reports", "preview"))
DATA_DIR = os.path.join(HERE, "data")
PREVIEW_START = "2021-01"
PREVIEW_METHOD = {"trailing_average": "provisional"}


def copy_preview_inputs(src: str) -> None:
    import shutil
    missing = [f for f in PREVIEW_FILES if not os.path.isfile(os.path.join(src, f))]
    if missing:
        sys.exit(f"BUILD FAILED: preview input(s) missing from {src}: {', '.join(missing)}. "
                 f"Run scripts/preview_router_synth.py or pass --preview-src.")
    os.makedirs(DATA_DIR, exist_ok=True)
    for f in PREVIEW_FILES:
        shutil.copyfile(os.path.join(src, f), os.path.join(DATA_DIR, f))


def load_backup_options(src: str):
    """backup_options.json, if the model-list decision has produced one; else None
    ('pending decision' in both modes). Never computed here."""
    for d in (DATA_DIR, src):
        p = os.path.join(d, "backup_options.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
    return None


def assemble_preview(skus: list[dict]) -> dict:
    """Per-SKU preview overrides, read as given from the copied files: bins, served
    forecast, served MASE / WAPE, and MA3's MASE / WAPE on the same holdout
    (ma3_holdout_mase / ma3_holdout_wape) all come from router_preview_synth.csv.
    Nothing is refitted or rescaled here. The only derived value is WHICH months
    are the holdout, for the chart shading: train_holdout_split on the file's own
    series, zero-filled first -> last row as the preview script does."""
    import numpy as np
    import pandas as pd
    from analytics.forecasting.sarima import HOLDOUT_FRACTION, train_holdout_split

    rp = pd.read_csv(os.path.join(DATA_DIR, "router_preview_synth.csv"))
    need = {"ma3_holdout_mase", "ma3_holdout_wape", "holdout_mase", "holdout_wape"}
    if need - set(rp.columns):
        sys.exit(f"BUILD FAILED: router_preview_synth.csv lacks {sorted(need - set(rp.columns))}")
    rp["backup_fired"] = rp["backup_fired"].astype(str).str.lower().eq("true")
    raw = pd.read_csv(os.path.join(DATA_DIR, "series_synth.csv"), dtype={"month": str})
    raw["is_placeholder"] = raw["is_placeholder"].astype(str).str.lower().eq("true")
    summary = pd.read_csv(os.path.join(DATA_DIR, "preview_summary.csv"))

    periods = months(PREVIEW_START, ABC_PERIOD)
    pidx = {p: i for i, p in enumerate(periods)}
    real = {s["pk"]: s for s in skus}
    if set(rp["product_key"]) != set(real):
        sys.exit("BUILD FAILED: router_preview_synth.csv product keys differ from the live Tier A cohort")

    def f(v, nd=4):
        return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), nd)

    out, checks = {}, {"ma3_equal": 0, "ma3_total": 0, "holdout_in_placeholder": 0}
    for r in rp.itertuples(index=False):
        pk = int(r.product_key)
        g = raw[raw["product_key"] == pk]
        monthly = [None] * len(periods)
        ph = [False] * len(periods)
        for m, q, isph in zip(g["month"], g["quantity"], g["is_placeholder"]):
            monthly[pidx[m]] = None if pd.isna(q) else round(float(q), 1)
            ph[pidx[m]] = bool(isph)
        # a real month whose quantity is NULL in the _Real view: the file carries the
        # pipeline's 0; the page marks it the same way in both modes
        off = len(periods) - len(real[pk]["monthly"])
        null_months = [i + off for i in real[pk]["null_months"]]
        for i in null_months:
            monthly[i] = None
        present = [i for i, v in enumerate(monthly) if v is not None or i in null_months]
        ph_idx = [i for i, x in enumerate(ph) if x]
        method = PREVIEW_METHOD.get(r.served_model, r.served_model)
        rec = {
            "monthly": monthly, "null_months": null_months, "ph": [ph_idx[0], ph_idx[-1]] if ph_idx else None,
            "ph_count": len(ph_idx),
            "first_i": present[0] if present else None, "last_i": present[-1] if present else None,
            "gap_months": sum(1 for i in range(present[0], present[-1] + 1)
                              if monthly[i] is None and i not in null_months) if present else 0,
            "neg_months": sum(1 for v in monthly if v is not None and v < 0),
            "view_rows": int(len(g)), "router_bin": r.bin, "real_bin": real[pk]["router_bin"], "method": method,
            "status": r.status, "served": f(r.forecast, 3), "ma3": f(r.ma3_forecast, 3), "lo": None, "hi": None,
            "components": None, "backup_reason": None, "provisional": r.status == "insufficient_data",
            "backup": ("fired" if r.backup_fired else "not fired") if method in CHALLENGERS else "not applicable",
            "mase": f(r.holdout_mase), "wape": f(r.holdout_wape),
            "ma3_mase": f(r.ma3_holdout_mase), "ma3_wape": f(r.ma3_holdout_wape),
            "holdout": None, "holdout_months": None,
        }
        zf = [0.0 if (monthly[i] is None) else monthly[i] for i in range(rec["first_i"], rec["last_i"] + 1)] if present else []
        rec["sales_months"] = sum(1 for v in zf if v > 0)
        rec["rlr"] = f(recent_level_ratio(zf), 3)
        rs = real[pk]["served"]
        rec["change"] = None if rec["served"] is None or not rs else round((rec["served"] - rs) / rs, 4)
        rec["gap"] = None if rec["served"] is None or not rec["ma3"] else round((rec["served"] - rec["ma3"]) / rec["ma3"], 4)
        if r.status == "ok" and present:
            series = pd.Series(zf, index=pd.to_datetime([periods[i] + "-01" for i in range(rec["first_i"], rec["last_i"] + 1)]))
            _, holdout = train_holdout_split(series, holdout_fraction=HOLDOUT_FRACTION)
            h0 = pidx[holdout.index[0].strftime("%Y-%m")]
            rec["holdout"], rec["holdout_months"] = [h0, h0 + len(holdout) - 1], int(len(holdout))
            if any(ph[i] for i in range(h0, h0 + len(holdout))):
                checks["holdout_in_placeholder"] += 1
            if method == "ma3":      # file consistency: MA3 served => served MASE == MA3 MASE
                checks["ma3_total"] += 1
                checks["ma3_equal"] += int(rec["ma3_mase"] is not None and rec["mase"] is not None
                                           and abs(rec["ma3_mase"] - rec["mase"]) < 1e-9)
        out[pk] = rec
    if checks["holdout_in_placeholder"]:
        sys.exit(f"BUILD FAILED: {checks['holdout_in_placeholder']} SKUs have a placeholder month in the preview holdout")

    def vc(col, mapping=None):
        s = rp[col].map(mapping).fillna(rp[col]) if mapping else rp[col]
        return {str(k): int(v) for k, v in s.value_counts().items()}
    served_m = rp["served_model"].map(PREVIEW_METHOD).fillna(rp["served_model"])
    backup_exp = {"not fired": int(((served_m.isin(CHALLENGERS)) & ~rp["backup_fired"]).sum()),
                  "not applicable": int((~served_m.isin(CHALLENGERS)).sum()),
                  "fired": int(((served_m.isin(CHALLENGERS)) & rp["backup_fired"]).sum())}
    blocks = summary[summary["table"] == "testable_blocks"]
    moves = summary[summary["table"] == "test_month_bin_moves"]
    return {
        "periods": periods, "skus": {str(k): v for k, v in out.items()},
        "expected": {"tier_a": int(len(rp)), "combined": EXPECTED["combined"], "router": vc("bin"),
                     "model": vc("served_model", PREVIEW_METHOD), "backup": backup_exp, "forecast_result": int(len(rp))},
        "file_rows": int(len(raw)), "placeholder_rows": int(raw["is_placeholder"].sum()),
        "placeholder_skus": int(raw.loc[raw["is_placeholder"], "product_key"].nunique()),
        "blocks": [{"arm": a, "bin": b, "value": int(v)} for a, b, v in zip(blocks["arm"], blocks["bin"], blocks["value"])],
        "moves": [{"real": a, "synth": b, "n": int(v)} for a, b, v in zip(moves["real_bin"], moves["synth_bin"], moves["value"])],
        "checks": checks,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preview-src", default=DEFAULT_PREVIEW_SRC,
                    help="folder holding the preview CSVs (default: $DSD_PREVIEW_SRC or the preview session's scratchpad)")
    args = ap.parse_args()
    t0 = time.perf_counter()
    copy_preview_inputs(args.preview_src)          # fails loudly before any DB work
    raw, timing = fetch()
    t_db = time.perf_counter() - t0
    payload = assemble(raw)
    payload["preview"] = assemble_preview(payload["skus"])
    payload["backup_options"] = load_backup_options(args.preview_src)
    data = json.dumps(payload, separators=(",", ":"), allow_nan=False, default=str).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data)
    out = os.path.join(HERE, "dsd_dev_viewer.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    c, m = payload["counts"], payload["meta"]
    print(f"cohort={m['n']} forecast_rows={sum(1 for s in payload['skus'] if s['status'])} "
          f"forecast_date={m['forecast_date']} view_rows={m['view_rows']} view_skus={m['view_skus']} "
          f"abc_classified={m['abc_classified']}")
    print(f"combined_v1={c['combined']}")
    print(f"router={c['router']} model={c['model']} backup={c['backup']}")
    short = [s for s in payload["skus"] if s["method"] == "ma3"]
    same = sum(1 for s in short if s["mase"] is not None and s["ma3_mase"] is not None and abs(s["ma3_mase"] - s["mase"]) <= 0.00051)
    print(f"MA3-served SKUs whose recomputed MA3 MASE equals the stored served MASE (3 dp, as stored): {same} of {len(short)}")
    pv = payload["preview"]
    pvc = {}
    for s in pv["skus"].values():
        pvc[s["router_bin"]] = pvc.get(s["router_bin"], 0) + 1
    print(f"preview: bins={pvc} placeholder_skus={pv['placeholder_skus']} placeholder_rows={pv['placeholder_rows']} "
          f"file check, MA3-served SKUs with served MASE == ma3_holdout_mase: {pv['checks']['ma3_equal']} of {pv['checks']['ma3_total']} "
          f"backup_options={'loaded' if payload['backup_options'] else 'none (pending decision)'}")
    print(f"problems={m['problems'] or 'none'}")
    print(f"query seconds={timing}  db total={t_db:.2f}s  build total={time.perf_counter() - t0:.2f}s  "
          f"html={os.path.getsize(out) / 1024:.0f} KB")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DSD Dev Viewer</title>
<style>
:root{
  color-scheme:dark;
  --bg:#0f1117;--surface-1:#161a24;--surface-2:#1d2230;--surface-3:#252b3b;
  --ink:#eef0f6;--ink-2:#b9bfd0;--ink-3:#7d8499;--line:rgba(255,255,255,.07);--line-2:rgba(255,255,255,.14);
  --accent:#6ea8fe;
  --actual:#c3c2b7;
  --m-ma3:#199e70;--m-tsb:#9085e9;--m-xgb:#d95926;--m-prov:#8a8f9e;
  --ok:#2fb36d;--warn:#e0a526;--bad:#e5484d;--none:#5b6173;
  --flag-bg:rgba(224,165,38,.14);--flag-ink:#f1c35c;
  --ui:"Segoe UI",-apple-system,"Helvetica Neue",Arial,sans-serif;
  --mono:"Cascadia Mono","Cascadia Code",Consolas,"Courier New",monospace;
  --r:10px;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 var(--ui)}
button,input,select{font:inherit;color:inherit}

header{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:20px;padding:0 24px;height:56px;
  background:rgba(15,17,23,.94);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:baseline;gap:10px;white-space:nowrap}
.brand b{font-size:15px}
.brand span{color:var(--ink-3);font-size:12px}
nav{display:flex;gap:4px;margin-left:8px;height:100%}
nav button{background:none;border:0;padding:0 14px;color:var(--ink-3);cursor:pointer;border-bottom:2px solid transparent;font-weight:600}
nav button:hover{color:var(--ink-2)}
nav button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)}
.meta{margin-left:auto;color:var(--ink-3);font-size:12px;text-align:right;line-height:1.35}

.wrap{padding:18px 24px 32px;max-width:1800px;margin:0 auto}
.note{display:flex;gap:10px;align-items:flex-start;padding:10px 14px;border-radius:var(--r);background:var(--surface-1);
  border:1px solid var(--line);color:var(--ink-2);font-size:12px;margin-bottom:14px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600;
  background:var(--surface-3);color:var(--ink-2);white-space:nowrap}
.pill i{width:8px;height:8px;border-radius:50%;display:inline-block}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.kpi{background:var(--surface-1);border:1px solid var(--line);border-radius:var(--r);padding:12px 14px}
.kpi .v{font:600 24px/1.1 var(--ui);font-variant-numeric:tabular-nums}
.kpi .l{color:var(--ink-3);font-size:12px;margin-top:4px}
.card{background:var(--surface-1);border:1px solid var(--line);border-radius:var(--r);padding:16px;min-width:0}
.card h2{margin:0 0 2px;font-size:14px;font-weight:600}
.card .sub{color:var(--ink-3);font-size:12px;margin-bottom:12px}
.two{display:grid;grid-template-columns:minmax(0,1fr) 440px;gap:14px;align-items:start}
.stack{display:grid;gap:14px;min-width:0}
.sticky{position:sticky;top:70px;max-height:calc(100vh - 86px);overflow:auto}

/* flow (routing) */
.flowSvg svg{width:100%;height:auto;display:block}
.colh{fill:var(--ink-3);font-size:11px;font-weight:600;letter-spacing:.04em}
.node{cursor:pointer}
.node rect.box{fill:var(--surface-2);stroke:var(--line-2)}
.node:hover rect.box{fill:var(--surface-3)}
.node.sel rect.box{stroke:var(--accent);stroke-width:2}
.node.empty rect.box{fill:none;stroke-dasharray:4 3}
.node text{fill:var(--ink);font-size:12px;pointer-events:none}
.node text.n{fill:var(--ink-2);font-family:var(--mono)}
.node text.s{fill:var(--ink-3);font-size:11px}
.link{fill:none;stroke-opacity:.32;transition:stroke-opacity .12s}
.link.hi{stroke-opacity:.65}
.filtered .link:not(.hi){stroke-opacity:.12}

/* controls */
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.search{background:var(--surface-2);border:1px solid var(--line-2);border-radius:8px;padding:6px 10px;width:260px;outline:none}
.search:focus{border-color:var(--accent)}
.btn{background:var(--surface-2);border:1px solid var(--line-2);border-radius:8px;padding:6px 12px;cursor:pointer}
.btn:hover{background:var(--surface-3)}
.btn:disabled{opacity:.4;cursor:default}
.seg{display:inline-flex;background:var(--surface-2);border:1px solid var(--line-2);border-radius:8px;padding:2px;flex-wrap:wrap}
.seg button{background:none;border:0;padding:4px 10px;border-radius:6px;cursor:pointer;color:var(--ink-2);display:inline-flex;align-items:center;gap:6px}
.seg button[aria-pressed="true"]{background:var(--surface-3);color:var(--ink)}
.seg i{width:8px;height:8px;border-radius:50%}
.count{color:var(--ink-3);font-size:12px;margin-left:auto}
.ac{position:relative}
.ac .search{width:340px}
.ac ul{position:absolute;top:100%;left:0;right:0;margin:4px 0 0;padding:4px;list-style:none;background:#0b0d13;border:1px solid var(--line-2);
  border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.5);z-index:40;max-height:320px;overflow:auto}
.ac li{padding:6px 8px;border-radius:6px;cursor:pointer;display:flex;gap:10px;align-items:baseline}
.ac li b{font-family:var(--mono);font-weight:600}
.ac li span{color:var(--ink-3);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ac li[aria-selected="true"],.ac li:hover{background:var(--surface-3)}

/* tables */
.tw{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}
td{white-space:nowrap}
th{position:sticky;top:0;background:var(--surface-2);color:var(--ink-3);font-weight:600;cursor:pointer;user-select:none;z-index:1;
  white-space:normal;vertical-align:bottom;line-height:1.25;min-width:56px}
th.num,td.num{text-align:right}
td.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--surface-2)}
tbody tr.sel{background:rgba(110,168,254,.10);box-shadow:inset 3px 0 0 var(--accent)}
td.name{max-width:220px;overflow:hidden;text-overflow:ellipsis}
td.flag{background:var(--flag-bg);color:var(--flag-ink);font-weight:600}
.muted{color:var(--ink-3)}
.ph{color:var(--ink-3);font-style:italic}

/* detail / focus */
.dhead{display:flex;flex-direction:column;gap:6px;margin-bottom:10px}
.dhead .code{font:600 18px/1.2 var(--mono)}
.dhead .nm{color:var(--ink-2)}
.tags{display:flex;gap:6px;flex-wrap:wrap}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px;margin:12px 0}
.stat{background:var(--surface-2);border-radius:8px;padding:8px 10px;min-width:0}
.stat .v{font:600 15px/1.2 var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat .l{color:var(--ink-3);font-size:11px;margin-top:2px}
.stat.flag{background:var(--flag-bg)}
.stat.flag .v{color:var(--flag-ink)}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--ink-2);font-size:11px;margin-top:6px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw-line{width:14px;height:2px;border-radius:1px;display:inline-block}
.sw-dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.sw-ring{width:9px;height:9px;border-radius:50%;display:inline-block;border:2px solid}
.sw-hollow{width:8px;height:8px;border-radius:50%;display:inline-block;border:1.5px solid var(--ink-3)}
.sw-band{width:9px;height:12px;border-radius:2px;display:inline-block;opacity:.3}
.sw-hold{width:12px;height:12px;border-radius:2px;display:inline-block;background:var(--accent);opacity:.18}
details{border-top:1px solid var(--line);padding:8px 0}
summary{cursor:pointer;color:var(--ink-2);font-weight:600;font-size:12px;padding:2px 0}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:8px 0 0;font-size:12px}
dl.kv dt{color:var(--ink-3)}
dl.kv dd{margin:0;font-family:var(--mono);word-break:break-word}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.xh{stroke:var(--ink-3);stroke-width:1;stroke-dasharray:3 3;pointer-events:none}
.focus{display:grid;grid-template-columns:minmax(0,1fr) 220px;gap:14px}
.focusnav{display:flex;align-items:center;gap:8px;margin-left:auto}
.backupbox{border:1px dashed var(--line-2);border-radius:8px;padding:12px;color:var(--ink-3);font-size:12px;align-self:start}
.backupbox b{display:block;color:var(--ink-2);margin-bottom:4px}
.spark svg{display:block}

/* grid view */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.fc{background:var(--surface-1);border:1px solid var(--line);border-radius:var(--r);padding:12px 12px 10px;cursor:pointer}
.fc:hover{border-color:var(--line-2)}
.fc.sel{border-color:var(--accent)}
.fc .top{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.fc .code{font:600 13px var(--mono)}
.fc .nm{color:var(--ink-3);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px}
.fc .foot{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:6px}
.fc .foot div{font-size:11px;color:var(--ink-3)}
.fc .foot b{display:block;font:600 12px var(--mono);color:var(--ink)}
.empty{padding:40px;text-align:center;color:var(--ink-3)}

/* pipeline */
.canvas{background:
  radial-gradient(circle, rgba(255,255,255,.05) 1px, transparent 1px) 0 0/18px 18px, var(--surface-1)}
.canvas svg{width:100%;height:auto;display:block}
.kn{cursor:pointer}
.kn .body{fill:var(--surface-2);stroke:var(--line-2);stroke-width:1}
.kn:hover .body{fill:var(--surface-3)}
.kn.sel .body{stroke:var(--accent);stroke-width:2}
.kn.path .body{stroke:var(--accent);stroke-width:2.5}
.kn.dim{opacity:.35}
.kn text{fill:var(--ink);font-size:12px;pointer-events:none}
.kn text.t{font-weight:600}
.kn text.io{fill:var(--ink-3);font-family:var(--mono);font-size:11px}
.kn text.st{fill:var(--ink-3);font-size:10.5px}
.wire{fill:none;stroke:var(--ink-3);stroke-width:1.5;opacity:.6}
.wire.path{stroke:var(--accent);opacity:1;stroke-width:2.5}
.lightbox{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--ink-2)}
.lightbox span{display:inline-flex;gap:6px;align-items:center}
.lamp{width:10px;height:10px;border-radius:50%;display:inline-block}
.pnode{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.pnode h3{margin:0;font-size:14px}
.checks{font-size:12px;color:var(--ink-2);margin:0 0 10px;padding-left:18px}

#tip{position:fixed;z-index:50;pointer-events:none;background:#0b0d13;border:1px solid var(--line-2);border-radius:8px;
  padding:7px 10px;font-size:12px;box-shadow:0 8px 24px rgba(0,0,0,.45);display:none;min-width:140px}
#tip .h{color:var(--ink-3);font-size:11px;margin-bottom:3px}
#tip .r{display:flex;justify-content:space-between;gap:14px}
#tip .r b{font-family:var(--mono);font-weight:600}
[hidden]{display:none!important}
@media (max-width:1200px){.two{grid-template-columns:1fr}.sticky{position:static;max-height:none}.focus{grid-template-columns:1fr}}
/* preview mode */
:root{--ph:#c9a227}
.pvbanner{position:sticky;top:56px;z-index:25;display:flex;gap:10px;align-items:center;padding:9px 24px;
  background:repeating-linear-gradient(135deg,#3a2f0c 0 10px,#2e260b 10px 20px);border-bottom:1px solid #6b5716;color:#f3dd8a;font-size:12.5px}
.pvbanner b{color:#ffe9a3;letter-spacing:.03em}
.modeSeg button[data-v="preview"][aria-pressed="true"]{background:#5a4a14;color:#ffe9a3}
.sw-null{width:8px;height:8px;display:inline-block;border:1.5px solid var(--warn)}
.sw-ph{width:14px;height:0;border-top:2px dashed var(--ph);display:inline-block}
.sw-phbg{width:12px;height:12px;border-radius:2px;display:inline-block;background:repeating-linear-gradient(135deg,rgba(201,162,39,.35) 0 3px,transparent 3px 6px)}
.pvnote{border-left:3px solid var(--ph);background:rgba(201,162,39,.08);color:#e8d48f;padding:8px 12px;border-radius:0 8px 8px 0;font-size:12px;margin:8px 0}
.mini{border-collapse:collapse;font-size:12px;margin:6px 0 10px}
.mini th,.mini td{padding:4px 10px;border:1px solid var(--line);text-align:right;position:static;background:none;cursor:default}
.mini th{color:var(--ink-3);font-weight:600}
.mini td.l,.mini th.l{text-align:left}
.pvgrid{display:grid;grid-template-columns:auto auto 1fr;gap:18px;align-items:start}
@media (max-width:1200px){.pvgrid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <div class="brand"><b>DSD Dev Viewer</b><span>Unilever · Tier A</span></div>
  <nav role="tablist">
    <button role="tab" data-tab="forecasts" aria-selected="true">Forecasts</button>
    <button role="tab" data-tab="pipeline" aria-selected="false">Pipeline</button>
  </nav>
  <div class="seg modeSeg" id="modeSeg" role="group" aria-label="Data mode"></div>
  <div class="meta" id="meta"></div>
</header>
<div class="pvbanner" id="pvbanner" hidden role="status"><b>PREVIEW</b><span>— 2021–22 months are placeholder data, not SSM's.
  Shows how routing changes with more history. Accuracy numbers here are not evidence: the placeholder is smoother than real sales.</span></div>
<div class="wrap">
  <div class="note"><span class="pill">Frozen snapshot</span><div id="noteText"></div></div>
  <div class="kpis" id="kpis"></div>

  <section id="tab-forecasts">
    <div class="toolbar">
      <div class="ac" id="acF"></div>
      <div class="seg" id="binSeg"></div>
      <div class="seg" id="modelSeg"></div>
      <div class="seg" id="viewSeg"></div>
      <span class="count" id="gcount"></span>
    </div>
    <div class="card" id="focus" style="margin-bottom:14px"></div>
    <div class="card" id="fTableCard">
      <div class="tw" style="max-height:640px"><table id="ftbl"><thead></thead><tbody></tbody></table></div>
    </div>
    <div class="grid" id="grid" hidden></div>
  </section>

  <section id="tab-pipeline" hidden>
    <div class="card" id="pvSummary" style="margin-bottom:14px" hidden></div>
    <div class="toolbar">
      <div class="ac" id="acP"></div>
      <button class="btn" id="pclr">Clear SKU</button>
      <div class="lightbox">
        <span><i class="lamp" style="background:var(--ok)"></i>matches expected count</span>
        <span><i class="lamp" style="background:var(--warn)"></i>warnings</span>
        <span><i class="lamp" style="background:var(--bad)"></i>count mismatch</span>
        <span><i class="lamp" style="background:var(--none)"></i>no expected count on record</span>
      </div>
    </div>
    <div class="two" id="pgrid">
      <div class="stack">
        <div class="card canvas"><div id="pSvg"></div></div>
        <div class="card" id="pPanel"></div>
      </div>
      <aside class="card sticky" id="pDock" hidden></aside>
    </div>
  </section>
</div>
<div id="tip"></div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = (v, d=3) => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits:d});
const pct = v => v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
const COLOR = {ma3:'var(--m-ma3)', tsb:'var(--m-tsb)', xgb_ma3_avg:'var(--m-xgb)', provisional:'var(--m-prov)'};
const mlabel = m => (D.model_label[m] || [m])[0];
const mnote = m => (D.model_label[m] || [,''])[1];
const PROV = s => s.status === 'insufficient_data';
const NT = 'not testable (<3 months)';
const modelPill = m => `<span class="pill"><i style="background:${COLOR[m]}"></i>${esc(mlabel(m))}</span>`;
const fcMonth = D.meta.forecast_date ? D.meta.forecast_date.slice(0, 7) : 'next';
const absGap = s => s.gap == null ? null : Math.abs(s.gap);
const LONG_NOTE = 'All 72 long forecasts change in preview: the global XGBoost model learns across SKUs, so extra history for 40 SKUs shifts every long forecast.';
const MODEL_KEYS = Object.keys(D.model_label);

// ---------------- mode: every view reads V, never D.skus directly ----------------
let V;
function count(rows, key, order){ const c = {}; (order || []).forEach(k => c[k] = 0); rows.forEach(s => c[s[key]] = (c[s[key]] || 0) + 1); return c; }
function buildView(mode){
  const pv = mode === 'preview';
  const skus = pv ? D.skus.map(s => ({...s, real_served: s.served, ...D.preview.skus[s.pk], mode})) : D.skus.map(s => ({...s, real_bin: s.router_bin, ph: null, ph_count: 0, mode}));
  return {
    mode, pv, skus, byPk: new Map(skus.map(s => [s.pk, s])),
    periods: pv ? D.preview.periods : D.periods,
    expected: pv ? D.preview.expected : D.expected,
    counts: {combined: count(skus, 'combined', D.combined_order), router: count(skus, 'router_bin', D.router_order),
             real_router: count(skus, 'real_bin', D.router_order), model: count(skus, 'method', MODEL_KEYS),
             backup: count(skus, 'backup', D.backup_order)},
  };
}
function setMode(mode){
  V = buildView(mode);
  seg($('#modeSeg'), [['real', 'Real only'], ['preview', 'Preview: with 2021–22 placeholder']], () => V.mode, setMode, true);
  $('#pvbanner').hidden = !V.pv;
  document.body.dataset.mode = mode;
  $('#noteText').innerHTML = V.pv
    ? `Preview reads <b>router_preview_synth.csv</b>, <b>series_synth.csv</b> and <b>preview_summary.csv</b> (copied to tools/dsd_dev_viewer/data/). Bins, served forecasts, served MASE / WAPE and MA3's MASE / WAPE on the same holdout are shown exactly as the preview file gives them; nothing is refitted or rescaled here. <b>Cohort result (real data):</b> TSB and the XGBoost + MA3 average tie MA3.`
    : `Every number is read from what the pipeline stored (forecast_result, sku_segment, sku_traits, unilever_sku_demand_fact_real). Nothing is refitted. <b>Cohort result:</b> TSB and the XGBoost + MA3 average tie MA3 on real Tier A data (half-year block tests). They are served because they are trained models that use the full history, not because they are more accurate. MA3 is the benchmark and the fallback. Per-SKU pages show that SKU's own MASE and WAPE only.`;
  filter = null;
  buildPN();
  drawKpis(); initSegs();
  showTab(tab);
}
function drawKpis(){
  const scored = V.skus.filter(s => s.status === 'ok');
  $('#kpis').innerHTML = [
    [V.skus.length, 'Tier A SKUs (as of 2026-02)'],
    [scored.length, 'Routed to a model'],
    [V.counts.model.provisional, 'Provisional (<3 months)'],
    [V.counts.model.tsb + V.counts.model.xgb_ma3_avg, 'Served by a challenger'],
    [scored.filter(s => s.mase != null && s.mase >= 1).length, 'SKUs with MASE ≥ 1'],
    ...(V.pv ? [[V.skus.filter(s => s.ph_count > 0).length, 'SKUs with placeholder months']] : [[V.counts.backup.fired, 'MA3 backup fired']]),
  ].map(([v, l]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
}
$('#meta').innerHTML = `${esc(D.meta.cohort)}<br>forecast month ${esc(fcMonth)} · built ${esc(D.meta.generated.replace('T', ' '))}`
  + (D.meta.problems.length ? ` · <b>${D.meta.problems.length} data problems</b>` : '');

function metricCell(s, k){
  if (PROV(s)) return `<td class="num muted">${NT}</td>`;
  const v = s[k], f = (k === 'mase' || k === 'ma3_mase') && v != null && v >= 1;
  return `<td class="num${f ? ' flag' : ''}"${f ? ' title="MASE ≥ 1: worse than the in-sample naive scale on this holdout"' : ''}>${fmt(v)}</td>`;
}
function backupOptions(s){
  const bo = D.backup_options;
  const list = bo && (bo[s.router_bin] || (bo.bins && bo.bins[s.router_bin]));
  if (!Array.isArray(list)) return '<span class="ph">pending decision</span>';
  return `${esc(list.join(', '))} <span class="muted">(${esc(s.router_bin)} bin)</span>`;
}

// ---------------- chart ----------------
const GEOM = {};
function chart(s, W, H, mode){
  const P = V.periods.concat([fcMonth]), n = P.length, big = mode === 'big', spark = mode === 'spark';
  const cand = s.monthly.concat(spark ? [s.served] : [s.served, s.ma3, s.hi, s.lo]).filter(v => v != null);
  const ymax = Math.max(1, ...cand) * 1.08, ymin = Math.min(0, ...cand);
  const L = big ? 56 : spark ? 2 : 6, R = spark ? 5 : big ? 18 : 12, T = spark ? 3 : 8, B = spark ? 3 : big ? 26 : 16;
  const X = i => L + i * (W - L - R) / (n - 1), Y = v => T + (H - T - B) * (1 - (v - ymin) / (ymax - ymin));
  const id = mode + s.pk + V.mode;
  GEOM[id] = {L, R, W, n};
  const isPh = i => s.ph && i >= s.ph[0] && i <= s.ph[1];
  let g = `<svg viewBox="0 0 ${W} ${H}" width="${spark ? W : ''}" height="${spark ? H : ''}" data-pk="${s.pk}" data-g="${id}" data-ph="${s.ph_count || 0}" role="img" aria-label="${esc(s.code)} monthly demand and forecast">`;
  if (s.ph) g += `<rect class="phband" x="${X(s.ph[0] - .5)}" y="${T}" width="${X(s.ph[1] + .5) - X(s.ph[0] - .5)}" height="${H - T - B}" fill="url(#phpat)"/>`
    + (big ? `<text x="${X(s.ph[0] - .5) + 4}" y="${T + 11}" fill="var(--ph)" font-size="10">placeholder (not SSM data)</text>` : '');
  if (!spark){
    if (big && s.holdout) g += `<rect x="${X(s.holdout[0] - .5)}" y="${T}" width="${X(s.holdout[1] + .5) - X(s.holdout[0] - .5)}" height="${H - T - B}" fill="var(--accent)" opacity=".10"/>`
      + `<text x="${X(s.holdout[0] - .5) + 4}" y="${T + 11}" fill="var(--accent)" font-size="10" opacity=".9">holdout</text>`;
    const ticks = big ? [0, 1, 2, 3, 4].map(t => ymin + (ymax - ymin) * t / 4) : [ymin, ymax / 1.08];
    ticks.forEach(v => {
      g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/>`;
      if (big) g += `<text x="${L - 6}" y="${Y(v) + 3}" text-anchor="end" fill="var(--ink-3)" font-size="10">${fmt(v, 0)}</text>`;
    });
    if (ymin < 0) g += `<line x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--line-2)"/>`;
    g += `<rect x="${X(n - 1.5)}" y="${T}" width="${X(n - 1) - X(n - 1.5) + R}" height="${H - T - B}" fill="var(--surface-3)" opacity=".45"/>`;
    const labels = big ? P.map((_, i) => i).filter(i => (i % 6 === 0 && i < n - 4) || i === n - 1) : [0, n - 1];
    labels.forEach(i => g += `<text x="${X(i)}" y="${H - (big ? 8 : 3)}" text-anchor="${big ? 'middle' : (i ? 'end' : 'start')}" fill="var(--ink-3)" font-size="${big ? 10 : 9}">${P[i]}</text>`);
  }
  // actual: a segment only between two consecutive months that both have a row AND are the same kind
  // (real vs placeholder). Placeholder months are dashed in their own colour, never styled as demand.
  const paths = {real: '', ph: ''};
  s.monthly.forEach((v, i) => {
    if (v == null) return;
    const kind = isPh(i) ? 'ph' : 'real';
    const prev = i > 0 ? s.monthly[i - 1] : null, next = i < s.monthly.length - 1 ? s.monthly[i + 1] : null;
    const joined = prev != null && (isPh(i - 1) ? 'ph' : 'real') === kind;
    const joinsNext = next != null && (isPh(i + 1) ? 'ph' : 'real') === kind;
    paths[kind] += (joined ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1);
    if (!joined && !joinsNext && !spark) g += `<circle cx="${X(i)}" cy="${Y(v)}" r="2.5" fill="${kind === 'ph' ? 'none' : 'var(--actual)'}" stroke="${kind === 'ph' ? 'var(--ph)' : 'none'}"/>`;
  });
  if (paths.ph) g += `<path class="phline" d="${paths.ph}" fill="none" stroke="var(--ph)" stroke-width="${big ? 1.8 : 1.3}" stroke-dasharray="5 4" stroke-linejoin="round"/>`;
  g += `<path d="${paths.real}" fill="none" stroke="var(--actual)" stroke-width="${big ? 2 : 1.5}" stroke-linejoin="round" stroke-linecap="round"/>`;
  if (!spark && s.first_i != null) for (let i = s.first_i; i <= s.last_i; i++)
    if (s.monthly[i] == null){
      const nul = (s.null_months || []).includes(i), r = big ? 3.5 : 2.5, y0 = Y(Math.max(0, ymin));
      g += nul ? `<rect class="nullq" x="${X(i) - r}" y="${y0 - r}" width="${2 * r}" height="${2 * r}" fill="var(--surface-1)" stroke="var(--warn)" stroke-width="1.5"><title>${P[i]}: NULL quantity (pipeline counts it as 0)</title></rect>`
        : `<circle cx="${X(i)}" cy="${y0}" r="${r}" fill="var(--surface-1)" stroke="var(--ink-3)" stroke-width="1.5"><title>${P[i]}: no row</title></circle>`;
    }
  const fx = X(n - 1), c = COLOR[s.method];
  if (!spark && s.lo != null && s.hi != null) g += `<rect x="${fx - 4}" y="${Y(s.hi)}" width="8" height="${Math.max(1, Y(Math.max(ymin, s.lo)) - Y(s.hi))}" rx="4" fill="${c}" opacity=".28"/>`;
  const last = s.monthly[n - 2];
  if (s.served != null && last != null) g += `<line x1="${X(n - 2)}" y1="${Y(last)}" x2="${fx}" y2="${Y(s.served)}" stroke="${c}" stroke-width="1.5" stroke-dasharray="3 3"/>`;
  if (!spark && s.ma3 != null && s.method !== 'ma3') g += `<circle cx="${fx}" cy="${Y(s.ma3)}" r="${big ? 5.5 : 4}" fill="none" stroke="var(--m-ma3)" stroke-width="2"/>`;
  if (s.served != null) g += `<circle cx="${fx}" cy="${Y(s.served)}" r="${big ? 6 : spark ? 2.8 : 4}" fill="${c}" stroke="var(--surface-1)" stroke-width="${spark ? 1 : 2}"/>`;
  if (!spark) g += `<line class="xh" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/><rect x="${L}" y="0" width="${W - L}" height="${H}" fill="transparent"/>`;
  return g + '</svg>';
}
document.body.insertAdjacentHTML('beforeend', `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><pattern id="phpat" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="rgba(201,162,39,.06)"/><line x1="0" y1="0" x2="0" y2="6" stroke="rgba(201,162,39,.30)" stroke-width="2"/></pattern></defs></svg>`);
const tip = $('#tip');
document.addEventListener('mousemove', ev => {
  const svg = ev.target.closest && ev.target.closest('.chart svg');
  $$('.xh[visibility="visible"]').forEach(l => { if (!svg || !svg.contains(l)) l.setAttribute('visibility', 'hidden'); });
  if (!svg || !GEOM[svg.dataset.g]){ tip.style.display = 'none'; return; }
  const s = V.byPk.get(+svg.dataset.pk), gm = GEOM[svg.dataset.g];
  const box = svg.getBoundingClientRect(), vx = (ev.clientX - box.left) * gm.W / box.width;
  const step = (gm.W - gm.L - gm.R) / (gm.n - 1), i = Math.max(0, Math.min(gm.n - 1, Math.round((vx - gm.L) / step)));
  const xh = svg.querySelector('.xh'); xh.setAttribute('x1', gm.L + i * step); xh.setAttribute('x2', gm.L + i * step); xh.setAttribute('visibility', 'visible');
  let rows;
  if (i === gm.n - 1){
    rows = [[`Served · ${mlabel(s.method)}`, fmt(s.served)], ['MA3', fmt(s.ma3)]];
    if (s.lo != null) rows.push(['Band', `${fmt(s.lo, 0)} – ${fmt(s.hi, 0)}`]);
    if (V.pv) rows.push(['Change vs real', pct(s.change)]);
  } else {
    const v = s.monthly[i], ph = s.ph && i >= s.ph[0] && i <= s.ph[1];
    rows = [[ph ? 'Placeholder' : 'Actual', v == null ? ((s.null_months || []).includes(i) ? 'NULL quantity (pipeline counts it as 0)' : 'no row') : fmt(v, 1)]];
    if (ph) rows.push(['', 'not SSM data']);
    if (s.holdout && i >= s.holdout[0] && i <= s.holdout[1]) rows.push(['', 'holdout month']);
  }
  tip.innerHTML = `<div class="h">${esc(s.code)} · ${i === gm.n - 1 ? fcMonth + ' (forecast)' : V.periods[i]}</div>`
    + rows.map(([k, v]) => `<div class="r"><span>${esc(k)}</span><b>${v}</b></div>`).join('');
  tip.style.display = 'block';
  tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 8, ev.clientX + 14) + 'px';
  tip.style.top = Math.max(8, ev.clientY - tip.offsetHeight - 12) + 'px';
});
const LEGEND = s => `<div class="legend"><span><i class="sw-line" style="background:var(--actual)"></i>Actual (real)</span>`
  + (s.ph ? `<span><i class="sw-ph"></i><i class="sw-phbg"></i>Placeholder months (not SSM data)</span>` : '')
  + `<span><i class="sw-hollow"></i>No row</span>`
  + ((s.null_months || []).length ? `<span><i class="sw-null"></i>NULL quantity (pipeline counts it as 0)</span>` : '')
  + `<span><i class="sw-dot" style="background:${COLOR[s.method]}"></i>Served · ${esc(mlabel(s.method))}</span>`
  + (s.method !== 'ma3' ? `<span><i class="sw-ring" style="border-color:var(--m-ma3)"></i>MA3</span>` : '')
  + (s.lo != null ? `<span><i class="sw-band" style="background:${COLOR[s.method]}"></i>Band</span>` : '')
  + (s.holdout ? `<span><i class="sw-hold"></i>Holdout months</span>` : '') + `</div>`;
function statTiles(s){
  const p = PROV(s);
  return `<div class="stats">` + [
    [fmt(s.served), `Served forecast${s.provisional ? ' (provisional)' : ''}`], [fmt(s.ma3), 'MA3 forecast'],
    [pct(s.gap), 'Served vs MA3'],
    ...(V.pv ? [[pct(s.change), 'Served change vs real']] : [[s.lo == null ? '—' : `${fmt(s.lo, 0)}–${fmt(s.hi, 0)}`, 'Band']]),
    [p ? NT : fmt(s.mase), 'MASE (served, holdout)', !p && s.mase >= 1],
    [p ? NT : fmt(s.ma3_mase), 'MA3 MASE (same holdout)', !p && s.ma3_mase >= 1],
    [p ? NT : fmt(s.wape), 'WAPE (served, holdout)'],
    [p ? NT : fmt(s.ma3_wape), 'MA3 WAPE (same holdout)'], [fmt(s.rlr), 'Recent level ratio (3 / 12 mo)'],
  ].map(([v, l, f]) => `<div class="stat${f ? ' flag' : ''}" title="${esc(v)}"><div class="v">${esc(v)}</div><div class="l">${l}</div></div>`).join('') + `</div>`;
}
const kv = o => '<dl class="kv">' + o.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('') + '</dl>';
const skuNotes = s => V.pv ? (s.ph_count ? `<div class="pvnote">${s.ph_count} placeholder months (2021–22) prepended. They are not SSM's sales.</div>` : '')
  + (s.router_bin === 'long' ? `<div class="pvnote">${esc(LONG_NOTE)} Served change vs real: <b>${pct(s.change)}</b>.</div>` : '') : '';
function detailHTML(s, W){
  if (!s) return '<div class="empty">Select a SKU.</div>';
  return `<div class="dhead"><div class="code">${esc(s.code)}</div><div class="nm">${esc(s.name)}</div>`
    + `<div class="tags">${modelPill(s.method)}<span class="pill">router: ${esc(s.router_bin)}</span>${V.pv ? `<span class="pill">real bin: ${esc(s.real_bin)}</span>` : ''}<span class="pill">combined_v1: ${esc(s.combined)}</span></div></div>`
    + skuNotes(s)
    + `<div class="chart">${chart(s, W || 420, 230, 'big')}</div>` + LEGEND(s) + statTiles(s)
    + `<details open><summary>Routing</summary>` + kv([
      ['status', esc(s.status)],
      ['router bin', esc(s.router_bin) + (s.sales_months != null ? ` (${s.sales_months} sales months${V.pv ? ', incl. placeholder' : ''})` : '')],
      ['holdout months', s.holdout ? `${s.holdout_months} (${V.periods[s.holdout[0]]} – ${V.periods[s.holdout[1]]})` : '—'],
      ['components', esc(s.components ? JSON.stringify(s.components) : '—')],
      ['MA3 backup', esc(s.backup) + (s.backup_reason ? ` — ${esc(s.backup_reason)}` : '')],
      ['backup options', backupOptions(s)],
      ['bin_reason', esc(s.bin_reason)],
      ['other schemes', esc(Object.entries(s.schemes).filter(([k]) => k !== 'combined_v1').map(([k, v]) => `${k}=${v}`).join(', '))],
    ]) + `</details>`
    + `<details><summary>Traits (sku_traits, 2026-02, real data)</summary>` + kv(Object.entries(s.traits || {}).map(([k, v]) => [k, esc(v == null ? '—' : v)])) + `</details>`;
}

// ---------------- sortable table helper ----------------
function sortRows(rows, key, dir){
  return rows.slice().sort((a, b) => {
    const x = typeof key === 'function' ? key(a) : a[key], y = typeof key === 'function' ? key(b) : b[key];
    if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
    return (x > y ? 1 : x < y ? -1 : 0) * dir;
  });
}
function renderTable(el, cols, rows, st, onRow, selected){
  const head = '<tr>' + cols.map(c => `<th data-k="${c.k}"${c.num ? ' class="num"' : ''}${c.tip ? ` title="${esc(c.tip)}"` : ''}>${c.l}${st.k === c.k ? (st.d > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('') + '</tr>';
  const col = cols.find(c => c.k === st.k);
  const sorted = col && col.sort !== false ? sortRows(rows, col.v || col.k, st.d) : rows;
  el.querySelector('thead').innerHTML = head;
  el.querySelector('tbody').innerHTML = sorted.map(s => `<tr data-pk="${s.pk}"${s.pk === selected ? ' class="sel"' : ''}>` + cols.map(c => c.r(s)).join('') + '</tr>').join('');
  el.querySelectorAll('th').forEach(th => th.onclick = () => {
    const c = cols.find(x => x.k === th.dataset.k); if (c.sort === false) return;
    st.d = st.k === c.k ? -st.d : (c.num ? -1 : 1); st.k = c.k; renderTable(el, cols, rows, st, onRow, selected);
  });
  el.querySelectorAll('tbody tr').forEach(tr => tr.onclick = () => onRow(+tr.dataset.pk));
  return sorted;
}
const C = {
  code: {k:'code', l:'SKU', r: s => `<td>${esc(s.code)}</td>`},
  name: {k:'name', l:'Product', r: s => `<td class="name" title="${esc(s.name)}">${esc(s.name)}</td>`},
  method: {k:'method', l:'Served model', r: s => `<td>${modelPill(s.method)}</td>`},
  served: {k:'served', l:'Served forecast', num:1, r: s => `<td class="num">${fmt(s.served)}</td>`},
  ma3: {k:'ma3', l:'MA3 forecast', num:1, r: s => `<td class="num">${fmt(s.ma3)}</td>`},
  gap: {k:'gap', l:'Served vs MA3', num:1, v: absGap, tip:'(served − MA3) / MA3; sorts on the absolute gap', r: s => `<td class="num">${pct(s.gap)}</td>`},
  change: {k:'change', l:'Change vs real', num:1, v: s => s.change == null ? null : Math.abs(s.change), tip:'(preview served − real served) / real served; sorts on the absolute change', r: s => `<td class="num">${pct(s.change)}</td>`},
  ph: {k:'ph_count', l:'Placeholder months', num:1, r: s => `<td class="num${s.ph_count ? ' flag' : ''}">${s.ph_count}</td>`},
  mase: {k:'mase', l:'MASE', num:1, r: s => metricCell(s, 'mase')},
  ma3_mase: {k:'ma3_mase', l:'MA3 MASE (same holdout)', num:1, tip:'MA3 scored on the same rolling one-step holdout months as the served model', r: s => metricCell(s, 'ma3_mase')},
  wape: {k:'wape', l:'WAPE', num:1, r: s => metricCell(s, 'wape')},
  ma3_wape: {k:'ma3_wape', l:'MA3 WAPE', num:1, r: s => metricCell(s, 'ma3_wape')},
  rlr: {k:'rlr', l:'Recent level ratio', num:1, tip:'mean(last 3 months) / mean(last 12 months) of the modelling series; display only, no threshold', r: s => `<td class="num">${fmt(s.rlr)}</td>`},
  spark: {k:'spark', l:'Monthly demand', sort:false, r: s => `<td class="spark">${chart(s, 150, 30, 'spark')}</td>`},
};

// ---------------- tabs ----------------
let tab = 'forecasts';
function showTab(t){
  tab = t;
  $$('nav button').forEach(x => x.setAttribute('aria-selected', x.dataset.tab === t));
  ['forecasts', 'pipeline'].forEach(k => $('#tab-' + k).hidden = k !== t);
  $('.kpis').hidden = t === 'pipeline';
  if (t === 'forecasts') drawForecasts();
  if (t === 'pipeline') drawPipeline();
}
$$('nav button').forEach(b => b.onclick = () => showTab(b.dataset.tab));

// ================= SANKEY (Pipeline panel of the combined_v1 / router nodes) =================
function sankeyCols(){
  return [
    {key:'src', title:'COHORT', items:['Tier A']},
    {key:'combined', title:'COMBINED_V1 BIN', items:D.combined_order},
    ...(V.pv ? [{key:'realrouter', title:'ROUTER BIN (REAL)', items:D.router_order}] : []),
    {key:'router', title:V.pv ? 'ROUTER BIN (PREVIEW)' : 'ROUTER BIN (LIVE)', items:D.router_order},
    {key:'model', title:'SERVED MODEL', items:MODEL_KEYS},
    {key:'backup', title:'MA3 BACKUP', items:D.backup_order},
  ];
}
const SKU_KEY = {combined:'combined', realrouter:'real_bin', router:'router_bin', model:'method', backup:'backup'};
let filter = null;
function drawFlow(){
  const COLS = sankeyCols();
  const val = (s, col) => col === 'src' ? 'Tier A' : s[SKU_KEY[col]];
  const edgesM = {};
  V.skus.forEach(s => { for (let i = 0; i < COLS.length - 1; i++){ const k = `${COLS[i].key}:${val(s, COLS[i].key)}|${COLS[i + 1].key}:${val(s, COLS[i + 1].key)}`; edgesM[k] = (edgesM[k] || 0) + 1; } });
  const edges = Object.entries(edgesM).map(([k, n]) => ({from:k.split('|')[0], to:k.split('|')[1], n}));
  const nodeCount = (col, item) => col === 'src' ? V.skus.length : V.skus.filter(s => s[SKU_KEY[col]] === item).length;
  const W = 1000, nodeW = V.pv ? 132 : 150, gap = 10, top = 28, H0 = 430, total = V.skus.length;
  const k = (H0 - gap * (Math.max(...COLS.map(c => c.items.length)) - 1)) / total;
  const x = i => i * ((W - nodeW) / (COLS.length - 1));
  const pos = {};
  COLS.forEach((c, i) => {
    let y = top;
    c.items.forEach(it => {
      const n = nodeCount(c.key, it);
      if (!n && c.key !== 'backup') return;
      const h = n ? n * k : 26;
      pos[`${c.key}:${it}`] = {x:x(i), y, h, n, col:c.key, item:it, outs:[], ins:[]};
      y += h + gap;
    });
  });
  edges.forEach(e => { const a = pos[e.from], b = pos[e.to]; if (a && b){ a.outs.push(e); b.ins.push(e); } });
  const off = {};
  Object.values(pos).forEach(p => {
    let o = 0; p.outs.sort((u, v) => pos[u.to].y - pos[v.to].y).forEach(e => { off['o' + e.from + e.to] = o; o += e.n * k; });
    let i = 0; p.ins.sort((u, v) => pos[u.from].y - pos[v.from].y).forEach(e => { off['i' + e.from + e.to] = i; i += e.n * k; });
  });
  const H = Math.max(...Object.values(pos).map(p => p.y + p.h)) + 6;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Tier A routing flow">`;
  COLS.forEach((c, i) => s += `<text class="colh" x="${x(i) + 2}" y="14">${c.title}</text>`);
  edges.forEach(e => {
    const a = pos[e.from], b = pos[e.to]; if (!a || !b) return;
    const w = e.n * k, y1 = a.y + off['o' + e.from + e.to] + w / 2, y2 = b.y + off['i' + e.from + e.to] + w / 2;
    const x1 = a.x + nodeW, x2 = b.x, mx = (x1 + x2) / 2;
    const moved = a.col === 'realrouter' && b.col === 'router' && a.item !== b.item;
    const col = moved ? 'var(--ph)' : b.col === 'model' ? COLOR[b.item] : a.col === 'model' ? COLOR[a.item] : 'var(--ink-3)';
    const hi = filter && (e.from === filter || e.to === filter) ? ' hi' : '';
    s += `<path class="link${hi}" stroke="${col}" stroke-width="${Math.max(w - 1, 1)}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"><title>${esc(e.from.split(':')[1])} → ${esc(e.to.split(':')[1])}: ${e.n} SKUs</title></path>`;
  });
  Object.entries(pos).forEach(([key, p]) => {
    const isModel = p.col === 'model', sub = isModel ? mnote(p.item) : '';
    s += `<g class="node${filter === key ? ' sel' : ''}${p.n ? '' : ' empty'}" data-k="${esc(key)}">`
      + `<rect class="box" x="${p.x}" y="${p.y}" width="${nodeW}" height="${p.h}" rx="6"/>`
      + (isModel ? `<rect x="${p.x}" y="${p.y}" width="4" height="${p.h}" rx="2" fill="${COLOR[p.item]}"/>` : '')
      + `<text x="${p.x + 12}" y="${p.y + 17}">${esc(isModel ? mlabel(p.item) : p.item)}</text>`
      + `<text class="n" x="${p.x + nodeW - 10}" y="${p.y + 17}" text-anchor="end">${p.n}</text>`
      + (sub && p.h > 34 ? `<text class="s" x="${p.x + 12}" y="${p.y + 32}">${esc(sub)}</text>` : '') + `</g>`;
  });
  $('#flowSvg').innerHTML = s + '</svg>';
  $('#flowSvg').classList.toggle('filtered', !!filter);
  $$('#flowSvg .node').forEach(g => g.onclick = () => { filter = filter === g.dataset.k ? null : g.dataset.k; drawPanel(); });
}
function binMoves(){
  const moved = V.skus.filter(s => s.real_bin !== s.router_bin), pref = V.skus.filter(s => s.ph_count > 0);
  const m = {}; moved.forEach(s => { const k = `${s.real_bin} → ${s.router_bin}`; m[k] = (m[k] || 0) + 1; });
  const allLong = pref.length && pref.every(s => s.router_bin === 'long' && s.real_bin === 'long');
  return {n: moved.length, pairs: m, text: `${moved.length} bin moves (REAL bin → preview bin)` + (Object.keys(m).length ? ': ' + Object.entries(m).map(([k, v]) => `${k} ${v}`).join(', ') : '')
    + (moved.length === 0 && allLong ? ` — all ${pref.length} prefixed SKUs are already long` : '')};
}
const R_COLS = () => [C.code, C.name,
  {k:'combined', l:'combined_v1', r: s => `<td>${esc(s.combined)}</td>`},
  ...(V.pv ? [{k:'real_bin', l:'Router bin (real)', r: s => `<td>${esc(s.real_bin)}</td>`}] : []),
  {k:'router_bin', l:V.pv ? 'Router bin (preview)' : 'Router bin', r: s => `<td>${esc(s.router_bin)}</td>`},
  C.method, C.served, ...(V.pv ? [C.change] : []), C.ma3, C.mase, C.ma3_mase, C.wape, C.ma3_wape,
  {k:'status', l:'Status', r: s => `<td>${esc(s.status)}</td>`},
  {k:'backup', l:'MA3 backup', r: s => `<td class="muted">${esc(s.backup)}</td>`},
  {k:'_bo', l:'Backup options', sort:false, r: s => `<td>${backupOptions(s)}</td>`}];
const textMatch = (s, q) => { q = (q || '').trim().toLowerCase(); return !q || String(s.code).toLowerCase().includes(q) || String(s.name).toLowerCase().includes(q); };
const sankeyMatch = s => { if (!filter) return true; const i = filter.indexOf(':'), col = filter.slice(0, i), item = filter.slice(i + 1); return !SKU_KEY[col] || s[SKU_KEY[col]] === item; };

// ================= AUTOCOMPLETE =================
function autocomplete(host, placeholder, onPick){
  host.innerHTML = `<input class="search" placeholder="${esc(placeholder)}" autocomplete="off" role="combobox" aria-expanded="false"><ul role="listbox" hidden></ul>`;
  const inp = host.querySelector('input'), ul = host.querySelector('ul');
  let items = [], idx = 0;
  const paint = () => {
    ul.innerHTML = items.map((s, i) => `<li role="option" data-pk="${s.pk}" aria-selected="${i === idx}"><b>${esc(s.code)}</b><span>${esc(s.name)}</span></li>`).join('');
    ul.hidden = !items.length; inp.setAttribute('aria-expanded', !!items.length);
    ul.querySelectorAll('li').forEach(li => li.onmousedown = e => { e.preventDefault(); pick(+li.dataset.pk); });
  };
  const pick = pk => { const s = V.byPk.get(pk); inp.value = `${s.code} · ${s.name}`; items = []; paint(); onPick(pk); };
  inp.oninput = () => {
    const q = inp.value.trim().toLowerCase(); idx = 0;
    items = q ? V.skus.filter(s => String(s.code).toLowerCase().includes(q) || String(s.name).toLowerCase().includes(q))
      .sort((a, b) => (String(b.code).startsWith(q) - String(a.code).startsWith(q))).slice(0, 12) : [];
    paint();
  };
  inp.onkeydown = e => {
    if (!items.length) return;
    if (e.key === 'ArrowDown'){ idx = (idx + 1) % items.length; paint(); e.preventDefault(); }
    else if (e.key === 'ArrowUp'){ idx = (idx - 1 + items.length) % items.length; paint(); e.preventDefault(); }
    else if (e.key === 'Enter'){ pick(items[idx].pk); e.preventDefault(); }
    else if (e.key === 'Escape'){ items = []; paint(); }
  };
  inp.onblur = () => setTimeout(() => { items = []; paint(); }, 100);
  return {input: inp, clear: () => { inp.value = ''; items = []; paint(); }};
}

// ================= FORECASTS =================
let gBin = 'all', gModel = 'all', gView = 'table';
const fState = {k:'gap', d:-1};
let fSel = null, fOrder = [];
function seg(el, opts, get, set, noRedraw){
  el.innerHTML = opts.map(([v, l, c]) => `<button data-v="${v}" aria-pressed="${get() === v}">${c ? `<i style="background:${c}"></i>` : ''}${esc(l)}</button>`).join('');
  el.querySelectorAll('button').forEach(b => b.onclick = () => { if (get() === b.dataset.v) return; set(b.dataset.v); if (!noRedraw){ seg(el, opts, get, set); drawForecasts(); } });
}
function initSegs(){
  seg($('#binSeg'), [['all', 'All bins'], ...D.router_order.map(b => [b, `${b} · ${V.counts.router[b]}`])], () => gBin, v => gBin = v);
  seg($('#modelSeg'), [['all', 'All models'], ...MODEL_KEYS.map(m => [m, mlabel(m), COLOR[m]])], () => gModel, v => gModel = v);
  seg($('#viewSeg'), [['table', 'Table view'], ['grid', 'Grid view']], () => gView, v => gView = v);
}
const acF = autocomplete($('#acF'), 'Find a SKU by code or product…', pk => { fSel = pk; drawForecasts(); });
const F_COLS = () => [C.code, C.name, C.method, C.spark, C.served, C.ma3, C.gap, ...(V.pv ? [C.change, C.ph] : []), C.mase, C.ma3_mase, C.wape, C.rlr];
function drawFocus(){
  const s = V.byPk.get(fSel), i = fOrder.findIndex(x => x.pk === fSel);
  if (!s){ $('#focus').innerHTML = '<div class="empty">Select a SKU.</div>'; return; }
  $('#focus').innerHTML = `<div class="toolbar" style="margin-bottom:6px"><div class="dhead" style="margin:0"><div class="code">${esc(s.code)}</div><div class="nm">${esc(s.name)}</div></div>`
    + `<div class="tags" style="align-self:flex-start;margin-left:12px">${modelPill(s.method)}<span class="pill">router: ${esc(s.router_bin)}</span>${V.pv ? `<span class="pill">real bin: ${esc(s.real_bin)}</span>` : ''}<span class="pill">combined_v1: ${esc(s.combined)}</span><span class="pill">${esc(s.status)}</span></div>`
    + `<div class="focusnav"><span class="muted">${i >= 0 ? `${i + 1} of ${fOrder.length} in filter` : 'outside the current filter'}</span>`
    + `<button class="btn" id="fPrev" ${i <= 0 ? 'disabled' : ''}>← Prev</button><button class="btn" id="fNext" ${i < 0 || i >= fOrder.length - 1 ? 'disabled' : ''}>Next →</button></div></div>`
    + skuNotes(s)
    + `<div class="focus"><div><div class="chart">${chart(s, 1100, 300, 'big')}</div>${LEGEND(s)}</div>`
    + `<div class="backupbox"><b>Backup options${V.pv ? ` · preview bin: ${esc(s.router_bin)}` : ''}</b><div class="bo">${backupOptions(s)}</div><div style="margin-top:6px">Live fallback today: MA3. MA3 backup: ${esc(s.backup)}.</div></div></div>`
    + statTiles(s);
  if (i > 0) $('#fPrev').onclick = () => { fSel = fOrder[i - 1].pk; drawForecasts(); };
  if (i >= 0 && i < fOrder.length - 1) $('#fNext').onclick = () => { fSel = fOrder[i + 1].pk; drawForecasts(); };
}
function drawForecasts(){
  if (fSel == null) fSel = (sortRows(V.skus.filter(s => s.gap != null), absGap, -1)[0] || V.skus[0]).pk;
  const rows = V.skus.filter(s => (gBin === 'all' || s.router_bin === gBin) && (gModel === 'all' || s.method === gModel));
  $('#gcount').textContent = `${rows.length} of ${V.skus.length} SKUs`;
  $('#fTableCard').hidden = gView !== 'table'; $('#grid').hidden = gView !== 'grid';
  const onRow = pk => { fSel = pk; drawForecasts(); };
  const cols = F_COLS();
  if (!cols.find(c => c.k === fState.k)) { fState.k = 'gap'; fState.d = -1; }
  if (gView === 'table') fOrder = renderTable($('#ftbl'), cols, rows, fState, onRow, fSel);
  else {
    fOrder = sortRows(rows, (cols.find(c => c.k === fState.k) || C.gap).v || fState.k, fState.d);
    const nt = '<span class="muted" style="font-weight:400">not testable</span>';
    $('#grid').innerHTML = fOrder.map(s => `<div class="fc${s.pk === fSel ? ' sel' : ''}" data-pk="${s.pk}">`
      + `<div class="top"><div><div class="code">${esc(s.code)}</div><div class="nm" title="${esc(s.name)}">${esc(s.name)}</div></div>${modelPill(s.method)}</div>`
      + `<div class="chart">${chart(s, 300, 110, 'card')}</div>`
      + `<div class="foot"><div>${V.pv ? 'Change vs real' : 'Served'}<b>${V.pv ? pct(s.change) : fmt(s.served, 0)}</b></div>`
      + `<div>MASE<b${!PROV(s) && s.mase >= 1 ? ' style="color:var(--flag-ink)"' : ''}>${PROV(s) ? nt : fmt(s.mase)}</b></div>`
      + `<div>MA3 MASE<b${!PROV(s) && s.ma3_mase >= 1 ? ' style="color:var(--flag-ink)"' : ''}>${PROV(s) ? nt : fmt(s.ma3_mase)}</b></div></div></div>`).join('') || '<div class="empty">No SKUs match.</div>';
    $$('#grid .fc').forEach(c => c.onclick = () => onRow(+c.dataset.pk));
  }
  drawFocus();
}

// ================= PIPELINE =================
const eqMap = (got, exp) => Object.keys(exp).every(k => (got[k] || 0) === exp[k]) && Object.keys(got).every(k => k in exp || !got[k]);
const maseHigh = rows => rows.filter(s => s.mase != null && s.mase >= 1);
const ma3High = rows => rows.filter(s => s.ma3_mase != null && s.ma3_mase >= 1);
const maseLine = rows => { const n = rows.filter(s => s.mase != null).length; return `${maseHigh(rows).length} of ${n} MASE ≥ 1 (MA3: ${ma3High(rows).length} of ${n})`; };
function light(checks){
  if (checks.some(c => c.ok === false)) return 'bad';
  if (checks.some(c => c.warn)) return 'warn';
  if (checks.some(c => c.ok === true)) return 'ok';
  return 'none';
}
let PN = [];
function buildPN(){
  const E = V.expected, S = V.skus, scored = S.filter(s => s.status === 'ok');
  const rowsOut = S.reduce((a, s) => a + s.view_rows, 0);
  const negSkus = S.filter(s => s.neg_months > 0), gapSkus = S.filter(s => s.gap_months > 0);
  const P = V.pv ? D.preview : null;
  const src = V.pv ? 'from preview file' : '';
  PN = [
    {id:'demand', col:0, title:V.pv ? 'Preview series' : 'Real demand view', sub:V.pv ? 'series_synth.csv' : 'unilever_sku_demand_fact_real',
     io:V.pv ? [`in ${fmt(P.file_rows, 0)} rows`, `${fmt(P.placeholder_rows, 0)} placeholder · ${P.placeholder_skus} SKUs`] : [`in ${fmt(D.meta.view_rows, 0)} rows`, `out ${fmt(rowsOut, 0)} rows · ${S.length} SKUs`],
     checks:[{ok:null, text:V.pv ? `No expected row count on record (file: ${fmt(P.file_rows, 0)} rows)` : `No expected row count on record (view: ${fmt(D.meta.view_rows, 0)} rows, ${D.meta.view_skus} SKUs)`},
       ...(V.pv ? [{warn:true, text:`${fmt(P.placeholder_rows, 0)} placeholder rows (2021–22) across ${P.placeholder_skus} SKUs — not SSM data`}] : []),
       {warn:negSkus.length > 0, text:`${negSkus.length} Tier A SKUs have a negative month`},
       {warn:gapSkus.length > 0, text:`${gapSkus.length} Tier A SKUs have months with no row between their first and last row`}],
     rows:() => S, has:() => true,
     cols:[C.code, C.name, {k:'view_rows', l:V.pv ? 'Rows in file' : 'Rows in view', num:1, r:s => `<td class="num">${s.view_rows}</td>`}, ...(V.pv ? [C.ph] : []),
       {k:'first_i', l:'First row', r:s => `<td>${s.first_i == null ? '—' : V.periods[s.first_i]}</td>`},
       {k:'last_i', l:'Last row', r:s => `<td>${s.last_i == null ? '—' : V.periods[s.last_i]}</td>`},
       {k:'gap_months', l:'Months with no row', num:1, r:s => `<td class="num${s.gap_months ? ' flag' : ''}">${s.gap_months}</td>`},
       {k:'neg_months', l:'Negative months', num:1, r:s => `<td class="num${s.neg_months ? ' flag' : ''}">${s.neg_months}</td>`}, C.spark]},
    {id:'abc', col:1, title:'ABC Tier A', sub:'abc_classification · 2026-02 · single',
     io:[`in ${D.meta.abc_classified} SKUs`, `out ${S.length} Tier A`],
     checks:[{ok:S.length === E.tier_a, text:`Tier A = ${S.length} (expected ${E.tier_a}${V.pv ? ', rows in preview file' : ''})`},
       {ok:null, text:`All tiers: ${Object.entries(D.meta.abc_tiers).map(([k, v]) => `${k}=${v}`).join(', ')}`}],
     rows:() => S, has:() => true,
     cols:[C.code, C.name, {k:'rev', l:'Revenue share 2026-02', num:1, v:s => s.traits && s.traits.revenue_share, r:s => `<td class="num">${fmt(s.traits && s.traits.revenue_share, 5)}</td>`}, C.spark]},
    {id:'combined', col:2, title:'combined_v1 bins', sub:'sku_segment' + (V.pv ? ' (real, not re-binned)' : ''),
     io:[`in ${S.length}`, `out ${D.combined_order.map(b => V.counts.combined[b]).join('/')}`],
     checks:[{ok:eqMap(V.counts.combined, E.combined), text:`${D.combined_order.map(b => `${b} ${V.counts.combined[b]}`).join(', ')} (expected ${D.combined_order.map(b => E.combined[b]).join('/')})`},
       ...(V.pv ? [{ok:null, text:'combined_v1 is the real sku_segment scheme; the preview does not re-bin it.'}] : [])],
     rows:() => S, has:() => true, sankey:true,
     cols:() => { const r = R_COLS(); return [...r.slice(0, 3), {k:'bin_reason', l:'bin_reason', r:s => `<td class="name" style="max-width:320px" title="${esc(s.bin_reason)}">${esc(s.bin_reason)}</td>`}, ...r.slice(3)]; }},
    {id:'router', col:3, title:V.pv ? 'Router bins (preview)' : 'Router bins (live)', sub:V.pv ? 'router_preview_synth.csv · bin' : 'model_params.bin · length_v2',
     io:[`in ${S.length}`, `out ${D.router_order.map(b => V.counts.router[b]).join('/')}`],
     checks:[{ok:eqMap(V.counts.router, E.router), text:`${D.router_order.map(b => `${b} ${V.counts.router[b]}`).join(', ')} (expected ${D.router_order.map(b => E.router[b]).join('/')}${src ? ' ' + src : ''})`},
       ...(V.pv ? [{ok:null, text:binMoves().text}] : [])],
     rows:() => S, has:() => true, sankey:true,
     cols:() => { const r = R_COLS(); const i = V.pv ? 5 : 4; return [...r.slice(0, i), {k:'sales_months', l:'Sales months', num:1, r:s => `<td class="num">${fmt(s.sales_months, 0)}</td>`}, ...r.slice(i)]; }},
    ...MODEL_KEYS.map((m, i) => {
      const mine = S.filter(s => s.method === m), sc = mine.filter(s => s.mase != null), hi = maseHigh(sc);
      const bin = {ma3:'short', tsb:'medium', xgb_ma3_avg:'long', provisional:'insufficient'}[m];
      return {id:'model:' + m, col:4, row:i, model:m, title:mlabel(m), sub:mnote(m),
        mline: m === 'provisional' ? null : `MASE≥1 ${hi.length}/${sc.length} · MA3 ${ma3High(sc).length}/${sc.length}`,
        io:[`in ${V.counts.router[bin]} (${bin})`, `out ${mine.length}`],
        checks:[{ok:mine.length === E.model[m], text:`${mine.length} SKUs (expected ${E.model[m]}${src ? ' ' + src : ''})`},
          ...(m === 'provisional' ? [] : [{warn:hi.length > 0, text:maseLine(mine)}]),
          ...(V.pv && m === 'xgb_ma3_avg' ? [{ok:null, text:`${LONG_NOTE} ${mine.filter(s => s.change != null && Math.abs(s.change) > 0).length} of ${mine.length} changed.`}] : [])],
        rows:() => mine, has:s => s.method === m,
        cols:[C.code, C.name, C.served, ...(V.pv ? [C.change] : []), C.ma3, C.gap, C.mase, C.ma3_mase, C.wape]};
    }),
    {id:'holdout', col:5, title:'Holdout evaluation', sub:V.pv ? 'as given in the preview file' : 'rolling one-step, served model',
     io:[`in ${scored.length} routed`, `out ${scored.filter(s => s.mase != null).length} scored`],
     checks:[{ok:scored.length === E.router.short + E.router.medium + E.router.long, text:`${scored.length} routed SKUs (expected ${E.router.short + E.router.medium + E.router.long} = short + medium + long)`},
       {ok:scored.every(s => s.mase != null), text:`${scored.filter(s => s.mase == null).length} routed SKUs without a MASE`},
       {warn:maseHigh(scored).length > 0, text:maseLine(scored)}],
     rows:() => scored, has:s => s.status === 'ok',
     cols:[C.code, C.name, C.method, {k:'holdout_months', l:'Holdout months', num:1, r:s => `<td class="num">${fmt(s.holdout_months, 0)}</td>`}, C.mase,
 C.ma3_mase, C.wape, C.ma3_wape]},
    {id:'fr', col:6, title:V.pv ? 'Preview forecasts' : 'forecast_result', sub:V.pv ? 'router_preview_synth.csv (not Forecast_Result)' : `forecast_date ${D.meta.forecast_date}`,
     io:[`in ${S.length}`, `out ${S.filter(s => s.status).length} rows`],
     checks:[{ok:S.filter(s => s.status).length === E.forecast_result, text:`${S.filter(s => s.status).length} rows (expected ${E.forecast_result}${src ? ' ' + src : ''})`},
       {ok:eqMap(V.counts.backup, E.backup), text:`MA3 backup: ${D.backup_order.map(b => `${b} ${V.counts.backup[b]}`).join(', ')} (expected ${D.backup_order.map(b => E.backup[b]).join('/')}${src ? ' ' + src : ''})`}],
     rows:() => S, has:() => true,
     cols:[C.code, C.name, {k:'status', l:'Status', r:s => `<td>${esc(s.status)}</td>`}, C.method, C.served, ...(V.pv ? [C.change] : []),
       {k:'lo', l:'Band low', num:1, r:s => `<td class="num">${fmt(s.lo)}</td>`}, {k:'hi', l:'Band high', num:1, r:s => `<td class="num">${fmt(s.hi)}</td>`},
       {k:'backup', l:'MA3 backup', r:s => `<td class="muted">${esc(s.backup)}</td>`}, {k:'_bo', l:'Backup options', sort:false, r:s => `<td>${backupOptions(s)}</td>`}]},
  ];
  PN.forEach(n => n.light = light(n.checks));
}
const LAMP = {ok:'var(--ok)', warn:'var(--warn)', bad:'var(--bad)', none:'var(--none)'};
let pSel = 'model:tsb', pSku = null;
const pStates = {};
function drawSummary(){
  const el = $('#pvSummary');
  el.hidden = !V.pv;
  if (!V.pv) return;
  const P = D.preview, bins = [...new Set(P.blocks.map(b => b.bin))];
  const bv = (arm, bin) => (P.blocks.find(b => b.arm === arm && b.bin === bin) || {}).value;
  const rb = [...new Set(P.moves.map(m => m.real))], sb = [...new Set(P.moves.map(m => m.synth))];
  const mv = (r, s) => (P.moves.find(m => m.real === r && m.synth === s) || {}).n;
  const bm = binMoves();
  el.innerHTML = `<h2>Preview summary</h2><div class="sub">From preview_summary.csv. Placeholder-backed numbers show what more history would change; they are not accuracy evidence.</div>`
    + `<div class="pvgrid"><div><b style="font-size:12px">Testable blocks per bin</b><table class="mini"><tr><th class="l">bin</th><th>REAL</th><th>Preview</th></tr>`
    + bins.map(b => `<tr><td class="l">${esc(b)}</td><td>${bv('REAL', b)}</td><td>${bv('SYNTH', b)}</td></tr>`).join('') + `</table>`
    + `<div class="muted" style="font-size:12px">REAL ${bins.map(b => bv('REAL', b)).join('/')} vs preview ${bins.map(b => bv('SYNTH', b)).join('/')}</div></div>`
    + `<div><b style="font-size:12px">Test-month bin moves (rows = REAL bin, columns = preview bin)</b><table class="mini"><tr><th class="l">REAL \\ preview</th>${sb.map(b => `<th>${esc(b)}</th>`).join('')}</tr>`
    + rb.map(r => `<tr><td class="l">${esc(r)}</td>${sb.map(s => `<td${r !== s && mv(r, s) ? ' style="color:var(--ph);font-weight:600"' : ''}>${fmt(mv(r, s), 0)}</td>`).join('')}</tr>`).join('') + `</table></div>`
    + `<div><b style="font-size:12px">At ${esc(fcMonth)} (the served forecast)</b><div class="pvnote">${esc(bm.text)}.</div><div class="pvnote">${esc(LONG_NOTE)}</div></div></div>`;
}
function drawPipeline(){
  drawSummary();
  const W = 1240, nw = 166, nh = 82, colX = c => 10 + c * ((W - nw - 20) / 6), mainY = 200;
  const pos = {};
  PN.forEach(n => { pos[n.id] = {x:colX(n.col), y:n.col === 4 ? 28 + n.row * (nh + 50) : mainY}; });
  const H = 28 + 4 * (nh + 50);
  const sku = pSku && V.byPk.get(pSku);
  const onPath = n => sku && n.has(sku);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Pipeline node graph">`;
  const wire = (a, b) => {
    const A = pos[a.id], B = pos[b.id], x1 = A.x + nw + 5, y1 = A.y + nh / 2, x2 = B.x - 5, y2 = B.y + nh / 2, mx = (x1 + x2) / 2;
    s += `<path class="wire${sku && onPath(a) && onPath(b) ? ' path' : ''}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
  };
  const byCol = c => PN.filter(n => n.col === c);
  for (let c = 0; c < 6; c++) byCol(c).forEach(a => byCol(c + 1).forEach(b => { if (!(a.model === 'provisional' && b.id === 'holdout')) wire(a, b); }));
  wire(PN.find(n => n.model === 'provisional'), PN.find(n => n.id === 'fr'));
  PN.forEach(n => {
    const {x, y} = pos[n.id];
    const cls = ['kn', pSel === n.id ? 'sel' : '', sku ? (onPath(n) ? 'path' : 'dim') : ''].join(' ');
    const trunc = (t, k) => t.length > k ? t.slice(0, k - 1) + '…' : t;
    s += `<g class="${cls}" data-id="${esc(n.id)}" tabindex="0">`
      + `<text class="t" x="${x + nw / 2}" y="${y - 8}" text-anchor="middle">${esc(n.title)}</text>`
      + `<rect class="body" x="${x}" y="${y}" width="${nw}" height="${nh}" rx="8"/>`
      + `<rect x="${x}" y="${y}" width="${nw}" height="5" rx="2" fill="${n.model ? COLOR[n.model] : V.pv ? 'var(--ph)' : 'var(--accent)'}" opacity=".85"/>`
      + `<path d="M${x - 6},${y + nh / 2 - 5} l6,5 l-6,5z" fill="var(--ink-3)"/><path d="M${x + nw},${y + nh / 2 - 5} l6,5 l-6,5z" fill="var(--ink-3)"/>`
      + `<text class="st" x="${x + 10}" y="${y + 22}">${esc(trunc(n.sub, 27))}</text>`
      + `<text class="io" x="${x + 10}" y="${y + 40}">${esc(trunc(n.io[0], 24))}</text>`
      + `<text class="io" x="${x + 10}" y="${y + 56}">${esc(trunc(n.io[1], 24))}</text>`
      + (n.mline ? `<text class="io" x="${x + 10}" y="${y + 72}" style="fill:var(--ink-2);font-size:10.5px">${esc(n.mline)}</text>` : '')
      + `<circle cx="${x + nw / 2}" cy="${y + nh + 12}" r="6" fill="${LAMP[n.light]}" stroke="var(--surface-1)" stroke-width="2"><title>${esc(n.light)}</title></circle>`
      + `<title>${esc(n.title)}: ${esc(n.io.join(' → '))}</title></g>`;
  });
  $('#pSvg').innerHTML = s + '</svg>';
  $$('#pSvg .kn').forEach(g => g.onclick = () => { pSel = g.dataset.id; drawPipeline(); });
  drawPanel(); drawDock();
}
function drawPanel(){
  const n = PN.find(x => x.id === pSel);
  const st = pStates[n.id] || (pStates[n.id] = {k:'code', d:1});
  const cols = typeof n.cols === 'function' ? n.cols() : n.cols;
  if (!cols.find(c => c.k === st.k)) { st.k = 'code'; st.d = 1; }
  $('#pPanel').innerHTML = `<div class="pnode"><i class="lamp" style="background:${LAMP[n.light]}"></i><h3>${esc(n.title)}</h3><span class="muted">${esc(n.sub)} · ${esc(n.io.join(' → '))}</span><span class="count" id="pcount"></span></div>`
    + `<ul class="checks">${n.checks.map(c => `<li>${c.ok === false ? '✗ ' : c.warn ? '⚠ ' : c.ok ? '✓ ' : ''}${esc(c.text)}</li>`).join('')}</ul>`
    + (n.sankey ? `<div style="color:var(--ink-3);font-size:12px;margin-bottom:6px">Tier A → combined_v1 bin → ${V.pv ? 'router bin (real) → router bin (preview)' : 'live router bin'} → served model → MA3 backup. Click a node to filter the table below.</div>`
      + (V.pv ? `<div class="pvnote" id="moveNote">${esc(binMoves().text)}</div>` : '')
      + `<div id="flowSvg" class="flowSvg" style="margin-bottom:12px;max-width:1000px"></div>`
      + `<div class="toolbar"><input class="search" id="q" placeholder="Search SKU code or product"><button class="btn" id="clr">Clear filter</button></div>` : '')
    + `<div class="tw" style="max-height:420px"><table id="ptbl"><thead></thead><tbody></tbody></table></div>`;
  const draw = () => {
    const rows = n.sankey ? n.rows().filter(s => sankeyMatch(s) && textMatch(s, $('#q').value)) : n.rows();
    renderTable($('#ptbl'), cols, rows, st, pk => selectPipelineSku(pk), pSku);
    $('#pcount').textContent = `${rows.length} of ${n.rows().length} rows` + (n.sankey && filter ? ` · ${filter.replace(':', ' = ')}` : '');
  };
  if (n.sankey){
    drawFlow();
    $('#q').oninput = draw;
    $('#clr').onclick = () => { filter = null; $('#q').value = ''; drawPanel(); };
  }
  draw();
}
function drawDock(){
  const s = pSku && V.byPk.get(pSku);
  $('#pDock').hidden = !s;
  $('#pgrid').style.gridTemplateColumns = s ? '' : '1fr';
  if (s) $('#pDock').innerHTML = detailHTML(s, 420);
}
const acP = autocomplete($('#acP'), 'Find a SKU to trace its path…', pk => selectPipelineSku(pk));
function selectPipelineSku(pk){ pSku = pk; drawPipeline(); }
$('#pclr').onclick = () => { pSku = null; acP.clear(); drawPipeline(); };

setMode('real');
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
