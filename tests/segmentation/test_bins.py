from analytics.segmentation.bins import (
    length_v1, length_v2, trend_v1, volatility_v1, stability_v1, combined_v1,
)


def test_insufficient_below_three():
    b, reason = length_v1(2)
    assert b == "insufficient"
    assert "2" in reason


def test_short_at_lower_boundary():
    b, _ = length_v1(3)
    assert b == "short"


def test_short_at_upper_boundary():
    b, _ = length_v1(11)
    assert b == "short"


def test_long_at_boundary():
    b, reason = length_v1(12)
    assert b == "long"
    assert "12" in reason


def test_long_above_boundary():
    b, _ = length_v1(38)
    assert b == "long"


def test_length_v2_matches_v1_below_twelve_and_splits_long():
    assert [length_v2(n)[0] for n in (2, 3, 11, 12, 23, 24, 38)] == [
        "insufficient", "short", "short", "medium", "medium", "long", "long"]


def test_trend_v1_gates_on_history_before_reading_trend():
    assert trend_v1(2, "up", 0.01, 5.0)[0] == "insufficient"
    b, reason = trend_v1(30, "down", 0.003, -12.34)
    assert b == "down"
    assert "-12.3" in reason and "0.0030" in reason


def test_volatility_v1_fixed_cutoffs():
    assert [volatility_v1(30, cv)[0] for cv in (0.49, 0.5, 0.99, 1.0)] == ["low", "medium", "medium", "high"]
    assert volatility_v1(2, 0.2)[0] == "insufficient"
    assert volatility_v1(30, None)[0] == "insufficient"


def test_stability_v1_passes_group_through():
    assert stability_v1("at_least_30", 33, 38) == ("at_least_30", "Tier A in 33 of 38 periods")


def test_combined_v1_consults_trend_only_at_24_plus():
    assert combined_v1(23, "up", 0.01, 5.0)[0] == "medium"
    assert [combined_v1(24, t, 0.01, 1.0)[0] for t in ("up", "down", "none")] == [
        "long_up", "long_down", "long_flat"]
    assert combined_v1(2, "none", None, None)[0] == "insufficient"
