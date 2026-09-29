import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import {
  ComposedChart, BarChart, Bar, Cell, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, ReferenceLine
} from 'recharts';
import { HelpCircle, ArrowRight, RotateCcw, CheckCircle2 } from 'lucide-react';
import { CHART_COLORS, STATUS_TIERS, COLORS, SEMANTIC } from '../theme/colors';
import { formatMonth } from '../utils/formatDate';
import { formatUnits } from '../utils/formatNumber';
import { chartAnim, prefersReducedMotion, CHART_ANIM_DURATION, CHART_ANIM_STAGGER } from '../theme/motion';
import { useChartZoom, ChartZoomSlider, SeriesFill, seriesDot, pointLabels, GRID_PROPS, EDGE_LABEL_MARGIN } from './ChartZoom';
import { ChartTable, ChartViewToggle } from './ChartTable';
import { DEFAULT_PRINCIPAL, PRINCIPALS, labelForPrincipal } from '../principals';
import { isPlaceholderPeriod } from '../dataMode';
import { placeholderSpan, renderPlaceholderBand } from '../utils/placeholderBand';
import { LoadingStatus, SkeletonChart } from './Skeleton';
import './Charts.css';

// Legend entry for the placeholder band (utils/placeholderBand.jsx).
const PlaceholderLegendItem = () => (
  <li className="legend-item">
    <span className="legend-placeholder" aria-hidden="true" />
    Placeholder months — not SSM&apos;s data
  </li>
);

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
                <CartesianGrid {...GRID_PROPS} />
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
                  dot={seriesDot({ color: CHART_COLORS.stockSeries })}
                  activeDot={{ r: 5 }}
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
      {/* Ink text with the status swatch beside it — the colour marks the
          direction, the words stay readable. */}
      <p className="chart-tooltip-row" style={{ marginTop: '0.35rem', fontWeight: 700 }}>
        <span className="chart-tooltip-swatch" style={{ backgroundColor: shortfall ? COLORS.critical : COLORS.warning }} aria-hidden="true" />
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
            <CartesianGrid vertical horizontal={false} stroke={CHART_COLORS.gridline} strokeWidth={1} />
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

const SalesStockTooltip = ({ active, payload, label, placeholder }) => {
  if (!active || !payload || !payload.length) return null;
  // The stock series is drawn twice — the Line, plus the wash under it —
  // so the raw payload can carry that value twice over. The fill declares
  // tooltipType="none", which Recharts passes through as `type` on the
  // entry; dropping those leaves exactly one row per real series.
  const rows = payload.filter((p) => p.type !== 'none');
  if (!rows.length) return null;
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>{formatAxisPeriod(label)}</p>
      {/* Swatch + ink text: the mark beside the words carries identity —
          text never wears the series colour. */}
      {rows.map((p) => (
        <p key={p.dataKey} className="chart-tooltip-row">
          <span className="chart-tooltip-swatch" style={{ backgroundColor: p.color }} aria-hidden="true" />
          {p.name}: <strong>{formatCompactPesos(p.value)}</strong>
        </p>
      ))}
      {isPlaceholderPeriod(label, placeholder) && (
        <p className="chart-tooltip-placeholder">Placeholder month — not SSM&apos;s data</p>
      )}
    </div>
  );
};

// No supplier allocation schedule exists anywhere in the schema or the
// source files; SSM has never provided one. This series is
// backend/routers/dashboard.py's sales_vs_stock[].received — the peso value
// of purchases actually RECEIVED (Purchase_Fact_Real.net_amount).
//
// It was labelled "Fixed Allocation" (product decision, 2026-08) even
// though no allocation figure exists to plot. Renamed 2026-09-23: a chart
// legend is read on its own, away from the subtitle that explained the
// substitution, and a reader has no way to tell a stand-in from the real
// thing when the stand-in wears the real thing's name. The subtitle still
// says it stands in for the allocation schedule. SalesStockTooltip renders
// whatever `name` each Line declares, so this constant is the only place
// the label lives.
const RECEIVED_LABEL = 'Purchases received';

