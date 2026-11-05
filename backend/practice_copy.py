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

ACCURACY IS WITHHELD, NOT LABELLED (hard rule 2, 2026-11-04). No accuracy figure computed on a generated month is presented, so the same
middleware, on the same copy-only mount, replaces them in the answer: no query changes and no other database is reached.
    A range that reaches a generated month    GET /dashboard's forecast_accuracy, GET /dashboard/accuracy (every level), the four
                                              /dashboard/error-decomposition routes: the figures go, blocked_reason says why. A range
                                              ending before that month keeps its figures: they are the real months'.
    A stored figure dated on or after it      mase, mape, the holdout metrics in model_params and the confidence band, which rebuilds
                                              the holdout error (GET /forecast's interval.basis). March's row was tested on February's
                                              history, and goes with April's: the rule is one line and it errs towards withholding.
    An undated figure                         GET /dashboard's evaluated and unreliable counts read the newest forecast. Withheld.
    A figure in a sentence                    "(MASE 2.54)" in GET /abc's reasons.
    A figure in the job log                   the Data Management panel shows the Run's log (GET /batch/job, /batch/status), where the forecast
                                              prints its MASE summary: that line goes, and a line says it went.
A month whose sales came through the panel's upload slot is withheld the same way, with its own reason (uploaded_months). Nothing here can tell a real
file from a made-up one, those rows are is_demo = false, and no real new monthly file has ever existed. They are not labelled generated: nobody knows that.
Which months could not be read: everything is withheld. No generated or uploaded month in the copy: nothing is.
What stays: whether a product is planned, and the rule's own threshold (mase_gate). The plan rests on the test; it is not an error figure.

RUN OR CLOSED (2026-11-04). scripts/close_cycle writes lp_recommendation.closed_at and no route read it. plan_state on GET /recommendations says
whether the plan shown is closed, and whether the month before it is. Added here because the copy is the only place a cycle has ever closed, and
live's answers are not changed by this work: serving it on every database is a separate decision.
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
UPLOAD_SRC_PREFIX = "local/monthly_batch/uploads/"   # backend/routers/monthly_batch.UPLOADS, as the loader records it in _src_file
# The keys that date an object. Anything else dated (a count date, a range edge) is covered by the top-level label, not by these.
MONTH_KEYS = ("period", "month", "calendar_month", "sales_period", "last_sale_period", "latest_sales_month", "latest_actual_month",
              "planning_cycle_date", "forecast_date", "forecast_period", "cycle", "cycle_date", "tier_period", "last_month")
_MONTH = re.compile(r"^(20\d{2}-\d{2})(-\d{2})?")
ACCURACY_RANGE_ROUTES = ("/dashboard/accuracy", "/dashboard/error-decomposition")   # the whole answer is a range's scored figures
STORED_ACCURACY_KEYS = ("mase", "mape", "wape", "confidence_lower", "confidence_upper", "evaluated_count", "unreliable_count")
MODEL_PARAMS_ACCURACY_KEYS = ("wape", "holdout_metrics_served", "holdout_metrics_all_methods", "oracle_method")
_MASE_IN_TEXT = re.compile(r"\s*\(MASE \d+(?:\.\d+)?\)")
# scripts/run_baseline_forecast.py's printed summary: every line of it that states or rebuilds an error, the win counts per class included.
_ACCURACY_LOG_LINE = re.compile(r"(?i)((mase|mape|wape|rmse|\bmae\b|\bbias\b|gap rule|outright wins).*\d|oracle_method=|\(\d+\)(\s+\d+){5}\s*$)")
LOG_LINE_WITHHELD = "[a forecast error figure was printed here: withheld on the practice copy]"


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


def uploaded_months(url: str | None = None) -> list[str] | None:
    """The months whose sales came through the panel's upload slot. None when it could not be read, which withholds everything."""
    import psycopg2
    try:
        conn = psycopg2.connect(url or _url(), connect_timeout=5)
    except psycopg2.Error as exc:
        logger.warning("The practice copy's uploaded months could not be read: %s", exc)
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT left(calendar_month::text, 7) FROM unilever_sku_demand_fact WHERE NOT is_demo AND starts_with(_src_file, %s) ORDER BY 1",
                    (UPLOAD_SRC_PREFIX,))
        return [r[0] for r in cur.fetchall()]
    except psycopg2.Error as exc:
        logger.warning("The practice copy's uploaded months could not be read: %s", exc)
        return None
    finally:
        conn.close()


def practice_label(months: list[str] | None, note: str | None = None) -> dict:
    if note is not None:   # the data-keyed label (DataKeyedLabel): the sentence is its own, and says nothing about a practice copy
        return {"not_a_result": True, "generated_months": months, "note": note}
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


