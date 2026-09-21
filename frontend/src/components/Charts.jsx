import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  ComposedChart, BarChart, Bar, Cell, Line,
  PieChart, Pie,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, ReferenceLine
} from 'recharts';
import { HelpCircle, ArrowRight } from 'lucide-react';
import { CHART_COLORS, STATUS_TIERS, COLORS, SEMANTIC } from '../theme/colors';
import { formatMonth } from '../utils/formatDate';
import { chartAnim, prefersReducedMotion, CHART_ANIM_DURATION, CHART_ANIM_STAGGER } from '../theme/motion';
import { useChartZoom, ChartZoomSlider, SeriesFill, seriesDot } from './ChartZoom';
import { PRINCIPALS } from '../principals';
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
  // Every series is now drawn twice — the Line, plus the Area shading under
  // it — so the raw payload carries each value twice over. The fills declare
  // tooltipType="none", which Recharts passes through as `type` on the
  // entry; dropping those leaves exactly one row per real series.
  const rows = payload.filter((p) => p.type !== 'none');
  if (!rows.length) return null;
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>{formatAxisPeriod(label)}</p>
      {rows.map((p) => (
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
  // Windows over whatever range the page's date filter fetched. At a wide
  // range that is 38 months, far more than the XAxis can label without
  // skipping — narrowing the window is what puts every month back on screen.
  const zoom = useChartZoom(data);
  // A legend entry with no drawn series is a phantom. Live,
  // Purchase_Fact_Real holds Del Monte rows only, so `received` is null
  // for every Unilever period: the "Fixed Allocation" line never drew a
  // single point while its legend swatch still claimed a series existed.
  // The Line and its legend entry now appear together, only when at least
  // one real point exists — and the subtitle says which case it is.
  const hasReceived = data.some((pt) => pt.received != null);

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Sales vs Stock on Hand</h4>
          <p>
            Monthly revenue and stock-on-hand valuation, in pesos.
            {hasReceived
              ? ' Received quantities stand in for the supplier allocation schedule, which SSM has not yet provided.'
              : ' No purchase records exist for this scope, so no received/allocation line is drawn.'}
          </p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No data available for this range'}</p>
      ) : (
        <>
          <div className={`chart-container${zoom.canPan ? ' chart-pannable' : ''}`} {...zoom.panHandlers}>
            <ResponsiveContainer width="99%" height="100%">
              <ComposedChart data={zoom.view} margin={{ top: 20, right: 20, left: 0, bottom: 10 }}>
                <defs>
                  <SeriesFill id="fill-sales" color={CHART_COLORS.salesSeries} />
                  <SeriesFill id="fill-stock" color={CHART_COLORS.stockSeries} />
                  {hasReceived && <SeriesFill id="fill-received" color={COLORS.forecast} />}
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                {/* Interval comes from the zoom window, not Recharts' own
                    crowding heuristic: 0 draws every month once the window is
                    narrow enough to fit them, and steps up only as it widens. */}
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }} dy={10} interval={zoom.labelInterval} tickFormatter={formatAxisPeriod} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  tickFormatter={(v) => formatCompactPesos(v)}
                />
                <Tooltip content={<SalesStockTooltip />} />
                {/* Fills are declared ahead of the Lines so every line paints
                    on top of every wash, including where two series overlap.
                    baseValue="dataMin" anchors them to the axis floor rather
                    than to zero, which keeps the Y domain exactly as it was. */}
                <Area type="monotone" dataKey="sales" stroke="none" fill="url(#fill-sales)" baseValue="dataMin" legendType="none" tooltipType="none" {...zoom.zoomAnim(0)} />
                <Area type="monotone" dataKey="stockOnHand" stroke="none" fill="url(#fill-stock)" baseValue="dataMin" legendType="none" tooltipType="none" {...zoom.zoomAnim(1)} />
                {hasReceived && (
                  <Area type="monotone" dataKey="received" stroke="none" fill="url(#fill-received)" baseValue="dataMin" legendType="none" tooltipType="none" {...zoom.zoomAnim(2)} />
                )}
                <Line
                  type="monotone"
                  dataKey="sales"
                  name="Sales"
                  stroke={CHART_COLORS.salesSeries}
                  strokeWidth={2}
                  dot={seriesDot({ show: zoom.showDots, color: CHART_COLORS.salesSeries })}
                  activeDot={{ r: 5 }}
                  {...zoom.zoomAnim(0)}
                />
                <Line
                  type="monotone"
                  dataKey="stockOnHand"
                  name="Stock on hand"
                  stroke={CHART_COLORS.stockSeries}
                  strokeWidth={2}
                  dot={seriesDot({ show: zoom.showDots, color: CHART_COLORS.stockSeries })}
                  activeDot={{ r: 5 }}
                  {...zoom.zoomAnim(1)}
                />
                {hasReceived && (
                  <Line
                    type="monotone"
                    dataKey="received"
                    name={RECEIVED_LABEL}
                    stroke={COLORS.forecast}
                    strokeDasharray="7 5"
                    strokeWidth={2.5}
                    dot={seriesDot({ show: zoom.showDots, color: COLORS.forecast })}
                    activeDot={{ r: 5 }}
                    {...zoom.zoomAnim(2)}
                  />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <ChartZoomSlider zoom={zoom} />
          <ul className="custom-legend">
            <li className="legend-item">
              <span className="legend-line" style={{ borderTopColor: CHART_COLORS.salesSeries }} />
              Sales
            </li>
            <li className="legend-item">
              <span className="legend-line" style={{ borderTopColor: CHART_COLORS.stockSeries }} />
              Stock on hand
            </li>
            {hasReceived && (
              <li className="legend-item">
                <span className="legend-line legend-line-dashed" style={{ borderTopColor: COLORS.forecast }} />
                {RECEIVED_LABEL}
              </li>
            )}
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
// The RING encodes revenue share, so the centre now states the revenue
// those shares are shares of (GET /dashboard's abc_revenue — the same
// net_amount basis the classification ran on) with the SKU count as a
// smaller second line. It used to print "710 SKUs" in the middle of a ring
// that was 80% Tier A by revenue — two units in one graphic, and Tier A is
// only ~19% of SKUs. The paired bars underneath put that Pareto contrast in
// one glance: the same three tiers as share of revenue vs share of SKUs.
// `revenue` is {period, total, blocked_reason}; a null total falls back to
// the SKU count in the centre with the reason in its tooltip, never a
// stand-in figure.
export const ABCDonutWidget = ({ data = [], revenue, emptyReason }) => {
  const hasData = data.length > 0;
  const total = data.reduce((sum, d) => sum + d.count, 0);
  const revenueTotal = revenue?.total ?? null;
  const sharePairs = [
    { key: 'sharePct', label: 'Share of revenue', value: (d) => d.sharePct },
    { key: 'skuPct', label: 'Share of SKUs', value: (d) => (total > 0 ? (d.count / total) * 100 : 0) },
  ];

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>ABC classification</h4>
          <p>Ring: each tier's share of revenue. Bars: that share next to the tier's share of the SKU count.</p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No ABC classification available'}</p>
      ) : (
        <div className="chart-widget-body">
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
              {revenueTotal != null ? (
                <>
                  <span className="donut-center-value">{formatCompactPesos(revenueTotal)}</span>
                  <span className="donut-center-caption">revenue · {formatMonth(revenue.period)}</span>
                  <span className="donut-center-secondary">{total.toLocaleString()} SKUs</span>
                </>
              ) : (
                <>
                  <span className="donut-center-value">{total.toLocaleString()}</span>
                  <span className="donut-center-caption">SKUs</span>
                  <span className="donut-center-secondary" title={revenue?.blocked_reason || 'Revenue total not available'}>
                    revenue n/a
                  </span>
                </>
              )}
            </div>
          </div>
          <ul className="custom-legend">
            {data.map((d) => (
              <li className="legend-item" key={d.tier}>
                <span className="legend-color" style={{ backgroundColor: ABC_TIER_COLORS[d.tier] || CHART_COLORS.abcRamp[0] }} />
                Tier {d.tier}
              </li>
            ))}
          </ul>
          <div className="abc-share-pair" role="img" aria-label="Share of revenue versus share of SKUs, by tier">
            {sharePairs.map((pair) => (
              <div className="abc-share-row" key={pair.key}>
                <span className="abc-share-label">{pair.label}</span>
                <div className="abc-share-track">
                  {data.map((d) => {
                    const v = pair.value(d);
                    return (
                      <span
                        key={d.tier}
                        style={{ width: `${v}%`, backgroundColor: ABC_TIER_COLORS[d.tier] || CHART_COLORS.abcRamp[0] }}
                        title={`Tier ${d.tier}: ${v.toFixed(0)}% ${pair.key === 'skuPct' ? `of SKUs (${d.count})` : 'of revenue'}`}
                      />
                    );
                  })}
                </div>
                <span className="abc-share-values">
                  {data.map((d) => `${d.tier} ${pair.value(d).toFixed(0)}%`).join(' · ')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// Horizontal per-tier composition bar, coloured by the app-wide SEMANTIC
// rule: Active = healthy (green), dead stock = watch (amber), pending
// reorder = a recommendation (indigo), never a health state. Pending
// reorder used to be amber — the same amber the ABC page used for "low
// stock" and Reorder Recs used for "urgent", three meanings on one hue.
const WAREHOUSE_STATUS_COLORS = {
  active: SEMANTIC.healthy,
  deadStock: SEMANTIC.watch,
  pendingReorder: SEMANTIC.recommendation,
};

// Paired-fraction bar per ABC tier — `data` is
// [{ tier: 'A'|'B'|'C', inStock, deadStock, noData, pendingReorderCount }],
// from GET /dashboard's tier_stock. Each row is one bar, its three segments
// sized as a share of that tier's own (inStock + deadStock +
// pendingReorderCount) — a composition view ("what's this tier made of"),
// not an absolute-count comparison across tiers, so a small tier's bar
// isn't visually dwarfed by a large one. no_data isn't part of the bar
// (mixing it in would crush the two segments that actually carry a
// decision-relevant signal) but its real count is still in the row's
// title tooltip, never silently dropped. No allocation segment: no
// supplier allocation table exists anywhere in the schema (see GET
// /dashboard's kpis.weeks_of_cover docstring), and the proxy
// SalesVsStockWidget uses instead (Purchase_Fact_Real) has no product key
// to break down by ABC tier at all — there is nothing honest to plot here.
//
// LABELS (2026-09-18): this widget and the ABC page's "Cover vs reorder
// point" both used to say "In stock" while measuring different things —
// this one reads Inventory_Fact_Real.stock_status (the warehouse's own
// Active/Inactive flag), the ABC page compares current stock with each
// SKU's reorder point. Category A showed as mostly green here and as "IN
// STOCK: 0 SKUs" there, a flat contradiction. Both are now named for what
// they measure. Legend entries appear only for segments that actually have
// a non-zero count somewhere in the data — live, no ABC-classified product
// is flagged Inactive, so a "Dead stock" swatch was pointing at nothing.
export const CategoryStockBarWidget = ({ data = [], emptyReason }) => {
  const hasData = data.length > 0;
  const hasDead = data.some((row) => (row.deadStock || 0) > 0);
  const hasPending = data.some((row) => (row.pendingReorderCount || 0) > 0);
  // Same "off entirely, not just shorter" reduced-motion rule motion.js's
  // chartAnim() uses for the Recharts-based widgets — this one is plain
  // CSS (no Recharts here), so it's applied by hand rather than picked up
  // for free.
  const disableAnim = prefersReducedMotion();

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Active / dead stock by ABC tier (warehouse status)</h4>
          <p>
            Counts each tier&apos;s products by the warehouse&apos;s own Active/Inactive flag on the latest
            stock snapshot — not by whether stock covers the reorder point (that is the ABC page&apos;s
            &ldquo;Cover vs reorder point&rdquo;).
          </p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No stock status data available'}</p>
      ) : (
        <div className="chart-widget-body">
          <div className="tier-stock-bars">
            {data.map((row, index) => {
              const inStock = row.inStock || 0;
              const deadStock = row.deadStock || 0;
              const pendingReorderCount = row.pendingReorderCount || 0;
              const noData = row.noData || 0;
              const total = inStock + deadStock + pendingReorderCount;
              // Floor at a visible width for any segment that's genuinely
              // non-zero — a real 2-unit dead-stock count on an 800-unit
              // tier is <1% and renders as a literal 0px sliver otherwise,
              // indistinguishable from "actually zero." A truly-zero count
              // stays at 0% — this never invents a value, it only keeps a
              // real one from being visually erased. Exact figures are
              // still in this row's title tooltip regardless.
              const MIN_VISIBLE_PCT = 1.5;
              const pct = (v) => {
                if (total <= 0 || v <= 0) return 0;
                return Math.max((v / total) * 100, MIN_VISIBLE_PCT);
              };
              const title =
                `Tier ${row.tier} — active: ${inStock.toLocaleString()}, ` +
                `dead stock (Inactive): ${deadStock.toLocaleString()}, pending reorder: ${pendingReorderCount.toLocaleString()}` +
                (noData ? `, no inventory record: ${noData.toLocaleString()}` : '');
              // Each row's bar sweeps in staggered by tier — same duration/
              // easing/stagger constants the Recharts widgets on this page
              // use (CHART_ANIM_DURATION/STAGGER), just applied as CSS
              // custom properties instead of Recharts animation props.
              const animStyle = disableAnim
                ? undefined
                : {
                    '--tier-anim-duration': `${CHART_ANIM_DURATION}ms`,
                    '--tier-anim-delay': `${index * CHART_ANIM_STAGGER}ms`,
                  };
              return (
                <div className="tier-stock-row" key={row.tier} title={title}>
                  <span className="tier-stock-label">{row.tier}</span>
                  <div className={`tier-stock-track${disableAnim ? '' : ' is-animated'}`} style={animStyle}>
                    {total <= 0 ? (
                      <span className="tier-stock-empty">No data</span>
                    ) : (
                      <>
                        <span style={{ width: `${pct(inStock)}%`, backgroundColor: WAREHOUSE_STATUS_COLORS.active }} />
                        <span style={{ width: `${pct(deadStock)}%`, backgroundColor: WAREHOUSE_STATUS_COLORS.deadStock }} />
                        <span style={{ width: `${pct(pendingReorderCount)}%`, backgroundColor: WAREHOUSE_STATUS_COLORS.pendingReorder }} />
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <ul className="custom-legend">
            <li className="legend-item">
              <span className="legend-color" style={{ backgroundColor: WAREHOUSE_STATUS_COLORS.active, borderRadius: '3px' }} />
              Active (warehouse status)
            </li>
            {hasDead && (
              <li className="legend-item">
                <span className="legend-color" style={{ backgroundColor: WAREHOUSE_STATUS_COLORS.deadStock, borderRadius: '3px' }} />
                Dead stock (warehouse status)
              </li>
            )}
            {hasPending && (
              <li className="legend-item">
                <span className="legend-color" style={{ backgroundColor: WAREHOUSE_STATUS_COLORS.pendingReorder, borderRadius: '3px' }} />
                Pending reorder
              </li>
            )}
          </ul>
        </div>
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
  principal,
  onPrincipalChange,
  isUpdating = false,
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
    // an isolated point with nothing adjacent to connect to, and Recharts
    // needs 2 adjacent non-null points to draw a segment. The Lines now
    // fall back to an isolated-point dot (seriesDot), but the confidence
    // band is an Area and has no such fallback, so the bridge still earns
    // its place. Injecting the last actual value as that point's own
    // "forecast" (and a zero-width band) gives both a real 2-point run to
    // draw from — the same fix SKUForecast.jsx already applies to its own
    // chart.
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

  // Zoom applies to the assembled chartData, not the raw series, so the
  // actual/forecast bridge point above is computed once over the whole
  // range instead of being recalculated for whatever window is showing.
  const zoom = useChartZoom(chartData);

  return (
    <div className={`chart-widget${onPrincipalChange ? ' chart-widget-filterable' : ''}${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Portfolio-level aggregate forecast</h4>
          <p>Summed demand across gated Category A SKUs vs. MA3 forecast</p>
        </div>
        {/* Card-scoped principal filter — re-scopes THIS card only, never
            the page (the Topbar's filter does that). Rendered in the empty
            state too, so a scope with no forecasts can be switched back
            out of. Own class names, not the Topbar's .principal-segment:
            CSS is global and that one carries viewport breakpoints meant
            for the topbar, not a card. */}
        {onPrincipalChange && (
          <div className="card-principal-filter" role="radiogroup" aria-label="Forecast principal">
            {PRINCIPALS.map((p) => (
              <button
                key={p.key}
                type="button"
                role="radio"
                aria-checked={principal === p.key}
                className={`card-principal-option${principal === p.key ? ' active' : ''}`}
                onClick={() => onPrincipalChange(p.key)}
              >
                {p.key === 'all' ? 'All' : p.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {!hasData ? (
        <p className={`dashboard-empty-note${isUpdating ? ' is-refreshing' : ''}`}>
          {isUpdating ? 'Loading forecast…' : emptyReason || 'No forecast data available'}
        </p>
      ) : (
        <div className={`portfolio-forecast-body${isUpdating ? ' is-refreshing' : ''}`} aria-busy={isUpdating}>
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

          <div className={`chart-container${zoom.canPan ? ' chart-pannable' : ''}`} {...zoom.panHandlers}>
            <ResponsiveContainer width="99%" height="100%">
              <ComposedChart data={zoom.view} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
                <defs>
                  <SeriesFill id="fill-actual" color={CHART_COLORS.salesSeries} />
                  <SeriesFill id="fill-forecast" color={COLORS.forecast} />
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
                {/* A numeric interval from the zoom window, replacing the
                    earlier equidistantPreserveStart. That was here because
                    Recharts' default preserveEnd skips labels counting
                    backward from the END and so silently dropped the first
                    point's label on a wide range; a numeric interval counts
                    forward from index 0, which keeps the first label by
                    construction, and drops to 0 (every month labelled) as
                    soon as the window is narrow enough to fit them. */}
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }} dy={10} interval={zoom.labelInterval} tickFormatter={formatAxisPeriod} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  domain={['auto', 'auto']}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  tickFormatter={(v) => `${Math.round(v / 1000)}k`}
                />
                <Tooltip content={<PortfolioForecastTooltip />} />
                <Area type="monotone" dataKey="confidenceBase" stackId="band" stroke="none" fill="transparent" {...zoom.zoomAnim(0)} />
                <Area type="monotone" dataKey="confidenceBand" stackId="band" stroke="none" fill={COLORS.forecastBg} fillOpacity={0.9} {...zoom.zoomAnim(0)} />
                {/* Series washes sit above the confidence band but below both
                    lines. No stackId — these are independent fills, and
                    joining the band's stack would add their values to it. */}
                <Area type="monotone" dataKey="actual" stroke="none" fill="url(#fill-actual)" baseValue="dataMin" legendType="none" tooltipType="none" connectNulls={false} {...zoom.zoomAnim(1)} />
                <Area type="monotone" dataKey="forecast" stroke="none" fill="url(#fill-forecast)" baseValue="dataMin" legendType="none" tooltipType="none" connectNulls={false} {...zoom.zoomAnim(2)} />
                <Line
                  type="monotone"
                  dataKey="actual"
                  name="Actual demand"
                  stroke={CHART_COLORS.salesSeries}
                  strokeWidth={2}
                  dot={seriesDot({ show: zoom.showDots, color: CHART_COLORS.salesSeries })}
                  activeDot={{ r: 5 }}
                  connectNulls={false}
                  {...zoom.zoomAnim(1)}
                />
                <Line
                  type="monotone"
                  dataKey="forecast"
                  name="Forecast (MA3)"
                  stroke={COLORS.forecast}
                  strokeDasharray="5 3"
                  strokeWidth={2}
                  dot={seriesDot({ show: zoom.showDots, color: COLORS.forecast })}
                  activeDot={{ r: 5 }}
                  connectNulls={false}
                  {...zoom.zoomAnim(2)}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <ChartZoomSlider zoom={zoom} />
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
        </div>
      )}
    </div>
  );
};

// One neutral pill style for every urgency tier — this card reads urgency
// from the row's position (most-urgent first, see sortedRows below) and its
// text, not from color, so CRITICAL/URGENT/PLANNED share the same chip look
// instead of a red/amber/green ramp.
const NEUTRAL_URGENCY_STYLE = { bg: 'var(--color-surface-sunken)', color: 'var(--color-text-muted)' };
const URGENCY_STYLES = {
  CRITICAL: NEUTRAL_URGENCY_STYLE,
  URGENT: NEUTRAL_URGENCY_STYLE,
  PLANNED: NEUTRAL_URGENCY_STYLE,
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
    // a rate line elsewhere in the app) implied a severity that isn't there. Teal
    // keeps it visually distinct from Service level (indigo) and Storage
    // (amber) without borrowing red's meaning.
    label: 'Cost',
    color: CHART_COLORS.lpWeights.cost,
    blurb: 'Placeholder: how strongly the optimizer favours minimizing total purchase and holding cost when choosing order quantities.',
  },
  {
    key: 'service_level',
    label: 'Service level',
    color: CHART_COLORS.lpWeights.service_level,
    blurb: 'Placeholder: how strongly the optimizer favours avoiding stockouts, so demand can be met from stock on hand.',
  },
  {
    key: 'storage',
    label: 'Storage',
    color: CHART_COLORS.lpWeights.storage,
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

  // The solver's real weights as whole percents. Read-only: GET /dashboard's
  // reorder_preview.lp_weights docstring is explicit that this is "a
  // read-only display value, not an adjustable control" — there's no
  // warehouse-capacity/supplier-ceiling/storage-cost data anywhere in the
  // schema to legitimately re-solve the LP against, and pulp (the solver)
  // is a batch dependency this always-on API/dashboard never loads. This
  // used to back a set of what-if sliders; removed rather than left
  // decorative, since a control that visibly moves but never changes the
  // list below it reads as broken, not as a deliberate design choice.
  const solverPct = useMemo(() => {
    const read = (key) =>
      typeof weights?.[key] === 'number' ? Math.round(weights[key] * 100) : LP_DEFAULT_PCT[key];
    return { cost: read('cost'), service_level: read('service_level'), storage: read('storage') };
  }, [weights]);

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
          {/* GET /dashboard's reorder_preview sums every pending recommendation
              across all planning cycles, while Reorder Recs shows one cycle at a
              time (latest by default), so the two pages' counts differ. Said
              here until the backend scopes the preview to the latest cycle. */}
          <p>LP-optimized purchase quantities, Category A SKUs · all pending planning cycles</p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No pending recommendations'}</p>
      ) : (
        <>
          <div className="reorder-mini-summary">
            {/* Only the two counts that carry real urgency get colored —
                Critical in this dashboard's one reserved alert red, Urgent
                in the same amber used for "watch this" elsewhere (e.g.
                STOCK_STATUS_COLORS.deadStock). Total order qty stays
                neutral: it's a quantity, not a severity, so coloring it
                would imply a good/bad judgment that doesn't exist. */}
            <div className="reorder-mini-chip">
              <span className="reorder-mini-value" style={{ color: SEMANTIC.act }}>{criticalCount}</span>
              <span className="reorder-mini-label">Critical</span>
            </div>
            <div className="reorder-mini-chip">
              <span className="reorder-mini-value" style={{ color: SEMANTIC.watch }}>{urgentCount}</span>
              <span className="reorder-mini-label">Urgent</span>
            </div>
            <div className="reorder-mini-chip">
              <span className="reorder-mini-value">{totalOrderQty.toLocaleString()}</span>
              <span className="reorder-mini-label">Total order qty</span>
            </div>
          </div>

          <div className="reorder-priorities">
            <div className="reorder-priorities-header">
              <span className="reorder-priorities-title">How this was optimized</span>
              <span className="reorder-priorities-caption">Weights the solver used for these recommendations</span>
            </div>

            {/* Read-only bar per weight — was a draggable slider, but
                GET /dashboard's reorder_preview.lp_weights docstring is
                explicit that this value is "read-only display... not an
                adjustable control" (see backend/routers/dashboard.py),
                so this now matches what the data actually is: a fact
                about how the solver ran, not a live control. */}
            {LP_PRIORITY_ROWS.map((p) => (
              <div className="reorder-priority-row" key={p.key}>
                <div className="reorder-priority-row-top">
                  <span className="reorder-priority-label">
                    <span className="reorder-priority-swatch" style={{ backgroundColor: p.color }} />
                    {p.label}
                  </span>
                  <PriorityInfo text={p.blurb} />
                  <span className="reorder-priority-pct">{solverPct[p.key]}%</span>
                </div>
                <div className="reorder-priority-bar" role="img" aria-label={`${p.label}: ${solverPct[p.key]}%`}>
                  <span style={{ width: `${solverPct[p.key]}%`, backgroundColor: p.color }} />
                </div>
              </div>
            ))}
          </div>

          <div className="reorder-mini-list">
            {/* Own class name, not "reorder-table": that one is the full
                Reorder Recs page table and carries min-width: 1180px, which
                leaked in here (CSS is global) and forced a horizontal scroll. */}
            <table className="reorder-mini-table">
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>Product</th>
                  <th>Urgency</th>
                  <th>Qty</th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((r) => (
                  <tr key={r.sku}>
                    <td>
                      {/* Was a plain <span> styled to look like a link (blue,
                          same color as every other clickable SKU in the app)
                          but had no click handler — a dead affordance. Now a
                          real link to that SKU's own recommendation, which the
                          Reorder Recs page opens in its detail modal on load
                          (see the ?sku= handling in ReorderRecommendations.jsx). */}
                      <Link to={`/reorder?sku=${encodeURIComponent(r.sku)}`} className="reorder-mini-sku">
                        {r.sku}
                      </Link>
                    </td>
                    <td className="reorder-mini-product" title={r.product}>{r.product}</td>
                    <td>
                      <span
                        className="urgency-badge-mini"
                        style={{
                          backgroundColor: URGENCY_STYLES[r.urgency]?.bg,
                          color: URGENCY_STYLES[r.urgency]?.color,
                        }}
                      >
                        {r.urgency}
                      </span>
                    </td>
                    <td className="reorder-mini-qty">
                      {Number(r.orderQty ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* This widget only ever shows a few rows (Dashboard is an
              overview, not the working list) — this is its one connection
              to the full Reorder Recs page, where the complete list,
              Accept/Dismiss actions, and decision log actually live. */}
          <Link to="/reorder" className="reorder-mini-view-all">
            View all recommendations
            <ArrowRight size={14} />
          </Link>
        </>
      )}
    </div>
  );
};

// LP safety stock vs SSM's blanket 3-week rule — GET /dashboard's
// policy_comparison. Two bars on one scale, in the demand series' unit
// (pieces): what the LP's per-SKU safety stock (SS_i) sums to across the
// latest planning cycle, and what holding three weeks of each SKU's own
// forecast would sum to. Units, not pesos — no per-piece cost exists to
// value the difference honestly (backend/routers/dashboard.py's
// policy_comparison docstring). The rule bar is slate (a baseline, no
// verdict) and the LP bar indigo (a model output), per the SEMANTIC rule.
export const PolicyComparisonWidget = ({ comparison, emptyReason }) => {
  const c = comparison || {};
  const hasData = c.lp_safety_stock_units != null && c.rule_safety_stock_units != null;
  const max = hasData ? Math.max(c.lp_safety_stock_units, c.rule_safety_stock_units, 1) : 1;
  const rows = [
    { key: 'rule', label: `Blanket ${c.rule_weeks ?? 3}-week rule`, value: c.rule_safety_stock_units, color: SEMANTIC.noData },
    { key: 'lp', label: 'LP safety stock (SS\u1d62)', value: c.lp_safety_stock_units, color: SEMANTIC.recommendation },
  ];

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Safety stock: LP policy vs the blanket 3-week rule</h4>
          <p>
            Total buffer stock each policy would hold across the latest planning cycle, in demand units.
            Rule = 3 weeks of each SKU&apos;s own MA3 forecast; LP = the per-SKU safety stock the optimizer solved for.
          </p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || c.blocked_reason || 'Policy comparison not available'}</p>
      ) : (
        <div className="chart-widget-body">
          <div className="policy-bars">
            {rows.map((r) => (
              <div className="policy-bar-row" key={r.key}>
                <span className="policy-bar-label">{r.label}</span>
                <div className="policy-bar-track" role="img" aria-label={`${r.label}: ${Math.round(r.value).toLocaleString()} units`}>
                  <span style={{ width: `${(r.value / max) * 100}%`, backgroundColor: r.color }} />
                </div>
                <span className="policy-bar-value">{Math.round(r.value).toLocaleString()} units</span>
              </div>
            ))}
          </div>
          <p className="dashboard-chart-footnote">
            {c.sku_count} SKUs in the {formatMonth(c.cycle_date)} cycle with a forecast for that month; units of the
            demand series (pieces). Not converted to pesos — no per-piece cost is recorded.
          </p>
        </div>
      )}
    </div>
  );
};

// ── Diagnostic: why this portfolio is hard to forecast ───────────────────
// The dashboard's only "why did it happen" widget. Reads GET /segment/
// summary, which rolls up the SAME sku_traits columns (cv, trend) that the
// per-SKU panel on SKU Forecast shows, so the portfolio view and the
// drill-down can never disagree.
//
// Volatility bands are a display convention over the coefficient of
// variation of monthly demand, defined once in backend/routers/segment.py
// (cv < 0.5 steady, < 1.0 variable, else erratic) — never re-derived here.
// Colour follows the app's semantic rule: erratic is the "act" red because
// it is the band that explains missed forecasts, steady is healthy green.
const VOLATILITY_META = {
  high: { label: 'Erratic', color: SEMANTIC.act, hint: 'CV ≥ 1.0 — month-to-month demand swings wildly' },
  medium: { label: 'Variable', color: SEMANTIC.watch, hint: 'CV 0.5–1.0 — noticeable swings' },
  low: { label: 'Steady', color: SEMANTIC.healthy, hint: 'CV < 0.5 — predictable month to month' },
  unknown: { label: 'Not measured', color: SEMANTIC.noData, hint: 'No CV recorded for these SKUs' },
};

const TREND_META = {
  up: { label: 'Rising', arrow: '↗' },
  none: { label: 'No clear trend', arrow: '→' },
  down: { label: 'Falling', arrow: '↘' },
};

export const DemandVolatilityWidget = ({ summary, emptyReason }) => {
  const s = summary || {};
  const buckets = s.volatility || [];
  const hasData = (s.analyzed_count ?? 0) > 0 && buckets.length > 0;
  const total = buckets.reduce((sum, b) => sum + (b.sku_count || 0), 0);

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Why demand is hard to forecast</h4>
          <p>
            How steady each Category A SKU&apos;s monthly demand is (coefficient of variation) and which way
            it trends — the measured reasons behind the forecast accuracy above.
          </p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || s.blocked_reason || 'No segmentation data for this scope'}</p>
      ) : (
        <div className="chart-widget-body">
          <div className="policy-bars">
            {buckets.map((b) => {
              const meta = VOLATILITY_META[b.band] || VOLATILITY_META.unknown;
              const pct = total > 0 ? (b.sku_count / total) * 100 : 0;
              const revPct = b.revenue_share != null ? Math.round(b.revenue_share * 100) : null;
              return (
                <div className="policy-bar-row" key={b.band} title={meta.hint}>
                  <span className="policy-bar-label">{meta.label}</span>
                  <div
                    className="policy-bar-track"
                    role="img"
                    aria-label={`${meta.label}: ${b.sku_count} SKUs`}
                  >
                    <span style={{ width: `${pct}%`, backgroundColor: meta.color }} />
                  </div>
                  <span className="policy-bar-value">
                    {b.sku_count} SKUs
                    {/* Revenue share is what makes the band actionable: 60
                        erratic SKUs matter differently if they carry 25% of
                        revenue than if they carry 2%. Omitted, not zeroed,
                        when no SKU in the band recorded a share. */}
                    {revPct != null && <span className="volatility-rev"> · {revPct}% rev</span>}
                  </span>
                </div>
              );
            })}
          </div>

          <div className="volatility-trend-row">
            {(s.trend || []).map((t) => {
              const meta = TREND_META[t.trend] || { label: t.trend, arrow: '·' };
              return (
                <span className="volatility-trend-chip" key={t.trend}>
                  <span className="volatility-trend-arrow" aria-hidden="true">{meta.arrow}</span>
                  <strong>{t.sku_count}</strong> {meta.label}
                </span>
              );
            })}
          </div>

          <p className="dashboard-chart-footnote">
            {s.analyzed_count} Category A SKUs in the {formatMonth(s.cohort_period)} cohort · trend from
            Mann-Kendall (p &lt; 0.05). Open a SKU on SKU Forecast for its own reason.
          </p>
        </div>
      )}
    </div>
  );
};