// Sales vs. Stock on Hand — the dashboard's hero chart. `data` is
// [{ period, sales, stockOnHand, received }], all three in pesos (GET
// /dashboard sums stock_on_hand and received as peso figures specifically
// so all three plot on one axis — see backend/routers/dashboard.py's
// kpis.soh_value and sales_vs_stock[].received docstring sections). No
// flat ReferenceLine for `received`: it varies per period like the other
// two series, so it's a dashed Line, not a constant.
//
// `insight` is GET /dashboard's sales_vs_stock_insight: the one-sentence
// takeaway under the title and the peak/low sales months this chart
// labels — computed by the backend from the same rows, never typed here.
export const SalesVsStockWidget = ({ data = [], emptyReason, placeholder = null, insight = null }) => {
  const hasData = data.length > 0;
  // Windows over whatever range the page's date filter fetched. At a wide
  // range that is 38 months, far more than the XAxis can label without
  // skipping — narrowing the window is what puts every month back on screen.
  const zoom = useChartZoom(data);
  const [view, setView] = useState('chart');
  // Hovering one legend entry or line pulls that series forward and drops
  // the others back — with three peso lines on one axis, this is how a
  // reader isolates the one they're tracing.
  const [focusKey, setFocusKey] = useState(null);
  const dimmable = (key) => (focusKey && focusKey !== key ? 0.25 : 1);
  const focusHandlers = (key) => ({
    onMouseEnter: () => setFocusKey(key),
    onMouseLeave: () => setFocusKey(null),
  });
  // A legend entry with no drawn series is a phantom. Live,
  // Purchase_Fact_Real holds Del Monte rows only, so `received` is null
  // for every Unilever period: the "Fixed Allocation" line never drew a
  // single point while its legend swatch still claimed a series existed.
  // The Line and its legend entry now appear together, only when at least
  // one real point exists — and the subtitle says which case it is.
  const hasReceived = data.some((pt) => pt.received != null);
  // Preview only: the placeholder months inside the visible window, and
  // whether the fetched range holds any at all (the legend entry).
  const bandSpan = placeholderSpan(zoom.view, placeholder);
  const hasPlaceholder = placeholderSpan(data, placeholder) != null;

  // Direct labels: each line's latest value at its end, plus the backend's
  // peak/low sales months. Selective by design — never a number on every
  // point. End labels drop out (legend + tooltip take over) when the two
  // lines finish too close together to label without overlap, measured
  // against the window's own value span.
  const labels = useMemo(() => {
    const rows = zoom.view;
    const lastWith = (key) => [...rows].reverse().find((pt) => pt[key] != null) ?? null;
    const lastSales = lastWith('sales');
    const lastStock = lastWith('stockOnHand');
    const values = rows.flatMap((pt) => [pt.sales, pt.stockOnHand, hasReceived ? pt.received : null])
      .filter((v) => v != null);
    const span = values.length ? Math.max(...values) - Math.min(...values) : 0;
    const collide = lastSales && lastStock && lastSales.period === lastStock.period && span > 0
      && Math.abs(lastSales.sales - lastStock.stockOnHand) / span < 0.09;
    const salesEntries = [];
    if (lastSales && !collide) {
      salesEntries.push({
        period: lastSales.period,
        text: `Sales ${formatCompactPesos(lastSales.sales)}`,
        below: lastStock && lastSales.sales < (lastStock.stockOnHand ?? -Infinity),
      });
    }
    // The backend's peak/low sales months — skipped at the line's end,
    // where the end label already carries that value.
    for (const mark of [insight?.peak, insight?.low]) {
      if (mark && mark.period !== lastSales?.period) {
        salesEntries.push({ period: mark.period, text: mark.label, below: mark === insight?.low });
      }
    }
    const stockEntries = lastStock && !collide
      ? [{
          period: lastStock.period,
          text: `Stock ${formatCompactPesos(lastStock.stockOnHand)}`,
          below: !(lastSales && lastSales.sales < (lastStock.stockOnHand ?? -Infinity)),
        }]
      : [];
    return {
      sales: pointLabels(rows, salesEntries),
      stock: pointLabels(rows, stockEntries),
    };
  }, [zoom.view, hasReceived, insight]);

  const tableColumns = [
    { key: 'period', label: 'Month', format: (v) => formatAxisPeriod(v), align: 'left' },
    { key: 'sales', label: 'Sales', format: (v) => formatCompactPesos(v) },
    { key: 'stockOnHand', label: 'Stock on hand', format: (v) => formatCompactPesos(v) },
    ...(hasReceived ? [{ key: 'received', label: RECEIVED_LABEL, format: (v) => formatCompactPesos(v) }] : []),
  ];

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Sales vs Stock on Hand <span className="chart-unit">₱</span></h4>
          <p>
            Monthly revenue and stock-on-hand valuation, in pesos.
            {hasReceived
              ? ' The purchases-received line stands in for the supplier allocation schedule, which SSM has not yet provided — it is what was bought, not an allocation.'
              : ' No purchases line: Unilever has no purchase records, so the line appears only in the Del Monte view.'}
          </p>
          {/* The backend's takeaway sentence, from the same rows this
              chart plots (sales_vs_stock_insight). */}
          {insight?.text && <p className="chart-insight">{insight.text}</p>}
        </div>
        {hasData && <ChartViewToggle view={view} onChange={setView} label="Sales vs stock: chart or table" />}
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No data available for this range'}</p>
      ) : view === 'table' ? (
        <ChartTable
          columns={tableColumns}
          rows={data}
          caption="Sales versus stock on hand by month, in pesos"
        />
      ) : (
        <>
          <ul className="custom-legend custom-legend-top">
            <li
              className="legend-item"
              {...focusHandlers('sales')}
            >
              <span className="legend-line" style={{ borderTopColor: CHART_COLORS.salesSeries }} />
              Sales
            </li>
            <li
              className="legend-item"
              {...focusHandlers('stockOnHand')}
            >
              <span className="legend-line" style={{ borderTopColor: CHART_COLORS.stockSeries }} />
              Stock on hand
            </li>
            {hasReceived && (
              <li className="legend-item" {...focusHandlers('received')}>
                <span className="legend-line legend-line-dashed" style={{ borderTopColor: COLORS.forecast }} />
                {RECEIVED_LABEL}
              </li>
            )}
            {hasPlaceholder && <PlaceholderLegendItem />}
          </ul>
          <div className={`chart-container${zoom.canPan ? ' chart-pannable' : ''}`} ref={zoom.containerRef} {...zoom.panHandlers}>
            <ResponsiveContainer width="99%" height="100%">
              <ComposedChart data={zoom.view} margin={{ top: 20, right: EDGE_LABEL_MARGIN, left: 0, bottom: 10 }}>
                <defs>
                  {/* ONE wash, under stock only — two overlapping gradients
                      turned muddy where the lines crossed, and the wash's
                      job (tie the band to its line) needs only the series
                      that reads as a level rather than a flow. */}
                  <SeriesFill id="fill-stock" color={CHART_COLORS.stockSeries} />
                </defs>
                <CartesianGrid {...GRID_PROPS} />
                {renderPlaceholderBand(bandSpan)}
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
                <Tooltip content={<SalesStockTooltip placeholder={placeholder} />} />
                {/* The wash is declared ahead of the Lines so both lines
                    paint on top of it. baseValue="dataMin" anchors it to the
                    axis floor rather than to zero, which keeps the Y domain
                    exactly as it was. */}
                <Area
                  type="linear"
                  dataKey="stockOnHand"
                  stroke="none"
                  fill="url(#fill-stock)"
                  baseValue="dataMin"
                  legendType="none"
                  tooltipType="none"
                  opacity={dimmable('stockOnHand')}
                  {...zoom.zoomAnim(1)}
                />
                {/* Straight segments (linear), not smoothed curves: these
                    are monthly totals, and a curve suggests values between
                    the months that don't exist. */}
                <Line
                  type="linear"
                  dataKey="sales"
                  name="Sales"
                  stroke={CHART_COLORS.salesSeries}
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeOpacity={dimmable('sales')}
                  dot={seriesDot({ color: CHART_COLORS.salesSeries })}
                  activeDot={{ r: 6 }}
                  label={labels.sales}
                  {...focusHandlers('sales')}
                  {...zoom.zoomAnim(0)}
                />
                <Line
                  type="linear"
                  dataKey="stockOnHand"
                  name="Stock on hand"
                  stroke={CHART_COLORS.stockSeries}
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeOpacity={dimmable('stockOnHand')}
                  dot={seriesDot({ color: CHART_COLORS.stockSeries })}
                  activeDot={{ r: 6 }}
                  label={labels.stock}
                  {...focusHandlers('stockOnHand')}
                  {...zoom.zoomAnim(1)}
                />
                {hasReceived && (
                  <Line
                    type="linear"
                    dataKey="received"
                    name={RECEIVED_LABEL}
                    stroke={COLORS.forecast}
                    strokeDasharray="7 5"
                    strokeWidth={2}
                    strokeOpacity={dimmable('received')}
                    dot={seriesDot({ color: COLORS.forecast })}
                    activeDot={{ r: 6 }}
                    {...focusHandlers('received')}
                    {...zoom.zoomAnim(2)}
                  />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <ChartZoomSlider zoom={zoom} zoomInRight />
        </>
      )}
    </div>
  );
};

