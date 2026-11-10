"""tests/forecasting/test_challenger.py - the challenger forecast (damped_trend_v1) and the selection rule committed
before any comparison (docs/CHALLENGER_SELECTION_RULE.md). Pure: synthetic test series, no DB."""
from __future__ import annotations

import pathlib
import re

import numpy as np
import pandas as pd
import pytest

from analytics.forecasting import challenger as ch, router, selection_rule as sr

REPO = pathlib.Path(__file__).resolve().parents[2]


def _series(values, start="2023-01-01") -> pd.Series:
    return pd.Series(np.asarray(values, float), index=pd.date_range(start, periods=len(values), freq="MS"))


def _target(s: pd.Series) -> pd.Timestamp:
    return s.index[-1] + pd.offsets.MonthBegin(1)


# --- challenger -------------------------------------------------------------------------------------------------

def test_short_history_challenger_is_the_served_ma3():
    s = _series([120, 90, 150, 110, 130, 100])            # 6 sales months: the short bin, served MA3
    c, r = ch.challenger_route(s, _target(s)), router.route(s, _target(s))
    assert c["bin"] == r["bin"] == "short"
    assert c["method"] == "ma3" and c["value"] == pytest.approx(r["value"])


def test_insufficient_history_has_no_challenger():
    s = _series([50, 60])
    assert ch.challenger_route(s, _target(s))["value"] is None


def test_damped_trend_sits_below_ma3_on_a_steady_decline():
    # The diagnosed mechanism: a falling level. MA3 trails it by a step; the trend term follows it down.
    s = _series(np.linspace(2000, 900, 30))
    c = ch.challenger_route(s, _target(s))
    assert c["bin"] == "long" and c["method"] == "damped_trend" and not c["backup_fired"]
    assert c["value"] < c["ma3_value"]
    assert c["value"] >= 0


def test_guards_fall_back_to_ma3_as_the_router_does():
    # A steep fall to near zero: an undamped extrapolation goes below zero; whatever the fit gives, the served guards
    # apply (below zero / above the historical maximum -> MA3, reason kept), and the value is never negative.
    s = _series(list(np.linspace(5000, 50, 26)))
    c = ch.challenger_route(s, _target(s))
    assert c["value"] >= 0
    if c["backup_fired"]:
        assert c["method"] == "ma3" and c["value"] == pytest.approx(max(0.0, c["ma3_value"]))
        assert c["backup_reason"].split(":")[0] in {"below_zero", "above_historical_max", "damped_trend_failed"}


def test_failed_fit_falls_back_to_ma3(monkeypatch):
    monkeypatch.setattr(ch, "damped_trend_value", lambda h: (None, "damped_trend_failed: test"))
    s = _series(np.linspace(1000, 800, 20))
    c = ch.challenger_route(s, _target(s))
    assert c["backup_fired"] and c["method"] == "ma3" and c["value"] == pytest.approx(c["ma3_value"])


def test_calendar_factor_applied_the_same_way_as_served():
    s = _series(np.linspace(1500, 1000, 30))
    totals = _series(np.r_[np.full(12, 100.0), np.full(12, 100.0), np.full(6, 100.0)]) * 1.0
    totals.iloc[[11, 23]] = 150.0                          # Decembers sell 1.5x the 3 months before
    t = pd.Timestamp("2025-12-01")
    s = s[s.index < t]
    c = ch.challenger_route(s, t, calendar_totals=totals)
    r = router.route(s, t, calendar_totals=totals)
    assert c["calendar_factor"] == pytest.approx(r["calendar_factor"]) and c["calendar_factor"] > 1
    assert c["value"] == pytest.approx(c["value_before_calendar"] * c["calendar_factor"])


def test_blank_month_is_skipped_not_zero():
    vals = list(np.linspace(1200, 900, 25))
    vals[10] = np.nan
    s = _series(vals)
    a = ch.challenger_route(s, _target(s))
    b = ch.challenger_route(s.dropna(), _target(s))
    assert a["value"] == pytest.approx(b["value"])


def test_nothing_served_imports_the_challenger_or_the_rule():
    """The challenger is never served: the router, the forecast runner, the LP and the API do not import it."""
    pat = re.compile(r"\b(challenger|selection_rule)\b")
    served = [REPO / "analytics/forecasting/router.py", REPO / "scripts/run_baseline_forecast.py",
              REPO / "scripts/run_lp.py", REPO / "scripts/run_month.py", *sorted((REPO / "backend").rglob("*.py")),
              *sorted((REPO / "analytics/optimization").rglob("*.py"))]
    hits = [str(p.relative_to(REPO)) for p in served if p.exists()
            and any(pat.search(line) and ("import" in line) for line in p.read_text(encoding="utf-8").splitlines())]
    assert hits == []


