"""tests/synthetic/test_delmonte_generator.py - the Del Monte placeholder path (Phase C, 2026-09-21).

Same purpose as the Unilever generator: a placeholder for data SSM has not delivered, justified by correctness
only. These tests pin the defects Phase C fixed: NULL net_amount rows, duplicate sell-out keys, 'unknown'
periods, synthetic rows leaking into the "real" resample pool, and SKUs no real file vouches for.
Pure tmp_path fixtures - no DB, no real staging.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import scripts.convert_synthetic_to_staging as conv
import scripts.generate_synthetic_backfill as gen
from analytics.etl.extract._shared import PROVENANCE_COLUMNS


def _staged(rows: list[dict], family: str, period: str, region: str, demo: bool | None = None) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in PROVENANCE_COLUMNS:
        df[col] = None
    df["_period"], df["_region"], df["_doc_type"], df["_principal"] = period, region, family, "delmonte"
    df["_src_file"], df["_header_row"], df["_grain"] = "data/raw/Del Monte/x.xlsx", 1, "category"
    if demo is not None:
        df["is_demo"] = demo
    return df


@pytest.fixture
def sell_out_staging(tmp_path, monkeypatch):
    """Real 2025 sell_out for both regions (4 categories, one of them on many rows) plus a synthetic copy."""
    d = tmp_path / "staging" / "sell_out"; d.mkdir(parents=True)
    for region in gen.REGIONS:
        for month in ("2025-03", "2025-04"):
            rows = [{"__col0__": "BEVERAGE", "Total Without Tax": "1000.00", "Product Quantity": 10.0} for _ in range(6)]
            rows += [{"__col0__": c, "Total Without Tax": "500.00", "Product Quantity": 5.0} for c in ("CULINARY", "FRUITS", "DAIRY")]
            _staged(rows, "sell_out", month, region).to_parquet(d / f"REAL_{month}_{region}.parquet")
        _staged([{"__col0__": "SYNTH_ONLY", "Total Without Tax": "9.00", "Product Quantity": 1.0}] * 50,
                "sell_out", "2025-05", region, demo=True).to_parquet(d / f"SYNTH__SELL_OUT_2025-05_{region}.parquet")
    monkeypatch.setattr(gen, "REAL_STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(gen, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(gen, "DRY_RUN", False)
    return tmp_path


def _read_out(tmp_path, family="sell_out") -> pd.DataFrame:
    files = sorted((tmp_path / "out" / family).glob("*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def test_sell_out_key_is_unique_per_region_and_period(sell_out_staging):
    gen.generate_del_monte_family("sell_out")
    out = _read_out(sell_out_staging)
    assert len(out) > 0
    assert not out.assign(cat=out["__col0__"].str.strip()).duplicated(["_region", "_period", "cat"]).any()


def test_resample_pool_holds_real_rows_only(sell_out_staging):
    pool = gen.load_real_family_template("sell_out")
    assert "SYNTH_ONLY" not in set(pool["__col0__"]) and gen.POOL_REPORT["sell_out"]["dropped_is_demo"] == 100
    gen.generate_del_monte_family("sell_out")
    assert "SYNTH_ONLY" not in set(_read_out(sell_out_staging)["__col0__"])      # synthetic never breeds synthetic


def test_deterministic_with_the_fixed_seed(sell_out_staging):
    gen.generate_del_monte_family("sell_out"); first = _read_out(sell_out_staging)
    gen.generate_del_monte_family("sell_out"); second = _read_out(sell_out_staging)
    pd.testing.assert_frame_equal(first, second)
    assert first["is_demo"].eq(True).all()


def test_dry_run_writes_nothing(sell_out_staging, monkeypatch):
    monkeypatch.setattr(gen, "DRY_RUN", True)
    result = gen.generate_del_monte_family("sell_out")
    assert result["total_rows"] > 0 and not list((sell_out_staging / "out").rglob("*.parquet"))


def test_pool_has_no_row_without_a_net_amount(tmp_path, monkeypatch):
    d = tmp_path / "staging" / "sales_register"; d.mkdir(parents=True)
    rows = [{"Net Amount": "120.50"}, {"Net Amount": "88.00"}, {"Net Amount": None}, {"Net Amount": "JUAN DELA CRUZ"}]
    _staged(rows, "sales_register", "2025-06", "ilocos").to_parquet(d / "REAL.parquet")
    monkeypatch.setattr(gen, "REAL_STAGING_DIR", tmp_path / "staging")
    pool = gen.load_real_family_template("sales_register")
    assert len(pool) == 2 and pd.to_numeric(pool["Net Amount"], errors="coerce").notna().all()
    assert gen.POOL_REPORT["sales_register"]["dropped_real_rows_without_net_amount"] == 2


@pytest.mark.parametrize("period, ok", [("2021-01", True), ("2026-12", True), ("unknown", False), ("2021-13", False), ("2021-1", False)])
def test_only_a_real_month_is_a_period(period, ok):
    assert bool(conv.PERIOD_RE.match(period)) is ok


def test_converter_rejects_a_file_whose_period_is_not_a_month(tmp_path):
    result = conv.convert_file(tmp_path / "PURCHASE_ORDER_2021-13_ILOCOS.xlsx")     # rejected before the file is read
    assert "skipped" in result and "not a YYYY-MM month" in result["reason"]
    assert "skipped" in conv.convert_file(tmp_path / "PURCHASE_ORDER_unknown_ILOCOS.xlsx")


def test_skus_without_real_evidence_produce_no_rows():
    df = pd.DataFrame({"__col0__": ["11858 DM TOMATO SAUCE 250G", "7DML10045 DM INVENTED ITEM", "9DBL58403 DM 100% PINE", "JUICES", None],
                       "Quantity": [1, 2, 3, 4, 5]})
    kept, report = conv.restrict_inventory_to_real_evidence(df, {"11858"})
    assert kept["__col0__"].tolist() == ["11858 DM TOMATO SAUCE 250G", "JUICES", None]   # banner / blank rows are Transform's call
    assert report["excluded_rows"] == 2 and report["excluded_codes"] == ["7DML10045", "9DBL58403"]
    # a trailing-digit match is NOT evidence: the loader would still create a product under the invented full code
    assert conv.restrict_inventory_to_real_evidence(df, {"58403"})[1]["excluded_rows"] == 3


def test_the_fine_grained_bridge_is_retired():
    """Retired at Gate C 2026-09-21: it fitted on synthetic-inclusive history, and 6 real post-Jan-2025 months
    cannot support a refit. Missing Del Monte 2025 sell-out months stay missing."""
    for name in ("generate_delmonte_finegrained_bridge", "_fit_trend_seasonality", "_load_sell_out_full_history"):
        assert not hasattr(gen, name)


def test_converter_pools_ignore_synthetic_copies_in_staging(tmp_path, monkeypatch):
    """staging/sales_register/ holds synthetic copies next to the real files. The converter's 'real' pools must
    not read them, or its output changes with whatever synthetic files happen to be present."""
    d = tmp_path / "sales_register"; d.mkdir()
    real = [{"Net Amount": "100.00", "Town Display": "URDANETA", "Branch Code": "0632", "Salesman": "REAL PERSON"}] * 3
    fake = [{"Net Amount": "999.00", "Town Display": "NOWHERE", "Branch Code": "9999", "Salesman": "INVENTED NAME"}] * 50
    _staged(real, "sales_register", "2025-06", "pangasinan").to_parquet(d / "REAL.parquet")
    _staged(fake, "sales_register", "2025-06", "pangasinan", demo=True).to_parquet(d / "SYNTH__COPY.parquet")
    monkeypatch.setattr(conv, "REAL_STAGING_DIR", tmp_path)
    monkeypatch.setattr(conv, "_NET_AMOUNT_POOL_CACHE", None)
    monkeypatch.setattr(conv, "_TOWN_BRANCH_MAP_CACHE", None)
    assert conv.derive_net_amount_pool() == [100.0, 100.0, 100.0]
    assert conv.derive_town_branch_map()["pangasinan"]["pairs"] == [("URDANETA", "0632")]


@pytest.mark.parametrize("family", ["sales_return", "rmr_gs_bo"])
def test_remaining_generator_pools_filter_synthetic_rows(family):
    import inspect
    fn = {"sales_return": gen.generate_sales_return, "rmr_gs_bo": gen.generate_rmr_gs_bo}[family]
    assert "real_df[~_is_demo(real_df)]" in inspect.getsource(fn)


def test_sales_return_pool_has_no_row_without_a_net_amount(tmp_path, monkeypatch):
    """Header rows, Good/Bad Stock markers and blank lines sit in the real sheets. Resampled, they became 6 synthetic
    returns with no Net Amount in the 2026-09-21 scratch load. Most of this pool is such junk, so without the filter
    a draw of one is near certain and generate_sales_return()'s own guard raises."""
    d = tmp_path / "staging" / "sales_return"; d.mkdir(parents=True)
    good = {c: "x" for c in gen.SALES_RETURN_BUSINESS_COLS} | {"Net Amount": "250.00", "Untaxed Amount": "223.21", "Tax": "26.79",
                                                                 "Discount Amount": "0", "Balance": "0"}
    junk = {c: None for c in gen.SALES_RETURN_BUSINESS_COLS} | {"Customer Name": "GOOD STOCK"}
    for region in gen.REGIONS:
        for role in ("gs", "bo"):
            df = _staged([good] * 3 + [junk] * 9, "sales_return", "2025-06", region)
            df["_sheet_role"], df["_src_file"] = role, f"data/raw/Del Monte/{region}_{role}.xlsx"
            df.to_parquet(d / f"REAL_{region}_{role}.parquet")
    monkeypatch.setattr(gen, "REAL_STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(gen, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(gen, "DRY_RUN", False)
    monkeypatch.setattr(gen, "assign_town_branch", lambda rows, region, seed_key: rows)
    result = gen.generate_sales_return()
    out = _read_out(tmp_path, "sales_return")
    assert result["total_rows"] == len(out) > 0
    assert pd.to_numeric(out["Net Amount"], errors="coerce").notna().all()
    assert gen.POOL_REPORT["sales_return"] == {"rows_2025": 48, "pool_rows": 12, "dropped_real_rows_without_net_amount": 36}
