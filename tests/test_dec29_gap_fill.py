"""DEC-29 gap fill (scripts/build_synthetic_v2_clean_pool.py): OFF by default, and its dry run writes nothing.

No database: the pools are the real Del Monte monthly row counts per site, read from public 2026-09-29 (read-only) -
the monthly sales-return files (source IS NULL) and the purchases. The planner is pure; dm_dec29_gaps runs against a
fake cursor that records every statement."""
import pytest

from scripts.build_synthetic_v2_clean_pool import (DEC29_PURCHASES, DEC29_RETURNS, FORWARD, MONTHS_2122, SITES,
                                                   dm_dec29_gaps, nearest_moy, plan_dec29_gaps, rng)


def _counts(s):
    return {k: int(v) for k, v in (x.split(":") for x in s.split(", "))}


RETURNS = {
    "ilocos": _counts("2023-01:25, 2023-02:17, 2023-03:18, 2023-04:13, 2023-05:28, 2023-06:27, 2023-08:15, 2023-09:31, 2023-11:20, "
                      "2023-12:49, 2024-01:60, 2024-02:21, 2025-03:20, 2025-04:15, 2025-06:40, 2025-08:47, 2025-09:28, 2025-12:30"),
    "pangasinan": _counts("2023-01:45, 2023-02:30, 2023-03:24, 2023-04:24, 2023-05:41, 2023-06:44, 2023-08:51, 2023-09:53, 2023-11:15, "
                          "2023-12:43, 2024-01:35, 2024-02:42, 2025-03:60, 2025-04:45, 2025-06:80, 2025-08:75, 2025-09:96, 2025-12:73"),
}
PURCHASES = {
    "ilocos": _counts("2023-09:7, 2023-11:23, 2023-12:10, 2024-01:11, 2024-02:8, 2025-03:16, 2025-04:14, 2025-06:23, 2025-08:27, 2025-12:24"),
    "pangasinan": _counts("2023-09:27, 2023-11:16, 2023-12:47, 2024-01:26, 2024-02:21, 2025-03:22, 2025-04:50, 2025-06:35, 2025-08:47, 2025-12:45"),
}


class FakeCursor:
    """Answers the two pool-count queries from the fixtures; records every statement it is given."""

    def __init__(self):
        self.statements, self._result = [], []

    def execute(self, sql, args=None):
        self.statements.append(sql)
        pool = RETURNS if "salesreturn_fact_real" in sql else PURCHASES if "purchase_fact_real" in sql else None
        self._result = sorted(pool[args[0]].items()) if pool and args else [(0,)]

    def fetchall(self):
        return self._result

    def writes(self):
        return [s for s in self.statements if s.lstrip().split()[0].upper() in {"INSERT", "DELETE", "UPDATE", "CREATE", "DROP", "ALTER", "TRUNCATE"}]


def test_the_plan_covers_exactly_the_dec29_months():
    plan = plan_dec29_gaps(RETURNS, PURCHASES)
    assert {(t, m) for t, m, _ in plan} == {("salesreturn_fact", m) for m in DEC29_RETURNS} | {("purchase_fact", "2025-09")}
    assert len(DEC29_RETURNS) == 19 and DEC29_PURCHASES == ["2025-09"]
    assert not any(m == "2026-09" for _, m, _ in plan)          # not yet delivered, never generated
    assert {s for _, _, s in plan} == set(SITES)


def test_dry_run_counts_and_writes_nothing():
    cur = FakeCursor()
    out = dm_dec29_gaps(cur)                                    # dry_run is the default
    assert out == {"dry_run": True, "rows": {"salesreturn_fact": 1540, "purchase_fact": 34},
                   "months": {"salesreturn_fact": 19, "purchase_fact": 1}}
    plan = plan_dec29_gaps(RETURNS, PURCHASES)
    assert sum(n for (t, _, s), n in plan.items() if t == "salesreturn_fact" and s == "ilocos") == 645
    assert sum(n for (t, _, s), n in plan.items() if t == "salesreturn_fact" and s == "pangasinan") == 895
    assert plan[("purchase_fact", "2025-09", "ilocos")] == 7 and plan[("purchase_fact", "2025-09", "pangasinan")] == 27
    assert cur.writes() == []


def test_a_fill_is_refused_without_the_flag():
    cur = FakeCursor()
    with pytest.raises(RuntimeError, match="--fill-dec29-gaps"):
        dm_dec29_gaps(cur, allow=False, dry_run=False)
    assert cur.writes() == []


def test_the_refactor_keeps_the_existing_blocks_draws():
    """dm_returns (2021-22) and dm_purchases_forward (2026-04..08) wrote 1,971 and 312 rows on 2026-09-28 through the same
    per-month draw the DEC-29 plan uses."""
    def total(counts, tag, months):
        return sum(int(rng(tag, m, s).choice([counts[s][p] for p in nearest_moy(m, sorted(counts[s]))])) for s in SITES for m in months)
    assert total(RETURNS, "dm_returns", MONTHS_2122) == 1971
    assert total(PURCHASES, "dm_purchases", FORWARD) == 312
