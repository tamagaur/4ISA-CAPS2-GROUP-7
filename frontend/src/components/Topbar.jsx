import React from 'react';
import { useLocation } from 'react-router-dom';
import { Check, Calendar } from 'lucide-react';
import { getCurrentUser } from '../auth';
import './Topbar.css';

const Topbar = ({ 
  toggleSidebar, 
  startMonth, 
  startYear, 
  endMonth,
  endYear,
  pendingStartMonth,
  setPendingStartMonth,
  pendingStartYear,
  setPendingStartYear,
  pendingEndMonth,
  setPendingEndMonth,
  pendingEndYear,
  setPendingEndYear,
  isPending,
  handleApplyPeriod,
  handleResetToToday,
  realWorldMonth = 'Aug',
  realWorldYear = '2026'
}) => {
  const location = useLocation();
  const isToday = 
    pendingStartMonth === realWorldMonth && 
    pendingStartYear === realWorldYear && 
    pendingEndMonth === realWorldMonth && 
    pendingEndYear === realWorldYear;
  const isForecastPage = location.pathname === '/forecast';

  const user = getCurrentUser();
  const getInitials = (u) => {
    if (!u) return 'JD'; // Fallback
    if (u.fullName) {
      const parts = u.fullName.split(' ').filter(Boolean);
      if (parts.length === 0) return '??';
      if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    if (u.email) {
      return u.email.substring(0, 2).toUpperCase();
    }
    return '??';
  };
  const initials = getInitials(user);

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
        
        {!isForecastPage && location.pathname !== '/' && (
          <div className="period-selector-wrapper">
            <select 
              className={`dropdown-select ${isPending ? 'dropdown-pending' : ''}`} 
              value={pendingStartMonth} 
              onChange={(e) => setPendingStartMonth(e.target.value)}
            >
              {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            
            <select 
              className={`dropdown-select ${isPending ? 'dropdown-pending' : ''}`} 
              value={pendingStartYear} 
              onChange={(e) => setPendingStartYear(e.target.value)}
            >
              {['2021', '2022', '2023', '2024', '2025', '2026'].map(y => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>

            <span style={{ color: '#a0aec0', fontSize: '0.85rem' }}>to</span>

            <select 
              className={`dropdown-select ${isPending ? 'dropdown-pending' : ''}`} 
              value={pendingEndMonth} 
              onChange={(e) => setPendingEndMonth(e.target.value)}
            >
              {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            
            <select 
              className={`dropdown-select ${isPending ? 'dropdown-pending' : ''}`} 
              value={pendingEndYear} 
              onChange={(e) => setPendingEndYear(e.target.value)}
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
        <div className="avatar blue-avatar" title={user?.fullName || user?.email || 'User'}>{initials}</div>
      </div>
    </header>
  );
};

export default Topbar;
