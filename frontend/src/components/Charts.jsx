import React, { useMemo } from 'react';
import {
  ComposedChart, BarChart, Bar, Cell, Line,
  PieChart, Pie,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, ReferenceLine
} from 'recharts';
import { CHART_COLORS, STATUS_TIERS, COLORS } from '../theme/colors';
import './Charts.css';

// Custom tooltip: "Wk 7 — 5.2 weeks (2.2 above policy)". wk is the point's
// 1-based position among the plotted (last-12) periods, not a calendar
// week — this is monthly data, "Wk" here just means "this plotted point".
const CoverTooltip = ({ active, payload, policyTarget }) => {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0].payload;
  if (point.weeks_of_cover === null || point.weeks_of_cover === undefined) return null;

  const diff = point.weeks_of_cover - policyTarget;
  const diffLabel = diff === 0 ? 'at policy' : `${Math.abs(diff).toFixed(1)} ${diff > 0 ? 'above' : 'below'} policy`;

  return (
    <div className="chart-tooltip">
      Wk {point.wk} — {point.weeks_of_cover.toFixed(1)} weeks ({diffLabel})
    </div>
  );
};

// coverSeries: [{ period, weeks_of_cover }] from getDashboardData().weeks_of_cover
// is null until the backend can compute it (needs a valuation column on
// inventory_fact that doesn't exist yet — same blocker as the "Cash tied
// up in stock" / "Stock above policy" KPI cards; all three unblock
// together). policyTarget should be the same inventory.policy_weeks value
// those cards use, so the reference line and the KPI card can never
// disagree about what "policy" means.
export const CoverTrendWidget = ({ coverSeries = [], policyTarget = 3 }) => {
  // X axis is the last 12 periods only, regardless of how many the API sends.
  const last12 = useMemo(() => coverSeries.slice(-12), [coverSeries]);

  const hasData = last12.length > 0 && last12.some((point) => point.weeks_of_cover !== null && point.weeks_of_cover !== undefined);

  // Shading should only cover the excess above the policy line — the whole
  // point of the chart is "how much more stock than the rule allows" — so
  // this splits each point into an invisible base (up to the target) and a
  // visible excess on top of it (stacked back together), rather than a
  // single area that fills from zero and shades stock that's already fine.
  // A null weeks_of_cover stays null in both — recharts renders that as a
  // gap, not a fabricated zero.
  const chartData = useMemo(
    () => last12.map((point, i) => {
      const w = point.weeks_of_cover;
      const missing = w === null || w === undefined;
      return {
        ...point,
        wk: i + 1,
        base: missing ? null : Math.min(w, policyTarget),
        excess: missing ? null : Math.max(0, w - policyTarget),
      };
    }),
    [last12, policyTarget]
  );

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>How long our stock lasts</h4>
          <p>Compared with our three-week rule</p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">Not available yet — inventory valuation has not been loaded</p>
      ) : (
        <>
          <div className="chart-container">
            <ResponsiveContainer width="99%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 20, right: 20, left: 0, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }} dy={10} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  domain={[0, 'auto']}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  label={{ value: 'Weeks of stock', angle: -90, position: 'insideLeft', fontSize: 10, fill: CHART_COLORS.axisLabel }}
                />
                <Tooltip content={<CoverTooltip policyTarget={policyTarget} />} />
                <Area type="monotone" dataKey="base" stackId="cover" stroke="none" fill="transparent" isAnimationActive={false} />
                <Area type="monotone" dataKey="excess" stackId="cover" fill={CHART_COLORS.stockSeries} fillOpacity={0.18} stroke="none" isAnimationActive={false} />
                <ReferenceLine
                  y={policyTarget}
                  stroke={STATUS_TIERS.loss}
                  strokeDasharray="4 4"
                  label={{ value: `our rule: ${policyTarget} weeks`, position: 'insideTopRight', fontSize: 10, fill: STATUS_TIERS.loss }}
                />
                <Area
                  type="monotone"
                  dataKey="weeks_of_cover"
                  stroke={CHART_COLORS.stockSeries}
                  fill="none"
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <ul className="custom-legend">
            <li className="legend-item">
              <span className="legend-line" style={{ borderTopColor: CHART_COLORS.stockSeries }} />
              Actual
            </li>
            <li className="legend-item">
              <span className="legend-line legend-line-dashed" style={{ borderTopColor: STATUS_TIERS.loss }} />
              Our rule
            </li>
          </ul>
        </>
      )}
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

