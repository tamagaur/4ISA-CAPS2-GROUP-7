import React, { Suspense, lazy, useEffect, useState } from 'react';
import PeriodContextStrip from './PeriodContextStrip';
import { COMPARE_MODES, COMPARE_STORAGE_KEY, isValidCompare, periodFromParam, periodToParam } from '../periodFilter';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { AlertTriangle, FlaskConical } from 'lucide-react';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import { preloadPages } from '../pageLoaders';
import { invalidateCache } from '../api/cache';
import { getDataModeInfo } from '../api/dataMode';
import { startSessionHeartbeat } from '../auth';
import DataFreshness from './DataFreshness';
import ErrorBoundary from './ErrorBoundary';
import { usePermissions } from '../permissions/context';
import { MOCK_PERMISSIONS } from '../api/mocks/permissionsMock';
import { LoadingStatus, PageSkeleton } from './Skeleton';
import { DEFAULT_PRINCIPAL, PRINCIPAL_STORAGE_KEY, isValidPrincipal, labelForPrincipal } from '../principals';
import { FIRST_DATA_YEAR, LATEST_DATA_PERIOD } from '../dataCoverage';
import {
  DATA_MODES, PLACEHOLDER_PRINCIPAL, PLACEHOLDER_START, getDataMode, isPreviewMode, setDataMode as storeDataMode,
} from '../dataMode';
import './DashboardLayout.css';

// The dev-only permissions mock switch (api/mocks/permissionsMock.js).
// Loaded on demand and only on a dev server, so a production build carries
// neither its code nor its CSS.
const MockPermissionsPanel = import.meta.env.DEV && MOCK_PERMISSIONS
  ? lazy(() => import('./dev/MockPermissionsPanel'))
  : null;

const PageLoadingFallback = () => (
  <>
    <LoadingStatus>Loading page…</LoadingStatus>
    <PageSkeleton />
  </>
);

// "Today" is pinned to February 2026, not the machine's actual clock — the
// app's own notion of "now" needs to stay fixed regardless of when it's
// actually opened, so every filter/default/upper-bound built on it stays
// consistent instead of drifting forward with the real calendar.
//
// Feb 2026 is also the system-wide upper bound on selectable dates (see
// DateFilter.jsx's LATEST_YEAR_MONTHS — it's the last month of real
// Unilever demand data), so "today" and "the latest pickable date" are the
// same value by construction: both read LATEST_DATA_PERIOD from
// dataCoverage.js, the one place to edit when a new month of data loads.
// This was Mar 2026, which is the FORECAST month, not a month with
// actuals — leaving it there made "Today" select an end month the picker
// no longer offers.
const getCurrentRealWorldPeriod = () => ({ ...LATEST_DATA_PERIOD });

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

// Default period: the 12 months ending "today" (the latest month with real
// data) — Mar 2025-Feb 2026 as of 2026-09. Twelve, not the seven this
// opened on until 2026-09-29, because a full year is one of every season:
// Unilever dips every July and February and peaks in June, and seven months
// (Aug-Feb) left out the June peak and the July dip, so one dip could read
// as a trend. It also shows Del Monte's real months properly (6 in the last
// year against 3 in seven months, its data being patchy), and matches SSM's
// own yearly view — its supplier allocation is last year's sales x
// 103-108%. Still comfortably inside the data (real demand starts Jan 2023).
// Both the initial state below and the "Today" reset button build off this
// same function, so they can never drift apart.
const DEFAULT_MONTHS_BACK = 11;

// Minimum SELECTABLE range width (inclusive month count, not "months
// back" — a 6-month minimum means Sep 2025-Feb 2026 is the shortest
// allowed pick, 6 points on a line chart). Matches two real numbers
// already in the pipeline, not an arbitrary UX guess:
//   - analytics/forecasting/baseline.py's MIN_MONTHS_WITH_SALES = 3 is the
//     hard floor below which no forecasting model runs for a SKU at all
//     (it gets a provisional trailing average instead).
//   - Six points is what "enough shape to see a trend, not just 2-3
//     connected dots" actually looks like in practice.
// 6 sits between those and the 12-month default above: comfortably past
// the analytics floor, and half a year is the shortest window that still
// says something about direction.
const MIN_RANGE_MONTHS = 6;

// Preview (src/dataMode.js) exists to show the whole span, so its default
// range is all of it: the first placeholder month through "today".
const getDefaultDateRange = (mode = DATA_MODES.REAL) => {
  const today = getCurrentRealWorldPeriod();
  const start = isPreviewMode(mode)
    ? PLACEHOLDER_START
    : subtractMonths(today.month, today.year, DEFAULT_MONTHS_BACK);
  return { startMonth: start.month, startYear: start.year, endMonth: today.month, endYear: today.year };
};

