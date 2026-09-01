import React from 'react';
import { useOutletContext } from 'react-router-dom';
import { Calendar, ChevronDown, Check, RefreshCw, RotateCcw } from 'lucide-react';
import './DateFilter.css';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// System-wide selectable range: Jan 2023 through Mar 2026 — Unilever's
// real data (the only principal left, see DashboardLayout.jsx/backend's
// 2026-09 Del Monte removal) runs Jan 2023 - Mar 2026 on the live
// database; anything outside that is real, but permanently empty, so it
// isn't offered as a choice rather than being pickable and then showing
// a blank page. 2023 is the floor, so every one of its months is valid;
// 2026 is the ceiling, so only Jan-Mar 2026 are — no month-restriction is
// needed for 2024/2025, which sit entirely inside the range.
const YEARS = ['2023', '2024', '2025', '2026'];
const LATEST_YEAR = '2026';
const LATEST_YEAR_MONTHS = ['Jan', 'Feb', 'Mar'];
const monthsForYear = (year) => (year === LATEST_YEAR ? LATEST_YEAR_MONTHS : MONTHS);

const noop = () => {};

// Rendered from the same title-row spot on every analytics page (Dashboard,
// SKU Forecast, ABC Classification, Reorder Recs) so the control stays in
// one uniform place app-wide.
//
// Two modes, same bounded Jan 2023 - Mar 2026 option logic either way:
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
const DateFilter = ({ onRefresh, localValue, onLocalChange, onReset }) => {
  const outlet = useOutletContext() || {};
  const isLocal = !!(localValue && onLocalChange);

  const sm = (isLocal ? localValue.startMonth : outlet.pendingStartMonth) ?? 'Jan';
  const sy = (isLocal ? localValue.startYear : outlet.pendingStartYear) ?? '2026';
  const em = (isLocal ? localValue.endMonth : outlet.pendingEndMonth) ?? 'Mar';
  const ey = (isLocal ? localValue.endYear : outlet.pendingEndYear) ?? '2026';

  const startMonthOptions = monthsForYear(sy);
  const endMonthOptions = monthsForYear(ey);

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
          title="Apply the selected date range"
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
  );
};

export default DateFilter;
