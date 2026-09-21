"""DIAGNOSTIC ONLY: same bake-off, synthetic 2021-22 prefix added as TRAINING context. No DB."""
import os, sys, pickle, time, warnings
import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
warnings.simplefilter("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
REPO = r"C:\Users\kyuan\Capstone-Project"; sys.path.insert(0, REPO)
OUT = os.path.dirname(os.path.abspath(__file__))

def run_sku(args):
    pk, qty, pre, arm = args
    warnings.simplefilter("ignore")
    from scripts.model_bakeoff import MODELS, GUARDED
    from analytics.forecasting.diagnostic_metrics import wape, smape, mase, naive_scale
    qty = np.asarray(qty, float); fs = int(np.nonzero(qty > 0)[0][0]); x = qty[fs:]
    n = len(x); ntr = int(np.floor(0.8 * n)); nte = n - ntr
    if len(pre):
        prefix = np.concatenate([pre, np.zeros(fs)]) if arm == "A" else pre
    else:
        prefix = np.zeros(0)
    base = dict(pk=pk, arm=arm, n=n, ntr=ntr, nte=nte, pre=len(pre))
    if ntr < 3 or nte < 1:
        return [dict(base, model=m, fittable=False, wape=np.nan, smape=np.nan, mase=np.nan) for m in MODELS]
    actual = x[ntr:]; scale = naive_scale(x[:ntr]); rows = []
    for name, fn in MODELS.items():
        preds = []
        for t in range(ntr, n):
            tr = np.concatenate([prefix, x[:t]])
            try: f = float(fn(tr))
            except Exception: f = np.nan
            preds.append((f, tr.max()))
        raw = np.array([p[0] for p in preds]); fittable = bool(np.isfinite(raw).all())
        if name in GUARDED:
            raw = np.array([np.nan if (np.isfinite(f) and f > mx) else f for f, mx in preds])
        if np.isfinite(raw).all():
            p = np.maximum(raw, 0.0)
            r = dict(wape=wape(actual, p), smape=smape(actual, p), mase=mase(actual, p, scale))
        else:
            r = dict(wape=np.nan, smape=np.nan, mase=np.nan)
        rows.append(dict(base, model=name, fittable=fittable, **r))
    return rows

if __name__ == "__main__":
    d = pickle.load(open(os.path.join(OUT, "a.pkl"), "rb")); s = pickle.load(open(os.path.join(OUT, "synth.pkl"), "rb"))
    s = s[s.month <= "2022-12"]; print("pre rows used:", len(s), "(expected 1954)")
    grid = [str(p) for p in pd.period_range("2021-01", "2022-12", freq="M")]; gi = {m: i for i, m in enumerate(grid)}
    pre = {}
    for pk, g in s.groupby("pk"):
        v = np.zeros(24)
        for m, q in zip(g.month, g.q): v[gi[m]] += q
        i0, i1 = gi[g.month.min()], gi[g.month.max()]
        pre[pk] = (v[i0:], v[i0:i1 + 1])          # A: through 2022-12 (calendar-true) | B: synthetic months only
    jobs = [(pk, d["m26"][pk], pre.get(pk, (np.zeros(0),) * 2)[0 if arm == "A" else 1], arm) for arm in "AB" for pk in d["cohort"]]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=14) as ex:
        res = list(ex.map(run_sku, jobs, chunksize=2))
    df = pd.DataFrame([r for rows in res for r in rows])
    df["bin"] = df.pk.map({pk: v["bin"] for pk, v in d["b26"].items()})
    df.to_pickle(os.path.join(OUT, "g.pkl"))
    print(f"done {time.time()-t0:.0f}s rows={len(df)} (expected {2*2244}) inf={int(np.isinf(df[['wape','smape','mase']]).sum().sum())}")
