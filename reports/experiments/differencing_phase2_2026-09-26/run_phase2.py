"""Phase 2 of the target-transform experiment, 2026-09-26. PERSONAL EXPERIMENT: read-only,
never adopted, never pushed. Nothing here touches forecast_result, the router, DEC-28,
backup_options.json, analytics/ or the dev viewer.

Groups (see chains.py for the settings):
  A  differencing alone: D2, D3, S12, S12+D1 (D1 = phase 1's diff1, a reference here)
  B  phase 1 transform, then D1 or S12
  C  repeated squeezing: sqrt, cube root, asinh, log1p, each x2 and x3
  D  AUTO-d: lag-1 differencing order 0..2 chosen by KPSS
  E  E1 auto-ARIMA, E2 auto-ARIMA on log1p, E3 fixed SARIMA(1,1,1)(0,1,1,12)
A, B, D run on MA3 and comb_simple only (XGBoost is left out of every differencing
candidate: phase 1's divide-by-recent-level step removed most forecast months). C runs on
MA3, comb_simple, the XGBoost + MA3 average and TSB (demand sizes only).

Harnesses, identity controls, the WAPE two-condition test and the round-trip rule are
phase 1's (../target_transforms_2026-09-26/run_experiment.py, imported, not modified).

Usage:
  python run_phase2.py --cache DIR --stage precheck   # round trip + skip counts (per-SKU models only, no XGBoost / ARIMA)
  python run_phase2.py --cache DIR --stage full       # everything, gates, scoring, CSVs
  python run_phase2.py --cache DIR --stage score      # re-score a finished full run
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
P1 = os.path.abspath(os.path.join(HERE, os.pardir, "target_transforms_2026-09-26"))
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
for _p in (REPO, P1, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_experiment as R1                                   # noqa: E402  phase 1 (imported before chains)
from transforms import (TRANSFORMS, TransformFailed, ma_forecast, ma_resid,  # noqa: E402
                        roundtrip_check, ses_fit, tsb_sizes)
from chains import (CHAINS, MIN_DIFF, MIN_SEAS, REPEATED_NAMES, e_forecasts,  # noqa: E402
                    rt_chain)

PER_SKU = ["identity"] + REPEATED_NAMES + list(CHAINS)       # MA3 / MA4 / MA12 / SES on these
TSB_SET = ["identity"] + REPEATED_NAMES                      # TSB on demand sizes: never differenced
XGB_SET = ["identity"] + REPEATED_NAMES                      # XGBoost: never differenced
B_T = ("sqrt", "log1p", "boxcox", "yeojohnson", "cbrt", "asinh", "anscombe", "winsor")
BINS3, BINS2 = ["short", "medium", "long"], ["medium", "long"]
E_COLS = ("E1", "E2", "E3")
BASES = R1.BASES_EXACT


def obj(name):
    return CHAINS[name] if name in CHAINS else TRANSFORMS[name]


def build_specs():
    S = []

    def add(col, group, model, variant, bins, ref):
        S.append(dict(col=col, group=group, model=model, variant=variant, bins=bins, ref=ref))
    for m in ("ma3", "comb_simple", "xgb_ma3_avg", "tsb"):
        add(f"{m}|identity", "control", m, "identity", BINS3, f"{m}|identity")
    for m in ("ma3", "comb_simple"):
        add(f"{m}|D1", "reference", m, "D1", BINS2, f"{m}|identity")
        for v in ("D2", "D3", "S12", "S12D1"):
            add(f"{m}|{v}", "A", m, v, BINS2, f"{m}|identity")
        for t in B_T:
            for dd in ("D1", "S12"):
                add(f"{m}|{t}+{dd}", "B", m, f"{t}+{dd}", BINS2, f"{m}|{dd}")
        add(f"{m}|AUTOd", "D", m, "AUTOd", BINS2, f"{m}|identity")
    for m in ("ma3", "comb_simple", "xgb_ma3_avg", "tsb"):
        for r in REPEATED_NAMES:
            add(f"{m}|{r}", "C", m, r, BINS3, f"{m}|identity")
    add("E1", "E", "arima", "auto (AICc, d<=2, D<=1)", BINS2, "ma3|identity")
    add("E2", "E", "arima", "auto on log1p + smearing", BINS2, "ma3|identity")
    add("E3", "E", "sarima", "fixed (1,1,1)(0,1,1,12)", ["long"], "ma3|identity")
    return S


SPECS = build_specs()


def _silence():
    import statsmodels.tsa.holtwinters  # noqa: F401  statsmodels re-enables its warnings on import
    import statsmodels.tsa.stattools  # noqa: F401
    warnings.simplefilter("ignore")


# --------------------------------------------------------------------------- #
# per-SKU workers (raw forecasts kept, for the 10x check)
# --------------------------------------------------------------------------- #
def _per_sku_pieces(tr, bname, row, rt, fails, dsel, key, ma3_fn):
    for name in PER_SKU:
        T = obj(name)
        try:
            z, ctx = T.prepare(tr)
        except TransformFailed as exc:
            k = (name, bname, "history" if "history" in str(exc) else "fit")
            fails[k] = fails.get(k, 0) + 1
            for base in ("ma3", "ma4", "ma12", "ses"):
                row[f"{base}|{name}_raw"] = np.nan
            continue
        R1.rt_add(rt, name, rt_chain(T, tr, z, ctx) if name in CHAINS else roundtrip_check(T, tr, z, ctx))
        if name == "AUTOd":
            dsel.append((*key, bname, len(ctx["lags"])))
        row[f"ma3|{name}_raw"] = T.invert(ma3_fn(z), ctx, ma_resid(z, 3) if T.smear else None)
        for base, k in (("ma4", 4), ("ma12", 12)):
            row[f"{base}|{name}_raw"] = T.invert(ma_forecast(z, k), ctx, ma_resid(z, k) if T.smear else None)
        f, e = ses_fit(z)
        row[f"ses|{name}_raw"] = T.invert(f, ctx, e if T.smear else None) if np.isfinite(f) else np.nan
    for name in TSB_SET:
        T = TRANSFORMS[name]
        try:
            f, _ = tsb_sizes(tr, T)
        except TransformFailed:
            f = np.nan
            fails[("tsb_" + name, bname, "fit")] = fails.get(("tsb_" + name, bname, "fit"), 0) + 1
        row[f"tsb|{name}_raw"] = f
        sizes = tr[tr > 0]
        if name != "identity" and len(sizes):
            try:
                zs, cs = T.prepare(sizes)
                R1.rt_add(rt, "tsb_sizes_" + name, roundtrip_check(T, sizes, zs, cs))
            except TransformFailed:
                pass
    row["hist_max"] = float(np.max(tr))
    row["ret"] = float(-np.min(tr)) if np.min(tr) < 0 else 0.0
    row["n_hist"] = len(tr)


def a_worker(args):
    pk, x, fs, origins = args
    _silence()
    rows, rt, fails, dsel = [], {}, {}, []
    for t, b in origins:
        tr = x[:t]
        row = {"pk": pk, "ti": fs + t}
        _per_sku_pieces(tr, b, row, rt, fails, dsel, (pk, fs + t), lambda z: ma_forecast(z, 3))
        rows.append(row)
    return rows, rt, fails, dsel


def b_worker(args):
    pk, s, b, present = args
    _silence()
    from analytics.forecasting import baseline
    from analytics.forecasting.global_model import from_first_sale
    rows, rt, fails, dsel = [], {}, {}, []
    ma3_fn = lambda z: float(baseline.moving_average_forecast(pd.Series(z), 1, baseline.MA_WINDOW)[0])  # noqa: E731
    for m in present:
        history = s[s.index < m]
        h = from_first_sale(history) if len(from_first_sale(history)) else history
        hv = h.to_numpy(dtype=float)
        row = dict(pk=pk, month=m, bin=b, actual=float(s.loc[m]),
                   ma3_plain=float(baseline.moving_average_forecast(h, 1, baseline.MA_WINDOW)[0]),
                   tsb_module=float(baseline.tsb_forecast(h, 1)[0]))
        _per_sku_pieces(hv, b, row, rt, fails, dsel, (pk, m), ma3_fn)
        rows.append(row)
    return rows, rt, fails, dsel


def e_worker(job):
    key, tr, long_ok = job
    _silence()
    return key, e_forecasts(tr, long_ok)


THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
E_WORKERS = 8
E_LOG = "p2_arima_searches.jsonl"


def _key_str(key):
    h, pk, when = key
    return f"{h}|{int(pk)}|{int(when) if h == 'A' else pd.Timestamp(when).strftime('%Y-%m-%d')}"


def _key_parse(s):
    h, pk, when = s.split("|")
    return (h, int(pk), int(when) if h == "A" else pd.Timestamp(when))


def e_worker_logged(job):
    """e_forecasts plus the CPU it took and the round trip of E2's log1p step."""
    key, tr, long_ok = job
    _silence()
    c0 = time.process_time()
    res = e_forecasts(tr, long_ok)
    cpu = time.process_time() - c0
    rt = None
    if len(tr) >= MIN_DIFF:
        lg = TRANSFORMS["log1p"]
        z, ctx = lg.prepare(tr)
        rt = roundtrip_check(lg, tr, z, ctx)
    return key, res, cpu, rt, os.environ.get("OPENBLAS_NUM_THREADS")


