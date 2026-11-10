"""
reports/experiments/forecastability_2026-11-10/classify.py - forecastability classes, a detection rule and a treatment
per class, scored against the served forecast in two windows (2026-11-10). BACKTEST ONLY: reads the throwaway copy
ssm_challenger (127.0.0.1:55432) in one READ ONLY transaction and local/horse_race_rows_2026-11-10.csv (the as-served
rows of run_horse_race.py); writes aggregates here and per-product rows to the git-ignored local/ (hard rule 9).

    SUPABASE_DB_URL=postgresql://postgres@127.0.0.1:55432/ssm_challenger python reports/experiments/forecastability_2026-11-10/classify.py

FRAME. The 4,370 product-months of the stored as-served backtest (Tier A the month before, 2024-01..2026-02). Served =
router + calendar factor, exactly as stored. Actual = as served (no row 0, net-negative 0, blank not scored).

DETECTION, at each forecast month t, from the product's history strictly before t (first match wins):
  DEAD        the served dead-SKU rule already zeroes the row (served = 0 and flagged dead): left alone.
  PROMO/LOW   name matches (n+m) | + | PROMO | PRMO | PRM | DUO | DUA, or the last 6 months sum to < 500 pieces
              ("under a few hundred pieces in six months", the brief; 500 is that phrase made a number, stated).
  SUCCESSION  last month < 0.5 x mean of the last 12 months, AND another code of the same brand x category whose piece
              holds the same content (+-10%, same unit) or the same name family made its first sale in the 3 months
              before t (a re-code: the old code's demand is moving to the new one).
  FADING      the live collapse rule, analytics.forecasting.review_flag.collapse_ratio < 0.5 (REVIEW_COLLAPSE_RATIO):
              mean of the last 3 months below half the mean of the last 12, on the months the product has (> 3).
  NEW         fewer than 6 months since the first sale.
  BURST       Syntetos-Boylan on the last 12 months (needs 12): CV^2 of the non-zero months >= 0.49
              (erratic, or lumpy when ADI >= 1.32). Standard cut-offs, not tuned here.
  STABLE      everything else.

TREATMENTS, fixed here before any scoring (no setting read from a scored month):
  PROMO/LOW   min(served, last month): replenish what sold, never above the forecast.
  SUCCESSION  last month (naive): follow the old code down at once.
  FADING      min(served, mean of last 3 months) [primary];  min(served, last month) [variant].
  BURST (a)   pack family x share: family = connected codes of one brand x category sharing a pack size or a name
              family (every Unilever code, Tier A or not). forecast = family MA3 x the product's share of family pieces
              over the last 12 months x the served calendar factor.
  BURST ctl   the product's own 12-month mean x the served calendar factor (does the family add anything beyond
              smoothing?).
  BURST (b)   no forecast: order up to a stock-cover target. Scored as an inventory policy, not a forecast:
              monthly review, zero lead time, lost sales. Target = 95th percentile of the product's last 12 months.
              Against: served + 1.645 x RMSE of served's own earlier errors (>= 3, else the sd of the last 12 months),
              and the same for (a). Fill rate, months short, leftover pieces.
  NEW/STABLE  served, unchanged.
  SYSTEM      every row gets its class's primary treatment (BURST: (a)).

SCORING. Windows: main 2025-09..2026-02, earlier 2024-01..2025-08. Sets: all products, the 109 planned (lp_run 6).
Lines: all months, December, January.
  pooled WAPE  sum |f - a| / sum |a|                                                         (leads)
  MASE         median over products of mean |f - a| / scale; ONE scale per product for both windows: mean
               |y_t - y_t-1| over 2023-01..2025-08 from its first sale (>= 2 months). The scale only normalises; it
               fits nothing. Products without 2 months there are left out of MASE (count reported).   (leads)
  MAPE         median over products of mean |f - a| / a over months with a > 0. Caveat: a falling actual shrinks the
               denominator, so MAPE inflates on fading, low and December rows whatever the method.
  bias         sum (f - a) / sum |a|
  95% interval of pooled WAPE(treatment) - pooled WAPE(served) by product bootstrap, 2,000 draws, seed 20261110.
  HOLDS = pooled WAPE lower in BOTH windows with the main-window interval below 0 or the earlier one below 0, and MASE
  not higher in either. Anything lower in one window only is reported as NOT HOLDING.

ADDED AFTER THE FIRST RUN (post hoc, labelled so in every output):
  BURST2      the pre-registered BURST rule caught 1 product-month in the main window and none of the Knorr items (their
              CV is 0.2-0.4: smooth series with sudden spikes, not high-CV demand). BURST2 is the LP's own entry test
              applied month by month: among rows that would be STABLE, the served forecast's own errors on the
              product's frame rows in the 6 months before t (>= 4 of them) give mean |e| / naive scale of the history
              before t >= 1, with errors two-sided (|sum e| / sum |e| < 0.5: right on average, wrong every month).
              Treatments as BURST: (a) t_family, control t_ma12, (b) the inventory policy.
  system_nopromo  SYSTEM with the PROMO/LOW treatment dropped (served kept there), because that treatment failed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analytics.forecasting.diagnostic_metrics import mape as mape_fn, naive_scale  # noqa: E402
from analytics.forecasting.review_flag import collapse_ratio  # noqa: E402
from checks import content, fine_key  # noqa: E402
from scripts.run_baseline_forecast import build_series, fetch_demand  # noqa: E402

OUT = Path(__file__).resolve().parent
WINDOWS = {"main 2025-09..2026-02": ("2025-09", "2026-02"), "earlier 2024-01..2025-08": ("2024-01", "2025-08")}
SCALE_WINDOW = ("2023-01-01", "2025-08-01")
SEED, DRAWS = 20261110, 2000
PROMO_RE = r"\(\d+\+\d+\)|\+|PROMO|PRMO|PRM |DUO|DUA"
LOW_PIECES_6M = 500
SBC_CV2, SBC_ADI = 0.49, 1.32
Z95 = 1.645
CLASSES = ["DEAD", "PROMO/LOW", "SUCCESSION", "FADING", "NEW", "BURST", "BURST2", "STABLE"]


def url() -> str:
    u = os.environ.get("SUPABASE_DB_URL", "")
    p = urlparse(u)
    if p.hostname not in ("127.0.0.1", "localhost") or p.port != 55432:
        sys.exit("refusing: this backtest reads only the throwaway copy on 127.0.0.1:55432")
    return u


def read(u: str):
    conn = psycopg2.connect(u)
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    demand = fetch_demand(cur)
    cur.execute("""SELECT product_key, product_name, COALESCE(brand, '?'), COALESCE(category_path, 'UNCLASSIFIED')
                   FROM product_dimension WHERE principal = 'unilever'""")
    meta = pd.DataFrame(cur.fetchall(), columns=["k", "name", "brand", "cat"]).set_index("k")
    cur.execute("""SELECT product_key, to_char(month, 'YYYY-MM'), calendar_factor, dead_sku FROM forecast_challenger
                   WHERE kind = 'backtest'""")
    fc = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "cal", "dead"]).astype({"cal": float})
    cur.execute("""SELECT product_key, served_value, calendar_factor FROM forecast_challenger WHERE kind = 'cycle'""")
    cycle = {int(k): (float(v), float(c)) for k, v, c in cur.fetchall()}
    cur.execute("""SELECT product_key, q_i FROM lp_recommendation WHERE planning_cycle_date = '2026-03-01' AND lp_run_key =
                   (SELECT MAX(lp_run_key) FROM lp_recommendation WHERE planning_cycle_date = '2026-03-01')""")
    plan = {int(k): float(q) for k, q in cur.fetchall()}
    conn.rollback()
    conn.close()
    return demand, meta, fc, cycle, plan


def pack_token(name: str) -> str | None:
    m = re.search(r"(\S*\d\S*)\s*$", name.upper().replace("​", ""))
    return m.group(1) if m else None


def families(meta: pd.DataFrame) -> pd.Series:
    """Connected components inside brand x category: two codes join when they share the pack token or the name family."""
    parent = {k: k for k in meta.index}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    m = meta.assign(tok=[pack_token(n) for n in meta.name],
                    fine=[fine_key(n, b, c) for n, b, c in zip(meta.name, meta.brand, meta.cat)])
    for col in ("tok", "fine"):
        for _, g in m.dropna(subset=[col]).groupby(["brand", "cat", col]):
            ks = list(g.index)
            for k in ks[1:]:
                parent[find(k)] = find(ks[0])
    return pd.Series({k: find(k) for k in meta.index})


def wide(demand: pd.DataFrame, latest: str) -> tuple[dict, pd.DataFrame]:
    series = {int(k): build_series(g, latest) for k, g in demand.groupby("product_key")}
    idx = pd.date_range("2023-01-01", f"{latest}-01", freq="MS")
    W = pd.DataFrame({k: s.reindex(idx) for k, s in series.items()}).fillna(0.0)
    return series, W


def detect(r, s: pd.Series, t: pd.Timestamp, name: str, newcodes: dict, meta_c: dict, fam_meta: dict) -> tuple[str, dict]:
    h = s[s.index < t]
    h = h.fillna(0.0)
    sold = np.flatnonzero(h.to_numpy() > 0)
    h = h.iloc[sold[0]:] if len(sold) else h.iloc[:0]
    feat = {"age": len(h)}
    if r.dead and r.served == 0:
        return "DEAD", feat
    last = float(h.iloc[-1]) if len(h) else 0.0
    if re.search(PROMO_RE, name) or (len(h) and float(h.tail(6).sum()) < LOW_PIECES_6M):
        return "PROMO/LOW", feat
    if len(h) >= 4:
        base12 = float(h.tail(12).mean())
        if base12 > 0 and last < 0.5 * base12:
            c0 = meta_c.get(r.product_key)
            for j in newcodes.get((fam_meta[r.product_key]["bc"], t), []):
                if j == r.product_key:
                    continue
                cj = meta_c.get(j)
                same_content = c0 and cj and c0[1] == cj[1] and abs(cj[0] / c0[0] - 1) <= 0.10
                same_name = fam_meta[j]["fine"] == fam_meta[r.product_key]["fine"]
                if same_content or same_name:
                    feat["successor"] = int(j)
                    return "SUCCESSION", feat
    cr = collapse_ratio(s.fillna(0.0), t)
    feat["collapse_ratio"] = cr
    if cr is not None and cr < 0.5:
        return "FADING", feat
    if len(h) < 6:
        return "NEW", feat
    if len(h) >= 12:
        x = h.tail(12).to_numpy()
        nz = x[x > 0]
        adi = 12 / max(len(nz), 1)
        cv2 = float((nz.std() / nz.mean()) ** 2) if len(nz) > 1 and nz.mean() > 0 else 0.0
        feat.update(adi=adi, cv2=cv2)
        if cv2 >= SBC_CV2:
            return "BURST", feat
    return "STABLE", feat


def build(demand, meta, fc, cycle):
    latest = demand.calendar_month.max()
    series, W = wide(demand, latest)
    fam = families(meta)
    fam_meta = {k: {"bc": f"{meta.at[k, 'brand']}|{meta.at[k, 'cat']}",
                    "fine": fine_key(meta.at[k, "name"], meta.at[k, "brand"], meta.at[k, "cat"])} for k in meta.index}
    meta_c = {k: content(n) for k, n in meta.name.items()}
    # Codes whose first sale is in the 3 months before t, by brand x category.
    first = {k: W.index[np.flatnonzero(W[k].to_numpy() > 0)[0]] for k in W.columns if (W[k] > 0).any()}
    newcodes: dict = {}
    for t in pd.date_range("2024-01-01", f"{latest}-01", freq="MS"):
        for k, f0 in first.items():
            if t - pd.DateOffset(months=3) <= f0 < t and k in fam_meta:
                newcodes.setdefault((fam_meta[k]["bc"], t), []).append(k)
    members = fam.groupby(fam).groups
    F = pd.DataFrame({f: W[[k for k in ks if k in W.columns]].sum(axis=1) for f, ks in members.items()
                      if any(k in W.columns for k in ks)})
    rows = pd.read_csv(REPO / "local" / "horse_race_rows_2026-11-10.csv")[["product_key", "month", "actual", "served"]]
    rows = rows.merge(fc, on=["product_key", "month"], how="left")
    out = []
    for r in rows.itertuples():
        t = pd.Timestamp(f"{r.month}-01")
        s = series[r.product_key]
        cls, feat = detect(r, s, t, meta.at[r.product_key, "name"], newcodes, meta_c, fam_meta)
        h = W.loc[W.index < t, r.product_key]
        sold = np.flatnonzero(h.to_numpy() > 0)
        h = h.iloc[sold[0]:] if len(sold) else h.iloc[:0]
        last = float(h.iloc[-1]) if len(h) else 0.0
        m3 = float(h.tail(3).mean()) if len(h) else 0.0
        m12 = float(h.tail(12).mean()) if len(h) else 0.0
        f = fam[r.product_key]
        Fh = F.loc[F.index < t, f]
        fam12 = float(Fh.tail(len(h.tail(12))).sum()) if len(h) else 0.0
        share12 = float(h.tail(12).sum()) / fam12 if fam12 > 0 else np.nan
        famT = float(Fh.tail(3).mean()) * share12 * r.cal if share12 == share12 else r.served
        sd12 = float(h.tail(12).std()) if len(h) >= 3 else np.nan
        p95 = float(np.quantile(h.tail(12), 0.95)) if len(h) >= 6 else np.nan
        out.append({"product_key": r.product_key, "month": r.month, "actual": r.actual, "served": r.served, "cls": cls,
                    "family": int(f), "family_size": int(len(members[f])),
                    "t_promo": min(r.served, last), "t_succession": last,
                    "t_fading": min(r.served, m3), "t_fading_last": min(r.served, last),
                    "t_family": max(0.0, famT), "t_ma12": m12 * r.cal, "naive": last,
                    "sd12": sd12, "p95_12": p95, **{k: v for k, v in feat.items() if k in ("collapse_ratio", "successor", "cv2", "adi", "age")}})
    df = pd.DataFrame(out)
    prim = {"PROMO/LOW": "t_promo", "SUCCESSION": "t_succession", "FADING": "t_fading", "BURST": "t_family"}
    df["system"] = [getattr(r, prim[r.cls]) if r.cls in prim else r.served for r in df.itertuples()]
    df["system_nopromo"] = [r.served if r.cls == "PROMO/LOW" else r.system for r in df.itertuples()]
    df = burst_v2(df, series)
    return df, series, fam, members, W


def burst_v2(df: pd.DataFrame, series: dict) -> pd.DataFrame:
    """Post hoc (see header): STABLE rows whose served forecast's own trailing record says MASE >= 1, errors two-sided."""
    df = df.sort_values(["product_key", "month"]).reset_index(drop=True)
    df["trail_mase"] = np.nan
    for k, g in df.groupby("product_key"):
        s = series[k].fillna(0.0)
        for i, r in g.iterrows():
            t = pd.Timestamp(f"{r.month}-01")
            lo = (t - pd.DateOffset(months=6)).strftime("%Y-%m")
            prev = g[(g.month >= lo) & (g.month < r.month)].dropna(subset=["actual"])
            if len(prev) < 4:
                continue
            h = s[s.index < t]
            nz = np.flatnonzero(h.to_numpy() > 0)
            h = h.iloc[nz[0]:] if len(nz) else h.iloc[:0]
            scale = naive_scale(h.to_numpy(float)) if len(h) >= 2 else 0.0
            e = prev.served - prev.actual
            if scale > 0 and e.abs().sum() > 0:
                df.at[i, "trail_mase"] = float(e.abs().mean() / scale)
                df.at[i, "trail_onesided"] = float(abs(e.sum()) / e.abs().sum())
    hit = (df.cls == "STABLE") & (df.trail_mase >= 1) & (df.trail_onesided < 0.5)
    df.loc[hit, "cls"] = "BURST2"
    return df


