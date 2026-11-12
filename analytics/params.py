"""
analytics.params — every analytic parameter the pipeline, the LP and the API
use, kept in ONE place, each with where its value comes from.

Source tags (the comment after each value):
  LIT          literature, cited
  SSM          said by SSM (client meeting / manuscript's confirmation)
  DEC-nn       a decision on record in ARCHITECTURE.md
  TEAM         a team decision on record elsewhere (the report is named)
  MEASURED     measured from our data (the file is named)
  CONVENTION   a convention with no citation on record yet
  PLACEHOLDER  a stand-in until SSM confirms it; never cite as SSM's figure

Standard library only: the always-on API imports this module, and pulp /
xgboost are batch-job dependencies it must not pull in (backend/lp_cycle.py).
tests/test_params.py pins every value here, and fails if another module
assigns one of these names itself.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Forecast evaluation
# --------------------------------------------------------------------------- #
# LIT: Hyndman & Koehler (2006), "Another look at measures of forecast
# accuracy", IJF 22(4). MASE < 1 means the forecast beat the in-sample
# one-step naive forecast on average. A definition, not a tuned cut. This is
# THE reliability gate: the LP's candidate pool (scripts/run_lp.py), the
# dashboard's forecast card and the runner's pass rates all use it. Adopted as
# the plan's quality gate by the team (DEC-46), not confirmed by SSM or the adviser.
MASE_GATE = 1.0

# TEAM: the 2026-09-23 fit review's severity bands, fixed before computing
# (reports/diagnostics/README.md "Verdict thresholds"). They grade a SKU on
# the review's COMMON window, a different scoring from the pipeline's 20%
# holdout, and they are review flags, never a gate on what gets planned.
FIT_REVIEW_NOT_FIT_MASE = 1.1       # not fit: MASE >= 1.1
FIT_REVIEW_BORDERLINE_MASE = 0.9    # borderline: 0.9 <= MASE < 1.1

# TEAM: the fit review's "high volatility" cause flag, CV(last 12) > this.
# Team-set, source script lost: reports/diagnostics/README.md calls it the
# measured p75 over 119 scored SKUs, but only 92 rows of
# fit_review_common_2026-09-23.csv carry a CV, and their p75 is 0.434-0.446
# under numpy's eight percentile methods (0.437 linear), never 0.4365. The
# flag count is 23 of 92 at either 0.4365 or 0.437. A cohort-relative
# descriptor for that review only; not a volatility threshold elsewhere.
FIT_REVIEW_HIGH_VOL_CV = 0.4365

# TEAM: the temporal 80/20 split (reports/BAKEOFF_8020_PROTOCOL.md).
HOLDOUT_FRACTION = 0.20

# CONVENTION: the stored forecast band is forecast ± z × the served model's
# holdout RMSE (DEC-25). 1.645 is a two-sided ~90% normal band; DEC-25 itself
# states no coverage level.
FORECAST_INTERVAL_Z = 1.645
FORECAST_INTERVAL_LEVEL_PCT = 90

# --------------------------------------------------------------------------- #
# Eligibility and demand classification
# --------------------------------------------------------------------------- #
# TEAM: a SKU needs 3 real months with sales to be forecast or binned (the
# runner's gate, analytics/forecasting/baseline.py; the router bins on the
# same floor via analytics/segmentation/bins.py).
MIN_MONTHS_WITH_SALES = 3

# TEAM: no sale in the last 6 months = dead SKU (the runner's
# Forecast_Result.status 'dead_sku') = FSN non-moving. Also the data marts'
# idle stock: a product in a stock count with no piece sold in the 6 sales
# months up to it (mart.idle_stock, migration 0041).
DEAD_SKU_MONTHS = 6

# DATA: Unilever stock counts on record as possibly partial. 2025-05: 404 rows
# against 513-812 in every other real month (inventory_fact_real, checked
# 2026-10-03), and 36 of 96 selling Tier A products absent (Claude Code 8,
# branch kelvin/surplus-bias-experiment, part0_count_completeness.csv). A list,
# not a threshold: none is on record. PENDING SSM CONFIRMATION that the 2025-05
# count was partial (Yuan). A product missing from one of these is unknown,
# not 0 on hand, in scripts/fill_missing.py; mart.accuracy_mart counts it as 0
# (the stock-limited rule below) and flags the row count_possibly_partial.
POSSIBLY_PARTIAL_COUNTS = ("2025-05",)

# TEAM: "possibly stock-limited" (kelvin/surplus-bias-experiment 3226cc4,
# README Part 0.1; adopted for mart.accuracy_mart by Yuan 2026-10-04,
# migration 0043): the opening or closing stock count is 0, or below
# STOCK_LIMITED_WEEKS weeks of the product's average sales — the mean monthly
# pieces over the STOCK_LIMITED_AVG_MONTHS months before the month, from the
# first sale, at least STOCK_LIMITED_AVG_MIN_MONTHS months; 1 week = mean x 12 / 52.
STOCK_LIMITED_WEEKS = 1.0
STOCK_LIMITED_AVG_MONTHS = 12
STOCK_LIMITED_AVG_MIN_MONTHS = 3


# LIT: Syntetos, Boylan & Croston (2005), "On the categorization of demand
# patterns", JORS 56(5). ADI (average inter-demand interval) >= 1.32 is
# intermittent, CV² of the non-zero demand sizes >= 0.49 is erratic/lumpy.
SBC_ADI_CUT = 1.32
SBC_CV2_CUT = 0.49

# CONVENTION: XYZ volatility cut-offs on sku_traits.cv (monthly units from
# the first sale on). Fixed on purpose, not cohort quartiles: a quartile
# moves with the cohort, so a SKU could change bin without its sales
# changing (analytics/segmentation/bins.py). No citation on record yet.
XYZ_CV_LOW = 0.5
XYZ_CV_HIGH = 1.0

# TEAM: FSN (analytics/classification/fsn.py). A product is fast only with
# at least this many months with sales in the window — a different floor
# from MIN_MONTHS_WITH_SALES that happens to share its value.
FSN_WINDOW_MONTHS = 12
FSN_MIN_FAST_SALES_MONTHS = 3

# --------------------------------------------------------------------------- #
# Tier A basis (analytics/classification/orchestrate_abc.py)
# --------------------------------------------------------------------------- #
# DEC-42 (team decision, adopted 2026-11-02, in use since 2026-10-05; the
# Technical Adviser has not confirmed it): which
# ABC run is "Tier A" for Unilever, read by the forecast runner, segmentation,
# the LP's pool and every backend tier read. 't12m_new' = Class A on the last
# 12 months' revenue, plus products first sold within those 12 months that are
# Class A on the last 3 (kelvin/tier-a-basis f753f4e, README section 7: 189
# products as of 2026-02). 'single' = Class A on the month alone, the basis
# until 2026-10-05; its runs are still written, so switching back is this one
# value plus a refresh. Del Monte stays on 'single': its ABC is category grain
# (DEC-03) and the 12-month rule was measured on Unilever SKUs only.
TIER_A_BASIS = "t12m_new"
TIER_A_BASES = ("single", "t12m_new")
TIER_A_BASIS_WINDOW_MONTHS = 12
TIER_A_NEW_PRODUCT_WINDOW_MONTHS = 3


def abc_method(principal: str) -> str:
    """The ABC_Classification.method holding `principal`'s Tier A."""
    return TIER_A_BASIS if principal == "unilever" else "single"