const SalesStockTooltip = ({ active, payload, label, fixedAllocation }) => {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ margin: '0.1rem 0', color: p.color }}>
          {p.name}: {Math.round(p.value).toLocaleString()}
        </p>
      ))}
      {typeof fixedAllocation === 'number' && (
        <p style={{ margin: '0.25rem 0 0 0', color: STATUS_TIERS.diagnostic }}>
          Supplier allocation target: {fixedAllocation.toLocaleString()}
        </p>
      )}
    </div>
  );
};

// Sales vs. Stock on Hand — the dashboard's hero chart. `data` is
// [{ period, sales, stockOnHand }]; `fixedAllocation` is the single flat
// number suppliers commit to per year (the sketch's broken/dashed line) —
// stock on hand is expected to track at or above it, so it's drawn as one
// ReferenceLine rather than a per-period series.
export const SalesVsStockWidget = ({ data = [], fixedAllocation, emptyReason }) => {
  const hasData = data.length > 0;

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Sales vs. stock on hand</h4>
          <p>Compared against the suppliers&apos; fixed yearly allocation</p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No data available for this range'}</p>
      ) : (
        <>
          <div className="chart-container">
            <ResponsiveContainer width="99%" height="100%">
              <ComposedChart data={data} margin={{ top: 20, right: 20, left: 0, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }} dy={10} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  tickFormatter={(v) => Math.round(v).toLocaleString()}
                />
                <Tooltip content={<SalesStockTooltip fixedAllocation={fixedAllocation} />} />
                {typeof fixedAllocation === 'number' && (
                  <ReferenceLine
                    y={fixedAllocation}
                    stroke={STATUS_TIERS.diagnostic}
                    strokeDasharray="4 4"
                    label={{ value: 'Fixed allocation', position: 'insideTopRight', fontSize: 10, fill: STATUS_TIERS.diagnostic }}
                  />
                )}
                <Line
                  type="monotone"
                  dataKey="sales"
                  name="Sales"
                  stroke={CHART_COLORS.salesSeries}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="stockOnHand"
                  name="Stock on hand"
                  stroke={CHART_COLORS.stockSeries}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <ul className="custom-legend">
            <li className="legend-item">
              <span className="legend-line" style={{ borderTopColor: CHART_COLORS.salesSeries }} />
              Sales
            </li>
            <li className="legend-item">
              <span className="legend-line" style={{ borderTopColor: CHART_COLORS.stockSeries }} />
              Stock on hand
            </li>
            <li className="legend-item">
              <span className="legend-line legend-line-dashed" style={{ borderTopColor: STATUS_TIERS.diagnostic }} />
              Fixed allocation
            </li>
          </ul>
        </>
      )}
    </div>
  );
};

const ABC_TIER_COLORS = { A: COLORS.abcA, B: COLORS.abcB, C: COLORS.abcC };

const ABCDonutTooltip = ({ active, payload }) => {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.15rem 0' }}>Tier {row.tier}</p>
      <p style={{ margin: 0 }}>{row.count} SKUs · {row.sharePct.toFixed(0)}% of revenue</p>
    </div>
  );
};

