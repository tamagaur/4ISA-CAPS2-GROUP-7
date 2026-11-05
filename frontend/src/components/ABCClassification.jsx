import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import SectionLede from './ui/SectionLede';
import { Link, useNavigate, useOutletContext, useSearchParams } from 'react-router-dom';
import AbcRangeView from './AbcRangeView';
import { Search, Clock, X, RotateCcw, Tag, Filter, AlertTriangle, Activity, CheckCircle2, Info, Layers, ListOrdered } from 'lucide-react';
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { COLORS, CHART_COLORS, SEMANTIC } from '../theme/colors';
import { chartAnim } from '../theme/motion';
import { GRID_PROPS, usePrefersTexture } from './ChartZoom';
import { getABCClassification } from '../api/abc';
import { getFsn } from '../api/analytics';
import { ParetoCard, AbcFsnMatrix } from './AbcBreakdowns';
import KPICard from './KPICard';
import PageHeader from './ui/PageHeader';
import { ClassBadge } from './ui/StatusBadge';
import DateFilter from './DateFilter';
import { formatDate, formatMonth } from '../utils/formatDate';
import { useBrandLookup } from '../utils/useBrandLookup';
import { labelForPrincipal } from '../principals';
import { latestRunFor, requestedAbcPeriod, shownAbcPeriod, DEL_MONTE_REGROUP_PERIOD } from '../utils/abcMonth';
import { parsePeriod } from '../dataCoverage';
import { isPlaceholderPeriod } from '../dataMode';
import Pagination from './Pagination';
import InfoTip from './InfoTip';
import ProductName from './ProductName';
import RefreshingNote from './RefreshingNote';
import { LoadingStatus, SkeletonChartCard, SkeletonLine, SkeletonStatCards, SkeletonTable } from './Skeleton';
import LoadError, { describeLoadError } from './ui/LoadError';
import SlowLoadNotice from './ui/SlowLoadNotice';
import { useEntranceReplay } from '../theme/useEntranceReplay';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import TierBasisLabel, { currentPeriodFor, isStaleTier, latestPeriod } from './TierBasisLabel';
import './ABCClassification.css';

// Story #43 / Manuscript §3.5.5: "flags SKUs approaching tier boundaries."
// Every rule this page states — the tier cutoffs and the boundary margin —
// comes from GET /abc's `rules` (analytics/classification/abc.py), the
// same numbers the run applied. The legend used to hard-code "3pp" while
// the stored flags used 2pp; stating the backend's own value can't drift.
// Fractions (0-1) from the backend, as a percent: "80%", "18.6%".
const asPct = (fraction, digits = 1) => `${Number((fraction * 100).toFixed(digits))}%`;
const asPp = (fraction) => `${Number((fraction * 100).toFixed(1))}pp`;
// "A makes up the first 80% of revenue, B the next 15%, C the last 5%."
const tierRuleText = (rules) =>
  `Class A makes up the first ${asPct(rules.tier_a_cutoff, 0)} of revenue, `
  + `B the next ${asPct(rules.tier_b_cutoff - rules.tier_a_cutoff, 0)}, C the last ${asPct(1 - rules.tier_b_cutoff, 0)}.`;

// Del Monte regrouped its product categories in Jan 2025 (about 63
// sub-categories became 4-5). In a run from then on, a Del Monte row last
// classified before this month is one of the old sub-categories carried
// forward — not a category that stopped selling. DEL_MONTE_REGROUP_PERIOD
// lives in utils/abcMonth.js since 2026-10-22, so SKU Management applies the
// same cut to its Class A count.

const MONTH_TO_NUM = {
  Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
  Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12',
};

// GET /abc takes a single 'YYYY-MM' classification_period (there's one
// classification run per period, not a range) — the shared date-range
// picker's *end* month/year is what maps onto it, so "Apr-Jun 2026"
// requests the Jun 2026 classification. Omitted (undefined) falls back to
// the backend's own "latest period present" default when the picker's
// applied period isn't available yet.
const toClassificationPeriod = (month, year) =>
  month && year ? `${year}-${MONTH_TO_NUM[month]}` : undefined;

// Product names render verbatim (see SKUManagement.jsx for why the old
// pack-size split was removed).

// Helper to format SKU to 5 digits (SKU-#####)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  return sku;
};

// The code shown under a row's name. A Del Monte row is a product category
// (sku_id carries its path, DEC-03), so it has no SKU code to show — its
// name is the category. Rows saved in recent searches before this field
// existed still carry principal and sku, so they read the same way.
const codeOf = (item) => (item.principal === 'delmonte' ? null : formatSKU(item.sku));

// A month range as the Technical Adviser reads periods: "Mar 2025 – Feb 2026".
const monthRange = (start, end) =>
  start === end ? formatMonth(end) : `${formatMonth(start)} – ${formatMonth(end)}`;

// Class-level aggregation replaces the old per-SKU Pareto chart: with
// 600+ SKUs a per-item bar chart is illegible and not actionable.
// Per class we show two things, both from real fields only (no $ value —
// unit_price is unpopulated on Product_Dimension — and no fabricated
// risk score):
//   1. Revenue Share % (existing revPct, rolled up)
//   2. Stock Status Mix — the % of that class's SKUs sitting in each of
//      the 3 real stock_status buckets (IN STOCK / LOW / CRITICAL).
// Comparing the two surfaces classes that look fine on revenue but are
// stock-unhealthy (or vice versa).
const CLASS_ARCHETYPE = {
  A: 'High-Value, Vital Few',
  B: 'Mid-Value, Secondary',
  C: 'Low-Value, Trivial Many',
};

// Copy for the drill-down panel's footer note — swapped in based on
// whichever class the user has clicked in the chart above. B and C used to
// talk about SKUs "below their target stock", a state the page can't show:
// the reorder plan follows Class A of the latest ranking, so a B or C SKU
// has a target only when it ranks A there (an earlier month on the page).
// The note counts them instead of assuming either way.
const classDrilldownNote = (cat, breakdown) => {
  if (cat === 'A') {
    return 'Top-value SKUs below their safety stock or target stock are the highest-priority reorders — a stockout there has the biggest revenue impact.';
  }
  const withTarget = breakdown
    .filter((r) => r.status === 'IN STOCK' || r.status === 'LOW')
    .reduce((sum, r) => sum + r.count, 0);
  if (withTarget > 0) {
    return `${withTarget.toLocaleString()} of these Class ${cat} SKUs have a target stock because they rank Class A in the latest month, which the reorder plan follows. The rest have none, so the plan won\u2019t flag them if they run out.`;
  }
  return cat === 'B'
    ? 'The reorder plan covers Class A only, so no Class B SKU has a target stock to fall below. Watch the out-of-stock count instead: the plan won\u2019t flag a mid-value SKU that runs out, so it needs a proactive check.'
    : 'The reorder plan covers Class A only, so no Class C SKU has a target stock. These earn the least revenue, but an out-of-stock one is still worth a periodic check, since the plan won\u2019t flag it.';
};

// GET /abc's no_target_code, in the words the drill-down groups by (each
// row's own no_target_reason, with its MASE figure, is in the table). The
// plan's pool is Class A of the latest ranking whose forecast passed the
// accuracy check (scripts/run_lp.py), so these are the ways a SKU misses it.
const NO_TARGET_LABELS = {
  not_class_a: 'Not Class A in the latest ranking (the plan covers Class A only)',
  not_ranked: 'No sales in the latest ranking month',
  accuracy: 'Forecast error in testing was not below the average month-to-month change in its sales before the test months (a check the team adopted, not confirmed by SSM or the adviser)',
  short_history: 'Too little sales history to forecast',
  no_recent_sales: 'No recent sales to forecast from',
  forecast_failed: 'Forecast could not be produced',
  not_measured: 'Forecast accuracy could not be measured',
  no_forecast: 'No forecast',
  no_plan: 'No current reorder plan',
  not_in_plan: 'Passes both checks but is not in the current plan',
};
// What the accuracy check is, in the page's plain words (the same test the
// reorder page states as a test error below the average month-to-month change in sales before the test months). The MASE name
// stays in brackets for the reader who knows it; the cutoff itself is a team
// decision (DEC-46), not confirmed by SSM or the adviser, said beside it (Technical Adviser, 2 Oct
// 2026: plain language; 2026-10-22).
const ACCURACY_CHECK_NOTE = 'The plan only uses forecasts whose error, tested on past months, was below the average month-to-month change in sales before those months '
  + '(MASE below 1). The team adopted this reliability check; it is not confirmed by SSM or the adviser.';

// GET /abc's stock_status values are a COVER-vs-TARGET-STOCK test (rop_i, the LP's target stock since the 2026-09-30 run)
// (backend/routers/abc.py's _stock_status): current stock in pieces against
// the SKU's own target stock from the LP's current cycle. A SKU the LP does
// not plan has no target stock and reads NO ROP — until 2026-09-29 it was
// judged against a flat 100 cases instead. They are NOT the warehouse's
// Active/Inactive flag — that is what the Dashboard's "Active / dead stock by
// ABC tier (warehouse status)" widget shows. Both used to say "In stock", and
// a client could see Category A mostly green on the Dashboard and "IN STOCK:
// 0 SKUs" here for the same month. The backend strings are unchanged; the
// labels below say what each one actually means.
const STATUS_LABELS = {
  'IN STOCK': 'Above target stock',
  LOW: 'Below target stock',
  // CRITICAL is "below safety stock" since kelvin-etl's 2026-10 rule
  // (backend/stock_status.py: below ss_i; before, below half the target
  // with no source). It never meant a zero count: the stock file lists no
  // zero rows, so "Out of stock" here named SKUs holding 22 pieces.
  CRITICAL: 'Below safety stock',
  'NO ROP': 'No target stock',
  'NO DATA': 'No stock record',
  // For an account without lp.view the backend sends ON HAND instead of the
  // three statuses that compare stock with the LP's target stock (Yuan's
  // permissions proposal: LP figures follow lp.view everywhere).
  'ON HAND': 'Stock on hand',
};
const statusLabel = (status) => STATUS_LABELS[status] || status;

// The Reorder page's ?urgency= value for each stock status it shares
// (backend/stock_status.py's URGENCY: below safety stock = critical, below
// target = urgent, at or above target = planned). The drill-down's counts
// link there (2026-10-22).
const REORDER_URGENCY = { CRITICAL: 'critical', LOW: 'urgent', 'IN STOCK': 'planned' };

