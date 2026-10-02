"""
backend.chart_insights — the Dashboard's chart-story fields, computed from
the same per-period figures the charts plot (design pass 2026-09-26).

Three kinds of output, all consumed verbatim by the frontend so no number,
month or direction is ever typed into JSX:

  kpi_trend            — a KPI card's own months as sparkline points, plus
                         the change vs the previous month with data.
  sales_vs_stock_insight — one plain sentence saying what the hero chart
                         shows, and the sales series' peak/low months for
                         the chart to label.
  portfolio_forecast_insight — one plain sentence comparing the forecast
                         bucket with the last actual month.

Same honest-null contract as the router: anything that cannot be computed
from real values is None, never a guess — the frontend renders nothing in
that case. Pure functions, no DB.
"""
from __future__ import annotations

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_label(period: str | None) -> str | None:
    """'2026-02' -> 'Feb 2026' — the same wording the frontend's
    periodLabel() renders, so a backend sentence and a frontend caption can
    never disagree about a month's name."""
    if not period:
        return None
    year, _, num = str(period).partition("-")
    try:
        return f"{_MONTHS[int(num) - 1]} {year}"
    except (ValueError, IndexError):
        return str(period)


def compact_pesos(value: float) -> str:
    """₱27.9M / ₱504k / ₱37 — mirrors frontend formatCompactPesos, so a
    figure inside an insight sentence matches the axis tick beside it."""
    abs_v = abs(float(value))
    if abs_v >= 1_000_000:
        millions = abs_v / 1_000_000
        text = f"{millions:.0f}" if millions == int(millions) else f"{millions:.1f}"
        return f"₱{text}M"
    if abs_v >= 1_000:
        return f"₱{round(abs_v / 1000):d}k"
    return f"₱{round(abs_v):d}"


def _pct_change(latest: float, prev: float) -> float | None:
    if prev is None or latest is None or prev == 0:
        return None
    return round((latest - prev) / abs(prev) * 100, 1)


def _months_between(earlier: str, later: str) -> int:
    """Whole months from one 'YYYY-MM' period to a later one."""
    ey, em = (int(x) for x in str(earlier)[:7].split("-"))
    ly, lm = (int(x) for x in str(later)[:7].split("-"))
    return (ly - ey) * 12 + (lm - em)


def kpi_trend(
    by_period: dict[str, float | None],
    latest_period: str | None,
    unusual: dict[str, str] | None = None,
) -> dict | None:
    """Sparkline points + month-over-month delta for one KPI card.

    points: every period with a real value, oldest first — nulls are
    dropped, never zero-filled (a missing month is not zero demand).
    delta_pct compares latest_period's value with the nearest EARLIER
    period that has one (the same walk-back the sales card itself uses),
    so the delta always describes two real months. months_apart says how
    far back that is, so a card can say so when it is not the month before
    (Del Monte's sell-out skips Oct–Nov 2025; the stock card's latest
    snapshot can sit well past the picked range). None when there is
    nothing real to plot.

    unusual: {period: reason} for months the team has reviewed and judged
    unusual (backend/data_notes.py). Such a month stays in `points` — it
    really was counted — but the walk-back passes over it, and `skipped`
    lists what it passed so the card can say so. The stock card read
    "−51.3% vs Feb 2026" against Unilever's outlier count; it now compares
    Mar 2026 with Jan 2026. If the card's own month is the unusual one, no
    delta is given (latest_unusual says why): a change measured from an
    outlier is no more true than one measured to it."""
    unusual = unusual or {}
    points = [
        {"period": p, "value": round(float(v), 2)}
        for p, v in sorted(by_period.items())
        if v is not None
    ]
    if not points:
        return None
    latest = next((pt for pt in reversed(points) if latest_period is None or pt["period"] <= latest_period), None)
    if latest is None:
        return None
    latest_unusual = unusual.get(latest["period"])
    prev = None if latest_unusual else next(
        (pt for pt in reversed(points) if pt["period"] < latest["period"] and pt["period"] not in unusual),
        None,
    )
    skipped = [
        {"period": pt["period"], "reason": unusual[pt["period"]]}
        for pt in points
        if prev is not None and prev["period"] < pt["period"] < latest["period"] and pt["period"] in unusual
    ]
    return {
        "points": points,
        "latest_period": latest["period"],
        "prev_period": prev["period"] if prev else None,
        "prev_value": prev["value"] if prev else None,
        "delta_pct": _pct_change(latest["value"], prev["value"]) if prev else None,
        "months_apart": _months_between(prev["period"], latest["period"]) if prev else None,
        "skipped": skipped,
        "latest_unusual": latest_unusual,
    }