# --- selection rule --------------------------------------------------------------------------------------------

def _rows(months, n_products=40, served_err=0.30, challenger_err=0.20, seed=1):
    rng = np.random.default_rng(seed)
    out = []
    for p in range(n_products):
        level = rng.uniform(100, 1000)
        for m in months:
            a = level * rng.uniform(0.8, 1.2)
            out.append({"product_key": p, "month": m, "actual": a,
                        "served": a * (1 + served_err * rng.choice([-1, 1])),
                        "challenger": a * (1 + challenger_err * rng.choice([-1, 1]))})
    return pd.DataFrame(out)


M2024 = [f"2024-{m:02d}" for m in range(1, 13)]


def test_rule_constants_are_the_committed_ones():
    assert sr.SEEN_MONTHS == {"2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"}
    assert (sr.MIN_EVAL_MONTHS, sr.BOOTSTRAP_RESAMPLES, sr.BOOTSTRAP_SEED, sr.CI_LEVEL) == (6, 2000, 20261110, 0.95)


def test_clearly_better_challenger_is_recommended():
    v = sr.decide(_rows(M2024), 2024)
    assert v["decision"] == sr.CHALLENGER and all(v["checks"].values())
    assert v["bootstrap_95"][1] < 0


def test_equal_forecasts_keep_the_served_model():
    r = _rows(M2024)
    r["challenger"] = r["served"]
    v = sr.decide(r, 2024)
    assert v["decision"] == sr.SERVED and v["delta_pooled_wape"] == pytest.approx(0)


def test_worse_in_one_half_keeps_the_served_model():
    r = _rows(M2024)
    second = r.month.isin(M2024[6:])
    r.loc[second, "challenger"] = r.loc[second, "actual"] * 1.9    # far worse in Jul-Dec
    v = sr.decide(r, 2024)
    assert v["decision"] == sr.SERVED and not v["checks"]["3_lower_in_the_second_half"]


def test_seen_months_never_enter_and_too_few_months_is_insufficient():
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    v = sr.decide(_rows(months), 2025)
    assert set(v["months"]).isdisjoint(sr.SEEN_MONTHS) and v["months"] == months[:8]
    only_seen = sr.decide(_rows(["2025-09", "2025-10", "2025-11", "2025-12"]), 2025)
    assert only_seen["decision"] == sr.INSUFFICIENT
    five = sr.decide(_rows(M2024[:5]), 2024)
    assert five["decision"] == sr.INSUFFICIENT


def test_rows_missing_either_forecast_or_the_actual_are_not_scored():
    r = _rows(M2024)
    r.loc[0, "challenger"] = np.nan
    r.loc[1, "actual"] = np.nan
    s = sr.scored(r)
    assert len(s) == len(r) - 2
    assert (s.err_served == s.served - s.actual).all() and (s.err_challenger == s.challenger - s.actual).all()


def test_decision_is_deterministic():
    r = _rows(M2024, challenger_err=0.28)
    assert sr.decide(r, 2024)["bootstrap_95"] == sr.decide(r, 2024)["bootstrap_95"]


def test_challenger_script_writes_only_its_own_table():
    """scripts/challenger_forecast.py may write forecast_challenger and nothing else (never Forecast_Result, the LP or
    the marts), and only behind --write, with --target-public off the throwaway server."""
    src = (REPO / "scripts/challenger_forecast.py").read_text(encoding="utf-8")
    written = set(re.findall(r"(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE)\s+([\w.]+)", src, flags=re.I))
    assert written == {"forecast_challenger"}
    assert "--target-public" in src and "is_throwaway" in src


def test_migration_0076_is_additive_and_locked():
    sql = (REPO / "analytics/db/migrations/0076_forecast_challenger.sql").read_text(encoding="utf-8")
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert re.search(r"ENABLE ROW LEVEL SECURITY", body)
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE|ALTER\s+TABLE\s+(?!forecast_challenger))\b", body, flags=re.I)
    assert ";" not in "\n".join(line for line in sql.splitlines() if line.lstrip().startswith("--"))
