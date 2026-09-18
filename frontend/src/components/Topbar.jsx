import React from 'react';
import { useLocation } from 'react-router-dom';
import { Check, Calendar } from 'lucide-react';
import { PRINCIPALS } from '../principals';
import './Topbar.css';

const Topbar = ({
  toggleSidebar,
  rightSlot,
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
  realWorldYear = '2026',
  principal = 'all',
  setPrincipal = () => {},
}) => {
  const location = useLocation();
  const isToday =
    pendingStartMonth === realWorldMonth &&
    pendingStartYear === realWorldYear &&
    pendingEndMonth === realWorldMonth &&
    pendingEndYear === realWorldYear;
  const isForecastPage = location.pathname === '/forecast';

  // Principal filter is only meaningful on analytics & management pages.
  // Admin-only pages (audit log, data upload, user management) operate
  // across all data and have no per-principal view, so it's hidden there.
  const ADMIN_PAGES = ['/audit-log', '/upload', '/users'];
  const showPrincipalFilter = !ADMIN_PAGES.includes(location.pathname);

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

        {showPrincipalFilter && (
          <div className="principal-filter">
            <div className="principal-segmented" role="tablist" aria-label="Principal filter">
              {PRINCIPALS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  role="tab"
                  aria-selected={principal === p.key}
                  className={`principal-segment ${principal === p.key ? 'active' : ''}`}
                  onClick={() => setPrincipal(p.key)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            {/* Below 640px the segmented control doesn't fit, so the same
                three options collapse into a native select (CSS swaps
                which one is visible — they're never both shown). */}
            <div className="principal-dropdown">
              <select
                className="dropdown-select"
                aria-label="Principal filter"
                value={principal}
                onChange={(e) => setPrincipal(e.target.value)}
              >
                {PRINCIPALS.map((p) => (
                  <option key={p.key} value={p.key}>{p.label}</option>
                ))}
              </select>
            </div>
          </div>
        )}
      </div>

      {rightSlot}

      {/* The topbar used to end with a second, bare "who am I" avatar here
          (no menu, no action — just initials in a circle) that duplicated
          the real identity card at the bottom of Sidebar.jsx (name, role,
          online status, logout). Removed rather than kept as a decoration;
          the sidebar card is the one place that information lives now. */}
    </header>
  );
};

export default Topbar;
