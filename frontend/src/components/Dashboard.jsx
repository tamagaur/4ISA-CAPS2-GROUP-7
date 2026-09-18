import React, { useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import KPICard from './KPICard';
import DateFilter from './DateFilter';
import {
  SalesVsStockWidget, ABCDonutWidget, CategoryStockBarWidget,
  PortfolioForecastWidget, ReorderRecommendationWidget,
  formatCompactPesos,
} from './Charts';
import { getDashboardData, peekDashboardData } from '../api/dashboard';
import { Package, Wallet, ShieldAlert, Clock } from 'lucide-react';
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

const formatPercent = (v) => `${Math.round(v * 100)}%`;

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

// Same outer structure and card classes as the loaded page below, so every
// block lands at its final size — nothing jumps when the real data replaces
// it. Replaces a lone "Loading dashboard data…" line that left the page
// blank for the whole /dashboard request (measured 5.4–7.1s).
const DashboardSkeleton = () => (
  <div className="dashboard-body" aria-hidden="true">
    <div className="dashboard-section">
      <div className="kpi-grid">
        {[0, 1, 2, 3].map((i) => (
          <div className="kpi-card skeleton-card" key={i}>
            <div className="skeleton-line skeleton-line-title" />
            <div className="skeleton-line skeleton-line-value" />
            <div className="skeleton-line skeleton-line-subtext" />
          </div>
        ))}
      </div>
    </div>
    <div className="dashboard-section">
      <div className="chart-primary">
        <div className="chart-widget skeleton-card">
          <div className="skeleton-line skeleton-line-title" />
          <div className="skeleton-chart-body" />
        </div>
      </div>
    </div>
    {['chart-duo chart-duo-abc', 'chart-duo chart-duo-tall'].map((rowClass) => (
      <div className="dashboard-section" key={rowClass}>
        <div className={rowClass}>
          {[0, 1].map((i) => (
            <div className="chart-widget skeleton-card" key={i}>
              <div className="skeleton-line skeleton-line-title" />
              <div className="skeleton-chart-body" />
            </div>
          ))}
        </div>
      </div>
    ))}
  </div>
);

const Dashboard = () => {
  const { startMonth, startYear, endMonth, endYear, principal } = useOutletContext() || {};
  const period = toPeriod(endMonth, endYear);
  const startPeriod = toPeriod(startMonth, startYear);
  const requestKey = `${period ?? ''}|${startPeriod ?? ''}`;

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
  const safetyStockRate = kpiDisplay(
    kpis.safety_stock_rate, kpis.safety_stock_rate_blocked_reason, formatPercent, 'Share of Category A SKUs at/above safety stock'
  );

  const weeksOfCoverValue = weeksOfCover.value ?? null;
  const weeksOfCoverReason = weeksOfCover.blocked_reason ?? null;
  const weeksOfCoverDisplay = kpiDisplay(
    weeksOfCoverValue, weeksOfCoverReason, (v) => `${v.toFixed(1)} wks`, "vs. SSM's 3-week policy"
  );
  // Below policy is a stockout-risk signal (KPICard's 'danger' tier is
  // documented for exactly this "too little" case); at/above policy reads
  // as excess tied-up capital via the 'gap' tier's isOverTarget branch.
  // Blocked (no value to judge) falls back to the same neutral 'action'
  // tier the other three cards already use in their own blocked state —
  // never a colored verdict on data that isn't there.
  const weeksOfCoverMetricType =
    weeksOfCoverValue === null ? 'recommendation' : weeksOfCoverValue < policyWeeks ? 'danger' : 'gap';
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

  const portfolioForecast = data.portfolio_forecast || {};
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

  return (
    <div className="dashboard">
      <div className="dashboard-content">
        {header}

        {isRefreshing && (
          <p className="dashboard-refreshing" role="status">
            <span className="dashboard-refreshing-dot" aria-hidden="true" />
            Updating to {startMonth} {startYear} – {endMonth} {endYear}…
          </p>
        )}

        <div className={`dashboard-body${isRefreshing ? ' is-refreshing' : ''}`} aria-busy={isRefreshing}>
        {/* ── 4 KPI cards ────────────────────────────────────────────── */}
        <div className="dashboard-section">
          <div className="kpi-grid">
            <KPICard
              title="Sales"
              value={sales.value}
              metricType="recommendation"
              contextLine={sales.contextLine}
              icon={<Wallet size={20} />}
            />
            <KPICard
              title="Stock on hand value"
              value={sohValue.value}
              metricType="recommendation"
              contextLine={sohValue.contextLine}
              icon={<Package size={20} />}
            />
            <KPICard
              title="SKUs at or above safety stock"
              value={safetyStockRate.value}
              metricType="recommendation"
              contextLine={safetyStockRate.contextLine}
              icon={<ShieldAlert size={20} />}
            />
            <KPICard
              title="Weeks of cover"
              value={weeksOfCoverDisplay.value}
              metricType={weeksOfCoverMetricType}
              isOverTarget={weeksOfCoverIsOverTarget}
              contextLine={weeksOfCoverDisplay.contextLine}
              icon={<Clock size={20} />}
            />
          </div>
        </div>

        {/* ── Sales vs. Stock on Hand — hero chart ──────────────────────── */}
        <div className="dashboard-section">
          <div className="chart-primary">
            <SalesVsStockWidget data={salesVsStock} />
          </div>
        </div>

        {/* ── ABC donut + category stock matrix ─────────────────────────── */}
        <div className="dashboard-section">
          <div className="chart-duo chart-duo-abc">
            <ABCDonutWidget data={abcMix} />
            <CategoryStockBarWidget data={tierStock} />
          </div>
        </div>

        {/* ── Portfolio-level aggregate forecast + reorder recommendations ── */}
        <div className="dashboard-section">
          <div className="chart-duo chart-duo-tall">
            <PortfolioForecastWidget
              series={portfolioSeries}
              gatedSkuCount={portfolioForecast.gated_sku_count ?? 0}
              avgMape={portfolioForecast.avg_mape}
              scopeLabel={portfolioForecast.scope_label}
              emptyReason={portfolioForecast.scope_label}
            />
            <ReorderRecommendationWidget
              rows={reorderRows}
              criticalCount={reorderPreview.critical_count ?? 0}
              urgentCount={reorderPreview.urgent_count ?? 0}
              totalOrderQty={reorderPreview.total_order_qty ?? 0}
              weights={reorderPreview.lp_weights}
            />
          </div>
        </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
