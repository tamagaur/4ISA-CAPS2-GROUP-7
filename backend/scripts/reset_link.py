"""
backend.scripts.reset_link — a password-reset link made on the server, for
an account that can't get one any other way.

Forgot password on the sign-in page emails a link to anyone, admins
included, and an admin can send anyone a link from User Management. The
case neither covers: the server has no email set up and the only admin has
forgotten their password, so there is nobody to ask. Whoever runs the
server (with its .env database settings) makes the link here instead:

    python -m backend.scripts.reset_link --email admin@ssm.example

It prints the link to pass on; nothing is emailed. The link points at
FRONTEND_URL from .env (localhost:5173 when unset), so set that to the live
site's address when making a link for the live dashboard. Same rules as an
admin-sent reset: it works once, lasts account_links.ADMIN_RESET_MINUTES,
retires the account's older links, and goes to the audit log as "Reset Link
Sent" by "system". The password is still chosen by the person who opens it.
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from backend import account_links, audit
from backend.deps import get_db


def make_reset_link(email: str) -> tuple[str, object]:
    db = next(get_db())
    try:
        row = db.execute(
            text("SELECT user_id, password_hash FROM users WHERE lower(email) = lower(:email)"),
            {"email": email},
        ).mappings().first()
        if row is None:
            raise SystemExit(f"No account uses {email!r}.")
        if row["password_hash"] is None:
            raise SystemExit(f"{email!r} hasn't accepted its invite yet; send a new invite from User Management.")
        token, expires_at = account_links.issue(
            db, user_id=row["user_id"], purpose="reset", minutes=account_links.ADMIN_RESET_MINUTES
        )
        audit.record(db, "Reset Link Sent", f"{email} (made on the server)", email="system")
        db.commit()
        return account_links.link_url(token), expires_at
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True, help="The account's email.")
    args = parser.parse_args()
    link, expires_at = make_reset_link(args.email)
    print(f"Reset link for {args.email} (works once, until {expires_at:%Y-%m-%d %H:%M %Z}):\n{link}")


if __name__ == "__main__":
    main()
