"""
analytics.optimization.lp_inputs — the LP's placeholder inputs and planning
conventions, kept in ONE place.

scripts/run_lp.py takes its CLI defaults from PLACEHOLDERS, and
backend/lp_cycle.lp_model_info() serves the same dict to the app, so the
numbers a run uses and the numbers the Reorder page states can't drift apart.
Step F of reports/LP_CLIENT_ALIGNMENT_PLAN_2026-09-29.md is editing this file
once SSM (Sir Abe) confirms the figures.

No pulp import here: the always-on API reads this module, and pulp is a
batch-job dependency (see backend/lp_cycle.py).

THESE ARE NOT SSM'S FIGURES. Each is a realistic value picked from our own
data or from what Sir Abe said in the 2026-09-29 meeting, agreed as a
placeholder with Yuan the same day. Don't cite them as SSM's in the
manuscript.
"""
from __future__ import annotations

# Weeks in an average month. The dashboard's AVG_WEEKS_PER_MONTH uses the
# same convention (tests/optimization/test_run_lp_script.py pins the two), so
# "3 weeks of sales" means the same figure on every screen and in the LP.
WEEKS_PER_MONTH = 365.25 / 12 / 7
BUSINESS_DAYS_PER_WEEK = 5

# How SSM's "keep N weeks of sales in stock" applies (--cover-rule):
#   aggregate  the planned SKUs' month-end stock, valued at cost, covers N
#              weeks of their sales at cost. A soft constraint; each SKU's
#              own target stays statistical. Yuan's reading, 2026-09-29: Sir
#              Abe's example was a peso total (₱48M × 3 ÷ 4 = ₱36M).
#   per-sku    every SKU's target is at least N weeks of its own sales.
# Sir Abe hasn't said which he means yet.
COVER_RULES = ("aggregate", "per-sku")

# Keys are scripts/run_lp.py's argparse dests, so each is one flag's default.
PLACEHOLDERS = {
    # Sir Abe: the yearly allocation is last year's sales × 103% (minimum),
    # 105% (mid) or 108% (maximum). Mid, until SSM says which applies.
    "allocation_pct": 105.0,
    # Business days. Weekly purchase orders, delivered 2-3 days later (Sir Abe).
    "review_days": 5.0,
    "lead_days": 3.0,
    # SSM's policy: keep 3 weeks of sales in stock (Sir Abe). The same 3 as
    # the dashboard's POLICY_WEEKS.
    "target_weeks": 3.0,
    "cover_rule": "aggregate",
    # Pieces: the most stock Unilever's warehouse has held, 3,816,842 in Jan 2025.
    "warehouse_capacity": 3_800_000.0,
    # ₱ per piece, only where the stock file gives a SKU no cost: the median
    # cost per piece (unit cost per case ÷ pack size) of the 73 planned SKUs
    # in the Mar 2026 stock file (₱24.55).
    "default_procurement_cost_per_unit": 25.0,
    # ₱ per piece per month: 2% of ₱25 (about 24% a year).
    "storage_cost_per_unit": 0.50,
}

# Stated with every plan (lp_model_info) until the adviser rules on it.
SAFETY_STOCK_ASSUMPTION = (
    "Safety stock = 1.28 × σ_monthly ÷ √(business days in a month) × √(review + lead days). "
    "Scaling a monthly σ down to days assumes demand is independent from one day to the next. "
    "Monthly data can't test that (reports/LP_READINESS.md §3.5: the demand is intermittent, "
    "66% of months are zero), and for a window shorter than a month it offers no clean "
    "alternative. An assumption, pending the adviser's safety-stock ruling."
)