def run_e_resumable(jobs, cache, t0):
    """Every finished search is appended to <cache>/p2_arima_searches.jsonl as it
    completes (flushed and fsynced), so a stop or crash loses nothing done; a rerun
    skips keys already on disk. Workers run single-threaded maths: multi-threaded
    OpenBLAS inside 12 workers cost 76-116 CPU-s per search against 3-13 single-threaded
    (measured 2026-09-26)."""
    import json
    from concurrent.futures import as_completed
    path = os.path.join(cache, E_LOG)
    done = {}
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    done[rec["key"]] = rec
    todo = [j for j in jobs if _key_str(j[0]) not in done]
    print(f"ARIMA searches: total={len(jobs)} | already on disk={len(jobs) - len(todo)} | to run={len(todo)} "
          f"| workers={E_WORKERS}, maths threads per worker=1", flush=True)
    for v in THREAD_VARS:                        # inherited by the spawned workers
        os.environ[v] = "1"
    t1 = time.time()
    if todo:
        with ProcessPoolExecutor(max_workers=E_WORKERS) as ex, open(path, "a") as fh:
            futs = [ex.submit(e_worker_logged, j) for j in todo]
            for i, f in enumerate(as_completed(futs), 1):
                key, res, cpu, rt, threads = f.result()
                rec = {"key": _key_str(key), "cpu_s": round(cpu, 3), "blas_threads": threads, "rt_log1p": rt}
                for k, v in res.items():
                    rec[k] = None if (isinstance(v, float) and not np.isfinite(v)) else v
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
                done[rec["key"]] = rec
                if i % 50 == 0 or i == len(todo):
                    rate = i / max((time.time() - t1) / 60, 1e-9)
                    print(f"  ARIMA {i}/{len(todo)} done | {rate:.1f} searches/min | ETA {(len(todo) - i) / rate:.0f} min "
                          f"| {time.time() - t0:.0f}s", flush=True)
    eres = {}
    for k, rec in done.items():
        eres[_key_parse(k)] = {c: (np.nan if rec.get(c) is None and c in E_COLS else rec.get(c))
                               for c in ("E1", "E1_order", "E2", "E2_order", "E3") if c in rec}
    return eres, done


