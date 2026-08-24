import React, { useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import './DashboardLayout.css';

// "Today" is pinned to June 2026, not the machine's actual clock — the
// app's own notion of "now" needs to stay fixed regardless of when it's
// actually opened, so every filter/default/upper-bound built on it stays
// consistent instead of drifting forward with the real calendar.
const getCurrentRealWorldPeriod = () => ({ month: 'Jun', year: '2026' });

const DashboardLayout = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const realWorldPeriod = getCurrentRealWorldPeriod();

  // Persistent Applied State (defaulting to real-world current month/year)
  const [startMonth, setStartMonth] = useState(realWorldPeriod.month);
  const [startYear, setStartYear] = useState(realWorldPeriod.year);
  const [endMonth, setEndMonth] = useState(realWorldPeriod.month);
  const [endYear, setEndYear] = useState(realWorldPeriod.year);

  // Principal filter — 'all' | 'unilever' | 'delmonte'. Deliberately not
  // persisted (no localStorage), unlike the period above: it applies
  // instantly, no pending/confirm step needed.
  const [principal, setPrincipal] = useState('all');

  // Pending Unsaved Selection State
  const [pendingStartMonth, setPendingStartMonth] = useState(startMonth);
  const [pendingStartYear, setPendingStartYear] = useState(startYear);
  const [pendingEndMonth, setPendingEndMonth] = useState(endMonth);
  const [pendingEndYear, setPendingEndYear] = useState(endYear);

  // Navigation Interception State
  const [navTarget, setNavTarget] = useState(null);
  const [showNavConfirm, setShowNavConfirm] = useState(false);

  const navigate = useNavigate();

  // Evaluates to true only when pending selection differs from applied period
  const isPending = 
    pendingStartMonth !== startMonth || 
    pendingStartYear !== startYear ||
    pendingEndMonth !== endMonth ||
    pendingEndYear !== endYear;

  const toggleSidebar = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };

  const handleApplyPeriod = () => {
    setStartMonth(pendingStartMonth);
    setStartYear(pendingStartYear);
    setEndMonth(pendingEndMonth);
    setEndYear(pendingEndYear);
    localStorage.setItem('san2_start_month', pendingStartMonth);
    localStorage.setItem('san2_start_year', pendingStartYear);
    localStorage.setItem('san2_end_month', pendingEndMonth);
    localStorage.setItem('san2_end_year', pendingEndYear);
  };

  const handleDiscardPeriod = () => {
    setPendingStartMonth(startMonth);
    setPendingStartYear(startYear);
    setPendingEndMonth(endMonth);
    setPendingEndYear(endYear);
  };

  const handleResetToToday = () => {
    const todayPeriod = getCurrentRealWorldPeriod();
    setPendingStartMonth(todayPeriod.month);
    setPendingStartYear(todayPeriod.year);
    setPendingEndMonth(todayPeriod.month);
    setPendingEndYear(todayPeriod.year);
  };

  // Intercept Sidebar module clicks if period is pending
  const handleNavAttempt = (targetPath) => {
    if (isPending) {
      setNavTarget(targetPath);
      setShowNavConfirm(true);
      return false; // Block immediate navigation
    }
    return true; // Allow immediate navigation
  };

  const handleConfirmSaveNav = () => {
    handleApplyPeriod();
    setShowNavConfirm(false);
    if (navTarget) {
      navigate(navTarget);
      setNavTarget(null);
    }
  };

  const handleConfirmDiscardNav = () => {
    handleDiscardPeriod();
    setShowNavConfirm(false);
    if (navTarget) {
      navigate(navTarget);
      setNavTarget(null);
    }
  };

  const updatePeriodImmediately = (sm, sy, em, ey) => {
    setStartMonth(sm);
    setStartYear(sy);
    setEndMonth(em);
    setEndYear(ey);
    setPendingStartMonth(sm);
    setPendingStartYear(sy);
    setPendingEndMonth(em);
    setPendingEndYear(ey);
    localStorage.setItem('san2_start_month', sm);
    localStorage.setItem('san2_start_year', sy);
    localStorage.setItem('san2_end_month', em);
    localStorage.setItem('san2_end_year', ey);
  };

  return (
    <div className={`dashboard-layout ${isSidebarOpen ? '' : 'sidebar-closed'}`}>
      <Sidebar 
        isOpen={isSidebarOpen} 
        onNavAttempt={handleNavAttempt}
        currentMonth={realWorldPeriod.month}
      />
      <div className="main-content">
        <Topbar
          toggleSidebar={toggleSidebar}
          startMonth={startMonth}
          startYear={startYear}
          endMonth={endMonth}
          endYear={endYear}
          pendingStartMonth={pendingStartMonth}
          setPendingStartMonth={setPendingStartMonth}
          pendingStartYear={pendingStartYear}
          setPendingStartYear={setPendingStartYear}
          pendingEndMonth={pendingEndMonth}
          setPendingEndMonth={setPendingEndMonth}
          pendingEndYear={pendingEndYear}
          setPendingEndYear={setPendingEndYear}
          isPending={isPending}
          handleApplyPeriod={handleApplyPeriod}
          handleResetToToday={handleResetToToday}
          realWorldMonth={realWorldPeriod.month}
          realWorldYear={realWorldPeriod.year}
          principal={principal}
          setPrincipal={setPrincipal}
        />
        <Outlet context={{ startMonth, startYear, endMonth, endYear, updatePeriodImmediately, realWorldPeriod, principal }} />
      </div>

      {/* Nav Interception Confirmation Dialog */}
      {showNavConfirm && (
        <div className="period-nav-overlay" onClick={() => setShowNavConfirm(false)}>
          <div className="period-nav-card" onClick={(e) => e.stopPropagation()}>
            <div className="period-nav-header">
              <h4 className="period-nav-title">Unsaved Period Change</h4>
            </div>
            <div className="period-nav-body">
              <p>
                You changed the selected period to <strong>{pendingStartMonth} {pendingStartYear} - {pendingEndMonth} {pendingEndYear}</strong> but haven't applied it. 
                Save this change, or discard it and keep viewing <strong>{startMonth} {startYear} - {endMonth} {endYear}</strong>?
              </p>
            </div>
            <div className="period-nav-footer">
              <button className="period-discard-btn" onClick={handleConfirmDiscardNav}>
                Discard
              </button>
              <button className="period-save-btn" onClick={handleConfirmSaveNav}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DashboardLayout;
