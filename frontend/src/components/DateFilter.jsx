import React from 'react';
import { useOutletContext } from 'react-router-dom';
import { Calendar, ChevronDown, Check, RefreshCw } from 'lucide-react';
import './DateFilter.css';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const YEARS = ['2021', '2022', '2023', '2024', '2025', '2026'];

const noop = () => {};

// Rendered from the same title-row spot on every analytics page (Dashboard,
// SKU Forecast, ABC Classification, Reorder Recs) so the control stays in
// one uniform place app-wide. Every select here edits the *pending* period
// held in DashboardLayout, not the applied one — nothing the rest of the
// app reads changes until Save is clicked, matching the existing
// nav-interception "unsaved period" dialog's rule, just surfaced inline
// instead of only when navigating away.
const DateFilter = ({ onRefresh }) => {
  const {
    pendingStartMonth, setPendingStartMonth,
    pendingStartYear, setPendingStartYear,
    pendingEndMonth, setPendingEndMonth,
    pendingEndYear, setPendingEndYear,
    isPending,
    handleApplyPeriod,
    handleResetToToday,
  } = useOutletContext() || {};

  const sm = pendingStartMonth ?? 'Apr';
  const sy = pendingStartYear ?? '2026';
  const em = pendingEndMonth ?? 'Jun';
  const ey = pendingEndYear ?? '2026';

  return (
    <div className="dashboard-date-controls">
      <div className="date-select-btn" style={{ position: 'relative' }}>
        <Calendar size={14} />
        {sm}
        <ChevronDown size={14} />
        <select
          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer', width: '100%', height: '100%' }}
          value={sm}
          onChange={(e) => (setPendingStartMonth || noop)(e.target.value)}
        >
          {MONTHS.map((m) => (
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
          onChange={(e) => (setPendingStartYear || noop)(e.target.value)}
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
          onChange={(e) => (setPendingEndMonth || noop)(e.target.value)}
        >
          {MONTHS.map((m) => (
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
          onChange={(e) => (setPendingEndYear || noop)(e.target.value)}
        >
          {YEARS.map((y) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
      </div>

      {isPending && (
        <button
          className="date-save-btn"
          onClick={handleApplyPeriod || noop}
          title="Apply the selected date range"
        >
          <Check size={14} />
          Save
        </button>
      )}

      <button className="date-today-btn" onClick={handleResetToToday || noop}>
        <Calendar size={14} />
        Today
      </button>

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
