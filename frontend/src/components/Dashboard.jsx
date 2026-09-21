import React, { useEffect, useState } from 'react';
import { useOutletContext, Link } from 'react-router-dom';
import KPICard from './KPICard';
import DateFilter from './DateFilter';
import {
  SalesVsStockWidget, ABCDonutWidget, CategoryStockBarWidget,
  PortfolioForecastWidget, ReorderRecommendationWidget, PolicyComparisonWidget,
  DemandVolatilityWidget, formatCompactPesos,
} from './Charts';
import { getDashboardData, peekDashboardData } from '../api/dashboard';
import { getSegmentSummary } from '../api/segment';
import { DEFAULT_PRINCIPAL, labelForPrincipal } from '../principals';
import { useEntranceReplay } from '../theme/useEntranceReplay';
import RefreshingNote from './RefreshingNote';
import { Package, Wallet, Clock, ArrowRight, AlertTriangle, ClipboardList } from 'lucide-react';
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

// GET /dashboard's sales/stock window ends at a single 'YYYY-MM' `period`
// anchor (a fixed trailing 12 months, same "picker's end maps onto the
// anchor" convention ABCClassification.jsx's toClassificationPeriod uses
// for GET /abc) UNLESS `startPeriod` is also sent, in which case it covers
// the exact start-through-end range the picker applied — otherwise a
// range wider than 12 months (e.g. Apr 2023 - Mar 2026) silently clipped
// to just its last 12 months, which read as "the start date does nothing."
const MONTH_TO_NUM = {
  Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
  Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12',
};
const toPeriod = (month, year) =>
  month && year ? `${year}-${MONTH_TO_NUM[month]}` : undefined;

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
// Each widget is tagged with the kind of analytics it answers, so the four
// types are demonstrable at a glance without a paragraph above each one.
//   Descriptive — what happened
//   Diagnostic  — why it happened
//   Predictive  — what happens next
//   Prescriptive— what to do about it
const Slot = ({ kind, children }) => (
  <div className="dash-slot" data-kind={kind}>
    <span className="dash-kind">{kind}</span>
    {children}
  </div>
);

// Same outer structure and card classes as the loaded page below, so every
// block lands at its final size — nothing jumps when the real data replaces
// it. Replaces a lone "Loading dashboard data…" line that left the page
// blank for the whole /dashboard request (measured 5.4–7.1s).
const DashboardSkeleton = () => (
  <div className="dashboard-body" aria-hidden="true">
    <div className="kpi-strip kpi-strip-hero">
      {[0, 1, 2, 3, 4].map((k) => (
        <div className="kpi-card skeleton-card" key={k}>
          <div className="skeleton-line skeleton-line-title" />
          <div className="skeleton-line skeleton-line-value" />
          <div className="skeleton-line skeleton-line-subtext" />
        </div>
      ))}
    </div>
    {['dash-row-wide-narrow', 'dash-row-narrow-wide', 'dash-row-even', 'dash-row-single'].map((rowClass) => (
      <div className={`dash-row ${rowClass}`} key={rowClass}>
        {(rowClass === 'dash-row-single' ? [0] : [0, 1]).map((k) => (
          <div className="chart-widget skeleton-card" key={k}>
            <div className="skeleton-line skeleton-line-title" />
            <div className="skeleton-chart-body" />
          </div>
        ))}
      </div>
    ))}
  </div>
);

