"""
analytics.forecasting.practice_switch - the one exception to the forecast's refusal of labelled rows (2026-11-02).

router.assert_real_rows refuses is_demo rows, and still does everywhere else. A practice month runs on generated sales
(scripts/local_pipeline_qa.py synth), so on the practice copy, and only there, the forecast accepts them. Decided by
Kelvin, 2026-11-02; CLAUDE.md hard rule 2 says what it allows.

WHAT TURNS IT ON. The connection in hand, and nothing else: no environment variable, flag, setting or file is read, and
neither function takes an argument that could say yes. Two witnesses must both name 127.0.0.1:55432/ssm_practice:

  the client   what libpq actually connected to (conn.info), so a connection string can only name a place, not vouch for it
  the server   what the server says it is (inet_server_addr, inet_server_port, current_database), so a tunnel or port
               forward from 127.0.0.1:55432 to another server is refused: that server reports its own address and port

The label is never hidden: the rows reach the forecast still is_demo = true, the guard still sees them, and this module
is the only source of the True that lets them pass. Marked on every line of a permitted run's printed output, because
the holdout tables it prints are computed partly on those rows.
"""
from __future__ import annotations

import io
import logging
import sys

logger = logging.getLogger(__name__)

PRACTICE_DATABASE = ("127.0.0.1", 55432, "ssm_practice")     # scripts/local_pg.py: HOST:PORT/PRACTICE_DB
SERVER_IDENTITY_SQL = "SELECT host(inet_server_addr()), inet_server_port(), current_database()"
LABELLED_ROWS_SQL = "SELECT COUNT(*) FROM Unilever_SKU_Demand_Fact_Real WHERE is_demo"
OUTPUT_LABEL = "[computed on generated sales] "


def is_practice_database(cur) -> bool:
    """True only when the client and the server both name the practice copy. A socket path, `localhost`, a pooler, another
    port or another database on the same server is not it."""
    info = cur.connection.info
    cur.execute(SERVER_IDENTITY_SQL)
    return (info.host, info.port, info.dbname) == PRACTICE_DATABASE and tuple(cur.fetchone()) == PRACTICE_DATABASE


class _LabelledOutput(io.TextIOBase):
    """Puts OUTPUT_LABEL at the start of every line written through it."""

    def __init__(self, stream):
        self.stream = stream
        self.at_line_start = True

    def write(self, text: str) -> int:
        for line in text.splitlines(keepends=True):
            self.stream.write((OUTPUT_LABEL if self.at_line_start else "") + line)
            self.at_line_start = line.endswith("\n")
        return len(text)

    def flush(self) -> None:
        self.stream.flush()


def labelled_rows_permitted(cur, demand) -> bool:
    """The value for the forecast's allow_placeholder. False without asking the database when `demand` holds no labelled
    row, which is every run on a database whose _Real view excludes them, so a real run is untouched. False too when the
    database is neither the practice copy nor one with a loaded month's window in force: the guard then refuses the rows as it always has."""
    if "is_demo" not in demand.columns or not demand["is_demo"].eq(True).any():
        return False
    practice = is_practice_database(cur)
    if not practice:
        # The other witness: the loaded-month window in force in THIS database (analytics/demo_session.py).
        # Asked of the connection's own database, never of the environment. Every labelled row must carry the session's tag.
        from analytics import demo_session
        if not demo_session.permits_labelled_rows(cur):
            return False
        cur.execute("SELECT COUNT(*) FROM Unilever_SKU_Demand_Fact_Real WHERE is_demo AND _src_file IS DISTINCT FROM %s", (demo_session.TAG,))
        if cur.fetchone()[0]:
            return False
    cur.execute(LABELLED_ROWS_SQL)
    count = cur.fetchone()[0]
    host, port, database = PRACTICE_DATABASE
    where = (f"database {database} at {host}:{port}" if practice else "a database with a loaded month's window in force")
    logger.warning(f"LABELLED SALES ON: the forecast is accepting {count} labelled generated sales rows (is_demo = true) "
                   f"on {where}. This run rests on generated sales; its output is not a result.")
    if not isinstance(sys.stdout, _LabelledOutput):
        sys.stdout = _LabelledOutput(sys.stdout)
    return True
