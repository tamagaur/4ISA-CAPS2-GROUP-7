# Del Monte Demo Data — Generation Spec

**Status: spec only. No data has been generated.** Audrey and Thea should be able to build the generator entirely from this document — every number below was re-derived from the real files today, not carried over from memory of earlier conversation.

**Scope discipline, stated once, binding for the whole document:** this spec fills in **missing months of file shapes that already exist for real**. It never adds a column, field, or grain that no real Del Monte file has. See "Out of scope" below — this is not a suggestion, it's a hard boundary tied to DEC-02/DEC-03.

---

## 0. Scope

**In scope — real range:** January 2023 – December 2025 (36 months), Del Monte only. Verified this session: zero Del Monte files/folders exist for 2021, 2022, or Jan–Mar 2026, anywhere under `data/raw/`, including a check for stray files outside the `MONTHLY REPORT`/`DAILY REPORT` folder convention. Del Monte's corpus genuinely begins in January 2023.

**Out of scope — do not generate, ever, for any family:**
- Product/SKU/category on **Sales Register**, **Purchases**, or **Sales Return**. Confirmed across all real files, all vocab eras: these are whole-invoice records with no item-level breakdown. There is no column to fill in — the concept doesn't exist in the source.
- Units/quantity on **RMR GS & BO**. Confirmed: 11 real columns, all identity/date or peso figures, no quantity column in any real file, any era.
- `units_received` on **Purchase Order**. Not a real column — Purchase Order's real money columns are `Untaxed Amount`/`Net Amount`/`Balance`, same shape as Sales Register.

Adding any of these would demonstrate a capability the real system can never have (DEC-02: no `product_key` on transaction-mart facts; DEC-03: Del Monte forecasts at category grain via Sell Out only, never invoice allocation). If a future contributor is tempted to add one "just for the demo," point them at this paragraph first.

**Unilever: do not touch.** Unilever's real range (Jan 2021 – Mar 2026, verified this session) has no gaps that matter for this exercise — nothing to generate.

---

## STEP 0 — Verification (re-derived today, not assumed)

Re-ran against the real corpus: for the 5 families with an Extract driver, queried `staging/<family>/*.parquet`'s real `_period`/`_principal` columns directly (not the raw folder listing). For **Sales Return**, which has no Extract driver at all (see §1.3), counted real months from the raw files' folder names directly, cross-checked against `infer_doc_type()`.

| Family | Months present | Months missing | Your stated count |
|---|---|---|---|
| Sell Out | 17 | **19** | Confirmed — 19 is correct |
| Sales Register | 20 | 16 | (not stated) |
| Purchase Order | 11 | 25 | (not stated) |
| Sales Return | 18 (19 files, 1 duplicate) | 18 | (not stated) |
| Inventory Sign Off | 17 | 19 | (not stated) |
| RMR GS & BO | 2 | 34 | (not stated) |

No disagreements with anything you stated. One thing worth flagging even though you didn't ask: **Sales Return has zero Extract driver.** `infer_doc_type()` correctly tags all 19 files `doc_type="sales_return"`, but none of the 7 `FAMILY_PARSERS` in `driver.py` select that doc_type — it's a genuine 8th family that's never been staged, ever. This matters for this spec because there's no `staging/sales_return/*.parquet` to validate a generated file against structurally — Audrey/Thea are working blind on this one family until that driver exists. Flagged again in §1.3.

**Missing-month lists** (the actual generation targets for §1):

- **Sell Out:** 2023-07, 2023-10, 2023-12 · 2024-03–12 (10 months) · 2025-01, 02, 05, 07, 10, 11
- **Sales Register:** 2023-07, 10 · 2024-03–12 · 2025-01, 02, 05, 07
- **Purchase Order:** 2023-01–08, 10 (9 months) · 2024-03–12 · 2025-01, 02, 05, 07, 10, 11
- **Sales Return:** 2023-07, 10 · 2024-03–12 · 2025-01, 02, 05, 07, 10, 11
- **Inventory Sign Off:** 2023-07, 10, 11 · 2024-03–12 · 2025-01, 02, 05, 07, 10, 11
- **RMR GS & BO:** everything except 2025-10 and 2025-11 — **but see §1.6, this family needs 0 generated months, not 34.**

