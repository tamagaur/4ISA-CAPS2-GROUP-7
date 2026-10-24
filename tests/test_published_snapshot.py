"""The pinned accuracy figures reproduce from their frozen rows (2026-10-24). Skipped where the git-ignored
per-product rows (local/published_snapshot_*/) are absent, e.g. a fresh clone."""
import json

import pytest

from scripts import snapshot_published_figures as sp


def test_snapshot_json_names_its_actuals_version_and_inputs():
    snap = json.loads(sp.SNAP_JSON.read_text(encoding="utf-8"))
    assert snap["actuals_version"]["key"].startswith("actuals-2026-02-")
    assert set(snap["inputs_sha256"]) == {"accuracy_as_served_rows.csv", "demand_money.csv", "mase_rows.csv",
                                          "error_decomposition_row.csv"}
    f = snap["figures"]
    assert (f["mase"]["mase_below_1"], f["mase"]["products_scored"]) == (109, 175)
    assert f["error_decomposition"]["A"]["exceeds_safety_stock_months"] == 749


@pytest.mark.skipif(not (sp.SNAP_DIR / "mase_rows.csv").exists(), reason="frozen per-product rows are local only")
def test_figures_reproduce_from_the_frozen_rows(capsys):
    assert sp.cmd_verify() in (0,)  # the live actuals line may not print without a database; the figures must match
