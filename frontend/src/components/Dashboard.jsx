import React, { useEffect, useRef, useState } from 'react';
import { useOutletContext, useNavigate, Link } from 'react-router-dom';
import PageHeader from './ui/PageHeader';
import AtRiskProductsModal from './AtRiskProductsModal';
import ClassProductsModal from './ClassProductsModal';
import {
  ClassChanges, DelMonteProductSalesCard, ForecastErrorSummaryCard, IdleStockCard, ProductListModal,
  CATEGORY_MISS_COLUMNS, DEMO_PRODUCT_SALES_LABEL, IDLE_COLUMNS, OVER_RUN_COLUMNS, PRODUCT_SALES_COLUMNS,
} from './RangeCards';
import RangePicker from './RangePicker';
import { ActionCard, AnnualSalesCard, InventoryCard, MiniList, ShareBar } from './HeroKpis';
import { formatUnits } from '../utils/formatNumber';
import {
  SalesVsStockWidget, ABCDonutWidget, CategoryStockBarWidget,
  PortfolioForecastWidget, ReorderRecommendationWidget, PolicyComparisonWidget,
  AllocationWidget, formatCompactPesos,
} from './Charts';
import {
  getClassChanges, getDashboardData, getForecastAccuracy, getIdleStock, getProductSales, peekDashboardData,
} from '../api/dashboard';
import { CHART_COLORS } from '../theme/colors';
import { ALL_PRINCIPALS, DEFAULT_PRINCIPAL, labelForPrincipal } from '../principals';
import { staleCoverageNotice } from '../dataCoverage';
import { usePermissions } from '../permissions/context';
import { PLACEHOLDER_START, isPlaceholderPeriod, isPreviewMode } from '../dataMode';
import { FIRST_DATA_YEAR } from '../dataCoverage';
import { COMPARE_MODES, comparisonRange } from '../periodFilter';
import BasisTag, { FOLLOWS_RANGE } from './BasisTag';
import { useEntranceReplay } from '../theme/useEntranceReplay';
import { prefersReducedMotion } from '../theme/motion';
import RefreshingNote from './RefreshingNote';
import { formatDate, formatMonth } from '../utils/formatDate';
import { LoadingStatus, SkeletonChartCard, SkeletonLine, SkeletonStatCards } from './Skeleton';
import { ArrowRight, AlertTriangle } from 'lucide-react';
import TierBasisLabel from './TierBasisLabel';
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

// GET /dashboard's sales_vs_stock as the hero chart's rows. Used for the
// page's own range and for the comparison period's, so both lines are read
// the same way (count days only where the counts record one; flagged counts
// keep their reason).
const chartPoints = (payload) => {
  if (!payload) return [];
  const counts = (payload.kpis?.stock_counts || []).filter((c) => c.available);
  const dayKnown = counts.length === 0 || counts.every((c) => c.counted_on);
  const flags = new Map((payload.stock_on_hand_flags || []).map((f) => [f.period, f.reason]));
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
    salesEstimated: pt.sales_estimated ?? null,
    salesEstimatedKind: pt.sales_estimated_kind ?? null,
    stockEstimated: pt.stock_on_hand_estimated ?? null,
    stockEstimatedKind: pt.stock_on_hand_estimated_kind ?? null,
    returns: pt.returns ?? null,
    returnsEstimated: pt.returns_estimated ?? null,
    returnsEstimatedKind: pt.returns_estimated_kind ?? null,
    stockUnusual: flags.get(pt.period) || null,
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
    trendDirection: pct > 0 ? 'up' : pct < 0 ? 'down' : undefined,
    deltaTone: pct > 0 ? 'positive' : pct < 0 ? 'negative' : 'neutral',
  };
};

const Slot = ({ kind, question, hint, realOnly = false, basis = null, children }) => (
  <div className="dash-slot" data-kind={kind}>
    <span className="dash-kind-row">
      {question && <span className="dash-question">{question}</span>}
      {hint && <span className="dash-question-hint">{hint}</span>}
      {/* Whether this card moves with the date filter, and if not, what it
          is pinned to (BasisTag). */}
      {basis && <span className="dash-basis"><BasisTag {...basis} /></span>}
      <span className="dash-kind">{kind}</span>
      {realOnly && (
        <span className="dash-real-only" title="Preview adds placeholder months to the descriptive views only. This card reads real data.">
          Real data only
        </span>
      )}
    </span>
    {children}
  </div>
);

