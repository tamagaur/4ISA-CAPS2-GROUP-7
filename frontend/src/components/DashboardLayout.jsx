import React, { useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import './DashboardLayout.css';

// "Today" is pinned to March 2026, not the machine's actual clock — the
// app's own notion of "now" needs to stay fixed regardless of when it's
// actually opened, so every filter/default/upper-bound built on it stays
// consistent instead of drifting forward with the real calendar. March
// 2026 is also the system-wide upper bound on selectable dates (see
// DateFilter.jsx's YEARS/month-options — Unilever's real data run ends
// there), so "today" and "the latest pickable date" are the same value
// by construction, not two numbers that have to be kept in sync by hand.
const getCurrentRealWorldPeriod = () => ({ month: 'Mar', year: '2026' });

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// Subtracts `count` months from (month, year), rolling the year backward
// across a January boundary rather than clamping — e.g. 2 months before
// Jan 2026 is Nov 2025.
const subtractMonths = (month, year, count) => {
  const total = MONTHS.indexOf(month) - count;
  const yearOffset = Math.floor(total / 12);
  const monthIndex = ((total % 12) + 12) % 12;
  return { month: MONTHS[monthIndex], year: String(Number(year) + yearOffset) };
};

// Default period: at least 2 months back from "today" through "today" —
// a 3-month window instead of the single current month, so the app opens
// on a range with enough history to look like a trend, not one bar.
// Both the initial state below and the "Today" reset button build off
// this same function, so they can never drift apart.
const getDefaultDateRange = () => {
  const today = getCurrentRealWorldPeriod();
  const start = subtractMonths(today.month, today.year, 2);
  return { startMonth: start.month, startYear: start.year, endMonth: today.month, endYear: today.year };
};

// On phone/tablet widths the sidebar becomes a slide-over overlay (see
// Sidebar.css's matching max-width: 900px breakpoint) rather than a
// permanently docked column, so it shouldn't default open and immediately
// cover the page on first load there — computed once at mount, not
// live-tracked across resizes.
const startsWithSidebarOpen = () => !window.matchMedia('(max-width: 900px)').matches;

const DashboardLayout = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(startsWithSidebarOpen);

  const realWorldPeriod = getCurrentRealWorldPeriod();
  const defaultRange = getDefaultDateRange();

  // Persistent Applied State (defaulting to the 3-month range ending "today")
  const [startMonth, setStartMonth] = useState(defaultRange.startMonth);
  const [startYear, setStartYear] = useState(defaultRange.startYear);
  const [endMonth, setEndMonth] = useState(defaultRange.endMonth);
  const [endYear, setEndYear] = useState(defaultRange.endYear);

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

  // "Today" is a one-click reset to the default range — unlike a manual
  // month/year pick, it applies immediately (via updatePeriodImmediately,
  // defined below) rather than staging a pending change that still needs
  // a separate Save.
  const handleResetToToday = () => {
    const range = getDefaultDateRange();
    updatePeriodImmediately(range.startMonth, range.startYear, range.endMonth, range.endYear);
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
        onClose={toggleSidebar}
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
        />
        <Outlet context={{
          startMonth, startYear, endMonth, endYear,
          pendingStartMonth, setPendingStartMonth,
          pendingStartYear, setPendingStartYear,
          pendingEndMonth, setPendingEndMonth,
          pendingEndYear, setPendingEndYear,
          isPending, handleApplyPeriod, handleResetToToday,
          updatePeriodImmediately, realWorldPeriod,
        }} />
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
