"""
tests/test_no_session_readonly.py - no Python file in the repo makes a
session-level READ ONLY.

conn.set_session(readonly=True) (and SET SESSION CHARACTERISTICS ... READ ONLY)
sets default_transaction_read_only for the whole server session. Through the
Supabase :6543 transaction pooler that session is shared: the setting outlives
this client and the next one handed the backend cannot write - it broke the
app's sign-ins on 2026-09-28. The rule: autocommit off, SET TRANSACTION READ
ONLY as the first statement, end with rollback() or close().

Static - parses source with ast, touches no database. Only a real call (or a
SQL string constant) counts, so a comment or docstring naming set_session is
not a violation.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "backups", "staging", "staging_synthetic", "staging_slices",
             "data", "frontend", "__pycache__", "broken_state_20260914", "SAN SAN Marketing"}
# built from \s+ so this file's own constants never contain the phrase it looks for
SESSION_READ_ONLY_SQL = re.compile(r"SESSION\s+CHARACTERISTICS\s+AS\s+TRANSACTION\s+READ\s+ONLY", re.I)
MAX_UNPARSEABLE = 5


def _is_false_or_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and (node.value is False or node.value is None)


def violations(source: str | bytes, filename: str = "<memory>") -> list[str]:
    """file:line for every set_session(... readonly=<anything but a literal False/None> ...) call and every string
    constant matching SESSION_READ_ONLY_SQL. Raises SyntaxError/ValueError on source that does not parse."""
    found = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_session":
            if any(kw.arg == "readonly" and not _is_false_or_none(kw.value) for kw in node.keywords):
                found.append(f"{filename}:{node.lineno} set_session(readonly=...)")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and SESSION_READ_ONLY_SQL.search(node.value):
            found.append(f"{filename}:{node.lineno} SESSION CHARACTERISTICS ... READ ONLY")
    return found


def _python_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                yield Path(root) / f


def test_no_session_level_read_only_anywhere():
    found, unparseable = [], []
    for path in _python_files():
        rel = path.relative_to(REPO).as_posix()
        try:
            found += violations(path.read_bytes(), rel)
        except (SyntaxError, ValueError) as exc:
            unparseable.append(f"{rel} ({type(exc).__name__})")
    if unparseable:
        print("not parsed, so not checked:", *unparseable, sep="\n  ")
    assert len(unparseable) <= MAX_UNPARSEABLE, unparseable
    assert not found, "session-level READ ONLY - use SET TRANSACTION READ ONLY with autocommit off:\n" + "\n".join(found)


def test_scan_sees_the_repo():
    """Guards against a walk that silently finds nothing (a wrong REPO, a skip list that swallows everything)."""
    rels = {p.relative_to(REPO).as_posix() for p in _python_files()}
    assert {"scripts/run_lp.py", "backend/deps.py", "tests/test_no_session_readonly.py"} <= rels


def test_checker_has_teeth():
    src = "import psycopg2\nconn = psycopg2.connect('x')\nconn.set_session(readonly=True)\n"
    assert violations(src) == ["<memory>:3 set_session(readonly=...)"]
    assert len(violations("c.set_session(autocommit=True, readonly=flag)\n")) == 1
    phrase = " ".join(["SET", "SESSION", "CHARACTERISTICS", "AS", "TRANSACTION", "READ", "ONLY"])
    assert len(violations(f"cur.execute({phrase.lower()!r})\n")) == 1


def test_naming_the_pattern_is_not_a_violation():
    src = ('"""Never conn.set_session(readonly=True): it is session-scoped."""\n'
           "# conn.set_session(readonly=True, autocommit=True) leaks through the pooler\n"
           "conn.set_session(autocommit=False)\n"
           "conn.set_session(readonly=False)\n"
           "conn.set_session(readonly=None)\n"
           'cur.execute("SET TRANSACTION READ ONLY")\n')
    assert violations(src) == []
