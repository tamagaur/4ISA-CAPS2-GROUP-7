import React, { useMemo } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import KPICard from './KPICard';
import { SalesVsStockWidget, ABCClassificationWidget } from './Charts';
import AlertsList from './AlertsList';
import DateFilter from './DateFilter';
import { COLORS } from '../theme/colors';
import { Wallet, FlaskConical, ShieldAlert, Timer, ShoppingCart } from 'lucide-react';
import './Dashboard.css';

const Dashboard = () => {
  const navigate = useNavigate();
  const { startMonth, startYear, endMonth, endYear, updatePeriodImmediately, realWorldPeriod } = useOutletContext() || { 
    startMonth: 'Apr', startYear: '2026', endMonth: 'Apr', endYear: '2026',
    updatePeriodImmediately: () => {}, 
    realWorldPeriod: { month: 'Aug', year: '2026' } 
  };

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
    const startMonthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(startMonth) || 0;
    const endMonthIndex = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(endMonth) || 0;
    const yearVal = parseInt(startYear) || 2026;
    const seed = (startMonthIndex + endMonthIndex + yearVal) % 6;
    const diff = seed - 1; 

    const trappedCapital = (57.2 + diff * 1.2).toFixed(1);
    const spoilageCost = (220.5 + diff * 8.5).toFixed(1);
    const stockoutRate = (3.9 + diff * 0.2).toFixed(1);
    const dsi = (34.7 + diff * 0.8).toFixed(1);
    const orderValue = (2.84 + diff * 0.1).toFixed(2);

    return {
      trappedCapital: `P${trappedCapital}M`,
      spoilageCost: `P${spoilageCost}k`,
      stockoutRate: `${stockoutRate}%`,
      dsi: `${dsi} days`,
      orderValue: `P${orderValue}M`,
      incidents: 159 + diff * 6
    };
  }, [startMonth, startYear, endMonth, endYear]);

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

        {/* KPIs Section */}
        <div className="kpi-grid">
          <KPICard 
            title="TRAPPED CAPITAL" 
            value={dynamicKPIs.trappedCapital} 
            subtext="+8.2% vs baseline" 
            subtextColor="#E5484D" 
            borderColor="#E5484D"
            icon={<Wallet size={20} />}
          />
          <KPICard 
            title="SPOILAGE COST" 
            value={dynamicKPIs.spoilageCost} 
            subtext={`This month · ${dynamicKPIs.incidents} incidents`} 
            subtextColor="#F5A623" 
            borderColor="#F5A623"
            icon={<FlaskConical size={20} />}
          />
          <KPICard
            title="CLASS A STOCKOUT RATE"
            value={dynamicKPIs.stockoutRate}
            subtext="↑ from 4.8% baseline"
            subtextColor="#3b82f6"
            borderColor="#3b82f6"
            icon={<ShieldAlert size={20} />}
          />
          <KPICard
            title="DAYS SALES OF INVENTORY"
            value={dynamicKPIs.dsi}
            subtext="SOH ÷ Avg daily sales"
            subtextColor="#a855f7"
            borderColor="#a855f7"
            icon={<Timer size={20} />}
          />
          <KPICard
            title="RECOMMENDED ORDER VALUE"
            value={dynamicKPIs.orderValue}
            subtext="Based on LP"
            subtextColor="#22c55e"
            borderColor="#22c55e"
            icon={<ShoppingCart size={20} />}
          />
        </div>

        {/* Charts Section */}
        <div className="charts-grid">
          <div className="chart-large">
            <SalesVsStockWidget startMonth={startMonth} startYear={startYear} endMonth={endMonth} endYear={endYear} />
          </div>
          <div className="chart-small">
            <ABCClassificationWidget />
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
