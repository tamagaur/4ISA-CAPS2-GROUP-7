"""
tools/routing_viewer/build.py — regenerate the Routing Viewer (dev tool).

Question it answers: does routing the forecast model by combined_v1 bin beat
always-MA3 on the Tier A (as of 2026-02, method 'single') Unilever cohort?

Read-only against the DB. Every model is refitted here from the series —
nothing is read from Forecast_Result, the bake-off CSVs or the other viewers.
Produces two files next to this script:
  routing_data.json   — the data payload
  routing_viewer.html — template.html with routing_data.json inlined;
                        self-contained, open it by double-clicking.

Method
------
  series   Unilever_SKU_Demand_Fact_Real, first sale -> 2026-02, zero-filled
  split    80/20 time-based per SKU (train = floor(0.8 n)); rolling-origin
           1-step-ahead, refit at every origin, forecasts clipped at 0
  floor    3 training months (MA3's own window)
  models   the 17 in scripts/model_bakeoff.py, incl. its ARIMA divergence guard
  metrics  analytics/forecasting/diagnostic_metrics.py (MASE scale: real train only)
  CI       bootstrap over SKUs within a bin, NBOOT resamples, fixed SEED
  bins     analytics/segmentation (traits + bins.combined_v1), derived fresh
           at 2026-02 and again from data through 2025-08 (stability)

--with-synthetic (DIAGNOSTIC ONLY): also reads the base unilever_sku_demand_fact
table for the cohort's is_demo=true months <= 2022-12 and prepends them as
TRAINING context only — test origins, actuals, MASE scale and bins stay real.
  arm A  calendar-true: the gap between 2022-12 and first real sale is zero-filled
  arm B  spliced: synthetic months butted directly against the real series
is_demo rows are frontend-validation-approved ONLY, never reported results
(CLAUDE.md rules 2 & 3). Same pattern as scripts/model_bakeoff.py --with-synthetic.

Usage (from the repo root, ~1 min; ~3 min with --with-synthetic):
    python tools/routing_viewer/build.py
    python tools/routing_viewer/build.py --with-synthetic
    python tools/routing_viewer/build.py --inline      # re-inline existing JSON, no DB
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

warnings.simplefilter("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)

ABC_PERIOD = "2026-02"
ABC_METHOD = "single"
REAL_START = "2023-01"
STABILITY_END = "2025-08"
MIN_TRAIN = 3
SEED, NBOOT = 20260921, 1000
ORDER = ["insufficient", "short", "medium", "long_down", "long_flat", "long_up"]
UNDERPOWERED = {"insufficient", "long_up"}
THIN_TEST_MONTHS = 3


# --------------------------------------------------------------------------- #
# DB (read-only)
# --------------------------------------------------------------------------- #
def load(with_synthetic: bool):
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO, ".env"))
    dsn = os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"]
    conn = psycopg2.connect(dsn, options="-c statement_timeout=0")
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")  # transaction-scoped READ ONLY, never session-level (pooler leak)
    cur.execute("""SELECT product_key FROM abc_classification
                   WHERE principal='unilever' AND classification_period=%s AND tier='A' AND method=%s""",
                (ABC_PERIOD, ABC_METHOD))
    cohort = sorted({r[0] for r in cur.fetchall()})
    cur.execute("""SELECT product_key, calendar_month, quantity_sold FROM unilever_sku_demand_fact_real
                   WHERE product_key = ANY(%s) ORDER BY 1, 2""", (cohort,))
    real = pd.DataFrame(cur.fetchall(), columns=["pk", "month", "q"])
    cur.execute("SELECT product_key, sku_code, product_name FROM product_dimension WHERE product_key = ANY(%s)", (cohort,))
    names = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    synth = None
    if with_synthetic:
        # base table, is_demo rows - DIAGNOSTIC path only
        cur.execute("""SELECT product_key, calendar_month, quantity_sold FROM unilever_sku_demand_fact
                       WHERE product_key = ANY(%s) AND is_demo AND calendar_month < %s ORDER BY 1, 2""",
                    (cohort, REAL_START))
        synth = pd.DataFrame(cur.fetchall(), columns=["pk", "month", "q"])
    conn.close()
    for df in (real, synth):
        if df is not None:
            df["q"] = pd.to_numeric(df["q"], errors="coerce").astype(float)
    return cohort, real, names, synth


def matrix(cohort, df, start, end):
    periods = [str(p) for p in pd.period_range(start, end, freq="M")]
    ix = {p: i for i, p in enumerate(periods)}
    m = {pk: np.zeros(len(periods)) for pk in cohort}
    for r in df.itertuples(index=False):
        i = ix.get(r.month)
        if i is not None and np.isfinite(r.q):
            m[r.pk][i] += r.q
    return m, periods


def derive_bins(m):
    from analytics.segmentation import bins as B, traits as T
    out = {}
    for pk, qty in m.items():
        hm = T.history_months(qty)
        tr, p, sl = T.trend_stats(qty)
        out[pk] = dict(bin=B.combined_v1(hm, tr, p, sl)[0], hm=hm, active=T.active_months(qty), trend=tr)
    return out


# --------------------------------------------------------------------------- #
# bake-off worker (top-level so the Windows process pool can import it)
# --------------------------------------------------------------------------- #
def run_sku(args):
    pk, qty, prefix, arm = args
    warnings.simplefilter("ignore")
    from scripts.model_bakeoff import GUARDED, MODELS
    from analytics.forecasting.diagnostic_metrics import mase, naive_scale, smape, wape
    from analytics.segmentation.traits import first_sale_index
    qty = np.asarray(qty, float)
    fs = first_sale_index(qty)
    x = qty[fs:] if fs is not None else qty[:0]
    n = len(x)
    ntr = int(np.floor(0.8 * n))
    nte = n - ntr
    if arm == "A" and len(prefix):
        prefix = np.concatenate([prefix, np.zeros(fs)])     # calendar-true: keep the pre-launch gap
    base = dict(pk=pk, arm=arm, n=n, ntr=ntr, nte=nte)
    if ntr < MIN_TRAIN or nte < 1:
        return [dict(base, model=m, fittable=False, guarded=0, wape=np.nan, smape=np.nan, mase=np.nan) for m in MODELS]
    actual, scale = x[ntr:], naive_scale(x[:ntr])
    rows = []
    for name, fn in MODELS.items():
        preds, guarded, fittable = [], 0, True
        for t in range(ntr, n):
            tr = np.concatenate([prefix, x[:t]])
            try:
                f = float(fn(tr))
            except Exception:
                f = np.nan
            if not np.isfinite(f):
                fittable = False
            elif name in GUARDED and f > tr.max():
                guarded += 1              # divergent fit - counted, never scored
                f = np.nan
            preds.append(f)
        preds = np.array(preds, float)
        if np.isfinite(preds).all():
            p = np.maximum(preds, 0.0)
            r = dict(wape=wape(actual, p), smape=smape(actual, p), mase=mase(actual, p, scale))
        else:
            r = dict(wape=np.nan, smape=np.nan, mase=np.nan)
        rows.append(dict(base, model=name, fittable=fittable, guarded=guarded, **r))
    return rows


# --------------------------------------------------------------------------- #
# summaries
# --------------------------------------------------------------------------- #
def _f(v, nd=4):
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


def summarize_arm(df, binof, models):
    """Per-bin tables, verdicts and routing for one arm. `df` = that arm's rows."""
    W = df.pivot(index="pk", columns="model", values="wape")[models]
    S = df.pivot(index="pk", columns="model", values="smape")[models]
    M = df.pivot(index="pk", columns="model", values="mase")[models]
    sk = df.drop_duplicates("pk").set_index("pk")
    fit = df.pivot_table(index="model", columns="pk", values="fittable", aggfunc="first")
    rng = np.random.default_rng(SEED)
    perbin, verdict, keep, winners, decisive = {}, {}, {}, {}, {}
    for b in ORDER:
        pks = binof[binof == b].index.to_numpy()
        evaluable = int(((sk.loc[pks, "ntr"] >= MIN_TRAIN) & (sk.loc[pks, "nte"] >= 1)).sum())
        fitn = {m: int(fit.loc[m, pks].sum()) for m in models}
        keep[b] = [m for m in models if fitn[m] * 2 >= len(pks)]
        rows = []
        if evaluable:
            idx = rng.integers(0, len(pks), size=(NBOOT, len(pks)))
            boot = {}
            for m in models:
                w = W.loc[pks, m].to_numpy()
                row = dict(model=m, fittable=fitn[m], dropped=m not in keep[b], n=int(np.isfinite(w).sum()))
                if m in keep[b] and row["n"]:
                    with np.errstate(all="ignore"):
                        boot[m] = np.nanmedian(w[idx], axis=1)
                    lo, hi = np.nanpercentile(boot[m], [2.5, 97.5])
                    row.update(wape=_f(np.nanmedian(w)), smape=_f(np.nanmedian(S.loc[pks, m])),
                               mase=_f(np.nanmedian(M.loc[pks, m])), lo=_f(lo), hi=_f(hi))
                rows.append(row)
            scored = sorted((r for r in rows if r.get("wape") is not None), key=lambda r: r["wape"])
            best, ma3 = scored[0], next(r for r in scored if r["model"] == "ma3")
            d = boot[best["model"]] - boot["ma3"]
            winners[b] = best["model"]
            decisive[b] = best["model"] != "ma3" and best["hi"] < ma3["lo"]
            tag = ("UNDERPOWERED" if b in UNDERPOWERED else "MA3 IS BEST" if best["model"] == "ma3"
                   else "DECISIVE" if decisive[b] else "NOT DECISIVE")
            verdict[b] = dict(best=best["model"], best_wape=best["wape"], best_lo=best["lo"], best_hi=best["hi"],
                              ma3_wape=ma3["wape"], ma3_lo=ma3["lo"], ma3_hi=ma3["hi"],
                              diff_lo=_f(np.nanpercentile(d, 2.5)), diff_hi=_f(np.nanpercentile(d, 97.5)), tag=tag)
        else:
            rows = [dict(model=m, fittable=fitn[m], dropped=True, n=0) for m in models]
            verdict[b] = dict(tag="NOT EVALUABLE")
        perbin[b] = rows

    ev = W.index[np.isfinite(W["ma3"])]
    return dict(W=W, ev=ev, perbin=perbin, verdict=verdict, keep=keep, winners=winners, decisive=decisive)