// Same outer structure and card classes as the loaded page below, so every
// block lands at its final size — nothing jumps when the real data replaces
// it. Replaces a lone "Loading dashboard data…" line that left the page
// blank for the whole /dashboard request (measured 5.4–7.1s). Each card sits
// in a .dash-slot like the real ones (that is where their 360px minimum
// height comes from) and takes its widget's shape, in page order: sales
// trend; ABC ring and tier bars; portfolio forecast and reorder list; policy
// bars beside the allocation bars. Row classes repeat (two dash-row-even),
// so keys come from the index, not the class.
const DASHBOARD_SKELETON_ROWS = [
  ['dash-row-trend', [{ variant: 'line' }]],
  ['dash-row-abc', [{ variant: 'donut' }, { variant: 'hbars', rows: 3 }]],
  ['dash-row-even', [{ variant: 'line' }, { variant: 'list', rows: 3 }]],
  ['dash-row-even', [{ variant: 'hbars', rows: 2, height: 120 }, { variant: 'hbars', rows: 4, height: 160 }]],
];

const DashboardSkeleton = () => (
  <div className="dashboard-body" aria-hidden="true">
    <div className="hero-kpis">
      <SkeletonStatCards count={4} cardClassName="hero-card" />
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
  { id: 'dash-summary', label: 'Summary', hint: 'The four headline numbers' },
  { id: 'dash-sales', label: 'Sales & inventory', hint: 'What happened: monthly sales against inventory value (₱, at last purchase price)' },
  { id: 'dash-abc', label: 'ABC classes', hint: 'What happened: which products earn the most, and their stock status' },
  { id: 'dash-forecast', label: 'Forecast & reorder', hint: "What's next and what to do: the demand forecast and the reorder list" },
  { id: 'dash-policy', label: 'Client policy', hint: "What to do: the LP safety stock against SSM's 3-week policy, and sales against the supplier allocation" },
];
const DASH_SECTION_IDS = DASH_SECTIONS.map((s) => s.id);

// The reason on the LP cards for an account without lp.view (GET
// /dashboard's lp_hidden).
const LP_HIDDEN_NOTE = 'Needs the reorder-recommendation permission';