---

## STEP 1 — Per-family spec

### 1.1 Sell Out

**Generate:** the 19 missing months listed above.

**Real files checked:** all 17 real Sell Out files, full read.

**Columns the pipeline consumes** (raw header names, per file — `apply_column_map` renames these; do not add anything else):
- `category_path` (raw column has **no header text** — it's the leftmost column, header row blank) — string
- `Total Without Tax` (2023–2024 files) / labeled differently in the one Aug-2023 file, see quirk below — decimal, peso
- `Product Quantity` — decimal
- Plus `is_demo = true` (new, generated rows only)

**Known pipeline gap, disclose, don't silently fix:** `sell_out.yaml`'s `category_path` mapping points at a placeholder `__col0__` that doesn't match the real staged column in either era. Transform currently reports `unmapped_canonical: ['category_path']` against real data. Generated files should use the **real** raw shape (category name in column A, no header text) so that whenever this gap gets fixed, generated files parse exactly like real ones — don't design the demo file around a column-map bug that's supposed to go away.

**Real row counts per sheet** (34 real sheets, both eras combined):
- Overall: min 5, max 77, median 65.5
- Region breakdown: `ilocos` n=17, min 5 / max 69 / median 64; `pangasinan` n=7 (see quirk below), min 65 / max 75 / median 71

**Regions are separate sheets, 2 per file** — but their content differs by **era**, not just region:

**Quirk — sheet-name region tagging.** Real sheet names: `ILOCOS SELL OUT` (or `ILOCOS_SELL OUT` in later files) parses to region=ilocos correctly. But `PANG_SELL OUT` (the abbreviated form used from Nov 2023 onward) does **not** match the region-detection pattern — it lands as `_region="unknown"` in real staged data (10 of 34 real sheets). Generated files should use `PANG_SELL OUT` for months where that's what the real neighboring months use (see the file-by-file sheet-name table your generator should match against real filenames — don't invent a cleaner name), and this is a real pipeline gap worth fixing, not something to work around in the generated data.

**Quirk — trailing space.** Some real sheet names carry a trailing space (`PANGASINAN SELL OUT `). Preserve exactly per era; don't strip it.

**Quirk — column swap in the single Aug-2023 file.** `DELMONTE_SELL OUT_PANGASINAN & ILOCOS _AUGUST 2023.xlsx` has its two value columns in the **opposite order** from every other file (`Product Quantity` in column B, `Total With Tax` — tax-**inclusive**, not the usual tax-exclusive `Total Without Tax` — in column C). This is real, confirmed by opening the file. Not relevant to which months to generate (Aug 2023 already has real data), but relevant if the generator's column-position logic gets reused for QA — don't assume column position is stable across all real files.

**Real anomalies to preserve:**
- **Blank/unlabeled category rows.** Every one of the 11 real fine-grained-era files has several trailing rows where the category cell is a literal blank that the reader surfaces as `False`, `False (2)` … `False (12)`. These are **not negligible** — `False (6)` alone is the 6th-largest "category" by revenue (5.47% of the fine-grained-era total). Real, keep them as blank/unlabeled rows in generated months, don't invent a name for them, don't drop them.
- **Negative rows exist** (2 real instances found: `/SWEET SPICY/NPI` and `/GOURMET SPAG SAUCE/PROMO`, both small, both real return/adjustment entries). Preserve the possibility, don't clamp to zero.
- **One real content/filename mismatch** (informational, not a generation target): `2025 MARCH SELL OUT.xlsx`'s internal period cell reads Feb 2025, not March. Real files aren't perfectly self-consistent — don't over-engineer generated files to be more internally consistent than the real ones.

**No date column finer than month** in any real sheet, any era — confirmed exhaustively earlier this session. Generated files: one period cell, monthly grain, same as real.

---

### 1.2 Sales Register

**Generate:** the 16 missing months listed above.

**Columns the pipeline consumes** (era A/2023–2024 shape — reuse for generated months since the missing months fall in this era):
`Invoice Date, Salesman, Town Display, Branch Code, Customer Name, Invoice Num, REFNBR, Untaxed Amount, Discount Rate, Discount Amount (or Dscount Amount, see quirk), Tax, Net Amount, Balance, Posted` — plus `is_demo = true`.

