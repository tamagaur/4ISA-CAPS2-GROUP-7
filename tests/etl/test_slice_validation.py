"""tests/etl/test_slice_validation.py - the slice loader's pre-delete checks
(2026-09-30, layout guard: analytics/etl/slice_validation.py). No database: the
history each check reads is passed in as the aggregate the loader would read.

Covers: the committed bands file, unit price refused outside the widened band
(a qty <-> amount swap), peso outside its band only warns, the known-SKU floor
refuses (and only warns for the month the bands file excludes), too little
history warns, a non-number refuses, and the totals-row allowlist.
"""
from __future__ import annotations

import pandas as pd
import pytest

from analytics.etl import slice_validation as sv

BANDS = sv.load_bands()


def hist_months(n: int, amt: float, qty: float, site=None, start=1) -> dict:
    """n prior months 2025-01.. each with the same totals."""
    return {(f"2025-{m:02d}", site): (amt, amt, qty) for m in range(start, start + n)}


def rows(amounts, qtys, month="2025-12", site="pangasinan", skus=None):
    df = pd.DataFrame({"net_amount": amounts, "quantity": qtys})
    if skus is not None:
        df["sku_code"] = skus
    return df, pd.DataFrame({"month": [month] * len(df), "site": [site] * len(df)})


def checks(findings, severity):
    return sorted({f.check for f in findings if f.severity == severity})


def test_the_bands_file_is_the_committed_measurement():
    assert BANDS["widen"] == 0.10
    assert set(BANDS["families"]) == set(sv.MEASURES)
    assert BANDS["families"]["sell_out"]["unit_price"] == {"min": 0.9346, "max": 1.1779, "n": 28}
    assert BANDS["families"]["inventory_sign_off"]["known_sku"]["min"] == 0.7130
    assert BANDS["families"]["inventory_sign_off"]["known_sku"]["excluded_months"] == ["2023-08"]


def test_a_slice_inside_its_bands_passes():
    df, sl = rows([5000.0, 1000.0], [10, 2])
    assert sv.validate_rows("sell_out", df, sl, hist_months(6, 6000.0, 12, "pangasinan")) == []


def test_a_quantity_amount_swap_is_refused_on_unit_price():
    df, sl = rows([10.0, 2.0], [5000.0, 1000.0])          # the two columns' values swapped
    f = sv.validate_rows("sell_out", df, sl, hist_months(6, 6000.0, 12, "pangasinan"))
    assert "unit_price" in checks(f, "refuse")


def test_unit_price_just_inside_the_widened_band_passes_and_just_outside_refuses():
    hi = BANDS["families"]["sell_out"]["unit_price"]["max"] * 1.10
    for factor, refused in ((hi * 0.999, False), (hi * 1.001, True)):
        df, sl = rows([500.0 * factor * 12], [12])
        f = sv.validate_rows("sell_out", df, sl, hist_months(6, 6000.0, 12, "pangasinan"))
        assert ("unit_price" in checks(f, "refuse")) is refused, factor


def test_a_peso_total_outside_its_band_only_warns():
    df, sl = rows([60000.0], [120])                      # 10x the usual month, same unit price
    f = sv.validate_rows("sell_out", df, sl, hist_months(6, 6000.0, 12, "pangasinan"))
    assert checks(f, "warn") == ["peso"] and checks(f, "refuse") == []


def test_no_quantities_where_every_measured_month_had_them_is_refused():
    df, sl = rows([6000.0], [None])
    f = sv.validate_rows("sell_out", df, sl, hist_months(6, 6000.0, 12, "pangasinan"))
    assert "unit_price" in checks(f, "refuse")


def test_fewer_than_three_prior_months_warns_and_skips_the_bands():
    df, sl = rows([10.0], [5000.0])                      # would be refused with history
    f = sv.validate_rows("sell_out", df, sl, hist_months(2, 6000.0, 12, "pangasinan"))
    assert checks(f, "warn") == ["history"] and checks(f, "refuse") == []


def test_a_value_that_is_not_a_number_is_refused():
    df, sl = rows(["12,00x", 5.0], [1, 1])
    assert checks(sv.validate_rows("sell_out", df, sl, {}), "refuse") == ["types"]


def _inv(skus, month):
    df = pd.DataFrame({"valuation": [100.0] * len(skus), "quantity_on_hand": [1.0] * len(skus), "sku_code": skus})
    return df, pd.DataFrame({"month": [month] * len(skus), "site": ["ilocos"] * len(skus)})


def test_known_sku_share_below_the_floor_is_refused():
    known = {f"9D{i:05d}" for i in range(100)}
    hist = {(f"2025-0{m}", "ilocos"): (100.0 * 10, 100.0 * 10, 10.0) for m in range(1, 7)}
    ok = sorted(known)[:8] + ["NEW1", "NEW2"]            # 80% known >= 71.3%
    bad = sorted(known)[:5] + [f"X{i}" for i in range(5)]  # 50% known
    for skus, refused in ((ok, False), (bad, True)):
        df, sl = _inv(skus, "2025-09")
        f = sv.validate_rows("inventory_sign_off", df, sl, hist, sku_lookup=lambda m: known)
        assert ("known_sku" in checks(f, "refuse")) is refused


def test_the_excluded_month_only_warns_on_known_skus():
    known = {"9D00001"}
    hist = {(f"2023-0{m}", "ilocos"): (1000.0, 1000.0, 10.0) for m in range(1, 7)}
    df, sl = _inv(["11858", "11859"], "2023-08")
    f = sv.validate_rows("inventory_sign_off", df, sl, hist, sku_lookup=lambda m: known)
    assert "known_sku" in checks(f, "warn") and "known_sku" not in checks(f, "refuse")


def test_the_totals_allowlist_is_keyed_by_file_content(tmp_path):
    entries = sv._allowlist()
    assert len(entries) == 6
    f = tmp_path / "2025 DECMBER PURCHASES.xlsx"
    f.write_bytes(b"not the listed file")
    assert sv.checksum_allowed(f, "PANGASINAN PURCHASE") is None   # same name, different bytes


@pytest.mark.parametrize("family", sorted(sv.MEASURES))
def test_every_family_has_a_band_entry(family):
    assert family in BANDS["families"]
