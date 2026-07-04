import React from 'react';
import KPICard from './KPICard';
import { LineChartWidget, DonutChartWidget } from './Charts';
import AlertsList from './AlertsList';
import './Dashboard.css';

const Dashboard = () => {
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

  return (
    <div className="dashboard">
      <div className="dashboard-content">
        <div className="dashboard-header">
          <h2>Inventory <span>pulse</span></h2>
          <p>Real-time KPIs across SSM's Urdaneta warehouse. Last synced: Apr 22, 2026</p>
        </div>

        {/* KPIs Section */}
        <div className="kpi-grid">
          <KPICard 
            title="TRAPPED CAPITAL" 
            value="P52.4M" 
            subtext="+ 8.2% vs. baseline" 
            subtextColor="#a0aec0" 
            borderColor="#e53e3e"
          />
          <KPICard 
            title="ACTIVE SKUS" 
            value="1,247" 
            subtext="187 Category A" 
            subtextColor="#a0aec0" 
            borderColor="#3182ce"
          />
          <KPICard 
            title="SPOILAGE COST" 
            value="P186.5k" 
            subtext="this month · 135 incidents" 
            subtextColor="#a0aec0" 
            borderColor="#d69e2e"
          />
          <KPICard 
            title="STOCKOUT RATE" 
            value="3.1%" 
            subtext="↓ from 4.8% baseline" 
            subtextColor="#a0aec0" 
            borderColor="#38a169"
          />
        </div>

        {/* Charts Section */}
        <div className="charts-grid">
          <div className="chart-large">
            <LineChartWidget />
          </div>
          <div className="chart-small">
            <DonutChartWidget />
          </div>
        </div>

        {/* Alerts Section */}
        <div className="alerts-grid">
          <AlertsList title="Reorder alerts" alerts={reorderAlerts} />
          <AlertsList title="Recent bad orders" alerts={badOrders} />
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
