"""tests/synthetic/test_unilever_generator_v2.py - the v2 Unilever placeholder generator.

v2 is justified by existence-correctness only: a SKU gets pre-2023 placeholder
rows only where the 2021-22 SOH sheets witness that it existed, and every value
comes from that SKU's own real history. Pure pandas fixtures - no DB, no files
except one tmp_path case.
"""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

import scripts.generate_synthetic_backfill as gen

REAL_MONTHS = [str(p) for p in pd.period_range("2023-01", "2026-02", freq="M")]


def _real_rows(sku, months, qty):
    return [{gen.PRODUCT_COL: sku, gen.DESC_COL: f"desc {sku}", gen.PACK_SIZE_COL: "12x1", gen.QTY_PC_COL: float(q),
             gen.QTY_CS_COL: float(q) / 12, gen.GSV_COL: float(q) * 10, gen.AMT_COL: float(q) * 11.2, "_period": m}
            for m, q in zip(months, qty)]


def _witness(pairs):
    return pd.DataFrame([{"sku": s, "period": p} for s, first, last in pairs
                         for p in (str(x) for x in pd.period_range(first, last, freq="M"))])


@pytest.fixture(scope="module")
def profile():
    rng = np.random.default_rng(0)
    steady = lambda n: rng.integers(80, 121, n)
    rows = (
        _real_rows("W_OK", REAL_MONTHS, steady(38))
        + _real_rows("UNWIT", REAL_MONTHS[14:], steady(24))                       # first real row 2024-03, no witness
        + _real_rows("W_FEW", REAL_MONTHS[:4], steady(4))                         # 4 positive months -> < 6 residuals
        + _real_rows("W_RET", REAL_MONTHS[:10], [-50] * 9 + [10])                 # real sum <= 0
        + _real_rows("W_NEG", REAL_MONTHS, [(-30 if i % 5 == 0 else v) for i, v in enumerate(steady(38))])
        + _real_rows("W_GONE", REAL_MONTHS[17:], steady(21))                      # relisted 2024-06 after a gap
        + _real_rows("DEAD", REAL_MONTHS[:24], steady(24))                        # last row 2024-12
    )
    witness = _witness([("W_OK", "2021-05", "2022-12"), ("W_FEW", "2021-01", "2022-12"), ("W_RET", "2021-01", "2022-12"),
                        ("W_NEG", "2021-01", "2022-12"), ("W_GONE", "2021-01", "2021-09"), ("DEAD", "2021-01", "2022-12")])
    return gen.derive_sku_profile(pd.DataFrame(rows), witness)


@pytest.fixture(scope="module")
def out(profile):
    return gen.plan_unilever_sku_backfill(profile)[0]


def _pre(out, sku):
    return out[(out[gen.PRODUCT_COL] == sku) & (out["_period"] <= gen.PRE_REAL_END)]


def test_deterministic_with_the_fixed_seed(profile, out):
    again = gen.plan_unilever_sku_backfill(profile)[0]
    pd.testing.assert_frame_equal(out, again)
    shuffled = dict(reversed(list(profile.items())))                  # a row never depends on which other SKUs exist
    pd.testing.assert_frame_equal(out, gen.plan_unilever_sku_backfill(shuffled)[0])


def test_no_rows_before_witness_first(profile, out):
    assert len(_pre(out, "W_OK")) > 0
    assert _pre(out, "W_OK")["_period"].min() >= profile["W_OK"]["witness_first"] == "2021-05"


def test_unwitnessed_sku_gets_no_pre_2023_rows(out):
    assert len(_pre(out, "UNWIT")) == 0
    assert len(out[(out[gen.PRODUCT_COL] == "UNWIT") & (out["_period"] > gen.PRE_REAL_END)]) > 0   # it is alive: forward rows only


def test_gone_then_relisted_stops_at_witness_last_with_no_bridging(profile, out):
    assert profile["W_GONE"]["pre_window"][-1] == "2021-09"
    assert len(_pre(out, "W_GONE")) > 0 and _pre(out, "W_GONE")["_period"].max() <= "2021-09"


