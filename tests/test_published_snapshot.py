"""The pinned accuracy figures reproduce from their frozen rows (2026-10-24). The rows are tracked in
docs/published_snapshot_2026-10-24/ (trimmed columns), so this runs on a fresh clone and never skips."""
import json

from scripts import snapshot_published_figures as sp


def test_snapshot_json_names_its_actuals_version_and_inputs():
    snap = json.loads(sp.SNAP_JSON.read_text(encoding="utf-8"))
    assert snap["actuals_version"]["key"].startswith("actuals-2026-02-")
    assert set(snap["inputs_sha256"]) == {"accuracy_as_served_rows.csv", "demand_money.csv", "mase_rows.csv",
                                          "error_decomposition_row.csv"}
    f = snap["figures"]
    assert (f["mase"]["mase_below_1"], f["mase"]["products_scored"]) == (115, 175)   # 110 before the product-grain calendar
    # 749 on the untreated backtest (run 11); 762 since 2026-11-10, the decomposition on the treated run 16; 797 since
    # 2026-11-11 (migration 0077: the rebuilt safety stock of zero-forecast and succession/fading product-months follows the level);
    # 852 since the calendar factor is computed per product (2026-11-12, scripts/apply_calendar_grain.py): the factor no longer
    # raises every product by the company's volume-weighted rise, so more months' demand beats forecast + safety stock.
    assert f["error_decomposition"]["A"]["exceeds_safety_stock_months"] == 852


def test_figures_reproduce_from_the_frozen_rows(capsys):
    assert sp.cmd_verify() in (0,)  # the live actuals line may not print without a database; the figures must match
