import React, { useState, useMemo, useRef, useEffect } from 'react';
import { Link, useNavigate, useOutletContext, useSearchParams } from 'react-router-dom';
import AbcRangeView from './AbcRangeView';
import { Search, Clock, X, RotateCcw, Tag, Filter, AlertTriangle, Info, Layers, ListOrdered } from 'lucide-react';
import { getABCClassification } from '../api/abc';
import { ParetoCard } from './AbcBreakdowns';
import KPICard from './KPICard';
import PageHeader from './ui/PageHeader';
import SectionHeading from './ui/SectionHeading';
import BasisTag from './BasisTag';
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
import {
  CANT_CHECK_YET, NOT_CHECKED, OUT_OF_STOCK, RELIABILITY_SHORT, STOCK_STATUS_LABEL, TO_BE_CONFIRMED,
  abcMonthViewLabel, tierLabel,
} from '../labels';
import { revenueShareBasis } from '../utils/reorderView';
import { shareBarWidth } from '../utils/stockBarScale';
import './ABCClassification.css';

// Story #43 / Manuscript §3.5.5: "flags SKUs approaching tier boundaries."
// Every rule this page states — the tier cutoffs and the boundary margin —
// comes from GET /abc's `rules` (analytics/classification/abc.py), the
// same numbers the run applied. The legend used to hard-code "3pp" while
// the stored flags used 2pp; stating the backend's own value can't drift.
// Fractions (0-1) from the backend, as a percent: "80%", "18.6%".
const asPct = (fraction, digits = 1) => `${Number((fraction * 100).toFixed(digits))}%`;
// "A makes up the first 80% of revenue, B the next 15%, C the last 5%."
const tierRuleText = (rules) =>
  `Class A makes up the first ${asPct(rules.tier_a_cutoff, 0)} of sales, `
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

// Class-level aggregation replaces the old per-product Pareto chart: with
// 600+ products a per-item bar chart is illegible and not actionable.
// Per class: the revenue share and the stock-status mix, both from real
// fields only. (The "High-Value, Vital Few" captions were removed 2026-11-05.)

// Why a product has no target stock (GET /abc's no_target_code), in plain
// words. `main` is the pop-up's first line; `short` is the drill-down's
// grouped list. The backend's own sentence (no_target_reason, with the MASE
// figure where there is one) goes under "Show details". `tbc`: the rule is
// a team decision (DEC-46, MASE below 1) not confirmed by SSM or the adviser.
const NO_TARGET_TEXT = {
  not_class_a: {
    main: 'Not a top seller in the latest ranking. The order plan covers top sellers only.',
    short: 'Not a top seller in the latest ranking',
  },
  not_ranked: {
    main: 'No sales in the month the order plan ranks, so it isn’t a top seller there.',
    short: 'No sales in the month the plan ranks',
  },
  accuracy: {
    main: `${RELIABILITY_SHORT.unreliable}. This product’s forecast test error was larger than the average month-to-month change in its sales before the test months, so the plan doesn’t use it yet.`,
    short: RELIABILITY_SHORT.unreliable,
    hover: 'forecast not reliable yet',
    tbc: true,
  },
  short_history: { main: 'Not enough sales history yet to forecast it.', short: 'Not enough sales history yet', hover: 'not enough sales history' },
  no_recent_sales: { main: 'No sale in the last 6 months, so no order is planned.', short: 'No sale in the last 6 months' },
  forecast_failed: { main: 'Its forecast couldn’t be produced.', short: 'Forecast couldn’t be produced' },
  not_measured: {
    main: `${NOT_CHECKED}: its forecast’s accuracy couldn’t be measured.`,
    short: NOT_CHECKED,
    hover: 'forecast not checked yet',
  },
  no_forecast: { main: 'There is no forecast for it yet.', short: 'No forecast yet' },
  no_plan: { main: 'There is no current order plan yet.', short: 'No current order plan' },
  not_in_plan: {
    main: 'Its forecast passes the check, but the current plan was made before this forecast or ranking.',
    short: 'Made after the current plan',
  },
};
// The accuracy reason's figure for "Show details": "MASE 1.26 (needs below 1)".
// GET /abc sends MASE only inside no_target_reason ("… not passed (MASE 1.26)").
const noTargetDetail = (code, reason) => {
  if (code === 'accuracy') {
    const m = /MASE ([\d.]+)/.exec(reason || '');
    if (m) return `MASE ${m[1]} (needs below 1)`;
  }
  return reason || null;
};
// "12 forecast not reliable yet": a reason's phrase after a count.
const noTargetPhrase = (code) => {
  const text = NO_TARGET_TEXT[code];
  if (!text) return 'no target stock';
  return text.hover ?? text.short.charAt(0).toLowerCase() + text.short.slice(1);
};
const TbcBadge = () => <span className="abc-tbc-badge">{TO_BE_CONFIRMED}</span>;
// One product's "Why … has no target stock" pop-up body.
const NoTargetWhy = ({ code, reason }) => {
  const text = NO_TARGET_TEXT[code];
  const detail = noTargetDetail(code, reason);
  return (
    <span className="abc-no-target-why">
      <span>{text?.main ?? reason}</span>
      {text?.tbc && <TbcBadge />}
      {text && detail && (
        <details className="abc-no-target-details">
          <summary>Show details</summary>
          <span>{detail}</span>
        </details>
      )}
    </span>
  );
};

