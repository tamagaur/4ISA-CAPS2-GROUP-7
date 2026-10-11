import React, { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useNavigate } from 'react-router-dom';
import {
  ComposedChart, BarChart, Bar, Cell, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, ReferenceLine, ReferenceArea
} from 'recharts';
import { ArrowRight, CheckCircle2, Info } from 'lucide-react';
import { CHART_COLORS, STATUS_TIERS, COLORS, SEMANTIC } from '../theme/colors';
import { formatMonth } from '../utils/formatDate';
import { formatUnits } from '../utils/formatNumber';
import { chartAnim, prefersReducedMotion, CHART_ANIM_DURATION, CHART_ANIM_STAGGER } from '../theme/motion';
import { useChartZoom, seriesDot, pointLabels, GRID_PROPS, EDGE_LABEL_MARGIN } from './ChartZoom';
import { ChartTable, ChartViewToggle } from './ChartTable';
import { isPlaceholderPeriod } from '../dataMode';
import { LoadingStatus, SkeletonChart } from './Skeleton';
import InfoTip from './InfoTip';
import ProductName from './ProductName';
import './Charts.css';

// Legend entry for the placeholder band (utils/placeholderBand.jsx).
// "Synthetic — SSM data not received": the label the data plan gives every
// synthetic point (PROJECT_STATE §18.6), for preview's placeholder months.
const PlaceholderLegendItem = () => (
  <li className="legend-item">
    <span className="legend-placeholder" aria-hidden="true" />
    Synthetic — SSM data not received
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

// Axis titles. The Technical Adviser's rule (2 Oct 2026): every number states
// its unit and its period, and a tick reading "₱25M" or "1.2M" does neither
// on its own — so every Dashboard chart names what each axis counts. One
// helper, so the titles share a size, colour and placement. The Y title is
// centred on the axis (textAnchor middle, which Recharts 3 lets a label
// override) rather than starting at its middle and running off the top.
const AXIS_TITLE = { fontSize: 10, fontWeight: 600, fill: CHART_COLORS.axisLabel };
const yAxisTitle = (value) => ({ value, angle: -90, position: 'insideLeft', textAnchor: 'middle', ...AXIS_TITLE });
const xAxisTitle = (value) => ({ value, position: 'insideBottom', offset: 0, ...AXIS_TITLE });
// The X axis grows from Recharts' default 30px to fit its title under the
// month ticks (which sit 10px low, dy={10}).
const X_AXIS_TITLED_HEIGHT = 44;

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

// The year-over-year axis: twelve calendar slots, so the same month of two
// years sits on one x position. Every series key is `${metric}_${slot}`,
// where the slot is the latest year in the range ('cur', solid) or the year
// before it ('prev', dashed). A point's `meta_${slot}` carries the month it
// came from, its stock count day, the unusual-count reason and the
// placeholder flag, so the tooltip can say them per year.
const CALENDAR_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const YEAR_SLOTS = ['cur', 'prev'];
const PREV_YEAR_DASH = '6 4';
const yearOf = (period) => Number(String(period).slice(0, 4));
const monthOf = (period) => Number(String(period).slice(5, 7));
const slotOf = (dataKey) => String(dataKey).split('_')[1];
const metricOf = (dataKey) => String(dataKey).split('_')[0];

// Colour tells the METRIC (the same teal or navy in both years); line style
// tells the YEAR. The previous year is the reference, not the subject:
// dashed, thinner, a touch lighter. No marker on every month (Audrey,
// 2026-10-03): the smooth line carries the shape, the hovered month gets a
// dot, and the tooltip gives its exact pesos.
const PREV_YEAR_WIDTH = 1.5;
const PREV_YEAR_OPACITY = 0.7;
// The shade under each line: the line's own colour, much lighter than the
// line, fading to nothing at the floor. The previous year's is fainter
// still, so four shades on one plot don't turn to mud.
const FILL_TOP_OPACITY = { cur: 0.26, prev: 0.1 };
const FILL_BOTTOM_OPACITY = 0.02;
// The plot's floor: 90% of the lowest visible value, rounded down to ₱5M,
// never below zero. With every value between ₱10M and ₱40M a zero floor
// spent half the card on empty space and flattened a ₱10M swing to a few
// pixels. The tick labels name the floor, so nothing is hidden.
const yoyFloor = (min) => Math.max(0, Math.floor((min * 0.9) / 5e6) * 5e6);
// Explicit ticks, because Recharts' own "nice" ticks round the floor back
// down to zero: with a ₱10M step, a ₱5M floor becomes ₱0 again. Steps of
// ₱5M, or ₱10M once that would be more than eight ticks. Recomputed from
// whatever is visible, so the scale follows the metric control.
const pesoTicks = (values) => {
  const present = values.filter((v) => v != null);
  if (!present.length) return null;
  const lo = yoyFloor(Math.min(...present));
  const hi = Math.ceil(Math.max(...present) / 5e6) * 5e6;
  const step = (hi - lo) / 5e6 > 8 ? 1e7 : 5e6;
  const ticks = [];
  for (let v = lo; v <= hi + 1; v += step) ticks.push(v);
  if (ticks[ticks.length - 1] < hi) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
};

// Month ticks shrink on a narrow card so twelve of them still fit.
const YOY_WIDE_PX = 700;
const useElementWidth = (ref) => {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => setWidth(el.getBoundingClientRect().width);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
};
// The tooltip gives the exact peso amount (the axis and end labels stay
// compact): ₱19,217,832 — whole pesos, the source rows carry centavos the
// reader never acts on.
const formatExactPesos = (value) => `₱${Math.round(value).toLocaleString('en-PH')}`;

// Which metrics the chart shows. The table always holds both.
const METRIC_VIEWS = [['both', 'Both'], ['sales', 'Sales'], ['inventory', 'Inventory']];
const METRIC_PREFIX = { sales: 'sales', inventory: 'stock' };
// Purchases get their own view (sales beside what was bought) once there is
// a purchases figure to draw, recorded or estimated.
const PURCHASES_VIEW = ['purchases', 'Purchases'];
const PURCHASES_METRICS = ['sales', 'received', 'recest'];
// An ESTIMATE is drawn apart from a recorded figure (3 Oct 2026 analysis):
// dotted and lighter, with its own legend entry, in the chart only — never
// in a KPI. GET /dashboard's received_estimated is purchases worked out from
// stock counts and sales (closing − opening stock + sales), not a purchase
// record. A negative estimate is shown as 0 and the tooltip flags it.
const ESTIMATED_LABEL = 'Purchases (estimated from stock counts and sales)';
const ESTIMATED_DASH = '2 5';
const ESTIMATED_OPACITY = 0.75;
// Mart estimates for a month with no real figure (GET /dashboard
// *_estimated, DEC-31): 'filled' rows are worked out from SSM's own data
// (real mode); 'generated' rows are synthetic and come in preview only.
// Drawn like the purchases estimate, in the chart and its table only.
const ESTIMATE_KIND_TEXT = {
  filled: 'estimated (filled gap)',
  generated: 'Synthetic — SSM data not received',
};
const estimateLabel = (base, kinds) => {
  const set = [...new Set(kinds.filter(Boolean))];
  if (set.length === 1 && set[0] === 'generated') return `${base} — ${ESTIMATE_KIND_TEXT.generated}`;
  if (set.length === 1 && set[0] === 'filled') return `${base} — ${ESTIMATE_KIND_TEXT.filled}`;
  return `${base} — estimated (filled gap or synthetic)`;
};
// Returns get a view of their own: they run at a few percent of sales, so on
// the sales axis they would lie flat along zero.
const RETURNS_VIEW = ['returns', 'Returns'];
const RETURNS_METRICS = ['returns', 'retest'];
// Which views draw each estimate: a sales or stock estimate rides with its
// own metric (and with Both); returns stay in their own view.
const ESTIMATE_VIEWS = { salesest: ['both', 'sales'], stockest: ['both', 'inventory'] };

// "Nov 2025", and the metric's own name without its basis ("Sales"): the
// legend already says the price basis, the tooltip says which month.
const plainPeriod = (period) => formatAxisPeriod(period).replace(' · ', ' ');
const shortMetric = (name) => String(name).split(' · ')[0].split(' (')[0];

const SalesStockTooltip = ({ active, payload, label, baseLabels = {} }) => {
  if (!active || !payload || !payload.length) return null;
  // A month one year has and the other hasn't shows only the year that
  // has it, so no row is ever a mislabelled blank.
  const rows = payload.filter((p) => p.type !== 'none' && p.value != null);
  if (!rows.length) return null;
  const row = rows[0].payload || {};
  const metas = YEAR_SLOTS.map((slot) => row[`meta_${slot}`]).filter(Boolean);
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>
        {row.period ? plainPeriod(row.period) : label}
        {row.meta_prev?.period && (
          <span className="chart-tooltip-sub"> vs {plainPeriod(row.meta_prev.period)}</span>
        )}
      </p>
      {/* Swatch + ink text: the mark beside the words carries identity —
          the metric's colour, drawn solid or dashed for the year, exactly
          as the line is — and the text never wears the series colour. */}
      {rows.map((p) => {
        const slot = slotOf(p.dataKey);
        const meta = row[`meta_${slot}`];
        return (
          <p key={p.dataKey} className="chart-tooltip-row">
            <span
              className={`chart-tooltip-swatch-line${slot === 'prev' ? ' is-dashed' : ''}`}
              style={{ borderTopColor: p.color }}
              aria-hidden="true"
            />
            {/* The metric, then the month this value is from: the dashed
                line's month is the comparison period's, not the range's. */}
            {shortMetric(baseLabels[p.dataKey] ?? p.name)}{meta?.period ? `, ${plainPeriod(meta.period)}` : ''}:{' '}
            <strong>{formatExactPesos(p.value)}</strong>
            {/* The month on this point is the one the count is filed under;
                the day it was actually counted can be a week later. */}
            {metricOf(p.dataKey) === 'stock' && meta?.stockCountDay && ` · counted ${meta.stockCountDay}`}
            {metricOf(p.dataKey) === 'recest' && ' · estimated'}
            {['salesest', 'stockest', 'retest'].includes(metricOf(p.dataKey)) && meta?.kinds?.[metricOf(p.dataKey)]
              && ` · ${ESTIMATE_KIND_TEXT[meta.kinds[metricOf(p.dataKey)]] || 'estimated'}`}
            {metricOf(p.dataKey) === 'recest' && meta?.estWasNegative && ' · negative estimate, shown as 0'}
            {metricOf(p.dataKey) === 'recest' && meta?.estNegativeSkus > 0
              && ` · ${meta.estNegativeSkus.toLocaleString()} products had a negative estimate`}
          </p>
        );
      })}
      {/* A stock count the team reviewed and judged unusual (GET
          /dashboard's stock_on_hand_flags) — the reason sits with the point,
          named by its year since two years share the slot. */}
      {rows.some((p) => metricOf(p.dataKey) === 'stock') && metas.filter((m) => m.stockUnusual).map((m) => (
        <p key={m.period} className="chart-tooltip-placeholder chart-tooltip-note">
          Unusual count, {formatAxisPeriod(m.period)}: {m.stockUnusual}
        </p>
      ))}
      {metas.some((m) => m.placeholder) && (
        <p className="chart-tooltip-placeholder">Synthetic — SSM data not received</p>
      )}
    </div>
  );
};

