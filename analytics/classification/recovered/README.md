# Recovered producer artifacts — DO NOT RUN

These two files are **evidence, not pipeline code.** They are the provenance for
the 25,437 `method='t3m'` rows live in `public.abc_classification`
(`run_id='phase2_unilever_2026-09-17_v2'`), and they exist nowhere else.

## What they are

On 2026-09-17 the Phase 2 single-vs-t3m comparison was built and written to
`public` by two ad-hoc scripts written into a Claude Code session scratchpad.
They were run once and never committed. The scratchpad directory has since been
emptied, so by 2026-09-20 the only surviving copy was inside the session
transcript `1edc0003-d626-459f-ad09-0ed535f48530.jsonl`. They were extracted
from that transcript and stored here verbatim.

| File | sha256 (first 32) | Bytes | What it did |
|---|---|---|---|
| `rebuild_abc_phase2_v2.py` | `29a0b6ac5b6bbb67a9ed614c85385fad` | 3906 | Built `ssm_abc_phase2.abc_scratch_v2` and `..._v2_repeat` (the determinism check) |
| `apply_and_write.py` | `7f1f9cac1734a2a4fae76c7a61c41174` | 2075 | Backed up `public`, applied migration 0017, inserted 23,223 `single` + 25,437 `t3m` rows |

Content is byte-exact as recovered. Do not edit them — if they need annotating,
annotate here instead, so the hashes above stay meaningful.

## Why they must not be run

- `apply_and_write.py` **writes directly to `public.abc_classification`.**
- `rebuild_abc_phase2_v2.py` opens with `DROP TABLE IF EXISTS` against
  `ssm_abc_phase2.abc_scratch_v2` and `..._v2_repeat` — which are currently the
  **only surviving intermediates** of the live t3m rows, carrying the
  `total_revenue`, `excluded_null`, `insufficient_history` and `inactive`
  columns that were dropped on the way into `public`. Running it would destroy
  the evidence it documents.
- Both hardcode an absolute `.env` path and connect on `SUPABASE_DIRECT_URL`.

## What replaced them

The t3m computation is now committed, as
`_fetch_unilever_sku_revenue_t3m()` in
[../orchestrate_abc.py](../orchestrate_abc.py), reachable via
`--method t3m` with a required `--schema`. It is a transcription of the
`single` / `t3m_win` / `t3m` CTEs below, and it reproduces all 25,437 live rows
exactly — verified 2026-09-20 by rebuilding into a scratch schema and diffing
`EXCEPT` both ways.

The load-bearing logic, for reference:

```sql
WINDOW w AS (PARTITION BY product_key ORDER BY period_date
             ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
CASE WHEN window_rows = 3 AND NOT any_excluded_null THEN window_sum END AS revenue
```

Note that the SQL reimplements the tier cutoffs (0.80 / 0.95), the
`(revenue DESC, product_key ASC)` tiebreak and the 0.02 boundary margin inline
rather than calling `classify_abc()`. The committed replacement calls
`classify_abc()` instead, which is why its output is identical — the constants
agree with [../abc.py](../abc.py).

## The inconsistency this source explains

`t3m` was computed as a window over **already-clamped single-month** revenues,
so a negative `net_amount` is zeroed per month before summing. `single` clamps
the aggregated total instead
([../orchestrate_abc.py `_split_negative_revenue`](../orchestrate_abc.py)). With
a one-month window the two coincide; over three months they do not.

This was a consequence of the construction, not a methodology decision. It is
documented in full at the top of `_fetch_unilever_sku_revenue_t3m()` and is a
disclosure for the adviser gate, not something reconciled here.
