import React from 'react';
import { useOutletContext } from 'react-router-dom';
import { Calendar, ChevronDown, Check, RefreshCw, RotateCcw, AlertTriangle } from 'lucide-react';
import './DateFilter.css';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// System-wide selectable range: Jan 2023 through FEBRUARY 2026 — the exact
// span of real Unilever demand data (verified against
// Unilever_SKU_Demand_Fact_Real: MIN = 2023-01, MAX = 2026-02). Unilever is
// the only principal left, see DashboardLayout.jsx / the backend's 2026-09
// Del Monte removal.
//
// The ceiling was Mar 2026 before, which conflated two different things:
// 2026-03 is the FORECAST month (MA3 projects last-actual + 1), not a month
// anyone has actuals for. Offering it as a selectable end let the user pick
// a window whose final month is empty by definition on every page that
// plots actuals. The forecast month is now derived from the selected end
// rather than being pickable itself.
//
// 2023 is the floor, so all of its months are valid; 2026 is the ceiling,
// so only Jan-Feb are. 2024/2025 sit entirely inside the range and need no
// month restriction.
const YEARS = ['2023', '2024', '2025', '2026'];
const LATEST_YEAR = '2026';
const LATEST_YEAR_MONTHS = ['Jan', 'Feb'];
const monthsForYear = (year) => (year === LATEST_YEAR ? LATEST_YEAR_MONTHS : MONTHS);

// year*12+monthIndex sorts (month, year) pairs correctly across a year
// boundary (Dec 2024 < Jan 2025) — used to catch a start-after-end pick
// (e.g. start Dec 2024, end Jan 2024), which neither mode used to reject:
// it saved/applied fine, then every page's own `period >= start && period
// <= end` filter matched nothing, so the user just got a silently empty
// chart with no explanation.
const periodValue = (month, year) => Number(year) * 12 + MONTHS.indexOf(month);

// Same default MIN_RANGE_MONTHS as DashboardLayout.jsx (kept as a literal
// here rather than imported — this file already duplicates small per-file
// constants like periodValue/MONTHS instead of a shared util module,
// matching the rest of this codebase's convention). A too-short range
// (e.g. one month) technically saves fine but every trend chart it feeds
// renders as 1-2 disconnected dots, not a readable trend — 6 is the
// analytics pipeline's own MIN_MONTHS_WITH_SALES (3) plus enough margin
// to match what this app already defaults to (DEFAULT_MONTHS_BACK = 6,
// a 7-point window). Overridable via the `minMonths` prop for local mode:
// SKU Forecast passes its own per-SKU effectiveMinMonths, since a SKU with
// under 6 months of real history shouldn't be told to select more than it
// has (see SKUForecast.jsx's effectiveMinMonths comment).
const DEFAULT_MIN_RANGE_MONTHS = 6;

const noop = () => {};

