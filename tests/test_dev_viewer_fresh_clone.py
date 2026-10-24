"""A fresh clone has none of the git-ignored per-product CSVs the dev viewer draws; the
build must stop with a message that names the script (or commit) that produces them."""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_evidence_missing_file_names_an_existing_generator():
    ev = _load("dsd_evidence", "tools/dsd_dev_viewer/evidence.py")
    assert ev.GENERATORS
    for rel, cmd in ev.GENERATORS.items():
        assert cmd in ev._missing_note(rel)
        script = cmd.split()[-1]
        assert (REPO / script).is_file(), script
    assert ev._missing_note("reports/evidence/ch02_lines.csv") == ""


def test_evidence_build_in_an_empty_repo_fails_with_the_generator_named(tmp_path):
    ev = _load("dsd_evidence2", "tools/dsd_dev_viewer/evidence.py")
    import shutil
    shutil.copytree(REPO / "reports" / "evidence", tmp_path / "reports" / "evidence",
                    ignore=shutil.ignore_patterns("ch01_sku_series.csv", "ch06_months.csv"))
    try:
        ev.load(str(tmp_path))
    except SystemExit as exc:
        text = str(exc)
    else:
        raise AssertionError("expected the evidence build to stop")
    assert "scripts/evidence/ch01_models.py" in text
    assert "scripts/evidence/ch06_unfit.py" in text