def abc_method_sql(alias: str = "") -> str:
    """SQL predicate pinning ABC_Classification.method to each row's own
    principal's basis, for queries that read both principals. `alias` is the
    table alias ('' for none); the basis is a checked constant, never input."""
    col = f"{alias}." if alias else ""
    return f"{col}method = CASE {col}principal WHEN 'unilever' THEN '{TIER_A_BASIS}' ELSE 'single' END"


# --------------------------------------------------------------------------- #
# Global model (analytics/forecasting/global_model.py)
# --------------------------------------------------------------------------- #
# TEAM: the served XGBoost trains single-threaded so a rerun is
# bit-identical. The stored bake-off artifacts were NOT all fitted this way:
# reports/experiment_artifacts/scripts/final_models.py:81,
# candidate_followup_2026-09-22/arms_local.py:121 and synth_check.py:38 used
# nthread=8; final_eval.py:60 and scripts/xgboost_bakeoff.py:41 used 4. A
# served-vs-artifact comparison can differ in the last digits for that
# reason alone.
XGB_NTHREAD = 1

# --------------------------------------------------------------------------- #
# Calendar factor (analytics/forecasting/calendar.py)
# --------------------------------------------------------------------------- #
# DEC-41 (team decision, adopted 2026-11-02; approved by Kelvin 2026-10-19 for build + dry run).
# Sir Catubag has not signed it off (a methodology change); the runner applies it only with --calendar-factor.
# LIVE STATUS (corrected 2026-10-20, calc audit): the factor IS applied to the stored forecast. All 175
# 'ok' Forecast_Result rows written 2026-10-19 10:37 UTC carry calendar_factor 1.0762 (March 2026, 2 earlier
# years) and value_before_calendar, so lp_run 3 (2026-10-19) plans on adjusted forecasts. Sir Catubag's
# sign-off has not been given: DEC-41 records the team's adoption, not his approval. The runner's default
# stays OFF (opt-in --calendar-factor); the live write used it.
# Measured sensitivity (closed form on the 107 stored LP rows, stored safety stock and 2026-02 stock held
# fixed): 424,127 pieces with the factor, 354,975 without, a 16.3% difference across 70 changed rows. Total
# forecast 2,036,469 with vs 1,892,199 without (+7.62%). reports/diagnostics/calc_audit_2026-10-20/.
# SHRINK 0.5 = the "half"
# variant: same overall gain as the full factor (median WAPE 0.318 -> 0.305 vs
# 0.304 on MA3) with more products improved (121/59 vs 113/67), chosen because
# only 1-2 earlier years back each month's factor. PRIOR_MONTHS 3 matches MA3's
# window, the trailing level the factor corrects.
CALENDAR_FACTOR_SHRINK = 0.5
CALENDAR_FACTOR_PRIOR_MONTHS = 3
# DEC-41: whether Sir Catubag has signed the factor off (he has not; the team
# adopted it without him). The live 2026-03 forecast was written with
# --calendar-factor on 2026-10-19 (Forecast_Result.model_params.calendar_factor
# on every 'ok' row), so the dashboard says the forecast is adjusted AND that
# his sign-off is missing, from this flag. Set True only when he approves it.
CALENDAR_FACTOR_SIGNED_OFF = False
# GRAIN of the calendar factor (analytics/forecasting/calendar.py, 2026-11-12): "product" = computed per product (each product's
# own month ratios pulled toward the typical product's, ProductCalendar); "company" = the company-total ratio applied to every
# product (live until this change). The company ratio is volume-weighted and disagreed in direction with the typical product in
# 4 of 35 month-years (March 2024: 1.136 vs 0.906). Chosen on criteria fixed before the results (STATE.md): all three product-grain
# estimators passed the both-windows bar; this one had the lowest mean pooled WAPE.
CALENDAR_GRAIN = "product"
CALENDAR_OWN_YEARS_PRIOR = 2     # a product's own years weigh n / (n + 2) against the typical product's ratio (fixed beforehand)
# December dip rule at product grain: a December target takes the most recent earlier December's product-median ratio in full
# when it was below 1. At product grain December 2023 was a dip too (0.950), so the rule acts in December 2024 and 2025 and was
# scored in both windows: it passed the bar against the product calendar (2024-01..2025-08 interval [-0.38, -0.20]). Not confirmed
# by SSM as to cause. False = off.
DECEMBER_DIP_RULE = True