**Real row counts per sheet** (127 real sheets): overall min 12, max 850, median 41. By region: `ilocos` n=58, min 12/max 405/median 30.5; `pangasinan` n=66, min 19/max 850/median 45. A few `unknown`-region sheets (n=3, min 426/max 630) are real stale/duplicate-template sheets, not a shape to replicate deliberately (see §1.5-style quirk below).

**Real Net Amount range:** min 17.29, max 4,043,777.20 (one real large institutional invoice), median 2,594.80. No real negative Net Amount values found anywhere in the family.

**Discount Rate is a real, closed set of text labels**, not numeric — use exactly these, don't invent new ones: `Public Pricelist` (83% of real rows), `Less 2%`, `LESS 4%`, `LESS 3%`, `LESS 2%`, `LESS 4% LESS 1%`, `LESS 4% LESS 2%`, `LESS 4% LESS 4%`, `Less 3% (PHP)`. One real row has the literal string `"False"` in this column (a real source-data quirk, not a bug — leave as-is if reproducing edge cases).

**Branch Code real format:** alphanumeric site codes, e.g. `L12E-000852`, `L12F-002336` — not simple zero-padded numerics. Preserve the letter-prefix + hyphen + 6-digit format.

**Day-of-week — real, verified, do NOT assume weekdays only:**

| Day | Real count | % of 23,051 real invoices |
|---|---|---|
| Friday | 4,984 | 21.6% |
| Thursday | 4,587 | 19.9% |
| Wednesday | 3,891 | 16.9% |
| Tuesday | 3,512 | 15.2% |
| Monday | 3,206 | 13.9% |
| **Saturday** | **2,871** | **12.5%** |
| **Sunday** | **0** | **0%** |

Del Monte real invoices run **Monday through Saturday**, never Sunday. Saturday is not a token presence — it's a real ~12.5% of volume, roughly on par with Monday. Generated daily-grain rows must include Saturday at comparable relative volume and must never place an invoice on a Sunday.

---

### 1.3 Sales Return — flagged blocker, spec provided anyway

**No Extract driver exists for this family** (see STEP 0). Whatever Audrey/Thea generate here cannot be validated against a real staged parquet, and won't flow through the pipeline until someone builds an 8th `FAMILY_PARSERS` entry. Recommend surfacing this to whoever owns ETL Pipeline > Transform in the AC tracker before investing real effort in this family — but the real-file shape below is solid regardless of when that driver lands.

**Generate:** the 18 missing months listed above, **once a driver exists** to consume them.

**Two real shapes, by era — use the one matching the target month:**

**2023–early-2025 shape** (sheet names like `ILOCOS SALES RETURN` / `PANGASINAN SALE RETURN`):
`Invoice Date, Invoice Num, REFNBR, Customer Name, Salesman, Untaxed Amount, Discount Rate, Discount Amount, Tax, Net Amount, Balance, Posted, Return Slip #`