def e_columns(A, B, eres):
    """Group E columns, by each harness's rules (see assemble_a / assemble_b)."""
    guards = {}
    key_a = list(zip(A.pk, A.ti))
    hm = A.hist_max.to_numpy(float)
    for c in E_COLS:
        raw = np.array([eres.get(("A", pk, ti), {}).get(c, np.nan) for pk, ti in key_a], float)
        g = np.isfinite(raw) & (raw > hm)
        guards[f"A:{c}"] = int(g.sum())
        A[f"{c}__raw"] = raw
        A[c] = clip0(np.where(g, np.nan, raw))
        if c in ("E1", "E2"):
            A[f"{c}_order"] = [eres.get(("A", pk, ti), {}).get(f"{c}_order") for pk, ti in key_a]
    key_b = list(zip(B.pk, B.month))
    floor = np.maximum(0.0, B.ma3_plain.to_numpy(float))
    hb = B.hist_max.to_numpy(float)
    for c in E_COLS:
        raw = np.array([eres.get(("B", pk, m), {}).get(c, np.nan) for pk, m in key_b], float)
        g = np.isfinite(raw) & ((raw > hb) | (raw < 0))
        guards[f"B:{c}"] = int(g.sum())
        B[f"{c}__raw"] = raw
        B[c] = np.where(~np.isfinite(raw), np.nan, np.where(g, floor, raw))
        if c in ("E1", "E2"):
            B[f"{c}_order"] = [eres.get(("B", pk, m), {}).get(f"{c}_order") for pk, m in key_b]
    return A, B, guards


def run_pool(fn, jobs, label, workers=12, chunksize=2):
    rows, rt, fails, dsel = [], {}, {}, []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r, t, f, d in ex.map(fn, jobs, chunksize=chunksize):
            rows += r
            R1.rt_merge(rt, t)
            for k, v in f.items():
                fails[k] = fails.get(k, 0) + v
            dsel += d
    print(f"  {label}: {len(rows)} rows", flush=True)
    return pd.DataFrame(rows), rt, fails, dsel


def run_e(jobs, t0):
    out = {}
    with ProcessPoolExecutor(max_workers=12) as ex:
        for i, (key, res) in enumerate(ex.map(e_worker, jobs, chunksize=1), 1):
            out[key] = res
            if i % 200 == 0:
                print(f"  ARIMA {i}/{len(jobs)} {time.time()-t0:.0f}s", flush=True)
    return out


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
def clip0(v):
    v = np.asarray(v, float)
    return np.where(np.isfinite(v), np.maximum(0.0, v), np.nan)


def assemble_a(meta_a, per, xv, eres):
    """Harness A columns, bake-off rules: every component clipped at 0 (final_fit.py:51);
    ARIMA-family forecasts above the training maximum are blank (model_bakeoff GUARDED)."""
    A = meta_a.merge(per, on=["pk", "ti"], how="left")
    new, guards = {}, {}
    for name in PER_SKU:
        for base in ("ma3", "ma4", "ma12", "ses"):
            new[f"{base}|{name}"] = clip0(A[f"{base}|{name}_raw"])
        comb = pd.DataFrame({k: new[f"{k}|{name}"] for k in ("ma4", "ma12", "ses")}).mean(axis=1, skipna=False)
        new[f"comb_simple|{name}"] = comb.to_numpy(float)
        new[f"ma3|{name}__raw"] = A[f"ma3|{name}_raw"].to_numpy(float)
        new[f"comb_simple|{name}__raw"] = A[[f"{k}|{name}_raw" for k in ("ma4", "ma12", "ses")]].mean(axis=1, skipna=False).to_numpy(float)
    key = list(zip(A.pk, A.ti))
    for name in XGB_SET:
        new[f"xgb|{name}"] = np.array([xv[name].get(k, np.nan) for k in key], float)
        new[f"xgb_ma3_avg|{name}"] = pd.DataFrame({"x": new[f"xgb|{name}"], "m": new[f"ma3|{name}"]}).mean(axis=1, skipna=False).to_numpy(float)
        new[f"xgb_ma3_avg|{name}__raw"] = pd.DataFrame({"x": new[f"xgb|{name}"], "m": new[f"ma3|{name}__raw"]}).mean(axis=1, skipna=False).to_numpy(float)
    for name in TSB_SET:
        new[f"tsb|{name}"] = clip0(A[f"tsb|{name}_raw"])
        new[f"tsb|{name}__raw"] = A[f"tsb|{name}_raw"].to_numpy(float)
    hm = A.hist_max.to_numpy(float)
    for c in E_COLS:
        raw = np.array([eres.get(("A", pk, ti), {}).get(c, np.nan) for pk, ti in key], float)
        g = np.isfinite(raw) & (raw > hm)
        guards[c] = int(g.sum())
        new[f"{c}__raw"] = raw
        new[c] = clip0(np.where(g, np.nan, raw))
        if c in ("E1", "E2"):
            new[f"{c}_order"] = [eres.get(("A", pk, ti), {}).get(f"{c}_order") for pk, ti in key]
    A = pd.concat([A, pd.DataFrame(new, index=A.index)], axis=1)
    return A, guards


