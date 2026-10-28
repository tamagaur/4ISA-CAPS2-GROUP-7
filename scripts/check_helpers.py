"""Helpers for scripts/check.sh. Two subcommands, both exit non-zero on failure.

    python scripts/check_helpers.py env
        The live database must be configured AND reachable (read-only probe). Names the missing variable.
    python scripts/check_helpers.py junit <junit.xml>
        Fails if any test was skipped (or none ran), and prints each skip reason with the variable it names.
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
REQUIRED = ("SUPABASE_DB_URL",)


def cmd_env() -> int:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    missing = [n for n in REQUIRED if not os.environ.get(n) or "<" in os.environ[n]]
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


def cmd_junit(path: str) -> int:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    skipped = [(c.get("classname", "") + "::" + c.get("name", ""), (c.find("skipped").get("message") or "")) for c in cases
               if c.find("skipped") is not None]
    print(f"{len(cases)} tests collected, {len(skipped)} skipped")
    if not cases:
        print("FAIL: no tests ran")
        return 1
    if not skipped:
        return 0
    by_reason = Counter(msg for _, msg in skipped)
    print(f"FAIL: {len(skipped)} skipped test(s). Skipped is not passed. Reasons:")
    for msg, n in by_reason.most_common():
        names = sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", msg)))
        print(f"  {n:3d} x {msg}" + (f"   [variable: {', '.join(names)}]" if names else ""))
    for name, _ in skipped[:5]:
        print(f"      e.g. {name}")
    return 1


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "env":
        sys.exit(cmd_env())
    if len(sys.argv) == 3 and sys.argv[1] == "junit":
        sys.exit(cmd_junit(sys.argv[2]))
    print(__doc__)
    sys.exit(2)
