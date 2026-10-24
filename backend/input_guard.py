"""Refuse requests Postgres, bcrypt or the JSON encoder cannot take, with a 400 instead of a 500.

QA 2026-10-24 findings 6 and 7:
  * A NUL character (U+0000) in any text value answered 500: bcrypt refuses it on the unauthenticated sign-in, and
    Postgres refuses it in a query value or a stored string. Checked in the path, the query string and every string
    (and key) of a JSON body, so no route has to remember to.
  * A JSON NaN / Infinity / -Infinity literal parsed, failed the schema's allow_inf_nan=False, and then the 422 body
    echoed `input: nan`, which the JSON encoder cannot write, so the error response itself became a 500. It is
    refused here, before validation, with the reason.

Pure ASGI so the body can be read once and handed on unchanged. Registered first in backend/main.py, which makes it
the innermost middleware: CORS still wraps its answers. A body that is not JSON, or is not valid JSON, is passed on
untouched for the framework to answer as it does today.
"""
from __future__ import annotations

import json

from starlette.responses import JSONResponse

NUL_MESSAGE = "A text value contains a NUL character (U+0000), which isn't allowed. Remove it and try again."
NAN_MESSAGE = "The request body contains NaN or Infinity, which JSON doesn't allow. Send a finite number."


class _NotFinite(ValueError):
    pass


def _refuse_constant(name: str):
    raise _NotFinite(name)


def _has_nul(value) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_nul(v) for v in value)
    return False


def _is_json(scope) -> bool:
    for name, value in scope["headers"]:
        if name == b"content-type":
            media = value.split(b";", 1)[0].strip().lower()
            return media == b"application/json" or media.endswith(b"+json")
    return False


class InputGuardMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # %00 survives in the raw query string; the path arrives already decoded.
        if "\x00" in scope["path"] or b"%00" in scope["query_string"] or b"\x00" in scope["query_string"]:
            return await JSONResponse({"detail": NUL_MESSAGE}, status_code=400)(scope, receive, send)

        if scope["method"] in ("POST", "PUT", "PATCH", "DELETE") and _is_json(scope):
            chunks: list[bytes] = []
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            body = b"".join(chunks)
            try:
                parsed = json.loads(body, parse_constant=_refuse_constant) if body else None
            except _NotFinite:
                return await JSONResponse({"detail": NAN_MESSAGE}, status_code=400)(scope, receive, send)
            except ValueError:
                parsed = None  # not valid JSON: the framework answers that, as it always has
            if _has_nul(parsed):
                return await JSONResponse({"detail": NUL_MESSAGE}, status_code=400)(scope, receive, send)

            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)

        return await self.app(scope, receive, send)
