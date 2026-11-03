// The one design every line graph wears (Audrey, 2026-11-03: "i want them all
// uniform so they have only 1 design"), taken from the Dashboard's forecast
// card. A change to how lines look is made here, once. No CSS is imported, so
// the KPI cards' sparkline can use this without pulling in the chart styles.
//
//   Measured figures  a solid 3px line, smooth (monotone: through every
//                     month's value, never past it), with the shade beneath.
//   Forecast          dashed, 2.5px.
//   Comparison        dashed, 2px (the same months earlier, a trend line).
//   Shade             the line's own colour, from LINE_SHADE_FROM at the top
//                     to LINE_SHADE_TO at the axis floor. One to a chart:
//                     two washes turn muddy where the lines cross (design pass
//                     2026-09-26), and a dash means "projected" or "for
//                     comparison", so dashed lines wear none. A floor can sit
//                     above zero (utils/pesoTicks), so the shade shows the
//                     line's shape, never an amount.
//   Dots              a ringed dot on the last point of a measured or forecast
//                     line and on a month with no neighbour (it has no line of
//                     its own), and the same dot with a halo on hover. Dots
//                     that say something stay on top of this: a stock count to
//                     check, SSM's own month against a generated one, each
//                     reported month on an axis that leaves months out.
import React, { useId } from 'react';

export const LINE_SHADE_FROM = 0.26;
export const LINE_SHADE_TO = 0.02;

const LINE_BASE = { type: 'monotone', strokeLinecap: 'round', strokeLinejoin: 'round' };
export const SOLID_LINE = { ...LINE_BASE, strokeWidth: 3 };
export const FORECAST_LINE = { ...LINE_BASE, strokeWidth: 2.5, strokeDasharray: '5 3' };
export const COMPARISON_LINE = { ...LINE_BASE, strokeWidth: 2, strokeDasharray: '5 4' };

// An Area that draws the shade alone, for a chart that keeps its solid series
// a Line. Recharts draws every Area under the bars and every Line over them,
// so a line that must stay on top of bars or a band cannot carry its own fill.
// No dot, no hover entry: the Line beside it has both.
export const SHADE_ONLY = {
  type: 'monotone',
  stroke: 'none',
  dot: false,
  activeDot: false,
  legendType: 'none',
  tooltipType: 'none',
  isAnimationActive: false,
};

// Gradient ids are global to the document, and some of these charts appear
// twice on a page (Category Trends, one per principal). The characters React
// puts in an id are left out so the id stays plain inside url(#...).
export const useLineShadeId = () => `line-shade-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;

// For a chart's <defs>; the series then takes fill={`url(#${id})`}.
export const LineShade = ({ id, color }) => (
  <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stopColor={color} stopOpacity={LINE_SHADE_FROM} />
    <stop offset="100%" stopColor={color} stopOpacity={LINE_SHADE_TO} />
  </linearGradient>
);

const DOT_RADIUS = 4.5;
const RingedDot = ({ cx, cy, color }) => (
  <circle cx={cx} cy={cy} r={DOT_RADIUS} fill={color} stroke="var(--color-surface, #fff)" strokeWidth={2} />
);

// For a Line's or an Area's `activeDot`. Recharts passes the series' colour as `fill`.
export const lineHoverDot = ({ cx, cy, fill }) => (
  cx == null || cy == null ? null : (
    <g>
      <circle cx={cx} cy={cy} r={9} fill={fill} fillOpacity={0.16} />
      <RingedDot cx={cx} cy={cy} color={fill} />
    </g>
  )
);

// A line's end, where its latest value is read. For a Line's or an Area's `dot`.
export const endDot = (color, lastIndex) => ({ cx, cy, index }) => (
  index === lastIndex && cx != null && cy != null
    ? <RingedDot key={`end-${index}`} cx={cx} cy={cy} color={color} />
    : null
);

// The same, for a line that can have gaps: its last point, wherever that is,
// and any month with no neighbour, whose dot is all there is of it. `everyPoint`
// is for an axis that leaves months out (Del Monte's months nobody collected):
// one stretch of line can then span several months, and only a dot on each
// point says which months were reported.
export const lineDots = (color, { everyPoint = false } = {}) => ({ cx, cy, index, points }) => {
  if (cx == null || cy == null) return null;
  const has = (i) => points?.[i]?.y != null;
  let last = (points?.length ?? 0) - 1;
  while (last >= 0 && !has(last)) last -= 1;
  return everyPoint || index === last || (!has(index - 1) && !has(index + 1))
    ? <RingedDot key={`dot-${index}`} cx={cx} cy={cy} color={color} />
    : null;
};
