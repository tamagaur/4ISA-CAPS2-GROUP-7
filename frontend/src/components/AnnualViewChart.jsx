// "Annual View: 5-Year Trend vs. FY26 Target Band" — the left card of the
// dashboard's "What happened?" row (layout pass, 2026-10-12). One bar per
// fiscal year, the base year in navy, the year being planned in orange, and
// the target band the allocation rule would set above the base year.
//
// LAYOUT PREVIEW ONLY. Every number on this card comes from MOCK_ANNUAL_VIEW
// below and is not a measured result. The fiscal-year totals, the FY26
// pace projection, the target band's rule and the date ranges behind them
// are pending further instructions; when they arrive, the mock constant is
// replaced by a prop built from GET /dashboard and nothing else here needs
// to know. Nothing on this card reads the date filter, the comparison
// setting or any API response.
import React from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { CHART_COLORS } from '../theme/colors';
import { formatCompactPesos } from '../utils/formatters';
import { GRID_PROPS } from './ChartZoom';
import './AnnualViewChart.css';

// ---- TEMPORARY MOCK DATA — replace with calculated results -----------------
// Placeholder figures so the card can be designed; they are not SSM's
// numbers and are not derived from the database. The band is a stand-in for
// "base year × 103% to 108%", itself still an assumption pending SSM.
export const MOCK_ANNUAL_VIEW = {
  years: [
    { key: 'FY22', label: 'FY22', value: 288_000_000, role: 'history' },
    { key: 'FY23', label: 'FY23', value: 312_000_000, role: 'history' },
    { key: 'FY24', label: 'FY24', value: 341_000_000, role: 'history' },
    { key: 'FY25', label: 'FY25 (Base)', value: 368_000_000, role: 'base' },
    { key: 'FY26', label: 'FY26 Pace (Projected)', value: 355_000_000, role: 'projected' },
  ],
  target: { low: 379_000_000, high: 397_400_000, line: 379_000_000, label: 'Target band 103–108%' },
};
// ---------------------------------------------------------------------------

// Muted slate for history, the dashboard's navy for the base year, orange
// for the year being planned (the one bar that is a projection).
const BAR_COLOR = { history: '#8FA3C4', base: CHART_COLORS.heroInventory, projected: '#F28C28' };

const AnnualTooltip = ({ active, payload }) => {
  const row = active && payload?.[0]?.payload;
  if (!row) return null;
  return (
    <div className="chart-tooltip">
      <p className="tooltip-label">{row.label}</p>
      <p className="tooltip-item">{formatCompactPesos(row.value)}</p>
      {row.role === 'projected' && <p className="tooltip-item annual-tooltip-note">Projected · mock value</p>}
    </div>
  );
};

const AnnualViewChart = ({ data = MOCK_ANNUAL_VIEW, mock = data === MOCK_ANNUAL_VIEW }) => {
  const rows = data.years;
  const target = data.target;
  const top = Math.max(...rows.map((r) => r.value), target?.high ?? 0);
  // Headroom for the labels above the bars, on a round ₱100M step.
  const step = 100_000_000;
  const ceiling = Math.ceil((top * 1.12) / step) * step;
  const ticks = Array.from({ length: ceiling / step + 1 }, (_, i) => i * step);

  return (
    <div className="chart-widget annual-view">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Annual View: 5-Year Trend vs. FY26 Target Band</h4>
        </div>
        {mock && (
          <span className="annual-view-mock" title="Layout preview: these figures are placeholders, not SSM's data">
            Mock data
          </span>
        )}
      </div>
      <div className="annual-view-legend" aria-hidden="true">
        <span><i style={{ backgroundColor: BAR_COLOR.history }} />Past years</span>
        <span><i style={{ backgroundColor: BAR_COLOR.base }} />Base year</span>
        <span><i style={{ backgroundColor: BAR_COLOR.projected }} />Projected pace</span>
        <span><i className="annual-view-legend-band" />{target?.label || 'Target band'}</span>
      </div>
      <div className="chart-container annual-view-plot">
        <ResponsiveContainer width="99%" height="100%">
          <BarChart data={rows} margin={{ top: 22, right: 12, left: 4, bottom: 4 }} barCategoryGap="28%">
            <CartesianGrid {...GRID_PROPS} vertical={false} />
            <XAxis
              dataKey="key"
              tickLine={false}
              axisLine={{ stroke: CHART_COLORS.gridline }}
              tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
            />
            <YAxis
              domain={[0, ceiling]}
              ticks={ticks}
              tickFormatter={(v) => formatCompactPesos(v)}
              tickLine={false}
              axisLine={false}
              width={58}
              tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
            />
            <Tooltip content={<AnnualTooltip />} cursor={{ fill: 'rgba(148, 163, 184, 0.12)' }} />
            {/* The band's name sits above its top edge; the bars' value
                labels sit below the band, so the two never meet. */}
            {target && (
              <ReferenceArea
                y1={target.low}
                y2={target.high}
                fill="#F28C28"
                fillOpacity={0.1}
                stroke="none"
                label={{ value: target.label, position: 'top', fill: '#C2410C', fontSize: 10, offset: 4 }}
              />
            )}
            {target && <ReferenceLine y={target.line} stroke="#C2410C" strokeDasharray="5 4" />}
            <Bar dataKey="value" radius={[6, 6, 0, 0]} maxBarSize={56} isAnimationActive={false}>
              {rows.map((r) => <Cell key={r.key} fill={BAR_COLOR[r.role] || BAR_COLOR.history} />)}
              <LabelList dataKey="value" position="top" formatter={(v) => formatCompactPesos(v)} fill="#344054" fontSize={11} fontWeight={600} offset={6} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default AnnualViewChart;
