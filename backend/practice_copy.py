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

THE LABEL IS IN THE BODY TOO (2026-11-04). A header is lost the moment an answer is saved or pasted, and inside the copy a generated month
is data_kind 'real' to every query. PracticeBodyLabel (mounted by backend/main.py only when the URL names the copy, so never on the
deployed API) rewrites every 2xx JSON answer, whatever route made it:
    practice_copy        on the answer, or on each element of an answer that is an array: not_a_result, generated_months, note.
                         It is the guarantee: any month it lists is generated wherever that month appears in the body, the
                         parallel arrays and month-keyed maps below included.
    generated_sales_month   on any object whose month (MONTH_KEYS) is a generated month. It says what that month's sales are; a real
                         stock count dated that month carries it too, because the statement is about the month's sales.
    rests_on_generated_sales  on any object dated after the last generated month: the forecast and the plan made from it.
    data_kind, estimated, estimated_rows, synthetic_months   corrected on those objects, because each would state the opposite.
Del Monte objects keep only the top-level label: the generated month is Unilever's.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from urllib.parse import urlparse

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

PRACTICE_DB = "ssm_practice"                  # scripts/local_pg.py PRACTICE_DB
LABEL_HEADER = "X-Practice-Copy"              # on every answer from the copy; frontend/src/practiceCopy.js reads it
PRACTICE_NOTE = "Read from the practice copy (ssm_practice), whose sales may be generated. Practice, not a result."
GENERATED_TAG = "qa_synthetic_march"          # scripts/local_pg.py TAG: what `local_pipeline_qa.py synth` writes
GENERATED_KIND = "generated_practice"
# The keys that date an object. Anything else dated (a count date, a range edge) is covered by the top-level label, not by these.
MONTH_KEYS = ("period", "month", "calendar_month", "sales_period", "last_sale_period", "latest_sales_month", "latest_actual_month",
              "planning_cycle_date", "forecast_date", "forecast_period", "cycle", "cycle_date", "tier_period", "last_month")
_MONTH = re.compile(r"^(20\d{2}-\d{2})(-\d{2})?")


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


def generated_months(url: str | None = None) -> list[str] | None:
    """The months holding generated sales, read from the copy. None when it could not be read, which says so rather than saying none."""
    import psycopg2
    try:
        conn = psycopg2.connect(url or _url(), connect_timeout=5)
    except psycopg2.Error as exc:
        logger.warning("The practice copy's generated months could not be read: %s", exc)
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT left(calendar_month::text, 7) FROM unilever_sku_demand_fact WHERE is_demo AND _src_file = %s ORDER BY 1",
                    (GENERATED_TAG,))
        return [r[0] for r in cur.fetchall()]
    except psycopg2.Error as exc:
        logger.warning("The practice copy's generated months could not be read: %s", exc)
        return None
    finally:
        conn.close()


def practice_label(months: list[str] | None) -> dict:
    if months is None:
        said = "Which months are generated could not be read: treat every month here as generated."
    elif months:
        said = f"Sales for {', '.join(months)} are generated, and every forecast and plan after them rests on them."
    else:
        said = "No generated sales are in this copy yet."
    return {"not_a_result": True, "generated_months": months, "note": f"{PRACTICE_NOTE} {said}"}


def _month_of(value) -> str | None:
    found = _MONTH.match(value) if isinstance(value, str) else None
    return found.group(1) if found else None


def _in_range(month: str, row: dict) -> bool:
    start, end = _month_of(row.get("start_period")), _month_of(row.get("end_period"))
    if start and end:
        return start <= month <= end
    return str(row["year"]) == month[:4] if "year" in row else False


def _label_points(node, months: list[str], delmonte: bool = False) -> None:
    if isinstance(node, list):
        for item in node:
            _label_points(item, months, delmonte)
        return
    if not isinstance(node, dict):
        return
    if isinstance(node.get("principal"), str):
        delmonte = node["principal"].lower().replace(" ", "") == "delmonte"
    if not delmonte:
        dated = [m for m in (_month_of(node.get(k)) for k in MONTH_KEYS) if m]
        if any(m in months for m in dated):
            node["generated_sales_month"] = True
            if node.get("data_kind") == "real":
                node["data_kind"] = GENERATED_KIND
            if node.get("estimated") is False:
                node["estimated"] = True
        if any(m > months[-1] for m in dated):
            node["rests_on_generated_sales"] = True
        if isinstance(node.get("synthetic_months"), list):
            node["synthetic_months"] = sorted({*node["synthetic_months"], *(m for m in months if _in_range(m, node))})
    for value in list(node.values()):
        _label_points(value, months, delmonte)
    if isinstance(node.get("estimated_rows"), int) and isinstance(node.get("rows"), list):
        node["estimated_rows"] = sum(1 for r in node["rows"] if isinstance(r, dict) and r.get("estimated"))


def label_payload(body, months: list[str] | None):
    """The body with its label. Changes the object it is given."""
    if months:
        _label_points(body, months)
    if isinstance(body, dict):
        body["practice_copy"] = practice_label(months)
    elif isinstance(body, list):
        for item in body:
            if isinstance(item, dict):
                item["practice_copy"] = {"not_a_result": True, "generated_months": months}
    return body


def _labelled_bytes(raw: bytes) -> bytes:
    try:
        body = json.loads(raw)
    except ValueError:
        logger.warning("An answer on the practice copy said it was JSON and was not: it went out without a body label")
        return raw
    return json.dumps(label_payload(body, generated_months()), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class PracticeBodyLabel:
    """Pure ASGI, and registered innermost in backend/main.py: GZip sits outside it, so it reads the answer before it is compressed."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start, chunks = None, []

        async def relay(message):
            nonlocal start
            if message["type"] == "http.response.start":
                ctype = dict(message.get("headers") or []).get(b"content-type", b"")
                if 200 <= message["status"] < 300 and ctype.startswith(b"application/json"):
                    start = message
                    return
                await send(message)
            elif start is None:
                await send(message)
            else:
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = await run_in_threadpool(_labelled_bytes, b"".join(chunks))
                headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
                await send({**start, "headers": [*headers, (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, relay)
