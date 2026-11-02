import React, { useLayoutEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { FlaskConical } from 'lucide-react';
import { DEFAULT_PRINCIPAL, SELECTABLE_PRINCIPALS } from '../principals';
import { DATA_MODES, isPreviewMode } from '../dataMode';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import NotificationBell from './NotificationBell';
import './Topbar.css';

// The date range moved into each page's own RangePicker (2026-10-09); the
// range props DashboardLayout still passes are not read here.
const Topbar = ({
  toggleSidebar,
  isSidebarOpen = true,
  rightSlot,
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
  const { role, hasPermission } = usePermissions();
  const showBell = role === 'admin' || hasPermission(P.LP_PROPOSE) || hasPermission(P.LP_DECIDE);

  // The bar's own height as --topbar-h on the pane that scrolls
  // (.main-content, its parent), kept current as the bar wraps or unwraps,
  // so a toolbar that sticks under it (the dashboard's section chips,
  // Dashboard.css .dash-toolbar) sits just below it rather than behind it.
  const barRef = useRef(null);
  useLayoutEffect(() => {
    const bar = barRef.current;
    const pane = bar?.parentElement;
    if (!bar || !pane) return undefined;
    const publish = () => pane.style.setProperty('--topbar-h', `${Math.round(bar.getBoundingClientRect().height)}px`);
    publish();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(publish);
    observer.observe(bar);
    return () => observer.disconnect();
  }, []);

  // The principal filter (and the synthetic-data switch beside it) only on
  // the pages whose data it filters (Audrey, 2026-10-16, again 2026-10-18):
  // the dashboard, the analysis pages and the inventory pages, each of which
  // reads `principal` to load its data. Everything else (Reference Guide,
  // audit log, data upload, user management, the card preview, My profile)
  // shows the same thing whichever principal is picked. A list of the pages
  // that use it, not of those that don't, so a new page has no switch until
  // it reads the principal.
  const PAGES_WITH_PRINCIPAL = ['/', '/forecast', '/category-trends', '/abc', '/sku-management', '/reorder'];
  const showPrincipalFilter = PAGES_WITH_PRINCIPAL.includes(location.pathname);

  return (
    <header className="topbar" ref={barRef}>
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

      {/* The greeting sat here until 2026-10-21; it is the dashboard's
          welcome banner now (ui/Greeting.jsx). */}

      {rightSlot}

      {/* The notification bell (2026-10-28): admins hear about staff
          requests, staff about the decisions on theirs. Shown to whoever can
          make or settle a request. */}
      {showBell && <NotificationBell />}

      {/* The topbar used to end with a second, bare "who am I" avatar here
          (no menu, no action — just initials in a circle) that duplicated
          the real identity card at the bottom of Sidebar.jsx (name, role,
          online status, logout). Removed rather than kept as a decoration;
          the sidebar card is the one place that information lives now. */}
    </header>
  );
};

export default Topbar;