**2025 shape** (sheet names split `<REGION> GS` / `<REGION> BO`, mirroring RMR's Good-Stock/Bad-Stock split):
`Invoice Date, Salesman, Town Display, Branch Code, Customer Name, Invoice Num, REFNBR, Untaxed Amount, Discount Rate, Discount Amount, Tax, Net Amount, Balance, Posted, Return Slip #, Return Type` (`Return Type` = `GS` or `BO`)

Since the real files transition shape between 2023-era and 2025-era, and the missing months span both sides (2024 gap sits between them), use the **2023-era shape for 2023/2024 generated months and the 2025-era GS/BO-split shape for 2025 generated months** — matching whichever real neighboring months use.

**Real row counts:** 50 real sheets across 19 files, min 14, max 573, median 45.

**Real Net Amount range:** 0 to 233,658.68 across 1,417 real real values. No negatives found. A real zero exists — don't treat zero as invalid.

---

### 1.4 Inventory Sign Off

**Generate:** the 19 missing months listed above.

**Columns the pipeline consumes:** `__col0__` (SKU code + description combined in one cell, no separate columns — real, not a parsing failure), `Quantity`, `CAS`, `PCS`, `PKG` — plus `is_demo = true`. Do not add `Cost`/`Valuation`/`Valuation with VAT` unless a specific downstream consumer needs them; they exist in real files but nothing in the pipeline currently reads them.

**Real `__col0__` format**, verified: `"9DBL58403 DM 100% PA Juice w/ Vit ACE 202 6-Pack"` — a SKU code (alphanumeric, ~9 chars) followed by a space and a free-text description. Generate as one combined string, not two fields.

**Real value ranges:**
- `Quantity`: min **−137.33**, max 18,340.82 — real negative quantities exist (inventory corrections), do not clamp.
- `PCS`: min **−18**, max 199,988 — same real-negative pattern.

**Known pipeline gap, disclose:** a third real header shape exists (`PRODUCT/ SKU CODE`, `DESCRIPTION`, `ITEM CODE`, `ITEM DESCRIPTION`, `CATEGORY` as named columns, not positional `__col0__`) in some real 2025-era files, and the column map doesn't cover it yet. Same guidance as Sell Out's `category_path` gap: generate using whichever real shape the neighboring real months in that era actually use, don't design around the bug.

**Real row counts per sheet** (41 real sheets): overall min 121, max 238, median 158. By region: `ilocos` n=17, min 131/max 201/median 148; `pangasinan` n=18, min 121/max 224/median 159.5.

**One real anomaly, not to be treated as a pattern:** a single file (`AUGUST 2023`) has two extra sheets with day-dated (not month-dated) SKU-level entries — confirmed a one-off in an earlier audit this session, appears in exactly 1 of 17 files. Do not replicate this in generated months; it would misrepresent Inventory Sign Off's real grain as finer than it actually is everywhere else.

---

### 1.5 Purchase Order

**Generate:** the 25 missing months listed above (the largest gap of any family — the real corpus only has 11 real months for this family to begin with).

**Columns the pipeline consumes:** same 14-column shape as Sales Register (`Invoice Date, Salesman, Town Display, Branch Code, Customer Name, Invoice Num, REFNBR, Untaxed Amount, Discount Rate, Discount Amount, Tax, Net Amount, Balance, Posted`) plus a real `Return Slip #` column present on some Purchase Order sheets — plus `is_demo = true`. **Do not add `units_received`** — not a real column (see Out of scope, §0).

**Real Net Amount range:** min 793.80, max 1,468,555.20, median 102,791.73. No negatives, no zeros found.

**Real quirk to preserve if replicating edge cases:** at least one real row has the literal string `"False"` in `Town Display` — a real source-data quirk (boolean leaking into a text field), not something to fix or avoid.

**With only 11 real months as a base, be conservative** about inferring seasonality or trend shape for this family specifically — 11 points with 6 different real month-labels (no two consecutive real months exist before 2024) is too thin to assert a real pattern. Recommend generating Purchase Order values as a flat-with-noise series anchored to the real median, not a trending one.

---

### 1.6 RMR GS & BO — zero months to generate

**Real coverage: 2025-10 and 2025-11, both already real.** This family's real-world existence window is fully covered by real data already.

**Named assumption:** RMR GS & BO is a **Daily Report**-convention file, and the Daily Report convention itself only exists starting October 2025 — Del Monte's own reporting format changed at that point (before then, the equivalent process was captured by the Monthly Report-era **Sales Return** files, see §1.3). Backfilling RMR GS & BO into, say, 2023 would mean inventing a file convention that did not exist yet in that period — a different and worse kind of fabrication than filling a data gap in an existing shape. **Recommend generating nothing for this family.** If a wider RMR-shaped history is genuinely wanted for the demo, that's a scope decision to make explicitly (and probably means treating Sales Return + RMR as one continuous logical series under two real shapes, at which point it's really an extension of §1.3, not this family).

---

## STEP 2 — Content rules for Sell Out

This is the one family that drives forecasting, so it gets the most scrutiny.

### 2.1 Real category taxonomy — two eras, not one list

**Critical finding, not previously documented anywhere in this project:** Sell Out's category vocabulary changed completely between the real Feb 2024 file and the real Mar 2025 file — exactly where the 10-month generation gap sits.

**Era A — fine-grained, Jan 2023 – Feb 2024 (11 real months):** category strings shaped `/BRAND/VARIANT`, e.g. `/TOM PASTE/BASE`, `/ACE/BASE`, leading spaces preserved as real formatting. **92 distinct real strings** found; excluding the blank/`False` artifacts (§1.1), **81 real named categories**.

**Era B — coarse, Mar 2025 – Dec 2025 (6 real months):** only **4–5 real category names**, no path structure: `FRUITS`, `CULINARY`, `BEVERAGE`, `INNOVATION`, and `DAIRY` (DAIRY appears only 3 of 6 real months, at near-zero/noise-level values — see 2.4).

**Do not merge these into one list.** They are not the same taxonomy at different granularity — Era B's names don't map cleanly onto Era A's (e.g. no real evidence "CULINARY" = the sum of any specific Era A subset; don't invent that mapping). Generated data must use whichever real taxonomy matches the era of the month being generated.

**Complete real Era A category list** (81 names, ranked by real total revenue, Jan2023–Feb2024, both regions combined — reuse these exact strings verbatim, never invent a new one):

Top 20 by revenue (full 81 available in the analysis backing this spec — ask if you need the complete list re-exported to CSV):
`/TIDBITS/BASE, /SWEET SPAG SAUCE/PROMO, /ORIGINAL TOMATO SAUCE/BASE, /TOTAL 100% JUICES/ACE - BASE REGULAR, /TODAY'S/BASE, /TOM PASTE/BASE, /KETCHUPS/OTHER SAUCES - BASE, /TOM SAUCE/ORIGINAL TOMATO SAUCE - BASE REGULAR, /ACE/BASE, /CRUSHED/BASE, /ORIGINAL BLEND/BASE, /CHUNKS/BASE, /TOTAL 100% JUICES/FIBER - BASE REGULAR, /TOTAL 100% JUICES/HEARTSMART - BASE REGULAR, /SLICED/BASE, /OTHER SAUCES/NPI, /TETRA/BASE, /STANDARD GRADE SOY SOUCE/BASE, /TOTAL 100% JUICES/HEARTSMART - PROMO REGULAR, /FILIPINO SPAG SAUCE/PROMO`

### 2.2 Implied unit price per category — real, and only moderately stable

Computed as `net_amount / quantity` per category per month, Era A:

| Category | Avg unit price (₱) | CV (coefficient of variation) |
|---|---|---|
| /TIDBITS/BASE | 1,433 | 31.9% |
| /SWEET SPAG SAUCE/PROMO | 838 | 31.7% |
| /ORIGINAL TOMATO SAUCE/BASE | 922 | 31.7% |
| /TOTAL 100% JUICES/ACE - BASE REGULAR | 545 | 31.6% |
| /TODAY'S/BASE | 1,242 | 31.7% |
| /TOM PASTE/BASE | 1,308 | 33.6% |
| /STANDARD GRADE SOY SOUCE/BASE | 2,134 | 32.9% |
| /FIESTA/BASE | 1,446 | 47.3% (least stable of the sampled set) |

**Pattern: unit price CV clusters tightly around 31–34% for nearly every real category**, regardless of price level. Treat this as the real noise band for unit price — a generated category with CV meaningfully outside ~30–35% (either flatter or wider) would look synthetic. One category (`/FIESTA/BASE`) runs wider at 47.3%; don't use it as the template for "typical" stability.

### 2.3 Real month-to-month swing per category

`swing = (max − min) / mean` across the 11 real Era-A months, excluding zero months:

- Tight/stable real examples: `/ORIGINAL TOMATO SAUCE/BASE` 144%, `/KETCHUPS/OTHER SAUCES - BASE` 133%, `/TOTAL 100% JUICES/ACE - BASE REGULAR` 143%
- Wide/volatile real examples: `/SWEET SPAG SAUCE/PROMO` **526%** (a real promo-driven category — near-zero most months, then a real ₱4M+ spike in Nov 2023/Jan 2024), `/BANANA/BASE` 326%, `/MACARONI/BASE` 285%, `/ACE/BASE` 254%

**Use 130–160% as the real "stable" band and 250–530% as the real "volatile" band** when assigning swing to generated categories in §3. Nothing in the real data swings less than ~130% or more than ~530% — those are the hard real bounds per the constraint in §3.

### 2.4 Real seasonality — honestly, there isn't enough data to claim one

11 real Era-A months, with 2 real gaps inside that window (Jul and Oct 2023 both missing), is not a full annual cycle and cannot support a real seasonality claim. Sept 2023 shows elevated values in several categories (`/TODAY'S/BASE`, `/MACARONI/BASE`, `/STANDARD GRADE SOY SOUCE/BASE` all peak or near-peak that month) — this could be back-to-school or pre-holiday buying, or could be one real month's ordinary volatility (per §2.3, single-month swings of 150%+ are themselves normal). **Recommendation: do not encode a seasonality curve into generated data.** Use the real swing bounds (§2.3) as random noise instead of a repeating seasonal shape — asserting a seasonal pattern from one partial cycle would be a real instance of exactly the fabrication this project's anti-fabrication principle exists to prevent.

### 2.5 Bridging the Mar–Dec 2024 gap

This gap is harder than a normal missing-month fill: it sits **exactly across the Era A → Era B vocabulary break** (§2.1). The real Feb 2024 endpoint is in 81-category fine-grained terms; the real Mar 2025 endpoint is in 4-category coarse terms. There is no real evidence for a category-by-category mapping between them.

**Proposed method, and why:**
1. Generate the 10 gap months (Mar–Dec 2024) **in the coarse Era-B taxonomy** (`FRUITS/CULINARY/BEVERAGE/INNOVATION`), not Era A. Reasoning: the real data on the far side of the gap (Mar 2025) is already coarse, and treating the vocabulary transition as having happened sometime during the unobserved 2024 gap is the least-invented assumption available — it requires inventing *when* the transition happened, but not *what* it maps to.
2. For each of the 4 coarse categories, **linearly interpolate between two real anchor points**: the real Feb 2024 fine-grained total (rolled up to one blended total — not per-category, since no real per-category mapping exists) apportioned across the 4 coarse categories using their real Mar 2025 revenue *shares* (not absolute values) as the apportionment weights, and the real Mar 2025 coarse-category values as the far endpoint.
3. Add random noise per generated month using the real swing bounds from §2.3 (130–530%, scaled to each category's real Era-B volatility — see §2.6 below, since Era B has its own real swing evidence too) — never a smooth straight line, since no real month-to-month series in this corpus is smooth.
4. **Do not generate DAIRY for the gap months.** Real DAIRY values are near-zero/noise-level even where DAIRY exists (§2.6) — not a real enough signal to extrapolate from.

**Named assumption, flagged explicitly:** step 2's apportionment-by-Mar-2025-share is an invented bridge, not a derived fact — there is no real evidence for how fast or in what pattern the vocabulary actually changed during 2024. This is the single largest liberty this spec takes. If Audrey/Thea want a more conservative alternative: generate the gap months as fine-grained (Era A) throughout, accept that the demo's category-level story only runs cleanly through Dec 2024, and present the real 2025 coarse months as separate, unmodified real data rather than a continuation of the generated narrative. That alternative is safer but tells a shorter story — see §3 for how this choice affects the demo narrative.

### 2.6 Real Era-B (coarse, 2025) trend evidence — use this for the "current" story

Real month-by-month, ₱ thousands, both regions:

| Category | Mar | Apr | Jun | Aug | Sep | Dec | Real first→last change |
|---|---|---|---|---|---|---|---|
| FRUITS | 2,113 | 2,904 | 2,385 | 1,786 | 2,363 | 3,953 | **+87.1%**, gradual, not spiky |
| BEVERAGE | 2,470 | 2,756 | 4,078 | 3,184 | 2,608 | 2,434 | −1.5%, roughly flat with a mid-year bulge |
| CULINARY | 2,526 | 3,207 | 4,356 | 2,888 | 2,799 | 15,731 | **+522.7%**, driven entirely by one real December spike — high-variance, not a trend |
| INNOVATION | 31 | 26 | 26 | 41 | 37 | 16 | −48.6%, small absolute volume throughout |
| DAIRY | 0 | −1 | 2 | 0 | 0 | 0 | noise-level, exclude from any role |

This table is real and independent of the bridging method in §2.5 — it's usable regardless of which bridging option gets chosen.

---

## STEP 3 — Story requirements

**The core tension, stated plainly:** the requested cast (2-3 up, 2-3 down, 1-2 high-variance, several steady-low Class C — at minimum ~8-10 distinct roles) cannot be filled from Era B's real 4-5 categories alone. It can be filled from Era A's 81 real categories. **Recommendation: assign story roles using Era A category identities**, carried through the generated 2024 gap, with the Era B table (§2.6) used as a real, independent, smaller-scale confirmation that the same kind of pattern (a real gradual riser, a real high-variance spike category) genuinely recurs in the most recent real data — not as the primary cast.

All figures below are real Era-A totals (Jan2023–Feb2024, both regions) unless marked otherwise; all proposed roles stay inside the real bounds from §2.2/§2.3.

### 3.1 Pareto split (A/B/C)

Real revenue concentration, Era A, 11 months, both regions, ₱83.99M grand total (excluding blank/`False` rows):

- **Class A (top 5, real, 47.6% cumulative):** `/TIDBITS/BASE` (13.3%), `/SWEET SPAG SAUCE/PROMO` (10.9%), `/ORIGINAL TOMATO SAUCE/BASE` (9.0%), `/TOTAL 100% JUICES/ACE - BASE REGULAR` (8.7%), `/TODAY'S/BASE` (5.7%)
- **Class B (next ~15, real, roughly 1–3.6% each, cumulative to ~90%):** `/TOM PASTE/BASE` through `/GRO/FS/DAIRY` in the ranked list — genuine mid-tier real categories, present in 10-11 of 11 real months each.
- **Class C (remaining ~60, real, each under 1%, several under 0.1%):** the long real tail, e.g. `/BANANA/BASE`, `/FIT N RIGHT/FNR 1L`, `/OYSTER SAUCE/BASE`.

This is a genuine, unforced Pareto shape already present in the real data — no generation needed to produce it, just don't distort it when filling gap months.

### 3.2 Trending up (2-3 categories) → reorder-critical

**Real-grounded candidates:** `/TOM PASTE/BASE` and `/STANDARD GRADE SOY SOUCE/BASE` both show a real upward drift within Era A (comparing early-2023 to late-2023/early-2024 months) without exceeding the real swing bounds (§2.3). Confirm exact slope from the raw series in §2.3's data before finalizing — this spec identifies plausible real candidates, not a locked slope.

**Independent real confirmation, Era B:** `FRUITS` (+87.1%, gradual across 6 real 2025 months, §2.6) is real evidence the same "gradual riser" shape recurs in the most current real data — cite this in the demo narrative even if the generated 2024 bridge doesn't literally connect to it category-by-category.

**Constraint respected:** proposed slope must not exceed the steepest *gradual* (non-single-spike) real trend observed — use FRUITS's real +87% over 6 months as the outer bound for a "trending up" role's magnitude, not CULINARY's +522% (that's a spike, see 3.4).

### 3.3 Trending down (2-3 categories) → overstocked / trapped capital

**Real-grounded candidate:** `/ACE/BASE` — real Era-A series shows a real decline from ₱425K (Jan 2023) down to ₱99K–167K range by late-2023/2024, a genuine real downward pattern, not manufactured. `/TETRA/BASE` shows a similar late-window real collapse (from ~₱90-170K down to ₱12-14K in the last two real months).

**Independent real confirmation, Era B:** `INNOVATION` (−48.6% over 6 real 2025 months, §2.6) — smaller absolute scale, but a real, genuine decline.

### 3.4 High-variance (1-2 categories) → high safety stock rationale

**Real-grounded candidate:** `/SWEET SPAG SAUCE/PROMO` — real 526% swing (§2.3), the widest in the sampled set, driven by genuine promo-timing spikes (near-zero most months, then a real ₱4M+ month). This is an authentic, extreme, real example — use it directly, no need to invent anything wider.

**Independent real confirmation, Era B:** `CULINARY`'s real +522.7% (§2.6), also driven by one real spike month (Dec 2025) — same shape, same real magnitude, different era. Strong signal this promo-driven volatility pattern is a genuine, recurring real Del Monte characteristic, not a one-off.

**Constraint respected:** do not exceed ~530%, the real maximum found in either era.

### 3.5 Steady low-volume (several categories) → Class C

Straightforward — the real Class C tail (§3.1) already has dozens of real, low-swing, low-revenue candidates. Pick any 4-6 from categories present in 10-11 of 11 real months with real swing under ~150% (e.g. `/VINEGAR/BASE`, `/CHICKEN COMPLIMENTS/BASE`, `/BANANA/BASE` — note `/BANANA/BASE` has 326% swing on a tiny base, revenue-wise it's still trivially Class C but don't cite it as "steady," use `/VINEGAR/BASE` or similar instead).

### 3.6 Where the real data can't support a role — stated honestly

- **DAIRY (Era B)** cannot support any role — real values are noise-level (§2.6). Exclude it from the story entirely rather than force it into "declining" or "low-volume."
- **A true 12-month seasonal cycle** cannot be claimed for any category (§2.4) — don't build a demo talking point around "Q4 seasonality" or similar; the real data doesn't cover enough of a repeating cycle to say that honestly.
- **The 2025 (Era B) cast alone** cannot fill more than 4 of the ~8-10 requested roles (§2.1) — this is why §3 recommends Era A as the primary cast, with Era B used only as independent confirmation, not as the main narrative.

---

## STEP 4 — Isolation and disclosure

**Isolation, mechanical:**
- Every generated row carries `is_demo = true`. This column does not currently exist on any real fact table — it needs to be added to whichever fact tables receive generated rows (`Sales_Fact`, `Purchase_Fact`, `SalesReturn_Fact`, `Inventory_Fact`, `SellOut_Fact`), defaulting `false`, `NOT NULL`.
- Generated rows go into the **same physical table** as real rows (not a separate table) but are always filterable via `is_demo`. A separate table was considered and rejected: it would require every downstream query (ABC, SARIMA, LP, every backend endpoint) to know to `UNION` two tables, doubling the surface area for a real/demo mixing bug. A single `WHERE is_demo = false` filter, enforced at the query layer, is the smaller blast radius.
- Every real-only query used for the manuscript, the panel demo's "real data" claims, or any exported report **must** include `WHERE is_demo = false` explicitly — this is a discipline requirement, not something the schema enforces automatically. Recommend a documented, reusable view (e.g. `Sales_Fact_Real`) per fact table that bakes in the filter, so nobody has to remember it by hand each time.
- Load, ABC, SARIMA, and LP code paths need an explicit decision (not covered by this spec — a separate task) on whether they ever run against demo rows at all, or whether demo rows are dashboard-display-only and never enter the analytical pipeline. Recommend the latter: generate demo data for the dashboard's visual completeness, but keep ABC/SARIMA/LP's real inputs `is_demo = false` only, so no forecast or recommendation number is ever influenced by generated data.

**Manuscript disclosure paragraph — superseded, see `DEL_MONTE_DEMO_GENERATION_SHEET.md`'s "Manuscript disclosure paragraph — updated" section for the current version (now covers the 2021-2022 backfill decision for both principals). Kept here only as the original 2023-2025-gap-only draft, for history:**

> To demonstrate the dashboard's full year-over-year view during development, a subset of Del Monte historical records outside the periods actually delivered by SSM (see §[X], real data coverage) was synthetically generated. Generation was constrained to the file shapes, columns, and value ranges already observed in SSM's real 2023–2025 delivery — no column, product identifier, or grain was introduced that does not exist in the real source data. Category-level demand figures were derived by interpolating between real anchor points using observed real month-to-month volatility as bounds, never exceeding the widest real swing or steepest real gradual trend found in the delivered data. All generated rows are flagged `is_demo = true` in the database and are excluded from every analytical result (ABC classification, SARIMA forecasts, LP recommendations) presented in this manuscript; they are used for dashboard demonstration purposes only. [Insert exact date range and row count once generation actually runs.]

---

## Open items for Audrey/Thea before generating

1. Confirm whether to build the Sales Return Extract driver first (§1.3) or generate that family's demo data ungated and reconcile later.
2. Confirm the §2.5 bridging method (coarse-taxonomy interpolation) versus the safer fine-grained-only alternative — this changes how far into 2025 the demo narrative visually extends.
3. Decide the `is_demo` real-vs-generated query discipline (§4) — specifically whether ABC/SARIMA/LP get a hard code-level guard against demo rows, or just a documented convention.
4. Full 81-category Era-A ranked list (only top 20 shown in §2.1) — ask if you want it re-exported as CSV rather than re-deriving it.