const ABC_TIER_COLORS = { A: COLORS.abcA, B: COLORS.abcB, C: COLORS.abcC };
const abcTierColor = (tier) => ABC_TIER_COLORS[tier] || CHART_COLORS.abcRamp[0];

// What each tier is called and what it means for the rest of the app, in
// plain words — the manuscript's own tier table (3.4.1.2): A gets the full
// predictive and prescriptive treatment, B descriptive monitoring only, C
// minimal monitoring. Without this the card showed "A / B / C" and left the
// reader to guess why a tier matters.
const ABC_TIER_ROLE = {
  A: { name: 'Top sellers', role: 'The only tier the app forecasts and plans reorders for.' },
  B: { name: 'Middle sellers', role: 'Watched on this dashboard only — not forecast, no reorder plan.' },
  C: { name: 'Long tail', role: 'Lowest revenue — kept on minimal monitoring.' },
};
// Del Monte is ranked by product category (it has no SKU-level sales) and
// nothing of Del Monte's is forecast or reordered, so the roles above would
// be false for it.
const DEL_MONTE_TIER_ROLE =
  'Ranked by category sell-out. Del Monte has no SKU-level sales, so no tier here is forecast or reordered.';

// The ring is plain SVG so each segment can be a real keyboard button. Same
// layout the Recharts ring had: it starts at 3 o'clock, runs
// counter-clockwise, with 2° gaps between tiers. The outer radius stops 2px
// short of the box, which leaves room for the selected tier's 2px stroke and
// keeps the ring's left edge on the card title's left edge.
const ABC_DONUT_SIZE = 180;
const ABC_RING_OUTER = 88;
const ABC_RING_INNER = 62;
const ABC_PAD_ANGLE = 2;
// Each principal's tier shares add up to 100% of that principal's revenue.
// Further off than this and they were summed across principals, so they are
// not a share of any revenue this card could name.
const ABC_SHARE_SUM_TOLERANCE = 2;
const ABC_TOOLTIP_GAP = 12;
const ABC_VIEWPORT_MARGIN = 4;

const abcPoint = (radius, degrees) => {
  const angle = (degrees * Math.PI) / 180;
  const centre = ABC_DONUT_SIZE / 2;
  return `${(centre + radius * Math.cos(angle)).toFixed(2)} ${(centre - radius * Math.sin(angle)).toFixed(2)}`;
};

const abcArc = (start, end) => {
  const large = end - start > 180 ? 1 : 0;
  return [
    `M${abcPoint(ABC_RING_OUTER, start)}`,
    `A${ABC_RING_OUTER} ${ABC_RING_OUTER} 0 ${large} 0 ${abcPoint(ABC_RING_OUTER, end)}`,
    `L${abcPoint(ABC_RING_INNER, end)}`,
    `A${ABC_RING_INNER} ${ABC_RING_INNER} 0 ${large} 1 ${abcPoint(ABC_RING_INNER, start)}`,
    'Z',
  ].join(' ');
};

// One arc per tier, sized by its revenue share exactly as the Recharts Pie
// sized it (shares relative to their own sum, minus the gaps).
const abcSegments = (data) => {
  const values = data.map((d) => (Number.isFinite(d.sharePct) && d.sharePct > 0 ? d.sharePct : 0));
  const sum = values.reduce((acc, v) => acc + v, 0);
  const available = 360 - ABC_PAD_ANGLE * values.filter((v) => v > 0).length;
  let angle = 0;
  return data.map((d, i) => {
    const sweep = sum > 0 ? (values[i] / sum) * available : 0;
    const segment = { tier: d.tier, path: sweep > 0 ? abcArc(angle, angle + sweep) : null };
    if (sweep > 0) angle += sweep + ABC_PAD_ANGLE;
    return segment;
  });
};

// The selected tier, SKUs first and revenue second. `facts` come from the
// same abc_mix rows the ring and the share bars draw. A revenue figure that
// can't be trusted (no total, or shares that don't add up to ~100%) reads
// "Revenue not available", and the sentence is left out rather than stated
// on numbers that aren't real.
const AbcTierCard = ({ facts }) => {
  const x = facts.skuPct.toFixed(0);
  const y = facts.revenuePct != null ? facts.revenuePct.toFixed(0) : null;
  const revenueKnown = facts.amount != null && y != null;
  const role = ABC_TIER_ROLE[facts.tier];
  const roleText = facts.units === 'categories' ? DEL_MONTE_TIER_ROLE : role?.role;
  return (
    <div className="abc-tier-card" aria-live="polite">
      <p className="abc-tier-card-name">
        <span className="legend-color" style={{ backgroundColor: abcTierColor(facts.tier) }} aria-hidden="true" />
        Tier {facts.tier}{role && <span className="abc-tier-card-alias">· {role.name}</span>}
      </p>
      {/* What the tier is FOR, before any number: the one line that says
          why a reader should care which tier a SKU is in. */}
      {roleText && <p className="abc-tier-card-role">{roleText}</p>}
      {/* Stacked when the card is narrow; side by side as it widens (see
          the container queries in Charts.css). Reading order stays SKUs,
          then revenue, then the sentence at every width. */}
      <div className="abc-tier-card-body">
        <div className="abc-tier-card-stat">
          <p className="abc-tier-card-skus">{facts.count.toLocaleString()} {facts.units}</p>
          <p className="abc-tier-card-note">{x}% of all {facts.units}</p>
        </div>
        <div className="abc-tier-card-stat">
          <p className={`abc-tier-card-revenue${facts.amount == null ? ' is-unavailable' : ''}`}>
            {facts.amount != null ? `${formatCompactPesos(facts.amount)} revenue` : 'Revenue not available'}
          </p>
          {y != null && <p className="abc-tier-card-note">{y}% of total revenue</p>}
        </div>
        {revenueKnown && (
          <p className="abc-tier-card-insight">
            <span>
              {Number(y) > Number(x) ? (
                <>Tier {facts.tier} is only <strong>{x}%</strong> of {facts.units} but brings in <strong>{y}%</strong> of revenue.</>
              ) : (
                <>Tier {facts.tier} is <strong>{x}%</strong> of {facts.units} but brings in only <strong>{y}%</strong> of revenue.</>
              )}
            </span>
          </p>
        )}
      </div>
      <Link to="/abc" className="abc-tier-card-link">
        See every SKU and its tier <ArrowRight size={12} aria-hidden="true" />
      </Link>
    </div>
  );
};

