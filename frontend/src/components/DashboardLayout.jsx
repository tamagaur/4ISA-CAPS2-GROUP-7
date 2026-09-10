import React, { useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import './DashboardLayout.css';

// "Today" is pinned to February 2026, not the machine's actual clock — the
// app's own notion of "now" needs to stay fixed regardless of when it's
// actually opened, so every filter/default/upper-bound built on it stays
// consistent instead of drifting forward with the real calendar.
//
// Feb 2026 is also the system-wide upper bound on selectable dates (see
// DateFilter.jsx's LATEST_YEAR_MONTHS — it's the last month of real
// Unilever demand data), so "today" and "the latest pickable date" are the
// same value by construction rather than two numbers kept in sync by hand.
// This was Mar 2026, which is the FORECAST month, not a month with
// actuals — leaving it there made "Today" select an end month the picker
// no longer offers.
const getCurrentRealWorldPeriod = () => ({ month: 'Feb', year: '2026' });

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// Orders (month, year) pairs so a start/end range can be compared —
// year*12+monthIndex sorts correctly across a year boundary (e.g. Dec 2024
// < Jan 2025). Used to catch a start-after-end range, which the picker used
// to accept silently: it saved fine, then every page's own real-period
// filter (`a.period >= start && a.period <= end`) matched nothing, so the
// user just saw an empty chart with no indication why.
const periodValue = (month, year) => Number(year) * 12 + MONTHS.indexOf(month);

// Subtracts `count` months from (month, year), rolling the year backward
// across a January boundary rather than clamping — e.g. 2 months before
// Jan 2026 is Nov 2025.
const subtractMonths = (month, year, count) => {
  const total = MONTHS.indexOf(month) - count;
  const yearOffset = Math.floor(total / 12);
  const monthIndex = ((total % 12) + 12) % 12;
  return { month: MONTHS[monthIndex], year: String(Number(year) + yearOffset) };
};

// Default period: 6 months back from "today" (the latest month with real
// data) through "today" — a 7-point window, up from the 3 points this
// used to open on. Short windows make the dashboard's trend charts read
// as a couple of disconnected dots; six months back is enough shape to
// see direction at a glance while still comfortably inside the data
// (real Unilever demand starts Jan 2023, so this never underflows).
// Both the initial state below and the "Today" reset button build off
// this same function, so they can never drift apart.
const DEFAULT_MONTHS_BACK = 6;

// Minimum SELECTABLE range width (inclusive month count, not "months
// back" — a 6-month minimum means Sep 2025-Feb 2026 is the shortest
// allowed pick, 6 points on a line chart). Matches two real numbers
// already in the pipeline, not an arbitrary UX guess:
//   - analytics/forecasting/baseline.py's MIN_MONTHS_WITH_SALES = 3 is the
//     hard floor below which MA3 won't even run for a SKU at all.
//   - This app's own DEFAULT_MONTHS_BACK above already opens on 7 points,
//     which is what "enough shape to see a trend, not just 2-3 connected
//     dots" actually looks like in practice.
// 6 sits between those: comfortably past the analytics floor, matching
// what the app already defaults to, so "the minimum you can pick" and
// "what you see with no changes" are the same order of magnitude.
const MIN_RANGE_MONTHS = 6;

const getDefaultDateRange = () => {
  const today = getCurrentRealWorldPeriod();
  const start = subtractMonths(today.month, today.year, DEFAULT_MONTHS_BACK);
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

  // false when the pending start is after the pending end (e.g. Dec 2024 -
  // Jan 2024). Checked here, not just in the picker UI, so the one function
  // that actually commits a range (handleApplyPeriod) can never be tricked
  // into applying an invalid one via some other caller.
  const isPendingRangeValid =
    periodValue(pendingStartMonth, pendingStartYear) <= periodValue(pendingEndMonth, pendingEndYear);

  // Inclusive month count of the PENDING range — only meaningful once it's
  // chronologically valid (a backwards range's "count" is negative/noise,
  // and already has its own message via isPendingRangeValid above).
  const pendingRangeMonthCount =
    periodValue(pendingEndMonth, pendingEndYear) - periodValue(pendingStartMonth, pendingStartYear) + 1;
  const isPendingRangeLongEnough = isPendingRangeValid && pendingRangeMonthCount >= MIN_RANGE_MONTHS;

  // The single gate that actually decides whether Save may commit the
  // pending range — both checks have to pass, chronological order first
  // (a backwards 8-month span shouldn't read as "long enough").
  const canApplyPendingPeriod = isPendingRangeValid && isPendingRangeLongEnough;

  const toggleSidebar = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };

  const handleApplyPeriod = () => {
    if (!canApplyPendingPeriod) return; // belt-and-suspenders — UI should already prevent this
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
          isPending, isPendingRangeValid, isPendingRangeLongEnough, canApplyPendingPeriod,
          handleApplyPeriod, handleResetToToday,
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
              {!isPendingRangeValid && (
                <p className="period-nav-error">
                  <AlertTriangle size={16} className="period-nav-error-icon" />
                  <span>That range starts after it ends — Save is disabled until the start month is on or before the end month.</span>
                </p>
              )}
              {isPendingRangeValid && !isPendingRangeLongEnough && (
                <p className="period-nav-error">
                  <AlertTriangle size={16} className="period-nav-error-icon" />
                  <span>
                    That range only spans {pendingRangeMonthCount} month{pendingRangeMonthCount === 1 ? '' : 's'} —
                    select at least {MIN_RANGE_MONTHS} for a meaningful trend before saving.
                  </span>
                </p>
              )}
            </div>
            <div className="period-nav-footer">
              <button className="period-discard-btn" onClick={handleConfirmDiscardNav}>
                Discard
              </button>
              <button
                className="period-save-btn"
                onClick={handleConfirmSaveNav}
                disabled={!canApplyPendingPeriod}
                title={canApplyPendingPeriod ? undefined : 'Fix the date range before saving'}
              >
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
