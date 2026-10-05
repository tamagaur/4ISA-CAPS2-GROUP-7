# Tier A basis check (2026-10-03)

**TA's question:** Tier A is the set of top-selling products that together make 80% of revenue. It is currently ranked on a single month, Feb 2026, and holds 132 products. Does that list match the products that matter over longer periods? (The period a list is ranked on is called its **basis** below.)

**Short answer: only partly.**
- **Overlap with the 12-month list.** Today's Tier A contains 111 of the 175 products that make 80% of revenue over the last 12 months (Mar 2025 – Feb 2026). That is 63.4% of the 12-month list.
- **Overlap with the 24-month list.** It contains 99 of the 185 products that make 80% over the last 24 months (Mar 2024 – Feb 2026). That is 53.5%.
- **Revenue left out.** Planning only today's Tier A leaves out **32.3% of Mar 2025 – Feb 2026 revenue (₱126.80M of ₱392.66M)**. A list ranked on those same 12 months leaves out 20.0%.
- **Stability.** A one-month list is unstable. From Jan 2025 to Feb 2026, an average of **28.1 products entered and 27.3 left each month**, and 20.3% of the list was new each month. On a 12-month basis the averages are 5.9 in and 4.9 out.
- **Proposal, for the TA and Yuan to decide:** make the **12-month basis** official. Three open decisions are listed in §6.
- **New-product add-on (§7).** Adding products first sold in the last 12 months that are Class A on the last 3 months gives **189 products**: the 175 plus 14 new codes. It leaves out 19.0% of Mar 2025 – Feb 2026 revenue and 17.8% of Feb 2026's, less than both today's list and the plain 12-month list. It is nearly as steady: on average 7.6 products in and 7.1 out per month (Jan 2025 – Feb 2026).
- **What a switch would touch (§8).** Of the 175, 147 have stock in the Mar 2026 stock file, but only 106 have a usable (`ok`) forecast for Mar 2026 today. 45 have stock and no `ok` forecast, because today's forecast runner (the script that writes forecasts) only covers today's 132.

Read-only work. Nothing was written to the database. Branch `kelvin/tier-a-basis`.

---

## Data used

