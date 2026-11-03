"""The rollover mechanics on a scratch schema with a synthetic March 2026 (scripts/rollover_scratch_test.py).

Clones the connected database's public (about 140 MB) into ssm_rollover_test and drops it again, so it is NOT part of the normal
suite. It runs through scripts/check.sh --optin, on a disposable copy restored from a backup, and is refused anywhere else
(scripts/optin_guard.py), live above all. It asserts 61 checks, among them the isolation checks of docs/ROLLOVER_DESIGN.md (e)."""
import os

import pytest


@pytest.mark.skipif(not os.environ.get("ROLLOVER_SCRATCH"), reason="needs ROLLOVER_SCRATCH=1 and the throwaway database: scripts/check.sh --optin")
def test_rollover_on_a_scratch_schema_with_a_synthetic_march():
    from analytics.config import get_settings
    from scripts import rollover_scratch_test
    from scripts.optin_guard import require_throwaway
    require_throwaway(get_settings().supabase_db_url)
    assert rollover_scratch_test.main() == 0
