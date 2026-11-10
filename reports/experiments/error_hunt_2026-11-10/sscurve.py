"""
reports/experiments/error_hunt_2026-11-10/sscurve.py - QUANTILES vs POINT + SAFETY STOCK, and SAFETY STOCK THAT FOLLOWS
THE LEVEL. Backtest only; reads hunt.py's rows (local/, git-ignored) and lab.py's frame.

    python reports/experiments/error_hunt_2026-11-10/sscurve.py

Setting (task 3's, kept): monthly review, the month's stock target Q covers that month's sale, zero lead time, lost sales,
no carry-over. For each policy Q = f(history before t; z) and a grid of z, per window x set:
  months short  = share of product-months with actual > Q        (1 - cycle service)
  leftover      = sum max(Q - actual, 0) / sum actual             (stock left, in months of sales)
  shortfall     = sum max(actual - Q, 0) / sum actual             (pieces missed)
Policies compared at MATCHED service: leftover interpolated at months short = 10% (the plan's 90% service level, Z 1.28)
and 5%. Lower leftover at the same service = less money in stock for the same stock-outs.

Policies (point = S1, the served forecast):
  P_full     S1 + z x sd of the whole history before t (what run_lp does: sigma over every month since the first row)
  P_level    S1 + z x sd_full x min(1, S1 / mean of the whole history)   ("safety stock follows the faded level")
  P_level_treated  the same, only on product-months where succession or fading changed the forecast (S1 != served)
  P_sd12     S1 + z x sd of the last 12 months
  P_err      S1 + z x RMSE of the product's own S1 errors (last 12 scored months before t; < 4: of MA3's errors)
  P_relerr   S1 x (1 + z x sd of the relative errors (a - f)/f over the same months)
  Q_emp      S1 x the empirical quantile at level Phi(z) of actual/S1 over the product's last 12 scored months, shrunk to
             the company's ratios with weight n/(n+6) (a direct quantile forecast; the point is only a scale)
  Q_wboot    Willemain bootstrap quantile at Phi(z) (occurrence chain + jittered sizes, 1,000 draws) x calendar factor
  Q_hist     the Phi(z) quantile of the last 12 months x calendar factor (the cover target of task 3)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "error_reduction_2026-11-10"))
import hunt  # noqa: E402
import lab  # noqa: E402

ZS = np.round(np.arange(0.0, 3.01, 0.1), 2)
RNG = np.random.default_rng(20261110)


def features(F, rows, panel):
    W = F["W"]
    pan = panel.set_index(["product_key", "t"])
    rows = rows.sort_values(["product_key", "t"]).reset_index(drop=True)
    out = []
    comp_ratios = {}
    for t, g in rows.groupby("t"):
        comp_ratios[t] = (g.actual / g.S1.where(g.S1 > 0)).dropna().clip(0, 5).to_numpy()
    for k, g in rows.groupby("product_key", sort=False):
        for i, r in enumerate(g.itertuples()):
            h = lab.hist(W[k], r.t).to_numpy(float)
            x = h[~np.isnan(h)]
            prev = g.iloc[:i]
            prev = prev[prev.t >= r.t - pd.DateOffset(months=12)]
            e = (prev.actual - prev.S1).to_numpy()
            rel = ((prev.actual - prev.S1) / prev.S1.where(prev.S1 > 0)).dropna().to_numpy()
            rat = (prev.actual / prev.S1.where(prev.S1 > 0)).dropna().clip(0, 5).to_numpy()
            if len(e) < 4:
                ee = []
                for j in range(1, 13):
                    p = r.t - pd.DateOffset(months=j)
                    if (k, p) in pan.index and np.isfinite(W.at[p, k]):
                        ee.append(W.at[p, k] - pan.at[(k, p), "ma3"] / max(r.cal, 1e-9) * r.cal)
                e = np.array(ee)
            cr = np.concatenate([comp_ratios[p] for p in comp_ratios if r.t - pd.DateOffset(months=12) <= p < r.t]) \
                if any(r.t - pd.DateOffset(months=12) <= p < r.t for p in comp_ratios) else np.array([1.0])
            out.append(dict(product_key=k, t=r.t, sd_full=np.std(x, ddof=1) if len(x) > 1 else np.nan,
                            mean_full=np.mean(x) if len(x) else np.nan,
                            sd12=np.std(x[-12:], ddof=1) if len(x) > 1 else np.nan,
                            rmse=np.sqrt(np.mean(np.square(e))) if len(e) else np.nan,
                            sdrel=np.std(rel, ddof=1) if len(rel) > 1 else np.nan,
                            rat=rat, comp=cr, hist12=x[-12:], hx=x))
    out = pd.DataFrame(out)
    rows = rows.drop(columns=[c for c in out.columns if c in rows.columns and c not in ("product_key", "t")])
    return rows.merge(out, on=["product_key", "t"])


def wboot_q(x, qs, draws=1000):
    if len(x) < 3:
        return np.full(len(qs), np.nan)
    occ = x > 0
    sizes = x[occ] if occ.any() else np.array([0.0])
    if occ.all():
        p = 1.0
    else:
        p11 = (occ[1:] & occ[:-1]).sum() / max(occ[:-1].sum(), 1)
        p01 = (occ[1:] & ~occ[:-1]).sum() / max((~occ[:-1]).sum(), 1)
        p = p11 if occ[-1] else p01
    js = sizes[RNG.integers(0, len(sizes), draws)]
    js = np.maximum(js + RNG.normal(0, 1, draws) * np.sqrt(js), 0) * (RNG.random(draws) < p)
    return np.quantile(js, qs)


def policy_Q(d: pd.DataFrame, z: float) -> dict:
    q = norm.cdf(z)
    S1 = d.S1.to_numpy()
    sdf = d.sd_full.fillna(0).to_numpy()
    lvl = np.minimum(1.0, np.where(d.mean_full > 0, S1 / d.mean_full.to_numpy(), 1.0))
    treated = (d.S1 != d.served).to_numpy()
    out = {"P_full": S1 + z * sdf, "P_level": S1 + z * sdf * lvl, "P_level_treated": S1 + z * sdf * np.where(treated, lvl, 1.0), "P_sd12": S1 + z * d.sd12.fillna(0).to_numpy(),
           "P_err": S1 + z * d.rmse.fillna(d.sd12).fillna(0).to_numpy(),
           "P_relerr": S1 * (1 + z * d.sdrel.fillna(d.sdrel.median()).to_numpy())}
    emp, hq = [], []
    for r in d.itertuples():
        n = len(r.rat)
        own = np.quantile(r.rat, q) if n else np.nan
        comp = np.quantile(r.comp, q)
        w = n / (n + 6)
        emp.append(r.S1 * ((w * own + (1 - w) * comp) if n else comp))
        hq.append(np.quantile(r.hist12, q) * r.cal if len(r.hist12) else r.S1)
    out["Q_emp"], out["Q_hist"] = np.array(emp), np.array(hq)
    out["Q_wboot"] = d[f"wb_{z}"].to_numpy() if f"wb_{z}" in d else np.full(len(d), np.nan)
    return {k: np.maximum(np.nan_to_num(v, nan=0.0), 0) for k, v in out.items()}


def curves(d: pd.DataFrame) -> pd.DataFrame:
    a = d.actual.to_numpy()
    rec = []
    for z in ZS:
        for pol, Q in policy_Q(d, z).items():
            rec.append(dict(policy=pol, z=z, short=float((a > Q).mean()), left=float(np.maximum(Q - a, 0).sum() / a.sum()),
                            shortfall=float(np.maximum(a - Q, 0).sum() / a.sum()),
                            pinball=float(np.mean(np.where(a > Q, norm.cdf(z) * (a - Q), (1 - norm.cdf(z)) * (Q - a))))))
    return pd.DataFrame(rec)


def at_service(c: pd.DataFrame, target: float, by: str = "short") -> dict:
    out = {}
    for pol, g in c.groupby("policy"):
        g = g.sort_values(by)
        if g[by].min() > target or g[by].max() < target:
            out[pol] = None
            continue
        out[pol] = {"leftover": float(np.interp(target, g[by], g.left)),
                    "short": float(np.interp(target, g[by], g.short)),
                    "shortfall": float(np.interp(target, g[by], g.shortfall)),
                    "z": float(np.interp(target, g[by], g.z))}
    return out


def main() -> int:
    F = hunt.load()
    rows = pd.read_pickle(hunt.OUT_ROWS)
    panel = pd.read_pickle(lab.LOCAL / "error_hunt_panel_2026-11-10.pkl")
    d = features(F, rows, panel)
    qs = norm.cdf(ZS)
    wb = np.vstack([wboot_q(h, qs) for h in d.hx]) * d.cal.to_numpy()[:, None]
    for j, z in enumerate(ZS):
        d[f"wb_{z}"] = wb[:, j]
    res = {}
    for wname, (a, b) in lab.WINDOWS.items():
        w = d[(d.month >= a) & (d.month <= b)]
        for sname, sdf in {"all": w, "planned": w[w.product_key.isin(F["plan7"])]}.items():
            c = curves(sdf)
            res[f"{wname} | {sname}"] = {"at_10pct_short": at_service(c, 0.10), "at_5pct_short": at_service(c, 0.05),
                                         "at_3pct_pieces_short": at_service(c, 0.03, "shortfall"),
                                         "at_5pct_pieces_short": at_service(c, 0.05, "shortfall"),
                                         "at_z1.28": {p: {"short": float(np.interp(1.28, g.z, g.short)),
                                                          "leftover": float(np.interp(1.28, g.z, g.left))}
                                                      for p, g in c.groupby("policy")}}
    (HERE / "results_sscurve.json").write_text(json.dumps(res, indent=1))
    for key, v in res.items():
        print("\n==", key)
        print(pd.DataFrame({p: (x or {}) for p, x in v["at_10pct_short"].items()}).T.round(3).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
