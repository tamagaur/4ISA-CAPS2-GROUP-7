"""
backend.scripts.seed_admin — one-time creation of the first admin user.

Story #89: POST /auth/register is admin-only, so on a fresh database there
is no admin token to call it with. This script breaks that chicken-and-egg
problem by inserting the first admin directly, outside the API — run it
once, manually, against Supabase:

    python -m backend.scripts.seed_admin --email admin@ssm.example --name "Full Name" --password "<a real password>"

It prompts for the password interactively if --password is omitted, so the
plaintext never has to sit in shell history. After the first admin exists,
use POST /auth/register (as that admin) for every subsequent account —
do not run this script again except to recover a locked-out deployment.
"""
from __future__ import annotations

import argparse
import getpass

from sqlalchemy import text

from backend.auth_utils import hash_password
from backend.deps import get_db


def seed_admin(email: str, password: str, full_name: str) -> None:
    db = next(get_db())
    try:
        existing = db.execute(
            text("SELECT 1 FROM Users WHERE email = :email"), {"email": email}
        ).first()
        if existing is not None:
            raise SystemExit(f"A user with email {email!r} already exists — refusing to overwrite.")

        db.execute(
            text(
                "INSERT INTO Users (email, password_hash, full_name, role) "
                "VALUES (:email, :password_hash, :full_name, 'admin')"
            ),
            {"email": email, "password_hash": hash_password(password), "full_name": full_name},
        )
        db.commit()
        print(f"Admin user {email!r} ({full_name!r}) created.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="Display name shown in the dashboard once signed in.")
    parser.add_argument("--password", default=None, help="Omit to be prompted interactively.")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters.")
    seed_admin(args.email, password, args.name)


if __name__ == "__main__":
    main()