# --------------------------------------------------------------------------- #
# Review flag (analytics/forecasting/review_flag.py) and the yearly-pattern
# label (analytics/forecasting/decomposition.py)
# --------------------------------------------------------------------------- #
# TEAM: the collapse rule, last-3-month mean < 0.5 x last-12-month mean, on the
# history the product has (2026-11-03: no 12-month minimum). 0.5 is Yuan's example (2026-10-03),
# recorded in reports/diagnostics/forecast_error_business_2026-10-03/README.md
# section 7 (kelvin/forecast-error-business b4f6b77).
REVIEW_COLLAPSE_RATIO = 0.5
REVIEW_COLLAPSE_RECENT_MONTHS = 3
REVIEW_COLLAPSE_BASE_MONTHS = 12

# TEAM (Kelvin, 2026-11-10: "switch on succession and fading"): the two forecastability treatments served inside
# router.route() (analytics/forecasting/treatments.py). Rules and thresholds as committed before scoring in
# reports/experiments/forecastability_2026-11-10/classify.py (f3ffe47); both held in both backtest windows (8a4f78d).
# FADING reuses REVIEW_COLLAPSE_RATIO above. False switches a treatment off (then re-run the forecast and the plan).
SERVE_SUCCESSION = True
SERVE_FADING = True
SUCCESSION_DROP = 0.5            # last month below this share of the 12-month mean
SUCCESSION_NEW_CODE_MONTHS = 3   # a related code's first sale within this many months before the forecast month
SUCCESSION_CONTENT_TOL = 0.10    # "same content per piece": within 10%, same unit
LOW_PIECES_6M = 500              # PROMO/LOW: under 500 pieces in the last 6 months is left on the served forecast

