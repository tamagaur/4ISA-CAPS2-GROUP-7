import React, { useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import KPICard from './KPICard';
import DateFilter from './DateFilter';
import { getRecommendations } from '../api/recommendations';
import { Package, Wallet, ShieldAlert, ClipboardCheck } from 'lucide-react';
import './Dashboard.css';
import './Charts.css';

const NO_DATA_YET = 'No recommendations yet';

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

const Dashboard = () => {
  const {
    startMonth, startYear, endMonth, endYear, principal,
  } = useOutletContext() || {
    startMonth: 'Apr', startYear: '2026', endMonth: 'Apr', endYear: '2026',
    principal: 'all',
  };

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryTick, setRetryTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getRecommendations({ principal, status: 'pending' })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items || []);
      })
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

  const hasItems = items.length > 0;

  // Real, computable straight off RecommendationItem (q_i, urgency) — no
  // price field exists anywhere in this response (backend/schemas/
  // recommendations.py says so explicitly), so this is cases, not pesos.
  const offeredCases = useMemo(
    () => items.reduce((sum, item) => sum + (item.q_i || 0), 0),
    [items]
  );
  // "Still short" = current_stock below the reorder point — same signal
  // the backend already derived into urgency (CRITICAL/URGENT vs PLANNED).
  const shortCount = useMemo(
    () => items.filter((item) => item.urgency !== 'PLANNED').length,
    [items]
  );

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
            {/* KPI strip. Offered-by-suppliers and Still-short are wired to
                real fields on RecommendationItem. Capital-saved and
                Needs-manual-review have no source anywhere in the API yet
                (no price field, no bulk forecast-reliability endpoint) so
                they always render the empty state, independent of row
                count. */}
            <div className="dashboard-section">
              <div className="kpi-grid">
                {loading ? (
                  <>
                    <KPISkeleton /><KPISkeleton /><KPISkeleton /><KPISkeleton />
                  </>
                ) : (
                  <>
                    <KPICard
                      title="Offered by suppliers"
                      value={hasItems ? `${Math.round(offeredCases).toLocaleString()} cases` : '—'}
                      metricType="recommendation"
                      contextLine={hasItems ? `${items.length} products` : NO_DATA_YET}
                      icon={<Package size={20} />}
                    />
                    <KPICard
                      title="Capital saved"
                      value="—"
                      metricType="recommendation"
                      contextLine={NO_DATA_YET}
                      icon={<Wallet size={20} />}
                    />
                    <KPICard
                      title="Still short"
                      value={hasItems ? `${shortCount} products` : '—'}
                      metricType="recommendation"
                      contextLine={hasItems ? `of ${items.length} total` : NO_DATA_YET}
                      icon={<ShieldAlert size={20} />}
                    />
                    <KPICard
                      title="Needs manual review"
                      value="—"
                      metricType="recommendation"
                      contextLine={NO_DATA_YET}
                      icon={<ClipboardCheck size={20} />}
                    />
                  </>
                )}
              </div>
            </div>

            {/* Supply versus demand — no peso-impact-per-product field
                exists in the API, so this stays an empty state regardless
                of row count. */}
            <div className="dashboard-section">
              <div className="chart-primary">
                {loading ? (
                  <ChartSkeleton />
                ) : (
                  <div className="chart-widget">
                    <div className="chart-header">
                      <div className="chart-title-area">
                        <h4>Supply versus demand</h4>
                        <p>Comparing what suppliers offered against what demand requires</p>
                      </div>
                    </div>
                    <EmptyNote>Order recommendations have not been generated yet</EmptyNote>
                    <p className="dashboard-chart-footnote">{items.length} products in total</p>
                  </div>
                )}
              </div>
            </div>

            {/* Accept less / Request more / Projected savings — same gap:
                no offer-vs-accept split and no cost fields exist yet. */}
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
                      <div className="chart-widget">
                        <div className="chart-header">
                          <div className="chart-title-area">
                            <h4>Accept less</h4>
                            <p>Products where the offer exceeds demand</p>
                          </div>
                        </div>
                        <EmptyNote>Waiting for the forecasting and optimisation run</EmptyNote>
                      </div>
                    </div>
                    <div className="secondary-col">
                      <div className="chart-widget">
                        <div className="chart-header">
                          <div className="chart-title-area">
                            <h4>Request more</h4>
                            <p>Products where the offer falls short</p>
                          </div>
                        </div>
                        <EmptyNote>Waiting for the forecasting and optimisation run</EmptyNote>
                      </div>
                    </div>
                    <div className="secondary-col">
                      <div className="chart-widget">
                        <div className="chart-header">
                          <div className="chart-title-area">
                            <h4>Projected savings</h4>
                          </div>
                        </div>
                        <EmptyNote>Waiting for the forecasting and optimisation run</EmptyNote>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default Dashboard;
