"""(d) Every pinned manuscript figure reproduces.

Guards against: loading March 2026 sales silently moving every accuracy figure the manuscript quotes
(mart.accuracy_mart and mart.error_decomposition read real sales at every refresh). The figures are frozen
(scripts/snapshot_published_figures.py, docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json) and recomputed from the
frozen rows; the published text of docs/ACCURACY_AS_SERVED.md is compared with what was pinned.

The frozen rows are tracked (docs/published_snapshot_2026-10-24/, trimmed columns); this FAILS if they are missing.
"""
import json

from scripts import snapshot_published_figures as sp

_META = ("source", "doc_sha256")


def test_frozen_rows_are_present():
    missing = [n for n in ("accuracy_as_served_rows.csv", "demand_money.csv", "mase_rows.csv", "error_decomposition_row.csv")
               if not (sp.SNAP_DIR / n).exists()]
    assert not missing, f"frozen rows missing from {sp.SNAP_DIR}: {missing} (tracked in git; restore with git checkout)"


def test_every_pinned_figure_reproduces_from_the_frozen_rows(live_env, capsys):
    rc = sp.cmd_verify()
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "live actuals version not read" not in out, "verify could not read the live actuals version: " + out


def test_the_published_doc_text_is_what_was_pinned():
    snap = json.loads(sp.SNAP_JSON.read_text(encoding="utf-8"))
    pinned = {k: v for k, v in snap["published_doc_sections_verbatim"].items() if k not in _META}
    now = sp.doc_sections(sp.DOC.read_text(encoding="utf-8"), tuple(pinned))
    for heading, text in pinned.items():
        assert now.get(heading) == text, f"docs/ACCURACY_AS_SERVED.md section {heading!r} no longer matches the pinned text"
