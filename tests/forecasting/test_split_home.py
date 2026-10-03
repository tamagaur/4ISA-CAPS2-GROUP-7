"""tests/forecasting/test_split_home.py — item 6: the holdout split lives in
analytics/forecasting/split.py with its fraction in analytics.params; live
code no longer imports the retired sarima.py to split a series."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from analytics import params
from analytics.forecasting import baseline, sarima, split

REPO = Path(__file__).resolve().parents[2]


def test_one_split_one_fraction():
    assert sarima.train_holdout_split is split.train_holdout_split is baseline.train_holdout_split
    assert sarima.HOLDOUT_FRACTION is baseline.HOLDOUT_FRACTION is params.HOLDOUT_FRACTION


def test_baseline_no_longer_pulls_in_the_retired_module():
    code = "import sys, analytics.forecasting.baseline; print('analytics.forecasting.sarima' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
