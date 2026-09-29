"""
backend.client_ip — gives each request the visitor's real IP address when the
API runs on Render, so the per-IP sign-in limits (backend/login_limiter.py)
count real visitors instead of an address the visitor made up.

Render's proxy keeps any X-Forwarded-For header the visitor sends and adds the
real address after it, and the start command's --forwarded-allow-ips="*" makes
uvicorn take the first entry. So a visitor could name any IP they liked:
checked 2026-09-29 on the live API, a request sent with
"X-Forwarded-For: 203.0.113.77" was logged as 203.0.113.77, and the
20-failures-per-IP lock could be dodged by changing that value every time.

Render's traffic comes through Cloudflare, which sets CF-Connecting-IP to the
address that actually connected and overwrites any value the visitor sent.
When RENDER=true (Render sets it on every service), this middleware puts that
address into the request's client address, so request.client.host and
uvicorn's access log both show it. Anywhere else (a laptop, the tests) it
changes nothing. Requests without the header, such as Render's own health
checks, keep the address uvicorn gave them.

If the API moves to a host without Cloudflare in front, this header can no
longer be trusted, and this rule has to change with the host.
"""
from __future__ import annotations

import ipaddress
import os

_HEADER = b"cf-connecting-ip"


def on_render() -> bool:
    return os.environ.get("RENDER", "").strip().lower() == "true"


class RealClientIPMiddleware:
    def __init__(self, app, enabled: bool | None = None) -> None:
        self.app = app
        self.enabled = on_render() if enabled is None else enabled

    async def __call__(self, scope, receive, send) -> None:
        if self.enabled and scope["type"] in ("http", "websocket"):
            ip = _header_ip(scope.get("headers", []))
            if ip is not None:
                port = scope["client"][1] if scope.get("client") else 0
                scope["client"] = (ip, port)
        await self.app(scope, receive, send)


def _header_ip(headers) -> str | None:
    for name, value in headers:
        if name == _HEADER:
            try:
                return str(ipaddress.ip_address(value.decode("latin-1").strip()))
            except ValueError:
                return None
    return None
