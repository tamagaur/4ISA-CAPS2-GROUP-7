"""
backend/abc_basis.py — names the ABC basis a tier count was made on (audit finding 1, 2026-10-23).

Two bases are live and both are defensible; before this, neither said which it was:

  * the ABC page, the SKU list and the order plan (LP) use analytics.params.TIER_A_BASIS ('t12m_new' for Unilever:
    Class A on the last 12 months, plus products first sold within those 12 months that are Class A on the last 3;
    DEC-38, adopted by the team as DEC-42; not confirmed by the Technical Adviser) and 'single' for Del Monte;
  * the Dashboard's tier cards (abc_mix, tier_stock) rank the date range the picker applies with a plain Pareto
    (backend/marts.pareto; the Technical Adviser's request of 2026-10-04).

For Unilever as of 2026-02 that is 189 against 175 Tier A products (the 14 are products first sold within 12 months).
This module only labels; it changes no number and no query.
"""
from __future__ import annotations

from analytics.params import TIER_A_BASIS, TIER_A_BASIS_WINDOW_MONTHS, TIER_A_NEW_PRODUCT_WINDOW_MONTHS, abc_method

_NAMES = {
    "t12m_new": (f"Class A on the last {TIER_A_BASIS_WINDOW_MONTHS} months of revenue, plus products first sold within "
                 f"those {TIER_A_BASIS_WINDOW_MONTHS} months that are Class A on the last {TIER_A_NEW_PRODUCT_WINDOW_MONTHS} "
                 "(team decision, DEC-42; not confirmed by SSM or the adviser)"),
    "single": "Class A on the one classification month alone",
}


def planning_basis(principals=("unilever", "delmonte")) -> dict[str, dict]:
    """The Tier A basis the ABC page, the SKU list and the order plan use, per principal."""
    return {who: {"method": abc_method(who), "label": _NAMES[abc_method(who)]} for who in principals}


def abc_page_basis(principal: str | None) -> dict:
    """The `basis` field of GET /abc."""
    who = ("unilever", "delmonte") if principal in (None, "all") else (principal,)
    return {"kind": "classification_run", "by_principal": planning_basis(who),
            "also_used_by": "the SKU list and the order plan (LP)"}


def dashboard_basis(range_text: str | None) -> dict:
    """The `abc_basis` field of GET /dashboard: what its tier cards (abc_mix, tier_stock) were ranked on."""
    return {
        "kind": "range_pareto",
        "method": "range_pareto",
        "label": f"Class A on net sales over {range_text}, a plain Pareto of the range on screen" if range_text
                 else "Class A on net sales over the range on screen, a plain Pareto of the range",
        "applies_to": ["abc_mix", "tier_stock"],
        "planning_basis": planning_basis(),
        "differs_from_planning_basis": TIER_A_BASIS != "single",
        "note": ("The ABC page and the order plan count Unilever Tier A on '" + TIER_A_BASIS + "', which also holds "
                 "products first sold within the last 12 months; these cards rank the range alone, so they hold fewer "
                 "(as of 2026-02: 175 here, 189 there)."),
    }
