"""
backend.api_errors — errors with a machine code, in the shape the
permissions proposal's API contract freezes (Yuan's proposal, revised
2026-09-30):

    {"detail": "<a sentence a person can read>", "code": "<machine code>", ...extra}

`detail` stays human because every frontend API wrapper shows body.detail
as its error text; the frontend branches on `code`, never on detail.
FastAPI's HTTPException nests everything under `detail`, so it can't carry
`code` beside it; ApiError plus the handler below can. main.py registers
the handler.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raise from a router or dependency: ApiError(403, "You don't have
    access to this. Ask an admin.", code="missing_permission",
    permission="lp.decide")."""

    def __init__(self, status_code: int, detail: str, *, code: str, **extra) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.extra = extra


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code, **exc.extra},
    )
