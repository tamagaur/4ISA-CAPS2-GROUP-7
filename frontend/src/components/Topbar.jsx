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
        
        {/* Date Filter removed and placed in page headers */}
      </div>
      
      <div className="topbar-right">
        <div className="avatar blue-avatar" title={user?.fullName || user?.email || 'User'}>{initials}</div>
      </div>
    </header>
  );
};

export default Topbar;
