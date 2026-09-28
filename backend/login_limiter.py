"""
backend.login_limiter — stops password guessing on POST /auth/login.

Rules:
  * 5 failed sign-ins for one email within 15 minutes lock that email for
    15 minutes.
  * 20 failed sign-ins from one IP address within 15 minutes lock that
    address for 15 minutes — catches someone trying a few passwords each on
    many different emails, which the per-email rule alone would not.

While locked, every attempt is refused with 429 BEFORE the password is
checked. If a correct password still got through during the lock, the
attacker could keep guessing and simply watch for the one attempt that
answers differently.

Only failures count: signing in and out repeatedly with the right password
is never limited, and a successful sign-in clears that email's count.
Unknown emails are counted and locked exactly like real ones, so the lock
cannot be used to find out which emails have accounts.

Kept in memory, not the database: the API runs as a single uvicorn process
(`uvicorn backend.main:app`), and a restart clearing the counts is an
acceptable cost. If the API is ever run with several worker processes, each
would keep its own counts, and this must move to shared storage (a table or
Redis). Behind a reverse proxy, request.client.host is the proxy's address,
so the per-IP rule would need the forwarded client address instead.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field

MAX_FAILURES_PER_EMAIL = 5
MAX_FAILURES_PER_IP = 20
WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60
# Once this many emails/IPs are remembered, expired ones are dropped, so a
# flood of made-up emails can't grow memory without limit.
_PRUNE_ABOVE = 10_000


@dataclass
class _Record:
    failures: deque = field(default_factory=deque)  # clock times of failures still inside the window
    locked_until: float = 0.0


class LoginLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._mutex = threading.Lock()  # sync endpoints run on a thread pool
        self._records: dict[str, _Record] = {}

    def retry_after(self, email: str, ip: str) -> int | None:
        """Seconds until this email and IP may try again, or None if neither
        is locked."""
        now = self._clock()
        with self._mutex:
            waits = [
                rec.locked_until - now
                for rec in (self._records.get(key) for key in (_email_key(email), _ip_key(ip)))
                if rec is not None and rec.locked_until > now
            ]
        return math.ceil(max(waits)) if waits else None

    def record_failure(self, email: str, ip: str) -> int | None:
        """Counts one failed sign-in against the email and the IP. Returns the
        lock length in seconds if this failure started a lock, else None."""
        now = self._clock()
        started = None
        with self._mutex:
            for key, limit in ((_email_key(email), MAX_FAILURES_PER_EMAIL), (_ip_key(ip), MAX_FAILURES_PER_IP)):
                rec = self._records.setdefault(key, _Record())
                while rec.failures and rec.failures[0] <= now - WINDOW_SECONDS:
                    rec.failures.popleft()
                rec.failures.append(now)
                if len(rec.failures) >= limit:
                    rec.locked_until = now + LOCKOUT_SECONDS
                    rec.failures.clear()
                    started = LOCKOUT_SECONDS
            if len(self._records) > _PRUNE_ABOVE:
                self._prune(now)
        return started

    def record_success(self, email: str) -> None:
        with self._mutex:
            self._records.pop(_email_key(email), None)

    def reset(self) -> None:
        """Forgets every count and lock (tests)."""
        with self._mutex:
            self._records.clear()

    def _prune(self, now: float) -> None:
        stale = [
            key for key, rec in self._records.items()
            if rec.locked_until <= now and (not rec.failures or rec.failures[-1] <= now - WINDOW_SECONDS)
        ]
        for key in stale:
            del self._records[key]


def _email_key(email: str) -> str:
    # Case-insensitive, so 'Admin@x.com' and 'admin@x.com' share one count.
    return "email:" + email.strip().lower()


def _ip_key(ip: str) -> str:
    return "ip:" + ip


# The one limiter POST /auth/login uses.
login_limiter = LoginLimiter()

# POST /auth/forgot-password counts every request here (not just failures):
# at most 5 reset emails per address, and 20 per IP, every 15 minutes, so the
# form can't be used to flood someone's inbox.
reset_limiter = LoginLimiter()
