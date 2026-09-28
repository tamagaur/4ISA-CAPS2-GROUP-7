"""Provenance guard (2026-09-28): a row from a synthetic source can never load as real.

A synthetic source is a _src_file under data/raw/Synthetic Data/ or a generator's GENERATED_BACKFILL_* name.
Its is_demo cell is not trusted: any value loads as true, and a blank raises instead of defaulting to real."""
import pandas as pd
import pytest

from analytics.etl.transform import (DEFAULT_CONFIG_DIR, SyntheticProvenanceError, coerce_is_demo_column,
                                     is_synthetic_source, transform_fact)

SYNTH_XLSX = "data/raw/Synthetic Data/SALES_REGISTER_2021-01_ILOCOS.xlsx"
SYNTH_GEN = "GENERATED_BACKFILL_sales_return_2026-04_ilocos_bo"
REAL = "data/raw/Del Monte/MONTHLY REPORT - JANUARY 2024/2024 JANUARY SALES RETURN.xlsx"


def frame(src_files, is_demo=None, with_flag=True):
    df = pd.DataFrame({"_src_file": src_files})
    if with_flag:
        df["is_demo"] = is_demo if is_demo is not None else [None] * len(src_files)
    return df


@pytest.mark.parametrize("blank", [None, "", "  ", float("nan")])
def test_blank_flag_on_a_synthetic_row_raises(blank):
    with pytest.raises(SyntheticProvenanceError):
        coerce_is_demo_column(frame([SYNTH_XLSX], [blank]))


def test_synthetic_source_without_an_is_demo_column_raises():
    with pytest.raises(SyntheticProvenanceError):
        coerce_is_demo_column(frame([SYNTH_GEN], with_flag=False))


@pytest.mark.parametrize("cell", [False, "False", "0", "no", True, "True"])
def test_synthetic_row_is_demo_whatever_the_cell_says(cell):
    out = coerce_is_demo_column(frame([SYNTH_XLSX, SYNTH_GEN], [cell, cell]))
    assert out["is_demo"].tolist() == [True, True]


def test_real_rows_are_unchanged_by_the_guard():
    out = coerce_is_demo_column(frame([REAL, REAL], [None, "True"]))
    assert out["is_demo"].tolist() == [False, True]
    untouched = frame([REAL], with_flag=False)
    assert coerce_is_demo_column(untouched) is untouched


def test_windows_paths_and_non_synthetic_look_alikes():
    s = is_synthetic_source(pd.DataFrame({"_src_file": [SYNTH_XLSX.replace("/", "\\"), "data/raw/Del Monte/Synthetic Data notes.xlsx",
                                                        "x/GENERATED_BACKFILL_y", None]}))
    assert s.tolist() == [True, False, False, False]


def test_a_blank_flag_synthetic_row_cannot_load_through_transform_fact():
    """End to end on the loader's own Transform path: the row reaches coerce_is_demo_column and stops there."""
    staged = pd.DataFrame([{
        "Invoice Date": "2021-01-05", "Invoice Num": "INV/2021/0001", "Customer Name": "X", "Net Amount": "100.00",
        "Return Slip #": "RMR00001", "is_demo": None,
        "_src_file": SYNTH_XLSX, "_src_sheet": "ILOCOS SALES RETURN", "_row_ordinal": 0, "_principal": "delmonte",
        "_region": "ilocos", "_period": "2021-01", "_doc_type": "sales_return", "_sheet_role": "data", "_grain": "invoice",
    }])
    with pytest.raises(SyntheticProvenanceError):
        transform_fact(staged, "sales_return", "delmonte", DEFAULT_CONFIG_DIR, amount_col="net_amount")
    staged["is_demo"] = "False"
    out, _ = transform_fact(staged, "sales_return", "delmonte", DEFAULT_CONFIG_DIR, amount_col="net_amount")
    assert out["is_demo"].tolist() == [True]
