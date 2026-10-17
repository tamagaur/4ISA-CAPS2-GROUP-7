import React from 'react';
import { useOutletContext } from 'react-router-dom';
import { Calendar, ChevronDown, Check, RefreshCw, RotateCcw, AlertTriangle } from 'lucide-react';
import { LATEST_DATA_PERIOD, FIRST_DATA_YEAR } from '../dataCoverage';
import { PLACEHOLDER_START, isPreviewMode } from '../dataMode';
import './DateFilter.css';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// System-wide selectable range: Jan 2023 through FEBRUARY 2026 — the span
// of real Unilever demand data (Unilever_SKU_Demand_Fact_Real: MIN =
// 2023-01, MAX = 2026-02). Both principals are in scope again (Del Monte
// was restored 2026-09-17, see principals.js); Del Monte's real sell-out
// runs 2023-01 to 2025-12, inside this window, so Unilever's span still
// bounds the picker.
//
// The ceiling was Mar 2026 before, which conflated two different things:
// 2026-03 is the FORECAST month (every served model projects last-actual
// + 1), not a month anyone has actuals for. Offering it as a selectable end
// let the user pick a window whose final month is empty by definition on
// every page that plots actuals. The forecast month is now derived from the
// selected end rather than being pickable itself.
//
// 2023 is the floor, so all of its months are valid; the latest year is the
// ceiling, so only its months up to the latest data month are. The years in
// between sit entirely inside the range and need no month restriction.
// Both ends come from dataCoverage.js — the one place to edit when a new
// month of data loads.
//
// Preview mode (src/dataMode.js) moves the floor back to the first
// placeholder year, 2021, so the five-year span is pickable. A page that
// reads real data only in preview too (SKU Forecast: forecasts never see a
// placeholder month) passes `realOnly` and keeps the real floor.
const yearsFrom = (firstYear) => Array.from(
  { length: Number(LATEST_DATA_PERIOD.year) - firstYear + 1 },
  (_, i) => String(firstYear + i)
);
const LATEST_YEAR = LATEST_DATA_PERIOD.year;
const LATEST_YEAR_MONTHS = MONTHS.slice(0, MONTHS.indexOf(LATEST_DATA_PERIOD.month) + 1);
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
// `singleMonth` (local mode only) shows one month + year instead of a range,
// for pages that read a single period — ABC Classification ignores the start
// of a range entirely. Not supported in shared mode: writing a one-month
// range into DashboardLayout would push every other page below its 6-month
// trend minimum.
const DateFilter = ({
  onRefresh, localValue, onLocalChange, onReset, minMonths = DEFAULT_MIN_RANGE_MONTHS, singleMonth = false, realOnly = false,
  showToday = true,
}) => {
  const outlet = useOutletContext() || {};
  const years = yearsFrom(
    !realOnly && isPreviewMode(outlet.dataMode) ? Number(PLACEHOLDER_START.year) : FIRST_DATA_YEAR
  );
  const isLocal = !!(localValue && onLocalChange);
  const isSingleMonth = isLocal && singleMonth;

  const sm = (isLocal ? localValue.startMonth : outlet.pendingStartMonth) ?? 'Jan';
  const sy = (isLocal ? localValue.startYear : outlet.pendingStartYear) ?? LATEST_YEAR;
  const em = (isLocal ? localValue.endMonth : outlet.pendingEndMonth) ?? LATEST_DATA_PERIOD.month;
  const ey = (isLocal ? localValue.endYear : outlet.pendingEndYear) ?? LATEST_YEAR;

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

  // Single-month mode keeps start === end so callers reading either field
  // get the same period.
  const handleSingleMonthChange = (month) => {
    onLocalChange({ ...localValue, startMonth: month, endMonth: month });
  };

  const handleSingleYearChange = (year) => {
    const month = (year === LATEST_YEAR && !LATEST_YEAR_MONTHS.includes(em))
      ? LATEST_YEAR_MONTHS[LATEST_YEAR_MONTHS.length - 1]
      : em;
    onLocalChange({ ...localValue, startMonth: month, startYear: year, endMonth: month, endYear: year });
  };

  if (isSingleMonth) {
    return (
      <div className="dashboard-date-controls-wrapper">
        <div className="dashboard-date-controls">
          <span className="date-single-label">Month</span>
          <div className="date-select-btn" style={{ position: 'relative' }}>
            <Calendar size={14} />
            {em}
            <ChevronDown size={14} />
            <select
              aria-label="Month"
              style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
              value={em}
              onChange={(e) => handleSingleMonthChange(e.target.value)}
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
              aria-label="Year"
              style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
              value={ey}
              onChange={(e) => handleSingleYearChange(e.target.value)}
            >
              {years.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>
          {onReset && (
            <button
              className="date-today-btn"
              onClick={onReset}
              title="Go back to the month the dashboard's date range ends on"
            >
              <RotateCcw size={14} />
              Clear
            </button>
          )}
        </div>
      </div>
    );
  }

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
          {years.map((y) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
      </div>

      <span style={{ color: '#667085', fontSize: '0.85rem', margin: '0 4px' }}>to</span>

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
          {years.map((y) => (
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

      {!isLocal && showToday && (
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
