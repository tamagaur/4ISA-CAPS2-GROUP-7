"""
backend.login_limiter — stops password guessing on POST /auth/login.

Rules:
  * 10 failed sign-ins for one email within 15 minutes lock that email for
    15 minutes (5 until 2026-11-18).
  * 100 failed sign-ins from one IP address within 15 minutes lock that
    address for 15 minutes — catches someone trying a few passwords each on
    many different emails, which the per-email rule alone would not (20 until
    2026-11-18: everyone at a defence shares the venue's one address, and 20
    mistyped passwords across a room locked every account out at once, the
    correct password included).

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
Redis). On Render, request.client.host is the visitor's real address, taken
from Cloudflare's CF-Connecting-IP by backend/client_ip.py; X-Forwarded-For
can't be used there, because the visitor can set it.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import NamedTuple

# Team-set (Kelvin, 2026-11-18), not measured. A bcrypt check costs about 0.2 s, so 100 is a ceiling of
# roughly one password guess every 9 seconds per address, and 10 per account.
MAX_FAILURES_PER_EMAIL = 10
MAX_FAILURES_PER_IP = 100
# The forgot-password form's flood guard keeps its own, unchanged limits (it counts requests, not
# failures, and bounds how many reset emails one address or one network can be sent).
MAX_RESET_REQUESTS_PER_EMAIL = 5
MAX_RESET_REQUESTS_PER_IP = 20
WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60
# Once this many emails/IPs are remembered, expired ones are dropped, so a
# flood of made-up emails can't grow memory without limit.
_PRUNE_ABOVE = 10_000


@dataclass
class _Record:
    failures: deque = field(default_factory=deque)  # clock times of failures still inside the window
    locked_until: float = 0.0


class Lock(NamedTuple):
    """A lock that one failed sign-in just started."""
    seconds: int
    limits: tuple[str, ...]  # which rule tripped: ("email",), ("ip",) or both


class LoginLimiter:
    def __init__(self, clock=time.monotonic, max_per_email: int | None = None, max_per_ip: int | None = None) -> None:
        self._clock = clock
        self._max_per_email = MAX_FAILURES_PER_EMAIL if max_per_email is None else max_per_email
        self._max_per_ip = MAX_FAILURES_PER_IP if max_per_ip is None else max_per_ip
        self._mutex = threading.Lock()  # sync endpoints run on a thread pool
        self._records: dict[str, _Record] = {}

    def retry_after(self, email: str, ip: str) -> int | None:
        """Seconds until this email and IP may try again, or None if neither
        is locked."""
        lock = self.locked(email, ip)
        return lock.seconds if lock else None

    def locked(self, email: str, ip: str) -> Lock | None:
        """The lock that holds this email and IP now: seconds left (the
        longer of the two) and which of them is locked, ("email",), ("ip",)
        or both, so the refusal can say whether it is the account or the
        network. None if neither is locked."""
        now = self._clock()
        with self._mutex:
            held = [
                (rule, rec.locked_until - now)
                for rule, rec in (
                    ("email", self._records.get(_email_key(email))),
                    ("ip", self._records.get(_ip_key(ip))),
                )
                if rec is not None and rec.locked_until > now
            ]
        if not held:
            return None
        return Lock(math.ceil(max(wait for _, wait in held)), tuple(rule for rule, _ in held))

    def record_failure(self, email: str, ip: str) -> Lock | None:
        """Counts one failed sign-in against the email and the IP. Returns the
        lock this failure started (its length and which limit tripped), or
        None."""
        now = self._clock()
        tripped = []
        with self._mutex:
            for rule, key, limit in (
                ("email", _email_key(email), self._max_per_email),
                ("ip", _ip_key(ip), self._max_per_ip),
            ):
                rec = self._records.setdefault(key, _Record())
                while rec.failures and rec.failures[0] <= now - WINDOW_SECONDS:
                    rec.failures.popleft()
                rec.failures.append(now)
                if len(rec.failures) >= limit:
                    rec.locked_until = now + LOCKOUT_SECONDS
                    rec.failures.clear()
                    tripped.append(rule)
            if len(self._records) > _PRUNE_ABOVE:
                self._prune(now)
        return Lock(LOCKOUT_SECONDS, tuple(tripped)) if tripped else None

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


# Failed sign-ins are written to the audit log (backend/routers/auth.py,
# 2026-09-30). The limits above already cap that per email and per IP
# in any 15 minutes: while locked, a request is refused before its
# password is checked and nothing is logged for it. They don't cap many
# addresses together, so at most MAX_LOGGED_FAILURES_PER_WINDOW failures are
# written in any one 15-minute window. Past that, one row says logging paused;
# the rest of the window still counts toward locks but is not written.
# Five addresses' worth of the per-IP limit (team-set, Yuan, 2026-09-30, not measured), so one venue network that fills
# its own 100 failures cannot use up the log for every other address. It was 100 = 5 x 20; kept at 5 x the limit
# when that moved to 100 (2026-11-18): at most 48,000 rows a day in a flood that never stops (96 windows x 500).
# It is due to move into the params module (session 5f).
MAX_LOGGED_FAILURES_PER_WINDOW = 5 * MAX_FAILURES_PER_IP


class FailureLogBudget:
    """Decides, per failed sign-in, whether it goes into the audit log:
    'log' while this fixed 15-minute window has room, 'pause' once when it
    runs out (the caller writes one row saying so), then 'skip' until the
    next window. In memory, like LoginLimiter, and for the same reason."""

    def __init__(self, limit: int = MAX_LOGGED_FAILURES_PER_WINDOW, clock=time.monotonic) -> None:
        self.limit = limit
        self._clock = clock
        self._mutex = threading.Lock()
        self._window: int | None = None
        self._used = 0

    def take(self) -> str:
        window = int(self._clock() // WINDOW_SECONDS)
        with self._mutex:
            if window != self._window:
                self._window, self._used = window, 0
            self._used += 1
            if self._used <= self.limit:
                return "log"
            return "pause" if self._used == self.limit + 1 else "skip"

    def reset(self) -> None:
        """Starts a fresh window (tests)."""
        with self._mutex:
            self._window, self._used = None, 0


# The one limiter POST /auth/login uses.
login_limiter = LoginLimiter()

# How many of its failures reach the audit log.
failure_log_budget = FailureLogBudget()

# POST /auth/forgot-password counts every request here (not just failures):
# at most MAX_RESET_REQUESTS_PER_EMAIL reset emails per address, and
# MAX_RESET_REQUESTS_PER_IP per IP, every 15 minutes, so the form can't be used
# to flood someone's inbox.
reset_limiter = LoginLimiter(max_per_email=MAX_RESET_REQUESTS_PER_EMAIL, max_per_ip=MAX_RESET_REQUESTS_PER_IP)