// Ranges and comparisons once kept in the browser (until 2026-10-09; the
// four san2_start_/san2_end_ keys before 2026-09-29). Nothing reads them now:
// the address carries the filters. They are removed once, at mount.
const RANGE_STORAGE_KEY = 'san2_date_range_v2';
const LEGACY_RANGE_KEYS = ['san2_start_month', 'san2_start_year', 'san2_end_month', 'san2_end_year'];

// A range in the address (?from=2025-03&to=2026-02), so a link or a reload
// shows the same view. Checked against what the picker offers: inside the
// data, not backwards, and at least MIN_RANGE_MONTHS long.
const loadUrlRange = (mode) => {
  const params = new URLSearchParams(window.location.search);
  const from = periodFromParam(params.get('from'));
  const to = periodFromParam(params.get('to'));
  if (!from || !to) return null;
  const today = getCurrentRealWorldPeriod();
  const first = isPreviewMode(mode) ? PLACEHOLDER_START : { month: 'Jan', year: String(FIRST_DATA_YEAR) };
  const start = periodValue(from.month, from.year);
  const end = periodValue(to.month, to.year);
  const fits = start >= periodValue(first.month, first.year)
    && end <= periodValue(today.month, today.year)
    && end - start + 1 >= MIN_RANGE_MONTHS;
  return fits ? { startMonth: from.month, startYear: from.year, endMonth: to.month, endYear: to.year } : null;
};

// The comparison in the address, else the default: the same months a year
// earlier, the like-for-like one for seasonal FMCG sales and the Technical
// Adviser's own question ("2025 vs 2024?").
const loadCompare = () => {
  const fromUrl = new URLSearchParams(window.location.search).get('compare');
  return isValidCompare(fromUrl) ? fromUrl : COMPARE_MODES.YEAR;
};


// On phone/tablet widths the sidebar becomes a slide-over overlay (see
// Sidebar.css's matching max-width: 900px breakpoint) rather than a
// permanently docked column, so it shouldn't default open and immediately
// cover the page on first load there — computed once at mount, not
// live-tracked across resizes.
const startsWithSidebarOpen = () => !window.matchMedia('(max-width: 900px)').matches;

