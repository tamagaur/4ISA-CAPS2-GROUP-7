"""Target-transform experiment, 2026-09-26. PERSONAL EXPERIMENT: read-only, never adopted,
never pushed. Nothing here touches forecast_result, the router, DEC-28, backup_options.json
or the dev viewer.

Two harnesses, both reproduced from the code that produced the numbers on record:

  A  bake-off   final_fit.py / final_models.py rolling-origin forecasts on Tier A (as of
                2026-02), scored by cells_all.py's cells()/compare(): origin-level bins,
                full window 2023-10..2026-02 plus 5 half-year blocks, per-SKU WAPE
                two-condition test, MASE on the per-origin scale.
  B  common     fit_review_common.py (session scratchpad 0e0a1cac, not in git): the router's
                rolling one-step forecasts over 2025-09..2026-02, stored router bin per SKU,
                MASE on naive_scale of the real months before 2025-09.

Every candidate is inverse(model(transform(train))) with the transform fitted per SKU per
origin on training months only. Identity is the control and must reproduce the stored
predictions exactly before anything is scored.

Usage:
  python run_experiment.py --cache DIR --stage identity   # load, identity controls, round trip
  python run_experiment.py --cache DIR --stage full       # every column, scoring, CSVs
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

warnings.simplefilter("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
for _p in (REPO, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from transforms import (ROUNDTRIP_TOL, TRANSFORMS, TSB_TRANSFORMS, TransformFailed,  # noqa: E402
                        ma_forecast, ma_resid, roundtrip_check, ses_fit, tsb_sizes)

LAM_T = ("boxcox", "yeojohnson")
LAM_EPS = 1e-4                      # "at a bound" = within 1e-4 of -1 or 2 (the same cut the 2026-09-26 count used)


def rt_add(acc: dict, key: str, r) -> None:
    if r is None:
        return
    a = acc.setdefault(key, dict(abs=0.0, rel=0.0, n=0, fail=0))
    a["abs"], a["rel"] = max(a["abs"], r["abs"]), max(a["rel"], r["rel"])
    a["n"] += 1
    a["fail"] += int(r["fail"])


def rt_merge(acc: dict, other: dict) -> None:
    for k, v in other.items():
        a = acc.setdefault(k, dict(abs=0.0, rel=0.0, n=0, fail=0))
        a["abs"], a["rel"] = max(a["abs"], v["abs"]), max(a["rel"], v["rel"])
        a["n"] += v["n"]
        a["fail"] += v["fail"]

MAIN_ENV = r"C:\Users\kyuan\Capstone-Project\.env"      # read by absolute path; never copied, never printed
FIT_REVIEW = os.path.join(REPO, "reports", "diagnostics", "fit_review_common_2026-09-23.csv")
PREDS_PLUS = os.path.join(REPO, "reports", "experiment_artifacts", "preds_plus.csv.gz")

SEED, NBOOT, MIN_ORIG, MIN_N = 20260921, 1000, 3, 5            # cells_all.py:2
START, END, FULL0 = "2023-01", "2026-02", "2023-10"             # final_fit.py:11, final_models.py:11
MIN_TRAIN = 3                                                   # final_fit.py:10
BLOCKS = [("2023-10", "2024-02"), ("2024-03", "2024-08"), ("2024-09", "2025-02"),
          ("2025-03", "2025-08"), ("2025-09", "2026-02")]       # cells_all.py:9
WINDOW = [pd.Timestamp(f"{m}-01") for m in ("2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02")]
WINDOW_START = WINDOW[0]
UNFIT_MASE = 1.1                                                # reports/diagnostics/README.md
HOLDOUT_ONLY_UNFIT = (738, 913, 1280)
SERVED_COL = {"short": "ma3", "medium": "tsb", "long": "ens_xgb_ma3@A"}   # router.LIVE_MODEL in artifact columns
BINS = ("short", "medium", "long")
MODELS = ("ma3", "tsb", "comb_simple", "xgb_ma3_avg")
XGB_A = dict(max_depth=4, eta=0.05, subsample=0.8, colsample_bytree=0.8,
             objective="reg:absoluteerror", seed=SEED, nthread=8)   # final_models.py:81
XGB_ROUNDS, XGB_MIN_ROWS = 300, 100                                 # final_models.py:82,105
UNIT = list(range(10))                                              # final_models.py:71


def transforms_for(model: str) -> list:
    return TSB_TRANSFORMS if model == "tsb" else list(TRANSFORMS)


def col(model: str, tname: str) -> str:
    return f"{model}|{tname}"


COLUMNS = [(m, t) for m in MODELS for t in transforms_for(m)]


def family(tname: str) -> str:
    return TRANSFORMS[tname].family


# --------------------------------------------------------------------------- #
# load (one SELECT on the _Real view, read-only session)
# --------------------------------------------------------------------------- #
def load_demand(cache: str, keys: list) -> pd.DataFrame:
    path = os.path.join(cache, "demand_tierA_132.pkl")
    if os.path.exists(path):
        print(f"demand: cached {path}")
        return pd.read_pickle(path)
    import psycopg2
    from dotenv import dotenv_values
    env = dotenv_values(MAIN_ENV)
    last = None
    for var in ("SUPABASE_DIRECT_URL", "SUPABASE_DB_URL"):
        if not env.get(var):
            continue
        try:
            conn = psycopg2.connect(env[var], connect_timeout=20)
            break
        except Exception as exc:                      # message only, never the DSN
            last = f"{var}: {type(exc).__name__}"
    else:
        raise SystemExit(f"no database connection ({last})")
    conn.set_session(readonly=True)
    try:
        cur = conn.cursor()
        cur.execute("""SELECT product_key, calendar_month, quantity_sold
                       FROM unilever_sku_demand_fact_real
                       WHERE product_key = ANY(%s) ORDER BY 1, 2""", (sorted(int(k) for k in keys),))
        d = pd.DataFrame(cur.fetchall(), columns=["pk", "month", "q"])
        conn.rollback()
    finally:
        conn.close()
    d["pk"] = d.pk.astype(int)
    d["q"] = pd.to_numeric(d.q, errors="coerce").astype(float)
    d.to_pickle(path)
    return d


def demand_checks(d: pd.DataFrame) -> None:
    print(f"demand rows={len(d)} (expected 3087) SKUs={d.pk.nunique()} (expected 132) "
          f"NaN={int(d.q.isna().sum())} (expected 0) dup sku-months={int(d.duplicated(['pk', 'month']).sum())} (expected 0) "
          f"negative={int((d.q < 0).sum())} zero={int((d.q == 0).sum())} span={d.month.min()}..{d.month.max()}")


# --------------------------------------------------------------------------- #
# harness A: final_fit origins
# --------------------------------------------------------------------------- #
def bin_of(tr):                                       # final_fit.py:16-23
    sales = int((tr > 0).sum())
    if sales < 3:
        return "insufficient", sales, np.nan
    adi = len(tr) / sales
    if adi >= 1.32:
        return "intermittent", sales, adi
    return ("short" if sales < 12 else "medium" if sales < 24 else "long"), sales, adi


def build_a(d: pd.DataFrame, keys: list):
    periods = [str(p) for p in pd.period_range(START, END, freq="M")]
    ix = {p: i for i, p in enumerate(periods)}
    mats = {pk: np.zeros(len(periods)) for pk in sorted(keys)}
    for r in d.itertuples(index=False):
        i = ix.get(r.month)
        if i is not None and np.isfinite(r.q):
            mats[r.pk][i] += r.q
    series, meta = {}, []
    for pk in sorted(mats):
        qty = mats[pk]
        nz = np.nonzero(qty > 0)[0]
        if not len(nz):
            continue
        fs = int(nz[0])
        x = qty[fs:]
        series[pk] = (x, fs)
        for t in range(MIN_TRAIN, len(x)):
            tr = x[:t]
            b, sales, adi = bin_of(tr)
            dd = np.abs(np.diff(tr))
            meta.append(dict(pk=pk, ti=fs + t, ntr=t, sales=sales, adi=adi, bin=b,
                             scale=float(dd.mean()) if len(dd) else 0.0, actual=float(x[t]), month=periods[fs + t]))
    return series, pd.DataFrame(meta), periods, ix


def sku_worker(args):
    """Per-SKU models at every origin of one SKU, for the requested transforms.
    Components are clipped at 0 in original units (final_fit.py:51)."""
    pk, x, fs, origins, tnames = args
    warnings.simplefilter("ignore")
    rows, rt, fails = [], {}, {}
    for t, b in origins:
        tr = x[:t]
        row = {"pk": pk, "ti": fs + t}
        for tn in tnames:
            T = TRANSFORMS[tn]
            if T.pattern and b != "long":
                continue
            try:
                z, ctx = T.prepare(tr)
            except TransformFailed:
                fails[tn] = fails.get(tn, 0) + 1
                for base in ("ma3", "ma4", "ma12", "ses"):
                    row[col(base, tn)] = np.nan
                if tn in LAM_T:
                    row["lam|" + tn] = np.nan
                continue
            rt_add(rt, tn, roundtrip_check(T, tr, z, ctx))
            if tn in LAM_T:
                row["lam|" + tn] = ctx["lm"]
            for base, k in (("ma3", 3), ("ma4", 4), ("ma12", 12)):
                v = T.invert(ma_forecast(z, k), ctx, ma_resid(z, k) if T.smear else None)
                row[col(base, tn)] = max(0.0, v) if np.isfinite(v) else np.nan
            f, e = ses_fit(z)
            v = T.invert(f, ctx, e if T.smear else None) if np.isfinite(f) else np.nan
            row[col("ses", tn)] = max(0.0, v) if np.isfinite(v) else np.nan
        for tn in TSB_TRANSFORMS:
            if tn not in tnames:
                continue
            T = TRANSFORMS[tn]
            try:
                f, _ = tsb_sizes(tr, T)
            except TransformFailed:
                f = np.nan
                fails["tsb_" + tn] = fails.get("tsb_" + tn, 0) + 1
            row[col("tsb", tn)] = max(0.0, f) if np.isfinite(f) else np.nan
            sizes = tr[tr > 0]
            if tn != "identity" and T.invertible and len(sizes):
                try:
                    zs, cs = T.prepare(sizes)
                    rt_add(rt, "tsb_sizes_" + tn, roundtrip_check(T, sizes, zs, cs))
                except TransformFailed:
                    pass
        rows.append(row)
    return rows, rt, fails


def per_sku_a(series, meta_a, tnames):
    jobs = []
    for pk, g in meta_a.groupby("pk"):
        x, fs = series[pk]
        jobs.append((pk, x, fs, list(zip(g.ntr.tolist(), g.bin.tolist())), tnames))
    rows, rt, fails = [], {}, {}
    with ProcessPoolExecutor(max_workers=12) as ex:
        for r, t, f in ex.map(sku_worker, jobs, chunksize=2):
            rows += r
            rt_merge(rt, t)
            for k, v in f.items():
                fails[k] = fails.get(k, 0) + v
    return pd.DataFrame(rows), rt, fails


def feat_a(tr, ntr, sales, ti):                       # final_models.py:63-69, unit columns / s
    s = tr[-6:].mean()
    lag = lambda k: tr[-k] if len(tr) >= k else np.nan   # noqa: E731
    f = [lag(1), lag(2), lag(3), lag(4), lag(5), lag(6), lag(12), tr[-3:].mean(),
         tr[-12:].mean() if len(tr) >= 12 else np.nan, tr[-6:].std(), float((tr[-6:] <= 0).sum()),
         ntr, sales / ntr, (ti % 12) + 1]
    return f, s


def xgb_a(series, periods, ix, tnames):
    """xgb_abs@A (final_models.py:97-109) on each transformed series: transform first,
    then the existing / s scaling unchanged. Returns {tname: {(pk, ti): value}}."""
    import xgboost as xgb
    out, rt, cnt = {}, {}, {}
    for tn in tnames:
        T = TRANSFORMS[tn]
        vals = {}
        c = dict(pool_excluded=0, train_rows_level_le0=0, target_level_le0=0, folds_under_100=0, target_blank=0)
        for m in range(ix[FULL0], len(periods)):
            Xtr, ytr, own, ztr, s_tr, tgt = [], [], [], [], [], []
            for pk in sorted(series):
                x, fs = series[pk]
                n = m - fs
                if n < MIN_TRAIN:
                    continue
                tr = x[:n]
                try:
                    z, ctx = T.prepare(tr)
                except TransformFailed:
                    c["pool_excluded"] += 1
                    continue
                rt_add(rt, tn, roundtrip_check(T, tr, z, ctx))
                off = len(tr) - len(z)
                for t in range(MIN_TRAIN, n):
                    zt = z[:t - off]
                    if not len(zt):
                        continue
                    f, s = feat_a(zt, t, int((x[:t] > 0).sum()), fs + t)
                    if not s > 0:
                        c["train_rows_level_le0"] += 1
                        continue
                    Xtr.append(f), s_tr.append(s), own.append(pk), ztr.append(z[t - off])
                f, s = feat_a(z, n, int((tr > 0).sum()), m)
                if not s > 0:
                    c["target_level_le0"] += 1
                    continue
                tgt.append((pk, fs + n, f, s, ctx))
            if len(Xtr) < XGB_MIN_ROWS or not tgt:
                c["folds_under_100"] += int(len(Xtr) < XGB_MIN_ROWS)
                continue
            F = np.array(Xtr, float)
            s_arr = np.array(s_tr, float)
            F[:, UNIT] = F[:, UNIT] / s_arr[:, None]
            y = np.array(ztr, float) / s_arr
            booster = xgb.train(XGB_A, xgb.DMatrix(F, label=y), num_boost_round=XGB_ROUNDS)
            resid = {}
            if T.smear:
                p_in = booster.predict(xgb.DMatrix(F)) * s_arr
                e_all = np.array(ztr, float) - p_in
                for pk_, e_ in zip(own, e_all):
                    resid.setdefault(pk_, []).append(e_)
            Fte = np.array([t_[2] for t_ in tgt], float)
            s_te = np.array([t_[3] for t_ in tgt], float)
            Fte[:, UNIT] = Fte[:, UNIT] / s_te[:, None]
            pz = booster.predict(xgb.DMatrix(Fte)) * s_te
            for (pk, ti, _, _, ctx), v in zip(tgt, pz):
                inv = T.invert(v, ctx, resid.get(pk) if T.smear else None)
                if not np.isfinite(inv):
                    c["target_blank"] += 1
                vals[(pk, ti)] = max(0.0, inv) if np.isfinite(inv) else np.nan
        out[tn] = vals
        cnt[tn] = c
        print(f"  xgb A {tn:<11} targets={len(vals)} {c}", flush=True)
    return out, rt, cnt


def assemble_a(meta_a, per_sku, xgb_vals, tnames):
    A = meta_a.merge(per_sku, on=["pk", "ti"], how="left")
    for tn in tnames:
        key = list(zip(A.pk, A.ti))
        A[col("xgb", tn)] = [xgb_vals[tn].get(k, np.nan) for k in key]
        if TRANSFORMS[tn].pattern:
            A.loc[A.bin != "long", col("xgb", tn)] = np.nan
        A[col("comb_simple", tn)] = A[[col("ma4", tn), col("ma12", tn), col("ses", tn)]].mean(axis=1, skipna=False)   # run7.py:77
        A[col("xgb_ma3_avg", tn)] = A[[col("xgb", tn), col("ma3", tn)]].mean(axis=1, skipna=False)                   # final_models.py:121
    return A


CANDIDATE_SEARCH = os.path.join(REPO, "reports", "experiment_artifacts", "candidate_search_tierA_preds.csv.gz")


def io_cycle(v: np.ndarray) -> np.ndarray:
    """One write (repr) + read (pandas default float parser) of a CSV column - what
    run7.py, run_lgbm.py and score_arms.py each did to preds_plus.csv.gz."""
    import io
    return pd.read_csv(io.StringIO(pd.DataFrame({"v": v}).to_csv(index=False)))["v"].to_numpy(float)


def io_fixed_point(v: np.ndarray) -> np.ndarray:
    for _ in range(8):
        w = io_cycle(v)
        if np.array_equal(w, v, equal_nan=True):
            return w
        v = w
    return v


def _diff(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    nan_mis = int((np.isnan(a) != np.isnan(b)).sum())
    both = np.isfinite(a) & np.isfinite(b)
    d = np.abs(a[both] - b[both])
    return int((d != 0).sum()) + nan_mis, nan_mis, (float(d.max()) if len(d) else 0.0)


def identity_a(A, P):
    """Three views of one question, all exact equality (no tolerance):
    1. vs candidate_search_tierA_preds.csv.gz read with the exact (round_trip) parser -
       that file was exported straight from final_models_A.pkl;
    2. vs preds_plus.csv.gz as the pipeline reads it (default parser), reported as found;
    3. vs preds_plus.csv.gz after putting our values through the same CSV write/read
       cycles preds_plus went through (comb_simple: components parsed once, as run7.py
       read them, then averaged, then cycled)."""
    pairs = [("ma3", "ma3|identity"), ("tsb", "tsb|identity"), ("ma4", "ma4|identity"), ("ma12", "ma12|identity"),
             ("ses", "ses|identity"), ("xgb_abs@A", "xgb|identity"), ("ens_xgb_ma3@A", "xgb_ma3_avg|identity")]
    Q = pd.read_csv(CANDIDATE_SEARCH, float_precision="round_trip")
    MQ = Q[["pk", "ti"] + [s for s, _ in pairs]].merge(A, on=["pk", "ti"])
    MP = P.merge(A, on=["pk", "ti"], suffixes=("", "_new"))
    print(f"\nIDENTITY A: candidate_search rows matched={len(MQ)}, preds_plus rows matched={len(MP)} (expected 2711 each)")
    print(f"  {'stored':<14} {'ours':<22} {'1: exact artifact':>20} {'2: preds_plus as read':>28} {'3: preds_plus, same I/O':>24}")
    ok1 = ok3 = True
    for s, n in pairs + [("comb_simple", "comb_simple|identity")]:
        if s in MQ:
            d1 = _diff(MQ[s], MQ[n])
            ok1 &= d1[0] == 0
            t1 = f"{d1[0]} diff (max {d1[2]:.2g})"
        else:
            t1 = "not in artifact"
        d2 = _diff(MP[s], MP[n])
        if s == "comb_simple":
            comps = pd.DataFrame({k: io_cycle(MP[f"{k}|identity"].to_numpy(float)) for k in ("ma4", "ma12", "ses")})
            sim = io_fixed_point(comps.mean(axis=1, skipna=False).to_numpy(float))
        else:
            sim = io_fixed_point(MP[n].to_numpy(float))
        d3 = _diff(MP[s], sim)
        ok3 &= d3[0] == 0
        print(f"  {s:<14} {n:<22} {t1:>20} {f'{d2[0]} diff (max {d2[2]:.2g}, NaN mis {d2[1]})':>28} {f'{d3[0]} diff (max {d3[2]:.2g})':>24}")
    print(f"  identity A: exact artifact {'PASS' if ok1 else 'FAIL'} | preds_plus via same I/O {'PASS' if ok3 else 'FAIL'}")
    return ok1 and ok3


# --------------------------------------------------------------------------- #
# harness B: router rolling one-step on the common window
# --------------------------------------------------------------------------- #
def build_b(d, keys):
    from scripts.run_baseline_forecast import build_series
    g = d.rename(columns={"month": "calendar_month", "q": "quantity"}).copy()
    g["quantity"] = g.quantity.fillna(0.0)
    return {int(k): build_series(x) for k, x in g.groupby("pk") if int(k) in keys}


def scored_b(fr, series_b):
    """SKUs fit_review_common scored on the window: status ok, window months present,
    at least one month before the window. Returns [(pk, bin, present)]."""
    out = []
    for r in fr.sort_values("product_key").itertuples(index=False):
        s = series_b.get(int(r.product_key))
        if s is None:
            continue
        present = [m for m in WINDOW if m in s.index]
        if r.status == "ok" and present and (s.index < WINDOW_START).any():
            out.append((int(r.product_key), r.bin, present))
    return out


def module_b(fr, series_b, targets):
    """fit_review_common.py:120-138 verbatim path: router.rolling_one_step + GlobalForecaster."""
    from analytics.forecasting.global_model import GlobalForecaster
    from analytics.forecasting.router import rolling_one_step
    fc = GlobalForecaster({k: series_b[k] for k in sorted(series_b)})
    rows = []
    for pk, b, present in targets:
        sc = rolling_one_step(series_b[pk], present, fc, force_bin=b)
        for r in sc.itertuples(index=False):
            rows.append(dict(pk=pk, month=r.month, actual=r.actual, value=r.value, ma3=r.ma3, method=r.method))
    return pd.DataFrame(rows)


def b_sku_worker(args):
    """Per-SKU pieces of harness B for one SKU: MA3 / TSB / comb_simple under every
    transform at every window month. XGBoost is added in the parent."""
    pk, s, b, present, tnames = args
    warnings.simplefilter("ignore")
    from analytics.forecasting import baseline
    from analytics.forecasting.global_model import from_first_sale
    out, rt, fails = [], {}, {}
    for m in present:
        history = s[s.index < m]
        h = from_first_sale(history) if len(from_first_sale(history)) else history
        hv = h.to_numpy(dtype=float)
        row = dict(pk=pk, month=m, actual=float(s.loc[m]), hist_max=float(hv.max()),
                   ma3_plain=float(baseline.moving_average_forecast(h, 1, baseline.MA_WINDOW)[0]),
                   tsb_module=float(baseline.tsb_forecast(h, 1)[0]), n_hist=len(hv))
        for tn in tnames:
            T = TRANSFORMS[tn]
            if T.pattern and b != "long":
                continue
            try:
                z, ctx = T.prepare(hv)
            except TransformFailed:
                fails[tn] = fails.get(tn, 0) + 1
                for base in ("ma3", "ma4", "ma12", "ses"):
                    row[col(base, tn) + "_raw"] = np.nan
                if tn in LAM_T:
                    row["lam|" + tn] = np.nan
                continue
            rt_add(rt, tn, roundtrip_check(T, hv, z, ctx))
            if tn in LAM_T:
                row["lam|" + tn] = ctx["lm"]
            f3 = float(baseline.moving_average_forecast(pd.Series(z), 1, baseline.MA_WINDOW)[0])
            row[col("ma3", tn) + "_raw"] = T.invert(f3, ctx, ma_resid(z, 3) if T.smear else None)
            for base, k in (("ma4", 4), ("ma12", 12)):
                row[col(base, tn) + "_raw"] = T.invert(ma_forecast(z, k), ctx, ma_resid(z, k) if T.smear else None)
            f, e = ses_fit(z)
            row[col("ses", tn) + "_raw"] = T.invert(f, ctx, e if T.smear else None) if np.isfinite(f) else np.nan
        for tn in TSB_TRANSFORMS:
            if tn not in tnames:
                continue
            try:
                f, _ = tsb_sizes(hv, TRANSFORMS[tn])
            except TransformFailed:
                f = np.nan
                fails["tsb_" + tn] = fails.get("tsb_" + tn, 0) + 1
            row[col("tsb", tn) + "_raw"] = f
        out.append(row)
    return out, rt, fails


def xgb_b(series_b, targets, tnames):
    """The served GlobalForecaster (global_model.py, PARAMS nthread=1) on transformed
    pools. Returns {(tname, pk, month): (value or None, reason)}."""
    import xgboost as xgb
    from analytics.forecasting.global_model import (MIN_HISTORY, MIN_TRAINING_ROWS, NUM_ROUNDS, PARAMS,
                                                    build_features, from_first_sale)
    out, rt, cnt = {}, {}, {}
    need = {}
    for pk, b, present in targets:
        for m in present:
            need.setdefault(m, []).append((pk, b))
    for tn in tnames:
        T = TRANSFORMS[tn]
        c = dict(pool_excluded=0, train_rows_level_le0=0, target_level_le0=0, pool_under_100=0, target_blank=0)
        for m in WINDOW:
            if m not in need:
                continue
            X, y, own, zt_all, sc_all, prep = [], [], [], [], [], {}
            for pk in sorted(series_b):
                hs = from_first_sale(series_b[pk][series_b[pk].index < m])
                if not len(hs):
                    continue
                hv = hs.to_numpy(dtype=float)
                try:
                    z, ctx = T.prepare(hv)
                except TransformFailed:
                    c["pool_excluded"] += 1
                    continue
                rt_add(rt, tn, roundtrip_check(T, hv, z, ctx))
                prep[pk] = (z, ctx)
                off = len(hv) - len(z)
                for t in range(MIN_HISTORY, len(hv)):
                    zt = z[:t - off]
                    if not len(zt):
                        continue
                    feats, scale = build_features(zt, hs.index[t])
                    if feats is None:
                        c["train_rows_level_le0"] += 1
                        continue
                    X.append(feats), y.append(z[t - off] / scale), own.append(pk), zt_all.append(z[t - off]), sc_all.append(scale)
            booster = None
            if len(y) >= MIN_TRAINING_ROWS:
                booster = xgb.train(PARAMS, xgb.DMatrix(np.vstack(X), label=np.asarray(y, dtype=float)), num_boost_round=NUM_ROUNDS)
            resid = {}
            if booster is not None and T.smear:
                p_in = booster.predict(xgb.DMatrix(np.vstack(X))) * np.asarray(sc_all)
                for pk_, e_ in zip(own, np.asarray(zt_all) - p_in):
                    resid.setdefault(pk_, []).append(e_)
            for pk, b in need[m]:
                if T.pattern and b != "long":
                    continue
                if booster is None:
                    c["pool_under_100"] += 1
                    out[(tn, pk, m)] = (None, "pool_under_100")
                    continue
                if pk not in prep:
                    out[(tn, pk, m)] = (np.nan, "transform_failed")
                    c["target_blank"] += 1
                    continue
                z, ctx = prep[pk]
                feats, scale = build_features(z, m)
                if feats is None:
                    c["target_level_le0"] += 1
                    out[(tn, pk, m)] = (None, "level_le0")
                    continue
                v = float(booster.predict(xgb.DMatrix(feats.reshape(1, -1)))[0]) * scale
                inv = T.invert(v, ctx, resid.get(pk) if T.smear else None)
                if not np.isfinite(inv):
                    c["target_blank"] += 1
                out[(tn, pk, m)] = (inv if np.isfinite(inv) else np.nan, None)
        cnt[tn] = c
        print(f"  xgb B {tn:<11} {c}", flush=True)
    return out, rt, cnt


def assemble_b(targets, series_b, tnames):
    jobs = [(pk, series_b[pk], b, present, tnames) for pk, b, present in targets]
    rows, rt, fails = [], {}, {}
    with ProcessPoolExecutor(max_workers=12) as ex:
        for r, t, f in ex.map(b_sku_worker, jobs, chunksize=2):
            rows += r
            rt_merge(rt, t)
            for k, v in f.items():
                fails[k] = fails.get(k, 0) + v
    B = pd.DataFrame(rows)
    binof = {pk: b for pk, b, _ in targets}
    B["bin"] = B.pk.map(binof)
    xv, xrt, xcnt = xgb_b(series_b, targets, tnames)
    for k, v in xrt.items():
        rt["xgb_" + k] = v
    guards = {}
    for tn in tnames:
        T = TRANSFORMS[tn]
        g = dict(tsb_guard=0, avg_guard=0, avg_fallback_no_xgb=0)
        ma3c, tsbc, combc, avgc = [], [], [], []
        for rd in B.to_dict("records"):                 # itertuples would rename the "|" columns
            floor_ma3 = max(0.0, rd["ma3_plain"])
            if T.pattern and rd["bin"] != "long":
                ma3c.append(np.nan), tsbc.append(np.nan), combc.append(np.nan), avgc.append(np.nan)
                continue
            m3 = rd.get(col("ma3", tn) + "_raw", np.nan)
            ma3c.append(max(0.0, m3) if np.isfinite(m3) else np.nan)            # a served MA3 is floored at 0
            comps = [rd.get(col(bb, tn) + "_raw", np.nan) for bb in ("ma4", "ma12", "ses")]
            comps = [max(0.0, v) if np.isfinite(v) else np.nan for v in comps]
            combc.append(float(np.mean(comps)) if np.isfinite(comps).all() else np.nan)
            if tn in TSB_TRANSFORMS:
                f = rd.get(col("tsb", tn) + "_raw", np.nan)
                if not np.isfinite(f):
                    tsbc.append(np.nan)
                elif f > rd["hist_max"] or f < 0:                               # router.py:111-120
                    g["tsb_guard"] += 1
                    tsbc.append(floor_ma3)
                else:
                    tsbc.append(float(f))
            xg, why = xv.get((tn, rd["pk"], rd["month"]), (None, "missing"))
            if xg is None:
                g["avg_fallback_no_xgb"] += 1
                avgc.append(floor_ma3)
            elif not np.isfinite(xg) or not np.isfinite(m3):
                avgc.append(np.nan)
            else:
                v = (xg + m3) / 2.0
                if v > rd["hist_max"] or v < 0:
                    g["avg_guard"] += 1
                    avgc.append(floor_ma3)
                else:
                    avgc.append(float(v))
        B[col("ma3", tn)] = ma3c
        B[col("comb_simple", tn)] = combc
        B[col("xgb_ma3_avg", tn)] = avgc
        if tn in TSB_TRANSFORMS:
            B[col("tsb", tn)] = tsbc
        guards[tn] = {**g, **xcnt[tn]}
    B["served|identity"] = [row[col(SERVED_KEY[b], "identity")] for b, row in zip(B.bin, B.to_dict("records"))]
    B["ma3_base"] = B.ma3_plain.clip(lower=0.0)
    return B, rt, fails, guards


SERVED_KEY = {"short": "ma3", "medium": "tsb", "long": "xgb_ma3_avg"}


def identity_b(fr, series_b, targets, B):
    from analytics.forecasting.diagnostic_metrics import mase, naive_scale
    mod = module_b(fr, series_b, targets)
    M = mod.merge(B, on=["pk", "month"], suffixes=("", "_g"))
    ok = True
    print(f"\nIDENTITY B: module SKU-months={len(mod)} generic={len(B)} matched={len(M)}")
    for a, b in (("value", "served|identity"), ("ma3", "ma3_base")):
        dd = np.abs(M[a].to_numpy(float) - M[b].to_numpy(float))
        n = int((dd != 0).sum() + np.isnan(dd).sum())
        print(f"  module {a:<6} vs generic {b:<16} differing SKU-months={n} max|diff|={np.nanmax(dd) if len(dd) else 0:.3g}")
        ok &= n == 0
    tm = int((np.abs(B.tsb_module - B["tsb|identity_raw"]) != 0).sum())
    print(f"  baseline.tsb_forecast vs transforms.tsb_sizes(identity): differing SKU-months={tm}")
    ok &= tm == 0
    ref = fr.set_index("product_key")
    mism = []
    rows = []
    for pk, g in mod.groupby("pk"):
        s = series_b[pk]
        ns = naive_scale(s[s.index < WINDOW_START].to_numpy(dtype=float))
        a = g.actual.to_numpy()
        ms = mase(a, g.value.to_numpy(), ns)
        m3 = mase(a, g.ma3.to_numpy(), ns)
        r4 = lambda v: None if v is None or not np.isfinite(v) else round(float(v), 4)   # noqa: E731
        rows.append(dict(pk=pk, mase_common=r4(ms), ma3_mase_common=r4(m3)))
        for mine, theirs in ((r4(ms), ref.loc[pk, "mase_common"]), (r4(m3), ref.loc[pk, "ma3_mase_common"])):
            if (mine is None) != pd.isna(theirs) or (mine is not None and mine != float(theirs)):
                mism.append((pk, mine, theirs))
    R = pd.DataFrame(rows)
    n107 = int(R.mase_common.notna().sum())
    print(f"  mase_common recomputed for {n107} SKUs (expected 107); stored non-null {int(fr.mase_common.notna().sum())}; mismatches at 4 dp={len(mism)}")
    if mism:
        print("   first mismatches:", mism[:5])
    ok &= not mism and n107 == 107
    R = R.merge(fr[["product_key", "bin"]].rename(columns={"product_key": "pk"}), on="pk")
    unfit = R[R.mase_common >= UNFIT_MASE]
    print(f"  unfit (mase_common >= {UNFIT_MASE}): {len(unfit)} {unfit.groupby('bin').size().to_dict()} (expected 25: short 5, medium 9, long 11)")
    return ok, R


# --------------------------------------------------------------------------- #
# scoring (cells_all.py:11-32 verbatim logic, plus n)
# --------------------------------------------------------------------------- #
def cells(df, models):
    out = []
    for pk, grp in df.groupby("pk"):
        a = grp.actual.to_numpy()
        den = np.abs(a).sum()
        if len(grp) < MIN_ORIG or den <= 0:
            continue
        r = dict(pk=pk, n=len(grp))
        sc = grp.scale.to_numpy()
        ok = sc > 0
        for m in models:
            p = grp[m].to_numpy(dtype=float)
            fin = np.isfinite(p).all()
            r[m] = np.abs(a - p).sum() / den if fin else np.nan
            r["mase_" + m] = float(np.mean(np.abs(a - p)[ok] / sc[ok])) if fin and ok.any() else np.nan
        out.append(r)
    return pd.DataFrame(out) if out else pd.DataFrame(columns=["pk", "n"] + models + ["mase_" + m for m in models])


def compare(m, b):
    m, b = np.asarray(m, float), np.asarray(b, float)
    ok = np.isfinite(m) & np.isfinite(b)
    m, b = m[ok], b[ok]
    if len(m) < MIN_N:
        return dict(n=len(m), v="NT")
    i = np.random.default_rng(SEED).integers(0, len(m), (NBOOT, len(m)))
    d = np.median(m[i], axis=1) - np.median(b[i], axis=1)
    lo, hi = np.percentile(d, [2.5, 97.5])
    nb, nw = int((m < b - 1e-12).sum()), int((m > b + 1e-12).sum())
    v = "W" if (hi < 0 and nb > nw) else "L" if (lo > 0 and nw > nb) else "T"
    return dict(n=len(m), lo=lo, hi=hi, nb=nb, nw=nw, v=v, mv=np.median(m), bv=np.median(b))


def label(fam, verdict, blocks):
    if fam == "control":
        return "CONTROL"
    w = blocks.count("W") if blocks else 0
    testable = len(blocks) - blocks.count("N") if blocks else 0
    if verdict == "NT":
        lab = "NOT_TESTABLE"
    elif verdict == "W" and blocks and w * 2 > testable:
        lab = "REAL_WIN"                    # (a) full window, (b) majority of testable blocks, (c) all-SKU selection
    elif verdict == "W" or w > 0:
        lab = "EXPLORATORY_WIN"
    elif verdict == "L":
        lab = "LOSS"
    else:
        lab = "TIE"
    return f"SANITY_{lab}" if fam == "sanity" else lab


BASES_EXACT = {"ma3": "ma3|identity", "short": "ma3|identity", "medium": "tsb|identity", "long": "xgb_ma3_avg|identity"}
BASES_STORED = {"ma3": "ma3", "short": "ma3", "medium": "tsb", "long": "ens_xgb_ma3@A"}   # preds_plus as read


def _nanmed(v):
    v = np.asarray(v, float)
    return float(np.nanmedian(v)) if np.isfinite(v).any() else np.nan


def score_a(A, cohort_name, bases, keys=None, served_by_sku=None, with_sku=False):
    """cohort 'all': per origin bin, as cells_all.py. cohort 'unfit25': these SKUs only,
    all origin bins pooled, served by the SKU's router bin (unfit_recon.py Part B).
    `bases` names the MA3 column and the served column per bin."""
    rows, sku_rows = [], []
    D = A
    if keys is not None:
        D = A[A.pk.isin(keys)].copy()
        D["served_sku"] = np.nan
        for b in BINS:
            msk = D.pk.map(served_by_sku) == b
            D.loc[msk, "served_sku"] = D.loc[msk, bases[b]]
    for model, tn in COLUMNS:
        c, idc, fam = col(model, tn), col(model, "identity"), family(tn)
        bins = ["all"] if keys is not None else (["long"] if TRANSFORMS[tn].pattern else list(BINS))
        for b in bins:
            Db = D if b == "all" else D[D.bin == b]
            bmap = {"ma3": bases["ma3"], "served": "served_sku" if b == "all" else bases[b]}
            W = Db[(Db.month >= FULL0) & (Db.month <= END)]
            full = cells(W, list(dict.fromkeys([c, bmap["ma3"], bmap["served"], idc])))
            blk = [cells(Db[(Db.month >= lo) & (Db.month <= hi)], list(dict.fromkeys([c, bmap["ma3"], bmap["served"]])))
                   for lo, hi in BLOCKS]
            n_blank = int(W[c].isna().sum())
            for base, bc in bmap.items():
                r = compare(full[c], full[bc]) if len(full) else dict(n=0, v="NT")
                vs = "".join((compare(cb[c], cb[bc])["v"] if len(cb) else "NT")[0] for cb in blk)
                mc = full["mase_" + c].to_numpy(float) if len(full) else np.array([])
                mb = full["mase_" + bc].to_numpy(float) if len(full) else np.array([])
                mi = full["mase_" + idc].to_numpy(float) if len(full) else np.array([])
                rows.append(dict(harness="A_bakeoff", cohort=cohort_name, bin=b, model=model, transform=tn, family=fam,
                                 candidate=c, baseline=base, baseline_col=bc, n_skus=r["n"], n_blank_origins=n_blank,
                                 med_wape=r.get("mv"), base_med_wape=r.get("bv"), ci_lo=r.get("lo"), ci_hi=r.get("hi"),
                                 n_better=r.get("nb"), n_worse=r.get("nw"), verdict_full=r["v"], blocks=vs,
                                 W=vs.count("W"), T=vs.count("T"), L=vs.count("L"), testable=5 - vs.count("N"),
                                 med_mase=_nanmed(mc), base_med_mase=_nanmed(mb),
                                 med_mase_change_vs_identity=_nanmed(mc - mi) if len(mc) else np.nan,
                                 label=label(fam, r["v"], vs)))
            if with_sku and len(full):
                for fd in full.to_dict("records"):
                    sku_rows.append(dict(harness="A_bakeoff", product_key=fd["pk"], bin=b, model=model, transform=tn,
                                         family=fam, candidate=c, n_months=fd["n"],
                                         wape=fd[c], mase=fd["mase_" + c], mase_identity_same_model=fd["mase_" + idc],
                                         wape_ma3=fd[bmap["ma3"]], mase_ma3=fd["mase_" + bmap["ma3"]],
                                         wape_served=fd[bmap["served"]], mase_served=fd["mase_" + bmap["served"]]))
    return pd.DataFrame(rows), pd.DataFrame(sku_rows)


def per_sku_b(B, series_b):
    from analytics.forecasting.diagnostic_metrics import mase, naive_scale, wape
    out = []
    ns_of = {pk: naive_scale(series_b[pk][series_b[pk].index < WINDOW_START].to_numpy(dtype=float)) for pk in B.pk.unique()}
    for (pk, b), g in B.groupby(["pk", "bin"]):
        a = g.actual.to_numpy(float)
        ns = ns_of[pk]
        base = {"ma3": g.ma3_base.to_numpy(float), "served": g["served|identity"].to_numpy(float)}
        for model, tn in COLUMNS:
            c = col(model, tn)
            if c not in g or (TRANSFORMS[tn].pattern and b != "long"):
                continue
            p = g[c].to_numpy(float)
            fin = np.isfinite(p).all()
            idp = g[col(model, "identity")].to_numpy(float)
            out.append(dict(harness="B_common_window", product_key=pk, bin=b, model=model, transform=tn, family=family(tn),
                            candidate=c, n_months=len(g), naive_scale=ns, blank_months=int((~np.isfinite(p)).sum()),
                            wape=wape(a, p) if fin else np.nan, mase=mase(a, p, ns) if fin else np.nan,
                            mase_identity_same_model=mase(a, idp, ns) if np.isfinite(idp).all() else np.nan,
                            wape_ma3=wape(a, base["ma3"]), mase_ma3=mase(a, base["ma3"], ns),
                            wape_served=wape(a, base["served"]), mase_served=mase(a, base["served"], ns)))
    return pd.DataFrame(out)


def score_b(S, cohort_name, keys=None):
    rows = []
    D = S if keys is None else S[S.product_key.isin(keys)]
    D = D[(D.n_months >= MIN_ORIG)]
    for model, tn in COLUMNS:
        c, fam = col(model, tn), family(tn)
        bins = ["all"] if keys is not None else (["long"] if TRANSFORMS[tn].pattern else list(BINS))
        for b in bins:
            g = D[D.candidate == c] if b == "all" else D[(D.candidate == c) & (D.bin == b)]
            for base in ("ma3", "served"):
                r = compare(g.wape, g["wape_" + base]) if len(g) else dict(n=0, v="NT")
                ok = np.isfinite(g.mase.to_numpy(float))
                ch = (g.mase - g.mase_identity_same_model).to_numpy(float)
                rows.append(dict(harness="B_common_window", cohort=cohort_name, bin=b, model=model, transform=tn, family=fam,
                                 candidate=c, baseline=base, baseline_col=("ma3" if base == "ma3" else "served (router bin)"),
                                 n_skus=r["n"], med_wape=r.get("mv"), base_med_wape=r.get("bv"), ci_lo=r.get("lo"),
                                 ci_hi=r.get("hi"), n_better=r.get("nb"), n_worse=r.get("nw"), verdict_full=r["v"],
                                 blocks="", W=None, T=None, L=None, testable=None,
                                 med_mase=float(np.median(g.mase[ok])) if ok.any() else np.nan,
                                 base_med_mase=float(np.nanmedian(g["mase_" + base])) if len(g) else np.nan,
                                 med_mase_change_vs_identity=float(np.nanmedian(ch)) if np.isfinite(ch).any() else np.nan,
                                 n_skus_mase_improved=int((ch < -1e-12).sum()), n_skus_mase_worse=int((ch > 1e-12).sum()),
                                 label=label(fam, r["v"], "")))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# lambda bounds (Box-Cox, Yeo-Johnson): where the fits sit, and what the results rest on
# --------------------------------------------------------------------------- #
def lam_class(v):
    v = np.asarray(v, float)
    return np.where(np.isnan(v), "failed",
                    np.where(v <= -1 + LAM_EPS, "at_-1", np.where(v >= 2 - LAM_EPS, "at_2", "interior")))


def wape_compare(df, c, bc):
    """The two-condition test on per-SKU WAPE over any subset of forecast rows (cells() rules:
    >= 3 rows per SKU, sum|actual| > 0, every forecast finite)."""
    pairs = []
    for _, g in df.groupby("pk"):
        a = g.actual.to_numpy(float)
        den = np.abs(a).sum()
        if len(g) < MIN_ORIG or den <= 0:
            continue
        p, q = g[c].to_numpy(float), g[bc].to_numpy(float)
        pairs.append((np.abs(a - p).sum() / den if np.isfinite(p).all() else np.nan,
                      np.abs(a - q).sum() / den if np.isfinite(q).all() else np.nan))
    if not pairs:
        return dict(n=0, v="NT")
    arr = np.array(pairs, float)
    return compare(arr[:, 0], arr[:, 1])


def gain_share(df, c, bc, bound):
    """Share of the absolute-error reduction vs the baseline (sum over rows) that comes from
    bound-hit fits. NaN when the candidate reduces no error overall."""
    a, p, q = df.actual.to_numpy(float), df[c].to_numpy(float), df[bc].to_numpy(float)
    ok = np.isfinite(p) & np.isfinite(q)
    g = np.abs(a - q) - np.abs(a - p)
    tot = g[ok].sum()
    return float(g[ok & bound].sum() / tot) if tot > 0 else np.nan


def lambda_analysis(A, B, res_bin):
    WA = A[(A.month >= FULL0) & (A.month <= END)]
    dist = []
    for tn in LAM_T:
        for h, D in (("A_bakeoff", WA), ("B_common_window", B)):
            ct = pd.crosstab(D["bin"], pd.Series(lam_class(D["lam|" + tn]), index=D.index))
            for b, r in ct.iterrows():
                dist.append(dict(harness=h, transform=tn, bin=b, **{k: int(v) for k, v in r.items()}))
    idx = res_bin.set_index(["harness", "cohort", "bin", "candidate", "baseline"])
    split = []
    for tn in LAM_T:
        for model in ("ma3", "comb_simple", "xgb_ma3_avg"):
            c = col(model, tn)
            for h, D in (("A_bakeoff", WA), ("B_common_window", B)):
                for b in BINS:
                    Db = D[D.bin == b]
                    cls = lam_class(Db["lam|" + tn])
                    bound, interior = np.isin(cls, ["at_-1", "at_2"]), cls == "interior"
                    for base in ("ma3", "served"):
                        if h == "A_bakeoff":
                            bc = BASES_EXACT["ma3"] if base == "ma3" else BASES_EXACT[b]
                        else:
                            bc = "ma3_base" if base == "ma3" else "served|identity"
                        mr = idx.loc[(h, "all", b, c, base)]
                        vb, vi = wape_compare(Db[bound], c, bc), wape_compare(Db[interior], c, bc)
                        win = np.zeros(len(Db), bool)
                        if mr.verdict_full == "W":
                            win[:] = True
                        for (lo, hi), v in zip(BLOCKS, mr.blocks if isinstance(mr.blocks, str) else ""):
                            if v == "W":
                                win |= ((Db.month >= lo) & (Db.month <= hi)).to_numpy()
                        is_win = "WIN" in str(mr.label)
                        sw = gain_share(Db[win], c, bc, bound[win]) if win.any() else np.nan
                        split.append(dict(harness=h, cohort="all", bin=b, candidate=c, baseline=base,
                                          n_rows_lambda_bound=int(bound.sum()), n_rows_lambda_interior=int(interior.sum()),
                                          n_skus_lambda_bound=vb["n"], verdict_lambda_bound=vb["v"],
                                          n_skus_lambda_interior=vi["n"], verdict_lambda_interior=vi["v"],
                                          gain_share_from_bound_full=gain_share(Db, c, bc, bound),
                                          gain_share_from_bound_winning_cells=sw,
                                          depends_mainly_on_bound=("n/a" if not is_win else
                                                                   "yes" if np.isfinite(sw) and sw > 0.5 else "no")))
    return pd.DataFrame(dist), pd.DataFrame(split)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--stage", choices=("identity", "full", "score"), required=True)
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)
    t0 = time.time()

    fr = pd.read_csv(FIT_REVIEW)
    keys = sorted(int(k) for k in fr.product_key)
    print(f"cohort from fit_review_common: {len(keys)} SKUs (expected 132); bins {fr.bin.value_counts().to_dict()}")
    d = load_demand(args.cache, keys)
    demand_checks(d)
    if args.stage == "score":                          # re-score the checked predictions of a finished full run
        P = pd.read_csv(PREDS_PLUS)
        P["month"] = P.month.astype(str).str[:7]
        score(pd.read_pickle(os.path.join(args.cache, "full_state.pkl")), P, fr, d, keys, args.cache, t0)
        return

    # ---- harness A ----
    series_a, meta_all, periods, ix = build_a(d, keys)
    meta_a = meta_all[meta_all.bin != "insufficient"].reset_index(drop=True)
    P = pd.read_csv(PREDS_PLUS)                      # default parser: how every existing scoring script read it
    P["month"] = P.month.astype(str).str[:7]
    MK = ["ntr", "sales", "bin", "scale", "actual", "month"]
    Q = pd.read_csv(CANDIDATE_SEARCH, float_precision="round_trip")
    Q["month"] = Q.month.astype(str).str[:7]
    bad = {}
    for name, ref in (("candidate_search (exact parser)", Q), ("preds_plus (default parser)", P)):
        chk = ref[["pk", "ti"] + MK].merge(meta_a[["pk", "ti"] + MK], on=["pk", "ti"], how="outer",
                                           suffixes=("", "_new"), indicator=True)
        bad[name] = {"unmatched": int((chk._merge != "both").sum()),
                     **{k: int((chk[k] != chk[k + "_new"]).sum()) for k in MK}}
    print(f"A origins: all={len(meta_all)} forecastable={len(meta_a)} (expected 2711)")
    for name, b in bad.items():
        print(f"  meta mismatches vs {name}: {b}")
    if any(bad["candidate_search (exact parser)"].values()):
        raise SystemExit("STOP: harness A origins do not match the exact artifact")

    tnames = ["identity"] if args.stage == "identity" else list(TRANSFORMS)
    per_sku, rt_a, fails_a = per_sku_a(series_a, meta_a, tnames)
    print(f"A per-SKU models done {time.time()-t0:.0f}s")
    xv, rt_xa, cnt_xa = xgb_a(series_a, periods, ix, tnames)
    print(f"A XGBoost done {time.time()-t0:.0f}s")
    A = assemble_a(meta_a, per_sku, xv, tnames)
    ok_a = identity_a(A, P)

    # ---- harness B ----
    series_b = build_b(d, keys)
    targets = scored_b(fr, series_b)
    print(f"\nB scored SKUs={len(targets)} SKU-months={sum(len(p) for _, _, p in targets)}")
    B, rt_b, fails_b, guards_b = assemble_b(targets, series_b, tnames)
    print(f"B done {time.time()-t0:.0f}s")
    ok_b, Rb = identity_b(fr, series_b, targets, B)

    # ---- round trip ----
    rt = {}
    for pre, dct in (("A", rt_a), ("A:xgb", rt_xa), ("B", rt_b)):
        for k, v in dct.items():
            rt[f"{pre}:{k}"] = v
    print("\nROUND TRIP inverse(transform(x)) vs x on every fitted training series "
          "(absolute 1e-9; Box-Cox / Yeo-Johnson max(1e-9 * |x|, 1e-9) element by element):")
    for k in sorted(rt):
        v = rt[k]
        print(f"  {k:<28} series={v['n']:>6} max_abs={v['abs']:.3g} max_rel={v['rel']:.3g} over_tol={v['fail']}"
              f"{'   <-- FAIL' if v['fail'] else ''}")
    print("transform fit failures (blank forecasts):", {"A": fails_a, "B": fails_b})
    ok_rt = not any(v["fail"] for v in rt.values())
    print(f"\nCHECKS: identity A {'PASS' if ok_a else 'FAIL'} | identity B {'PASS' if ok_b else 'FAIL'} | round trip {'PASS' if ok_rt else 'FAIL'} | {time.time()-t0:.0f}s")
    if not (ok_a and ok_b and ok_rt):
        raise SystemExit("STOP: a correctness check failed; nothing is scored")
    if args.stage == "identity":
        return
    state = dict(A=A, B=B, Rb=Rb, guards_b=guards_b, cnt_xa=cnt_xa, rt=rt, fails_a=fails_a, fails_b=fails_b)
    pd.to_pickle(state, os.path.join(args.cache, "full_state.pkl"))
    score(state, P, fr, d, keys, args.cache, t0)


def score(state, P, fr, d, keys, cache, t0):
    A, B, Rb = state["A"], state["B"], state["Rb"]
    series_b = build_b(d, keys)
    unfit25 = Rb[Rb.mase_common >= UNFIT_MASE].pk.tolist()
    binof = dict(zip(fr.product_key.astype(int), fr["bin"]))
    AS = A.merge(P[["pk", "ti", "ma3", "tsb", "ens_xgb_ma3@A"]], on=["pk", "ti"])     # stored columns, for the old-file rescore
    ra, sa = score_a(AS, "all", BASES_EXACT, with_sku=True)
    ra_u, _ = score_a(AS, "unfit25", BASES_EXACT, keys=unfit25, served_by_sku=binof)
    print(f"A scored {time.time()-t0:.0f}s", flush=True)
    sb = per_sku_b(B, series_b)
    rb = score_b(sb, "all")
    rb_u = score_b(sb, "unfit25", keys=unfit25)
    res_bin = pd.concat([ra, rb, ra_u, rb_u], ignore_index=True)
    dist, split = lambda_analysis(A, B, res_bin)
    n0 = len(res_bin)
    res_bin = res_bin.merge(split, on=["harness", "cohort", "bin", "candidate", "baseline"], how="left")
    assert len(res_bin) == n0, "lambda merge changed the row count"
    res_sku = pd.concat([sa, sb], ignore_index=True)
    grp = {pk: "common_window_unfit" for pk in unfit25}
    grp.update({pk: "holdout_only_unfit" for pk in HOLDOUT_ONLY_UNFIT})
    res_sku["unfit_group"] = res_sku.product_key.map(grp).fillna("")
    unfit_rows = res_sku[res_sku.unfit_group != ""].copy()

    # old preds_plus file as the baseline instead of the exact identity values
    ro, _ = score_a(AS, "all", BASES_STORED)
    ro_u, _ = score_a(AS, "unfit25", BASES_STORED, keys=unfit25, served_by_sku=binof)
    new, old = pd.concat([ra, ra_u]), pd.concat([ro, ro_u])
    cm = new.merge(old, on=["cohort", "bin", "candidate", "baseline"], suffixes=("", "_old"))
    differs = lambda k: (cm[k] != cm[k + "_old"]) & ~(cm[k].isna() & cm[k + "_old"].isna())   # noqa: E731  NaN == NaN here
    changed = cm[differs("verdict_full") | differs("blocks") | differs("label") | differs("n_better") | differs("n_worse")]
    print(f"\nOLD-FILE RESCORE (harness A baselines from preds_plus as read): rows compared={len(cm)}, "
          f"rows with any change in verdict / blocks / label / better-worse counts={len(changed)}")
    if len(changed):
        print(changed[["cohort", "bin", "candidate", "baseline", "verdict_full", "verdict_full_old", "blocks", "blocks_old",
                       "n_better", "n_better_old", "n_worse", "n_worse_old"]].to_string(index=False))

    n_sku_a = len(sa)
    print(f"\nexpected rows: results_by_bin 672 | results_by_sku = {n_sku_a} (A per-SKU cells) + {len(sb)} (B per-SKU rows) "
          f"= {n_sku_a + len(sb)} | unfit_subset = the results_by_sku rows of 28 SKUs")
    print(f"results_by_bin rows={len(res_bin)} | results_by_sku rows={len(res_sku)} | unfit_subset rows={len(unfit_rows)} "
          f"(SKUs {unfit_rows.product_key.nunique()})")
    res_bin.to_csv(os.path.join(HERE, "results_by_bin.csv"), index=False)
    res_sku.to_csv(os.path.join(HERE, "results_by_sku.csv"), index=False)
    unfit_rows.to_csv(os.path.join(HERE, "unfit_subset.csv"), index=False)
    print("\nLAMBDA distribution (fits in the scored rows):")
    print(dist.to_string(index=False))

    # ---- existing-50 reference under the same harness and the stricter bar ----
    META = ["pk", "ti", "ntr", "sales", "adi", "bin", "scale", "actual", "month", "tier"]
    C50 = [c for c in P.columns if c not in META and c != "ma3"]
    ref = []
    for c in C50:
        for b in BINS:
            Db = P[P.bin == b]
            for base in ("ma3", "served"):
                bc = "ma3" if base == "ma3" else SERVED_COL[b]
                if bc == c:
                    continue
                full = cells(Db[(Db.month >= FULL0) & (Db.month <= END)], [c, bc])
                v = compare(full[c], full[bc])["v"] if len(full) else "NT"
                vs = "".join((compare(cb[c], cb[bc])["v"] if len(cb) else "NT")[0]
                             for cb in (cells(Db[(Db.month >= lo) & (Db.month <= hi)], [c, bc]) for lo, hi in BLOCKS))
                ref.append(dict(candidate=c, bin=b, baseline=base, verdict_full=v, blocks=vs, label=label("squeeze", v, vs)))
    ref = pd.DataFrame(ref)
    pd.to_pickle(dict(existing50=ref, lambda_dist=dist, old_file_changes=changed), os.path.join(cache, "summary_inputs.pkl"))
    print("\nEXISTING 50 under the stricter bar (harness A, all SKUs, preds_plus as stored):")
    print(ref.groupby(["baseline", "label"]).size().to_string())
    print("\nguards / skips harness B:", state["guards_b"])
    print("XGBoost counts harness A:", state["cnt_xa"])
    print(f"total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
