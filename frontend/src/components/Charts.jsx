import React, { useMemo, useState, useEffect } from 'react';
import {
  ComposedChart, BarChart, Bar, Cell, Line, LabelList,
  PieChart, Pie,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, ReferenceLine
} from 'recharts';
import { HelpCircle, RotateCcw } from 'lucide-react';
import { CHART_COLORS, STATUS_TIERS, COLORS } from '../theme/colors';
import { chartAnim } from '../theme/motion';
import './Charts.css';

// X-axis tick + tooltip header for every period-keyed chart on this page:
// "Jan · 2026" — short month, middle dot, full year. Was the raw 'YYYY-MM'
// string with no formatting at all (e.g. "2025-08"). Accepts 'YYYY-MM' and
// 'YYYY-MM-DD' alike — slicing only the first two '-'-separated segments
// ignores any day part, so a forecast_date's day-of-month never leaks in.
const AXIS_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const formatAxisPeriod = (period) => {
  if (!period) return '';
  const [year, num] = String(period).split('-');
  return `${AXIS_MONTHS[Number(num) - 1] || num} · ${year}`;
};

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
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }} dy={10} tickFormatter={formatAxisPeriod} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  domain={[0, 'auto']}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  label={{ value: 'Weeks of stock', angle: -90, position: 'insideLeft', fontSize: 10, fill: CHART_COLORS.axisLabel }}
                />
                <Tooltip content={<CoverTooltip policyTarget={policyTarget} />} />
                <Area type="monotone" dataKey="base" stackId="cover" stroke="none" fill="transparent" {...chartAnim()} />
                <Area type="monotone" dataKey="excess" stackId="cover" fill={CHART_COLORS.stockSeries} fillOpacity={0.18} stroke="none" {...chartAnim()} />
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
                  {...chartAnim()}
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
export function formatCompactPesos(value) {
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
            <Bar dataKey="variancePesos" radius={[3, 3, 3, 3]} {...chartAnim()}>
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

const SalesStockTooltip = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>{formatAxisPeriod(label)}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ margin: '0.1rem 0', color: p.color }}>
          {p.name}: {formatCompactPesos(p.value)}
        </p>
      ))}
    </div>
  );
};

// SUPPLIER-ALLOCATION PROXY — no supplier allocation schedule exists
// anywhere in the schema or the source files; SSM has never provided one.
// backend/routers/dashboard.py's sales_vs_stock[].received sums
// Purchase_Fact_Real.net_amount as a stand-in instead. Displayed as "Fixed
// Allocation" per product decision (2026-08) despite being received-
// quantity data underneath, not a real allocation schedule — see this
// file's git history for the more literal "Received (proxy for
// allocation)" wording this replaced. SalesStockTooltip renders whatever
// `name` each Line declares, so that's the only other place this label
// lives.
const RECEIVED_LABEL = 'Fixed Allocation';

// Sales vs. Stock on Hand — the dashboard's hero chart. `data` is
// [{ period, sales, stockOnHand, received }], all three in pesos (GET
// /dashboard sums stock_on_hand and received as peso figures specifically
// so all three plot on one axis — see backend/routers/dashboard.py's
// kpis.soh_value and sales_vs_stock[].received docstring sections). No
// flat ReferenceLine for `received`: it varies per period like the other
// two series, so it's a dashed Line, not a constant.
export const SalesVsStockWidget = ({ data = [], emptyReason }) => {
  const hasData = data.length > 0;

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Sales vs Stock on Hand</h4>
          <p>
            Monthly revenue and stock-on-hand valuation, in pesos. Received quantities stand in
            for the supplier allocation schedule, which SSM has not yet provided.
          </p>
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
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }} dy={10} tickFormatter={formatAxisPeriod} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  tickFormatter={(v) => formatCompactPesos(v)}
                />
                <Tooltip content={<SalesStockTooltip />} />
                <Line
                  type="monotone"
                  dataKey="sales"
                  name="Sales"
                  stroke={CHART_COLORS.salesSeries}
                  strokeWidth={2}
                  dot={false}
                  {...chartAnim()}
                />
                <Line
                  type="monotone"
                  dataKey="stockOnHand"
                  name="Stock on hand"
                  stroke={CHART_COLORS.stockSeries}
                  strokeWidth={2}
                  dot={false}
                  {...chartAnim()}
                />
                <Line
                  type="monotone"
                  dataKey="received"
                  name={RECEIVED_LABEL}
                  stroke={COLORS.forecast}
                  strokeDasharray="7 5"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: COLORS.forecast, strokeWidth: 0 }}
                  activeDot={{ r: 5 }}
                  {...chartAnim()}
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
              <span className="legend-line legend-line-dashed" style={{ borderTopColor: COLORS.forecast }} />
              {RECEIVED_LABEL}
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
                  dataKey="sharePct"
                  nameKey="tier"
                  innerRadius="60%"
                  outerRadius="85%"
                  paddingAngle={2}
                  {...chartAnim()}
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

