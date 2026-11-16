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


class _Conn:
    def rollback(self): pass
    def close(self): pass


def _fake_live(monkeypatch, key=None, mase_below_1=None, change=None):
    """cmd_verify against a stand-in for the database: the pinned figures, optionally with one thing changed
    (`change` edits the stand-in's figures in place)."""
    snap = json.loads(sp.SNAP_JSON.read_text(encoding="utf-8"))
    fig = json.loads(json.dumps(snap["figures"]))
    if mase_below_1 is not None:
        fig["mase"]["mase_below_1"] = mase_below_1
    if change is not None:
        change(fig)
    stamp = dict(snap["actuals_version"], key=key or snap["actuals_version"]["key"])
    import analytics.actuals_version as av
    monkeypatch.setattr(sp, "connect", lambda: (_Conn(), None))
    monkeypatch.setattr(av, "read", lambda cur: stamp)
    monkeypatch.setattr(sp, "live_figures", lambda cur: fig)


def test_verify_passes_when_live_matches_the_pinned_figures(monkeypatch, capsys):
    _fake_live(monkeypatch)
    assert sp.cmd_verify() == 0
    assert "live matches the pinned figures" in capsys.readouterr().out


def test_verify_fails_when_a_live_figure_differs_from_the_pinned_one(monkeypatch, capsys):
    _fake_live(monkeypatch, mase_below_1=110)
    assert sp.cmd_verify() == 1
    assert "live mase.mase_below_1" in capsys.readouterr().out


def test_verify_fails_when_the_actuals_have_moved(monkeypatch, capsys):
    _fake_live(monkeypatch, key="actuals-2026-03-000000000000")
    assert sp.cmd_verify() == 1
    assert "actuals version" in capsys.readouterr().out


def test_verify_fails_when_the_live_headline_wape_differs(monkeypatch, capsys):
    """2026-11-16: the headline WAPE is compared to live like every other pinned figure (it was frozen rows only)."""
    def move(fig):
        fig["headline_wape"]["as_served_calendar"]["pooled_wape_pcs_served"] += 0.001
    _fake_live(monkeypatch, change=move)
    assert sp.cmd_verify() == 1
    assert "live headline_wape.as_served_calendar.pooled_wape_pcs_served" in capsys.readouterr().out


def test_verify_fails_when_live_cannot_give_a_pinned_figure(monkeypatch, capsys):
    """A stored backtest run that is gone, or a whole group live does not recompute, is a divergence, not a pass."""
    _fake_live(monkeypatch, change=lambda fig: fig["headline_wape"].pop("as_served"))
    assert sp.cmd_verify() == 1
    assert "live gives no such figure" in capsys.readouterr().out
    _fake_live(monkeypatch, change=lambda fig: fig.pop("error_decomposition"))
    assert sp.cmd_verify() == 1


class _Cursor:
    """Answers live_headline's two queries from the frozen rows, as the mart stores them (a raw net quantity)."""

    def __init__(self, rows, money):
        self.rows, self.money, self.out = rows, money, []

    def execute(self, sql, params=None):
        from scripts.accuracy_as_served import AS_SERVED_RUNS
        if "Unilever_SKU_Demand_Fact_Real" in sql:
            self.out = list(self.money[["product_key", "month", "net_amount", "quantity_raw"]].itertuples(index=False, name=None))
            return
        assert "GREATEST(a.actual_pieces, 0)" in sql and "r.label = %s" in sql
        run = next(name for name in sp.HEADLINE_RUNS if AS_SERVED_RUNS[name][0] == params[0])
        bt = self.rows[self.rows.run == run]
        self.out = [(k, m, max(a, 0.0), v, ma3) for k, m, a, v, ma3 in
                    bt[["product_key", "month", "actual", "value", "ma3"]].itertuples(index=False, name=None)]

    def fetchall(self):
        return self.out


def test_the_live_headline_is_the_frozen_headline_when_the_stored_rows_are_the_frozen_rows():
    """live_headline reads the stored runs by their AS_SERVED_RUNS labels, counts a net-negative month as 0 sold and
    prices from the demand view; on the frozen rows it gives the pinned figures to the last digit."""
    rows, money, _, _ = sp.read_frozen()
    got = sp.live_headline(_Cursor(rows, money))
    pinned = json.loads(sp.SNAP_JSON.read_text(encoding="utf-8"))["figures"]["headline_wape"]
    assert set(got) == set(pinned) == set(sp.HEADLINE_RUNS)
    for run in sp.HEADLINE_RUNS:
        for k in sp.HEADLINE_KEYS:
            assert abs(got[run][k] - pinned[run][k]) < 1e-9, (run, k)