def assemble_b(Bp, xv, eres):
    """Harness B columns, router rules: a served MA3 is floored at 0; a challenger above
    the SKU's historical maximum or below 0 falls back to MA3 (router.py:111-122)."""
    B = Bp.copy()
    floor = np.maximum(0.0, B.ma3_plain.to_numpy(float))
    hm = B.hist_max.to_numpy(float)
    new, guards = {}, {}

    def guarded(raw, name):
        raw = np.asarray(raw, float)
        g = np.isfinite(raw) & ((raw > hm) | (raw < 0))
        guards[name] = int(g.sum())
        return np.where(~np.isfinite(raw), np.nan, np.where(g, floor, raw))
    for name in PER_SKU:
        new[f"ma3|{name}"] = clip0(B[f"ma3|{name}_raw"])
        comps = np.column_stack([clip0(B[f"{k}|{name}_raw"]) for k in ("ma4", "ma12", "ses")])
        new[f"comb_simple|{name}"] = np.where(np.isfinite(comps).all(axis=1), comps.mean(axis=1), np.nan)
        new[f"ma3|{name}__raw"] = B[f"ma3|{name}_raw"].to_numpy(float)
        rc = np.column_stack([B[f"{k}|{name}_raw"].to_numpy(float) for k in ("ma4", "ma12", "ses")])
        new[f"comb_simple|{name}__raw"] = np.where(np.isfinite(rc).all(axis=1), rc.mean(axis=1), np.nan)
    for name in TSB_SET:
        new[f"tsb|{name}__raw"] = B[f"tsb|{name}_raw"].to_numpy(float)
        new[f"tsb|{name}"] = guarded(B[f"tsb|{name}_raw"], f"tsb|{name}")
    keys = list(zip(B.pk, B.month))
    for name in XGB_SET:
        m3 = B[f"ma3|{name}_raw"].to_numpy(float)
        vals, raws, fb = [], [], 0
        for i, k in enumerate(keys):
            xg, _ = xv.get((name, *k), (None, "missing"))
            if xg is None:
                fb += 1
                vals.append(floor[i]), raws.append(np.nan)
            elif not np.isfinite(xg) or not np.isfinite(m3[i]):
                vals.append(np.nan), raws.append(np.nan)
            else:
                v = (xg + m3[i]) / 2.0
                raws.append(v)
                vals.append(floor[i] if (v > hm[i] or v < 0) else float(v))
        new[f"xgb_ma3_avg|{name}"] = np.array(vals, float)
        new[f"xgb_ma3_avg|{name}__raw"] = np.array(raws, float)
        r = np.array(raws, float)
        guards[f"xgb_ma3_avg|{name}"] = int((np.isfinite(r) & ((r > hm) | (r < 0))).sum())
        guards[f"xgb_ma3_avg|{name} (no XGBoost value -> MA3)"] = fb
    for c in E_COLS:
        raw = np.array([eres.get(("B", pk, m), {}).get(c, np.nan) for pk, m in keys], float)
        new[f"{c}__raw"] = raw
        new[c] = guarded(raw, c)
        if c in ("E1", "E2"):
            new[f"{c}_order"] = [eres.get(("B", pk, m), {}).get(f"{c}_order") for pk, m in keys]
    B = pd.concat([B, pd.DataFrame(new, index=B.index)], axis=1)
    B["ma3_base"] = floor
    B["served|identity"] = [row[f"{R1.SERVED_KEY[b]}|identity"] for b, row in zip(B.bin, B.to_dict("records"))]
    B["tsb|identity_raw"] = B["tsb|identity__raw"]
    return B, guards


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def d1_check(A, B, cache):
    """Recomputed D1 must equal phase 1's diff1 wherever phase 1 had a value."""
    st = pd.read_pickle(os.path.join(cache, "full_state.pkl"))
    ok = True
    for h, new, old, on in (("A", A, st["A"], ["pk", "ti"]), ("B", B, st["B"], ["pk", "month"])):
        M = old[on + ["ma3|diff1", "comb_simple|diff1"]].merge(new[on + ["ma3|D1", "comb_simple|D1"]], on=on)
        for a, b in (("ma3|diff1", "ma3|D1"), ("comb_simple|diff1", "comb_simple|D1")):
            m = M[a].notna()
            dd = np.abs(M.loc[m, a].to_numpy(float) - M.loc[m, b].to_numpy(float))
            n = int((dd != 0).sum() + np.isnan(dd).sum())
            print(f"  D1 reproduction {h}: {b} vs phase 1 {a} on {int(m.sum())} rows: differing={n}")
            ok &= n == 0 and m.sum() > 0
    return ok


def breach_table(A, B):
    rows = []
    WA = A[(A.month >= R1.FULL0) & (A.month <= R1.END)]
    for h, D in (("A_bakeoff", WA), ("B_common_window", B)):
        hm, rt = D.hist_max.to_numpy(float), D.ret.to_numpy(float)
        for s in SPECS:
            raw = D[f"{s['col']}__raw"].to_numpy(float)
            fin = np.isfinite(raw)
            rows.append(dict(harness=h, candidate=s["col"], group=s["group"], n_forecasts=int(fin.sum()),
                             above_10x_hist_max=int((fin & (raw > 10 * hm)).sum()),
                             below_minus_10x_largest_return=int((fin & (raw < -10 * rt)).sum())))
    return pd.DataFrame(rows)


