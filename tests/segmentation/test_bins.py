from analytics.segmentation.bins import length_v1


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
