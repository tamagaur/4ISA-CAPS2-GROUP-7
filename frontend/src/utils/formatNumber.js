// Stock quantities (safety stock, reorder point, order quantity) come out of
// the formulas with decimals (41,713.61 units), but nobody stocks or orders
// a fraction of a unit, and a column mixing 9,818,339.99 with 9,818,340
// reads as noise. Tables show whole units, rounded UP: a buffer or order
// that rounds down would fall just short of what the formula asked for.
// The unrounded value stays available through exactUnits() for tooltips.

// Formula outputs carry float noise (1782.0000000002), which a bare ceil
// would bump to the next unit.
const EPSILON = 1e-6;

export function wholeUnits(value) {
  if (value == null || Number.isNaN(Number(value))) return null;
  // `+ 0` turns -0 (ceil of 0 minus epsilon) into 0, which would
  // otherwise print as "-0".
  return Math.ceil(Number(value) - EPSILON) + 0;
}

export function formatUnits(value) {
  const units = wholeUnits(value);
  return units == null ? '—' : units.toLocaleString();
}

export function exactUnits(value) {
  if (value == null || Number.isNaN(Number(value))) return undefined;
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} pcs (exact)`;
}

// A big count rounded for reading (2026-10-20): 10,000 or more to the nearest
// 1,000, 1,000-9,999 to the nearest 100, under 1,000 as is. The exact figure
// goes in a hover (components/ExactValue.jsx) and in table views.
export function approxCount(value) {
  if (value == null || Number.isNaN(Number(value))) return null;
  const v = Number(value);
  const a = Math.abs(v);
  const step = a >= 10000 ? 1000 : a >= 1000 ? 100 : 1;
  return Math.round(v / step) * step;
}

export function formatApprox(value) {
  const n = approxCount(value);
  return n == null ? '—' : n.toLocaleString();
}