// Colours follow the app-wide SEMANTIC rule (theme/colors.js): green =
// healthy (above target stock), amber = watch (below it), red = act now (below
// safety stock), slate = no data. NO DATA is its own status, not folded into
// CRITICAL — Inventory_Fact_Real only covers a subset of classified
// products, so "no record yet" and "confirmed zero stock" stay distinct.
const STOCK_STATUS_COLORS = {
  'IN STOCK': SEMANTIC.healthy,
  LOW: SEMANTIC.watch,
  CRITICAL: SEMANTIC.act,
  'NO ROP': SEMANTIC.notPlanned,
  'NO DATA': SEMANTIC.noData,
  'ON HAND': SEMANTIC.notPlanned,
};

// The statuses GET /abc can send, in drill-down order: with the LP's target
// stock, or without it (no lp.view).
const STATUSES_WITH_ROP = ['CRITICAL', 'LOW', 'IN STOCK', 'NO ROP', 'NO DATA'];

// The movement class as the table prints it; the badge's hover says why (fsnTitle).
const FSN_LABEL = { F: 'Fast', S: 'Slow', N: 'Non-moving' };
const STATUSES_WITHOUT_ROP = ['CRITICAL', 'ON HAND', 'NO DATA'];

const ClassAggregateTooltip = ({ active, payload, lpHidden, periodLabel, unit }) => {
  if (active && payload && payload.length) {
    const point = payload[0].payload;
    // Swatch + ink rows: the coloured square carries identity, the words
    // stay in text ink (a light status hue is illegible as text on the
    // white bubble).
    const row = (color, label, value) => (
      <p className="chart-tooltip-row">
        <span className="chart-tooltip-swatch" style={{ backgroundColor: color }} aria-hidden="true" />
        {label}: <strong>{value}</strong>
      </p>
    );
    return (
      <div className="abc-pareto-tooltip">
        <p className="abc-pareto-tooltip-title">{point.label}</p>
        {point.revenueTotal != null
          && row(COLORS[`abc${point.cat}`], `Share of ${periodLabel ? `${periodLabel} ` : ''}revenue`, `${point.revenueTotal.toFixed(1)}%`)}
        {lpHidden ? (
          <>
            {row(STOCK_STATUS_COLORS['ON HAND'], statusLabel('ON HAND'), `${point.onHandPct.toFixed(0)}%`)}
            {row(STOCK_STATUS_COLORS.CRITICAL, statusLabel('CRITICAL'), `${point.criticalPct.toFixed(0)}%`)}
          </>
        ) : (
          <>
            {row(STOCK_STATUS_COLORS['IN STOCK'], statusLabel('IN STOCK'), `${point.inStockPct.toFixed(0)}%`)}
            {row(STOCK_STATUS_COLORS.LOW, statusLabel('LOW'), `${point.lowPct.toFixed(0)}%`)}
            {row(STOCK_STATUS_COLORS.CRITICAL, statusLabel('CRITICAL'), `${point.criticalPct.toFixed(0)}%`)}
            {row(STOCK_STATUS_COLORS['NO ROP'], statusLabel('NO ROP'), `${point.noRopPct.toFixed(0)}%`)}
          </>
        )}
        {row(STOCK_STATUS_COLORS['NO DATA'], statusLabel('NO DATA'), `${point.noDataPct.toFixed(0)}%`)}
        <p className="abc-pareto-tooltip-line" style={{ color: CHART_COLORS.axisLabel }}>
          {point.skuCount.toLocaleString()} {unit} ({point.skuSharePct.toFixed(0)}% of all classified)
        </p>
      </div>
    );
  }
  return null;
};

// Cold-load placeholder in the shape of the real page, top to bottom: four
// summary cards, the Pareto chart and its drill-down, the brand Pareto and
// movement matrix, the filter bar and the 7-column SKU table — so the
// layout doesn't jump when the rows arrive. Mirrors DashboardSkeleton's
// approach with this page's classes.
const ABCSkeleton = () => (
  <div className="abc-body" aria-hidden="true">
    <div className="abc-summary-grid">
      <SkeletonStatCards count={4} cardClassName="kpi-card" />
    </div>
    <div className="abc-analysis-row">
      <SkeletonChartCard className="abc-pareto-container abc-analysis-chart" variant="bars" height={260} />
      <SkeletonChartCard className="abc-pareto-container abc-analysis-drilldown" variant="list" rows={3} height={260} />
    </div>
    <div className="abc-breakdown-row">
      <SkeletonChartCard className="abcb-card" variant="bars" height={220} />
      <div className="abcb-card skeleton-card">
        <SkeletonLine variant="title" />
        <SkeletonLine width="62%" height="0.7rem" />
        <SkeletonTable rows={3} columns={4} />
      </div>
    </div>
    <div className="abc-filters-row">
      <SkeletonLine width="100%" height="2.25rem" />
    </div>
    <div className="data-table-card">
      <SkeletonTable rows={8} columns={7} />
    </div>
  </div>
);