// In-stock reads as the neutral, "normal" state — a calm teal. Dead stock
// (Inventory_Fact_Real.stock_status = 'Inactive') is the one that should
// draw the eye, but it's a watch-list condition rather than a critical
// alert, so it gets amber rather than this dashboard's one reserved alert
// red (the reorder card's CRITICAL badge). No_data gets the neutral
// "we don't know" slate STATUS_TIERS already uses for "no inherent
// direction" — a product with no Inventory_Fact_Real row that
// period, or a NULL stock_status, lands here (see GET /dashboard's
// tier_stock docstring), never folded into either real bucket.
const STOCK_STATUS_COLORS = {
  inStock: CHART_COLORS.salesSeries,
  deadStock: COLORS.warning,
  noData: STATUS_TIERS.diagnostic,
  // Indigo — this dashboard's own token for "a recommendation the system
  // is outputting" (STATUS_TIERS.action), reused here since
  // pendingReorderCount IS that: a count of LP_Recommendation rows, not a
  // stock status. Deliberately distinct from the stock-status colors so
  // the two bars never read as the same kind of thing.
  pendingReorder: STATUS_TIERS.action,
};

const CategoryStockTooltip = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload || {};
  const inStock = row.inStock || 0;
  const deadStock = row.deadStock || 0;
  const noData = row.noData || 0;
  const pendingReorderCount = row.pendingReorderCount || 0;
  const covered = inStock + deadStock;
  const total = covered + noData;
  const pct = (v) => (covered > 0 ? `${Math.round((v / covered) * 100)}%` : '—');
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>Tier {label}</p>
      <p style={{ margin: '0.1rem 0', color: STOCK_STATUS_COLORS.inStock }}>
        In stock: {inStock.toLocaleString()} ({pct(inStock)})
      </p>
      <p style={{ margin: '0.1rem 0', color: STOCK_STATUS_COLORS.deadStock }}>
        Dead stock: {deadStock.toLocaleString()} ({pct(deadStock)})
      </p>
      <p style={{ margin: '0.1rem 0 0 0', color: STOCK_STATUS_COLORS.noData }}>
        No inventory data: {noData.toLocaleString()} of {total.toLocaleString()} products
      </p>
      <p style={{ margin: '0.3rem 0 0 0', paddingTop: '0.3rem', borderTop: '1px solid #f1f5f9', color: STOCK_STATUS_COLORS.pendingReorder, fontWeight: 600 }}>
        Pending reorder: {pendingReorderCount.toLocaleString()} products
      </p>
    </div>
  );
};

const barLabelStyle = { fontSize: 10, fontWeight: 700, fill: '#ffffff' };
const pendingReorderLabelStyle = { fontSize: 10, fill: CHART_COLORS.axisLabel };

// A segment under this fraction of its own bar's covered height renders no
// inline label — Tier A/B's smallest slices used to overlap into an
// unreadable smear; the exact figure is still available on hover via
// CategoryStockTooltip.
const MIN_LABEL_FRACTION = 0.04;