// The one marker an inventory line keeps: a count GET /dashboard flags as
// unusual (stock_on_hand_flags, from the team's reviewed list in backend/
// data_notes.py) gets a muted slate dot, so the point stays on its line —
// it was counted — and reads apart from the ordinary months. The tooltip
// gives the reason. Every other month has no dot.
const unusualStockDot = (slot) => {
  const UnusualDot = ({ cx, cy, payload, index }) => {
    if (!payload?.[`meta_${slot}`]?.stockUnusual || cx == null || cy == null) return null;
    return (
      <circle
        key={`unusual-${slot}-${index}`}
        cx={cx}
        cy={cy}
        r={4.5}
        fill="var(--color-text-muted, #556070)"
        stroke="var(--color-surface, #fff)"
        strokeWidth={1.5}
      />
    );
  };
  return UnusualDot;
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
// "At last purchase price", not "at cost" (3 Oct 2026 analysis): the SOH
// file's extended cost prices each product at what it was last bought for,
// which is above SSM's true cost, so "at cost" claimed more than it knows.
// The stock line is the PESO value of the stock count at cost (Inventory_
// Fact.valuation, the SOH file's own extended cost), not a quantity on hand.
// It was labelled "Stock on hand", which a reader takes for pieces or cases;
// renamed 2026-10-02 so the legend, tooltip and table say what is plotted.
const INVENTORY_LABEL = 'Inventory value (at last purchase price)';

// Sales vs Inventory Value — the dashboard's hero chart, as a year-over-year
// overlay (2026-10-03). `data` is [{ period, sales, stockOnHand, received }],
// all in pesos (GET /dashboard sums stock_on_hand and received as peso
// figures specifically so they plot on one axis — see backend/routers/
// dashboard.py's kpis.soh_value and sales_vs_stock[].received docstrings).
// It reads the same rows the date filter fetched; the two years it draws
// are the latest in that range and the one before it.
//
// Since 2026-10-09 the x axis is the selected range's months in order and
// the dashed line is the comparison period from the date bar's "Compare
// with" (same months last year by default), so the chart follows both
// filters with no calendar gaps. Before that (described below) the axis
// was a fixed Jan–Dec calendar. Colour tells the metric — sales
// teal, inventory navy, purchases received violet — the same colour in
// both years; line style tells the year: the latest year in the range
// solid, the year before it dashed. So "how does this month compare with
// the same month last year" is read straight off the chart — the
// Technical Adviser's "story in the changes" — instead of walked along a
// timeline. Only those two years are drawn; the subtitle names any earlier
// year the range holds. A control shows both metrics, sales only or
// inventory only; the axis follows what is visible.
//
// The lines are smooth, with no dot per month and a light shade of their
// own colour beneath them. The Past / Present / Future sections tried on
// 2026-10-03 were taken out again the same day (commit 3b687b3 has them).
//
// `insight` is GET /dashboard's sales_vs_stock_insight: the one-sentence
// takeaway under the title and the peak/low sales months this chart
// labels — computed by the backend from the same rows, never typed here.
//
// `basis` is GET /dashboard's sales_vs_stock_basis ({sales, received}):
// the tax basis of the two flow lines, named in the legend and tooltip.
// Del Monte's purchases were plotted VAT-inclusive beside its ex-VAT sales
// until 2026-10-01 (₱23.0M vs ₱22.1M in Dec 2025, ₱20.5M ex-VAT); the
// backend now puts both on one basis per principal, and the label says
// which. Null under All principals, where `note` (vat_note) explains the mix.
// A point's `stockUnusual` is the reason a stock count was flagged (GET
// /dashboard's stock_on_hand_flags): marked, never dropped.
export const SalesVsStockWidget = ({
  data = [], emptyReason, placeholder = null, insight = null, note = null, basis = null,
  compare = null, compareNote = null, rangeLabel = null,
}) => {
  const hasData = data.length > 0;
  // "Sales · ex-VAT" — a middle dot, not brackets: a Del Monte range holding
  // Aug 2023 brings its own "(except Aug 2023, recorded with tax)".
  const withBasis = (label, key) => (basis?.[key] ? `${label} · ${basis[key]}` : label);
  const salesLabel = withBasis('Monthly sales', 'sales');
  const receivedLabel = withBasis(RECEIVED_LABEL, 'received');
  const [view, setView] = useState('chart');
  const [metricView, setMetricView] = useState('both');
  // Hovering a legend entry or a line pulls those series forward and drops
  // the others back: a metric entry lifts both of its years, a year entry
  // lifts both metrics of that year, a line lifts itself. With up to six
  // peso lines on one axis, this is how a reader isolates what they trace.
  const [focus, setFocus] = useState(null);
  const inFocus = (key) => {
    if (!focus) return true;
    if (focus.type === 'key') return focus.value === key;
    if (focus.type === 'metric') return metricOf(key) === focus.value;
    return slotOf(key) === focus.value;
  };
  const dimmable = (key) => (inFocus(key) ? 1 : 0.25);
  const focusHandlers = (type, value) => ({
    onMouseEnter: () => setFocus({ type, value }),
    onMouseLeave: () => setFocus(null),
  });
  // A legend entry with no drawn series is a phantom. Live,
  // Purchase_Fact_Real holds Del Monte rows only, so `received` is null
  // for every Unilever period: the line and its legend entry appear
  // together, only when at least one real point exists.
  const hasReceived = data.some((pt) => pt.received != null);
  // Unilever has no purchase records, only this estimate (see ESTIMATED_LABEL).
  const hasEstimated = data.some((pt) => pt.receivedEstimated != null);
  // Mart estimates and returns (GET /dashboard, data marts): each series and
  // its legend entry appear only when at least one point carries it.
  const hasSalesEst = data.some((pt) => pt.salesEstimated != null);
  const hasStockEst = data.some((pt) => pt.stockEstimated != null);
  const hasReturns = data.some((pt) => pt.returns != null);
  const hasReturnsEst = data.some((pt) => pt.returnsEstimated != null);
  const metricViews = [
    ...METRIC_VIEWS,
    ...(hasReceived || hasEstimated ? [PURCHASES_VIEW] : []),
    ...(hasReturns || hasReturnsEst ? [RETURNS_VIEW] : []),
  ];
  const kindsOf = (key) => data.map((pt) => pt[key]);
  const salesEstLabel = estimateLabel('Sales', kindsOf('salesEstimatedKind'));
  const stockEstLabel = estimateLabel('Inventory value', kindsOf('stockEstimatedKind'));
  const returnsLabel = withBasis('Returns', 'returns');
  const returnsEstLabel = estimateLabel('Returns', kindsOf('returnsEstimatedKind'));
  const widgetRef = useRef(null);
  const wide = useElementWidth(widgetRef) >= YOY_WIDE_PX;

  // One row per month of the SELECTED RANGE, in order, on one continuous
  // axis (2026-10-09): the chart moves with the date filter and has no
  // calendar gaps. The comparison period (the date bar's "Compare with",
  // GET /dashboard for that period) rides on the same rows, month for
  // month, `compare.shift` months earlier. Solid = the range, dashed = the
  // comparison. A month with no figure is null, so its line breaks there.
  const { rows, slots, slotLabels } = useMemo(() => {
    const sorted = [...data].sort((a, b) => (a.period < b.period ? -1 : a.period > b.period ? 1 : 0));
    const prevByPeriod = new Map((compare?.points || []).map((pt) => [pt.period, pt]));
    const shiftBack = (period) => {
      const n = yearOf(period) * 12 + monthOf(period) - 1 - (compare?.shift || 0);
      return `${Math.floor(n / 12)}-${String((n % 12) + 1).padStart(2, '0')}`;
    };
    const fill = (row, slot, pt) => {
      row[`sales_${slot}`] = pt?.sales ?? null;
      row[`stock_${slot}`] = pt?.stockOnHand ?? null;
      row[`received_${slot}`] = pt?.received ?? null;
      row[`recest_${slot}`] = pt?.receivedEstimated != null ? Math.max(0, pt.receivedEstimated) : null;
      row[`salesest_${slot}`] = pt?.salesEstimated ?? null;
      row[`stockest_${slot}`] = pt?.stockEstimated ?? null;
      row[`returns_${slot}`] = pt?.returns ?? null;
      row[`retest_${slot}`] = pt?.returnsEstimated ?? null;
      row[`meta_${slot}`] = pt
        ? {
            period: pt.period,
            stockCountDay: pt.stockCountDay ?? null,
            stockUnusual: pt.stockUnusual ?? null,
            placeholder: isPlaceholderPeriod(pt.period, placeholder),
            estWasNegative: pt.receivedEstimated != null && pt.receivedEstimated < 0,
            estNegativeSkus: pt.receivedEstimatedNegativeSkus ?? null,
            kinds: {
              salesest: pt.salesEstimatedKind ?? null,
              stockest: pt.stockEstimatedKind ?? null,
              retest: pt.returnsEstimatedKind ?? null,
            },
          }
        : null;
    };
    const built = sorted.map((pt, i) => {
      const row = { x: i, period: pt.period, month: formatAxisPeriod(pt.period) };
      fill(row, 'cur', pt);
      fill(row, 'prev', compare ? prevByPeriod.get(shiftBack(pt.period)) ?? null : null);
      return row;
    });
    const prevDrawn = compare != null && built.some((r) => ['sales', 'stock', 'received', 'returns']
      .some((m) => r[`${m}_prev`] != null));
    const first = sorted[0]?.period;
    const last = sorted[sorted.length - 1]?.period;
    const plain = (period) => formatAxisPeriod(period).replace(' · ', ' ');
    return {
      rows: built,
      slots: prevDrawn ? ['cur', 'prev'] : ['cur'],
      slotLabels: { cur: rangeLabel || (first && last ? `${plain(first)} – ${plain(last)}` : ''), prev: compare?.label ?? null },
    };
  }, [data, placeholder, compare, rangeLabel]);
  // Month ticks: every month up to about a year, every other one beyond
  // (sooner on a narrow card); the year is written on the first tick and on
  // each January, so a range that crosses a year says where.
  const tickStep = rows.length > (wide ? 14 : 7) ? 2 : 1;
  const xTicks = rows.map((r) => r.x).filter((x) => x % tickStep === 0);
  const xTickLabel = (x) => {
    const r = rows[x];
    if (!r) return '';
    const [y, m] = r.period.split('-');
    const name = CALENDAR_MONTHS[Number(m) - 1];
    return x === 0 || m === '01' ? `${name} ${y}` : name;
  };

  // Every series the data could draw, then the ones the control shows.
  // Legend and lines share these descriptions, so the pairing the legend
  // promises (colour = metric, dash = year) is the one that is drawn.
  const series = useMemo(() => [
    ...slots.map((slot) => ({ key: `sales_${slot}`, slot, metric: 'sales', name: `${salesLabel} · ${slotLabels[slot]}`, base: salesLabel, color: CHART_COLORS.heroSales })),
    ...slots.map((slot) => ({ key: `stock_${slot}`, slot, metric: 'stock', name: `${INVENTORY_LABEL} · ${slotLabels[slot]}`, base: INVENTORY_LABEL, color: CHART_COLORS.heroInventory })),
    ...(hasReceived
      ? slots.map((slot) => ({ key: `received_${slot}`, slot, metric: 'received', name: `${receivedLabel} · ${slotLabels[slot]}`, base: receivedLabel, color: COLORS.forecast }))
      : []),
    ...(hasEstimated
      ? slots.map((slot) => ({ key: `recest_${slot}`, slot, metric: 'recest', estimated: true, name: `${ESTIMATED_LABEL} · ${slotLabels[slot]}`, base: ESTIMATED_LABEL, color: COLORS.forecast }))
      : []),
    ...(hasSalesEst
      ? slots.map((slot) => ({ key: `salesest_${slot}`, slot, metric: 'salesest', estimated: true, name: `${salesEstLabel} · ${slotLabels[slot]}`, base: salesEstLabel, color: CHART_COLORS.heroSales }))
      : []),
    ...(hasStockEst
      ? slots.map((slot) => ({ key: `stockest_${slot}`, slot, metric: 'stockest', estimated: true, name: `${stockEstLabel} · ${slotLabels[slot]}`, base: stockEstLabel, color: CHART_COLORS.heroInventory }))
      : []),
    ...(hasReturns
      ? slots.map((slot) => ({ key: `returns_${slot}`, slot, metric: 'returns', name: `${returnsLabel} · ${slotLabels[slot]}`, base: returnsLabel, color: CHART_COLORS.heroReturns }))
      : []),
    ...(hasReturnsEst
      ? slots.map((slot) => ({ key: `retest_${slot}`, slot, metric: 'retest', estimated: true, name: `${returnsEstLabel} · ${slotLabels[slot]}`, base: returnsEstLabel, color: CHART_COLORS.heroReturns }))
      : []),
  ], [slots, slotLabels, salesLabel, receivedLabel, hasReceived, hasEstimated, hasSalesEst, hasStockEst, hasReturns,
    hasReturnsEst, salesEstLabel, stockEstLabel, returnsLabel, returnsEstLabel]);
  // Purchases received ride with "Both": they are neither metric the
  // control names, and a sales-only or inventory-only view is for a
  // single comparison.
  const { visible, visibleKeys } = useMemo(() => {
    // "Both" keeps to recorded figures plus the mart's sales and stock
    // estimates for months with no record; the purchases estimate is drawn
    // only in the Purchases view, beside sales, and returns in their own.
    const shown = series.filter((sr) => {
      if (ESTIMATE_VIEWS[sr.metric]) return ESTIMATE_VIEWS[sr.metric].includes(metricView);
      if (metricView === 'returns') return RETURNS_METRICS.includes(sr.metric);
      if (RETURNS_METRICS.includes(sr.metric)) return false;
      return metricView === 'both' ? !sr.estimated
        : metricView === 'purchases' ? PURCHASES_METRICS.includes(sr.metric)
          : sr.metric === METRIC_PREFIX[metricView];
    });
    return { visible: shown, visibleKeys: new Set(shown.map((sr) => sr.key)) };
  }, [series, metricView]);

  // The unusual-count key only while an inventory line is drawn to carry it.
  const hasUnusual = (visibleKeys.has('stock_cur') || visibleKeys.has('stock_prev'))
    && rows.some((r) => slots.some((s) => r[`meta_${s}`]?.stockUnusual && r[`stock_${s}`] != null));
  const hasPlaceholder = rows.some((r) => slots.some((s) => r[`meta_${s}`]?.placeholder));
  // The axis follows what is visible: sales only shouldn't be scaled to
  // an inventory peak that isn't drawn.
  const yTicks = useMemo(
    () => pesoTicks(rows.flatMap((r) => visible.map((sr) => r[sr.key]))),
    [rows, visible],
  );
  // Why no dashed line is drawn when a comparison was asked for (the data
  // starts too late, it is still loading, or that period has no figures).
  const compareLine = compareNote
    || (compare && slots.length === 1 ? `No figures on record in ${compare.label} to draw as the comparison.` : null);
  const baseLabels = useMemo(() => Object.fromEntries(series.map((sr) => [sr.key, sr.base])), [series]);

  // Direct labels: the current year's latest sales and inventory values at
  // their line ends, plus the backend's peak/low sales months on whichever
  // year's line holds them. Selective by design — never a number on every
  // point. End labels drop out (legend + tooltip take over) when the two
  // lines finish too close together to label without overlap, measured
  // against the chart's own value span.
  const labels = useMemo(() => {
    const lastWith = (key) => (visibleKeys.has(key) ? [...rows].reverse().find((r) => r[key] != null) ?? null : null);
    const lastSales = lastWith('sales_cur');
    const lastStock = lastWith('stock_cur');
    const values = rows.flatMap((r) => visible.map((sr) => r[sr.key])).filter((v) => v != null);
    const span = values.length ? Math.max(...values) - Math.min(...values) : 0;
    const collide = lastSales && lastStock && lastSales.month === lastStock.month && span > 0
      && Math.abs(lastSales.sales_cur - lastStock.stock_cur) / span < 0.09;
    const entries = { sales_cur: [], sales_prev: [], stock_cur: [] };
    if (lastSales && !collide) {
      entries.sales_cur.push({
        period: lastSales.month,
        text: `Sales ${formatCompactPesos(lastSales.sales_cur)}`,
        below: lastStock && lastSales.sales_cur < (lastStock.stock_cur ?? -Infinity),
      });
    }
    if (visibleKeys.has('sales_cur')) {
      for (const mark of [insight?.peak, insight?.low]) {
        if (!mark) continue;
        // The backend's peak and low are months of the selected range.
        const markRow = rows.find((r) => r.period === mark.period);
        if (!markRow) continue;
        // Skipped at the line's end, where the end label has it.
        if (lastSales && markRow.month === lastSales.month) continue;
        entries.sales_cur.push({ period: markRow.month, text: mark.label, below: mark === insight?.low });
      }
    }
    // A flagged count keeps its end label, but says it is unusual — the
    // label is where the eye lands first.
    if (lastStock && !collide) {
      entries.stock_cur.push({
        period: lastStock.month,
        text: `Inventory ${formatCompactPesos(lastStock.stock_cur)}${lastStock.meta_cur?.stockUnusual ? ' (unusual)' : ''}`,
        below: !(lastSales && lastSales.sales_cur < (lastStock.stock_cur ?? -Infinity)),
      });
    }
    const byMonth = { key: 'month' };
    return {
      sales_cur: pointLabels(rows, entries.sales_cur, byMonth),
      sales_prev: pointLabels(rows, entries.sales_prev, byMonth),
      stock_cur: pointLabels(rows, entries.stock_cur, byMonth),
    };
  }, [rows, visible, visibleKeys, insight]);

  // The table keeps the months in order, one row each, with both metrics
  // whatever the control shows — every column names its unit (₱), and the
  // stock column's count day rides with its value.
  const hasCountDays = data.some((pt) => pt.stockCountDay);
  const tableColumns = [
    { key: 'period', label: 'Month', format: (v) => formatAxisPeriod(v), align: 'left' },
    { key: 'sales', label: `${salesLabel} (₱)`, format: (v) => formatCompactPesos(v) },
    { key: 'stockOnHand', label: `${INVENTORY_LABEL} (₱)`, format: (v) => formatCompactPesos(v) },
    ...(hasCountDays
      ? [{ key: 'stockCountDay', label: 'Stock counted on', format: (v) => v, align: 'left' }]
      : []),
    ...(hasReceived ? [{ key: 'received', label: `${receivedLabel} (₱)`, format: (v) => formatCompactPesos(v) }] : []),
    ...(hasEstimated
      ? [{
          key: 'receivedEstimated',
          label: `${ESTIMATED_LABEL} (₱)`,
          format: (v) => (v < 0 ? '₱0 (negative estimate)' : formatCompactPesos(v)),
        }]
      : []),
    ...(hasSalesEst ? [{ key: 'salesEstimated', label: `${salesEstLabel} (₱)`, format: (v) => formatCompactPesos(v) }] : []),
    ...(hasStockEst ? [{ key: 'stockEstimated', label: `${stockEstLabel} (₱)`, format: (v) => formatCompactPesos(v) }] : []),
    ...(hasReturns ? [{ key: 'returns', label: `${returnsLabel} (₱)`, format: (v) => formatCompactPesos(v) }] : []),
    ...(hasReturnsEst ? [{ key: 'returnsEstimated', label: `${returnsEstLabel} (₱)`, format: (v) => formatCompactPesos(v) }] : []),
    ...(data.some((pt) => pt.stockUnusual && pt.stockOnHand != null)
      ? [{ key: 'stockUnusual', label: 'Stock note', format: (v) => `Unusual count: ${v}`, align: 'left' }]
      : []),
  ];

  const metricEntries = [
    { metric: 'sales', label: salesLabel, color: CHART_COLORS.heroSales },
    { metric: 'stock', label: INVENTORY_LABEL, color: CHART_COLORS.heroInventory },
    ...(hasReceived ? [{ metric: 'received', label: receivedLabel, color: COLORS.forecast }] : []),
    ...(hasEstimated ? [{ metric: 'recest', label: ESTIMATED_LABEL, color: COLORS.forecast, estimated: true }] : []),
    ...(hasSalesEst ? [{ metric: 'salesest', label: salesEstLabel, color: CHART_COLORS.heroSales, estimated: true }] : []),
    ...(hasStockEst ? [{ metric: 'stockest', label: stockEstLabel, color: CHART_COLORS.heroInventory, estimated: true }] : []),
    ...(hasReturns ? [{ metric: 'returns', label: returnsLabel, color: CHART_COLORS.heroReturns }] : []),
    ...(hasReturnsEst ? [{ metric: 'retest', label: returnsEstLabel, color: CHART_COLORS.heroReturns, estimated: true }] : []),
  ].filter((entry) => visible.some((sr) => sr.metric === entry.metric));

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`} ref={widgetRef}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Sales vs Inventory Value (₱)</h4>
          {/* GET /dashboard's vat_note — only under All principals, where the
              combined pesos mix Unilever's VAT-inclusive amounts with Del
              Monte's VAT-exclusive ones. */}
          {note && <p>{note}</p>}
          {/* The backend's takeaway sentence, from the same rows this
              chart plots (sales_vs_stock_insight). */}
          {insight?.text && <p className="chart-insight">{insight.text}</p>}
          {hasData && compareLine && view === 'chart' && <p className="chart-insight">{compareLine}</p>}
        </div>
        {hasData && (
          <div className="chart-header-controls">
            {view === 'chart' && (
              <div className="chart-view-toggle" role="group" aria-label="Metrics shown">
                {metricViews.map(([key, text]) => (
                  <button
                    key={key}
                    type="button"
                    className={metricView === key ? 'active' : ''}
                    aria-pressed={metricView === key}
                    onClick={() => setMetricView(key)}
                  >
                    {text}
                  </button>
                ))}
              </div>
            )}
            <ChartViewToggle view={view} onChange={setView} label="Sales vs inventory value: chart or table" />
          </div>
        )}
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No data available for this range'}</p>
      ) : view === 'table' ? (
        <ChartTable
          columns={tableColumns}
          rows={data}
          caption="Sales versus inventory value at last purchase price by month, in pesos (₱)"
        />
      ) : (
        <>
          {/* Two keys, not four: the metric's colour, then the year's line
              style. Together they name every line without listing each. */}
          <ul className="custom-legend custom-legend-top">
            {metricEntries.map((entry) => (
              <li key={entry.metric} className="legend-item" {...focusHandlers('metric', entry.metric)}>
                {entry.estimated
                  ? <span className="legend-line legend-line-dotted" style={{ borderTopColor: entry.color }} aria-hidden="true" />
                  : <span className="legend-color" style={{ backgroundColor: entry.color }} aria-hidden="true" />}
                {entry.label}
              </li>
            ))}
            {slots.length > 1 && <li className="legend-divider" aria-hidden="true" />}
            {slots.map((slot) => (
              <li key={slot} className="legend-item" {...focusHandlers('slot', slot)}>
                <span className={`legend-line legend-line-year${slot === 'prev' ? ' legend-line-dashed' : ''}`} aria-hidden="true" />
                {slotLabels[slot]}{slots.length > 1 ? (slot === 'prev' ? ' (dashed)' : ' (solid)') : ''}
              </li>
            ))}
            {hasUnusual && (
              <li className="legend-item">
                <span className="legend-unusual" aria-hidden="true" />
                Unusual stock count — hover or tap it for why
              </li>
            )}
            {hasPlaceholder && <PlaceholderLegendItem />}
          </ul>
          <div className="chart-container chart-container-yoy">
            <ResponsiveContainer width="99%" height="100%">
              <ComposedChart data={rows} margin={{ top: 20, right: 16, left: 0, bottom: 10 }}>
                <defs>
                  {visible.map((sr) => (
                    <linearGradient key={sr.key} id={`svs-fill-${sr.key}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={sr.color} stopOpacity={FILL_TOP_OPACITY[sr.slot]} />
                      <stop offset="100%" stopColor={sr.color} stopOpacity={FILL_BOTTOM_OPACITY} />
                    </linearGradient>
                  ))}
                </defs>
                {/* Horizontal gridlines only (GRID_PROPS): a value is read
                    across, a month is read down from its label. */}
                <CartesianGrid {...GRID_PROPS} />
                {/* The range's months in order, the first at the left edge. */}
                <XAxis
                  dataKey="x"
                  type="number"
                  domain={[0, Math.max(rows.length - 1, 1)]}
                  ticks={xTicks}
                  tickFormatter={xTickLabel}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: wide ? 10 : 8.5, fill: CHART_COLORS.axisLabel }}
                  dy={10}
                  interval={0}
                  height={X_AXIS_TITLED_HEIGHT}
                  label={xAxisTitle('Month')}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  width={64}
                  tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                  tickFormatter={(v) => formatCompactPesos(v)}
                  label={yAxisTitle('Pesos (₱)')}
                  domain={yTicks ? [yTicks[0], yTicks[yTicks.length - 1]] : [0, 'auto']}
                  ticks={yTicks ?? undefined}
                />
                <Tooltip content={<SalesStockTooltip baseLabels={baseLabels} />} />
                {/* Smooth (monotone: the curve passes through every month's
                    value and never overshoots it), no dot per month, a
                    light shade of the line's colour beneath it. A null
                    month breaks the line rather than bridging it
                    (connectNulls off), so a year that ends in Feb stops in
                    Feb. The hovered month gets a dot (activeDot). */}
                {visible.map((sr) => {
                  const prev = sr.slot === 'prev';
                  return (
                    <Area
                      key={sr.key}
                      type="monotone"
                      dataKey={sr.key}
                      name={sr.name}
                      stroke={sr.color}
                      strokeWidth={prev ? PREV_YEAR_WIDTH : 2.5}
                      strokeLinecap="round"
                      strokeDasharray={sr.estimated ? ESTIMATED_DASH : prev ? PREV_YEAR_DASH : undefined}
                      strokeOpacity={dimmable(sr.key) * (prev ? PREV_YEAR_OPACITY : 1) * (sr.estimated ? ESTIMATED_OPACITY : 1)}
                      fill={sr.estimated ? 'none' : `url(#svs-fill-${sr.key})`}
                      fillOpacity={dimmable(sr.key)}
                      dot={sr.metric === 'stock' ? unusualStockDot(sr.slot) : false}
                      activeDot={{ r: 5, strokeWidth: 2, stroke: 'var(--color-surface, #fff)' }}
                      label={labels[sr.key] ?? false}
                      connectNulls={false}
                      {...chartAnim()}
                    />
                  );
                })}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
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
  A: { name: 'Top sellers', role: 'The only class the app forecasts and plans reorders for.' },
  B: { name: 'Middle sellers', role: 'Watched on this dashboard only — not forecast, no reorder plan.' },
  C: { name: 'Long tail', role: 'Lowest revenue — kept on minimal monitoring.' },
};
// Del Monte is ranked by product category (it has no SKU-level sales) and
// nothing of Del Monte's is forecast or reordered, so the roles above would
// be false for it.
const DEL_MONTE_TIER_ROLE =
  'Ranked by category sell-out. Del Monte has no SKU-level sales, so no class here is forecast or reordered.';

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
const AbcTierCard = ({ facts, atRisk = null, onOpenClass = null }) => {
  const x = facts.skuPct.toFixed(0);
  const role = ABC_TIER_ROLE[facts.tier];
  const roleText = facts.units === 'categories' ? DEL_MONTE_TIER_ROLE : role?.role;
  return (
    <div className="abc-tier-card" aria-live="polite">
      <p className="abc-tier-card-name">
        <span className="legend-color" style={{ backgroundColor: abcTierColor(facts.tier) }} aria-hidden="true" />
        Class {facts.tier}{role && <span className="abc-tier-card-alias">· {role.name}</span>}
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
            {facts.amount != null ? formatCompactPesos(facts.amount) : 'Revenue not available'}
          </p>
          {/* The period the class's pesos were earned in (abc_revenue); its
              share of revenue is the figure in the ring's centre. */}
          {facts.amount != null && <p className="abc-tier-card-note">revenue{facts.month ? `, ${facts.month}` : ''}</p>}
        </div>
      </div>
      {/* The next step of the story, on the class it is about: of these
          important products, how many are below safety stock — and the
          list (Dashboard's AtRiskProductsModal). `atRisk` is the
          dashboard's safety_stock_exposure; absent for an account without
          the reorder plan, or when nothing is measurable. */}
      {facts.tier === 'A' && atRisk && (
        <button type="button" className="abc-tier-card-link abc-tier-card-atrisk" onClick={atRisk.onOpen}>
          {atRisk.below.toLocaleString()} of the {atRisk.measurable.toLocaleString()} with a stock count are below
          safety stock — <span className="abc-tier-card-nowrap">see which <ArrowRight size={12} aria-hidden="true" /></span>
        </button>
      )}
      {/* "Which ones?" — the products behind this class's count, one click
          away. When the ring ranks the selected range, the list opens on the
          dashboard from that same ranking (ClassProductsModal), so its count
          is this count. A payload ranked on one month keeps the ABC page
          link, which ranks one month too. */}
      {facts.rangeBased && onOpenClass ? (
        <button type="button" className="abc-tier-card-link" onClick={() => onOpenClass(facts.tier)}>
          See the {facts.count.toLocaleString()} Class {facts.tier} {facts.units} <ArrowRight size={12} aria-hidden="true" />
        </button>
      ) : (
        <Link to={`/abc?class=${facts.tier}`} className="abc-tier-card-link">
          See the {facts.count.toLocaleString()} Class {facts.tier} {facts.units} <ArrowRight size={12} aria-hidden="true" />
        </Link>
      )}
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
    : [facts.amount != null ? formatCompactPesos(facts.amount) : null, `${facts.revenuePct.toFixed(0)}% of ${facts.month ? `${facts.month} ` : ''}revenue`]
      .filter(Boolean).join(' · ');

  return createPortal(
    <div
      ref={tipRef}
      className="abc-hover-tip"
      role="tooltip"
      style={pos ? { left: pos.left, top: pos.top } : { left: 0, top: 0, visibility: 'hidden' }}
    >
      <span className="abc-hover-tip-title">Class {facts.tier}</span>
      <span>{facts.count.toLocaleString()} {facts.units} · {facts.skuPct.toFixed(0)}% of {facts.units}</span>
      <span>{revenueLine}</span>
    </div>,
    document.body,
  );
};

// ABC classification — `data` is [{ tier: 'A'|'B'|'C', count, sharePct,
// revenue }] (revenue: the class's own pesos, GET /dashboard's
// abc_mix[].revenue), `revenue` is GET /dashboard's abc_revenue {period,
// total, ranked_total, blocked_reason}.
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
export const ABCDonutWidget = ({ data = [], revenue, rules, emptyReason, note, coverage = null, units = 'SKUs', atRisk = null, onOpenClass = null }) => {
  const [selectedTier, setSelectedTier] = useState('A');
  const [hover, setHover] = useState(null);
  const ringRef = useRef(null);

  const hasData = data.length > 0;
  const total = data.reduce((sum, d) => sum + d.count, 0);
  const skuSharePct = (d) => (total > 0 ? (d.count / total) * 100 : 0);

  // The revenue the ring's shares are shares OF: the ranked products' own
  // (abc_revenue.ranked_total), not the month's net sales (`total`), which
  // also carry the net returns of the products the ABC run left unranked.
  // Shares x net sales put Class A at ₱22.3M when its SKUs sold ₱22,443,150
  // (Unilever 2026-02). Each class's exact revenue (abc_mix[].revenue) is
  // used first; the share x ranked total is only its fallback.
  const rankedTotal = revenue?.ranked_total != null && Number.isFinite(Number(revenue.ranked_total))
    ? Number(revenue.ranked_total)
    : null;
  const shareSum = data.reduce((sum, d) => sum + Number(d.sharePct), 0);
  const sharesAddUp = Number.isFinite(shareSum) && Math.abs(shareSum - 100) <= ABC_SHARE_SUM_TOLERANCE;
  // GET /dashboard withholds revenue shares a run can't support (two
  // principals' shares are fractions of two different totals). The ring is
  // then sized by counts and the revenue bar is left out, not drawn from
  // null.
  const sharePairs = [
    ...(sharesAddUp ? [{ key: 'sharePct', label: 'Share of revenue (%)', value: (d) => d.sharePct }] : []),
    { key: 'skuPct', label: `Share of ${units} (%)`, value: skuSharePct },
  ];
  // The ring ranks the selected range since 2026-10-04 (abc_revenue.label,
  // e.g. "Mar 2025 – Feb 2026"); a payload without it still names its month.
  const rankedMonth = revenue?.label || (revenue?.period ? formatMonth(revenue.period) : null);
  const factsFor = (d) => ({
    tier: d.tier,
    count: d.count,
    units,
    month: rankedMonth,
    rangeBased: Boolean(revenue?.label),
    skuPct: skuSharePct(d),
    revenuePct: sharesAddUp ? d.sharePct : null,
    amount: !sharesAddUp ? null
      : d.revenue != null ? Number(d.revenue)
        : rankedTotal != null ? (rankedTotal * d.sharePct) / 100
          : null,
  });

  const selected = data.find((d) => d.tier === selectedTier) || data.find((d) => d.tier === 'A') || data[0];
  const hovered = hover ? data.find((d) => d.tier === hover.tier) : null;
  const segments = abcSegments(sharesAddUp ? data : data.map((d) => ({ ...d, sharePct: skuSharePct(d) })));
  const unitsTitle = units.charAt(0).toUpperCase() + units.slice(1);
  const selectedFacts = selected ? factsFor(selected) : null;
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
          <h4>
            ABC classification
            {/* The cut-offs are GET /dashboard's abc_rules (the ABC run's own
                constants), never restated here. How a class is decided sits
                behind the "?" (UI pass, 2026-10-08); the line below keeps the
                definition of an important product and the ranking's period
                (3 Oct 2026 analysis). */}
            {rules && (
              <InfoTip label="How classes are decided">
                {`${unitsTitle} are ranked by revenue${rankedMonth ? ` over ${rankedMonth}` : ''}`
                  + `${revenue?.label || !rankedMonth ? '' : ' (a single month)'}. Class A is the top sellers that `
                  + `together make the first ${Math.round(rules.tier_a_cutoff * 100)}% of revenue, B the next `
                  + `${Math.round((rules.tier_b_cutoff - rules.tier_a_cutoff) * 100)}%, C the last `
                  + `${Math.round((1 - rules.tier_b_cutoff) * 100)}%.`}
                {/* With only a handful of categories a tier can't land on its
                    cut-off (Del Monte 2025-12: A 71%, B 18%, C 11%). */}
                {units === 'categories' && ' With only a few categories, a class cannot land exactly on its cut-off.'}
              </InfoTip>
            )}
          </h4>
          <p>
            {rules
              ? `Class A = the top sellers that together make ${Math.round(rules.tier_a_cutoff * 100)}% of revenue`
                + `${rankedMonth ? `, ${rankedMonth}` : ''}. Click a class for details.`
              : `${unitsTitle} are ranked by revenue${rankedMonth ? `, ${rankedMonth}` : ''}. Click a class for details.`}
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
                aria-label={sharesAddUp ? 'Share of revenue by class' : `Share of ${units} by class`}
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
                    aria-label={`Class ${s.tier}`}
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
                      Class {selectedFacts.tier}
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
                      aria-label={`Class ${d.tier}${ABC_TIER_ROLE[d.tier] ? `, ${ABC_TIER_ROLE[d.tier].name}` : ''}`}
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
            <AbcTierCard facts={factsFor(selected)} atRisk={atRisk} onOpenClass={onOpenClass} />
          </div>
          <div
            className="abc-share-pair"
            role="img"
            aria-label={sharesAddUp ? `Share of revenue versus share of ${units}, by class` : `Share of ${units}, by class`}
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
                        title={`Class ${d.tier}: ${v.toFixed(0)}% ${pair.key === 'skuPct' ? `of ${units} (${d.count} ${units})` : `of ${rankedMonth ? `${rankedMonth} ` : ''}revenue`}`}
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

// One tier's exact counts, for the detail line under the bars. Pending
// reorder is null when the account can't see LP figures (no lp.view).
const tierStockDetail = (row) => {
  const pending = row.pendingReorderCount ?? null;
  const noData = row.noData || 0;
  // "products": the unit every count here is in.
  return `Class ${row.tier} products — active: ${(row.inStock || 0).toLocaleString()}, `
    + `dead stock (Inactive): ${(row.deadStock || 0).toLocaleString()}`
    + (pending != null ? `, pending reorder: ${pending.toLocaleString()}` : '')
    + (noData ? `, no inventory record: ${noData.toLocaleString()}` : '');
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
// `countDay` ('6 Apr 2026') is the day that snapshot was counted (GET
// /dashboard's tier_stock_count_date); `period` the month it is filed under,
// the fallback. `cycleLabel` ('Mar 2026') names the LP plan the pending
// counts belong to.
export const CategoryStockBarWidget = ({
  data = [], emptyReason, note, period = null, countDay = null, cycleLabel = null, coverage = null,
}) => {
  const countPhrase = countDay ? `the ${countDay} stock count` : period ? `the ${formatMonth(period)} stock count` : 'the latest stock count';
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
  // The tier whose counts the detail line under the bars shows — set by
  // hover, keyboard focus or a tap (2026-09-30: was a native title tooltip
  // that floated over the bars below it).
  const [activeTier, setActiveTier] = useState(null);
  const activeRow = data.find((row) => row.tier === activeTier) || null;

  return (
    <div className={`chart-widget tier-stock-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>
            Active / dead stock by ABC class <span className="chart-unit">products</span>
            <InfoTip label="What this measures">
              The warehouse&apos;s own Active / Inactive flag on each product in {countPhrase} — not whether its
              stock covers the plan&apos;s target (that is the ABC page&apos;s &ldquo;Cover vs target stock&rdquo;).
            </InfoTip>
          </h4>
          <p>Each class&apos;s products by warehouse status, {countPhrase}.</p>
          {coverage && <p className="chart-placeholder-note">{coverage}</p>}
          {note && <p className="chart-placeholder-note">{note}</p>}
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No stock status data available'}</p>
      ) : (
        <div className="chart-widget-body tier-stock-body">
          {/* When no tier has a single Inactive product, the bars alone
              just read "everything is green" — say the finding outright.
              The month is GET /dashboard's tier_stock_period (the snapshot
              the flags were read at), never typed here. */}
          {!hasDead && flaggedTotal > 0 && (
            <p className="tier-stock-note">
              <CheckCircle2 size={15} aria-hidden="true" />
              <span>
                No dead stock flagged in {countPhrase} — every one of the{' '}
                {flaggedTotal.toLocaleString()} classified products with a stock record is marked Active.
              </span>
            </p>
          )}
          {/* The bars' scale, in place of an axis title: each one is a whole
              class, so lengths are shares of that class, not counts. */}
          <p className="bar-scale-note">Each bar = 100% of the class&apos;s products</p>
          <div
            className={`tier-stock-bars${activeRow ? ' has-active' : ''}`}
            onMouseLeave={() => setActiveTier(null)}
          >
            {data.map((row, index) => {
              const inStock = row.inStock || 0;
              const deadStock = row.deadStock || 0;
              const noData = row.noData || 0;
              const total = inStock + deadStock + noData;
              // Floor at a visible width for any segment that's genuinely
              // non-zero — a real 2-unit dead-stock count on an 800-unit
              // tier is <1% and renders as a literal 0px sliver otherwise,
              // indistinguishable from "actually zero." A truly-zero count
              // stays at 0% — this never invents a value, it only keeps a
              // real one from being visually erased. Exact figures are
              // still in the detail line under the bars regardless.
              const MIN_VISIBLE_PCT = 1.5;
              const pct = (v) => {
                if (total <= 0 || v <= 0) return 0;
                return Math.max((v / total) * 100, MIN_VISIBLE_PCT);
              };
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
              // Focusable so keyboard users reach the same detail line;
              // a tap sets it too (touch has no hover), and it clears when
              // focus or the pointer leaves the bars.
              return (
                <div
                  className={`tier-stock-row${row.tier === activeTier ? ' is-active' : ''}`}
                  key={row.tier}
                  tabIndex={0}
                  aria-label={tierStockDetail(row)}
                  onMouseEnter={() => setActiveTier(row.tier)}
                  onFocus={() => setActiveTier(row.tier)}
                  onBlur={() => setActiveTier(null)}
                  onClick={() => setActiveTier(row.tier)}
                >
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
          {/* The hovered / focused / tapped tier's exact counts, under the
              bars instead of over them. The hint holds the line's height so
              the legend doesn't jump when a tier is picked. */}
          <p className={`tier-stock-detail${activeRow ? '' : ' is-hint'}`} aria-live="polite">
            {activeRow ? tierStockDetail(activeRow) : 'Hover or tap a bar for its counts.'}
          </p>
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
              Pending reorder recommendations in the {cycleLabel ? `${cycleLabel} plan` : 'LP\'s current plan'}, in SKUs:{' '}
              {data.map((row) => `${row.tier} ${(row.pendingReorderCount || 0).toLocaleString()}`).join(' · ')}.
              {' '}The LP plans Class A
              {/* Only true while an older run's rows linger in the cycle —
                  the 2026-09-30 run retired them, leaving B and C at 0. */}
              {data.some((row) => row.tier !== 'A' && (row.pendingReorderCount || 0) > 0)
                ? '; rows now in B or C come from a cycle solved against an earlier ABC run.'
                : '.'}
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
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>{formatAxisPeriod(row.period ?? label)}</p>
      {row.actual != null && (
        <p className="chart-tooltip-row">
          <span className="chart-tooltip-swatch" style={{ backgroundColor: CHART_COLORS.salesSeries }} aria-hidden="true" />
          Actual demand: <strong>{Math.round(row.actual).toLocaleString()} pieces</strong>
        </p>
      )}
      {row.forecast != null && (
        <p className="chart-tooltip-row">
          <span className="chart-tooltip-swatch" style={{ backgroundColor: COLORS.forecast }} aria-hidden="true" />
          Forecast: <strong>{Math.round(row.forecast).toLocaleString()} pieces</strong>
        </p>
      )}
      {row.confidenceBase != null && row.confidenceBand != null && row.confidenceBand > 0 && (
        <>
          <p className="chart-tooltip-row">
            <span className="chart-tooltip-swatch" style={{ backgroundColor: COLORS.forecastBg }} aria-hidden="true" />
            About 90% likely: <strong>
              {Math.round(row.confidenceBase).toLocaleString()} – {Math.round(row.confidenceBase + row.confidenceBand).toLocaleString()} pieces
            </strong>
          </p>
          <p className="chart-tooltip-placeholder chart-tooltip-note">
            Assumes each SKU&apos;s forecast misses independently; a shared seasonal swing would widen it.
          </p>
        </>
      )}
    </div>
  );
};

// 236k / 1.2M / 940 — the same compaction the pieces axis uses.
// millionDigits: the axis passes 2 so a 1,350k tick reads 1.35M, not a
// rounded 1.4M that sits beside a gridline it doesn't match; trailing
// zeros are dropped (1.80M -> 1.8M).
const formatCompactQty = (value, millionDigits = 1) => {
  const n = Math.abs(value);
  // 999,600 rounds to "1000k" in thousands, so it is shown as 1M instead.
  if (Math.round(n / 1_000) >= 1_000) return `${parseFloat((value / 1_000_000).toFixed(millionDigits))}M`;
  if (n >= 1_000) return `${Math.round(value / 1_000)}k`;
  return `${Math.round(value)}`;
};

// Past / Present / Future on the forecast chart (Audrey, 2026-10-03). The
// sections follow the DATA's clock, not the calendar: the present is the
// latest month with actual demand, the past every month before it, the
// future the forecast months after it. (By today's date the whole chart
// would be "past" whenever the data lags, and the forecast — the reason
// for the card — would sit under the wrong name.) A boundary falls halfway
// between two months.
// Softer bands (UI pass): the past barely tinted, the present a faint
// coral, the future the forecast's lavender — read as regions, not blocks.
const FORECAST_SECTION_STYLE = {
  past: { label: 'Past', fill: CHART_COLORS.stockSeries, fillOpacity: 0.025 },
  present: { label: 'Present', narrowLabel: 'Now', fill: 'var(--color-brand-primary, #c53030)', fillOpacity: 0.05 },
  future: { label: 'Future', fill: COLORS.forecast, fillOpacity: 0.06 },
};
// Every month is labelled while a month name fits its slot; only below this
// width per month (a phone) are labels thinned, to every 2nd or 3rd month.
const MONTH_LABEL_MIN_PX = 17.5;
// Below this width per month, "PRESENT" no longer fits its one-month band:
// it reads "NOW", set against the band's right edge, so it and "FUTURE"
// (set against its left edge) sit either side of the rule between them
// instead of on top of each other.
const SECTION_LABEL_MIN_SLOT_PX = 62;

// The month axis, in two rows (Audrey, 2026-10-03): the month names, and
// under them one bracket per year — a rule spanning that year's months with
// the year in the middle of it ("──── 2025 ────") — so a month is read off
// the top row and its year straight below, and where one year ends and the
// next begins is the gap between two brackets.
//
// `slot` is the width of one month in px. Each tick draws its own month;
// the first labelled month of a year also draws that year's bracket, from
// the year's first month to its last (labelled or not).
const YEAR_LABEL_WIDTH = 38;
const MonthYearTick = ({ x, y, payload, rows, step, slot }) => {
  const i = payload.value;
  const row = rows[i];
  if (!row) return null;
  const year = yearOf(row.period);
  const before = rows[i - step];
  const startsYear = !before || yearOf(before.period) !== year;
  const month = (
    <text x={x} y={y + 14} textAnchor="middle" fontSize={slot < 20 ? 8.5 : slot < 26 ? 9.5 : 10.5} fill={CHART_COLORS.axisLabel}>
      {AXIS_MONTHS[monthOf(row.period) - 1]}
    </text>
  );
  if (!startsYear) return month;
  const yearText = (cx) => (
    <text x={cx} y={y + 36} textAnchor="middle" fontSize={11.5} fontWeight={700} fill="var(--color-text, #1a202c)">
      {year}
    </text>
  );
  // Before the plot is measured there is no slot width to span: the year
  // sits under its first month.
  if (!Number.isFinite(slot)) return <g>{month}{yearText(x)}</g>;
  let first = i;
  while (first > 0 && yearOf(rows[first - 1].period) === year) first -= 1;
  let last = i;
  while (last < rows.length - 1 && yearOf(rows[last + 1].period) === year) last += 1;
  // Half a month either side of the year's months, less a gap so two
  // brackets never touch; the axis's own ends stop just past the point.
  const x1 = x + (first - i) * slot - (first === 0 ? 6 : slot / 2 - 4);
  const x2 = x + (last - i) * slot + (last === rows.length - 1 ? 6 : slot / 2 - 4);
  const cx = (x1 + x2) / 2;
  const lineY = y + 32;
  const hasRule = x2 - x1 > YEAR_LABEL_WIDTH + 16;
  return (
    <g>
      {month}
      {hasRule && (
        <>
          <line x1={x1} x2={cx - YEAR_LABEL_WIDTH / 2} y1={lineY} y2={lineY} stroke="var(--color-slate-400, #94a3b8)" strokeWidth={1} />
          <line x1={cx + YEAR_LABEL_WIDTH / 2} x2={x2} y1={lineY} y2={lineY} stroke="var(--color-slate-400, #94a3b8)" strokeWidth={1} />
          <line x1={x1} x2={x1} y1={lineY - 4} y2={lineY} stroke="var(--color-slate-400, #94a3b8)" strokeWidth={1} />
          <line x1={x2} x2={x2} y1={lineY - 4} y2={lineY} stroke="var(--color-slate-400, #94a3b8)" strokeWidth={1} />
        </>
      )}
      {yearText(cx)}
    </g>
  );
};
// The forecast plot's fixed frame, so one month's width can be worked out
// from the container's: the y axis, and the chart's right margin.
const PF_Y_AXIS_WIDTH = 60;
// A measured width for an element that mounts late (the plot sits behind
// the loading and table states, so a ref read once on mount would miss it).
const useMeasuredWidth = () => {
  const [width, setWidth] = useState(0);
  const observer = useRef(null);
  const ref = useCallback((node) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const measure = () => setWidth(node.getBoundingClientRect().width);
    measure();
    observer.current = new ResizeObserver(measure);
    observer.current.observe(node);
  }, []);
  return [ref, width];
};

// Portfolio-level aggregate forecast — sums forecast_value across every
// gated (MASE < 1, the LP's own gate) Class A SKU per period and plots it
// as one line against actual aggregate demand, with an approximate 90%
// range. The range used to be the per-SKU bounds summed, which assumed
// every SKU misses as far as it can in the same direction at once — ±62%
// around Mar 2026's 1,085,193 pieces, an overstatement this comment used
// to admit. Since 2026-10-01 GET /dashboard combines the SKUs' half-widths
// (1.645 x each one's holdout RMSE) as a root-sum-of-squares: ±159k (±15%).
// That assumes the SKUs' misses are independent; demand that swings
// together (a seasonal month) makes the true range wider, and the legend
// and tooltip say so rather than presenting the band as exact.
//
// series: [{ period, actual, forecast, confidenceLower, confidenceUpper }].
// actual is only present for historical periods, forecast/confidence only
// for projected ones — they're expected to share one point where the
// two meet so the lines read as continuous.
//
// Drawn like the hero chart (2026-10-03): a smooth line with no dot per
// month and a light shade of its own colour beneath, divided into Past /
// Present / Future, with months on the axis and the year beneath them.
export const PortfolioForecastWidget = ({
  series = [],
  scopeLabel,
  emptyReason,
  isUpdating = false,
  insight = null,
  // How many SKUs the series sums (GET /dashboard's gated_sku_count) out of
  // the scope's Category A forecasts (forecast.total_count). The tiles that
  // showed the gate's figures are hidden; this line still says the card is
  // a subset — 19 of 132 on 2026-09-29 under the old MAPE gate, when "1.6%
  // below" read as the whole portfolio while all 132 together were +16.4%.
  // Since 2026-09-29 the gate is MASE < 1 (the LP's own), which passes 73.
  gatedSkuCount = null,
  reliability = null,
  // Why the forecast point is not drawn (a range ending before the latest
  // month: the one forecast is for the month after the latest sales).
  forecastNote = null,
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

  // The whole selected range is always in view: the zoom slider and drag-
  // to-pan this card had were removed (Audrey, 2026-10-03) — the date
  // filter at the top of the page is the range control. useChartZoom stays
  // for its entrance animation; with no slider its window never narrows.
  const zoom = useChartZoom(chartData);

  // The x axis is the month's position in the window (0, 1, 2 …), so a
  // section can end halfway between two months.
  const plotRows = useMemo(() => zoom.view.map((pt, i) => ({ ...pt, idx: i })), [zoom.view]);
  const [plotRef, plotWidth] = useMeasuredWidth();

  // Past / Present / Future (FORECAST_SECTION_STYLE): the present is the
  // latest month with actual demand in the whole series; panned away from
  // it, everything in the window is past. The future gets half a month of
  // room past its last point so a single forecast month is a visible band.
  const { sections, xMax } = useMemo(() => {
    const last = plotRows.length - 1;
    if (last < 0) return { sections: [], xMax: 0 };
    const latestActual = [...chartData].reverse().find((pt) => pt.actual != null);
    const present = latestActual ? plotRows.findIndex((pt) => pt.period === latestActual.period) : -1;
    const span = (key, first, lastIdx, x1, x2) => ({
      key, x1, x2, from: plotRows[first].period, to: plotRows[lastIdx].period, ...FORECAST_SECTION_STYLE[key],
    });
    // A range ending before the latest month (forecastNote set) has no
    // present in it: its last month is history, not "latest with sales".
    if (present === -1 || forecastNote) return { sections: [span('past', 0, last, 0, last)], xMax: last };
    const hasFuture = present < last;
    const max = hasFuture ? last + 0.5 : last;
    return {
      xMax: max,
      sections: [
        present > 0 ? span('past', 0, present - 1, 0, present - 0.5) : null,
        span('present', present, present, Math.max(0, present - 0.5), Math.min(max, present + 0.5)),
        hasFuture ? span('future', present + 1, last, present + 0.5, max) : null,
      ].filter(Boolean),
    };
  }, [plotRows, chartData, forecastNote]);
  // Width of one month on the plot: the container (ResponsiveContainer
  // takes 99% of it) less the y axis and the right margin, over the axis's
  // span. Infinity until the plot is measured.
  const slotPx = plotWidth && xMax > 0
    ? (plotWidth * 0.99 - PF_Y_AXIS_WIDTH - EDGE_LABEL_MARGIN) / xMax
    : Infinity;
  // Every month labelled, unless the names would run into each other.
  const tickStep = Math.max(1, Math.ceil(MONTH_LABEL_MIN_PX / slotPx));
  const narrowSlots = slotPx < SECTION_LABEL_MIN_SLOT_PX;
  // The sections in words, so the reader knows which months each one is.
  const sectionNote = { present: ' (latest month with sales)', future: ' (forecast)' };
  const sectionsLine = sections.length > 1
    ? sections.map((sec) => `${sec.label}: ${sec.from === sec.to
      ? formatMonth(sec.from)
      : `${formatMonth(sec.from)} – ${formatMonth(sec.to)}`}${sectionNote[sec.key] ?? ''}`).join(' · ')
    : null;

  // The projection's value, labelled at the end of its line.
  const forecastLabels = useMemo(() => {
    const last = [...zoom.view].reverse().find((pt) => pt.forecast != null);
    return pointLabels(zoom.view, last && last.actual == null
      ? [{ period: last.period, text: `Forecast ${formatCompactQty(last.forecast)} pcs` }]
      : []);
  }, [zoom.view]);

  const tableColumns = [
    { key: 'period', label: 'Month', format: (v) => formatAxisPeriod(v), align: 'left' },
    { key: 'actual', label: 'Actual (pieces)', format: (v) => Math.round(v).toLocaleString() },
    { key: 'forecast', label: 'Forecast (pieces)', format: (v) => Math.round(v).toLocaleString() },
    { key: 'confidenceLower', label: 'Approx. 90% range, low (pieces)', format: (v) => Math.round(v).toLocaleString() },
    { key: 'confidenceUpper', label: 'Approx. 90% range, high (pieces)', format: (v) => Math.round(v).toLocaleString() },
  ];
  // The months the card spans, for the subtitle: the picker's range plus
  // the forecast month after it.
  const seriesSpan = series.length
    ? `${formatMonth(series[0].period)} – ${formatMonth(series[series.length - 1].period)}`
    : null;

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          {/* The unit is PIECES here and pesos on the chart above it; the
              y-axis reads "120k" in both, so it is named in the heading. */}
          <h4>
            Portfolio demand forecast <span className="chart-unit">pieces</span>
            {gatedSkuCount != null && tierACount ? (
              <InfoTip label="Which SKUs are summed">
                {`Demand summed across ${gatedSkuCount.toLocaleString()} of the ${tierACount.toLocaleString()} Class A SKUs: `
                  + 'those whose forecasts beat a simple last-month guess (MASE below 1), the same check the reorder plan uses. '
                  + 'The rest are left out rather than summed on forecasts that failed the check.'}
              </InfoTip>
            ) : null}
          </h4>
          <p>
            {seriesSpan ? `Pieces per month, ${seriesSpan}` : 'Pieces per month'}
            {gatedSkuCount != null && tierACount
              ? ` · ${gatedSkuCount.toLocaleString()} of ${tierACount.toLocaleString()} Class A SKUs that beat a simple last-month guess`
              : ' · planned Class A SKUs'}
          </p>
          {hasData && sectionsLine && view === 'chart' && <p className="chart-insight">{sectionsLine}</p>}
          {hasData && forecastNote && <p className="chart-insight">{forecastNote}</p>}
        </div>
        {/* The card follows the Topbar's principal filter like the rest of
            the page (2026-09-30). Its own All / Del Monte / Unilever + Reset
            filter is on branch parked/all-principals-filter. */}
        {hasData && <ChartViewToggle view={view} onChange={setView} label="Portfolio forecast: chart or table" />}
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
          {/* The scope sentence only when the subtitle could not state the
              SKU count itself (UI pass); otherwise it said the same twice. */}
          {!(gatedSkuCount != null && tierACount) && scopeLabel && (
            <div className="portfolio-stat-row">
              <div className="portfolio-stat">
                <span className="portfolio-stat-label">Scope</span>
                <span className="portfolio-stat-value portfolio-stat-scope">{scopeLabel}</span>
              </div>
            </div>
          )}

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
                  Actual demand (past and present)
                </li>
                {/* Only when a forecast is drawn: a range ending before the
                    latest month shows history alone (forecastNote). */}
                {!forecastNote && (
                  <>
                    <li className="legend-item">
                      <span className="legend-line legend-line-dashed" style={{ borderTopColor: COLORS.forecast }} />
                      Forecast (future)
                    </li>
                    <li className="legend-item">
                      <span className="legend-color" style={{ backgroundColor: COLORS.forecastBg, borderRadius: '3px' }} />
                      Approx. 90% range (if SKUs miss independently)
                    </li>
                  </>
                )}
              </ul>
              <div className="chart-container" ref={plotRef}>
                <ResponsiveContainer width="99%" height="100%">
                  <ComposedChart data={plotRows} margin={{ top: 10, right: EDGE_LABEL_MARGIN, left: 0, bottom: 10 }}>
                    <defs>
                      <linearGradient id="pf-fill-actual" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={CHART_COLORS.salesSeries} stopOpacity={0.26} />
                        <stop offset="100%" stopColor={CHART_COLORS.salesSeries} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid {...GRID_PROPS} />
                    {/* Months by name, each year bracketed beneath them
                        (MonthYearTick) — every month, thinned only when
                        the card is too narrow for the names (tickStep). */}
                    <XAxis
                      dataKey="idx"
                      type="number"
                      domain={[0, xMax]}
                      ticks={plotRows.filter((pt) => pt.idx % tickStep === 0).map((pt) => pt.idx)}
                      axisLine={false}
                      tickLine={false}
                      interval={0}
                      tick={<MonthYearTick rows={plotRows} step={tickStep} slot={slotPx} />}
                      height={X_AXIS_TITLED_HEIGHT + 22}
                      label={xAxisTitle('Month')}
                    />
                    <YAxis
                      width={PF_Y_AXIS_WIDTH}
                      axisLine={false}
                      tickLine={false}
                      domain={['auto', 'auto']}
                      tick={{ fontSize: 10, fill: CHART_COLORS.axisLabel }}
                      tickFormatter={(v) => formatCompactQty(v, 2)}
                      label={yAxisTitle('Pieces')}
                    />
                    {/* Past / Present / Future: a tint behind the lines, the
                        name at the top, a thin rule at each boundary. The
                        present-to-future rule is where history hands over to
                        the projection (it replaces "Forecast starts"). */}
                    {sections.map((sec) => (
                      <ReferenceArea
                        key={sec.key}
                        x1={sec.x1}
                        x2={sec.x2}
                        fill={sec.fill}
                        fillOpacity={sec.fillOpacity}
                        stroke="none"
                        label={{
                          value: (narrowSlots ? sec.narrowLabel ?? sec.label : sec.label).toUpperCase(),
                          position: sec.key === 'future'
                            ? 'insideTopLeft'
                            : sec.key === 'present' && narrowSlots ? 'insideTopRight' : 'insideTop',
                          fontSize: narrowSlots ? 9 : 10,
                          fontWeight: 700,
                          letterSpacing: narrowSlots ? 0.3 : 1,
                          fill: CHART_COLORS.axisLabel,
                        }}
                      />
                    ))}
                    {sections.slice(1).map((sec) => (
                      <ReferenceLine key={`edge-${sec.key}`} x={sec.x1} stroke="var(--color-slate-400, #94a3b8)" strokeWidth={1} />
                    ))}
                    <Tooltip content={<PortfolioForecastTooltip />} />
                    {/* The forecast's uncertainty cone. */}
                    <Area type="linear" dataKey="confidenceBase" stackId="band" stroke="none" fill="transparent" activeDot={false} {...zoom.zoomAnim(0)} />
                    <Area type="linear" dataKey="confidenceBand" stackId="band" stroke="none" fill={COLORS.forecastBg} fillOpacity={0.9} activeDot={false} {...zoom.zoomAnim(0)} />
                    {/* Actual demand: smooth (monotone — through every
                        month's value, never past it), no dot per month, a
                        light shade of its own colour beneath. The hovered
                        month gets a dot. */}
                    <Area
                      type="monotone"
                      dataKey="actual"
                      name="Actual demand"
                      stroke={CHART_COLORS.salesSeries}
                      strokeWidth={2.5}
                      strokeLinecap="round"
                      fill="url(#pf-fill-actual)"
                      dot={false}
                      activeDot={{ r: 5, strokeWidth: 2, stroke: 'var(--color-surface, #fff)' }}
                      connectNulls={false}
                      {...zoom.zoomAnim(1)}
                    />
                    <Line
                      type="monotone"
                      dataKey="forecast"
                      name="Forecast"
                      stroke={COLORS.forecast}
                      strokeDasharray="5 3"
                      strokeWidth={2.5}
                      dot={false}
                      activeDot={{ r: 5, strokeWidth: 2, stroke: 'var(--color-surface, #fff)' }}
                      connectNulls={false}
                      label={forecastLabels}
                      {...zoom.zoomAnim(2)}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
        </div>
      )}
      {/* The card's takeaway, composed by the backend from this same series
          (portfolio_forecast.insight): a soft strip under the chart it sums
          up (mockup pass), where it used to sit in the header. */}
      {insight?.text && (
        <p className="chart-insight portfolio-insight-strip">
          <Info size={15} aria-hidden="true" />
          <span>{insight.text}</span>
        </p>
      )}
    </div>
  );
};

// Soft pills in the shared badge tints (ui.css): critical soft red, urgent
// soft amber, planned neutral. The word is printed in every pill and rows
// stay most-urgent first (sortedRows below), so colour never stands alone.
const URGENCY_STYLES = {
  CRITICAL: { bg: 'var(--badge-critical-bg)', color: 'var(--badge-critical-fg)' },
  URGENT: { bg: 'var(--badge-warning-bg)', color: 'var(--badge-warning-fg)' },
  PLANNED: { bg: 'var(--badge-neutral-bg)', color: 'var(--badge-neutral-fg)' },
};

// Keys match GET /dashboard's reorder_preview.lp_weights exactly (backend/
// routers/dashboard.py's LP_WEIGHT_* constants, themselves a mirror of
// analytics/optimization/lp.py's W1/W2/W3 — the weights the LP solver
// actually used for every currently-pending recommendation).
//
// The bars below are read-only (they were sliders): the API never re-solves
// the LP, so a control that moved would change nothing underneath it.
//
// `blurb` says what each weight actually does in the LP since the
// 2026-09-30 rework (analytics/optimization/lp.py's docstring). The LP
// first orders every SKU up to its target stock, in layers (this month's
// demand, then safety stock, then the rest of the target, which carries
// SSM's 3-week rule). The weights (w1·TC − w2·SL + w3·SC) only decide
// anything when the supplier allocation can't cover every order: then they
// pick which SKUs come up short within the layer being cut. With enough
// allocation they change nothing. The old blurbs described the retired
// model — "reorder-point demand", and storage keeping orders "within what
// the warehouse can affordably hold" — and storage has no effect at all
// today: every SKU carries the same placeholder storage cost per piece
// (lp_inputs.PLACEHOLDERS), so it scores every SKU alike (raising its
// weight to 0.8 changed 0 SKUs' orders).
//
// One colour for all three rows (CHART_COLORS.lpWeight, the model-output
// indigo): they are co-equal weights of a single objective, not three
// categories, so three hues implied a difference in kind that isn't
// there — and the labels carry identity on their own.
const LP_PRIORITY_ROWS = [
  {
    key: 'cost',
    label: 'Cost',
    blurb: 'Only matters when the supplier allocation can’t cover every order. Then SKUs that cost more per piece are cut first. With enough allocation it changes nothing.',
  },
  {
    key: 'service_level',
    label: 'Service level',
    blurb: 'Only matters when the supplier allocation can’t cover every order. Then SKUs that bring in more revenue keep their orders longest, so the best sellers are the last to come up short.',
  },
  {
    key: 'storage',
    label: 'Storage',
    blurb: 'Meant to cut SKUs that are costly to store first. It has no effect today: every SKU has the same placeholder storage cost per piece until SSM gives real per-SKU costs, so it can’t tell one SKU from another.',
  },
];

// Small "?" affordance — hover (or keyboard focus) reveals the blurb.
// Pure CSS visibility off :hover/:focus-within, so there's no popover
// dependency and nothing to position in JS.
const PriorityInfo = ({ text }) => <InfoTip label="About this priority" size={12}>{text}</InfoTip>;

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
  // 'Mar 2026' — the LP plan these rows belong to (GET /dashboard's
  // lp.cycle_date) — and 'counted 6 Apr 2026', the stock count the
  // urgencies were judged against. Either may be null; the text then falls
  // back to "current plan" / leaves the count out.
  cycleLabel = null,
  countLabel = null,
}) => {
  const hasData = rows.length > 0;
  const navigate = useNavigate();

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
          <p>
            Order quantities in pieces from the optimizer (LP) · {cycleLabel ? `${cycleLabel} plan` : 'current plan'}
            {countLabel ? ` · ${countLabel}` : ''}
          </p>
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
              <span className="reorder-mini-label">Critical SKUs</span>
            </div>
            <div className="reorder-mini-chip">
              <span className="reorder-mini-value" style={{ color: SEMANTIC.watch }}>{urgentCount}</span>
              <span className="reorder-mini-label">Urgent SKUs</span>
            </div>
            <div className="reorder-mini-chip">
              <span className="reorder-mini-value">{totalOrderQty.toLocaleString()}</span>
              <span className="reorder-mini-label">Pieces to order</span>
            </div>
          </div>

          {/* The solver's weights, compact: a subheading, one line and three
              thin bars — kept on the card, under the figures, above the list.
              Read-only: GET /dashboard's reorder_preview.lp_weights docstring
              is explicit that this is "read-only display... not an adjustable
              control" (backend/routers/dashboard.py). */}
          <div className="reorder-priorities reorder-priorities-compact">
            <div className="reorder-priorities-header">
              <span className="reorder-priorities-title">How this was optimized</span>
              <span className="reorder-priorities-caption">
                Each SKU is ordered up to its target stock; these weights only decide which SKUs come up short when the
                supplier allocation can&apos;t cover every order.
              </span>
            </div>
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
                  <th>Product</th>
                  <th>Urgency</th>
                  <th>Order (pieces)</th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((r) => (
                  <tr key={r.sku}>
                    {/* Name first, SKU code under it (Sir Catubag, 2 Oct
                        2026) — the table used to lead with the code. The name
                        opens that SKU's own recommendation, which the Reorder
                        Recs page shows in its detail modal on load (the ?sku=
                        handling in ReorderRecommendations.jsx), as the code
                        link did. */}
                    <td className="reorder-mini-product" title={r.product || r.sku}>
                      <ProductName
                        name={r.product}
                        code={r.sku}
                        onOpen={() => navigate(`/reorder?sku=${encodeURIComponent(r.sku)}`)}
                        openLabel="Open the recommendation for"
                      />
                    </td>
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

// LP target stock vs SSM's own 3-week stock policy — GET /dashboard's
// policy_comparison, in the demand series' unit (pieces). SSM's policy
// (client meeting, Sep 2026: keep three weeks of sales in the warehouse)
// is applied per SKU to the same forecasts the LP used. Since the
// 2026-09-30 LP run each SKU has a target stock (demand over the review +
// lead window plus safety stock), and THAT is what compares with 3 weeks:
// both are how much stock to hold. Until then this card set the LP's
// safety stock alone against the rule's whole 3 weeks, which read "35.2%
// less" when the targets hold 18.2% more. The LP bar is stacked into its
// two parts — sales until the next delivery, then safety stock — so the
// buffer is visible inside the target. Units, not pesos — no
// agreed per-piece cost exists (the backend's policy_comparison
// docstring). The policy bar is slate (a baseline, no verdict), the LP
// bars indigo (model output), per the SEMANTIC rule.
export const PolicyComparisonWidget = ({ comparison, emptyReason }) => {
  const c = comparison || {};
  const ruleUnits = c.rule_stock_units ?? c.rule_safety_stock_units;
  const hasData = c.lp_target_stock_units != null && ruleUnits != null;
  const max = hasData ? Math.max(c.lp_target_stock_units, ruleUnits, 1) : 1;
  const ruleWeeks = c.rule_weeks ?? 3;
  // The LP target is two parts added together, so it is ONE stacked bar
  // rather than a target bar plus a separate safety-stock bar (which read as
  // a third policy): the sales expected until the next delivery arrives,
  // and the safety stock on top for demand above the forecast. Both are
  // steps of the LP's indigo, validated as a pair (dataviz
  // validate_palette.js: CVD ΔE 19.9, normal 21.5); the lighter one is
  // under 3:1 against the surface, so the legend below labels both parts
  // with their figures rather than leaving them to colour.
  const windowDays = c.window_business_days != null ? Number(c.window_business_days) : null;
  const safetyUnits = c.lp_safety_stock_units;
  const cycleUnits = hasData && safetyUnits != null ? Math.max(c.lp_target_stock_units - safetyUnits, 0) : null;
  const lpParts = cycleUnits != null
    ? [
      {
        key: 'cycle',
        label: 'Sales until the next delivery',
        note: windowDays != null ? `${windowDays.toFixed(0)} business days of forecast sales` : 'forecast sales over the review period + lead time',
        value: cycleUnits,
        color: SEMANTIC.recommendation,
      },
      {
        key: 'safety',
        label: 'Safety stock',
        note: 'buffer for demand above the forecast',
        value: safetyUnits,
        color: '#A5A7F6',
      },
    ]
    : [{ key: 'target', label: 'LP target stock', value: c.lp_target_stock_units, color: SEMANTIC.recommendation }];
  const rows = [
    { key: 'rule', label: `SSM ${ruleWeeks}-week policy`, value: ruleUnits, color: SEMANTIC.noData,
      parts: [{ key: 'rule', label: `SSM ${ruleWeeks}-week policy`, value: ruleUnits, color: SEMANTIC.noData }] },
    { key: 'target', label: 'LP target stock', value: c.lp_target_stock_units, color: SEMANTIC.recommendation, parts: lpParts },
  ].filter((r) => r.value != null);
  const pieces = (v) => `${Math.round(v).toLocaleString()} pieces`;

  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Stock target: LP vs SSM&apos;s 3-week policy</h4>
          <p>
            How much stock each policy would hold across the latest planning cycle, in pieces.
            SSM&apos;s policy keeps three weeks of each SKU&apos;s own forecast in stock; the LP sets a
            per-SKU target instead — the demand expected before the next delivery plus a safety buffer.
          </p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || c.blocked_reason || 'Policy comparison not available'}</p>
      ) : (
        <div className="chart-widget-body">
          {/* The one-number headline (IMPLEMENTATION_PLAN Phase 1.1-1.2):
              units and percent, never pesos. target_vs_rule_pct is how much
              less stock the LP's targets hold than the rule; negative = more. */}
          {c.target_vs_rule_pct != null && (
            <p className="policy-headline">
              <span className="policy-headline-number">{Math.abs(c.target_vs_rule_pct).toFixed(1)}%</span>
              <span className="policy-headline-text">
                {c.target_vs_rule_pct >= 0 ? 'less' : 'more'} stock under the LP&apos;s per-SKU targets than
                SSM&apos;s {ruleWeeks}-week policy
                {c.lp_target_weeks != null ? ` — ${Number(c.lp_target_weeks).toFixed(2)} weeks of sales against ${ruleWeeks}` : ''},
                across {c.sku_count} SKUs
              </span>
            </p>
          )}
          {/* Where the difference comes from: the targets move stock between
              SKUs by how volatile each one's demand is, rather than giving
              every SKU the same 3 weeks. */}
          {c.skus_above_rule != null && (
            <p className="dashboard-chart-footnote">
              {c.skus_above_rule} of {c.sku_count} SKUs get a target above {ruleWeeks} weeks (the ones with the
              most volatile demand); the other {c.sku_count - c.skus_above_rule} get less.
            </p>
          )}
          <div className="policy-bars">
            {rows.map((r) => (
              <div className="policy-bar-row" key={r.key}>
                <span className="policy-bar-label">{r.label}</span>
                {/* Meter rule: the unfilled track is a lighter step of the
                    fill's own hue, so each bar reads as one meter. Each part
                    of a stacked bar carries its own hover title. */}
                <div
                  className="policy-bar-track"
                  role="img"
                  aria-label={r.parts.length > 1
                    ? `${r.label}: ${pieces(r.value)} — ${r.parts.map((part) => `${part.label.toLowerCase()} ${pieces(part.value)}`).join(' + ')}`
                    : `${r.label}: ${pieces(r.value)}`}
                  style={{ background: `color-mix(in srgb, ${r.color} 12%, var(--color-surface))` }}
                >
                  {r.parts.map((part) => (
                    <span
                      key={part.key}
                      title={`${part.label}: ${pieces(part.value)}`}
                      style={{ width: `${(part.value / max) * 100}%`, backgroundColor: part.color }}
                    />
                  ))}
                </div>
                <span className="policy-bar-value">{pieces(r.value)}</span>
              </div>
            ))}
          </div>
          {/* What the LP bar is made of, with each part's figure — the
              labels the lighter segment's contrast requires. */}
          {lpParts.length > 1 && (
            <ul className="custom-legend policy-parts-legend">
              {lpParts.map((part) => (
                <li className="legend-item" key={part.key}>
                  <span className="legend-color" style={{ backgroundColor: part.color, borderRadius: '3px' }} />
                  <span>
                    <strong>{part.label}</strong> {pieces(part.value)}
                    <span className="policy-part-note"> · {part.note}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="dashboard-chart-footnote">
            {c.sku_count} SKUs in the {formatMonth(c.cycle_date)} cycle with a forecast for that month, all in
            pieces — the unit the LP solves in — so the policies compare without a peso conversion.
          </p>
          {/* The headline moves most with the safety stock's window and the
              placeholders behind it (analytics/optimization/lp_inputs.py),
              so they are stated beside the number. */}
          <p className="policy-assumption">
            <strong>Assumption:</strong> the safety stock covers
            {c.window_business_days != null ? ` ${Number(c.window_business_days).toFixed(0)} business days` : ' the review period plus lead time'}{' '}
            (weekly orders, delivered 2–3 days later), assuming demand is independent from one day to the
            next.{c.inputs_are_placeholders ? ' These are placeholder inputs until SSM confirms them, and the headline is sensitive to them.' : ''}
          </p>
        </div>
      )}
    </div>
  );
};

// Sales vs SSM's supplier allocation — GET /dashboard's `allocation`.
// SSM's rule (client meeting, Sep 2026): the principal sets the year's
// allocation from the PREVIOUS year's total sales — minimum x103%, mid
// x105%, maximum x108%, revised in Q4 on how the market went. The three
// allocation bars are slate (a policy baseline, no verdict) and the sales
// bar the sales-series colour, all as average pesos per month so a partial
// year compares honestly with a full-year allocation. Withheld under All
// principals (allocations are per principal, and the two principals'
// pesos sit on different tax bases — the backend's blocked_reason says so).
export const AllocationWidget = ({ allocation }) => {
  const a = allocation || {};
  const hasData = a.basis_sales != null && (a.levels || []).length > 0;
  const avgMonthlySales = hasData && a.ytd_sales != null && a.ytd_months > 0
    ? a.ytd_sales / a.ytd_months
    : null;
  // The allocation year (the year after the basis): the year the selected
  // range ends in (GET /dashboard, 2026-10-09), its sales Jan to that month.
  const latestYear = a.allocation_year ?? (a.latest_month ? Number(a.latest_month.slice(0, 4)) : null);
  const latestMonthName = a.latest_month ? formatMonth(a.latest_month).split(' ')[0] : null;
  // The period in the header: "Jan–Feb 2026", or one month alone. A past
  // year reads in full ("Jan–Dec 2025"), so "so far" is not claimed for it.
  const monthSpan = a.ytd_months === 1 ? latestMonthName : `Jan–${latestMonthName}`;
  const periodText = latestYear && a.ytd_months > 0
    ? `${monthSpan} ${latestYear}`
    : latestYear ? `${latestYear} — no sales loaded yet` : null;
  // `monthly` is an average month of the basis x pct (GET /dashboard, since
  // 2026-10-01): basis_months < 12 is a partial basis, said in the tooltip.
  const levels = hasData ? [...a.levels].sort((x, y) => x.pct - y.pct) : [];
  const minimum = levels[0] || null;
  const highest = levels[levels.length - 1] || null;
  // The statement: average monthly sales against the minimum level (and
  // the highest), in pesos a month — below, meeting or above.
  const gap = minimum && avgMonthlySales != null ? minimum.monthly - avgMonthlySales : null;
  let statement = null;
  if (gap != null) {
    if (gap > 0) {
      statement = <>Sales are <strong>{formatCompactPesos(gap)} a month short</strong> of SSM&apos;s minimum allocation ({minimum.pct}%).</>;
    } else if (highest && avgMonthlySales < highest.monthly) {
      statement = <>Sales <strong>meet SSM&apos;s minimum allocation</strong> ({minimum.pct}%), {formatCompactPesos(highest.monthly - avgMonthlySales)} a month short of the {highest.pct}% level.</>;
    } else {
      statement = <>Sales are <strong>{formatCompactPesos(avgMonthlySales - highest.monthly)} a month above</strong> even the {highest.pct}% allocation level.</>;
    }
  }
  // One scale for the bar and the markers, from zero to a little past the
  // highest level, so every length is comparable.
  const scaleMax = Math.max(highest?.monthly || 0, avgMonthlySales || 0) * 1.06 || 1;
  const at = (v) => `${(Math.max(0, v) / scaleMax) * 100}%`;
  const shortfall = gap != null && gap > 0;
  // Sales as a share of the minimum level, both pesos a month.
  const achievement = minimum?.monthly > 0 && avgMonthlySales != null ? avgMonthlySales / minimum.monthly : null;

  return (
    <div className={`chart-widget alloc-card${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="alloc-head">
        <h4 className="alloc-title">Sales vs supplier allocation</h4>
        <span className="alloc-head-tags">
          {periodText && <span className="fc-period">{periodText}</span>}
          {hasData && <span className="badge badge-warning">Assumption · pending SSM</span>}
        </span>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{a.blocked_reason || 'Allocation not available'}</p>
      ) : (
        <>
          {/* 1. The answer. */}
          {statement
            ? <p className="alloc-answer">{statement}</p>
            : (
              <p className="alloc-answer">
                No {latestYear} sales are loaded yet
                {a.latest_month ? ` (the latest month on record is ${formatMonth(a.latest_month)})` : ''}, so there is
                nothing to compare with the {latestYear} allocation yet.
              </p>
            )}

          {/* The three figures behind the sentence. */}
          {achievement != null && (
            <div className="alloc-metrics">
              <div className="alloc-metric is-sales">
                <span className="alloc-metric-label">Sales, {monthSpan} {latestYear}</span>
                <span className="alloc-metric-value">{formatCompactPesos(avgMonthlySales)}<small>/month</small></span>
              </div>
              <div className="alloc-metric is-target">
                <span className="alloc-metric-label">Minimum allocation ({minimum.pct}%)</span>
                <span className="alloc-metric-value">{formatCompactPesos(minimum.monthly)}<small>/month</small></span>
              </div>
              <div className="alloc-metric is-achieved">
                <span className="alloc-metric-label">Achievement</span>
                <span className="alloc-metric-value">{Math.round(achievement * 100)}%<small>of the minimum</small></span>
              </div>
            </div>
          )}

          {/* 2. One bar: average monthly sales, with each allocation level
              as a marker on the same peso scale. */}
          <div className="alloc-chart">
            <div className="alloc-track" role="img" aria-label={
              `${avgMonthlySales != null ? `Average monthly sales ${formatCompactPesos(avgMonthlySales)}` : 'No sales yet'}; `
              + levels.map((l) => `${l.pct}% allocation ${formatCompactPesos(l.monthly)} a month`).join('; ')
            }>
              {avgMonthlySales != null && (
                <span className="alloc-bar" style={{ width: at(avgMonthlySales), backgroundColor: CHART_COLORS.salesSeries }}>
                  <span className="alloc-bar-label">{formatCompactPesos(avgMonthlySales)}/mo</span>
                </span>
              )}
              {/* The shortfall to the minimum, a soft amber stretch. */}
              {shortfall && (
                <span className="alloc-gap" style={{ left: at(avgMonthlySales), width: `${(gap / scaleMax) * 100}%` }} aria-hidden="true" />
              )}
              {levels.map((l) => (
                <span
                  key={l.pct}
                  className={`alloc-tick${l === minimum ? ' is-minimum' : ''}`}
                  style={{ left: at(l.monthly) }}
                  aria-hidden="true"
                />
              ))}
            </div>
            {/* Marker labels as a staircase: each on its own row, ending at
                its marker, so close levels never overlap at any width. */}
            <div className="alloc-ticks">
              {levels.map((l, i) => (
                <div className="alloc-tick-row" key={l.pct} style={{ '--row': i }}>
                  <span className="alloc-tick-lead" style={{ left: at(l.monthly) }} aria-hidden="true" />
                  <span className={`alloc-tick-label${l === minimum ? ' is-minimum' : ''}`} style={{ right: `calc(100% - ${at(l.monthly)})` }}>
                    {l.pct}%{l === minimum ? ' minimum' : ''} · {formatCompactPesos(l.monthly)}/mo
                  </span>
                </div>
              ))}
            </div>
            <ul className="alloc-key">
              <li><span className="alloc-key-swatch" style={{ backgroundColor: CHART_COLORS.salesSeries }} aria-hidden="true" />
                Average monthly sales{a.ytd_months > 0 ? `, ${a.ytd_months} month${a.ytd_months === 1 ? '' : 's'}` : ''}</li>
              <li><span className="alloc-key-tick" aria-hidden="true" />Allocation levels (assumed)</li>
              {shortfall && <li><span className="alloc-key-swatch is-gap" aria-hidden="true" />Shortfall to the minimum</li>}
            </ul>
          </div>

          {/* 3. The assumption, small, with the derivation behind the "?". */}
          <p className="alloc-foot">
            Assumed rule: last year&apos;s sales × {minimum?.pct}–{highest?.pct}%. Not yet confirmed by SSM.
            <InfoTip label="How the allocation levels are worked out">
              SSM&apos;s rule (client meeting, Sep 2026): the year&apos;s allocation is the previous year&apos;s total
              sales ×103% (minimum), ×105% (mid) or ×108% (maximum), revised each Q4. Each level here is {a.basis_year}
              {' '}sales of {formatCompactPesos(a.basis_sales)} ({a.vat_basis}) × the percentage, as an average month
              {a.basis_months < 12
                ? ` of the ${a.basis_months} months on record — a partial basis, so the levels may change once the year is complete`
                : ' (÷ 12)'}
              . Sales are this year&apos;s monthly average over the same months on the same basis. SSM has not shared its
              real allocation figures, and which percentage applies in {latestYear} is a question for SSM.
            </InfoTip>
          </p>
        </>
      )}
    </div>
  );
};