// ABC classification donut — `data` is [{ tier: 'A'|'B'|'C', count, sharePct }].
// Center label shows the total SKU count across all tiers so the chart
// still reads at a glance without hovering any slice.
export const ABCDonutWidget = ({ data = [], emptyReason }) => {
  const hasData = data.length > 0;
  const total = data.reduce((sum, d) => sum + d.count, 0);

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>ABC classification</h4>
          <p>Products by revenue contribution</p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No ABC classification available'}</p>
      ) : (
        <>
          <div className="chart-container donut-container" style={{ position: 'relative' }}>
            <ResponsiveContainer width="99%" height="100%">
              <PieChart>
                <Pie
                  data={data}
                  dataKey="count"
                  nameKey="tier"
                  innerRadius="60%"
                  outerRadius="85%"
                  paddingAngle={2}
                  isAnimationActive={false}
                >
                  {data.map((d) => (
                    <Cell key={d.tier} fill={ABC_TIER_COLORS[d.tier] || CHART_COLORS.abcRamp[0]} />
                  ))}
                </Pie>
                <Tooltip content={<ABCDonutTooltip />} />
              </PieChart>
            </ResponsiveContainer>
            <div className="donut-center-label">
              <span className="donut-center-value">{total}</span>
              <span className="donut-center-caption">SKUs</span>
            </div>
          </div>
          <ul className="custom-legend">
            {data.map((d) => (
              <li className="legend-item" key={d.tier}>
                <span className="legend-color" style={{ backgroundColor: ABC_TIER_COLORS[d.tier] || CHART_COLORS.abcRamp[0] }} />
                Tier {d.tier} ({d.sharePct.toFixed(0)}%)
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
};

const STOCK_STATUS_COLORS = { deadStock: '#94A3B8', inStock: CHART_COLORS.stockSeries };

const CategoryStockTooltip = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>{label} · Tier {row.tier}</p>
      <p style={{ margin: '0.1rem 0', color: STOCK_STATUS_COLORS.inStock }}>In stock: {row.inStock.toLocaleString()}</p>
      <p style={{ margin: '0.1rem 0', color: STOCK_STATUS_COLORS.deadStock }}>Dead stock: {row.deadStock.toLocaleString()}</p>
    </div>
  );
};

// Category-tick label with a small ABC-tier chip underneath the category
// name, so the grouping-by-tier the sketch shows (A / B / C bands under
// the bars) survives without needing a second axis.
const CategoryTick = ({ x, y, payload, dataByCategory }) => {
  const row = dataByCategory[payload.value];
  if (!row) return null;
  return (
    <g transform={`translate(${x},${y})`}>
      <text dy={12} textAnchor="middle" fontSize={10} fill={CHART_COLORS.axisLabel}>{payload.value}</text>
      <text dy={26} textAnchor="middle" fontSize={9} fontWeight={700} fill={ABC_TIER_COLORS[row.tier] || CHART_COLORS.axisLabel}>
        Tier {row.tier}
      </text>
    </g>
  );
};

// Stacked stock matrix per category — `data` is
// [{ category, tier: 'A'|'B'|'C', deadStock, inStock }]. Stacked bar
// (dead stock beneath in-stock) so each category's total column height is
// its total stock; the ABC tier isn't a separate axis, it's the small
// chip rendered under each category's tick (see CategoryTick above) and
// the tint of the "in stock" segment.
export const CategoryStockBarWidget = ({ data = [], emptyReason }) => {
  const hasData = data.length > 0;
  const dataByCategory = useMemo(
    () => Object.fromEntries(data.map((d) => [d.category, d])),
    [data]
  );

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Stock matrix by category</h4>
          <p>Dead stock vs. in-stock, grouped by ABC tier</p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No category stock data available'}</p>
      ) : (
        <>
          <div className="chart-container">
            <ResponsiveContainer width="99%" height="100%">
              <BarChart data={data} margin={{ top: 20, right: 20, left: 0, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                <XAxis
                  dataKey="category"
                  axisLine={false}
                  tickLine={false}
                  interval={0}
                  height={40}
                  tick={<CategoryTick dataByCategory={dataByCategory} />}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  tickFormatter={(v) => Math.round(v).toLocaleString()}
                />
                <Tooltip content={<CategoryStockTooltip />} />
                <Bar dataKey="deadStock" name="Dead stock" stackId="stock" fill={STOCK_STATUS_COLORS.deadStock} radius={[0, 0, 3, 3]} isAnimationActive={false} />
                <Bar dataKey="inStock" name="In stock" stackId="stock" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                  {data.map((d) => (
                    <Cell key={d.category} fill={ABC_TIER_COLORS[d.tier] || STOCK_STATUS_COLORS.inStock} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ul className="custom-legend">
            <li className="legend-item">
              <span className="legend-color" style={{ backgroundColor: STOCK_STATUS_COLORS.deadStock, borderRadius: '3px' }} />
              Dead stock
            </li>
            <li className="legend-item">
              <span className="legend-color" style={{ backgroundColor: COLORS.abcA, borderRadius: '3px' }} />
              In stock (colored by ABC tier)
            </li>
          </ul>
        </>
      )}
    </div>
  );
};

const PortfolioForecastTooltip = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>{label}</p>
      {row.actual != null && (
        <p style={{ margin: '0.1rem 0', color: CHART_COLORS.salesSeries }}>Actual demand: {Math.round(row.actual).toLocaleString()} units</p>
      )}
      {row.forecast != null && (
        <p style={{ margin: '0.1rem 0', color: COLORS.forecast }}>Forecast: {Math.round(row.forecast).toLocaleString()} units</p>
      )}
    </div>
  );
};

// Portfolio-level aggregate forecast — sums forecast_value across every
// gated (MAPE < 20%) Category A SKU per period and plots it as one line
// with a confidence band (sum of confidence_lower/confidence_upper)
// against actual aggregate demand. Deliberately a directional visual, not
// a statistically rigorous aggregate interval — summing independent
// per-SKU confidence intervals overstates the true aggregate interval, so
// this trades SKU-level nuance for an at-a-glance "is demand trending up
// or down overall" read.
//
// series: [{ period, actual, forecast, confidenceLower, confidenceUpper }].
// actual is only present for historical periods, forecast/confidence only
// for projected ones — they're expected to share one point where the
// two meet so the lines read as continuous.
export const PortfolioForecastWidget = ({
  series = [],
  gatedSkuCount,
  avgMape,
  scopeLabel,
  emptyReason,
}) => {
  const hasData = series.length > 0;

  // Same base/excess stacking trick as CoverTrendWidget's policy shading:
  // an invisible area up to confidenceLower, then a visible band on top
  // of it sized to (confidenceUpper - confidenceLower), so the shaded
  // region reads as "the uncertainty range" rather than filling from zero.
  const chartData = useMemo(
    () => series.map((point) => {
      const hasBand = point.confidenceLower != null && point.confidenceUpper != null;
      return {
        ...point,
        confidenceBase: hasBand ? point.confidenceLower : null,
        confidenceBand: hasBand ? point.confidenceUpper - point.confidenceLower : null,
      };
    }),
    [series]
  );

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Portfolio-level aggregate forecast</h4>
          <p>Summed demand across gated Category A SKUs vs. SARIMA forecast</p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No forecast data available'}</p>
      ) : (
        <>
          <div className="portfolio-stat-row">
            <div className="portfolio-stat">
              <span className="portfolio-stat-label">Gated SKUs (MAPE &lt; 20%)</span>
              <span className="portfolio-stat-value">{gatedSkuCount}</span>
            </div>
            <div className="portfolio-stat">
              <span className="portfolio-stat-label">Avg. MAPE, portfolio</span>
              <span className="portfolio-stat-value">{avgMape.toFixed(1)}%</span>
            </div>
            <div className="portfolio-stat">
              <span className="portfolio-stat-label">Scope</span>
              <span className="portfolio-stat-value portfolio-stat-scope">{scopeLabel}</span>
            </div>
          </div>

          <div className="chart-container">
            <ResponsiveContainer width="99%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }} dy={10} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  domain={['auto', 'auto']}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  tickFormatter={(v) => `${Math.round(v / 1000)}k`}
                />
                <Tooltip content={<PortfolioForecastTooltip />} />
                <Area type="monotone" dataKey="confidenceBase" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} />
                <Area type="monotone" dataKey="confidenceBand" stackId="band" stroke="none" fill={COLORS.forecastBg} fillOpacity={0.9} isAnimationActive={false} />
                <Line
                  type="monotone"
                  dataKey="actual"
                  name="Actual demand"
                  stroke={CHART_COLORS.salesSeries}
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="forecast"
                  name="Forecast (SARIMA)"
                  stroke={COLORS.forecast}
                  strokeDasharray="5 3"
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <ul className="custom-legend">
            <li className="legend-item">
              <span className="legend-line" style={{ borderTopColor: CHART_COLORS.salesSeries }} />
              Actual demand
            </li>
            <li className="legend-item">
              <span className="legend-line legend-line-dashed" style={{ borderTopColor: COLORS.forecast }} />
              Forecast (SARIMA)
            </li>
            <li className="legend-item">
              <span className="legend-color" style={{ backgroundColor: COLORS.forecastBg, borderRadius: '3px' }} />
              Confidence band
            </li>
          </ul>
        </>
      )}
    </div>
  );
};

