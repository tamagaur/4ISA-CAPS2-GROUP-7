import React from 'react';
import { ReferenceArea } from 'recharts';
import { CHART_COLORS } from '../theme/colors';
import { isPlaceholderPeriod } from '../dataMode';

// Placeholder months in preview mode (src/dataMode.js): one light neutral
// band behind them, named in the plot, and by each chart's legend and
// tooltip too, so the marking never rests on colour alone. `placeholder` is
// the payload's own data_mode.placeholder window — nothing here decides
// which months are placeholder.

/** First and last placeholder period among `points`, or null if none. */
export const placeholderSpan = (points, placeholder) => {
  const inside = points.filter((pt) => isPlaceholderPeriod(pt.period, placeholder));
  return inside.length ? { x1: inside[0].period, x2: inside[inside.length - 1].period } : null;
};

// A plain function, not a component, so the ReferenceArea stays a direct
// child of the chart. fillOpacity is mirrored by the legend swatches'
// color-mix (Charts.css .legend-placeholder, CategoryTrends.css).
export const renderPlaceholderBand = (span) => span && (
  <ReferenceArea
    x1={span.x1}
    x2={span.x2}
    fill={CHART_COLORS.placeholder}
    fillOpacity={0.16}
    stroke="none"
    ifOverflow="hidden"
    label={{ value: 'Placeholder data', position: 'insideTopLeft', fill: CHART_COLORS.axisLabel, fontSize: 10, fontWeight: 600 }}
  />
);