// Per-segment LabelList content renderer: `data[index]` is that bar's own
// row (recharts renders one rect per data item in array order, so `index`
// lines up directly — no separate lookup key needed), used to compute this
// segment's share of ITS OWN bar (in_stock+dead_stock only — no_data is
// not part of the stack, see CategoryStockBarWidget below) rather than a
// global threshold, so a small tier isn't penalized differently than a
// large one.
function makeSegmentLabel(data) {
  return ({ x, y, width, height, value, index }) => {
    if (!value) return null;
    const row = data[index] || {};
    const covered = (row.inStock || 0) + (row.deadStock || 0);
    if (covered <= 0 || value / covered < MIN_LABEL_FRACTION) return null;
    return (
      <text x={x + width / 2} y={y + height / 2} textAnchor="middle" dominantBaseline="middle" style={barLabelStyle}>
        {value.toLocaleString()}
      </text>
    );
  };
}

// Custom two-line X-axis tick: "Tier A" plus a muted coverage caption
// ("inventory data for 499 of 1,492") — no_data is deliberately kept OUT
// of the stacked bar (a product with no Inventory_Fact_Real row that
// period would otherwise crush the two segments that actually carry a
// decision-relevant signal) but must stay visible somewhere on the
// chart, not be silently dropped.
function makeCategoryStockTick(data) {
  return ({ x, y, payload }) => {
    const row = data.find((d) => d.tier === payload.value) || {};
    const covered = (row.inStock || 0) + (row.deadStock || 0);
    const total = covered + (row.noData || 0);
    return (
      <g transform={`translate(${x},${y})`}>
        <text x={0} y={0} dy={14} textAnchor="middle" fontSize={11} fontWeight={700} fill={CHART_COLORS.axisLabel}>
          Tier {payload.value}
        </text>
        <text x={0} y={0} dy={28} textAnchor="middle" fontSize={9} fill={CHART_COLORS.axisLabel}>
          inventory data for {covered.toLocaleString()} of {total.toLocaleString()}
        </text>
      </g>
    );
  };
}

