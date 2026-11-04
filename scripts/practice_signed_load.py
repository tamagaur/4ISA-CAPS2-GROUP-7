"""
scripts/practice_signed_load.py - a Data Management panel Run with uploaded files, on the practice copy only.

    python -m scripts.practice_signed_load --pressed-by NAME -- -m scripts.run_month --month ... --slice SPEC --file PATH ...

A load refuses a manifest nobody signed (scripts/load_slices.py, fingerprint_unsigned), and until this existed nothing in the panel signed one,
so every uploaded file, sales and stock count alike, stopped the Run at its load step.

THE SYSTEM SIGNS, AND THE RECORD SAYS SO (2026-11-04). Nobody reads the manifest on this path, so no person's name goes on it: decided_by is
SYSTEM_SIGNER, the etl_load_event and audit_log rows name it too (load_slices.run), and the person who pressed Run is recorded as exactly that.

ONE READ (2026-11-04). This used to run a dry run, sign what it printed, then load, so every SSIS workbook was read twice (763 s against 112 s).
The dry run existed only to produce a manifest to sign. Now run_month's load step gets --practice-auto-sign: the load builds its manifest from what
it staged, signs that (sign_manifest) and passes the unchanged gate. What the fingerprint binds is the same, the staged sheets that are then
loaded. What goes is only the re-read, which on the manual path catches a file changed between the review and the load: here no review exists.

It reaches no further than that copy: the loader refuses the flag on any connection but the practice copy's (the forecast's own test,
analytics/forecasting/practice_switch), and it changes nothing in the gate itself. A live sign-off still needs a named person
(analytics.etl.transform_signoff). When the run ends, _signoff.json is moved aside, because a sign-off is tied to its manifest's fingerprint and a
later load of these same files with these same slices would otherwise find it. The record stays, in _signoff_practice_auto.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.report_target import PRACTICE_MARKER  # noqa: E402

RUN_KEY = re.compile(r"\[manifest\] run key (\S+):")
SYSTEM_SIGNER = "system: auto-signed on the practice copy, no review"
NOTES = "Auto-signed by the system on the practice copy. No person read this manifest."
AUTO_FLAG = "--practice-auto-sign"
KEPT_RECORD = "_signoff_practice_auto.json"


def on_practice_copy() -> bool:
    import psycopg2

    from analytics.forecasting.practice_switch import is_practice_database
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        return is_practice_database(conn.cursor())
    finally:
        conn.close()


def sign_manifest(transform_dir: Path) -> None:
    """Called by the loader, for the manifest it just wrote, only under AUTO_FLAG (refused off the practice copy in load_slices.run)."""
    from analytics.etl.transform_signoff import record_signoff
    record_signoff(transform_dir, "approved", SYSTEM_SIGNER, NOTES)
    print(f"[practice load] sign-off recorded by {SYSTEM_SIGNER}", flush=True)


def retire_signoff(folder: Path, pressed_by: str) -> None:
    """Out of the gate's way, into a record that says what happened. The marker comes first, where a reader sees it."""
    signoff = folder / "_signoff.json"
    if not signoff.exists():
        return
    record = {"_practice": PRACTICE_MARKER, "_what_happened": f"The system signed this manifest; {pressed_by} pressed Run; no person reviewed it.",
              "run_pressed_by": pressed_by, **json.loads(signoff.read_text(encoding="utf-8"))}
    (folder / KEPT_RECORD).write_text(json.dumps(record, indent=2), encoding="utf-8")
    signoff.unlink()


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
    ap.add_argument("--pressed-by", required=True)
    args = ap.parse_args(argv[:cut])
    if not on_practice_copy():
        print("REFUSED: this has the system sign a manifest nobody read, so it runs on the practice copy and nowhere else.")
        return 2
    print(f"[practice load] Run pressed by {args.pressed_by}. The system signs the manifest; nobody reviews it.", flush=True)
    rc, output = tee([sys.executable, *argv[cut + 1:], AUTO_FLAG])
    key = run_key_of(output)
    if key:
        retire_signoff(REPO / "transform" / "slices" / key, args.pressed_by)
    return rc


if __name__ == "__main__":
    sys.exit(main())
