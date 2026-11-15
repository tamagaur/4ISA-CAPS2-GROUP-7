"""Calendar adjustment: out-of-sample selection and scoring (protocol: docs/CALENDAR_SELECTION_PROTOCOL_2026-11-16.md).

Reads only cached inputs (no database): local/cal_demand_*.pkl (fetch_demand, read-only) and the as-served panel without a
calendar factor (local/accuracy_as_served_rows.csv, run 'as_served'). Every factor for target month t reads months before t.
Run:  python -I -m scripts.calendar_selection        (prints the protocol hash first; writes local/cal_sel_results.pkl)
"""
from __future__ import annotations

import hashlib
import itertools
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "CALENDAR_SELECTION_PROTOCOL_2026-11-16.md"
SHRINKS = [round(0.1 * i, 1) for i in range(11)]
GRAINS = [("company", 0), ("median", 0), ("own", 1), ("own", 2), ("own", 4)]
FOLDS = {  # name: (choose months, test months)  months as 'YYYY-MM' inclusive ranges
    "T1": (("2024-04", "2025-02"), ("2025-03", "2025-08")),
    "T2": (("2024-04", "2025-08"), ("2025-09", "2026-02")),
    "T3": (("2025-01", "2026-02"), ("2024-04", "2024-12")),
    "FINAL": (("2024-04", "2026-02"), None),
}
LIVE = dict(grain="own", k=2, avg="geo", s=0.5, dec=True, gate="none", linear=True)
NONE = dict(grain="median", k=0, avg="geo", s=0.0, dec=False, gate="none", linear=False)


def load():
    d = pickle.load(open(sorted((ROOT / "local").glob("cal_demand_*.pkl"))[-1], "rb"))
    d = d.dropna(subset=["quantity"])
    t = pd.to_datetime(d.calendar_month + "-01")
    W = d.assign(t=t).pivot_table(index="product_key", columns="t", values="quantity", aggfunc="sum")
    full = pd.date_range(W.columns.min(), "2026-03-01", freq="MS")
    W = W.reindex(columns=full)
    raw = pickle.load(open(sorted((ROOT / "local").glob("cal_demand_*.pkl"))[-1], "rb"))
    comp = raw.groupby("calendar_month")["quantity"].sum(min_count=1).dropna()
    comp.index = pd.to_datetime(comp.index + "-01")
    comp = comp.reindex(full)
    panel = pd.read_csv(ROOT / "local" / "accuracy_as_served_rows.csv")
    panel = panel[panel.run == "as_served"].copy()
    panel["t"] = pd.to_datetime(panel.month + "-01")
    panel = panel.reset_index(drop=True)
    return W, comp, panel


