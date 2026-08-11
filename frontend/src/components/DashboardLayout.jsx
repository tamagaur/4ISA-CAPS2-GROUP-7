import React, { useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import './DashboardLayout.css';

// Helper to derive current real-world month & year from system date
const getCurrentRealWorldPeriod = () => {
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const now = new Date();
  const currentMonthName = months[now.getMonth()] || 'Aug';
  const currentYearStr = now.getFullYear().toString();
  const validYear = ['2021', '2022', '2023', '2024', '2025', '2026'].includes(currentYearStr) ? currentYearStr : '2026';
  return { month: currentMonthName, year: validYear };
};

const DashboardLayout = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const realWorldPeriod = getCurrentRealWorldPeriod();

  // Persistent Applied State (stored in localStorage, defaulting to real-world current month/year: Aug 2026)
  const [selectedMonth, setSelectedMonth] = useState(() => {
    return localStorage.getItem('san2_selected_month') || realWorldPeriod.month;
  });
  const [selectedYear, setSelectedYear] = useState(() => {
    return localStorage.getItem('san2_selected_year') || realWorldPeriod.year;
  });

  // Pending Unsaved Selection State
  const [pendingMonth, setPendingMonth] = useState(selectedMonth);
  const [pendingYear, setPendingYear] = useState(selectedYear);

  // Navigation Interception State
  const [navTarget, setNavTarget] = useState(null);
  const [showNavConfirm, setShowNavConfirm] = useState(false);

  const navigate = useNavigate();

  // Evaluates to true only when pending selection differs from applied period
  const isPending = pendingMonth !== selectedMonth || pendingYear !== selectedYear;

  const toggleSidebar = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };

  const handleApplyPeriod = () => {
    setSelectedMonth(pendingMonth);
    setSelectedYear(pendingYear);
    localStorage.setItem('san2_selected_month', pendingMonth);
    localStorage.setItem('san2_selected_year', pendingYear);
  };

  const handleDiscardPeriod = () => {
    setPendingMonth(selectedMonth);
    setPendingYear(selectedYear);
  };

  const handleResetToToday = () => {
    const todayPeriod = getCurrentRealWorldPeriod();
    setPendingMonth(todayPeriod.month);
    setPendingYear(todayPeriod.year);
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
          selectedMonth={selectedMonth} 
          selectedYear={selectedYear} 
          pendingMonth={pendingMonth}
          setPendingMonth={setPendingMonth}
          pendingYear={pendingYear}
          setPendingYear={setPendingYear}
          isPending={isPending}
          handleApplyPeriod={handleApplyPeriod}
          handleResetToToday={handleResetToToday}
          realWorldMonth={realWorldPeriod.month}
          realWorldYear={realWorldPeriod.year}
        />
        <Outlet context={{ selectedMonth, selectedYear }} />
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
                You changed the selected period to <strong>{pendingMonth} {pendingYear}</strong> but haven't applied it. 
                Save this change, or discard it and keep viewing <strong>{selectedMonth} {selectedYear}</strong>?
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
