import React, { useMemo } from 'react';
import {
  ComposedChart, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
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

// Instruction per tier — same for every principal, since the tier's meaning
// (not the grain) is what determines the action.
const TIER_INSTRUCTIONS = {
  A: 'Watch closely — never run out',
  B: 'Check monthly',
  C: "Don't tie up cash here",
};

// abc: { grain: 'sku' | 'category' | 'mixed', tiers: [{ tier, sku_count, revenue_share }] }
// Components branch on grain, never on the principal name — see the label
// and note below. Rendered as 3 horizontal bars rather than a curve: with
// only 3 tiers (as few as 12 items for Del Monte) a Pareto curve implies a
// SKU-count of data this widget doesn't have — that shape stays on the ABC
// Classification page, which has the real ranked per-row data to justify it.
export const ABCClassificationWidget = ({ abc }) => {
  const grain = abc?.grain ?? 'sku';
  const tiers = abc?.tiers ?? [];
  const unitLabel = grain === 'sku' ? 'SKUs' : grain === 'category' ? 'categories' : 'items';
  const showGrainNote = grain === 'category' || grain === 'mixed';

  return (
    <div className="chart-widget">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>ABC Classification</h4>
        </div>
        <div className="chart-header-right">
          <span style={{ fontSize: '0.75rem', color: '#a0aec0' }}>By revenue share</span>
        </div>
      </div>

      <div className="chart-container abc-bars">
        {tiers.map((t, i) => (
          <div className="abc-bar-row" key={t.tier}>
            <div className="abc-bar-header">
              <span className="abc-bar-label" style={{ color: CHART_COLORS.abcRamp[i] }}>Class {t.tier}</span>
              <span className="abc-bar-count">{t.sku_count} {unitLabel}</span>
              <span className="abc-bar-share">{t.revenue_share}% revenue</span>
            </div>
            <div className="abc-bar-track">
              <div className="abc-bar-fill" style={{ width: `${t.revenue_share}%`, backgroundColor: CHART_COLORS.abcRamp[i] }} />
            </div>
            <p className="abc-bar-instruction">{TIER_INSTRUCTIONS[t.tier]}</p>
          </div>
        ))}
      </div>

      {showGrainNote && (
        <p className="abc-grain-note">
          Del Monte is analysed at category level — no SKU-level data is available from this principal
        </p>
      )}
    </div>
  );
};

// Bad Order Trend — stacked bar chart by reason (Expiry / Transport Damage /
// Storage Issue). Source: SalesReturn_Fact grouped by (week, return_type).
// Colors are from the shared palette — deliberately not red, since red is
// reserved for chart-layer alert markers (policy reference lines, etc.).
// Expiry → amber (warning), Transport Damage → teal (dispatched),
// Storage Issue → violet (forecast). All three avoid status-tier red.
export const BadOrderTrendWidget = ({ badOrderSeries = [] }) => {
  const reasonLabels = {
    expiry:           'Expiry',
    transport_damage: 'Transport Damage',
    storage_issue:    'Storage Issue',
  };
  const reasonColors = {
    expiry:           COLORS.warning,    // amber
    transport_damage: COLORS.dispatched, // teal
    storage_issue:    COLORS.forecast,   // violet
  };

  const renderLegend = () => (
    <ul className="custom-legend" style={{ marginTop: '0.75rem' }}>
      {Object.entries(reasonLabels).map(([key, label]) => (
        <li key={key} className="legend-item">
          <span className="legend-color" style={{ backgroundColor: reasonColors[key] }} />
          {label}
        </li>
      ))}
    </ul>
  );

  return (
    <div className="chart-widget">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Bad Order Trend</h4>
          <p>Weekly bad order value (₱k) by incident reason — from SalesReturn records</p>
        </div>
      </div>

      <div className="chart-container" style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1 }}>
          <ResponsiveContainer width="99%" height="100%">
            <BarChart data={badOrderSeries} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
              <XAxis
                dataKey="period"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                dy={6}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                label={{ value: '₱k', angle: -90, position: 'insideLeft', fontSize: 10, fill: CHART_COLORS.axisLabel }}
              />
              <Tooltip
                contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                formatter={(value, name) => [`₱${value}k`, reasonLabels[name] || name]}
              />
              <Bar dataKey="expiry"           name="expiry"           stackId="bo" fill={reasonColors.expiry}           isAnimationActive={false} />
              <Bar dataKey="transport_damage" name="transport_damage" stackId="bo" fill={reasonColors.transport_damage} isAnimationActive={false} />
              <Bar dataKey="storage_issue"    name="storage_issue"    stackId="bo" fill={reasonColors.storage_issue}    radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        {renderLegend()}
      </div>
    </div>
  );
};