def sales_vs_stock_insight(series: list[dict], unusual_stock: dict[str, str] | None = None) -> dict | None:
    """One sentence + the sales peak/low, from sales_vs_stock's own rows.

    The sentence compares the latest real sales month with the previous
    one and states the latest stock valuation; the highlights mark the
    window's best and worst sales months so the chart can label them.
    Peak/low need >= 3 real months and distinct months, or they are None —
    two points have no 'extreme' worth labelling.

    unusual_stock: {period: reason} for stock counts the team judged unusual
    (backend/data_notes.py). The sentence quotes the latest stock month that
    is NOT one of them — it said stock "stood at ₱46.6M in Feb 2026", which
    was Unilever's outlier count — and says a later count was passed over."""
    unusual_stock = unusual_stock or {}
    sales_pts = [r for r in series if r.get("sales") is not None]
    all_stock_pts = [r for r in series if r.get("stock_on_hand") is not None]
    stock_pts = [r for r in all_stock_pts if r["period"] not in unusual_stock]
    if not sales_pts:
        return None

    latest = sales_pts[-1]
    prev = sales_pts[-2] if len(sales_pts) >= 2 else None
    pct = _pct_change(latest["sales"], prev["sales"]) if prev else None
    if prev and pct is not None:
        verb = "rose" if pct > 0 else "fell" if pct < 0 else "held flat"
        if pct == 0:
            sales_part = (
                f"Sales held flat at {compact_pesos(latest['sales'])} "
                f"from {month_label(prev['period'])} to {month_label(latest['period'])}"
            )
        else:
            sales_part = (
                f"Sales {verb} {abs(pct)}% from {compact_pesos(prev['sales'])} in {month_label(prev['period'])} "
                f"to {compact_pesos(latest['sales'])} in {month_label(latest['period'])}"
            )
    else:
        sales_part = f"Sales were {compact_pesos(latest['sales'])} in {month_label(latest['period'])}"

    if stock_pts:
        s = stock_pts[-1]
        passed = [r["period"] for r in all_stock_pts if r["period"] > s["period"]]
        aside = (
            f" ({' and '.join(month_label(p) for p in passed)}'s count is marked as unusual on the chart)"
            if passed else ""
        )
        stock_part = (
            f"; stock on hand stood at {compact_pesos(s['stock_on_hand'])} in {month_label(s['period'])}{aside}."
        )
    else:
        stock_part = "."

    peak = low = None
    if len(sales_pts) >= 3:
        peak_row = max(sales_pts, key=lambda r: r["sales"])
        low_row = min(sales_pts, key=lambda r: r["sales"])
        if peak_row["period"] != low_row["period"]:
            peak = {"period": peak_row["period"], "value": round(float(peak_row["sales"]), 2),
                    "label": f"Peak · {compact_pesos(peak_row['sales'])}"}
            low = {"period": low_row["period"], "value": round(float(low_row["sales"]), 2),
                   "label": f"Low · {compact_pesos(low_row['sales'])}"}

    return {"text": sales_part + stock_part, "peak": peak, "low": low}


def portfolio_forecast_insight(series: list[dict]) -> dict | None:
    """One sentence for the portfolio forecast card: the forecast bucket's
    total against the last actual month — only when that month is the one
    right before the forecast's. With a picked range ending earlier the
    sentence used to compare Mar 2026's forecast with Jun 2024's sales
    ("247.4% above"), which says nothing about demand now; the forecast is
    then stated on its own. None without a forecast bucket."""
    forecast_pts = [r for r in series if r.get("forecast") is not None and r.get("actual") is None]
    actual_pts = [r for r in series if r.get("actual") is not None]
    if not forecast_pts:
        return None
    target = forecast_pts[0]
    qty = f"{round(float(target['forecast'])):,d}"
    adjacent = bool(actual_pts) and _months_between(actual_pts[-1]["period"], target["period"]) == 1
    if adjacent and float(actual_pts[-1]["actual"]) > 0:
        last = actual_pts[-1]
        pct = _pct_change(float(target["forecast"]), float(last["actual"]))
        if pct is not None and pct != 0:
            direction = "above" if pct > 0 else "below"
            text = (
                f"The {month_label(target['period'])} forecast is {qty} pieces — "
                f"{abs(pct)}% {direction} the {round(float(last['actual'])):,d} sold in {month_label(last['period'])}."
            )
        else:
            text = (
                f"The {month_label(target['period'])} forecast is {qty} pieces, "
                f"level with {month_label(last['period'])}'s actual demand."
            )
    else:
        text = f"The {month_label(target['period'])} forecast is {qty} pieces."
    return {"text": text, "forecast_period": target["period"]}
