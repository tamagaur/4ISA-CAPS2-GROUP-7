"""
scripts/practice_signed_load.py - a Data Management panel Run with uploaded files, on the practice copy only.

    python -m scripts.practice_signed_load --approved-by NAME --slice SPEC --file PATH ... -- -m scripts.run_month --month ... --slice SPEC --file PATH ...

A load refuses a manifest nobody signed (scripts/load_slices.py, fingerprint_unsigned), and until this existed nothing in the panel signed one,
so every uploaded file, sales and stock count alike, stopped the Run at its load step. This does what docs/MONTHLY_LOAD_PROCEDURE.md
steps 3 to 5 do by hand: dry run, record the sign-off, load (through scripts.run_month). The name on it is the person who pressed Run.

THAT IS NOT A REVIEW. Nobody read the manifest; pressing Run on a file you chose stands in for it, on a throwaway copy, and the notes say so.
So it reaches no further than that copy: it refuses any connection but the practice copy's (the forecast's own test,
analytics/forecasting/practice_switch), it changes nothing in the gate itself, and the sign-off is deleted when the run ends. A sign-off is
tied to its manifest's fingerprint, and a later load of these same files with these same slices would otherwise find it.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RUN_KEY = re.compile(r"\[manifest\] run key (\S+):")
NOTES = "Practice copy, Data Management panel: the person who pressed Run. Not a review of this manifest."


def on_practice_copy() -> bool:
    import psycopg2

    from analytics.forecasting.practice_switch import is_practice_database
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        return is_practice_database(conn.cursor())
    finally:
        conn.close()


def run_key_of(output: str) -> str | None:
    found = RUN_KEY.search(output)
    return found.group(1) if found else None


def tee(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    seen = []
    for line in proc.stdout:
        seen.append(line)
        print(line, end="", flush=True)
    return proc.wait(), "".join(seen)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--" not in argv:
        print("usage: ... -- <the run_month arguments>")
        return 2
    cut = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved-by", required=True)
    ap.add_argument("--slice", action="append", required=True)
    ap.add_argument("--file", action="append", required=True)
    args = ap.parse_args(argv[:cut])
    if not on_practice_copy():
        print("REFUSED: this signs a manifest for a person who did not read it, so it runs on the practice copy and nowhere else.")
        return 2
    py = sys.executable
    pairs = [x for s in args.slice for x in ("--slice", s)] + [x for f in args.file for x in ("--file", f)]
    print("[practice load] dry run of the uploaded files", flush=True)
    rc, output = tee([py, "-m", "scripts.run_canonical_load", "--schema", "public", "--target-public", "--dry-run", *pairs])
    key = run_key_of(output)
    if rc or key is None:
        print(f"[practice load] the dry run refused (exit {rc}): nothing was loaded. Its reason is above.", flush=True)
        return rc or 1
    folder = REPO / "transform" / "slices" / key
    try:
        print(f"[practice load] sign-off recorded for {args.approved_by}: {NOTES}", flush=True)
        rc, _ = tee([py, "-m", "analytics.etl.transform_signoff", "--transform-dir", folder.relative_to(REPO).as_posix(),
                     "--decision", "approved", "--by", args.approved_by, "--notes", NOTES])
        if rc:
            return rc
        rc, _ = tee([py, *argv[cut + 1:]])
        return rc
    finally:
        (folder / "_signoff.json").unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
