import React, { useEffect, useMemo, useState } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import KPICard from './KPICard';
import { BadOrderTrendWidget, ABCClassificationWidget } from './Charts';
import AlertsList from './AlertsList';
import DateFilter from './DateFilter';
import { getDashboardData } from '../api/dashboard';
import { FlaskConical, ShieldAlert, ShoppingCart, Wallet } from 'lucide-react';
import './Dashboard.css';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// startMonth/startYear/endMonth/endYear are month-name + year strings (the
// rest of the app's period-picker convention); getDashboardData wants ISO
// dates, so this is the one place that bridges the two.
function toISODateRange(startMonth, startYear, endMonth, endYear) {
  const startIdx = Math.max(0, MONTH_NAMES.indexOf(startMonth));
  const endIdx   = Math.max(0, MONTH_NAMES.indexOf(endMonth));
  const from = `${startYear}-${String(startIdx + 1).padStart(2, '0')}-01`;
  const lastDay = new Date(Number(endYear), endIdx + 1, 0).getDate();
  const to   = `${endYear}-${String(endIdx + 1).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
  return { from, to };
}

// Arrow glyph is pure fact (which way the number moved).
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
  const {
    startMonth, startYear, endMonth, endYear,
    updatePeriodImmediately, realWorldPeriod, principal,
  } = useOutletContext() || {
    startMonth: 'Apr', startYear: '2026', endMonth: 'Apr', endYear: '2026',
    updatePeriodImmediately: () => {},
    realWorldPeriod: { month: 'Aug', year: '2026' },
    principal: 'all',
  };

  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [retryTick, setRetryTick] = useState(0);

  const { from, to } = useMemo(
    () => toISODateRange(startMonth, startYear, endMonth, endYear),
    [startMonth, startYear, endMonth, endYear],
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

    return () => { cancelled = true; };
  }, [principal, from, to, retryTick]);

  const handleRetry   = () => setRetryTick((t) => t + 1);
  const handleRefresh = () => window.location.reload();

  const view = useMemo(() => {
    if (!data) return null;
    const { kpis } = data;
    const unitNoun = kpis.reorder_items.unit_noun;

    // ── KPI 1: Bad Order Value ──────────────────────────────────────────────
    // Source: SalesReturn_Fact.net_amount aggregated by period.
    // Value-based only — bo_units is always NULL in real source files.
    const boValueArrow = arrowFromDelta(kpis.bad_order_value.delta_vs_prev);
    const boValueDelta = kpis.bad_order_value.delta_vs_prev;
    const br           = kpis.bad_order_value.by_reason;

    // ── KPI 2: Active Incidents ─────────────────────────────────────────────
    // Source: COUNT of OPEN + UNDER INVESTIGATION rows in SalesReturn_Fact.
    const incArrow = arrowFromDelta(kpis.bad_order_incidents.delta_vs_prev);

    return {
      unitNoun,

      // KPI 1
      boValue:      `₱${kpis.bad_order_value.value}k`,
      boDirection:  kpis.bad_order_value.direction,
      boArrow:      boValueArrow,
      boDeltaLine:  boValueArrow
        ? `₱${Math.abs(boValueDelta).toFixed(1)}k ${boValueArrow === 'up' ? 'more' : 'less'} than last period`
        : 'Unchanged from last period',
      boContext: `${kpis.bad_order_value.incident_count} incidents · ₱${br.expiry}k expiry · ₱${br.transport_damage}k transport`,

      // KPI 2
      activeIncidents:    `${kpis.bad_order_incidents.value}`,
      incDirection:       kpis.bad_order_incidents.direction,
      incArrow,
      incContext: `${kpis.bad_order_incidents.open_count} open · ${kpis.bad_order_incidents.under_investigation} under investigation`,
      incDeltaLine: `${kpis.bad_order_incidents.total_count} total · ${kpis.bad_order_incidents.resolved_count} resolved this period`,

      // KPI 3: Items to Reorder
      // Source: LP_Recommendation count for current planning cycle.
      reorderItems:   `${kpis.reorder_items.value} ${unitNoun}`,
      reorderItemsContext: `${kpis.reorder_items.critical_count} critical · ₱${kpis.reorder_items.total_value}M total order`,

      // KPI 4: Total Reorder Value
      // Source: SUM of LP_Recommendation values for current planning cycle.
      reorderValue:   `₱${kpis.reorder_value.value}M`,
      reorderValueContext: `${kpis.reorder_value.item_count} ${unitNoun} need ordering · ${kpis.reorder_value.critical_count} critical`,

      // Alerts lists
      reorderAlerts: data.reorder_alerts.map((a) => ({
        title:    a.product_name,
        subtitle: `${a.sku_id} • Stock: ${a.current_stock} / ROP: ${a.rop}`,
        type:     a.urgency,
      })),
      badOrders: data.bad_orders.map((b) => ({
        title:    b.product_name,
        subtitle: `${b.incident_id} • ${b.reason}`,
        type:     b.status,
      })),
      badOrdersSummary: `${data.bad_orders.length} incidents · ${data.bad_orders.filter(b => b.status === 'OPEN').length} open`,
    };
  }, [data]);

  return (
    <div className="dashboard">
      <div className="dashboard-content">
        <div className="dashboard-header">
          <div className="dashboard-title-row">
            <h2>Inventory <span>pulse</span></h2>
            <DateFilter onRefresh={handleRefresh} />
          </div>
          <p>Real-time KPIs across SSM's Urdaneta warehouse. Last synced: {startMonth} {startYear} – {endMonth} {endYear}</p>
        </div>

        {error ? (
          <div className="dashboard-error-state">
            <p>{error}</p>
            <button className="dashboard-retry-btn" onClick={handleRetry}>Retry</button>
          </div>
        ) : (
          <>
            {/* ── KPI STRIP — 4 tiles, all backed by real data sources ──────── */}
            {/* KPI 1 & 2: Bad orders (SalesReturn_Fact / bo_monitoring_view)   */}
            {/* KPI 3 & 4: Reorder action items (LP_Recommendation)             */}
            <div className="dashboard-section">
              <div className="kpi-grid">
                {loading || !view ? (
                  <>
                    <KPISkeleton />
                    <KPISkeleton />
                    <KPISkeleton />
                    <KPISkeleton />
                  </>
                ) : (
                  <>
                    <KPICard
                      title="Bad order value"
                      value={view.boValue}
                      metricType="loss"
                      direction={view.boDirection}
                      trendDirection={view.boArrow}
                      deltaLine={view.boDeltaLine}
                      contextLine={view.boContext}
                      icon={<FlaskConical size={20} />}
                    />
                    <KPICard
                      title="Active incidents"
                      value={view.activeIncidents}
                      metricType="loss"
                      direction={view.incDirection}
                      trendDirection={view.incArrow}
                      contextLine={view.incContext}
                      deltaLine={view.incDeltaLine}
                      icon={<ShieldAlert size={20} />}
                    />
                    <KPICard
                      title={view.unitNoun === 'categories' ? 'Categories to reorder' : 'Products to reorder'}
                      value={view.reorderItems}
                      metricType="recommendation"
                      contextLine={view.reorderItemsContext}
                      icon={<ShoppingCart size={20} />}
                    />
                    <KPICard
                      title="Total reorder value"
                      value={view.reorderValue}
                      metricType="recommendation"
                      contextLine={view.reorderValueContext}
                      icon={<Wallet size={20} />}
                    />
                  </>
                )}
              </div>
            </div>

            {/* ── PRIMARY CHART — Bad Order Trend (full width) ─────────────── */}
            {/* Stacked bar by reason (Expiry / Transport Damage / Storage).    */}
            {/* Source: SalesReturn_Fact grouped by (week, return_type).         */}
            <div className="dashboard-section">
              <div className="chart-primary">
                {loading || !data ? (
                  <ChartSkeleton />
                ) : !data.bad_order_series || data.bad_order_series.length === 0 ? (
                  <div className="chart-widget"><EmptyNote>No data for this selection</EmptyNote></div>
                ) : (
                  <BadOrderTrendWidget badOrderSeries={data.bad_order_series} />
                )}
              </div>
            </div>

            {/* ── SECONDARY ROW — ABC | Reorder | Bad Orders ───────────────── */}
            <div className="dashboard-section">
              <div className="secondary-grid">

                {/* ABC Classification — from ABC_Classification analytics table */}
                <div className="secondary-col">
                  {loading || !data ? (
                    <ChartSkeleton />
                  ) : !data.abc || data.abc.tiers.length === 0 ? (
                    <div className="chart-widget"><EmptyNote>No data for this selection</EmptyNote></div>
                  ) : (
                    <ABCClassificationWidget abc={data.abc} />
                  )}
                </div>

                {/* Reorder: LP_Recommendation count + alert list */}
                <div className="secondary-col reorder-merged-card">
                  {loading || !view ? (
                    <>
                      <KPISkeleton />
                      <AlertsSkeleton />
                    </>
                  ) : (
                    <>
                      <KPICard
                        title={view.unitNoun === 'categories' ? 'Categories to reorder' : 'Products to reorder'}
                        value={view.reorderItems}
                        metricType="recommendation"
                        contextLine={view.reorderItemsContext}
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

                {/* Bad orders — recent incidents for quick triage */}
                <div className="secondary-col bad-orders-card">
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
