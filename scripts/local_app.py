"""
scripts/local_app.py - run the whole app on the throwaway local database, signed in, no password (2026-11-02).

    python -m scripts.local_pg start                        # once
    python -m scripts.local_app                             # backend :8000 and frontend :5173, stops on Ctrl+C
    python -m scripts.local_app --reset BACKUP_DIR          # first restore that backup and migrate it

It prints one line to paste into the browser console at http://localhost:5173 to be signed in.

WHY THIS CANNOT REACH LIVE. No login code changed: the deployed app has no bypass. This script writes a session row into the
local database and signs a token for it with a secret it makes up on each run, so the token means nothing to the live
backend. It refuses to start unless the database is 127.0.0.1:55432, and both child processes get the local URL and that
secret in place of the ones in .env. It also switches on the Data Management batch (backend/routers/monthly_batch.py).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

LOCAL_URL = "postgresql://postgres@127.0.0.1:55432/ssm_local"     # scripts/local_pg.py
SESSION_FILE = REPO / "local" / "local_app_session.json"          # git-ignored

ADMIN_SQL = "SELECT user_id, email, full_name, role FROM users WHERE role = 'admin' ORDER BY user_id LIMIT 1"
START_SESSION_SQL = """
    INSERT INTO user_session (session_id, user_id, user_email, user_name, role, started_at, last_seen_at)
    VALUES (%s, %s, %s, %s, %s, now(), now())
"""


def require_throwaway(url: str) -> None:
    parsed = urlparse(url or "")
    if (parsed.hostname, parsed.port) != ("127.0.0.1", 55432):
        sys.exit(f"REFUSED: not the throwaway database ({parsed.hostname}:{parsed.port})")


def new_secret() -> str:
    return secrets.token_urlsafe(48)


def child_env(base: dict, url: str, secret: str) -> dict:
    return {**base, "SUPABASE_DB_URL": url, "SUPABASE_DIRECT_URL": url, "JWT_SECRET_KEY": secret, "MONTHLY_BATCH_ENABLED": "true",
            "PYTHONUTF8": "1", "VITE_API_URL": "http://localhost:8000"}


def mint_token(user_id: int, email: str, role: str, full_name: str, session_id: str) -> str:
    from backend.auth_utils import create_access_token
    return create_access_token(user_id=user_id, email=email, role=role, full_name=full_name, session_id=session_id)


def browser_snippet(token: str, role: str) -> str:
    return f"localStorage.setItem('dsd_access_token','{token}');localStorage.setItem('dsd_role','{role}');location.href='/upload'"


def start_session(url: str) -> dict:
    import psycopg2
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute(ADMIN_SQL)
        row = cur.fetchone()
        if row is None:
            sys.exit("REFUSED: the local database has no admin user to sign in as")
        user_id, email, full_name, role = row
        session_id = str(uuid.uuid4())
        cur.execute(START_SESSION_SQL, (session_id, user_id, email, full_name, role))
        conn.commit()
    finally:
        conn.close()
    return {"user_id": user_id, "email": email, "role": role, "full_name": full_name or "", "session_id": session_id}


def reset(backup: str, env: dict) -> None:
    subprocess.run([sys.executable, "-m", "scripts.local_pg", "restore", backup], cwd=REPO, check=True)
    subprocess.run([sys.executable, "-m", "scripts.run_canonical_load", "--schema", "public", "--target-public", "--schema-only"],
                   cwd=REPO, env=env, check=True)
    make_practice_copy()


def make_practice_copy() -> None:
    subprocess.run([sys.executable, "-m", "scripts.local_pg", "practice"], cwd=REPO, check=True)


def practice_copy_exists(url: str) -> bool:
    import psycopg2
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'ssm_practice'")
        return cur.fetchone() is not None
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", metavar="BACKUP_DIR", help="restore this backup into the local database and migrate it first")
    ap.add_argument("--no-frontend", action="store_true", help="start only the backend")
    args = ap.parse_args()
    url = os.environ.get("LOCAL_PG_URL", LOCAL_URL)
    require_throwaway(url)
    secret = new_secret()
    env = child_env(dict(os.environ), url, secret)
    os.environ.update(env)      # this process signs the token with the same secret
    if args.reset:
        reset(args.reset, env)
    elif not practice_copy_exists(url):
        make_practice_copy()
    session = start_session(url)
    token = mint_token(session["user_id"], session["email"], session["role"], session["full_name"], session["session_id"])
    SESSION_FILE.parent.mkdir(exist_ok=True)
    SESSION_FILE.write_text(json.dumps({"token": token, "role": session["role"], "email": session["email"]}), encoding="utf-8")
    print(f"\nLOCAL APP on the throwaway database, signed in as {session['email']}. Not live.")
    print("Open http://localhost:5173, press F12, and paste this into the Console:\n")
    print(browser_snippet(token, session["role"]) + "\n", flush=True)
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=REPO, env=env)
    frontend = None
    if not args.no_frontend:
        frontend = subprocess.Popen("npm run dev -- --port 5173 --strictPort", cwd=REPO / "frontend", env=env, shell=True)
    try:
        return backend.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        backend.terminate()
        if frontend is not None:
            subprocess.run(["taskkill", "/PID", str(frontend.pid), "/T", "/F"], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