const Dashboard = () => {
  const { startMonth, startYear, endMonth, endYear, principal } = useOutletContext() || {};
  const period = toPeriod(endMonth, endYear);
  const startPeriod = toPeriod(startMonth, startYear);
  // Every input the request varies on, principal included. It was
  // `period|startPeriod` only, which silently broke the principal filter
  // on this page: the fetch effect below early-returns when
  // loadedKey === requestKey, and switching principal leaves both periods
  // untouched, so the request was never issued and the dashboard kept
  // showing the previous principal's numbers. Nothing remounted it
  // either — DashboardLayout's <Outlet key={refreshKey}> only changes on
  // the Topbar's Refresh. The segmentation panel below refetches on
  // [principal] with no such guard, so the page rendered one principal's
  // diagnostic beside another principal's KPIs.
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
  const loadedKey = loaded?.key;

  // Segmentation summary (the diagnostic panel) is its own request: it is
  // cohort-scoped, not range-scoped, so it must NOT refetch when the date
  // picker moves — only when the principal does. A failure here leaves the
  // panel in its honest "no segmentation data" state and never blocks the
  // rest of the dashboard.
  const [segmentSummary, setSegmentSummary] = useState(null);
  useEffect(() => {
    let cancelled = false;
    getSegmentSummary({ principal })
      .then((res) => { if (!cancelled) setSegmentSummary(res); })
      .catch(() => { if (!cancelled) setSegmentSummary(null); });
    return () => { cancelled = true; };
  }, [principal]);

  // The portfolio forecast card has its OWN principal filter, independent
  // of the Topbar's page-wide one — switching it re-scopes that card only.
  // When the two match, the card reads the page's own payload; otherwise
  // it fetches GET /dashboard for its own scope (same period range),
  // through the same response cache, so flipping back and forth never
  // refetches a scope already loaded this session.
  const pagePrincipal = principal ?? DEFAULT_PRINCIPAL;
  const [forecastPrincipal, setForecastPrincipal] = useState(DEFAULT_PRINCIPAL);
  const forecastKey = `${period ?? ''}|${startPeriod ?? ''}|${forecastPrincipal}`;
  const forecastFollowsPage = forecastPrincipal === pagePrincipal;
  const [cardForecast, setCardForecast] = useState(null); // { key, data, error }
  const cardForecastKey = cardForecast?.key;
  useEffect(() => {
    if (forecastFollowsPage || cardForecastKey === forecastKey) return undefined;
    let cancelled = false;
    getDashboardData({ period, startPeriod, principal: forecastPrincipal })
      .then((res) => {
        if (!cancelled) setCardForecast({ key: forecastKey, data: res.portfolio_forecast || {} });
      })
      .catch(() => {
        if (!cancelled) setCardForecast({ key: forecastKey, data: null, error: true });
      });
    return () => { cancelled = true; };
  }, [forecastFollowsPage, cardForecastKey, forecastKey, period, startPeriod, forecastPrincipal]);

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

  const isRefreshing = Boolean(loaded) && loaded.key !== requestKey;

  // Rebuild the cards whenever a different response lands — a date range
  // or principal change, not a re-render. Keyed on the loaded data's own
  // key rather than requestKey so the build plays with the new numbers
  // already in place, instead of animating the outgoing view while the
  // request is still in flight. Must sit above the early returns below:
  // hooks cannot be called conditionally.
  const enterCycle = useEntranceReplay(loaded?.key ?? '');
  const currentError = error?.key === requestKey ? error.message : null;

  // Header is rendered in every state — loading, error and loaded — rather
  // than only on success. The date picker lives inside it, so blanking the
  // whole page on load meant the control the user had just changed
  // disappeared underneath them on every single refetch, and an error left
  // them with no way to pick a different range to recover.
  const header = (
    <div className="dashboard-header">
      <div className="dashboard-title-row">
        <h2>Inventory <span className="page-title-accent">pulse</span></h2>
        <DateFilter />
      </div>
      <p>Inventory and ordering overview — SSM Urdaneta warehouse</p>
    </div>
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
          <p className="visually-hidden" role="status">Loading dashboard data…</p>
          <DashboardSkeleton />
        </div>
      </div>
    );
  }

  const { data } = loaded;
  const kpis = data.kpis || {};
  const weeksOfCover = kpis.weeks_of_cover || {};
  const policyWeeks = data.inventory?.policy_weeks ?? 3;

  const sales = kpiDisplay(kpis.sales, kpis.sales_blocked_reason, formatCompactPesos, "This period's total sales");
  const sohValue = kpiDisplay(kpis.soh_value, kpis.soh_value_blocked_reason, formatCompactPesos, 'Stock-on-hand valuation');

  const weeksOfCoverValue = weeksOfCover.value ?? null;
  const weeksOfCoverReason = weeksOfCover.blocked_reason ?? null;
  const weeksOfCoverDisplay = kpiDisplay(
    weeksOfCoverValue, weeksOfCoverReason, (v) => `${v.toFixed(1)} wks`, "vs. SSM's 3-week policy"
  );
  // Below policy is a stockout-risk signal (red, 'danger'); above policy
  // reads as excess tied-up capital via the 'gap' tier's isOverTarget
  // branch (amber); exactly at policy is healthy. Blocked (no value to
  // judge) gets no metricType at all, which KPICard renders in slate —
  // never a coloured verdict on data that isn't there.
  const weeksOfCoverMetricType =
    weeksOfCoverValue === null ? undefined : weeksOfCoverValue < policyWeeks ? 'danger' : 'gap';
  const weeksOfCoverIsOverTarget = weeksOfCoverValue !== null && weeksOfCoverValue > policyWeeks;

  const salesVsStock = (data.sales_vs_stock || []).map((pt) => ({
    period: pt.period,
    sales: pt.sales,
    stockOnHand: pt.stock_on_hand,
    received: pt.received,
  }));

  const abcMix = (data.abc_mix || []).map((d) => ({
    tier: d.tier,
    count: d.count,
    sharePct: d.revenue_share_pct,
  }));

  const tierStock = (data.tier_stock || []).map((t) => ({
    tier: t.tier,
    inStock: t.in_stock,
    deadStock: t.dead_stock,
    noData: t.no_data,
    pendingReorderCount: t.pending_reorder_count,
  }));

  // While the card's own scope is loading, keep the last thing it showed
  // on screen (dimmed) rather than blanking it.
  const cardForecastReady = cardForecast?.key === forecastKey;
  const forecastUpdating = !forecastFollowsPage && !cardForecastReady;
  const forecastError = !forecastFollowsPage && cardForecastReady && cardForecast.error;
  const portfolioForecast = forecastFollowsPage
    ? data.portfolio_forecast || {}
    : (cardForecast?.data ?? data.portfolio_forecast) || {};
  const portfolioSeries = (portfolioForecast.series || []).map((pt) => ({
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

  const exposure = data.safety_stock_exposure || {};
  const exposureReason = exposure.blocked_reason || 'Safety-stock exposure cannot be measured yet';
  // Health tier for the safety-stock card, from the same rate the
  // exposure figures are derived from.
  const ssTier = safetyStockMetricType(kpis.safety_stock_rate ?? null);
  const belowSs = kpiDisplay(
    exposure.below_count ?? null, exposure.below_count == null ? exposureReason : null,
    (v) => `${v.toLocaleString()} of ${(exposure.comparable_count ?? 0).toLocaleString()}`,
    'Measurable Category A SKUs below their safety stock'
  );

  // Pending action count — the "what to do" figure in the hero strip.
  const pendingCount = data.recommendations?.product_count ?? 0;

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
          {/* Hero strip — the five figures that answer "what is happening
              right now": money in, money parked, service risk, cover vs the
              policy this project exists to replace, and work waiting. */}
          <div className="kpi-strip kpi-strip-hero">
            <KPICard
              title="Sales"
              value={sales.value}
              contextLine={sales.contextLine}
              icon={<Wallet size={20} />}
            />
            <KPICard
              title="Stock on hand value"
              value={sohValue.value}
              contextLine={sohValue.contextLine}
              icon={<Package size={20} />}
            />
            <KPICard
              title="Below safety stock"
              value={belowSs.value}
              metricType={belowSs.value === '—' ? undefined : ssTier}
              contextLine={belowSs.contextLine}
              icon={<AlertTriangle size={20} />}
            />
            <KPICard
              title="Weeks of cover"
              value={weeksOfCoverDisplay.value}
              metricType={weeksOfCoverMetricType}
              isOverTarget={weeksOfCoverIsOverTarget}
              contextLine={weeksOfCoverDisplay.contextLine}
              icon={<Clock size={20} />}
            />
            <KPICard
              title="Pending reorder actions"
              value={pendingCount.toLocaleString()}
              metricType="recommendation"
              contextLine="LP recommendations awaiting a decision"
              icon={<ClipboardList size={20} />}
            />
          </div>

          {/* DESCRIPTIVE — what happened */}
          <div className="dash-row dash-row-wide-narrow">
            <Slot kind="Descriptive"><SalesVsStockWidget data={salesVsStock} /></Slot>
            <Slot kind="Descriptive"><ABCDonutWidget data={abcMix} revenue={data.abc_revenue} /></Slot>
          </div>

          {/* DESCRIPTIVE + DIAGNOSTIC — the state, then why it looks that way */}
          <div className="dash-row dash-row-narrow-wide">
            <Slot kind="Descriptive"><CategoryStockBarWidget data={tierStock} /></Slot>
            <Slot kind="Diagnostic"><DemandVolatilityWidget summary={segmentSummary} /></Slot>
          </div>

          {/* PREDICTIVE + PRESCRIPTIVE — what next, and what to do */}
          <div className="dash-row dash-row-even">
            <Slot kind="Predictive">
              <PortfolioForecastWidget
                series={portfolioSeries}
                gatedSkuCount={portfolioForecast.gated_sku_count ?? 0}
                avgMape={portfolioForecast.avg_mape}
                scopeLabel={portfolioForecast.scope_label}
                emptyReason={
                  forecastError
                    ? `Couldn't load the forecast for ${labelForPrincipal(forecastPrincipal)}.`
                    : portfolioForecast.scope_label
                }
                principal={forecastPrincipal}
                onPrincipalChange={setForecastPrincipal}
                isUpdating={forecastUpdating}
              />
            </Slot>
            <Slot kind="Prescriptive">
              <ReorderRecommendationWidget
                rows={reorderRows}
                criticalCount={reorderPreview.critical_count ?? 0}
                urgentCount={reorderPreview.urgent_count ?? 0}
                totalOrderQty={reorderPreview.total_order_qty ?? 0}
                weights={reorderPreview.lp_weights}
              />
            </Slot>
          </div>

          {/* PRESCRIPTIVE — the policy question this project exists to answer */}
          <div className="dash-row dash-row-single">
            <Slot kind="Prescriptive"><PolicyComparisonWidget comparison={data.policy_comparison} /></Slot>
          </div>

          <p className="dash-footnote">
            Reorder Recs ranks every pending recommendation by revenue at risk and shows the top 20 as
            &ldquo;Act now&rdquo;.{' '}
            <Link to="/reorder" className="band-link">Open Reorder Recs <ArrowRight size={12} /></Link>
          </p>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