def scales(series: dict, keys) -> dict:
    out = {}
    for k in keys:
        s = series[k]
        s = s[(s.index >= SCALE_WINDOW[0]) & (s.index <= SCALE_WINDOW[1])].dropna()
        nz = np.flatnonzero(s.to_numpy() > 0)
        s = s.iloc[nz[0]:] if len(nz) else s.iloc[:0]
        out[k] = naive_scale(s.to_numpy(float)) if len(s) >= 2 else np.nan
    return out


def score(d: pd.DataFrame, m: str, sc: dict) -> dict:
    e = d[m] - d.actual
    a = d.actual.abs().sum()
    per = d.groupby("product_key")
    mapes = per.apply(lambda g: mape_fn(g.actual.to_numpy(), g[m].to_numpy()), include_groups=False).dropna()
    mases = per.apply(lambda g: (np.abs(g[m] - g.actual).mean() / sc[g.name]) if sc.get(g.name, 0) > 0 else np.nan,
                      include_groups=False).dropna()
    return {"pooled_wape": float(np.abs(e).sum() / a) if a else np.nan, "mase": float(mases.median()) if len(mases) else np.nan,
            "mase_lt1": f"{int((mases < 1).sum())}/{len(mases)}", "mape": float(mapes.median()) if len(mapes) else np.nan,
            "bias": float(e.sum() / a) if a else np.nan, "product_months": int(len(d)), "products": int(d.product_key.nunique()),
            "actual_pieces": float(a)}


