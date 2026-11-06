import React, { useEffect, useRef, useState } from 'react';
import { useOutletContext, useNavigate, useLocation, Link } from 'react-router-dom';
import PageHeader from './ui/PageHeader';
import InfoTip from './InfoTip';
import AtRiskProductsModal from './AtRiskProductsModal';
import ClassProductsModal from './ClassProductsModal';
import {
  ClassChanges, ForecastErrorSummaryCard, IdleStockCard, ProductListModal,
  CATEGORY_MISS_COLUMNS, IDLE_COLUMNS, OVER_RUN_COLUMNS, aboveRuleColumns,
} from './RangeCards';
import RangePicker from './RangePicker';
import { ActionStrip, AnnualSalesCard, BelowSafetyCard, InventoryCard, PendingReordersCard, StockCoverCard } from './HeroKpis';
import { formatCompactCount, policyRatio, shareOf, stockChangeTone } from '../utils/kpiMath';
import {
  SalesVsStockWidget, ABCDonutWidget,
  PortfolioForecastWidget, ReorderRecommendationWidget, PolicyComparisonWidget,
} from './Charts';
import { formatCompactPesos } from '../utils/formatters';
import {
  getClassChanges, getDashboardData, getForecastAccuracy, getIdleStock, getStockDetail, peekDashboardData,
} from '../api/dashboard';
import { CHART_COLORS } from '../theme/colors';
import { ALL_PRINCIPALS, DEFAULT_PRINCIPAL, labelForPrincipal } from '../principals';
import { staleCoverageNotice } from '../dataCoverage';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import { PLACEHOLDER_START, isPlaceholderPeriod, isPreviewMode } from '../dataMode';
import { FIRST_DATA_YEAR } from '../dataCoverage';
import { COMPARE_MODES, comparisonAvailable, comparisonRange, periodToParam } from '../periodFilter';
import BasisTag, { FOLLOWS_RANGE } from './BasisTag';
import { useEntranceReplay } from '../theme/useEntranceReplay';
import { prefersReducedMotion } from '../theme/motion';
import RefreshingNote from './RefreshingNote';
import { DemoForecastList } from './DemoForecasts';
import { DemoOrderPlanCard } from './DemoOrderPlan';
import { formatDate, formatMonth } from '../utils/formatDate';
import { monthsBetween } from '../utils/timeline';
import { noSaleNote } from '../utils/aboveRuleNote';
import { calendarFactorText, calendarSignoffText, calendarYearsText } from '../utils/calendarAdjustment';
import { LoadingStatus, SkeletonChartCard, SkeletonLine, SkeletonStatCards } from './Skeleton';
import { ArrowRight, AlertTriangle, CalendarX, Boxes, PackageX, ShoppingCart } from 'lucide-react';
import EmptyState from './ui/EmptyState';
import LoadError, { describeLoadError } from './ui/LoadError';
import SlowLoadNotice from './ui/SlowLoadNotice';
import TierBasisLabel from './TierBasisLabel';
import AnnualViewChart from './AnnualViewChart';
import './Dashboard.css';
import './Charts.css';

// value/contextLine for a KPI card whose backend field can be honestly
// null: blockedReason present -> render "—" with the reason underneath
// (KPICard's existing contextLine slot, directly under the value — no
// new prop needed); otherwise the real formatted value with its normal
// context line.
function kpiDisplay(value, blockedReason, formatter, normalContext) {
  if (blockedReason) return { value: '—', contextLine: blockedReason };
  return { value: formatter(value), contextLine: normalContext };
}

// When the stock behind a card was counted (GET /dashboard's stock_counts,
// the latest count): "stock counted Apr 6, 2026". A Del Monte count has no
// loaded date (its stored one is a 1st-of-month placeholder, never shown),
// so it names the month: "count month: Dec 2025 (exact date not recorded)".
function stockCountedLine(counts) {
  const usable = (counts || []).filter((c) => c.available);
  return usable.map((c) => {
    const who = usable.length > 1 ? `${PRINCIPAL_NAMES[c.principal] || c.principal} ` : '';
    // A plan made before the opening count was loaded starts from a projection, never a count (opening_basis).
    if (c.opening_basis === 'projected') {
      return `${who}PROJECTED opening stock (from the ${formatMonth(c.period)} count${c.counted_on ? `, counted ${formatDate(c.counted_on)}` : ''}, plus orders on the way, less sales)`;
    }
    return c.counted_on
      ? `${who}stock counted ${formatDate(c.counted_on)}`
      : `${who}count month: ${formatMonth(c.period)} (exact date not recorded)`;
  }).join(' · ') || null;
}

// GET /dashboard's sales/stock window covers the exact start-through-end
// range the picker applied — this page always sends both `period` and
// `startPeriod` (the picker opens on 12 months, DashboardLayout.jsx). The
// backend's own fallback, a fixed trailing 12 months ending at `period`,
// only applies to callers that omit the start; before startPeriod was
// sent, a range wider than 12 months (e.g. Apr 2023 - Mar 2026) silently
// clipped to its last 12, which read as "the start date does nothing."
// Weeks of cover follows the range's end (its count), not its start.
const MONTH_TO_NUM = {
  Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
  Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12',
};
const toPeriod = (month, year) =>
  month && year ? `${year}-${MONTH_TO_NUM[month]}` : undefined;

// 'YYYY-MM' -> 'Feb 2026'. Every figure on this page belongs to a specific
// month, and until 2026-09-23 no card said which: the Sales card read
// "This period's total sales" while the backend walks back to the most
// recent month that HAS data, which under All principals is Dec 2025 (Del
// Monte's last) against Unilever's own Feb 2026. Same card, same caption,
// two different months depending on a filter elsewhere on the page.
const NUM_TO_MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const periodLabel = (period) => {
  if (!period) return null;
  const [year, num] = String(period).split('-');
  return `${NUM_TO_MONTH[Number(num) - 1] || num} ${year}`;
};

// 'YYYY-MM-DD' -> 'Apr 6, 2026': the day a stock count was taken (GET
// /dashboard's kpis.soh_count_date, Inventory_Fact_Real.snapshot_date). The
// stock filed under "Mar 2026" is Unilever's count of Apr 6, 2026; the
// Technical Adviser read the bare month as a month-end figure, so stock
// figures name the count day whenever the backend knows it. Written with
// the app's shared formatDate so every page writes a day the same way.
const dayLabel = (day) => (day ? formatDate(day) : null);

// Names the principals a figure actually covers, but only when that is
// NARROWER than what the user asked for — saying "Unilever only" while the
// Unilever filter is already on would be noise. Under All principals it is
// the whole point: stock valuation and the ABC run are Unilever-only today
// (Del Monte carries no unit cost, and the latest ABC run has no Del Monte
// rows), which the page used to present as the portfolio's own numbers.
const PRINCIPAL_NAMES = { unilever: 'Unilever', delmonte: 'Del Monte' };
const coverageNote = (coverage, pagePrincipal) => {
  if (!coverage || coverage.length === 0) return null;
  if (pagePrincipal !== ALL_PRINCIPALS) return null;
  if (coverage.length > 1) return null;
  return `${PRINCIPAL_NAMES[coverage[0]] || coverage[0]} only`;
};

// The selected range's own sales total (kpis.sales_cumulative, data marts
// since 2026-10-04) under the Sales card's month: "₱391.1M over Mar 2025 –
// Feb 2026 (all 12 months)". Under All principals a month counts only when
// both principals have sales, so a part-year total names the months left out
// rather than passing for the year. Nothing for a one-month range, where the
// total is the card's own figure.
function rangeTotal(total, pagePrincipal) {
  if (!total) return null;
  if (total.value == null) return total.blocked_reason ? { short: null, detail: total.blocked_reason } : null;
  if ((total.months_in_range || 0) <= 1) return null;
  const partial = total.months_with_data !== total.months_in_range;
  const missing = total.missing_months || [];
  const short = `${formatCompactPesos(total.value)} over `
    + `${partial ? `${total.months_with_data} of ${total.months_in_range} months, ` : ''}${total.label}`;
  const detail = partial && missing.length
    ? `No ${pagePrincipal === ALL_PRINCIPALS ? 'figure for both principals' : 'sales on record'} in `
      + `${missing.map(periodLabel).join(', ')}; the range total covers the other months.`
    : `All ${total.months_in_range} months of the range have sales on record.`;
  return { short, detail };
}

// Sparkline + "vs last month" extras for a value card, from GET
// /dashboard's kpis.sales_trend / kpis.soh_trend (backend/chart_insights
// .py) — every number and month here is the backend's. The change renders
// as a shaded pill coloured by direction (Audrey's call, 2026-09-26):
// green when the figure rose, red when it fell, gray when flat — with the
// arrow repeating the direction so it never relies on colour alone.
// `noun` follows the comparison month ("vs Jan 2026 count") where the month
// alone would not say what was compared — the stock card's months are counts.
const trendExtras = (trend, color, noun = '') => {
  if (!trend) return {};
  const extras = {};
  if ((trend.points?.length ?? 0) >= 2) {
    extras.trend = { points: trend.points, color };
  }
  if (trend.delta_pct != null && trend.prev_period) {
    // The comparison month is the nearest earlier one WITH data (backend/
    // chart_insights.kpi_trend); months_apart says when that is not simply
    // last month, e.g. Del Monte's Dec 2025 against Sep 2025. When the gap
    // is a month the backend passed over as an unusual count (backend/
    // data_notes.py — Unilever's Feb 2026 stock), the pill stays as short as
    // the other cards' (Audrey, 2026-10-01): the chart below marks that
    // month as unusual and says why.
    const gap = (trend.skipped || []).length === 0 && trend.months_apart > 1
      ? ` (${trend.months_apart} months earlier)`
      : '';
    extras.deltaLine = `${Math.abs(trend.delta_pct).toFixed(1)}% vs ${periodLabel(trend.prev_period)}${noun ? ` ${noun}` : ''}${gap}`;
    extras.trendDirection = trend.delta_pct > 0 ? 'up' : trend.delta_pct < 0 ? 'down' : undefined;
    extras.deltaTone = trend.delta_pct > 0 ? 'positive' : trend.delta_pct < 0 ? 'negative' : 'neutral';
  } else if (trend.delta_blocked_reason) {
    // The nearest earlier count is more than a year back (kpi_trend's
    // MAX_COMPARE_GAP_MONTHS): no percentage, and the backend says why.
    extras.deltaLine = trend.delta_blocked_reason;
    extras.deltaTone = 'neutral';
  }
  return extras;
};

// "Share of Category A SKUs at/above safety stock" — display thresholds
// for the card's colour, not a pipeline rule: below 60% is an act-now
// signal (red), below 90% a watch (amber), otherwise healthy. The 9% live
// figure used to render in the neutral indigo every card wore, which read
// as "fine" for a number that plainly isn't.
const SAFETY_STOCK_WATCH = 0.9;
const SAFETY_STOCK_ACT = 0.6;
const safetyStockMetricType = (rate) => {
  if (rate == null) return undefined; // blocked: slate, no verdict
  if (rate < SAFETY_STOCK_ACT) return 'danger';
  if (rate < SAFETY_STOCK_WATCH) return 'watch';
  return 'healthy';
};

// One continuous page: no numbered sections, no per-section explanation.
// Each widget is tagged with the kind of analytics it answers, so the three
// types in the analytical mapping (reports/PROJECT_DIAGNOSIS_2026-09-21.md
// §3) are demonstrable at a glance without a paragraph above each one.
//   Descriptive — what happened
//   Predictive  — what happens next
//   Prescriptive— what to do about it
// The mapping has no diagnostic questions, so there is no Diagnostic card
// (removed 2026-09-24 together with GET /segment/summary).
// `realOnly` (preview mode only) tags a predictive or prescriptive widget
// that preview deliberately leaves on real data (backend/data_mode.py), so
// the page says which cards the placeholder months reach and which not.
//
// `question` is the plain question the card answers, and it leads (Technical
// Adviser, 2 Oct 2026: every card starts from "this answers: which products
// matter most?", and jargon is not a label). Read down the page the
// questions are the storyline: what happened -> which products matter ->
// what happens next -> what to do. `hint` is a few quiet words naming what
// the card shows; the analytics type stays as the small tag after them.
// The Client policy card is hidden (3 Oct 2026 analysis): its headline
// compares the plan with SSM's 3-week rule on one basis only, and the answer
// flips with the basis — more stock than the rule at peak (order-up-to)
// stock, less at average stock — pending SSM's answer on whether 3 weeks is
// a minimum or an average. GET /dashboard's policy_comparison serves neither
// of those two figures yet, so they can't be shown side by side from data.
// The widget and its props are untouched; set this to true to bring it back.
const SHOW_POLICY_CARD = false;

// Why the "Suggested orders" card is empty for Del Monte. The card used to say only "No pending recommendations",
// which reads like a fault. Checked against SellOut_Fact_Real, 2026-10-20: no Del Monte category has three
// consecutive real months ending at its latest month (Dec 2025; the best any category has is 1), and the
// moving-average-3 model needs three, so no real forecast exists to plan an order from.
const DEL_MONTE_NO_ORDERS_REASON =
  'Del Monte has no real forecast, so nothing is recommended to order. No category has three consecutive months '
  + 'of real sales ending at its latest month, and the 3-month moving average needs three.';
// What an empty card says on the category-only principal: one note at the top
// of the page gives the reason (2026-11-05).
const CATEGORY_ONLY_EMPTY = 'Not available';
// The sentences that describe or interpret a chart are hidden for now
// (Audrey, 2026-10-13): the line under each card's title, the generated
// takeaways and the how-to-read notes, leaving a card its title, switches,
// legend and plot. What warns stays: synthetic months, missing data, an
// assumption SSM has not confirmed. Nothing is taken out of the widgets;
// the list of what is hidden is under .dashboard-plain in Dashboard.css.
// Set this to true to bring every sentence back.
const SHOW_CHART_DESCRIPTIONS = false;

// The origins a demonstration month is made of (GET /dashboard's
// demonstration.monthly_totals: real / interpolated / bridged / backcast
// pesos), in that order; null for a month that is not from it.
const DEMO_ORIGINS = ['real', 'interpolated', 'bridged', 'backcast'];
const demoOrigins = (month) => (month ? DEMO_ORIGINS.filter((k) => month[k] != null) : null);

// With synthetic data on, Del Monte: each year's bar also counts the
// demonstration's months with no real sales (its canonical monthly totals;
// never a sum of its category series, docs/DEMO_DATA.md) and lists them as
// synthetic, so AnnualViewChart hatches the bar and says how many. Real
// months keep their real figures. Unilever's generated months come in
// annual_sales itself.
//
// Only for the principal the demonstration is for (2026-10-18): under All
// principals the block is still Del Monte's, and adding its months to the
// combined years put Del Monte-only synthetic pesos into months the combined
// figure has no Unilever sales for, then counted the year as complete.
const withDemoYears = (annual, demonstration, principal) => {
  const generated = demonstration?.demonstration && demonstration.principal === principal
    ? (demonstration.monthly_totals || []).filter((m) => m.real == null && m.pesos != null)
    : [];
  if (!annual?.years || generated.length === 0) return annual;
  return {
    ...annual,
    years: annual.years.map((y) => {
      const extra = generated.filter((m) => m.period.startsWith(`${y.year}-`));
      if (extra.length === 0) return y;
      const periods = [y.first_month, y.last_month, ...extra.map((m) => m.period)].filter(Boolean).sort();
      return {
        ...y,
        sales: Math.round(((y.sales ?? 0) + extra.reduce((sum, m) => sum + m.pesos, 0)) * 100) / 100,
        months: y.months + extra.length,
        first_month: periods[0],
        last_month: periods[periods.length - 1],
        synthetic_months: [...(y.synthetic_months || []), ...extra.map((m) => m.period)].sort(),
      };
    }),
  };
};