# Safety stock follows the level (Kelvin's brief 2026-11-10: "Surf Fabcon SOL is forecast at zero and the plan still orders
# 23,400 pieces of it, all safety stock sized on pre-collapse sales"). run_lp multiplies sigma_d by
# min(1, forecast / mean monthly quantity of the months sigma is taken over) (scripts/run_lp.level_factor), Unilever only:
#   "treated"  only for products whose latest forecast succession or fading changed (Forecast_Result.model_params), or whose
#              latest 'ok' forecast is zero (added 2026-11-11, Kelvin's brief: 2 products, MA3 of three zero months but under the
#              dead-SKU window, ordered 2,784 pieces of pure safety stock against a zero forecast in lp_run 8)
#   "all"      for every product
#   False      never (the plan as it stands)
# Backtest: reports/experiments/error_hunt_2026-11-10/README.md (sscurve.py, P_level_treated / P_level).
# DECIDED "treated" (Kelvin, 2026-11-10): not "all", which cuts more stock but holds more for planned products at matched
# pieces short in the main window. Changing it moves the plan (re-run run_lp; the plan invariant in STATE.md moves with it).
SAFETY_STOCK_FOLLOWS_LEVEL: str | bool = "treated"

# TEAM: option D of the surplus-bias experiment (kelvin/surplus-bias-
# experiment 3226cc4, README "Candidate fixes"; chosen 2026-10-03 because no
# forecast change met the recorded 5% threshold): flag a product when it is in
# a run of 3+ over-forecast months ending the month before the cycle. The
# look-back is that experiment's PRIOR_MONTHS: how far back a run is counted,
# so a stored run length of 6 reads "6 or more".
REVIEW_OVER_RUN_MONTHS = 3
REVIEW_LOOKBACK_MONTHS = 6

# DEC-23 / LIT: the lag-12 autocorrelation test against the 95% white-noise
# bound 1.96 / sqrt(n), on 24+ months from the first sale. Rule R1 of
# b4f6b77 README section 10: its false-alarm rate on no-seasonality series at
# our lengths is under 1%, against 15-18% for the STL-strength >= 0.6 band
# ("Strong seasonality") it replaces. The label reads only the positive side
# (decomposition.yearly_pattern says why).
YEARLY_ACF_MIN_MONTHS = 24
YEARLY_ACF_Z = 1.96

# --------------------------------------------------------------------------- #
# LP (analytics/optimization/lp.py, scripts/run_lp.py)
# --------------------------------------------------------------------------- #
# TEAM (asserted): "stakeholder consultation" per the manuscript; in no
# scribe note (reports/LP_READINESS.md §1.5). Must sum to 1.
LP_WEIGHTS = {"cost": 0.45, "service_level": 0.35, "storage": 0.20}

# SSM: 90% cycle service level, confirmed by SSM procurement management per
# the manuscript (reports/LP_READINESS.md §1.5). Z = 1.28 is its normal quantile.
SERVICE_Z = 1.28
SERVICE_LEVEL_PCT = 90

# CONVENTION: calendar arithmetic shared by every screen and the LP, so
# "3 weeks of sales" is the same figure everywhere.
DAYS_PER_MONTH = 365.25 / 12
WEEKS_PER_MONTH = DAYS_PER_MONTH / 7
BUSINESS_DAYS_PER_WEEK = 5

# SSM: keep 3 weeks of sales in stock (Sir Abe, 2026-09-29). The dashboard's
# policy card and the LP's --target-weeks default.
POLICY_COVER_WEEKS = 3

# Cover measured from sales HISTORY, two windows on purpose, both ending at
# the principal's stock snapshot month:
#   TEAM: the dashboard's weeks-of-cover KPI, a portfolio figure, over 12
#   months so the range picker doesn't move it (commit c63b1d9,
#   reports/LP_CLIENT_ALIGNMENT_PLAN_2026-09-29.md "Done since").
#   CONVENTION: the Reorder page's per-SKU days of cover, over 3 months, the
#   same window as the MA3 forecast. No DEC.
COVER_KPI_HISTORY_MONTHS = 12
SKU_COVER_HISTORY_MONTHS = 3

# SSM: the principal sets the year's allocation from the previous year's
# sales — x103% minimum, x105% mid, x108% maximum (Sir Abe, client meeting
# Sep 2026). analytics/allocation.py applies it.
ALLOCATION_LEVELS_PCT = (103, 105, 108)
# DEC-44 (stated assumption, adopted 2026-11-02; SSM has not said which level
# applies): the guaranteed minimum (Yuan, 2026-09-30): the LP's --allocation-pct
# default and the level the dashboard card reports as the default.
ALLOCATION_DEFAULT_PCT = 103
# What the sales basis is counted in; the caller says which. The LP needs
# pieces; the dashboard card uses pesos (Del Monte's sell-out has no pieces).
ALLOCATION_UNITS = ("pieces", "pesos")

