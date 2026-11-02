"""
scripts/chapter_figures.py - pin the figures Chapter 4 prints that come from the code or the running system, and fail
when one drifts (2026-11-02).

Pinned in docs/CHAPTER4_CODE_FIGURES.json, one entry per figure with its value and the command that produces it.
The accuracy figures are pinned separately (docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json); these are the rest.

    python -m scripts.chapter_figures --measure [ID]      print the current value of one figure (or all)
    python -m scripts.chapter_figures --verify            measure the static figures, compare with the pin (scripts/check.sh --fast)
    python -m scripts.chapter_figures --verify-junit A.xml B.xml
                                                          compare the pytest totals of a whole run (invariants + suite) with the pin
                                                          (scripts/check.sh --full)
    python -m scripts.chapter_figures --write [--junit A.xml B.xml]
                                                          re-pin from the live measurement (a human act: say why in the commit)

The test totals: a run on a clean clone skips all of the opt-in list; a machine that holds SSM's real data/raw and the
per-product policy table runs REAL_DATA_TESTS and skips that many fewer. The check expects exactly
(opt-in list size) minus (REAL_DATA_TESTS that ran), so a partial environment is not a false alarm and a new unlisted
skip is still a failure (scripts/check_helpers.py already fails it).

The collected total also depends on the machine: tests/etl/test_extract.py parametrizes its six raw-file tests over
"synthetic" and, only where data/raw exists, "real_corpus". The pin holds both totals (REAL_CORPUS_MARK counts the cases).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
PIN = REPO / "docs" / "CHAPTER4_CODE_FIGURES.json"
ROUTERS = REPO / "backend" / "routers"

# The tests that need SSM's real files (never committed); they are the only listed skips that can run on a machine that has them.
REAL_DATA_TESTS = (
    "tests.etl.test_layout_regression::test_content_identification_reproduces_todays_family_and_month_for_every_file",
    "tests.etl.test_extract::test_parse_unilever_sku_against_real_file",
    "tests.backend.test_policy_comparison::test_pesos_reproduce_the_lp_logic_check_totals",
)


def _permissions_module():
    """tests/backend/test_permissions.py walks the live FastAPI app the way ROUTE_COUNT does; reuse its walk."""
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    os.environ.setdefault("JWT_SECRET_KEY", "chapter-figures-measurement-only")   # the route walk never signs anything
    from tests.backend import test_permissions
    return test_permissions


def route_split() -> dict:
    tp = _permissions_module()
    seen = {}
    for method, path, keys, _calls in tp._routes():
        seen[(method, path)] = bool(keys)
    public = {r for r in seen if r in tp.PUBLIC}
    named = {r for r, k in seen.items() if k and r not in public}
    return {"routes_total": len(seen), "routes_public": len(public), "routes_require_sign_in": len(seen) - len(public),
            "routes_named_permission": len(named), "routes_sign_in_only": len(seen) - len(public) - len(named)}


def cached_get_routes() -> int:
    """@cached("GET /path") decorators on the routers; each is one cached GET route."""
    pat = re.compile(r'^@cached\(\s*"GET ', re.M)
    return sum(len(pat.findall(p.read_text(encoding="utf-8"))) for p in sorted(ROUTERS.glob("*.py")))


def opt_in_list_size() -> int:
    from scripts.check_helpers import load_allowed
    return len(load_allowed())


REAL_CORPUS_MARK = "[real_corpus]"


def collect_count() -> tuple[int, int]:
    """(tests collected, of which real_corpus cases) on this machine."""
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
                         cwd=REPO, capture_output=True, text=True).stdout
    m = re.search(r"(\d+) tests? collected", out)
    if not m:
        raise SystemExit("could not read the collected-test count from pytest --collect-only")
    return int(m.group(1)), sum(1 for line in out.splitlines() if "::" in line and REAL_CORPUS_MARK in line)


def read_junit(paths) -> dict:
    total = failed = skipped = real_cases = 0
    ran, skipped_ids = set(), set()
    for p in paths:
        for case in ET.parse(p).getroot().iter("testcase"):
            total += 1
            real_cases += REAL_CORPUS_MARK in (case.get("name") or "")
            tid = f"{case.get('classname')}::{case.get('name')}"
            if case.find("skipped") is not None:
                skipped += 1
                skipped_ids.add(tid)
            elif case.find("failure") is not None or case.find("error") is not None:
                failed += 1
            else:
                ran.add(tid)
    real_ran = sum(1 for t in REAL_DATA_TESTS if t in ran)
    return {"tests_collected": total, "tests_failed": failed, "tests_skipped": skipped, "tests_passed": total - skipped - failed,
            "real_data_tests_that_ran": real_ran, "real_corpus_cases": real_cases}


def measure_static() -> dict:
    return {**route_split(), "cached_get_routes": cached_get_routes(), "opt_in_list_size": opt_in_list_size()}


FIGURES = [  # id, what the chapter says, equivalent plain command
    ("routes_total", "Method/path pairs the API serves", "python -m scripts.chapter_figures --measure routes_total  (= tests/backend/test_permissions.py ROUTE_COUNT)"),
    ("routes_require_sign_in", "Routes that need a signed-in user (every route but the public ones)", "python -m scripts.chapter_figures --measure routes_require_sign_in"),
    ("routes_named_permission", "...of which gated by a named permission key", "python -m scripts.chapter_figures --measure routes_named_permission"),
    ("routes_sign_in_only", "...of which sign-in only, no permission key", "python -m scripts.chapter_figures --measure routes_sign_in_only"),
    ("routes_public", "Routes that need no sign-in (test_permissions.PUBLIC)", "python -m scripts.chapter_figures --measure routes_public"),
    ("cached_get_routes", "GET routes behind the response cache", "grep -rhE '^@cached\\(\"GET ' backend/routers | wc -l"),
    ("opt_in_list_size", "Tests allowed to skip in the whole suite (scripts/known_opt_in_skips.txt)", "grep -vc '^#' scripts/known_opt_in_skips.txt"),
    ("tests_collected_clean_clone", "Tests in the whole run on a clean clone (invariants plus suite)", "python -m pytest --collect-only -q tests | tail -1  (on a clone with no data/raw)"),
    ("tests_collected_with_real_data", "Tests in the whole run where data/raw exists (adds the real_corpus cases)", "python -m pytest --collect-only -q tests | tail -1  (where data/raw exists)"),
    ("real_corpus_cases", "Extract test cases that exist only where data/raw exists", "python -m pytest --collect-only -q tests | grep -c 'real_corpus]'  (where data/raw exists)"),
    ("tests_failed", "Failed tests in a full run", "scripts/check.sh --full"),
    ("tests_skipped_clean_clone", "Skipped tests on a clean clone (the whole opt-in list)", "scripts/check.sh --full on a clone with no data/raw and no local/"),
    ("tests_skipped_with_real_data", "Skipped tests on a machine with SSM's data/raw and the per-product policy table", "scripts/check.sh --full there"),
    ("tests_passed_clean_clone", "Passed tests on a clean clone (collected minus skipped)", "scripts/check.sh --full on a clone with no data/raw and no local/"),
    ("tests_passed_with_real_data", "Passed tests with SSM's real files present (collected minus skipped)", "scripts/check.sh --full there"),
]


def derived(static: dict, collected: int, real_cases: int, failed: int = 0) -> dict:
    """collected and real_cases are as measured on the machine that writes the pin; the clean-clone total is collected minus real_cases."""
    n = static["opt_in_list_size"]
    r = len(REAL_DATA_TESTS)
    clean, withdata = collected - real_cases, collected
    return {**static, "tests_collected_clean_clone": clean, "tests_collected_with_real_data": withdata, "real_corpus_cases": real_cases,
            "tests_failed": failed, "tests_skipped_clean_clone": n, "tests_skipped_with_real_data": n - r,
            "tests_passed_clean_clone": clean - n - failed, "tests_passed_with_real_data": withdata - (n - r) - failed}


def cmd_write(junit) -> int:
    static = measure_static()
    if junit:
        j = read_junit(junit)
        collected, real_cases = j["tests_collected"], j["real_corpus_cases"]
    else:
        collected, real_cases = collect_count()
    if not real_cases:
        raise SystemExit("this machine has no data/raw, so the real_corpus cases cannot be counted: re-pin on the machine that has it")
    vals = derived(static, collected, real_cases)
    out = {"pinned_on": "2026-11-02",
           "rule": "Chapter 4 prints these from the code or the live system. Re-pin only on purpose, in the commit that changes the code; "
                   "the chapter must take every figure from one commit. scripts/check.sh fails on drift.",
           "figures": [{"id": i, "what": w, "value": vals[i], "command": c} for i, w, c in FIGURES]}
    PIN.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {PIN.relative_to(REPO)}: " + ", ".join(f"{i}={vals[i]}" for i, _, _ in FIGURES))
    return 0


def _pinned() -> dict:
    return {f["id"]: f["value"] for f in json.loads(PIN.read_text(encoding="utf-8"))["figures"]}


def cmd_verify() -> int:
    pin = _pinned()
    now = measure_static()
    bad = [f"{k}: pinned {pin.get(k)!r}, measured {v!r}" for k, v in now.items() if pin.get(k) != v]
    bad += [f"{i}: not in {PIN.name}" for i, _, _ in FIGURES if i not in pin]
    if now["opt_in_list_size"] != pin.get("tests_skipped_clean_clone"):
        bad.append(f"tests_skipped_clean_clone: pinned {pin.get('tests_skipped_clean_clone')!r}, opt-in list has {now['opt_in_list_size']}")
    for b in bad:
        print("FAIL", b)
    if bad:
        print(f"FAIL: {len(bad)} Chapter 4 code figure(s) drifted. If the change is intended, re-pin: "
              "python -m scripts.chapter_figures --write   (and update the chapter from the same commit)")
        return 1
    print("OK: " + ", ".join(f"{k}={v}" for k, v in now.items()))
    return 0


def cmd_verify_junit(paths) -> int:
    pin = _pinned()
    got = read_junit(paths)
    n_ran = got["real_data_tests_that_ran"]
    want_skipped = pin["tests_skipped_clean_clone"] - n_ran
    bad = []
    real = got["real_corpus_cases"]
    if real not in (0, pin["real_corpus_cases"]):
        bad.append(f"real_corpus_cases: pinned {pin['real_corpus_cases']} (or 0 without data/raw), ran {real}")
    want_collected = pin["tests_collected_with_real_data"] if real else pin["tests_collected_clean_clone"]
    if got["tests_collected"] != want_collected:
        bad.append(f"tests_collected: pinned {want_collected} ({'with' if real else 'without'} data/raw), ran {got['tests_collected']}")
    if got["tests_failed"] != pin["tests_failed"]:
        bad.append(f"tests_failed: pinned {pin['tests_failed']}, ran {got['tests_failed']}")
    if got["tests_skipped"] != want_skipped:
        bad.append(f"tests_skipped: expected {want_skipped} (opt-in list {pin['tests_skipped_clean_clone']} minus {n_ran} real-data test(s) that ran), got {got['tests_skipped']}")
    for b in bad:
        print("FAIL", b)
    if bad:
        print("FAIL: the pytest totals drifted from docs/CHAPTER4_CODE_FIGURES.json. If intended: python -m scripts.chapter_figures --write --junit <invariants.xml> <full.xml>")
        return 1
    print(f"OK: {got['tests_passed']} passed, {got['tests_skipped']} skipped, {got['tests_failed']} failed of {got['tests_collected']} "
          f"({n_ran} of {len(REAL_DATA_TESTS)} real-data tests ran here; {real} real_corpus cases)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--measure", nargs="?", const="all", metavar="ID")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--verify-junit", nargs="+", metavar="XML")
    g.add_argument("--write", action="store_true")
    ap.add_argument("--junit", nargs="+", metavar="XML", help="with --write: take the collected total from these junit files")
    a = ap.parse_args()
    if a.measure:
        now = measure_static()
        if a.measure == "all":
            print(json.dumps(now, indent=1))
        elif a.measure in now:
            print(now[a.measure])
        elif a.measure == "tests_collected":
            print(collect_count()[0])
        else:
            raise SystemExit(f"{a.measure} is a test-run figure: scripts/check.sh --full measures it")
        return 0
    if a.verify:
        return cmd_verify()
    if a.verify_junit:
        return cmd_verify_junit(a.verify_junit)
    return cmd_write(a.junit)


if __name__ == "__main__":
    sys.exit(main())
