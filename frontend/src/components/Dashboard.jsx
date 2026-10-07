import React, { useEffect, useRef, useState } from 'react';
import { useOutletContext, useNavigate, Link } from 'react-router-dom';
import KPICard from './KPICard';
import AtRiskProductsModal from './AtRiskProductsModal';
import {
  ClassChanges, ForecastErrorSummaryCard, IdleStockCard, ProductListModal, IDLE_COLUMNS, OVER_RUN_COLUMNS,
} from './RangeCards';
import DateFilter from './DateFilter';
import {
  SalesVsStockWidget, ABCDonutWidget, CategoryStockBarWidget,
  PortfolioForecastWidget, ReorderRecommendationWidget, PolicyComparisonWidget,
  AllocationWidget, formatCompactPesos,
} from './Charts';
import {
  getClassChanges, getDashboardData, getForecastAccuracy, getIdleStock, peekDashboardData,
} from '../api/dashboard';
import { CHART_COLORS } from '../theme/colors';
import { ALL_PRINCIPALS, DEFAULT_PRINCIPAL } from '../principals';
import { staleCoverageNotice } from '../dataCoverage';
import { usePermissions } from '../permissions/context';
import { isPlaceholderPeriod, isPreviewMode } from '../dataMode';
import { useEntranceReplay } from '../theme/useEntranceReplay';
import { prefersReducedMotion } from '../theme/motion';
import RefreshingNote from './RefreshingNote';
import { formatDate, formatMonth } from '../utils/formatDate';
import { LoadingStatus, SkeletonChartCard, SkeletonLine, SkeletonStatCards } from './Skeleton';
import { Package, Wallet, ArrowRight, AlertTriangle, ClipboardList } from 'lucide-react';
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
function rangeTotalLine(total, pagePrincipal) {
  if (!total) return null;
  if (total.value == null) return total.blocked_reason || null;
  if ((total.months_in_range || 0) <= 1) return null;
  const months = total.months_with_data === total.months_in_range
    ? `all ${total.months_in_range} months`
    : `${total.months_with_data} of ${total.months_in_range} months`;
  const missing = total.missing_months || [];
  const gap = missing.length === 0 ? ''
    : `; no ${pagePrincipal === ALL_PRINCIPALS ? 'figure for both principals' : 'sales on record'} in `
      + missing.map(periodLabel).join(', ');
  return `${formatCompactPesos(total.value)} over ${total.label} (${months}${gap})`;
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

const Slot = ({ kind, question, hint, realOnly = false, children }) => (
  <div className="dash-slot" data-kind={kind}>
    <span className="dash-kind-row">
      {question && <span className="dash-question">{question}</span>}
      {hint && <span className="dash-question-hint">{hint}</span>}
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
    <div className="kpi-strip kpi-strip-hero">
      <SkeletonStatCards count={4} cardClassName="kpi-card" />
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
    <nav className="dash-section-nav" aria-label="Dashboard sections">
      {DASH_SECTIONS.map((s) => {
        const current = enabled && active === s.id;
        return (
          <button
            key={s.id}
            type="button"
            className={`dash-section-chip${current ? ' is-active' : ''}`}
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
  const { startMonth, startYear, endMonth, endYear, principal, dataMode } = useOutletContext() || {};
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
  // Class A changes for the same range and principal (GET /dashboard/
  // class-changes), keyed like `loaded` so a stale range never shows.
  const [classChanges, setClassChanges] = useState(null); // { key, data }
  // The list behind a range card's figure: { kind, rows, loading, error }.
  const [rangeList, setRangeList] = useState(null);
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
    let cancelled = false;
    getClassChanges({ period, startPeriod, principal })
      .then((res) => { if (!cancelled) setClassChanges({ key: requestKey, data: res }); })
      // The card is extra to the page: on a failure it is left out, and the
      // rest of the dashboard stands.
      .catch(() => { if (!cancelled) setClassChanges({ key: requestKey, data: null }); });
    return () => { cancelled = true; };
  }, [requestKey, period, startPeriod, principal]);

  // Opens a range card's product list, fetched on demand for the same range.
  const openRangeList = (kind) => {
    setRangeList({ kind, rows: [], loading: true, error: null });
    const request = kind === 'idle'
      ? getIdleStock({ period, principal }).then((res) => res.items || [])
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
      <div className="dashboard-header">
        <div className="dashboard-title-row">
          <h2>Inventory <span className="page-title-accent">pulse</span></h2>
        </div>
        <p>Inventory and ordering overview — SSM Urdaneta warehouse</p>
      </div>
      <div className={`dash-toolbar${toolbarStuck ? ' is-stuck' : ''}`} ref={toolbarRef}>
        <DashSectionNav active={activeSection} enabled={sectionsReady} />
        <DateFilter />
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
  const salesIsPlaceholder = isPlaceholderPeriod(kpis.sales_period, placeholder);
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
  const sales = kpiDisplay(
    kpis.sales, kpis.sales_blocked_reason, formatCompactPesos,
    [salesMonth ? `Total sales · ${salesMonth}${salesIsPlaceholder ? ' (placeholder)' : ''}` : 'Total sales', salesBasis, vatNote]
      .filter(Boolean).join(' · '),
  );
  const salesRangeNote = kpis.sales_blocked_reason ? null : rangeTotalLine(kpis.sales_cumulative, pagePrincipal);
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
    ? `≈ ${Number(cover.value).toFixed(1)} weeks of ${coverWindow ? `${coverWindow} ` : ''}sales`
      + `${coverProvisional ? ' (provisional)' : ''} · SSM policy: ${policyWeeks} weeks`
    : null;
  // Del Monte's year has sales in only some months (6 of 12 in 2025); the
  // average is over those, and the tooltip says so rather than imply a year.
  const coverMonthsNote = cover.months_used != null && cover.months_used < 12
    ? ` Only ${cover.months_used} of those months have sales on record; the average is over those.`
    : '';
  const priceBasisNote = 'Stock is valued at each product\'s last purchase price, which is not SSM\'s true cost.';
  const coverTooltip = cover.value != null && coverWindow
    ? `${priceBasisNote} Weeks of cover = this stock ÷ average weekly sales over ${coverWindow}, the 12 months up to `
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
  // Del Monte's stock files carry no pack size, so its stock can't be
  // turned into pieces: the card says why it is in pesos only.
  const pesosOnlyNote = pagePrincipal === 'delmonte' ? 'pesos only, since Del Monte files have no pack size' : null;
  const sohValue = kpiDisplay(
    kpis.soh_value, kpis.soh_value_blocked_reason, formatCompactPesos,
    ['At last purchase price', countLabel, pesosOnlyNote, sohCoverage, coverLine].filter(Boolean).join(' · '),
  );

  // stock_on_hand_flags: counts the team reviewed and judged unusual — the
  // chart marks those points and gives the reason, it never drops them.
  const stockFlags = new Map((data.stock_on_hand_flags || []).map((f) => [f.period, f.reason]));
  const salesVsStock = (data.sales_vs_stock || []).map((pt) => ({
    period: pt.period,
    sales: pt.sales,
    stockOnHand: pt.stock_on_hand,
    // No count day for a principal whose counts don't record one.
    stockCountDay: countDayKnown ? dayLabel(pt.stock_count_date) : null,
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
    stockUnusual: stockFlags.get(pt.period) || null,
  }));

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
  const portfolioSeries = (portfolioForecast.series || [])
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
      'Measurable Class A SKUs below safety stock',
      lpCycleLabel ? `${lpCycleLabel} plan` : null,
      stockCountedLine(exposure.stock_counts),
      abcCoverage,
    ].filter(Boolean).join(' · ')
  );

  // Pending action count — the "what to do" figure in the hero strip. Now
  // the CURRENT LP cycle only: it counted every undecided row ever written,
  // so 179 leftovers from runs going back to 2023-05 were being presented
  // as work awaiting a decision today (429 against the real 250).
  const pendingCount = data.recommendations?.product_count ?? 0;
  // Non-null only when the live data has moved past the hardcoded ceiling.
  const coverageStale = staleCoverageNotice(data.latest_data_period);
  const pendingContext = [
    'Reorder suggestions awaiting a decision',
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
  const openForecast = (sku) => navigate(`/forecast?sku=${encodeURIComponent(sku)}`);
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
          <div className="kpi-strip kpi-strip-hero dash-section-anchor" id="dash-summary">
            <KPICard
              title="Sales"
              value={sales.value}
              // Green accent (top bar + icon) for money coming in — card
              // chrome only; the pill below carries the month's direction.
              // Slate, like every blocked card, when there is no figure.
              metricType={sales.value === '—' ? undefined : 'healthy'}
              contextLine={sales.contextLine}
              note={salesRangeNote}
              icon={<Wallet size={20} />}
              {...(sales.value !== '—' ? trendExtras(kpis.sales_trend, CHART_COLORS.salesSeries) : {})}
            />
            <KPICard
              title="Inventory value"
              value={sohValue.value}
              contextLine={sohValue.contextLine}
              // A count the team judged unusual is kept and says so
              // (kpis.soh_count_note, Yuan 2026-10-04), beside the figure.
              flag={sohValue.value !== '—' ? kpis.soh_count_note || null : null}
              tooltip={coverTooltip}
              icon={<Package size={20} />}
              {...(sohValue.value !== '—' ? trendExtras(kpis.soh_trend, CHART_COLORS.stockSeries, 'count') : {})}
            />
            <KPICard
              title="Below safety stock"
              value={belowSs.value}
              unit={belowSs.value === '—' ? undefined : exposure.comparable_count === 1 ? 'SKU' : 'SKUs'}
              metricType={belowSs.value === '—' ? undefined : ssTier}
              contextLine={belowSs.contextLine}
              action={canListAtRisk
                ? { label: `See the ${exposure.below_count.toLocaleString()} products`, onClick: openAtRisk }
                : undefined}
              icon={<AlertTriangle size={20} />}
            />
            <KPICard
              title="Pending reorder actions"
              value={lpHidden ? '—' : pendingCount.toLocaleString()}
              unit={lpHidden ? undefined : pendingCount === 1 ? 'SKU' : 'SKUs'}
              metricType={lpHidden ? undefined : 'recommendation'}
              contextLine={lpHidden ? LP_HIDDEN_NOTE : pendingContext}
              action={!lpHidden && pendingCount > 0 ? { label: 'Open the order plan', to: '/reorder' } : undefined}
              icon={<ClipboardList size={20} />}
            />
          </div>

          {/* DESCRIPTIVE — what happened: the sales trend across the full
              row, then the ABC mix beside each tier's warehouse status. */}
          <div className="dash-row dash-row-trend dash-section-anchor" id="dash-sales">
            <Slot kind="Descriptive" question="What happened?" hint="Sales and inventory value over time"><SalesVsStockWidget data={salesVsStock} placeholder={placeholder} insight={data.sales_vs_stock_insight} note={vatNote} basis={data.sales_vs_stock_basis} /></Slot>
          </div>

          <div className="dash-row dash-row-abc dash-section-anchor" id="dash-abc">
            <Slot kind="Descriptive" question="Which products matter most?">
              <ABCDonutWidget
                data={abcMix}
                revenue={data.abc_revenue}
                rules={data.abc_rules}
                note={placeholderNote(data.abc_revenue?.period)}
                coverage={abcCoverage}
                units={abcUnits}
                atRisk={canListAtRisk
                  ? { below: exposure.below_count, measurable: exposure.comparable_count, onOpen: openAtRisk }
                  : null}
              />
            </Slot>
            <Slot kind="Descriptive" question="Is any of our stock dead?">
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
            <div className={`dash-row ${rangeChanges && data.idle_stock ? 'dash-row-even' : 'dash-row-trend'}`}>
              {rangeChanges && (
                <Slot kind="Descriptive" question="Which products entered or left the top sellers?">
                  <ClassChanges changes={rangeChanges} onOpen={openForecast} />
                </Slot>
              )}
              {data.idle_stock && (
                <Slot kind="Descriptive" question="Is any stock sitting idle?">
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
            <Slot kind="Predictive" question="What will happen next?" hint="Demand forecast" realOnly={portfolioRealOnly}>
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
                insight={portfolioForecast.insight}
              />
            </Slot>
            {!lpHidden && (
              <Slot kind="Prescriptive" question="What should we do?" hint="What to order, and how much" realOnly={preview && realOnly.has('reorder_preview')}>
                <ReorderRecommendationWidget
                  rows={reorderRows}
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

          {/* How far off the forecasts were over the range, in pesos first. */}
          {data.forecast_accuracy && (
            <div className="dash-row dash-row-trend">
              <Slot kind="Predictive" question="How far off were the forecasts?" hint="Forecast against actual sales">
                <ForecastErrorSummaryCard
                  accuracy={data.forecast_accuracy}
                  scope={coverageNote(data.forecast_accuracy.coverage, pagePrincipal)}
                  onOpenList={() => openRangeList('over')}
                />
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
            <Slot kind="Descriptive" question="Are sales keeping pace with the allocation?">
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
        } : {
          title: 'Products over-forecast several months in a row',
          subtitle: overRunSubtitle,
          columns: OVER_RUN_COLUMNS,
          footnote: 'Largest surplus first. Click a product to open its forecast.',
          onOpenProduct: openForecast,
          openLabel: 'Open its forecast',
        })}
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
          abcMonth: periodLabel(data.abc_revenue?.period),
          planLabel: lpCycleLabel ? `${lpCycleLabel} plan` : null,
          countDay,
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
