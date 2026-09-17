# ABC Phase 2 — Unilever, single vs t3m (2026-09-17)

Scope: Unilever only, scratch schema (`ssm_abc_phase2.abc_scratch`), no public writes.
Del Monte skipped — no SKU-level sales source, pending adviser ruling.

Existing cutoffs used unchanged (Tier A ≤0.80, B ≤0.95, else C — [abc.py:54-55](analytics/classification/abc.py#L54)).
`run_id = 'phase2_unilever_2026-09-17'`.

## Pre-step: fetch defect fix + verification

`orchestrate_abc.py` was reading base tables (`unilever_sku_demand_fact`, `sellout_fact`) with no
`is_demo` filter (Hard Rule 1 violation). Fixed to read `unilever_sku_demand_fact_real` /
`sellout_fact_real` ([orchestrate_abc.py:80](analytics/classification/orchestrate_abc.py#L80),
[:136](analytics/classification/orchestrate_abc.py#L136)).

Verified impact on stored output before rebuilding:

| Principal | Periods checked | Periods with real+demo mixed in same period | Stored `abc_classification` rows affected |
|---|---|---|---|
| Unilever | 38 (all stored periods) | 0 | 0 — real and demo months are cleanly separated (2023-01–2026-02 real, no overlap) |
| Del Monte | 68 distinct `sellout_fact` periods | 6 (2025-03, 04, 06, 08, 09, 12) | 0 rows stored for delmonte in `abc_classification` — ABC has never been run for this principal, so the risk was latent, not realized |

No downstream rework needed. Del Monte's 6 mixed periods are logged in Open Items below.

## 1. Tier A/B/C counts per period, both methods

79,724 rows per method (2,098 Unilever SKUs × 38 periods). Full table:

| Period | Method | Tier A | Tier B | Tier C | Excluded |
|---|---|---|---|---|---|
| 2023-01 | single | 126 | 150 | 1822 | 0 |
| 2023-01 | t3m | 0 | 0 | 0 | 2098 (insufficient history) |
| 2023-02 | single | 125 | 154 | 1819 | 0 |
| 2023-02 | t3m | 0 | 0 | 0 | 2098 (insufficient history) |
| 2023-03 | single | 109 | 146 | 1843 | 0 |
| 2023-03 | t3m | 124 | 159 | 1815 | 0 |
| 2023-04 | single | 123 | 147 | 1828 | 0 |
| 2023-04 | t3m | 122 | 157 | 1819 | 0 |
| 2023-05 | single | 118 | 156 | 1824 | 0 |
| 2023-05 | t3m | 125 | 168 | 1805 | 0 |
| 2023-06 | single | 118 | 145 | 1835 | 0 |
| 2023-06 | t3m | 131 | 169 | 1798 | 0 |
| 2023-07 | single | 139 | 150 | 1809 | 0 |
| 2023-07 | t3m | 135 | 165 | 1798 | 0 |
| 2023-08 | single | 128 | 157 | 1813 | 0 |
| 2023-08 | t3m | 140 | 162 | 1796 | 0 |
| 2023-09 | single | 113 | 154 | 1830 | 1 (null net_amount, sku 859) |
| 2023-09 | t3m | 134 | 167 | 1796 | 1 |
| 2023-10 | single | 115 | 153 | 1830 | 0 |
| 2023-10 | t3m | 126 | 165 | 1806 | 1 (window includes 2023-09 null) |
| 2023-11 | single | 124 | 148 | 1826 | 0 |
| 2023-11 | t3m | 123 | 159 | 1815 | 1 (window includes 2023-09 null) |
| 2023-12 | single | 96 | 136 | 1866 | 0 |
| 2023-12 | t3m | 120 | 154 | 1824 | 0 |
| 2024-01 | single | 125 | 155 | 1818 | 0 |
| 2024-01 | t3m | 123 | 157 | 1818 | 0 |
| 2024-02 | single | 117 | 162 | 1819 | 0 |
| 2024-02 | t3m | 120 | 161 | 1817 | 0 |
| 2024-03 | single | 104 | 151 | 1843 | 0 |
| 2024-03 | t3m | 122 | 164 | 1812 | 0 |
| 2024-04 | single | 131 | 151 | 1816 | 0 |
| 2024-04 | t3m | 130 | 170 | 1798 | 0 |
| 2024-05 | single | 128 | 160 | 1810 | 0 |
| 2024-05 | t3m | 133 | 169 | 1796 | 0 |
| 2024-06 | single | 116 | 179 | 1803 | 0 |
| 2024-06 | t3m | 136 | 175 | 1787 | 0 |
| 2024-07 | single | 126 | 172 | 1800 | 0 |
| 2024-07 | t3m | 136 | 203 | 1759 | 0 |
| 2024-08 | single | 124 | 165 | 1809 | 0 |
| 2024-08 | t3m | 137 | 198 | 1763 | 0 |
| 2024-09 | single | 112 | 173 | 1813 | 0 |
| 2024-09 | t3m | 131 | 184 | 1783 | 0 |
| 2024-10 | single | 120 | 160 | 1818 | 0 |
| 2024-10 | t3m | 127 | 174 | 1797 | 0 |
| 2024-11 | single | 142 | 179 | 1777 | 0 |
| 2024-11 | t3m | 133 | 186 | 1779 | 0 |
| 2024-12 | single | 120 | 162 | 1815 | 1 (null net_amount, sku 108) |
| 2024-12 | t3m | 137 | 181 | 1779 | 1 |
| 2025-01 | single | 140 | 171 | 1787 | 0 |
| 2025-01 | t3m | 144 | 185 | 1768 | 1 (window includes 2024-12 null) |
| 2025-02 | single | 123 | 174 | 1801 | 0 |
| 2025-02 | t3m | 136 | 183 | 1778 | 1 (window includes 2024-12 null) |
| 2025-03 | single | 129 | 172 | 1797 | 0 |
| 2025-03 | t3m | 138 | 185 | 1775 | 0 |
| 2025-04 | single | 129 | 168 | 1801 | 0 |
| 2025-04 | t3m | 133 | 180 | 1785 | 0 |
| 2025-05 | single | 132 | 197 | 1769 | 0 |
| 2025-05 | t3m | 137 | 188 | 1773 | 0 |
| 2025-06 | single | 145 | 178 | 1775 | 0 |
| 2025-06 | t3m | 146 | 191 | 1761 | 0 |
| 2025-07 | single | 141 | 193 | 1764 | 0 |
| 2025-07 | t3m | 152 | 203 | 1743 | 0 |
| 2025-08 | single | 145 | 182 | 1771 | 0 |
| 2025-08 | t3m | 155 | 205 | 1738 | 0 |
| 2025-09 | single | 144 | 214 | 1740 | 0 |
| 2025-09 | t3m | 158 | 220 | 1720 | 0 |
| 2025-10 | single | 138 | 195 | 1765 | 0 |
| 2025-10 | t3m | 154 | 218 | 1726 | 0 |
| 2025-11 | single | 146 | 187 | 1765 | 0 |
| 2025-11 | t3m | 153 | 217 | 1728 | 0 |
| **2025-12** | single | 89 | 150 | 1859 | 0 |
| **2025-12** | t3m | 139 | 201 | 1758 | 0 |
| 2026-01 | single | 149 | 209 | 1740 | 0 |
| 2026-01 | t3m | 149 | 210 | 1739 | 0 |
| 2026-02 | single | 132 | 194 | 1772 | 0 |
| 2026-02 | t3m | 143 | 215 | 1740 | 0 |

**2025-12 flagged as documented anomaly** (not excluded): single Tier A drops to 89 (period min) while t3m holds at 139 — the trailing-3-month basis smooths the anomaly out, single does not.

## 2. Tier A count min/max/median per method

| Method | Min | Max | Median |
|---|---|---|---|
| single | 89 | 149 | 125.5 |
| t3m | 0 (2023-01/02, insufficient history) | 158 | 134.5 |

## 3. Pareto band pass/fail per period per method (summary)

| Method | Pass (75–85%) | Fail |
|---|---|---|
| single | 38 / 38 | 0 |
| t3m | 36 / 36 evaluable (2023-01/02 excluded, no Tier A) | 0 |

**Note:** this check is close to tautological — Tier A's cumulative share is capped at ≤0.80 by the same cutoff used to assign it, so it lands near 0.80 by construction whenever SKU granularity is fine enough (2,098 SKUs here). It confirms no single SKU's revenue share is large enough to jump the cutoff, not an independent validation of the 80% choice.

## 4. Core vs pool counts (membership frequency, ≥50% of present periods in Tier A = core)

| Method | Core | Pool | Never present |
|---|---|---|---|
| single | 95 | 2003 | 0 |
| t3m | 113 | 1985 | 0 |

## 5. 2026-02 Tier A cohort: single vs t3m

| Single Tier A | t3m Tier A | Overlap | Only single | Only t3m |
|---|---|---|---|---|
| 132 | 143 | 119 | 13 | 24 |

Only-single product_keys: 150, 151, 630, 634, 674, 833, 1037, 1201, 1280, 1547, 1791, 1792, 1801
Only-t3m product_keys: 21, 67, 132, 195, 264, 289, 347, 515, 525, 526, 534, 588, 589, 614, 728, 755, 834, 836, 856, 877, 986, 1005, 1036, 1318

## 6. Expected public changes

| Change | Detail |
|---|---|
| `abc_classification` rows added/replaced | **0** this session — Step 2 output lives only in `ssm_abc_phase2.abc_scratch` (scratch schema), no public write made or proposed |
| Code fix already applied (not scratch) | `orchestrate_abc.py` fetch functions repointed to `_Real` views — this is a real code change, committed to working tree, not yet pushed (no commit made per "no commits until Yuan says complete") |
| Migration needed for method/run_id on public `abc_classification` | **Migration 0017** (next free number — 0001–0016 exist, 0002 is duplicated by two files, 0017 is clean) — not written yet, per your instruction to confirm first |

## 7. Open items (scope-locked, not investigated)

| Item | Note |
|---|---|
| 4 null net_amount rows (not 2 as originally assumed) | 2023-09/sku 859 (real), 2024-12/sku 108 (real), 2022-09/sku 108 (demo), 2026-03/sku 108 (demo) — excluded from ABC input in both methods |
| `abc_classification` has no `method`/`run_id` column | Blocks storing this comparison publicly; migration 0017 proposed, not written |
| net_amount is gross, not net of returns | `SalesReturn_Fact` never subtracted at any point in the ETL; source-column figure only — record as a stated limitation, not a bug |
| sellout_fact has 6 periods (2025-03,04,06,08,09,12) mixing real+demo rows | Del Monte only; 0 stored ABC rows affected since delmonte was never run |
| 1,681 negative net_amount rows in `unilever_sku_demand_fact_real` | Clamped to 0.0 per existing `_split_negative_revenue()` logic (unchanged), same treatment as deployed pipeline — root cause of negatives not investigated (out of ABC-input scope) |
| Pareto band check is near-tautological given fine SKU granularity | See note under table 3; not a defect, just a limited-power check |
| net_amount is gross, not net of returns | Manuscript-level limitation: `SalesReturn_Fact` is never subtracted anywhere in the ETL; record in Ch.4 as a stated limitation, not a bug to fix |
| 1,681 negative net_amount rows in `unilever_sku_demand_fact_real` | Clamped to 0.0 by `_split_negative_revenue()` (unchanged logic), then excluded as "inactive" by the new zero-revenue split — root cause not investigated, out of ABC-input scope |
| Migration file `0002` is duplicated (`0002_add_boundary_flag.sql` and `0002_add_sku_management_fields.sql`) | Pre-existing numbering collision in `analytics/db/migrations/`, unrelated to this session's 0017 — flagged for whoever owns migration hygiene next |
| `sellout_fact` has 6 periods (2025-03,04,06,08,09,12) mixing real+demo rows | Del Monte only; 0 stored ABC rows affected since delmonte was never run — see Pre-step section above |

## Post-approval update (2026-09-17): deployed-code fixes, verification, and public write

Two deployed-code fixes applied (not just scratch) before the public write:

1. **"Present" redefinition** — `orchestrate_abc.py` now excludes zero-revenue product-periods (`_split_zero_revenue()`) from `classify_abc()`'s input entirely instead of zero-filling them into Tier C. A negative row clamped to 0.0 by the existing `_split_negative_revenue()` flows into this same exclusion. No tier is written for these rows (absence = not classified that period, not a fabricated tier).
2. **Deterministic tiebreak** — `classify_abc()` now sorts `["total_revenue", "sku_id"]` descending/ascending instead of revenue-only, removing the DB-return-order dependency on ties ([abc.py:110](analytics/classification/abc.py#L110)).

Also fixed: a pre-existing stale test assertion in `test_orchestrate_abc.py` (`test_negative_revenue_split_out_not_coerced` expected rows to be dropped; the function has always clamped to 0.0 per its own docstring) — confirmed via `git stash` that this failure pre-dates this session, unrelated to today's changes.

### Checks (all against a from-scratch rebuild using the fixed deployed-code logic)

| Check | Result | Verdict |
|---|---|---|
| 2026-02 single Tier A count | 132 (unchanged from pre-fix report) | PASS |
| Tier A counts per period vs this report | max absolute delta = 0 across all 38×2 method/period combinations | PASS |
| Two identical rebuilds produce identical output | 0 rows differ either direction (`EXCEPT` both ways) | PASS |
| Tests pass | 158/158 (`tests/`, excluding `tests/backend/*` — 4 collection errors confirmed pre-existing via `git stash`, a FastAPI/Router version mismatch unrelated to ABC) | PASS |

### Core/pool, recomputed with corrected "present" denominator (present = net_amount > 0 that period)

| Method | Core (≥50% of present periods in Tier A) | Pool (<50%) | Never present |
|---|---|---|---|
| single | 255 | 1276 | 567 |
| t3m | 246 | 1285 | 567 |

For comparison, the earlier report's core/pool used "any period with a tier" (including zero-filled Tier C) as the denominator: single 95/2003, t3m 113/1985 — the corrected denominator roughly triples the core count because most SKUs are only genuinely "present" a fraction of the 38 months, not every month.

### Earlier definition, for comparison (absolute Tier A period counts, not frequency)

| Method | Tier A in all 38 periods | Tier A ≥30 periods | Churn pool (≥1, <30) |
|---|---|---|---|
| single | 21 | 49 | 366 |
| t3m | 0 (impossible — 2023-01/02 always insufficient history) | 59 | 292 |

### Public write

- Backup: `ssm_abc_phase2.abc_classification_backup_20260917` (23,223 rows, full pre-write snapshot of `public.abc_classification`)
- Migration 0017 applied: `method`, `run_id` columns + widened unique constraint `(product_key, classification_period, method)`
- Written to `public.abc_classification`: 23,223 `single` rows (exact match to the pre-existing row count — confirms Tier A/B/C composition was unaffected by the fixes, only the `boundary_flag`/`revenue_share` precision and now-present `method`/`run_id` columns changed) + 25,437 new `t3m` rows, `run_id = 'phase2_unilever_2026-09-17_v2'`
