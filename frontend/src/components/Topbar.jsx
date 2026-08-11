import React from 'react';
import { useLocation } from 'react-router-dom';
import { Check, Calendar } from 'lucide-react';
import './Topbar.css';

const Topbar = ({ 
  toggleSidebar, 
  selectedMonth, 
  selectedYear, 
  pendingMonth,
  setPendingMonth,
  pendingYear,
  setPendingYear,
  isPending,
  handleApplyPeriod,
  handleResetToToday,
  realWorldMonth = 'Aug',
  realWorldYear = '2026'
}) => {
  const location = useLocation();

  const getPathBadge = () => {
    const path = location.pathname;
    if (path === '/sku-management') return '01';
    if (path === '/abc') return '02';
    if (path === '/forecast') return '03';
    if (path === '/reorder') return '04';
    if (path === '/warehouse') return '05';
    if (path === '/bad-orders') return '06';
    if (path === '/upload') return '07';
    return '00';
  };

  const isToday = pendingMonth === realWorldMonth && pendingYear === realWorldYear;
  const isForecastPage = location.pathname === '/forecast';

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className="sidebar-toggle-btn" onClick={toggleSidebar} aria-label="Toggle Sidebar">
          <svg className="menu-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="12" x2="21" y2="12"></line>
            <line x1="3" y1="6" x2="21" y2="6"></line>
            <line x1="3" y1="18" x2="21" y2="18"></line>
          </svg>
        </button>
        <span className="breadcrumb-path">§ {getPathBadge()} / 07</span>
        
        {!isForecastPage && (
          <div className="period-selector-wrapper">
            <select 
              className={`dropdown-select ${isPending ? 'dropdown-pending' : ''}`} 
              value={pendingMonth} 
              onChange={(e) => setPendingMonth(e.target.value)}
            >
              {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            
            <select 
              className={`dropdown-select ${isPending ? 'dropdown-pending' : ''}`} 
              value={pendingYear} 
              onChange={(e) => setPendingYear(e.target.value)}
            >
              {['2021', '2022', '2023', '2024', '2025', '2026'].map(y => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>

            <button 
              className={`period-today-btn ${isToday ? 'is-today' : ''}`}
              onClick={handleResetToToday}
              title={`Reset to current month & year (${realWorldMonth} ${realWorldYear})`}
            >
              <Calendar size={13} />
              <span>Today</span>
            </button>

            {isPending && (
              <div className="period-apply-group">
                <span className="pending-indicator-dot" title="Unapplied period selection"></span>
                <button 
                  className="period-apply-btn" 
                  onClick={handleApplyPeriod}
                  title="Apply selected month & year"
                >
                  <Check size={14} />
                  <span>Apply</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>
      
      <div className="topbar-right">
        <div className="avatar blue-avatar">JD</div>
      </div>
    </header>
  );
};

export default Topbar;
