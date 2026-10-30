"""Audit P1 and P2 (2026-10-30): the runners refuse a stale ABC period and an already-planned cycle (scripts/run_guards.py).
End to end (exit code 2, the flags letting the run through) was shown on the throwaway local database, scripts/local_pg."""
from scripts import run_guards as g


class _Cur:
    def __init__(self, one=None, many=None):
        self.one, self.many, self.sql = one, many, []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        return (self.one,)

    def fetchall(self):
        return self.many


def test_stale_abc_is_refused_and_current_abc_is_not():
    assert "2026-02" in g.stale_abc_refusal(_Cur(one="2026-03"), "2026-02")
    assert g.stale_abc_refusal(_Cur(one="2026-03"), "2026-03") is None
    assert g.stale_abc_refusal(_Cur(one=None), "2026-03") is None   # no sales at all: nothing to compare


def test_cycles_with_a_plan_counts_only_rows_that_came_from_a_run():
    cur = _Cur(many=[("2026-04-01", 121)])
    assert g.cycles_with_a_plan(cur, ["2026-04-01"], {"unilever"}) == [("2026-04-01", 121)]
    assert "lp_run_key IS NOT NULL" in cur.sql[0][0]    # legacy row 4 (no run key) never counts as a plan


def test_both_runners_expose_the_escape_flags():
    import pathlib
    lp = pathlib.Path("scripts/run_lp.py").read_text(encoding="utf-8")
    fc = pathlib.Path("scripts/run_baseline_forecast.py").read_text(encoding="utf-8")
    assert '"--replan"' in lp and '"--allow-stale-abc"' in lp and '"--allow-stale-abc"' in fc
    assert "EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2" in lp
    assert "sys.exit(EXIT_REFUSED)" in lp and "sys.exit(2)" in fc
