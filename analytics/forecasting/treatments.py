"""
analytics.forecasting.treatments - the two forecastability treatments that held in both backtest windows, applied to the
served forecast inside router.route() (served from 2026-11-10, Kelvin's brief "switch on succession and fading").

Evidence: reports/experiments/forecastability_2026-11-10/ (rules committed before scoring at f3ffe47, scored at 8a4f78d).
Together, on the as-served backtest, all products: pooled WAPE -3.5 pts [-7.3, -1.3] in 2025-09..2026-02 and -2.6
[-4.4, -1.5] in 2024-01..2025-08 (95% product bootstrap), MASE 0.776 -> 0.731 and 0.888 -> 0.871.

At forecast month t, from the product's history strictly before t (from its first sale; a blank month counts 0 here, as in
the backtest that tested the rule), first match wins:

  PROMO/LOW   the name is a promo or bundle (PROMO_NAME_RE) or the last 6 months sum to < LOW_PIECES_6M: untouched
              (the promo treatment failed for planned products in both windows; served is kept).
  SUCCESSION  last month < SUCCESSION_DROP x mean of the last 12 months AND a code of the same brand x category, holding the
              same content per piece (+-10%, same unit) or the same name family, made its first sale in the 3 months before
              t (a re-code: demand is moving to the new code). Served value -> last month.
  FADING      collapse ratio (review_flag.collapse_ratio: mean of the last 3 months / mean of the last 12) < the review
              rule's REVIEW_COLLAPSE_RATIO. Served value -> min(served, mean of the last 3 months).

Both act on the final value, after the calendar factor, exactly as scored. A product with no context (`None`) is not
treated: every caller that serves, stores or scores a served forecast passes one (run_baseline_forecast, accuracy_as_served,
compute_review_flags). Switches: analytics.params.SERVE_SUCCESSION / SERVE_FADING.

Pure functions, no DB access.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from analytics.forecasting.review_flag import collapse_ratio
from analytics.params import (
    LOW_PIECES_6M,
    REVIEW_COLLAPSE_RATIO,
    SERVE_FADING,
    SERVE_SUCCESSION,
    SUCCESSION_CONTENT_TOL,
    SUCCESSION_DROP,
    SUCCESSION_NEW_CODE_MONTHS,
)

PROMO_NAME_RE = r"\(\d+\+\d+\)|\+|PROMO|PRMO|PRM |DUO|DUA"

# Name family (the forecastability checks' FINE key): sizes, pack/format and promo words dropped, abbreviations expanded.
_ABBR = {"MNTHL": "MENTHOL", "FRSH": "FRESH", "BLOSSM": "BLOSSOM", "KRTN": "KERATIN", "KRATIN": "KERATIN",
         "STRT": "STRAIGHT", "ST": "STRAIGHT", "HF": "HAIRFALL", "HFALL": "HAIRFALL", "RBOND": "REBOND",
         "PWD": "POWDER", "ACBLCH": "ACTIVEBLEACH", "CUBES": "CUBE", "ROSEFRSH": "ROSE FRESH",
         "SUNFRESH": "SUN FRESH", "SPRT": "SPORT", "MYNS": "MAYONNAISE", "DRSG": "DRESSING"}
_DROP = {"BN", "BLN", "SINGLES", "SNGLS", "PANTRY", "SAVERS", "SACH", "SCH", "STR", "SOL", "PCH", "POU", "MP", "DUO",
         "DUA", "DUA2", "PROMO", "PRMO", "PRM", "N", "HL", "NEW", "L", "S", "SIX", "ATL", "DOY", "DISPENSERS", "RLN",
         "RL", "ULP", "TKR", "RO", "HC", "TMT", "CP", "SH", "STD", "HS", "3C", "+", "X"}


def name_family(name: str, brand: str, cat: str) -> str:
    n = re.sub(r"[​]", "", name.upper())
    toks = []
    for t in re.split(r"\s+", n):
        if not t or re.search(r"\d", t):
            continue
        toks.extend(_ABBR.get(t, t).split())
    b = brand.upper().replace("CREAMSILK", "CREAM SILK").replace("CLOSEUP", "CLOSE UP").split()
    while toks and b and toks[0] in (b[0], "CLOSEUP", "CREAMSILK"):
        toks.pop(0)
        if b and toks and toks[0] in b[1:]:
            toks.pop(0)
        b = []
    toks = [t for t in toks if t not in _DROP]
    return f"{brand}|{cat}|{' '.join(toks[:2])}"


def content(name: str) -> tuple[float, str] | None:
    """Content of one piece from the trailing size: '24X12X11G' -> (11, 'G'), '6X1.6L' -> (1600, 'ML'). Bundles: None."""
    n = name.upper().replace("​", "")
    if "+" in n and re.search(r"\(\d+G\+\d+G\)|\(\d+\+\d+\)", n):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(KG|G|ML|L)\s*$", n)
    if not m:
        return None
    v, unit = float(m.group(1)), m.group(2)
    return (v * 1000, "G") if unit == "KG" else (v * 1000, "ML") if unit == "L" else (v, unit)


@dataclass(frozen=True)
class ProductContext:
    promo_name: bool
    successor_first_sales: tuple[pd.Timestamp, ...]   # first-sale months of related codes (possible successors)


def build_contexts(meta: pd.DataFrame, first_sale: dict) -> dict[int, ProductContext]:
    """meta: product_key, product_name, brand, category_path (every Unilever code). first_sale: {product_key: Timestamp of
    its first positive month}. A related code shares brand x category and either the content per piece (+-tol, same
    unit) or the name family."""
    m = meta.copy()
    m["brand"] = m["brand"].fillna("?")
    m["category_path"] = m["category_path"].fillna("UNCLASSIFIED")
    m["bc"] = m.brand + "|" + m.category_path
    m["fam"] = [name_family(n, b, c) for n, b, c in zip(m.product_name, m.brand, m.category_path)]
    m["ct"] = [content(n) for n in m.product_name]
    out = {}
    for _, g in m.groupby("bc"):
        recs = list(g.itertuples())
        for r in recs:
            starts = []
            for j in recs:
                if j.product_key == r.product_key or int(j.product_key) not in first_sale:
                    continue
                same_ct = bool(r.ct and j.ct and r.ct[1] == j.ct[1] and abs(j.ct[0] / r.ct[0] - 1) <= SUCCESSION_CONTENT_TOL)
                if same_ct or j.fam == r.fam:
                    starts.append(first_sale[int(j.product_key)])
            out[int(r.product_key)] = ProductContext(bool(re.search(PROMO_NAME_RE, r.product_name)), tuple(sorted(starts)))
    return out


def first_sales(series_by_key: dict) -> dict:
    out = {}
    for k, s in series_by_key.items():
        pos = s.index[s.fillna(0).to_numpy() > 0]
        if len(pos):
            out[int(k)] = pos[0]
    return out


def apply(series: pd.Series, target_month: pd.Timestamp, value: float, ctx: ProductContext | None) -> tuple[float, str | None]:
    """(treated value, treatment name or None)."""
    if ctx is None or value is None:
        return value, None
    h = series[series.index < target_month].fillna(0.0)
    sold = np.flatnonzero(h.to_numpy() > 0)
    h = h.iloc[sold[0]:] if len(sold) else h.iloc[:0]
    if not len(h):
        return value, None
    last = float(h.iloc[-1])
    if ctx.promo_name or float(h.tail(6).sum()) < LOW_PIECES_6M:
        return value, None
    if SERVE_SUCCESSION and len(h) >= 4:
        base12 = float(h.tail(12).mean())
        lo = target_month - pd.DateOffset(months=SUCCESSION_NEW_CODE_MONTHS)
        if base12 > 0 and last < SUCCESSION_DROP * base12 and any(lo <= f < target_month for f in ctx.successor_first_sales):
            return max(0.0, last), "succession"
    if SERVE_FADING:
        cr = collapse_ratio(series.fillna(0.0), target_month)
        if cr is not None and cr < REVIEW_COLLAPSE_RATIO:
            return max(0.0, min(value, float(h.tail(3).mean()))), "fading"
    return value, None