// Hover detail for one segment. Portalled to <body> with position: fixed, so
// no card's overflow can clip it and nothing on the page sits above it.
// Placed 12px from the pointer on the side away from the ring's centre;
// when that would leave the viewport it flips (up/down, then left/right),
// and any spot that would cover the ring is skipped. Mouse only — a tap
// selects instead.
const AbcHoverTooltip = ({ hover, facts, ringRef }) => {
  const tipRef = useRef(null);
  const [pos, setPos] = useState(null);

  useLayoutEffect(() => {
    const tip = tipRef.current?.getBoundingClientRect();
    const ring = ringRef.current?.getBoundingClientRect();
    if (!tip || !ring) return;
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const m = ABC_VIEWPORT_MARGIN;
    const gap = ABC_TOOLTIP_GAP;
    const scale = ring.width / ABC_DONUT_SIZE;
    const cx = ring.left + ring.width / 2;
    const cy = ring.top + ring.height / 2;
    const clearRadius = (ABC_RING_OUTER + 2) * scale;
    const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
    const onScreen = (l, t) => l >= m && t >= m && l + tip.width <= vw - m && t + tip.height <= vh - m;
    const clearOfRing = (l, t) => {
      const nx = clamp(cx, l, l + tip.width);
      const ny = clamp(cy, t, t + tip.height);
      return (nx - cx) ** 2 + (ny - cy) ** 2 > clearRadius ** 2;
    };
    // Corner of the tooltip 12px from (x, y), towards side (sx, sy).
    const beside = (x, y, sx, sy) => [sx > 0 ? x + gap : x - gap - tip.width, sy > 0 ? y + gap : y - gap - tip.height];
    const sx = hover.x >= cx ? 1 : -1;
    const sy = hover.y >= cy ? 1 : -1;
    // A pointer deep in the ring is pushed out to the ring's edge first.
    const r = Math.hypot(hover.x - cx, hover.y - cy) || 1;
    const edge = Math.max(r, ABC_RING_OUTER * scale) / r;
    const ex = cx + (hover.x - cx) * edge;
    const ey = cy + (hover.y - cy) * edge;
    const candidates = [
      beside(hover.x, hover.y, sx, sy), beside(hover.x, hover.y, sx, -sy),
      beside(hover.x, hover.y, -sx, sy), beside(hover.x, hover.y, -sx, -sy),
      beside(ex, ey, sx, sy), beside(ex, ey, sx, -sy), beside(ex, ey, -sx, sy), beside(ex, ey, -sx, -sy),
      [ring.right + gap, clamp(hover.y - tip.height / 2, m, vh - tip.height - m)],
      [ring.left - gap - tip.width, clamp(hover.y - tip.height / 2, m, vh - tip.height - m)],
      [clamp(hover.x - tip.width / 2, m, vw - tip.width - m), ring.bottom + gap],
      [clamp(hover.x - tip.width / 2, m, vw - tip.width - m), ring.top - gap - tip.height],
    ];
    const [left, top] = candidates.find(([l, t]) => onScreen(l, t) && clearOfRing(l, t)) || candidates[0];
    setPos({ left: clamp(left, m, vw - tip.width - m), top: clamp(top, m, vh - tip.height - m) });
  }, [hover, ringRef]);

  const revenueLine = facts.revenuePct == null
    ? 'Revenue not available'
    : [facts.amount != null ? formatCompactPesos(facts.amount) : null, `${facts.revenuePct.toFixed(0)}% of revenue`]
      .filter(Boolean).join(' · ');

  return createPortal(
    <div
      ref={tipRef}
      className="abc-hover-tip"
      role="tooltip"
      style={pos ? { left: pos.left, top: pos.top } : { left: 0, top: 0, visibility: 'hidden' }}
    >
      <span className="abc-hover-tip-title">Tier {facts.tier}</span>
      <span>{facts.count.toLocaleString()} {facts.units} · {facts.skuPct.toFixed(0)}% of {facts.units}</span>
      <span>{revenueLine}</span>
    </div>,
    document.body,
  );
};

