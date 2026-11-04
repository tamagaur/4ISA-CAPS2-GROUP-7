"""
backend.practice_copy - whether this API process may answer from the practice copy (ssm_practice).

The same test the forecast's exception uses: analytics.forecasting.practice_switch.is_practice_database, over a real
connection, so the client and the server must both say 127.0.0.1:55432/ssm_practice. No flag, setting or header can turn it on.

    names_practice_copy()  SUPABASE_DB_URL names ssm_practice. Only decides whether to ask: every other process, the deployed API
                           included, stops here and neither connects nor imports anything for it.
    confirmed()            the connection says so too. A URL that names the copy and is not confirmed (a tunnel, a look-alike, a
                           server that is down) stays refused (routers/monthly_batch.practice_copy_refusal).

What the pages then see is decided inside that copy, never in a reader: scripts/local_pg.py makes mart.data_kind count the generated
month there and nowhere else, so backend/marts.py reads the same SQL on every database. This process only adds the label.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PRACTICE_DB = "ssm_practice"                  # scripts/local_pg.py PRACTICE_DB
LABEL_HEADER = "X-Practice-Copy"              # on every answer from the copy; frontend/src/practiceCopy.js reads it
PRACTICE_NOTE = "Read from the practice copy (ssm_practice), whose sales may be generated. Practice, not a result."


def _url() -> str:
    return os.environ.get("SUPABASE_DB_URL") or ""


def names_practice_copy() -> bool:
    return urlparse(_url()).path == f"/{PRACTICE_DB}"


@lru_cache(maxsize=4)
def _server_confirms(url: str) -> bool:
    import psycopg2

    from analytics.forecasting.practice_switch import is_practice_database
    try:
        conn = psycopg2.connect(url, connect_timeout=5)
    except psycopg2.Error as exc:
        logger.warning("The URL names the practice copy and no connection could confirm it: %s", exc)
        return False
    try:
        return is_practice_database(conn.cursor())
    finally:
        conn.close()


def confirmed() -> bool:
    return names_practice_copy() and _server_confirms(_url())
