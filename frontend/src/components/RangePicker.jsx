// The dashboard's filter controls as one compact row (2026-10-09): a button
// that names the applied range and opens a panel (quick ranges that apply at
// once, custom months with Save, back to the default), and the shared
// "Compare with". The row never changes height, so the pinned toolbar holds
// still while the page scrolls under it; the panel floats above the page.
//
// LOCAL mode (2026-10-28, SKU Forecast): pass `localValue` / `onLocalChange`
// (DateFilter's local mode, the same pair) and the picker reads and writes
// the caller's own range instead of the shared one: a quick range or a
// custom month applies at once, there is no Save and no "Compare with" (the
// page's comparison is fixed), and `onReset` (optional) is the caller's own
// "back to the Dashboard's range". `minMonths` and `realOnly` pass through
// to DateFilter.
import React, { useEffect, useRef, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { CalendarRange, ChevronDown, RotateCcw } from 'lucide-react';
import DateFilter from './DateFilter';
import { PLACEHOLDER_START, isPreviewMode } from '../dataMode';
import { COMPARE_MODES, COMPARE_OPTIONS, quickRanges, rangeText, sameRange } from '../periodFilter';
import './RangePicker.css';

const RangePicker = ({ localValue, onLocalChange, onReset, minMonths, realOnly = false } = {}) => {
  const outlet = useOutletContext() || {};
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const isLocal = !!(localValue && onLocalChange);
  const applied = isLocal ? localValue : {
    startMonth: outlet.startMonth, startYear: outlet.startYear,
    endMonth: outlet.endMonth, endYear: outlet.endYear,
  };
  const preview = !realOnly && isPreviewMode(outlet.dataMode);
  const calendarLatest = outlet.dataLatest || outlet.latestPeriod;
  // Rolling ranges use the latest month for this principal; calendar years
  // reach through the latest year across both principals.
  const quick = quickRanges(
    preview ? Number(PLACEHOLDER_START.year) : undefined,
    outlet.latestPeriod || undefined,
    calendarLatest || undefined,
  );
  const activeQuick = quick.find((q) => sameRange(q.range, applied)) || null;
  const calendarRanges = quick.filter((q) => q.key.startsWith('y'));
  const rollingRanges = quick.filter((q) => !q.key.startsWith('y'));
  const defaultCalendarKey = calendarLatest?.year ? `y${calendarLatest.year}` : null;
  const appliedKey = rangeText(applied);
  // "Mar 25 – Feb 26" for a phone-width button.
  const shortText = `${applied.startMonth} ${String(applied.startYear).slice(2)} – ${applied.endMonth} ${String(applied.endYear).slice(2)}`;

  // Close on a click outside, on Escape, and once a new range is applied
  // (a quick range, or Save on the custom months).
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  useEffect(() => { setOpen(false); }, [appliedKey]);

  const isDefault = activeQuick?.key === defaultCalendarKey && outlet.compare === COMPARE_MODES.YEAR;
  const applyQuick = (q) => (isLocal ? onLocalChange(q.range) : outlet.applyPreset(q.range, q.key));
  const renderQuickRange = (q) => (
    <button
      key={q.key}
      type="button"
      className={`range-quick-btn${activeQuick?.key === q.key ? ' is-active' : ''}`}
      aria-pressed={activeQuick?.key === q.key}
      onClick={() => { applyQuick(q); setOpen(false); }}
    >
      {q.label}
      <span className="range-quick-sub">{q.subtitle || rangeText(q.range)}</span>
    </button>
  );

  return (
    <div className="range-picker" ref={rootRef}>
      <button
        type="button"
        className={`range-picker-btn${open ? ' is-open' : ''}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <CalendarRange size={15} aria-hidden="true" />
        <span className="range-picker-text">
          <span className="range-picker-range range-picker-long">{appliedKey}</span>
          <span className="range-picker-range range-picker-short">{shortText}</span>
          {activeQuick && <span className="range-picker-quick">{activeQuick.label}</span>}
        </span>
        {!isLocal && outlet.isPending && <span className="range-picker-pending" title="A custom range is picked but not saved">Unsaved</span>}
        <ChevronDown size={14} aria-hidden="true" />
      </button>

      {!isLocal && outlet.setCompare && (
        <label className="range-compare">
          <span className="range-compare-label">Compare with</span>
          <select value={outlet.compare} onChange={(e) => outlet.setCompare(e.target.value)} aria-label="Compare with">
            {COMPARE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
      )}

      {open && (
        <div className="range-panel" role="dialog" aria-label="Date range">
          {calendarRanges.length > 0 && (
            <>
              <p className="range-panel-title">Calendar years</p>
              <div className="range-panel-quick">
                {calendarRanges.map(renderQuickRange)}
              </div>
            </>
          )}
          {rollingRanges.length > 0 && (
            <>
              <p className="range-panel-title">Rolling ranges</p>
              <div className="range-panel-quick">
                {rollingRanges.map(renderQuickRange)}
              </div>
            </>
          )}
          <p className="range-panel-title">Custom months</p>
          {isLocal ? (
            <DateFilter showLatestYear={false} localValue={localValue} onLocalChange={onLocalChange}
              minMonths={minMonths} realOnly={realOnly} />
          ) : (
            <DateFilter showLatestYear={false} />
          )}
          <div className="range-panel-foot">
            <span className="range-panel-default">
              {isLocal
                ? 'Follows the Dashboard’s range until you pick one here; a pick here changes this page only.'
                : 'Default: the latest data calendar year (Jan–Dec), compared with the same calendar year before it. Months without records stay missing.'}
            </span>
            {isLocal ? onReset && (
              <button type="button" className="range-reset-btn" onClick={() => { onReset(); setOpen(false); }}>
                <RotateCcw size={13} aria-hidden="true" />
                Back to the Dashboard&apos;s range
              </button>
            ) : !isDefault && (
              <button type="button" className="range-reset-btn" onClick={outlet.handleResetToLatestYear}>
                <RotateCcw size={13} aria-hidden="true" />
                Back to default
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default RangePicker;
