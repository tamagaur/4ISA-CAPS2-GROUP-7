import React, { useEffect, useState } from 'react';
import { useOutletContext, Link } from 'react-router-dom';
import KPICard from './KPICard';
import DateFilter from './DateFilter';
import {
  SalesVsStockWidget, ABCDonutWidget, CategoryStockBarWidget,
  PortfolioForecastWidget, ReorderRecommendationWidget, PolicyComparisonWidget,
  formatCompactPesos,
} from './Charts';
import { getDashboardData, peekDashboardData } from '../api/dashboard';
import { formatMonth } from '../utils/formatDate';
import { Package, Wallet, ShieldAlert, Clock, ArrowRight, Layers, Boxes, AlertTriangle, Percent } from 'lucide-react';
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
const formatUnitsCompact = (v) => {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(abs / 1_000_000).toFixed(2).replace(/\.?0+$/, '')}M`;
  if (abs >= 1_000) return `${Math.round(abs / 1_000)}k`;
  return `${Math.round(abs)}`;
};

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

// ── Band headlines — generated from the response, never hardcoded ──────
// Each returns { text, reason }: `text` is the takeaway sentence, `reason`
// an optional second line explaining what could not be computed. When a
// band's data is missing the text says so, in place of a number.

function moneyHeadline({ sohValue, sohReason, abcMix, abcRevenue }) {
  const tierA = abcMix.find((t) => t.tier === 'A');
  const totalSkus = abcMix.reduce((sum, t) => sum + t.count, 0);
  const abcPart = tierA && totalSkus
    ? `Category A — ${tierA.count} of ${totalSkus.toLocaleString()} SKUs (${Math.round((tierA.count / totalSkus) * 100)}%) — earns ${Math.round(tierA.sharePct)}% of revenue`
      + (abcRevenue?.total != null ? ` (${formatCompactPesos(abcRevenue.total)} in ${formatMonth(abcRevenue.period)})` : '')
    : null;
  if (sohValue != null && abcPart) return { text: `${formatCompactPesos(sohValue)} in stock — ${abcPart}.`, reason: null };
  if (sohValue != null) return { text: `${formatCompactPesos(sohValue)} in stock; no ABC classification to show where it sits.`, reason: null };
  if (abcPart) return { text: `${abcPart}; stock value is not available.`, reason: sohReason };
  return { text: 'Stock value and ABC mix are not available for this selection.', reason: sohReason };
}

function riskHeadline(exposure) {
  if (!exposure || exposure.below_count == null) {
    return { text: 'Safety-stock exposure cannot be measured yet.', reason: exposure?.blocked_reason || null };
  }
  const share = exposure.below_revenue_share != null ? ` — ${Math.round(exposure.below_revenue_share * 100)}% of revenue exposed` : '';
  const unmeasured = exposure.tier_a_count - exposure.comparable_count;
  return {
    text: `${exposure.below_count} of ${exposure.comparable_count} measurable Category A SKUs sit below safety stock${share}.`,
    reason: unmeasured > 0
      ? `${unmeasured} Category A SKU${unmeasured === 1 ? '' : 's'} could not be measured (no stock record or no pending recommendation) and are excluded, not counted as failing.`
      : null,
  };
}

function actionHeadline({ productCount, preview }) {
  if (!productCount) return { text: 'No pending reorder recommendations.', reason: null };
  const parts = [`${preview.critical_count ?? 0} critical`, `${preview.urgent_count ?? 0} urgent`];
  if (preview.no_data_count) parts.push(`${preview.no_data_count} with no stock record`);
  return {
    text: `${productCount.toLocaleString()} pending recommendations across all planning cycles — ${parts.join(', ')}.`,
    reason: null,
  };
}

function savingsHeadline(pc) {
  if (!pc || pc.lp_safety_stock_units == null || pc.rule_safety_stock_units == null) {
    return { text: 'The LP policy cannot be compared with the 3-week rule yet.', reason: pc?.blocked_reason || null };
  }
  const diff = pc.rule_safety_stock_units - pc.lp_safety_stock_units;
  const pctDiff = pc.rule_safety_stock_units > 0 ? Math.round((Math.abs(diff) / pc.rule_safety_stock_units) * 100) : null;
  const direction = diff >= 0 ? 'less' : 'more';
  return {
    text: `LP safety stock totals ${formatUnitsCompact(pc.lp_safety_stock_units)} units across ${pc.sku_count} SKUs vs ${formatUnitsCompact(pc.rule_safety_stock_units)} under the blanket ${pc.rule_weeks}-week rule`
      + (pctDiff != null ? ` — ${pctDiff}% ${direction} buffer stock for the ${formatMonth(pc.cycle_date)} cycle.` : '.'),
    reason: 'Demand units, not pesos — no per-piece cost is recorded, so the peso value of the difference is not computed.',
  };
}

const Band = ({ index, kicker, headline, children }) => (
  <section className="dashboard-band" aria-labelledby={`band-${index}`}>
    <header className="band-header">
      <span className="band-kicker">{index} · {kicker}</span>
      <h3 className="band-headline" id={`band-${index}`}>{headline.text}</h3>
      {headline.reason && <p className="band-reason">{headline.reason}</p>}
    </header>
    {children}
  </section>
);

// Same outer structure and card classes as the loaded page below, so every
// block lands at its final size — nothing jumps when the real data replaces
// it. Replaces a lone "Loading dashboard data…" line that left the page
// blank for the whole /dashboard request (measured 5.4–7.1s).
const DashboardSkeleton = () => (
  <div className="dashboard-body" aria-hidden="true">
    {[0, 1, 2, 3].map((i) => (
      <section className="dashboard-band" key={i}>
        <header className="band-header">
          <div className="skeleton-line skeleton-line-title" />
          <div className="skeleton-line skeleton-line-headline" />
        </header>
        {i < 2 ? (
          <>
            <div className="kpi-strip">
              {[0, 1, 2, 3].map((k) => (
                <div className="kpi-card skeleton-card" key={k}>
                  <div className="skeleton-line skeleton-line-title" />
                  <div className="skeleton-line skeleton-line-value" />
                  <div className="skeleton-line skeleton-line-subtext" />
                </div>
              ))}
            </div>
            <div className={`band-charts ${i === 0 ? 'band-charts-money' : 'band-charts-risk'}`}>
              {[0, 1].map((k) => (
                <div className="chart-widget skeleton-card" key={k}>
                  <div className="skeleton-line skeleton-line-title" />
                  <div className="skeleton-chart-body" />
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="chart-widget skeleton-card">
            <div className="skeleton-line skeleton-line-title" />
            <div className="skeleton-chart-body" />
          </div>
        )}
      </section>
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

  // Strip figures for bands 1 and 2. Every one comes from a field the
  // band's headline is already built from, so a card and its headline can
  // never disagree; a missing field renders "—" with the reason, never 0.
  const tierA = abcMix.find((t) => t.tier === 'A');
  const totalSkus = abcMix.reduce((sum, t) => sum + t.count, 0);
  const noAbcReason = tierA ? null : 'No ABC classification for this selection';
  const catAShare = kpiDisplay(
    tierA ? tierA.sharePct : null, noAbcReason,
    (v) => `${Math.round(v)}%`, 'Share of revenue earned by Category A'
  );
  const catASkuPct = tierA && totalSkus ? Math.round((tierA.count / totalSkus) * 100) : null;
  const catASkus = kpiDisplay(
    tierA ? tierA.count : null, noAbcReason,
    (v) => `${v.toLocaleString()} of ${totalSkus.toLocaleString()}`,
    catASkuPct != null ? `${catASkuPct}% of all classified SKUs` : ''
  );

  const exposure = data.safety_stock_exposure || {};
  const exposureReason = exposure.blocked_reason || 'Safety-stock exposure cannot be measured yet';
  // One fact, three cards (at/above %, below count, revenue exposed) — they
  // share the same health tier so the band can't show mixed verdicts.
  const ssTier = safetyStockMetricType(kpis.safety_stock_rate ?? null);
  const belowSs = kpiDisplay(
    exposure.below_count ?? null, exposure.below_count == null ? exposureReason : null,
    (v) => `${v.toLocaleString()} of ${(exposure.comparable_count ?? 0).toLocaleString()}`,
    'Measurable Category A SKUs below their safety stock'
  );
  const revenueExposed = kpiDisplay(
    exposure.below_revenue_share ?? null, exposure.below_revenue_share == null ? exposureReason : null,
    formatPercent, 'Revenue share of the SKUs below safety stock'
  );

  const headlines = {
    money: moneyHeadline({
      sohValue: kpis.soh_value ?? null,
      sohReason: kpis.soh_value_blocked_reason,
      abcMix,
      abcRevenue: data.abc_revenue,
    }),
    risk: riskHeadline(data.safety_stock_exposure),
    action: actionHeadline({ productCount: data.recommendations?.product_count ?? 0, preview: reorderPreview }),
    savings: savingsHeadline(data.policy_comparison),
  };

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
          {/* ── 1. Where our money is ─────────────────────────────────── */}
          <Band index={1} kicker="Where our money is" headline={headlines.money}>
            <div className="kpi-strip">
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
                title="Category A share of revenue"
                value={catAShare.value}
                contextLine={catAShare.contextLine}
                icon={<Layers size={20} />}
              />
              <KPICard
                title="Category A SKUs"
                value={catASkus.value}
                contextLine={catASkus.contextLine}
                icon={<Boxes size={20} />}
              />
            </div>
            <div className="band-charts band-charts-money">
              <SalesVsStockWidget data={salesVsStock} />
              <ABCDonutWidget data={abcMix} revenue={data.abc_revenue} />
            </div>
          </Band>

          {/* ── 2. What's at risk ─────────────────────────────────────── */}
          <Band index={2} kicker="What's at risk" headline={headlines.risk}>
            <div className="kpi-strip">
              <KPICard
                title="SKUs at or above safety stock"
                value={safetyStockRate.value}
                metricType={ssTier}
                contextLine={safetyStockRate.contextLine}
                icon={<ShieldAlert size={20} />}
              />
              <KPICard
                title="Below safety stock"
                value={belowSs.value}
                metricType={belowSs.value === '—' ? undefined : ssTier}
                contextLine={belowSs.contextLine}
                icon={<AlertTriangle size={20} />}
              />
              <KPICard
                title="Revenue exposed"
                value={revenueExposed.value}
                metricType={revenueExposed.value === '—' ? undefined : ssTier}
                contextLine={revenueExposed.contextLine}
                icon={<Percent size={20} />}
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
            <div className="band-charts band-charts-risk">
              <CategoryStockBarWidget data={tierStock} />
              <PortfolioForecastWidget
                series={portfolioSeries}
                gatedSkuCount={portfolioForecast.gated_sku_count ?? 0}
                avgMape={portfolioForecast.avg_mape}
                scopeLabel={portfolioForecast.scope_label}
                emptyReason={portfolioForecast.scope_label}
              />
            </div>
          </Band>

          {/* ── 3. What to do ─────────────────────────────────────────── */}
          <Band index={3} kicker="What to do" headline={headlines.action}>
            <div className="band-reorder">
              <ReorderRecommendationWidget
                rows={reorderRows}
                criticalCount={reorderPreview.critical_count ?? 0}
                urgentCount={reorderPreview.urgent_count ?? 0}
                totalOrderQty={reorderPreview.total_order_qty ?? 0}
                weights={reorderPreview.lp_weights}
              />
            </div>
            <p className="band-footnote">
              Reorder Recs ranks every pending recommendation by revenue at risk and shows the top 20 as
              &ldquo;Act now&rdquo;.{' '}
              <Link to="/reorder" className="band-link">Open Reorder Recs <ArrowRight size={12} /></Link>
            </p>
          </Band>

          {/* ── 4. What it saves ──────────────────────────────────────── */}
          <Band index={4} kicker="What it saves" headline={headlines.savings}>
            <PolicyComparisonWidget comparison={data.policy_comparison} />
          </Band>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
