import React, { useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import KPICard from './KPICard';
import DateFilter from './DateFilter';
import { getRecommendations } from '../api/recommendations';
import { getDashboardData } from '../api/dashboard';
import { CoverTrendWidget } from './Charts';
import { Package, Wallet, ShieldAlert, ClipboardCheck, TrendingUp, PiggyBank, CheckCircle2, Leaf } from 'lucide-react';
import './Dashboard.css';
import './Charts.css';

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

const EmptyNote = ({ children }) => <p className="dashboard-empty-note">{children}</p>;

const formatPeso = (value) => `₱${Math.round(value).toLocaleString()}`;
const formatWeeks = (value) => value.toFixed(1);

// TEMP: real KPI cards hidden per request (they're mostly empty states
// right now — forecasting/optimisation aren't fully wired to live data
// yet) in favour of leading with the illustrative "Project impact" cards
// instead. The real cards' fetch/logic below is untouched — flip this
// back to true to restore them at the top; nothing else needs to change.
const SHOW_REAL_KPI_CARDS = false;
// Same reasoning, for the chart and the 3-card row below it.
const SHOW_REAL_CHART = false;
const SHOW_REAL_THREE_CARDS = false;

// Sample-only — same 12-period shape as the real cover_series, feeding
// the same CoverTrendWidget the real chart uses. Trending down toward
// the 3-week policy line to tell a coherent "the model finds the excess
// and it comes down" story, not just a flat illustration.
const DEMO_COVER_SERIES = [
  { period: '2025-09', weeks_of_cover: 7.1 },
  { period: '2025-10', weeks_of_cover: 6.8 },
  { period: '2025-11', weeks_of_cover: 6.4 },
  { period: '2025-12', weeks_of_cover: 6.6 },
  { period: '2026-01', weeks_of_cover: 6.0 },
  { period: '2026-02', weeks_of_cover: 5.7 },
  { period: '2026-03', weeks_of_cover: 5.3 },
  { period: '2026-04', weeks_of_cover: 5.5 },
  { period: '2026-05', weeks_of_cover: 4.9 },
  { period: '2026-06', weeks_of_cover: 4.6 },
  { period: '2026-07', weeks_of_cover: 4.2 },
  { period: '2026-08', weeks_of_cover: 3.8 },
];

const Dashboard = () => {
  const { principal } = useOutletContext() || { principal: 'all' };

  // ── 3-card row data (unchanged) — drives Accept less, Request more,
  // Projected savings. Left exactly as it was; the chart no longer uses
  // this fetch (moved to kpiData.cover_series below).
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryTick, setRetryTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getRecommendations({ principal, status: 'pending' })
      .then(() => {})
      .catch(() => {
        if (cancelled) return;
        setError("Couldn't load data");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [principal, retryTick]);

  const handleRetry   = () => setRetryTick((t) => t + 1);
  const handleRefresh = () => window.location.reload();

  // ── Top KPI strip data — independent fetch/loading/error from the
  // section above, so a failure or slow load in one never blocks the other.
  const [kpiData, setKpiData] = useState(null);
  const [kpiLoading, setKpiLoading] = useState(true);
  const [kpiError, setKpiError] = useState(null);
  const [kpiRetryTick, setKpiRetryTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setKpiLoading(true);
    setKpiError(null);

    getDashboardData({ principal })
      .then((result) => {
        if (cancelled) return;
        setKpiData(result);
      })
      .catch(() => {
        if (cancelled) return;
        setKpiError("Couldn't load data");
      })
      .finally(() => {
        if (!cancelled) setKpiLoading(false);
      });

    return () => { cancelled = true; };
  }, [principal, kpiRetryTick]);

  const handleKpiRetry = () => setKpiRetryTick((t) => t + 1);

  // Card 1 — Cash tied up in stock. Null exactly when inventory.value is
  // null (valuation hasn't been loaded) — never shows 0 as if it were empty.
  const stockValue = kpiData?.inventory?.value ?? null;
  const cashTiedUp = stockValue === null
    ? { value: '—', contextLine: 'Inventory valuation not yet loaded' }
    : { value: formatPeso(stockValue), contextLine: kpiData.period || undefined };

  // Card 2 — Stock above policy. Depends on inventory.weeks_of_cover, which
  // itself depends on the same valuation as Card 1 — same null reason chain.
  const weeksOfCover = kpiData?.inventory?.weeks_of_cover ?? null;
  const policyWeeks = kpiData?.inventory?.policy_weeks ?? 3;
  let stockAbovePolicy;
  if (weeksOfCover === null) {
    stockAbovePolicy = { value: '—', contextLine: 'Depends on inventory valuation' };
  } else {
    const weeksOver = weeksOfCover - policyWeeks;
    stockAbovePolicy = {
      value: weeksOver <= 0 ? 'Within policy' : `${formatWeeks(weeksOver)} weeks over`,
      contextLine: `${formatWeeks(weeksOfCover)} weeks held, policy is ${policyWeeks} weeks`,
    };
  }

  // Card 3 — Order value. Null exactly when recommendations.order_value is
  // null (LP optimisation hasn't produced a recommendation yet).
  const orderValue = kpiData?.recommendations?.order_value ?? null;
  const orderValueCard = orderValue === null
    ? { value: '—', contextLine: 'Optimisation model has not been run' }
    : { value: formatPeso(orderValue), contextLine: `${kpiData.recommendations.product_count} products recommended` };

  // Card 4 — Needs manual review. Null exactly when forecast.unreliable_count
  // is null (SARIMA forecasting hasn't been run yet).
  const unreliableCount = kpiData?.forecast?.unreliable_count ?? null;
  let needsManualReview;
  if (unreliableCount === null) {
    needsManualReview = { value: '—', contextLine: 'Forecasting model has not been run' };
  } else {
    const totalCount = kpiData.forecast.total_count;
    const reliableCount = totalCount - unreliableCount;
    needsManualReview = {
      value: `${unreliableCount}`,
      contextLine: `${reliableCount} of ${totalCount} forecasts reliable`,
    };
  }

  return (
    <div className="dashboard">
      <div className="dashboard-content">
        <div className="dashboard-header">
          <div className="dashboard-title-row">
            <h2>Inventory <span>pulse</span></h2>
            <DateFilter onRefresh={handleRefresh} />
          </div>
          <p>Inventory and ordering overview — SSM Urdaneta warehouse</p>
        </div>

        {/* Project impact — moved to the top, temporarily standing in for
            the real KPI cards below (see SHOW_REAL_KPI_CARDS). NOT live
            data. Every value here is a fixed, hardcoded illustration of
            what this dashboard is designed to deliver once forecasting
            (SARIMA) and optimisation (LP) are both running against real
            cost/valuation data — neither is fully wired yet. Kept in its
            own visibly-badged section so nobody mistakes these for
            production numbers. Maps directly to the capstone's five
            specific objectives: forecast model comparison (Obj. 2),
            multi-objective cost minimisation (Obj. 3), reorder-
            recommendation adoption vs. override (Obj. 4), and the SDG 12
            waste/stockout framing from the general objective. */}
        <div className="dashboard-section demo-section">
          <div className="demo-section-header">
            <div>
              <h3>Project impact</h3>
              <p>What this dashboard aims to deliver once it's fully connected to live data</p>
            </div>
            <span className="demo-badge">Sample figures — for illustration</span>
          </div>
          <div className="kpi-grid">
            <KPICard
              title="Forecast accuracy"
              value="87.3%"
              metricType="recommendation"
              contextLine="Compared against a simple average-based estimate"
              icon={<TrendingUp size={20} />}
            />
            <KPICard
              title="Total inventory cost saved"
              value="₱1.85M / qtr"
              metricType="recommendation"
              contextLine="Covers storage, ordering, and shortage costs"
              icon={<PiggyBank size={20} />}
            />
            <KPICard
              title="Recommendation adoption"
              value="76%"
              metricType="recommendation"
              contextLine="24% adjusted manually, with reason recorded"
              icon={<CheckCircle2 size={20} />}
            />
            <KPICard
              title="Waste & stockouts reduced"
              value="31%"
              metricType="recommendation"
              contextLine="Supports responsible consumption (UN SDG 12)"
              icon={<Leaf size={20} />}
            />
          </div>

          {/* Same CoverTrendWidget the real chart uses (see SHOW_REAL_CHART
              below) — only the input data differs, so the sample looks and
              behaves exactly like the real thing will once it has data. */}
          <div className="chart-primary demo-chart">
            <CoverTrendWidget coverSeries={DEMO_COVER_SERIES} policyTarget={3} />
          </div>

          <div className="secondary-grid demo-secondary-grid">
            <div className="secondary-col">
              <div className="chart-widget">
                <div className="chart-header">
                  <div className="chart-title-area">
                    <h4>Order less of these</h4>
                    <p>Stock already above what demand needs</p>
                  </div>
                </div>
                <div className="demo-list">
                  <div className="demo-list-row">
                    <span className="demo-list-name">Surf Powder Detergent 1kg</span>
                    <span className="demo-list-detail">38 cases above what's needed</span>
                  </div>
                  <div className="demo-list-row">
                    <span className="demo-list-name">Dove Shampoo 340ml</span>
                    <span className="demo-list-detail">22 cases above what's needed</span>
                  </div>
                </div>
                <p className="demo-list-footer">~₱410k in capital freed up</p>
              </div>
            </div>
            <div className="secondary-col">
              <div className="chart-widget">
                <div className="chart-header">
                  <div className="chart-title-area">
                    <h4>Order these now</h4>
                    <p>Stock below the reorder point</p>
                  </div>
                </div>
                <div className="demo-list">
                  <div className="demo-list-row">
                    <span className="demo-list-name">Knorr Cubes 8g</span>
                    <span className="demo-list-detail">15 cases below reorder point</span>
                  </div>
                  <div className="demo-list-row">
                    <span className="demo-list-name">Canned Juices (category)</span>
                    <span className="demo-list-detail">60 cases below reorder point</span>
                  </div>
                </div>
                <p className="demo-list-footer">2 products at risk of stocking out</p>
              </div>
            </div>
            <div className="secondary-col">
              <div className="chart-widget">
                <div className="chart-header">
                  <div className="chart-title-area">
                    <h4>Products to watch</h4>
                    <p>Forecast too irregular to rely on</p>
                  </div>
                </div>
                <div className="demo-list">
                  <div className="demo-list-row">
                    <span className="demo-list-name">Sauces &amp; Vegetables (category)</span>
                    <span className="demo-list-detail">34% forecast error</span>
                  </div>
                  <div className="demo-list-row">
                    <span className="demo-list-name">Fabric Conditioner 800ml</span>
                    <span className="demo-list-detail">28% forecast error</span>
                  </div>
                </div>
                <p className="demo-list-footer">Flagged for manual check</p>
              </div>
            </div>
          </div>
        </div>

        {/* KPI strip — independent data source (getDashboardData), own
            loading/error/retry, scoped to this grid only. Temporarily
            hidden (SHOW_REAL_KPI_CARDS) — see the note by that constant. */}
        {SHOW_REAL_KPI_CARDS && (
          <div className="dashboard-section">
            <div className="kpi-grid">
              {kpiLoading ? (
                <>
                  <KPISkeleton /><KPISkeleton /><KPISkeleton /><KPISkeleton />
                </>
              ) : kpiError ? (
                <div className="dashboard-error-state kpi-grid-error">
                  <p>{kpiError}</p>
                  <button className="dashboard-retry-btn" onClick={handleKpiRetry}>Retry</button>
                </div>
              ) : (
                <>
                  <KPICard
                    title="Cash tied up in stock"
                    value={cashTiedUp.value}
                    metricType="recommendation"
                    contextLine={cashTiedUp.contextLine}
                    icon={<Wallet size={20} />}
                  />
                  <KPICard
                    title="Stock above policy"
                    value={stockAbovePolicy.value}
                    metricType="recommendation"
                    contextLine={stockAbovePolicy.contextLine}
                    icon={<ShieldAlert size={20} />}
                  />
                  <KPICard
                    title="Order value"
                    value={orderValueCard.value}
                    metricType="recommendation"
                    contextLine={orderValueCard.contextLine}
                    icon={<Package size={20} />}
                  />
                  <KPICard
                    title="Needs manual review"
                    value={needsManualReview.value}
                    metricType="recommendation"
                    contextLine={needsManualReview.contextLine}
                    icon={<ClipboardCheck size={20} />}
                  />
                </>
              )}
            </div>
          </div>
        )}

        {/* Weeks-of-cover chart — same independent data source/loading/error
            as the KPI strip above (kpiData.cover_series), since both need
            the same inventory valuation the backend can't compute yet.
            Temporarily hidden (SHOW_REAL_CHART) — see the note by that
            constant. */}
        {SHOW_REAL_CHART && (
          <div className="dashboard-section">
            <div className="chart-primary">
              {kpiLoading ? (
                <ChartSkeleton />
              ) : kpiError ? (
                <div className="dashboard-error-state">
                  <p>{kpiError}</p>
                  <button className="dashboard-retry-btn" onClick={handleKpiRetry}>Retry</button>
                </div>
              ) : (
                <CoverTrendWidget coverSeries={kpiData?.cover_series ?? []} policyTarget={policyWeeks} />
              )}
            </div>
          </div>
        )}

        {error ? (
          <div className="dashboard-error-state">
            <p>{error}</p>
            <button className="dashboard-retry-btn" onClick={handleRetry}>Retry</button>
          </div>
        ) : (
          <>
            {/* Order less of these / Order these now / Products to watch —
                real, well-defined sources (lp_recommendation.q_i vs current
                stock; inventory vs lp_recommendation.rop_i;
                forecast_result.mape >= 20.0 — mape is stored as a percent,
                not a 0-1 fraction, see schema.sql's column comment). Still
                empty: lp_recommendation has 0 rows (blocks the first two —
                the optimisation model hasn't run), so the whole row stays
                in its empty state below even though forecast_result now
                has real rows (scripts/run_sarima.py has been run) — wiring
                "Products to watch" to it is a separate, not-yet-done task.
                chart-widget-empty is unconditional here (not data-driven,
                unlike the KPI/chart sections above) because none of these
                three has a live fetch behind it yet — once one is wired,
                its className needs to go back to plain "chart-widget" when
                that card actually has data. Temporarily hidden
                (SHOW_REAL_THREE_CARDS) — see the note by that constant. */}
            {SHOW_REAL_THREE_CARDS && (
            <div className="dashboard-section">
              <div className="secondary-grid">
                {loading ? (
                  <>
                    <div className="secondary-col"><ChartSkeleton /></div>
                    <div className="secondary-col"><ChartSkeleton /></div>
                    <div className="secondary-col"><ChartSkeleton /></div>
                  </>
                ) : (
                  <>
                    <div className="secondary-col">
                      <div className="chart-widget chart-widget-empty">
                        <div className="chart-header">
                          <div className="chart-title-area">
                            <h4>Order less of these</h4>
                            <p>Stock already above what demand needs</p>
                          </div>
                        </div>
                        <EmptyNote>Not available yet — the optimisation model has not been run</EmptyNote>
                      </div>
                    </div>
                    <div className="secondary-col">
                      <div className="chart-widget chart-widget-empty">
                        <div className="chart-header">
                          <div className="chart-title-area">
                            <h4>Order these now</h4>
                            <p>Stock below the reorder point</p>
                          </div>
                        </div>
                        <EmptyNote>Not available yet — the optimisation model has not been run</EmptyNote>
                      </div>
                    </div>
                    <div className="secondary-col">
                      <div className="chart-widget chart-widget-empty">
                        <div className="chart-header">
                          <div className="chart-title-area">
                            <h4>Products to watch</h4>
                            <p>Forecast too irregular to rely on</p>
                          </div>
                        </div>
                        <EmptyNote>Not available yet — the forecasting model has not been run</EmptyNote>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default Dashboard;
