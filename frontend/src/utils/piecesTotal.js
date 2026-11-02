// The pieces total over a list of order rows (the Dashboard's Suggested
// orders strip, 2026-10-24): each row rounded up to a whole piece exactly as
// its own cell shows it (formatNumber.wholeUnits), then added, the backend's
// rule for the plan total. Rounding the sum instead could print a total 1-2
// pieces short of the figures listed above it.
//
// A row without a quantity shows "—", not 0, so a total over it would be a
// sum with a gap in it: the result is null and the caller leaves it out.
import { wholeUnits } from './formatNumber.js';

export const shownPiecesTotal = (rows = [], qty = (r) => r?.orderQty) => {
  let total = 0;
  for (const r of rows || []) {
    const v = qty(r);
    if (typeof v !== 'number' || !Number.isFinite(v)) return null;
    total += wholeUnits(v);
  }
  return total;
};
