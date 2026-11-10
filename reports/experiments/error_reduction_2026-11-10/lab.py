"""
reports/experiments/error_reduction_2026-11-10/lab.py - shared frame, metrics and gate for the error-reduction work of
2026-11-10. BACKTEST ONLY: reads the throwaway copy ssm_challenger (127.0.0.1:55432, a restore of the 2026-11-04 backup)
in one READ ONLY transaction, and the as-served rows of the forecastability run (local/forecastability_rows_2026-11-10.csv,
git-ignored). Refuses any other database.

FRAME. The 4,370 product-months of the stored as-served backtest (Tier A the month before, 2024-01..2026-02), the same rows
as the horse race and the forecastability classes. served = router + calendar factor, as stored. actual = as served (no row
0, net-negative 0, blank not scored). S1 = served with SUCCESSION -> last month and FADING -> min(served, last-3 mean)
(classify.py's system_nopromo): the forecast that task 1 serves.

SCORING, every candidate, both windows, every time (classify.py's definitions, imported, not re-written):
  pooled WAPE = sum|f-a| / sum|a| (leads); MASE = median over products of mean|f-a| / one fixed naive scale per product
  (2023-01..2025-08), same scale in both windows (leads); MAPE = median over products of mean|f-a|/a over a>0 (named
  beside them); bias = sum(f-a)/sum|a|. 95% product bootstrap of the pooled WAPE difference, 2,000 draws, seed 20261110.
  Windows main 2025-09..2026-02, earlier 2024-01..2025-08. Sets: all products, the 109 planned (lp_run 6).
  Lines: all months, December, January.
GATE (fixed before any candidate was scored): a candidate HOLDS against a baseline when its pooled WAPE is lower in BOTH
  windows, the 95% interval is below 0 in at least one of them, and MASE is not higher in either; STRICT when both intervals
  are below 0. Anything lower in one window only is NOT HOLDING. Scored for all products and, separately, planned.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FC_DIR = REPO / "reports" / "experiments" / "forecastability_2026-11-10"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(FC_DIR))

import classify as C  # noqa: E402  (score, boot, scales, families, detect: the forecastability definitions)
from scripts.run_baseline_forecast import build_series, fetch_demand  # noqa: E402

WINDOWS = C.WINDOWS
LOCAL = REPO / "local"
CACHE = LOCAL / "error_reduction_frame_2026-11-10.pkl"


def url() -> str:
    u = os.environ.get("SUPABASE_DB_URL", "postgresql://postgres@127.0.0.1:55432/ssm_challenger")
    p = urlparse(u)
    if p.hostname not in ("127.0.0.1", "localhost") or p.port != 55432:
        sys.exit("refusing: this backtest reads only the throwaway copy on 127.0.0.1:55432")
    return u


def load(refresh: bool = False) -> dict:
    """{rows, series, W, meta, plan, sc}: rows = the as-served frame plus cal, with S1 = system_nopromo."""
    if CACHE.exists() and not refresh:
        return pd.read_pickle(CACHE)
    demand, meta, fc, cycle, plan = C.read(url())
    latest = demand.calendar_month.max()
    series = {int(k): build_series(g, latest) for k, g in demand.groupby("product_key")}
    idx = pd.date_range("2023-01-01", f"{latest}-01", freq="MS")
    W = pd.DataFrame({k: s.reindex(idx) for k, s in series.items()})          # NaN = blank or before first row
    rows = pd.read_csv(LOCAL / "forecastability_rows_2026-11-10.csv")
    rows = rows.merge(fc[["product_key", "month", "cal"]], on=["product_key", "month"], how="left")
    rows["cal"] = rows["cal"].fillna(1.0)
    rows["S1"] = rows["system_nopromo"]
    rows["t"] = pd.to_datetime(rows.month + "-01")
    sc = C.scales(series, rows.product_key.unique())
    out = {"rows": rows, "series": series, "W": W, "meta": meta, "plan": set(plan), "plan_q": plan, "cycle": cycle,
           "sc": sc, "demand": demand}
    pd.to_pickle(out, CACHE)                                                 # per-product sales: local/ only (rule 9)
    return out


def hist(series: pd.Series, t: pd.Timestamp) -> pd.Series:
    """History strictly before t, from the first sale; a blank month stays NaN."""
    h = series[series.index < t]
    nz = np.flatnonzero(h.fillna(0).to_numpy() > 0)
    return h.iloc[nz[0]:] if len(nz) else h.iloc[:0]


def table(df: pd.DataFrame, methods: list[str], sc: dict, plan: set, bases=("served", "S1"),
          lines=True) -> pd.DataFrame:
    """One row per window x set x line x method, with differences and intervals against each base."""
    out = []
    for wname, (a, b) in WINDOWS.items():
        w = df[(df.month >= a) & (df.month <= b)]
        for sname, sdf in {"all": w, "planned": w[w.product_key.isin(plan)]}.items():
            ls = {"all months": sdf}
            if lines:
                ls.update({"December": sdf[sdf.month.str.endswith("-12")], "January": sdf[sdf.month.str.endswith("-01")]})
            for lname, ldf in ls.items():
                if ldf.empty:
                    continue
                base_scores = {bs: C.score(ldf, bs, sc) for bs in bases}
                for m in methods:
                    s_ = C.score(ldf, m, sc)
                    rec = {"window": wname, "set": sname, "line": lname, "method": m, **s_}
                    for bs in bases:
                        rec[f"d_wape_vs_{bs}"] = s_["pooled_wape"] - base_scores[bs]["pooled_wape"]
                        rec[f"d_mase_vs_{bs}"] = s_["mase"] - base_scores[bs]["mase"]
                        lo, hi = (0.0, 0.0) if m == bs else boot(ldf, m, bs)
                        rec[f"ci_lo_vs_{bs}"], rec[f"ci_hi_vs_{bs}"] = lo, hi
                    out.append(rec)
    return pd.DataFrame(out)


def boot(d: pd.DataFrame, m: str, base: str) -> tuple[float, float]:
    g = d.assign(es=(d[base] - d.actual).abs(), em=(d[m] - d.actual).abs(), aa=d.actual.abs()) \
        .groupby("product_key")[["es", "em", "aa"]].sum()
    if len(g) < 2 or g.aa.sum() == 0:
        return np.nan, np.nan
    rng = np.random.default_rng(C.SEED)
    idx = rng.integers(0, len(g), size=(C.DRAWS, len(g)))
    es, em, aa = (g[c].to_numpy()[idx].sum(axis=1) for c in ("es", "em", "aa"))
    ok = aa > 0
    lo, hi = np.quantile((em[ok] - es[ok]) / aa[ok], [0.025, 0.975])
    return float(lo), float(hi)


def gate(t: pd.DataFrame, method: str, base: str, sset: str = "all") -> str:
    cells = t[(t.set == sset) & (t.line == "all months") & (t.method == method)]
    if len(cells) < 2:
        return "not scored in both windows"
    d, lo, hi, dm = (cells[f"{x}_vs_{base}"] for x in ("d_wape", "ci_lo", "ci_hi", "d_mase"))
    lower_both = bool((d < 0).all())
    if lower_both and (hi < 0).all() and (dm.fillna(0) <= 0).all():
        return "HOLDS (strict: both intervals below 0)"
    if lower_both and (hi < 0).any() and (dm.fillna(0) <= 0).all():
        return "HOLDS"
    if lower_both:
        return "lower in both, inside the noise or MASE higher"
    if (d < 0).any():
        return "NOT HOLDING (one window only)"
    return "worse in both"


def show(t: pd.DataFrame, base: str = "S1", line: str = "all months") -> str:
    cols = ["window", "set", "method", "products", "pooled_wape", "mase", "mape", "bias",
            f"d_wape_vs_{base}", f"ci_lo_vs_{base}", f"ci_hi_vs_{base}", f"d_mase_vs_{base}"]
    s = t[t.line == line][cols].copy()
    for c in ("pooled_wape", "mape", "bias", f"d_wape_vs_{base}", f"ci_lo_vs_{base}", f"ci_hi_vs_{base}"):
        s[c] = (100 * s[c]).round(2)
    s["mase"] = s["mase"].round(3)
    s[f"d_mase_vs_{base}"] = s[f"d_mase_vs_{base}"].round(3)
    return s.to_string(index=False)
