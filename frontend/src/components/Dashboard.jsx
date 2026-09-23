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
import { staleCoverageNotice } from '../dataCoverage';
import { isPlaceholderPeriod, isPreviewMode } from '../dataMode';
import { useEntranceReplay } from '../theme/useEntranceReplay';
import RefreshingNote from './RefreshingNote';
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

// Names the principals a figure actually covers, but only when that is
// NARROWER than what the user asked for — saying "Unilever only" while the
// Unilever filter is already on would be noise. Under All principals it is
// the whole point: stock valuation and the ABC run are Unilever-only today
// (Del Monte carries no unit cost, and the latest ABC run has no Del Monte
// rows), which the page used to present as the portfolio's own numbers.
const PRINCIPAL_NAMES = { unilever: 'Unilever', delmonte: 'Del Monte' };
const coverageNote = (coverage, pagePrincipal) => {
  if (!coverage || coverage.length === 0) return null;
  if (pagePrincipal !== DEFAULT_PRINCIPAL) return null;
  if (coverage.length > 1) return null;
  return `${PRINCIPAL_NAMES[coverage[0]] || coverage[0]} only`;
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
// Each widget is tagged with the kind of analytics it answers, so the four
// types are demonstrable at a glance without a paragraph above each one.
//   Descriptive — what happened
//   Diagnostic  — why it happened
//   Predictive  — what happens next
//   Prescriptive— what to do about it
// `realOnly` (preview mode only) tags a predictive or prescriptive widget
// that preview deliberately leaves on real data (backend/data_mode.py), so
// the page says which cards the placeholder months reach and which not.
const Slot = ({ kind, realOnly = false, children }) => (
  <div className="dash-slot" data-kind={kind}>
    <span className="dash-kind-row">
      <span className="dash-kind">{kind}</span>
      {realOnly && (
        <span className="dash-real-only" title="Preview adds placeholder months to descriptive and diagnostic views only. This card reads real data.">
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
// blank for the whole /dashboard request (measured 5.4–7.1s).
const DashboardSkeleton = () => (
  <div className="dashboard-body" aria-hidden="true">
    <div className="kpi-strip kpi-strip-hero">
      {[0, 1, 2, 3].map((k) => (
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
  //
  // Deliberately not remembered (no localStorage, unlike the Topbar's
  // filter): every visit to the dashboard starts this card on All
  // principals, and the card's Reset button returns it there.
  const pagePrincipal = principal ?? DEFAULT_PRINCIPAL;
  const [forecastPrincipal, setForecastPrincipal] = useState(DEFAULT_PRINCIPAL);
  const forecastKey = `${period ?? ''}|${startPeriod ?? ''}|${forecastPrincipal}`;
  const forecastFollowsPage = forecastPrincipal === pagePrincipal;
  const [cardForecast, setCardForecast] = useState(null); // { key, data, reliability, error }
  const cardForecastKey = cardForecast?.key;
  useEffect(() => {
    if (forecastFollowsPage || cardForecastKey === forecastKey) return undefined;
    let cancelled = false;
    getDashboardData({ period, startPeriod, principal: forecastPrincipal })
      .then((res) => {
        if (!cancelled) setCardForecast({ key: forecastKey, data: res.portfolio_forecast || {}, reliability: res.forecast || null });
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
      ? `${periodLabel(period)} is a placeholder month — these tiers come from placeholder sales, not SSM's.`
      : null
  );

  // Each card names the month it is for, and the principals it covers when
  // those are narrower than the page's own filter — see periodLabel /
  // coverageNote above for why both are necessary.
  const salesMonth = periodLabel(kpis.sales_period);
  const sohMonth = periodLabel(kpis.soh_period);
  const sohCoverage = coverageNote(kpis.soh_coverage, pagePrincipal);
  const salesIsPlaceholder = isPlaceholderPeriod(kpis.sales_period, placeholder);
  const sales = kpiDisplay(
    kpis.sales, kpis.sales_blocked_reason, formatCompactPesos,
    salesMonth ? `Total sales · ${salesMonth}${salesIsPlaceholder ? ' (placeholder)' : ''}` : 'Total sales',
  );
  const sohValue = kpiDisplay(
    kpis.soh_value, kpis.soh_value_blocked_reason, formatCompactPesos,
    [sohMonth ? `Stock-on-hand valuation · ${sohMonth}` : 'Stock-on-hand valuation', sohCoverage]
      .filter(Boolean).join(' · '),
  );

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
  // The card's own scope for the MASE reliability count too (GET
  // /dashboard's forecast block), so the two never describe different
  // principals. Null while that scope is still loading.
  const forecastReliability = forecastFollowsPage
    ? data.forecast || null
    : (cardForecastReady ? cardForecast?.reliability ?? null : null);
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

  // Pending action count — the "what to do" figure in the hero strip. Now
  // the CURRENT LP cycle only: it counted every undecided row ever written,
  // so 179 leftovers from runs going back to 2023-05 were being presented
  // as work awaiting a decision today (429 against the real 250).
  const pendingCount = data.recommendations?.product_count ?? 0;
  const lp = data.lp || {};
  // Non-null only when the live data has moved past the hardcoded ceiling.
  const coverageStale = staleCoverageNotice(data.latest_data_period);
  const lpCycleLabel = periodLabel(lp.cycle_date ? String(lp.cycle_date).slice(0, 7) : null);
  const pendingContext = [
    'LP recommendations awaiting a decision',
    lpCycleLabel ? `${lpCycleLabel} cycle` : null,
  ].filter(Boolean).join(' · ');

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
              so instead, naming the one file to edit. */}
          {coverageStale && (
            <div className="dash-stale-note" role="status">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                <strong>New data has loaded past the date picker&apos;s range.</strong>{' '}
                The database now holds sales through {coverageStale.live}, but this app is pinned to{' '}
                {coverageStale.pinned}. Update <code>LATEST_DATA_PERIOD</code> in{' '}
                <code>frontend/src/dataCoverage.js</code> so the picker and every default range
                reach the newest month.
              </span>
            </div>
          )}

          {/* The LP's own freshness. q_i and rop_i are solved against the
              forecasts of the day the LP ran; when the forecasts are later
              rewritten (they were, on 2026-09-21, while the LP last ran
              2026-08-24) those two are built on numbers the table no longer
              holds. Safety stock is unaffected — it comes from demand
              history, not from a model. Stated on the page rather than
              left for someone to discover in a report. */}
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
              title="Pending reorder actions"
              value={pendingCount.toLocaleString()}
              metricType="recommendation"
              contextLine={pendingContext}
              icon={<ClipboardList size={20} />}
            />
          </div>

          {/* DESCRIPTIVE — what happened */}
          <div className="dash-row dash-row-wide-narrow">
            <Slot kind="Descriptive"><SalesVsStockWidget data={salesVsStock} placeholder={placeholder} /></Slot>
            <Slot kind="Descriptive">
              <ABCDonutWidget data={abcMix} revenue={data.abc_revenue} note={placeholderNote(data.abc_revenue?.period)} />
            </Slot>
          </div>

          {/* DESCRIPTIVE + DIAGNOSTIC — the state, then why it looks that way */}
          <div className="dash-row dash-row-narrow-wide">
            <Slot kind="Descriptive">
              <CategoryStockBarWidget data={tierStock} note={placeholderNote(data.abc_revenue?.period)} />
            </Slot>
            <Slot kind="Diagnostic"><DemandVolatilityWidget summary={segmentSummary} /></Slot>
          </div>

          {/* PREDICTIVE + PRESCRIPTIVE — what next, and what to do */}
          <div className="dash-row dash-row-even">
            <Slot kind="Predictive" realOnly={portfolioRealOnly}>
              <PortfolioForecastWidget
                series={portfolioSeries}
                gatedSkuCount={portfolioForecast.gated_sku_count ?? 0}
                avgMape={portfolioForecast.avg_mape}
                scopeLabel={portfolioForecast.scope_label}
                // The backend's scope_label already says it plainly for Del
                // Monte ("No SKU-level forecasts exist for Del Monte — …").
                // The local sentence only stands in if it is ever missing,
                // so the card can't fall back to a generic "No forecast data".
                emptyReason={
                  forecastError
                    ? `Couldn't load the forecast for ${labelForPrincipal(forecastPrincipal)}.`
                    : portfolioForecast.scope_label
                      || (forecastPrincipal === 'delmonte'
                        ? 'No SKU-level forecasts for Del Monte — it has no SKU-level sales data, only category sell-out.'
                        : undefined)
                }
                principal={forecastPrincipal}
                onPrincipalChange={setForecastPrincipal}
                isUpdating={forecastUpdating}
                reliability={forecastReliability}
              />
            </Slot>
            <Slot kind="Prescriptive" realOnly={preview && realOnly.has('reorder_preview')}>
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
            <Slot kind="Prescriptive" realOnly={preview && realOnly.has('policy_comparison')}>
              <PolicyComparisonWidget comparison={data.policy_comparison} />
            </Slot>
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