def test_values_stay_within_the_skus_own_real_range(profile, out):
    for sku, g in out.groupby(gen.PRODUCT_COL):
        positive = g[g[gen.QTY_PC_COL] > 0][gen.QTY_PC_COL]
        assert positive.between(profile[sku]["min_positive"], profile[sku]["max_qty"]).all()
        negative = g[g[gen.QTY_PC_COL] < 0][gen.QTY_PC_COL]
        assert set(negative).issubset(set(profile[sku]["negative_values"]))          # real magnitudes only


def test_no_negatives_when_the_sku_has_none(out):
    assert (out[out[gen.PRODUCT_COL] == "W_OK"][gen.QTY_PC_COL] > 0).all()
    assert (out[out[gen.PRODUCT_COL] == "W_NEG"][gen.QTY_PC_COL] < 0).any()         # and they do appear where they are real


def test_unique_sku_month(out):
    assert not out.duplicated([gen.PRODUCT_COL, "_period"]).any()


def test_no_rows_for_thin_or_returns_dominated_skus(profile, out):
    assert profile["W_FEW"]["excluded"] == "fewer_than_6_residuals" and profile["W_RET"]["excluded"] == "returns_dominated"
    assert out[gen.PRODUCT_COL].isin(["W_FEW", "W_RET"]).sum() == 0


def test_dead_sku_gets_no_forward_rows(profile, out):
    assert profile["DEAD"]["dead"] and not profile["DEAD"]["dead_by_runner_series"]
    assert (out[out[gen.PRODUCT_COL] == "DEAD"]["_period"] <= gen.PRE_REAL_END).all()


def test_seasonal_residuals_flag_is_off_by_default():
    for fn in (gen.generate_sku_series, gen.plan_unilever_sku_backfill, gen.run_unilever_sku_backfill):
        assert inspect.signature(fn).parameters["seasonal_residuals"].default is False


def test_every_row_is_labelled_is_demo_and_only_backfill_months_appear(out):
    assert out["is_demo"].eq(True).all()
    assert set(out["_period"]) <= set(gen.UNILEVER_BACKFILL_PERIODS)
    assert not out["_period"].between(gen.FIRST_REAL_PERIOD, "2026-02").any()       # never inside the real span


def test_every_witness_file_counts_including_a_high_overlap_month(tmp_path):
    """Adjacent SOH files share ~95% of their articles, so a high overlap is not evidence of a duplicate file:
    2021-07 stays a witness for every article in it (a rule that dropped it was withdrawn 2026-09-21)."""
    shared = [f"S{i}" for i in range(95)]
    w = pd.DataFrame([{"sku": s, "period": "2021-06", "stock": 1} for s in shared + ["JUNE_ONLY"]]
                     + [{"sku": s, "period": "2021-07", "stock": 1} for s in shared + [f"JULY_ONLY{i}" for i in range(5)]])
    path = tmp_path / "w.parquet"; w.to_parquet(path)
    witness, report = gen.load_witness(path)
    assert witness[witness.sku == "S0"].period.tolist() == ["2021-06", "2021-07"]
    assert report["files_discarded"] == 0 and report["adjacent_overlap_median"] == 0.95
    assert len(witness) == len(w)


def test_real_loader_ignores_materialised_synthetic_copies(tmp_path, monkeypatch):
    d = tmp_path / "unilever_sku"; d.mkdir()
    pd.DataFrame(_real_rows("R", ["2023-01"], [5])).to_parquet(d / "Real.parquet")
    pd.DataFrame(_real_rows("SYN", ["2021-01"], [5])).assign(is_demo=True).to_parquet(d / "SYNTH__UNILEVER_SKU_2021-01.parquet")
    monkeypatch.setattr(gen, "REAL_STAGING_DIR", tmp_path)
    assert gen.load_real_unilever_sku()[gen.PRODUCT_COL].tolist() == ["R"]
