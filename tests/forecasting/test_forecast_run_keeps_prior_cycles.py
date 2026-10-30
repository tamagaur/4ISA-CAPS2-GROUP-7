"""A forecast run writes its own cycle only (2026-10-30: it used to DELETE earlier cycles' rows for products
that had left Tier A; QA finding 4). Two consecutive cycles: the first cycle's rows must be intact."""
from __future__ import annotations

import datetime
import inspect
import json

from scripts import run_baseline_forecast as rbf

C1, C2 = datetime.date(2026, 3, 1), datetime.date(2026, 4, 1)
META = {"written_at": "2026-10-30T00:00:00Z", "code_version": "test"}


class FakeCur:
    """forecast_result as a dict keyed (product_key, forecast_date); understands only the helper's UPDATE."""
    def __init__(self, rows):
        self.rows, self.rowcount, self.statements = rows, 0, []

    def execute(self, sql, params):
        self.statements.append(" ".join(sql.split()))
        assert self.statements[-1].startswith("UPDATE forecast_result"), "a forecast run may only UPDATE-flag, never delete"
        flag, date, keep = json.loads(params[0]), params[1], set(params[2])
        self.rowcount = 0
        for (pk, d), mp in self.rows.items():
            if d == date and pk not in keep:
                mp.update(flag)
                self.rowcount += 1


def test_second_cycle_leaves_first_cycle_rows_intact():
    rows = {(pk, C1): {"method": "ma3"} for pk in (1, 2, 3)}
    before = json.dumps({str(k): v for k, v in rows.items()}, sort_keys=True)
    cur = FakeCur(rows)
    # cycle 2's Tier A set drops product 3; its writes are upserts at C2 only
    flagged = rbf._flag_retired_own_cycle(cur, C2, [1, 2], META)
    for pk in (1, 2):
        rows[(pk, C2)] = {"method": "ma3"}
    assert flagged == 0
    assert json.dumps({str(k): v for k, v in rows.items() if k[1] == C1}, sort_keys=True) == before
    assert len(rows) == 5


def test_same_cycle_stray_is_flagged_not_deleted():
    rows = {(1, C2): {"method": "ma3"}, (3, C2): {"method": "ma3"}, (3, C1): {"method": "ma3"}}
    assert rbf._flag_retired_own_cycle(FakeCur(rows), C2, [1], META) == 1
    assert "retired" in rows[(3, C2)] and "retired" not in rows[(1, C2)] and "retired" not in rows[(3, C1)]
    assert len(rows) == 3


def test_no_delete_on_forecast_result_in_the_runner():
    src = inspect.getsource(rbf)
    assert "delete from forecast_result" not in " ".join(src.lower().split())
