"""
reports/experiments/error_hunt_2026-11-10/hunt.py - every lead of the 2026-11-10 "lower the error by any means" brief, on
one frame. BACKTEST ONLY: reads the throwaway copy ssm_challenger (127.0.0.1:55432) through ../error_reduction_2026-11-10/
lab.py (READ ONLY, refuses any other server). Writes per-product rows to the git-ignored local/ (hard rule 9) and the
aggregate table here.

    python reports/experiments/error_hunt_2026-11-10/hunt.py

FRAME: the 4,370 as-served product-months of lab.py (Tier A the month before, 2024-01..2026-02). Base = S1, the forecast
served since 2026-11-10 (router + calendar factor + succession + fading). Every candidate is computed at month t from the
product's (or the aggregate's) history strictly before t, and multiplied by t's calendar factor as served is, unless its
name ends in _nocal. Scoring: lab.table (pooled WAPE and MASE lead, MAPE beside, MASE scale fixed on 2023-01..2025-08 per
product, the same in both windows), both windows, all products and planned products (lp_run 7's 110), December and January
lines, 95% product-bootstrap interval of the pooled WAPE difference against S1. Verdict per lab.gate, fixed before scoring.

Names of candidates (all point forecasts in pieces unless stated):
  naive, ma3, ma6, ma12, med3, med6           simple levels
  ses2, ses4, holtd                           exponential smoothing; Holt with damped trend (alpha .3, beta .1, phi .9)
  croston, sba, tsb                           intermittent: Croston (alpha .1), Syntetos-Boylan, Teunter-Syntetos-Babai
  wboot                                       Willemain bootstrap mean (occurrence Markov chain + jittered sizes, 500 draws)
  ma3_clip, S1_clip, S1_clip2                 spike damping: history capped at median + 3 MAD of the last 12 (clip2 also
                                              lifts lows to median - 3 MAD); S1 scaled by MA3(clean)/MA3(raw)
  peso_ma3                                    MA3 of the product's PESOS divided by its last-3-month price per piece
  grp_ma3, grp_ses, grp_S1mix                 flavour groups (brand x category x first two words x pack token): group total
                                              forecast x product's share of the last 6 months; grp_S1mix = mean with S1
  S1_td_pcs, S1_td_peso                       S1 x company growth factor (company YoY forecast / company MA3), in pieces or
                                              in pesos; fall back to 1 before 2024-04
  S1_seas, ma3_seas                           x company month index from earlier years only (shrunk halfway to 1)
  S1_bias_p, S1_bias_c                        S1 x trailing actual/S1 ratio, per product (last 6 frame months, >= 3, shrunk
                                              halfway, clipped .5..1.5) or company (last 3 months, clipped .8..1.2)
  S1_nocal                                    S1 without the calendar factor
  mint_struct, mint_wls                       hierarchical reconciliation (product -> flavour group -> brand x category ->
                                              total over the month's frame products): base S1 at the bottom, SES at every
                                              aggregate; structural or variance (WLS, trailing MSE) weights
  ens_inv, ens_best, ens_eq                   adaptive ensemble over {S1, ma3, ses4, med3, grp_ses, holtd}: weights 1/MAE
                                              over the product's last 6 months; or the single best of the last 6; or equal
  S1_mapa_gate                                temporal aggregation (MAPA k=1,2,3,4,6, SES .3) where the product failed the
                                              MASE gate (trailing served MASE >= 1), S1 elsewhere
  ORACLE_c3, ORACLE_lvl                       NOT FORECASTS: centred mean of t-1, t, t+1 actuals; the product's mean over the
                                              scored window. The error left when the level is known: a floor.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "error_reduction_2026-11-10"))
import lab  # noqa: E402

C = lab.C
OUT_ROWS = lab.LOCAL / "error_hunt_rows_2026-11-10.pkl"
RNG = np.random.default_rng(20261110)


# ---------------------------------------------------------------- methods on a history array (NaN = blank, dropped)
def _x(h):
    x = np.asarray(h, float)
    return x[~np.isnan(x)]


def ma(x, n):
    return float(np.mean(x[-n:])) if len(x) else np.nan


def med(x, n):
    return float(np.median(x[-n:])) if len(x) else np.nan


def ses(x, a):
    if not len(x):
        return np.nan
    lv = x[0]
    for v in x[1:]:
        lv += a * (v - lv)
    return float(lv)


def holtd(x, a=0.3, b=0.1, phi=0.9):
    if len(x) < 3:
        return ma(x, 3)
    lv, tr = x[0], x[1] - x[0]
    for v in x[1:]:
        pl = lv
        lv = a * v + (1 - a) * (lv + phi * tr)
        tr = b * (lv - pl) + (1 - b) * phi * tr
    return float(max(lv + phi * tr, 0.0))


def croston(x, a=0.1, sba=False):
    nz = np.flatnonzero(x > 0)
    if not len(nz):
        return 0.0
    z, p, last = x[nz[0]], float(nz[0] + 1), nz[0]
    for i in nz[1:]:
        z += a * (x[i] - z)
        p += a * ((i - last) - p)
        last = i
    f = z / p
    return float(f * (1 - a / 2) if sba else f)


def tsb(x, a=0.1, b=0.1):
    nz = np.flatnonzero(x > 0)
    if not len(nz):
        return 0.0
    z, pr = x[nz[0]], 1.0
    for v in x[nz[0] + 1:]:
        pr += b * ((v > 0) - pr)
        if v > 0:
            z += a * (v - z)
    return float(z * pr)


def wboot(x, draws=500):
    if len(x) < 3:
        return ma(x, 3)
    occ = x > 0
    if occ.all():
        sizes = x
        js = sizes[RNG.integers(0, len(sizes), draws)]
        js = np.maximum(js + RNG.normal(0, 1, draws) * np.sqrt(js), 0)
        return float(js.mean())
    p11 = (occ[1:] & occ[:-1]).sum() / max(occ[:-1].sum(), 1)
    p01 = (occ[1:] & ~occ[:-1]).sum() / max((~occ[:-1]).sum(), 1)
    p = p11 if occ[-1] else p01
    sizes = x[occ]
    js = sizes[RNG.integers(0, len(sizes), draws)]
    js = np.maximum(js + RNG.normal(0, 1, draws) * np.sqrt(js), 0)
    return float(p * js.mean())


def clean(x, low=False):
    if len(x) < 6:
        return x
    w = x[-12:]
    m = np.median(w)
    mad = 1.4826 * np.median(np.abs(w - m))
    if mad == 0:
        return x
    y = np.minimum(x, m + 3 * mad)
    return np.maximum(y, m - 3 * mad) if low else y


def mapa(h, ks=(1, 2, 3, 4, 6), a=0.3):
    h = np.asarray(h, float)
    out = []
    for k in ks:
        n = (len(h) // k) * k
        if n < 2 * k:
            continue
        with np.errstate(invalid="ignore"):
            b = np.nanmean(h[-n:].reshape(-1, k), axis=1) * k
        b = b[~np.isnan(b)]
        if len(b) >= 2:
            out.append(ses(b, a) / k)
    return float(np.mean(out)) if out else np.nan


# ---------------------------------------------------------------- data
def load():
    F = lab.load()
    meta, demand, W = F["meta"], F["demand"], F["W"]
    pes = demand.assign(t=pd.to_datetime(demand.calendar_month + "-01")).pivot_table(
        index="t", columns="product_key", values="net_amount", aggfunc="sum").reindex(W.index)
    keys = meta.index.intersection(W.columns)
    gk = {}
    for k in keys:
        name = str(meta.at[k, "name"]).upper()
        words = re.sub(r"[^A-Z0-9 ]", " ", name).split()
        gk[k] = f"{meta.at[k, 'brand']}|{meta.at[k, 'cat']}|{' '.join(words[:2])}|{C.pack_token(name)}"
    gk = pd.Series(gk)
    # lp_run 7's 110 planned products: keys from a READ ONLY run_lp --dry-run on live (switch off), which reproduced
    # lp_run 7 exactly (110 rows, 419,344 pieces); the throwaway copy holds lp_run 6 (109).
    plan = set(json.loads((lab.LOCAL / "lp_run7_planned_keys_2026-11-10.json").read_text())["product_keys"])
    F.update(pes=pes, gk=gk, plan7=plan)
    return F


# ---------------------------------------------------------------- per-row candidates
def row_candidates(F, k, t, cal):
    W, pes, gk = F["W"], F["pes"], F["gk"]
    hs = lab.hist(W[k], t)
    x = _x(hs.to_numpy())
    r = {}
    if len(x) == 0:
        return r
    r["naive"] = x[-1]
    for n in (3, 6, 12):
        r[f"ma{n}"] = ma(x, n)
    r["med3"], r["med6"] = med(x, 3), med(x, 6)
    r["ses2"], r["ses4"] = ses(x, 0.2), ses(x, 0.4)
    r["holtd"] = holtd(x)
    r["croston"], r["sba"], r["tsb"] = croston(x), croston(x, sba=True), tsb(x)
    r["wboot"] = wboot(x)
    xc, xc2 = clean(x), clean(x, low=True)
    r["ma3_clip"] = ma(xc, 3)
    r["_clipratio"] = (ma(xc, 3) / r["ma3"]) if r["ma3"] > 0 else 1.0
    r["_clipratio2"] = (ma(xc2, 3) / r["ma3"]) if r["ma3"] > 0 else 1.0
    # pesos -> pieces
    ph = pes[k][pes.index < t].dropna()
    q3, p3 = W[k][W.index < t].iloc[-3:].fillna(0).sum(), ph.iloc[-3:].sum() if len(ph) else 0
    r["peso_ma3"] = (ph.iloc[-3:].mean() / (p3 / q3)) if (q3 > 0 and p3 > 0) else r["ma3"]
    # flavour group
    members = gk.index[gk == gk.get(k)]
    G = W[members][W.index < t].fillna(0).sum(axis=1)
    own = W[k][W.index < t].fillna(0)
    sh = own.iloc[-6:].sum() / G.iloc[-6:].sum() if G.iloc[-6:].sum() > 0 else 1.0
    g = _x(G.loc[G.index >= hs.index[0]].to_numpy()) if len(hs) else np.array([])
    r["grp_ma3"] = ma(g, 3) * sh if len(g) else r["ma3"]
    r["grp_ses"] = ses(g, 0.4) * sh if len(g) else r["ses4"]
    r["_grpsize"] = len(members)
    # temporal aggregation
    r["mapa"] = mapa(hs.to_numpy())
    for c in list(r):
        if not c.startswith("_"):
            r[c] = max(float(r[c]), 0.0) * cal if np.isfinite(r[c]) else np.nan
    return r


def company(F):
    W, pes = F["W"], F["pes"]
    T = W.fillna(0).sum(axis=1)
    P = pes.fillna(0).sum(axis=1)
    out = {}
    for t in W.index:
        i = W.index.get_loc(t)
        rec = {}
        for nm, S in (("pcs", T), ("peso", P)):
            if i >= 15:
                yoy = S.iloc[i - 12] * S.iloc[i - 3:i].mean() / S.iloc[i - 15:i - 12].mean()
                rec[f"g_{nm}"] = yoy / S.iloc[i - 3:i].mean()
            else:
                rec[f"g_{nm}"] = 1.0
        # month index: same calendar month in earlier years vs its prior 3 months, pieces, shrunk halfway
        idx = [T.iloc[j] / T.iloc[j - 3:j].mean() for j in range(i - 12, -1, -12) if j >= 3]
        rec["seas"] = 1 + 0.5 * (np.mean(idx) - 1) if idx else 1.0
        out[t] = rec
    return pd.DataFrame(out).T


# ---------------------------------------------------------------- hierarchical reconciliation
def mint(F, rows):
    """Per month: bottom = frame products (base S1), aggregates = flavour group, brand x category, total (base SES .4 x cal).
    Variance weights: trailing 12-month MSE of each node's base one-step error (bottom: S1's earlier frame rows, else MA3's)."""
    W, gk, meta = F["W"], F["gk"], F["meta"]
    out_s, out_w = {}, {}
    rows = rows.set_index(["product_key", "t"])
    for t, R in rows.groupby(level="t"):
        ks = [k for k, _ in R.index]
        cal = float(R.cal.median())
        nodes = [("total", ks)]
        for lvl, key in (("grp", lambda k: gk.get(k)), ("bc", lambda k: f"{meta.at[k, 'brand']}|{meta.at[k, 'cat']}")):
            d = {}
            for k in ks:
                d.setdefault(key(k), []).append(k)
            nodes += [(f"{lvl}:{n}", m) for n, m in d.items() if len(m) > 1]
        nb = len(ks)
        S = np.vstack([np.isin(ks, m).astype(float) for _, m in nodes] + [np.eye(nb)])
        H = W[ks][W.index < t].fillna(0)
        yhat, var = [], []
        for _, m in nodes:
            s = H[m].sum(axis=1).to_numpy()
            s = s[np.argmax(s > 0):] if (s > 0).any() else s
            yhat.append(ses(s, 0.4) * cal)
            errs = [s[j] - ses(s[:j], 0.4) for j in range(max(3, len(s) - 12), len(s))]
            var.append(np.mean(np.square(errs)) if errs else np.nan)
        for k in ks:
            yhat.append(R.loc[(k, t), "S1"])
            prev = rows.loc[k] if k in rows.index.get_level_values(0) else None
            e = []
            if prev is not None:
                p = prev[prev.index < t].iloc[-12:]
                e = (p.S1 - p.actual).to_numpy()
            if len(e) >= 4:
                var.append(np.mean(np.square(e)))
            else:
                s = H[k].to_numpy()
                ee = [s[j] - ma(s[:j], 3) for j in range(max(3, len(s) - 12), len(s))]
                var.append(np.mean(np.square(ee)) if ee else np.nan)
        yhat, var = np.array(yhat, float), np.array(var, float)
        var = np.where(~np.isfinite(var) | (var <= 0), np.nanmedian(var[var > 0]) if (var > 0).any() else 1.0, var)
        for nm, w in (("struct", S.sum(axis=1)), ("wls", var)):
            Wi = 1.0 / w
            A = S.T * Wi
            P = np.linalg.solve(A @ S, A @ yhat)
            for k, v in zip(ks, P):
                (out_s if nm == "struct" else out_w)[(k, t)] = max(v, 0.0)
    rows = rows.reset_index()
    rows["mint_struct"] = [out_s.get((k, t), np.nan) for k, t in zip(rows.product_key, rows.t)]
    rows["mint_wls"] = [out_w.get((k, t), np.nan) for k, t in zip(rows.product_key, rows.t)]
    return rows


