# Diagnosis: Del Monte sell_out incomplete category coverage

**My hypothesis going in — "the generator doesn't hold the category roster constant across months" — is WRONG.** All four questions were checked directly against the raw files/DB, not assumed. No fixes applied.

## 1. The original corpus (374 files, Thea's team) — 92 SELL_OUT_*.xlsx files

Read every file directly with openpyxl (not staging, not the DB).

- **Per-file category count: min=11, max=76, mean=57.5.** The roster is *not* constant across the 92 files — never was.
- **93 distinct categories appear across all 92 files combined. Only 7 of those 93 appear in every single file.** 40 categories appear in 74/92 files (the "core" roster), and the rest trail off in a long tail (1, 2, 5, 8, 9, ... files).
- `/CHUNKS/NPI` specifically: present in 74/92 files, **missing from exactly 18/92** — and all 18 are `SELL_OUT_2025-*` and `SELL_OUT_2026-01/02/03` (both regions). It disappears cleanly starting January 2025 and never comes back within this corpus.

**Conclusion for Q1: the roster was never constant in the original corpus.** Variable, month-dependent category presence is a pre-existing property of Thea's team's synthetic data, not something introduced this session.

## 2. This session's generation (2026-04 → 2026-08)

These 10 files (5 months × 2 regions) were **not** processed by `convert_synthetic_to_staging.py` at all — that script only converts the original 374 `.xlsx` files. This session's Del Monte backfill is written straight to parquet by `scripts/generate_synthetic_backfill.py::generate_del_monte_family()`.

Quoted from that function (`scripts/generate_synthetic_backfill.py:225-259`):

```python
def load_real_family_template(family: str) -> pd.DataFrame:
    files = sorted(REAL_STAGING_DIR.glob(f"{family}/*.parquet"))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    return df[df["_period"].str.startswith(DELMONTE_TEMPLATE_YEAR_PREFIX)]
```
```python
DELMONTE_TEMPLATE_YEAR_PREFIX = "2025"  # resample pool: all real 2025 rows (most recent full real era)
```
```python
def generate_del_monte_family(family: str) -> dict:
    real_df = load_real_family_template(family)
    ...
    for period in DELMONTE_BACKFILL_PERIODS:      # 2026-04 .. 2026-08
        for region in REGIONS:
            rng = _seed_for(family, period, region)
            pool = real_df[real_df["_region"] == region]
            ...
            n = int(rng.choice(row_counts))
            sample_idx = rng.integers(0, len(pool), size=n)
            rows = pool.iloc[sample_idx][business_cols].reset_index(drop=True).copy()
```

There is no roster-holding logic anywhere in this function — no code that enumerates a fixed category list and forces every period to carry it. What it actually does is: for every 2026-04..08 period/region, draw `n` individual rows **with replacement, uniformly at random, from the full pool of real 2025 sell_out rows** for that region. Whatever `category_path` (`__col0__`) each sampled row happens to carry comes along for free — nothing constrains or holds the roster.

**The decisive detail: the resample pool is filtered to `_period.str.startswith("2025")`.** Since real 2025 sell_out data never contains `/CHUNKS/NPI` (see §3), it is *structurally impossible* for this generator to ever sample a `/CHUNKS/NPI` row for 2026-04..08 — not a probability, a certainty, because the category isn't in the pool it draws from.

