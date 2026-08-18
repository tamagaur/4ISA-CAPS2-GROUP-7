import React, { useMemo } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import KPICard from './KPICard';
import { LineChartWidget, DonutChartWidget } from './Charts';
import AlertsList from './AlertsList';
import { mockSKUDatabase } from './SKUForecast';
import { getAverageMape, getConfidenceTier } from '../utils/forecastAccuracy';
import { COLORS } from '../theme/colors';
import './Dashboard.css';

const Dashboard = () => {
  const navigate = useNavigate();
  const { selectedMonth, selectedYear } = useOutletContext() || { selectedMonth: 'Apr', selectedYear: '2026' };

  const reorderAlerts = [
    { title: 'Surf Powder Detergent 1kg', subtitle: 'SKU-4721 • Stock: 45 / ROP: 120', type: 'CRITICAL' },
    { title: 'Pineapple Juice 1L', subtitle: 'SKU-8934 • Stock: 12 / ROP: 88', type: 'CRITICAL' },
    { title: 'Knorr Cubes 8g', subtitle: 'SKU-2891 • Stock: 78 / ROP: 150', type: 'URGENT' }
  ];

  const badOrders = [
    { title: 'Dove Shampoo 340ml', subtitle: 'INC-2024-135 • Transport Damage • Qty: 24', type: 'OPEN' },
    { title: 'Tomato Sauce 250g', subtitle: 'INC-2024-134 • Expiry • Qty: 18', type: 'RESOLVED' },
    { title: 'Sweet Corn 425g', subtitle: 'INC-2024-133 • Storage Issue • Qty: 32', type: 'UNDER INVESTIGATION' }
  ];

  const dynamicKPIs = useMemo(() => {
    const monthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(selectedMonth) || 0;
    const yearVal = parseInt(selectedYear) || 2026;
    const seed = (monthIndex + yearVal) % 6;
    const diff = seed - 1; // 0 offset for Apr 2026

    const trappedCapital = (52.4 + diff * 1.2).toFixed(1);
    const spoilageCost = (186.5 + diff * 8.5).toFixed(1);
    const stockoutRate = (3.1 + diff * 0.2).toFixed(1);

    return {
      trappedCapital: `P${trappedCapital}M`,
      spoilageCost: `P${spoilageCost}k`,
      stockoutRate: `${stockoutRate}%`,
      incidents: 135 + diff * 6
    };
  }, [selectedMonth, selectedYear]);

  // Story #49/#52: roll up per-SKU forecast accuracy so a decision-maker
  // doesn't have to open every SKU individually to gauge overall trust.
  const avgMape = useMemo(
    () => getAverageMape(mockSKUDatabase.map(s => s.code)),
    []
  );
  const avgConfidence = getConfidenceTier(avgMape);
  const confidenceColor = avgConfidence.level === 'high'
    ? COLORS.success
    : avgConfidence.level === 'moderate'
      ? COLORS.warning
      : COLORS.critical;

  return (
    <div className="dashboard">
      <div className="dashboard-content">
        <div className="dashboard-header">
          <h2>Inventory <span>pulse</span></h2>
          <p>Real-time KPIs across SSM's Urdaneta warehouse. Last synced: {selectedMonth} 22, {selectedYear}</p>
        </div>

        {/* KPIs Section */}
        <div className="kpi-grid">
          <KPICard 
            title="TRAPPED CAPITAL" 
            value={dynamicKPIs.trappedCapital} 
            subtext="↑ 8.2% vs. baseline" 
            subtextColor={COLORS.critical} 
            borderColor={COLORS.critical}
          />
          <KPICard 
            title="ACTIVE SKUS" 
            value="1,247" 
            subtext="187 Category A" 
            subtextColor="#718096" 
            borderColor={COLORS.abcA}
          />
          <KPICard 
            title="SPOILAGE COST" 
            value={dynamicKPIs.spoilageCost} 
            subtext={`this month · ${dynamicKPIs.incidents} incidents`} 
            subtextColor={COLORS.critical} 
            borderColor={COLORS.warning}
          />
          <KPICard
            title="STOCKOUT RATE"
            value={dynamicKPIs.stockoutRate}
            subtext="↓ from 4.8% baseline"
            subtextColor={COLORS.success}
            borderColor={COLORS.success}
          />
          <KPICard
            title="FORECAST ACCURACY"
            value={`${avgMape.toFixed(1)}% MAPE`}
            subtext={`${avgConfidence.label} · avg across ${mockSKUDatabase.length} SKUs`}
            subtextColor={confidenceColor}
            borderColor={COLORS.forecast}
          />
        </div>

        {/* Charts Section */}
        <div className="charts-grid">
          <div className="chart-large">
            <LineChartWidget selectedMonth={selectedMonth} selectedYear={selectedYear} />
          </div>
          <div className="chart-small">
            <DonutChartWidget />
          </div>
        </div>

        {/* Alerts Section */}
        <div className="alerts-grid">
          <AlertsList 
            title="Reorder alerts" 
            alerts={reorderAlerts} 
            onViewAll={() => navigate('/reorder')}
          />
          <AlertsList 
            title="Recent bad orders" 
            alerts={badOrders} 
            onViewAll={() => navigate('/bad-orders')}
          />
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
