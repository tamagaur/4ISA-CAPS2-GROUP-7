"""Phase B: per-SKU 80/20 rolling-origin 1-step bake-off, real-only, all 17 models refit. No DB."""
import os, sys, pickle, time, warnings
import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor

warnings.simplefilter("ignore")
REPO = r"C:\Users\kyuan\Capstone-Project"
sys.path.insert(0, REPO)
OUT = os.path.dirname(os.path.abspath(__file__))
MIN_TRAIN = 3


def run_sku(args):
    pk, qty = args
    warnings.simplefilter("ignore")
    from scripts.model_bakeoff import MODELS, GUARDED
    from analytics.forecasting.diagnostic_metrics import wape, smape, mase, naive_scale
    from analytics.segmentation.traits import from_first_sale
    x = from_first_sale(np.asarray(qty, float))
    n = len(x)
    ntr = int(np.floor(0.7 * n))
    nte = n - ntr
    base = dict(pk=pk, n=n, ntr=ntr, nte=nte)
    if ntr < MIN_TRAIN or nte < 1:
        return [dict(base, model=m, fittable=False, guarded=0, wape=np.nan, smape=np.nan, mase=np.nan)
                for m in MODELS]
    actual = x[ntr:]
    scale = naive_scale(x[:ntr])
    rows = []
    for name, fn in MODELS.items():
        raw, guarded = [], 0
        for t in range(ntr, n):
            tr = x[:t]
            try:
                f = float(fn(tr))
            except Exception:
                f = np.nan
            raw.append(f)
        raw = np.array(raw, float)
        fittable = bool(np.isfinite(raw).all())
        preds = raw.copy()
        if name in GUARDED:
            for i, t in enumerate(range(ntr, n)):
                if np.isfinite(preds[i]) and preds[i] > x[:t].max():
                    preds[i] = np.nan
                    guarded += 1
        if np.isfinite(preds).all():
            preds = np.maximum(preds, 0.0)
            r = dict(wape=wape(actual, preds), smape=smape(actual, preds), mase=mase(actual, preds, scale))
        else:
            r = dict(wape=np.nan, smape=np.nan, mase=np.nan)
        rows.append(dict(base, model=name, fittable=fittable, guarded=guarded, **r))
    return rows


if __name__ == "__main__":
    d = pickle.load(open(os.path.join(OUT, "a.pkl"), "rb"))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=14) as ex:
        res = list(ex.map(run_sku, [(pk, d["m26"][pk]) for pk in d["cohort"]], chunksize=2))
    df = pd.DataFrame([r for rows in res for r in rows])
    df["bin"] = df["pk"].map({pk: v["bin"] for pk, v in d["b26"].items()})
    df.to_pickle(os.path.join(OUT, "b70.pkl"))
    print(f"done {time.time() - t0:.0f}s rows={len(df)} (expected {132 * 17}) SKUs={df.pk.nunique()}")
    print("inf in metrics:", int(np.isinf(df[["wape", "smape", "mase"]]).sum().sum()))
