"""analytics.demo.stock: Del Monte demonstration stock — no real anchor, a seeded months-of-cover draw against
that month's own demonstration demand."""
from analytics.demo.stock import CENTER_MONTHS_OF_COVER, generate_category_stock

DEMAND = {"2024-01": 100.0, "2024-02": 110.0, "2024-03": 90.0, "2024-04": 120.0}


def test_one_point_per_period_with_demand_none_is_skipped():
    pts = generate_category_stock("/A", {**DEMAND, "2024-05": None}, cv=0.1)
    assert [p.period for p in pts] == sorted(DEMAND)


def test_flat_cv_zero_gives_exactly_the_center_ratio_every_month():
    pts = generate_category_stock("/A", DEMAND, cv=0.0)
    for p in pts:
        assert p.months_of_cover == round(CENTER_MONTHS_OF_COVER, 4)
        assert p.quantity_on_hand == round(CENTER_MONTHS_OF_COVER * DEMAND[p.period], 2)


def test_never_negative_even_with_a_large_cv():
    pts = generate_category_stock("/A", DEMAND, cv=5.0)
    assert all(p.months_of_cover >= 0.0 and p.quantity_on_hand >= 0.0 for p in pts)


def test_same_seed_same_output_and_series_are_independent_of_sales_stream():
    a = generate_category_stock("/A", DEMAND, cv=0.2, seed=7)
    b = generate_category_stock("/A", DEMAND, cv=0.2, seed=7)
    assert a == b
    assert a != generate_category_stock("/A", DEMAND, cv=0.2, seed=8)
    assert a != generate_category_stock("/B", DEMAND, cv=0.2, seed=7)