// GET /abc's stock_status (backend/stock_status.py): the product's stock in
// pieces on the LATEST count against its own safety stock and target stock
// from the LP's current cycle. Not the warehouse's Active/Inactive flag (the
// Dashboard's warehouse-status chart). The words come from labels.js
// (2026-11-06), not the Reorder page's Critical / Urgent, which judge the
// count that opens the plan. Without lp.view the backend sends CRITICAL for
// nothing on hand (backend/routers/abc.py _status_for): "Out of stock".
const statusLabel = (status, lpHidden = false) => (
  status === 'CRITICAL' && lpHidden ? OUT_OF_STOCK : (STOCK_STATUS_LABEL[status] || status)
);

// One colour per status, shared by the stock check's bars and the table's
// badges (2026-11-06; ABCClassification.css .is-<tone>, the app's SEMANTIC
// red / amber / green, grey for no verdict).
const STATUS_TONE = {
  CRITICAL: 'critical', LOW: 'warning', 'IN STOCK': 'success', 'ON HAND': 'success', 'NO ROP': 'neutral', 'NO DATA': 'neutral',
};

// The stock check's bars (2026-11-06): top sellers only, most urgent first.
// `statuses`: the GET /abc values a bar counts; `tone`: the colour of the
// table's badge for them (ui.css --badge-*-fg).
const STOCK_BARS = [
  { key: 'CRITICAL', statuses: ['CRITICAL'], tone: 'critical', hover: 'Stock is below the safety stock.' },
  { key: 'LOW', statuses: ['LOW'], tone: 'warning', hover: 'Stock is at or above the safety stock, but below the target stock.' },
  { key: 'IN STOCK', statuses: ['IN STOCK'], tone: 'success', hover: 'Stock is at or above the target stock.' },
  { key: 'CANT_CHECK', statuses: ['NO ROP', 'NO DATA'], tone: 'neutral' },
];
// Without lp.view: only what the count itself says.
const STOCK_BARS_NO_LP = [
  { key: 'CRITICAL', statuses: ['CRITICAL'], tone: 'critical', hover: 'Nothing on hand in the latest stock count.' },
  { key: 'ON HAND', statuses: ['ON HAND'], tone: 'success', hover: 'Some stock on hand in the latest stock count.' },
  { key: 'NO DATA', statuses: ['NO DATA'], tone: 'neutral', hover: 'Not in the latest stock count.' },
];

