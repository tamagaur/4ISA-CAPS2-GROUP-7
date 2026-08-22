import React, { useMemo } from 'react';
import {
  ComposedChart, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, ReferenceLine
} from 'recharts';
import { CHART_COLORS, STATUS_TIERS, COLORS } from '../theme/colors';
import './Charts.css';

// coverSeries: [{ period, weeks_of_cover }] from getDashboardData(). Single
// series (not the old dual sales-vs-stock mock) because that's the only
// per-period trend the dashboard API actually provides — the previous
// "Sales Velocity vs Stock-on-Hand" chart plotted two series that have no
// home in that response shape, so it's been replaced rather than left
// permanently disconnected from real data.
export const CoverTrendWidget = ({ coverSeries = [], policyTarget }) => {
  const target = typeof policyTarget === 'number' ? policyTarget : 0;

  // Shading should only cover the excess above the policy line — the whole
  // point of the chart is "how much more stock than the rule allows" — so
  // this splits each point into an invisible base (up to the target) and a
  // visible excess on top of it (stacked back together), rather than a
  // single area that fills from zero and shades stock that's already fine.
  const chartData = useMemo(
    () => coverSeries.map((point) => ({
      ...point,
      base: Math.min(point.weeks_of_cover, target),
      excess: Math.max(0, point.weeks_of_cover - target),
    })),
    [coverSeries, target]
  );

  return (
    <div className="chart-widget">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Weeks of Cover Trend</h4>
          <p>How long current stock would last at the recent sales pace</p>
        </div>
      </div>

      <div className="chart-container">
        <ResponsiveContainer width="99%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 20, right: 20, left: 0, bottom: 35 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
            <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: CHART_COLORS.axisLabel}} dy={10} />
            <YAxis
              axisLine={false}
              tickLine={false}
              tick={{fontSize: 10, fill: CHART_COLORS.stockSeries}}
              label={{ value: 'Weeks', angle: -90, position: 'insideLeft', fontSize: 10, fill: CHART_COLORS.axisLabel }}
            />
            <Tooltip
              contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
              formatter={(value, name) => (name === 'weeks_of_cover' ? [`${value} weeks`, 'Weeks of cover'] : [null, null])}
            />
            <Area type="monotone" dataKey="base" stackId="cover" stroke="none" fill="transparent" isAnimationActive={false} />
            <Area type="monotone" dataKey="excess" stackId="cover" name="Excess over policy" stroke="none" fill={CHART_COLORS.stockSeries} fillOpacity={0.18} isAnimationActive={false} />
            {typeof policyTarget === 'number' && (
              <ReferenceLine
                y={policyTarget}
                stroke={STATUS_TIERS.loss}
                strokeDasharray="4 4"
                label={{ value: `Policy target: ${policyTarget}w`, position: 'insideTopRight', fontSize: 10, fill: CHART_COLORS.axisLabel }}
              />
            )}
            <Area
              type="monotone"
              dataKey="weeks_of_cover"
              name="weeks_of_cover"
              stroke={CHART_COLORS.stockSeries}
              fill="none"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

// ₱500k / ₱1.2M / ₱0 — compact currency, unsigned (callers prepend a sign
// where one is needed). Shared by the axis ticks and the bar-end labels so
// the two can never disagree on formatting.
function formatCompactPesos(value) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    const millions = abs / 1_000_000;
    return `₱${Number.isInteger(millions) ? millions : millions.toFixed(1)}M`;
  }
  if (abs >= 1_000) return `₱${Math.round(abs / 1000)}k`;
  return `₱${Math.round(abs)}`;
}

const AllocationTooltip = ({ active, payload }) => {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  const shortfall = row.variancePesos < 0;
  return (
    <div style={{
      backgroundColor: '#ffffff', border: '1px solid #e2e8f0', padding: '0.6rem 0.8rem',
      borderRadius: '8px', boxShadow: '0 4px 15px rgba(0, 0, 0, 0.08)',
    }}>
      <p style={{ fontWeight: 700, color: '#1a202c', margin: '0 0 0.3rem 0', fontSize: '0.8rem' }}>{row.sku}</p>
      <p style={{ margin: '0.1rem 0', fontSize: '0.75rem', color: '#4a5568' }}>Allocation: {row.allocationCases} cases</p>
      <p style={{ margin: '0.1rem 0', fontSize: '0.75rem', color: '#4a5568' }}>Forecast: {row.forecastCases} cases</p>
      <p style={{
        margin: '0.35rem 0 0 0', fontSize: '0.78rem', fontWeight: 700,
        color: shortfall ? COLORS.critical : COLORS.warning,
      }}>
        {shortfall ? '−' : '+'}{Math.abs(row.varianceCases)} cases · {shortfall ? '−' : '+'}{formatCompactPesos(row.variancePesos)}
      </p>
    </div>
  );
};