def boot(d: pd.DataFrame, m: str) -> tuple[float, float]:
    g = d.assign(es=(d.served - d.actual).abs(), em=(d[m] - d.actual).abs(), aa=d.actual.abs()) \
        .groupby("product_key")[["es", "em", "aa"]].sum()
    if len(g) < 2 or g.aa.sum() == 0:
        return np.nan, np.nan
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(g), size=(DRAWS, len(g)))
    es, em, aa = (g[c].to_numpy()[idx].sum(axis=1) for c in ("es", "em", "aa"))
    ok = aa > 0
    lo, hi = np.quantile((em[ok] - es[ok]) / aa[ok], [0.025, 0.975])
    return float(lo), float(hi)


def inventory(d: pd.DataFrame, full: pd.DataFrame) -> dict:
    """BURST (b): order-up-to targets scored as a policy (monthly review, zero lead time, lost sales)."""
    res = {}
    allrows = full.sort_values("month")
    rmse = {}
    for col in ("served", "t_family"):
        r = {}
        for k, g in allrows.groupby("product_key"):
            errs = []
            for row in g.itertuples():
                r[(k, row.month)] = float(np.sqrt(np.mean(np.square(errs)))) if len(errs) >= 3 else np.nan
                errs.append(getattr(row, col) - row.actual)
        rmse[col] = r
    pol = {}
    for col in ("served", "t_family"):
        sig = np.array([rmse[col].get((k, m), np.nan) for k, m in zip(d.product_key, d.month)])
        sig = np.where(np.isnan(sig), d.sd12.to_numpy(), sig)
        pol[f"forecast {col} + 1.645 sigma"] = np.maximum(0, d[col].to_numpy() + Z95 * np.nan_to_num(sig))
    pol["no forecast: cover target = p95 of last 12 months"] = np.nan_to_num(d.p95_12.to_numpy(), nan=d.served.to_numpy())
    a = d.actual.to_numpy()
    for name, S in pol.items():
        res[name] = {"fill_rate": round(float(np.minimum(S, a).sum() / a.sum()), 4),
                     "months_short_pct": round(float(100 * (a > S).mean()), 1),
                     "leftover_pieces_per_month": round(float(np.maximum(S - a, 0).mean())),
                     "leftover_months_of_sales": round(float(np.maximum(S - a, 0).sum() / a.sum()), 3),
                     "mean_target_pieces": round(float(S.mean()))}
    return res