Same check on `scripts/convert_synthetic_to_staging.py` (which handles the original 374-file corpus, not this session's new backfill): grepped for `category`/`__col0__`/`roster` — the only `__col0__`-touching logic there is Total-row exclusion for negative injection (`_shared` line ~400-402) and a Shape-B/C column-split routine; nothing writes to or filters the category values themselves. `__col0__` passes through as read from each raw file. No roster-holding logic exists there either.

## 3. The real data (34 real sell_out sheets, 17 files)

Read directly with openpyxl, category rows starting after the banner+Total rows (row index 4 onward), values stripped of leading whitespace.

- **Per-sheet category count: min=4, max=76, mean=45.3. Zero categories appear in all 34 real sheets** — the real roster varies month to month too.
- `/CHUNKS/NPI`: present in **22/34** real sheets, missing from **12/34**. The missing 12 are **every single 2025 real sheet** (March, April, June, August, September, December 2025 — both regions, 6 months × 2 = 12). It's present in every 2023 and 2024 real sheet without exception.

**Conclusion for Q3: yes — real months genuinely carry different category sets, and `/CHUNKS/NPI` specifically stops appearing in real Del Monte sell_out reporting starting with the first available 2025 real month (March 2025) and stays absent through the last (December 2025).** This reads like a real product/SKU discontinuation or a reporting-category change on Del Monte's side, not a data artifact.

## 4. Where the /CHUNKS/NPI gaps actually come from — full 68-month table

| Month | Layer | `/CHUNKS/NPI` present? |
|---|---|---|
| 2021-01 – 2022-12 (24 months) | THEA-SYNTH | YES (all 24) |
| 2023-01 – 2023-06 | REAL | YES |
| 2023-07 | THEA-SYNTH | YES |
| 2023-08 – 2023-09 | REAL | YES |
| 2023-10 | THEA-SYNTH | YES |
| 2023-11 | REAL | YES |
| 2023-12 | THEA-SYNTH | YES |
| 2024-01 – 2024-02 | REAL | YES |
| 2024-03 – 2024-12 | THEA-SYNTH | YES (all 10) |
| **2025-01** | THEA-SYNTH | **NO** |
| **2025-02** | THEA-SYNTH | **NO** |
| **2025-03** | REAL | **NO** |
| **2025-04** | REAL | **NO** |
| **2025-05** | THEA-SYNTH | **NO** |
| **2025-06** | REAL | **NO** |
| **2025-07** | THEA-SYNTH | **NO** |
| **2025-08** | REAL | **NO** |
| **2025-09** | REAL | **NO** |
| **2025-10** | THEA-SYNTH | **NO** |
| **2025-11** | THEA-SYNTH | **NO** |
| **2025-12** | REAL | **NO** |
| **2026-01** | THEA-SYNTH | **NO** |
| **2026-02** | THEA-SYNTH | **NO** |
| **2026-03** | THEA-SYNTH | **NO** |
| **2026-04** | SESSION-SYNTH | **NO** |
| **2026-05** | SESSION-SYNTH | **NO** |
| **2026-06** | SESSION-SYNTH | **NO** |
| **2026-07** | SESSION-SYNTH | **NO** |
| **2026-08** | SESSION-SYNTH | **NO** |

Real coverage (17 months) and Thea's synthetic coverage (46 months) are perfectly complementary across 2021-2026 with zero overlap — synthetic fills exactly the months real doesn't cover, confirming the corpus was built that way deliberately. This session's 5 months (2026-04..08) extend that same complementary pattern forward.

**20 of the 68 months have zero `/CHUNKS/NPI` rows — every single month from 2025-01 through 2026-08, with no exceptions, regardless of which of the three layers supplied that month.**

## Plain answer

**The incomplete coverage is inherited from how real data is structured — it was present in the original corpus, and this session's work extended the exact same real pattern forward. My hypothesis was wrong.**

Specifically:
1. `/CHUNKS/NPI` genuinely disappears from Del Monte's *real* sell_out reporting starting the first real 2025 month and never returns through the last real 2025 month (Dec 2025) — confirmed directly from the real files, not inferred.
2. Thea's original synthetic corpus faithfully reflects this: every one of its 2025+ files is also missing the category, because whatever anchoring/resampling process built those files drew from real eras that already lacked it.
3. This session's generator is architecturally *guaranteed* to also miss it for 2026-04..08, because `generate_del_monte_family()` explicitly resamples only from the real-2025 row pool (`DELMONTE_TEMPLATE_YEAR_PREFIX = "2025"`) — and real 2025 never had the category to sample from in the first place.

No layer invented a gap. No layer "failed to hold a roster constant" in a way that differs from how the real source and the original corpus already behave — variable, non-constant category rosters are the norm in every layer checked, real included. Forcing `/CHUNKS/NPI` (or any other category) to appear in 2025+ synthetic rows would mean fabricating presence the real source doesn't support for that period, which is exactly what this project's anti-fabrication rule forbids. If the coverage gap needs to be closed, the fix is not in the generator's roster logic — it would have to be a deliberate, flagged decision to either (a) accept the real discontinuation as accurate and stop treating 2025+ absence as a "gap," or (b) resample 2026-04..08 sell_out from a *pre-2025* pool for categories known to be real-discontinued, which is a different and more invasive design change than anything diagnosed here. No fix applied — diagnosis only, per instruction.

## 5. Finding a category that spans the full range — and why none do

Ranked all 87 clean `category_path` values (excluding `False%` artifacts) in `sellout_fact` by longest continuous month-run, 2021-01..2026-08.

**Top 15 by longest continuous run:**

| category_path | total months present | longest run | start | end | reaches 2026-08 |
|---|---|---|---|---|---|
| /ACE/BASE | 48 | 48 | 2021-01 | 2024-12 | No |
| /ACE/NPI | 48 | 48 | 2021-01 | 2024-12 | No |
| /FIESTA/BASE | 48 | 48 | 2021-01 | 2024-12 | No |
| /FIBER/NPI | 48 | 48 | 2021-01 | 2024-12 | No |
| /CRUSHED/BASE | 48 | 48 | 2021-01 | 2024-12 | No |
| /CHUNKS/BASE | 48 | 48 | 2021-01 | 2024-12 | No |
| /CHUNKS/NPI | 48 | 48 | 2021-01 | 2024-12 | No |
| /FILIPINO SPAG SAUCE/PROMO | 48 | 48 | 2021-01 | 2024-12 | No |
| /FILIPINO SPAG SAUCE/BASE | 48 | 48 | 2021-01 | 2024-12 | No |
| /OTHER SAUCES/NPI | 48 | 48 | 2021-01 | 2024-12 | No |
| /PASTA/SPAGHETTI PASTA - BASE | 48 | 48 | 2021-01 | 2024-12 | No |
| /SPAG SAUCE/GOURMET SPAG SAUCE - BASE REGULAR | 48 | 48 | 2021-01 | 2024-12 | No |
| /SPAG SAUCE/FILIPINO SPAG SAUCE - BASE | 48 | 48 | 2021-01 | 2024-12 | No |
| /SLICED/BASE | 48 | 48 | 2021-01 | 2024-12 | No |
| /RECIPE MIX/BASE | 48 | 48 | 2021-01 | 2024-12 | No |

**Zero of the 87 clean categories span all 68 months.** All 42 categories that tie for the longest run share the exact same span: **2021-01 through 2024-12 (48 months)**.

**The binding constraint, confirmed directly:** every `category_path` value present anywhere from 2025-01 onward is one of exactly 5 values — `BEVERAGE, CULINARY, DAIRY, FRUITS, INNOVATION` — in both real (`is_demo=false`) and synthetic (`is_demo=true`) rows. This matches a pre-existing, already-documented finding in `scripts/convert_synthetic_to_staging.py` (lines 96-110): Del Monte's real sell_out data carries "a completely different, coarse 5-category vocabulary ('Total', 'FRUITS', 'CULINARY', 'BEVERAGE', 'INNOVATION')" that never overlaps with the fine-grained `category_path` taxonomy (`/DISPENSER JUICE/...` etc.) every 2021-2024 real and synthetic row uses. This is a genuine taxonomy change in Del Monte's real reporting starting 2025, not specific to `/CHUNKS/NPI` — it caps *every* fine-grained category at 2024-12, systemically.

**Highest-volume category among the 42 tied at 48 months: `/TIDBITS/BASE`** — total net_amount ₱51,195,689.88, total quantity 31,889.32 units, 2021-01 through 2024-12, fully continuous. This is what was driven end-to-end below, replacing `/CHUNKS/NPI` (₱548,351.39 total — far smaller volume, same span).

## 6. End-to-end drive — Del Monte category `/TIDBITS/BASE`

Same method as the Unilever SKU 20292811 drive: pulled directly from `sellout_fact` via SQL, fed through `fit_sarima()` / `forecast_one_step()` / `compute_safety_stock()` / `compute_rop()`.

| Step | Value |
|---|---|
| Series length | 48 months (2021-01..2024-12), 0 nulls |
| Series mean / std | 664.3608 / 261.1265 |
| Series min / max | 247.70 / 1645.18 |
| ADF stationarity | statistic=-8.4072, p-value=0.0000 → stationary |
| SARIMA order chosen | (0,1,2) |
| SARIMA seasonal order | (0,1,1,12) |
| AIC / BIC | 148.54 / 149.75 |
| Grid search | 144 combinations tried, 144 converged |
| Train series length | 38 (80/20 split) |
| One-step-ahead forecast (Ŷ_t+1) | **633.8691** |
| σ used for safety stock (monthly, same substitution rationale as SKU 20292811 — no daily grain exists for Del Monte category demand either, per `granularity.py`'s category-grain design) | 261.1265 |
| Safety stock (Z=1.28 × σ) | 334.2419 |
| **Reorder point (ROP)** | **968.1110** |

**Del Monte recommendation: ROP = 968.11 units for `/TIDBITS/BASE`**, to sit next to Unilever SKU 20292811's ROP = 293.13 units.

Note the forecast horizon difference: this ROP projects one month past the category's real continuous data (i.e. "next month after 2024-12"), not one month past 2026-08 — `/TIDBITS/BASE`'s data doesn't extend into 2025+ under the fine-grained taxonomy (§5), so the forecast is anchored to the end of its actual continuous span, exactly as SKU 20292811's was anchored to 2026-08.
