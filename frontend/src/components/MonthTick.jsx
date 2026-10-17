// A month-axis tick in two lines: the month, and its year under it (Audrey,
// 2026-10-11) — "Mar" over "2025" rather than "Mar · 2025" or "Mar '25" on
// one line, so the months read across and the year is found straight below.
// The Dashboard's forecast card does the same with one bracket per year
// (Charts.jsx's MonthYearTick); this is the plain tick for every other
// month axis.
//
// Recharts calls it with the tick's position (x, y) and value. `period`
// turns that value into 'YYYY-MM' (or 'YYYY-MM-DD') when the axis is keyed
// by something else, such as a row index. `showYear` leaves the year off a
// tick, for an axis that draws every month and names the year once.
import React from 'react';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// 'YYYY-MM' -> 'Mar'. Also the axis's tickFormatter: Recharts spaces the
// ticks by this text's width, and the two lines are about as wide.
export const monthName = (period) => {
  if (!period) return '';
  const num = String(period).split('-')[1];
  return MONTHS[Number(num) - 1] || num || '';
};

// The axis height two lines of ticks need, over one line's.
export const MONTH_TICK_EXTRA_HEIGHT = 14;

const MonthTick = ({
  x, y, payload, fontSize = 11, fill, dy = 0, period = (value) => value, showYear = () => true,
}) => {
  const p = period(payload?.value);
  if (!p) return null;
  const year = String(p).split('-')[0];
  return (
    <text x={x} y={y + dy} textAnchor="middle" fontSize={fontSize} fill={fill}>
      <tspan x={x} dy="0.8em">{monthName(p)}</tspan>
      {showYear(payload.value) && <tspan x={x} dy="1.25em">{year}</tspan>}
    </text>
  );
};

export default MonthTick;