def skip_table(A, B):
    rows = []
    WA = A[(A.month >= R1.FULL0) & (A.month <= R1.END) & A.bin.isin(BINS3)]
    for h, D in (("A_bakeoff", WA), ("B_common_window", B)):
        for b, g in D.groupby("bin"):
            n = g.n_hist.to_numpy()
            rows.append(dict(harness=h, bin=b, forecast_months=len(g), skipped_under_18=int((n < MIN_DIFF).sum()),
                             skipped_under_24=int((n < MIN_SEAS).sum())))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# scoring (phase 1 cells / compare / label)
# --------------------------------------------------------------------------- #
def _lab(group, v, vs):
    return {"control": "CONTROL", "reference": "REFERENCE"}.get(group) or R1.label("x", v, vs)


def _nanmed(v):
    v = np.asarray(v, float)
    return float(np.nanmedian(v)) if np.isfinite(v).any() else np.nan


def score_a(A, cohort, keys=None, served_by_sku=None, with_sku=False):
    rows, sku = [], []
    D = A
    if keys is not None:
        D = A[A.pk.isin(keys)].copy()
        D["served_sku"] = np.nan
        for b in BINS3:
            msk = D.pk.map(served_by_sku) == b
            D.loc[msk, "served_sku"] = D.loc[msk, BASES[b]]
    for s in SPECS:
        c, ref = s["col"], s["ref"]
        for b in (["all"] if keys is not None else s["bins"]):
            Db = D if b == "all" else D[D.bin == b]
            bm = {"ma3": BASES["ma3"], "served": "served_sku" if b == "all" else BASES[b]}
            W = Db[(Db.month >= R1.FULL0) & (Db.month <= R1.END)]
            full = R1.cells(W, list(dict.fromkeys([c, bm["ma3"], bm["served"], ref])))
            blk = [R1.cells(Db[(Db.month >= lo) & (Db.month <= hi)], list(dict.fromkeys([c, bm["ma3"], bm["served"]])))
                   for lo, hi in R1.BLOCKS]
            for base, bc in bm.items():
                r = R1.compare(full[c], full[bc]) if len(full) else dict(n=0, v="NT")
                vs = "".join((R1.compare(cb[c], cb[bc])["v"] if len(cb) else "NT")[0] for cb in blk)
                g = lambda k: full["mase_" + k].to_numpy(float) if len(full) else np.array([])  # noqa: E731
                rows.append(dict(harness="A_bakeoff", cohort=cohort, bin=b, group=s["group"], model=s["model"],
                                 variant=s["variant"], candidate=c, baseline=base, baseline_col=bc, reference_col=ref,
                                 n_skus=r["n"], n_blank_forecasts=int(W[c].isna().sum()),
                                 med_wape=r.get("mv"), base_med_wape=r.get("bv"), ci_lo=r.get("lo"), ci_hi=r.get("hi"),
                                 n_better=r.get("nb"), n_worse=r.get("nw"), verdict_full=r["v"], blocks=vs,
                                 W=vs.count("W"), T=vs.count("T"), L=vs.count("L"), testable=5 - vs.count("N"),
                                 med_mase=_nanmed(g(c)), base_med_mase=_nanmed(g(bc)),
                                 med_mase_change_vs_reference=_nanmed(g(c) - g(ref)) if len(full) else np.nan,
                                 label=_lab(s["group"], r["v"], vs)))
            if with_sku and len(full):
                for fd in full.to_dict("records"):
                    sku.append(dict(harness="A_bakeoff", product_key=fd["pk"], bin=b, group=s["group"], candidate=c,
                                    reference_col=ref, n_months=fd["n"], wape=fd[c], mase=fd["mase_" + c],
                                    mase_reference=fd["mase_" + ref], wape_ma3=fd[bm["ma3"]], mase_ma3=fd["mase_" + bm["ma3"]],
                                    wape_served=fd[bm["served"]], mase_served=fd["mase_" + bm["served"]]))
    return pd.DataFrame(rows), pd.DataFrame(sku)


def per_sku_b(B, series_b):
    from analytics.forecasting.diagnostic_metrics import mase, naive_scale, wape
    out = []
    for (pk, b), g in B.groupby(["pk", "bin"]):
        a = g.actual.to_numpy(float)
        s = series_b[pk]
        ns = naive_scale(s[s.index < R1.WINDOW_START].to_numpy(dtype=float))
        base = {"ma3": g.ma3_base.to_numpy(float), "served": g["served|identity"].to_numpy(float)}
        for sp in SPECS:
            if b not in sp["bins"]:
                continue
            p, rp = g[sp["col"]].to_numpy(float), g[sp["ref"]].to_numpy(float)
            fin = np.isfinite(p).all()
            out.append(dict(harness="B_common_window", product_key=pk, bin=b, group=sp["group"], candidate=sp["col"],
                            reference_col=sp["ref"], n_months=len(g), naive_scale=ns, blank_months=int((~np.isfinite(p)).sum()),
                            wape=wape(a, p) if fin else np.nan, mase=mase(a, p, ns) if fin else np.nan,
                            mase_reference=mase(a, rp, ns) if np.isfinite(rp).all() else np.nan,
                            wape_ma3=wape(a, base["ma3"]), mase_ma3=mase(a, base["ma3"], ns),
                            wape_served=wape(a, base["served"]), mase_served=mase(a, base["served"], ns)))
    return pd.DataFrame(out)


