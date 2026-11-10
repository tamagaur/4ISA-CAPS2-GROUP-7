"""
reports/experiments/error_hunt_2026-11-10/extra.py - the leads that are not a level method. Backtest only (lab.py frame,
hunt.py rows, throwaway copy, READ ONLY).

    python reports/experiments/error_hunt_2026-11-10/extra.py

1. UNIT. Is the gap between 37.88% (median product WAPE, pieces) and 10.77% (total WAPE, pesos) the unit or the
   aggregation? S1 scored four ways on the same rows: pooled per product-month in pieces and in pesos (each product-month's
   error x its own last-3-month price), and the WAPE of the monthly TOTALS in pieces and in pesos.
2. WHERE THE ERROR IS (oracles, NOT forecasts; they use the scored months): S1 x the product's true window ratio (level
   known per product), S1 x the true company ratio of that month (company level known), and 2-month totals.
3. PROMO TIMING. No Unilever pricelist exists and net/gross is flat within a code, so the only promo signal in the data is
   a promo/bundle code (treatments.PROMO_NAME_RE) of the same brand x category x name family selling. Two versions:
   promo_lag  (known: the sibling sold last month, a factor fitted on earlier months only)
   promo_cal  (NEEDS A PROMO CALENDAR: the sibling sells in the month forecast; the factor is fitted on earlier months only
              but the indicator is the month's own; valid only if SSM knows its promo months in advance)
4. GLOBAL GRADIENT BOOSTING (gbm): one XGBoost model over every Unilever code, refitted each month on months before t.
   Target actual / MA3, sample weight MA3, absolute-error loss (so the loss is pieces of absolute error, the WAPE
   numerator). Features fixed before scoring: lags 1-6 / MA3, MA3/MA12, MA6/MA12, sd12/MA12, log MA3, age, month of year,
   business days of t, same month last year / its MA12, the group's (hunt.py flavour group) share trend, company growth in
   pieces and pesos (MA3/MA12), promo sibling sold last month. Settings fixed: 300 trees, depth 4, eta 0.05, subsample and
   colsample 0.8, seed 20261110. gbm_layer keeps S1's succession/fading rows; gbm_mix = mean(S1, gbm).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "error_reduction_2026-11-10"))
import hunt  # noqa: E402
import lab  # noqa: E402

sys.path.insert(0, str(lab.REPO))
from analytics.etl.granularity import business_days_in_month  # noqa: E402
from analytics.forecasting.treatments import PROMO_NAME_RE, name_family  # noqa: E402

OUT = lab.LOCAL / "error_hunt_extra_rows_2026-11-10.pkl"


def promo_map(F):
    meta = F["meta"]
    m = meta.assign(promo=[bool(re.search(PROMO_NAME_RE, str(n).upper())) for n in meta.name],
                    fam=[name_family(str(n), str(b), str(c)) for n, b, c in zip(meta.name, meta.brand, meta.cat)])
    m["key"] = m.brand.astype(str) + "|" + m.cat.astype(str) + "|" + m.fam
    sib = {}
    for _, g in m.groupby("key"):
        promos = [k for k in g.index if g.at[k, "promo"]]
        for k in g.index:
            if not g.at[k, "promo"]:
                sib[k] = [p for p in promos if p in F["W"].columns]
    return sib, m.promo


def promo_flags(F, sib):
    W = F["W"].fillna(0)
    act = pd.DataFrame(0, index=W.index, columns=W.columns, dtype=float)
    for k, ps in sib.items():
        if ps and k in act:
            act[k] = (W[ps].sum(axis=1) > 0).astype(float)
    return act


def features(F, act):
    W = F["W"]
    X = W.fillna(0).to_numpy()
    nan = W.isna().to_numpy()
    T, N = X.shape
    first = np.argmax(X > 0, axis=0)
    has = (X > 0).any(axis=0)
    pes = F["pes"].fillna(0)
    Tq = X.sum(axis=1)
    Tp = pes.to_numpy().sum(axis=1)
    gk = F["gk"].reindex(W.columns)
    G = {}
    for g, cols in pd.Series(range(N), index=W.columns).groupby(gk.values):
        G[g] = X[:, cols.to_numpy()].sum(axis=1)
    Gm = np.column_stack([G[g] if isinstance(g, str) else X[:, j] for j, g in enumerate(gk.values)])
    bdays = np.array([len(business_days_in_month(t.strftime("%Y-%m"))) for t in W.index], float)
    A = act.reindex(index=W.index, columns=W.columns).fillna(0).to_numpy()
    recs = []
    for i in range(6, T):
        for j in range(N):
            if not has[j] or first[j] > i - 3:
                continue
            h = X[first[j]:i, j]
            m3, m6, m12 = h[-3:].mean(), h[-6:].mean(), h[-12:].mean()
            if m3 <= 0 and m12 <= 0:
                continue
            base = max(m3, 1.0)
            lags = [X[i - l, j] / base for l in range(1, 7)]
            ly = (X[i - 12, j] / max(X[max(i - 24, 0):i - 12, j].mean(), 1.0)) if i - 12 >= first[j] else np.nan
            g = Gm[:, j]
            gsh3 = h[-3:].sum() / max(g[i - 3:i].sum(), 1.0)
            gsh12 = h[-12:].sum() / max(g[max(i - 12, 0):i].sum(), 1.0)
            recs.append([i, j, *lags, m3 / max(m12, 1), m6 / max(m12, 1), (h[-12:].std() / max(m12, 1)),
                         np.log1p(m3), i - first[j], W.index[i].month, bdays[i], ly, gsh3 / max(gsh12, 1e-6),
                         Tq[i - 3:i].mean() / Tq[max(i - 12, 0):i].mean(), Tp[i - 3:i].mean() / Tp[max(i - 12, 0):i].mean(),
                         A[i - 1, j], base, X[i, j] if not nan[i, j] else np.nan])
    cols = ["i", "j"] + [f"lag{l}" for l in range(1, 7)] + ["r3_12", "r6_12", "cv12", "logm3", "age", "moy", "bdays",
                                                              "ly", "gshare", "co_pcs", "co_peso", "promo_lag", "base", "y"]
    return pd.DataFrame(recs, columns=cols)


FEATS = [f"lag{l}" for l in range(1, 7)] + ["r3_12", "r6_12", "cv12", "logm3", "age", "moy", "bdays", "ly", "gshare",
                                             "co_pcs", "co_peso", "promo_lag"]


def gbm(F, rows, P):
    W = F["W"]
    tindex = {t: i for i, t in enumerate(W.index)}
    cindex = {k: j for j, k in enumerate(W.columns)}
    out = {}
    for t in sorted(rows.t.unique()):
        i = tindex[pd.Timestamp(t)]
        tr = P[(P.i < i) & P.y.notna()]
        params = dict(objective="reg:absoluteerror", max_depth=4, eta=0.05, subsample=0.8, colsample_bytree=0.8,
                      seed=20261110, nthread=4)
        d = xgb.DMatrix(tr[FEATS], label=np.clip(tr.y / tr.base, 0, 5), weight=tr.base)
        bst = xgb.train(params, d, num_boost_round=300)
        te = P[P.i == i]
        pred = bst.predict(xgb.DMatrix(te[FEATS])) * te.base.to_numpy()
        for j, v in zip(te.j, pred):
            out[(W.columns[j], pd.Timestamp(t))] = max(float(v), 0.0)
        print(t, len(tr), flush=True)
    rows["gbm"] = [out.get((k, pd.Timestamp(t)), np.nan) * c for k, t, c in zip(rows.product_key, rows.t, rows.cal)]
    return rows


def main() -> int:
    F = hunt.load()
    rows = pd.read_pickle(hunt.OUT_ROWS)
    if "naive_y" in rows:
        rows = rows.rename(columns={"naive_y": "naive"}).drop(columns=["naive_x"])
    sib, is_promo = promo_map(F)
    act = promo_flags(F, sib)
    res = {}

    # 1. unit vs aggregation
    pes, W = F["pes"], F["W"]
    price = {}
    for r in rows.itertuples():
        q = W[r.product_key][W.index < r.t].iloc[-3:].fillna(0).sum()
        p = pes[r.product_key][pes.index < r.t].iloc[-3:].fillna(0).sum()
        price[(r.product_key, r.t)] = p / q if q > 0 and p > 0 else np.nan
    rows["price"] = [price[(k, t)] for k, t in zip(rows.product_key, rows.t)]
    for wname, (a, b) in lab.WINDOWS.items():
        w = rows[(rows.month >= a) & (rows.month <= b) & rows.price.notna()]
        for m in ("served", "S1"):
            e = (w[m] - w.actual)
            tot = w.groupby("t")[[m, "actual"]].sum()
            totp = w.assign(fp=w[m] * w.price, ap=w.actual * w.price).groupby("t")[["fp", "ap"]].sum()
            per = w.assign(e=e.abs()).groupby("product_key")[["e", "actual"]].sum()
            res.setdefault("unit", {})[f"{wname} {m}"] = {
                "pooled_pieces": float(e.abs().sum() / w.actual.sum()),
                "pooled_pesos": float((e.abs() * w.price).sum() / (w.actual * w.price).sum()),
                "median_product_pieces": float((per.e / per.actual)[per.actual > 0].median()),
                "total_monthly_pieces": float((tot[m] - tot.actual).abs().sum() / tot.actual.sum()),
                "total_monthly_pesos": float((totp.fp - totp.ap).abs().sum() / totp.ap.sum())}

    # 2. oracles
    for (a, b) in lab.WINDOWS.values():
        msk = (rows.month >= a) & (rows.month <= b)
        g = rows[msk].groupby("product_key")
        rows.loc[msk, "ORACLE_prodlevel"] = rows[msk].S1 * (g.actual.transform("sum") / g.S1.transform("sum").replace(0, np.nan)).fillna(1)
    c = rows.groupby("t")[["actual", "S1"]].transform("sum")
    rows["ORACLE_colevel"] = rows.S1 * c.actual / c.S1

    # 3. promo timing
    A = act
    rows["promo_now"] = [A.at[t, k] if k in A else 0 for k, t in zip(rows.product_key, rows.t)]
    rows["promo_prev"] = [A.at[t - pd.DateOffset(months=1), k] if (k in A and t - pd.DateOffset(months=1) in A.index) else 0
                          for k, t in zip(rows.product_key, rows.t)]
    rows["lr"] = np.log((rows.actual + 1) / (rows.S1 + 1))
    for col, name in (("promo_prev", "promo_lag"), ("promo_now", "promo_cal")):
        f = []
        for r in rows.itertuples():
            if not getattr(r, col):
                f.append(r.S1)
                continue
            past = rows[(rows.t < r.t) & (rows[col] == 1)]
            ctrl = rows[(rows.t < r.t) & (rows[col] == 0)]
            fac = np.exp(past.lr.median() - ctrl.lr.median()) if len(past) >= 20 else 1.0
            f.append(r.S1 * fac)
        rows[name] = f
    res["promo"] = {"rows_with_sibling_now": int(rows.promo_now.sum()), "rows_with_sibling_prev": int(rows.promo_prev.sum()),
                    "median_log_ratio_now_vs_not": float(rows[rows.promo_now == 1].lr.median() - rows[rows.promo_now == 0].lr.median()),
                    "median_log_ratio_start_vs_not": float(rows[(rows.promo_now == 1) & (rows.promo_prev == 0)].lr.median()
                                                           - rows[rows.promo_now == 0].lr.median()),
                    "base_codes_with_a_promo_sibling": int(sum(1 for v in sib.values() if v))}

    # 4. global gradient boosting
    if OUT.exists() and "--rebuild" not in sys.argv:
        g = pd.read_pickle(OUT)
        rows = rows.merge(g, on=["product_key", "t"], how="left")
    else:
        P = features(F, act)
        rows = gbm(F, rows, P)
        rows[["product_key", "t", "gbm"]].to_pickle(OUT)
    rows["gbm"] = rows.gbm.fillna(rows.S1)
    rows["gbm_layer"] = np.where(rows.S1 != rows.served, rows.S1, rows.gbm)
    rows["gbm_mix"] = 0.5 * (rows.S1 + rows.gbm_layer)

    methods = ["ORACLE_prodlevel", "ORACLE_colevel", "promo_lag", "promo_cal", "gbm", "gbm_layer", "gbm_mix"]
    t = lab.table(rows, ["S1"] + methods, F["sc"], F["plan7"], bases=("S1",))
    t.to_csv(HERE / "results_extra.csv", index=False)
    v = {m: {s: lab.gate(t, m, "S1", s) for s in ("all", "planned")} for m in methods}
    (HERE / "results_extra_verdicts.json").write_text(json.dumps(v, indent=1))
    (HERE / "results_extra.json").write_text(json.dumps(res, indent=1))
    pd.to_pickle(rows, lab.LOCAL / "error_hunt_rows_extra_2026-11-10.pkl")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
