"""At-the-time forecast accuracy on the new Tier A list (2026-10-05). Read-only.

    python reports/diagnostics/tier_a_refresh_2026-10-05/at_the_time.py

Same production path and metrics as the stored at-the-time backtest (forecast run 2,
scripts/backtest_forecast_run.py): per test month T, the products Tier A at T-1, XGBoost
trained on those products only, the router on the history before T; headline() is that
script's own (median product WAPE, company-total WAPE in pesos).

Two lists: 'single' (Tier A on the month alone, the stored run's) and 't12m_new' (DEC-37).
t12m_new runs start at 2023-12, so its test months start at 2024-01; 'single' is also scored on
those same months so the two compare like for like, and on its full window 2023-10..2026-02.

Since kelvin/blank-qty-fix (merged 2026-10-05) a blank quantity is a missing month, so its
actual is unknown: such product-months are dropped from scoring here (the accuracy mart's
rule), for both lists. The committed 34.8% headline counted them as 0, so this script's
'single' full-window figure is printed next to it, not asserted equal.

Writes headline_at_the_time.csv (aggregates only).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from analytics.config import get_settings  # noqa: E402
import scripts.backtest_forecast_run as bt  # noqa: E402

FIRST_T12M_TEST = "2024-01"


def scored(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["actual"].notna()].copy()


def main() -> None:
    db = get_settings().supabase_db_url
    rows = []
    for method in ("single", "t12m_new"):
        series, money, tier_by = bt.read_inputs(db, method)
        res = bt.run_at_the_time(series, tier_by)
        dropped = int(res["actual"].isna().sum())
        res = scored(res)
        windows = {"2024-01..2026-02": res[res.month >= FIRST_T12M_TEST]}
        if method == "single":
            windows["2023-10..2026-02"] = res
        for label, frame in windows.items():
            h = bt.headline(frame, money)
            rows.append({"tier_a_list": method, "test_months": label, "months": frame.month.nunique(),
                         "blank_quantity_rows_dropped": dropped, **h})
            print(method, label, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in h.items()})
    out = pd.DataFrame(rows)
    out.to_csv(HERE / "headline_at_the_time.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