# How SSM's "keep N weeks of sales in stock" applies (--cover-rule):
#   aggregate  the planned SKUs' month-end stock, valued at cost, covers N
#              weeks of their sales at cost. A soft constraint; each SKU's
#              own target stays statistical. Yuan's reading, 2026-09-29: Sir
#              Abe's example was a peso total (₱48M × 3 ÷ 4 = ₱36M).
#   per-sku    every SKU's target is at least N weeks of its own sales.
# Sir Abe hasn't said which he means yet.
COVER_RULES = ("aggregate", "per-sku")

# DEC-44 (2026-11-02): the four optimisation inputs below (procurement cost,
# storage cost, warehouse capacity, supplier ceiling = the allocation %) are
# adopted by the team as stated assumptions. SSM has not confirmed any of them.
# PLACEHOLDER: THESE ARE NOT SSM'S FIGURES. Each is a realistic value picked
# from our own data or from what Sir Abe said in the 2026-09-29 meeting,
# agreed as a placeholder with Yuan the same day. Keys are scripts/run_lp.py's
# argparse dests, so each is one flag's default, and backend/lp_cycle serves
# the same dict. Step F of reports/LP_CLIENT_ALIGNMENT_PLAN_2026-09-29.md
# edits them once SSM confirms.
PLACEHOLDERS = {
    # Sir Abe: the yearly allocation is last year's sales × 103% (minimum),
    # 105% (mid) or 108% (maximum). ALLOCATION_DEFAULT_PCT until SSM says
    # which applies.
    "allocation_pct": float(ALLOCATION_DEFAULT_PCT),
    # Business days. SSM's own stated practice: weekly purchase orders, delivered 2-3 days
    # later (Sir Abe). An assumption the system neither implements nor verifies: no code
    # splits the month's order into weekly POs (analytics/optimization/lp.py).
    "review_days": 5.0,
    "lead_days": 3.0,
    "target_weeks": float(POLICY_COVER_WEEKS),
    "cover_rule": "aggregate",
    # Pieces: the most stock Unilever's warehouse has held in one count, 3,816,842
    # (the 2025-01 period, counted 3 Feb 2025; the 2026-02 count, 2 Mar 2026, is the
    # next highest at 3,800,930). A floor on the true capacity, not a measured limit.
    # Corrected 2026-10-22 from 3,800,000, which the 2026-02 whole-warehouse count
    # already exceeded. The LP applies it to the planned products' stock plus orders
    # (2,663,949 pieces for cycle 2026-03), so it does not bind this cycle.
    "warehouse_capacity": 3_816_842.0,
    # ₱ per piece, only where the stock file gives a SKU no cost: the median
    # cost per piece (unit cost per case ÷ pack size) of the 101 planned SKUs of
    # cycle 2026-03 that are in the Feb 2026 stock count (₱33.48; ₱36.16 over all
    # 109 planned SKUs' plan prices). Corrected 2026-10-22 from 25.0 (₱24.55 for
    # an older 73-SKU cycle). Every 2026-03 row has a stock-file price, so this
    # default is applied to no row this cycle.
    "default_procurement_cost_per_unit": 33.48,
    # ₱ per piece per month: 2% of ₱25 (about 24% a year). The ₱25 is the old
    # procurement default; the rate is kept, not re-derived, because this value
    # enters the objective for every product (a stated assumption, DEC-44; not
# confirmed by SSM).
    "storage_cost_per_unit": 0.50,
}

# Stated with every plan (lp_model_info) until the adviser rules on it.
SAFETY_STOCK_ASSUMPTION = (
    f"Safety stock = {SERVICE_Z:g} × σ_monthly ÷ √(business days in a month) × √(review + lead days). "
    "Scaling a monthly σ down to days assumes demand is independent from one day to the next. "
    "Monthly data can't test that (reports/LP_READINESS.md §3.5: the demand is intermittent, "
    "66% of months are zero), and for a window shorter than a month it offers no clean "
    "alternative. An assumption, pending the adviser's safety-stock ruling."
)

assert abs(sum(LP_WEIGHTS.values()) - 1.0) < 1e-9, "LP_WEIGHTS must sum to 1"
assert TIER_A_BASIS in TIER_A_BASES, "TIER_A_BASIS must be one of TIER_A_BASES"