# ---------------------------------------------------------------- build all
def build(F):
    rows = F["rows"].copy()
    W = F["W"]
    calm = rows.groupby("t").cal.median()
    co = company(F)
    # candidates on the frame and on a wider panel (same products, every month from 2023-07) for trailing weights
    keys = rows.product_key.unique()
    panel = []
    for k in keys:
        for t in W.index[W.index >= "2023-07-01"]:
            cal = float(calm.get(t, 1.0))
            r = row_candidates(F, k, t, cal)
            if r:
                r.update(product_key=k, t=t, actual_p=W.at[t, k])
                panel.append(r)
    panel = pd.DataFrame(panel)
    rows = rows.drop(columns=[c for c in panel.columns if c in rows.columns and c not in ("product_key", "t")])
    rows = rows.merge(panel.drop(columns=["actual_p"]), on=["product_key", "t"], how="left")
    rows = rows.merge(co, left_on="t", right_index=True, how="left")
    rows["S1_nocal"] = rows.S1 / rows.cal
    rows["S1_clip"] = rows.S1 * rows._clipratio
    rows["S1_clip2"] = rows.S1 * rows._clipratio2
    rows["grp_S1mix"] = 0.5 * (rows.S1 + rows.grp_ses)
    rows["S1_td_pcs"] = rows.S1 * rows.g_pcs
    rows["S1_td_peso"] = rows.S1 * rows.g_peso
    rows["S1_td_peso_half"] = 0.5 * (rows.S1 + rows.S1_td_peso)
    rows["S1_seas"] = rows.S1 * rows.seas
    rows["ma3_seas"] = rows.ma3 * rows.seas
    rows["S1_mapa_gate"] = np.where(rows.trail_mase >= 1, rows.mapa.fillna(rows.S1), rows.S1)
    rows["S1_mapa_gate_mix"] = np.where(rows.trail_mase >= 1, 0.5 * (rows.S1 + rows.mapa.fillna(rows.S1)), rows.S1)
    # bias corrections, strictly from earlier months
    rows = rows.sort_values(["product_key", "t"]).reset_index(drop=True)
    bp = []
    for _, g in rows.groupby("product_key", sort=False):
        a, f = g.actual.to_numpy(), g.S1.to_numpy()
        tt = g.t.to_numpy()
        for i in range(len(g)):
            sel = (tt < tt[i]) & (tt >= tt[i] - np.timedelta64(200, "D"))
            sa, sf = a[sel].sum(), f[sel].sum()
            bp.append(np.clip(1 + 0.5 * (sa / sf - 1), 0.5, 1.5) if (sel.sum() >= 3 and sf > 0) else 1.0)
    rows["S1_bias_p"] = rows.S1 * np.array(bp)
    agg = rows.groupby("t")[["actual", "S1"]].sum()
    ratio = {t: np.clip(agg.loc[(agg.index < t)].iloc[-3:].actual.sum() / agg.loc[(agg.index < t)].iloc[-3:].S1.sum(), 0.8, 1.2)
             if (agg.index < t).sum() >= 3 else 1.0 for t in agg.index}
    rows["S1_bias_c"] = rows.S1 * rows.t.map(ratio)
    # adaptive ensemble: trailing 6 months of each pool member, from the frame (S1) and the panel (the rest)
    pool = ["S1", "ma3", "ses4", "med3", "grp_ses", "holtd"]
    pan = panel.set_index(["product_key", "t"])
    s1 = rows.set_index(["product_key", "t"])[["S1", "actual"]]
    inv, best, eq = [], [], []
    for r in rows.itertuples():
        past = [r.t - pd.DateOffset(months=j) for j in range(1, 7)]
        errs = {m: [] for m in pool}
        for p in past:
            if (r.product_key, p) not in s1.index or (r.product_key, p) not in pan.index:
                continue
            a = s1.at[(r.product_key, p), "actual"]
            if not np.isfinite(a):
                continue
            errs["S1"].append(abs(s1.at[(r.product_key, p), "S1"] - a))
            for m in pool[1:]:
                errs[m].append(abs(pan.at[(r.product_key, p), m] - a))
        vals = np.array([getattr(r, m) for m in pool], float)
        ok = np.isfinite(vals)
        eq.append(np.nanmean(vals))
        if len(errs["S1"]) >= 3:
            mae = np.array([np.mean(errs[m]) for m in pool])
            w = np.where(ok, 1.0 / np.maximum(mae, 1e-6), 0)
            inv.append(float((w * np.nan_to_num(vals)).sum() / w.sum()))
            best.append(float(vals[np.nanargmin(np.where(ok, mae, np.inf))]))
        else:
            inv.append(r.S1)
            best.append(r.S1)
    rows["ens_inv"], rows["ens_best"], rows["ens_eq"] = inv, best, eq
    rows = mint(F, rows)
    # oracles (use the future: a floor, not a forecast)
    Wf = W.fillna(np.nan)
    c3 = []
    for r in rows.itertuples():
        i = W.index.get_loc(r.t)
        win = Wf[r.product_key].iloc[max(i - 1, 0):i + 2]
        c3.append(float(np.nanmean(win)))
    rows["ORACLE_c3"] = c3
    rows["ORACLE_lvl"] = np.nan
    for (a, b) in lab.WINDOWS.values():
        m = (rows.month >= a) & (rows.month <= b)
        rows.loc[m, "ORACLE_lvl"] = rows[m].groupby("product_key").actual.transform("mean")
    return rows, panel


