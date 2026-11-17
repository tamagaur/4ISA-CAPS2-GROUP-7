# Where every number comes from: the provenance ledger

> Figures as of 2026-11-17: the counts below are the sweep of that day (`python -m scripts.figure_provenance --verify`, kelvin-be after
> 5701a5d). The ledger is `docs/FIGURE_PROVENANCE.json`; the check is `scripts/figure_provenance.py`, run by `scripts/check.sh` in both
> modes (no database). Its live figures are read by `tests/invariants/test_g_constants_match_live.py`.

## What the check holds

Every tracked file has a class, the first rule of the ledger that matches it. A file no rule matches fails the check.

| Class | What it is | What a figure in it must be |
|---|---|---|
| current | states the present: CLAUDE.md, STATE.md, ARCHITECTURE.md, KNOWN_ISSUES.md, README.md, the runbooks, the deploy sheet | **dated** (an ISO date on its line, in its paragraph or table row, or in a heading above it, or a `Figures as of <date>` line at the head of the file), **checked** (a `checked` entry names the test that reads it against live, or the constant it must equal), or marked `UNTRACEABLE (settle: ...)` in place |
| code | source code: comments, docstrings, and prose strings (text on a page, messages) | the same, plus: a **definition** (the same literal is in the file's code, or is a named UPPER_CASE setting in analytics/, backend/ or scripts/), an **example** (an `e.g.` line), or a ledger `not_claims` entry (example of a format, definition, identifier, a manuscript sentence quoted to place a citation; each with its note) |
| record | a report of a run, an experiment, a rehearsal or an audit | a Markdown record carries `Dated record (<ISO date>` in its first 8 lines; a CSV or JSON record is dated by its ledger rule |
| generated | written by a script | the rule names the generator and a verifier that check.sh runs (or says why there is none) |
| data | data folders, configuration maps, assets, lock files | traced to the commit that set them |
| fixture | tests | inputs and expectations of synthetic cases |
| manuscript | the chapter drafts and edit lists | counted, not checked (out of scope: knowingly stale) |

**Adding a figure to a current file or a code comment.** Date it in the sentence; or, if live can give it, add a test to
`tests/invariants/test_g_constants_match_live.py` and a `checked` entry naming it; or, for a stated setting, a `checked` entry with
`params` (compared with the constant in the code, no database). If nobody can say where it came from, write
`UNTRACEABLE (settle: <what would settle it>)` beside it. A file the month-load attestation hashes (CLAUDE.md, "The gate") is dated
from the ledger (`dated`, with the commit that wrote the line), because editing even a comment there switches live loading off until
re-rehearsed.

**What it does not prove** (limits, stated):
- "Dated" is mechanical: a present-tense figure on a line that also carries a date passes. A dated figure is a record; the check does
  not say it is still true.
- Integers under 10 are not tracked.
- A figure equal to a named setting anywhere in the code passes as a definition, even where the sentence means something else.
- Records are labelled as a whole, not traced figure by figure; data files are traced only to their commit.
- `scripts.manuscript_figures --verify` compares the committed FIGURES.md and tables file to what the code writes from live; it does
  not compare the PNGs (it draws them at a lower resolution).

## The sweep of 2026-11-17

Figures found by the scanner, by status (one figure per number token): record 38,901; fixture 4,529; dated 3,356; data 1,554;
manuscript 1,030; generated 603; definition 558; example 106; checked 67; manuscript-quote 22; identifier 10; untraceable 2 (on 1 line).
2,383 tracked files. The full list, one row per figure: `python -m scripts.figure_provenance --inventory` (writes to the git-ignored
`local/`; it is not committed because it restates every number of the repository).

### The three named in the brief

| Figure | Where | Outcome | What it was |
|---|---|---|---|
| "median product WAPE about 40%" | reports/figures/FIGURES.md, caption of Figure 4.2.26 (a literal in scripts/manuscript_figures.py) | **UNTRACEABLE, replaced** | No stored Tier A run gives about 40% on Mar 2025-Feb 2026 (runs 3-21 read on live: 27.95% to 35.49%; only the Tier B and C counterfactual runs exceed 40%). The caption now computes it from the rows drawn: 33.2% over 222 products (run 21). |
| "35.49%" | the same file, caption of Figure 4.2.27 | **DATED, replaced** | Stored mart.forecast_run 11's median product WAPE on that window (Σ\|forecast − net sold\| ÷ Σ\|net sold\| per product, 222 products). The figures read run 21 since 2026-11-17. Now computed: 33.2%. |
| baselines 32.00% / 36.43% | docs/CHAPTER4_MOVED_FIGURES_2026-11-11.md, the launch-handover test | **CURRENT under its own rule, now named** | The card's rows (run 21) scored Σ\|forecast − actual\| ÷ Σ\|actual\| by the git-ignored `local/q9.py`: 32.00% / 36.43% / 27.25% on live. The card's two rules give 32.04 / 36.53 / 27.25 (before 2026-11-17) and 31.95 / 36.33 / 27.24 (since). |
| backtest MASE 0.871 vs 0.901, earlier window | STATE.md, reports/CALENDAR_GRAIN_2026-11-12.md, docs/CHAPTER4_MOVED_FIGURES, the error hunt | **two definitions; 0.871 CURRENT, 0.901 DATED with a 0.003 gap unresolved** | One forecast (stored run 16), two MASE scales: fixed per product on 2023-01..2025-08, which includes the earlier window itself (error hunt; 270 products; 0.871 exactly on live), and the change before the window (calendar grain; 188 products; 0.904 on live, against 0.901 as written). Run 21 under the second gives 0.869 exactly, as written. Settled by re-running the calendar-grain scoring frames of 2026-11-12, which are not in the repository. |

### Other figures that were wrong, now corrected

| Where | Was | Now |
|---|---|---|
| docs/DEMO_DATA.md, the Unilever demonstration run | run 8: 24,906 real_copy, 12,816 backcast | runs 10, 11 and 12 on live, 4,786 and 1,584 each (live holds no run 8); held to live by a test |
| docs/MONTHLY_LOAD_PROCEDURE.md | "The 51 pinned figures read frozen rows and do not move" | compared to live by snapshot_published_figures --verify since 2026-11-16; a real month moves their MASE figures |
| docs/RENDER_SETUP.md | "the month-load attestation hashes 21 files" | 98 files since 2026-11-17 (the computed import closure) |
| README.md | `check.sh --full` "about 10 min" | about 12 min (719 s and 745 s on 2026-11-17) |
| scripts/manuscript_figures.py, Figure 4.2.30's axis (fig q) | "Cumulative share of the ₱38.2 M" | computed: ₱43.8 M on live (₱38.2 M was the value published on 2026-10-24) |
| scripts/manuscript_figures.py, the suggested sentence for Figure 4.2.29 (fig p) | 12,242,746 / 4,847,983 / 2,669,295 pieces; 749 of 4,370 (17.14%); ₱38,187,551 | computed from the rows drawn: 9,389,241 / 5,083,650 / 3,096,724; 852 of 4,370 (19.50%); ₱43,767,343 |
| scripts/manuscript_figures.py, sources of figures h-k, p, q | "frozen as-served rows" / "frozen ... csv" (they read live since 2026-11-17) | the live tables they read |
| scripts/manuscript_figures.py, the monthly figures' scoring | "scored as GET /dashboard forecast_accuracy scores them" (the card changed its rule on 2026-11-17) | "scored on net pieces sold, the dashboard card's rule until 2026-11-17" |
| docs/MANUSCRIPT_HELD_CHECKS.json, basis of four held checks (p, q) | "pinned", "STATE.md headline", "docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.md": none holds the value | "manuscript as published 2026-10-24 (live and the pin moved since)"; values and counts unchanged (265 / 193 / 72) |
| reports/figures/FIGURES.md | regenerated on 2026-11-13, before figures h-k read live | regenerated from live; `scripts.manuscript_figures --verify` now fails when it or the tables file is not what the code writes |

### Labelled as dated

- 106 Markdown records gained the `Dated record (<date>)` label (reports/, profiling/, scratch/, analytics/docs/, and the dated docs:
  CHAPTER4_MOVED_FIGURES, CALENDAR_SELECTION and its protocol, EVALUATION_METRICS_INVENTORY, COVERAGE_MATRIX, CHALLENGER_FORECAST,
  TEST_PLAN, MONTHLY_BATCH_REVIEW). The date is the file name's, the folder's, the title's, or the first commit's, with the last edit
  when later.
- reports/BASELINE_FORECAST_RUN.md is dated from the ledger: it is the forecast report of 2026-10-21; the live forecast was rewritten on
  2026-11-13 without rewriting it.
- docs/LOCAL_DEMO_RUNBOOK.md: `Figures as of 2026-11-05` (every figure in it is the seed backup's or the practice walkthroughs').
- 69 code comment and docstring lines: dated in place (36) or from the ledger (33 entries, files in the month-load closure), each with the
  date of the commit that wrote the line.

### Read against live now (CURRENT), by test

CLAUDE.md: the numeric gate, the Tier A count, the calendar factor range, the blank captures (71 rows, 63 SKUs; 59 of the 63) and the
Unilever gap months (4,473 across 714 of 1,807). docs/DEMO_DATA.md: the gap months, both demonstration rows, the generated stock
(4,150 rows, 82 categories, run 7) and the demonstration order plan. docs/DATA_GOVERNANCE.md: the seven inventory counts. The runbooks'
"51 pinned figures". scripts/chapter_figures.py's "326,491 before rounding". scripts/accuracy_as_served.py's run 5 median (38.72%).
Compared with the constant in the code: the LP weights (CLAUDE.md, ARCHITECTURE.md, README.md), the sign-in limits, the JWT minimum
length, the month-load step timeout, the Python version.

### UNTRACEABLE (listed, not passed)

| Figure | Where | What would settle it |
|---|---|---|
| a personal-data breach is reported "within 72 hours" | docs/DATA_GOVERNANCE.md, item 4 | the National Privacy Commission issuance and section that sets it; the file names none and none was read |
