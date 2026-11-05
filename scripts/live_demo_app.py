"""scripts/live_demo_app.py - run the app with the Data Management live demonstration switched on (2026-11-05).

    python -m scripts.live_demo_app --rehearsal          # on ssm_rehearsal, a restored copy of live on 127.0.0.1:55432; signed in without a password; NOT live
    python -m scripts.live_demo_app --live               # on the database in .env (the real one); you sign in with your password

--rehearsal is the gate: the whole cycle (open, upload, decide, run, undo) is driven through the real page on the restored copy first.
    python -m scripts.local_pg start
    python -m scripts.live_demo_app --rehearsal --restore backups/full_backup_<stamp>     # (re)makes ssm_rehearsal from that backup, no practice changes

--live refuses to start unless local/demo_revert_proof.json says passed, and it sets LIVE_DEMO_CONFIRM_HOST to the host in .env, which is what
backend/routers/live_demo.py checks. It starts the backend on 127.0.0.1:8000 and the frontend on :5173, both on this machine only; nothing is
deployed. The hosted API never has these routes. While a demonstration is open, anyone reading the same database (the hosted site included) reads
generated March sales too, so open it when nobody else is looking, and undo it before you leave.
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
PROOF_FILE = REPO / "local" / "demo_revert_proof.json"


def rehearsal_url() -> str:
    return local_pg.local_url(db=REHEARSAL_DB)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rehearsal", action="store_true")
    mode.add_argument("--live", action="store_true")
    ap.add_argument("--restore", metavar="BACKUP_DIR", help="with --rehearsal: restore this backup into ssm_rehearsal first")
    ap.add_argument("--no-frontend", action="store_true")
    args = ap.parse_args()
    from dotenv import dotenv_values
    dotenv = dotenv_values(REPO / ".env")
    env = {**os.environ, "PYTHONUTF8": "1", "VITE_API_URL": "http://localhost:8000", "LIVE_DEMO_ENABLED": "true"}
    local_app.clear_uploads()
    if args.rehearsal:
        if args.restore:
            bad = local_pg.restore(Path(args.restore), db=REHEARSAL_DB)
            if bad:
                sys.exit(f"REFUSED: the restore does not match its manifest: {bad}")
        url = rehearsal_url()
        secret = local_app.new_secret()
        env.update({"SUPABASE_DB_URL": url, "SUPABASE_DIRECT_URL": url, "DATABASE_URL": url, "JWT_SECRET_KEY": secret, "SUPABASE_KEY": env.get("SUPABASE_KEY") or "local-dummy",
                    "CORS_ALLOWED_ORIGINS": "http://localhost:5173"})
        os.environ.update(env)
        session = local_app.start_session(url)
        token = local_app.mint_token(session["user_id"], session["email"], session["role"], session["full_name"], session["session_id"])
        (REPO / "local").mkdir(exist_ok=True)
        (REPO / "local" / "live_demo_rehearsal_session.json").write_text(json.dumps({"token": token, "role": session["role"], "email": session["email"]}), encoding="utf-8")
        print(f"\nREHEARSAL on {REHEARSAL_DB}, a restored copy of live. Not live. Signed in as {session['email']}.")
        print("Open http://localhost:5173, press F12, and paste into the Console:\n")
        print(local_app.browser_snippet(token, session["role"]) + "\n", flush=True)
    else:
        if not PROOF_FILE.is_file() or json.loads(PROOF_FILE.read_text(encoding="utf-8")).get("passed") is not True:
            sys.exit("REFUSED: no passing revert proof (local/demo_revert_proof.json)")
        url = dotenv.get("SUPABASE_DB_URL") or ""
        host = urlparse(url).hostname or ""
        if not host or host in ("127.0.0.1", "localhost"):
            sys.exit("REFUSED: .env does not name the live database")
        env.update({"SUPABASE_DB_URL": url, "LIVE_DEMO_CONFIRM_HOST": host,
                    "CORS_ALLOWED_ORIGINS": ",".join(filter(None, [dotenv.get("CORS_ALLOWED_ORIGINS"), "http://localhost:5173"]))})
        env.pop("RENDER", None)
        print(f"\nLIVE: the app on {host}, with the live demonstration switched on. Sign in with your own password at http://localhost:5173")
        print("While a demonstration is open the hosted site reads generated March sales too. Undo it before you leave.\n", flush=True)
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=REPO, env=env)
    frontend = None if args.no_frontend else subprocess.Popen("npm run dev -- --port 5173 --strictPort", cwd=REPO / "frontend", env=env, shell=True)
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
