"""
tests/backend/test_migrations.py — public.users must always list every
column of app.users.

Why this exists: migrations 0058 (avatar_data_url) and the original
0058_user_avatar_path.sql (avatar_path, renumbered to 0059 on the merge of
kelvin/merge-main-final-conflict, 2026-10-18) were written independently,
each re-creating public.users with ONLY its own new column appended to the
old 6-column list. Whichever one reached the live database second would have
silently dropped the other's column from public.users -- the table itself
would still have both columns, but the view the backend actually reads
(`backend/routers/users.py`, `backend/profile.py`: "SELECT ... FROM users",
unqualified, resolved through search_path to the view) would expose only
one. Static, so it runs with no database.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "analytics" / "db" / "migrations"

sys.path.insert(0, str(REPO_ROOT))
from scripts.run_canonical_load import _strip_sql_file  # noqa: E402

ADD_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+app\.users\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE
)
DROP_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+app\.users\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?(\w+)", re.IGNORECASE
)
# Plain single-table SELECT of bare column references (0048's own comment:
# "a single-table SELECT of plain column references, which makes it
# automatically updatable") -- never an expression or alias, so splitting the
# SELECT list on commas is exact, not a heuristic.
VIEW_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+public\.users\b.*?AS\s+SELECT\s+(.*?)\s+FROM\s+app\.users",
    re.IGNORECASE | re.DOTALL,
)


def _migration_files() -> list[Path]:
    # Same application order the runner uses: sorted() on the filename
    # (scripts/run_canonical_load.py, _assert_no_new_number_collision).
    return sorted(MIGRATIONS_DIR.glob("0*.sql"))


def test_every_public_users_view_lists_every_app_users_column():
    columns: list[str] | None = None  # None until the view (and so app.users) exists
    checked_views = 0

    for f in _migration_files():
        # Strip comment lines first -- a rollback note like "then ALTER TABLE
        # app.users DROP COLUMN x" would otherwise be read as real SQL and
        # cancel out the very ADD COLUMN it is describing.
        sql = _strip_sql_file(f.read_text(encoding="utf-8"))

        for match in ADD_COLUMN_RE.finditer(sql):
            name = match.group(1)
            if columns is not None and name not in columns:
                columns.append(name)

        for match in DROP_COLUMN_RE.finditer(sql):
            name = match.group(1)
            if columns is not None and name in columns:
                columns.remove(name)

        view_match = VIEW_RE.search(sql)
        if view_match is None:
            continue
        view_columns = [c.strip() for c in view_match.group(1).split(",")]
        if columns is None:
            # The first view (0048) establishes the baseline column set --
            # at this point app.users has just arrived via SET SCHEMA with no
            # ADD/DROP COLUMN of its own, so the view's own list IS the truth.
            columns = view_columns
        else:
            assert view_columns == columns, (
                f"{f.name}: public.users lists {view_columns}, but app.users' columns at this "
                f"point in the migration order are {columns}. A migration that re-creates "
                f"public.users must list every current column of app.users, not just the one "
                f"it is adding or dropping -- otherwise whichever migration applies last "
                f"silently drops every other migration's column from the view."
            )
        checked_views += 1

    assert columns is not None, "no migration ever created public.users"
    assert checked_views >= 1
    # Locks in the specific regression this test was written for (migration
    # 0060, DEC-?): avatar_data_url (0058) is retired, avatar_path (0059)
    # stays, nothing else has touched app.users.
    assert columns == ["user_id", "email", "password_hash", "role", "created_at", "full_name", "avatar_path"]


def test_0073_only_changes_comments():
    sql = (MIGRATIONS_DIR / "0073_decision_column_comments.sql").read_text(encoding="utf-8")
    body = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
    statements = [s.strip() for s in body.split(";") if s.strip()]
    assert [s.split(" IS")[0].strip() for s in statements] == ["COMMENT ON COLUMN lp_recommendation.decided_q_i",
                                                               "COMMENT ON COLUMN lp_recommendation.decision_reason"]
    assert "nothing reads" not in body
