"""
analytics.etl.events — Stage-agnostic, opt-in run event log.

Off by default (DSD_EVENTS != "1"): every EventLog method is then a true
no-op, so this module can be imported and called from inside a hot loop
with zero behavioral or output effect on a normal run. A logging failure
must never crash a real Extract/Transform run - every emit() body is
wrapped in try/except.

Schema (one flat JSON object per line, written to <stage_dir>/_events.jsonl):
  ts, seq, stage, event, doc_type, principal, src_file, src_sheet, status,
  rows_in, rows_out, reject_count, duration_ms, message

event is one of:
  run_start | family_start | file_start | sheet_done | file_done |
  family_done | run_end

`stage` distinguishes "extract" now from "transform" later - Transform's
driver can reuse this exact class and schema unchanged once it exists.

Each run TRUNCATES the log (see __init__) rather than appending - without
this, a second run's events land after the first run's run_end, and a
viewer polling from a fresh page load reads the stale run_end in its very
first batch and stops watching before the new run has emitted anything.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

SCHEMA_FIELDS = [
    "ts", "seq", "stage", "event", "doc_type", "principal", "src_file",
    "src_sheet", "status", "rows_in", "rows_out", "reject_count",
    "duration_ms", "message",
]


class EventLog:
    def __init__(self, path: Path | None, stage: str = "extract"):
        self.path = path
        self.stage = stage
        self.enabled = bool(path) and os.getenv("DSD_EVENTS") == "1"
        self._seq = 0
        if self.enabled:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                # Truncate: each run starts a fresh log, never appends onto
                # a prior run's (see module docstring for why this matters).
                self.path.write_text("", encoding="utf-8")
            except Exception:
                self.enabled = False

    def emit(self, fields: dict) -> None:
        """fields is a partial flat dict - must include 'event'; any other
        schema field it omits defaults to None. ts/seq/stage are always
        injected here, overriding anything the caller passed for them."""
        if not self.enabled:
            return
        try:
            self._seq += 1
            record = dict.fromkeys(SCHEMA_FIELDS)
            record.update(fields)
            record["ts"] = time.time()
            record["seq"] = self._seq
            record["stage"] = self.stage
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                fh.flush()
        except Exception:
            pass


# Shared no-op default so call sites never need `if events:` guards -
# events.emit(...) is always safe to call unconditionally. Constructed with
# path=None, so it never even reads DSD_EVENTS - existing tests that call
# parse_*() with zero arguments resolve to this and stay silent regardless
# of what's in the environment.
NULL_EVENTS = EventLog(None)
