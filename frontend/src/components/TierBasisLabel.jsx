import { formatMonth } from '../utils/formatDate';
import InfoTip from './InfoTip';
import { tierShort } from '../labels';
import './TierBasisLabel.css';

// One statement of which ABC run the tiers on a page come from, shared by the
// Dashboard, Reorder, ABC and SKU pages so all four say it the same way.
// `periods` is the response's tier_a_periods ({ 'Unilever': '2026-02', 'Del Monte':
// '2025-12' }, one run per principal); `period` is the older single value, used
// only when the map is missing.

// The visible line says "top sellers" (src/labels.js); the class letter is in the "?".
const BASIS = {
  Unilever: 'the biggest sellers over the last 12 months, plus new products that are among them over the last 3',
  'Del Monte': 'the biggest sellers in that month',
};
const TECHNICAL = {
  Unilever: 'Top sellers are ABC Class A: the products that together make up the first 80% of revenue over the last 12 months, plus products first sold within 12 months that are Class A over the last 3. Middle sellers are Class B, low sellers Class C.',
  'Del Monte': 'Top sellers are ABC Class A in that month. Middle sellers are Class B, low sellers Class C.',
};

// A basis still waiting on the adviser (DEC-38): said behind the line's "?",
// not in the visible line (2026-10-19), on every page that shows it.
const CAVEAT = {
  Unilever: 'This rule for Unilever\'s top sellers is pending adviser confirmation.',
};

const PRINCIPAL_LABEL = { unilever: 'Unilever', delmonte: 'Del Monte' };

// A tier from a run more than this many months before the page's own is marked stale.
export const STALE_AFTER_MONTHS = 6;

const monthIndex = (period) => {
  const m = /^(\d{4})-(\d{2})/.exec(String(period || ''));
  return m ? Number(m[1]) * 12 + Number(m[2]) - 1 : null;
};

// True when tierPeriod is more than 6 months before anchor ('YYYY-MM' both).
export function isStaleTier(tierPeriod, anchor) {
  const t = monthIndex(tierPeriod);
  const a = monthIndex(anchor);
  return t != null && a != null && a - t > STALE_AFTER_MONTHS;
}

// The run a principal's rows are current against: its own entry in tier_a_periods,
// else the single fallback. A row whose tier_period differs is carried forward.
export function currentPeriodFor(principal, periods, fallback) {
  const own = periods?.[PRINCIPAL_LABEL[principal]];
  return own ?? fallback ?? null;
}

// The newest run in the map: the anchor a mixed-principal page measures staleness from.
export function latestPeriod(periods, fallback) {
  const values = Object.values(periods || {});
  return values.length ? values.reduce((a, b) => (a > b ? a : b)) : fallback ?? null;
}

export function tierBasisText(periods, period) {
  const entries = Object.entries(periods || {});
  if (entries.length === 0) return period ? `Top sellers as of ${formatMonth(period)}` : null;
  if (entries.length === 1) {
    const [name, p] = entries[0];
    return `Top sellers as of ${formatMonth(p)}${BASIS[name] ? `: ${BASIS[name]}` : ''}`;
  }
  return `Top sellers as of ${entries.map(([name, p]) => `${formatMonth(p)} (${name})`).join(' · ')}`;
}

export default function TierBasisLabel({ periods, period, className = '' }) {
  const text = tierBasisText(periods, period);
  if (!text) return null;
  const names = Object.keys(periods || {});
  const title = names.length > 1 ? names.map((n) => `${n}: ${BASIS[n]}`).join('\n') : undefined;
  const caveats = names.filter((n) => CAVEAT[n]);
  const technical = names.map((n) => TECHNICAL[n]).filter(Boolean);
  return (
    <p className={`tier-basis-label ${className}`.trim()} title={title}>
      {text}
      {(caveats.length > 0 || technical.length > 0) && (
        <InfoTip label="About top sellers" size={12}>
          {[...technical, ...caveats.map((n) => CAVEAT[n])].join(' ')}
        </InfoTip>
      )}
    </p>
  );
}

// A tier letter with its run's age: current runs plain, carried-forward ones faded with
// the month they were set ("C · Jun 2025"), and a "stale" badge past 6 months. Display only:
// nothing on a page counts, filters or ranks by an aged tier.
export function TierChip({ tier, tierPeriod, isCurrent, anchor }) {
  if (!tier) return <span className="cell-empty">—</span>;
  const aged = isCurrent === false;
  const stale = aged && isStaleTier(tierPeriod, anchor);
  const title = aged
    ? `Class ${tier} — last classified ${formatMonth(tierPeriod)}; not ranked in the current run, so this is carried forward${stale ? ' (stale: over 6 months old)' : ''}`
    : `Class ${tier} — current run${tierPeriod ? ` (${formatMonth(tierPeriod)})` : ''}`;
  return (
    <span className={`tier-chip tier-chip-${tier}${aged ? ' tier-chip-aged' : ''}`} title={title}>
      {tierShort(tier)}
      {aged && tierPeriod && <span className="tier-chip-age">{formatMonth(tierPeriod)}</span>}
      {stale && <span className="tier-chip-stale">stale</span>}
    </span>
  );
}