// GET /dashboard's sales_vs_stock as the hero chart's rows. Used for the
// page's own range and for the comparison period's, so both lines are read
// the same way (count days only where the counts record one; flagged counts
// keep their reason).
const chartPoints = (payload, { synthetic = false } = {}) => {
  if (!payload) return [];
  const counts = (payload.kpis?.stock_counts || []).filter((c) => c.available);
  const dayKnown = counts.length === 0 || counts.every((c) => c.counted_on);
  const flags = new Map((payload.stock_on_hand_flags || []).map((f) => [f.period, f.reason]));
  // With synthetic data on (the Topbar switch) and the server's demonstration
  // switch on, Del Monte's generated months come in a block of their own (GET
  // /dashboard's demonstration, schema demo; CLAUDE.md rule 2), never in the
  // real sales line. A month with no real sales takes the demonstration's
  // canonical monthly total as its estimate, drawn dotted beside the real
  // line, with how it was made for the tooltip.
  const demo = synthetic && payload.demonstration?.demonstration
    ? new Map((payload.demonstration.monthly_totals || []).map((m) => [m.period, m]))
    : null;
  const demoMonth = (pt) => (demo && pt.sales == null ? demo.get(pt.period) ?? null : null);
  // Retired synthetic_v2 stock (kind 'generated') is left out: synthetic data
  // comes from schema demo only, and the demonstration has no stock. The
  // backend still sends it in preview (post-merge data check, item B1).
  const retiredStock = (pt) => String(pt.stock_on_hand_estimated_kind || '').includes('generated');
  return (payload.sales_vs_stock || []).map((pt) => ({
    period: pt.period,
    sales: pt.sales,
    stockOnHand: pt.stock_on_hand,
    stockCountDay: dayKnown ? dayLabel(pt.stock_count_date) : null,
    received: pt.received,
    // Purchases estimated from stock counts and sales (Unilever has no
    // purchase records): the chart's Purchases view only, never a KPI.
    receivedEstimated: pt.received_estimated ?? null,
    receivedEstimatedNegativeSkus: pt.received_estimated_negative_skus ?? null,
    // The marts' estimates for months with no real figure, and returns
    // (DEC-31; 'filled' in real mode, 'generated' in preview): the chart and
    // its table only, labelled by kind, never a KPI.
    salesEstimated: demoMonth(pt)?.pesos ?? pt.sales_estimated ?? null,
    salesEstimatedKind: demoMonth(pt) ? 'demonstration' : (pt.sales_estimated_kind ?? null),
    salesOrigin: demoOrigins(demoMonth(pt)),
    stockEstimated: retiredStock(pt) ? null : (pt.stock_on_hand_estimated ?? null),
    stockEstimatedKind: retiredStock(pt) ? null : (pt.stock_on_hand_estimated_kind ?? null),
    returns: pt.returns ?? null,
    returnsEstimated: pt.returns_estimated ?? null,
    returnsEstimatedKind: pt.returns_estimated_kind ?? null,
    stockUnusual: flags.get(pt.period) || null,
    // Flagged even when no reason came with it: the chart then says "Reason
    // not recorded" rather than losing the flag.
    stockFlagged: flags.has(pt.period),
    // The month's sales are not SSM's own figure: a filled or generated row
    // counted so the month isn't a gap (backend/marts.py, COMPLETE MONTHS).
    salesSynthetic: pt.provenance?.sales === 'synthetic',
    // Why the month has no sales figure (backend/series_gaps.py, kelvin-etl
    // 2026-10-15): not_collected (Del Monte) or no data before 2023.
    salesReason: pt.sales_reason ?? null,
  }));
};

// The shared comparison (src/periodFilter.js) as a KPI pill: the change from
// the comparison period's figure, coloured by direction, with what it was
// compared with spelled out ("range total vs Mar 2024 – Feb 2025"). Null when
// there is no earlier figure to divide by.
const comparePill = (now, then, label) => {
  if (now == null || then == null || !(Number(then) > 0)) return null;
  const pct = ((Number(now) - Number(then)) / Number(then)) * 100;
  return {
    deltaLine: `${Math.abs(pct).toFixed(1)}% ${label}`,
    // The change and what it compared, apart, for the stock card's boxes.
    pct,
    label,
    now: Number(now),
    then: Number(then),
    trendDirection: pct > 0 ? 'up' : pct < 0 ? 'down' : undefined,
    deltaTone: pct > 0 ? 'positive' : pct < 0 ? 'negative' : 'neutral',
  };
};

// What each kind of question is called on screen. The analytics terms
// (descriptive, predictive, prescriptive) stay in data-kind for the styles
// and for reviewers; SSM's staff read the plain words (Audrey, 2026-10-15).
const KIND_LABEL = { Descriptive: 'Looking back', Predictive: 'Looking ahead', Prescriptive: 'What to do' };

// Each question is a section heading (2026-10-16, no step numbers): the
// question with the section's one "?" (2026-11-05: what the period tag means
// and anything else worth knowing), a thin accent rule running to the right,
// then the period tag, the stock count's date and the kind.
// `hideKind` leaves out the kind label ("Looking back") for one section.
// `id` makes the slot a link target (#idle-stock, from the Reorder page).
const Slot = ({ kind, question, hint, realOnly = false, basis = null, counted = null, hideKind = false, id, children }) => {
  const notes = [basis?.detail, hint?.more].filter(Boolean);
  return (
    <div className="dash-slot" data-kind={kind} id={id}>
      <span className="dash-kind-row">
        {question && <span className="dash-question">{question}</span>}
        {/* Named for its section, so a screen reader's list of buttons does
            not read six identical "More about this section" (2026-10-22). */}
        {notes.length > 0 && (
          <InfoTip label={`More about ${hint?.name || 'this section'}`}>
            {notes.map((line) => <span key={line} className="chart-tip-line">{line}</span>)}
          </InfoTip>
        )}
        <span className="dash-question-rule" aria-hidden="true" />
        {/* Whether this card moves with the date filter, and if not, what it
            is pinned to (BasisTag). */}
        {basis && <span className="dash-basis"><BasisTag label={basis.label} follows={basis.follows} /></span>}
        {/* The stock count this section's figures read, said once here. */}
        {counted && <span className="dash-basis"><BasisTag label={counted} follows={false} /></span>}
        {!hideKind && <span className="dash-kind">{KIND_LABEL[kind] || kind}</span>}
        {realOnly && (
          <span className="dash-real-only" title="Sample data reaches the charts that show history only. This card reads real data.">
            Real data only
          </span>
        )}
      </span>
      {children}
    </div>
  );
};

// Same outer structure and card classes as the loaded page below, so every
// block lands at its final size — nothing jumps when the real data replaces
// it. Replaces a lone "Loading dashboard data…" line that left the page
// blank for the whole /dashboard request (measured 5.4–7.1s). Each card sits
// in a .dash-slot like the real ones (that is where their 360px minimum
// height comes from) and takes its widget's shape, in page order: sales
// trend; ABC ring beside the top-seller changes; forecast beside its
// accuracy; the order list beside idle stock. Row classes repeat (two dash-row-even),
// so keys come from the index, not the class.
const DASHBOARD_SKELETON_ROWS = [
  ['dash-row-trend', [{ variant: 'line' }]],
  ['dash-row-abc', [{ variant: 'donut' }, { variant: 'list', rows: 4 }]],
  ['dash-row-even', [{ variant: 'line' }, { variant: 'line' }]],
  ['dash-row-even', [{ variant: 'list', rows: 3 }, { variant: 'list', rows: 4 }]],
];

const DashboardSkeleton = () => (
  <div className="dashboard-body" aria-hidden="true">
    <div className="hero-kpis">
      <SkeletonStatCards count={1} cardClassName="hero-card hero-card-wide" />
      <SkeletonStatCards count={1} cardClassName="hero-card hero-card-inventory" />
      <SkeletonStatCards count={3} cardClassName="hero-card" />
    </div>
    {DASHBOARD_SKELETON_ROWS.map(([rowClass, cards], i) => (
      <div className={`dash-row ${rowClass}`} key={i}>
        {cards.map((card, k) => (
          <div className="dash-slot" key={k}>
            <span className="dash-kind-row"><SkeletonLine width="5.5rem" height="1.1rem" /></span>
            <SkeletonChartCard className="chart-widget" {...card} />
          </div>
        ))}
      </div>
    ))}
  </div>
);

// The sticky section menu's jump targets, in page order — the page's own
// story: the headline numbers, what happened, what's next, what to do. Each
// id sits on the row it names; the hint (the chip's tooltip) says which part
// of that story the section tells.
const DASH_SECTIONS = [
  { id: 'dash-summary', label: 'Summary', hint: 'The headline numbers' },
  { id: 'dash-sales', label: 'Sales & stock', hint: 'How sales and the value of stock changed over time' },
  { id: 'dash-abc', label: 'Top products', hint: 'The products that bring in most of the sales, and which joined or left them' },
  { id: 'dash-forecast', label: 'Forecast', hint: 'How much the top sellers will sell next, and how close past forecasts were' },
  { id: 'dash-order', label: 'What to order', hint: 'What to order now, and the money in stock that is not selling' },
  // The 3-week comparison is named only while its card is shown.
  ...(SHOW_POLICY_CARD ? [{ id: 'dash-policy', label: 'The 3-week rule', hint: "The plan's safety stock against SSM's 3-week rule" }] : []),
];

// The one plain sentence under each step's question (Audrey, 2026-10-15:
// the page tells one story for SSM's staff, from which products matter to
// what to order, as Sir Catubag asked on 2 Oct). No figures here: every
// number is on the cards, with its period and unit.
// Each section's line under its question (2026-10-21, Audrey: less text on
// the page): `text` is one short line; `more`, when there is more worth
// knowing, opens from the "?" beside it (Slot). Same facts as before, the
// units and the 9-in-10 band included.
const STORY = {
  sales: { name: 'sales and stock' },
  abc: {
    name: 'the top sellers',
    more: 'These top sellers are the ones the system forecasts and plans orders for.',
  },
  changes: {
    name: 'products that joined or left the top sellers',
    more: 'Compared with the same months a year earlier, with how much each one\'s sales changed.',
  },
  // The reliability check (MASE < 1) is a team decision (DEC-46), not confirmed by SSM or the adviser,
  // and the band's 9 in 10 is its design (z = 1.645), never measured
  // (Technical Adviser, 2 Oct 2026; 2026-10-22).
  forecast: {
    name: 'the forecast',
    more: 'Only the top sellers whose forecast test error was below the average month-to-month change in their sales before the test months (a reliability check the team adopted, '
      + 'not confirmed by SSM or the adviser). The shaded band is meant to cover about 9 in 10 months.',
  },
  accuracy: {
    name: 'past forecasts',
    more: 'Above zero, the forecast was higher than what sold; below zero, lower.',
  },
  order: {
    name: 'suggested orders',
    more: "Critical means the product's stock is already below its safety stock. Safety stock uses each product's "
      + 'month-to-month demand variability scaled to days, a method pending adviser confirmation.',
  },
  idle: {
    name: 'stock with no sale',
    more: 'Valued at what SSM last paid for it.',
  },
};

const DASH_SECTION_IDS = DASH_SECTIONS.map((s) => s.id);

// The reason on the LP cards for an account without lp.view (GET
// /dashboard's lp_hidden).
const LP_HIDDEN_NOTE = 'Needs the reorder-recommendation permission';

// Safety stock for a Unilever SKU is set from its monthly demand variability,
// scaled to days (a daily series is impossible, DEC-03), a method awaiting the
// Technical Adviser's ruling (Technical Adviser, 2 Oct 2026: flag a pending
// method where it sets a number). 2026-10-22.
const SAFETY_STOCK_METHOD_NOTE = "Safety stock uses each product's monthly demand variability scaled to days, "
  + 'a method pending adviser confirmation.';

// Which section is being read, and whether the toolbar has stuck under the
// top bar. Both are read off the pane that scrolls, once per frame while it
// scrolls. That is .main-content (DashboardLayout), with the top bar sticky
// inside it. It used to read `.dashboard`, which was a scroll container of
// its own (overflow-y: auto) that never scrolled, being as tall as the page:
// the toolbar stuck to it and so never stuck, and the chips never followed
// the reader (fixed 2026-10-21; Dashboard.css .dashboard now clips instead).
// `enabled` is false until the sections exist (skeleton, error).
function useSectionSpy(toolbarRef, enabled) {
  const [active, setActive] = useState(DASH_SECTION_IDS[0]);
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    const bar = toolbarRef.current;
    const scroller = bar?.closest('.main-content') || bar?.closest('.dashboard');
    if (!bar || !scroller) return undefined;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const barRect = bar.getBoundingClientRect();
      // Stuck = resting against the top bar's bottom edge (or the pane's top
      // where there is no top bar).
      const topbar = scroller.querySelector(':scope > .topbar');
      const line = topbar ? topbar.getBoundingClientRect().bottom : scroller.getBoundingClientRect().top;
      setStuck(scroller.scrollTop > 0 && barRect.top <= line + 1);
      if (!enabled) return;
      // The last section whose top has reached the toolbar is the one being
      // read. At the very bottom the last one wins, even though it is too
      // short to ever scroll up to the toolbar.
      let current = DASH_SECTION_IDS[0];
      DASH_SECTION_IDS.forEach((id) => {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top - barRect.bottom <= 24) current = id;
      });
      const scrollable = scroller.scrollHeight > scroller.clientHeight + 2;
      const atEnd = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2;
      setActive(scrollable && atEnd ? DASH_SECTION_IDS[DASH_SECTION_IDS.length - 1] : current);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    scroller.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    measure();
    return () => {
      scroller.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      cancelAnimationFrame(frame);
    };
  }, [toolbarRef, enabled]);
  return { active, stuck };
}

// One chip per section; the current one is filled. Chips are buttons, not
// #hash links: a hash would land the section under the sticky toolbar and
// push a history entry per click.
// Also the Summary cards' links to the charts below them.
const jumpTo = (id) => {
  document.getElementById(id)?.scrollIntoView({
    behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    block: 'start',
  });
};

const DashSectionNav = ({ active, enabled }) => {
  return (
    <nav className="segmented dash-section-nav" aria-label="Dashboard sections">
      {DASH_SECTIONS.map((s) => {
        const current = enabled && active === s.id;
        return (
          <button
            key={s.id}
            type="button"
            className={`segmented-item${current ? ' is-active' : ''}`}
            aria-current={current ? 'true' : undefined}
            title={s.hint}
            disabled={!enabled}
            onClick={() => jumpTo(s.id)}
          >
            {s.label}
          </button>
        );
      })}
    </nav>
  );
};

