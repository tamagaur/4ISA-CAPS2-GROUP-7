"""
backend.response_cache — read endpoints' responses, kept in memory until the data changes.

WHY (2026-10-04). A page's data only changes when the pipeline or an app user changes it:
a data load, a fill, a forecast run, an LP run (each followed by a mart refresh), a reorder
decision, or a SKU added or edited. Between those, every request rebuilt the same answer.

KEY. Endpoint + every query/path parameter (principal, date range, ...) + the user's
EFFECTIVE PERMISSION SET. Two users share an entry only when they hold exactly the same
permissions, so a response built for a user with lp.view (LP figures included) is never
served to one without it: the endpoint itself leaves those figures out for that user, and
that user's requests have a key of their own.

CLEARED. The session check reads a data version in the same round trip
(backend/deps.DATA_VERSION_COLUMN: the marts' refresh status, which moves with every data
load, fill, forecast run, LP run and mart refresh; the latest reorder decision; the latest
SKU added or edited). When it differs from the version the entries were built at, every
entry is dropped. So a change made anywhere (the pipeline on a laptop, the app on Render)
clears this server's cache on its next request. A write through this server also clears it
at once (invalidate(), called by the app's own write endpoints).

NOT CACHED. Preview mode (its data also comes from files, outside the version); a request
without a data version or a permission set (tests' fake sessions, a database before
migration 0041); anything that raises.
"""
from __future__ import annotations

import functools
import threading
from collections import OrderedDict

from backend.data_mode import PREVIEW

# Entries, least recently used dropped first: the cap is what bounds memory. The largest
# response, GET /sku, is ~0.7-0.9 MB as JSON (measured 2026-10-04); held as Python objects
# it takes more (not measured).
MAX_ENTRIES = 64

_lock = threading.Lock()
_entries: OrderedDict[tuple, object] = OrderedDict()
_state = {"version": None, "hits": 0, "misses": 0}


def invalidate() -> None:
    """Drop every entry (an app write changed the data the responses were built from)."""
    with _lock:
        _entries.clear()
        _state["version"] = None


def stats() -> dict:
    with _lock:
        return {"entries": len(_entries), "hits": _state["hits"], "misses": _state["misses"]}


def _freeze(value):
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    return value


def cached(endpoint: str):
    """Decorates a GET route whose parameters include `db` (the request's Session) and
    `current_user` (from get_current_user / require_permission). Its response may depend
    only on the database, its parameters and the user's permissions."""
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            db, user = kwargs.get("db"), kwargs.get("current_user")
            info = getattr(db, "info", None)
            version = info.get("data_version") if isinstance(info, dict) else None
            granted = getattr(user, "permissions", None)
            if args or version is None or granted is None or kwargs.get("mode") == PREVIEW:
                return fn(*args, **kwargs)
            key = (endpoint, _freeze({k: v for k, v in kwargs.items() if k not in ("db", "current_user")}),
                   frozenset(granted))
            with _lock:
                if _state["version"] != version:
                    _entries.clear()
                    _state["version"] = version
                if key in _entries:
                    _entries.move_to_end(key)
                    _state["hits"] += 1
                    return _entries[key]
                _state["misses"] += 1
            result = fn(*args, **kwargs)
            with _lock:
                if _state["version"] == version:
                    _entries[key] = result
                    _entries.move_to_end(key)
                    while len(_entries) > MAX_ENTRIES:
                        _entries.popitem(last=False)
            return result
        return wrapper
    return decorate