METHODS = ["naive", "ma3", "ma6", "ma12", "med3", "med6", "ses2", "ses4", "holtd", "croston", "sba", "tsb", "wboot",
           "ma3_clip", "S1_clip", "S1_clip2", "peso_ma3", "grp_ma3", "grp_ses", "grp_S1mix", "S1_td_pcs", "S1_td_peso",
           "S1_td_peso_half", "S1_seas", "ma3_seas", "S1_bias_p", "S1_bias_c", "S1_nocal", "mint_struct", "mint_wls",
           "ens_inv", "ens_best", "ens_eq", "mapa", "S1_mapa_gate", "S1_mapa_gate_mix", "ORACLE_c3", "ORACLE_lvl"]


def main() -> int:
    F = load()
    if OUT_ROWS.exists() and "--rebuild" not in sys.argv:
        rows = pd.read_pickle(OUT_ROWS)
        if "naive_y" in rows:                       # first build merged onto the frame's own 'naive' column
            rows = rows.rename(columns={"naive_y": "naive"}).drop(columns=["naive_x"])
            pd.to_pickle(rows, OUT_ROWS)
    else:
        rows, panel = build(F)
        pd.to_pickle(rows, OUT_ROWS)
        pd.to_pickle(panel, lab.LOCAL / "error_hunt_panel_2026-11-10.pkl")
    for m in METHODS:
        rows[m] = rows[m].fillna(rows.S1)
    t = lab.table(rows, ["served", "S1"] + METHODS, F["sc"], F["plan7"], bases=("S1",))
    t.to_csv(HERE / "results_hunt.csv", index=False)
    verdict = {m: {s: lab.gate(t, m, "S1", s) for s in ("all", "planned")} for m in METHODS + ["served"]}
    (HERE / "results_hunt_verdicts.json").write_text(json.dumps(verdict, indent=1))
    print(lab.show(t, "S1"))
    print(json.dumps(verdict, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