| Item | Value | Source |
|---|---|---|
| Sales table | `unilever_sku_demand_fact_real`: monthly sales per product (SKU = stock-keeping unit, one product code), La Union file | `pull_extract.py` |
| Generated data excluded | Flag column **`is_demo`**: only `is_demo = false` rows are used. This is the `_Real` view's own filter (the view shows only real rows). This drops 12,243 rows tagged `fill_source = synthetic_v2` (2021-01 to 2026-08, 911 products). They were counted by one query on the base table; nothing else reads it. Gap fills and estimates live in separate tables (`derived_receipt_fact`, `sku_demand_fill`) and were not read. | `base_counts` query → `extract_profile.csv` |
| Other tables read | `inventory_fact_real` (stock files; also filtered `is_demo = false`) and `product_dimension` (the product master). Two pipeline outputs, both built only from the `_Real` sales view: `abc_classification` (the live tier table, `orchestrate_abc.py:85`) and `forecast_result` (today's forecasts, `run_baseline_forecast.py:183`). Checked on the live database 2026-10-03: both `_Real` views end in `WHERE is_demo = false`, and the other three tables have no `is_demo` column. | `pull_extract.py` |
| Real rows used | 24,906 product-months, 1,807 products, **Jan 2023 – Feb 2026** (38 months), region `la_union` only | `demand_real` query → `extract_profile.csv` |
| Revenue | the `net_amount` column, in pesos, which is the same column the live tier table ranks on | `analytics/classification/orchestrate_abc.py:88` |
| Snapshot | one read-only transaction (repeatable read, so all queries see the same moment) at 2026-10-03 06:26 UTC, then rolled back. Everything after that ran offline. | `pull_extract.py` → `extract_profile.csv` |
| Follow-up snapshot (§8) | a second read-only transaction at 06:46 UTC, for the Mar 2026 stock file and today's forecasts. The sales table was unchanged between the two: same 24,906 rows, 1,807 products and ₱1,230,639,943.77 net of returns. | `pull_extract.py --only followup` → `extract_profile.csv`, `checks.csv` |

## How each list is built

The rules are the same as the live tier table's (`orchestrate_abc.py`, `abc.py`):
1. Add up each product's revenue over the window. A month where returns exceeded sales counts as ₱0 (`orchestrate_abc.py:208`).
2. Products with ₱0 in the window get no class.
3. Rank from highest revenue down. Class A is everything up to 80% of cumulative revenue, Class B up to 95%, Class C the rest (`abc.py:56-57`).

**Check:** this recomputation reproduces the live tier table exactly. That covers 52 of 52 month-and-method runs (single month and 3-month, 2024-01 to 2026-02), including today's 132 (`reproduction_check.csv`).

---

## 1. Class A on each basis (all windows end Feb 2026)

| Basis | Window | Products with sales | **Class A** | Class B | Class C | Total revenue in window | Class A revenue |
|---|---|---|---|---|---|---|---|
| Latest month (today's Tier A) | Feb 2026 | 710 | **132** | 194 | 384 | ₱28.06M | ₱22.44M (80.0%) |
| Last 3 months | Dec 2025 – Feb 2026 | 843 | **143** | 215 | 485 | ₱85.52M | ₱68.34M (79.9%) |
| Last 12 months | Mar 2025 – Feb 2026 | 1,091 | **175** | 244 | 672 | ₱392.66M | ₱314.00M (80.0%) |
| Last 24 months | Mar 2024 – Feb 2026 | 1,330 | **185** | 289 | 856 | ₱780.29M | ₱623.94M (80.0%) |
| Full real history | Jan 2023 – Feb 2026 | 1,529 | **217** | 324 | 988 | ₱1,231.30M | ₱984.09M (79.9%) |

The longer the window, the more products it takes to reach 80%. A likely reason, not tested: over a longer window, more products have had a good stretch at some point. Per-product detail: `tiers_by_basis.csv`.

## 2. Overlap between the lists

**Products in both lists.** The diagonal is each list's size. In brackets: products in both ÷ products in either.

| | Latest month | Last 3 | Last 12 | Last 24 | Full |
|---|---|---|---|---|---|
| **Latest month (132)** | 132 | 119 (76%) | 111 (57%) | 99 (45%) | 92 (36%) |
| **Last 3 (143)** | | 143 | 126 (66%) | 114 (53%) | 103 (40%) |
| **Last 12 (175)** | | | 175 | 156 (76%) | 140 (56%) |
| **Last 24 (185)** | | | | 185 | 164 (69%) |

Read across a row for "what % of this list is also in that list" (`overlap_matrix.csv`, column `pct_of_x_also_in_y`). Of the 12-month Class A, only 63.4% is in today's Tier A. Of the 24-month Class A, only 53.5%.

### Products in the 12- or 24-month Class A but missing from today's Tier A

**92 products** are in this group: 58 in both longer lists, 6 in the 12-month list only, 28 in the 24-month list only.
- **12-month subset:** 64 products, with ₱53.23M of revenue in Mar 2025 – Feb 2026.
- **24-month subset:** 86 products, with ₱137.87M in Mar 2024 – Feb 2026.

Why they are not in today's Tier A:

| Their Feb 2026 status | Products |
|---|---|
| Class B in Feb 2026 | 45 |
| Class C in Feb 2026 | 9 |
| No sales row in Feb 2026 | 29 |
| Returns ≥ sales in Feb 2026 | 9 |

30 of the 92 last sold before Dec 2025. 5 of them, all 24-month-only, had no sales at all in Mar 2025 – Feb 2026. So part of this gap is **products that are fading, or possibly now sold under a new code** (unconfirmed, see §4), rather than products the plan is wrongly ignoring.

Top 15 by 12-month revenue, highest first (all 92 are in `missing_from_current_tier_a.csv`; per-product revenue is in the `local/` copy only, see Files):

| Product | SKU | Feb 2026 status | Months with sales (of 38) | Last month sold |
|---|---|---|---|---|
| KNORR SINGLES PORK + PORK 48(12+2)X10G | 64957375 | no sales row | 10 | 2026-01 |
| KNORR SINGLES CHKN + CHKN 48(12+2)X10G | 64957373 | C | 10 | 2026-02 |
| BESTFOODS RGLR MYNS MAYO MGC DOY12X470ML | 65004623 | B | 38 | 2026-02 |
| KNORR SINIGANG ORIG+KOPIKOTP 24(6+1)X22G | 69617844 | C | 26 | 2026-02 |
| KNORR LIQUID SEASONING ORIGINAL 6X1L | 68395711 | returns ≥ sales | 35 | 2025-11 |
| SURF FABCON BLOSSOM FRESH SOL 360X28ML | 64373260 | returns ≥ sales | 15 | 2025-10 |
| SURF POWDER CHERRY BLOSSOM L 12X1100G | 69668142 | B | 32 | 2026-02 |
| LADY'S CHOICE SS CHICKEN DOY 24X220ML | 68763999 | B | 19 | 2026-02 |
| LADYS CHOICE MAYO DY+SLDMAC 12(1+1)470ML | 62720543 | no sales row | 11 | 2025-10 |
| LADYS CHOICE MAYO DY+TDBITS 24(1+1)220ML | 62720545 | no sales row | 10 | 2025-10 |
| DOVE SH KRTN STRT&SILKY 24(11+1)X13.5ML | 64314336 | B | 20 | 2026-02 |
| CLEAR SH COOL SPRT MENTHOL MEN 288X12ML | 67834798 | returns ≥ sales | 37 | 2026-01 |
| KNORR SINIGANG SAM ORIG 144X44G | 67749048 | B | 38 | 2026-02 |
| SUNSILK SH AD HTHY&STRNG (11+1)24X13.5ML | 62681009 | returns ≥ sales | 27 | 2026-01 |
| SUNSILK SH SMOOTH&MNGBLE 24X180ML | 67469128 | B | 38 | 2026-02 |

The reverse case: **20 products in today's Tier A are in neither longer list**, with ₱1.50M of Feb 2026 revenue (5.3% of the month). 18 of the 20 first sold in Jun 2025 or later, so these are mostly new codes still building a history (`current_tier_a_not_in_12m_or_24m.csv`).

### Revenue left out of planning under each basis

Left out = revenue from products not on the planning list. The rows are the list used; the columns are the period the revenue is measured over.

| Planning list (size) | Feb 2026 (₱28.06M) | Mar 2025–Feb 2026 (₱392.66M) | Mar 2024–Feb 2026 (₱780.29M) |
|---|---|---|---|
| **Latest month (132)** | ₱5.61M (20.0%) | **₱126.80M (32.3%)** | **₱281.48M (36.1%)** |
| **Last 12 months (175)** | ₱6.10M (21.7%) | ₱78.65M (20.0%) | ₱183.37M (23.5%) |
| **Last 24 months (185)** | ₱8.11M (28.9%) | ₱81.88M (20.9%) | ₱156.35M (20.0%) |

The 12-month list costs 1.7 percentage points on Feb 2026 (21.7% vs 20.0% left out). In exchange it recovers 12.3 percentage points of Mar 2025 – Feb 2026 revenue (20.0% vs 32.3%), which is ₱48.15M. All five lists against all five windows: `revenue_left_out.csv`.

## 3. Monthly churn: how stable is a single-month list?

Class A rebuilt on each single month, Jan 2025 to Feb 2026, and compared with the month before:

| Month | Class A | Entered | Left | New share of the list | Revenue share of new entrants (that month) |
|---|---|---|---|---|---|
| 2025-01 | 140 | 40 | 20 | 28.6% | 9.7% |
| 2025-02 | 123 | 11 | 28 | 8.9% | 2.5% |
| 2025-03 | 129 | 23 | 17 | 17.8% | 5.6% |
| 2025-04 | 129 | 21 | 21 | 16.3% | 6.8% |
| 2025-05 | 132 | 22 | 19 | 16.7% | 4.8% |
| 2025-06 | 145 | 41 | 28 | 28.3% | 9.1% |
| 2025-07 | 141 | 21 | 25 | 14.9% | 4.3% |
| 2025-08 | 145 | 31 | 27 | 21.4% | 8.2% |
| 2025-09 | 144 | 27 | 28 | 18.8% | 12.6% |
| 2025-10 | 138 | 24 | 30 | 17.4% | 9.1% |
| 2025-11 | 146 | 30 | 22 | 20.5% | 5.8% |
| 2025-12 | **89** | 8 | **65** | 9.0% | 2.3% |
| 2026-01 | 149 | **71** | 11 | 47.7% | 18.9% |
| 2026-02 | 132 | 24 | 41 | 18.2% | 6.8% |

Monthly averages over these 14 months, the same test on every basis (`monthly_churn_average.csv`):

| Basis | Average list size | Entered / month | Left / month | New share of the list | Range entered / left |
|---|---|---|---|---|---|
| Single month | 134 | **28.1** | **27.3** | **20.3%** | 8–71 / 11–65 |
| Last 3 months | 146 | 13.1 | 12.6 | 8.9% | 6–20 / 6–21 |
| Last 12 months | 160 | 5.9 | 4.9 | 3.6% | 1–10 / 0–8 |
| Last 24 months | 183 | 5.1 | 4.9 | 2.8% | 2–9 / 3–8 |

**Conclusion: a single-month basis is not stable.**
- On average, 20.3% of the single-month list was new each month (Jan 2025 – Feb 2026).
- Over the 14 months, 279 different products were Class A at least once, but only 49 were Class A in every month.
- Of today's 132, 23 were Class A in 3 or fewer of the 14 months (`class_a_frequency_2025_01_to_2026_02.csv`).
- One unusual month moves the whole list. In Dec 2025, Class A fell to 89 products, then jumped back to 149 in Jan 2026. Dec 2025 sales were ₱19.17M net of returns, against a 2025 monthly average of ₱32.78M. They were also more concentrated: the top 10 products took 34.2% of the month, the highest of the 14 months; the other 13 months ranged from 24.7% to 29.5% (`extract_profile.csv`). The cause was not investigated.

New entrants carried 7.6% of their month's revenue on average while making up 20.3% of the list. So the churn mostly involves products with small revenue shares. Monthly entry/exit names: `monthly_churn_members_1m.csv`.

## 4. For the dashboard: Class A in calendar 2025 vs calendar 2024

| | Products | Their revenue in 2024 | Their revenue in 2025 |
|---|---|---|---|
| Class A both years | 123 | ₱271.79M | ₱276.13M |
| **Entered** (Class A in 2025, not 2024) | 44 | ₱8.59M | ₱39.62M |
| **Left** (Class A in 2024, not 2025) | 38 | ₱38.03M | ₱4.71M |

Class A sizes: 161 in 2024 and 167 in 2025.
- **Entered:** 15 of the 44 had no 2024 sales at all, so they are new codes. 25 were Class B in 2024.
- **Left:** 18 of the 38 had no 2025 sales.

Biggest movers (full lists: `calendar_2025_vs_2024.csv`; "new" = no 2024 sales; per-product revenue is in the `local/` copy only):

| Change | Product | SKU | Revenue change, 2024 to 2025 |
|---|---|---|---|
| Entered | KNORR SINGLES PORK + PORK 48(12+2)X10G | 64957375 | new |
| Entered | KNORR SINGLES CHKN + CHKN 48(12+2)X10G | 64957373 | new |
| Entered | REX WMN DLN POWDER DRY + BRGHT 360X3ML | 64824382 | +499% |
| Entered | KNORR SIN ORIG+SINORIG 48(6+1)X11G | 64971078 | new |
| Left | KNORR SIN ORIG+SINORIG 24(12+1)X11G | 64320191 | −100% |
| Left | REXONA DLN POWDER DRY BRGHT 360X3ML | 68562304 | −100% |
| Left | KNORR CBS CHCKN SNGLS MP 72(6+2)10G | 64366637 | −83.5% |
| Left | SURF FABCON BLOSSOM FRESH SACH 360X25ML | 67882538 | −100% |

**Story angle (unconfirmed):** some entries and exits have look-alike names and may be the same item under a new pack or promo code. Two examples:
- KNORR SIN ORIG+SINORIG 24(12+1)X11G (64320191) left, and KNORR SIN ORIG+SINORIG 48(6+1)X11G (64971078) entered.
- REXONA DLN POWDER DRY BRGHT 360X3ML (68562304) left, and REX WMN DLN POWDER DRY + BRGHT 360X3ML (64824382) entered.

These pairs are look-alikes only and are **not confirmed as successors**. `supersedes_product_key` is empty for all 2,098 Unilever products in the product master. Only 6 product names in the Jan 2023 – Feb 2026 sales data carry more than one code (12 codes in all, `extract_profile.csv`).

## 5. Option only: tiered safety stock vs flat 90%, on the 12-month basis

**What was compared**
- Safety stock is the buffer held against demand being higher than expected. The formula is the one the LP (the linear-programming order planner) uses now (`scripts/run_lp.py:309-388`):
  - SS (safety stock, in pieces) = Z × σ_monthly ÷ √(average weekdays per month) × √(5 review + 3 lead = **8 business days**).
  - σ_monthly (sigma) is the standard deviation of each product's monthly pieces sold, measured over its real months from Jan 2023 to Feb 2026. A blank quantity counts as 0, as the LP's fetch does (`scripts/run_lp.py:399`).
  - Z is the service-level multiplier.
- **Check:** the flat-90% result matches the LP dry run of 2026-09-29 exactly for its 73 products. The largest difference is 0.00 pieces.
- **Z values:**
  - Flat 90%: 1.28 (`analytics/params.py:108`).
  - Tiered: Class A at 95% gets 1.645, Class B at 90% gets 1.28, Class C at 85% gets 1.036 (normal quantiles).
- **Cost:** pesos per piece = cost per case ÷ pack size, taken from each product's latest stock file with a cost. That is the same rule as the LP. 678 products are costed from the Mar 2026 file and the rest from earlier files.

| Class (12-mo basis, Mar 2025–Feb 2026) | Products | No SS: under 2 months of data | No cost in any stock file | Flat 90%: pieces | Flat 90%: ₱ at cost | Tiered: pieces | Tiered: ₱ at cost | Difference |
|---|---|---|---|---|---|---|---|---|
| A (95%) | 175 | 0 | 0 | 823,833 | ₱9,652,537 | 1,058,660 | ₱12,403,915 | **+₱2,751,378 (+28.5%)** |
| B (90%) | 244 | 1 | 0 | 139,867 | ₱2,846,257 | 139,867 | ₱2,846,257 | ₱0 |
| C (85%) | 672 | 54 | 58 | 99,190 | ₱2,136,233 | 80,315 | ₱1,729,736 | −₱406,496 (−19.0%) |
| **All** | 1,091 | 55 | 58 | 1,062,890 | ₱14,635,027 | 1,278,842 | ₱16,979,909 | **+₱2,344,882 (+16.0%)** |

**Reading the result**
- Piece totals include the 58 products without a cost. Peso totals cover the 978 products that have both a safety stock and a cost.
- Valued at the LP's ₱25/piece PLACEHOLDER, those 58 products would add ₱40,533 (flat) or ₱32,820 (tiered). That is not SSM's figure.
- **Tiered costs more, not less.** Class A products already hold most of the safety stock: ₱9.65M of ₱14.64M at flat 90%. So raising them to 95% adds ₱2.75M, while lowering Class C to 85% saves ₱0.41M.
- 90% is the level SSM confirmed (`params.py:106`). Changing it is SSM's and the adviser's call.
- Per product: `safety_stock_by_sku.csv`.

## 6. Proposal for the TA and Yuan: make the 12-month basis official

This is a proposal, not a decision.

**Why 12 months**
- **It covers the year.** It leaves out 20.0% of Mar 2025 – Feb 2026 revenue, against 32.3% for today's list. That is ₱48.15M more of the year planned. It leaves out 23.5% of the 24-month revenue, against 36.1%.
- **It barely hurts on the latest month.** It leaves out 21.7% of Feb 2026 revenue, against 20.0%.
- **It is steady.** On average 5.9 products entered and 4.9 left per month, with 3.6% of the list new each month (Jan 2025 – Feb 2026). A single-month list averaged 28.1 and 27.3. Planners and the LP would reshuffle far less often, and one odd month like Dec 2025 cannot reshape it.
- **It contains every season exactly once**, so no month of the year is over- or under-weighted.
- **It matches how SSM already works.** The principal sets the yearly allocation from the previous year's sales (`params.py:131-134`). The dashboard's weeks-of-cover figure already uses 12 months (`params.py:128`).

**What it costs**
- **A bigger list.** 175 products instead of 132, so 43 more to plan (+32.6%).
- **Slow to notice new codes.** 20 of today's Tier A (₱1.50M, 5.3% of Feb 2026) are in neither the 12- nor the 24-month list, and most first sold in Jun 2025 or later. A 12-month list adds them only once they have built up enough sales.
- **Keeps fading codes for a while.** Of the 64 products in the 12-month Class A but not today's Tier A, 14 had no sale after Nov 2025. They stay on the list until the window rolls past their good months.

**Why not 24 months**
- It is the steadiest (2.8% of the list new per month, Jan 2025 – Feb 2026), but the slowest to react.
- It leaves out 28.9% of Feb 2026 revenue.
- It still carries 5 products with no sales in Mar 2025 – Feb 2026.
- 65 of the 175 products in the 12-month Class A first sold after Mar 2024. In a 24-month window they are ranked against up to 24 months of older codes' sales.

**Why not the latest month:** it is unstable (20.3% of the list new each month, Jan 2025 – Feb 2026) and leaves out 32.3% of Mar 2025 – Feb 2026 revenue.

**Open decisions for the TA and Yuan (not decided here)**
1. **New products:** whether to add products too new for 12 months of history. One rule is computed in §7, and adopting it is still open.
2. **Possibly replaced codes:** whether to build a reviewed successor map, because `supersedes_product_key` is empty for all Unilever products. Only 4 of the 92 missing products have an exact-name twin in today's Tier A. More look-alikes exist (§4) but are unconfirmed.
3. **Tiered safety stock (§5):** this costs ₱2.34M more in safety-stock value at stock-file cost (12-month classes). It is SSM's and the adviser's call, not a pipeline default.

## 7. New-product rule: 12-month Class A plus new 3-month Class A

**The rule as computed:**
- Take the 12-month Class A (Mar 2025 – Feb 2026).
- Add every product whose first real sale falls within those 12 months **and** that is Class A on the last 3 months (Dec 2025 – Feb 2026).
- "First real sale" means the first month with pieces sold > 0, the same definition the forecast runner uses (`scripts/run_baseline_forecast.py:347-350`). Using pesos > 0 instead changes 0 products.

**Result: 189 products, the 175 plus 14 added.** 12 of the 14 are in today's Tier A. The rule catches 12 of the 20 new codes that were in today's Tier A but missed by both longer lists (§2).

| Product | SKU | First sale | 3-mo rank (Dec 2025–Feb 2026) | 12-mo class (Mar 2025–Feb 2026) | Feb 2026 class |
|---|---|---|---|---|---|
| KNORR SINGLES SHMP + SHMP 48(12+2)X10G | 65247613 | 2026-01 | 54 | B | A |
| KNORR SINIGANG GABI+KOPIKOTP 24(6+1)22G | 65459782 | 2026-01 | 57 | B | A |
| CLEAR SH COMPLETE SOFT CARE 3C 288X13ML | 65244857 | 2025-11 | 73 | B | A |
| CLEAR SH COOL SPRT MNTHL MEN3C 288X12ML | 65244853 | 2025-11 | 74 | B | A |
| CREAMSILK TRI-KRTN SCD R&S 24(11+1)X14ML | 64900614 | 2025-06 | 89 | B | A |
| SURF FABCON LP STR 60(5+1)25ML | 65071340 | 2025-09 | 92 | B | A |
| KNORR SIN GABI+SINGABI 48(6+1)X11G | 65247617 | 2026-01 | 105 | B | A |
| LADY'S CHOICE REAL MAYO DOY 24X130ML | 64961947 | 2025-07 | 108 | B | A |
| SURF FABCON ANTIBAC W MINT STR 360X25ML | 64856504 | 2025-07 | 109 | B | B |
| KNORR LIQUID SSONING ORIG TPR 12X500ML | 64985753 | 2025-09 | 110 | B | A |
| CLOSEUP RED HOT PROMO HL 36X2X173G | 64953872 | 2025-10 | 111 | B | A |
| LADY'S CHOICE SS BACON DOY 24X220ML | 64967994 | 2025-07 | 114 | B | A |
| LADYS CHOICE MAYO+MILK 12(3+2)80ML | 65455331 | 2026-02 | 133 | B | A |
| SURF FABCON F&B STR 60(5+1)28ML | 65071345 | 2025-09 | 141 | B | B |

The 14 together had ₱2.51M of revenue in Dec 2025 – Feb 2026, ₱4.01M in Mar 2025 – Feb 2026, and ₱1.10M in Feb 2026. The 8 new codes the rule still misses all first sold within the 12 months, but every one is Class B on the last 3 months (3-month ranks 150–287). They are in today's Tier A only because of one strong month (`rule1_added_products.csv`, `tiers_by_basis.csv`).

**Revenue left out** (`rule1_revenue_left_out.csv`):

| Planning list (size) | Feb 2026 (₱28.06M) | Dec 2025–Feb 2026 (₱85.52M) | Mar 2025–Feb 2026 (₱392.66M) | Mar 2024–Feb 2026 (₱780.29M) |
|---|---|---|---|---|
| Latest month, today (132) | ₱5.61M (20.0%) | ₱20.00M (23.4%) | ₱126.80M (32.3%) | ₱281.48M (36.1%) |
| Last 12 months (175) | ₱6.10M (21.7%) | ₱17.18M (20.1%) | ₱78.65M (20.0%) | ₱183.37M (23.5%) |
| **12 months + new (189)** | **₱5.00M (17.8%)** | **₱14.67M (17.2%)** | **₱74.64M (19.0%)** | **₱179.35M (23.0%)** |

The rule fixes the 12-month list's higher left-out share on Feb 2026. It leaves out less of Feb 2026 than today's list does (17.8% vs 20.0%), while keeping the 12-month list's coverage of Mar 2025 – Feb 2026.

**Monthly churn, same 14-month test (Jan 2025 – Feb 2026):**

| Basis | Average list size | Entered / month | Left / month | New share of the list | Range entered / left |
|---|---|---|---|---|---|
| Single month | 134 | 28.1 | 27.3 | 20.3% | 8–71 / 11–65 |
| Last 12 months | 160 | 5.9 | 4.9 | 3.6% | 1–10 / 0–8 |
| **12 months + new** | **175** | **7.6** | **7.1** | **4.3%** | **3–14 / 2–10** |

Compared with the plain 12-month list, the rule adds 1.8 more products entering and 2.2 more leaving per month on average. It stays far steadier than a single month. Month by month: `monthly_churn.csv`, basis `12m+new`.

## 8. Impact preview of switching to the 12-month basis (counts only, nothing changed)

**How each column is defined**
- **History** is the forecast router's own count (the router picks a model by length of history): months with pieces sold > 0, Jan 2023 – Feb 2026 (`analytics/forecasting/router.py:52-56`).
- **Runner outcome** is what the forecast runner (`scripts/run_baseline_forecast.py`) would do for Mar 2026. It uses the runner's own series builder and its gates (lines 330-375):
  - fewer than 3 sales months → `insufficient_data`, which gets a provisional trailing average and no accuracy score;
  - no sale in the last 6 calendar months (Sep 2025 – Feb 2026) → `dead_sku`, which gets no forecast;
  - otherwise the router picks by sales months:
    - 3–11 months: MA3, a 3-month moving average;
    - 12–23 months: TSB (Teunter-Syntetos-Babai), a method for products that do not sell every month;
    - 24+ months: the average of XGBoost (a machine-learning model) and MA3.
- **Check:** this replication matches today's 132 forecasts exactly. Status matches 132/132, bin 119/119 and sales months 132/132 (`model_params` of the 2026-03-01 rows; `checks.csv`).
- **Stock count** = the product has a row in the Mar 2026 Unilever stock file, the latest one (785 products, `extract_profile.csv`). Every listed product with a row shows stock above zero.
- **Forecast today** = a row dated 2026-03-01 with status `ok`. These 132 rows were written 2026-09-21: 119 `ok` and 13 `insufficient_data`.

| | Today's Tier A (132) | **12-month list (175)** | 12 months + new (189) |
|---|---|---|---|
| History < 3 months | 13 | 5 | 9 |
| History 3–11 months | 30 | 26 | 36 |
| History 12–23 months | 17 | 36 | 36 |
| History 24+ months | 72 | 108 | 108 |
| Runner: insufficient data (provisional average) | 13 | 5 | 9 |
| Runner: dead SKU, no forecast | 0 | 5 | 5 |
| Runner: MA3 (short) | 30 | 26 | 36 |
| Runner: TSB (medium) | 17 | 34 | 34 |
| Runner: XGBoost + MA3 (long) | 72 | 105 | 105 |
| In the Mar 2026 stock file | 120 | 147 | 158 |
| `ok` forecast today | 119 | 106 | 114 |
| **Stock count but no `ok` forecast today** | **9** | **45** | **49** |
| … no forecast row at all | 0 | 40 | 42 |
| … forecast row, status `insufficient_data` | 9 | 5 | 7 |

**What this means for a switch**
- **The forecast runner must widen its scope.** It forecasts only today's Tier A (`run_baseline_forecast.py:159-169`, `tier = 'A'` on the single-month basis). Under the 12-month list, 40 products with stock would have no forecast row until it does.
- **Most of the 175 have long histories.** 108 have 24+ sales months (Jan 2023 – Feb 2026), so the long-history model would serve 105 of them, against 72 today.
- **5 products would be dead SKUs.** They are in the 12-month Class A, but nothing has sold since May–Aug 2025, so the runner would give them no forecast:
  - CREAM SILK TRI-KRTN SCD STRT 288X15ML (64356034), last sold 2025-05.
  - CREAM SILK TMT DAMAGE REPAIR 288X18ML (68854478), last sold 2025-06.
  - CREAM SILK TMT REBOND STRAIGHT 288X18ML (68854475), last sold 2025-07. This is the only one still in the Mar 2026 stock file.
  - SURF FABCON LUXE PERFUME SACH 360X25ML (67882539), last sold 2025-08.
  - CLOSE UP RED HOT BYC PRM DUA2 48X2X120G (64395913), last sold 2025-08.

  This is the "keeps fading codes" cost from §6, made concrete.
- **5 new Knorr codes are already in the 12-month Class A on 2 months of sales,** all first sold 2026-01. Under every list they stay `insufficient_data` until a third sales month lands:
  - KNORR SINGLES PORK + PORK 48(12+2)X10G (65247611)
  - KNORR SINGLES CHKN + CHKN 48(12+2)X10G (65247609)
  - KNORR SINGLES BEEF + BEEF 48(12+2)X10G (65247607)
  - KNORR SIN ORIG+SINORIG 48(6+1)X11G (65247615)
  - KNORR SINIGANG ORIG+KOPIKOTP 24(6+1)22G (65459780)
- 28 of the 175 have no row in the Mar 2026 stock file. 13 of them sold in Feb 2026, so a missing row does not by itself mean discontinued.

Per product: `impact_preview_by_product.csv`. Per list: `impact_preview_summary.csv`.

---

## Caveats

- **Revenue rules tested.** Swapping either rule changes at most 3 products on any list. The two swaps are (a) returns netted over the whole window instead of per month, and (b) a blank month skipped instead of dropping the product. The biggest change is the 3-month list, 143 → 140 (`sensitivity.csv`).
- **Blank revenue.** Two rows have no `net_amount`:
  - LADYS CHOICE RL MY+KOPIKOTP 12(3+1)80ML (64369313), 2024-12.
  - CREAMSILK ULT REBORN SS 24(12+1)11ML (69704383), 2023-09.

  Following the live 3-month rule, each product is left out of every window that contains its blank month:
  - LADYS CHOICE RL MY+KOPIKOTP 12(3+1)80ML (64369313) is out of the 24-month, full-history and calendar-2024 lists. It is also out of the churn-test windows that include Dec 2024, and the live 3-month runs for 2024-12 to 2025-02, which the recomputation reproduces.
  - CREAMSILK ULT REBORN SS 24(12+1)11ML (69704383) is out of the full-history list and the churn-test windows that include Sep 2023. It has no sales in the 1-, 3-, 12- or 24-month windows ending Feb 2026.

  Counts per list are in `basis_summary.csv`, column `products_dropped_for_blank_revenue`. Skipping the blank month instead changes at most 2 products in any list (`sensitivity.csv`).
- **Single sales month.** A product with one month of sales is ranked like any other, for example LADYS CHOICE MAYO+MILK 12(3+2)80ML (65455331), first sold Feb 2026. It gets no safety stock (the LP needs at least 2 months) and an `insufficient_data` forecast (the runner needs at least 3 sales months).
- **One product per code.** Lists count product codes (`product_key`), as the live tier table does. Code changes are not linked (see §6, item 2).
- **One region.** La Union is the only Unilever per-product sales source.
- **Safety stock assumption.** The formula scales monthly variation down to days. This is a disclosed assumption pending the adviser's ruling (`params.py:179-185`).
- **Dec 2025 dip.** The size and concentration are measured; the cause was not investigated.

## Files

| File | What it holds |
|---|---|
| `basis_summary.csv` | §1: list sizes and revenue per basis |
| `tiers_by_basis.csv` | §1: every product's rank and class on all five bases, plus months of history (revenue: `local/` copy only) |
| `overlap_matrix.csv` | §2: overlap counts and shares between every pair of lists |
| `missing_from_current_tier_a.csv` | §2: the 92 products in the 12-/24-month Class A but not today's Tier A |
| `current_tier_a_not_in_12m_or_24m.csv` | §2: the 20 products in today's Tier A only |
| `revenue_left_out.csv` | §2: revenue left out, each list × each window |
| `monthly_churn.csv`, `monthly_churn_average.csv` | §3 and §7: month-by-month churn on four bases plus §7's `12m+new` |
| `monthly_churn_members_1m.csv` | §3: which products entered or left each month (single-month basis) |
| `class_a_frequency_2025_01_to_2026_02.csv` | §3: months each product spent in Class A, per basis |
| `calendar_2025_vs_2024.csv` | §4: entered, left and stayed, with revenue change in % (pesos: `local/` copy only) |
| `safety_stock_by_sku.csv`, `safety_stock_summary.csv` | §5: per product (pieces; cost and peso values: `local/` copy only) and per class |
| `rule1_added_products.csv`, `rule1_revenue_left_out.csv` | §7: the 14 added products; revenue left out by today's, 12-month and §7 lists |
| `impact_preview_by_product.csv`, `impact_preview_summary.csv` | §8: history, runner outcome, stock-file row and today's forecast, per product and per list |
| `sensitivity.csv` | Caveats: effect of the two revenue rules |
| `reproduction_check.csv` | Recomputation vs the live tier table, 52 runs |
| `extract_profile.csv` | aggregate facts from the extract that the README quotes: row counts, totals, monthly net totals, top-10 shares, snapshot times, stock-file and forecast counts |
| `checks.csv` | the analysis run's self-checks: live reproduction, LP cross-check, forecast replication, sales fingerprint |
| `pull_extract.py`, `run_tier_a_basis.py` | the read-only extract and the offline analysis |
| `qa_independent_recompute.py`, `qa_check.py` | final quality check: headline numbers from separate code; every README number and the arithmetic checked against the CSVs |

**Client data kept out of git (2026-10-05).** The project rule is that per-product sales and prices are never committed. The per-product tables in this folder therefore carry ranks, classes, month counts and pieces only. The full-detail tables, with the same file names, live in the git-ignored `local/` subfolder. `run_tier_a_basis.py` writes both copies (its `CLIENT_COLUMNS` pattern decides which columns stay out), and `qa_check.py` reads the `local/` copy and checks that the committed copy is the same table minus those columns. Without `local/`, rerun `run_tier_a_basis.py` to recreate it. Aggregate tables (per basis, per class, per month) are unchanged. Columns held in `local/` only:

| File | Columns in the `local/` copy only |
|---|---|
| `tiers_by_basis.csv` | `revenue_php_1m`, `revenue_php_3m`, `revenue_php_12m`, `revenue_php_24m`, `revenue_php_full` |
| `missing_from_current_tier_a.csv` | `revenue_php_12m`, `revenue_php_24m`, `revenue_php_1m` |
| `current_tier_a_not_in_12m_or_24m.csv` | `revenue_php_1m`, `revenue_php_12m`, `revenue_php_24m` |
| `monthly_churn_members_1m.csv` | `revenue_php_this_month`, `revenue_php_previous_month` |
| `calendar_2025_vs_2024.csv` | `revenue_php_2024`, `revenue_php_2025`, `change_php` |
| `safety_stock_by_sku.csv` | `revenue_php_12m`, `cost_per_piece_php`, `ss_flat_value_php`, `ss_tiered_value_php`, `difference_value_php` |
| `rule1_added_products.csv` | `revenue_php_3m`, `revenue_php_12m`, `revenue_php_1m` |

## Reproduce

From the repo root, using the project's virtual environment (`requirements.txt`). `SUPABASE_DB_URL` is read from the `.env` file named by `--env`; no other environment variable is needed.

```
D=reports/diagnostics/tier_a_basis_2026-10-03
X=<a folder outside the repo>
python $D/pull_extract.py --out $X --env .env                    # sales, product master, live tiers, costs
python $D/pull_extract.py --out $X --env .env --only followup    # stock file and today's forecasts (§8)
python $D/run_tier_a_basis.py --extract $X --lp-plan reports/lp_dry_run_2026-09-29/plan_aggregate_103.csv
python $D/qa_independent_recompute.py --extract $X               # headline numbers, separate code
python $D/qa_check.py --extract $X                               # README numbers, arithmetic, edge cases
```

`run_tier_a_basis.py` rewrites the CSVs in this folder and the full-detail copies in `local/`. The pulls read the live database, so a later run reflects whatever the database holds then. `extract_profile.csv` records the snapshot times and the sales fingerprint, so you can tell whether anything changed. The extract holds SSM sales rows. It stays outside the repo, following the `.gitignore` rule that client data is never committed.
