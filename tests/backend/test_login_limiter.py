"""
tests/backend/test_login_limiter.py — backend/login_limiter.py's counting
rules, driven by a fake clock so 15-minute windows take no real time. The
endpoint behaviour (401 vs 429, password not checked while locked) is in
test_auth.py.
"""
from __future__ import annotations

from backend.login_limiter import (
    LOCKOUT_SECONDS,
    MAX_FAILURES_PER_EMAIL,
    MAX_FAILURES_PER_IP,
    MAX_LOGGED_FAILURES_PER_WINDOW,
    WINDOW_SECONDS,
    FailureLogBudget,
    Lock,
    LoginLimiter,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make():
    clock = FakeClock()
    return LoginLimiter(clock=clock), clock


def fail(limiter, times, email="a@x.com", ip="1.1.1.1"):
    return [limiter.record_failure(email, ip) for _ in range(times)]


def test_locks_on_the_fifth_failure_not_before():
    limiter, _ = make()
    results = fail(limiter, MAX_FAILURES_PER_EMAIL)
    assert results[:-1] == [None] * (MAX_FAILURES_PER_EMAIL - 1)
    assert results[-1] == Lock(LOCKOUT_SECONDS, ("email",))
    assert limiter.retry_after("a@x.com", "1.1.1.1") == LOCKOUT_SECONDS


def test_lock_expires_after_fifteen_minutes_with_a_fresh_count():
    limiter, clock = make()
    fail(limiter, MAX_FAILURES_PER_EMAIL)
    clock.advance(LOCKOUT_SECONDS - 1)
    assert limiter.retry_after("a@x.com", "1.1.1.1") == 1
    clock.advance(1)
    assert limiter.retry_after("a@x.com", "1.1.1.1") is None
    # Five fresh attempts, not one.
    assert fail(limiter, MAX_FAILURES_PER_EMAIL - 1) == [None] * (MAX_FAILURES_PER_EMAIL - 1)


def test_failures_older_than_the_window_stop_counting():
    limiter, clock = make()
    fail(limiter, MAX_FAILURES_PER_EMAIL - 1)
    clock.advance(WINDOW_SECONDS)
    assert limiter.record_failure("a@x.com", "1.1.1.1") is None
    assert limiter.retry_after("a@x.com", "1.1.1.1") is None


def test_email_matching_ignores_case_and_spaces():
    limiter, _ = make()
    for email in ("A@x.com", " a@X.com", "a@x.com ", "A@X.COM"):
        limiter.record_failure(email, "1.1.1.1")
    assert limiter.record_failure("a@x.com", "1.1.1.1") == Lock(LOCKOUT_SECONDS, ("email",))


def test_success_clears_the_email_count():
    limiter, _ = make()
    fail(limiter, MAX_FAILURES_PER_EMAIL - 1)
    limiter.record_success("a@x.com")
    assert fail(limiter, MAX_FAILURES_PER_EMAIL - 1) == [None] * (MAX_FAILURES_PER_EMAIL - 1)


def test_ip_limit_catches_a_few_guesses_on_many_emails():
    """Four wrong passwords on each of many emails never trips the
    per-email rule; the per-IP rule is what stops it."""
    limiter, _ = make()
    total = 0
    locks = []
    for n in range(10):
        for _ in range(MAX_FAILURES_PER_EMAIL - 1):
            if total < MAX_FAILURES_PER_IP:
                locks.append(limiter.record_failure(f"user{n}@x.com", "6.6.6.6"))
                total += 1
    assert locks[-1] == Lock(LOCKOUT_SECONDS, ("ip",))  # the lock says which limit tripped
    assert limiter.retry_after("someone-new@x.com", "6.6.6.6") == LOCKOUT_SECONDS
    assert limiter.retry_after("someone-new@x.com", "7.7.7.7") is None


def test_one_failure_can_trip_both_limits():
    limiter, _ = make()
    for n in range(MAX_FAILURES_PER_IP - MAX_FAILURES_PER_EMAIL):
        assert limiter.record_failure(f"other{n}@x.com", "6.6.6.6") is None
    results = fail(limiter, MAX_FAILURES_PER_EMAIL, ip="6.6.6.6")
    assert results[-1] == Lock(LOCKOUT_SECONDS, ("email", "ip"))


def test_stale_entries_are_pruned(monkeypatch):
    import backend.login_limiter as mod

    monkeypatch.setattr(mod, "_PRUNE_ABOVE", 10)
    limiter, clock = make()
    for n in range(8):
        limiter.record_failure(f"user{n}@x.com", f"10.0.0.{n}")  # 16 keys
    clock.advance(WINDOW_SECONDS + 1)
    limiter.record_failure("late@x.com", "10.0.1.1")
    assert len(limiter._records) == 2  # only the two fresh keys survive


# --- how many failures reach the audit log ---------------------------------

def test_failure_log_budget_logs_then_pauses_once_then_skips():
    budget = FailureLogBudget(limit=3, clock=FakeClock())
    assert [budget.take() for _ in range(6)] == ["log", "log", "log", "pause", "skip", "skip"]


def test_failure_log_budget_starts_over_each_window():
    clock = FakeClock()
    budget = FailureLogBudget(limit=1, clock=clock)
    assert [budget.take() for _ in range(3)] == ["log", "pause", "skip"]
    clock.advance(WINDOW_SECONDS)
    assert [budget.take() for _ in range(2)] == ["log", "pause"]


def test_failure_log_cap_is_tied_to_the_per_ip_limit():
    assert MAX_LOGGED_FAILURES_PER_WINDOW == 5 * MAX_FAILURES_PER_IP == 100
