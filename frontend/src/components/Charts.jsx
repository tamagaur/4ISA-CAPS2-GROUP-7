import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import SectionLede from './ui/SectionLede';
import { createPortal } from 'react-dom';
import { Link, useNavigate } from 'react-router-dom';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import {
  ComposedChart, BarChart, Bar, Cell, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, ReferenceLine, ReferenceArea,
  usePlotArea,
} from 'recharts';
import {
  AlertTriangle, ArrowRight, Box, CalendarDays, ChartColumn, CheckCircle2, ChevronLeft, ChevronRight, Clock, Info, Layers, RotateCcw, ShoppingCart,
} from 'lucide-react';
import { CHART_COLORS, STATUS_TIERS, COLORS, SEMANTIC } from '../theme/colors';
import { formatMonth } from '../utils/formatDate';
import { formatUnits } from '../utils/formatNumber';
import { shownPiecesTotal } from '../utils/piecesTotal';
import { formatCompactPesos, formatExactPesos, formatCompactQty } from '../utils/formatters';
import { chartAnim, prefersReducedMotion, CHART_ANIM_DURATION, CHART_ANIM_STAGGER } from '../theme/motion';
import { useChartZoom, seriesDot, GRID_PROPS, EDGE_LABEL_MARGIN } from './ChartZoom';
import { ChartTable, ChartViewToggle } from './ChartTable';
import { isPlaceholderPeriod } from '../dataMode';
import { LoadingStatus, SkeletonChart } from './Skeleton';
import InfoTip from './InfoTip';
import ProductName from './ProductName';
import GapNote from './GapNote';
import { gapLabel, originLabel } from '../utils/gapReasons';
import { monthsBetween, monthsEarlier, timelineMonths } from '../utils/timeline';
import {
  comparedMonthsMissing, comparisonRows, longMonth, monthRuns, monthWindows, oppositeMovement, periodsLabel, stripScale, yearGroupsOf,
} from '../utils/periodComparison';
import { pesoTicks } from '../utils/pesoTicks';
import { demandHighlights, labelsThatFit } from '../utils/forecastHighlights';
import { reviewReasonsSentence } from '../utils/reviewReasons';
import MonthTick, { monthName } from './MonthTick';
import { Callout, CalloutLine, CalloutNote, Callouts } from './ui/ChartParts';
import { COMPARISON_LINE, FORECAST_LINE, LineShade, SHADE_ONLY, SOLID_LINE, endDot, lineHoverDot, useLineShadeId } from './ui/lineDesign';
import {
  CALENDAR_HISTORY_NOTE, CALENDAR_METHOD_FALLBACK, calendarFactorText, calendarSignoffText, calendarYearsText,
} from '../utils/calendarAdjustment';
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

// Axis titles. The Technical Adviser's rule (2 Oct 2026): every number states
// its unit and its period, and a tick reading "₱25M" or "1.2M" does neither
// on its own — so every Dashboard chart names what each axis counts. One
// helper, so the titles share a size, colour and placement. The Y title is
// centred on the axis (textAnchor middle, which Recharts 3 lets a label
// override) rather than starting at its middle and running off the top.
const AXIS_TITLE = { fontSize: 11, fontWeight: 600, fill: CHART_COLORS.axisLabel };
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
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: CHART_COLORS.axisLabel }} dy={10} tickFormatter={formatAxisPeriod} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  domain={[0, 'auto']}
                  tick={{ fontSize: 11, fill: CHART_COLORS.axisLabel }}
                  label={{ value: 'Weeks of stock', angle: -90, position: 'insideLeft', fontSize: 11, fill: CHART_COLORS.axisLabel }}
                />
                <Tooltip content={<CoverTooltip policyTarget={policyTarget} />} />
                <Area type="monotone" dataKey="base" stackId="cover" stroke="none" fill="transparent" {...chartAnim()} />
                <Area type="monotone" dataKey="excess" stackId="cover" fill={CHART_COLORS.stockSeries} fillOpacity={0.18} stroke="none" {...chartAnim()} />
                <ReferenceLine
                  y={policyTarget}
                  stroke={STATUS_TIERS.loss}
                  strokeDasharray="4 4"
                  label={{ value: `our rule: ${policyTarget} weeks`, position: 'insideTopRight', fontSize: 11, fill: STATUS_TIERS.loss }}
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

const AllocationTooltip = ({ active, payload }) => {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  const shortfall = row.variancePesos < 0;
  return (
    <div style={{
      backgroundColor: '#ffffff', border: '1px solid #e2e8f0', padding: '0.6rem 0.8rem',
      borderRadius: '8px', boxShadow: '0 4px 15px rgba(0, 0, 0, 0.08)',
    }}>
      <p style={{ fontWeight: 700, color: '#1a202c', margin: '0 0 0.3rem 0', fontSize: '0.9rem' }}>{row.sku}</p>
      <p style={{ margin: '0.1rem 0', fontSize: '0.86rem', color: '#4a5568' }}>Allocation: {row.allocationCases} cases</p>
      <p style={{ margin: '0.1rem 0', fontSize: '0.86rem', color: '#4a5568' }}>Forecast: {row.forecastCases} cases</p>
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
              tick={{ fontSize: 11, fill: CHART_COLORS.axisLabel }}
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

// Weeks of stock (the "Weeks of stock" view): month-end stock ÷ that month's
// average weekly sales, with monthly sales turned weekly by the backend's own
// convention, analytics/params.py WEEKS_PER_MONTH = (365.25 / 12) / 7 (about
// 4.35; GET /dashboard does not send it, so it is copied here: change both
// together). Real months only: a month without both a real stock count and
// real sales has no point (CLAUDE.md rule 2: no generated figure feeds it).
const WEEKS_PER_MONTH = 365.25 / 12 / 7;
const weeksOfStock = (stock, sales) => (stock != null && sales != null && sales > 0 ? stock / (sales / WEEKS_PER_MONTH) : null);
// The weeks axis: 0 to past the highest value and the rule, in 1, 2 or 5
// week steps.
const weekTicks = (values, policy) => {
  const present = values.filter((v) => v != null);
  if (!present.length) return null;
  const top = Math.max(...present, policy ?? 0) * 1.1;
  const step = top <= 8 ? 1 : top <= 16 ? 2 : 5;
  const hi = Math.ceil(top / step) * step;
  return Array.from({ length: hi / step + 1 }, (_, i) => i * step);
};
const fmtWeeksValue = (v) => `${Number(v).toFixed(1)} wks`;
// The figures a point can carry onto the chart.
const PLOTTED_FIELDS = [
  'sales', 'stockOnHand', 'received', 'receivedEstimated', 'salesEstimated', 'stockEstimated', 'returns', 'returnsEstimated',
];
// The ₱ axis's floor and ticks (a floor just under the lowest value, explicit
// ticks): utils/pesoTicks.js, shared with the forecast card's chart.

// Month ticks shrink on a narrow card so they still fit.
const YOY_WIDE_PX = 700;
// Below this the card is on a phone.
const YOY_PHONE_PX = 480;
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

// Which metrics the chart shows. The table always holds both.
const METRIC_VIEWS = [['both', 'Both'], ['sales', 'Sales'], ['inventory', 'Inventory']];
// Purchases get their own view (sales beside what was bought) once there is
// a purchases figure to draw, recorded or estimated.
const PURCHASES_VIEW = ['purchases', 'Purchases'];
const WEEKS_VIEW = ['weeks', 'Weeks of stock'];
// An ESTIMATE is drawn apart from a recorded figure (3 Oct 2026 analysis):
// dotted and lighter, with its own legend entry, in the chart only — never
// in a KPI. GET /dashboard's received_estimated is purchases worked out from
// stock counts and sales (closing − opening stock + sales), not a purchase
// record. A negative estimate is shown as 0 and the tooltip flags it.
const ESTIMATED_DASH = '2 5';
const ESTIMATED_OPACITY = 0.75;
// Mart estimates for a month with no real figure (GET /dashboard
// *_estimated, DEC-31): 'filled' rows are worked out from SSM's own data
// (real mode); 'generated' rows are synthetic and come in preview only.
// Drawn like the purchases estimate, in the chart and its table only.
const ESTIMATE_KIND_TEXT = {
  filled: 'estimated (filled gap)',
  generated: 'Synthetic — SSM data not received',
  // Del Monte's synthetic demonstration months (GET /dashboard's
  // demonstration block, schema demo), drawn only with synthetic data on.
  demonstration: 'synthetic',
};
// Returns get a view of their own: they run at a few percent of sales, so on
// the sales axis they would lie flat along zero.
const RETURNS_VIEW = ['returns', 'Returns'];

// "Nov 2025": a month as the tooltip and the Purchases bars say it.
const plainPeriod = (period) => formatAxisPeriod(period).replace(' · ', ' ');

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
// "At last purchase price", not "at cost" (3 Oct 2026 analysis): the SOH
// file's extended cost prices each product at what it was last bought for,
// which is above SSM's true cost, so "at cost" claimed more than it knows.
// The stock line is the PESO value of the stock count at cost (Inventory_
// Fact.valuation, the SOH file's own extended cost), not a quantity on hand.
// It was labelled "Stock on hand", which a reader takes for pieces or cases;
// renamed 2026-10-02 so the legend, tooltip and table say what is plotted.
const WEEKS_LABEL = 'Weeks of stock';


// Sales vs Inventory Value — the dashboard's hero chart. Three layers, top to
// bottom: the main chart, the change strips, and the month windows.
//   The main chart shows both periods, so a month's two figures can be read
//   straight off it (Technical Adviser, 2 Oct 2026: "2025 vs 2024?"; Audrey,
//   2026-11-03: both years must be seen). The comparison is always the lighter
//   shade of the metric's own colour, and in a bar pair the earlier month is on
//   the left. Two periods are never added together.
//     Both           one combo chart: monthly sales as bar pairs, stock value as
//                    a solid line and the comparison as a dashed one (monotone,
//                    so a curve never overshoots a month's figure), on one ₱ axis
//                    from ₱0;
//     Sales          the bar pairs alone;
//     Inventory,
//     Returns        two lines each, on an axis that starts just under the lowest
//                    value (yoyFloor);
//     Weeks of stock a bar pair per month: the selected month blue under SSM's
//                    rule and orange over it, a dashed line at the rule, and a
//                    month whose stock count needs checking outlined;
//     Purchases      "Sold vs bought": a pair each per month; a month whose
//                    purchase estimate rests on a stock count that needs
//                    checking has its "bought" bar as a dashed outline.
//   The months carry no year on the axis; a quiet band under them does.
//   The change strips give each month's change in percent ("the story is in
//   the changes"), one strip per metric, directly under that month: SvsChangeStrip. It uses
//   the plot's own measurements, so the two can't drift out of line. The pairing
//   and the change are worked out once (utils/periodComparison.js), for the
//   strips, the hover and the table alike. "No comparison" has no strips.
//   The month windows: at most 12 months show at once, fewer where they would
//   crowd (a phone shows about 6), and buttons move between the windows. The
//   selected range itself doesn't change, and the table always lists all of it.
// One month is "read" at a time, by mouse, tap or the arrow keys, and the plot,
// the strips and the hover all follow it. The hover is drawn by this card.
// A month with no figure is a gap, never a 0; an estimate or a synthetic month
// is drawn apart (a hatched bar, a dotted line) and named in the legend; a stock
// count GET /dashboard flags keeps its grey marker. Switching views never moves
// the card: the notes under the plot share the body's fixed height with it.
//
// `data` is [{ period, sales, stockOnHand, received, … }] (Dashboard.jsx's
// chartPoints), all in pesos. `insight` is GET /dashboard's
// sales_vs_stock_insight: the sentence under the title and the peak/low
// sales months, said in the hover. `basis` is sales_vs_stock_basis (the
// flows' tax basis), `note` the vat_note under All principals.
const SVS_COLOR = {
  sales: '#139BA6',
  stock: '#385BA9',
  returns: CHART_COLORS.heroReturns,
};
// The comparison: a lighter shade of each metric's own colour, so a pair reads
// as one metric in two periods. Lines are dashed as well, so colour is never the
// only thing telling them apart; a bar pair also has its place, earlier on the left.
const COMPARE_COLOR = { sales: '#A5DCE2', stock: '#92A8D5', returns: '#DDB27E', bought: '#B3C1E1', weeks: '#CBD5E1' };
const COMPARE_DASH = COMPARISON_LINE.strokeDasharray;
// Weeks of stock: under the rule blue, over it orange (a pair that stays
// apart for colour-blind readers), and grey near it (within half a week);
// blue and orange mean this and nothing else in this view (2026-10-19).
const WEEKS_UNDER = '#2563EB';
const WEEKS_OVER = '#E8710A';
const WEEKS_NEAR = '#98A2B3';
const WEEKS_COLOR = { under: WEEKS_UNDER, over: WEEKS_OVER, near: WEEKS_NEAR };
// This view's change strip: neither band's colour.
const WEEKS_COMPARE = '#344054';
const WEEKS_NEAR_BAND = 0.5;
const weeksBand = (weeks, policy) => (weeks == null ? 'near'
  : weeks < policy - WEEKS_NEAR_BAND ? 'under'
    : weeks > policy + WEEKS_NEAR_BAND ? 'over' : 'near');
const UNUSUAL_INK = 'var(--color-text-muted, #556070)';

// Sold vs bought (the Purchases view): sold in the card's sales teal, bought
// navy, the same meaning on every view.
const SOLD_COLOR = SVS_COLOR.sales;
const BOUGHT_COLOR = SVS_COLOR.stock;

// ₱ ticks from ₱0, about five, for the combo chart's bars.
const zeroPesoTicks = (values) => {
  const top = Math.max(0, ...values.filter((v) => v != null));
  if (!(top > 0)) return null;
  const raw = top / 5;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 2.5, 5, 10].find((f) => f * magnitude >= raw) || 10) * magnitude;
  const ticks = [];
  for (let v = 0; v < top + step; v += step) ticks.push(v);
  return ticks;
};

// The month axis is the dashboard's shared two-line tick (MonthTick.jsx:
// the month over its year) since 2026-10-19; Recharts thins the ticks on a
// long range (minTickGap).

// A key in the legend, drawn the way the plot draws it.
const SvsSwatch = ({ kind, color }) => {
  if (kind === 'line' || kind === 'dotted' || kind === 'dash') {
    return (
      <svg className="legend-metric-line" width="26" height="8" aria-hidden="true">
        <line
          x1="2"
          x2="24"
          y1="4"
          y2="4"
          stroke={color}
          strokeWidth={kind === 'line' ? SOLID_LINE.strokeWidth : COMPARISON_LINE.strokeWidth}
          strokeLinecap="round"
          strokeDasharray={kind === 'dotted' ? ESTIMATED_DASH : kind === 'dash' ? COMPARE_DASH : undefined}
        />
      </svg>
    );
  }
  const style = kind === 'hatch'
    ? { background: `repeating-linear-gradient(45deg, ${color} 0 2px, #fff 2px 4px)`, boxShadow: `inset 0 0 0 1px ${color}` }
    : kind === 'outline'
      ? { background: 'transparent', boxShadow: `inset 0 0 0 1.5px ${color}` }
      : kind === 'dot'
        ? { background: color, borderRadius: '50%' }
        : { background: color };
  return <span className="svs-swatch" style={style} aria-hidden="true" />;
};