TREATMENTS = {
    "PROMO/LOW": ["served", "t_promo", "naive"],
    "SUCCESSION": ["served", "t_succession", "t_fading"],
    "FADING": ["served", "t_fading", "t_fading_last"],
    "NEW": ["served"],
    "BURST": ["served", "t_family", "t_ma12"],
    "BURST2": ["served", "t_family", "t_ma12"],
    "STABLE": ["served", "t_family", "t_ma12"],
    "DEAD": ["served"],
    "ALL (system)": ["served", "system", "system_nopromo"],
}


def main() -> int:
    demand, meta, fc, cycle, plan = read(url())
    planned = set(plan)
    df, series, fam, members, W = build(demand, meta, fc, cycle)
    df = df.dropna(subset=["actual"])
    df.to_csv(REPO / "local" / "forecastability_rows_2026-11-10.csv", index=False)   # per product: git-ignored (rule 9)
    sc = scales(series, df.product_key.unique())
    table, counts, inv = [], {}, {}
    for wname, (a, b) in WINDOWS.items():
        w = df[(df.month >= a) & (df.month <= b)]
        counts[wname] = {c: {"product_months": int((w.cls == c).sum()), "products": int(w[w.cls == c].product_key.nunique()),
                             "actual_share": round(float(w[w.cls == c].actual.sum() / w.actual.sum()), 3),
                             "served_abs_error_share": round(float((w[w.cls == c].served - w[w.cls == c].actual).abs().sum()
                                                                   / (w.served - w.actual).abs().sum()), 3),
                             "served_over_pieces": (round(float((w[w.cls == c].served - w[w.cls == c].actual).sum()))
                                                    if w[w.cls == c].product_key.nunique() >= 3 else None)}
                         for c in CLASSES}
        for sname, sdf in {"all": w, "planned": w[w.product_key.isin(planned)]}.items():
            for cname, methods in TREATMENTS.items():
                cdf = sdf if cname.startswith("ALL") else sdf[sdf.cls == cname]
                for lname, ldf in {"all months": cdf, "December": cdf[cdf.month.str.endswith("-12")],
                                   "January": cdf[cdf.month.str.endswith("-01")]}.items():
                    if ldf.empty:
                        continue
                    base = score(ldf, "served", sc)
                    for m in methods:
                        s_ = base if m == "served" else score(ldf, m, sc)
                        lo, hi = (0.0, 0.0) if m == "served" else boot(ldf, m)
                        table.append({"window": wname, "set": sname, "class": cname, "line": lname, "method": m, **s_,
                                      "d_wape": s_["pooled_wape"] - base["pooled_wape"], "d_mase": s_["mase"] - base["mase"],
                                      "ci_lo": lo, "ci_hi": hi})
            for bc in ("BURST", "BURST2"):
                b_ = sdf[sdf.cls == bc]
                if len(b_) and b_.actual.sum() > 0:
                    inv[f"{bc} | {wname} | {sname}"] = {"product_months": int(len(b_)), "products": int(b_.product_key.nunique()),
                                                        **inventory(b_, df)}
    t = pd.DataFrame(table)
    # Aggregates only: a piece total over fewer than 3 products is one product's sales (hard rule 9), so it is blanked.
    t_out = t.copy()
    t_out.loc[t_out.products < 3, "actual_pieces"] = np.nan
    t_out.to_csv(OUT / "results_classes.csv", index=False)
    # Verdicts: all products and planned, 'all months' line.
    verdict = {}
    for sname in ("all", "planned"):
        for cname, methods in TREATMENTS.items():
            for m in methods:
                if m == "served":
                    continue
                cells = t[(t.set == sname) & (t["class"] == cname) & (t.line == "all months") & (t.method == m)]
                if len(cells) < 2:
                    verdict[f"{sname} | {cname} | {m}"] = "not scored in both windows"
                    continue
                lower_both = bool((cells.d_wape < 0).all())
                ci_ok = bool((cells.ci_hi < 0).any())
                mase_ok = bool((cells.d_mase.fillna(0) <= 0).all())
                verdict[f"{sname} | {cname} | {m}"] = ("HOLDS" if lower_both and ci_ok and mase_ok else
                                                       "lower in both windows, inside the noise or MASE higher" if lower_both else
                                                       "NOT HOLDING (one window only)" if (cells.d_wape < 0).any() else "worse in both")
    # Surf Fabcon SOL 360X28ML (64373260): when each rule catches it.
    k = int(meta.index[meta.name.str.contains("SURF FABCON BLOSSOM FRESH SOL 360X28ML", regex=False)][0])
    sf = df[df.product_key == k].sort_values("month")[["month", "actual", "served", "cls", "collapse_ratio", "t_fading", "t_succession"]]
    s = series[k].fillna(0.0)
    t_mar = pd.Timestamp("2026-03-01")
    cr_mar = collapse_ratio(s, t_mar)
    h = s[s.index < t_mar]
    flag_by_month = {m.strftime("%Y-%m"): collapse_ratio(s, m) for m in pd.date_range("2025-08-01", "2026-03-01", freq="MS")}
    surf = {"product_key": k, "rows": sf.round(1).to_dict("records"), "collapse_ratio_by_forecast_month": flag_by_month,
            "march_2026_cycle": {"served": cycle.get(k, (None,))[0], "plan_q_i": plan.get(k),
                                 "collapse_ratio": cr_mar, "fading_treatment": min(cycle.get(k, (0,))[0] or 0, float(h.tail(3).mean())),
                                 "succession_treatment_last_month": float(h.iloc[-1])}}
    # The per-month rows are per-product sales: local/ only (hard rule 9). The committed file keeps when each rule fires.
    (REPO / "local" / "forecastability_surf_fabcon_2026-11-10.json").write_text(json.dumps(surf, indent=1, default=str),
                                                                               encoding="utf-8")
    fires = {"succession_first_forecast_month": next((r["month"] for r in surf["rows"] if r["cls"] == "SUCCESSION"), None),
             "collapse_first_forecast_month": next((m for m, v in flag_by_month.items() if v is not None and v < 0.5), None),
             "served_forecast_zero_by_2026-03": bool((cycle.get(k, (1,))[0] or 0) == 0),
             "in_march_2026_plan": k in plan}
    res = {"counts_by_class": counts, "verdicts": verdict, "inventory_burst_b": inv, "surf_fabcon_sol": fires,
           "mase_scale_window": SCALE_WINDOW, "mase_missing_scale": int(sum(1 for v in sc.values() if not v > 0)),
           "families": {"codes": int(len(fam)), "families": int(fam.nunique()),
                        "frame_products_in_multi_code_families": int(sum(len(members[fam[k]]) > 1 for k in df.product_key.unique()))}}
    (OUT / "results_classes.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 500)
    show = t[t.line == "all months"][["window", "set", "class", "method", "products", "product_months", "pooled_wape", "mase",
                                      "mase_lt1", "mape", "bias", "d_wape", "ci_lo", "ci_hi", "d_mase"]]
    print(show.round(3).to_string(index=False))
    print(json.dumps({k_: v for k_, v in res.items() if k_ != "surf_fabcon_sol"}, indent=1, default=str))
    print(json.dumps(surf, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
