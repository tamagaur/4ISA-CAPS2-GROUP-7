"""
backend.demo_flag — the DM_DEMO_ENABLED switch for the labelled demonstration path (CLAUDE.md rule 2).

Default OFF: unset, empty or anything but 1 / true / yes / on is off. Read on every call, so a deployment flips it
by environment variable alone. With it off, GET /demo/series is a plain 404 and no other route changes.
"""
from __future__ import annotations

import os

ENV_VAR = "DM_DEMO_ENABLED"
_ON = {"1", "true", "yes", "on"}


def demo_enabled() -> bool:
    return os.environ.get(ENV_VAR, "").strip().lower() in _ON
