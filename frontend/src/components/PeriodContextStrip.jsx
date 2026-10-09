// One line under the top bar on every page except the dashboard (which has
// the full filter bar): what the shared filters are set to, and whether THIS
// page follows them. The Technical Adviser changes a filter and watches what
// moves; a page that does not move must say why rather than look broken.
import React from 'react';
import { Link } from 'react-router-dom';
import { CalendarRange, Pin } from 'lucide-react';
import { labelForPrincipal } from '../principals';
import { COMPARE_MODES, comparisonRange, rangeText } from '../periodFilter';
import './PeriodContextStrip.css';

// follows: the page's figures change with the date range.
const PAGE_RULES = {
  '/abc': {
    follows: 'partly',
    text: 'The "Selected range" view follows the date range. The "One month" view ranks the month you pick on the page.',
  },
  '/forecast': {
    follows: true,
    text: 'The chart follows the date range unless you set its own range on the page; Clear goes back to this one.',
  },
  '/category-trends': {
    follows: false,
    text: 'Each trend is fitted on the category’s last 24 months of sales, so the date range does not change this page.',
  },
  '/reorder': {
    follows: false,
    text: 'A plan is made for one month: this page follows the planning cycle you pick on it, not the date range.',
  },
  '/sku-management': {
    follows: false,
    text: 'A product list: the date range does not apply. Each class is from the latest ABC run.',
  },
  '/audit-log': {
    follows: false,
    text: 'The date range does not apply to the activity log.',
  },
};

const PeriodContextStrip = ({ pathname, principal, range, compare }) => {
  const rule = PAGE_RULES[pathname];
  if (!rule) return null;
  const versus = comparisonRange(range, compare);
  const compareText = compare === COMPARE_MODES.NONE || !versus
    ? 'no comparison'
    : `compared with ${compare === COMPARE_MODES.YEAR ? 'the same months last year' : 'the previous period'} (${versus.label})`;
  const tone = rule.follows === true ? 'is-follows' : rule.follows === 'partly' ? 'is-partly' : 'is-fixed';
  return (
    <div className={`period-strip ${tone}`} role="note">
      <span className="period-strip-filters">
        <CalendarRange size={14} aria-hidden="true" />
        <strong>{labelForPrincipal(principal)} · {rangeText(range)}</strong>
        <span className="period-strip-compare">· {compareText}</span>
      </span>
      <span className="period-strip-rule">
        {rule.follows !== true && <Pin size={12} aria-hidden="true" />}
        {rule.text}
      </span>
      <Link to={{ pathname: '/', search: window.location.search }} className="period-strip-link">
        Change filters
      </Link>
    </div>
  );
};

export default PeriodContextStrip;