// Rendered from the same title-row spot on every analytics page (Dashboard,
// SKU Forecast, ABC Classification, Reorder Recs) so the control stays in
// one uniform place app-wide.
//
// Two modes, same bounded Jan 2023 - Feb 2026 option logic either way:
//   SHARED (default — no `localValue`/`onLocalChange` passed): edits the
//     *pending* period held in DashboardLayout, not the applied one —
//     nothing the rest of the app reads changes until Save is clicked
//     (nav-interception's "unsaved period" rule, surfaced inline). This
//     is the cross-page range every page but SKU Forecast's own chart
//     follows.
//   LOCAL (`localValue`/`onLocalChange` passed — SKU Forecast's own
//     picker): reads/writes a range that lives entirely in the caller's
//     own state, applies every change immediately (no pending/Save step),
//     and never touches DashboardLayout's shared range. This is what
//     gives SKU Forecast "freedom to pick a range for this one chart"
//     without ever dragging every other page's date along with it. In
//     place of Save/Today it takes an optional `onReset` — the caller's
//     own "go back to the dashboard's range" handler, since "reset to
//     what" means something different per page in local mode (there is
//     no single shared "Today" default to fall back to here).
const DateFilter = ({ onRefresh, localValue, onLocalChange, onReset, minMonths = DEFAULT_MIN_RANGE_MONTHS }) => {
  const outlet = useOutletContext() || {};
  const isLocal = !!(localValue && onLocalChange);

  const sm = (isLocal ? localValue.startMonth : outlet.pendingStartMonth) ?? 'Jan';
  const sy = (isLocal ? localValue.startYear : outlet.pendingStartYear) ?? '2026';
  const em = (isLocal ? localValue.endMonth : outlet.pendingEndMonth) ?? 'Feb';
  const ey = (isLocal ? localValue.endYear : outlet.pendingEndYear) ?? '2026';

  const startMonthOptions = monthsForYear(sy);
  const endMonthOptions = monthsForYear(ey);

  const isRangeValid = periodValue(sm, sy) <= periodValue(em, ey);
  const rangeMonthCount = periodValue(em, ey) - periodValue(sm, sy) + 1; // only meaningful once isRangeValid
  const isRangeLongEnough = isRangeValid && rangeMonthCount >= minMonths;

  // Shared mode already has its own canApplyPendingPeriod computed in
  // DashboardLayout (guards handleApplyPeriod itself, not just this
  // button) — reuse it when present so the two can't disagree; local mode
  // has no separate pending/applied split, so the live checks above (from
  // the current sm/sy/em/ey) are the only ones that apply.
  const rangeValid = isLocal
    ? (isRangeValid && isRangeLongEnough)
    : (outlet.canApplyPendingPeriod ?? (isRangeValid && isRangeLongEnough));

  // Changing TO 2026 can strand the other field's already-selected month
  // outside Jan-Mar (e.g. start year was 2025 with month=Aug, then the
  // user picks 2026) — clamp it to the boundary rather than leaving an
  // option selected that no longer exists in that side's own dropdown.
  // Never clamps unnecessarily: only fires when the current month isn't
  // already within LATEST_YEAR_MONTHS. In local mode both fields live in
  // ONE object, so the clamp is folded into a single onLocalChange call —
  // two separate calls would have the second overwrite the first's year
  // change, since each would spread the same still-stale `localValue`.
  const handleStartYearChange = (year) => {
    const nextMonth = (year === LATEST_YEAR && !LATEST_YEAR_MONTHS.includes(sm))
      ? LATEST_YEAR_MONTHS[LATEST_YEAR_MONTHS.length - 1]
      : sm;
    if (isLocal) {
      onLocalChange({ ...localValue, startYear: year, startMonth: nextMonth });
    } else {
      (outlet.setPendingStartYear || noop)(year);
      if (nextMonth !== sm) (outlet.setPendingStartMonth || noop)(nextMonth);
    }
  };

  const handleEndYearChange = (year) => {
    const nextMonth = (year === LATEST_YEAR && !LATEST_YEAR_MONTHS.includes(em))
      ? LATEST_YEAR_MONTHS[LATEST_YEAR_MONTHS.length - 1]
      : em;
    if (isLocal) {
      onLocalChange({ ...localValue, endYear: year, endMonth: nextMonth });
    } else {
      (outlet.setPendingEndYear || noop)(year);
      if (nextMonth !== em) (outlet.setPendingEndMonth || noop)(nextMonth);
    }
  };

  const handleStartMonthChange = (month) => {
    if (isLocal) onLocalChange({ ...localValue, startMonth: month });
    else (outlet.setPendingStartMonth || noop)(month);
  };

  const handleEndMonthChange = (month) => {
    if (isLocal) onLocalChange({ ...localValue, endMonth: month });
    else (outlet.setPendingEndMonth || noop)(month);
  };

  return (
    <div className="dashboard-date-controls-wrapper">
    <div className="dashboard-date-controls">
      <div className="date-select-btn" style={{ position: 'relative' }}>
        <Calendar size={14} />
        {sm}
        <ChevronDown size={14} />
        <select
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
          value={sm}
          onChange={(e) => handleStartMonthChange(e.target.value)}
        >
          {startMonthOptions.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      <div className="date-select-btn" style={{ position: 'relative' }}>
        {sy}
        <ChevronDown size={14} />
        <select
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
          value={sy}
          onChange={(e) => handleStartYearChange(e.target.value)}
        >
          {YEARS.map((y) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
      </div>

      <span style={{ color: '#a0aec0', fontSize: '0.85rem', margin: '0 4px' }}>to</span>

      <div className="date-select-btn" style={{ position: 'relative' }}>
        <Calendar size={14} />
        {em}
        <ChevronDown size={14} />
        <select
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
          value={em}
          onChange={(e) => handleEndMonthChange(e.target.value)}
        >
          {endMonthOptions.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      <div className="date-select-btn" style={{ position: 'relative' }}>
        {ey}
        <ChevronDown size={14} />
        <select
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
          value={ey}
          onChange={(e) => handleEndYearChange(e.target.value)}
        >
          {YEARS.map((y) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
      </div>

      {!isLocal && outlet.isPending && (
        <button
          className="date-save-btn"
          onClick={outlet.handleApplyPeriod || noop}
          disabled={!rangeValid}
          title={rangeValid ? 'Apply the selected date range' : 'Fix the date range before saving'}
        >
          <Check size={14} />
          Save
        </button>
      )}

      {!isLocal && (
        <button className="date-today-btn" onClick={outlet.handleResetToToday || noop}>
          <Calendar size={14} />
          Today
        </button>
      )}

      {isLocal && onReset && (
        <button
          className="date-today-btn"
          onClick={onReset}
          title="Clear this chart's custom date range and follow the dashboard's again"
        >
          <RotateCcw size={14} />
          Clear
        </button>
      )}

      {onRefresh && (
        <button className="refresh-btn" onClick={onRefresh}>
          <RefreshCw size={14} />
          Refresh
        </button>
      )}
    </div>

    {/* Both checks are caught live, as soon as they happen, not only on
        Save — local mode has no Save step at all, so this is the only
        feedback that mode gets. Named explicitly with the actual months
        picked (and, for the too-short case, the actual count), matching
        the "flag the valid range" pattern the SKU Forecast per-SKU
        coverage check already uses elsewhere on this page. Start-after-end
        takes priority — a backwards range's month count is meaningless,
        so there's nothing useful to say about length until that's fixed. */}
    {!isRangeValid && (
      <p className="date-range-error">
        <AlertTriangle size={15} className="date-range-error-icon" />
        <span>{sm} {sy} is after {em} {ey} — pick a start date on or before the end date.</span>
      </p>
    )}
    {isRangeValid && !isRangeLongEnough && (
      <p className="date-range-error">
        <AlertTriangle size={15} className="date-range-error-icon" />
        <span>
          {sm} {sy} – {em} {ey} is only {rangeMonthCount} month{rangeMonthCount === 1 ? '' : 's'} — select at least{' '}
          {minMonths} month{minMonths === 1 ? '' : 's'} so the trend charts have enough points to read.
        </span>
      </p>
    )}
    </div>
  );
};

export default DateFilter;
