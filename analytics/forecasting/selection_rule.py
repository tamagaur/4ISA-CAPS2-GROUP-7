"""
analytics.forecasting.selection_rule - the recalibration rule that decides between the served forecast and the
challenger. Written and committed 2026-11-10 BEFORE any comparison of the two was run; the text is
docs/CHALLENGER_SELECTION_RULE.md and this module is its only implementation. Changing either after a comparison
has been seen is not allowed: a changed rule is committed before the NEXT recalibration point and applies from it.

The rule's output is a recommendation. Switching the served model is a team decision recorded as a DEC entry;
nothing reads this module's verdict to change what is served.

Pure functions, no DB access. Deterministic (fixed bootstrap seed).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Months the 2026-11-10 diagnosis looked at (scripts/forecast_bias_diagnosis.py), and on which the challenger was
# chosen. They never enter a comparison.
SEEN_MONTHS = frozenset(("2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"))
# At least one half-year (the half-year block of DEC-26's model tests) of evaluable months, split into two halves.
MIN_EVAL_MONTHS = 6
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261110
CI_LEVEL = 0.95

SERVED, CHALLENGER, INSUFFICIENT = "served", "challenger", "insufficient"


def scored(rows: pd.DataFrame) -> pd.DataFrame:
    """The rows both forecasts are scored on, with each error computed by the same expression.
    `rows`: product_key, month ('YYYY-MM'), actual (the as-served actual: net-negative month 0, no row 0, blank NaN),
    served, challenger. A row is scored only when the actual and BOTH forecasts exist, so the two are always
    scored on identical product-months."""
    r = rows.dropna(subset=["actual", "served", "challenger"]).copy()
    for col in ("served", "challenger"):
        r[f"err_{col}"] = r[col].astype(float) - r["actual"].astype(float)
    return r


def evaluation_months(turn_year: int, months_with_actuals) -> list[str]:
    """The months compared at the turn from `turn_year` to `turn_year`+1: January to December of `turn_year` that
    have actuals, minus SEEN_MONTHS."""
    want = {f"{turn_year}-{m:02d}" for m in range(1, 13)}
    return sorted(m for m in set(months_with_actuals) if m in want and m not in SEEN_MONTHS)


def pooled_wape(actual: np.ndarray, err: np.ndarray) -> float:
    a = np.abs(actual).sum()
    return float(np.abs(err).sum() / a) if a > 0 else float("nan")


def _runs3(r: pd.DataFrame, col: str) -> int:
    """Products whose last 3 scored rows are all over-forecast (the review rule's 3, rows in month order)."""
    n = 0
    for _, g in r.sort_values("month").groupby("product_key"):
        last = g[f"err_{col}"].to_numpy()[-3:]
        n += int(len(last) == 3 and (last > 0).all())
    return n


def summary(r: pd.DataFrame, col: str) -> dict:
    err, act = r[f"err_{col}"].to_numpy(dtype=float), r["actual"].to_numpy(dtype=float)
    per = r.groupby("product_key").apply(lambda g: pooled_wape(g.actual.to_numpy(float), g[f"err_{col}"].to_numpy(float)),
                                         include_groups=False).dropna()
    return {"pooled_wape_pieces": pooled_wape(act, err), "median_product_wape": float(per.median()) if len(per) else None,
            "net_bias_pieces": float(err.sum() / np.abs(act).sum()) if np.abs(act).sum() > 0 else None,
            "surplus_share_of_miss_pieces": float(np.clip(err, 0, None).sum() / np.abs(err).sum()) if np.abs(err).sum() > 0 else None,
            "over_3_in_a_row": _runs3(r, col)}


def bootstrap_delta(r: pd.DataFrame) -> tuple[float, float]:
    """95% percentile interval of WAPE(challenger) - WAPE(served), resampling PRODUCTS with replacement (a product's
    months stay together), BOOTSTRAP_RESAMPLES draws, BOOTSTRAP_SEED."""
    g = r.groupby("product_key").agg(a=("actual", lambda x: np.abs(x).sum()),
                                     s=("err_served", lambda x: np.abs(x).sum()),
                                     c=("err_challenger", lambda x: np.abs(x).sum()))
    a, s, c = g.a.to_numpy(float), g.s.to_numpy(float), g.c.to_numpy(float)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    idx = rng.integers(0, len(g), size=(BOOTSTRAP_RESAMPLES, len(g)))
    den = a[idx].sum(axis=1)
    ok = den > 0
    d = (c[idx].sum(axis=1)[ok] - s[idx].sum(axis=1)[ok]) / den[ok]
    lo, hi = np.quantile(d, [(1 - CI_LEVEL) / 2, 1 - (1 - CI_LEVEL) / 2])
    return float(lo), float(hi)


def decide(rows: pd.DataFrame, turn_year: int) -> dict:
    """Apply the rule at the turn from `turn_year` to `turn_year`+1. See docs/CHALLENGER_SELECTION_RULE.md.
    Returns {decision, reasons, months, ...}. decision is 'challenger' only when every condition holds; 'served'
    otherwise; 'insufficient' (served stays) when fewer than MIN_EVAL_MONTHS months can be compared."""
    r = scored(rows)
    months = evaluation_months(turn_year, r["month"].unique())
    base = {"turn": f"{turn_year}/{turn_year + 1}", "months": months, "seen_months_excluded": sorted(SEEN_MONTHS)}
    if len(months) < MIN_EVAL_MONTHS:
        return {**base, "decision": INSUFFICIENT,
                "reasons": [f"{len(months)} evaluable months, the rule needs {MIN_EVAL_MONTHS}: the served model stays"]}
    r = r[r["month"].isin(months)]
    half = len(months) // 2
    h1, h2 = r[r.month.isin(months[:half])], r[r.month.isin(months[half:])]
    delta = lambda x: (pooled_wape(x.actual.to_numpy(float), x.err_challenger.to_numpy(float))  # noqa: E731
                       - pooled_wape(x.actual.to_numpy(float), x.err_served.to_numpy(float)))
    d, d1, d2 = delta(r), delta(h1), delta(h2)
    lo, hi = bootstrap_delta(r)
    checks = {
        "1_lower_pooled_wape_over_the_window": d < 0,
        "2_lower_in_the_first_half": d1 < 0,
        "3_lower_in_the_second_half": d2 < 0,
        "4_bootstrap_interval_entirely_below_zero": hi < 0,
    }
    decision = CHALLENGER if all(checks.values()) else SERVED
    return {**base, "decision": decision, "checks": checks,
            "reasons": [k for k, v in checks.items() if not v] if decision == SERVED else [],
            "delta_pooled_wape": d, "delta_first_half": d1, "delta_second_half": d2,
            "halves": [months[:half], months[half:]], "bootstrap_95": [lo, hi],
            "product_months": int(len(r)), "products": int(r.product_key.nunique()),
            "served": summary(r, "served"), "challenger": summary(r, "challenger")}