const ABCClassification = () => {
  // One classification run exists per month, and GET /abc only ever read
  // the END of the shared date range — so this page used to make people
  // pick a 6-month range whose start did nothing. It now keeps its own
  // single month, seeded from the dashboard range's end month on mount,
  // and never writes back to the shared range (same local-state pattern
  // as SKUForecast.jsx's own picker).
  const dashboardRange = useOutletContext() || {};
  // Without lp.view the stock statuses carry no target-stock comparison
  // (ON HAND instead), so the chart, legend and drill-down show those.
  const { hasPermission } = usePermissions();
  const lpHidden = !hasPermission(P.LP_VIEW);
  // The drill-down's status counts open the Reorder page, which needs lp.view too.
  const canOpenReorder = !lpHidden;
  // A product's name opens its sales history and forecast (SKU Forecast), so
  // the table leads somewhere. Unilever SKUs only: a Del Monte row is a
  // category, which has no product series to open.
  const navigate = useNavigate();
  const canOpenForecast = hasPermission(P.FORECAST_VIEW);
  const openForecast = (item) => (canOpenForecast && item.principal === 'unilever' && item.sku
    ? () => navigate(`/forecast?sku=${encodeURIComponent(item.sku)}`)
    : undefined);
  // Shared principal scope (Topbar's segmented control). Refetches on
  // change via this page's load effect deps.
  const { principal } = dashboardRange;
  // The month the person picked ('YYYY-MM'), or null: then the page follows
  // the dashboard range's last month, whatever the principal (FE-6). Only
  // the picker and its Clear change this (utils/abcMonth.js says why).
  const [pickedPeriod, setPickedPeriod] = useState(null);
  const requestedPeriod = requestedAbcPeriod(
    pickedPeriod, toClassificationPeriod(dashboardRange.endMonth, dashboardRange.endYear),
  );
  const isCustomMonth = pickedPeriod != null;

  const [rawData, setRawData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Try again on a failed load re-runs the request below.
  const [attempt, setAttempt] = useState(0);
  const [classificationPeriod, setClassificationPeriod] = useState(null);
  // This principal's latest classification run, from its own response: the picker's ceiling.
  const [latestRun, setLatestRun] = useState({ principal: null, period: null });
  // Preview mode only (src/dataMode.js): the payload's placeholder window.
  // A run for one of those months is computed on request from placeholder
  // sales (backend/routers/abc.py), and every label that names it says so.
  const [placeholder, setPlaceholder] = useState(null);
  // Products in scope ABC has never ranked at or before this period (no
  // sales in any run) — counted by the backend, not listed, since they have
  // no tier to show.
  const [unclassifiedCount, setUnclassifiedCount] = useState(null);
  // The run's rules, per-tier measured shares and the manuscript's Pareto
  // check (§3.4.4.2.2), all from GET /abc — nothing on this page restates
  // them in its own copy.
  const [rules, setRules] = useState(null);
  const [tierSummary, setTierSummary] = useState([]);
  // Each principal's own ABC run ({ 'Unilever': '2026-02', 'Del Monte': '2025-12' }): under
  // All principals the two differ, and a row is current against ITS principal's run.
  const [tierAPeriods, setTierAPeriods] = useState({});
  const [paretoCheck, setParetoCheck] = useState(null);
  // When the stock was counted and which LP plan the target stock comes
  // from (GET /abc's stock_count_dates / planning_cycle_date, 2026-10-03):
  // the Technical Adviser asked that every stock figure state its count
  // date — the file filed as "Mar 2026" was counted on 6 Apr 2026.
  const [stockCountDates, setStockCountDates] = useState({});
  const [planCycle, setPlanCycle] = useState(null);
  // Which request the rows currently on screen came from — null until the
  // first one lands. Distinguishes "nothing to show yet" (cold load, needs
  // a skeleton) from "showing the previous answer while a new one loads"
  // (refetch, keep it), which `loading` alone cannot: it is true for both.
  const [loadedKey, setLoadedKey] = useState(null);
  // What the picker shows: the run on screen once its answer is this
  // request's, else the month asked for ({ month: 'Feb', year: 2026 }).
  const shownMonth = parsePeriod(shownAbcPeriod(
    requestedPeriod, classificationPeriod, loadedKey === `${requestedPeriod ?? ''}|${principal ?? ''}`,
  )) || { month: dashboardRange.endMonth, year: dashboardRange.endYear };

  // Arriving from the Dashboard's ABC card (/abc?class=B): the page opens
  // on that class — the table filtered to it and narrowed to this run's
  // ranking, so its row count is the count the dashboard card showed — and
  // scrolls to the table.
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedClass = ['A', 'B', 'C'].includes(searchParams.get('class')) ? searchParams.get('class') : null;
  // Ranking basis: one month's ABC run (the default, with stock status and
  // movement classes), or the dashboard's selected range (AbcRangeView, the
  // ranking the dashboard's ABC card draws). ?basis=range opens the range,
  // which is where the dashboard's class list sends people, so counts match.
  // The range basis reads GET /dashboard/pareto and /yoy, which need dashboard.view; this page needs abc.view.
  const canRank = hasPermission(P.DASHBOARD_VIEW);
  const basis = canRank && searchParams.get('basis') === 'range' ? 'range' : 'month';
  const setBasis = (next) => {
    const params = new URLSearchParams(searchParams);
    if (next === 'range') params.set('basis', 'range'); else params.delete('basis');
    setSearchParams(params, { replace: true });
  };
  const rangeStartPeriod = toClassificationPeriod(dashboardRange.startMonth, dashboardRange.startYear);
  const rangeEndPeriod = toClassificationPeriod(dashboardRange.endMonth, dashboardRange.endYear);
  const rangeLabel = dashboardRange.startMonth && dashboardRange.endMonth
    ? `${dashboardRange.startMonth} ${dashboardRange.startYear} – ${dashboardRange.endMonth} ${dashboardRange.endYear}`
    : 'the selected range';
  const classTableRef = useRef(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState(linkedClass || 'ALL');
  const [brandFilter, setBrandFilter] = useState('ALL');
  const [fsnFilter, setFsnFilter] = useState('ALL');
  // Off by default: the table lists every SKU's most recent tier. On, it
  // narrows to the SKUs ranked in THIS run — what the page showed before
  // last-known tiers, and the only set whose Rev % values sum to 100%.
  const [currentRunOnly, setCurrentRunOnly] = useState(Boolean(linkedClass));

  // Table pagination — the full SKU table can run 600+ rows, which is
  // slow to render and hard to scan in one scroll. PAGE_SIZE_OPTIONS
  // lets the user trade off rows-per-page vs. number of pages; default
  // matches the old "show everything" feel most closely while still
  // capping the DOM node count per render.
  const PAGE_SIZE_OPTIONS = [25, 50, 100];
  const scrolledToClass = useRef(false);
  useEffect(() => {
    if (!linkedClass || loading || scrolledToClass.current || !classTableRef.current) return;
    scrolledToClass.current = true;
    classTableRef.current.scrollIntoView({ block: 'start', behavior: 'auto' });
  }, [linkedClass, loading]);
  const [pageSize, setPageSize] = useState(25);
  const [currentPage, setCurrentPage] = useState(1);

  // Which class's stock-status drill-down is showing below the chart.
  // Defaults to 'A' — Category A is the highest-value tier (the first 80%
  // of revenue) and the one a reviewer most wants to see on
  // first load, not the long-tail Class C. Still swappable via any
  // class's bar or the tab buttons.
  const [selectedClass, setSelectedClass] = useState(linkedClass || 'A');
  // Hatch the CRITICAL segments only when the reader asked for a
  // non-colour channel (high-contrast / forced-colors) — see ChartZoom.
  const wantsTexture = usePrefersTexture();

  const [isComboboxOpen, setIsComboboxOpen] = useState(false);
  const [highlightedSKUId, setHighlightedSKUId] = useState(null);
  const comboboxRef = useRef(null);

  // Persistent Recently Searched SKUs
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_recent_abc_searches');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    // last_known: each SKU's most recent tier at or before this month, the
    // same rule SKU Management uses, so the two pages count the same SKUs.
    // Only-this-run used to leave two thirds of the catalogue off the page
    // (a SKU with no sales in the month simply isn't ranked in it).
    getABCClassification({ classification_period: requestedPeriod, principal, view: 'last_known' })
      .then((res) => {
        if (cancelled) return;
        setRawData(res.items || []);
        setClassificationPeriod(res.classification_period || null);
        setPlaceholder(res.data_mode?.placeholder ?? null);
        setUnclassifiedCount(res.unclassified_count ?? null);
        setRules(res.rules ?? null);
        setTierSummary(res.tier_summary || []);
        setTierAPeriods(res.tier_a_periods || {});
        setParetoCheck(res.pareto_check ?? null);
        setStockCountDates(res.stock_count_dates || {});
        setPlanCycle(res.planning_cycle_date ?? null);
        setLoadedKey(`${requestedPeriod ?? ''}|${principal ?? ''}`);
        setLatestRun({ principal, period: latestRunFor(res.tier_a_periods, principal === 'all' ? null : labelForPrincipal(principal)) });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(describeLoadError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [requestedPeriod, principal, attempt]);

  // GET /abc has no brand field; this was hardcoded 'Unilever' (the
  // principal) on every row. Real brand comes from the product master.
  const brandLookup = useBrandLookup(principal);

  // Map API shape -> the row shape the rest of this page renders.
  const sourceData = useMemo(
    () =>
      rawData.map((item) => ({
        // Row key. product_key is unique per item; sku_id is only a label and
        // was '' for every Del Monte (category-grain) row before the backend
        // fell back to category_path — 85 rows sharing one React key.
        id: item.product_key ?? `${item.principal}:${item.sku_id}`,
        sku: item.sku_id,
        productKey: item.product_key,
        principal: item.principal,
        // A Del Monte row is a product category (sku_id carries its path),
        // and many old sub-categories have no name, so the path is the name
        // then. A Unilever SKU with no name shows its code alone
        // (ProductName's fallback) rather than "Unknown Product".
        product: item.product_name || (item.principal === 'delmonte' ? item.sku_id : ''),
        brand: brandLookup?.get(String(item.sku_id)) ?? null,
        cat: item.tier,
        // The run this row's tier and shares come from. When it is older than
        // the page's period the tier is carried forward: the SKU had no sales
        // in the later runs, so it was not re-ranked.
        catPeriod: item.tier_period,
        isCurrent: item.tier_period === currentPeriodFor(item.principal, tierAPeriods, classificationPeriod),
        // Carried forward more than 6 months before the page's run: marked stale. Display only.
        isStale: item.tier_period !== currentPeriodFor(item.principal, tierAPeriods, classificationPeriod)
          && isStaleTier(item.tier_period, latestPeriod(tierAPeriods, classificationPeriod)),
        // revenue_share / cumulative_share come from the API as 0-1 fractions
        // (see analytics/classification/abc.py); everything downstream here
        // (table cells, chart axis 0-100, tooltip) expects 0-100 percentages.
        // For a carried-forward row this is its share of ITS OWN month's
        // revenue, so it is labelled with that month and never summed into
        // this run's totals.
        revPct: (item.revenue_share ?? 0) * 100,
        cumulativePct: (item.cumulative_share ?? 0) * 100,
        // Distance to a tier cutoff in an old run says nothing about the next
        // review, so the flag only counts on current-run rows.
        nearBoundary: !!item.boundary_flag
          && item.tier_period === currentPeriodFor(item.principal, tierAPeriods, classificationPeriod),
        status: item.stock_status,
        // Why the LP's current cycle gives this SKU no target stock (GET
        // /abc's _no_target_reason). Null when it has one, or without lp.view.
        noTargetReason: item.no_target_reason ?? null,
        noTargetCode: item.no_target_code ?? null,
      })),
    [rawData, brandLookup, classificationPeriod, tierAPeriods]
  );

  // FSN (fast / slow / non-moving) per product over the 12 observed months
  // up to this page's run — GET /fsn, joined to the rows by product_key.
  // Fetched once the ABC response lands, since its window ends at that
  // response's classification period. A classified product with no FSN
  // row sold nothing in the window, which is non-moving by definition.
  const fsnKey = `${principal ?? ''}|${classificationPeriod ?? ''}`;
  // `windows` is GET /fsn's {principal: {start, end}}: the months the
  // movement classes were judged over, which the matrix and column state.
  const [fsn, setFsn] = useState({ key: null, byKey: new Map(), rules: null, windows: {}, error: false });
  useEffect(() => {
    if (!classificationPeriod) return undefined;
    let cancelled = false;
    getFsn({ principal, period: classificationPeriod })
      .then((res) => {
        if (cancelled) return;
        setFsn({
          key: fsnKey,
          byKey: new Map((res?.items || []).map((i) => [i.product_key, i])),
          rules: res?.rules ?? null,
          windows: res?.windows || {},
          error: false,
        });
      })
      .catch(() => { if (!cancelled) setFsn({ key: fsnKey, byKey: new Map(), rules: null, windows: {}, error: true }); });
    return () => { cancelled = true; };
  }, [principal, classificationPeriod, fsnKey]);
  const fsnLoaded = fsn.key === fsnKey && !fsn.error;
  const fsnOf = useCallback((row) => {
    if (!fsnLoaded) return null;
    return fsn.byKey.get(row.productKey) ?? { fsn: 'N', adi: null, months_with_sales: 0, months_observed: null, noSaleInWindow: true };
  }, [fsn, fsnLoaded]);
  // "Mar 2025 – Feb 2026" for one principal; each principal's own window
  // when the rows span both (their data ends in different months).
  // `fsnWindowMonths` says how many of those months had data: Del Monte's
  // sell-out has gaps, so its 12 observed months span more of the calendar.
  const fsnWindowEntries = fsnLoaded ? Object.entries(fsn.windows || {}) : [];
  const fsnWindowText = fsnWindowEntries.length === 0
    ? null
    : fsnWindowEntries.length === 1
      ? monthRange(fsnWindowEntries[0][1].start, fsnWindowEntries[0][1].end)
      : fsnWindowEntries.map(([p, w]) => `${labelForPrincipal(p)} ${monthRange(w.start, w.end)}`).join('; ');
  const fsnWindowMonths = fsnWindowEntries.length === 1 ? fsnWindowEntries[0][1].observed_months : null;
  const fsnTitle = (f) => {
    const label = { F: 'Fast-moving', S: 'Slow-moving', N: 'Non-moving' }[f.fsn];
    if (f.noSaleInWindow) return `${label} — no sale in ${fsnWindowText || 'the 12 months with data up to this run'}`;
    if (f.fsn === 'N') {
      return `${label} — no sale in the last 6 months with data (sold in ${f.months_with_sales} of the ${f.months_observed} months with data)`;
    }
    // Counted from the first sale in the window, as ADI is: a category
    // launched mid-window that has sold every month since is regular.
    const span = f.active_months ?? f.months_observed;
    const since = span < f.months_observed ? ' since its first sale in the window' : '';
    const sold = `sold in ${f.months_with_sales} of ${span} months with data${since}`;
    const cadence = f.adi == null ? '' : f.adi <= 1 ? ', every month' : `, a sale every ${f.adi.toFixed(1)} months on average`;
    return `${label} — ${sold}${cadence}`;
  };

  // Handle click outside combobox to close dropdown
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (comboboxRef.current && !comboboxRef.current.contains(e.target)) {
        setIsComboboxOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const catACount = sourceData.filter(d => d.cat === 'A').length;
  const catBCount = sourceData.filter(d => d.cat === 'B').length;
  const catCCount = sourceData.filter(d => d.cat === 'C').length;
  const carriedCountOf = (cat) => sourceData.filter(d => d.cat === cat && !d.isCurrent).length;
  const currentRunCount = sourceData.filter(d => d.isCurrent).length;

  // Del Monte is ranked by product category, not SKU — its sales data has no
  // SKU column — so with the Topbar on Del Monte every noun that names a row
  // says "category". The All view lists both principals' rows, so its
  // column header names both.
  const isDelMonte = principal === 'delmonte';
  const hasDelMonteRows = sourceData.some((d) => d.principal === 'delmonte');
  // `unit` is what a count on this page counts, said beside the number.
  const rowNoun = isDelMonte
    ? { one: 'category', many: 'categories', header: 'Category', count: 'Categories', CAPS: 'CATEGORIES', unit: 'categories' }
    : {
      one: 'SKU',
      many: 'SKUs',
      header: hasDelMonteRows ? 'Product / category' : 'Product',
      count: hasDelMonteRows ? 'SKUs / categories' : 'SKUs',
      CAPS: 'SKUS',
      unit: hasDelMonteRows ? 'SKUs / categories' : 'SKUs',
    };

  // The run's month, as every share on the page names it ("Feb 2026").
  const periodLabel = classificationPeriod ? formatMonth(classificationPeriod) : null;
  // The run(s) the month view's counts come from: "Feb 2026", or each
  // principal's own run under All principals ("Unilever Feb 2026 and Del
  // Monte Dec 2025").
  const runEntries = Object.entries(tierAPeriods || {});
  const runText = runEntries.length > 1
    ? runEntries.map(([name, p]) => `${name} ${formatMonth(p)}`).join(' and ')
    : periodLabel;
  // The stock count the statuses compare. Unilever's only: Del Monte's rows
  // here are categories, which have no stock record (the chart says so), so
  // its count date would label figures that aren't there.
  const stockCountDate = isDelMonte ? null : (stockCountDates.unilever ?? null);
  // "Stock counted Apr 6, 2026 · target stock from the Mar 2026 plan" — the
  // period line of the cover chart, drill-down and table column. The plan
  // half needs lp.view (GET /abc sends no cycle without it).
  // The stock is always the LATEST count, whichever month is picked here or
  // range on the Dashboard (GET /abc reads no other), so it says that in
  // plain words (Technical Adviser, 2 Oct 2026: a page follows the filter or
  // says plainly what period it shows; 2026-10-22).
  const stockBasisText = [
    stockCountDate && `Stock: latest count (${formatDate(stockCountDate)}), not the month or range you selected`,
    !lpHidden && !isDelMonte && planCycle && `target stock from the ${formatMonth(planCycle)} plan`,
  ].filter(Boolean).join(' · ');
  // The Dashboard and Reorder pages judge the plan on the count that opens
  // it; this page reads the latest count, so the same question ("how many
  // Class A products are below safety stock?") gets a different number here
  // (43 against 10 for the Mar 2026 plan, checked 2026-10-12). Said beside
  // the count date rather than left for a reader to trip over.
  const otherCountNote = !lpHidden && !isDelMonte && planCycle && stockCountDate
    ? 'The Dashboard and Reorder pages judge the plan on the count that opens it, so their numbers can differ.'
    : null;
  // The same, short enough for the table's column header.
  const coverHeaderText = [
    stockCountDate && `latest count, ${formatDate(stockCountDate)}`,
    !lpHidden && !isDelMonte && planCycle && `${formatMonth(planCycle)} plan`,
  ].filter(Boolean).join(' · ');

  // This run's measured shares for one tier, from GET /abc's tier_summary,
  // naming the group they describe: the card's headline counts carried-
  // forward rows too, while the shares are of the rows ranked in this run
  // ("152 · 18.6% of SKUs" read as 152 of something; it was 132 of 710).
  // sku_share is null when the rows span both principals (their revenue
  // shares are fractions of two different totals), so only the count is
  // stated then.
  const measuredShares = (tier) => {
    const s = tierSummary.find((t) => t.tier === tier);
    if (!s) return null;
    const ranked = s.sku_count - (s.carried_forward_count || 0);
    const when = periodLabel ? ` in ${periodLabel}` : ' in this run';
    return s.sku_share != null
      ? `${ranked.toLocaleString()} ranked${when} (${asPct(s.sku_share)} of ${currentRunCount.toLocaleString()}) · `
        + `${asPct(s.revenue_share_total)} of ${periodLabel ? `${periodLabel} ` : ''}revenue`
      : `${ranked.toLocaleString()} ranked${when}`;
  };

  // 'pass' | 'fail' | 'not_applicable' (too few ranked rows for an 80/20
  // check). `passes` is the fallback for a response from before the status.
  const paretoState = paretoCheck ? (paretoCheck.status ?? (paretoCheck.passes ? 'pass' : 'fail')) : null;

  // Carried-forward Del Monte rows from before the Jan 2025 regrouping —
  // explained in a Del Monte-only note, but only for a run after the
  // regrouping: in an earlier run those sub-categories were the live scheme.
  const carriedCount = sourceData.length - currentRunCount;
  const preRegroupCarriedCount = sourceData.filter(
    (d) => d.principal === 'delmonte' && !d.isCurrent && d.catPeriod && d.catPeriod < DEL_MONTE_REGROUP_PERIOD
  ).length;
  const showRegroupNote = isDelMonte && !!classificationPeriod
    && classificationPeriod >= DEL_MONTE_REGROUP_PERIOD && preRegroupCarriedCount > 0;

  const brandsList = ['ALL', ...Array.from(new Set(sourceData.map(d => d.brand).filter(Boolean))).sort()];

  // Current-run SKUs first, ranked by this run's revenue share (which is
  // also A -> B -> C order). Carried-forward SKUs follow, by tier then most
  // recently classified: their shares belong to different months, so
  // ranking them against this run's shares would be meaningless.
  const dataWithCumulative = useMemo(() => {
    const sorted = [...sourceData].sort((a, b) => {
      if (a.isCurrent !== b.isCurrent) return a.isCurrent ? -1 : 1;
      if (a.isCurrent) return b.revPct - a.revPct;
      if (a.cat !== b.cat) return a.cat < b.cat ? -1 : 1;
      if (a.catPeriod !== b.catPeriod) return (b.catPeriod || '') < (a.catPeriod || '') ? -1 : 1;
      return b.revPct - a.revPct;
    });
    return sorted.map((item, index) => ({ ...item, rank: index + 1 }));
  }, [sourceData]);

  // Roll per-item revenue share + stock_status up to the 3 tiers.
  const buildClassAggregates = (items, summary) => {
    const totalCount = items.length;
    // Each principal's shares are fractions of its OWN revenue, so shares
    // from two principals cannot be added (a month both principals ranked
    // read Class A 150.9% under All principals). The cards withhold theirs
    // the same way (GET /abc's sku_share is null then).
    const onePrincipal = new Set(items.filter((d) => d.isCurrent).map((d) => d.principal)).size <= 1;
    return ['A', 'B', 'C'].map((cat) => {
      const catItems = items.filter((d) => d.cat === cat);
      const n = catItems.length || 1; // guard divide-by-zero for an empty tier
      const countOf = (status) => catItems.filter((d) => d.status === status).length;
      const tierRow = summary.find((t) => t.tier === cat);
      return {
        cat,
        label: `Class ${cat}`,
        skuCount: catItems.length,
        skuSharePct: totalCount > 0 ? (catItems.length / totalCount) * 100 : 0,
        // This run's revenue only — a carried-forward share is a fraction of
        // another month's revenue, and adding it would push the three
        // classes past 100% combined. GET /abc's tier_summary figure, the
        // same one the cards show: summing the rows' 4-dp shares here read
        // February's Class B as 14.9% where it is 15.0%.
        revenueTotal: onePrincipal ? (tierRow?.revenue_share_total ?? 0) * 100 : null,
        inStockPct: (countOf('IN STOCK') / n) * 100,
        lowPct: (countOf('LOW') / n) * 100,
        criticalPct: (countOf('CRITICAL') / n) * 100,
        noRopPct: (countOf('NO ROP') / n) * 100,
        onHandPct: (countOf('ON HAND') / n) * 100,
        // Inventory_Fact_Real is a partial load (backend/routers/abc.py) —
        // most products currently have no stock record at all yet. Kept
        // as its own bucket rather than folded into CRITICAL, so the
        // chart doesn't misreport "no data" as "confirmed out of stock".
        noDataPct: (countOf('NO DATA') / n) * 100,
      };
    });
  };

  const buildStockBreakdown = (items, withoutRop) => {
    const total = items.length || 1;
    return (withoutRop ? STATUSES_WITHOUT_ROP : STATUSES_WITH_ROP).map((status) => {
      const count = items.filter((d) => d.status === status).length;
      return { status, count, pct: (count / total) * 100 };
    });
  };

  const classAggregates = useMemo(
    () => buildClassAggregates(dataWithCumulative, tierSummary),
    [dataWithCumulative, tierSummary]
  );
  // Drill-down now follows whichever class is selected (click a bar, or
  // a tab) instead of always being Class C.
  const selectedClassStockBreakdown = useMemo(
    () => buildStockBreakdown(dataWithCumulative.filter((d) => d.cat === selectedClass), lpHidden),
    [dataWithCumulative, selectedClass, lpHidden]
  );
  // Why the selected class's "No target stock" rows have none, grouped by
  // GET /abc's no_target_code, largest group first — the drill-down's count
  // used to stand there with no reason (50 of February's Class A).
  const noTargetGroups = useMemo(() => {
    const counts = new Map();
    dataWithCumulative
      .filter((d) => d.cat === selectedClass && d.status === 'NO ROP' && d.noTargetCode)
      .forEach((d) => counts.set(d.noTargetCode, (counts.get(d.noTargetCode) || 0) + 1));
    return [...counts.entries()]
      .map(([code, count]) => ({ code, count, label: NO_TARGET_LABELS[code] || code }))
      .sort((a, b) => b.count - a.count);
  }, [dataWithCumulative, selectedClass]);

  const filteredData = useMemo(() => {
    return dataWithCumulative.filter(item => {
      const matchesSearch = searchQuery === '' ||
        item.sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (item.brand || '').toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = categoryFilter === 'ALL' || item.cat === categoryFilter;
      const matchesBrand = brandFilter === 'ALL' || item.brand === brandFilter;
      const matchesRun = !currentRunOnly || item.isCurrent;
      const matchesFsn = fsnFilter === 'ALL' || fsnOf(item)?.fsn === fsnFilter;
      return matchesSearch && matchesCat && matchesBrand && matchesRun && matchesFsn;
    });
  }, [dataWithCumulative, searchQuery, categoryFilter, brandFilter, currentRunOnly, fsnFilter, fsnOf]);

  // Whenever the filtered set changes shape (new search, new filter, or
  // the page size itself), snap back to page 1 — staying on e.g. page 4
  // after a filter shrinks the result set would otherwise show a blank
  // page or an out-of-range slice.
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, categoryFilter, brandFilter, currentRunOnly, fsnFilter, pageSize]);

  const totalPages = Math.max(1, Math.ceil(filteredData.length / pageSize));

  // Clamp defensively (e.g. if filteredData shrinks between renders
  // before the reset effect above has run) so slice() below never goes
  // out of range.
  const safeCurrentPage = Math.min(currentPage, totalPages);

  const paginatedData = useMemo(() => {
    const start = (safeCurrentPage - 1) * pageSize;
    return filteredData.slice(start, start + pageSize);
  }, [filteredData, safeCurrentPage, pageSize]);

  const boundaryCount = useMemo(
    () => dataWithCumulative.filter(item => item.nearBoundary).length,
    [dataWithCumulative]
  );

  const handleSelectSuggestion = (item) => {
    setSearchQuery(item.sku);
    setIsComboboxOpen(false);

    // Save to recent searches
    setRecentSearches(prev => {
      const filtered = prev.filter(s => s.id !== item.id);
      const updated = [item, ...filtered].slice(0, 5);
      localStorage.setItem('san2_recent_abc_searches', JSON.stringify(updated));
      return updated;
    });

    // Scroll & Highlight row
    setHighlightedSKUId(item.id);
    setTimeout(() => {
      const el = document.getElementById(`abc-row-${item.id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 80);

    setTimeout(() => {
      setHighlightedSKUId(null);
    }, 2000);
  };

  const hasActiveFilters =
    searchQuery !== '' || categoryFilter !== 'ALL' || brandFilter !== 'ALL' || currentRunOnly || fsnFilter !== 'ALL';

  const handleClearFilters = () => {
    setSearchQuery('');
    setCategoryFilter('ALL');
    setBrandFilter('ALL');
    setFsnFilter('ALL');
    setCurrentRunOnly(false);
  };

  // Hover text for a category badge: which run it came from, and an explicit
  // note when it is carried forward — same wording as SKU Management.
  const catTitle = (item) => {
    if (!item.catPeriod) return `Class ${item.cat}`;
    const when = isPlaceholderPeriod(item.catPeriod, placeholder)
      ? `${formatMonth(item.catPeriod)} (placeholder data)`
      : formatMonth(item.catPeriod);
    if (item.isCurrent) return `Class ${item.cat} — current run (${when})`;
    // Per row, so a Del Monte row keeps its reason in the All view too.
    if (item.principal === 'delmonte' && item.catPeriod < DEL_MONTE_REGROUP_PERIOD) {
      return `Class ${item.cat} — last classified ${when}: an older Del Monte sub-category from before the Jan 2025 regrouping, carried forward`;
    }
    return `Class ${item.cat} — last classified ${when}; no sales since, so this is carried forward${item.isStale ? ' (stale: over 6 months old)' : ''}`;
  };

  const getStatusClass = (status) => {
    switch (status) {
      case 'IN STOCK': return 'pill pill-success';
      case 'LOW': return 'pill pill-warning';
      case 'CRITICAL': return 'pill pill-critical';
      case 'NO ROP': return 'pill pill-neutral';
      case 'NO DATA': return 'pill pill-neutral';
      case 'ON HAND': return 'pill pill-neutral';
      default: return 'pill pill-neutral';
    }
  };

  const getCatBadgeClass = (cat) => {
    switch (cat) {
      case 'A': return 'abc-cat-badge abc-cat-a';
      case 'B': return 'abc-cat-badge abc-cat-b';
      case 'C': return 'abc-cat-badge abc-cat-c';
      default: return 'abc-cat-badge';
    }
  };

  // Rendered in every state (loading, error, loaded) rather than only on
  // success — the date picker lives in this header, so blanking the page
  // while refetching removed the control the user had just changed. Same
  // fix as Dashboard.jsx's `header`.
  const periodPlaceholderNote = isPlaceholderPeriod(classificationPeriod, placeholder)
    ? " — a placeholder month: these classes come from placeholder sales, not SSM's"
    : '';
  // How to read the table's faded rows and its boundary flag; shown above
  // the table (tableLegend below), not in the page's subtitle. "More
  // likely", not "likely": measured, 42% of flagged SKUs change class the
  // next month against 17% of unflagged ones — most flagged SKUs stay put.
  const tableLegend = (
    <p className="ui-note abc-table-legend">
      <Info size={14} aria-hidden="true" />
      <span>
        {isDelMonte
          ? 'Categories with no sales that month keep their most recent tier, shown faded with the month it was set.'
          : 'SKUs with no sales that month keep their most recent category, shown faded with the month it was set.'}
        {rules && (
          <> <AlertTriangle size={12} className="abc-boundary-legend-icon" aria-hidden="true" /> flags a {rowNoun.one} within{' '}
            {asPp(rules.boundary_margin)} of a class cutoff — more likely to change class next month.</>
        )}
      </span>
    </p>
  );
  const basisSwitch = !canRank ? null : (
    <div className="segmented abc-basis-switch" role="tablist" aria-label="Rank by">
      {[['month', 'One month'], ['range', 'Selected range']].map(([value, text]) => (
        <button
          key={value}
          type="button"
          role="tab"
          aria-selected={basis === value}
          className={`segmented-item${basis === value ? ' is-active' : ''}`}
          onClick={() => setBasis(value)}
        >
          {text}
        </button>
      ))}
    </div>
  );
  const header = (
    <div className="abc-page-header">
      <PageHeader
        title="ABC"
        accent="Classification"
        subtitle={basis === 'range'
          ? `${isDelMonte ? 'Product categories' : 'Products'} ranked by sales value over ${rangeLabel} (the dashboard's range).`
            + `${rules ? ` ${tierRuleText(rules)}` : ''}`
          : `${isDelMonte ? 'Product categories' : 'Products'} ranked by sales value`
          + `${classificationPeriod ? `, ${formatMonth(classificationPeriod)}${periodPlaceholderNote}` : ''}.`
          + `${rules ? ` ${tierRuleText(rules)}` : ''}`}
        actions={basis === 'range' ? basisSwitch : (
          <div className="abc-header-actions">
          {basisSwitch}
          <DateFilter
            singleMonth
            ceiling={latestRun.principal === principal ? parsePeriod(latestRun.period) : null}
            localValue={{
              startMonth: shownMonth.month, startYear: shownMonth.year,
              endMonth: shownMonth.month, endYear: shownMonth.year,
            }}
            onLocalChange={(v) => setPickedPeriod(toClassificationPeriod(v.endMonth, v.endYear))}
            onReset={isCustomMonth ? () => setPickedPeriod(null) : undefined}
          />
          </div>
        )}
      />
      {/* The monthly run's basis; a range ranking is not a run. */}
      {basis !== 'range' && <TierBasisLabel periods={tierAPeriods} period={classificationPeriod} />}
      {/* Del Monte's rows are product categories, not SKUs. Said once, up
          front, and it also separates the two meanings of "category" on
          this page: the product category a row IS, and the A/B/C tier it
          was ranked into. */}
      {isDelMonte && (
        <p className="abc-principal-note">
          <strong>Del Monte is ranked by product category, not SKU.</strong> Its sales data has no SKU-level
          detail, so each row below is a product category, and its A/B/C is that category&apos;s ABC class.
        </p>
      )}
      {!isDelMonte && hasDelMonteRows && (
        <p className="abc-principal-note">
          <strong>Del Monte rows are product categories, not SKUs.</strong> Del Monte&apos;s sales data has no
          SKU-level detail, so it is ranked by category.
        </p>
      )}
    </div>
  );

  // `loading` alone can't choose a loading state: it is true for the first
  // request and for every later one. Only the first has nothing to show.
  const isColdLoad = loading && loadedKey === null;
  const isRefreshing = loading && loadedKey !== null;
  const principalLabel = labelForPrincipal(principal);

  // Rebuild the cards when a different response lands. This page used to
  // get the rebuild for free by unmounting its whole tree while loading —
  // that unmount WAS the blank page, so keeping the view means driving the
  // replay explicitly, the same way the dashboard does.
  const enterCycle = useEntranceReplay(loadedKey ?? '');

  if (basis === 'range') {
    return (
      <div className="abc-page">
        <div className="abc-content">
          {header}
          <AbcRangeView
            startPeriod={rangeStartPeriod}
            endPeriod={rangeEndPeriod}
            principal={principal}
            initialClass={linkedClass}
            onShowMonth={() => setBasis('month')}
          />
        </div>
      </div>
    );
  }

  if (isColdLoad) {
    return (
      <div className="abc-page">
        <div className="abc-content">
          {header}
          <LoadingStatus>Loading ABC classification data…</LoadingStatus>
          <SlowLoadNotice />
          <ABCSkeleton />
        </div>
      </div>
    );
  }

  // A failure with nothing behind it is still a full-page message; there is
  // no previous answer to keep. A failure on a REFETCH is reported inline
  // above the retained view instead (below) — throwing away rows someone is
  // reading because a newer request failed loses more than it protects.
  if (error && loadedKey === null) {
    return (
      <div className="abc-page">
        <div className="abc-content">
          {header}
          <LoadError what="the ABC classification" message={error} onRetry={() => setAttempt((n) => n + 1)} />
        </div>
      </div>
    );
  }

  return (
    <div className="abc-page">
      <div className="abc-content">
        {/* Page Header */}
        {header}

        {/* Stale-but-useful: a refetch keeps the previous classification on
            screen instead of replacing the page with a loading line. The
            note says it is stale, pointer-events keeps anyone from acting
            on it, and the entrance replay rebuilds the cards when the new
            rows land. */}
        {isRefreshing && <RefreshingNote>Updating {principalLabel}…</RefreshingNote>}

        {error && (
          <p className="abc-page-subtitle" role="alert">
            Could not update: {error} Showing the last classification that loaded.{' '}
            <button type="button" className="link-button" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
          </p>
        )}

        <div
          className={`abc-body${isRefreshing ? ' is-refreshing' : ''}`}
          aria-busy={isRefreshing}
          data-enter-cycle={enterCycle}
        >

          {/* Summary Cards */}
          {/* The shared KPI card (UI pass): the count, its measured shares
              on one line, carried-forward rows as a second quiet line. */}
          <div className="ui-card ui-card-stack">
            <div className="ui-card-head is-centered">
              <span className="icon-tile" aria-hidden="true"><Layers size={20} /></span>
              <div className="ui-card-head-text"><SectionLede className="ui-card-label">How the products split by value</SectionLede></div>
            </div>
          <div className="kpi-strip abc-summary-grid">
            {['A', 'B', 'C'].map((cat) => (
              <KPICard
                key={cat}
                title={`Class ${cat}`}
                value={{ A: catACount, B: catBCount, C: catCCount }[cat].toLocaleString()}
                unit={rowNoun.unit}
                contextLine={measuredShares(cat) || undefined}
                note={carriedCountOf(cat) > 0 ? `${carriedCountOf(cat).toLocaleString()} carried forward from earlier months` : null}
                accent={{ A: 'var(--color-abc-a)', B: 'var(--color-abc-b)', C: 'var(--color-abc-c)' }[cat]}
                icon={<span className={`abc-kpi-letter abc-kpi-letter-${cat.toLowerCase()}`} aria-hidden="true">{cat}</span>}
              />
            ))}
            <KPICard
              title={`Classified ${rowNoun.many}`}
              value={sourceData.length.toLocaleString()}
              unit={rowNoun.unit}
              contextLine={`${currentRunCount.toLocaleString()} ranked in ${periodLabel ?? 'this run'}`
                + (!isDelMonte && unclassifiedCount > 0 ? ` · ${unclassifiedCount.toLocaleString()} never classified` : '')}
              // Not for Del Monte: its unclassified count is SKU-level product
              // records, which are never ranked one by one (the ranking is by
              // category) — beside a category count it would read as
              // categories missing. Under All, most of the never-classified
              // count is Del Monte item codes, said behind the "?".
              tooltip={!isDelMonte && unclassifiedCount > 0 && hasDelMonteRows
                ? 'The never-classified count includes Del Monte item codes, which are ranked by category, never one by one.'
                : undefined}
              flag={boundaryCount > 0
                ? {
                    label: `${boundaryCount.toLocaleString()} near a class boundary`,
                    detail: `${boundaryCount.toLocaleString()} ${boundaryCount === 1 ? rowNoun.one : rowNoun.many} within `
                      + `${rules ? asPp(rules.boundary_margin) : 'a few points'} of a class cutoff — more likely to change class next month.`,
                  }
                : null}
              icon={<Layers size={20} />}
              accent="var(--color-nav-bg)"
            />
          </div>
          </div>

          {/* Why this Class A count differs from the Dashboard's ring (the
              same thing should give the same number across pages, or say
              why not: Technical Adviser, 2 Oct 2026; 2026-10-22). This view
              counts one month's run on the basis above; the ring and the
              Selected range view rank sales over the dashboard's range. */}
          {classificationPeriod && (
            <p className="ui-note is-info abc-month-vs-range">
              <Info size={14} aria-hidden="true" />
              <span>
                Class A here ({catACount.toLocaleString()} {rowNoun.unit}) comes from the {runText} run{runEntries.length > 1 ? 's' : ''}.
                The Dashboard&apos;s ABC ring{canRank ? ' and the Selected range view rank' : ' ranks'} sales over {rangeLabel} instead,
                so their Class A count can differ.
                {canRank && (
                  <>
                    {' '}
                    <button type="button" className="link-button" onClick={() => setBasis('range')}>
                      Show the range ranking
                    </button>
                  </>
                )}
              </span>
            </p>
          )}

          {/* The manuscript's validation of the classification (§3.4.4.2.2),
              computed by the backend for this run: the revenue earned by the
              top fifth of ranked rows, against the range it has to fall in.
              Below GET /abc's min_items it is 'not_applicable' and shown as a
              neutral note: Del Monte's 4 categories read as a red "fails"
              when the top fifth was simply one category. */}
          {paretoCheck && paretoState === 'not_applicable' && (
            <p className="ui-note is-info">
              <Info size={14} aria-hidden="true" />
              <span>
                <strong>Pareto check not applicable:</strong> {paretoCheck.reason}
              </span>
            </p>
          )}
          {paretoCheck && paretoState !== 'not_applicable' && (
            <p className={`ui-note ${paretoCheck.passes ? 'is-success' : 'is-warning'}`}>
              {paretoCheck.passes
                ? <CheckCircle2 size={14} aria-hidden="true" />
                : <AlertTriangle size={14} aria-hidden="true" />}
              <span>
                <strong>Pareto check {paretoCheck.passes ? 'passes' : 'fails'}:</strong>{' '}
                the top {asPct(paretoCheck.top_fraction, 0)} of {rowNoun.many} ({paretoCheck.top_count.toLocaleString()} of the{' '}
                {paretoCheck.ranked_count.toLocaleString()} ranked) earn {asPct(paretoCheck.revenue_share)} of
                {classificationPeriod ? ` ${formatMonth(classificationPeriod)}` : ''} revenue —{' '}
                {paretoCheck.passes ? 'inside' : 'outside'} the {asPct(paretoCheck.band_low, 0)}–{asPct(paretoCheck.band_high, 0)} range
                a valid classification should fall in.
              </span>
            </p>
          )}

          {/* Why most Del Monte rows read "carried forward": the old
              sub-categories stopped receiving sales under those names when
              Del Monte regrouped in Jan 2025. Del Monte only, and only for a
              run after the regrouping (showRegroupNote). */}
          {showRegroupNote && (
            <p className="abc-principal-note">
              <strong>Del Monte regrouped its product categories in Jan 2025</strong> — about 63 sub-categories
              became 4–5 — so {preRegroupCarriedCount === carriedCount
                ? `the ${preRegroupCarriedCount.toLocaleString()} carried-forward rows`
                : `${preRegroupCarriedCount.toLocaleString()} of the ${carriedCount.toLocaleString()} carried-forward rows`}{' '}
              here are the older sub-categories, last ranked before the change.
            </p>
          )}

          {/* Class Aggregation Chart + interactive drill-down — replaces
              the per-SKU Pareto chart, which wasn't readable/actionable at
              600+ SKUs. Revenue share vs. stock-status mix per class (both
              real fields, no fabricated $ value or risk score). Clicking
              any bar for a class (or its tab below the chart) swaps the
              drill-down table on the right to that class's real
              stock_status counts — it's no longer locked to Class C. */}
          {[{ label: null, classAggregates, selectedClassStockBreakdown }].map((panel) => (
            <div className="abc-analysis-row" key="single">
              <div className="abc-pareto-container abc-analysis-chart">
                <div className="abc-pareto-header">
                  <div className="abc-pareto-title-group">
                    <h3 className="abc-pareto-title">
                      {`${panel.label ? `${panel.label} — ` : ''}${lpHidden ? 'Stock status' : 'Cover vs target stock'}, by class`}
                    </h3>
                    <SectionLede>Which classes have too much or too little stock</SectionLede>
                    {/* The period line (2026-10-03): when the stock was
                        counted and which plan the target stock is from, so
                        no status here reads as "now". */}
                    {stockBasisText && (
                      <p className="abc-pareto-period">
                        {stockBasisText}. Bars: % of each class&apos;s {rowNoun.many}.
                        {otherCountNote && <> {otherCountNote}</>}
                      </p>
                    )}
                    <p className="abc-pareto-subtitle">
                      {isDelMonte ? (
                        <>
                          Del Monte has no stock record or target stock at category grain, so every Del Monte row
                          shows No data here.
                        </>
                      ) : lpHidden ? (
                        <>
                          Whether each SKU has stock. The comparison with its target stock needs the
                          reorder-recommendation permission, which this account doesn&apos;t have.
                        </>
                      ) : (
                        <>
                          Each SKU&apos;s stock, in pieces, against its own target stock from the current order plan.
                          <InfoTip label="What this measures">
                            The plan covers only top sellers (Class A) whose forecast passed the accuracy check; every other SKU
                            shows No target stock, and the ? beside it says why. Not the warehouse&apos;s Active/Inactive
                            flag, which is what the Dashboard&apos;s warehouse-status chart shows.
                          </InfoTip>
                        </>
                      )}
                    </p>
                  </div>
                  <div className="abc-pareto-legend">
                    {lpHidden ? (
                      <div className="abc-pareto-legend-item">
                        <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS['ON HAND'] }} />
                        <span>{statusLabel('ON HAND')}</span>
                      </div>
                    ) : (
                      <>
                        <div className="abc-pareto-legend-item">
                          <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS['IN STOCK'] }} />
                          <span>{statusLabel('IN STOCK')}</span>
                        </div>
                        <div className="abc-pareto-legend-item">
                          <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS.LOW }} />
                          <span>{statusLabel('LOW')}</span>
                        </div>
                      </>
                    )}
                    <div className="abc-pareto-legend-item">
                      <span className="abc-pareto-legend-swatch abc-pareto-legend-swatch--critical" />
                      <span>{statusLabel('CRITICAL')}</span>
                    </div>
                    {!lpHidden && (
                      <div className="abc-pareto-legend-item">
                        <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS['NO ROP'] }} />
                        <span>{statusLabel('NO ROP')}</span>
                      </div>
                    )}
                    <div className="abc-pareto-legend-item">
                      <span className="abc-pareto-legend-swatch" style={{ backgroundColor: STOCK_STATUS_COLORS['NO DATA'] }} />
                      <span>{statusLabel('NO DATA')}</span>
                    </div>
                  </div>
                </div>
                <div className="abc-pareto-chart-wrapper">
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={panel.classAggregates} margin={{ top: 10, right: 20, left: 8, bottom: 0 }} barCategoryGap="30%" barGap={4}>
                      {/* Colorblind safety: CRITICAL and IN STOCK sit right next
                          to each other in this stack, and red/green is the one
                          hue pair ~8% of men (red-green deficiency) can't
                          reliably tell apart. A hatch pattern gives CRITICAL a
                          texture cue that doesn't depend on hue at all, and the
                          white segment borders below mean no boundary in the
                          stack relies on color contrast alone. */}
                      <defs>
                        <pattern id="criticalHatch" patternUnits="userSpaceOnUse" width="7" height="7" patternTransform="rotate(45)">
                          <rect width="7" height="7" fill={STOCK_STATUS_COLORS.CRITICAL} />
                          <line x1="0" y1="0" x2="0" y2="7" stroke="rgba(255,255,255,0.6)" strokeWidth="3" />
                        </pattern>
                      </defs>
                      <CartesianGrid {...GRID_PROPS} />
                      <XAxis
                        dataKey="label"
                        axisLine={{ stroke: CHART_COLORS.gridline }}
                        tickLine={false}
                        tick={{ fill: CHART_COLORS.axisLabel, fontSize: 12, fontWeight: 600 }}
                      />
                      <YAxis
                        domain={[0, 100]}
                        ticks={[0, 20, 40, 60, 80, 100]}
                        tickFormatter={(v) => `${v}%`}
                        axisLine={{ stroke: CHART_COLORS.gridline }}
                        tickLine={{ stroke: CHART_COLORS.gridline }}
                        tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                        label={{
                          value: `% of the class's ${rowNoun.many}`,
                          angle: -90,
                          position: 'insideLeft',
                          style: { textAnchor: 'middle', fill: CHART_COLORS.axisLabel, fontSize: 11 },
                        }}
                      />
                      <Tooltip
                        content={<ClassAggregateTooltip lpHidden={lpHidden} periodLabel={periodLabel} unit={rowNoun.unit} />}
                        cursor={{ fill: '#f7fafc' }}
                      />
                      {/* Was a two-bar-per-class combo: this stock-status stack
                          next to a separate solid "revenue share" bar on the
                          SAME 0-100% axis. Dropped the revenue-share bar
                          (2026-09) — it mixed two different kinds of
                          percentage on one axis (per-class stock composition
                          vs. share-of-portfolio-revenue), which invited a
                          false comparison, and it duplicated what the 4 KPI
                          cards above already say (each tier's measured share
                          of revenue). This chart now has one job: stock-status
                          composition, stacked to 100%. NO DATA sits at the
                          base since it's usually the largest segment right
                          now (partial inventory load) — putting it first
                          keeps the rounded top corner on whichever real
                          status segment is on top. Each stacked segment is
                          clickable and outlines the whole column for
                          whichever class is selected. */}
                      <Bar dataKey="noDataPct" stackId="stockMix" fill={STOCK_STATUS_COLORS['NO DATA']} barSize={44} {...chartAnim(0)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                        {panel.classAggregates.map((entry) => (
                          <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={2} />
                        ))}
                      </Bar>
                      <Bar dataKey="noRopPct" stackId="stockMix" fill={STOCK_STATUS_COLORS['NO ROP']} barSize={44} {...chartAnim(1)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                        {panel.classAggregates.map((entry) => (
                          <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={2} />
                        ))}
                      </Bar>
                      <Bar dataKey="criticalPct" stackId="stockMix" fill={wantsTexture ? "url(#criticalHatch)" : STOCK_STATUS_COLORS.CRITICAL} barSize={44} {...chartAnim(2)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                        {panel.classAggregates.map((entry) => (
                          <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={2} />
                        ))}
                      </Bar>
                      <Bar dataKey="lowPct" stackId="stockMix" fill={STOCK_STATUS_COLORS.LOW} barSize={44} {...chartAnim(3)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                        {panel.classAggregates.map((entry) => (
                          <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={2} />
                        ))}
                      </Bar>
                      <Bar dataKey="inStockPct" stackId="stockMix" fill={STOCK_STATUS_COLORS['IN STOCK']} radius={[4, 4, 0, 0]} barSize={44} {...chartAnim(4)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                        {panel.classAggregates.map((entry) => (
                          <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={2} />
                        ))}
                      </Bar>
                      {/* Zero, so invisible, unless the account lacks lp.view. */}
                      <Bar dataKey="onHandPct" stackId="stockMix" fill={STOCK_STATUS_COLORS['ON HAND']} radius={[4, 4, 0, 0]} barSize={44} {...chartAnim(5)} onClick={(data) => setSelectedClass(data.payload?.cat ?? data.cat)} style={{ cursor: 'pointer' }}>
                        {panel.classAggregates.map((entry) => (
                          <Cell key={entry.cat} stroke={entry.cat === selectedClass ? '#1a202c' : '#fff'} strokeWidth={2} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <p className="abc-drilldown-hint">Click a class's bar above to drill into its {lpHidden ? 'stock status' : 'cover vs target stock'}.</p>
                <div className="abc-class-summary-row">
                  {panel.classAggregates.map((entry) => (
                    <div key={entry.cat} className="abc-class-summary-item">
                      {/* The run's measured shares from GET /abc — the same
                          figures as the cards. The old caption paired a share
                          of ALL classified rows (carried forward included,
                          ~10% for A) with THIS run's revenue (~80%), two
                          populations that overstated the concentration. */}
                      <span className="abc-class-summary-headline">
                        {measuredShares(entry.cat) ?? `${entry.skuCount.toLocaleString()} ${rowNoun.many}`}
                      </span>
                      <span className="abc-class-summary-archetype">{CLASS_ARCHETYPE[entry.cat]}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="abc-pareto-container abc-analysis-drilldown">
                <div className="abc-pareto-header">
                  <h3 className="abc-pareto-title">
                    {`${panel.label ? `${panel.label} — ` : ''}Drill-down · Class ${selectedClass} ${lpHidden ? 'stock status' : 'cover vs target stock'}`}
                  </h3>
                  <SectionLede>Where the stock problems sit within a class</SectionLede>
                </div>
                {stockBasisText && <p className="abc-pareto-period">{stockBasisText}.</p>}
                {/* Tab buttons — same class-switching as clicking the chart,
                    but explicit/tappable for touch and keyboard users. */}
                <div className="segmented abc-drilldown-tabs" role="tablist" aria-label="Select ABC class to drill into">
                  {['A', 'B', 'C'].map((cat) => (
                    <button
                      key={cat}
                      type="button"
                      role="tab"
                      aria-selected={selectedClass === cat}
                      className={`segmented-item${selectedClass === cat ? ' is-active' : ''}`}
                      onClick={() => setSelectedClass(cat)}
                    >
                      Class {cat}
                    </button>
                  ))}
                </div>
                <table className="abc-drilldown-table">
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th className="table-num">{rowNoun.count}</th>
                      <th className="table-num">% of Class {selectedClass} {rowNoun.many}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {panel.selectedClassStockBreakdown.map((row) => (
                      <tr key={row.status}>
                        <td>
                          <span className="abc-drilldown-dot" style={{ backgroundColor: STOCK_STATUS_COLORS[row.status] }} />
                          {statusLabel(row.status)}
                          {row.status === 'NO ROP' && noTargetGroups.length > 0 && (
                            <InfoTip label={`Why Class ${selectedClass} ${rowNoun.many} have no target stock`}>
                              <span className="abc-no-target-tip-title">
                                Why {row.count.toLocaleString()} Class {selectedClass} {row.count === 1 ? rowNoun.one : rowNoun.many} have no target stock
                              </span>
                              {noTargetGroups.map((g) => (
                                <span key={g.code} className="abc-no-target-tip-row">
                                  <span>{g.label}</span>
                                  <strong>{g.count.toLocaleString()}</strong>
                                </span>
                              ))}
                              {noTargetGroups.some((g) => g.code === 'accuracy') && (
                                <span className="abc-no-target-tip-foot">{ACCURACY_CHECK_NOTE}</span>
                              )}
                            </InfoTip>
                          )}
                        </td>
                        <td className="table-num">
                          {/* A status the Reorder page also filters by opens
                              it on that urgency (Technical Adviser, 2 Oct
                              2026: cards connected; 2026-10-22). That page
                              lists every planned product of the urgency, on
                              the count that opens the plan, so its number
                              can differ from this class's here. */}
                          {REORDER_URGENCY[row.status] && row.count > 0 && !isDelMonte && canOpenReorder ? (
                            <Link
                              to={`/reorder?urgency=${REORDER_URGENCY[row.status]}`}
                              className="abc-drilldown-link"
                              title={`Open the ${REORDER_URGENCY[row.status]} products on the Reorder page. It judges stock on the count that opens the plan, so its count can differ.`}
                            >
                              {row.count.toLocaleString()}
                            </Link>
                          ) : row.count.toLocaleString()}
                        </td>
                        <td className="table-num">{row.pct.toFixed(0)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {/* The class notes are SKU reorder guidance; Del Monte rows
                    are categories with no stock or target stock (the chart's
                    subtitle says so), so there is nothing here to act on. */}
                {!isDelMonte && (
                  <p className="abc-page-grain-note">
                    {classDrilldownNote(selectedClass, panel.selectedClassStockBreakdown)}
                  </p>
                )}
                {/* Why the Dashboard's "Below safety stock" can be lower than
                    this table's (2026-10-26): different products, different
                    count. Only figures GET /abc sent are named here; the
                    Dashboard's own counts are not restated. */}
                {!lpHidden && !isDelMonte && stockCountDate && (() => {
                  const classSize = panel.classAggregates.find((c) => c.cat === selectedClass)?.skuCount;
                  return (
                    <p className="abc-page-grain-note">
                      These counts cover {classSize != null ? `all ${classSize.toLocaleString()}` : 'every'} Class {selectedClass}{' '}
                      {rowNoun.many} on the latest stock count ({formatDate(stockCountDate)}). The Dashboard&apos;s
                      Below safety stock card checks only the products in the order
                      plan{planCycle ? ` (${formatMonth(planCycle)} plan)` : ''}, on the stock count that opens that
                      plan, so its count can be lower.
                    </p>
                  );
                })()}
              </div>
            </div>
          ))}

          {/* Brand / category Pareto (D1) and ABC × FSN (D3) — the two
              questions the SKU table alone can't answer. */}
          <div className="abc-breakdown-row">
            <ParetoCard principal={principal} period={classificationPeriod} />
            <AbcFsnMatrix
              rows={sourceData.filter((d) => d.isCurrent)}
              carriedCount={carriedCount}
              fsnOf={fsnOf}
              rules={fsn.rules}
              loaded={fsnLoaded}
              windowText={fsnWindowText && fsnWindowMonths
                ? `${fsnWindowText} (${fsnWindowMonths} months with data)`
                : fsnWindowText}
              periodLabel={periodLabel}
              unit={rowNoun.unit}
            />
          </div>

          {tableLegend}

          {/* Searchable Combobox & Filters Bar */}
          <div className="abc-filters-row">
            {/* Search Combobox */}
            <div className="abc-combobox-container" ref={comboboxRef}>
              <div className="abc-search-wrapper">
                <Search className="abc-search-icon" size={16} />
                <input
                  type="text"
                  placeholder={isDelMonte ? 'Search by category name...' : 'Search by product name, SKU code, or brand...'}
                  value={searchQuery}
                  onFocus={() => setIsComboboxOpen(true)}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setIsComboboxOpen(true);
                  }}
                  className="abc-search-input"
                />
                {searchQuery && (
                  <button className="abc-input-clear-btn" onClick={() => setSearchQuery('')} title="Clear search">
                    <X size={14} />
                  </button>
                )}
              </div>

              {/* Combobox Dropdown Panel */}
              {isComboboxOpen && (
                <div className="abc-combobox-dropdown">
                  {searchQuery.trim() !== '' ? (
                    /* Live Suggestions */
                    <div className="abc-combobox-section">
                      <div className="abc-section-header">
                        <span>SUGGESTIONS ({filteredData.length})</span>
                      </div>
                      {filteredData.length > 0 ? (
                        filteredData.map((item) => (
                          <div
                            key={item.id}
                            className="abc-suggestion-row"
                            onClick={() => handleSelectSuggestion(item)}
                          >
                            <div className="abc-row-middle">
                              <ProductName name={item.product} code={codeOf(item)} className="abc-row-product" />
                            </div>
                            <div className="abc-row-left">
                              {item.brand && <span className="abc-row-brand">{item.brand}</span>}
                              <span className="abc-row-rev">
                                {item.revPct.toFixed(1)}% of {formatMonth(item.isCurrent ? classificationPeriod : item.catPeriod)} revenue
                              </span>
                            </div>
                            <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                          </div>
                        ))
                      ) : (
                        <div className="abc-no-suggestions">No matching products found.</div>
                      )}
                    </div>
                  ) : (
                    /* Quick Access Panel */
                    <div className="abc-combobox-default">
                      {recentSearches.length > 0 && (
                        <div className="abc-combobox-section">
                          <div className="abc-section-header">
                            <Clock size={12} />
                            <span>RECENTLY SEARCHED</span>
                          </div>
                          {recentSearches.map((item) => (
                            <div
                              key={item.id}
                              className="abc-suggestion-row"
                              onClick={() => handleSelectSuggestion(item)}
                            >
                              <div className="abc-row-middle">
                                <ProductName name={item.product} code={codeOf(item)} className="abc-row-product" />
                              </div>
                              {item.brand && (
                                <div className="abc-row-left">
                                  <span className="abc-row-brand">{item.brand}</span>
                                </div>
                              )}
                              <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      <div className="abc-combobox-section">
                        <div className="abc-section-header">
                          <span>TOP ABC CLASSIFIED {rowNoun.CAPS}</span>
                        </div>
                        {filteredData.slice(0, 5).map((item) => (
                          <div
                            key={item.id}
                            className="abc-suggestion-row"
                            onClick={() => handleSelectSuggestion(item)}
                          >
                            <div className="abc-row-middle">
                              <ProductName name={item.product} code={codeOf(item)} className="abc-row-product" />
                            </div>
                            <div className="abc-row-left">
                              {item.brand && <span className="abc-row-brand">{item.brand}</span>}
                              <span className="abc-row-rev">
                                {item.revPct.toFixed(1)}% of {formatMonth(item.isCurrent ? classificationPeriod : item.catPeriod)} revenue
                              </span>
                            </div>
                            <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Filter Controls Row */}
            <div className="abc-filter-controls">
              <div className="abc-filter-select-wrapper">
                <span className="abc-filter-icon-label"><Tag size={12} /> Brand:</span>
                <select
                  value={brandFilter}
                  onChange={(e) => setBrandFilter(e.target.value)}
                >
                  {brandsList.map(b => (
                    <option key={b} value={b}>{b === 'ALL' ? 'All Brands' : b}</option>
                  ))}
                </select>
              </div>

              <div className="abc-filter-select-wrapper">
                <span className="abc-filter-icon-label"><Activity size={12} /> Movement:</span>
                <select value={fsnFilter} onChange={(e) => setFsnFilter(e.target.value)} disabled={!fsnLoaded}>
                  <option value="ALL">All</option>
                  <option value="F">Fast-moving</option>
                  <option value="S">Slow-moving</option>
                  <option value="N">Non-moving</option>
                </select>
              </div>

              <div className="abc-cat-toggle-group" ref={classTableRef}>
                {['ALL', 'A', 'B', 'C'].map(cat => (
                  <button
                    key={cat}
                    className={`abc-cat-toggle-btn ${categoryFilter === cat ? 'active' : ''}`}
                    onClick={() => setCategoryFilter(cat)}
                  >
                    {cat === 'ALL' ? 'ALL' : `Class ${cat}`}
                  </button>
                ))}
              </div>

              <label className="abc-current-run-toggle">
                <input
                  type="checkbox"
                  checked={currentRunOnly}
                  onChange={(e) => setCurrentRunOnly(e.target.checked)}
                />
                This run only
              </label>
            </div>
          </div>

          {/* Active Filter Chips Bar */}
          {hasActiveFilters && (
            <div className="abc-active-chips-row">
              <span className="abc-chips-label">
                <Filter size={12} /> Active Filters:
              </span>

              {searchQuery && (
                <span className="abc-active-chip">
                  Search: "{searchQuery}"
                  <button className="abc-chip-remove" onClick={() => setSearchQuery('')}>
                    <X size={12} />
                  </button>
                </span>
              )}

              {brandFilter !== 'ALL' && (
                <span className="abc-active-chip">
                  Brand: {brandFilter}
                  <button className="abc-chip-remove" onClick={() => setBrandFilter('ALL')}>
                    <X size={12} />
                  </button>
                </span>
              )}

              {categoryFilter !== 'ALL' && (
                <span className="abc-active-chip">
                  Class {categoryFilter}
                  <button className="abc-chip-remove" onClick={() => setCategoryFilter('ALL')}>
                    <X size={12} />
                  </button>
                </span>
              )}

              {fsnFilter !== 'ALL' && (
                <span className="abc-active-chip">
                  Movement: {{ F: 'Fast', S: 'Slow', N: 'Non-moving' }[fsnFilter]}
                  <button className="abc-chip-remove" onClick={() => setFsnFilter('ALL')}>
                    <X size={12} />
                  </button>
                </span>
              )}

              {currentRunOnly && (
                <span className="abc-active-chip">
                  Ranked in {classificationPeriod ? formatMonth(classificationPeriod) : 'this run'} only
                  <button className="abc-chip-remove" onClick={() => setCurrentRunOnly(false)}>
                    <X size={12} />
                  </button>
                </span>
              )}

              <button
                className="abc-clear-all-chips-btn"
                onClick={handleClearFilters}
                title="Reset all filters"
              >
                <RotateCcw size={12} />
                Clear all filters
              </button>
            </div>
          )}

          {/* Table */}
          <div className="ui-card is-flush">
          <div className="ui-card-intro">
            <div className="ui-card-head is-centered">
              <span className="icon-tile" aria-hidden="true"><ListOrdered size={20} /></span>
              <div className="ui-card-head-text"><SectionLede className="ui-card-label">Every product, ranked by sales value</SectionLede></div>
            </div>
          </div>
          <div className="data-table-card ui-card-table">
            <table className="data-table abc-table">
              <thead>
                <tr>
                  <th className="table-num col-fit">#</th>
                  <th className="col-text col-product">{rowNoun.header}</th>
                  <th className="col-fit">Brand</th>
                  <th className="table-center col-fit">Class</th>
                  <th className="table-center col-fit" title={`Fast / Slow / Non-moving over ${fsnWindowText || 'the 12 months with data up to this run'}`}>
                    Movement
                    {fsnWindowText && <span className="abc-th-sub">{fsnWindowText}</span>}
                  </th>
                  {/* A carried-forward row's share is of its own month's
                      revenue, named under its value; the header names the
                      run's month, which every other row's share is of. */}
                  <th className="table-num col-fit" title={`Share of revenue in the run the ${rowNoun.one} was classified in`}>
                    Revenue share (%)
                    {periodLabel && <span className="abc-th-sub">of {periodLabel} revenue</span>}
                  </th>
                  <th className="col-fit" title="Stock, in pieces, against the SKU's target stock in the order plan">
                    {lpHidden ? 'Stock status' : 'Cover vs target'}
                    {coverHeaderText && <span className="abc-th-sub">{coverHeaderText}</span>}
                  </th>
                </tr>
              </thead>
              <tbody>
                {paginatedData.map((item, index) => (
                  <tr
                    key={item.id}
                    id={`abc-row-${item.id}`}
                    className={highlightedSKUId === item.id ? 'highlighted-row-flash' : ''}
                  >
                    <td className="cell-rownum table-num">{(safeCurrentPage - 1) * pageSize + index + 1}</td>
                    <td className="cell-product">
                      <ProductName
                        name={item.product}
                        code={codeOf(item)}
                        onOpen={openForecast(item)}
                        openLabel="Open the sales history and forecast for"
                      />
                    </td>
                    <td className={item.brand ? 'cell-muted' : 'cell-empty'}>{item.brand || '—'}</td>
                    <td className="table-center" title={catTitle(item)}>
                      {/* The warning icon always has a reserved slot, so badges
                          stay in one straight column whether or not a row is
                          near a tier boundary. */}
                      <span className="abc-cat-cell-inner">
                        <ClassBadge tier={item.cat} faded={!item.isCurrent} />
                        {item.isStale && <span className="tier-chip-stale">stale</span>}
                        <span className="abc-boundary-slot">
                          {item.nearBoundary && (
                            <AlertTriangle
                              size={13}
                              className="abc-boundary-icon"
                              aria-label="Near a class boundary"
                            >
                              <title>{`Cumulative revenue ${item.cumulativePct.toFixed(1)}%${rules ? ` — within ${asPp(rules.boundary_margin)} of a class cutoff` : ' — near a class cutoff'}`}</title>
                            </AlertTriangle>
                          )}
                        </span>
                      </span>
                    </td>
                    <td className="table-center">
                      {(() => {
                        const f = fsnOf(item);
                        return f
                          ? <span className={`fsn-badge fsn-${f.fsn}`} title={fsnTitle(f)}>{FSN_LABEL[f.fsn] ?? f.fsn}</span>
                          : <span className="fsn-badge fsn-pending" title="Loading movement class">…</span>;
                      })()}
                    </td>
                    {item.isCurrent ? (
                      <td className="table-num cell-strong">{item.revPct.toFixed(1)}%</td>
                    ) : (
                      <td
                        className="table-num cell-muted"
                        title={`${item.revPct.toFixed(2)}% of ${formatMonth(item.catPeriod)} revenue — no sales in ${formatMonth(classificationPeriod)}, so not part of this run's total`}
                      >
                        {item.revPct.toFixed(1)}%
                        <span className="abc-rev-period">{formatMonth(item.catPeriod)}</span>
                      </td>
                    )}
                    <td>
                      <span className={getStatusClass(item.status)} title={`stock_status: ${item.status}`}>{statusLabel(item.status)}</span>
                      {/* The reason sits on the label it explains. 50 of
                          February's Class A read "No target stock" with no
                          why, beside copy saying the LP plans Class A. */}
                      {item.status === 'NO ROP' && item.noTargetReason && (
                        <InfoTip label={`Why ${item.product || formatSKU(item.sku)} has no target stock`}>
                          {item.noTargetReason}.
                          {item.noTargetCode === 'accuracy' && (
                            <span className="abc-no-target-tip-foot">{ACCURACY_CHECK_NOTE}</span>
                          )}
                        </InfoTip>
                      )}
                    </td>
                  </tr>
                ))}
                {filteredData.length === 0 && (
                  <tr className="table-empty-row">
                    <td colSpan="7">No data for this selection.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <Pagination
            currentPage={safeCurrentPage}
            totalPages={totalPages}
            totalItems={filteredData.length}
            pageSize={pageSize}
            onPageChange={setCurrentPage}
            onPageSizeChange={setPageSize}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
            idPrefix="abc"
          />
          </div>
        </div>
      </div>
    </div>
  );
};

export default ABCClassification;