// The hover: one white panel for the month. The month and what it is compared
// with, then a section per metric in the view, each with its figures and the
// change, then the notes: why a count needs checking, what a purchases estimate
// rests on, why a month has no figure. Change figures stay in a neutral ink: a
// rise in stock is not good, and a fall is not bad, by itself.
const estimateKind = (metric, pt) => ({
  sales: pt.salesSynthetic ? 'synthetic' : pt.salesEstimatedKind === 'demonstration'
    ? `synthetic, ${(pt.salesOrigin || []).map(originLabel).join(' and ') || 'generated'}`
    : ESTIMATE_KIND_TEXT[pt.salesEstimatedKind] || 'estimated',
  stock: ESTIMATE_KIND_TEXT[pt.stockEstimatedKind] || 'estimated',
  returns: ESTIMATE_KIND_TEXT[pt.returnsEstimatedKind] || 'estimated',
}[metric]);

const changeSign = (v) => (v > 0 ? '+' : v < 0 ? '−' : '');
const signedPct = (v) => `${changeSign(v)}${Math.abs(v).toFixed(1)}%`;
const signedPesos = (v) => `${changeSign(v)}${formatExactPesos(Math.abs(v))}`;
const signedWeeks = (v) => `${changeSign(v)}${Math.abs(v).toFixed(1)} wks`;

const stockNote = (period, pt) => (
  <p key={`flag-${period}`} className="svs-tip-note">
    <strong>{longMonth(period)}: Stock count needs checking</strong>
    {pt?.stockUnusual ? `Reason: ${pt.stockUnusual}` : 'Reason not recorded'}
  </p>
);

// A suggestion to look, not a diagnosis: oppositeMovement says only which way
// the two figures went, and nothing here says why.
const MOVEMENT_TEXT = {
  stockUp: 'Inventory increased while sales declined. Review this month\'s stock movement.',
  stockDown: 'Inventory decreased while sales increased. Review this month\'s stock movement.',
};

const SvsTooltip = ({ row, comparing, pending, sections, marks, purchases = false, side, style, arrowTop }) => {
  const missingCompared = (section) => {
    if (row.noEarlier) return 'No earlier data available';
    if (pending) return 'Loading…';
    if (section.metric === 'sales' && row.cpt?.salesReason) return gapLabel(row.cpt.salesReason);
    return 'No figure on record';
  };
  const missingSelected = (section) => (
    section.metric === 'sales' && row.pt?.salesReason ? gapLabel(row.pt.salesReason) : 'No figure on record'
  );
  const figure = (label, section, period, pt, own, est, missing) => {
    const estimated = own == null && est != null;
    const value = own ?? est ?? null;
    const asides = [
      estimated && estimateKind(section.metric, pt),
      section.metric === 'sales' && marks[period],
      section.metric === 'stock' && pt?.stockCountDay && `counted ${pt.stockCountDay}`,
    ].filter(Boolean);
    return (
      <span className="svs-tip-line">
        <span>
          {label}
          {asides.length > 0 && <span className="svs-tip-aside"> · {asides.join(' · ')}</span>}
        </span>
        {value != null ? <strong>{section.format(value)}</strong> : <strong className="is-missing">{missing}</strong>}
      </span>
    );
  };
  const usesStock = sections.some((s) => s.metric === 'stock' || s.metric === 'weeks');
  const bothMetrics = sections.some((s) => s.metric === 'sales') && sections.some((s) => s.metric === 'stock');
  const movement = comparing && bothMetrics ? oppositeMovement(row.change) : null;
  return (
    <div className={`svs-tip is-${side}`} style={style} role="status">
      <span className="svs-tip-arrow" style={arrowTop != null ? { '--tip-arrow-top': `${arrowTop}px` } : undefined} aria-hidden="true" />
      <div className="svs-tip-head">
        <strong>{longMonth(row.period)}</strong>
        {comparing && row.comparePeriod && <span>vs {longMonth(row.comparePeriod)}</span>}
      </div>
      {sections.map((section) => {
        const change = row.change?.[section.change];
        return (
          <div key={section.key} className="svs-tip-section">
            <span className="svs-tip-title">
              <SvsSwatch kind={section.swatch} color={section.color} />
              {section.title}
              {section.basis && <span className="svs-tip-basis">{section.basis}</span>}
            </span>
            {figure('Selected', section, row.period, row.pt, row[section.own], section.est ? row[section.est] : null, missingSelected(section))}
            {comparing && figure(
              'Comparison', section, row.comparePeriod, row.cpt, row[section.compared], section.comparedEst ? row[section.comparedEst] : null, missingCompared(section),
            )}
            {comparing && (
              <span className="svs-tip-line svs-tip-change">
                <span>Change</span>
                <strong>{change ? `${section.signed(change.amount)} (${change.pct != null ? signedPct(change.pct) : 'N/A'})` : 'N/A'}</strong>
              </span>
            )}
          </div>
        );
      })}
      {movement && (
        <p className="svs-tip-insight">
          <Info size={14} aria-hidden="true" />
          <span>{MOVEMENT_TEXT[movement]}</span>
        </p>
      )}
      {purchases && row.purch < 0 && <p className="svs-tip-note">{longMonth(row.period)}: a negative estimate, shown as ₱0.</p>}
      {purchases && row.net != null && (
        <p className="svs-tip-note">
          {row.net >= 0
            ? <>Bought <strong className="is-inline">{formatCompactPesos(row.net)}</strong> more than sold → stock grew.</>
            : <>Sold <strong className="is-inline">{formatCompactPesos(-row.net)}</strong> more than bought → stock shrank.</>}
        </p>
      )}
      {purchases && row.purchFlag && <p className="svs-tip-note">Bought in {longMonth(row.period)} is estimated from a stock count that needs checking.</p>}
      {purchases && row.purchFlagC && <p className="svs-tip-note">Bought in {longMonth(row.comparePeriod)} is estimated from a stock count that needs checking.</p>}
      {usesStock && row.flagged && (row.stock != null || row.weeks != null) && stockNote(row.period, row.pt)}
      {usesStock && comparing && row.flaggedC && (row.stockC != null || row.weeksC != null) && stockNote(row.comparePeriod, row.cpt)}
    </div>
  );
};

// Tells the card where the plot's area is, so the strips, the year band and the
// month highlight use the plot's own measurements and can't drift out of line.
const PlotAreaReporter = ({ onChange }) => {
  const area = usePlotArea();
  const x = area?.x;
  const y = area?.y;
  const width = area?.width;
  const height = area?.height;
  useLayoutEffect(() => {
    if (width > 0) onChange({ x, y, width, height });
  }, [x, y, width, height, onChange]);
  return null;
};

// One change strip: a thin bar per visible month around a clearly marked zero
// line, directly under that month on the plot. Up is a rise and down a fall, in
// the metric's own colour: no green or red, since a rise in stock is neither good
// nor bad by itself. A month with no percent has no bar; a change of exactly 0%
// has a flat mark on the line, so the two can't be confused. A bar past the
// strip's limit stops at the edge with an arrow and its real figure beside it. A
// grey dot across the line says the figure rests on a stock count that needs
// checking.
const STRIP_HEIGHT = 48;
const STRIP_REACH = 20;
// A view with one metric: its strip also takes the room of the second row (that
// row's name line and plot), so the panel, and the plot above it, keep their height
// in every view.
const STRIP_SOLO_HEIGHT = 124;
const STRIP_SOLO_REACH = 58;
const SvsChangeStrip = ({ strip, rows, scale, left, width, activeIndex, solo = false }) => {
  const stripHeight = solo ? STRIP_SOLO_HEIGHT : STRIP_HEIGHT;
  const stripReach = solo ? STRIP_SOLO_REACH : STRIP_REACH;
  const band = width / Math.max(rows.length, 1);
  const mid = stripHeight / 2;
  const barWidth = clamp(Math.round(band * 0.26), 5, 12);
  const Icon = strip.icon;
  return (
    <div className="svs-strip">
      <div className="svs-strip-name">
        <span className="svs-strip-icon" aria-hidden="true"><Icon size={12} /></span>
        {strip.label}
        {scale && <span className="svs-strip-range">±{scale.limit}%</span>}
      </div>
      <div className="svs-strip-row">
        <div className="svs-strip-ticks" style={{ width: left, height: stripHeight }} aria-hidden="true">
          {scale && (
            <>
              <span style={{ top: mid - stripReach }}>+{scale.limit}%</span>
              <span style={{ top: mid }}>0%</span>
              <span style={{ top: mid + stripReach }}>−{scale.limit}%</span>
            </>
          )}
        </div>
        <svg
          className="svs-strip-plot"
          width={width}
          height={stripHeight}
          role="img"
          aria-label={`${strip.label}: percentage change for each month shown, around a zero line. The exact figures are in the table view.`}
        >
          <line className="svs-strip-grid" x1={0} x2={width} y1={mid - stripReach} y2={mid - stripReach} />
          <line className="svs-strip-grid" x1={0} x2={width} y1={mid + stripReach} y2={mid + stripReach} />
          {scale && rows.map((row, i) => {
            const pct = row.change?.[strip.key]?.pct;
            if (pct == null) return null;
            const cx = band * (i + 0.5);
            const opacity = activeIndex == null || activeIndex === i ? 1 : 0.72;
            if (pct === 0) {
              return <rect key={row.period} className="svs-strip-zero" x={cx - barWidth / 2 - 2} y={mid - 1.5} width={barWidth + 4} height={3} rx={1} fill={strip.color} opacity={opacity} />;
            }
            const over = Math.abs(pct) > scale.limit;
            const reach = over ? stripReach : Math.max(1.5, (Math.abs(pct) / scale.limit) * stripReach);
            const up = pct > 0;
            const tip = up ? mid - reach : mid + reach;
            const flagged = (strip.flags || []).some((key) => row[key]);
            const overText = `${up ? '+' : '−'}${Math.round(Math.abs(pct))}%`;
            const overWidth = overText.length * 5.4 + 8;
            const pillRight = cx + barWidth / 2 + 4;
            const pillX = pillRight + overWidth > width + 8 ? cx - barWidth / 2 - 4 - overWidth : pillRight;
            const pillY = up ? tip - 1 : tip - 11;
            return (
              <g key={row.period} opacity={opacity}>
                <rect className="svs-strip-bar" x={cx - barWidth / 2} y={up ? tip : mid} width={barWidth} height={reach} rx={1.5} fill={strip.color} />
                {over && (
                  <>
                    <path d={`M${cx - barWidth / 2 - 1} ${tip}L${cx + barWidth / 2 + 1} ${tip}L${cx} ${tip + (up ? -3 : 3)}Z`} fill={strip.color} />
                    <rect className="svs-strip-pill" x={pillX} y={pillY} width={overWidth} height={12} rx={4} />
                    <text className="svs-strip-over" x={pillX + overWidth / 2} y={pillY + 9} textAnchor="middle">{overText}</text>
                  </>
                )}
                {flagged && <circle cx={cx} cy={up ? mid + 5 : mid - 5} r={2.5} fill={UNUSUAL_INK} />}
              </g>
            );
          })}
          <line className="svs-strip-zero-line" x1={0} x2={width} y1={mid} y2={mid} />
        </svg>
      </div>
    </div>
  );
};

// A month on the axis, with no year: the band under the axis carries the year.
// "Previous period" on a range that isn't whole years pairs different months,
// which nothing else can show, so there the compared month sits under it.
const SvsMonthTick = ({ x, y, payload, rowByPeriod, showCompared, fontSize, fill, comparedFill, activePeriod }) => {
  const period = payload?.value;
  if (!period) return null;
  const compared = showCompared ? rowByPeriod.get(period)?.comparePeriod : null;
  const differs = compared && monthName(compared) !== monthName(period);
  const reading = period === activePeriod;
  return (
    <text x={x} y={y} textAnchor="middle" fontSize={fontSize} fill={reading ? '#1F2A3A' : fill}>
      <tspan x={x} dy="0.8em" fontWeight={reading ? 700 : undefined}>{monthName(period)}</tspan>
      {differs && <tspan x={x} dy="1.25em" fill={comparedFill}>{monthName(compared)}</tspan>}
    </text>
  );
};

// Below this width a month's labels and bar crowd, so fewer months show at once.
const MIN_MONTH_PX = 40;
const MAX_MONTHS_SHOWN = 12;
const PLOT_RIGHT_MARGIN = 16;
const X_AXIS_HEIGHT = 24;
const X_AXIS_HEIGHT_TWO_MONTHS = 38;
const MAX_BAR_WIDTH = 28;
const MAX_BAR_WIDTH_PAIRED = 22;
const TIP_WIDTH = 300;
const TIP_TOP = 2;
const TIP_ARROW = 11;
const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
const COMPARE_TEXT = { year: 'Compared with same months last year', previous: 'Compared with previous period' };
const CHANGE_TEXT = { year: 'Change vs same months last year', previous: 'Change vs previous period' };
// What each view draws of the comparison, for "is any of it there?".
const COMPARED_KEYS = {
  both: ['salesC', 'salesestC', 'stockC', 'stockestC'],
  sales: ['salesC', 'salesestC'],
  inventory: ['stockC', 'stockestC'],
  returns: ['returnsC', 'retestC'],
  purchases: ['salesC', 'boughtC'],
  weeks: ['weeksC'],
};