def accuracy_withheld_reason(months: list[str] | None, uploaded: list[str] | None = ()) -> str:
    """Worded as the panel words it (scripts/cycle_feedback.score)."""
    if months is None or uploaded is None:
        return "Forecast error withheld: which months are generated could not be read, and an error computed on generated sales is not presented."
    said = []
    if months:
        said.append(f"sales for {', '.join(months)} on this practice copy are generated")
    if uploaded:
        said.append(f"sales for {', '.join(uploaded)} on this practice copy came from an uploaded file that nothing here has checked")
    first = min(*months, *uploaded) if len([*months, *uploaded]) > 1 else [*months, *uploaded][0]
    return (f"Forecast error withheld: {' and '.join(said)}, and an error computed on them is not presented. "
            f"A date range ending before {first} shows the real months' error.")


def _reaches_generated(block: dict, months: list[str] | None) -> bool:
    end = _month_of(block.get("end_period") or block.get("period_end"))
    return months is None or end is None or end >= months[0]


def _withheld_range(block: dict, reason: str) -> dict:
    """The answer a range with nothing to score gives, so a page reads it the way it reads Del Monte's: blocked_reason and no figures."""
    from analytics.params import REVIEW_OVER_RUN_MONTHS
    from backend.marts import accuracy_summary
    start, end = block.get("start_period"), block.get("end_period")
    keep = {k: block[k] for k in ("coverage", "level") if k in block}
    return {**accuracy_summary([], start, end, REVIEW_OVER_RUN_MONTHS), **keep, "rows": [], "compare_run": None, "actuals_version": None,
            "blocked_reason": reason, "accuracy_withheld": True}


def _withheld_decomposition(block: dict, reason: str) -> dict:
    keep = ("coverage", "product_key", "sku_code", "product_name", "category_path", "period_start", "period_end", "products_tier")
    return {**{k: block[k] for k in keep if k in block}, "available": False, "blocked_reason": reason, "accuracy_withheld": True}


def _stands(node: dict, months: list[str] | None) -> bool:
    """A stored figure stands only on an object dated, every date of it, before the first generated month."""
    if months is None:
        return False
    dated = [m for m in (_month_of(node.get(k)) for k in MONTH_KEYS) if m]
    return bool(dated) and all(m < months[0] for m in dated)


def _withhold_log(log: str) -> str:
    return "\n".join(LOG_LINE_WITHHELD if _ACCURACY_LOG_LINE.search(line) else line for line in log.split("\n"))


def _withhold_stored(node, months: list[str] | None, reason: str, delmonte: bool = False, stands: bool = False) -> None:
    if isinstance(node, list):
        for item in node:
            _withhold_stored(item, months, reason, delmonte, stands)
        return
    if not isinstance(node, dict):
        return
    if isinstance(node.get("principal"), str):
        delmonte = node["principal"].lower().replace(" ", "") == "delmonte"
    stands = stands or _stands(node, months)
    if not (delmonte or stands):
        held = [k for k in STORED_ACCURACY_KEYS if node.get(k) is not None]
        params = node.get("model_params")
        held_params = [k for k in MODEL_PARAMS_ACCURACY_KEYS if k in params] if isinstance(params, dict) else []
        for key in held:
            node[key] = None
        for key in held_params:
            del params[key]
        if held or held_params:
            node["accuracy_withheld"] = reason
    for key, value in list(node.items()):
        if isinstance(value, str):
            node[key] = _withhold_log(value) if key == "log" else _MASE_IN_TEXT.sub(" (its MASE is withheld on the practice copy)", value)
        else:
            _withhold_stored(value, months, reason, delmonte, stands)


def withhold_accuracy(body, generated: list[str] | None, path: str = "", uploaded: list[str] | None = ()):
    """The body with no accuracy figure computed on a generated or uploaded month. A new dict where a whole range goes; else changes what it is given."""
    months = None if generated is None or uploaded is None else sorted({*generated, *uploaded})
    if months == []:
        return body
    reason = accuracy_withheld_reason(generated, uploaded)
    if isinstance(body, dict) and path.startswith(ACCURACY_RANGE_ROUTES) and not body.get("blocked_reason") and _reaches_generated(body, months):
        return _withheld_range(body, reason) if path == "/dashboard/accuracy" else _withheld_decomposition(body, reason)
    if isinstance(body, dict) and path == "/dashboard" and isinstance(body.get("forecast_accuracy"), dict):
        block = body["forecast_accuracy"]
        if block.get("coverage") and _reaches_generated(block, months):
            body["forecast_accuracy"] = _withheld_range(block, reason)
    _withhold_stored(body, months, reason)
    return body


def label_payload(body, months: list[str] | None, path: str = "", uploaded: list[str] | None = (), note: str | None = None):
    """The body with its label and without the accuracy it may not present. Changes the object it is given, except where a whole range goes."""
    body = withhold_accuracy(body, months, path, uploaded)
    if months:
        _label_points(body, months)
    if isinstance(body, dict):
        body["practice_copy"] = practice_label(months, note)
    elif isinstance(body, list):
        for item in body:
            if isinstance(item, dict):
                item["practice_copy"] = {"not_a_result": True, "generated_months": months}
    return body


