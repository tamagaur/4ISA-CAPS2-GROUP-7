import React from 'react';
import { useLocation } from 'react-router-dom';
import { Check, Calendar, FlaskConical } from 'lucide-react';
import { DEFAULT_PRINCIPAL, SELECTABLE_PRINCIPALS } from '../principals';
import { DATA_MODES, isPreviewMode } from '../dataMode';
import Greeting from './ui/Greeting';
import './Topbar.css';

const Topbar = ({
  toggleSidebar,
  isSidebarOpen = true,
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
  principal = DEFAULT_PRINCIPAL,
  setPrincipal = () => {},
  dataMode = DATA_MODES.REAL,
  onDataModeChange = () => {},
  // Whether this server has synthetic data to show (DashboardLayout asks GET
  // /data-mode): false greys the switch out; null while unknown.
  syntheticAvailable = null,
}) => {
  const preview = isPreviewMode(dataMode);
  const location = useLocation();
  const isToday =
    pendingStartMonth === realWorldMonth &&
    pendingStartYear === realWorldYear &&
    pendingEndMonth === realWorldMonth &&
    pendingEndYear === realWorldYear;
  const isForecastPage = location.pathname === '/forecast';

  // The principal filter (and the synthetic-data switch beside it) only
  // where a page has a per-principal view: the dashboard and the analysis
  // and inventory pages. The admin pages (audit log, data upload, user
  // management), the card preview and My profile show the same thing
  // whichever principal is picked, so neither control appears there
  // (Audrey, 2026-10-16).
  const PAGES_WITHOUT_PRINCIPAL = ['/audit-log', '/upload', '/users', '/preview', '/profile'];
  const showPrincipalFilter = !PAGES_WITHOUT_PRINCIPAL.includes(location.pathname);

  return (
    <header className="topbar">
      <div className="topbar-left">
        {/* Three lines while the sidebar is open; once it is closed on a
            desktop the SAN2 logo takes their place, so the brand stays on
            screen and clicking it brings the sidebar back. Phones and
            tablets keep the three lines (Topbar.css), where the sidebar
            starts closed and a logo alone would not read as a menu. */}
        <button
          className={`sidebar-toggle-btn${isSidebarOpen ? '' : ' is-sidebar-closed'}`}
          onClick={toggleSidebar}
          aria-label={isSidebarOpen ? 'Hide the menu' : 'Show the menu'}
          aria-expanded={isSidebarOpen}
        >
          <svg className="menu-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <line x1="3" y1="12" x2="21" y2="12"></line>
            <line x1="3" y1="6" x2="21" y2="6"></line>
            <line x1="3" y1="18" x2="21" y2="18"></line>
          </svg>
          <img src="/logo-topbar.png" alt="" className="sidebar-toggle-logo" />
        </button>

        {/* Date Filter removed and placed in page headers */}

        {showPrincipalFilter && (
          <div className="principal-filter">
            <div className="principal-segmented" role="tablist" aria-label="Principal filter">
              {SELECTABLE_PRINCIPALS.map((p) => (
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
                principal options collapse into a native select (CSS swaps
                which one is visible — they're never both shown). */}
            <div className="principal-dropdown">
              <select
                className="dropdown-select"
                aria-label="Principal filter"
                value={principal}
                onChange={(e) => setPrincipal(e.target.value)}
              >
                {SELECTABLE_PRINCIPALS.map((p) => (
                  <option key={p.key} value={p.key}>{p.label}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Real data, or real data plus the labelled synthetic demonstration
            data (src/dataMode.js; schema demo, CLAUDE.md rule 2), asked for by
            Kelvin on 2026-10-16. Same pages as the principal filter; the
            banner under this bar says what it adds whenever it is on. Greyed
            out while the server has no synthetic data to show, unless it is
            already on, so it can always be turned off. */}
        {showPrincipalFilter && (
          <button
            type="button"
            role="switch"
            aria-checked={preview}
            aria-label="Include synthetic data"
            disabled={!preview && syntheticAvailable === false}
            className={`data-mode-toggle${preview ? ' is-on' : ''}`}
            onClick={() => onDataModeChange(preview ? DATA_MODES.REAL : DATA_MODES.PREVIEW)}
            title={preview
              ? 'On: real data plus synthetic data, marked as synthetic on every chart. Click to go back to real data only.'
              : syntheticAvailable === false
                ? 'Synthetic data is not switched on for this server.'
                : "Show SSM's real data plus synthetic (generated) data for the months SSM has no figures for. For viewing only, not for decisions."}
          >
            <FlaskConical size={14} aria-hidden="true" />
            <span className="data-mode-toggle-label">Include synthetic data</span>
            <span className="data-mode-toggle-track" aria-hidden="true"><span className="data-mode-toggle-thumb" /></span>
          </button>
        )}
      </div>

      {/* "Good afternoon, Mikhaella!" (ui/Greeting.jsx), between the
          filters and the Refresh block; on its own line when the bar is
          too narrow for all three. */}
      <Greeting />

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