class Calendar:
    """Ratios of month to the mean of its 3 prior months, per product, median and company, all as arrays."""

    def __init__(self, W: pd.DataFrame, comp: pd.Series):
        self.months = list(W.columns)
        self.midx = {m: i for i, m in enumerate(self.months)}
        self.keys = list(W.index)
        self.kidx = {k: i for i, k in enumerate(self.keys)}
        A = W.to_numpy(float)
        n = A.shape[1]
        R = np.full(A.shape, np.nan)
        for j in range(3, n):
            cur, pr = A[:, j], A[:, j - 3:j]
            ok = np.isfinite(cur) & np.isfinite(pr).all(axis=1) & (cur > 0) & (pr > 0).all(axis=1)
            R[ok, j] = cur[ok] / pr[ok].mean(axis=1)
        self.A, self.R = A, R
        self.L = np.log(R)
        self.med = np.array([np.nanmedian(R[:, j]) if np.isfinite(R[:, j]).any() else np.nan for j in range(n)])
        c = comp.to_numpy(float)
        self.comp = np.full(n, np.nan)
        for j in range(3, n):
            pr = c[j - 3:j]
            if np.isfinite(c[j]) and np.isfinite(pr).all() and c[j] > 0 and pr.mean() > 0:
                self.comp[j] = c[j] / pr.mean()

    def earlier(self, t: pd.Timestamp, series: np.ndarray) -> list[int]:
        j = self.midx[t]
        return [j - 12 * y for y in range(1, 5) if j - 12 * y >= 0 and np.isfinite(series[j - 12 * y])]

    def factors(self, t: pd.Timestamp, keys: np.ndarray, cfg: dict) -> tuple[np.ndarray, int]:
        """Factor per product key for target t; (factors, earlier years on the grain's own series)."""
        j = self.midx[t]
        grain, k, avg, s = cfg["grain"], cfg["k"], cfg["avg"], cfg["s"]
        ser = self.comp if grain == "company" else self.med
        ear = self.earlier(t, ser)
        one = np.ones(len(keys))
        if not ear or s == 0 and not cfg["dec"]:
            return one, len(ear)
        red = np.mean if avg == "geo" else np.median
        base = red(np.log(ser[ear]))
        agg = np.full(len(keys), base)
        if grain == "own":
            rows = np.array([self.kidx.get(int(x), -1) for x in keys])
            Lm = np.where(rows[:, None] >= 0, self.L[np.maximum(rows, 0)][:, ear], np.nan)
            n = np.isfinite(Lm).sum(axis=1)
            with np.errstate(all="ignore"):
                own = np.nanmean(Lm, axis=1) if avg == "geo" else np.nanmedian(Lm, axis=1)
            own = np.where(n > 0, own, 0.0)
            w = n / (n + k)
            agg = w * own + (1 - w) * base
        gate = cfg["gate"]
        if gate == "side":
            lg = np.log(ser[ear])
            if not ((lg > 0).all() or (lg < 0).all()):
                agg = np.zeros(len(keys))
        elif gate == "agree":
            ec, em = self.earlier(t, self.comp), self.earlier(t, self.med)
            if not ec or not em:
                agg = np.zeros(len(keys))
            else:
                a, b = red(np.log(self.comp[ec])), red(np.log(self.med[em]))
                if np.sign(a) != np.sign(b):
                    agg = np.zeros(len(keys))
        f = (1.0 + (np.exp(agg) - 1.0) * s) if cfg.get("linear") else np.exp(s * agg)
        if cfg["dec"] and t.month == 12:
            pm = t - pd.DateOffset(years=1)
            if pm in self.midx and np.isfinite(self.med[self.midx[pm]]) and self.med[self.midx[pm]] < 1.0:
                f = np.full(len(keys), self.med[self.midx[pm]])
        return f, len(ear)

    def seasonal_naive(self, t: pd.Timestamp, keys: np.ndarray) -> np.ndarray:
        j = self.midx[t]
        out = np.full(len(keys), np.nan)
        if j - 15 < 0:
            return out
        rows = np.array([self.kidx.get(int(x), -1) for x in keys])
        ok = rows >= 0
        A = self.A[np.maximum(rows, 0)]
        ya, lvl, lvl_ya = A[:, j - 12], A[:, j - 3:j], A[:, j - 15:j - 12]
        good = ok & np.isfinite(ya) & (ya > 0) & np.isfinite(lvl).all(1) & (lvl > 0).all(1) \
            & np.isfinite(lvl_ya).all(1) & (lvl_ya > 0).all(1)
        out[good] = ya[good] * lvl[good].mean(1) / lvl_ya[good].mean(1)
        return out


def window(panel, lo, hi):
    return (panel.month >= lo) & (panel.month <= hi)


def wape(v, a):
    return float(np.abs(v - a).sum() / a.sum())