// Cold-load placeholder in the shape of the real page, top to bottom: four
// summary cards, the Pareto chart and its drill-down, the brand Pareto,
// the filter bar and the 6-column SKU table — so the
// layout doesn't jump when the rows arrive. Mirrors DashboardSkeleton's
// approach with this page's classes.
const ABCSkeleton = () => (
  <div className="abc-body" aria-hidden="true">
    <div className="abc-summary-grid">
      <SkeletonStatCards count={4} cardClassName="kpi-card" />
    </div>
    <SkeletonChartCard className="abc-stock-check" variant="bars" height={200} />
    <div className="abc-breakdown-row">
      <SkeletonChartCard className="abcb-card" variant="bars" height={220} />
    </div>
    <div className="abc-filters-row">
      <SkeletonLine width="100%" height="2.25rem" />
    </div>
    <div className="data-table-card">
      <SkeletonTable rows={8} columns={6} />
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
  // "About these numbers" opens from a small link beside the subtitle
  // (2026-11-06); closed by default.
  const [aboutOpen, setAboutOpen] = useState(false);
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

  // The table's stock filter, set by the stock check's bars (2026-11-06):
  // { label, statuses, principal } or null. `principal` keeps the table to
  // the rows the bar counted (Unilever only, under All principals).
  const [statusFilter, setStatusFilter] = useState(null);

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
      one: 'product',
      many: 'products',
      header: hasDelMonteRows ? 'Product / category' : 'Product',
      count: hasDelMonteRows ? 'Products / categories' : 'Products',
      CAPS: 'PRODUCTS',
      unit: hasDelMonteRows ? 'products / categories' : 'products',
    };

  // The run's month, as every share on the page names it ("Feb 2026").
  const periodLabel = classificationPeriod ? formatMonth(classificationPeriod) : null;
  // Each principal's own run ({ Unilever: '2026-02', 'Del Monte': '2025-12' }).
  const runEntries = Object.entries(tierAPeriods || {});
  // What the month view ranks (2026-11-06): Unilever the 12 months up to the
  // month picked (TIER_A_BASIS t12m_new, analytics/params.py), Del Monte that
  // one month. Every label that names the ranked period says which.
  const isUnilever = principal === 'unilever';
  const allRunsText = runEntries
    .map(([name, p]) => (name === 'Unilever' ? `Unilever: 12 months to ${formatMonth(p)}` : `${name}: ${formatMonth(p)}`))
    .join('; ');
  // "the last 12 months (to Mar 2026)" / "Mar 2026" / "the latest ranking (…)"
  const windowText = isUnilever
    ? `the last 12 months${periodLabel ? ` (to ${periodLabel})` : ''}`
    : isDelMonte ? (periodLabel ?? 'this month')
      : `the latest ranking${allRunsText ? ` (${allRunsText})` : ''}`;
  // The same, for a table header: "last 12 months to Mar 2026".
  const windowShort = isUnilever
    ? `last 12 months${periodLabel ? ` to ${periodLabel}` : ''}`
    : isDelMonte ? periodLabel : 'latest ranking';
  const notSoldPhrase = isUnilever ? 'not sold in the last 12 months'
    : isDelMonte ? 'not sold this month' : 'not sold in the period ranked';
  // "the ranking of the 12 months to Mar 2026" / "the Mar 2026 ranking".
  const rankingText = isUnilever
    ? `the ranking of the 12 months to ${periodLabel}`
    : isDelMonte ? `the ${periodLabel} ranking` : `the latest rankings (${allRunsText})`;
  // The stock check counts Unilever only, so its share header names
  // Unilever's ranking: "last 12 months to Feb 2026".
  const stockWindowShort = `last 12 months to ${formatMonth(tierAPeriods?.Unilever ?? classificationPeriod)}`;
  // A row's own ranked period, for its hovers.
  const rankedWhenOf = (item, when) => (item.principal === 'unilever' ? `the 12 months to ${when}` : when);
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
  // (43 against 10 for the Mar 2026 plan, checked 2026-10-12). Said once,
  // in "About these numbers" (2026-11-05).
  // The same, short enough for the table's column header.
  const coverHeaderText = [
    stockCountDate && `count ${formatDate(stockCountDate)}`,
    !lpHidden && !isDelMonte && planCycle && `${formatMonth(planCycle)} plan`,
  ].filter(Boolean).join(' · ');
  // Inside the stock check the count's date is in the section's tag, said
  // once (2026-11-06), so the card's own header keeps only the plan.
  const stockPlanText = !lpHidden && !isDelMonte && planCycle ? `${formatMonth(planCycle)} plan` : '';
  // The stock section's "?": "About these numbers"' stock line without the
  // date, which its tag already says.
  const stockTipText = [
    stockCountDate && 'Stock: the latest count, not the month or range you selected',
    stockPlanText && `target stock from the ${stockPlanText}`,
  ].filter(Boolean).join(' · ');

  // The period tags of the section headings (2026-11-06; BasisTag, grey with
  // a pin: this view ranks the month picked here, not the date filter's
  // range). "12 months to Feb 2026" / "Dec 2025" / "Latest ranking".
  const rankTag = isUnilever
    ? (periodLabel ? `12 months to ${periodLabel}` : null)
    : isDelMonte ? periodLabel : 'Latest ranking';

  // The summary card's figures (2026-11-05): the big number is the class's
  // products ranked in this month; the context line is this run's measured
  // shares from GET /abc's tier_summary. sku_share is null when the rows
  // span both principals (their revenue shares are fractions of two
  // different totals), so only the count is stated then.
  const rankedCountOf = (cat) => sourceData.filter((d) => d.cat === cat && d.isCurrent).length;
  // Card copy (2026-11-06): "81% of sales" on the card, the product share
  // behind a hover on the count.
  const salesShareOf = (tier) => {
    const s = tierSummary.find((t) => t.tier === tier);
    if (!s || s.sku_share == null) return null;
    return `${asPct(s.revenue_share_total, 0)} of sales`;
  };
  const productShareOf = (tier) => {
    const s = tierSummary.find((t) => t.tier === tier);
    if (!s || s.sku_share == null) return undefined;
    return `${asPct(s.sku_share)} of the ${currentRunCount.toLocaleString()} ${rowNoun.many} sold in ${windowText}`;
  };

  // 'pass' | 'fail' | 'not_applicable' (too few ranked rows for an 80/20
  // check). `passes` is the fallback for a response from before the status.
  const paretoState = paretoCheck ? (paretoCheck.status ?? (paretoCheck.passes ? 'pass' : 'fail')) : null;
  // The check's sentence: on screen as a warning when it fails, otherwise
  // under "About these numbers" → Show details.
  const paretoCheckText = !paretoCheck ? null : paretoState === 'not_applicable' ? (
    <><strong>Pareto check not applicable:</strong> {paretoCheck.reason}</>
  ) : (
    <>
      <strong>Pareto check {paretoCheck.passes ? 'passes' : 'fails'}:</strong>{' '}
      the top {asPct(paretoCheck.top_fraction, 0)} of {rowNoun.many} ({paretoCheck.top_count.toLocaleString()} of the{' '}
      {paretoCheck.ranked_count.toLocaleString()} ranked) earn {asPct(paretoCheck.revenue_share)}{' '}
      {classificationPeriod
        ? (isUnilever ? revenueShareBasis('unilever', formatMonth(classificationPeriod)) : `of ${formatMonth(classificationPeriod)} revenue`)
        : 'of revenue'} —{' '}
      {paretoCheck.passes ? 'inside' : 'outside'} the {asPct(paretoCheck.band_low, 0)}–{asPct(paretoCheck.band_high, 0)} range
      a valid classification should fall in.
    </>
  );

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

  // The stock check (2026-11-06): top sellers' stock status on the latest
  // count. Del Monte rows are categories with no stock count, so under All
  // principals it counts Unilever's rows only (and says so).
  const stockScope = useMemo(
    () => (isDelMonte ? [] : dataWithCumulative.filter((d) => d.principal === 'unilever')),
    [dataWithCumulative, isDelMonte]
  );
  const stockBars = useMemo(() => {
    const top = stockScope.filter((d) => d.cat === 'A');
    const bars = (lpHidden ? STOCK_BARS_NO_LP : STOCK_BARS).map((bar) => {
      const rows = top.filter((d) => bar.statuses.includes(d.status));
      // "% of sales": the products' shares in this ranking (Unilever's 12
      // months). A product not ranked in it adds nothing; its share is of
      // another ranking's total.
      const share = rows.filter((d) => d.isCurrent).reduce((sum, d) => sum + d.revPct, 0);
      const shareText = share > 0 && share < 0.5 ? 'under 1%' : `${Math.round(share)}%`;
      let hover = bar.hover;
      if (bar.key === 'CANT_CHECK') {
        // "12 forecast not reliable yet · 3 not enough sales history · 29 not in the stock count"
        const reasons = new Map();
        rows.filter((d) => d.status === 'NO ROP').forEach((d) => {
          const phrase = noTargetPhrase(d.noTargetCode);
          reasons.set(phrase, (reasons.get(phrase) || 0) + 1);
        });
        const parts = [...reasons.entries()].sort((a, b) => b[1] - a[1]).map(([phrase, n]) => `${n.toLocaleString()} ${phrase}`);
        const notCounted = rows.filter((d) => d.status === 'NO DATA').length;
        if (notCounted > 0) parts.push(`${notCounted.toLocaleString()} not in the stock count`);
        hover = parts.length ? parts.join(' · ') : null;
      }
      return {
        ...bar,
        label: bar.key === 'CANT_CHECK' ? CANT_CHECK_YET : statusLabel(bar.key, lpHidden),
        count: rows.length,
        shareText: rows.length > 0 ? shareText : '—',
        // The bar is this share of sales on a 0-100% scale (2026-11-06; it
        // was the product count against the largest count, which disagreed
        // with the share printed beside it).
        widthPct: shareBarWidth(share),
        hover,
      };
    });
    return bars;
  }, [stockScope, lpHidden]);
  // Middle / low sellers' stock-count split, for their hover.
  const otherSplitText = (cat) => `${otherClassStock[cat].counted.toLocaleString()} in the stock count · `
    + `${otherClassStock[cat].notCounted.toLocaleString()} not`;
  // Middle and low sellers: how many are in the stock count at all.
  const otherClassStock = useMemo(() => Object.fromEntries(['B', 'C'].map((cat) => {
    // The cards' count (2026-11-06): only products ranked this time, not
    // those kept in their group from an earlier ranking.
    const rows = stockScope.filter((d) => d.cat === cat && d.isCurrent);
    const notCounted = rows.filter((d) => d.status === 'NO DATA').length;
    return [cat, { total: rows.length, counted: rows.length - notCounted, notCounted }];
  })), [stockScope]);
  const scrollToTable = () => {
    if (classTableRef.current) classTableRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  // A brand bar of "What drives sales" (2026-11-06): the table on that
  // brand. GET /pareto's brand names and the product master's can differ in
  // case, so the match ignores it; a brand the table's list doesn't have
  // goes into the search box, which also searches brand names.
  const showBrandInTable = (name) => {
    const want = String(name || '').trim().toLowerCase();
    const match = brandsList.find((b) => b !== 'ALL' && b.trim().toLowerCase() === want);
    setCategoryFilter('ALL');
    setStatusFilter(null);
    setCurrentRunOnly(false);
    if (match) {
      setBrandFilter(match);
      setSearchQuery('');
    } else {
      setBrandFilter('ALL');
      setSearchQuery(String(name || ''));
    }
    scrollToTable();
  };
  const showStockInTable = (bar) => {
    setCategoryFilter('A');
    setCurrentRunOnly(false);
    setStatusFilter({ label: bar.label, statuses: bar.statuses, principal: hasDelMonteRows ? 'unilever' : null });
    scrollToTable();
  };
  const showClassInTable = (cat) => {
    setCategoryFilter(cat);
    setStatusFilter(null);
    // The footer counts ranked products only, so the table does too.
    setCurrentRunOnly(true);
    scrollToTable();
  };

  const filteredData = useMemo(() => {
    return dataWithCumulative.filter(item => {
      const matchesSearch = searchQuery === '' ||
        item.sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (item.brand || '').toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = categoryFilter === 'ALL' || item.cat === categoryFilter;
      const matchesBrand = brandFilter === 'ALL' || item.brand === brandFilter;
      const matchesRun = !currentRunOnly || item.isCurrent;
      const matchesStatus = !statusFilter || (statusFilter.statuses.includes(item.status)
        && (!statusFilter.principal || item.principal === statusFilter.principal));
      return matchesSearch && matchesCat && matchesBrand && matchesRun && matchesStatus;
    });
  }, [dataWithCumulative, searchQuery, categoryFilter, brandFilter, currentRunOnly, statusFilter]);

  // Whenever the filtered set changes shape (new search, new filter, or
  // the page size itself), snap back to page 1 — staying on e.g. page 4
  // after a filter shrinks the result set would otherwise show a blank
  // page or an out-of-range slice.
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, categoryFilter, brandFilter, currentRunOnly, statusFilter, pageSize]);

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
    searchQuery !== '' || categoryFilter !== 'ALL' || brandFilter !== 'ALL' || currentRunOnly || statusFilter != null;

  const handleClearFilters = () => {
    setSearchQuery('');
    setCategoryFilter('ALL');
    setBrandFilter('ALL');
    setCurrentRunOnly(false);
    setStatusFilter(null);
  };

  // Hover text for a category badge: which run it came from, and an explicit
  // note when it is carried forward — same wording as SKU Management.
  const catTitle = (item) => {
    if (!item.catPeriod) return `Class ${item.cat}`;
    const when = isPlaceholderPeriod(item.catPeriod, placeholder)
      ? `${formatMonth(item.catPeriod)} (placeholder data)`
      : formatMonth(item.catPeriod);
    if (item.isCurrent) return `Class ${item.cat} — current ranking (${rankedWhenOf(item, when)})`;
    // Per row, so a Del Monte row keeps its reason in the All view too.
    if (item.principal === 'delmonte' && item.catPeriod < DEL_MONTE_REGROUP_PERIOD) {
      return `Class ${item.cat} — last grouped in ${when}: an older Del Monte sub-category from before the Jan 2025 regrouping, so it keeps its last group.`;
    }
    return `Class ${item.cat} — last grouped on sales of ${rankedWhenOf(item, when)}. `
      + `${item.principal === 'unilever' ? 'Not sold in the last 12 months' : 'Not sold this month'}, so it keeps its last group.`
      + `${item.isStale ? ' Over 6 months old.' : ''}`;
  };

  const getStatusClass = (status) => {
    switch (status) {
      case 'IN STOCK': return 'pill pill-success';
      case 'LOW': return 'pill pill-warning';
      case 'CRITICAL': return 'pill pill-critical';
      case 'NO ROP': return 'pill pill-neutral';
      case 'NO DATA': return 'pill pill-neutral';
      case 'ON HAND': return 'pill pill-success';
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
  // How to read the table's faded rows and its boundary flag, now one item
  // of "About these numbers". The flag is the backend's boundary margin
  // (rules.boundary_margin, in the row hover); measured, 42% of flagged
  // products change class the next month against 17% of unflagged ones.
  const tableLegend = (
    <>
      {isDelMonte
        ? 'Categories with no sales that month keep their most recent class, shown faded with the month it was set.'
        : `Products with no sales in ${isUnilever ? 'the 12 months ranked' : 'the period ranked'} keep their most recent class, shown faded with the month it was set.`}
      {rules && (
        <> <AlertTriangle size={12} className="abc-boundary-legend-icon" aria-hidden="true" /> flags a {rowNoun.one} close
          to changing class next month.</>
      )}
    </>
  );
  // How brands and categories are grouped: in "About these numbers" and
  // behind the brand section's "?" (2026-11-06), one text for both.
  const groupingText = rules ? (
    <>
      &ldquo;What drives sales&rdquo; ranks brands (or categories) by sales the same way as products. The
      ones that together make up the first {asPct(rules.tier_a_cutoff, 0)} of sales are its top group (the
      maroon bars, Class A), the next ones up to {asPct(rules.tier_b_cutoff, 0)} are Class B, and the rest
      Class C. The table view lists each one&apos;s class.
    </>
  ) : null;
  const basisSwitch = !canRank ? null : (
    <div className="segmented abc-basis-switch" role="tablist" aria-label="Rank by">
      {[['month', abcMonthViewLabel(principal)], ['range', 'Selected range']].map(([value, text]) => (
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
  const mostSales = <strong className="title-accent">the most sales</strong>;
  const header = (
    <div className="abc-page-header">
      <PageHeader
        // The Dashboard's title (ui.css .page-header.is-accented, 2026-11-06).
        className="is-accented"
        title="ABC"
        accent="Classification"
        // One plain line in both views (2026-11-06). The A/B/C cutoffs and
        // the "Top sellers as of…" line are in "About these numbers", opened
        // by the small link beside it. Its key phrase in the accent.
        subtitle={(
            <>
              {basis === 'range'
                ? <>Which {isDelMonte ? 'product categories' : 'products'} bring in {mostSales} in {rangeLabel}</>
                : isUnilever
                  ? <>Which products brought in {mostSales} over {windowText}</>
                  : <>Which {isDelMonte ? 'product categories' : 'products'} bring in {mostSales} in {windowText}</>}
              {basis !== 'range' && periodPlaceholderNote}.
              {(basis === 'range' || loadedKey !== null) && (
                <>
                  {' '}
                  <button
                    type="button"
                    className="link-button abc-about-link"
                    aria-expanded={aboutOpen}
                    aria-controls="abc-about-panel"
                    onClick={() => setAboutOpen((o) => !o)}
                  >
                    <Info size={13} aria-hidden="true" /> About these numbers
                  </button>
                </>
              )}
            </>
          )}
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
      {/* Del Monte's rows are product categories, not SKUs. Said once, up
          front, and it also separates the two meanings of "category" on
          this page: the product category a row IS, and the A/B/C tier it
          was ranked into. */}
      {isDelMonte && (
        <p className="abc-principal-note">
          <strong>Del Monte is grouped by product category, not by individual product.</strong> Its sales data has no
          product-level detail, so each row below is a product category, and its A/B/C is that category&apos;s ABC class.
        </p>
      )}
      {!isDelMonte && hasDelMonteRows && (
        <p className="abc-principal-note">
          <strong>Del Monte rows are product categories, not individual products.</strong> Del Monte&apos;s sales data has no
          product-level detail, so it is grouped by category.
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
          {/* The range view's own "About these numbers" (2026-11-06): the
              A/B/C cutoffs, moved out of its subtitle as on One month. */}
          {aboutOpen && (
            <div id="abc-about-panel" className="ui-card abc-about" role="region" aria-label="About these numbers">
              <ul className="abc-about-list">
                {rules && <li>{tierRuleText(rules)}</li>}
                <li>This view looks at sales over {rangeLabel}, the same range as the Dashboard, so its groups can differ from the &ldquo;{abcMonthViewLabel(principal)}&rdquo; view&apos;s.</li>
              </ul>
            </div>
          )}
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

          {/* "About these numbers" (2026-11-05; opened from the link beside
              the subtitle since 2026-11-06, closed by default): which run the
              top sellers come from, the A/B/C cutoffs, the never-sold count,
              why this Class A count differs from the Dashboard's ring, which
              stock count the statuses use, the drill-down's class note, how
              to read the table, and the Pareto check. */}
          {aboutOpen && (
          <div id="abc-about-panel" className="ui-card abc-about" role="region" aria-label="About these numbers">
            <ul className="abc-about-list">
              {/* The monthly run's basis, with its own "?" (TierBasisLabel). */}
              <li><TierBasisLabel periods={tierAPeriods} period={classificationPeriod} className="abc-about-basis" /></li>
              {rules && <li>{tierRuleText(rules)}</li>}
              {/* Not for Del Monte: its never-ranked count is product
                  records, which are never ranked one by one (the ranking is
                  by category). Under All, it includes Del Monte item codes. */}
              {!isDelMonte && unclassifiedCount > 0 && (
                <li>
                  {unclassifiedCount.toLocaleString()} products on SSM&apos;s list have no recorded sales up to {periodLabel ?? 'this month'}.
                  {hasDelMonteRows && ' This count includes Del Monte item codes, which are grouped by category, never one by one.'}
                </li>
              )}
              {classificationPeriod && (
                <li>
                  The {catACount.toLocaleString()} top sellers come from {rankingText}. The Dashboard&apos;s ABC ring
                  {canRank ? ' and the Selected range view rank' : ' ranks'} sales over {rangeLabel} instead, so their
                  top-seller count can differ.
                  {canRank && (
                    <>
                      {' '}
                      <button type="button" className="link-button" onClick={() => setBasis('range')}>
                        Show the range ranking
                      </button>
                    </>
                  )}
                </li>
              )}
              {stockBasisText && (
                <li>
                  {stockBasisText}. The stock check counts every top seller, including those {notSoldPhrase}.
                  {!lpHidden && !isDelMonte && (
                    <>
                      {' '}The Dashboard&apos;s Below safety stock card and the Reorder page check only the products in the
                      order plan{planCycle ? ` (${formatMonth(planCycle)} plan)` : ''}, on the stock count that opens
                      that plan, so their counts can be lower. This page uses the latest count instead, so its numbers
                      can differ from the Reorder page.
                    </>
                  )}
                </li>
              )}
              <li>{tableLegend}</li>
              {/* The brand chart's cutoffs (2026-11-06; its dashed lines
                  are gone): the same rules as the product ranking. */}
              {groupingText && (
                <li>
                  <details className="abc-about-details">
                    <summary>How brands and categories are grouped</summary>
                    <span>{groupingText}</span>
                  </details>
                </li>
              )}
              {paretoCheck && paretoState !== 'fail' && (
                <li>
                  <details className="abc-about-details">
                    <summary>Show details</summary>
                    <span>{paretoCheckText}</span>
                  </details>
                </li>
              )}
            </ul>
          </div>
          )}

          {/* Summary Cards */}
          {/* The shared KPI card (UI pass). The big number is the products
              ranked in the selected month (2026-11-05); carried-forward rows
              are a small second line, and the cover chart and drill-down
              below (which count both) say the split beside their figures. */}
          {/* Shorter cards (2026-11-06): no section header row, the tier
              name as the title (labels.js; upper-cased by KPICard.css), the
              count and its share of sales on the card, and the rest behind
              a hover. */}
          <div className="kpi-strip abc-summary-grid" role="group" aria-label={`How the ${rowNoun.many} split by sales`}>
            {['A', 'B', 'C'].map((cat) => (
              <KPICard
                key={cat}
                title={tierLabel(cat)}
                // The ⓘ pop-up (InfoTip), not a native title, so the detail
                // opens on tap and from the keyboard too (2026-11-06).
                value={rankedCountOf(cat).toLocaleString()}
                unit={rowNoun.unit}
                contextLine={salesShareOf(cat) ? (
                  <span className="abc-card-line">
                    {salesShareOf(cat)}
                    {productShareOf(cat) && (
                      <InfoTip label={`About the ${tierLabel(cat).toLowerCase()} count`} size={12}>
                        {productShareOf(cat)}.
                      </InfoTip>
                    )}
                  </span>
                ) : undefined}
                note={carriedCountOf(cat) > 0 ? (
                  <span className="abc-card-line">
                    +{carriedCountOf(cat).toLocaleString()} {notSoldPhrase}
                    <InfoTip label={`About ${notSoldPhrase}`} size={12}>
                      {`No sales in ${windowText}, so they keep the group from the last time they were ranked.`}
                    </InfoTip>
                  </span>
                ) : null}
                accent={{ A: 'var(--color-abc-a)', B: 'var(--color-abc-b)', C: 'var(--color-abc-c)' }[cat]}
                icon={<span className={`abc-kpi-letter abc-kpi-letter-${cat.toLowerCase()}`} aria-hidden="true">{cat}</span>}
              />
            ))}
            <KPICard
              title={`${rowNoun.count} sold`}
              value={currentRunCount.toLocaleString()}
              unit={rowNoun.unit}
              contextLine={`in ${windowText}`}
              flag={boundaryCount > 0
                ? {
                    label: `${boundaryCount.toLocaleString()} may move to another group next month`,
                    detail: `${boundaryCount.toLocaleString()} ${boundaryCount === 1 ? `${rowNoun.one} is` : `${rowNoun.many} are`} close to a group cutoff, so ${boundaryCount === 1 ? 'it' : 'they'} may move to another group next month.`,
                  }
                : null}
              icon={<Layers size={20} />}
              accent="var(--color-nav-bg)"
            />
          </div>

          {/* The Pareto check (manuscript §3.4.4.2.2) stays on screen only
              when it FAILS: a warning shouldn't hide in a closed box. A pass,
              or 'not applicable' (too few ranked rows, e.g. Del Monte's
              categories), is in "About these numbers" → Show details. */}
          {paretoCheck && paretoState === 'fail' && (
            <p className="ui-note is-warning">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>{paretoCheckText}</span>
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
                ? `the ${preRegroupCarriedCount.toLocaleString()} rows not sold this month`
                : `${preRegroupCarriedCount.toLocaleString()} of the ${carriedCount.toLocaleString()} rows not sold this month`}{' '}
              here are the older sub-categories, last grouped before the change.
            </p>
          )}

          {/* "Are our top sellers stocked enough?" (2026-11-06): replaces the
              cover-vs-target chart by class and its drill-down. Top sellers
              only, one bar per status on the latest count; a bar opens the
              table on those products. Middle and low sellers get one line
              under it: they have no target stock to check. */}
          {/* As a Dashboard section (2026-11-06): the question above the
              card, with the count's date in its grey tag, said once; the
              card's old title said the same as the question. */}
          <section className="ui-section" aria-labelledby="abc-stock-check-title">
            <SectionHeading
              id="abc-stock-check-title"
              info={stockTipText ? <>{stockTipText}. The stock check counts every top seller, including those {notSoldPhrase}.</> : null}
              infoLabel="About the stock check"
              tags={stockCountDate ? <BasisTag label={`Stock counted ${formatDate(stockCountDate)}`} follows={false} /> : null}
            >
              Do the top sellers have <span className="title-accent">enough stock</span>?
            </SectionHeading>
          <div className="ui-card abc-stock-check card-accent-top">
            {isDelMonte ? (
              <p className="ui-card-subtitle">
                Del Monte is grouped by category, which has no stock count, so its stock can&apos;t be checked here.
              </p>
            ) : (
              <>
                {stockCountDate && !lpHidden && planCycle && (
                  <p className="ui-card-subtitle">
                    Compared with the {formatMonth(planCycle)} order plan.
                  </p>
                )}
                {hasDelMonteRows && (
                  <p className="ui-card-subtitle">
                    Unilever only: Del Monte is grouped by category, which has no stock count.
                  </p>
                )}
                {/* A small table with bars (2026-11-06): status | bar |
                    products | share of sales. Each row is one button laid
                    over the row, so the whole row filters the table; the
                    cells under it don't take the pointer, except the
                    "Can't check yet" ⓘ, which opens its split and reasons.
                    The other rows' explanation is the row's own hover.
                    Shares are Unilever's (the only principal counted here),
                    so over the 12 months of its ranking. */}
                <div className="abc-stock-table" role="group" aria-label="Top sellers by stock status">
                  <div className="abc-stock-head" aria-hidden="true">
                    {/* The same headers as the product table's (2026-11-06):
                        two lines each, so every label sits on one line. */}
                    <span className="abc-stock-label-head">
                      Stock status
                      <span className="abc-stock-head-sub">{stockPlanText || ' '}</span>
                    </span>
                    {/* The bars' scale (2026-11-06): share of sales, 0 to 100%. */}
                    <span className="abc-stock-bar-cell abc-stock-scale">
                      <span>0%</span>
                      <span>100% of sales</span>
                    </span>
                    <span className="abc-stock-num">
                      Products
                      <span className="abc-stock-head-sub">{' '}</span>
                    </span>
                    <span className="abc-stock-num">
                      Share of sales
                      <span className="abc-stock-head-sub">({stockWindowShort})</span>
                    </span>
                  </div>
                  {stockBars.map((bar) => (
                    // A status with no verdict ("Can't check yet", or "Not in
                    // the latest stock count" without lp.view) is missing
                    // stock data, not a stock level: a divider above it and a
                    // hatched bar, its count and share as they are (2026-11-06).
                    <div key={bar.key} className={`abc-stock-row${bar.tone === 'neutral' ? ' is-missing' : ''}`}>
                      <button
                        type="button"
                        className="abc-stock-row-hit"
                        onClick={() => showStockInTable(bar)}
                        title={bar.key === 'CANT_CHECK' ? undefined : bar.hover}
                        aria-label={`${bar.label}: ${bar.count.toLocaleString()} ${bar.count === 1 ? 'product' : 'products'}, `
                          + `${bar.shareText} of sales over the last 12 months.`
                          + `${bar.hover ? ` ${bar.hover}${bar.key === 'CANT_CHECK' ? '.' : ''}` : ''} Show them in the table below.`}
                      />
                      <span className="abc-stock-label">
                        {bar.label}
                        {bar.key === 'CANT_CHECK' && bar.hover && (
                          <span className="abc-stock-tip">
                            <InfoTip label={`About ${bar.label}`} size={12}>{bar.hover}</InfoTip>
                          </span>
                        )}
                      </span>
                      <span className="abc-stock-bar-cell" aria-hidden="true">
                        <span className={`abc-stock-bar-fill chart-grow-x is-${bar.tone}`} style={{ width: `${bar.widthPct}%` }} />
                      </span>
                      <span className="abc-stock-num">{bar.count.toLocaleString()}</span>
                      <span className="abc-stock-num">{bar.shareText}</span>
                    </div>
                  ))}
                </div>
                <p className="abc-stock-hint">Click a bar to see those products below.</p>
                {/* Middle and low sellers: one line, each class a link that
                    filters the table; its stock-count split in the hover. */}
                <div className="abc-stock-foot">
                  <p className="abc-stock-foot-text">
                    Not checked:{' '}
                    {['B', 'C'].map((cat, k) => (
                      <React.Fragment key={cat}>
                        {k > 0 && ' and '}
                        <button
                          type="button"
                          className="abc-stock-class-link"
                          onClick={() => showClassInTable(cat)}
                          title={otherSplitText(cat)}
                          aria-label={`${otherClassStock[cat].total.toLocaleString()} ${tierLabel(cat).toLowerCase()} `
                            + `(${otherSplitText(cat)}). Show them in the table below.`}
                        >
                          {otherClassStock[cat].total.toLocaleString()} {tierLabel(cat).toLowerCase()}
                        </button>
                      </React.Fragment>
                    ))}
                    , because only top sellers get a target stock.
                  </p>
                  {canOpenReorder && (
                    <Link to="/reorder" className="abc-stock-check-link">See what to order →</Link>
                  )}
                </div>
              </>
            )}
          </div>
          </section>

          {/* Brand / category Pareto (D1), full width: which brands and
              categories drive revenue, which the SKU table alone can't answer.
              Its section heading is drawn by ParetoCard, which holds the
              brand / category and window choices its question and tag
              follow. */}
          <div className="abc-breakdown-row">
            <ParetoCard principal={principal} period={classificationPeriod} onSelectBrand={showBrandInTable} headingInfo={groupingText} />
          </div>


          {/* The product ranking as one Dashboard section (2026-11-06): the
              question over the filters, the chips and the table; its tag is
              the ranking's period, its "?" how to read the table. */}
          <section className="ui-section" aria-labelledby="abc-products-title">
          <SectionHeading
            id="abc-products-title"
            info={tableLegend}
            infoLabel="How to read the table"
            tags={rankTag ? <BasisTag label={rankTag} follows={false} /> : null}
          >
            Where does <span className="title-accent">each {rowNoun.one}</span> rank?
          </SectionHeading>

          {/* Searchable Combobox & Filters Bar */}
          <div className="abc-filters-row">
            {/* Search Combobox */}
            <div className="abc-combobox-container" ref={comboboxRef}>
              <div className="abc-search-wrapper">
                <Search className="abc-search-icon" size={16} />
                <input
                  type="text"
                  placeholder={isDelMonte ? 'Search by category name...' : 'Search by product name, product code, or brand...'}
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
                {/* Rows ranked in this ranking only (2026-11-06 wording). */}
                {isUnilever
                  ? 'Only products sold in the last 12 months'
                  : isDelMonte
                    ? `Only categories sold in ${periodLabel ?? 'this month'}`
                    : 'Only products sold in the period ranked'}
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

              {statusFilter && (
                <span className="abc-active-chip">
                  Stock: {statusFilter.label}
                  <button className="abc-chip-remove" onClick={() => setStatusFilter(null)} aria-label="Remove the stock filter">
                    <X size={12} />
                  </button>
                </span>
              )}

              {currentRunOnly && (
                <span className="abc-active-chip">
                  Sold in {windowText} only
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
          <div className="ui-card is-flush card-accent-top">
          <div className="ui-card-intro">
            <div className="ui-card-head is-centered">
              <span className="icon-tile" aria-hidden="true"><ListOrdered size={20} /></span>
              <div className="ui-card-head-text">
                <h4 className="section-card-title">All {rowNoun.many}, <span className="title-accent">best-selling</span> first</h4>
              </div>
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
                  {/* A carried-forward row's share is of its own month's
                      revenue, named under its value; the header names the
                      run's month, which every other row's share is of. */}
                  <th className="table-center col-fit" title={`Share of sales in the ranking the ${rowNoun.one} was last grouped in`}>
                    Share of sales
                    {windowShort && <span className="abc-th-sub">({windowShort})</span>}
                  </th>
                  <th className="col-fit" title="Stock, in pieces, against the product's target stock in the order plan">
                    Stock status
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
                              <title>{`Running share of sales ${item.cumulativePct.toFixed(1)}% — may move to another group next month`}</title>
                            </AlertTriangle>
                          )}
                        </span>
                      </span>
                    </td>
                    {item.isCurrent ? (
                      <td className="table-center cell-strong">{item.revPct.toFixed(1)}%</td>
                    ) : (
                      <td
                        className="table-center cell-muted"
                        title={`${item.revPct.toFixed(2)}% of sales in ${rankedWhenOf(item, formatMonth(item.catPeriod))}: not part of this ranking's total`}
                      >
                        {item.revPct.toFixed(1)}%
                        <span className="abc-rev-period">{formatMonth(item.catPeriod)}</span>
                      </td>
                    )}
                    <td>
                      <span className={getStatusClass(item.status)} title={`stock_status: ${item.status}`}>
                        <span className={`abc-status-dot is-${STATUS_TONE[item.status] || 'neutral'}`} aria-hidden="true" />
                        {statusLabel(item.status, lpHidden)}
                      </span>
                      {/* The reason sits on the label it explains. 50 of
                          February's Class A read "No target stock" with no
                          why, beside copy saying the LP plans Class A. */}
                      {item.status === 'NO ROP' && item.noTargetReason && (
                        <InfoTip label={`Why ${item.product || formatSKU(item.sku)} has no target stock`}>
                          <NoTargetWhy code={item.noTargetCode} reason={item.noTargetReason} />
                        </InfoTip>
                      )}
                    </td>
                  </tr>
                ))}
                {filteredData.length === 0 && (
                  <tr className="table-empty-row">
                    <td colSpan="6">No data for this selection.</td>
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
          </section>
        </div>
      </div>
    </div>
  );
};

export default ABCClassification;