// Paired bar chart per ABC tier — `data` is
// [{ tier: 'A'|'B'|'C', inStock, deadStock, noData, pendingReorderCount }],
// from GET /dashboard's tier_stock. Two bars per tier: a stacked bar (dead
// stock beneath in-stock, from Inventory_Fact_Real.stock_status at the
// latest inventory period — a real, Unilever-only "is this product
// moving" signal, NOT the reorder-point-derived in_stock/low/critical
// split GET /abc uses) next to a single plain bar for that tier's pending
// reorder count (COUNT(DISTINCT product_key) with a pending
// LP_Recommendation row — a different source table, deliberately chosen
// so this bar doesn't restate the ABC donut's own count/revenue-share
// view under a different name). Y-axis is "SKUs" for both — both are
// product counts. No allocation bar: no supplier allocation table exists
// anywhere in the schema (see GET /dashboard's kpis.weeks_of_cover
// docstring), and the proxy SalesVsStockWidget uses instead
// (Purchase_Fact_Real) has no product key to break down by ABC tier at
// all — there is nothing honest to plot in its place.
export const CategoryStockBarWidget = ({ data = [], emptyReason }) => {
  const hasData = data.length > 0;

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Stock status by ABC tier</h4>
          <p>Dead/in-stock mix vs. pending reorders, by classification tier</p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No stock status data available'}</p>
      ) : (
        <>
          <div className="chart-container">
            <ResponsiveContainer width="99%" height="100%">
              <BarChart
                data={data}
                margin={{ top: 20, right: 20, left: 0, bottom: 10 }}
                barGap={4}
                barCategoryGap="30%"
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                <XAxis
                  dataKey="tier"
                  axisLine={false}
                  tickLine={false}
                  height={44}
                  tick={makeCategoryStockTick(data)}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  tickFormatter={(v) => Math.round(v).toLocaleString()}
                  label={{ value: 'SKUs', angle: -90, position: 'insideLeft', fontSize: 10, fill: CHART_COLORS.axisLabel }}
                />
                <Tooltip content={<CategoryStockTooltip />} cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }} />
                <Bar dataKey="deadStock" name="Dead stock" stackId="mix" fill={STOCK_STATUS_COLORS.deadStock} {...chartAnim(0)}>
                  <LabelList dataKey="deadStock" content={makeSegmentLabel(data)} />
                </Bar>
                <Bar dataKey="inStock" name="In stock" stackId="mix" fill={STOCK_STATUS_COLORS.inStock} radius={[3, 3, 0, 0]} {...chartAnim(1)}>
                  <LabelList dataKey="inStock" content={makeSegmentLabel(data)} />
                </Bar>
                <Bar dataKey="pendingReorderCount" name="Pending reorder" fill={STOCK_STATUS_COLORS.pendingReorder} radius={[3, 3, 0, 0]} {...chartAnim(2)}>
                  <LabelList dataKey="pendingReorderCount" position="top" style={pendingReorderLabelStyle} formatter={(v) => v.toLocaleString()} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ul className="custom-legend">
            <li className="legend-item">
              <span className="legend-color" style={{ backgroundColor: STOCK_STATUS_COLORS.inStock, borderRadius: '3px' }} />
              In stock
            </li>
            <li className="legend-item">
              <span className="legend-color" style={{ backgroundColor: STOCK_STATUS_COLORS.deadStock, borderRadius: '3px' }} />
              Dead stock
            </li>
            <li className="legend-item">
              <span className="legend-color" style={{ backgroundColor: STOCK_STATUS_COLORS.pendingReorder, borderRadius: '3px' }} />
              Pending reorder
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
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>{formatAxisPeriod(label)}</p>
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
  const chartData = useMemo(() => {
    const withBand = series.map((point) => {
      const hasBand = point.confidenceLower != null && point.confidenceUpper != null;
      return {
        ...point,
        confidenceBase: hasBand ? point.confidenceLower : null,
        confidenceBand: hasBand ? point.confidenceUpper - point.confidenceLower : null,
      };
    });

    // Bridge the actual/forecast junction: dashboard.py's portfolio_forecast
    // usually has exactly ONE real forecast bucket (see its docstring) —
    // an isolated point with nothing adjacent to connect to. Both Lines
    // below use dot={false}, so with no bridge that lone point renders as
    // literally nothing (Recharts needs 2 adjacent non-null points to draw
    // a segment, and the Area needs the same for the confidence band).
    // Injecting the last actual value as that point's own "forecast" (and
    // a zero-width band) gives both a real 2-point run to draw from —
    // the same fix SKUForecast.jsx already applies to its own chart.
    const lastActualIndex = withBand.reduce(
      (found, point, i) => (point.actual != null ? i : found), -1
    );
    const firstForecastIndex = withBand.findIndex((point) => point.forecast != null);
    if (lastActualIndex !== -1 && firstForecastIndex !== -1 && lastActualIndex < firstForecastIndex) {
      const bridge = withBand[lastActualIndex];
      bridge.forecast = bridge.actual;
      bridge.confidenceBase = bridge.actual;
      bridge.confidenceBand = 0;
    }

    return withBand;
  }, [series]);

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Portfolio-level aggregate forecast</h4>
          <p>Summed demand across gated Category A SKUs vs. MA3 forecast</p>
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
                {/* equidistantPreserveStart, not Recharts' default preserveEnd —
                    this series now spans the dashboard's picked date range
                    (can be 30+ months) instead of a fixed trailing 8, and
                    preserveEnd calculates its label-skipping backward from
                    the END, silently dropping the label at the true first
                    point on a wide range (diagnosed for SKUForecast.jsx's
                    identical chart earlier — same fix, same cause). */}
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }} dy={10} interval="equidistantPreserveStart" tickFormatter={formatAxisPeriod} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  domain={['auto', 'auto']}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  tickFormatter={(v) => `${Math.round(v / 1000)}k`}
                />
                <Tooltip content={<PortfolioForecastTooltip />} />
                <Area type="monotone" dataKey="confidenceBase" stackId="band" stroke="none" fill="transparent" {...chartAnim()} />
                <Area type="monotone" dataKey="confidenceBand" stackId="band" stroke="none" fill={COLORS.forecastBg} fillOpacity={0.9} {...chartAnim()} />
                <Line
                  type="monotone"
                  dataKey="actual"
                  name="Actual demand"
                  stroke={CHART_COLORS.salesSeries}
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                  {...chartAnim()}
                />
                <Line
                  type="monotone"
                  dataKey="forecast"
                  name="Forecast (MA3)"
                  stroke={COLORS.forecast}
                  strokeDasharray="5 3"
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                  {...chartAnim()}
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
              Forecast (MA3)
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

