import React, { useMemo } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import KPICard from './KPICard';
import { AllocationVarianceWidget } from './Charts';
import DateFilter from './DateFilter';
import { getMockDashboard } from '../data/mockData';
import { Package, Wallet, ShieldAlert, Activity } from 'lucide-react';
import './Dashboard.css';

// "Accept less" — the largest excesses. Uses the same amber the
// chart's excess bars use. accept/offered/frees all come straight from
// mockData's takeLessRecsFrom(), where accept is already capped at the
// offer (Fix 1) — this panel can never show an impossible quantity.
const TakeLessPanel = ({ recs, totalFreedLabel, onViewAll }) => (
  <div className="chart-widget action-panel action-panel-excess">
    <div className="chart-header">
      <div className="chart-title-area">
        <h4>Accept less</h4>
        <p>Products where the offer exceeds demand</p>
      </div>
      <button className="view-all-btn" onClick={onViewAll}>View all &rarr;</button>
    </div>
    <div className="action-list">
      {recs.map((r) => (
        <div className="action-row" key={r.sku}>
          <span className="action-instruction">{r.sku} — accept {r.accept} of {r.offered}</span>
          <span className="action-secondary">saves {formatPesosK(r.freesPesos)}</span>
        </div>
      ))}
    </div>
    <p className="action-footer action-footer-excess">Total freed: {totalFreedLabel}</p>
  </div>
);

// "Request more" — the largest shortfalls. Uses the same red the
// chart's shortfall bars use. SSM already accepts the full offer here
// (there's nothing more to accept) — the gap is a request back to the
// principal, reported in cases via mockData's shortfallCases.
const AskMorePanel = ({ recs, stockoutCount, onViewAll }) => (
  <div className="chart-widget action-panel action-panel-shortfall">
    <div className="chart-header">
      <div className="chart-title-area">
        <h4>Request more</h4>
        <p>Products where the offer falls short</p>
      </div>
      <button className="view-all-btn" onClick={onViewAll}>View all &rarr;</button>
    </div>
    <div className="action-list">
      {recs.map((r) => (
        <div className="action-row" key={r.sku}>
          <span className="action-instruction">{r.sku} — {r.shortCases} cases short</span>
          <span className="action-secondary">{formatPesosK(r.impactPesos)} impact</span>
        </div>
      ))}
    </div>
    <p className="action-footer action-footer-shortfall">
      {stockoutCount} SKU{stockoutCount === 1 ? '' : 's'} will stock out even at full allocation
    </p>
  </div>
);

// "Projected savings" — each row appends the saving amount
// and a direction arrow (always a reduction, so always the success colour)
// so the improvement doesn't have to be inferred from two bare numbers.
const BenchmarkPanel = ({ benchmark }) => {
  const holdingDeltaK = Math.round((benchmark.holdingCost.currentM - benchmark.holdingCost.modelM) * 1000);
  const spoilageDeltaK = Math.round(benchmark.spoilage.currentK - benchmark.spoilage.modelK);
  const stockoutDelta = benchmark.stockoutDays.current - benchmark.stockoutDays.model;

  return (
    <div className="chart-widget">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Projected savings</h4>
          <p>Based on the last six ordering cycles</p>
        </div>
      </div>
      <div className="benchmark-list">
        <div className="benchmark-row">
          <span className="benchmark-label">Holding cost</span>
          <span className="benchmark-values">
            ₱{benchmark.holdingCost.currentM}M → ₱{benchmark.holdingCost.modelM}M
            <span className="benchmark-delta"> ↓ ₱{holdingDeltaK}k</span>
          </span>
        </div>
        <div className="benchmark-row">
          <span className="benchmark-label">Spoilage</span>
          <span className="benchmark-values">
            ₱{benchmark.spoilage.currentK}k → ₱{benchmark.spoilage.modelK}k
            <span className="benchmark-delta"> ↓ ₱{spoilageDeltaK}k</span>
          </span>
        </div>
        <div className="benchmark-row">
          <span className="benchmark-label">Stockout days</span>
          <span className="benchmark-values">
            {benchmark.stockoutDays.current} → {benchmark.stockoutDays.model}
            <span className="benchmark-delta"> ↓ {stockoutDelta}</span>
          </span>
        </div>
      </div>
    </div>
  );
};

