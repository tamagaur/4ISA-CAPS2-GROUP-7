"""scripts/demo_rehearsal.py: a rehearsal counts only for the code it ran, only when it was a whole month, only when made on this machine."""
from __future__ import annotations

import json

from scripts import demo_rehearsal as dr

WHOLE_MONTH = [f"{t}: removed 1, put back 0" for t in dr.MUST_HAVE_CHANGED]


def test_a_rehearsal_of_a_load_alone_is_not_a_rehearsal():
    assert dr.month_really_ran(WHOLE_MONTH) == []
    assert dr.month_really_ran(["public.unilever_sku_demand_fact: removed 709, put back 644"]) == [t for t in dr.MUST_HAVE_CHANGED if t != "public.unilever_sku_demand_fact"]


def test_the_record_counts_only_for_the_code_it_ran(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "PROOF", tmp_path / "rehearsal.json")
    assert dr.ok()[0] is False and "no rehearsal" in dr.ok()[1]
    dr.write("127.0.0.1/ssm_rehearsal", (109, 435988), (109, 435988), WHOLE_MONTH)
    assert dr.ok() == (True, "")
    monkeypatch.setattr(dr, "code_hash", lambda: "a different file set")      # any edit to the files that make the window changes the hash
    passed, why = dr.ok()
    assert passed is False and "rehearse it again" in why


def test_a_record_made_off_this_machine_or_not_passed_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "rehearsal.json"
    monkeypatch.setattr(dr, "PROOF", path)
    good = {"passed": True, "code_hash": dr.code_hash(), "target": "127.0.0.1/ssm_rehearsal"}
    for change, fragment in (({"passed": False}, "did not pass"), ({"target": "aws-0.pooler.supabase.com/postgres"}, "not made on a database on this machine")):
        path.write_text(json.dumps({**good, **change}))
        assert dr.ok()[0] is False and fragment in dr.ok()[1]
    path.write_text(json.dumps(good))
    assert dr.ok()[0] is True


def test_every_file_the_hash_covers_exists():
    for name in dr.FILES:
        assert (dr.REPO / name).is_file(), name
