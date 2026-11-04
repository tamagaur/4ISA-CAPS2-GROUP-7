"""Helpers for scripts/check.sh. Two subcommands, both exit non-zero on failure.

    python scripts/check_helpers.py env [--full]
        The live database must be configured AND reachable (read-only probe), and every variable the checks import
        must be set: SUPABASE_DB_URL and SUPABASE_KEY always (analytics/config.py), plus JWT_SECRET_KEY with --full
        (two test modules build a signed token at import, KNOWN_ISSUES B1). Names every missing variable.
    python scripts/check_helpers.py junit <junit.xml> [--allow-listed]
        Fails if any test was skipped that is not on scripts/known_opt_in_skips.txt (exact id and reason), or none ran.
        Skipped is not passed: a suite where tests vanish when an environment variable is unset looks healthy
        while the live integration is broken.
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REQUIRED = ("SUPABASE_DB_URL", "SUPABASE_KEY")
REQUIRED_FULL = ("JWT_SECRET_KEY",)   # read at import by tests/backend/test_reorder_approval.py and test_reorder_requests.py


def cmd_env(full: bool = False) -> int:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    missing = [n for n in (REQUIRED + REQUIRED_FULL if full else REQUIRED) if not os.environ.get(n) or "<" in os.environ[n]]
    if missing:
        print(f"FAIL: live checks cannot run, environment variable(s) not set: {', '.join(missing)}")
        print("      set them in .env or the shell; a check that cannot run is a failure, not a pass")
        return 1
    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=15)
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")      # transaction-scoped (hard rule 7)
        cur.execute("SELECT 1")
        conn.rollback()
        conn.close()
    except Exception as exc:
        print(f"FAIL: SUPABASE_DB_URL is set but the database is not reachable: {type(exc).__name__}: {str(exc)[:160]}")
        return 1
    print("live database configured and reachable (read-only probe)")
    return 0


ALLOWED_SKIPS = REPO / "scripts" / "known_opt_in_skips.txt"


def load_allowed(path: Path = ALLOWED_SKIPS) -> dict[str, str]:
    """{test id: exact skip reason} from the allow-list file (comments and blank lines ignored). A third column, if any, says what
    runs the test: it is no part of the reason."""
    allowed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            cols = line.split("	")
            allowed[cols[0].strip()] = cols[1].strip() if len(cols) > 1 else ""
    return allowed


OPTIN_COMMAND = "check.sh --optin"


def covered_by_optin(path: Path = ALLOWED_SKIPS) -> list[str]:
    """The tests the list says scripts/check.sh --optin runs (third column), in the list's order."""
    return [line.split("	")[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
            if not line.startswith("#") and line.count("	") >= 2 and line.split("	")[2].strip() == OPTIN_COMMAND]


def cmd_junit(path: str, allowed: dict[str, str] | None = None) -> int:
    """Fails on any skip not on the allow-list, by exact test id AND exact reason; also fails when an allow-list entry
    names a test that was not collected (the list must stay exactly the known set). Allow-listed skips are named and
    counted as NOT RUN: they are never reported as passed."""
    allowed = {} if allowed is None else allowed   # no allow-list unless the caller passes one (only the whole suite does)
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    ids = {c.get("classname", "") + "::" + c.get("name", "") for c in cases}
    skipped = [(c.get("classname", "") + "::" + c.get("name", ""), (c.find("skipped").get("message") or "")) for c in cases
               if c.find("skipped") is not None]
    print(f"{len(cases)} tests collected, {len(skipped)} skipped")
    if not cases:
        print("FAIL: no tests ran")
        return 1
    unknown = [(n, m) for n, m in skipped if allowed.get(n) != m]
    gone = sorted(n for n in allowed if n not in ids)
    known = [(n, m) for n, m in skipped if allowed.get(n) == m]
    if known:
        print(f"NOT RUN (allow-listed opt-in, not coverage): {len(known)} of {len(allowed)} listed")
    if gone:
        print(f"FAIL: {len(gone)} allow-list entr(y/ies) name a test that no longer exists; remove them from {ALLOWED_SKIPS.name}:")
        for n in gone[:5]:
            print(f"      {n}")
    if unknown:
        by_reason = Counter(msg for _, msg in unknown)
        print(f"FAIL: {len(unknown)} skipped test(s) not on the allow-list. Skipped is not passed. Reasons:")
        for msg, k in by_reason.most_common():
            names = sorted(set(re.findall(r"[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+", msg)))
            print(f"  {k:3d} x {msg}" + (f"   [variable: {', '.join(names)}]" if names else ""))
        for name, _ in unknown[:5]:
            print(f"      e.g. {name}")
    return 1 if (unknown or gone) else 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "env":
        sys.exit(cmd_env(full="--full" in sys.argv[2:]))
    if len(sys.argv) in (3, 4) and sys.argv[1] == "junit":
        sys.exit(cmd_junit(sys.argv[2], load_allowed() if sys.argv[3:] == ["--allow-listed"] else None))
    print(__doc__)
    sys.exit(2)
