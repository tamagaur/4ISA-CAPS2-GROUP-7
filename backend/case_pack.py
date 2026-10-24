"""
backend/case_pack.py — a planner's quantity must be a whole number of case packs (audit finding 4, 2026-10-23).

Since 2026-10-22 every planned order is a whole number of cases (analytics/optimization/lp.round_to_case_packs, run by
scripts/run_lp.py). The edit paths took any number: 6,192 pieces was applied on a 288-piece pack (21.5 cases) and 5 on
a pack of 288. They now REFUSE such a quantity (HTTP 422, code `not_whole_cases`) and say the two whole-case
quantities either side of it. Refusing rather than rounding, because the planner typed a number to order: silently
turning 6,192 into 6,048 or 6,336 would record a decision the planner did not make. The LP rounds because nobody typed
its number.

The rule is the LP's: a pack of 1 or less, or no usable pack size, is not checked (the LP leaves those unchanged), and
a quantity within PACK_TOLERANCE pieces of a whole pack counts as whole. 0 is a whole number of cases. A quantity equal
to the recommendation is no edit and is not checked (an old row written before the rounding may sit off-pack).
"""
from __future__ import annotations

from backend.api_errors import ApiError
from backend.stock_units import PACK_SIZE_NUMERIC

PACK_TOLERANCE = 1e-6   # pieces; the same tolerance as analytics/optimization/lp.PACK_TOLERANCE

# Product_Dimension.pack_size as a number (NULL when it is not one), for a query aliased `pd`.
PACK_SQL = f"CASE WHEN {PACK_SIZE_NUMERIC.replace('pd_pack.', 'pd.')} THEN pd.pack_size::numeric END"


def check_whole_cases(quantity: float, pack, recommended=None) -> None:
    """Raise ApiError(422, code='not_whole_cases') unless `quantity` is a whole number of `pack`-piece cases."""
    if pack is None:
        return
    pack = float(pack)
    quantity = float(quantity)
    if pack <= 1 or (recommended is not None and round(quantity, 2) == round(float(recommended), 2)):
        return
    cases = quantity / pack
    if abs(cases - round(cases)) * pack <= PACK_TOLERANCE:
        return
    below = float(int(cases)) * pack
    above = below + pack
    raise ApiError(
        422,
        f"{quantity:g} pieces is not a whole number of cases: a case is {pack:g} pieces, so {quantity:g} is "
        f"{cases:.2f} cases. Use {below:g} ({below / pack:g} cases) or {above:g} ({above / pack:g} cases).",
        code="not_whole_cases", pack_size=pack, quantity=quantity, nearest_below=below, nearest_above=above)