// Keys match GET /dashboard's reorder_preview.lp_weights exactly (backend/
// routers/dashboard.py's LP_WEIGHT_* constants, themselves a mirror of
// analytics/optimization/lp.py's W1/W2/W3 — the weights the LP solver
// actually used for every currently-pending recommendation).
//
// The sliders below are a WHAT-IF control, not a re-solve: moving one
// changes the displayed weight only. The recommendations underneath keep
// reflecting the weights the solver actually ran with, because there is no
// warehouse-capacity/supplier-ceiling/storage-cost data anywhere in the
// schema to re-solve the LP against (see reorder_preview.lp_weights's
// docstring in dashboard.py). Rather than silently implying the list
// updated, the widget shows an explicit "not re-solved" note the moment
// the sliders diverge from the solver's real weights.
//
// `blurb` is placeholder copy for each priority's hover tooltip — meant to
// be replaced with the real methodology wording from the manuscript.
const LP_PRIORITY_ROWS = [
  {
    key: 'cost',
    // Was COLORS.critical (red). Cost, Service level, and Storage are three
    // co-equal trade-off weights in one multi-objective LP — none of them
    // is inherently more alarming than the others, so giving Cost the same
    // red used for genuine alerts elsewhere (Reorder Recs' CRITICAL badge,
    // the Bad Order rate line) implied a severity that isn't there. Teal
    // keeps it visually distinct from Service level (indigo) and Storage
    // (amber) without borrowing red's meaning.
    label: 'Cost',
    color: COLORS.dispatched,
    blurb: 'Placeholder: how strongly the optimizer favours minimizing total purchase and holding cost when choosing order quantities.',
  },
  {
    key: 'service_level',
    label: 'Service level',
    color: COLORS.salesTrend,
    blurb: 'Placeholder: how strongly the optimizer favours avoiding stockouts, so demand can be met from stock on hand.',
  },
  {
    key: 'storage',
    label: 'Storage',
    color: COLORS.warning,
    blurb: 'Placeholder: how strongly the optimizer favours keeping within warehouse space and limiting spoilage risk.',
  },
];

// The solver's real defaults (analytics/optimization/lp.py W1/W2/W3),
// used to seed the sliders whenever the API hasn't sent weights.
const LP_DEFAULT_PCT = { cost: 45, service_level: 35, storage: 20 };

// Small "?" affordance — hover (or keyboard focus) reveals the blurb.
// Pure CSS visibility off :hover/:focus-within, so there's no popover
// dependency and nothing to position in JS.
const PriorityInfo = ({ text }) => (
  <span className="reorder-priority-info" tabIndex={0} role="button" aria-label="More information">
    <HelpCircle size={12} />
    <span className="reorder-priority-tip" role="tooltip">{text}</span>
  </span>
);

// Compact dashboard-card version of the ReorderRecommendations page.
// rows: [{ sku, product, urgency, orderQty }] — rendered below the
// priority sliders as a scrollable list, most-urgent first.
// weights: { cost, service_level, storage } fractions (0-1), from GET
// /dashboard's reorder_preview.lp_weights — seeds the sliders' starting
// position; LP_DEFAULT_PCT is the fallback when the API sends nothing.
const URGENCY_RANK = { CRITICAL: 0, URGENT: 1, PLANNED: 2 };