def routing(W, ev, base, binof, winners, decisive, keep):
    def route(pick):
        out = W.loc[ev, "ma3"].copy()
        for pk in ev:
            m = pick(pk)
            if m and np.isfinite(W.loc[pk, m]):
                out[pk] = W.loc[pk, m]
        return out

    def named(pk):
        b = binof[pk]
        return winners.get(b) if b not in UNDERPOWERED else None

    def loo(pk):
        b = binof[pk]
        if b in UNDERPOWERED or b not in winners:
            return None
        others = binof[(binof == b) & (binof.index != pk)].index
        return W.loc[others, keep[b]].median().idxmin()

    strat = [
        ("always-MA3", W.loc[ev, "ma3"]),
        ("per-bin winner", route(named)),
        ("winner where decisive, else MA3", route(lambda pk: named(pk) if decisive.get(binof[pk]) else None)),
        ("per-bin winner, leave-one-out selection", route(loo)),
        ("per-SKU oracle (ceiling)", W.loc[ev].min(axis=1)),
    ]
    rows = [dict(strategy=k, median=_f(s.median()), mean=_f(s.mean()),
                 improved=int((s < base - 1e-12).sum()), worsened=int((s > base + 1e-12).sum()),
                 nan=int(s.isna().sum())) for k, s in strat]
    return rows, strat[1][1]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def _inline():
    data_str = open(os.path.join(HERE, "routing_data.json"), encoding="utf-8").read()
    template = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    if "__ROUTING_DATA__" not in template:
        sys.exit("template.html is missing the __ROUTING_DATA__ placeholder")
    with open(os.path.join(HERE, "routing_viewer.html"), "w", encoding="utf-8") as fh:
        fh.write(template.replace("__ROUTING_DATA__", data_str.replace("</", "<\\/")))
    print("inlined routing_data.json into routing_viewer.html")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--with-synthetic", action="store_true", help="DIAGNOSTIC ONLY: add arms A/B with the is_demo 2021-22 prefix")
    ap.add_argument("--inline", action="store_true", help="re-inline the existing routing_data.json, no DB")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args()
    if args.inline:
        return _inline()

    from scripts.model_bakeoff import MODELS
    models = list(MODELS)
    cohort, real, names, synth = load(args.with_synthetic)
    null_q = int(real["q"].isna().sum())
    print(f"cohort={len(cohort)} real rows={len(real)} NULL/NaN qty={null_q} negative={int((real.q < 0).sum())}"
          + (f" synthetic prefix rows={len(synth)}" if synth is not None else ""))

    m26, periods = matrix(cohort, real, REAL_START, ABC_PERIOD)
    m25, _ = matrix(cohort, real, REAL_START, STABILITY_END)
    b26, b25 = derive_bins(m26), derive_bins(m25)
    binof = pd.Series({pk: v["bin"] for pk, v in b26.items()})
    print("combined_v1 @", ABC_PERIOD, {b: int((binof == b).sum()) for b in ORDER})

    arms = ["real"]
    prefixes = {"real": {}}
    if synth is not None:
        grid = [str(p) for p in pd.period_range("2021-01", "2022-12", freq="M")]
        sm, _ = matrix(cohort, synth, grid[0], grid[-1])
        first = synth.groupby("pk").month.min().map(grid.index)
        last = synth.groupby("pk").month.max().map(grid.index)
        prefixes["A"] = {pk: sm[pk][first[pk]:] for pk in first.index}
        prefixes["B"] = {pk: sm[pk][first[pk]:last[pk] + 1] for pk in first.index}
        arms += ["A", "B"]

    jobs = [(pk, m26[pk], prefixes[a].get(pk, np.zeros(0)), a) for a in arms for pk in cohort]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        res = list(ex.map(run_sku, jobs, chunksize=2))
    df = pd.DataFrame([r for rows in res for r in rows])
    n_inf = int(np.isinf(df[["wape", "smape", "mase"]]).sum().sum())
    print(f"bake-off rows={len(df)} (expected {len(arms) * len(cohort) * len(models)}) inf={n_inf}")

    out_arms, base = {}, None
    for a in arms:
        s = summarize_arm(df[df.arm == a], binof, models)
        if a == "real":
            base, real_sum = s["W"].loc[s["ev"], "ma3"], s
        rows, routed = routing(s["W"], real_sum["ev"], base, binof, s["winners"], s["decisive"], s["keep"])
        g = df[(df.arm == a) & df.model.isin(["sarima_plain", "sarima_seasonal"])].groupby("model").guarded
        out_arms[a] = dict(perbin=s["perbin"], verdict=s["verdict"], routing=rows,
                           guard={m: dict(origins=int(v.sum()), skus=int((v > 0).sum())) for m, v in g},
                           _routed=routed, _W=s["W"])

    sk = df[df.arm == "real"].drop_duplicates("pk").set_index("pk")
    bins_meta = []
    for b in ORDER:
        pks = binof[binof == b].index
        e = sk.loc[pks][(sk.loc[pks, "ntr"] >= MIN_TRAIN) & (sk.loc[pks, "nte"] >= 1)]
        bins_meta.append(dict(bin=b, n=len(pks), evaluable=len(e),
                              med_active=_f(sk.loc[pks, "n"].median(), 1),
                              med_train=_f(e.ntr.median(), 1) if len(e) else None,
                              med_test=_f(e.nte.median(), 1) if len(e) else None,
                              thin=bool(len(e) and e.nte.median() < THIN_TEST_MONTHS),
                              underpowered=b in UNDERPOWERED))

    t = pd.DataFrame({"b25": {pk: v["bin"] for pk, v in b25.items()}, "b26": binof})
    longs = {"long_down", "long_flat", "long_up"}
    ch = t[t.b25 != t.b26]
    stability = dict(
        from_period=STABILITY_END, to_period=ABC_PERIOD,
        matrix=pd.crosstab(t.b25, t.b26).reindex(index=ORDER, columns=ORDER, fill_value=0).values.tolist(),
        changed=len(ch), total=len(t), length_moves=int((~ch.b25.isin(longs)).sum()),
        trend_flips=int(ch.b25.isin(longs).sum()), long_at_from=int(t.b25.isin(longs).sum()),
        no_sales_at_from=sum(1 for v in b25.values() if v["hm"] == 0))

    Wr = out_arms["real"]["_W"]
    skus = []
    for pk in cohort:
        w = Wr.loc[pk]
        orc = w.idxmin() if w.notna().any() else None
        skus.append(dict(pk=int(pk), code=names.get(pk, (None, None))[0], name=names.get(pk, (None, None))[1],
                         bin=b26[pk]["bin"], bin_prev=b25[pk]["bin"], hm=b26[pk]["hm"], trend=b26[pk]["trend"],
                         ntr=int(sk.loc[pk, "ntr"]), nte=int(sk.loc[pk, "nte"]), ma3=_f(w["ma3"]),
                         routed=_f(out_arms["real"]["_routed"].get(pk, np.nan)),
                         oracle_model=orc, oracle=_f(w.min())))
    for a in out_arms.values():
        a.pop("_routed"), a.pop("_W")

    payload = dict(
        meta=dict(generated=datetime.datetime.now().isoformat(timespec="seconds"), cohort=f"Tier A as of {ABC_PERIOD}, method '{ABC_METHOD}'",
                  n_skus=len(cohort), real_rows=len(real), null_qty=null_q, span=f"{REAL_START}..{ABC_PERIOD}",
                  eval_skus=int(len(real_sum["ev"])), seed=SEED, nboot=NBOOT, min_train=MIN_TRAIN,
                  synthetic_rows=None if synth is None else len(synth), arms=arms),
        order=ORDER, models=models, bins=bins_meta, arms=out_arms, stability=stability, skus=skus)
    data_str = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    with open(os.path.join(HERE, "routing_data.json"), "w", encoding="utf-8") as fh:
        fh.write(data_str)
    _inline()
    for r in out_arms["real"]["routing"]:
        print(f"  {r['strategy']:<42}{r['median']:>7.3f}{r['mean']:>8.3f}{r['improved']:>5}{r['worsened']:>5}")


if __name__ == "__main__":
    main()