const Dashboard = () => {
  const { role, hasPermission } = usePermissions();
  const isAdmin = role === 'admin';
  const {
    startMonth, startYear, endMonth, endYear, principal, dataMode, compare = COMPARE_MODES.YEAR, handleResetToToday,
    dataLatest: outletLatest,
  } = useOutletContext() || {};
  const preview = isPreviewMode(dataMode);
  const period = toPeriod(endMonth, endYear);
  const startPeriod = toPeriod(startMonth, startYear);
  // Every input the request varies on, principal included. It was
  // `period|startPeriod` only, which silently broke the principal filter
  // on this page: the fetch effect below early-returns when
  // loadedKey === requestKey, and switching principal leaves both periods
  // untouched, so the request was never issued and the dashboard kept
  // showing the previous principal's numbers. Nothing remounted it
  // either — DashboardLayout's <Outlet key={refreshKey}> only changes on
  // the Topbar's Refresh.
  const requestKey = `${period ?? ''}|${startPeriod ?? ''}|${principal ?? ''}`;

  // The comparison period (Same months last year / Previous period / none,
  // chosen beside the date picker) and its own GET /dashboard, so every
  // compared figure is measured exactly like the one beside it. Fetched
  // after the page's own answer lands, so it never slows the first view; a
  // comparison that would start before the data does is not fetched.
  const versus = comparisonRange(
    { startMonth, startYear, endMonth, endYear }, compare, preview ? PLACEHOLDER_START : undefined,
  );
  const versusKey = versus && !versus.beforeData ? `${versus.endPeriod}|${versus.startPeriod}|${principal ?? ''}` : null;
  const [versusLoaded, setVersusLoaded] = useState({ key: null, data: null, failed: false });
  // A comparison that starts before the data isn't fetched above, because the
  // cards compare whole periods. The hero chart can still show the part that
  // exists, month by month, so it fetches that part for itself. Not when the
  // range's own months already hold it (Jan 2023 onward against a year earlier).
  const dataFloor = preview ? PLACEHOLDER_START : { month: 'Jan', year: String(FIRST_DATA_YEAR) };
  const chartPart = versus?.beforeData ? comparisonAvailable(versus, dataFloor) : null;
  const chartPartKey = chartPart && chartPart.startPeriod < startPeriod
    ? `${chartPart.endPeriod}|${chartPart.startPeriod}|${principal ?? ''}`
    : null;
  const [chartPartLoaded, setChartPartLoaded] = useState({ key: null, data: null, failed: false });

  // `loaded` remembers WHICH range its data belongs to. When the range
  // changes, the previous range's view stays on screen (dimmed, labeled
  // "Updating") until the new one arrives, instead of blanking the page
  // for the whole request. Seeded from the response cache, so revisiting a
  // range already fetched this session renders on the first frame.
  const [loaded, setLoaded] = useState(() => {
    const cached = peekDashboardData({ period, startPeriod, principal });
    return cached ? { key: requestKey, data: cached } : null;
  });
  const [error, setError] = useState(null); // { key, message }
  // Bumped by "Try again" on a failed load, to re-run the fetch below.
  const [attempt, setAttempt] = useState(0);
  // The list behind "N below safety stock" (AtRiskProductsModal).
  const [showAtRisk, setShowAtRisk] = useState(false);
  // The SSM target picked on the Summary card (103/105/108%), shared with the
  // Sales per year chart's dashed line and "to go" bar (2026-10-19). Null
  // until a level is picked: both then read the allocation's default_pct.
  const [allocPct, setAllocPct] = useState(null);
  // The class whose products are listed for the range (ClassProductsModal), or null.
  const [listedClass, setListedClass] = useState(null);
  // Class A changes for the same range and principal (GET /dashboard/
  // class-changes), keyed like `loaded` so a stale range never shows.
  const [classChanges, setClassChanges] = useState(null); // { key, data }
  // The list behind a range card's figure: { kind, rows, loading, error }.
  const [rangeList, setRangeList] = useState(null);
  // Del Monte's estimated product sales (GET /dashboard/product-sales), on
  // the Del Monte view only.
  const navigate = useNavigate();
  const loadedKey = loaded?.key;

  // Every card, the portfolio forecast included, follows the Topbar's
  // principal filter (2026-09-30). The forecast card's own filter, and the
  // separate GET /dashboard it fetched for that scope, are on branch
  // parked/all-principals-filter.
  const pagePrincipal = principal ?? DEFAULT_PRINCIPAL;

  useEffect(() => {
    if (loadedKey === requestKey) return undefined;
    let cancelled = false;
    setError(null);
    getDashboardData({ period, startPeriod, principal })
      .then((res) => {
        if (!cancelled) setLoaded({ key: requestKey, data: res });
      })
      .catch((err) => {
        if (!cancelled) setError({ key: requestKey, message: describeLoadError(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [requestKey, loadedKey, period, startPeriod, principal, attempt]);

  useEffect(() => {
    if (!versusKey || loadedKey !== requestKey) return undefined;
    let cancelled = false;
    getDashboardData({ period: versus.endPeriod, startPeriod: versus.startPeriod, principal })
      .then((res) => { if (!cancelled) setVersusLoaded({ key: versusKey, data: res, failed: false }); })
      .catch(() => { if (!cancelled) setVersusLoaded({ key: versusKey, data: null, failed: true }); });
    return () => { cancelled = true; };
    // versus' periods are read through versusKey.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versusKey, loadedKey, requestKey, principal]);
  const prior = versusKey && versusLoaded.key === versusKey ? versusLoaded : null;

  useEffect(() => {
    if (!chartPartKey || loadedKey !== requestKey) return undefined;
    let cancelled = false;
    getDashboardData({ period: chartPart.endPeriod, startPeriod: chartPart.startPeriod, principal })
      .then((res) => { if (!cancelled) setChartPartLoaded({ key: chartPartKey, data: res, failed: false }); })
      .catch(() => { if (!cancelled) setChartPartLoaded({ key: chartPartKey, data: null, failed: true }); });
    return () => { cancelled = true; };
    // chartPart's periods are read through chartPartKey.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartPartKey, loadedKey, requestKey, principal]);
  const priorPart = chartPartKey && chartPartLoaded.key === chartPartKey ? chartPartLoaded : null;


  useEffect(() => {
    let cancelled = false;
    getClassChanges({ period, startPeriod, principal })
      .then((res) => { if (!cancelled) setClassChanges({ key: requestKey, data: res }); })
      // The card is extra to the page: on a failure it is left out, and the
      // rest of the dashboard stands.
      .catch(() => { if (!cancelled) setClassChanges({ key: requestKey, data: null }); });
    return () => { cancelled = true; };
  }, [requestKey, period, startPeriod, principal]);

  // Opens a range card's product list, fetched on demand for the same range.
  // `runId`: the forecast run an error-card list comes from — the card's
  // "Before the adjustment" view passes the unadjusted twin's (2026-10-19);
  // null is the default (the run the card shows first).
  // 'above' (2026-10-22): the products behind the Stock cover card's "Above
  // SSM's 3-week rule" (GET /dashboard/stock-detail), most pesos above the
  // rule first; `meta` keeps the response's count date, sales window and
  // totals for the list's header (Technical Adviser, 2 Oct 2026: the list
  // behind a count one click away).
  const openRangeList = (kind, runId = null) => {
    setRangeList({ kind, rows: [], meta: null, loading: true, error: null });
    let meta = null;
    const request = kind === 'idle'
      ? getIdleStock({ period, principal }).then((res) => res.items || [])
      : kind === 'above'
        ? getStockDetail({ period, startPeriod, principal }).then((res) => {
          const why = res.blocked_reason || res.cover_blocked_reason;
          if (why) throw new Error(why);
          meta = res;
          return (res.items || [])
            .filter((r) => r.above_rule_pesos > 0)
            .sort((a, b) => b.above_rule_pesos - a.above_rule_pesos);
        })
      : kind === 'category'
        // Category rows carry no product: the category is the row's name.
        ? getForecastAccuracy({ level: 'category', period, startPeriod, principal, run_id: runId })
          .then((res) => (res.rows || []).map((r) => ({ ...r, product_name: r.category_path })))
        : getForecastAccuracy({ period, startPeriod, principal, run_id: runId }).then((res) => res.over_forecast_runs?.items || []);
    request
      .then((rows) => setRangeList((prev) => (prev?.kind === kind ? { kind, rows, meta, loading: false, error: null } : prev)))
      .catch((err) => setRangeList((prev) => (prev?.kind === kind
        ? { kind, rows: [], loading: false, error: err.message || 'Failed to load the list' } : prev)));
  };

  const isRefreshing = Boolean(loaded) && loaded.key !== requestKey;

  // Rebuild the cards whenever a different response lands — a date range
  // or principal change, not a re-render. Keyed on the loaded data's own
  // key rather than requestKey so the build plays with the new numbers
  // already in place, instead of animating the outgoing view while the
  // request is still in flight. Must sit above the early returns below:
  // hooks cannot be called conditionally.
  const enterCycle = useEntranceReplay(loaded?.key ?? '');
  const currentError = error?.key === requestKey ? error.message : null;

  // Also above the early returns (hooks). The section chips only work once
  // the sections exist, so they stay disabled under the skeleton or an error.
  // A range with no data (2026-10-16): no month of sales and nothing on the
  // chart, real or estimated. 'all' = nothing to show at all (no stock count
  // either), so the page says why instead of a page of blanks; 'sales' = no
  // sales, but a stock count stands, so the cards stay under a note. Never a
  // made-up 0 (CLAUDE.md hard rule 3).
  const rangeEmpty = (() => {
    if (!loaded || loaded.key !== requestKey) return null;
    const d = loaded.data || {};
    const sales = d.kpis?.sales_cumulative;
    if (!sales || sales.months_with_data !== 0) return null;
    const points = Array.isArray(d.sales_vs_stock) ? d.sales_vs_stock : [];
    const shown = (p) => [p.sales, p.stock_on_hand, p.sales_estimated, p.stock_on_hand_estimated].some((v) => v != null);
    if (points.some(shown)) return null;
    return d.kpis?.soh_value != null ? 'sales' : 'all';
  })();
  const emptyReason = (() => {
    if (!rangeEmpty) return null;
    const d = loaded.data;
    const latest = d.latest_data_period_by_principal?.[pagePrincipal] || d.latest_data_period;
    if (period && period < `${FIRST_DATA_YEAR}-01`) {
      return `SSM's records start in January ${FIRST_DATA_YEAR}, so there is nothing to show before then.`;
    }
    if (latest && startPeriod > latest) {
      return `The latest month with ${labelForPrincipal(pagePrincipal)} sales is ${periodLabel(latest)}; `
        + "later months haven't been loaded yet.";
    }
    return `No sales were recorded for ${labelForPrincipal(pagePrincipal)} in these months.`;
  })();
  const latestRangeAction = handleResetToToday && (
    <button type="button" className="btn btn-primary" onClick={handleResetToToday}>Go to the latest data</button>
  );

  const sectionsReady = Boolean(loaded) && !currentError && rangeEmpty !== 'all';
  const toolbarRef = useRef(null);
  const { active: activeSection, stuck: toolbarStuck } = useSectionSpy(toolbarRef, sectionsReady);

  // /#idle-stock (the Reorder page links here, 2026-10-22): once the cards
  // have loaded, bring the idle-stock card into view, once per arrival.
  // Once per visit, not per location.key: the layout keeps the hash when it
  // rewrites the address on a filter change (DashboardLayout, 2026-10-24),
  // and each rewrite is a new key, which used to jump back to the card.
  const location = useLocation();
  const hashScrolled = useRef(false);
  useEffect(() => {
    if (location.hash !== '#idle-stock') {
      hashScrolled.current = false;
      return;
    }
    if (!sectionsReady || hashScrolled.current) return;
    const el = document.getElementById('idle-stock');
    if (!el) return;
    hashScrolled.current = true;
    el.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
  }, [sectionsReady, location.hash]);

  // Header is rendered in every state — loading, error and loaded — rather
  // than only on success. The date picker lives inside it, so blanking the
  // whole page on load meant the control the user had just changed
  // disappeared underneath them on every single refetch, and an error left
  // them with no way to pick a different range to recover.
  //
  // The date picker sits in a toolbar with the section menu that sticks
  // under the top bar once the title scrolls away (2026-09-25), so the range
  // stays in reach however far down the page someone has read. The
  // principal filter needs no such help: it is in the top bar, which never
  // scrolls.
  const header = (
    <>
      <PageHeader className="dash-page-header" title="Inventory" accent="pulse">
        {/* The question the whole page answers, before any number (Sir
            Catubag, 2 Oct: a reader measures every card against it). One
            line since 2026-10-21, with no "?" (Audrey, 2026-10-22). */}
        <p className="dash-main-question">
          Monitor inventory, forecast demand and decide <strong className="title-accent">how much of each product to order</strong>.
        </p>
      </PageHeader>
      <div className={`dash-toolbar${toolbarStuck ? ' is-stuck' : ''}`} ref={toolbarRef}>
        <DashSectionNav active={activeSection} enabled={sectionsReady} />
        <RangePicker />
      </div>
    </>
  );

  if (currentError) {
    return (
      <div className="dashboard">
        <div className="dashboard-content">
          {header}
          <LoadError what="the dashboard" message={currentError} onRetry={() => setAttempt((n) => n + 1)} />
        </div>
      </div>
    );
  }

  if (!loaded) {
    return (
      <div className="dashboard">
        <div className="dashboard-content">
          {header}
          <LoadingStatus>Loading dashboard data…</LoadingStatus>
          <SlowLoadNotice />
          <DashboardSkeleton />
        </div>
      </div>
    );
  }

  if (rangeEmpty === 'all') {
    return (
      <div className="dashboard">
        <div className="dashboard-content">
          {header}
          <EmptyState
            role="status"
            icon={CalendarX}
            title={`No data for ${startMonth} ${startYear} – ${endMonth} ${endYear}`}
            actions={latestRangeAction}
          >
            <p>{emptyReason}</p>
            <p>Pick another range above, or jump to the latest months that have data.</p>
          </EmptyState>
        </div>
      </div>
    );
  }

  const { data } = loaded;
  const kpis = data.kpis || {};
  // Preview only: the payload's own placeholder window (null in real mode),
  // which marks the months and the cards the placeholder data reaches.
  const placeholder = data.data_mode?.placeholder ?? null;
  // The fields this payload left on real data (backend/data_mode.py). With
  // the what-if forecasts built, the predictive and prescriptive cards
  // follow the five-year history too; without them they stay real and say so.
  const realOnly = new Set(data.data_mode?.real_only || []);
  const portfolioRealOnly = preview && realOnly.has('portfolio_forecast');
  const placeholderNote = (period) => (
    isPlaceholderPeriod(period, placeholder)
      ? `${periodLabel(period)} is a placeholder month — these classes come from placeholder sales, not SSM's.`
      : null
  );

  // Each card names the month it is for, and the principals it covers when
  // those are narrower than the page's own filter — see periodLabel /
  // coverageNote above for why both are necessary.
  const salesMonth = periodLabel(kpis.sales_period);
  const sohMonth = periodLabel(kpis.soh_period);
  const sohCoverage = coverageNote(kpis.soh_coverage, pagePrincipal);
  // Only under All principals (GET /dashboard's vat_note): the combined
  // pesos mix Unilever's VAT-inclusive amounts with Del Monte's
  // VAT-exclusive ones, and the card must say so rather than imply one basis.
  const vatNote = data.vat_note || null;
  // The tax basis of a single principal's pesos (sales_vs_stock_basis.sales),
  // so the figure states its unit in full: "₱27.9M · Feb 2026 · incl. VAT".
  // A Del Monte range can bring "(except Aug 2023, recorded with tax)"; that
  // aside matters on the card only when the card's own month is the one
  // recorded with tax — and then that month IS tax-inclusive.
  const salesBasisRaw = data.sales_vs_stock_basis?.sales || null;
  const salesBasis = !salesBasisRaw ? null
    : salesMonth && salesBasisRaw.includes(salesMonth) ? 'selling price, VAT-inclusive (recorded with tax)'
      : salesBasisRaw.split(' (')[0];
  // One context line (UI pass): the month and the range's own total, both
  // periods stated. The price basis and the months behind the total sit in
  // the card's "?".
  const salesRange = kpis.sales_blocked_reason ? null : rangeTotal(kpis.sales_cumulative, pagePrincipal);
  // The annual card's "?" (its latest month is the latest with sales, not
  // the range's end): the price basis, the VAT note, the range's months.
  const salesTooltip = [
    salesBasis ? `Sales at ${salesBasis}.` : null,
    vatNote ? `${vatNote}.` : null,
    salesRange?.detail,
  ].filter(Boolean).join(' ');
  // The stock card also answers SSM's own rule (client meeting, Sep 2026:
  // keep three weeks of sales in stock) with the backend's weeks_of_cover,
  // so the target and the actual sit on one line. Since the data marts
  // (DEC-36, 2026-10-04) it reads the card's own count, the one at the
  // range's end, against the 12 months of sales up to that count; the
  // tooltip names that year.
  const cover = kpis.weeks_of_cover || {};
  const policyWeeks = data.inventory?.policy_weeks ?? 3;
  const coverWindow = cover.sales_window
    ? `${periodLabel(cover.sales_window.start)} – ${periodLabel(cover.sales_window.end)}`
    : null;
  // The weeks figure names the sales it is measured in, so "6.2 weeks"
  // never reads as weeks of the range on screen. Not a final figure while
  // the backend serves a caveat (Unilever: stock is the Ilocos Sur
  // warehouse's, product sales La Union's, a match SSM has not confirmed):
  // the card says "provisional" and the tooltip gives the caveat as served.
  const coverProvisional = Boolean(cover.caveat);
  // Del Monte's year has sales in only some months (6 of 12 in 2025); the
  // average is over those, and the tooltip says so rather than imply a year.
  const coverMonthsNote = cover.months_used != null && cover.months_used < 12
    ? ` Only ${cover.months_used} of those months have sales on record; the average is over those.`
    : '';
  // The inventory and stock-cover cards' "?" (2026-10-11): what the card
  // used to spell out in lines of text, one short paragraph each.
  const inventoryTooltip = [
    'Stock on hand at each product\'s last purchase price (the buying price), which is not SSM\'s true cost, so the '
      + 'value is an estimate. It is the stock count at the end of the selected range, not a total over the range, so '
      + 'it changes with the date filter.',
    '"vs last count" compares with the previous stock count on record, skipping an earlier count marked unusual; '
      + 'when this count is the unusual one, the comparison is still shown and says so. "vs a year ago" compares with '
      + 'the count a year earlier, when the comparison beside the date picker is "Same months last year". Red means '
      + 'the change moves cover further from the target.',
    '"Not sold in 6 months": stock of products with no sale in the 6 months up to the count, at the same price. '
      + 'Unilever only: Del Monte\'s sales are by category, so no product can be shown to have gone unsold.',
  ];
  // The figure's unit is the backend's weeks_of_cover.basis (2026-10-22):
  // 'pieces' (Unilever: pieces in stock ÷ pieces sold a week, so no price
  // enters it) or 'pesos' (Del Monte has no pack size: stock at last purchase
  // price ÷ sales at selling price). The "?" used to blame the two prices for
  // the Unilever figure too, which is in pieces (backend/routers/dashboard.py
  // cover_at). The product list behind "Above the 3-week rule" (GET
  // /dashboard/stock-detail) works in pesos, so its own cover differs.
  const coverInPieces = cover.basis === 'pieces';
  const coverTooltip = [
    cover.value != null && coverWindow
      ? (coverInPieces
        ? `Stock cover = pieces in stock ÷ average pieces sold per week over ${coverWindow}, the 12 months up to the count.`
        : `Stock cover = stock value (at last purchase price) ÷ average weekly sales (at selling price) over ${coverWindow}, `
          + 'the 12 months up to the count.')
        + `${coverMonthsNote} SSM's policy (the target) is to keep ${policyWeeks} weeks of sales in stock; "Needed" `
        + 'is the part of the cover the target asks for, "Extra" what is past it.'
      : null,
    cover.value == null ? null
      : coverInPieces
        ? 'Both sides are in pieces, so no price enters this figure. The product list behind "Above the '
          + `${policyWeeks}-week rule" is worked out in pesos (stock at last purchase price, sales at selling price), so `
          + 'the weeks it shows differ from this one.'
        // Two price bases in one ratio: cover reads lower than on one basis.
        : 'Stock is valued at last purchase price and sales at selling price, so cover reads lower than it would on '
          + 'one price basis.',
    coverProvisional ? `Provisional: ${cover.caveat}.` : null,
  ];
  // The count the cover is measured at, for the card's face (2026-10-22: it
  // was on hover only). Del Monte's count has no recorded day.
  const coverCountLine = cover.value == null ? null
    : cover.stock_count_date ? `Stock counted ${dayLabel(cover.stock_count_date)}`
      : cover.stock_period ? `${periodLabel(cover.stock_period)} count (exact date not recorded)` : null;
  // Stock is valued at the SOH file's own extended cost — each product's
  // last purchase price (Inventory_Fact.valuation) — and dated by the day it
  // was counted, not by the month it is filed under: "At last purchase
  // price · stock counted Apr 6, 2026". A count with no recorded day (Del
  // Monte: its stored date is a 1st-of-month placeholder) names its month
  // instead — kpis.stock_counts, the same line the safety-stock card uses.
  const latestCounts = (kpis.stock_counts || []).filter((c) => c.available);
  const countDayKnown = latestCounts.length === 0 || latestCounts.every((c) => c.counted_on);
  const countDay = countDayKnown ? dayLabel(kpis.soh_count_date) : null;
  const countLabel = stockCountedLine(kpis.stock_counts)
    || (countDay ? `counted ${countDay}` : sohMonth ? `${sohMonth} count` : null);
  // Said once for the Summary section, in a chip (2026-11-05). A card reading a
  // different count keeps its own date, so every figure still shows its count.
  const countChip = countLabel ? `${countLabel.charAt(0).toUpperCase()}${countLabel.slice(1)}` : null;
  const sohValue = kpiDisplay(
    kpis.soh_value, kpis.soh_value_blocked_reason, formatCompactPesos,
    ['At last purchase price', countLabel, sohCoverage].filter(Boolean).join(' · '),
  );
  // The same count in pieces (kpis.soh_snapshot.pieces: cases x pack size
  // + loose pieces), short on the card with the exact figure on hover.
  // Unilever only: Del Monte's files carry no pack size, so the backend
  // sends null there with the reason (pieces_note), and the card says it
  // is in pesos only rather than drawing a partial total.
  const sohPieces = kpis.soh_snapshot?.pieces ?? null;
  const piecesNote = kpis.soh_snapshot?.pieces_note || null;
  const inventorySubtitle = sohValue.value === '—' ? sohValue.contextLine
    : sohPieces != null ? `${formatCompactCount(sohPieces)} pieces · at last purchase price`
      : piecesNote ? 'Pesos only (no pack size on file) · at last purchase price' : 'At last purchase price';
  const inventorySubtitleTitle = sohValue.value === '—' ? undefined
    : sohPieces != null ? `${Math.round(sohPieces).toLocaleString()} pieces (cases × pack size + loose pieces)`
      : piecesNote || undefined;

  // The hero chart's rows (chartPoints), and what it compares them with: the
  // "Compare with" setting and that period's rows once they land. Its months
  // are the ones this answer is about (loadedKey), so during a range change the
  // chart on screen stays one consistent picture.
  const salesVsStock = chartPoints(data, { synthetic: preview });
  const [shownEnd, shownStart] = (loadedKey || '').split('|');
  const chartRange = { start: shownStart || null, end: shownEnd || null };
  const chartCompareAnswer = versus?.beforeData ? priorPart : prior;
  const chartCompare = versus
    ? {
        mode: compare,
        shift: versus.shift,
        label: versus.label,
        floor: periodToParam(dataFloor.month, dataFloor.year),
        points: chartCompareAnswer?.data ? chartPoints(chartCompareAnswer.data, { synthetic: preview }) : [],
        pending: versus.beforeData ? Boolean(chartPartKey) && !priorPart : !prior,
        failed: Boolean(chartCompareAnswer?.failed),
      }
    : null;

  const abcMix = (data.abc_mix || []).map((d) => ({
    tier: d.tier,
    count: d.count,
    sharePct: d.revenue_share_pct,
    revenue: d.revenue ?? null,
  }));
  // The principals the ABC run covers (GET /dashboard's abc_coverage), named
  // when narrower than the page's filter: under All principals the latest
  // run is usually Unilever's alone, so the ring, the warehouse-status bars
  // and the below-safety-stock card are Unilever figures and say so.
  const abcCoverage = coverageNote(data.abc_coverage, pagePrincipal);
  // What one ranked row is: Del Monte is ranked by product category (DEC-03).
  const abcCovered = data.abc_coverage || [];
  const abcUnits = abcCovered.length === 1 && abcCovered[0] === 'delmonte'
    ? 'categories'
    : abcCovered.includes('delmonte') ? 'items' : 'products';

  // The page's own payload, so the card and the MASE reliability count
  // (GET /dashboard's forecast block) describe the page's principal.
  const portfolioForecast = data.portfolio_forecast || {};
  // With synthetic data on, Del Monte: the demonstration's category forecasts
  // (GET /dashboard's demonstration.forecasts), shown under the empty card.
  const demoForecasts = preview && pagePrincipal === 'delmonte' && data.demonstration?.demonstration
    ? data.demonstration.forecasts || [] : [];
  // ...and its order plan and dead stock (the same block), shown under the empty "Suggested orders" card.
  const demoPlan = preview && pagePrincipal === 'delmonte' && data.demonstration?.demonstration
    ? data.demonstration : null;
  const forecastReliability = data.forecast || null;
  // A real-only forecast card in preview has nothing in the placeholder
  // months by construction — dropped rather than drawn as a blank run.
  // The one stored forecast is for the month after the latest sales month
  // (Mar 2026). It is drawn only when the range ends on that latest month;
  // an earlier range would put Mar 2026 right after its last month, as if
  // the next month (2024 then Mar 2026). The card says where to look then.
  const forecastPeriod = portfolioForecast.insight?.forecast_period ?? null;
  const monthAfter = (p) => {
    const y = Number(p.slice(0, 4));
    const m = Number(p.slice(5, 7));
    return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
  };
  const forecastBeyondRange = Boolean(forecastPeriod && period && monthAfter(period) < forecastPeriod);
  const forecastNote = forecastBeyondRange
    ? `The forecast is for ${periodLabel(forecastPeriod)}, the month after the latest sales, so it is drawn only `
      + `when the range ends there. How forecasts did in ${periodLabel(startPeriod)} – ${periodLabel(period)}: `
      + '"How far off were the forecasts?" below.'
    : null;
  // The company calendar factor inside the forecast (GET /dashboard's
  // portfolio_forecast.calendar_adjustment, 2026-10-19): the forecast card,
  // the error card and the order plan's cards all say it, from this one block.
  const calendarAdj = portfolioForecast.calendar_adjustment?.applied ? portfolioForecast.calendar_adjustment : null;
  const portfolioSeries = (portfolioForecast.series || [])
    .filter((pt) => !(forecastBeyondRange && pt.period > period))
    .filter((pt) => !(portfolioRealOnly && isPlaceholderPeriod(pt.period, placeholder)))
    .map((pt) => ({
    period: pt.period,
    actual: pt.actual,
    forecast: pt.forecast,
    confidenceLower: pt.confidence_lower,
    confidenceUpper: pt.confidence_upper,
    // The same month's forecast before the calendar factor (its own month only).
    beforeAdjustment: calendarAdj && pt.period === calendarAdj.forecast_period ? calendarAdj.before_pieces : null,
  }));

  const reorderPreview = data.reorder_preview || {};
  const reorderRows = (reorderPreview.rows || []).map((r) => ({
    sku: r.sku_id,
    product: r.product_name,
    urgency: r.urgency,
    orderQty: r.q_i,
    // Why that urgency: the stock it was judged on (0 when the product is
    // missing from the opening count) against its safety stock.
    stock: r.current_stock ?? null,
    safetyStock: r.ss_i ?? null,
    notInCount: Boolean(r.stock_not_in_count),
    // Flagged to check before ordering (review_flag), as the Reorder page
    // flags it (Technical Adviser, 2 Oct 2026: what to order, and what not
    // to order blindly).
    needsReview: r.needs_review === true,
    reviewReasons: r.review_reasons || [],
  }));
  // The planned SKUs' share of the latest month's pieces: this card's own
  // last actual against the Summary card's pieces for the same month.
  const latestPortfolioActual = [...portfolioSeries].reverse().find((pt) => pt.actual != null) || null;
  const salesSnap = kpis.sales_snapshot || null;
  const piecesShare = latestPortfolioActual && salesSnap?.pieces > 0 && salesSnap.period === latestPortfolioActual.period
    ? {
      pct: (latestPortfolioActual.actual / salesSnap.pieces) * 100,
      period: periodLabel(salesSnap.period),
      all: salesSnap.pieces,
      theirs: latestPortfolioActual.actual,
    }
    : null;

  // Hero-strip figures. Each reads the same backend field the widget
  // below it is drawn from, so a card and its chart can never disagree; a
  // missing field renders "—" with the reason, never 0.

  // An account without lp.view gets GET /dashboard with every LP-derived
  // figure left out and lp_hidden set (Yuan's permissions proposal): those
  // cards say why they're empty, and the reorder and policy widgets are
  // not drawn at all rather than drawn with zeros.
  const lpHidden = data.lp_hidden === true;
  // The LP cycle every LP figure on the page belongs to ("Mar 2026"),
  // written "Mar 2026 plan" beside each one.
  const lp = data.lp || {};
  const lpCycleLabel = periodLabel(lp.cycle_date ? String(lp.cycle_date).slice(0, 7) : null);
  const exposure = data.safety_stock_exposure || {};
  // The ring ranks the selected range; plan and safety-stock figures use the
  // Tier A list from their ABC run (t12m_new, DEC-38), so labels name its period.
  // Under All principals safety_stock_exposure.tier_a_count is BOTH
  // principals' Tier A (2026-10-24: 190 = Unilever's products as of Feb 2026
  // + Del Monte's categories as of Dec 2025, tier_a_periods), while the plan
  // and its forecasts (forecast.total_count, 189) are Unilever's alone: Del
  // Monte has no product forecasts and no plan. So the plan's label names
  // Unilever's run, and the safety-stock card names both runs instead of
  // calling all 190 "in the order plan". GET /dashboard sends no count per
  // principal, so the split is said in words, never worked out here.
  const tierPeriods = exposure.tier_a_periods || {};
  const mixedTier = Object.keys(tierPeriods).length > 1;
  const tierPeriodsText = Object.entries(tierPeriods)
    .sort((a, b) => (b[0] === 'Unilever') - (a[0] === 'Unilever'))
    .map(([who, p]) => `${who} as of ${periodLabel(p)}`).join(', ');
  const planTierPeriod = mixedTier ? tierPeriods.Unilever ?? null : exposure.tier_a_period;
  const planTierLabel = planTierPeriod ? `Top sellers as of ${periodLabel(planTierPeriod)}` : 'Top sellers';
  const planTierPhrase = planTierPeriod ? `top sellers as of ${periodLabel(planTierPeriod)}` : 'top sellers';
  const bothTierRuns = Boolean(mixedTier && tierPeriods.Unilever && tierPeriods['Del Monte']);
  // The Below safety stock card's line under its bar, All principals only.
  const belowScopeNote = bothTierRuns
    ? `Unilever's products as of ${periodLabel(tierPeriods.Unilever)} and Del Monte's categories as of `
      + `${periodLabel(tierPeriods['Del Monte'])}. The order plan does not cover Del Monte, so its categories can't be checked.`
    : null;
  const exposureReason = lpHidden
    ? LP_HIDDEN_NOTE
    : exposure.blocked_reason || 'Safety-stock exposure cannot be measured yet';
  // Health tier for the safety-stock card, from the same rate the
  // exposure figures are derived from.
  const ssTier = safetyStockMetricType(kpis.safety_stock_rate ?? null);
  const belowSs = kpiDisplay(
    exposure.below_count ?? null, exposure.below_count == null ? exposureReason : null,
    (v) => `${v.toLocaleString()} of ${(exposure.comparable_count ?? 0).toLocaleString()}`,
    // Two dates meet in this figure — the LP plan's safety stock and the
    // stock count it is checked against (the latest count, stock_counts) —
    // so both are named.
    [
      'Class A SKUs with a stock count',
      lpCycleLabel ? `${lpCycleLabel} plan` : null,
      stockCountedLine(exposure.stock_counts),
      abcCoverage,
    ].filter(Boolean).join(' · ')
  );
  // A range ending before the plan's opening count: the card shows the
  // current plan's figure, like the pending-reorder card, and says it does
  // not follow the date range (safety_stock_exposure.pinned_to_plan).
  const ssPinned = Boolean(exposure.pinned_to_plan) && exposure.below_count != null;
  const ssPinnedFlag = ssPinned ? {
    label: 'Current plan',
    tone: 'info',
    detail: `Safety stock exists only for the ${lpCycleLabel ? `${lpCycleLabel} ` : 'current '}plan, which starts from the `
      + `${periodLabel(exposure.plan_opening_period) || 'latest'} stock count. Your date range ends before that, so this `
      + `card shows the plan's own figure and does not follow the date range.`,
  } : null;
  const belowSsTooltip = `Of the Class A SKUs the ${lpCycleLabel ? `${lpCycleLabel} ` : ''}plan covers that have a `
    + 'stock count, how many hold less than their safety stock — the plan\'s own figure for each SKU, in pieces.';

  // Pending action count — the "what to do" figure in the hero strip. Now
  // the CURRENT LP cycle only: it counted every undecided row ever written,
  // so 179 leftovers from runs going back to 2023-05 were being presented
  // as work awaiting a decision today (429 against the real 250).
  const pendingCount = data.recommendations?.product_count ?? 0;
  // No order plan covers this scope at all: GET /dashboard's lp.cycle_date
  // is null only when the scope has no plan row in any status
  // (backend/lp_cycle.current_cycle), so a fully decided plan still counts
  // as covered. That is Del Monte today: it has no SKU-level sales to
  // forecast. Its "Pending reorders" used to say "0 products, nothing
  // awaiting a decision" and Suggested orders "No pending recommendations",
  // as if a plan existed and were done (audit FE-1, 2026-10-21). Both now
  // say there is no plan, in the Reorder page's own words
  // (ReorderRecommendations.jsx, the empty table).
  const noPlan = !lpHidden && !lp.cycle_date;
  const noPlanNote = pagePrincipal === 'delmonte'
    ? 'The order plan does not cover Del Monte: it has no SKU-level sales to forecast, so there are no reorder recommendations for it.'
    : 'No run of the order plan has produced recommendations for this scope yet.';
  // Non-null only when the live data has moved past the hardcoded ceiling.
  // Only when the layout could not read "today" from GET /data-mode and fell
  // back to dataCoverage.js's month while this payload knows a newer one.
  const coverageStale = staleCoverageNotice(data.latest_data_period, outletLatest);
  // The cards connected (Technical Adviser, 2 Oct 2026): which products
  // matter (ABC card) -> which are at risk (the count below, and the list
  // behind it) -> what to order (Reorder Recs). The list is GET
  // /dashboard's safety_stock_exposure.below_items — the rows the count was
  // taken from — so it opens only when there is a count and its rows.
  const belowItems = exposure.below_items || [];
  const canListAtRisk = !lpHidden && (exposure.below_count ?? 0) > 0 && belowItems.length > 0;
  const openAtRisk = () => setShowAtRisk(true);


  // The range cards (RangeCards.jsx). Class A changes arrive on their own
  // request; only the answer for the range on screen is shown.
  const rangeChanges = classChanges?.key === loaded.key ? classChanges.data : null;
  // Every product link opens SKU Forecast, which needs forecast.view: without it there is no link.
  const openForecast = hasPermission(P.FORECAST_VIEW) ? (sku) => navigate(`/forecast?sku=${encodeURIComponent(sku)}`) : undefined;

  // ── The shared comparison on the inventory card ──────────────────────
  // Stock compares the COUNT at each range's end (a snapshot); with "Same
  // months last year" it is the card's "vs a year ago" box. It says what it
  // compared, and a gap says so instead of a percentage (Del Monte has no
  // stock count from Mar 2024 to Feb 2025).
  const noEarlierData = { deltaLine: `No comparison: the data starts Jan ${preview ? PLACEHOLDER_START.year : FIRST_DATA_YEAR}` };
  const stockCompare = (() => {
    if (!versus || kpis.soh_value == null) return {};
    if (versus.beforeData) return noEarlierData;
    if (!prior) return {};
    if (prior.failed) return { deltaLine: `Could not load ${versus.label} to compare` };
    const then = prior.data?.kpis || {};
    // The backend falls back to the latest count on or before each range's
    // end. The earlier count may sit no further from its range's end than
    // this range's count sits from its own, so the two counts are as far
    // apart as the two ranges and "vs a year ago" means a year. Until
    // 2026-10-21 it only had to fall inside the comparison range: for a
    // whole-year range a Feb 2024 count passed as Dec 2024's, and Del Monte
    // compared Dec 2025 with it, 22 months back, as "a year ago" (audit
    // FE-3; Del Monte has no count from Mar 2024 to Feb 2025). No tolerance
    // is invented: this range's own lag is the allowance, 0 months when its
    // count is in its last month.
    const lagNow = kpis.soh_period ? Math.max(monthsBetween(kpis.soh_period, period).length - 1, 0) : 0;
    const lagThen = then.soh_period ? monthsBetween(then.soh_period, versus.endPeriod).length - 1 : null;
    // The two counts must sit the same distance before their range ends, so
    // they are exactly as far apart as the ranges: an old count could
    // otherwise be met by a CLOSER one, or by itself (Del Monte Mar 2024 –
    // Feb 2025 found Feb 2024 on both sides and showed 0%; audit NEW3-FE-1).
    if (then.soh_value != null && lagThen != null && lagThen >= 0 && lagThen < lagNow
      && then.soh_period >= versus.startPeriod) {
      return {
        deltaLine: `No count a year before the ${periodLabel(kpis.soh_period)} one to compare `
          + `(the nearest is ${periodLabel(then.soh_period)})`,
      };
    }
    if (then.soh_value == null || lagThen == null || lagThen < 0 || lagThen > lagNow
      || then.soh_period < versus.startPeriod) {
      const earliest = monthsBetween(versus.startPeriod, versus.endPeriod).slice(-(lagNow + 1))[0] || versus.endPeriod;
      return {
        deltaLine: earliest === versus.endPeriod
          ? `No stock count in ${periodLabel(versus.endPeriod)} to compare`
          : `No stock count from ${periodLabel(earliest)} to ${periodLabel(versus.endPeriod)} to compare`,
      };
    }
    const thenCounts = (then.stock_counts || []).filter((c) => c.available);
    const thenDayKnown = thenCounts.length === 0 || thenCounts.every((c) => c.counted_on);
    const thenLabel = (thenDayKnown && then.soh_count_date
      ? `vs count of ${dayLabel(then.soh_count_date)}`
      : then.soh_period ? `vs ${periodLabel(then.soh_period)} count` : `vs the end of ${versus.label}`)
      + (then.soh_period && then.soh_period !== versus.endPeriod ? ' (nearest earlier count)' : '')
      + (then.soh_count_note ? ' (a count marked unusual)' : '');
    return comparePill(kpis.soh_value, then.soh_value, thenLabel) || {};
  })();

  // ── Period basis of every card (BasisTag) ─────────────────────────────
  // Which cards move with the date filter, and what the others are pinned
  // to, so a filter change never looks like a card that failed to update.
  const planBasis = {
    label: lpCycleLabel ? `${lpCycleLabel} plan` : 'Current plan',
    follows: false,
    detail: 'Does not change with the date filter: it reads the current order plan, its opening stock count '
      + 'and its Class A list.',
  };
  const rangeBasis = { label: 'Selected range', follows: true, detail: FOLLOWS_RANGE };
  const BASIS = {
    sales: { ...rangeBasis, detail: `${FOLLOWS_RANGE} The big figure is the range's last month; the range total is under it.` },
    stock: {
      label: 'Range-end count',
      follows: true,
      detail: `${FOLLOWS_RANGE} It is the stock count at the end of the selected range, not a total over the range.`,
    },
    plan: planBasis,
    chart: {
      ...rangeBasis,
      detail: `${FOLLOWS_RANGE} The chart shows the selected months and, in a lighter shade, the months they are `
        + 'compared with, from the "Compare with" setting. The panel under it shows each month\'s change.',
    },
    abc: {
      ...rangeBasis,
      // abc_basis.note is left out: it carries fixed counts ("as of 2026-02:
      // 175 here, 189 there") that do not follow the range or the principal
      // (177 and 190 under All principals, Mar 2025 – Feb 2026). The card's
      // own note gives both counts as served.
      detail: `${FOLLOWS_RANGE} Classes are ranked on sales over the whole range.`
        + (data.abc_basis ? ` ${data.abc_basis.label}.` : '')
        + (data.abc_basis?.differs_from_planning_basis && data.abc_basis.planning_basis?.unilever?.label
          ? ` The order plan keeps Unilever's own list instead: ${data.abc_basis.planning_basis.unilever.label}.`
          : ''),
    },
    classChanges: {
      label: 'Range vs a year earlier',
      follows: true,
      detail: `${FOLLOWS_RANGE} It always compares the selected range with the same months a year earlier.`,
    },
    idle: {
      label: 'Range-end count',
      follows: true,
      detail: `${FOLLOWS_RANGE} It reads the stock count at the range's end and the months with no sales before it.`,
    },
    forecast: {
      ...rangeBasis,
      detail: `${FOLLOWS_RANGE} The past months follow the range; the forecast month is the one after the latest `
        + 'sales, drawn when the range ends there.',
    },
    accuracy: { ...rangeBasis, detail: `${FOLLOWS_RANGE} Forecasts are checked against sales in the range's months.` },
    allocation: {
      label: data.allocation?.allocation_year ? `Year ${data.allocation.allocation_year}` : 'Range’s end year',
      follows: true,
      detail: `${FOLLOWS_RANGE} It reads the year the range ends in: that year’s sales so far against its `
        + 'allocation, set from the year before (SSM’s rule).',
    },
  };

  // ── The top row (HeroKpis.jsx): the figures above, side by side ─────────
  const allocation = data.allocation || {};
  const allocMonthName = allocation.latest_month ? periodLabel(allocation.latest_month).split(' ')[0] : null;
  // The annual card does not follow the date range (Audrey, 2026-10-09):
  // the year being planned, its sales so far against the same months of
  // the previous year (allocation.prior_ytd_sales), and the latest month
  // with sales — all from GET /dashboard's allocation block, which reads
  // the same whatever the range.
  const yoy = (() => {
    if (allocation.ytd_sales == null || !allocation.latest_month) return null;
    const y = Number(allocation.latest_month.slice(0, 4));
    const label = allocation.ytd_months === 12
      ? String(y - 1)
      : `${allocation.ytd_months === 1 ? allocMonthName : `Jan–${allocMonthName}`} ${y - 1}`;
    if (allocation.prior_ytd_sales == null) return { note: `No ${label} sales on record to compare with.` };
    if (allocation.prior_ytd_months !== allocation.ytd_months) {
      return { note: `Not like-for-like: ${allocation.ytd_months} months on record now, ${allocation.prior_ytd_months} in ${label}.` };
    }
    return allocation.prior_ytd_sales > 0
      ? { pct: ((allocation.ytd_sales - allocation.prior_ytd_sales) / allocation.prior_ytd_sales) * 100, label }
      : null;
  })();
  const annualLatestMonth = periodLabel(allocation.latest_month);
  const annualTrend = allocation.latest_sales != null ? trendExtras(allocation.trend, CHART_COLORS.salesSeries) : {};
  const rangeSales = kpis.sales_cumulative || {};
  // No sales yet in the year being planned (Del Monte: latest sales Dec 2025,
  // planning 2026): the card's headline falls back to the selected range.
  const annualHasYtd = allocation.ytd_sales != null && allocation.ytd_months > 0;
  // Synthetic months (generated to complete the range, not SSM's files) are
  // named in the banner above the cards. Each figure built on them says so
  // on its own card too (the Technical Adviser: what is real and what is
  // generated must be visible where the number is). Only the selected
  // range's months are known here (kpis.sales_cumulative.synthetic_months).
  const syntheticInRange = rangeSales.synthetic_months || [];
  const syntheticSet = new Set(syntheticInRange);
  const monthsText = (list) => list.map(periodLabel).join(', ');
  const rangeSyntheticMark = syntheticInRange.length > 0
    ? `Includes ${syntheticInRange.length} sample-data month${syntheticInRange.length === 1 ? '' : 's'}`
    : null;
  const latestPrev = allocation.trend?.prev_period;
  const latestSyntheticMark = syntheticSet.has(allocation.latest_month)
    ? `${annualLatestMonth} is a sample-data month`
    : latestPrev && syntheticSet.has(latestPrev) ? `${periodLabel(latestPrev)} is a sample-data month` : null;
  const basisSynthetic = allocation.basis_year
    ? syntheticInRange.filter((m) => m.startsWith(`${allocation.basis_year}-`))
    : [];
  // The planned year's months so far (Jan to the latest month with sales),
  // for the "FY sales so far" figure's own synthetic mark.
  const allocLatestYear = allocation.latest_month ? Number(allocation.latest_month.slice(0, 4)) : null;
  const allocLatestIndex = allocation.latest_month ? Number(allocation.latest_month.slice(5, 7)) : 0;
  const ytdSynthetic = allocLatestYear && allocLatestYear === allocation.allocation_year
    ? Array.from({ length: allocLatestIndex }, (_, i) => `${allocLatestYear}-${String(i + 1).padStart(2, '0')}`)
      .filter((m) => syntheticSet.has(m))
    : [];
  const ytdSyntheticMark = ytdSynthetic.length > 0
    ? `FY ${allocation.allocation_year} sales so far include sample-data months: ${monthsText(ytdSynthetic)}`
    : null;
  const allocSyntheticMark = basisSynthetic.length > 0
    ? `FY ${allocation.basis_year} sales include sample-data months: ${monthsText(basisSynthetic)}`
    : null;
  // The chart's sentence quotes two months; say so when either is synthetic.
  const insightSynthetic = syntheticInRange.filter((m) => (data.sales_vs_stock_insight?.text || '').includes(periodLabel(m)));
  const chartSyntheticNote = insightSynthetic.length > 0
    ? `${monthsText(insightSynthetic)} ${insightSynthetic.length === 1 ? 'is a sample-data month' : 'are sample-data months'}, `
      + 'not SSM\u2019s own figures.'
    : null;
  const annualCard = {
    allocation,
    yoy,
    latest: {
      month: annualLatestMonth,
      value: allocation.latest_sales != null ? formatCompactPesos(allocation.latest_sales) : '—',
      trend: annualTrend.trend || null,
      change: annualTrend.deltaLine ? annualTrend : null,
      blockedReason: allocation.latest_sales == null ? allocation.blocked_reason || null : null,
      synthetic: latestSyntheticMark,
    },
    allocSynthetic: allocSyntheticMark,
    ytdSynthetic: ytdSyntheticMark,
    range: {
      label: rangeSales.label ? `Sales, ${rangeSales.label}` : 'Sales',
      value: rangeSales.value != null && !kpis.sales_blocked_reason ? formatCompactPesos(rangeSales.value) : '—',
      synthetic: rangeSyntheticMark,
    },
    basis: {
      // Without sales in the planned year the tag names the target's year,
      // rather than labelling the range's figures as that year's.
      label: !allocation.allocation_year ? 'Current year'
        : annualHasYtd
          ? `${allocLatestIndex === 1 ? allocMonthName : `Jan–${allocMonthName}`} ${allocation.allocation_year}`
          : `FY ${allocation.allocation_year} target`,
      follows: false,
      detail: (annualHasYtd ? '' : `No FY ${allocation.allocation_year ?? ''} sales are on record yet, so the headline `
        + 'shows the selected range\u2019s sales instead; the allocation target is for that year. ')
        + 'Does not change with the date filter: the year being planned, its sales so far against the same '
        + 'months a year earlier, and the latest month with sales. The allocation is the previous year\u2019s sales '
        + '\u00d7 103/105/108%, one year only, whatever the range.',
    },
    tooltip: salesTooltip,
  };
  // ── The three KPI cards (HeroKpis.jsx, 2026-10-11) ───────────────────
  // Each shows a figure, one supporting line and the date it is for; how a
  // figure is formed, and what moves with the date filter, is in its "?".
  const capitalise = (text) => (text ? text.charAt(0).toUpperCase() + text.slice(1) : null);
  const hasStock = sohValue.value !== '—';
  const inventoryCover = hasStock && cover.value != null
    ? {
      weeks: Number(cover.value),
      provisional: coverProvisional,
      stockValue: cover.stock_value ?? null,
      basis: cover.basis ?? null,
      counted: [coverCountLine === countChip || cover.stock_period === kpis.soh_period ? null : coverCountLine,
        coverageNote(cover.coverage, pagePrincipal)].filter(Boolean).join(' · ') || null,
    }
    : null;
  // When the plan was generated (lp.lp_generated_at), so a figure that moved
  // since yesterday can be traced to a re-run (the LP ran on 19 Oct 2026
  // while the cards were being checked).
  const planRun = lp.lp_generated_at ? dayLabel(String(lp.lp_generated_at).slice(0, 10)) : null;
  // When the served forecasts were written (lp.forecast_generated_at), for the
  // stale-plan note's plain sentence.
  const forecastRun = lp.forecast_generated_at ? dayLabel(String(lp.forecast_generated_at).slice(0, 10)) : null;
  // The plan orders the same gated SKUs the forecast card sums, from their
  // stored forecasts: when those carry the calendar factor, every plan row
  // made after that forecast is built on it. lp.is_stale is true when even
  // one row predates it (2026-10-22: one leftover decided row did), which
  // used to hide the note while 109 of 110 rows carried the factor; the
  // Technical Adviser's sign-off must be visible wherever it moves an order.
  const planRows = lp.row_count ?? 0;
  const olderPlanRows = lp.stale_row_count ?? 0;
  const planCalendarNote = calendarAdj && !lpHidden && lp.cycle_date && planRows > olderPlanRows
    ? `The order quantities are built on the calendar-adjusted forecast (${calendarFactorText(calendarAdj)} for `
      + `${periodLabel(calendarAdj.forecast_period)}, learned from ${calendarYearsText(calendarAdj) || 'earlier years'})`
      + `${calendarSignoffText(calendarAdj.signed_off) ? `, ${calendarSignoffText(calendarAdj.signed_off)}` : ''}`
      + `${olderPlanRows > 0 ? ` (${olderPlanRows.toLocaleString()} of the ${planRows.toLocaleString()} plan rows predate it)` : ''}.`
    : null;
  const planCalendarSummary = calendarAdj && !lpHidden && lp.cycle_date && planRows > olderPlanRows
    ? `${calendarFactorText(calendarAdj)} · ${periodLabel(calendarAdj.forecast_period)}`
      + `${calendarSignoffText(calendarAdj.signed_off) ? ' · review pending' : ''}`
    : null;
  const planLabel = lpCycleLabel ? `${lpCycleLabel} plan${planRun ? ` · run ${planRun}` : ''}` : null;
  // Below safety stock: the count, the SKUs it was checked on, and the two
  // dates that meet in it (the plan's safety stock, the stock count).
  const belowBlocked = belowSs.value === '—';
  const belowTooltip = belowBlocked ? null : [
    belowSsTooltip,
    `${(exposure.comparable_count ?? 0).toLocaleString()} of the ${(exposure.tier_a_count ?? 0).toLocaleString()} `
      + `Class A ${abcUnits}${tierPeriodsText ? ` (${mixedTier ? tierPeriodsText : `as of ${periodLabel(exposure.tier_a_period)}`})` : ''} `
      + 'have both a safety stock in the plan and a stock count. The others can\'t be checked and are left out of both numbers.'
      + (bothTierRuns ? ' Del Monte\'s categories are among them: the order plan does not cover Del Monte.' : ''),
    'A planned SKU missing from the stock count is left out here; the pending-reorders card reads it as 0 on hand, '
      + 'so its Critical count can be higher.',
    'The ABC page judges the same plan on the latest stock count, so its below-safety-stock number can differ.',
    ssPinnedFlag ? ssPinnedFlag.detail
      : `The ${lpCycleLabel ? `${lpCycleLabel} ` : ''}order plan, the latest one. This card does not change with `
        + 'the date filter: safety stock exists only for the current plan.',
    // A method awaiting the Technical Adviser's sign-off, said where it sets
    // the number (Technical Adviser, 2 Oct 2026; CLAUDE.md known open items).
    SAFETY_STOCK_METHOD_NOTE,
  ];
  // Pending reorders: the Reorder page's own three counts, from
  // reorder_preview.action_counts (2026-11-05), so "Act Now" is one number on
  // both pages.
  const actions = lpHidden || noPlan || !(reorderPreview.plan_count > 0) ? null : reorderPreview.action_counts ?? null;
  // What still waits for someone, as the Reorder page counts it: a row with
  // nothing to order has no decision to make.
  const awaitingCount = actions ? actions.act_now + actions.review_later : reorderPreview.pending_count;
  // The whole plan stays the card's figure, so the rows add up to it: a row
  // already decided that orders something is its own row, once there is one.
  const decidedCount = actions ? reorderPreview.plan_count - awaitingCount - actions.no_order : 0;
  const pendingParts = actions ? [
    { key: 'actNow', value: actions.act_now },
    { key: 'reviewLater', value: actions.review_later },
    { key: 'noOrder', value: actions.no_order },
    ...(decidedCount > 0 ? [{ key: 'decided', value: decidedCount }] : []),
  ] : null;
  const openingCount = stockCountedLine(reorderPreview.stock_counts);
  const pendingTooltip = lpHidden ? null : [
    `Order recommendations in the ${planLabel || 'current plan'}: the whole plan, as the Reorder page counts it. `
      + 'A row that has been accepted or dismissed stays in it. '
      + (awaitingCount != null
        ? `${awaitingCount.toLocaleString()} of them still wait for a decision `
          + `(${(reorderPreview.pending_order_qty ?? 0).toLocaleString()} pieces). ` : '')
      + 'Undecided rows from earlier plans are not counted.',
    'Act Now: below the target stock (Critical: below safety stock; Urgent: above it). Review Later: at or above the '
      + 'target stock. No order needed: a suggested order of 0 pieces, so there is no decision to make. '
      + `Stock is the count that opens the plan${openingCount ? ` (${openingCount})` : ''}; a SKU missing from that `
      + 'count is read as 0 on hand.',
    'Pieces to order: each pending row\'s order quantity, rounded up to a whole piece, added together.',
    planBasis.detail,
    planCalendarNote,
  ];
  // Why the plan holds these products and not every top seller (GET
  // /dashboard's forecast block; Sir Catubag, 2 Oct 2026: "what happens to
  // the rest?"): tested, passed, failed the reliability check, too new.
  const fc = data.forecast || {};
  const planScope = !lpHidden && fc.total_count != null && fc.evaluated_count != null && fc.unreliable_count != null
    ? {
      total: fc.total_count,
      evaluated: fc.evaluated_count,
      failed: fc.unreliable_count,
      passed: fc.evaluated_count - fc.unreliable_count,
      gate: fc.mase_gate ?? null,
      // Forecasts exist for Unilever only, so under All the list is named as Unilever's.
      tierLabel: mixedTier ? `Unilever's ${planTierPhrase}` : planTierPhrase,
    }
    : null;
  // Critical reads a planned product missing from the opening count as 0 on
  // hand; the Below safety stock card cannot check those. Said on the card
  // only when the two counts differ by exactly that many.
  const noCount = exposure.uncheckable?.no_stock_count;
  const criticalAddsUp = !lpHidden && !belowBlocked && noCount > 0 && reorderPreview.critical_count != null
    && reorderPreview.critical_count - exposure.below_count === noCount;
  const criticalNote = criticalAddsUp
    ? `${reorderPreview.critical_count} Critical = ${exposure.below_count} below safety stock + ${noCount} not in the stock count.`
    : null;
  if (criticalAddsUp) {
    pendingTooltip.push(`${reorderPreview.critical_count} critical = the ${exposure.below_count} below safety stock + ${noCount} missing from `
      + 'the stock count, which the plan reads as 0 on hand (the Below safety stock card cannot check those).');
  }

  // Months in the range with no sales on record (Del Monte has many). Said
  // once, under the filters, so a short total is never read as a low year.
  const salesTotal = kpis.sales_cumulative;
  const gapMonths = salesTotal?.missing_months || [];
  const rangeGapNote = salesTotal && salesTotal.months_in_range > 1 && gapMonths.length > 0
    ? `${pagePrincipal === ALL_PRINCIPALS ? 'Both principals have' : `${labelForPrincipal(pagePrincipal)} has`} sales on record for `
      + `${salesTotal.months_with_data} of the ${salesTotal.months_in_range} months in this range. `
      // With synthetic data on, Del Monte's charts fill those months from the
      // demonstration, so the list gives way to what is real and what is not.
      + (preview && data.demonstration?.demonstration
        ? `Totals and comparisons count those months only; the charts draw the other ${gapMonths.length} as sample data.`
        : `No sales on record in ${gapMonths.map(periodLabel).join(', ')}: totals and comparisons cover the other months only.`)
    : null;
  // Months whose sales are generated or filled, not SSM's files (counted
  // since 2026-10-11 so the months are complete). Said once, here, so no
  // total on the page passes as SSM's own figure.
  const syntheticMonths = salesTotal?.synthetic_months || [];
  const syntheticNote = syntheticMonths.length > 0
    ? `${syntheticMonths.length} of the ${salesTotal.months_with_data} months of sales in this range are sample data `
      + `(generated to complete the months, not from SSM's files): ${syntheticMonths.map(periodLabel).join(', ')}. `
      + 'Sales totals and comparisons on this page include them.'
    : null;
  const idle = data.idle_stock || {};
  const idleSubtitle = [
    idle.count_date ? `Stock counted ${dayLabel(idle.count_date)}` : idle.count_period ? `${periodLabel(idle.count_period)} count` : null,
    idle.window_start && idle.window_end
      ? `no sale ${periodLabel(idle.window_start)} – ${periodLabel(idle.window_end)}` : null,
    idle.pesos_basis ? `value ${idle.pesos_basis}` : null,
  ].filter(Boolean).join(' · ');
  const overRuns = data.forecast_accuracy?.over_forecast_runs || {};
  const overRunSubtitle = [data.forecast_accuracy?.label, overRuns.rule].filter(Boolean).join(' · ');

  // The list behind the Stock cover card's "Above SSM's 3-week rule"
  // (2026-10-22): GET /dashboard/stock-detail's products holding stock
  // beyond the rule, most pesos above it first, with the count day, the sales
  // months and the price bases stated. Its weeks are in pesos and the card's
  // (Unilever) in pieces, so the footnote names both units.
  const aboveMeta = rangeList?.kind === 'above' ? rangeList.meta : null;
  const aboveTotals = aboveMeta?.totals || null;
  const aboveWeeks = aboveMeta?.policy_weeks ?? kpis.above_policy?.policy_weeks ?? policyWeeks;
  const aboveListProps = {
    title: aboveTotals?.above_rule_pesos != null && aboveTotals.above_rule_products != null
      ? `Above SSM's ${aboveWeeks}-week rule: ${formatCompactPesos(aboveTotals.above_rule_pesos)} in `
        + `${aboveTotals.above_rule_products.toLocaleString()} products`
      : `Above SSM's ${aboveWeeks}-week rule`,
    lede: `Stock beyond ${aboveWeeks} weeks of each product's own sales`,
    subtitle: [
      aboveMeta?.principal ? PRINCIPAL_NAMES[aboveMeta.principal] || aboveMeta.principal : null,
      aboveMeta?.count_date ? `stock counted ${dayLabel(aboveMeta.count_date)}`
        : aboveMeta?.count_period ? `${periodLabel(aboveMeta.count_period)} count (exact date not recorded)` : null,
      aboveMeta?.sales_window
        ? `sales ${periodLabel(aboveMeta.sales_window.start)} – ${periodLabel(aboveMeta.sales_window.end)}` : null,
      aboveMeta?.pesos_basis ? `stock ${aboveMeta.pesos_basis}` : null,
    ].filter(Boolean).join(' · '),
    columns: aboveRuleColumns(aboveWeeks),
    footnote: [
      `Most pesos above the rule first. Above the rule = the product's stock value − ${aboveWeeks} weeks of its average `
        + 'weekly sales; stock is at last purchase price, sales at selling price.',
      // Counted from the rows, so it reconciles with the list: a no-sale
      // product valued at ₱0 has nothing above the rule and is not listed
      // (utils/aboveRuleNote, 2026-10-24).
      Array.isArray(aboveMeta?.items) && aboveMeta.items.length > 0
        ? noSaleNote(aboveMeta.items)
        : aboveTotals?.no_sale_products > 0
          ? `${aboveTotals.no_sale_products.toLocaleString()} products had no sale in those months, so all of their stock counts `
            + 'as above the rule.'
          : null,
      aboveTotals?.weeks_of_cover != null
        ? `In pesos, this stock covers ${aboveTotals.weeks_of_cover.toFixed(1)} weeks of sales`
          + (coverInPieces && cover.value != null
            ? `; the Stock cover card's ${Number(cover.value).toFixed(1)} weeks is in pieces, so the two differ.`
            : '.')
        : null,
    ].filter(Boolean).join(' '),
    onOpenProduct: openForecast,
    openLabel: 'Open its forecast',
  };

  // ── The inventory card's boxes (2026-10-18 redesign) ─────────────────
  // A change in stock is coloured by where cover stands (kpiMath
  // .stockChangeTone): more stock is bad when cover is already past the target.
  const signedPct = (pct) => `${pct >= 0 ? '+' : '−'}${Math.abs(pct).toFixed(1)}%`;
  const coverRatioNow = cover.value != null ? policyRatio(cover.value, policyWeeks) : null;
  const changeCell = (pct, sub, now, then) => ({
    value: signedPct(pct),
    direction: pct > 0 ? 'up' : pct < 0 ? 'down' : null,
    tone: stockChangeTone(pct, coverRatioNow),
    sub,
    // The two pesos figures compared, for the box's "?".
    now: now ?? null,
    then: then ?? null,
  });
  // vs last count: kpis.soh_trend, the card's own counts. The backend passes
  // over a count the team judged unusual and says so (skipped / latest_unusual).
  // When the LATEST count is the unusual one it sends no comparison at all;
  // the card still shows one (the year-ago box beside it compares the same
  // count), from the trend's own last two points, with the warning in its
  // "?" (2026-10-19). "n/a" with no figure invited "why?" for a count that
  // was on record.
  const sohTrend = kpis.soh_trend || null;
  const sohPoints = (sohTrend?.points || []).filter((pt) => pt.value != null);
  const sohLatest = sohPoints.length ? sohPoints[sohPoints.length - 1] : null;
  const sohPrev = sohPoints.length >= 2 ? sohPoints[sohPoints.length - 2] : null;
  const lastCountCell = !sohTrend || ((sohTrend.delta_pct == null || !sohTrend.prev_period) && !sohTrend.latest_unusual)
    ? { reason: 'No earlier count on record' }
    : sohTrend.latest_unusual
      ? (sohLatest && sohPrev && sohPrev.value > 0
        ? {
          ...changeCell(((sohLatest.value - sohPrev.value) / sohPrev.value) * 100, `${periodLabel(sohPrev.period)} count`, sohLatest.value, sohPrev.value),
          note: `This count is marked "needs checking": ${sohTrend.latest_unusual}`,
        }
        : { reason: 'This count is marked unusual, so it is not compared' })
      : changeCell(
        sohTrend.delta_pct,
        `${periodLabel(sohTrend.prev_period)} count${(sohTrend.skipped || []).length > 0 ? ' (skips an unusual count)' : ''}`,
        (sohTrend.points || []).find((pt) => pt.period === sohTrend.latest_period)?.value,
        sohTrend.prev_value,
      );
  // vs a year ago: the shared comparison's count, when it is a year back.
  const yearAgoCell = !versus || versus.shift !== 12
    ? { reason: 'Choose "Same months last year" to compare' }
    : stockCompare.pct != null
      ? changeCell(stockCompare.pct, stockCompare.label.replace(/^vs /, ''), stockCompare.now, stockCompare.then)
      : { reason: stockCompare.deltaLine || `Loading ${versus.label}…` };
  // Not sold in 6 months: GET /dashboard's idle_stock (Unilever only; Del
  // Monte's sales are by category, so it is "—" with the backend's reason,
  // never 0). Its share of the card's value only when both read the same
  // count for the same principals.
  const idleLabel = `Not sold in ${idle.window_rule_months ?? 6} months`;
  const idleCell = idle.blocked_reason || idle.pesos == null
    ? { label: idleLabel, value: null, reason: idle.blocked_reason || 'No figure for this stock count.' }
    : (() => {
      const sameCount = idle.count_period === kpis.soh_period;
      const sameScope = (idle.coverage || []).join() === (kpis.soh_coverage || []).join();
      return {
        label: idleLabel,
        value: idle.pesos,
        share: sameCount && sameScope ? shareOf(idle.pesos, kpis.soh_value) : null,
        stock: kpis.soh_value,
        // The no-sale list's length, for the card's "See the N products".
        products: idle.products ?? 0,
        note: !sameScope ? 'Unilever only.' : !sameCount ? `From the ${periodLabel(idle.count_period)} count.` : null,
      };
    })();

  // The one principal with no per-product plan (real data only: with synthetic
  // data on, those cards show the demonstration, labelled).
  const categoryOnly = pagePrincipal === 'delmonte' && !preview && noPlan;
  const categoryOnlyReasons = categoryOnly ? [...new Set([
    belowSs.contextLine,
    noPlanNote,
    portfolioForecast.scope_label,
    data.forecast_accuracy?.blocked_reason,
    DEL_MONTE_NO_ORDERS_REASON,
    idle.blocked_reason,
  ].filter(Boolean))] : [];
  const idleCounted = idle.blocked_reason ? null
    : idle.count_date ? `Stock counted ${dayLabel(idle.count_date)}`
      : idle.count_period ? `${periodLabel(idle.count_period)} count` : null;
  // The three things to act on, from figures this page already has.
  const abovePolicy = hasStock ? kpis.above_policy : null;
  const actionItems = [
    actions && {
      key: 'orders',
      icon: ShoppingCart,
      label: 'Orders to act on',
      value: actions.act_now.toLocaleString(),
      unit: actions.act_now === 1 ? 'product' : 'products',
      sub: lpCycleLabel ? `${lpCycleLabel} plan` : null,
      tone: actions.act_now > 0 ? 'danger' : null,
      to: '/reorder',
    },
    abovePolicy?.pesos != null && abovePolicy.products > 0 && {
      key: 'above',
      icon: Boxes,
      label: `Stock value above ${abovePolicy.policy_weeks ?? policyWeeks}-week target`,
      value: formatCompactPesos(abovePolicy.pesos),
      sub: `${abovePolicy.products.toLocaleString()} products`,
      onClick: () => openRangeList('above'),
    },
    hasStock && idleCell.value != null && data.idle_stock && {
      key: 'idle',
      icon: PackageX,
      label: `Stock not sold in ${idle.window_rule_months ?? 6} months`,
      value: formatCompactPesos(idleCell.value),
      sub: `${(idleCell.products ?? 0).toLocaleString()} products`,
      onClick: () => jumpTo('idle-stock'),
    },
  ].filter(Boolean);

  return (
    <div className={`dashboard${SHOW_CHART_DESCRIPTIONS ? '' : ' dashboard-plain'}`}>
      <div className="dashboard-content">
        {header}

        {isRefreshing && (
          <RefreshingNote>
            Updating to {startMonth} {startYear} – {endMonth} {endYear}…
          </RefreshingNote>
        )}
        {isRefreshing && <SlowLoadNotice key={requestKey} />}

        {/* The range has no sales, but a stock count stands: the cards stay,
            and this says why the sales figures are blank. */}
        {!isRefreshing && rangeEmpty === 'sales' && (
          <EmptyState
            compact
            role="status"
            icon={CalendarX}
            title={`No sales data for ${startMonth} ${startYear} – ${endMonth} ${endYear}`}
            actions={latestRangeAction}
          >
            <p>{emptyReason} The stock figures below are from the latest count before this range.</p>
          </EmptyState>
        )}

        <div
          className={`dashboard-body${isRefreshing ? ' is-refreshing' : ''}`}
          aria-busy={isRefreshing}
          data-enter-cycle={enterCycle}
        >
          {/* The date picker's ceiling and the app's pinned "today" are a
              hand-edited constant. When the database moves past it, every
              page quietly keeps ending at the old month — so the page says
              so in plain words, and names the one file to edit only to
              admins, who can get it changed. */}
          {coverageStale && (
            <div className="dash-stale-note" role="status">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                <strong>Newer sales data is available than this app shows.</strong>{' '}
                Sales are loaded through {coverageStale.live}, but the date range still ends at{' '}
                {coverageStale.pinned}, so the newest months don&apos;t appear on any page yet.
                {' '}Refresh the page; if this stays, the app could not read the latest month from the server{isAdmin ? ' (GET /data-mode)' : ''}.
              </span>
            </div>
          )}

          {/* The LP's own freshness. q_i and rop_i are solved against the
              forecasts of the day the LP ran; when the forecasts are later
              rewritten (they were, on 2026-09-21, while the LP last ran
              2026-08-24) those two are built on numbers the table no longer
              holds, and ss_i reflects the demand history as of that run.
              Taken off the page 2026-09-24, restored 2026-09-29 at Audrey's
              request until the LP is rerun. It renders only while
              lp.is_stale, so a fresh run hides it without a code change. */}
          {lp.is_stale && (
            // The finding and its size on the note's face; the backend's full
            // reason (when the runs were, and how to clear it) one click down
            // (2026-10-21: the paragraph filled the top of the page).
            // Plain words on the face (2026-10-22, Technical Adviser, 2 Oct
            // 2026: jargon is not a label): the sentence is written here from
            // lp's numbers, since lp.reason names q_i, rop_i, MASE and a
            // script. lp.reason stays in Details for admins only.
            <div className="dash-stale-note" role="status">
              <AlertTriangle size={14} aria-hidden="true" />
              <div className="dash-stale-body">
                <p className="dash-stale-head">
                  <strong>
                    {olderPlanRows > 0 && olderPlanRows < planRows ? 'Part of the order plan' : 'The order plan'}
                    {' '}was made before the latest forecast; ask the team to bring the plan up to date.
                  </strong>
                  {planRows > 0 && olderPlanRows > 0 && (
                    <>
                      {' '}{olderPlanRows.toLocaleString()} of the {planRows.toLocaleString()} suggested orders
                      {lpCycleLabel ? ` in the ${lpCycleLabel} plan` : ''} predate it.
                    </>
                  )}
                </p>
                <details className="dash-stale-more">
                  <summary>Details</summary>
                  <p>
                    {forecastRun ? `The forecast was last updated ${forecastRun}` : 'The forecast was updated after part of the plan'}
                    {planRun ? `; the plan last ran ${planRun}` : ''}.
                    {' '}A re-run updates only the products it plans again; the older orders keep the quantities they were
                    given, so check them on the Reorder page before ordering.
                    {lp.superseded_pending_count > 0 && (
                      <>
                        {' '}{lp.superseded_pending_count.toLocaleString()} undecided orders from earlier plans are not
                        counted here.
                      </>
                    )}
                  </p>
                  {isAdmin && lp.reason && <p>Technical note: {lp.reason}</p>}
                </details>
              </div>
            </div>
          )}

          {/* Hero strip — the four figures that answer "what is happening
              right now": money in, money parked, service risk, and work
              waiting. */}
          <div className="dash-top">
          <div className="dash-context-row">
            <TierBasisLabel short periods={exposure.tier_a_periods} period={exposure.tier_a_period} />
            {hasStock && countChip && <BasisTag label={countChip} follows={false} />}
          </div>
          {/* A count the team judged unusual is kept and says so, once, as the
              API words it (kpis.soh_count_note, Yuan 2026-10-04): the stock
              value, the cover and the plan all read it. */}
          {hasStock && kpis.soh_count_note && (
            <p className="dash-gap-note" role="note">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>{kpis.soh_count_note}</span>
            </p>
          )}
          {/* One principal has category-level sales only, so these cards are
              empty on purpose and are never filled. One note says why; each
              card's own reason is behind its "?". With synthetic data on, the
              cards show what the demonstration gives them, as before. */}
          {categoryOnly && (
            <p className="dash-gap-note" role="note">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                {noPlanNote} Below safety stock, Pending reorders, Forecast demand, How close the forecasts were, Suggested
                orders and Stock with no sale stay empty for that reason.
                <InfoTip label="Why each of these cards is empty">
                  {categoryOnlyReasons.map((line) => <span key={line} className="chart-tip-line">{line}</span>)}
                </InfoTip>
              </span>
            </p>
          )}
          {rangeGapNote && (
            <p className="dash-gap-note" role="note">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>{rangeGapNote}</span>
            </p>
          )}
          {syntheticNote && (
            <p className="dash-gap-note" role="note">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>{syntheticNote}</span>
            </p>
          )}
          {/* What to do first (2026-11-05), then the figures behind it. */}
          <ActionStrip items={actionItems} />
          </div>
          {/* Lead with sales and allocation beside inventory value, then
              move through stock cover, below-safety risk and pending orders. */}
          <div className="hero-kpis dash-section-anchor" id="dash-summary">
            <AnnualSalesCard {...annualCard} pct={allocPct} onPctChange={setAllocPct} onOpenYearly={() => jumpTo('dash-sales')} />
            <InventoryCard
              value={sohValue.value}
              subtitle={inventorySubtitle}
              subtitleTitle={inventorySubtitleTitle}
              asOf={hasStock ? sohCoverage || null : null}
              lastCount={lastCountCell}
              yearAgo={yearAgoCell}
              idle={idleCell}
              tooltip={inventoryTooltip}
              onOpenChart={() => jumpTo('dash-sales')}
              onOpenIdle={idleCell.value != null ? () => openRangeList('idle') : null}
            />
            <StockCoverCard
              cover={inventoryCover}
              reason={cover.blocked_reason || null}
              policyWeeks={policyWeeks}
              salesWindow={coverWindow}
              runningLow={belowBlocked ? null : exposure.below_count}
              onOpenLow={canListAtRisk ? openAtRisk : null}
              // What is still to confirm about the figure, as served: where
              // stock and sales come from (weeks_of_cover.caveat). An unusual
              // count (kpis.soh_count_note) is said once, at the top of the page.
              toConfirm={hasStock ? (cover.caveat ? cover.caveat.split(' · ') : [])
                .map((line) => line && `${capitalise(line)}${/[.!?]$/.test(line) ? '' : '.'}`) : []}
              tooltip={coverTooltip}
              // The pesos beyond the rule, product by product (kpis.above_policy),
              // and the list behind them (GET /dashboard/stock-detail).
              abovePolicy={kpis.above_policy || null}
              onOpenAbove={kpis.above_policy?.products > 0 ? () => openRangeList('above') : null}
            />
            <BelowSafetyCard
              below={belowBlocked ? null : exposure.below_count}
              checked={exposure.comparable_count ?? 0}
              total={exposure.tier_a_count ?? null}
              severity={ssTier === 'danger' ? 'danger' : ssTier === 'watch' ? 'watch' : null}
              asOf={[planLabel, capitalise(stockCountedLine(exposure.stock_counts) || '') === countChip ? null : stockCountedLine(exposure.stock_counts), abcCoverage].filter(Boolean).join(' · ')}
              reason={categoryOnly ? null : belowSs.contextLine}
              tooltip={belowTooltip}
              // The list is safety_stock_exposure.below_items, the rows the
              // count was taken from, so it opens the same SKUs.
              onOpen={canListAtRisk ? openAtRisk : null}
              abcTo={hasPermission(P.ABC_VIEW) ? '/abc' : null}
              // Why the rest can't be checked, by reason (safety_stock_exposure.uncheckable).
              uncheckable={exposure.uncheckable || null}
              // Both principals' Tier A under All (not all of it is in the plan).
              tierLabel={mixedTier ? `Top sellers: ${tierPeriodsText}` : planTierLabel}
              inPlan={!mixedTier}
              totalLabel={abcUnits === 'categories' ? 'top-selling categories' : 'top sellers'}
              scopeNote={belowScopeNote}
              methodNote={SAFETY_STOCK_METHOD_NOTE}
            />
            <PendingReordersCard
              count={lpHidden || noPlan ? null : pendingCount}
              reason={noPlan ? (categoryOnly ? null : noPlanNote) : LP_HIDDEN_NOTE}
              asOf={planLabel}
              parts={pendingParts}
              orderQty={pendingParts ? reorderPreview.total_order_qty : null}
              tooltip={pendingTooltip}
              to="/reorder"
              scope={planScope}
              criticalNote={criticalNote}
            />
          </div>

          {/* Step 1 — what happened: yearly sales beside the monthly sales and
              stock chart, across the full row. */}
          <div className="dash-row dash-row-trend dash-section-anchor" id="dash-sales">
            <Slot kind="Descriptive" hideKind question={<>How have sales and stock <span className="title-accent">changed</span> over time?</>} hint={STORY.sales} basis={BASIS.chart}>
              {/* Two cards in one row (layout pass, 2026-10-12): the Annual
                  View bars at about 40% and the Sales vs Inventory chart at
                  about 60%, stacked where the row is too narrow (.dash-split,
                  a container query, so the menu opening narrows it too). The
                  bars are each calendar year's sales (GET /dashboard's
                  annual_sales). */}
              <div className="dash-split-host">
                <div className="dash-split">
                  <AnnualViewChart annual={preview ? withDemoYears(data.annual_sales, data.demonstration, pagePrincipal) : data.annual_sales} allocation={allocation} note={vatNote} selectedPct={allocPct} />
                  <SalesVsStockWidget data={salesVsStock} gapNote={data.gap_note ?? null} placeholder={placeholder} insight={data.sales_vs_stock_insight} syntheticNote={chartSyntheticNote} note={vatNote} basis={data.sales_vs_stock_basis} compare={chartCompare} range={chartRange} policyWeeks={policyWeeks} />
                </div>
              </div>
            </Slot>
          </div>

          {/* Steps 2 and 3 — which products matter: the classes for the range,
              beside the products that joined or left the top sellers. */}
          <div className={`dash-row ${rangeChanges ? 'dash-row-abc' : 'dash-row-trend'} dash-section-anchor`} id="dash-abc">
            <Slot kind="Descriptive" question={<>Which products bring in <span className="title-accent">most of the sales</span>?</>} hint={STORY.abc} basis={BASIS.abc}>
              <ABCDonutWidget
                data={abcMix}
                revenue={data.abc_revenue}
                rules={data.abc_rules}
                note={placeholderNote(data.abc_revenue?.period)}
                syntheticNote={rangeSyntheticMark
                  ? `The revenue ranked here includes ${syntheticInRange.length} sample-data month${syntheticInRange.length === 1 ? '' : 's'}: ${monthsText(syntheticInRange)}.`
                  : null}
                coverage={abcCoverage}
                units={abcUnits}
                atRisk={canListAtRisk && !ssPinned
                  ? { below: exposure.below_count, measurable: exposure.comparable_count, onOpen: openAtRisk, tierLabel: planTierPhrase }
                  : null}
                onOpenClass={setListedClass}
              />
            </Slot>
            {rangeChanges && (
              <Slot kind="Descriptive" question={<>Which products <span className="title-accent">joined or left</span> the top sellers?</>} hint={STORY.changes} basis={BASIS.classChanges}>
                <ClassChanges changes={rangeChanges} onOpen={openForecast} compact />
              </Slot>
            )}
          </div>

          {/* Steps 4 and 5 — what comes next: the forecast for the top sellers,
              beside how close past forecasts came. */}
          <div className={`dash-row ${data.forecast_accuracy ? 'dash-row-even' : 'dash-row-trend'} dash-section-anchor`} id="dash-forecast">
            <Slot kind="Predictive" question={<>How much will the top sellers <span className="title-accent">sell next</span>?</>} hint={STORY.forecast} realOnly={portfolioRealOnly && demoForecasts.length === 0} basis={BASIS.forecast}>
              <PortfolioForecastWidget
                series={portfolioSeries}
                gatedSkuCount={portfolioForecast.gated_sku_count ?? 0}
                scopeLabel={portfolioForecast.scope_label}
                // The backend's scope_label already says it plainly for Del
                // Monte ("No SKU-level forecasts exist for Del Monte — …").
                // The local sentence only stands in if it is ever missing,
                // so the card can't fall back to a generic "No forecast data".
                emptyReason={
                  categoryOnly ? CATEGORY_ONLY_EMPTY : portfolioForecast.scope_label
                    || (pagePrincipal === 'delmonte'
                      ? 'No SKU-level forecasts for Del Monte — it has no SKU-level sales data, only category sell-out.'
                      : undefined)
                }
                reliability={forecastReliability}
                // Without lp.view there is no planScope (or period), but the
                // count is still Unilever's alone under All principals.
                tierLabel={planScope?.tierLabel ?? (pagePrincipal === ALL_PRINCIPALS ? `Unilever's ${planTierPhrase}` : null)}
                planLabel={lpCycleLabel ? `${lpCycleLabel} plan` : null}
                forecastNote={forecastNote}
                piecesShare={piecesShare}
                calendar={forecastBeyondRange ? null : calendarAdj}
              />
              {demoForecasts.length > 0 && <DemoForecastList forecasts={demoForecasts} canOpenForecast={hasPermission(P.FORECAST_VIEW)} />}
            </Slot>
            {data.forecast_accuracy && (
              <Slot kind="Predictive" question={<>How <span className="title-accent">close</span> were past forecasts?</>} hint={STORY.accuracy} basis={BASIS.accuracy}>
                <ForecastErrorSummaryCard
                  accuracy={data.forecast_accuracy}
                  scope={coverageNote(data.forecast_accuracy.coverage, pagePrincipal)}
                  blockedNote={categoryOnly ? CATEGORY_ONLY_EMPTY : null}
                  onOpenList={(runId) => openRangeList('over', runId)}
                  onOpenCategories={(runId) => openRangeList('category', runId)}
                  principal={principal}
                  calendar={portfolioForecast.calendar_adjustment || null}
                />
              </Slot>
            )}
          </div>

          {/* Steps 6 and 7 — what to do: this cycle's order, beside the money in
              stock that has stopped selling (Sir Catubag, 2 Oct: what to order,
              then what it costs or saves). */}
          {(!lpHidden || data.idle_stock) && (
            <div className={`dash-row ${!lpHidden && data.idle_stock ? 'dash-row-even' : 'dash-row-trend'} dash-row-natural dash-section-anchor`} id="dash-order">
              {!lpHidden && (
                <Slot kind="Prescriptive" question={<>What should we <span className="title-accent">order now</span>?</>} hint={STORY.order} realOnly={preview && realOnly.has('reorder_preview')} basis={BASIS.plan} counted={reorderRows.length > 0 ? (openingCount ? capitalise(openingCount) : countChip) : null}>
                  <ReorderRecommendationWidget
                    // The first three; the Reorder page has every row ("See all suggested orders").
                    rows={reorderRows.slice(0, 3)}
                    // One prop (a second emptyReason below used to override this one).
                    emptyReason={categoryOnly ? CATEGORY_ONLY_EMPTY : pagePrincipal === 'delmonte' ? DEL_MONTE_NO_ORDERS_REASON : noPlan ? noPlanNote : undefined}
                    weights={reorderPreview.lp_weights}
                    cycleLabel={lpCycleLabel}
                    runLabel={planRun ? `run ${planRun}` : null}
                    calendarNote={planCalendarNote}
                    calendarSummary={planCalendarSummary}
                    inputsArePlaceholders={Boolean(data.policy_comparison?.inputs_are_placeholders)}
                  />
                  {demoPlan?.order_plan && (
                    <DemoOrderPlanCard plan={demoPlan.order_plan} kind="delmonte" deadStock={demoPlan.dead_stock || null} />
                  )}
                </Slot>
              )}
              {data.idle_stock && (
                <Slot id="idle-stock" kind="Descriptive" question={<>How much <span className="title-accent">money is stuck</span> in stock that is not selling?</>} hint={STORY.idle} basis={BASIS.idle} counted={idleCounted}>
                  <IdleStockCard
                    idle={data.idle_stock}
                    prior={prior?.data?.idle_stock ?? null}
                    scope={coverageNote(data.idle_stock.coverage, pagePrincipal)}
                    onOpenList={() => openRangeList('idle')}
                    blockedNote={categoryOnly ? CATEGORY_ONLY_EMPTY : null}
                  />
                </Slot>
              )}
            </div>
          )}

          {/* The policy question this project exists to answer, once its
              comparison is corrected (SHOW_POLICY_CARD). */}
          {SHOW_POLICY_CARD && !lpHidden && (
            <div className="dash-row dash-row-trend dash-section-anchor" id="dash-policy">
              <Slot kind="Prescriptive" question={<>Is the <span className="title-accent">3-week rule</span> working?</>} realOnly={preview && realOnly.has('policy_comparison')}>
                <PolicyComparisonWidget comparison={data.policy_comparison} />
              </Slot>
            </div>
          )}

          {/* Where Unilever's two data sets come from (3 Oct 2026 analysis):
              every figure that sets stock against sales rests on this match. */}
          {coverProvisional && (
            <p className="dash-footnote">
              Data note: stock counts are from the Ilocos Sur warehouse; product sales are La Union only; the match is
              unverified with SSM.
            </p>
          )}
          {!lpHidden && (
            <p className="dash-footnote">
              The Reorder page lists every suggested order and puts those below their target stock first,
              under &ldquo;Act now&rdquo;, with the most sales at risk at the top.{' '}
              <Link to="/reorder" className="band-link">Open the Reorder page <ArrowRight size={12} /></Link>
            </p>
          )}
        </div>
      </div>
      <ProductListModal
        isOpen={Boolean(rangeList)}
        onClose={() => setRangeList(null)}
        loading={rangeList?.loading}
        error={rangeList?.error}
        rows={rangeList?.rows || []}
        {...(rangeList?.kind === 'above' ? aboveListProps : rangeList?.kind === 'idle' ? {
          title: data.idle_stock?.window_rule_months ? `Stock with no sale in ${data.idle_stock.window_rule_months} months` : 'Idle stock',
          lede: "Money stuck in stock that isn't moving",
          subtitle: idleSubtitle,
          columns: IDLE_COLUMNS,
          footnote: 'Most stock value first.',
        } : rangeList?.kind === 'category' ? {
          title: 'Forecast misses by category',
          lede: 'Which categories the forecast misses most',
          subtitle: [data.forecast_accuracy?.label, 'Unilever products with a scored forecast',
            data.forecast_accuracy?.pesos_basis ? `pesos at ${String(data.forecast_accuracy.pesos_basis).split(' (')[0]}` : null]
            .filter(Boolean).join(' · '),
          columns: CATEGORY_MISS_COLUMNS,
          firstColumnLabel: 'Category',
          footnote: 'Largest misses in pesos first. A category can be too high in some months and too low in others; '
            + 'the net miss in pieces says which way it leaned overall.',
        } : {
          title: 'Products over-forecast several months in a row',
          lede: 'Where the forecast keeps overshooting',
          subtitle: overRunSubtitle,
          columns: OVER_RUN_COLUMNS,
          footnote: 'Largest surplus first. Click a product to open its forecast.',
          onOpenProduct: openForecast,
          openLabel: 'Open its forecast',
        })}
      />
      <ClassProductsModal
        isOpen={listedClass != null}
        onClose={() => setListedClass(null)}
        tier={listedClass}
        args={{ period, startPeriod, principal }}
        onOpenProduct={openForecast}
        onOpenAbcPage={hasPermission(P.ABC_VIEW) ? () => navigate(`/abc?class=${listedClass}&basis=range`) : undefined}
      />
      <AtRiskProductsModal
        isOpen={showAtRisk && canListAtRisk}
        onClose={() => setShowAtRisk(false)}
        items={belowItems}
        chain={{
          classACount: exposure.tier_a_count ?? null,
          plannedCount: pendingCount || null,
          measurableCount: exposure.comparable_count ?? null,
          belowCount: exposure.below_count ?? null,
          abcMonth: periodLabel(ssPinned ? exposure.tier_a_period : data.abc_revenue?.period),
          planLabel: lpCycleLabel ? `${lpCycleLabel} plan` : null,
          countDay: ssPinned
            ? (exposure.stock_counts || []).filter((c) => c.available && c.counted_on).map((c) => dayLabel(c.counted_on))[0] ?? null
            : countDay,
        }}
        revenueShare={exposure.below_revenue_share ?? null}
        revenueTotal={data.abc_revenue?.ranked_total ?? null}
        onOpenProduct={(sku) => navigate(`/reorder?sku=${encodeURIComponent(sku)}`)}
        onOpenPlan={() => navigate('/reorder')}
      />
    </div>
  );
};

export default Dashboard;