export const ReorderRecommendationWidget = ({
  rows = [],
  criticalCount = 0,
  urgentCount = 0,
  totalOrderQty = 0,
  weights,
  emptyReason,
}) => {
  const hasData = rows.length > 0;

  // The solver's real weights as whole percents — both the sliders' seed
  // and the baseline the "not re-solved" note compares against.
  const solverPct = useMemo(() => {
    const read = (key) =>
      typeof weights?.[key] === 'number' ? Math.round(weights[key] * 100) : LP_DEFAULT_PCT[key];
    return { cost: read('cost'), service_level: read('service_level'), storage: read('storage') };
  }, [weights]);

  const [draftPct, setDraftPct] = useState(solverPct);

  // Re-seed if the API's weights change (e.g. a new date range loads a
  // different planning cycle) — but only when the user hasn't dragged yet,
  // so a background refetch can't yank a slider out from under them.
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (!touched) setDraftPct(solverPct);
  }, [solverPct, touched]);

  const isModified = LP_PRIORITY_ROWS.some((p) => draftPct[p.key] !== solverPct[p.key]);
  const draftTotal = LP_PRIORITY_ROWS.reduce((sum, p) => sum + draftPct[p.key], 0);

  const handleSlide = (key, value) => {
    setTouched(true);
    setDraftPct((prev) => ({ ...prev, [key]: Number(value) }));
  };

  const handleReset = () => {
    setTouched(false);
    setDraftPct(solverPct);
  };

  // Most-urgent first so the critical SKUs are what's visible before the
  // list is scrolled; ties break on the larger order quantity.
  const sortedRows = useMemo(
    () =>
      [...rows].sort(
        (a, b) =>
          (URGENCY_RANK[a.urgency] ?? 9) - (URGENCY_RANK[b.urgency] ?? 9) ||
          (b.orderQty ?? 0) - (a.orderQty ?? 0)
      ),
    [rows]
  );

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Reorder recommendations</h4>
          <p>LP-optimized purchase quantities, Category A SKUs</p>
        </div>
        {isModified && (
          <button type="button" className="reorder-card-reset" onClick={handleReset}>
            <RotateCcw size={12} />
            Reset
          </button>
        )}
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

          <div className="reorder-priorities">
            <div className="reorder-priorities-header">
              <span className="reorder-priorities-title">Optimization priorities</span>
              <span className="reorder-priorities-caption">Weights used for these recommendations</span>
            </div>

            {LP_PRIORITY_ROWS.map((p) => (
              <div className="reorder-priority-row" key={p.key}>
                <div className="reorder-priority-row-top">
                  <label className="reorder-priority-label" htmlFor={`lp-weight-${p.key}`}>
                    <span className="reorder-priority-swatch" style={{ backgroundColor: p.color }} />
                    {p.label}
                  </label>
                  <PriorityInfo text={p.blurb} />
                  <span className="reorder-priority-pct">{draftPct[p.key]}%</span>
                </div>
                <input
                  id={`lp-weight-${p.key}`}
                  className="reorder-priority-slider"
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={draftPct[p.key]}
                  onChange={(e) => handleSlide(p.key, e.target.value)}
                  style={{ '--slider-accent': p.color, '--slider-pct': `${draftPct[p.key]}%` }}
                />
              </div>
            ))}

            {/* Honest about what the sliders do and don't do: they're a
                what-if, and the list below is still the solver's real
                output. Also surfaces when the three stop summing to 100%,
                since the LP's weights are shares of one whole. */}
            {isModified && (
              <p className="reorder-priorities-note">
                What-if only — recommendations below still use the solver&apos;s actual weights
                ({solverPct.cost}/{solverPct.service_level}/{solverPct.storage}).
                {draftTotal !== 100 && ` Weights total ${draftTotal}%, not 100%.`}
              </p>
            )}
          </div>

          <div className="reorder-mini-list">
            {sortedRows.map((r) => (
              <div className="reorder-mini-row" key={r.sku}>
                <div className="reorder-mini-row-main">
                  <span className="reorder-mini-sku">{r.sku}</span>
                  <span className="reorder-mini-product">{r.product}</span>
                </div>
                <div className="reorder-mini-row-side">
                  <span
                    className="urgency-badge-mini"
                    style={{
                      backgroundColor: URGENCY_STYLES[r.urgency]?.bg,
                      color: URGENCY_STYLES[r.urgency]?.color,
                    }}
                  >
                    {r.urgency}
                  </span>
                  <span className="reorder-mini-qty">
                    {Number(r.orderQty ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} units
                  </span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
};