// Which section is being read, and whether the toolbar has stuck under the
// top bar. Both are read off `.dashboard` — the element that scrolls on this
// page; the top bar sits outside it — once per frame while it scrolls.
// `enabled` is false until the sections exist (skeleton, error).
function useSectionSpy(toolbarRef, enabled) {
  const [active, setActive] = useState(DASH_SECTION_IDS[0]);
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    const bar = toolbarRef.current;
    const scroller = bar?.closest('.dashboard');
    if (!bar || !scroller) return undefined;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const barRect = bar.getBoundingClientRect();
      setStuck(scroller.scrollTop > 0 && barRect.top <= scroller.getBoundingClientRect().top + 1);
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
const DashSectionNav = ({ active, enabled }) => {
  const jumpTo = (id) => {
    document.getElementById(id)?.scrollIntoView({
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'start',
    });
  };
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
  const isAdmin = usePermissions().role === 'admin';
  const { startMonth, startYear, endMonth, endYear, principal, dataMode, compare = COMPARE_MODES.YEAR } = useOutletContext() || {};
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
  // The list behind "N below safety stock" (AtRiskProductsModal).
  const [showAtRisk, setShowAtRisk] = useState(false);
  // The class whose products are listed for the range (ClassProductsModal), or null.
  const [listedClass, setListedClass] = useState(null);
  // Class A changes for the same range and principal (GET /dashboard/
  // class-changes), keyed like `loaded` so a stale range never shows.
  const [classChanges, setClassChanges] = useState(null); // { key, data }
  // The list behind a range card's figure: { kind, rows, loading, error }.
  const [rangeList, setRangeList] = useState(null);
  // Del Monte's estimated product sales (GET /dashboard/product-sales), on
  // the Del Monte view only.
  const [productSales, setProductSales] = useState(null); // { key, data }
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
        if (!cancelled) setError({ key: requestKey, message: err.message || 'Failed to load dashboard data' });
      });
    return () => {
      cancelled = true;
    };
  }, [requestKey, loadedKey, period, startPeriod, principal]);

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
    let cancelled = false;
    getClassChanges({ period, startPeriod, principal })
      .then((res) => { if (!cancelled) setClassChanges({ key: requestKey, data: res }); })
      // The card is extra to the page: on a failure it is left out, and the
      // rest of the dashboard stands.
      .catch(() => { if (!cancelled) setClassChanges({ key: requestKey, data: null }); });
    return () => { cancelled = true; };
  }, [requestKey, period, startPeriod, principal]);

  useEffect(() => {
    if (principal !== 'delmonte') return undefined;
    let cancelled = false;
    getProductSales({ period, startPeriod, principal })
      .then((res) => { if (!cancelled) setProductSales({ key: requestKey, data: res }); })
      .catch(() => { if (!cancelled) setProductSales({ key: requestKey, data: null }); });
    return () => { cancelled = true; };
  }, [requestKey, period, startPeriod, principal]);

  // Opens a range card's product list, fetched on demand for the same range.
  // 'sales' arrives with its rows (the card already holds them).
  const openSalesList = (rows) => setRangeList({ kind: 'sales', rows, loading: false, error: null });
  const openRangeList = (kind) => {
    setRangeList({ kind, rows: [], loading: true, error: null });
    const request = kind === 'idle'
      ? getIdleStock({ period, principal }).then((res) => res.items || [])
      : kind === 'category'
        // Category rows carry no product: the category is the row's name.
        ? getForecastAccuracy({ level: 'category', period, startPeriod, principal })
          .then((res) => (res.rows || []).map((r) => ({ ...r, product_name: r.category_path })))
        : getForecastAccuracy({ period, startPeriod, principal }).then((res) => res.over_forecast_runs?.items || []);
    request
      .then((rows) => setRangeList((prev) => (prev?.kind === kind ? { kind, rows, loading: false, error: null } : prev)))
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
  const sectionsReady = Boolean(loaded) && !currentError;
  const toolbarRef = useRef(null);
  const { active: activeSection, stuck: toolbarStuck } = useSectionSpy(toolbarRef, sectionsReady);

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
      <PageHeader title="Inventory" accent="pulse" subtitle="Inventory and ordering overview — SSM Urdaneta warehouse" />
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
          <p className="dashboard-empty-note" role="alert">Failed to load dashboard data: {currentError}</p>
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
          <DashboardSkeleton />
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
  const coverLine = cover.value != null
    ? `≈ ${Number(cover.value).toFixed(1)} weeks of cover${coverProvisional ? ' (provisional)' : ''}`
      + ` · SSM policy: ${policyWeeks} weeks`
    : null;
  // Del Monte's year has sales in only some months (6 of 12 in 2025); the
  // average is over those, and the tooltip says so rather than imply a year.
  const coverMonthsNote = cover.months_used != null && cover.months_used < 12
    ? ` Only ${cover.months_used} of those months have sales on record; the average is over those.`
    : '';
  // Del Monte's stock files carry no pack size, so its stock can't be
  // turned into pieces: the card says why it is in pesos only.
  const pesosOnlyNote = pagePrincipal === 'delmonte' ? 'pesos only, since Del Monte files have no pack size' : null;
  const priceBasisNote = 'Stock is valued at each product\'s last purchase price, which is not SSM\'s true cost.';
  const coverTooltip = cover.value != null && coverWindow
    ? `${priceBasisNote}${pesosOnlyNote ? ` Pesos only: ${pesosOnlyNote.replace('pesos only, since ', '')}.` : ''}`
      + ` Weeks of cover = this stock ÷ average weekly sales over ${coverWindow}, the 12 months up to `
      + `the stock count at the end of the selected range.${coverMonthsNote} SSM's policy is `
      + `to keep ${policyWeeks} weeks of sales in stock.`
      + (coverProvisional ? ` Provisional: ${cover.caveat}.` : '')
    : priceBasisNote;
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
  const sohValue = kpiDisplay(
    kpis.soh_value, kpis.soh_value_blocked_reason, formatCompactPesos,
    ['At last purchase price', countLabel, sohCoverage].filter(Boolean).join(' · '),
  );
  // The same count in pieces (kpis.soh_snapshot.pieces: cases x pack size
  // + loose pieces). Unilever only: Del Monte's files carry no pack size, so
  // the backend sends null there and under All principals, and no line is
  // drawn rather than a partial total.
  const sohPieces = kpis.soh_snapshot?.pieces ?? null;
  const piecesLine = sohValue.value !== '—' && sohPieces != null
    ? `${Math.round(sohPieces).toLocaleString()} pieces in the same count`
    : null;

  // The hero chart's rows (chartPoints), and the comparison period's when one
  // is chosen, with the reason when it can't be drawn.
  const salesVsStock = chartPoints(data);
  const chartCompare = versus && !versus.beforeData && prior?.data
    ? { points: chartPoints(prior.data), label: versus.label, shift: versus.shift }
    : null;
  const chartCompareNote = !versus ? null
    : versus.beforeData ? `No comparison line: the data starts Jan ${preview ? PLACEHOLDER_START.year : FIRST_DATA_YEAR}.`
      : prior?.failed ? `Could not load ${versus.label} to compare.`
        : !prior ? `Loading ${versus.label} to compare…` : null;

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
    : abcCovered.includes('delmonte') ? 'items' : 'SKUs';

  const tierStock = (data.tier_stock || []).map((t) => ({
    tier: t.tier,
    inStock: t.in_stock,
    deadStock: t.dead_stock,
    noData: t.no_data,
    pendingReorderCount: t.pending_reorder_count,
  }));

  // The page's own payload, so the card and the MASE reliability count
  // (GET /dashboard's forecast block) describe the page's principal.
  const portfolioForecast = data.portfolio_forecast || {};
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
  const portfolioSeries = (portfolioForecast.series || [])
    .filter((pt) => !(forecastBeyondRange && pt.period > period))
    .filter((pt) => !(portfolioRealOnly && isPlaceholderPeriod(pt.period, placeholder)))
    .map((pt) => ({
    period: pt.period,
    actual: pt.actual,
    forecast: pt.forecast,
    confidenceLower: pt.confidence_lower,
    confidenceUpper: pt.confidence_upper,
  }));

  const reorderPreview = data.reorder_preview || {};
  const reorderRows = (reorderPreview.rows || []).map((r) => ({
    sku: r.sku_id,
    product: r.product_name,
    urgency: r.urgency,
    orderQty: r.q_i,
  }));

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
  // Non-null only when the live data has moved past the hardcoded ceiling.
  const coverageStale = staleCoverageNotice(data.latest_data_period);
  const pendingContext = [
    'Awaiting a decision',
    lpCycleLabel ? `${lpCycleLabel} plan` : null,
  ].filter(Boolean).join(' · ');
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
  const dmProductSales = pagePrincipal === 'delmonte' && productSales?.key === loaded.key ? productSales.data : null;
  const openForecast = (sku) => navigate(`/forecast?sku=${encodeURIComponent(sku)}`);

  // ── The shared comparison on the two value cards ─────────────────────
  // Sales compares RANGE TOTALS (a flow: the range against the comparison
  // range, on the same months with sales); stock compares the COUNT at each
  // range's end (a snapshot). Each pill says what it compared, and a gap
  // says so instead of a percentage (Del Monte has no sales on record from
  // Mar 2024 to Feb 2025).
  const noEarlierData = { deltaLine: `No comparison: the data starts Jan ${preview ? PLACEHOLDER_START.year : FIRST_DATA_YEAR}` };
  const salesCompare = (() => {
    if (!versus || kpis.sales_blocked_reason) return {};
    if (versus.beforeData) return noEarlierData;
    if (!prior) return {};
    if (prior.failed) return { deltaLine: `Could not load ${versus.label} to compare` };
    const nowTotal = kpis.sales_cumulative;
    const thenTotal = prior.data?.kpis?.sales_cumulative;
    if (nowTotal?.value == null) return {};
    if (thenTotal?.value == null || !thenTotal.months_with_data) {
      return { deltaLine: `No sales on record in ${versus.label} to compare` };
    }
    if (thenTotal.months_with_data !== nowTotal.months_with_data) {
      return {
        deltaLine: `Not like-for-like: ${nowTotal.months_with_data} months on record now, `
          + `${thenTotal.months_with_data} in ${versus.label}`,
      };
    }
    return comparePill(nowTotal.value, thenTotal.value, `range total vs ${versus.label}`) || {};
  })();
  const stockCompare = (() => {
    if (!versus || kpis.soh_value == null) return {};
    if (versus.beforeData) return noEarlierData;
    if (!prior) return {};
    if (prior.failed) return { deltaLine: `Could not load ${versus.label} to compare` };
    const then = prior.data?.kpis || {};
    // The backend falls back to the latest count on or before the range's
    // end; one from before the comparison period even starts is not that
    // period's stock (Del Monte has no count from Mar 2024 to Feb 2025).
    if (then.soh_value == null || (then.soh_period && then.soh_period < versus.startPeriod)) {
      return { deltaLine: `No stock count in ${versus.label} to compare` };
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
      detail: `${FOLLOWS_RANGE} The comparison period from "Compare with" is drawn dashed on the same months.`,
    },
    abc: { ...rangeBasis, detail: `${FOLLOWS_RANGE} Classes are ranked on sales over the whole range.` },
    // Checked live 2026-10-09: the bars read the count at the range's end
    // (tier_stock_period), like the Inventory card; only the pending-reorder
    // figures inside them come from the current plan.
    tierStock: {
      label: 'Range-end count',
      follows: true,
      detail: `${FOLLOWS_RANGE} It reads the warehouse status flags in the stock count at the end of the range`
        + `${data.tier_stock_count_date ? ` (counted ${dayLabel(data.tier_stock_count_date)})` : ''}; `
        + 'the pending-reorder figures in it are from the current plan.',
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
  const annualCard = {
    allocation,
    yoy,
    latest: {
      month: annualLatestMonth,
      value: allocation.latest_sales != null ? formatCompactPesos(allocation.latest_sales) : '—',
      trend: annualTrend.trend || null,
      change: annualTrend.deltaLine ? annualTrend : null,
      blockedReason: allocation.latest_sales == null ? allocation.blocked_reason || null : null,
    },
    range: {
      short: salesRange?.short ?? null,
      change: salesCompare,
      label: rangeSales.label ? `Sales, ${rangeSales.label}` : 'Sales',
      value: rangeSales.value != null && !kpis.sales_blocked_reason ? formatCompactPesos(rangeSales.value) : '—',
    },
    basis: {
      label: allocation.allocation_year ? `FY ${allocation.allocation_year}` : 'Current year',
      follows: false,
      detail: 'Does not change with the date filter: the year being planned, its sales so far against the same '
        + 'months a year earlier, and the latest month with sales. The allocation is the previous year\u2019s sales '
        + '\u00d7 103/105/108%, one year only, whatever the range. Only the "Selected range" line follows the filter.',
    },
    tooltip: salesTooltip,
  };
  // Weeks of cover is drawn as a bar against the policy (CoverMeter) when
  // there is a figure; the text line stays only as the fallback.
  const coverMeter = sohValue.value !== '—' && cover.value != null
    ? { weeks: Number(cover.value), policy: policyWeeks, provisional: coverProvisional }
    : null;
  const inventoryLines = sohValue.value === '—'
    ? [sohValue.contextLine]
    : ['At last purchase price', countLabel ? countLabel.charAt(0).toUpperCase() + countLabel.slice(1) : null,
      sohCoverage, piecesLine, coverMeter ? null : coverLine];
  // The two operational cards' visuals (HeroKpis.jsx). Below safety stock:
  // the count as a share of the SKUs it was checked on, and the first three
  // of below_items (already ordered by revenue share, the list the link
  // opens). Pending reorders: the same pending rows by urgency, from
  // reorder_preview's counts; "Planned" is what is left of the card's count.
  const belowShare = belowSs.value !== '—' && exposure.comparable_count > 0 ? [
    { key: 'below', label: 'Below', value: exposure.below_count },
    { key: 'above', label: 'At or above', value: exposure.comparable_count - exposure.below_count },
  ] : null;
  const belowTop = belowSs.value !== '—'
    ? belowItems.slice(0, 3).map((it) => ({
      key: it.sku_id || it.product_name,
      name: it.product_name || it.sku_id,
      figure: `${formatUnits(it.short_by)} pcs`,
    }))
    : [];
  const pendingParts = (() => {
    if (lpHidden || pendingCount <= 0) return null;
    const critical = reorderPreview.critical_count ?? 0;
    const urgent = reorderPreview.urgent_count ?? 0;
    const noData = reorderPreview.no_data_count ?? 0;
    const planned = pendingCount - critical - urgent - noData;
    // The counts come from a separate read of the same pending rows; if they
    // ever disagree with the card's count, draw nothing rather than a bar
    // that doesn't add up.
    if (planned < 0) return null;
    return [
      { key: 'critical', label: 'Critical', value: critical },
      { key: 'urgent', label: 'Urgent', value: urgent },
      planned > 0 ? { key: 'planned', label: 'Planned', value: planned } : null,
      noData > 0 ? { key: 'nodata', label: 'No stock data', value: noData } : null,
    ].filter(Boolean);
  })();
  const pendingQtyLine = pendingParts && reorderPreview.total_order_qty > 0
    ? `${reorderPreview.total_order_qty.toLocaleString()} pieces to order in all`
    : null;
  // The first two of reorder_preview.rows: already most urgent first, then
  // by the Reorder page's own priority, so they match the top of that page.
  const pendingTop = pendingParts
    ? reorderRows.slice(0, 2).map((r) => ({
      key: r.sku || r.product,
      name: r.product || r.sku,
      figure: `${formatUnits(r.orderQty)} pcs`,
    }))
    : [];
  const belowLines = belowSs.value === '—'
    ? [belowSs.contextLine]
    : [
      ['Class A SKUs with a stock count', abcCoverage].filter(Boolean).join(' · '),
      [lpCycleLabel ? `${lpCycleLabel} plan` : null, stockCountedLine(exposure.stock_counts)].filter(Boolean).join(' · '),
    ];
  const belowBadge = belowSs.value === '—' ? null : ssPinnedFlag || {
    label: 'Current plan',
    tone: 'info',
    detail: `The ${lpCycleLabel ? `${lpCycleLabel} ` : ''}order plan, the latest one. This card does not change with `
      + 'the date filter: safety stock exists only for the current plan.',
  };

  // Months in the range with no sales on record (Del Monte has many). Said
  // once, under the filters, so a short total is never read as a low year.
  const salesTotal = kpis.sales_cumulative;
  const gapMonths = salesTotal?.missing_months || [];
  const rangeGapNote = salesTotal && salesTotal.months_in_range > 1 && gapMonths.length > 0
    ? `${pagePrincipal === ALL_PRINCIPALS ? 'Both principals have' : `${labelForPrincipal(pagePrincipal)} has`} sales on record for `
      + `${salesTotal.months_with_data} of the ${salesTotal.months_in_range} months in this range. `
      + `No sales on record in ${gapMonths.map(periodLabel).join(', ')}: totals and comparisons cover the other months only.`
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

  return (
    <div className="dashboard">
      <div className="dashboard-content">
        {header}

        {isRefreshing && (
          <RefreshingNote>
            Updating to {startMonth} {startYear} – {endMonth} {endYear}…
          </RefreshingNote>
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
                {isAdmin
                  ? <> To fix it, update <code>LATEST_DATA_PERIOD</code> in <code>frontend/src/dataCoverage.js</code>.</>
                  : ' Let an admin know.'}
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
            <div className="dash-stale-note" role="status">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                <strong>
                  {lp.stale_row_count < lp.row_count ? 'Some reorder quantities' : 'Reorder quantities'}
                  {' '}are from an older LP run.
                </strong>{' '}
                {lp.reason}{' '}
                {lp.superseded_pending_count > 0 && (
                  <>
                    {lp.superseded_pending_count.toLocaleString()} undecided rows from earlier cycles
                    are not counted here.
                  </>
                )}
              </span>
            </div>
          )}

          {/* Hero strip — the four figures that answer "what is happening
              right now": money in, money parked, service risk, and work
              waiting. */}
          <TierBasisLabel periods={exposure.tier_a_periods} period={exposure.tier_a_period} />
          {rangeGapNote && (
            <p className="dash-gap-note" role="note">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>{rangeGapNote}</span>
            </p>
          )}
          {/* The top row (HeroKpis.jsx): performance first — annual sales and
              the allocation, inventory value — then the two operational
              cards, tinted, with the way to act on them. */}
          <div className="hero-kpis dash-section-anchor" id="dash-summary">
            <AnnualSalesCard {...annualCard} />
            <InventoryCard
              value={sohValue.value}
              lines={inventoryLines}
              // A count the team judged unusual is kept and says so
              // (kpis.soh_count_note, Yuan 2026-10-04).
              flag={sohValue.value !== '—' && kpis.soh_count_note ? { label: 'Unusual count', detail: kpis.soh_count_note } : null}
              change={sohValue.value !== '—' ? stockCompare : null}
              cover={coverMeter}
              tooltip={coverTooltip}
              basis={BASIS.stock}
            />
            <ActionCard
              tone="orange"
              title="Below safety stock"
              value={belowSs.value}
              unit={belowSs.value === '—' ? undefined : exposure.comparable_count === 1 ? 'SKU' : 'SKUs'}
              severity={belowSs.value === '—' || ssTier === 'healthy' ? null : ssTier === 'danger' ? 'danger' : 'watch'}
              lines={belowLines}
              badge={belowBadge}
              tooltip={belowSs.value === '—' ? undefined : belowSsTooltip}
              link={canListAtRisk
                ? { label: `See the ${exposure.below_count.toLocaleString()} products`, onClick: openAtRisk }
                : null}
            >
              {belowShare && (
                <ShareBar
                  inline
                  parts={belowShare}
                  label={`${exposure.below_count} of ${exposure.comparable_count} Class A SKUs below safety stock`}
                />
              )}
              <MiniList title="Top sellers among them" figureLabel="Short by" rows={belowTop} />
            </ActionCard>
            <ActionCard
              tone="purple"
              title="Pending reorder actions"
              value={lpHidden ? '—' : pendingCount.toLocaleString()}
              unit={lpHidden ? undefined : pendingCount === 1 ? 'SKU' : 'SKUs'}
              lines={lpHidden ? [LP_HIDDEN_NOTE] : ['Awaiting a decision', lpCycleLabel ? `${lpCycleLabel} plan` : null]}
              link={!lpHidden && pendingCount > 0 ? { label: 'Open the order plan', to: '/reorder' } : null}
            >
              {pendingParts && (
                <ShareBar
                  parts={pendingParts}
                  label={`${pendingCount} pending SKUs by urgency: `
                    + pendingParts.map((p) => `${p.value} ${p.label.toLowerCase()}`).join(', ')}
                />
              )}
              {pendingQtyLine && <p className="hero-note">{pendingQtyLine}</p>}
              <MiniList title="First in line" figureLabel="Order" rows={pendingTop} />
            </ActionCard>
          </div>

          {/* DESCRIPTIVE — what happened: the sales trend across the full
              row, then the ABC mix beside each tier's warehouse status. */}
          <div className="dash-row dash-row-trend dash-section-anchor" id="dash-sales">
            <Slot kind="Descriptive" question="What happened?" hint="Sales and inventory value over time" basis={BASIS.chart}><SalesVsStockWidget data={salesVsStock} placeholder={placeholder} insight={data.sales_vs_stock_insight} note={vatNote} basis={data.sales_vs_stock_basis} compare={chartCompare} compareNote={chartCompareNote} /></Slot>
          </div>

          <div className="dash-row dash-row-abc dash-section-anchor" id="dash-abc">
            <Slot kind="Descriptive" question="Which products matter most?" basis={BASIS.abc}>
              <ABCDonutWidget
                data={abcMix}
                revenue={data.abc_revenue}
                rules={data.abc_rules}
                note={placeholderNote(data.abc_revenue?.period)}
                coverage={abcCoverage}
                units={abcUnits}
                atRisk={canListAtRisk && !ssPinned
                  ? { below: exposure.below_count, measurable: exposure.comparable_count, onOpen: openAtRisk }
                  : null}
                onOpenClass={setListedClass}
              />
            </Slot>
            <Slot kind="Descriptive" question="Is any of our stock dead?" basis={BASIS.tierStock}>
              <CategoryStockBarWidget
                data={tierStock}
                note={placeholderNote(data.abc_revenue?.period)}
                period={data.tier_stock_period}
                countDay={countDayKnown ? dayLabel(data.tier_stock_count_date) : null}
                cycleLabel={lpCycleLabel}
                coverage={abcCoverage}
              />
            </Slot>
          </div>

          {/* Which products entered or left Class A against the same months a
              year before, and the stock that has not moved: both answer for
              the selected range (data marts, 2026-10-04/05). */}
          {(rangeChanges || data.idle_stock) && (
            <div className={`dash-row dash-row-top ${rangeChanges && data.idle_stock ? 'dash-row-even' : 'dash-row-trend'}`}>
              {rangeChanges && (
                <Slot kind="Descriptive" question="Which products entered or left the top sellers?" basis={BASIS.classChanges}>
                  <ClassChanges changes={rangeChanges} onOpen={openForecast} />
                </Slot>
              )}
              {data.idle_stock && (
                <Slot kind="Descriptive" question="Is any stock sitting idle?" basis={BASIS.idle}>
                  <IdleStockCard
                    idle={data.idle_stock}
                    scope={coverageNote(data.idle_stock.coverage, pagePrincipal)}
                    onOpenList={() => openRangeList('idle')}
                  />
                </Slot>
              )}
            </div>
          )}

          {/* PREDICTIVE + PRESCRIPTIVE — what next, and what to do */}
          <div className={`dash-row ${lpHidden ? 'dash-row-trend' : 'dash-row-even'} dash-section-anchor`} id="dash-forecast">
            <Slot kind="Predictive" question="What will happen next?" hint="Demand forecast" realOnly={portfolioRealOnly} basis={BASIS.forecast}>
              <PortfolioForecastWidget
                series={portfolioSeries}
                gatedSkuCount={portfolioForecast.gated_sku_count ?? 0}
                scopeLabel={portfolioForecast.scope_label}
                // The backend's scope_label already says it plainly for Del
                // Monte ("No SKU-level forecasts exist for Del Monte — …").
                // The local sentence only stands in if it is ever missing,
                // so the card can't fall back to a generic "No forecast data".
                emptyReason={
                  portfolioForecast.scope_label
                    || (pagePrincipal === 'delmonte'
                      ? 'No SKU-level forecasts for Del Monte — it has no SKU-level sales data, only category sell-out.'
                      : undefined)
                }
                reliability={forecastReliability}
                insight={forecastBeyondRange ? null : portfolioForecast.insight}
                forecastNote={forecastNote}
              />
            </Slot>
            {!lpHidden && (
              <Slot kind="Prescriptive" question="What should we do?" hint="What to order, and how much" realOnly={preview && realOnly.has('reorder_preview')} basis={BASIS.plan}>
                <ReorderRecommendationWidget
                  rows={reorderRows}
                  cycle={lpCycleLabel}
                  criticalCount={reorderPreview.critical_count ?? 0}
                  urgentCount={reorderPreview.urgent_count ?? 0}
                  totalOrderQty={reorderPreview.total_order_qty ?? 0}
                  weights={reorderPreview.lp_weights}
                  cycleLabel={lpCycleLabel}
                  countLabel={countLabel}
                />
              </Slot>
            )}
          </div>

          {/* How far off the forecasts were over the range, right under the forecast it checks. */}
          {data.forecast_accuracy && (
            <div className="dash-row dash-row-trend">
              <Slot kind="Predictive" question="How far off were the forecasts?" hint="Forecast against actual sales" basis={BASIS.accuracy}>
                <ForecastErrorSummaryCard
                  accuracy={data.forecast_accuracy}
                  scope={coverageNote(data.forecast_accuracy.coverage, pagePrincipal)}
                  onOpenList={() => openRangeList('over')}
                  onOpenCategories={() => openRangeList('category')}
                />
              </Slot>
            </div>
          )}

          {/* Del Monte's product sales: estimates only, labelled as a demo. */}
          {dmProductSales && (
            <div className="dash-row dash-row-trend">
              <Slot kind="Descriptive" question="Which Del Monte products sell most?" hint="Estimated" basis={rangeBasis}>
                <DelMonteProductSalesCard sales={dmProductSales} onOpenList={openSalesList} />
              </Slot>
            </div>
          )}

          {/* PRESCRIPTIVE — the policy question this project exists to answer,
              beside SSM's own allocation rule applied to the sales data */}
          <div className={`dash-row ${lpHidden || !SHOW_POLICY_CARD ? 'dash-row-trend' : 'dash-row-even'} dash-section-anchor`} id="dash-policy">
            {SHOW_POLICY_CARD && !lpHidden && (
              <Slot kind="Prescriptive" question="Is the 3-week rule working?" realOnly={preview && realOnly.has('policy_comparison')}>
                <PolicyComparisonWidget comparison={data.policy_comparison} />
              </Slot>
            )}
            <Slot kind="Descriptive" question="Are sales keeping pace with the allocation?" basis={BASIS.allocation}>
              <AllocationWidget allocation={data.allocation} />
            </Slot>
          </div>

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
              Reorder Recs ranks every pending recommendation by revenue at risk and shows the top 20 as
              &ldquo;Act now&rdquo;.{' '}
              <Link to="/reorder" className="band-link">Open Reorder Recs <ArrowRight size={12} /></Link>
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
        {...(rangeList?.kind === 'idle' ? {
          title: 'Idle stock',
          subtitle: idleSubtitle,
          columns: IDLE_COLUMNS,
          footnote: 'Most stock value first.',
        } : rangeList?.kind === 'category' ? {
          title: 'Forecast misses by category',
          subtitle: [data.forecast_accuracy?.label, 'Unilever products with a scored forecast',
            data.forecast_accuracy?.pesos_basis ? `pesos at ${String(data.forecast_accuracy.pesos_basis).split(' (')[0]}` : null]
            .filter(Boolean).join(' · '),
          columns: CATEGORY_MISS_COLUMNS,
          firstColumnLabel: 'Category',
          footnote: 'Largest misses in pesos first. A category can be too high in some months and too low in others; '
            + 'the net miss in pieces says which way it leaned overall.',
        } : rangeList?.kind === 'sales' ? {
          title: 'Del Monte product sales (demo)',
          subtitle: [dmProductSales?.label, DEMO_PRODUCT_SALES_LABEL].filter(Boolean).join(' · '),
          columns: PRODUCT_SALES_COLUMNS,
          footnote: 'Highest estimated sales first. Every figure here is an estimate, not a sale on record.',
        } : {
          title: 'Products over-forecast several months in a row',
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
        onOpenAbcPage={() => navigate(`/abc?class=${listedClass}&basis=range`)}
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
