// Shared motion tokens for charts.
//
// Every Recharts series in the app used to carry a hardcoded
// `isAnimationActive={false}` (28 of them across Charts.jsx,
// ABCClassification.jsx, BadOrders.jsx and SKUForecast.jsx), so charts
// snapped into place with no transition — on first paint and on every
// date/filter change alike. These helpers turn that back on with ONE set
// of timings, so a future tweak is a single edit here rather than 28.
//
// Recharts animates on mount AND whenever the underlying `data` array
// changes, so the same props cover both cases the UI needs: the entrance
// when a page opens, and the re-draw when the date range or a filter
// changes underneath an already-mounted chart.

// Long enough to read as deliberate, short enough not to delay someone
// scanning numbers. Bars/areas sweep in over this; lines draw over it.
export const CHART_ANIM_DURATION = 700;

// Decelerating: quick to start, settles gently. Matches the cubic-bezier
// easing the modals/toasts already use for their entrances.
export const CHART_ANIM_EASING = 'ease-out';

// Per-series stagger. On a stacked or multi-series chart, offsetting each
// series slightly reads as one coordinated build instead of everything
// lurching at once.
export const CHART_ANIM_STAGGER = 90;

// Checked at call time rather than module load, so a viewer who changes
// the OS setting mid-session gets the new behavior on the next render
// without a reload.
export const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Spread onto any Recharts <Line>/<Area>/<Bar>/<Pie>:
//     <Bar dataKey="x" {...chartAnim()} />
//     <Bar dataKey="y" {...chartAnim(1)} />   // second series, staggered
//
// `seriesIndex` drives the stagger. Animation is switched off entirely
// (not merely shortened) when the viewer has asked for reduced motion —
// an animated chart is exactly the kind of large-area movement that
// setting exists to suppress.
export const chartAnim = (seriesIndex = 0) => {
  if (prefersReducedMotion()) {
    return { isAnimationActive: false };
  }
  return {
    isAnimationActive: true,
    animationDuration: CHART_ANIM_DURATION,
    animationBegin: seriesIndex * CHART_ANIM_STAGGER,
    animationEasing: CHART_ANIM_EASING,
  };
};
