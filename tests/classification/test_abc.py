"""
tests/classification/test_abc.py — Tests for analytics.classification.abc.

Phase 3C (CLAUDE.md Steps 10–11 — Checkpoint: all active SKUs have a tier; no nulls):
  test_tier_assignment_coverage   — every SKU receives a tier (no nulls)
  test_pareto_split               — A-tier cumulative share ≤ 80%, C-tier ≥ 95%
  test_revenue_sort_descending    — SKUs sorted correctly before cumulative sum
  test_no_negative_revenue        — guard against data cleaning gaps upstream

"""

import pandas as pd
import pytest

from analytics.classification.abc import classify_abc


@pytest.fixture
def revenue_df() -> pd.DataFrame:
    """10 SKUs with a deliberately skewed revenue distribution so all
    three tiers are exercised."""
    return pd.DataFrame({
        "sku_id": [f"SKU-{i}" for i in range(1, 11)],
        "total_revenue": [4000, 3000, 1500, 800, 400, 200, 100, 50, 30, 20],
    })


def test_tier_assignment_coverage(revenue_df):
    """Every SKU receives a tier (no nulls)."""
    result = classify_abc(revenue_df)
    assert result["tier"].notna().all()
    assert set(result["tier"].unique()) <= {"A", "B", "C"}
    assert len(result) == len(revenue_df)


def test_pareto_split(revenue_df):
    """A-tier cumulative share <= 80%, C-tier >= 95% (each tier's rows
    sit on the correct side of its cumulative-share cutoff)."""
    result = classify_abc(revenue_df)

    a_rows = result[result["tier"] == "A"]
    b_rows = result[result["tier"] == "B"]
    c_rows = result[result["tier"] == "C"]

    assert (a_rows["cumulative_share"] <= 0.80).all()
    assert (b_rows["cumulative_share"] > 0.80).all()
    assert (b_rows["cumulative_share"] <= 0.95).all()
    assert (c_rows["cumulative_share"] > 0.95).all()
    # with this fixture's skew, at least one SKU should land in C
    assert not c_rows.empty


def test_revenue_sort_descending(revenue_df):
    """SKUs are sorted by revenue descending before the cumulative sum
    is taken (a Pareto curve is meaningless unsorted)."""
    result = classify_abc(revenue_df)
    revenues = result["total_revenue"].tolist()
    assert revenues == sorted(revenues, reverse=True)


def test_no_negative_revenue():
    """Guard against data cleaning gaps upstream: negative revenue must
    raise, never be silently classified."""
    bad_df = pd.DataFrame({
        "sku_id": ["SKU-1", "SKU-2"],
        "total_revenue": [100, -5],
    })
    with pytest.raises(ValueError):
        classify_abc(bad_df)


def test_missing_required_column_raises():
    bad_df = pd.DataFrame({"sku_id": ["SKU-1"]})
    with pytest.raises(ValueError):
        classify_abc(bad_df)


def test_duplicate_sku_id_raises():
    dup_df = pd.DataFrame({
        "sku_id": ["SKU-1", "SKU-1"],
        "total_revenue": [100, 50],
    })
    with pytest.raises(ValueError):
        classify_abc(dup_df)


def test_empty_input_returns_empty_output():
    empty_df = pd.DataFrame({"sku_id": [], "total_revenue": []})
    result = classify_abc(empty_df)
    assert result.empty
    assert list(result.columns) == ["sku_id", "total_revenue", "revenue_share", "cumulative_share", "tier", "boundary_flag"]


def test_revenue_share_sums_to_one(revenue_df):
    result = classify_abc(revenue_df)
    assert result["revenue_share"].sum() == pytest.approx(1.0)


def test_boundary_flag_marks_skus_near_a_cutoff():
    """Backlog #43: a SKU whose cumulative_share lands right at 80% (the
    A/B cutoff) should be flagged, one that lands comfortably inside a
    tier should not."""
    # Revenue chosen so cumulative_share lands at exactly 0.80 after the
    # 2nd SKU (400+400 = 800 of a 1000 total), and at 0.10 after the 3rd
    # (comfortably inside B, far from either cutoff).
    df = pd.DataFrame({
        "sku_id": ["SKU-1", "SKU-2", "SKU-3"],
        "total_revenue": [400, 400, 200],
    })
    result = classify_abc(df)
    at_cutoff = result[result["sku_id"] == "SKU-2"].iloc[0]
    assert at_cutoff["cumulative_share"] == pytest.approx(0.80)
    assert bool(at_cutoff["boundary_flag"]) is True

    first_row = result[result["sku_id"] == "SKU-1"].iloc[0]
    assert first_row["cumulative_share"] == pytest.approx(0.40)
    assert bool(first_row["boundary_flag"]) is False


def test_boundary_flag_false_for_all_zero_revenue():
    """No revenue means no meaningful cumulative_share to be 'near' a
    cutoff — must not be fabricated as flagged or unflagged by chance."""
    df = pd.DataFrame({"sku_id": ["SKU-1", "SKU-2"], "total_revenue": [0, 0]})
    result = classify_abc(df)
    assert (result["boundary_flag"] == False).all()  # noqa: E712 (explicit bool check, not truthiness)


def test_pareto_check_uses_the_top_fifth_and_the_manuscript_band():
    """Manuscript §3.4.4.2.2: valid when the top 20% of items earn 75-85%."""
    from analytics.classification.abc import PARETO_VALID_BAND, pareto_check
    shares = [0.45, 0.35] + [0.025] * 8  # top 2 of 10 earn 80%
    check = pareto_check(shares)
    assert check["top_count"] == 2
    assert check["ranked_count"] == 10
    assert check["revenue_share"] == pytest.approx(0.80)
    assert (check["band_low"], check["band_high"]) == PARETO_VALID_BAND
    assert check["passes"] is True


def test_pareto_check_fails_outside_the_band():
    from analytics.classification.abc import pareto_check
    assert pareto_check([0.1] * 10)["passes"] is False  # top 20% earn only 20%


def test_pareto_check_is_none_for_an_empty_run():
    from analytics.classification.abc import pareto_check
    assert pareto_check([]) is None


def test_abc_rules_are_the_constants_the_run_applies():
    from analytics.classification.abc import BOUNDARY_MARGIN, TIER_A_CUTOFF, TIER_B_CUTOFF, abc_rules
    assert abc_rules() == {"tier_a_cutoff": TIER_A_CUTOFF, "tier_b_cutoff": TIER_B_CUTOFF, "boundary_margin": BOUNDARY_MARGIN}