// Tighter than a typical single-purpose bar chart on purpose: showing
// every shortfall (Fix 2) can put up to 12 rows in this chart for "All
// principals", and the page still has to fit a 900px-tall viewport with
// no scroll, so per-row height has to shrink as the row count can grow.
const BAR_HEIGHT = 16;
const BAR_GAP = 6;

// Round outer tick candidates (each with a clean half, e.g. 600000 -> its
// own ticks land on 300000) — picking from this list instead of scaling
// the raw data max is what keeps the axis reading "₱600k / ₱300k / ₱0"
// instead of an arbitrary "₱646k / ₱270k / ₱0".
const NICE_OUTER_TICKS = [
  50_000, 100_000, 150_000, 200_000, 300_000, 400_000, 600_000, 800_000,
  1_000_000, 1_500_000, 2_000_000, 3_000_000, 5_000_000, 7_500_000, 10_000_000,
];
function niceOuterTick(maxAbs) {
  const padded = maxAbs * 1.1;
  return NICE_OUTER_TICKS.find((t) => t >= padded) || Math.ceil(padded / 1_000_000) * 1_000_000;
}

// Allocation vs Forecast — diverging horizontal bar, one bar per SKU
// centred on a zero axis. Left/negative = allocation is below forecast
// (shortfall, stockout risk, red); right/positive = allocation exceeds
// forecast (excess, trapped capital, amber). Sorted defensively here (not
// just trusting mockData's own ordering) by signed peso variance ascending
// — most-negative first, most-positive last — so the bars always taper
// into a clean arrow instead of zigzagging, regardless of what order the
// data happens to arrive in.
//
// classACount comes from the caller (it isn't in `rows` itself, which is
// already capped to the top 5 by impact) and drives the "N products in
// total" caption below the chart — the chart's job is scale, not detail:
// no bar-end value labels (the exact peso figures live in the "Accept
// less"/"Request more" cards below instead, so they aren't duplicated
// here) and no per-side axis captions.
export const AllocationVarianceWidget = ({ rows = [], classACount }) => {
  const sortedRows = [...rows].sort((a, b) => a.variancePesos - b.variancePesos);

  const values = sortedRows.map((r) => r.variancePesos);
  const maxAbsValue = Math.max(1, ...values.map((v) => Math.abs(v)));
  const outerTick = niceOuterTick(maxAbsValue);
  const domain = [-outerTick, outerTick];
  const axisTicks = [-outerTick, -outerTick / 2, 0, outerTick / 2, outerTick];
  const tickFormatter = (v) => (v < 0 ? `−${formatCompactPesos(v)}` : formatCompactPesos(v));

  const plotHeight = sortedRows.length * (BAR_HEIGHT + BAR_GAP);
  const chartHeight = plotHeight + 40; // + room for the x-axis tick row

  return (
    <div className="chart-widget">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Supply versus demand</h4>
          <p>Comparing what suppliers offered against what demand requires</p>
        </div>
      </div>

      <div className="chart-container">
        <ResponsiveContainer width="99%" height={chartHeight}>
          <BarChart
            data={sortedRows}
            layout="vertical"
            barSize={BAR_HEIGHT}
            barCategoryGap={BAR_GAP}
            margin={{ top: 10, right: 60, left: 0, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={CHART_COLORS.gridline} />
            <XAxis
              type="number"
              domain={domain}
              ticks={axisTicks}
              tickFormatter={tickFormatter}
              tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="sku"
              width={190}
              tick={{ fontSize: 11, fill: '#4a5568', textAnchor: 'end' }}
              tickMargin={6}
              axisLine={false}
              tickLine={false}
            />
            <ReferenceLine x={0} stroke="#cbd5e0" />
            <Tooltip content={<AllocationTooltip />} />
            <Bar dataKey="variancePesos" radius={[3, 3, 3, 3]} isAnimationActive={false}>
              {sortedRows.map((r) => (
                <Cell key={r.sku} fill={r.variancePesos < 0 ? COLORS.critical : COLORS.warning} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {typeof classACount === 'number' && (
        <p className="allocation-subset-caption">{classACount} products in total</p>
      )}
    </div>
  );
};