export const SalesVsStockWidget = ({
  data = [], emptyReason, placeholder = null, insight = null, note = null, basis = null, gapNote = null,
  // Which of the months the sentence quotes are synthetic, if any.
  syntheticNote = null,
  // What "Compare with" asks for: { mode, shift, label, floor, points, pending,
  // failed } (Dashboard.jsx), null for "No comparison". `range` is the months
  // this answer is about: { start, end }.
  compare = null, range = null,
  // SSM's rule in weeks (GET /dashboard's inventory.policy_weeks), the dashed
  // line on the "Weeks of stock" view.
  policyWeeks = 3,
}) => {
  const hasData = data.length > 0;
  const comparing = Boolean(compare);
  const shadeId = useLineShadeId();
  const [view, setView] = useState('chart');
  const [metricChoice, setMetricChoice] = useState('both');
  const widgetRef = useRef(null);
  const widgetWidth = useElementWidth(widgetRef);
  const wide = widgetWidth >= YOY_WIDE_PX;
  // A phone: the axes drop their rotated titles.
  const phone = widgetWidth > 0 && widgetWidth < YOY_PHONE_PX;

  // A month is SSM's own figure unless it is a placeholder or synthetic one.
  const real = useCallback((pt) => Boolean(pt) && !pt.salesSynthetic && !isPlaceholderPeriod(pt.period, placeholder), [placeholder]);

  // The selected months, every one kept: the range itself, not only the months
  // with a figure, so a selection is never quietly cut down.
  const filledMonths = useMemo(() => timelineMonths(data, PLOTTED_FIELDS), [data]);
  const months = useMemo(
    () => (range?.start && range?.end ? monthsBetween(range.start, range.end) : filledMonths),
    [range?.start, range?.end, filledMonths],
  );
  const rows = useMemo(() => comparisonRows({
    months,
    points: data,
    comparePoints: compare?.points || [],
    shift: compare?.shift ?? null,
    floor: compare?.floor ?? null,
    isReal: real,
    weeksOf: weeksOfStock,
  }), [months, data, compare?.points, compare?.shift, compare?.floor, real]);

  const firstMonth = months[0];
  const lastMonth = months[months.length - 1];
  const selectedLabel = periodsLabel(firstMonth, lastMonth);
  const comparedLabel = comparing && firstMonth
    ? periodsLabel(monthsEarlier(firstMonth, compare.shift), monthsEarlier(lastMonth, compare.shift))
    : '';

  const has = (key) => rows.some((r) => r[key] != null);
  const hasReceived = data.some((pt) => pt.received != null);
  const hasEstimated = data.some((pt) => pt.receivedEstimated != null);
  const hasReturns = has('returns') || has('retest');
  const hasWeeks = has('weeks');
  const metricViews = [
    ...METRIC_VIEWS,
    ...(hasReceived || hasEstimated ? [PURCHASES_VIEW] : []),
    ...(hasWeeks ? [WEEKS_VIEW] : []),
    ...(hasReturns ? [RETURNS_VIEW] : []),
  ];
  // A view the new range has nothing for falls back to "Both".
  const metricView = metricViews.some(([key]) => key === metricChoice) ? metricChoice : 'both';
  const weeksView = metricView === 'weeks';
  const comboView = metricView === 'both';
  const purchasesView = metricView === 'purchases';
  const inventoryView = metricView === 'inventory';
  const returnsView = metricView === 'returns';
  const salesBars = comboView || metricView === 'sales';
  const drawsStock = comboView || inventoryView;

  const boughtLabel = hasReceived ? 'Bought' : 'Bought (estimated)';
  const flatPesos = (v) => formatExactPesos(v);
  const SECTION = {
    sales: {
      key: 'sales', metric: 'sales', title: 'Sales', basis: basis?.sales ?? null, swatch: 'bar', color: SVS_COLOR.sales, format: flatPesos, signed: signedPesos,
      own: 'sales', est: 'salesest', compared: 'salesC', comparedEst: 'salesestC', change: 'sales',
    },
    stock: {
      key: 'stock', metric: 'stock', title: 'Inventory value', basis: 'last purchase price', swatch: 'line', color: SVS_COLOR.stock, format: flatPesos, signed: signedPesos,
      own: 'stock', est: 'stockest', compared: 'stockC', comparedEst: 'stockestC', change: 'stock',
    },
    returns: {
      key: 'returns', metric: 'returns', title: 'Returns', basis: basis?.returns ?? null, swatch: 'line', color: SVS_COLOR.returns, format: flatPesos, signed: signedPesos,
      own: 'returns', est: 'retest', compared: 'returnsC', comparedEst: 'retestC', change: 'returns',
    },
    weeks: {
      key: 'weeks', metric: 'weeks', title: WEEKS_LABEL, basis: null, swatch: 'bar', color: WEEKS_COMPARE, format: fmtWeeksValue, signed: signedWeeks,
      own: 'weeks', compared: 'weeksC', change: 'weeks',
    },
    sold: {
      key: 'sold', metric: 'sold', title: 'Sold', basis: basis?.sales ?? null, swatch: 'bar', color: SOLD_COLOR, format: flatPesos, signed: signedPesos,
      own: 'sales', compared: 'salesC', change: 'sales',
    },
    bought: {
      key: 'bought', metric: 'bought', title: boughtLabel, basis: null, swatch: 'bar', color: BOUGHT_COLOR, format: flatPesos, signed: signedPesos,
      own: 'bought', compared: 'boughtC', change: 'bought',
    },
  };
  const sections = {
    both: [SECTION.sales, SECTION.stock],
    sales: [SECTION.sales],
    inventory: [SECTION.stock],
    returns: [SECTION.returns],
    weeks: [SECTION.weeks],
    purchases: [SECTION.sold, SECTION.bought],
  }[metricView];

  // The y axis: from ₱0 where there are bars, so a bar's height means what it
  // says; just under the lowest value for a line. Worked out on every selected
  // month and its comparison, so the scale holds still while moving between
  // windows and no mark runs off the plot.
  const yTicks = useMemo(() => {
    const values = (keys) => rows.flatMap((r) => keys.map((k) => r[k]));
    if (weeksView) return weekTicks(values(['weeks', 'weeksC']), policyWeeks);
    if (purchasesView) return zeroPesoTicks(values(['sales', 'bought', 'salesC', 'boughtC']));
    if (comboView) return zeroPesoTicks(values(['sales', 'salesest', 'stock', 'stockest', 'salesC', 'salesestC', 'stockC', 'stockestC']));
    if (salesBars) return zeroPesoTicks(values(['sales', 'salesest', 'salesC', 'salesestC']));
    return pesoTicks(values(inventoryView ? ['stock', 'stockest', 'stockC', 'stockestC'] : ['returns', 'retest', 'returnsC', 'retestC']));
  }, [rows, weeksView, comboView, purchasesView, salesBars, inventoryView, policyWeeks]);
  // "₱ millions" only where the ticks are in millions (returns can run under ₱1M).
  const yTitle = weeksView ? 'Weeks of stock'
    : (yTicks && yTicks[yTicks.length - 1] >= 1e6) ? 'Value (₱ millions)' : 'Value (₱)';

  const marks = useMemo(() => Object.fromEntries(
    [insight?.peak, insight?.low].filter(Boolean).map((m) => [m.period, m.label]),
  ), [insight]);

  // Generated months, on either side of the comparison: named in the legend and
  // the table, drawn apart on the plot.
  const isSyntheticMonth = useCallback((pt) => Boolean(pt) && (
    (pt.sales != null && !real(pt))
    || pt.salesEstimatedKind === 'demonstration' || pt.salesEstimatedKind === 'generated'
    || pt.stockEstimatedKind === 'generated' || pt.returnsEstimatedKind === 'generated'
  ), [real]);
  const synthetic = rows.some((r) => isSyntheticMonth(r.pt) || isSyntheticMonth(r.cpt));
  const filledEstimate = rows.some((r) => [r.pt, r.cpt].some((pt) => pt && (
    pt.salesEstimatedKind === 'filled' || pt.stockEstimatedKind === 'filled' || pt.returnsEstimatedKind === 'filled'
  )));

  // ── The change strips: one per metric in the view.
  const strips = useMemo(() => {
    if (!comparing) return [];
    const stock = { key: 'stock', label: 'Inventory', icon: Layers, color: SVS_COLOR.stock, flags: ['flagged', 'flaggedC'] };
    const sales = { key: 'sales', label: 'Sales', icon: ChartColumn, color: SVS_COLOR.sales };
    const list = {
      both: [sales, stock],
      sales: [sales],
      inventory: [stock],
      returns: [{ key: 'returns', label: 'Returns', icon: RotateCcw, color: SVS_COLOR.returns }],
      weeks: [{ key: 'weeks', label: 'Weeks of stock', icon: Clock, color: WEEKS_COMPARE, flags: ['flagged', 'flaggedC'] }],
      purchases: [
        { key: 'sales', label: 'Sold', icon: ChartColumn, color: SOLD_COLOR },
        { key: 'bought', label: 'Bought', icon: ShoppingCart, color: BOUGHT_COLOR, flags: ['purchFlag', 'purchFlagC'] },
      ],
    }[metricView];
    // The scale reads every selected month, so it holds still between windows.
    return list.map((strip) => ({ ...strip, scale: stripScale(rows.map((r) => r.change?.[strip.key]?.pct)) }));
  }, [comparing, metricView, rows]);
  const comparedKeys = COMPARED_KEYS[metricView] || [];
  const anyChange = comparing && rows.some((r) => strips.some((strip) => r.change?.[strip.key]?.pct != null));
  const missingCompared = comparing ? comparedMonthsMissing(rows, comparedKeys) : [];
  const comparePending = comparing && Boolean(compare.pending);
  const compareFailed = comparing && !compare.pending && Boolean(compare.failed);
  // With no month to compare, the strips give way to one line saying so.
  const showStrips = comparing && !compareFailed && (anyChange || comparePending);
  const anyCompared = comparing && rows.some((r) => comparedKeys.some((key) => r[key] != null));
  const compareMessage = !comparing || comparePending ? null
    : compareFailed ? `Could not load ${comparedLabel} to compare.`
      : anyChange ? null
        : anyCompared ? 'No month has figures in both periods, so there is no change to show.'
          : 'No earlier data available for this comparison.';

  // ── The plot's frame and how many months it shows at once.
  const [frame, setFrame] = useState(null);
  const [frameWidth, setFrameWidth] = useState(0);
  const [plot, setPlot] = useState(null);
  useLayoutEffect(() => {
    if (!frame) return undefined;
    const measure = () => setFrameWidth(frame.getBoundingClientRect().width);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(frame);
    return () => ro.disconnect();
  }, [frame]);
  const yAxisWidth = phone ? 46 : 64;
  const pageSize = frameWidth > 0
    ? clamp(Math.floor((frameWidth - yAxisWidth - PLOT_RIGHT_MARGIN) / MIN_MONTH_PX), 3, MAX_MONTHS_SHOWN)
    : MAX_MONTHS_SHOWN;
  const windows = useMemo(() => monthWindows(rows, pageSize), [rows, pageSize]);
  // Which window is showing: the latest one until someone moves, and again
  // whenever the selected months or the number that fit change.
  const windowKey = `${firstMonth}|${lastMonth}|${pageSize}`;
  const [pageChoice, setPageChoice] = useState({ key: null, page: 0 });
  const lastPage = Math.max(windows.length - 1, 0);
  const page = pageChoice.key === windowKey ? clamp(pageChoice.page, 0, lastPage) : lastPage;
  const visibleRows = useMemo(() => windows[page] || [], [windows, page]);
  const windowLabel = visibleRows.length ? periodsLabel(visibleRows[0].period, visibleRows[visibleRows.length - 1].period) : '';
  const monthsWord = (n) => (n === 1 ? '1 month' : `${n} months`);
  const rowByPeriod = useMemo(() => new Map(visibleRows.map((r) => [r.period, r])), [visibleRows]);

  // Is the comparison on the plot in this window? Its pale marks, the third line
  // on the axis and the legend's second column all follow this.
  const comparedVisibleIn = (viewKey) => comparing
    && (comparePending || visibleRows.some((r) => (COMPARED_KEYS[viewKey] || []).some((key) => r[key] != null)));
  const comparedVisible = comparedVisibleIn(metricView);

  // "Previous period" on a range that isn't whole years pairs different months.
  const monthsDiffer = comparedVisible && visibleRows.some((r) => (
    r.comparePeriod && monthName(r.comparePeriod) !== monthName(r.period)
  ));

  // A view's legend: each metric's group, then its periods by their dates for the
  // months on show. A window of a long range has its own two periods. Every view's
  // is built, because the legend's space is the tallest one's (.svs-legend).
  const legendFor = (viewKey) => {
    const weeks = viewKey === 'weeks';
    const bars = viewKey === 'both' || viewKey === 'sales';
    const stockLine = viewKey === 'both' || viewKey === 'inventory';
    const comparedOn = comparedVisibleIn(viewKey);
    const entry = (kind, color, text) => ({ kind, color, text });
    const lastShown = visibleRows[visibleRows.length - 1];
    const shownLabel = lastShown ? periodsLabel(visibleRows[0].period, lastShown.period) : '';
    const comparedShown = lastShown?.comparePeriod
      ? `${periodsLabel(visibleRows[0].comparePeriod, lastShown.comparePeriod)}${comparePending ? ' · loading…' : ''}`
      : '';
    const drawn = (...keys) => visibleRows.some((r) => keys.some((key) => r[key] != null));
    const metrics = [];
    if (viewKey === 'purchases') {
      metrics.push(
        ['Sold', 'bar', SOLD_COLOR, 'bar', COMPARE_COLOR.sales, drawn('salesC')],
        [boughtLabel, 'bar', BOUGHT_COLOR, 'bar', COMPARE_COLOR.bought, drawn('boughtC')],
      );
    } else if (!weeks) {
      if (bars) metrics.push(['Sales', 'bar', SVS_COLOR.sales, 'bar', COMPARE_COLOR.sales, drawn('salesC', 'salesestC')]);
      if (stockLine) metrics.push(['Inventory value', 'line', SVS_COLOR.stock, 'dash', COMPARE_COLOR.stock, drawn('stockC', 'stockestC')]);
      if (viewKey === 'returns') metrics.push(['Returns', 'line', SVS_COLOR.returns, 'dash', COMPARE_COLOR.returns, drawn('returnsC', 'retestC')]);
    }
    const out = [];
    if (weeks) {
      out.push({
        label: null,
        items: [
          entry('bar', WEEKS_UNDER, `Under SSM's ${policyWeeks}-week rule`),
          entry('bar', WEEKS_NEAR, `Near the rule (${policyWeeks - WEEKS_NEAR_BAND}–${policyWeeks + WEEKS_NEAR_BAND} wks)`),
          entry('bar', WEEKS_OVER, 'Over the rule'),
          entry('dash', '#344054', `SSM's ${policyWeeks}-week rule`),
          ...(comparedOn ? [entry('bar', COMPARE_COLOR.weeks, comparedShown)] : []),
        ],
      });
    } else if (comparedOn) {
      metrics.forEach(([label, kind, color, comparedKind, comparedColor, comparedDrawn]) => {
        out.push({
          label,
          items: [entry(kind, color, shownLabel), ...(comparedDrawn ? [entry(comparedKind, comparedColor, comparedShown)] : [])],
        });
      });
    } else {
      out.push({ label: null, items: metrics.map(([label, kind, color]) => entry(kind, color, label)) });
    }
    const notes = [];
    const flaggedOnShow = (stockLine || weeks) && visibleRows.some((r) => (
      (r.flagged && (weeks ? r.weeks != null : r.stock != null))
      || (r.flaggedC && (weeks ? r.weeksC != null : r.stockC != null))
    ));
    if (flaggedOnShow) notes.push(entry(weeks ? 'outline' : 'dot', weeks ? '#475467' : UNUSUAL_INK, 'Stock count needs checking'));
    if (visibleRows.some((r) => isSyntheticMonth(r.pt) || isSyntheticMonth(r.cpt))) {
      notes.push(entry('hatch', bars ? SVS_COLOR.sales : UNUSUAL_INK, 'Synthetic data'));
    }
    if (filledEstimate) notes.push(entry('dotted', UNUSUAL_INK, ESTIMATE_KIND_TEXT.filled));
    if (notes.length) out.push({ label: null, items: notes });
    return out;
  };
  const yearGroups = yearGroupsOf(visibleRows.map((r) => r.period));

  // ── The month being read: one index for the plot, the strips and the hover,
  // from a mouse, a tap or the arrow keys.
  const [activeIndex, setActiveIndex] = useState(null);
  const activeRow = activeIndex != null ? visibleRows[activeIndex] ?? null : null;
  const goToPage = (next, index = null) => {
    setPageChoice({ key: windowKey, page: next });
    setActiveIndex(index);
  };
  const monthAt = (clientX) => {
    if (!frame || !plot || !visibleRows.length) return null;
    const x = clientX - frame.getBoundingClientRect().left - plot.x;
    if (x < 0 || x >= plot.width) return null;
    return Math.min(visibleRows.length - 1, Math.floor(x / (plot.width / visibleRows.length)));
  };
  const onFramePointerMove = (event) => {
    if (event.pointerType === 'mouse') setActiveIndex(monthAt(event.clientX));
  };
  const onFramePointerLeave = (event) => {
    if (event.pointerType === 'mouse') setActiveIndex(null);
  };
  // A tap reads the month under it, and a second tap on it closes. A swipe that
  // scrolls the page ends in pointercancel, not here.
  const onFramePointerUp = (event) => {
    if (event.pointerType === 'mouse') return;
    const at = monthAt(event.clientX);
    setActiveIndex((current) => (current === at ? null : at));
  };
  const onFrameKeyDown = (event) => {
    if (event.key === 'Escape') {
      setActiveIndex(null);
      return;
    }
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    event.preventDefault();
    const last = visibleRows.length - 1;
    const forward = event.key === 'ArrowRight';
    const next = activeIndex == null ? (forward ? 0 : last) : activeIndex + (forward ? 1 : -1);
    if (next > last) {
      if (page < lastPage) goToPage(page + 1, 0);
    } else if (next < 0) {
      if (page > 0) goToPage(page - 1, windows[page - 1].length - 1);
    } else {
      setActiveIndex(next);
    }
  };
  // Tapping anywhere else closes the month.
  useEffect(() => {
    if (activeIndex == null || !frame) return undefined;
    const close = (event) => {
      if (!frame.contains(event.target)) setActiveIndex(null);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [activeIndex, frame]);

  // The hover opens on the side of the month with more room.
  const monthBand = plot ? plot.width / Math.max(visibleRows.length, 1) : 0;
  const activeX = plot && activeIndex != null ? plot.x + monthBand * (activeIndex + 0.5) : 0;
  const tipSide = activeX <= frameWidth / 2 ? 'right' : 'left';
  const tipPlace = tipSide === 'right'
    ? { left: Math.max(0, Math.min(activeX + 14, frameWidth - TIP_WIDTH)) }
    : { right: Math.max(0, Math.min(frameWidth - activeX + 14, frameWidth - TIP_WIDTH)) };
  // Where the card's pointer aims: the month's inventory point, or in a view
  // without one, its first figure. The stylesheet keeps it on the card.
  const tipArrowTop = (() => {
    if (!activeRow || !plot || !yTicks) return null;
    const anchor = sections.find((s) => s.metric === 'stock') ?? sections[0];
    const value = activeRow[anchor.own] ?? (anchor.est ? activeRow[anchor.est] : null);
    const low = yTicks[0];
    const high = yTicks[yTicks.length - 1];
    if (value == null || high <= low) return null;
    const pointY = plot.y + plot.height * (1 - (value - low) / (high - low));
    return Math.max(14, pointY - TIP_TOP - TIP_ARROW / 2);
  })();
  // The other months step back a little while one is read.
  const emphasis = (i) => (activeIndex == null || activeIndex === i ? 1 : 0.82);

  // A line's markers, kept few: a stock count that needs checking (grey), the
  // month being read, the solid line's last month, and a month with no
  // neighbour on its line, which has no line to draw (Del Monte's single
  // months). The months are read on the frame, not by Recharts, so the hover
  // dot is drawn here.
  const FLAG_OF = { stock: 'flagged', stockC: 'flaggedC' };
  const lineDot = (key, color, compared) => {
    const last = compared ? -1 : visibleRows.reduce((found, r, i) => (r[key] != null ? i : found), -1);
    return (props) => {
      const { cx, cy, index } = props;
      const r = visibleRows[index];
      if (cx == null || cy == null || r?.[key] == null) return null;
      const reading = index === activeIndex;
      if (FLAG_OF[key] && r[FLAG_OF[key]]) {
        return (
          <g key={`u-${index}`}>
            {reading && <circle cx={cx} cy={cy} r={9} fill={UNUSUAL_INK} fillOpacity={0.16} />}
            <circle cx={cx} cy={cy} r={reading ? 5 : 4} fill={UNUSUAL_INK} stroke="var(--color-surface, #fff)" strokeWidth={1.5} />
          </g>
        );
      }
      if (reading) return <g key={`a-${index}`}>{lineHoverDot({ cx, cy, fill: color })}</g>;
      if (index !== last && (visibleRows[index - 1]?.[key] != null || visibleRows[index + 1]?.[key] != null)) return null;
      return endDot(color, index)(props);
    };
  };
  const line = (key, color, { estimate = false, compared = false, dash = null } = {}) => (
    <Line
      key={key}
      {...(estimate || compared ? COMPARISON_LINE : SOLID_LINE)}
      dataKey={estimate ? `${key}Line` : key}
      name={key}
      stroke={color}
      strokeDasharray={dash || (estimate ? ESTIMATED_DASH : compared ? COMPARE_DASH : undefined)}
      strokeOpacity={estimate ? ESTIMATED_OPACITY : 1}
      dot={estimate ? false : lineDot(key, color, compared)}
      activeDot={false}
      connectNulls={false}
      isAnimationActive={false}
    />
  );
  // The shade under the solid line. An Area of its own: the line stays a Line,
  // on top of the bars, and the shade goes behind them.
  const shade = (key) => (
    <Area
      key={`${key}-shade`}
      {...SHADE_ONLY}
      dataKey={key}
      name={`${key}shade`}
      fill={`url(#${shadeId}-${key})`}
      connectNulls={false}
    />
  );

  // The table: the same rows as the chart, so the two can't disagree, with the
  // columns of the metric in view. Every selected month, whichever window the
  // chart is on, and every peso figure in full.
  const hasCountDays = drawsStock && data.some((pt) => pt.stockCountDay);
  const noteFor = (period, pt) => `${plainPeriod(period)}: ${pt?.stockUnusual || 'Reason not recorded'}`;
  const tableRows = useMemo(() => rows.map((r) => {
    const cells = {};
    Object.values(SECTION).forEach((s) => {
      cells[`${s.key}_own`] = r[s.own] ?? (s.est ? r[s.est] : null) ?? null;
      cells[`${s.key}_cmp`] = r[s.compared] ?? (s.comparedEst ? r[s.comparedEst] : null) ?? null;
      cells[`${s.key}_amt`] = r.change?.[s.change]?.amount ?? null;
      cells[`${s.key}_pct`] = r.change?.[s.change]?.pct ?? null;
    });
    const notes = [
      r.flagged && (r.stock != null || r.weeks != null) && noteFor(r.period, r.pt),
      r.flaggedC && (r.stockC != null || r.weeksC != null) && noteFor(r.comparePeriod, r.cpt),
    ].filter(Boolean);
    const selectedSynthetic = isSyntheticMonth(r.pt);
    const comparedSynthetic = isSyntheticMonth(r.cpt);
    return {
      ...r,
      ...cells,
      stockCountDay: r.pt?.stockCountDay ?? null,
      qualityNote: notes.length ? notes.join(' ') : null,
      syntheticStatus: selectedSynthetic && comparedSynthetic ? 'Selected and comparison'
        : selectedSynthetic ? 'Selected' : comparedSynthetic ? 'Comparison' : null,
    };
    // SECTION is rebuilt each render from the values listed here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [rows, isSyntheticMonth, boughtLabel]);
  const sectionColumns = (s) => {
    const { label: name, sub } = {
      sales: { label: 'Sales', sub: basis?.sales ?? null },
      stock: { label: 'Inventory value', sub: 'at last purchase price' },
      returns: { label: 'Returns', sub: basis?.returns ?? null },
      weeks: { label: WEEKS_LABEL, sub: 'stock ÷ weekly sales' },
      sold: { label: 'Sold', sub: basis?.sales ?? null },
      bought: { label: boughtLabel, sub: hasReceived ? 'purchases received' : 'from stock counts and sales' },
    }[s.key];
    const unit = s.key === 'weeks' ? 'wks' : '₱';
    const ownFormat = s.key === 'bought' ? (v, row) => (row.purch < 0 ? '₱0 (negative estimate)' : s.format(v)) : s.format;
    const comparedFormat = s.key === 'bought' ? (v, row) => (row.purchC < 0 ? '₱0 (negative estimate)' : s.format(v)) : s.format;
    return [
      { key: `${s.key}_own`, label: `${name} (${unit})`, sub, format: ownFormat },
      ...(comparing
        ? [
            { key: `${s.key}_cmp`, label: `Comparison ${name.toLowerCase()} (${unit})`, format: comparedFormat },
            { key: `${s.key}_amt`, label: `${name} change (${unit})`, format: s.signed },
            { key: `${s.key}_pct`, label: `${name} change (%)`, format: signedPct },
          ]
        : []),
    ];
  };
  const tableColumns = [
    { key: 'period', label: comparing ? 'Selected month' : 'Month', format: (v) => plainPeriod(v), align: 'left' },
    ...(comparing ? [{ key: 'comparePeriod', label: 'Comparison month', format: (v) => plainPeriod(v), align: 'left' }] : []),
    ...sections.flatMap(sectionColumns),
    ...(hasCountDays
      ? [{
          key: 'stockCountDay',
          label: (
            <>
              Stock counted on
              <InfoTip label="About stock count dates" size={11}>
                A count on the 1st of a month is the stock at the end of the previous month.
              </InfoTip>
            </>
          ),
          format: (v) => v,
          align: 'left',
        }]
      : []),
    ...(tableRows.some((r) => r.qualityNote && (drawsStock || weeksView))
      ? [{
          key: 'qualityNote',
          label: 'Data quality',
          align: 'left',
          note: { lead: 'Stock count needs checking', title: (row) => `Stock count, ${plainPeriod(row.period)}` },
        }]
      : []),
    ...(tableRows.some((r) => r.syntheticStatus)
      ? [{ key: 'syntheticStatus', label: 'Synthetic data', align: 'left' }]
      : []),
  ];

  const yAxisProps = {
    axisLine: false,
    tickLine: false,
    width: yAxisWidth,
    tick: { fontSize: 11, fill: '#667085' },
    tickFormatter: (v) => (weeksView ? `${v} wks` : formatCompactPesos(v)),
    label: phone ? undefined : yAxisTitle(yTitle),
    domain: yTicks ? [yTicks[0], yTicks[yTicks.length - 1]] : [0, 'auto'],
    ticks: yTicks ?? undefined,
  };
  const flaggedOutlines = visibleRows.filter((r) => r.purchFlag).map((r) => plainPeriod(r.period));

  return (
    <div className={`chart-widget chart-widget-svs${hasData ? '' : ' chart-widget-empty'}${phone ? ' is-narrow' : ''}`} ref={widgetRef}>
      <div className="chart-header">
        <div className="chart-title-area svs-head">
          <span className="svs-head-icon" aria-hidden="true"><Box size={18} /></span>
          <div className="svs-head-text">
            <h4>
              <span>Sales vs Inventory Value (₱)</span>
              <InfoTip label="About Sales vs Inventory Value" size={13}>
                {purchasesView && (
                  <span className="chart-tip-line">
                    Sold against bought each month: when the bought bar is taller, more stock came in than went out.{' '}
                    {hasReceived
                      ? 'Bought is SSM\'s purchase records (purchases received).'
                      : 'Bought is estimated from stock counts and sales, not from SSM\'s purchase records.'}
                  </span>
                )}
                {weeksView && (
                  <span className="chart-tip-line">
                    How many weeks the stock would last: each month&apos;s stock value ÷ that month&apos;s average weekly
                    sales (monthly sales ÷ {WEEKS_PER_MONTH.toFixed(2)} weeks). It uses that month&apos;s own sales, so it
                    moves more than the Summary card&apos;s stock cover, which averages 12 months. Only months with both a
                    real stock count and real sales have a bar.
                  </span>
                )}
                {salesBars && (
                  <span className="chart-tip-line">
                    {comparedVisible
                      ? 'The dark bars are sales in the selected months. The lighter bar beside each is its comparison month.'
                      : 'Bars show sales for the selected months.'}
                  </span>
                )}
                {drawsStock && (
                  <span className="chart-tip-line">
                    {comparedVisible
                      ? 'The solid line is inventory value in the selected months. The dashed line is the comparison months.'
                      : 'The line shows inventory value for the selected months.'}
                  </span>
                )}
                {comparing && (
                  <span className="chart-tip-line">
                    The panel below shows each month&apos;s percentage change against its comparison month: above the zero
                    line is a rise, below is a fall. A bar with an arrow runs past the scale, with its figure beside it.
                  </span>
                )}
                <span className="chart-tip-line">
                  {comparing ? 'Hover or tap a month for its exact figures and changes.' : 'Hover or tap a month for its exact figures.'}
                  {comboView && ' Sales and inventory use different price bases, so compare their patterns, not their amounts.'}
                </span>
              </InfoTip>
            </h4>
            <SectionLede>{comparing ? 'Monthly performance and period comparison' : 'Monthly performance'}</SectionLede>
            {/* GET /dashboard's vat_note — only under All principals, where the
                combined pesos mix Unilever's VAT-inclusive amounts with Del
                Monte's VAT-exclusive ones. */}
            {note && <p className="keep-visible">{note}</p>}
            {/* No composed summary sentence (2026-10-28, Audrey: figures
                only, no written-out readings). The synthetic-data label
                stays: it says what the data is. */}
            {syntheticNote && <p className="chart-insight chart-insight-synthetic">{syntheticNote}</p>}
          </div>
        </div>
        {hasData && (
          <div className="chart-header-controls">
            <div className="chart-view-toggle" role="group" aria-label="Metrics shown">
              {metricViews.map(([key, text]) => (
                <button
                  key={key}
                  type="button"
                  className={metricView === key ? 'active' : ''}
                  aria-pressed={metricView === key}
                  onClick={() => setMetricChoice(key)}
                >
                  {text}
                </button>
              ))}
            </div>
            <ChartViewToggle view={view} onChange={setView} label="Sales vs inventory value: chart or table" />
          </div>
        )}
      </div>

      {selectedLabel && (
        <div className="svs-period-row">
          <CalendarDays size={16} aria-hidden="true" />
          <div>
            <div className="svs-period">{selectedLabel}</div>
            {comparing && (
              <div className="svs-compared">
                {COMPARE_TEXT[compare.mode] || 'Compared with an earlier period'}
                {comparedLabel && ` · ${comparedLabel}`}
              </div>
            )}
          </div>
        </div>
      )}

      {!hasData || !filledMonths.length ? (
        <p className="dashboard-empty-note">{emptyReason || 'No data available for this range'}</p>
      ) : view === 'table' ? (
        <div className={`yoy-body is-table${tableRows.length >= 10 ? ' is-filled' : ''}`}>
          <ChartTable
            columns={tableColumns}
            rows={tableRows}
            caption={`Sales versus inventory value by month, in pesos (₱): ${selectedLabel}${comparing ? `, ${(COMPARE_TEXT[compare.mode] || '').toLowerCase()}` : ''}`}
          />
        </div>
      ) : (
        <div className="yoy-body">
          <div className="svs-legend">
            {metricViews.map(([key]) => (
              <div key={key} className={`svs-legend-flow${key === metricView ? '' : ' svs-spacer'}`}>
                {legendFor(key).map((group, i) => (
                  <ul key={group.label || i} className="custom-legend svs-legend-group">
                    {group.label && <li className="svs-legend-label">{group.label}</li>}
                    {group.items.map((item) => (
                      <li key={item.text} className="legend-item">
                        <SvsSwatch kind={item.kind} color={item.color} />
                        {item.text}
                      </li>
                    ))}
                  </ul>
                ))}
              </div>
            ))}
          </div>
          <div
            className="svs-plot-frame"
            ref={setFrame}
            tabIndex={0}
            role="group"
            aria-label={`Sales vs inventory value, ${windowLabel}. Use the left and right arrow keys to read each month, and Escape to close.`}
            onPointerMove={onFramePointerMove}
            onPointerLeave={onFramePointerLeave}
            onPointerUp={onFramePointerUp}
            onKeyDown={onFrameKeyDown}
            onBlur={() => setActiveIndex(null)}
          >
            <div className="chart-container chart-container-yoy svs-plot">
              <ResponsiveContainer width="99%" height="100%">
                <ComposedChart
                  data={visibleRows}
                  margin={{ top: 10, right: PLOT_RIGHT_MARGIN, left: 0, bottom: 0 }}
                  barCategoryGap={comparedVisible ? '22%' : purchasesView ? '22%' : '34%'}
                  barGap={comparedVisible ? 3 : purchasesView ? 3 : undefined}
                  accessibilityLayer={false}
                >
                  <PlotAreaReporter onChange={setPlot} />
                  <defs>
                    <LineShade id={`${shadeId}-stock`} color={SVS_COLOR.stock} />
                    <LineShade id={`${shadeId}-returns`} color={SVS_COLOR.returns} />
                    <pattern id="svs-hatch-sales" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                      <rect width="6" height="6" fill={SVS_COLOR.sales} fillOpacity="0.35" />
                      <rect width="2.5" height="6" fill={SVS_COLOR.sales} />
                    </pattern>
                    <pattern id="svs-hatch-compare" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                      <rect width="6" height="6" fill={COMPARE_COLOR.sales} fillOpacity="0.45" />
                      <rect width="2.5" height="6" fill={COMPARE_COLOR.sales} />
                    </pattern>
                  </defs>
                  {/* Horizontal gridlines only (GRID_PROPS): a value is read
                      across, a month is read down from its label. */}
                  <CartesianGrid {...GRID_PROPS} stroke="#EDF0F4" />
                  {/* scale="band": a view with no bars would otherwise run its months from
                      edge to edge, out of line with the panel and the highlight. */}
                  <XAxis
                    dataKey="period"
                    scale="band"
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={monthName}
                    interval={0}
                    tick={(
                      <SvsMonthTick
                        rowByPeriod={rowByPeriod}
                        showCompared={comparedVisible}
                        fontSize={wide ? 12 : 11}
                        fill="#475467"
                        comparedFill="var(--color-text-subtle, #8792A2)"
                        activePeriod={activeRow?.period}
                      />
                    )}
                    height={monthsDiffer ? X_AXIS_HEIGHT_TWO_MONTHS : X_AXIS_HEIGHT}
                  />
                  <YAxis {...yAxisProps} />
                  {weeksView && policyWeeks != null && (
                    <ReferenceLine
                      y={policyWeeks}
                      stroke="#344054"
                      strokeDasharray="5 4"
                      ifOverflow="extendDomain"
                      label={{
                        value: `SSM's ${policyWeeks}-week rule`,
                        position: 'insideTopRight',
                        offset: 8,
                        fill: '#344054',
                        fontSize: 11,
                        fontWeight: 600,
                      }}
                    />
                  )}
                  {purchasesView && comparedVisible && (
                    <Bar dataKey="salesC" name="soldC" radius={[3, 3, 0, 0]} maxBarSize={12} isAnimationActive={false}>
                      {visibleRows.map((r, i) => <Cell key={r.period} fill={COMPARE_COLOR.sales} fillOpacity={emphasis(i)} />)}
                    </Bar>
                  )}
                  {purchasesView && (
                    <Bar dataKey="sales" name="sold" radius={[3, 3, 0, 0]} maxBarSize={comparedVisible ? 12 : 18} isAnimationActive={false}>
                      {visibleRows.map((r, i) => <Cell key={r.period} fill={SOLD_COLOR} fillOpacity={emphasis(i)} />)}
                    </Bar>
                  )}
                  {purchasesView && comparedVisible && (
                    <Bar dataKey="boughtC" name="boughtC" radius={[3, 3, 0, 0]} maxBarSize={12} isAnimationActive={false}>
                      {visibleRows.map((r, i) => (r.purchFlagC
                        ? <Cell key={r.period} fill="#fff" fillOpacity={0} stroke={COMPARE_COLOR.stock} strokeWidth={1.5} strokeDasharray="4 3" />
                        : <Cell key={r.period} fill={COMPARE_COLOR.bought} fillOpacity={emphasis(i)} />))}
                    </Bar>
                  )}
                  {purchasesView && (
                    <Bar dataKey="bought" name="bought" radius={[3, 3, 0, 0]} maxBarSize={comparedVisible ? 12 : 18} isAnimationActive={false}>
                      {visibleRows.map((r, i) => (r.purchFlag
                        ? <Cell key={r.period} fill="#fff" fillOpacity={0} stroke={BOUGHT_COLOR} strokeWidth={1.75} strokeDasharray="4 3" />
                        : <Cell key={r.period} fill={BOUGHT_COLOR} fillOpacity={emphasis(i)} />))}
                    </Bar>
                  )}
                  {/* Each month's pair, the earlier period on the left. Each stack
                      holds one figure for its month, so two periods are never added. */}
                  {salesBars && comparedVisible && (
                    <Bar
                      dataKey="salesC"
                      name="salesC"
                      stackId="compared"
                      radius={[3, 3, 0, 0]}
                      maxBarSize={MAX_BAR_WIDTH_PAIRED}
                      minPointSize={(_, i) => (visibleRows[i]?.salesC === 0 ? 2 : 0)}
                      isAnimationActive={false}
                    >
                      {visibleRows.map((r, i) => <Cell key={r.period} fill={COMPARE_COLOR.sales} fillOpacity={emphasis(i)} />)}
                    </Bar>
                  )}
                  {salesBars && comparedVisible && visibleRows.some((r) => r.salesestC != null) && (
                    <Bar
                      dataKey="salesestC"
                      name="salesestC"
                      stackId="compared"
                      fill="url(#svs-hatch-compare)"
                      stroke={COMPARE_COLOR.sales}
                      strokeWidth={1}
                      radius={[3, 3, 0, 0]}
                      maxBarSize={MAX_BAR_WIDTH_PAIRED}
                      isAnimationActive={false}
                    />
                  )}
                  {salesBars && (
                    <Bar
                      dataKey="sales"
                      name="sales"
                      stackId="sales"
                      radius={[3, 3, 0, 0]}
                      maxBarSize={comparedVisible ? MAX_BAR_WIDTH_PAIRED : MAX_BAR_WIDTH}
                      minPointSize={(_, i) => (visibleRows[i]?.sales === 0 ? 2 : 0)}
                      isAnimationActive={false}
                    >
                      {visibleRows.map((r, i) => <Cell key={r.period} fill={SVS_COLOR.sales} fillOpacity={emphasis(i)} />)}
                    </Bar>
                  )}
                  {salesBars && visibleRows.some((r) => r.salesest != null) && (
                    <Bar
                      dataKey="salesest"
                      name="salesest"
                      stackId="sales"
                      fill="url(#svs-hatch-sales)"
                      stroke={SVS_COLOR.sales}
                      strokeWidth={1}
                      radius={[3, 3, 0, 0]}
                      maxBarSize={comparedVisible ? MAX_BAR_WIDTH_PAIRED : MAX_BAR_WIDTH}
                      isAnimationActive={false}
                    />
                  )}
                  {weeksView && comparedVisible && (
                    <Bar dataKey="weeksC" name="weeksC" radius={[3, 3, 0, 0]} maxBarSize={MAX_BAR_WIDTH_PAIRED} isAnimationActive={false}>
                      {visibleRows.map((r, i) => (r.flaggedC
                        ? <Cell key={r.period} fill="#fff" fillOpacity={0} stroke="#94A3B8" strokeWidth={1.5} />
                        : <Cell key={r.period} fill={COMPARE_COLOR.weeks} fillOpacity={emphasis(i)} />))}
                    </Bar>
                  )}
                  {weeksView && (
                    <Bar dataKey="weeks" name="weeks" radius={[3, 3, 0, 0]} maxBarSize={comparedVisible ? MAX_BAR_WIDTH_PAIRED : MAX_BAR_WIDTH} isAnimationActive={false}>
                      {visibleRows.map((r, i) => {
                        const band = weeksBand(r.weeks, policyWeeks);
                        return r.flagged
                          ? <Cell key={r.period} fill="#fff" fillOpacity={0} stroke={WEEKS_COLOR[band]} strokeWidth={1.75} />
                          : <Cell key={r.period} fill={WEEKS_COLOR[band]} fillOpacity={emphasis(i)} />;
                      })}
                    </Bar>
                  )}
                  {drawsStock && shade('stock')}
                  {returnsView && shade('returns')}
                  {/* The comparison first, so the selected months' line is on top. */}
                  {drawsStock && comparedVisible && line('stockC', COMPARE_COLOR.stock, { compared: true })}
                  {drawsStock && comparedVisible && visibleRows.some((r) => r.stockestC != null) && line('stockestC', COMPARE_COLOR.stock, { compared: true, dash: ESTIMATED_DASH })}
                  {drawsStock && line('stock', SVS_COLOR.stock)}
                  {drawsStock && visibleRows.some((r) => r.stockest != null) && line('stockest', SVS_COLOR.stock, { estimate: true })}
                  {returnsView && comparedVisible && line('returnsC', COMPARE_COLOR.returns, { compared: true })}
                  {returnsView && comparedVisible && visibleRows.some((r) => r.retestC != null) && line('retestC', COMPARE_COLOR.returns, { compared: true, dash: ESTIMATED_DASH })}
                  {returnsView && line('returns', SVS_COLOR.returns)}
                  {returnsView && visibleRows.some((r) => r.retest != null) && line('retest', SVS_COLOR.returns, { estimate: true })}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            {/* The year each month belongs to, as one quiet band per year. */}
            {plot && (
              <div className="svs-year-band" style={{ marginLeft: plot.x, width: plot.width }} aria-hidden="true">
                {yearGroups.map((group) => (
                  <span key={group.year} style={{ flexGrow: group.months }}>{group.year}</span>
                ))}
              </div>
            )}
            {/* The month being read, through the plot. */}
            {activeRow && plot && (
              <span
                className="svs-month-highlight"
                style={{
                  left: plot.x + monthBand * activeIndex,
                  width: monthBand,
                  top: plot.y,
                  height: plot.height + (monthsDiffer ? X_AXIS_HEIGHT_TWO_MONTHS : X_AXIS_HEIGHT),
                }}
                aria-hidden="true"
              />
            )}
            {showStrips && (
              <div className="svs-strips">
                <div className="svs-strips-head">
                  <span className="svs-strips-title">{CHANGE_TEXT[compare.mode] || 'Change vs comparison period'}</span>
                  {comparePending && <span className="svs-strips-note">Loading {comparedLabel}…</span>}
                  {!comparePending && missingCompared.length > 0 && (
                    <span className="svs-strips-note">No earlier data for {monthRuns(missingCompared)}</span>
                  )}
                </div>
                {plot && (
                  <div className="svs-strips-body">
                    {/* The same month, through the strips. */}
                    {activeRow && (
                      <span className="svs-month-highlight" style={{ left: plot.x + monthBand * activeIndex, width: monthBand, top: 0, bottom: 0 }} aria-hidden="true" />
                    )}
                    {strips.map((strip) => (
                      <SvsChangeStrip
                        key={strip.label}
                        strip={strip}
                        rows={visibleRows}
                        scale={strip.scale}
                        left={plot.x}
                        width={plot.width}
                        activeIndex={activeIndex}
                        solo={strips.length === 1}
                      />
                    ))}
                    <div className="svs-strip-months" style={{ marginLeft: plot.x, width: plot.width }} aria-hidden="true">
                      {visibleRows.map((r, i) => <span key={r.period} className={i === activeIndex ? 'is-active' : undefined}>{monthName(r.period)}</span>)}
                    </div>
                  </div>
                )}
              </div>
            )}
            {compareMessage && <p className="svs-compare-note" role="note">{compareMessage}</p>}
            {activeRow && (
              <SvsTooltip
                row={activeRow}
                comparing={comparing}
                pending={comparePending}
                sections={sections}
                marks={marks}
                purchases={purchasesView}
                side={tipSide}
                style={tipPlace}
                arrowTop={tipArrowTop}
              />
            )}
          </div>
          {windows.length > 1 && (
            <div className="svs-window-nav" role="group" aria-label="Months shown">
              <span className="svs-window-label" aria-live="polite">Viewing {windowLabel}</span>
              <span className="svs-window-buttons">
                <button type="button" disabled={page === 0} onClick={() => goToPage(page - 1)}>
                  <ChevronLeft size={14} aria-hidden="true" />
                  Previous {monthsWord(page === 0 ? pageSize : windows[page - 1].length)}
                </button>
                <button type="button" disabled={page === lastPage} onClick={() => goToPage(page + 1)}>
                  Next {monthsWord(page === lastPage ? pageSize : windows[page + 1].length)}
                  <ChevronRight size={14} aria-hidden="true" />
                </button>
              </span>
            </div>
          )}
          {/* The notes sit inside the body, whose height is fixed (.yoy-body):
              the plot gives way to them. The two that depend on the view share
              one slot, as tall as the taller, so the plot stays put when a view
              has the other one or neither. With synthetic data on, the notes are
              about SSM's own figures: say what the hatched bars and dotted lines
              are first. */}
          <div className="svs-note-slot">
            {synthetic && (
              <p className={`gap-note${purchasesView ? ' svs-spacer' : ''}`} role="note">
                <strong>Synthetic.</strong> Months SSM has no figures for are filled with generated figures (hatched bars,
                dotted lines), because synthetic data is on. The solid bars and lines are SSM&apos;s own data, and the notes
                below are about them.
              </p>
            )}
            {flaggedOutlines.length > 0 && (
              <p className={`gap-note${purchasesView ? '' : ' svs-spacer'}`} role="note">
                {flaggedOutlines.join(' and ')} &ldquo;bought&rdquo; {flaggedOutlines.length === 1 ? 'is' : 'are'} outlined:{' '}
                {flaggedOutlines.length === 1 ? 'it comes' : 'they come'} from the stock count that needs checking.
              </p>
            )}
          </div>
          {/* What the empty months mean (GET /dashboard's gap_note). */}
          <GapNote note={gapNote} />
        </div>
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
const DEL_MONTE_TIER_ROLE = 'Del Monte has no SKU-level sales, so no class here is forecast or reordered.';

// The ring is plain SVG so each segment can be a real keyboard button. Same
// layout the Recharts ring had: it starts at 3 o'clock, runs
// counter-clockwise, with a hairline gap between tiers (the mockup's ring
// has none to speak of; the three plums tell the tiers apart). The outer
// radius stops 2px short of the box, which leaves room for the selected
// tier's 2px stroke. A tier at least ABC_LABEL_MIN_SWEEP degrees wide
// carries its share on its band (2026-10-19).
const ABC_DONUT_SIZE = 200;
const ABC_RING_OUTER = 98;
const ABC_RING_INNER = 66;
const ABC_PAD_ANGLE = 1;
const ABC_LABEL_MIN_SWEEP = 16;
// Each principal's tier shares add up to 100% of that principal's revenue.
// Further off than this and they were summed across principals, so they are
// not a share of any revenue this card could name.
const ABC_SHARE_SUM_TOLERANCE = 2;
const ABC_TOOLTIP_GAP = 12;
const ABC_VIEWPORT_MARGIN = 4;

const abcXY = (radius, degrees) => {
  const angle = (degrees * Math.PI) / 180;
  const centre = ABC_DONUT_SIZE / 2;
  return { x: centre + radius * Math.cos(angle), y: centre - radius * Math.sin(angle) };
};
const abcPoint = (radius, degrees) => {
  const { x, y } = abcXY(radius, degrees);
  return `${x.toFixed(2)} ${y.toFixed(2)}`;
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
// sized it (shares relative to their own sum, minus the gaps), with the spot
// for its label at the middle of its band when the band is wide enough.
const abcSegments = (data) => {
  const values = data.map((d) => (Number.isFinite(d.sharePct) && d.sharePct > 0 ? d.sharePct : 0));
  const sum = values.reduce((acc, v) => acc + v, 0);
  const available = 360 - ABC_PAD_ANGLE * values.filter((v) => v > 0).length;
  let angle = 0;
  return data.map((d, i) => {
    const sweep = sum > 0 ? (values[i] / sum) * available : 0;
    const segment = {
      tier: d.tier,
      value: values[i],
      path: sweep > 0 ? abcArc(angle, angle + sweep) : null,
      label: sweep >= ABC_LABEL_MIN_SWEEP ? abcXY((ABC_RING_OUTER + ABC_RING_INNER) / 2, angle + sweep / 2) : null,
    };
    if (sweep > 0) angle += sweep + ABC_PAD_ANGLE;
    return segment;
  });
};

// Where a class's list opens: on the dashboard, from the range's own
// ranking (ClassProductsModal), when the ring ranks the selected range, so
// its count is this count; else the ABC page, which ranks one month too.
// No link to the ABC page for an account that can't open it (audit FE-7).
const ClassListLink = ({ facts, onOpenClass, className, label = undefined, children }) => {
  const canOpenAbc = usePermissions().hasPermission(P.ABC_VIEW);
  if (facts.rangeBased && onOpenClass) {
    return <button type="button" className={className} onClick={() => onOpenClass(facts.tier)} aria-label={label}>{children}</button>;
  }
  return canOpenAbc ? <Link to={`/abc?class=${facts.tier}`} className={className} aria-label={label}>{children}</Link> : null;
};

// The finding, first (2026-10-19): what Class A is worth against its size,
// with the period it was ranked over, from the same abc_mix rows the ring
// draws, never a figure of its own. Without a trustworthy revenue share it
// states the count instead, and the widget puts the reason (blocked_reason)
// under it. Under the finding, the definition of an important product on
// the card's face (Technical Adviser, 2 Oct 2026): the ABC run's own
// cut-off (abc_rules) and its period, never restated here, and Class A's
// list. What the system does with Class A is the hint above the card; the
// "?" has the full rule and each class's role.
//
// A plain answer line, as the Forecast accuracy card's (RangeCards.css
// .fc-answer), not a tinted strip: on this page a tinted strip with an icon
// is something to act on (the review action, a synthetic-data note), and a
// finding is not.
const AbcInsight = ({ facts, total, units, rules, onOpenClass, tip }) => {
  const pctOf = facts.skuPct.toFixed(0);
  const when = facts.month ? `, ${facts.month}` : '';
  const noun = units === 'categories' ? 'the categories' : 'the top sellers';
  const rule = rules
    ? `Class A = ${noun} that together make the first ${Math.round(rules.tier_a_cutoff * 100)}% of revenue (the ABC rule)`
    : `Class A = ${noun} ranked highest by revenue`;
  const definition = `${rule}${facts.month ? `, ranked over ${facts.month}` : ''}.`;
  return (
    <div className="abc-finding">
      <p className="abc-finding-answer">
        <span>
          {facts.revenuePct != null
            ? <>Class A drives <strong>{facts.revenuePct.toFixed(0)}%</strong> of revenue from just <strong>{pctOf}%</strong> of {units}{when}.</>
            : <>Class A is <strong>{facts.count.toLocaleString()}</strong> of the {total.toLocaleString()} {units} ranked (<strong>{pctOf}%</strong>){when}.</>}
        </span>
        {tip}
      </p>
      <p className="abc-finding-definition">
        {definition}
        {units === 'categories' && ` ${DEL_MONTE_TIER_ROLE}`}
      </p>
      <ClassListLink facts={facts} onOpenClass={onOpenClass} className="abc-finding-link">
        See the {facts.count.toLocaleString()} {units} <ArrowRight size={13} aria-hidden="true" />
      </ClassListLink>
    </div>
  );
};

// The next step of the story, beside the ring: of the top sellers, how many
// are below their safety stock, and the list (Dashboard's
// AtRiskProductsModal). `atRisk` is the dashboard's safety_stock_exposure;
// absent for an account without the reorder plan, or when nothing is
// measurable. Red while any is below, green when none is.
const AbcAtRisk = ({ atRisk }) => {
  const clear = atRisk.below === 0;
  const below = atRisk.below.toLocaleString();
  const measurable = atRisk.measurable.toLocaleString();
  return (
    <div className={`abc-panel abc-atrisk${clear ? ' is-clear' : ''}`} role="status">
      <span className="abc-atrisk-icon" aria-hidden="true">
        {clear ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
      </span>
      <div className="abc-atrisk-text">
        <p className="abc-panel-title">
          {clear
            ? 'No top sellers below safety stock'
            : `${below} top seller${atRisk.below === 1 ? '' : 's'} below safety stock`}
        </p>
        <p className="abc-panel-text">
          {clear
            ? `All ${measurable} we could check have enough stock until the next delivery.`
            : `${below} of the ${measurable} we could check could run out before the next delivery arrives.`}
          {/* These are the order plan's Tier A, not the ring's range ranking
              (2026-10-22), so the panel names its list. */}
          {atRisk.tierLabel ? ` Checked on the order plan's ${atRisk.tierLabel}.` : ''}
        </p>
        {!clear && (
          <button type="button" className="abc-panel-link" onClick={atRisk.onOpen}>
            Review at-risk products <ArrowRight size={13} aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );
};

// The selected tier: its count and its revenue side by side, the period
// they are from, and its list. `facts` come from the same abc_mix rows the
// ring and the share bars draw. A revenue figure that can't be trusted (no
// total, or shares that don't add up to ~100%) reads "Revenue not
// available" rather than a number that isn't real. What each class is FOR
// is behind the card's "?" (AbcInsight's tip).
const AbcTierCard = ({ facts, onOpenClass = null }) => {
  const role = ABC_TIER_ROLE[facts.tier];
  return (
    <div className="abc-panel abc-tier-card" aria-live="polite">
      <p className="abc-tier-card-name">
        <span className="legend-color" style={{ backgroundColor: abcTierColor(facts.tier) }} aria-hidden="true" />
        Class {facts.tier}{role && <span className="abc-tier-card-alias">· {role.name}</span>}
      </p>
      <div className="abc-tier-card-body">
        <div className="abc-tier-card-stat">
          <p className="abc-tier-card-skus">{facts.count.toLocaleString()}</p>
          <p className="abc-tier-card-note">{facts.units}</p>
        </div>
        <div className="abc-tier-card-stat">
          <p className={`abc-tier-card-revenue${facts.amount == null ? ' is-unavailable' : ''}`}>
            {facts.amount != null ? formatCompactPesos(facts.amount) : 'Revenue not available'}
          </p>
          {facts.amount != null && <p className="abc-tier-card-note">revenue</p>}
        </div>
      </div>
      {/* The period the class's pesos were earned in (abc_revenue); its
          share of revenue is the figure in the ring's centre. */}
      {facts.month && <p className="abc-tier-card-period">{facts.month}</p>}
      {/* "Which ones?" — the products behind this class's count, one click
          away. */}
      <ClassListLink facts={facts} onOpenClass={onOpenClass} className="abc-tier-card-link">
        See the {facts.count.toLocaleString()} Class {facts.tier} {facts.units} <ArrowRight size={12} aria-hidden="true" />
      </ClassListLink>
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
      <Callout
        color={abcTierColor(facts.tier)}
        period={`Class ${facts.tier}${ABC_TIER_ROLE[facts.tier] ? ` · ${ABC_TIER_ROLE[facts.tier].name}` : ''}`}
        value={`${facts.count.toLocaleString()} ${facts.units}`}
        name={`${facts.skuPct.toFixed(0)}% of ${facts.units}`}
      >
        <CalloutLine>{revenueLine}</CalloutLine>
      </Callout>
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
export const ABCDonutWidget = ({ data = [], revenue, rules, emptyReason, note, coverage = null, units = 'SKUs', atRisk = null, onOpenClass = null, syntheticNote = null }) => {
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

  // The cut-offs are GET /dashboard's abc_rules (the ABC run's own
  // constants), never restated here. How a class is decided, and what each
  // class is for (ABC_TIER_ROLE), sit behind the "?" in the finding.
  const tip = rules ? (
    <InfoTip label="How classes are decided">
      <span className="chart-tip-line">
        {`${unitsTitle} are ranked by revenue${rankedMonth ? ` over ${rankedMonth}` : ''}`
          + `${revenue?.label || !rankedMonth ? '' : ' (a single month)'}. Class A is the top sellers that `
          + `together make the first ${Math.round(rules.tier_a_cutoff * 100)}% of revenue, B the next `
          + `${Math.round((rules.tier_b_cutoff - rules.tier_a_cutoff) * 100)}%, C the last `
          + `${Math.round((1 - rules.tier_b_cutoff) * 100)}%.`}
      </span>
      {/* With only a handful of categories a tier can't land on its cut-off
          (Del Monte 2025-12: A 71%, B 18%, C 11%). */}
      {units === 'categories'
        ? <span className="chart-tip-line">With only a few categories, a class cannot land exactly on its cut-off.</span>
        : ['A', 'B', 'C'].map((t) => (
          <span key={t} className="chart-tip-line">
            Class {t} ({ABC_TIER_ROLE[t].name.toLowerCase()}): {ABC_TIER_ROLE[t].role}
          </span>
        ))}
    </InfoTip>
  ) : null;
  const tierA = data.find((d) => d.tier === 'A');
  const notes = [
    coverage,
    !sharesAddUp ? revenue?.blocked_reason : null,
    note,
    syntheticNote,
  ].filter(Boolean);

  // The card, top to bottom (2026-10-19, after the mockup): the finding,
  // then the ring and its legend beside the at-risk count and the selected
  // class, then the share bars. No title of its own: the dashboard's
  // question above it names the card.
  return (
    <div className={`chart-widget abc-card${hasData ? '' : ' chart-widget-empty'}`}>
      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No ABC classification available'}</p>
      ) : (
        <div className="chart-widget-body abc-body">
          {tierA && <AbcInsight facts={factsFor(tierA)} total={total} units={units} rules={rules} onOpenClass={onOpenClass} tip={tip} />}
          {notes.length > 0 && (
            <div className="abc-notes">
              {notes.map((text) => <p key={text} className="chart-placeholder-note">{text}</p>)}
            </div>
          )}
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
                {/* Each tier's share on its band, where the band is wide
                    enough; the pale plum takes dark text. Not the selected
                    tier's: its share is the figure in the centre. */}
                {segments.map((s) => s.label && s.tier !== selected.tier && (
                  <text
                    key={`label-${s.tier}`}
                    x={s.label.x}
                    y={s.label.y}
                    textAnchor="middle"
                    dominantBaseline="central"
                    className={`abc-seg-label${s.tier === 'C' ? ' is-dark' : ''}`}
                    aria-hidden="true"
                  >
                    {s.value.toFixed(0)}%
                  </text>
                ))}
                {/* The selected tier's headline number, where the eye lands
                    first. Revenue share when it can be trusted, else the SKU
                    count (the notes above say why). */}
                {selectedFacts && (
                  <g className="abc-donut-centre" aria-hidden="true">
                    <text x={centre} y={centre - 20} textAnchor="middle" className="abc-donut-centre-tier">
                      Class {selectedFacts.tier}
                    </text>
                    <text x={centre} y={centre + 10} textAnchor="middle" className="abc-donut-centre-value">
                      {selectedFacts.revenuePct != null
                        ? `${selectedFacts.revenuePct.toFixed(0)}%`
                        : selectedFacts.count.toLocaleString()}
                    </text>
                    <text x={centre} y={centre + 30} textAnchor="middle" className="abc-donut-centre-label">
                      {selectedFacts.revenuePct != null ? 'of revenue' : units}
                    </text>
                  </g>
                )}
              </svg>
              {/* One tier per row: its name, and its share of the products.
                  Picks the tier the panel beside the ring describes. */}
              <ul className="abc-legend">
                {data.map((d) => (
                  <li key={d.tier}>
                    <button
                      type="button"
                      className={`abc-legend-btn${d.tier === selected.tier ? ' is-selected' : ''}`}
                      aria-pressed={d.tier === selected.tier}
                      aria-label={`Class ${d.tier}${ABC_TIER_ROLE[d.tier] ? `, ${ABC_TIER_ROLE[d.tier].name}` : ''}: ${skuSharePct(d).toFixed(0)}% of ${units}`}
                      onClick={() => setSelectedTier(d.tier)}
                    >
                      <span className="legend-color" style={{ backgroundColor: abcTierColor(d.tier) }} aria-hidden="true" />
                      <span className="abc-legend-text">
                        <span className="abc-legend-head">
                          <span className="abc-legend-tier">{d.tier}</span>
                          {ABC_TIER_ROLE[d.tier] && <span className="abc-legend-name">{ABC_TIER_ROLE[d.tier].name}</span>}
                        </span>
                        <span className="abc-legend-sub">{skuSharePct(d).toFixed(0)}% of {units}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div className="abc-side">
              {atRisk && <AbcAtRisk atRisk={atRisk} />}
              <AbcTierCard facts={factsFor(selected)} onOpenClass={onOpenClass} />
            </div>
          </div>
          <div
            className="abc-share-pair"
            role="img"
            aria-label={sharesAddUp ? `Share of revenue versus share of ${units}, by class` : `Share of ${units}, by class`}
          >
            {sharePairs.map((pair) => (
              <div className="abc-share-row" key={pair.key}>
                <div className="abc-share-head">
                  <span className="abc-share-label">{pair.label}</span>
                  <span className="abc-share-values">
                    {data.map((d) => (
                      <span key={d.tier} className="abc-share-value">
                        <span className="legend-color" style={{ backgroundColor: abcTierColor(d.tier) }} aria-hidden="true" />
                        {d.tier} {pair.value(d).toFixed(0)}%
                      </span>
                    ))}
                  </span>
                </div>
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
  noRecordReason = null,
}) => {
  const countPhrase = countDay ? `the ${countDay} stock count` : period ? `the ${formatMonth(period)} stock count` : 'the latest stock count';
  const hasData = data.length > 0;
  const hasDead = data.some((row) => (row.deadStock || 0) > 0);
  const hasNoData = data.some((row) => (row.noData || 0) > 0);
  // Every bar is "No stock record" (Del Monte: its classes are categories):
  // the card then says so in words, since all-grey bars read as broken.
  const noneRecorded = hasData && hasNoData && data.every((row) => !((row.inStock || 0) > 0) && !((row.deadStock || 0) > 0));
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
          {noneRecorded && (
            <p className="chart-placeholder-note">
              No product in these classes has a stock record in {countPhrase}, so none can be marked active or dead.
              {noRecordReason ? ` ${noRecordReason}` : ''}
            </p>
          )}
          {/* Overlaps Active, so listed rather than drawn. The rows are GET
              /dashboard's tier_stock pending counts for the LP's current
              cycle, grouped by each SKU's tier in the latest ABC run. */}
          {hasPending && (
            <p className="chart-placeholder-note tier-stock-pending-note">
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

// The hover, in the dashboard's shared boxes: a teal box for the month's
// actual pieces, a violet one for the forecast with its likely range under
// it. The bridge point (the last actual month, given the actual as its own
// "forecast" so the lines join, chartData below) shows actual only.
const PortfolioForecastTooltip = ({ active, payload, label, calendar = null }) => {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  const when = plainPeriod(row.period ?? label);
  // The headline compact ("1.2M pcs", as the axis and the labels read), the
  // exact count under it (2026-10-21, mockup pass).
  const compact = (v) => `${formatCompactQty(v, 2)} pcs`;
  const exact = (v) => `${Math.round(v).toLocaleString()} pieces`;
  const band = row.confidenceBase != null && row.confidenceBand != null && row.confidenceBand > 0;
  const bridged = row.actual != null && row.forecast === row.actual;
  return (
    <Callouts>
      {row.actual != null && (
        <Callout color={CHART_COLORS.salesSeries} period={when} value={compact(row.actual)} name="Actual sales">
          <CalloutLine>{exact(row.actual)}</CalloutLine>
        </Callout>
      )}
      {row.forecast != null && !bridged && (
        <Callout color={COLORS.forecast} period={when} value={compact(row.forecast)} name="Forecast demand">
          {band && (
            <CalloutLine>
              Likely range: <strong>
                {formatCompactQty(row.confidenceBase, 2)} – {formatCompactQty(row.confidenceBase + row.confidenceBand, 2)}
              </strong> pcs (meant to cover about 9 in 10 months)
            </CalloutLine>
          )}
          <CalloutLine>{exact(row.forecast)}</CalloutLine>
          {calendar && row.beforeAdjustment != null && (
            <CalloutLine>
              Before the calendar adjustment: <strong>{Math.round(row.beforeAdjustment).toLocaleString()}</strong> pieces
              {calendarFactorText(calendar) ? ` (${calendarFactorText(calendar)})` : ''}
            </CalloutLine>
          )}
        </Callout>
      )}
      {band && !bridged && (
        <CalloutNote>Assumes each SKU&apos;s forecast misses independently; a shared seasonal swing would widen it.</CalloutNote>
      )}
    </Callouts>
  );
};

// The marked points (2026-10-21, mockup pass): the highest and lowest month
// of actual demand and the next forecast, each a small box with the month
// over its value. Drawn inside the plot: above the point, or below it where
// there is no room above (and the other way round for the low), and pulled
// in at the plot's edges. `frame` is the plot's box in pixels, worked out
// from the measured container (Recharts gives a series label no plot box).
// Which marks are drawn at all is labelsThatFit's: one that would run into
// another is left to the tooltip. The .chart-end-label class hides them on
// a phone, where there is no room.
const PF_MARK_H = 34;
const PF_MARK_GAP = 12;
const markWidth = (lines) => Math.ceil(Math.max(lines[0].length * 5.8, lines[1].length * 7.4)) + 18;
const markLabels = (marks, frame) => {
  if (!marks.length || !frame) return false;
  return ({ x, y, index }) => {
    const m = marks.find((k) => k.idx === index);
    if (!m || x == null || y == null) return null;
    const roomAbove = y - PF_MARK_GAP - PF_MARK_H >= frame.top;
    const roomBelow = y + PF_MARK_GAP + PF_MARK_H <= frame.bottom;
    const above = m.below ? !roomBelow && roomAbove : roomAbove || !roomBelow;
    const top = above ? y - PF_MARK_GAP - PF_MARK_H : y + PF_MARK_GAP;
    const left = Math.max(frame.left, Math.min(x - m.width / 2, frame.right - m.width));
    return (
      <g className="chart-end-label pf-mark" pointerEvents="none">
        <rect x={left} y={top} width={m.width} height={PF_MARK_H} rx={7} className="pf-mark-box" stroke={m.color} />
        <text x={left + 9} y={top + 14} fontSize={10.5} fontWeight={600} fill="var(--color-text-muted, #5F6B7D)">{m.lines[0]}</text>
        <text x={left + 9} y={top + 28} fontSize={12.5} fontWeight={700} fill="var(--color-text, #182230)">{m.lines[1]}</text>
      </g>
    );
  };
};
// Dots on a line at the given points (its end, its marked months).
const dotsAt = (color, indices) => ({ cx, cy, index }) => (
  indices.includes(index) && cx != null && cy != null
    ? <circle key={`dot-${index}`} cx={cx} cy={cy} r={4.5} fill={color} stroke="var(--color-surface, #fff)" strokeWidth={2} />
    : null
);

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
// Every month is labelled while a month name fits its slot at a readable
// size; only below this width per month (a phone) are labels thinned, to
// every 2nd or 3rd month. Was 17.5: at a phone's ~19px per month all
// thirteen names showed at 8.5px, run together (2026-10-15).
const MONTH_LABEL_MIN_PX = 24;
// Below this width per month, "PRESENT" no longer fits its one-month band:
// it reads "NOW", set against the band's right edge, so it and "FUTURE"
// (set against its left edge) sit either side of the rule between them
// instead of on top of each other.
const SECTION_LABEL_MIN_SLOT_PX = 62;

// The month axis: the dashboard's shared two-line tick (MonthTick.jsx, the
// month over its year) since 2026-10-19; until then one bracket per year
// under the month names, which no other chart drew.
// The forecast plot's fixed frame, so one month's width can be worked out
// from the container's: the y axis, and the chart's right margin.
const PF_Y_AXIS_WIDTH = 60;
// A measured width for an element that mounts late (the plot sits behind
// the loading and table states, so a ref read once on mount would miss it).
// Height too since 2026-10-21: the marked points need the plot's bottom.
const useMeasuredSize = () => {
  const [size, setSize] = useState({ width: 0, height: 0 });
  const observer = useRef(null);
  const ref = useCallback((node) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const box = node.getBoundingClientRect();
      setSize((prev) => (prev.width === box.width && prev.height === box.height ? prev : { width: box.width, height: box.height }));
    };
    measure();
    observer.current = new ResizeObserver(measure);
    observer.current.observe(node);
  }, []);
  return [ref, size];
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
  // How many SKUs the series sums (GET /dashboard's gated_sku_count) out of
  // the scope's Category A forecasts (forecast.total_count). The tiles that
  // showed the gate's figures are hidden; this line still says the card is
  // a subset — 19 of 132 on 2026-09-29 under the old MAPE gate, when "1.6%
  // below" read as the whole portfolio while all 132 together were +16.4%.
  // Since 2026-09-29 the gate is MASE < 1 (the LP's own), which passes 73.
  gatedSkuCount = null,
  reliability = null,
  // The list reliability.total_count is ('Tier A as of Feb 2026', or
  // "Unilever's Tier A as of Feb 2026" under All principals); null keeps
  // "Class A SKUs".
  tierLabel = null,
  // Why the forecast point is not drawn (a range ending before the latest
  // month: the one forecast is for the month after the latest sales).
  forecastNote = null,
  // The summed SKUs' share of the latest month's pieces across every
  // product ({ pct, period, all, theirs }, Dashboard.jsx), so this chart's
  // "actual" is never mistaken for the summary card's: 965,554 pieces here
  // against 1,766,710 there for the same month (2026-10-19).
  piecesShare = null,
  // The company calendar factor inside the forecast (GET /dashboard's
  // portfolio_forecast.calendar_adjustment, applied only; 2026-10-19).
  calendar = null,
}) => {
  const hasData = series.length > 0;
  const tierACount = reliability?.total_count ?? null;
  const tierAUnits = tierLabel ? `SKUs in ${tierLabel}` : 'Class A SKUs';
  const shadeId = useLineShadeId();
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
  // Each line's end, for its ringed dot: the last month with actual demand,
  // and the forecast month (never the bridge point, which is an actual).
  const lastActualIdx = plotRows.reduce((found, pt, i) => (pt.actual != null ? i : found), -1);
  const lastForecastIdx = plotRows.reduce((found, pt, i) => (pt.forecast != null && pt.actual == null ? i : found), -1);
  const [plotRef, plotSize] = useMeasuredSize();
  const plotWidth = plotSize.width;

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

  // The highest and lowest month of actual demand and the next forecast
  // (utils/forecastHighlights.js), for the marked points and the Key
  // takeaways under the chart. From `series` as served: the bridge point
  // chartData adds is an actual month, never the next forecast. No next
  // forecast when the range ends before the latest month (forecastNote).
  const highlights = useMemo(() => {
    const h = demandHighlights(series);
    return forecastNote ? { ...h, next: null } : h;
  }, [series, forecastNote]);
  // The plot's box in the chart's own pixels (margins and axes as drawn below).
  const plotFrame = plotSize.width && plotSize.height ? {
    top: 10,
    bottom: plotSize.height - 10 - (X_AXIS_TITLED_HEIGHT + 22),
    left: PF_Y_AXIS_WIDTH,
    right: plotSize.width * 0.99 - EDGE_LABEL_MARGIN,
  } : null;
  // The marks, in priority order: the forecast, then the high, then the low.
  const marks = useMemo(() => {
    const idxOf = (period) => plotRows.findIndex((pt) => pt.period === period);
    const mark = (h, title, color, below = false) => {
      if (!h) return null;
      const idx = idxOf(h.period);
      if (idx < 0) return null;
      const lines = [title, `${formatCompactQty(h.value, 2)} pcs`];
      return { idx, lines, width: markWidth(lines), color, below };
    };
    return labelsThatFit([
      mark(highlights.next, `Forecast · ${formatMonth(highlights.next?.period)}`, COLORS.forecast),
      mark(highlights.peak, formatMonth(highlights.peak?.period), CHART_COLORS.salesSeries),
      mark(highlights.low, formatMonth(highlights.low?.period), CHART_COLORS.salesSeries, true),
    ], Number.isFinite(slotPx) ? slotPx : 1e6);
  }, [highlights, plotRows, slotPx]);
  const forecastMarks = marks.filter((m) => m.color === COLORS.forecast);
  const actualMarks = marks.filter((m) => m.color !== COLORS.forecast);

  const tableColumns = [
    { key: 'period', label: 'Month', format: (v) => formatAxisPeriod(v), align: 'left' },
    { key: 'actual', label: 'Actual (pieces)', format: (v) => Math.round(v).toLocaleString() },
    { key: 'forecast', label: 'Forecast (pieces)', format: (v) => Math.round(v).toLocaleString() },
    { key: 'confidenceLower', label: 'Approx. 90% range, low (pieces)', format: (v) => Math.round(v).toLocaleString() },
    { key: 'confidenceUpper', label: 'Approx. 90% range, high (pieces)', format: (v) => Math.round(v).toLocaleString() },
    ...(calendar
      ? [{ key: 'beforeAdjustment', label: 'Forecast before the calendar adjustment (pieces)', format: (v) => Math.round(v).toLocaleString() }]
      : []),
  ];
  // The months the card spans, for the subtitle: the picker's range plus
  // the forecast month after it.
  const seriesSpan = series.length
    ? `${formatMonth(series[0].period)} – ${formatMonth(series[series.length - 1].period)}`
    : null;

  return (
    <div className={`chart-widget pf-card${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          {/* The unit is PIECES here and pesos on the chart above it; the
              y-axis reads "120k" in both, so it is named in the heading.
              The badge is how many SKUs the line sums (gated_sku_count),
              never a count the card doesn't have (2026-10-21). */}
          <h4>
            <span><span className="title-accent">Forecast</span> demand · Top sellers</span>
            {gatedSkuCount > 0 && (
              <span className="pf-sku-badge" title={`The chart sums ${gatedSkuCount.toLocaleString()} SKUs`}>
                {gatedSkuCount.toLocaleString()} SKUs
              </span>
            )}
            <span className="chart-unit">pieces</span>
            {gatedSkuCount != null && tierACount ? (
              <InfoTip label="Which SKUs are summed">
                {`Demand summed across ${gatedSkuCount.toLocaleString()} of the ${tierACount.toLocaleString()} ${tierAUnits}: `
                  + 'those whose forecasts had a test error below the average month-to-month change in their sales before the test months (MASE below 1), the same check the reorder plan uses, '
                  + 'a check the team adopted, not confirmed by SSM or the adviser. '
                  + `The other ${(tierACount - gatedSkuCount).toLocaleString()} are left out rather than summed on forecasts that failed `
                  + 'the check, and the plan gives them no order recommendation: their forecast did not pass, or the product '
                  + 'has too little history or no recent sales.'}
                {piecesShare && (
                  <span className="chart-tip-line">
                    {`In ${piecesShare.period} these SKUs sold ${Math.round(piecesShare.theirs).toLocaleString()} of the `
                      + `${Math.round(piecesShare.all).toLocaleString()} pieces sold across every product (${piecesShare.pct.toFixed(0)}%), `
                      + 'so this chart is a part of the Summary card\'s pieces, not all of them.'}
                  </span>
                )}
              </InfoTip>
            ) : null}
          </h4>
          <SectionLede>What the top sellers will most likely sell</SectionLede>
          <p>
            {seriesSpan ? `Pieces per month, ${seriesSpan}` : 'Pieces per month'}
            {gatedSkuCount != null && tierACount
              ? ` · ${gatedSkuCount.toLocaleString()} of ${tierACount.toLocaleString()} ${tierAUnits} whose test error was below the average month-to-month change in their sales before the test months (a check the team adopted, not confirmed by SSM or the adviser)`
              : ' · planned Class A SKUs'}
            {piecesShare && ` · ${piecesShare.pct.toFixed(0)}% of all pieces sold in ${piecesShare.period}`}
          </p>
          {/* The calendar adjustment inside the forecast, on the card's face:
              it is a method change awaiting the adviser's sign-off, so it is
              said, not left in a "?" (2026-10-19). */}
          {hasData && calendar && (
            <p className="chart-insight chart-calendar-note keep-visible">
              {`The ${formatMonth(calendar.forecast_period)} forecast includes a calendar adjustment of `
                + `${calendarFactorText(calendar)}, learned from ${calendarYearsText(calendar) || 'earlier years'}.`}
              {/* Pending sign-off as a pill, on the card's face (not behind
                  the "?"), only while the API says signed_off is false. */}
              {calendarSignoffText(calendar.signed_off) && (
                <span className="badge badge-warning chart-calendar-pending">
                  {calendarSignoffText(calendar.signed_off).replace(/^./, (c) => c.toUpperCase())}
                </span>
              )}
              <InfoTip label="About the calendar adjustment">
                <span className="chart-tip-line">{calendar.method || CALENDAR_METHOD_FALLBACK}</span>
                <span className="chart-tip-line">
                  {`${formatMonth(calendar.forecast_period)}: ${Math.round(calendar.before_pieces).toLocaleString()} pieces from the `
                    + `models × ${calendar.factor != null ? calendar.factor.toFixed(4) : 'each product’s factor'} = `
                    + `${Math.round(calendar.forecast_pieces).toLocaleString()} pieces, over ${calendar.products.toLocaleString()} `
                    + `of the ${calendar.of_products.toLocaleString()} products summed here.`}
                </span>
                <span className="chart-tip-line">{CALENDAR_HISTORY_NOTE}</span>
              </InfoTip>
            </p>
          )}
          {hasData && sectionsLine && view === 'chart' && <p className="chart-insight">{sectionsLine}</p>}
          {hasData && forecastNote && <p className="chart-insight keep-visible">{forecastNote}</p>}
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
            // In the plot's place and at the plot's height, so the card is
            // the same size in both views; the table scrolls inside.
            <div className="chart-container chart-table-box">
              <ChartTable
                columns={tableColumns}
                rows={series}
                caption="Actual demand and forecast by month, in pieces"
              />
            </div>
          ) : (
            <>
              <ul className="custom-legend custom-legend-top">
                <li className="legend-item">
                  <span className="legend-line" style={{ borderTopColor: CHART_COLORS.salesSeries }} />
                  Actual sales
                </li>
                {/* Only when a forecast is drawn: a range ending before the
                    latest month shows history alone (forecastNote). */}
                {!forecastNote && (
                  <>
                    <li className="legend-item">
                      <span className="legend-line legend-line-dashed" style={{ borderTopColor: COLORS.forecast }} />
                      Forecast (future)
                    </li>
                    {/* The band assumes each product's miss is independent of the
                        others' (GET /dashboard's combined half-widths); said on
                        hover, the legend stays plain. */}
                    <li
                      className="legend-item"
                      title="Assumes each product's forecast misses on its own; if products move together, the real range is wider."
                    >
                      <span className="legend-color" style={{ backgroundColor: COLORS.forecastBg, borderRadius: '3px' }} />
                      {/* The band's design (z = 1.645), never measured against
                          sales, so it says what it is meant to do (2026-10-22). */}
                      Likely range: meant to cover about 9 in 10 months
                    </li>
                  </>
                )}
              </ul>
              <div className="chart-container" ref={plotRef}>
                <ResponsiveContainer width="99%" height="100%">
                  <ComposedChart data={plotRows} margin={{ top: 10, right: EDGE_LABEL_MARGIN, left: 0, bottom: 10 }}>
                    <defs>
                      <LineShade id={shadeId} color={CHART_COLORS.salesSeries} />
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
                      tick={(
                        <MonthTick
                          fontSize={slotPx * tickStep < 26 ? 9.5 : 11}
                          fill={CHART_COLORS.axisLabel}
                          period={(i) => plotRows[i]?.period}
                        />
                      )}
                      height={X_AXIS_TITLED_HEIGHT + 22}
                      label={xAxisTitle('Month')}
                    />
                    <YAxis
                      width={PF_Y_AXIS_WIDTH}
                      axisLine={false}
                      tickLine={false}
                      domain={['auto', 'auto']}
                      tick={{ fontSize: 11, fill: CHART_COLORS.axisLabel }}
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
                          fontSize: narrowSlots ? 9.5 : 11,
                          fontWeight: 700,
                          letterSpacing: narrowSlots ? 0.3 : 1,
                          fill: CHART_COLORS.axisLabel,
                        }}
                      />
                    ))}
                    {sections.slice(1).map((sec) => (
                      <ReferenceLine key={`edge-${sec.key}`} x={sec.x1} stroke="var(--color-slate-400, #94a3b8)" strokeWidth={1} />
                    ))}
                    <Tooltip content={<PortfolioForecastTooltip calendar={calendar} />} />
                    {/* The forecast's uncertainty cone. */}
                    <Area type="linear" dataKey="confidenceBase" stackId="band" stroke="none" fill="transparent" activeDot={false} {...zoom.zoomAnim(0)} />
                    <Area type="linear" dataKey="confidenceBand" stackId="band" stroke="none" fill={COLORS.forecastBg} fillOpacity={0.9} activeDot={false} {...zoom.zoomAnim(0)} />
                    {/* Actual demand: smooth (monotone — through every
                        month's value, never past it), no dot per month, a
                        light shade of its own colour beneath. The hovered
                        month gets a dot. */}
                    <Area
                      {...SOLID_LINE}
                      dataKey="actual"
                      name="Actual demand"
                      stroke={CHART_COLORS.salesSeries}
                      fill={`url(#${shadeId})`}
                      dot={dotsAt(CHART_COLORS.salesSeries, [lastActualIdx, ...actualMarks.map((m) => m.idx)])}
                      label={markLabels(actualMarks, plotFrame)}
                      activeDot={lineHoverDot}
                      connectNulls={false}
                      {...zoom.zoomAnim(1)}
                    />
                    <Line
                      {...FORECAST_LINE}
                      dataKey="forecast"
                      name="Forecast"
                      stroke={COLORS.forecast}
                      dot={endDot(COLORS.forecast, lastForecastIdx)}
                      activeDot={lineHoverDot}
                      connectNulls={false}
                      label={markLabels(forecastMarks, plotFrame)}
                      {...zoom.zoomAnim(2)}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
        </div>
      )}
      {/* Key takeaways (2026-10-21, mockup pass): the highest and lowest
          month and the next forecast, from the same series the chart draws
          (highlights above). One that has no figure is left out. Shown even
          with SHOW_CHART_DESCRIPTIONS off: asked for by name. */}
      {hasData && (highlights.peak || highlights.low || highlights.next) && (
        <section className="pf-takeaways" aria-label="Key takeaways">
          <p className="pf-takeaways-title">Key takeaways</p>
          {/* role="list": the list's markers are off (list-style: none), and
              Safari then drops the list semantics (2026-10-22). */}
          <ol className="pf-takeaways-list" role="list">
            {highlights.peak && (
              <li>
                Highest month: <strong>{formatCompactQty(highlights.peak.value, 2)} pcs</strong> in {formatMonth(highlights.peak.period)}.
              </li>
            )}
            {highlights.low && (
              <li>
                Lowest month: <strong>{formatCompactQty(highlights.low.value, 2)} pcs</strong> in {formatMonth(highlights.low.period)}.
              </li>
            )}
            {highlights.next && (
              <li>
                Next forecast: <strong>{formatCompactQty(highlights.next.value, 2)} pcs</strong> for {formatMonth(highlights.next.period)}
                {highlights.next.low != null && highlights.next.high != null
                  ? `, likely ${formatCompactQty(highlights.next.low, 2)} – ${formatCompactQty(highlights.next.high, 2)} pcs.`
                  : '.'}
              </li>
            )}
          </ol>
        </section>
      )}
      {/* The backend's summary sentence (portfolio_forecast.insight) and the
          year-earlier and before-adjustment asides that followed it are no
          longer shown (2026-10-28, Audrey: figures only, no written-out
          readings); the figures are on the chart and in its tooltip. */}
    </div>
  );
};

// Soft pills in the shared badge tints (ui.css): critical soft red, urgent
// soft amber, planned neutral. The word is printed in every pill and rows
// stay most-urgent first (sortedRows below), so colour never stands alone.
// The urgency badge's tint (Charts.css .urgency-*): soft red, soft amber,
// neutral. The word carries the meaning; colour only repeats it.
const URGENCY_CLASS = {
  CRITICAL: 'urgency-critical',
  URGENT: 'urgency-urgent',
  PLANNED: 'urgency-planned',
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

// Where the LP weights (45/35/20) come from is not on record: analytics/
// params.py:205-207 marks them asserted, in no scribe note (2026-10-22).
const LP_WEIGHTS_SOURCE_NOTE = 'a team setting; source not yet confirmed';

// Compact dashboard-card version of the ReorderRecommendations page.
// rows: [{ sku, product, urgency, orderQty, stock, safetyStock, notInCount, needsReview, reviewReasons }]
// — the list, in GET /dashboard's order. weights: { cost, service_level,
// storage } fractions (0-1), from GET /dashboard's reorder_preview
// .lp_weights, said in one line (they only matter when supply is short).
// The urgency counts and the pieces to order are the Pending reorders
// summary card's (2026-10-19); this card no longer repeats them.

export const ReorderRecommendationWidget = ({
  rows = [],
  weights,
  emptyReason,
  // 'Mar 2026' — the LP plan these rows belong to (GET /dashboard's
  // lp.cycle_date) — 'run 19 Oct 2026', when that plan was generated
  // (lp.lp_generated_at), and 'counted 6 Apr 2026', the stock count the
  // urgencies were judged against. Any may be null; the text then falls
  // back to "current plan" / leaves the part out.
  cycleLabel = null,
  runLabel = null,
  countLabel = null,
  // That the quantities are built on the calendar-adjusted forecast, and
  // whether it awaits sign-off (Dashboard.jsx planCalendarNote, 2026-10-19).
  calendarNote = null,
  calendarSummary = null,
  // The plan's cost and capacity inputs are still placeholders (GET
  // /dashboard's policy_comparison.inputs_are_placeholders); the Reorder
  // page says so, and so does this card.
  inputsArePlaceholders = false,
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

  // The strip above the table (Audrey, 2026-10-21): counts over the rows this
  // card lists (GET /dashboard sends the 5 most urgent), never the whole
  // plan, whose totals are the Pending reorders card's. The pieces total is
  // left out unless every listed row has a quantity, so it is never a sum
  // with a gap in it. It adds each row's figure as its cell shows it (rounded
  // up to a whole piece), so it equals the rows listed (2026-10-24; rounding
  // the sum instead printed a total 2 pieces short of them).
  const shownCount = sortedRows.length;
  const shownCritical = sortedRows.filter((r) => r.urgency === 'CRITICAL').length;
  const shownNotInCount = sortedRows.filter((r) => r.notInCount).length;
  const shownToCheck = sortedRows.filter((r) => r.needsReview).length;
  const shownPieces = shownPiecesTotal(sortedRows);

  return (
    <div className={`chart-widget dash-action-card reorder-card${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4><span>Suggested <span className="title-accent">orders</span></span></h4>
          <SectionLede>What to order, most urgent first</SectionLede>
          {/* GET /dashboard's reorder_preview has been scoped to the LP's
              current cycle since 2026-09-23 (backend/lp_cycle.py), the same
              rows Reorder Recs lists by default. */}
          <p className="keep-visible">
            Order quantities in pieces from the order plan · {cycleLabel ? `${cycleLabel} plan` : 'current plan'}
            {runLabel ? ` · ${runLabel}` : ''}
            {countLabel ? ` · ${countLabel}` : ''}
          </p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{emptyReason || 'No pending recommendations'}</p>
      ) : (
        <>
          {/* Keep the decision summary brief; the info tip retains the full
              explanation and data caveats. */}
          <p className="reorder-priorities-line">
            Target stock · Short-supply priorities:{' '}
            {LP_PRIORITY_ROWS.map((p, i) => (
              <React.Fragment key={p.key}>
                {i > 0 && ' · '}
                {p.label.toLowerCase()} <strong>{solverPct[p.key] == null ? '—' : `${solverPct[p.key]}%`}</strong>
              </React.Fragment>
            ))}
            <InfoTip label="How the order was worked out">
              <span className="chart-tip-line">
                Each product is ordered up to its target stock, in layers: this month&apos;s demand, then safety stock,
                then the rest of the target (SSM&apos;s 3-week rule). The priorities only matter when the supplier
                allocation can&apos;t cover every order; then they decide which products come up short.
              </span>
              {LP_PRIORITY_ROWS.map((p) => (
                <span key={p.key} className="chart-tip-line">
                  <strong>{p.label} ({solverPct[p.key] == null ? '—' : `${solverPct[p.key]}%`}).</strong> {p.blurb}
                </span>
              ))}
              <span className="chart-tip-line">
                The percentages are {LP_WEIGHTS_SOURCE_NOTE}: the manuscript cites stakeholder consultation, but no
                meeting note records it.
              </span>
              {inputsArePlaceholders && (
                <span className="chart-tip-line">Cost and capacity figures are placeholders until SSM confirms them.</span>
              )}
              {calendarNote && <span className="chart-tip-line">{calendarNote}</span>}
            </InfoTip>
          </p>
          {(inputsArePlaceholders || calendarSummary) && (
            <p className="reorder-plan-status">
              {inputsArePlaceholders && (
                <span>Cost/capacity placeholders · storage weight inactive</span>
              )}
              {calendarSummary && (
                <span>{inputsArePlaceholders ? ' · ' : ''}Forecast adjustment: {calendarSummary}</span>
              )}
            </p>
          )}

          <div
            className="reorder-mini-strip"
            title="These counts cover the products listed below only. The whole plan's totals are on the Pending reorders card."
          >
            <span className="reorder-mini-strip-scope">Of the {shownCount} shown</span>
            <span className="reorder-mini-strip-item">
              <strong className={shownCritical > 0 ? 'is-critical' : undefined}>{shownCritical}</strong> critical
            </span>
            <span className="reorder-mini-strip-item">
              <strong className={shownNotInCount > 0 ? 'is-caution' : undefined}>{shownNotInCount}</strong> not in the stock count
            </span>
            <span className="reorder-mini-strip-item">
              <strong className={shownToCheck > 0 ? 'is-caution' : undefined}>{shownToCheck}</strong> to check before ordering
            </span>
            {shownPieces != null && (
              <span className="reorder-mini-strip-item">
                <strong>{formatUnits(shownPieces)}</strong> pieces to order
              </span>
            )}
          </div>

          <div className="reorder-mini-list">
            {/* Own class name, not "reorder-table": that one is the full
                Reorder Recs page table and carries min-width: 1180px, which
                leaked in here (CSS is global) and forced a horizontal scroll. */}
            {/* Explicit table roles (2026-10-22): under 560px the rows turn
                into a grid (Charts.css), and a table with display changed
                loses its semantics in VoiceOver. */}
            <table className="reorder-mini-table" role="table">
              <thead role="rowgroup">
                <tr role="row">
                  <th role="columnheader">Product</th>
                  <th role="columnheader">Urgency</th>
                  <th role="columnheader" className="reorder-mini-num">Stock (pieces)</th>
                  <th role="columnheader" className="reorder-mini-num">Order (pieces)</th>
                </tr>
              </thead>
              <tbody role="rowgroup">
                {sortedRows.map((r) => (
                  <tr key={r.sku} role="row">
                    {/* Name first, SKU code under it (Sir Catubag, 2 Oct
                        2026) — the table used to lead with the code. The name
                        opens that SKU's own recommendation, which the Reorder
                        Recs page shows in its detail modal on load (the ?sku=
                        handling in ReorderRecommendations.jsx), as the code
                        link did. */}
                    <td role="cell" className="reorder-mini-product" title={r.product || r.sku}>
                      <ProductName
                        name={r.product}
                        code={r.sku}
                        onOpen={() => navigate(`/reorder?sku=${encodeURIComponent(r.sku)}`)}
                        openLabel="Open the recommendation for"
                      />
                      {/* Flagged for review on the Reorder page (review_flag):
                          said here too, so the Dashboard never suggests an
                          order the plan itself says to check first. The
                          chip is an InfoTip trigger (2026-10-24): the reason
                          opens on hover, tap or Enter and is read on focus
                          (aria-describedby); it used to be a title only. */}
                      {r.needsReview && (
                        <InfoTip
                          label="Why check first"
                          className="reorder-mini-review-tip"
                          triggerClassName="reorder-mini-review"
                          trigger="Check first"
                        >
                          {reviewReasonsSentence(r.reviewReasons)}
                        </InfoTip>
                      )}
                    </td>
                    <td role="cell">
                      {/* Why this urgency, on hover: the stock against the
                          safety stock it is judged by (2026-10-19). */}
                      <span
                        className={`urgency-badge-mini${URGENCY_CLASS[r.urgency] ? ` ${URGENCY_CLASS[r.urgency]}` : ''}`}
                        title={r.safetyStock != null
                          ? `${r.urgency === 'CRITICAL' ? 'Below' : r.urgency === 'URGENT' ? 'Above' : 'Well above'} its safety stock of ${formatUnits(r.safetyStock)} pieces`
                            + `${r.notInCount ? '; not in the stock count, so read as 0 on hand' : ''}`
                          : undefined}
                      >
                        {r.urgency === 'CRITICAL' && <AlertTriangle size={11} strokeWidth={2.5} aria-hidden="true" />}
                        {r.urgency}
                      </span>
                    </td>
                    {/* The stock the urgency was judged on. A product missing
                        from the opening count is read as 0 by the plan; the
                        cell says "not in count" (amber), never a 0 that would
                        look like a counted, empty shelf. */}
                    <td role="cell" className="reorder-mini-qty" data-label="Stock (pieces)">
                      {r.notInCount
                        ? <span className="reorder-mini-nocount" title="Not in the cycle's opening stock count; the plan reads it as 0 on hand">Not in count</span>
                        : r.stock != null ? formatUnits(r.stock) : '—'}
                    </td>
                    <td role="cell" className="reorder-mini-qty" data-label="Order (pieces)">
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
          <div className="dash-card-footer">
            <Link to="/reorder" className="reorder-mini-view-all">
              See all suggested orders
              <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </div>
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
            (SSM’s stated practice of weekly orders, delivered 2–3 days later, an assumption the system neither implements nor verifies), assuming demand is independent from one day to the
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
              <p className="alloc-answer alloc-answer-reason">
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