// ₱287k / ₱1.8M — used only by the two action panels' peso amounts.
function formatPesosK(value) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `₱${(abs / 1_000_000).toFixed(1)}M`;
  return `₱${Math.round(abs / 1000)}k`;
}

const Dashboard = () => {
  const navigate = useNavigate();
  const { principal } = useOutletContext() || { principal: 'all' };

  // Mock data is synchronous and local (see src/data/mockData.js's own
  // PLACEHOLDER comments for which fields are awaiting real sources), so
  // there's no fetch/loading/error state to manage here — swapping in a
  // real API later means this becomes an async call, not a rewrite of the
  // JSX below.
  const data = useMemo(() => getMockDashboard(principal), [principal]);
  const { kpis, allocationVariance, funnel, takeLessRecs, askMoreRecs, benchmark } = data;

  const handleRefresh = () => window.location.reload();

  const forecastTooltip =
    `Forecast accuracy measured by MAPE. ${kpis.forecastHealth.passed} SKUs scored below 20% error; ` +
    `${kpis.forecastHealth.fallback} use a fallback model.`;

  return (
    <div className="dashboard">
      <div className="dashboard-content">
        <div className="dashboard-header">
          <div className="dashboard-title-row">
            <h2>Inventory <span>pulse</span></h2>
            <DateFilter onRefresh={handleRefresh} />
          </div>
        </div>

        {/* ── KPI row — the accept/reject question in four numbers ───────── */}
        <div className="dashboard-section">
          <div className="kpi-grid">
            <KPICard
              title="Allocation offered"
              value={`₱${kpis.allocationOffered.valueM}M`}
              contextLine={`${kpis.allocationOffered.cases.toLocaleString()} cases · ${kpis.allocationOffered.classACount} class A`}
              icon={<Package size={20} />}
            />
            <KPICard
              title="Cash freed"
              value={`₱${kpis.cashFreed.valueM}M`}
              direction="better"
              contextLine={`Accept ₱${kpis.cashFreed.offeredM}M of ₱${kpis.allocationOffered.valueM}M offered · ${kpis.cashFreed.pctLess}% less capital tied up`}
              icon={<Wallet size={20} />}
            />
            <KPICard
              title="Stockout risk"
              value={`${kpis.stockoutRisk.count} SKUs`}
              metricType="danger"
              contextLine="Short even at full allocation"
              icon={<ShieldAlert size={20} />}
            />
            <KPICard
              title="Forecast health"
              value={`${kpis.forecastHealth.passed} / ${kpis.forecastHealth.total}`}
              contextLine={`${kpis.forecastHealth.passed} of ${kpis.forecastHealth.total} forecasts reliable`}
              icon={<Activity size={20} />}
              tooltip={forecastTooltip}
            />
          </div>
        </div>

        {/* ── Hero chart — allocation vs forecast, diverging bar ──────────── */}
        <div className="dashboard-section">
          <div className="chart-primary">
            <AllocationVarianceWidget
              rows={allocationVariance}
              classACount={funnel.classA}
            />
          </div>
        </div>

        {/* ── Bottom row — take less | ask for more | model benchmark ────── */}
        <div className="dashboard-section">
          <div className="secondary-grid">
            <div className="secondary-col">
              <TakeLessPanel
                recs={takeLessRecs}
                totalFreedLabel={`₱${kpis.cashFreed.valueM}M`}
                onViewAll={() => navigate('/reorder')}
              />
            </div>
            <div className="secondary-col">
              <AskMorePanel
                recs={askMoreRecs}
                stockoutCount={kpis.stockoutRisk.count}
                onViewAll={() => navigate('/reorder')}
              />
            </div>
            <div className="secondary-col">
              <BenchmarkPanel benchmark={benchmark} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
