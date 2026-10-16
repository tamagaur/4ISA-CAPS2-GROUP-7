"""
backend.sessions — the user_session rules shared by sign-in
(backend/routers/auth.py), the check every request passes
(backend/deps.py:get_current_user) and user management.

Every sign-in opens a user_session row (migration 0023) and its id rides in
the JWT as 'sid'. Since 2026-09-28 each request checks that row, so a session
can be ended from the server — by signing out, by going SESSION_IDLE_MINUTES
without a heartbeat, or by an admin changing or removing the account — and
the token stops working at once instead of when it expires hours later.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# A session with no heartbeat for this long is over. The frontend beats every
# 60s while the page is visible, so only a hidden or closed tab goes this
# quiet; without the cut-off a tab left open overnight would read as one
# 8-hour session (tokens last 8h). 4 hours since 2026-10-16 (was 30 min):
# Audrey, so people working in another window aren't signed out every half
# hour; the 8-hour token limit still applies.
SESSION_IDLE_MINUTES = 4 * 60

# Closes the session at its last activity if it has been idle too long, so
# the idle gap is never counted as part of it.
CLOSE_IF_IDLE_SQL = """
    UPDATE user_session
       SET ended_at = last_seen_at, end_reason = 'idle'
     WHERE session_id = :session_id AND ended_at IS NULL
       AND last_seen_at < now() - make_interval(mins => :idle_minutes)
"""

# end_reason 'revoked' needs migration 0031.
REVOKE_USER_SESSIONS_SQL = """
    UPDATE user_session SET ended_at = now(), end_reason = 'revoked'
     WHERE user_id = :user_id AND ended_at IS NULL
"""


def revoke_user_sessions(db: Session, user_id: int) -> None:
    """Ends every open session of one account, so its next request is refused
    and the person signs in again: after their role or email changes, their
    password is set or reset, or the account is deleted. Runs in the caller's
    transaction; the caller commits."""
    db.execute(text(REVOKE_USER_SESSIONS_SQL), {"user_id": user_id})
