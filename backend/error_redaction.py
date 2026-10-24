"""The 422 body, without the values that failed validation when they are secrets.

FastAPI's default 422 echoes each failing field's `input`. For sign-in that put the submitted password in the
response, and so in any proxy or client log that records bodies (QA 2026-10-24, finding 16). A field whose name
mentions password, token, secret, key (api/private/encryption key, or a field called key) or a sign-in code never has its value in an error body; nor does a value nested inside a
larger input, nor a whole body that failed to parse (the text may hold any of them).

Logs: no handler logs a request body or a validation error. The few logger calls in backend/ name an object or an
e-mail address, never a field value; tests/backend/test_secret_redaction.py fails if one starts to log a request.
"""
from __future__ import annotations

import re

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

SECRET_NAME = re.compile(r"password|passwd|token|secret|api_?key|private_?key|encryption_?key|^key$|authorization|credential|otp|recovery|^code$", re.I)
REDACTED = "[hidden]"


def _redact(value):
    """A copy of `value` with the contents of every secret-named key hidden."""
    if isinstance(value, dict):
        return {k: (REDACTED if SECRET_NAME.search(str(k)) else _redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def clean_error(error: dict) -> dict:
    loc = [str(part) for part in error.get("loc", ())]
    out = {k: v for k, v in error.items() if k != "ctx"}
    whole_body = loc == ["body"] or error.get("type") == "json_invalid"
    if any(SECRET_NAME.search(part) for part in loc) or whole_body and not isinstance(error.get("input"), dict):
        out.pop("input", None)
    elif "input" in out:
        out["input"] = _redact(out["input"])
    if "ctx" in error:   # limits (max_length, pattern...) are safe; an embedded error object or value is not
        out["ctx"] = {k: v for k, v in error["ctx"].items() if isinstance(v, (int, float, str)) and k != "error"}
    return out


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder([clean_error(e) for e in exc.errors()])})
