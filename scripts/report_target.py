"""
scripts/report_target.py - keep a non-live run from overwriting a tracked report.

Several scripts write a file under reports/ or docs/ that is committed and describes the LIVE database. Run against
the throwaway local Postgres (scripts/local_pg.py) they used to overwrite it with numbers that are not live's.

    path = report_path(REPO / "docs" / "X.md")

returns the path unchanged when the run's database is live, and local/nonlive_reports/<path relative to the repo>
(git-ignored) when it is not. "Not live" = the connection URL's host is 127.0.0.1 or localhost; an unset URL counts
as live, since the scripts that call this refuse to run without one anyway.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
NONLIVE_DIR = REPO / "local" / "nonlive_reports"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def is_live_target() -> bool:
    url = os.environ.get("SUPABASE_DB_URL") or ""
    if not url:
        try:
            from dotenv import dotenv_values
            url = dotenv_values(REPO / ".env").get("SUPABASE_DB_URL") or ""
        except ImportError:
            pass
    return (urlparse(url).hostname or "") not in _LOCAL_HOSTS


def report_path(tracked: str | os.PathLike) -> Path:
    """The path to write `tracked` to: itself for live, local/nonlive_reports/... otherwise."""
    p = Path(tracked).resolve()
    if is_live_target():
        return p
    if REPO not in p.parents:  # an explicit path outside the repo is the caller's choice
        return p
    out = NONLIVE_DIR / p.relative_to(REPO)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out
