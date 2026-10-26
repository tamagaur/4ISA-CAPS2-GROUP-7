// One line under the top bar on the pages that read the shared date range
// but have no full filter bar of their own (the dashboard has one): what the
// shared filters are set to, and how THIS page follows them, with the way
// back to change them. The Technical Adviser changes a filter and watches
// what moves.
//
// Only pages that use the date range (2026-10-20): a page the range does not
// touch — the order plan (its own planning cycle), the product list, the
// activity log, the Reference Guide, the admin pages — shows no date at all,
// rather than a range it ignores. The principal filter in the top bar is
// gated the same way (Topbar.jsx's PAGES_WITH_PRINCIPAL).
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
    follows: 'partly',
    // Drawn like the Sales forecast page's strip (2026-10-25); the text still
    // says which part of the range it follows.
    look: 'follows',
    text: 'Trends are fitted as of the end of the date range, on the 24 months of sales up to it. The start of the range does not shorten that history.',
  },
};

const PeriodContextStrip = ({ pathname, principal, range, compare }) => {
  const rule = PAGE_RULES[pathname];
  if (!rule) return null;
  const versus = comparisonRange(range, compare);
  const compareText = compare === COMPARE_MODES.NONE || !versus
    ? 'no comparison'
    : `compared with ${compare === COMPARE_MODES.YEAR ? 'the same months last year' : 'the previous period'} (${versus.label})`;
  const look = rule.look ?? rule.follows;
  const tone = look === true || look === 'follows' ? 'is-follows' : look === 'partly' ? 'is-partly' : 'is-fixed';
  return (
    <div className={`period-strip ${tone}`} role="note">
      <span className="period-strip-filters">
        <CalendarRange size={14} aria-hidden="true" />
        <strong>{labelForPrincipal(principal)} · {rangeText(range)}</strong>
        <span className="period-strip-compare">· {compareText}</span>
      </span>
      <span className="period-strip-rule">
        {tone !== 'is-follows' && <Pin size={12} aria-hidden="true" />}
        {rule.text}
      </span>
      <Link to={{ pathname: '/', search: window.location.search }} className="period-strip-link">
        Change filters
      </Link>
    </div>
  );
};

export default PeriodContextStrip;