const URGENCY_STYLES = {
  CRITICAL: { bg: '#fff5f5', color: '#e53e3e' },
  URGENT: { bg: '#fffff0', color: '#d69e2e' },
  PLANNED: { bg: '#f0fff4', color: '#38a169' },
};

// Compact dashboard-card version of the ReorderRecommendations page — same
// urgency badge colors/vocabulary (CRITICAL/URGENT/PLANNED) as that page's
// full table, condensed to a short ranked list so it fits next to the
// portfolio forecast chart. rows: [{ sku, product, urgency, orderQty }].
export const ReorderRecommendationWidget = ({
  rows = [],
  criticalCount = 0,
  urgentCount = 0,
  totalOrderQty = 0,
  emptyReason,
}) => {
  const hasData = rows.length > 0;

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Reorder recommendations</h4>
          <p>LP-optimized purchase quantities, Category A SKUs</p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No pending recommendations'}</p>
      ) : (
        <>
          <div className="reorder-mini-summary">
            <div className="reorder-mini-chip">
              <span className="reorder-mini-value" style={{ color: URGENCY_STYLES.CRITICAL.color }}>{criticalCount}</span>
              <span className="reorder-mini-label">Critical</span>
            </div>
            <div className="reorder-mini-chip">
              <span className="reorder-mini-value" style={{ color: URGENCY_STYLES.URGENT.color }}>{urgentCount}</span>
              <span className="reorder-mini-label">Urgent</span>
            </div>
            <div className="reorder-mini-chip">
              <span className="reorder-mini-value">{totalOrderQty.toLocaleString()}</span>
              <span className="reorder-mini-label">Total order qty</span>
            </div>
          </div>

          <div className="reorder-mini-list">
            {rows.map((r) => (
              <div className="reorder-mini-row" key={r.sku}>
                <div className="reorder-mini-row-main">
                  <span className="reorder-mini-sku">{r.sku}</span>
                  <span className="reorder-mini-product">{r.product}</span>
                </div>
                <div className="reorder-mini-row-side">
                  <span
                    className="urgency-badge-mini"
                    style={{ backgroundColor: URGENCY_STYLES[r.urgency]?.bg, color: URGENCY_STYLES[r.urgency]?.color }}
                  >
                    {r.urgency}
                  </span>
                  <span className="reorder-mini-qty">{r.orderQty.toLocaleString()} units</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
};
