import React, { useEffect, useMemo, useState } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import KPICard from './KPICard';
import { CoverTrendWidget, ABCClassificationWidget } from './Charts';
import AlertsList from './AlertsList';
import DateFilter from './DateFilter';
import { getDashboardData } from '../api/dashboard';
import { Wallet, FlaskConical, ShieldAlert, Timer, ShoppingCart } from 'lucide-react';
import './Dashboard.css';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// startMonth/startYear/endMonth/endYear are month-name + year strings (the
// rest of the app's period-picker convention); getDashboardData wants ISO
// dates, so this is the one place that bridges the two.
function toISODateRange(startMonth, startYear, endMonth, endYear) {
  const startIdx = Math.max(0, MONTH_NAMES.indexOf(startMonth));
  const endIdx = Math.max(0, MONTH_NAMES.indexOf(endMonth));
  const from = `${startYear}-${String(startIdx + 1).padStart(2, '0')}-01`;
  const lastDay = new Date(Number(endYear), endIdx + 1, 0).getDate();
  const to = `${endYear}-${String(endIdx + 1).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
  return { from, to };
}

// Arrow glyph is pure fact (which way the number moved) — kept separate
// from the tier/colour decision, which now lives entirely in KPICard.jsx
// keyed off metricType + direction/isOverTarget, never off a number's sign.
function arrowFromDelta(delta) {
  if (!delta) return null;
  return delta > 0 ? 'up' : 'down';
}

const KPISkeleton = () => (
  <div className="kpi-card skeleton-card">
    <div className="skeleton-line skeleton-line-title" />
    <div className="skeleton-line skeleton-line-value" />
    <div className="skeleton-line skeleton-line-subtext" />
  </div>
);

const ChartSkeleton = () => (
  <div className="chart-widget skeleton-card">
    <div className="skeleton-line skeleton-line-title" style={{ width: '30%' }} />
    <div className="skeleton-chart-body" />
  </div>
);

const AlertsSkeleton = () => (
  <div className="alerts-widget skeleton-card">
    <div className="skeleton-line skeleton-line-title" style={{ width: '40%' }} />
    <div className="skeleton-line skeleton-line-row" />
    <div className="skeleton-line skeleton-line-row" />
    <div className="skeleton-line skeleton-line-row" />
  </div>
);

const EmptyNote = ({ children }) => <p className="dashboard-empty-note">{children}</p>;

const Dashboard = () => {
  const navigate = useNavigate();
  const { startMonth, startYear, endMonth, endYear, updatePeriodImmediately, realWorldPeriod, principal } = useOutletContext() || {
    startMonth: 'Apr', startYear: '2026', endMonth: 'Apr', endYear: '2026',
    updatePeriodImmediately: () => {},
    realWorldPeriod: { month: 'Aug', year: '2026' },
    principal: 'all',
  };

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryTick, setRetryTick] = useState(0);

  const { from, to } = useMemo(
    () => toISODateRange(startMonth, startYear, endMonth, endYear),
    [startMonth, startYear, endMonth, endYear]
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getDashboardData({ principal, from, to })
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError("Couldn't load dashboard data");
        setLoading(false);
      });

    // Ignores whatever this request eventually resolves with if the filter
    // changes again before it lands, so a slow stale response can never
    // clobber a newer selection's data.
    return () => {
      cancelled = true;
    };
  }, [principal, from, to, retryTick]);

  const handleRetry = () => setRetryTick((t) => t + 1);

  const view = useMemo(() => {
    if (!data) return null;
    const { kpis } = data;

    // Del Monte has no SKU-level data anywhere in this project — this reads
    // the grain the API already reports rather than checking the principal
    // name, so it's correct for a future fourth/fifth principal too.
    const unitNoun = data.abc.grain === 'category' ? 'categories' : 'products';

    const spoilageCostArrow = arrowFromDelta(kpis.spoilage_cost.delta_vs_prev);
    const stockoutArrow = arrowFromDelta(kpis.stockout_rate.delta_vs_prev);
    const overstockArrow = arrowFromDelta(kpis.weeks_of_cover.delta_vs_prev);

    const overstockWeeks = Number((kpis.weeks_of_cover.value - kpis.weeks_of_cover.policy_target).toFixed(1));
    const isOverstocked = overstockWeeks > 0;

    return {
      unitNoun,

      // TYPE 2 (gap) — the excess over policy is the headline, not the raw
      // held value; the raw held/justified figures are demoted to context.
      excessValue: `₱${kpis.trapped_capital.excess.value}M`,
      excessIsOverTarget: kpis.trapped_capital.excess.value > 0,
      excessContext: `₱${kpis.trapped_capital.held.value}M held · ₱${kpis.trapped_capital.justified.value}M justified by demand`,

      // TYPE 1 (loss) — colour comes from direction only; every card names
      // its baseline explicitly rather than just saying "this month".
      spoilageCostValue: `₱${kpis.spoilage_cost.value}k`,
      spoilageCostRawDirection: kpis.spoilage_cost.direction,
      spoilageCostArrow,
      spoilageCostDeltaLine: spoilageCostArrow
        ? `₱${Math.abs(kpis.spoilage_cost.delta_vs_prev).toFixed(1)}k ${spoilageCostArrow === 'up' ? 'more' : 'less'} than last month · ${kpis.spoilage_cost.incident_count} incidents`
        : `Unchanged from last month · ${kpis.spoilage_cost.incident_count} incidents`,

      stockoutValue: `${kpis.stockout_rate.value}%`,
      stockoutRawDirection: kpis.stockout_rate.direction,
      stockoutArrow,
      stockoutDeltaLine: stockoutArrow
        ? `${Math.abs(kpis.stockout_rate.delta_vs_prev).toFixed(1)}pp ${stockoutArrow === 'up' ? 'higher' : 'lower'} than last month`
        : 'Unchanged from last month',

      // TYPE 2 (gap) — headline is the overstock amount (weeks_of_cover
      // minus policy_target), computed here rather than hard-coded; zero or
      // negative reads as "Within policy" and the card turns green.
      overstockValue: isOverstocked ? `${overstockWeeks.toFixed(1)} weeks over` : 'Within policy',
      overstockIsOverTarget: isOverstocked,
      overstockContext: `${kpis.weeks_of_cover.value} weeks held · policy is ${kpis.weeks_of_cover.policy_target} weeks`,
      overstockArrow,
      overstockDeltaLine: overstockArrow
        ? `${Math.abs(kpis.weeks_of_cover.delta_vs_prev).toFixed(1)} weeks ${overstockArrow === 'up' ? 'more' : 'less'} than last month`
        : 'Unchanged from last month',

      // TYPE 3 (recommendation) — always neutral, never coloured by data.
      reorderValue: `₱${kpis.reorder_count.total_value}M`,
      reorderContext: `${kpis.reorder_count.value} ${unitNoun} need ordering`,

      reorderAlerts: data.reorder_alerts.map((a) => ({
        title: a.product_name,
        subtitle: `${a.sku_id} • Stock: ${a.current_stock} / ROP: ${a.rop}`,
        type: a.urgency,
      })),
      badOrders: data.bad_orders.map((b) => ({
        title: b.product_name,
        subtitle: `${b.incident_id} • ${b.reason} • Qty: ${b.quantity}`,
        type: b.status,
      })),
      badOrdersSummary: `${data.bad_orders.length} incidents this month · ${data.bad_orders.reduce((sum, b) => sum + b.quantity, 0)} units affected`,
    };
  }, [data]);

  const handleRefresh = () => {
    window.location.reload();
  };

  return (
    <div className="dashboard">
      <div className="dashboard-content">
        <div className="dashboard-header">
          <div className="dashboard-title-row">
            <h2>Inventory <span>pulse</span></h2>
            <DateFilter onRefresh={handleRefresh} />
          </div>

          <p>Real-time KPIs across SSM's Urdaneta warehouse. Last synced: {startMonth} {startYear} - {endMonth} {endYear}</p>
        </div>

        {error ? (
          <div className="dashboard-error-state">
            <p>{error}</p>
            <button className="dashboard-retry-btn" onClick={handleRetry}>Retry</button>
          </div>
        ) : (
          <>
            {/* Excess stock value is the hero (it's the problem); the other
                three metrics are smaller context tiles beside it. Recommended
                Order Value lives at the bottom now (next to the reorder list
                it explains), so only 3 tiles remain here — a vertical stack
                beside the hero rather than a literal 2x2. */}
            <div className="dashboard-section">
              <div className="kpi-hero-row">
                <div className="kpi-hero-wrapper">
                  {loading || !view ? (
                    <KPISkeleton />
                  ) : (
                    <KPICard
                      title="Excess stock value"
                      value={view.excessValue}
                      metricType="gap"
                      isOverTarget={view.excessIsOverTarget}
                      contextLine={view.excessContext}
                      icon={<Wallet size={28} />}
                    />
                  )}
                </div>
                <div className="kpi-tile-stack">
                  {loading || !view ? (
                    <>
                      <KPISkeleton />
                      <KPISkeleton />
                      <KPISkeleton />
                    </>
                  ) : (
                    <>
                      <KPICard
                        title="Lost to damage & expiry"
                        value={view.spoilageCostValue}
                        metricType="loss"
                        direction={view.spoilageCostRawDirection}
                        trendDirection={view.spoilageCostArrow}
                        deltaLine={view.spoilageCostDeltaLine}
                        icon={<FlaskConical size={18} />}
                      />
                      <KPICard
                        title="Top sellers out of stock"
                        value={view.stockoutValue}
                        metricType="loss"
                        direction={view.stockoutRawDirection}
                        trendDirection={view.stockoutArrow}
                        deltaLine={view.stockoutDeltaLine}
                        icon={<ShieldAlert size={18} />}
                      />
                      <KPICard
                        title="Stock above policy"
                        value={view.overstockValue}
                        metricType="gap"
                        isOverTarget={view.overstockIsOverTarget}
                        contextLine={view.overstockContext}
                        trendDirection={view.overstockArrow}
                        deltaLine={view.overstockDeltaLine}
                        icon={<Timer size={18} />}
                      />
                    </>
                  )}
                </div>
              </div>
            </div>

            <div className="dashboard-section">
              <div className="charts-grid">
                <div className="chart-large">
                  {loading || !data ? (
                    <ChartSkeleton />
                  ) : data.cover_series.length === 0 ? (
                    <div className="chart-widget"><EmptyNote>No data for this selection</EmptyNote></div>
                  ) : (
                    <CoverTrendWidget coverSeries={data.cover_series} policyTarget={data.kpis.weeks_of_cover.policy_target} />
                  )}
                </div>
                <div className="chart-small">
                  {loading || !data ? (
                    <ChartSkeleton />
                  ) : data.abc.tiers.length === 0 ? (
                    <div className="chart-widget"><EmptyNote>No data for this selection</EmptyNote></div>
                  ) : (
                    <ABCClassificationWidget abc={data.abc} />
                  )}
                </div>
              </div>
            </div>

            {/* Reorder action sits last, where the eye finishes, and the
                order-value figure is merged directly above the reorder list
                it refers to. */}
            <div className="dashboard-section">
              <div className="alerts-grid">
                <div className="reorder-merged-card">
                  {loading || !view ? (
                    <>
                      <KPISkeleton />
                      <AlertsSkeleton />
                    </>
                  ) : (
                    <>
                      <KPICard
                        title={view.unitNoun === 'categories' ? 'Categories to reorder' : 'Products to reorder'}
                        value={view.reorderValue}
                        metricType="recommendation"
                        contextLine={view.reorderContext}
                        icon={<ShoppingCart size={18} />}
                      />
                      {view.reorderAlerts.length === 0 ? (
                        <div className="alerts-widget"><EmptyNote>No data for this selection</EmptyNote></div>
                      ) : (
                        <AlertsList
                          title="Reorder alerts"
                          alerts={view.reorderAlerts}
                          onViewAll={() => navigate('/reorder')}
                        />
                      )}
                    </>
                  )}
                </div>
                <div className="bad-orders-card">
                  {loading || !view ? (
                    <AlertsSkeleton />
                  ) : view.badOrders.length === 0 ? (
                    <div className="alerts-widget"><EmptyNote>No data for this selection</EmptyNote></div>
                  ) : (
                    <AlertsList
                      title={(
                        <span className="alerts-title-block">
                          Recent bad orders
                          <span className="alerts-title-summary">{view.badOrdersSummary}</span>
                        </span>
                      )}
                      alerts={view.badOrders}
                      onViewAll={() => navigate('/bad-orders')}
                    />
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default Dashboard;
