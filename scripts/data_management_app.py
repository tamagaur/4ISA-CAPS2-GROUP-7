"""scripts/data_management_app.py - run the app on a database so Data Management can be used against it (2026-11-06).

    python -m scripts.data_management_app --rehearsal [--restore backups/full_backup_<stamp>] [--db ssm_ui]   # a restored copy on 127.0.0.1:55432; signed in without a password; NOT live
    python -m scripts.data_management_app --live                                                           # the database in .env (the real one); you sign in with your password

Data Management is the one way a month is loaded (backend/routers/monthly_batch.py, mode "live"), and the routes are always mounted: nothing here switches them
on. This only starts the backend on 127.0.0.1:8000 and the frontend on :5173, both on this machine, and points them at a database. Nothing is deployed.
--rehearsal restores nothing unless --restore is given, and refuses any database that is not on 127.0.0.1:55432.
--live refuses unless .env names a database that is not on this machine. A load or a rollback on it still needs the attestation of this exact code
(docs/MONTH_LOAD_REHEARSAL.json), which backend/routers/monthly_batch.py reads on every request.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import local_app, local_pg  # noqa: E402

REHEARSAL_DB = "ssm_rehearsal"


def rehearsal_url(db: str = REHEARSAL_DB) -> str:
    return local_pg.local_url(db=db)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rehearsal", action="store_true")
    mode.add_argument("--live", action="store_true")
    ap.add_argument("--restore", metavar="BACKUP_DIR", help="with --rehearsal: restore this backup into ssm_rehearsal first")
    ap.add_argument("--db", default=REHEARSAL_DB, help="with --rehearsal: the restored copy's database name")
    ap.add_argument("--api-port", type=int, default=8000)
    ap.add_argument("--web-port", type=int, default=5173)
    ap.add_argument("--no-frontend", action="store_true")
    args = ap.parse_args()
    from dotenv import dotenv_values
    dotenv = dotenv_values(REPO / ".env")
    env = {**os.environ, "PYTHONUTF8": "1", "VITE_API_URL": f"http://localhost:{args.api_port}"}
    local_app.clear_uploads()
    if args.rehearsal:
        if args.restore:
            bad = local_pg.restore(Path(args.restore), db=args.db)
            if bad:
                sys.exit(f"REFUSED: the restore does not match its manifest: {bad}")
        url = rehearsal_url(args.db)
        secret = local_app.new_secret()
        env.update({"SUPABASE_DB_URL": url, "SUPABASE_DIRECT_URL": url, "DATABASE_URL": url, "JWT_SECRET_KEY": secret, "SUPABASE_KEY": env.get("SUPABASE_KEY") or "local-dummy",
                    "CORS_ALLOWED_ORIGINS": f"http://localhost:{args.web_port}"})
        os.environ.update(env)
        session = local_app.start_session(url)
        token = local_app.mint_token(session["user_id"], session["email"], session["role"], session["full_name"], session["session_id"])
        (REPO / "local").mkdir(exist_ok=True)
        (REPO / "local" / "data_management_rehearsal_session.json").write_text(json.dumps({"token": token, "role": session["role"], "email": session["email"]}), encoding="utf-8")
        print(f"\nREHEARSAL on {args.db}, a restored copy of live. Not live. Signed in as {session['email']}.")
        print(f"Open http://localhost:{args.web_port}, press F12, and paste into the Console:\n")
        print(local_app.browser_snippet(token, session["role"]) + "\n", flush=True)
    else:
        url = dotenv.get("SUPABASE_DB_URL") or ""
        host = urlparse(url).hostname or ""
        if not host or host in ("127.0.0.1", "localhost"):
            sys.exit("REFUSED: .env does not name the live database")
        env.update({"SUPABASE_DB_URL": url,
                    "CORS_ALLOWED_ORIGINS": ",".join(filter(None, [dotenv.get("CORS_ALLOWED_ORIGINS"), f"http://localhost:{args.web_port}"]))})
        env.pop("RENDER", None)
        print(f"\nLIVE: the app on {host}. Sign in with your own password at http://localhost:{args.web_port}")
        print("While a month is loaded, the hosted site reads it too (it is labelled as generated). Roll it back from Data Management if it should not stay.\n", flush=True)
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(args.api_port)], cwd=REPO, env=env)
    frontend = None if args.no_frontend else subprocess.Popen(f"npm run dev -- --port {args.web_port} --strictPort", cwd=REPO / "frontend", env=env, shell=True)
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