def score_b(S, cohort, keys=None):
    rows = []
    D = S if keys is None else S[S.product_key.isin(keys)]
    D = D[D.n_months >= R1.MIN_ORIG]
    for sp in SPECS:
        c = sp["col"]
        for b in (["all"] if keys is not None else sp["bins"]):
            g = D[D.candidate == c] if b == "all" else D[(D.candidate == c) & (D.bin == b)]
            for base in ("ma3", "served"):
                r = R1.compare(g.wape, g["wape_" + base]) if len(g) else dict(n=0, v="NT")
                ch = (g.mase - g.mase_reference).to_numpy(float)
                rows.append(dict(harness="B_common_window", cohort=cohort, bin=b, group=sp["group"], model=sp["model"],
                                 variant=sp["variant"], candidate=c, baseline=base,
                                 baseline_col="ma3" if base == "ma3" else "served (router bin)", reference_col=sp["ref"],
                                 n_skus=r["n"], n_blank_forecasts=int(g.blank_months.sum()) if len(g) else 0,
                                 med_wape=r.get("mv"), base_med_wape=r.get("bv"), ci_lo=r.get("lo"), ci_hi=r.get("hi"),
                                 n_better=r.get("nb"), n_worse=r.get("nw"), verdict_full=r["v"], blocks="",
                                 W=None, T=None, L=None, testable=None, med_mase=_nanmed(g.mase),
                                 base_med_mase=_nanmed(g["mase_" + base]), med_mase_change_vs_reference=_nanmed(ch),
                                 label=_lab(sp["group"], r["v"], "")))
    return pd.DataFrame(rows)


def earlier_blocks(A, unfit_rows, binof):
    """For each unfit SKU a candidate brings below MASE 1.1 on the common window: harness A,
    the four earlier half-year blocks, that SKU's forecast months only - is the candidate
    better than the served model there, and below 1.1?"""
    out = []
    hit = unfit_rows[(unfit_rows.harness == "B_common_window") & (unfit_rows.mase < R1.UNFIT_MASE)]
    for r in hit.itertuples(index=False):
        sv = BASES[binof[r.product_key]]
        testable = beats = below = 0
        for lo, hi in R1.BLOCKS[:4]:
            g = A[(A.pk == r.product_key) & (A.month >= lo) & (A.month <= hi)]
            c = R1.cells(g, list(dict.fromkeys([r.candidate, sv])))
            if not len(c) or not np.isfinite(c["mase_" + r.candidate].iloc[0]) or not np.isfinite(c["mase_" + sv].iloc[0]):
                continue
            testable += 1
            beats += int(c["mase_" + r.candidate].iloc[0] < c["mase_" + sv].iloc[0])
            below += int(c["mase_" + r.candidate].iloc[0] < R1.UNFIT_MASE)
        out.append(dict(product_key=r.product_key, candidate=r.candidate, earlier_blocks_testable=testable,
                        earlier_blocks_beats_served=beats, earlier_blocks_below_1_1=below,
                        holds_on_earlier_blocks=("n/a" if not testable else "yes" if beats * 2 > testable else "no")))
    return pd.DataFrame(out, columns=["product_key", "candidate", "earlier_blocks_testable", "earlier_blocks_beats_served",
                                      "earlier_blocks_below_1_1", "holds_on_earlier_blocks"])


def expected_bin_rows():
    return 2 * (2 * sum(len(s["bins"]) for s in SPECS) + 2 * len(SPECS))


def score(state, fr, d, keys, cache, t0):
    A, B, Rb = state["A"], state["B"], state["Rb"]
    series_b = R1.build_b(d, keys)
    unfit25 = Rb[Rb.mase_common >= R1.UNFIT_MASE].pk.tolist()
    binof = dict(zip(fr.product_key.astype(int), fr["bin"]))
    ra, sa = score_a(A, "all", with_sku=True)
    ra_u, _ = score_a(A, "unfit25", keys=unfit25, served_by_sku=binof)
    print(f"A scored {time.time()-t0:.0f}s", flush=True)
    sb = per_sku_b(B, series_b)
    rb, rb_u = score_b(sb, "all"), score_b(sb, "unfit25", keys=unfit25)
    res_bin = pd.concat([ra, rb, ra_u, rb_u], ignore_index=True)
    res_sku = pd.concat([sa, sb], ignore_index=True)
    grp = {pk: "common_window_unfit" for pk in unfit25}
    grp.update({pk: "holdout_only_unfit" for pk in R1.HOLDOUT_ONLY_UNFIT})
    res_sku["unfit_group"] = res_sku.product_key.map(grp).fillna("")
    unfit = res_sku[res_sku.unfit_group != ""].copy()
    eb = earlier_blocks(A, unfit[unfit.unfit_group == "common_window_unfit"], binof)
    if len(eb):                                   # describes the harness B (common window) row only
        unfit = unfit.merge(eb.assign(harness="B_common_window"), on=["harness", "product_key", "candidate"], how="left")
    unfit["below_1_1_common_window"] = np.where(unfit.harness == "B_common_window", unfit.mase < R1.UNFIT_MASE, np.nan)
    print(f"\nexpected rows: results_by_bin {expected_bin_rows()} | results_by_sku = {len(sa)} (A) + {len(sb)} (B) = {len(sa) + len(sb)} "
          f"| unfit_subset = the results_by_sku rows of the 28 unfit SKUs")
    print(f"results_by_bin rows={len(res_bin)} | results_by_sku rows={len(res_sku)} | unfit_subset rows={len(unfit)} "
          f"(SKUs {unfit.product_key.nunique()})")
    res_bin.to_csv(os.path.join(HERE, "results_by_bin.csv"), index=False)
    res_sku.to_csv(os.path.join(HERE, "results_by_sku.csv"), index=False)
    unfit.to_csv(os.path.join(HERE, "unfit_subset.csv"), index=False)
    pd.to_pickle(dict(earlier_blocks=eb), os.path.join(cache, "p2_score_extras.pkl"))
    print(f"total {time.time()-t0:.0f}s")


