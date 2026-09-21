import numpy as np
import pandas as pd

from analytics.segmentation.orchestrate_segment import _to_records


def test_to_records_writes_missing_values_as_none_not_nan():
    # One measurable SKU, one launched this month (no CV, no trend test).
    df = pd.DataFrame({"product_key": [1, 2], "cv": [0.4, None], "trend_pvalue": [0.03, np.nan], "trend": ["up", "none"]})
    records = _to_records(df)
    assert records[0] == {"product_key": 1, "cv": 0.4, "trend_pvalue": 0.03, "trend": "up"}
    assert records[1]["cv"] is None
    assert records[1]["trend_pvalue"] is None
    assert records[1]["product_key"] == 2