// ABC classification — `data` is [{ tier: 'A'|'B'|'C', count, sharePct }],
// `revenue` is GET /dashboard's abc_revenue {period, total, blocked_reason}.
// The ring encodes each tier's share of revenue, with the selected tier's
// share written in its centre; clicking a segment or its legend item picks
// the tier the card beside it describes (Tier A on load, never nothing). The
// paired bars underneath put all three tiers' share of revenue next to their
// share of SKUs.
//
// The subtitle says what the card is FOR and how a tier is decided (the
// 80 / 95% revenue cutoffs) and for which month — the ring alone answered
// "how big is each slice" but not "why should I care", and without the
// month the 132 here read as contradicting the ABC page's carried-forward
// total.
// `coverage` names the principals the run covers when narrower than the
// page's filter ("Unilever only", Dashboard.jsx's coverageNote). `units` is
// what a row is: 'SKUs', or 'categories' for Del Monte, which is ranked by
// product category.
export const ABCDonutWidget = ({ data = [], revenue, rules, emptyReason, note, coverage = null, units = 'SKUs' }) => {
  const [selectedTier, setSelectedTier] = useState('A');
  const [hover, setHover] = useState(null);
  const ringRef = useRef(null);

  const hasData = data.length > 0;
  const total = data.reduce((sum, d) => sum + d.count, 0);
  const skuSharePct = (d) => (total > 0 ? (d.count / total) * 100 : 0);

  const revenueTotal = revenue?.total != null && Number.isFinite(Number(revenue.total)) ? Number(revenue.total) : null;
  const shareSum = data.reduce((sum, d) => sum + Number(d.sharePct), 0);
  const sharesAddUp = Number.isFinite(shareSum) && Math.abs(shareSum - 100) <= ABC_SHARE_SUM_TOLERANCE;
  // GET /dashboard withholds revenue shares a run can't support (two
  // principals' shares are fractions of two different totals). The ring is
  // then sized by counts and the revenue bar is left out, not drawn from
  // null.
  const sharePairs = [
    ...(sharesAddUp ? [{ key: 'sharePct', label: 'Share of revenue', value: (d) => d.sharePct }] : []),
    { key: 'skuPct', label: `Share of ${units}`, value: skuSharePct },
  ];
  const factsFor = (d) => ({
    tier: d.tier,
    count: d.count,
    units,
    skuPct: skuSharePct(d),
    revenuePct: sharesAddUp ? d.sharePct : null,
    amount: sharesAddUp && revenueTotal != null ? (revenueTotal * d.sharePct) / 100 : null,
  });

  const selected = data.find((d) => d.tier === selectedTier) || data.find((d) => d.tier === 'A') || data[0];
  const hovered = hover ? data.find((d) => d.tier === hover.tier) : null;
  const segments = abcSegments(sharesAddUp ? data : data.map((d) => ({ ...d, sharePct: skuSharePct(d) })));
  const unitsTitle = units.charAt(0).toUpperCase() + units.slice(1);
  const selectedFacts = selected ? factsFor(selected) : null;
  const rankedMonth = revenue?.period ? formatMonth(revenue.period) : null;
  const centre = ABC_DONUT_SIZE / 2;

  const selectOnKey = (tier) => (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setSelectedTier(tier);
    }
  };
  const trackHover = (tier) => (e) => {
    if (e.pointerType === 'mouse') setHover({ tier, x: e.clientX, y: e.clientY });
  };

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>ABC classification</h4>
          {/* The cutoffs are GET /dashboard's abc_rules (the ABC run's own
              constants), never restated here. */}
          <p>
            Which products earn the most. {unitsTitle} are ranked by revenue{rankedMonth ? ` in ${rankedMonth}` : ''}
            {rules
              ? `: Tier A makes up the first ${Math.round(rules.tier_a_cutoff * 100)}%, `
                + `B the next ${Math.round((rules.tier_b_cutoff - rules.tier_a_cutoff) * 100)}%, `
                + `C the last ${Math.round((1 - rules.tier_b_cutoff) * 100)}%.`
              : '.'}
            {/* With only a handful of categories a tier can't land on its
                cut-off (Del Monte 2025-12: A 71%, B 18%, C 11%). */}
            {units === 'categories' && ' With only a few categories, a tier cannot land exactly on its cut-off.'}
            {' '}Click a tier for details.
          </p>
          {coverage && <p className="chart-placeholder-note">{coverage}</p>}
          {!sharesAddUp && revenue?.blocked_reason && <p className="chart-placeholder-note">{revenue.blocked_reason}</p>}
          {note && <p className="chart-placeholder-note">{note}</p>}
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No ABC classification available'}</p>
      ) : (
        <div className="chart-widget-body">
          <div className="abc-overview">
            <div className="abc-donut-col">
              <svg
                ref={ringRef}
                className="abc-donut"
                width={ABC_DONUT_SIZE}
                height={ABC_DONUT_SIZE}
                viewBox={`0 0 ${ABC_DONUT_SIZE} ${ABC_DONUT_SIZE}`}
                role="group"
                aria-label={sharesAddUp ? 'Share of revenue by tier' : `Share of ${units} by tier`}
              >
                {segments.map((s) => s.path && (
                  <path
                    key={s.tier}
                    d={s.path}
                    fill={abcTierColor(s.tier)}
                    className={`abc-seg${s.tier === selected.tier ? ' is-selected' : ''}`}
                    role="button"
                    tabIndex={0}
                    aria-pressed={s.tier === selected.tier}
                    aria-label={`Tier ${s.tier}`}
                    onClick={() => setSelectedTier(s.tier)}
                    onKeyDown={selectOnKey(s.tier)}
                    onPointerEnter={trackHover(s.tier)}
                    onPointerMove={trackHover(s.tier)}
                    onPointerLeave={() => setHover(null)}
                  />
                ))}
                {/* The selected tier's headline number, where the eye lands
                    first. Revenue share when it can be trusted, else the SKU
                    count (the tier card beside it says why). */}
                {selectedFacts && (
                  <g className="abc-donut-centre" aria-hidden="true">
                    <text x={centre} y={centre - 18} textAnchor="middle" className="abc-donut-centre-tier">
                      Tier {selectedFacts.tier}
                    </text>
                    <text x={centre} y={centre + 9} textAnchor="middle" className="abc-donut-centre-value">
                      {selectedFacts.revenuePct != null
                        ? `${selectedFacts.revenuePct.toFixed(0)}%`
                        : selectedFacts.count.toLocaleString()}
                    </text>
                    <text x={centre} y={centre + 27} textAnchor="middle" className="abc-donut-centre-label">
                      {selectedFacts.revenuePct != null ? 'of revenue' : units}
                    </text>
                  </g>
                )}
              </svg>
              <ul className="abc-legend">
                {data.map((d) => (
                  <li key={d.tier}>
                    <button
                      type="button"
                      className={`abc-legend-btn${d.tier === selected.tier ? ' is-selected' : ''}`}
                      aria-pressed={d.tier === selected.tier}
                      aria-label={`Tier ${d.tier}${ABC_TIER_ROLE[d.tier] ? `, ${ABC_TIER_ROLE[d.tier].name}` : ''}`}
                      onClick={() => setSelectedTier(d.tier)}
                    >
                      <span className="legend-color" style={{ backgroundColor: abcTierColor(d.tier) }} aria-hidden="true" />
                      <span className="abc-legend-tier">{d.tier}</span>
                      {ABC_TIER_ROLE[d.tier] && <span className="abc-legend-name">{ABC_TIER_ROLE[d.tier].name}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <AbcTierCard facts={factsFor(selected)} />
          </div>
          <div
            className="abc-share-pair"
            role="img"
            aria-label={sharesAddUp ? `Share of revenue versus share of ${units}, by tier` : `Share of ${units}, by tier`}
          >
            {sharePairs.map((pair) => (
              <div className="abc-share-row" key={pair.key}>
                <span className="abc-share-label">{pair.label}</span>
                <div className="abc-share-track">
                  {data.map((d) => {
                    const v = pair.value(d);
                    return (
                      <span
                        key={d.tier}
                        style={{ width: `${v}%`, backgroundColor: abcTierColor(d.tier) }}
                        title={`Tier ${d.tier}: ${v.toFixed(0)}% ${pair.key === 'skuPct' ? `of ${units} (${d.count})` : 'of revenue'}`}
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
      {hovered && <AbcHoverTooltip hover={hover} facts={factsFor(hovered)} ringRef={ringRef} />}
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
  noData: SEMANTIC.noData,
};

// One bar per ABC tier — `data` is
// [{ tier: 'A'|'B'|'C', inStock, deadStock, noData, pendingReorderCount }],
// from GET /dashboard's tier_stock. Each bar splits that tier's classified
// products into Active / Inactive / no stock record, which never overlap and
// add up to the tier — a composition view ("what's this tier made of"), not
// an absolute-count comparison across tiers, so a small tier's bar isn't
// visually dwarfed by a large one. Pending reorders are NOT a segment: until
// 2026-09-29 they were stacked beside Active although they overlap it (every
// Class A SKU was both), so Class A read half "pending" while the note said
// all of it was Active. They are listed under the bars instead. No
// allocation segment: no supplier allocation table exists anywhere in the
// schema (see GET /dashboard's kpis.weeks_of_cover docstring), and the proxy
// SalesVsStockWidget uses instead (Purchase_Fact_Real) has no product key to
// break down by ABC tier at all — there is nothing honest to plot here.
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
export const CategoryStockBarWidget = ({ data = [], emptyReason, note, period = null, coverage = null }) => {
  const hasData = data.length > 0;
  const hasDead = data.some((row) => (row.deadStock || 0) > 0);
  const hasNoData = data.some((row) => (row.noData || 0) > 0);
  const hasPending = data.some((row) => (row.pendingReorderCount || 0) > 0);
  // Every count that could be flagged, for the all-clear line below.
  const flaggedTotal = data.reduce((sum, row) => sum + (row.inStock || 0) + (row.deadStock || 0), 0);
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
          {coverage && <p className="chart-placeholder-note">{coverage}</p>}
          {note && <p className="chart-placeholder-note">{note}</p>}
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No stock status data available'}</p>
      ) : (
        <div className="chart-widget-body">
          {/* When no tier has a single Inactive product, the bars alone
              just read "everything is green" — say the finding outright.
              The month is GET /dashboard's tier_stock_period (the snapshot
              the flags were read at), never typed here. */}
          {!hasDead && flaggedTotal > 0 && (
            <p className="tier-stock-note">
              <CheckCircle2 size={15} aria-hidden="true" />
              <span>
                No dead stock flagged{period ? ` in ${formatMonth(period)}` : ''} — every one of the{' '}
                {flaggedTotal.toLocaleString()} classified products with a stock record is marked Active.
              </span>
            </p>
          )}
          <div className="tier-stock-bars">
            {data.map((row, index) => {
              const inStock = row.inStock || 0;
              const deadStock = row.deadStock || 0;
              const pendingReorderCount = row.pendingReorderCount || 0;
              const noData = row.noData || 0;
              const total = inStock + deadStock + noData;
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
                        <span style={{ width: `${pct(noData)}%`, backgroundColor: WAREHOUSE_STATUS_COLORS.noData }} />
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
            {hasNoData && (
              <li className="legend-item">
                <span className="legend-color" style={{ backgroundColor: WAREHOUSE_STATUS_COLORS.noData, borderRadius: '3px' }} />
                No stock record
              </li>
            )}
          </ul>
          {/* Overlaps Active, so listed rather than drawn. The rows are GET
              /dashboard's tier_stock pending counts for the LP's current
              cycle, grouped by each SKU's tier in the latest ABC run. */}
          {hasPending && (
            <p className="chart-placeholder-note">
              Pending reorder recommendations in the LP&apos;s current cycle:{' '}
              {data.map((row) => `${row.tier} ${(row.pendingReorderCount || 0).toLocaleString()}`).join(' · ')}.
              {' '}The LP plans Category A; rows now in B or C come from a cycle solved against an earlier ABC run.
            </p>
          )}
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
        <p className="chart-tooltip-row">
          <span className="chart-tooltip-swatch" style={{ backgroundColor: CHART_COLORS.salesSeries }} aria-hidden="true" />
          Actual demand: <strong>{Math.round(row.actual).toLocaleString()} units</strong>
        </p>
      )}
      {row.forecast != null && (
        <p className="chart-tooltip-row">
          <span className="chart-tooltip-swatch" style={{ backgroundColor: COLORS.forecast }} aria-hidden="true" />
          Forecast: <strong>{Math.round(row.forecast).toLocaleString()} units</strong>
        </p>
      )}
      {row.confidenceBase != null && row.confidenceBand != null && row.confidenceBand > 0 && (
        <p className="chart-tooltip-row">
          <span className="chart-tooltip-swatch" style={{ backgroundColor: COLORS.forecastBg }} aria-hidden="true" />
          Range: <strong>
            {Math.round(row.confidenceBase).toLocaleString()} – {Math.round(row.confidenceBase + row.confidenceBand).toLocaleString()}
          </strong>
        </p>
      )}
    </div>
  );
};

// 236k / 1.2M / 940 — the same compaction the pieces axis uses.
const formatCompactQty = (value) => {
  const n = Math.abs(value);
  if (n >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  if (n >= 1_000) return `${Math.round(value / 1_000)}k`;
  return `${Math.round(value)}`;
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
  scopeLabel,
  emptyReason,
  principal,
  onPrincipalChange,
  isUpdating = false,
  insight = null,
  // How many SKUs the series sums (GET /dashboard's gated_sku_count) out of
  // the scope's Category A forecasts (forecast.total_count). The tiles that
  // showed the gate's figures are hidden; this line still says the card is
  // a subset — 19 of 132 on 2026-09-29, when "1.6% below" read as the whole
  // portfolio while all 132 together were +16.4%.
  gatedSkuCount = null,
  reliability = null,
}) => {
  const hasData = series.length > 0;
  const tierACount = reliability?.total_count ?? null;
  const [view, setView] = useState('chart');

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
    // needs 2 adjacent non-null points to draw a segment. The Lines would
    // still show it as an isolated-point dot (seriesDot), but the confidence
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

  // "Forecast starts" divider: the bridge month, where the last actual
  // hands over to the projection — drawn only while it is in the window.
  const forecastStart = useMemo(() => {
    const bridge = chartData.filter((pt) => pt.actual != null && pt.forecast != null).pop();
    return bridge && zoom.view.some((pt) => pt.period === bridge.period) ? bridge.period : null;
  }, [chartData, zoom.view]);

  // The projection's value, labelled at the end of its line.
  const forecastLabels = useMemo(() => {
    const last = [...zoom.view].reverse().find((pt) => pt.forecast != null);
    return pointLabels(zoom.view, last && last.actual == null
      ? [{ period: last.period, text: `Forecast ${formatCompactQty(last.forecast)}` }]
      : []);
  }, [zoom.view]);

  const tableColumns = [
    { key: 'period', label: 'Month', format: (v) => formatAxisPeriod(v), align: 'left' },
    { key: 'actual', label: 'Actual (pieces)', format: (v) => Math.round(v).toLocaleString() },
    { key: 'forecast', label: 'Forecast (pieces)', format: (v) => Math.round(v).toLocaleString() },
    { key: 'confidenceLower', label: 'Range low', format: (v) => Math.round(v).toLocaleString() },
    { key: 'confidenceUpper', label: 'Range high', format: (v) => Math.round(v).toLocaleString() },
  ];

  return (
    <div className={`chart-widget${onPrincipalChange ? ' chart-widget-filterable' : ''}${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          {/* The unit is PIECES here and pesos on the chart above it; the
              y-axis reads "120k" in both, so it is named in the heading. */}
          <h4>Portfolio-level aggregate forecast <span className="chart-unit">pieces</span></h4>
          <p>
            {gatedSkuCount != null && tierACount
              ? `Summed demand across ${gatedSkuCount.toLocaleString()} of the ${tierACount.toLocaleString()} `
                + 'Category A SKUs (those whose forecasts pass the accuracy gate) vs. forecast'
              : 'Summed demand across gated Category A SKUs vs. forecast'}
          </p>
          {/* The card's takeaway, composed by the backend from this same
              series (portfolio_forecast.insight). */}
          {insight?.text && <p className="chart-insight">{insight.text}</p>}
        </div>
        {/* Card-scoped principal filter — re-scopes THIS card only, never
            the page (the Topbar's filter does that). Rendered in the empty
            state too, so a scope with no forecasts can be switched back
            out of. Own class names, not the Topbar's .principal-segment:
            CSS is global and that one carries viewport breakpoints meant
            for the topbar, not a card. */}
        {onPrincipalChange && (
          <div className="card-filter-controls">
            {hasData && <ChartViewToggle view={view} onChange={setView} label="Portfolio forecast: chart or table" />}
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
            {/* Back to the default scope (Unilever), where this card starts on every visit. */}
            <button
              type="button"
              className="card-filter-reset"
              onClick={() => onPrincipalChange(DEFAULT_PRINCIPAL)}
              disabled={principal === DEFAULT_PRINCIPAL}
              title={principal === DEFAULT_PRINCIPAL
                ? `Already showing ${labelForPrincipal(DEFAULT_PRINCIPAL)}`
                : `Reset to ${labelForPrincipal(DEFAULT_PRINCIPAL)}`}
            >
              <RotateCcw size={12} aria-hidden="true" />
              Reset
            </button>
          </div>
        )}
      </div>

      {!hasData && isUpdating ? (
        <>
          <LoadingStatus>Loading forecast…</LoadingStatus>
          <SkeletonChart variant="line" />
        </>
      ) : !hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No forecast data available'}</p>
      ) : (
        <div className={`portfolio-forecast-body${isUpdating ? ' is-refreshing' : ''}`} aria-busy={isUpdating}>
          {/* Gated SKUs / Avg. MAPE / Beat naive tiles kept off the page
              (Audrey, 2026-09-29); the subtitle still says how many SKUs the
              card sums. Dashboard still passes their props; restore from git
              history. */}
          <div className="portfolio-stat-row">
            <div className="portfolio-stat">
              <span className="portfolio-stat-label">Scope</span>
              <span className="portfolio-stat-value portfolio-stat-scope">{scopeLabel}</span>
            </div>
          </div>

          {view === 'table' ? (
            <ChartTable
              columns={tableColumns}
              rows={series}
              caption="Actual demand and forecast by month, in pieces"
            />
          ) : (
            <>
              <ul className="custom-legend custom-legend-top">
                <li className="legend-item">
                  <span className="legend-line" style={{ borderTopColor: CHART_COLORS.salesSeries }} />
                  Actual demand
                </li>
                <li className="legend-item">
                  <span className="legend-line legend-line-dashed" style={{ borderTopColor: COLORS.forecast }} />
                  Forecast
                </li>
                <li className="legend-item">
                  <span className="legend-color" style={{ backgroundColor: COLORS.forecastBg, borderRadius: '3px' }} />
                  Confidence band
                </li>
              </ul>
              <div className={`chart-container${zoom.canPan ? ' chart-pannable' : ''}`} ref={zoom.containerRef} {...zoom.panHandlers}>
                <ResponsiveContainer width="99%" height="100%">
                  <ComposedChart data={zoom.view} margin={{ top: 10, right: EDGE_LABEL_MARGIN, left: 0, bottom: 10 }}>
                    <CartesianGrid {...GRID_PROPS} />
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
                    {/* The uncertainty cone is this chart's ONE fill — the
                        series washes that used to sit under both lines
                        muddied it, and the cone is the fill that carries
                        real information. */}
                    <Area type="linear" dataKey="confidenceBase" stackId="band" stroke="none" fill="transparent" {...zoom.zoomAnim(0)} />
                    <Area type="linear" dataKey="confidenceBand" stackId="band" stroke="none" fill={COLORS.forecastBg} fillOpacity={0.9} {...zoom.zoomAnim(0)} />
                    {/* Where history hands over to projection — the divider
                        the dashed line style is then read against. */}
                    {forecastStart && (
                      <ReferenceLine
                        x={forecastStart}
                        stroke={CHART_COLORS.axisLabel}
                        strokeDasharray="4 4"
                        label={{ value: 'Forecast starts', position: 'insideTopRight', fontSize: 10, fill: CHART_COLORS.axisLabel }}
                      />
                    )}
                    <Line
                      type="linear"
                      dataKey="actual"
                      name="Actual demand"
                      stroke={CHART_COLORS.salesSeries}
                      strokeWidth={2}
                      strokeLinecap="round"
                      dot={seriesDot({ color: CHART_COLORS.salesSeries })}
                      activeDot={{ r: 6 }}
                      connectNulls={false}
                      {...zoom.zoomAnim(1)}
                    />
                    <Line
                      type="linear"
                      dataKey="forecast"
                      name="Forecast"
                      stroke={COLORS.forecast}
                      strokeDasharray="5 3"
                      strokeWidth={2}
                      dot={seriesDot({ color: COLORS.forecast, skip: (p) => p?.actual != null })}
                      activeDot={{ r: 6 }}
                      connectNulls={false}
                      label={forecastLabels}
                      {...zoom.zoomAnim(2)}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <ChartZoomSlider zoom={zoom} zoomInRight />
            </>
          )}
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
// `blurb` states each weight's term in the LP objective as
// analytics/optimization/lp.py actually defines it (Step 19's
// Z = w1·TC − w2·SL + w3·SC) — real methodology wording, replacing the
// "Placeholder:" copy that shipped before 2026-09-26.
//
// One colour for all three rows (CHART_COLORS.lpWeight, the model-output
// indigo): they are co-equal weights of a single objective, not three
// categories, so three hues implied a difference in kind that isn't
// there — and the labels carry identity on their own.
const LP_PRIORITY_ROWS = [
  {
    key: 'cost',
    label: 'Cost',
    blurb: 'The weight on total procurement cost in the LP objective — how strongly the solver favours cheaper order quantities. Cost is minimized: the sum of each SKU’s procurement cost times its order quantity.',
  },
  {
    key: 'service_level',
    label: 'Service level',
    blurb: 'The weight on service level — total ordered quantity relative to total reorder-point demand. It enters the objective negatively, so the solver is rewarded for covering more of the demand and avoiding stockouts.',
  },
  {
    key: 'storage',
    label: 'Storage',
    blurb: 'The weight on storage cost — each SKU’s storage cost per unit times its order quantity, minimized so orders stay within what the warehouse can affordably hold.',
  },
];

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
// priority sliders as a scrollable list, in GET /dashboard's order.
// weights: { cost, service_level, storage } fractions (0-1), from GET
// /dashboard's reorder_preview.lp_weights — seeds the sliders' starting
// position; LP_DEFAULT_PCT is the fallback when the API sends nothing.

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
  //
  // No hardcoded fallback percentages: the API always sends lp_weights
  // (tests pin that), and if a weight ever went missing the row shows an
  // honest null rather than a number this file made up.
  const solverPct = useMemo(() => {
    const read = (key) =>
      typeof weights?.[key] === 'number' ? Math.round(weights[key] * 100) : null;
    return { cost: read('cost'), service_level: read('service_level'), storage: read('storage') };
  }, [weights]);

  // GET /dashboard already orders the rows most-urgent first and, within an
  // urgency, by the Reorder page's own priority (revenue share x units below
  // the reorder point), so the card and the page agree on what comes first.
  // Re-sorting here by order quantity used to override that.
  const sortedRows = rows;

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Reorder recommendations</h4>
          {/* GET /dashboard's reorder_preview has been scoped to the LP's
              current cycle since 2026-09-23 (backend/lp_cycle.py), the same
              rows Reorder Recs lists by default. */}
          <p>LP-optimized purchase quantities for the SKUs the LP planned as Category A · current planning cycle</p>
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
                  <span className="reorder-priority-label">{p.label}</span>
                  <PriorityInfo text={p.blurb} />
                  <span className="reorder-priority-pct">{solverPct[p.key] == null ? '—' : `${solverPct[p.key]}%`}</span>
                </div>
                <div className="reorder-priority-bar" role="img" aria-label={`${p.label}: ${solverPct[p.key] == null ? 'not available' : `${solverPct[p.key]}%`}`}>
                  <span style={{ width: `${solverPct[p.key] ?? 0}%`, backgroundColor: CHART_COLORS.lpWeight }} />
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
                      {formatUnits(r.orderQty)}
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
            Rule = 3 weeks of each SKU&apos;s own forecast; LP = the per-SKU safety stock the optimizer solved for.
          </p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || c.blocked_reason || 'Policy comparison not available'}</p>
      ) : (
        <div className="chart-widget-body">
          {/* The one-number headline (IMPLEMENTATION_PLAN Phase 1.1-1.2):
              units and percent, never pesos. lp_vs_rule_pct is how much
              less buffer the LP holds than the rule; negative = more. */}
          {c.lp_vs_rule_pct != null && (
            <p className="policy-headline">
              <span className="policy-headline-number">{Math.abs(c.lp_vs_rule_pct).toFixed(1)}%</span>
              <span className="policy-headline-text">
                {c.lp_vs_rule_pct >= 0 ? 'less' : 'more'} safety stock under the LP policy than the blanket{' '}
                {c.rule_weeks ?? 3}-week rule, across {c.sku_count} SKUs
              </span>
            </p>
          )}
          <div className="policy-bars">
            {rows.map((r) => (
              <div className="policy-bar-row" key={r.key}>
                <span className="policy-bar-label">{r.label}</span>
                {/* Meter rule: the unfilled track is a lighter step of the
                    fill's own hue, so each bar reads as one meter. */}
                <div
                  className="policy-bar-track"
                  role="img"
                  aria-label={`${r.label}: ${Math.round(r.value).toLocaleString()} units`}
                  style={{ background: `color-mix(in srgb, ${r.color} 12%, var(--color-surface))` }}
                >
                  <span style={{ width: `${(r.value / max) * 100}%`, backgroundColor: r.color }} />
                </div>
                <span className="policy-bar-value">{Math.round(r.value).toLocaleString()} units</span>
              </div>
            ))}
          </div>
          <p className="dashboard-chart-footnote">
            {c.sku_count} SKUs in the {formatMonth(c.cycle_date)} cycle with a forecast for that month; both sides in
            units of the demand series (pieces), the unit the safety stock itself is solved in, so the two
            are compared without a peso conversion.
          </p>
          {/* The headline depends on how many days of demand variability the
              LP's safety stock covers — run_lp.py's --protection-days, 1
              business day by default. Stated beside the number, since it
              changes the answer (reports/PROJECT_DIAGNOSIS_2026-09-21.md). */}
          <p className="policy-assumption">
            <strong>Assumption:</strong> the LP&apos;s safety stock covers the demand variability of the protection
            period it was run with (scripts/run_lp.py --protection-days; the default is 1 business day, with no
            review period or lead time). The comparison is sensitive to that setting, which is still an open
            planning decision.
          </p>
        </div>
      )}
    </div>
  );
};
