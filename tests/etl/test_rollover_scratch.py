"""The rollover mechanics on a scratch schema with a synthetic March 2026 (scripts/rollover_scratch_test.py).

Clones public (about 140 MB) into ssm_rollover_test and drops it again, so it is NOT part of the normal suite:
set ROLLOVER_SCRATCH=1 to run it. It asserts 61 checks, among them the isolation checks of docs/ROLLOVER_DESIGN.md (e)."""
import os

import pytest


@pytest.mark.skipif(not os.environ.get("ROLLOVER_SCRATCH"), reason="clones the live database into a scratch schema: opt in with ROLLOVER_SCRATCH=1")
def test_rollover_on_a_scratch_schema_with_a_synthetic_march():
    from scripts import rollover_scratch_test
    assert rollover_scratch_test.main() == 0
