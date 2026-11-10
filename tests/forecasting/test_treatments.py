"""analytics.forecasting.treatments: succession and fading, served inside router.route() (2026-11-10)."""
import pandas as pd
import pytest

from analytics.forecasting import treatments as T
from analytics.forecasting.router import route


def _series(values, start="2024-01-01"):
    return pd.Series([float(v) for v in values], index=pd.date_range(start, periods=len(values), freq="MS"))


T_MONTH = pd.Timestamp("2025-04-01")   # the month after each 15-month test series
NO_SUCCESSOR = T.ProductContext(promo_name=False, successor_first_sales=())


def test_no_context_means_untreated():
    s = _series([1000] * 12 + [900, 100, 50])
    assert T.apply(s, T_MONTH, 777.0, None) == (777.0, None)


def test_fading_caps_at_last_three_month_mean():
    s = _series([1000] * 12 + [300, 200, 100])          # last 3 mean 200 < 0.5 x 12-month mean
    v, name = T.apply(s, T_MONTH, 700.0, NO_SUCCESSOR)
    assert name == "fading" and v == pytest.approx(200.0)


def test_fading_never_raises_the_forecast():
    s = _series([1000] * 12 + [300, 200, 100])
    v, _ = T.apply(s, T_MONTH, 50.0, NO_SUCCESSOR)
    assert v == 50.0


def test_succession_follows_last_month_when_a_related_code_just_started():
    s = _series([1000] * 14 + [100])                    # last month < 0.5 x 12-month mean
    ctx = T.ProductContext(promo_name=False, successor_first_sales=(pd.Timestamp("2025-01-01"),))
    v, name = T.apply(s, T_MONTH, 950.0, ctx)
    assert name == "succession" and v == 100.0


def test_succession_ignores_a_related_code_started_long_ago_or_later():
    s = _series([1000] * 14 + [100])
    for start in ("2024-06-01", "2025-04-01", "2025-06-01"):
        ctx = T.ProductContext(promo_name=False, successor_first_sales=(pd.Timestamp(start),))
        assert T.apply(s, T_MONTH, 950.0, ctx)[1] != "succession"


def test_promo_and_low_volume_are_left_on_the_served_forecast():
    s = _series([1000] * 12 + [300, 200, 100])
    assert T.apply(s, T_MONTH, 700.0, T.ProductContext(True, ()))[1] is None
    low = _series([50] * 12 + [20, 10, 5])                # under 500 pieces in 6 months
    assert T.apply(low, T_MONTH, 40.0, NO_SUCCESSOR)[1] is None


def test_stable_product_untouched():
    s = _series([1000, 1100, 900] * 5)
    assert T.apply(s, T_MONTH, 1000.0, NO_SUCCESSOR) == (1000.0, None)


def test_route_applies_the_treatment_after_the_model():
    s = _series([1000] * 12 + [300, 200, 100, 0])         # target 2025-04 needs the month in the index
    target = pd.Timestamp("2025-04-01")
    plain = route(s, target)
    treated = route(s, target, context=NO_SUCCESSOR)
    assert treated["treatment"] == "fading"
    assert treated["value_before_treatment"] == pytest.approx(plain["value"])
    assert treated["value"] == pytest.approx(min(plain["value"], 200.0))


def test_related_codes_by_content_or_name_family():
    meta = pd.DataFrame({"product_key": [1, 2, 3, 4],
                         "product_name": ["SURF FABCON BLOSSOM FRESH SOL 360X28ML", "SURF FABCON BLOSSOM FRESH STR 360X28ML",
                                          "SURF FABCON BLOSSOM FRESH 24X800ML", "KNORR CUBES 48X10G"],
                         "brand": ["SURF", "SURF", "SURF", "KNORR"], "category_path": ["FAB", "FAB", "FAB", "FOOD"]})
    first = {1: pd.Timestamp("2023-01-01"), 2: pd.Timestamp("2025-08-01"), 3: pd.Timestamp("2023-05-01"),
             4: pd.Timestamp("2023-01-01")}
    ctx = T.build_contexts(meta, first)
    assert pd.Timestamp("2025-08-01") in ctx[1].successor_first_sales     # same content, re-coded
    assert ctx[4].successor_first_sales == ()                            # nothing related in its brand x category