PLAN_STATE_SQL = """
    SELECT COUNT(*), COUNT(lr.closed_at), MAX(lr.closed_at)::text,
           (SELECT pc.state FROM planning_cycle pc WHERE pc.principal = 'unilever' AND pc.cycle = %(cycle)s)
    FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE pd.principal = 'unilever' AND lr.planning_cycle_date = %(cycle)s AND lr.lp_run_key IS NOT NULL
"""


def plan_state_of(rows: int, closed: int, cycle_state: str | None) -> str:
    """closed only when every plan row is marked and the cycle says so: anything less is a plan that can still change."""
    if rows and closed == rows and cycle_state == "closed":
        return "closed"
    return "closing" if cycle_state == "closing" else "run"


def plan_state(cycle: str) -> dict | None:
    """The plan of `cycle` (YYYY-MM-DD) and of the month before it, read from the copy. None when it could not be read."""
    import datetime

    import psycopg2
    this = datetime.date.fromisoformat(cycle[:10])
    prior = (this.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    try:
        conn = psycopg2.connect(_url(), connect_timeout=5)
    except psycopg2.Error as exc:
        logger.warning("The practice copy's plan state could not be read: %s", exc)
        return None
    try:
        cur = conn.cursor()
        out = {}
        for name, when in (("this", this), ("prior", prior)):
            cur.execute(PLAN_STATE_SQL, {"cycle": when})
            rows, closed, closed_at, state = cur.fetchone()
            out[name] = {"cycle": f"{when:%Y-%m}", "rows": rows, "state": plan_state_of(rows, closed, state), "closed_at": closed_at}
        return {**out["this"], "prior": out["prior"] if out["prior"]["rows"] else None}
    except psycopg2.Error as exc:
        logger.warning("The practice copy's plan state could not be read: %s", exc)
        return None
    finally:
        conn.close()


DEMO_LABEL_TTL_S = 5.0
_demo_labels_cache: dict = {"at": -1e9, "value": ([], [])}


def demo_labels(now=None) -> tuple[list[str] | None, list[str] | None]:
    """(generated months, uploaded months) read from the database this process answers from, whichever database that is, kept for
    DEMO_LABEL_TTL_S seconds. This is the DATA deciding, not the connection: a database holding no generated sales answers ([], [])
    and the middleware stays out of the way; one that holds them is labelled and its accuracy is withheld. None means unreadable."""
    import time
    if not _url():   # nothing to read (a test client, a tool): no database is named, so none is holding generated sales
        return [], []
    at = time.monotonic() if now is None else now
    if at - _demo_labels_cache["at"] > DEMO_LABEL_TTL_S:
        _demo_labels_cache["value"] = (generated_months(), uploaded_months())
        _demo_labels_cache["at"] = at
    return _demo_labels_cache["value"]


def demo_note(months: list[str] | None, uploaded: list[str] | None) -> str:
    if months is None or uploaded is None:
        return "Which months hold generated sales could not be read: treat every recent figure here as generated. Demonstration, not a result."
    said = f"Sales for {', '.join(months)} are generated demonstration data (is_demo)" if months else ""
    if uploaded:
        said += (", and " if said else "") + f"sales for {', '.join(uploaded)} came through the upload slot, which cannot tell a real file from a made-up one"
    return f"{said}. Forecast error is withheld wherever they are counted, and every forecast and plan after them rests on them. Demonstration, not a result."


def _labelled_bytes(raw: bytes, path: str = "", data_keyed: bool = False) -> bytes:
    note = None
    if data_keyed:
        generated, uploaded = demo_labels()
        note = demo_note(generated, uploaded)
    try:
        body = json.loads(raw)
    except ValueError:
        logger.warning("An answer on the practice copy said it was JSON and was not: it went out without its label")
        return raw
    if path == "/recommendations" and isinstance(body, dict) and isinstance(body.get("planning_cycle_date"), str):
        body["plan_state"] = plan_state(body["planning_cycle_date"])
    if data_keyed:
        return json.dumps(label_payload(body, generated, path, uploaded, note), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return json.dumps(label_payload(body, generated_months(), path, uploaded_months()), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class PracticeBodyLabel:
    """Pure ASGI, and registered innermost in backend/main.py: GZip sits outside it, so it reads the answer before it is compressed."""

    def __init__(self, app, data_keyed: bool = False):
        self.app = app
        self.data_keyed = data_keyed   # True on every database but the practice copy: acts only while the data holds generated sales

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start, chunks, generated, uploaded = None, [], [], []
        if self.data_keyed:
            generated, uploaded = await run_in_threadpool(demo_labels)
            if generated == [] and uploaded == []:   # no generated sales in this database: the answer goes out as it is, unread and unbuffered
                await self.app(scope, receive, send)
                return

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
                body = await run_in_threadpool(_labelled_bytes, b"".join(chunks), scope.get("path", ""), self.data_keyed)
                headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
                if self.data_keyed:   # the page's banner reads this (frontend/src/practiceCopy.js); the practice URL sets it in main.py instead
                    headers.append((LABEL_HEADER.lower().encode(), demo_note(generated, uploaded).encode("ascii", "replace")))
                await send({**start, "headers": [*headers, (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, relay)
