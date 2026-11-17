"""Helpers for scripts/check.sh. Two subcommands, both exit non-zero on failure.

    python scripts/check_helpers.py env [--full]
        The live database must be configured AND reachable (read-only probe), and every variable the checks import
        must be set: SUPABASE_DB_URL (analytics/config.py; SUPABASE_KEY is no longer required there since 2026-11-13, nothing reads it).
        Names every missing variable. JWT_SECRET_KEY
        is not required since 2026-11-11: no test signs a token at import any more (KNOWN_ISSUES B1, fixed), and the
        tests that sign one in-process supply a throwaway secret (tests/backend/conftest.py, tests/invariants/conftest.py).
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
REQUIRED = ("SUPABASE_DB_URL",)
REQUIRED_FULL: tuple[str, ...] = ()   # was JWT_SECRET_KEY, for the import-time tokens of KNOWN_ISSUES B1 (fixed 2026-11-11)


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


def cmd_target() -> int:
    """One line naming the database the live checks read: `live (host/db)` or `LOCAL COPY (host/db), not live`. check.sh
    prints it under the env step and in its last line, so a run against a restored copy (allowed: rehearsals and clean
    clones are checked that way) can never be read as a check against live (added 2026-11-17)."""
    from urllib.parse import urlparse

    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    sys.path.insert(0, str(REPO))
    from scripts.report_target import is_live_target
    u = urlparse(os.environ.get("SUPABASE_DB_URL") or "")
    where = f"{u.hostname or '?'}{u.path or ''}"
    print(f"live ({where})" if is_live_target() else f"LOCAL COPY ({where}), not live")
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


def cmd_every_file(path: str, folder: str) -> int:
    """Fails when a test_*.py file of `folder` contributed no test case to the junit file: a file whose tests were renamed
    away, or a class pytest cannot collect, passes a run it took no part in (found 2026-11-17: --fast pinned no count)."""
    root = ET.parse(path).getroot()
    seen = {c.get("classname", "").split(".")[-1] for c in root.iter("testcase")}
    seen |= {c.get("classname", "").rsplit(".", 2)[-2] for c in root.iter("testcase") if c.get("classname", "").count(".") >= 2}
    files = sorted(f.stem for f in (REPO / folder).glob("test_*.py"))
    empty = [f for f in files if f not in seen]
    if empty:
        print(f"FAIL: {len(empty)} test file(s) in {folder} ran no test: {', '.join(empty)}")
        return 1
    print(f"every one of the {len(files)} test files in {folder} ran at least one test")
    return 0


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
            names = sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", msg)))
            print(f"  {k:3d} x {msg}" + (f"   [variable: {', '.join(names)}]" if names else ""))
        for name, _ in unknown[:5]:
            print(f"      e.g. {name}")
    return 1 if (unknown or gone) else 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "env":
        sys.exit(cmd_env(full="--full" in sys.argv[2:]))
    if len(sys.argv) == 2 and sys.argv[1] == "target":
        sys.exit(cmd_target())
    if len(sys.argv) == 4 and sys.argv[1] == "every-file":
        sys.exit(cmd_every_file(sys.argv[2], sys.argv[3]))
    if len(sys.argv) in (3, 4) and sys.argv[1] == "junit":
        sys.exit(cmd_junit(sys.argv[2], load_allowed() if sys.argv[3:] == ["--allow-listed"] else None))
    print(__doc__)
    sys.exit(2)