const DashboardLayout = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(startsWithSidebarOpen);
  // True once the menu button has been used, so the page's slide
  // (Sidebar.css) plays on a toggle and not on first load.
  const [sidebarAnimated, setSidebarAnimated] = useState(false);

  // Warm every page's code in the background once someone is signed in, so
  // only the first page they land on waits on a chunk download.
  useEffect(() => {
    const idle = window.requestIdleCallback || ((cb) => setTimeout(cb, 1500));
    idle(preloadPages);
  }, []);

  // Keeps this sign-in's session open on the backend while the app is in
  // use — the Audit Log page's session lengths are measured from it.
  useEffect(() => startSessionHeartbeat(), []);

  const realWorldPeriod = getCurrentRealWorldPeriod();

  // Real data, or preview with the 2021-22 placeholder (src/dataMode.js).
  // Held here as state so the Topbar, the banner and every page re-render
  // on a flip; the module copy is what apiFetch reads.
  const [dataMode, setDataModeState] = useState(getDataMode);
  // Where the page opens (2026-10-09): the filters in the address when there
  // are any (a reload, a shared link), else the default view — the last 12
  // months, compared with the same months a year earlier. A range picked on
  // an earlier visit is no longer carried over, so every new visit starts on
  // the full-year, like-for-like view the Technical Adviser reads first.
  const [initialRange] = useState(() => loadUrlRange(dataMode) || getDefaultDateRange(dataMode));

  // What every comparison on the page is against (src/periodFilter.js):
  // the same months a year earlier (default), the period just before, or
  // none. Shared like the range, remembered per browser, kept in the address.
  const [compare, setCompareState] = useState(loadCompare);
  const setCompare = (next) => {
    if (isValidCompare(next)) setCompareState(next);
  };

  // What preview means right now (GET /data-mode): the placeholder window
  // and, when scripts/build_preview_outputs.py has run, `outputs` — the
  // what-if forecasts and LP the predictive and prescriptive cards show.
  // Null in real mode, and while the request is in flight.
  const [previewInfo, setPreviewInfo] = useState(null);

  // Applied range: the saved one, or the 12-month default ending "today".
  const [startMonth, setStartMonth] = useState(initialRange.startMonth);
  const [startYear, setStartYear] = useState(initialRange.startYear);
  const [endMonth, setEndMonth] = useState(initialRange.endMonth);
  const [endYear, setEndYear] = useState(initialRange.endYear);

  // The four keys the range used to be written to (never read) are removed
  // once, so they don't linger in anyone's browser.
  useEffect(() => {
    try {
      [...LEGACY_RANGE_KEYS, `${RANGE_STORAGE_KEY}:real`, `${RANGE_STORAGE_KEY}:preview`, COMPARE_STORAGE_KEY]
        .forEach((key) => localStorage.removeItem(key));
    } catch {
      // Storage unavailable: nothing to tidy.
    }
  }, []);

  // Pending Unsaved Selection State
  const [pendingStartMonth, setPendingStartMonth] = useState(startMonth);
  const [pendingStartYear, setPendingStartYear] = useState(startYear);
  const [pendingEndMonth, setPendingEndMonth] = useState(endMonth);
  const [pendingEndYear, setPendingEndYear] = useState(endYear);

  // Principal scope ('all' | 'unilever' | 'delmonte'), shared by every
  // page the same way the date range is. Read back from localStorage on
  // mount, but validated first — a stale or hand-edited value would
  // otherwise be sent straight to the backend, which 400s on anything
  // outside its allowlist.
  const [principal, setPrincipalState] = useState(() => {
    const fromUrl = new URLSearchParams(window.location.search).get('principal');
    if (isValidPrincipal(fromUrl)) return fromUrl;
    const stored = localStorage.getItem(PRINCIPAL_STORAGE_KEY);
    return isValidPrincipal(stored) ? stored : DEFAULT_PRINCIPAL;
  });

  const setPrincipal = (next) => {
    if (!isValidPrincipal(next)) return;
    setPrincipalState(next);
    localStorage.setItem(PRINCIPAL_STORAGE_KEY, next);
  };

  // Navigation Interception State
  const [navTarget, setNavTarget] = useState(null);
  const [showNavConfirm, setShowNavConfirm] = useState(false);

  const navigate = useNavigate();
  const location = useLocation();
  const isAdmin = usePermissions().role === 'admin';

  // Top-bar Refresh: drop every cached response and remount the current page
  // so its effects fetch again. Remounting (rather than asking each page to
  // refetch) keeps this in one place; a page's local picks, like ABC's
  // month, reset to their defaults, the same as reloading the page.
  const [refreshKey, setRefreshKey] = useState(0);
  const handleRefreshData = () => {
    invalidateCache();
    setRefreshKey((k) => k + 1);
  };

  // Refetched on every mode flip and Refresh, like the pages themselves.
  useEffect(() => {
    if (!isPreviewMode(dataMode)) {
      setPreviewInfo(null);
      return undefined;
    }
    let cancelled = false;
    getDataModeInfo()
      .then((info) => { if (!cancelled) setPreviewInfo(info); })
      .catch(() => { if (!cancelled) setPreviewInfo(null); });
    return () => { cancelled = true; };
  }, [dataMode, refreshKey]);

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
    setSidebarAnimated(true);
  };

  const handleApplyPeriod = () => {
    if (!canApplyPendingPeriod) return; // belt-and-suspenders — UI should already prevent this
    setStartMonth(pendingStartMonth);
    setStartYear(pendingStartYear);
    setEndMonth(pendingEndMonth);
    setEndYear(pendingEndYear);
  };

  // A quick range (Last 12 months, 2025, ...) applies at once, with no Save
  // step: the Technical Adviser changes the filter first and expects the
  // screen to answer.
  const applyPreset = (range) => {
    updatePeriodImmediately(range.startMonth, range.startYear, range.endMonth, range.endYear);
  };

  // The filters live in the address too (?from=&to=&compare=&principal=),
  // merged into whatever the page keeps there (?sku=, ?class=), so a copied
  // link or a reload opens the same view. Replaced, never pushed: Back still
  // leaves the page rather than stepping through filter changes.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const wanted = {
      from: periodToParam(startMonth, startYear),
      to: periodToParam(endMonth, endYear),
      compare,
      principal,
    };
    let changed = false;
    Object.entries(wanted).forEach(([key, value]) => {
      if (value && params.get(key) !== value) {
        params.set(key, value);
        changed = true;
      }
    });
    if (changed) navigate({ pathname: location.pathname, search: `?${params.toString()}` }, { replace: true });
  }, [startMonth, startYear, endMonth, endYear, compare, principal, location.pathname, location.search, navigate]);

  const handleDiscardPeriod = () => {
    setPendingStartMonth(startMonth);
    setPendingStartYear(startYear);
    setPendingEndMonth(endMonth);
    setPendingEndYear(endYear);
  };

  // "Today" is a one-click reset to the default range — unlike a manual
  // month/year pick, it applies immediately (via updatePeriodImmediately,
  // defined below) rather than staging a pending change that still needs
  // a separate Save — and forgets the saved range, so the next visit opens
  // on the default too.
  const handleResetToToday = () => {
    const range = getDefaultDateRange(dataMode);
    updatePeriodImmediately(range.startMonth, range.startYear, range.endMonth, range.endYear);
    setCompareState(COMPARE_MODES.YEAR);
  };

  // Flipping the mode switches to that mode's own range: the one saved for
  // it, else its default — all of Jan 2021 – today in preview, the usual
  // 12 months in real mode (whose picker can't show 2021-22 at all).
  // Turning preview on also switches to Unilever, the one principal with
  // placeholder months — under All, the both-principals-or-nothing rule
  // leaves those months blank. Every cached response is dropped and the
  // page remounts, like the Refresh button.
  const handleDataModeChange = (next) => {
    if (next === dataMode) return;
    const mode = storeDataMode(next);
    setDataModeState(mode);
    const range = getDefaultDateRange(mode);
    updatePeriodImmediately(range.startMonth, range.startYear, range.endMonth, range.endYear);
    if (isPreviewMode(mode)) setPrincipal(PLACEHOLDER_PRINCIPAL);
    invalidateCache();
    setRefreshKey((k) => k + 1);
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
  };

  return (
    <div className={`dashboard-layout ${isSidebarOpen ? '' : 'sidebar-closed'} ${sidebarAnimated ? 'sidebar-animated' : ''}`}>
      <Sidebar
        isOpen={isSidebarOpen}
        onClose={toggleSidebar}
        onNavAttempt={handleNavAttempt}
        currentMonth={realWorldPeriod.month}
      />
      {MockPermissionsPanel && (
        <Suspense fallback={null}>
          <MockPermissionsPanel />
        </Suspense>
      )}
      <div className="main-content">
        <Topbar
          toggleSidebar={toggleSidebar}
          isSidebarOpen={isSidebarOpen}
          rightSlot={<DataFreshness navKey={`${location.pathname}#${refreshKey}`} onRefresh={handleRefreshData} />}
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
          dataMode={dataMode}
          onDataModeChange={handleDataModeChange}
        />
        {/* On every page for as long as preview is on — a placeholder month
            must never be readable as SSM's own figure. */}
        {isPreviewMode(dataMode) && (
          <div className="preview-banner" role="status">
            <FlaskConical size={16} aria-hidden="true" className="preview-banner-icon" />
            <p className="preview-banner-text">
              <strong>Preview: Jan 2021 – Dec 2022 is placeholder data, not SSM&apos;s.</strong>{' '}
              Those months are synthetic Unilever sales, added so the dashboard can be seen over five years.
              {previewInfo?.outputs
                ? <> Forecasts, reorder recommendations and safety stock are a what-if run of the same models on that
                  five-year history (built {String(previewInfo.outputs.built_at).slice(0, 10)}) — never saved, not for decisions.</>
                : <> Forecasts, reorder recommendations and safety stock still use real data only.</>}
              {/* GET /data-mode compares the placeholder the what-if files
                  were built on with the one in the database now. */}
              {previewInfo?.outputs_stale && (
                <> <strong>That what-if run is outdated:</strong> the placeholder data has changed since it was built,
                  so those figures may not match the months shown.
                  {isAdmin ? ' Rebuild it with scripts/build_preview_outputs.py.' : ' Let an admin know.'}</>
              )}
              {principal !== PLACEHOLDER_PRINCIPAL && (
                <> The placeholder is Unilever&apos;s, so under {labelForPrincipal(principal)} those months stay empty.</>
              )}
            </p>
            <button type="button" className="preview-banner-btn" onClick={() => handleDataModeChange(DATA_MODES.REAL)}>
              Back to real data
            </button>
          </div>
        )}
        {/* Off the dashboard, which has the full filter bar: what the shared
            filters are set to, and whether this page follows them. */}
        <PeriodContextStrip
          pathname={location.pathname}
          principal={principal}
          range={{ startMonth, startYear, endMonth, endYear }}
          compare={compare}
        />
        <ErrorBoundary resetKey={`${location.pathname}:${refreshKey}`}>
          <Suspense fallback={<PageLoadingFallback />}>
            <Outlet key={refreshKey} context={{
              startMonth, startYear, endMonth, endYear,
              pendingStartMonth, setPendingStartMonth,
              pendingStartYear, setPendingStartYear,
              pendingEndMonth, setPendingEndMonth,
              pendingEndYear, setPendingEndYear,
              isPending, isPendingRangeValid, isPendingRangeLongEnough, canApplyPendingPeriod,
              handleApplyPeriod, handleResetToToday,
              updatePeriodImmediately, realWorldPeriod, applyPreset,
              compare, setCompare,
              principal, setPrincipal,
              dataMode, previewInfo,
            }} />
          </Suspense>
        </ErrorBoundary>
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