def e_jobs(series_a, meta_a, series_b, targets):
    from analytics.forecasting.global_model import from_first_sale
    jobs = [(("A", r.pk, r.ti), series_a[r.pk][0][:r.ntr], r.bin == "long")
            for r in meta_a.itertuples(index=False) if r.ntr >= MIN_DIFF]
    for pk, b, present in targets:
        s = series_b[pk]
        for m in present:
            h = s[s.index < m]
            h = from_first_sale(h) if len(from_first_sale(h)) else h
            if len(h) >= MIN_DIFF:
                jobs.append((("B", pk, m), h.to_numpy(dtype=float), b == "long"))
    return jobs


def arima_stage(fr, d, keys, cache, series_a, meta_a, series_b, targets, t0):
    """Group E on top of the saved groups A-D state (p2_state_noE.pkl): resumable
    single-threaded searches, then every gate again, then the full scoring."""
    state = pd.read_pickle(os.path.join(cache, "p2_state_noE.pkl"))
    jobs = e_jobs(series_a, meta_a, series_b, targets)
    eres, done = run_e_resumable(jobs, cache, t0)
    missing = [j[0] for j in jobs if _key_str(j[0]) not in done]
    print(f"ARIMA searches on disk={len(done)} | missing={len(missing)} (expected 0)", flush=True)
    if missing:
        raise SystemExit("STOP: searches missing; rerun this stage to resume")
    cpu = np.array([r["cpu_s"] for r in done.values()], float)
    thr = pd.Series([r.get("blas_threads") for r in done.values()]).value_counts(dropna=False).to_dict()
    print(f"CPU per search: mean {cpu.mean():.1f}s, median {np.median(cpu):.1f}s, max {cpu.max():.1f}s, total {cpu.sum():.0f}s "
          f"| OPENBLAS_NUM_THREADS seen by workers: {thr}")
    A, B, guards_e = e_columns(state["A"], state["B"], eres)
    rt = dict(state["rt"])
    for r in done.values():
        if r.get("rt_log1p"):
            R1.rt_add(rt, "E2_log1p", r["rt_log1p"])
    P = pd.read_csv(R1.PREDS_PLUS)
    P["month"] = P.month.astype(str).str[:7]
    ok_a = R1.identity_a(A, P)
    ok_b, Rb = R1.identity_b(fr, series_b, targets, B)
    ok_d1 = d1_check(A, B, cache)
    ok_rt = not any(v["fail"] for v in rt.values())
    v = rt["E2_log1p"]
    print(f"ROUND TRIP: {len(rt)} chains/transforms, {sum(x['n'] for x in rt.values())} series, E2 log1p step "
          f"{v['n']} series max_abs={v['abs']:.3g} over_tol={v['fail']}")
    br = breach_table(A, B)
    print(f"10x check with E: above 10x historical max={int(br.above_10x_hist_max.sum())}, "
          f"below -10x largest return={int(br.below_minus_10x_largest_return.sum())} | E guards/fallbacks {guards_e}")
    print(f"\nCHECKS: identity A {'PASS' if ok_a else 'FAIL'} | identity B {'PASS' if ok_b else 'FAIL'} | "
          f"D1 reproduction {'PASS' if ok_d1 else 'FAIL'} | round trip {'PASS' if ok_rt else 'FAIL'} | {time.time()-t0:.0f}s")
    full = dict(state, A=A, B=B, Rb=Rb, rt=rt, breaches=br, guards_e=guards_e, arima_cpu=cpu)
    pd.to_pickle(full, os.path.join(cache, "p2_state.pkl"))
    if not (ok_a and ok_b and ok_d1 and ok_rt):
        raise SystemExit("STOP: a correctness gate failed; nothing scored")
    score(full, fr, d, keys, cache, t0)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--stage", choices=("precheck", "full", "no_arima", "arima", "score", "score_no_arima"), required=True)
    args = ap.parse_args()
    t0 = time.time()
    global SPECS
    no_e = args.stage in ("no_arima", "score_no_arima")      # groups A-D + controls; E left for a separate run
    if no_e:
        SPECS = [s for s in SPECS if s["group"] != "E"]
    state_file = os.path.join(args.cache, "p2_state_noE.pkl" if no_e else "p2_state.pkl")
    fr = pd.read_csv(R1.FIT_REVIEW)
    keys = sorted(int(k) for k in fr.product_key)
    d = R1.load_demand(args.cache, keys)                     # phase 1's read-only SELECT, cached
    R1.demand_checks(d)
    print(f"columns per harness={len(set(s['col'] for s in SPECS))} (expected {80 if no_e else 83}) | new candidates="
          f"{sum(s['group'] in 'ABCDE' for s in SPECS)} (expected {74 if no_e else 77}) | scored cells per harness="
          f"{sum(len(s['bins']) for s in SPECS)} (expected {196 if no_e else 201})")
    if args.stage in ("score", "score_no_arima"):
        score(pd.read_pickle(state_file), fr, d, keys, args.cache, t0)
        return

    series_a, meta_all, periods, ix = R1.build_a(d, keys)
    meta_a = meta_all[meta_all.bin != "insufficient"].reset_index(drop=True)
    series_b = R1.build_b(d, keys)
    targets = R1.scored_b(fr, series_b)
    if args.stage == "arima":
        arima_stage(fr, d, keys, args.cache, series_a, meta_a, series_b, targets, t0)
        return
    jobs_a =[(pk, *series_a[pk], list(zip(g.ntr.tolist(), g.bin.tolist()))) for pk, g in meta_a.groupby("pk")]
    jobs_b = [(pk, series_b[pk], b, present) for pk, b, present in targets]
    per_a, rt_a, fails_a, dsel_a = run_pool(a_worker, jobs_a, "A per-SKU")
    per_b, rt_b, fails_b, dsel_b = run_pool(b_worker, jobs_b, "B per-SKU")
    print(f"per-SKU done {time.time()-t0:.0f}s", flush=True)
    rt = {**{f"A:{k}": v for k, v in rt_a.items()}, **{f"B:{k}": v for k, v in rt_b.items()}}
    if args.stage == "precheck":
        for k in sorted(rt):
            v = rt[k]
            print(f"  RT {k:<24} series={v['n']:>5} max_abs={v['abs']:.3g} over_tol={v['fail']}{'  <-- FAIL' if v['fail'] else ''}")
        ff = pd.Series(fails_a).rename("A").to_frame().join(pd.Series(fails_b).rename("B"), how="outer").fillna(0).astype(int)
        print("skips / fit failures (name, bin, reason):\n" + ff.to_string())
        print(f"ROUND TRIP {'PASS' if not any(v['fail'] for v in rt.values()) else 'FAIL'} | {time.time()-t0:.0f}s")
        return

    xv_a, rt_xa, cnt_xa = R1.xgb_a(series_a, periods, ix, XGB_SET)
    xv_b, rt_xb, cnt_xb = R1.xgb_b(series_b, targets, XGB_SET)
    rt.update({f"A:xgb_{k}": v for k, v in rt_xa.items()})
    rt.update({f"B:xgb_{k}": v for k, v in rt_xb.items()})
    print(f"XGBoost done {time.time()-t0:.0f}s", flush=True)

    eres = {}
    if not no_e:
        ejobs = [(("A", r.pk, r.ti), series_a[r.pk][0][:r.ntr], r.bin == "long")
                 for r in meta_a.itertuples(index=False) if r.ntr >= MIN_DIFF]
        from analytics.forecasting.global_model import from_first_sale
        for pk, b, present in targets:
            s = series_b[pk]
            for m in present:
                h = s[s.index < m]
                h = from_first_sale(h) if len(from_first_sale(h)) else h
                if len(h) >= MIN_DIFF:
                    ejobs.append((("B", pk, m), h.to_numpy(dtype=float), b == "long"))
        print(f"ARIMA jobs={len(ejobs)}", flush=True)
        eres = run_e(ejobs, t0)
        print(f"ARIMA done {time.time()-t0:.0f}s", flush=True)

    A, guards_a = assemble_a(meta_a, per_a, xv_a, eres)
    B, guards_b = assemble_b(per_b, xv_b, eres)
    P = pd.read_csv(R1.PREDS_PLUS)
    P["month"] = P.month.astype(str).str[:7]
    ok_a = R1.identity_a(A, P)
    ok_b, Rb = R1.identity_b(fr, series_b, targets, B)
    ok_d1 = d1_check(A, B, args.cache)
    print("\nROUND TRIP (phase 1 rules):")
    for k in sorted(rt):
        v = rt[k]
        if v["fail"] or k.split(":")[-1] in ("identity", "xgb_identity"):
            print(f"  {k:<28} series={v['n']:>6} max_abs={v['abs']:.3g} over_tol={v['fail']}{'  <-- FAIL' if v['fail'] else ''}")
    ok_rt = not any(v["fail"] for v in rt.values())
    print(f"  {len(rt)} chains/transforms checked, {sum(v['n'] for v in rt.values())} series, "
          f"worst max_abs={max(v['abs'] for v in rt.values()):.3g}")
    br, sk = breach_table(A, B), skip_table(A, B)
    dsel = pd.DataFrame(dsel_a + dsel_b, columns=["pk", "when", "bin", "d"])
    print("\nskips by history length:\n" + sk.to_string(index=False))
    print(f"\n10x check: forecasts above 10x historical max={int(br.above_10x_hist_max.sum())}, "
          f"below -10x largest return={int(br.below_minus_10x_largest_return.sum())}")
    print(f"\nCHECKS: identity A {'PASS' if ok_a else 'FAIL'} | identity B {'PASS' if ok_b else 'FAIL'} | "
          f"D1 reproduction {'PASS' if ok_d1 else 'FAIL'} | round trip {'PASS' if ok_rt else 'FAIL'} | {time.time()-t0:.0f}s")
    state = dict(A=A, B=B, Rb=Rb, rt=rt, fails_a=fails_a, fails_b=fails_b, guards_a=guards_a, guards_b=guards_b,
                 cnt_xa=cnt_xa, cnt_xb=cnt_xb, breaches=br, skips=sk, dsel=dsel)
    pd.to_pickle(state, state_file)
    if not (ok_a and ok_b and ok_d1 and ok_rt):
        raise SystemExit("STOP: a correctness gate failed; predictions saved to the cache, nothing scored")
    score(state, fr, d, keys, args.cache, t0)


if __name__ == "__main__":
    main()
