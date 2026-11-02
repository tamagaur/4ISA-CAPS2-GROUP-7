"""Response headers the browser enforces, set by the API itself (docs/DATA_GOVERNANCE.md, G2).

Vercel serves the frontend with its own headers (frontend/vercel.json); this covers the backend on Render, which
terminates HTTPS but adds nothing of the app's. Pure ASGI. A header a route already set is left alone.

  X-Content-Type-Options: nosniff        a JSON answer is never reinterpreted as a script or page
  X-Frame-Options: DENY                  the API is never framed
  Referrer-Policy: no-referrer           no URL (which can carry an id) leaks to another site
  Strict-Transport-Security              production only: browsers keep to HTTPS for a year
  Cache-Control: no-store                on sign-in, account, permission and audit routes: tokens and personal data
                                         are not kept by a browser or an intermediary cache
"""
from __future__ import annotations

NO_STORE_PREFIXES = ("/auth", "/users", "/admin", "/audit-log")
HSTS = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    def __init__(self, app, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                wanted = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                          (b"referrer-policy", b"no-referrer")]
                if self.hsts:
                    wanted.append((b"strict-transport-security", HSTS.encode("ascii")))
                if path.startswith(NO_STORE_PREFIXES):
                    wanted.append((b"cache-control", b"no-store"))
                headers.extend(h for h in wanted if h[0] not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
