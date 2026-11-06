// The one motion every graph in the app wears (2026-11-06: "make the graphs
// load with an animation … uniform in motion").
//
// Every graph enters the same way, on every tab:
//   - lines and areas sweep in from the left;
//   - bars grow from their baseline (up, or rightward for a horizontal bar);
//   - all of it over CHART_ANIM_DURATION, on the CHART_ANIM_EASING curve,
//     starting CHART_ANIM_DELAY after the card frame starts to rise, each
//     further series of one chart CHART_ANIM_STAGGER later.
//
// Two layers carry it, with the same four values:
//   - Recharts series spread chartAnim(i) (or ChartZoom's zoomAnim(i), which
//     is chartAnim held still while a slider is being dragged);
//   - hand-built bars (HTML spans, small SVGs) take the class chart-grow-x,
//     chart-grow-y, chart-grow-mid or chart-sweep (index.css), which read the
//     --chart-draw-* custom properties on :root.
// theme/motion.test.js fails if the two sets of values drift apart, or if a
// Recharts series is drawn without chartAnim/zoomAnim (Recharts' own default
// is 1500ms on a different curve, so a forgotten one moves differently).
//
// Recharts animates on mount AND whenever `data` changes, so the same props
// cover the entrance when a page opens and the re-draw when a filter changes
// under a chart that stays mounted. The hand-built bars replay through
// useEntranceReplay's data-enter-cycle (index.css).

// Long enough to read as deliberate, short enough not to delay someone
// scanning numbers.
export const CHART_ANIM_DURATION = 700;

// Decelerating: quick to start, settles gently. Written as a cubic-bezier,
// not a keyword, on purpose: Recharts' 'ease-out' is not CSS's (Recharts maps
// it to 0.42, 0, 0.58, 1, which is CSS's ease-in-out), so a keyword would
// move the Recharts graphs and the CSS bars differently. A cubic-bezier
// string means the same curve to both.
export const CHART_ANIM_EASING = 'cubic-bezier(0.22, 1, 0.36, 1)';

// The card frame fades and rises first (chart-card-enter, index.css); the
// marks start once it is mostly in, so the start of the draw is not spent
// behind a transparent card.
export const CHART_ANIM_DELAY = 150;

// Per-series stagger: on a chart with several series, each starts a little
// after the one before, so the chart reads as one build instead of
// everything lurching at once.
export const CHART_ANIM_STAGGER = 90;

// The stagger stops growing after this many steps, so a chart with many
// series does not keep someone waiting for its last one.
export const CHART_ANIM_MAX_STEPS = 3;

// Checked at call time rather than module load, so a viewer who changes
// the OS setting mid-session gets the new behavior on the next render
// without a reload.
export const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// When series `seriesIndex` of a chart starts to draw, in ms.
export const chartAnimBegin = (seriesIndex = 0) =>
  CHART_ANIM_DELAY + Math.min(Math.max(seriesIndex, 0), CHART_ANIM_MAX_STEPS) * CHART_ANIM_STAGGER;

// Spread onto every Recharts <Line>/<Area>/<Bar>/<Pie>:
//     <Bar dataKey="x" {...chartAnim()} />
//     <Line dataKey="y" {...chartAnim(1)} />   // second series, staggered
//
// Series that move together (a stack, a line and its own shade, a band and
// its invisible base) take the same index. Animation is switched off
// entirely (not merely shortened) when the viewer has asked for reduced
// motion: an animated chart is exactly the kind of large-area movement that
// setting exists to suppress.
export const chartAnim = (seriesIndex = 0) => {
  if (prefersReducedMotion()) {
    return { isAnimationActive: false };
  }
  return {
    isAnimationActive: true,
    animationDuration: CHART_ANIM_DURATION,
    animationBegin: chartAnimBegin(seriesIndex),
    animationEasing: CHART_ANIM_EASING,
  };
};