def build_values(cal: Calendar, panel: pd.DataFrame, cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    F = np.ones(len(panel))
    N = np.zeros(len(panel), int)
    for t, idx in panel.groupby("t").indices.items():
        f, n = cal.factors(t, panel.product_key.to_numpy()[idx], cfg)
        F[idx] = f
        N[idx] = n
    v = np.where(panel.dead.to_numpy(), 0.0, np.maximum(0.0, panel.value_before_dead.to_numpy() * F))
    return v, F, N


def build_sn_values(cal, panel, a):
    SN = np.full(len(panel), np.nan)
    for t, idx in panel.groupby("t").indices.items():
        SN[idx] = cal.seasonal_naive(t, panel.product_key.to_numpy()[idx])
    base = panel.value_before_dead.to_numpy()
    v = np.where(np.isfinite(SN), (1 - a) * base + a * np.nan_to_num(SN), base)
    return np.where(panel.dead.to_numpy(), 0.0, np.maximum(0.0, v))


def grid():
    for (g, k), avg, s, dec, gate in itertools.product(GRAINS, ["geo", "median"], SHRINKS, [False, True], ["none", "side", "agree"]):
        yield dict(grain=g, k=k, avg=avg, s=s, dec=dec, gate=gate, linear=False)


def cfg_key(c):
    return f"{c['grain']}{c['k'] or ''}|{c['avg']}|s={c['s']}|dec={int(c['dec'])}|gate={c['gate']}" + ("|lin" if c.get("linear") else "")


def complexity(c):
    return (c["s"], int(c["dec"]) + int(c["gate"] != "none") + (c["grain"] == "own") * c["k"] * 0 + int(c["grain"] == "own"))


def main():
    h = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    print("protocol sha256", h)
    W, comp, panel = load()
    cal = Calendar(W, comp)
    a = panel.actual.to_numpy(float)
    cands = list(grid())
    vals = {}
    for c in cands + [LIVE, NONE]:
        vals[cfg_key(c)] = build_values(cal, panel, c)
    for aa in SHRINKS:
        vals[f"SN|a={aa}"] = (build_sn_values(cal, panel, aa), None, None)
    pickle.dump(dict(hash=h, keys=list(vals), panel=panel), open(ROOT / "local" / "cal_sel_meta.pkl", "wb"))
    res = {"hash": h, "folds": {}}
    keys_all = [k for k in vals if k not in (cfg_key(LIVE), cfg_key(NONE))]
    for name, (ch, te) in FOLDS.items():
        mc = window(panel, *ch).to_numpy()
        scores = {k: wape(vals[k][0][mc], a[mc]) for k in keys_all}
        best = min(scores.values())
        near = [k for k, v in scores.items() if v <= best + 0.001]
        # simplest within 0.1 WAPE points: smallest s, then fewest parts (shorter key of gates/dec), SN last
        def simp(k):
            if k.startswith("SN"):
                return (float(k.split("=")[1]), 9)
            parts = k.split("|")
            s = float(parts[2][2:]); dec = parts[3] == "dec=1"; gate = parts[4] != "gate=none"; own = parts[0].startswith("own")
            return (s, int(dec) + int(gate) + int(own))
        pick = sorted(near, key=simp)[0]
        r = dict(choose=ch, test=te, pick=pick, choose_wape=scores[pick], best_choose_wape=best,
                 live_choose=wape(vals[cfg_key(LIVE)][0][mc], a[mc]), none_choose=wape(vals[cfg_key(NONE)][0][mc], a[mc]))
        if te:
            mt = window(panel, *te).to_numpy()
            r.update(test_n=int(mt.sum()), pick_test=wape(vals[pick][0][mt], a[mt]), live_test=wape(vals[cfg_key(LIVE)][0][mt], a[mt]),
                     none_test=wape(vals[cfg_key(NONE)][0][mt], a[mt]))
            pk = panel.product_key.to_numpy()[mt]
            rng = np.random.default_rng(20261116)
            prods = np.unique(pk)
            grp = {p: np.where(pk == p)[0] for p in prods}
            aT = a[mt]
            vv = {n: vals[k][0][mt] for n, k in [("pick", pick), ("live", cfg_key(LIVE)), ("none", cfg_key(NONE))]}
            err = {n: np.array([np.abs(vv[n][grp[p]] - aT[grp[p]]).sum() for p in prods]) for n in vv}
            act = np.array([aT[grp[p]].sum() for p in prods])
            dl, dn = [], []
            for _ in range(2000):
                ii = rng.integers(0, len(prods), len(prods))
                s_a = act[ii].sum()
                dl.append((err["pick"][ii].sum() - err["live"][ii].sum()) / s_a)
                dn.append((err["pick"][ii].sum() - err["none"][ii].sum()) / s_a)
            r["ci_vs_live"] = (float(np.percentile(dl, 2.5)), float(np.percentile(dl, 97.5)))
            r["ci_vs_none"] = (float(np.percentile(dn, 2.5)), float(np.percentile(dn, 97.5)))
        res["folds"][name] = r
    res["scores_all"] = {k: {n: wape(vals[k][0][window(panel, *ch).to_numpy()], a[window(panel, *ch).to_numpy()]) for n, (ch, te) in FOLDS.items()} for k in keys_all}
    pickle.dump(res, open(ROOT / "local" / "cal_sel_results.pkl", "wb"))
    pickle.dump({k: v for k, v in vals.items()}, open(ROOT / "local" / "cal_sel_values.pkl", "wb"))
    for n, r in res["folds"].items():
        print(n, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})


if __name__ == "__main__":
    sys.exit(main())
