// The ₱ axis of a line chart: a floor just under the lowest value, explicit
// ticks (2026-10-19, out of Charts.jsx so the forecast card's chart can
// share the Sales vs Inventory Value chart's scale rule).

// The plot's floor: 90% of the lowest visible value, rounded down to ₱5M,
// never below zero. With every value between ₱10M and ₱40M a zero floor
// spent half the card on empty space and flattened a ₱10M swing to a few
// pixels. The tick labels name the floor, so nothing is hidden.
export const yoyFloor = (min) => Math.max(0, Math.floor((min * 0.9) / 5e6) * 5e6);

// Explicit ticks, because Recharts' own "nice" ticks round the floor back
// down to zero: with a ₱10M step, a ₱5M floor becomes ₱0 again. Steps of
// ₱5M, or ₱10M once that would be more than eight ticks. Recomputed from
// whatever is visible, so the scale follows the metric control.
export const pesoTicks = (values) => {
  const present = values.filter((v) => v != null);
  if (!present.length) return null;
  // Small figures (returns run under ₱1M a month): ₱5M steps would lay them
  // flat along zero, so the step shrinks to a round one that gives about
  // five gridlines, from ₱0 (2026-10-19).
  const top = Math.max(...present);
  if (top < 10e6) {
    const magnitude = 10 ** Math.floor(Math.log10(Math.max(top, 1) / 5));
    const fine = ([1, 2, 2.5, 5, 10].find((f) => f * magnitude >= top / 5) || 10) * magnitude;
    return Array.from({ length: Math.ceil(top / fine) + 1 }, (_, i) => i * fine);
  }
  const lo = yoyFloor(Math.min(...present));
  const hi = Math.ceil(Math.max(...present) / 5e6) * 5e6;
  const step = (hi - lo) / 5e6 > 8 ? 1e7 : 5e6;
  const ticks = [];
  for (let v = lo; v <= hi + 1; v += step) ticks.push(v);
  if (ticks[ticks.length - 1] < hi) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
};
