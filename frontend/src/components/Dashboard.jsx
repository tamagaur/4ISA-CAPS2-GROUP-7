import React, { useMemo } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import KPICard from './KPICard';
import { SalesVsStockWidget, ABCClassificationWidget } from './Charts';
import AlertsList from './AlertsList';
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
            <button className="refresh-btn" onClick={handleRefresh}>
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-refresh-cw"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
              Refresh
            </button>
          </div>
          
          <div className="dashboard-date-controls">
            <div className="date-select-btn" style={{ position: 'relative' }}>
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-calendar"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
              {startMonth}
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-chevron-down"><path d="m6 9 6 6 6-6"/></svg>
              <select 
                style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
                value={startMonth}
                onChange={(e) => updatePeriodImmediately(e.target.value, startYear, endMonth, endYear)}
              >
                {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            
            <div className="date-select-btn" style={{ position: 'relative' }}>
              {startYear}
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-chevron-down"><path d="m6 9 6 6 6-6"/></svg>
              <select 
                style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
                value={startYear}
                onChange={(e) => updatePeriodImmediately(startMonth, e.target.value, endMonth, endYear)}
              >
                {['2021', '2022', '2023', '2024', '2025', '2026'].map(y => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </div>

            <span style={{ color: '#a0aec0', fontSize: '0.85rem', margin: '0 4px' }}>to</span>

            <div className="date-select-btn" style={{ position: 'relative' }}>
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-calendar"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
              {endMonth}
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-chevron-down"><path d="m6 9 6 6 6-6"/></svg>
              <select 
                style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
                value={endMonth}
                onChange={(e) => updatePeriodImmediately(startMonth, startYear, e.target.value, endYear)}
              >
                {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            
            <div className="date-select-btn" style={{ position: 'relative' }}>
              {endYear}
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-chevron-down"><path d="m6 9 6 6 6-6"/></svg>
              <select 
                style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
                value={endYear}
                onChange={(e) => updatePeriodImmediately(startMonth, startYear, endMonth, e.target.value)}
              >
                {['2021', '2022', '2023', '2024', '2025', '2026'].map(y => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </div>
            
            <button className="date-today-btn" onClick={() => updatePeriodImmediately(realWorldPeriod?.month || 'Aug', realWorldPeriod?.year || '2026', realWorldPeriod?.month || 'Aug', realWorldPeriod?.year || '2026')}>
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-calendar"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>
              Today
            </button>
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
