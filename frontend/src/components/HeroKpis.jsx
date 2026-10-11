// The dashboard's top row (2026-10-10 redesign, after the team's reference
// mock-up): one wide performance card (annual sales against SSM's supplier
// allocation), inventory value, and the two operational cards (below safety
// stock, pending reorder actions), which are tinted so the things to act on
// read apart from the performance figures.
//
// Presentation only. Every figure is one GET /dashboard already serves and
// Dashboard.jsx already computes (kpis, allocation, safety_stock_exposure,
// recommendations); nothing here is a new calculation except reading those
// figures side by side:
//   - the allocation status compares average monthly sales with the chosen
//     level's monthly figure, the existing allocation card's own rule;
//   - year-over-year compares the year's sales with the SAME months a year
//     earlier, from GET /dashboard's allocation block for that period
//     (Dashboard.jsx fetches it), and is left out when the months on record
//     differ.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDown, ArrowRight, ArrowUp, Check, AlertTriangle, Info } from 'lucide-react';
import InfoTip from './InfoTip';
import BasisTag from './BasisTag';
import { Sparkline } from './KPICard';
import { formatCompactPesos } from './Charts';
import { formatMonth } from '../utils/formatDate';
import './HeroKpis.css';

const monthName = (period) => (period ? formatMonth(period).split(' ')[0] : null);

// A rounded change pill: arrow + text, coloured by direction (or tone).
const Pill = ({ text, direction, tone = 'neutral', icon = null }) => {
  if (!text) return null;
  const Icon = icon || (direction === 'up' ? ArrowUp : direction === 'down' ? ArrowDown : null);
  return (
    <span className={`hero-pill is-${tone}`}>
      {Icon && <Icon size={12} aria-hidden="true" />}
      <span>{text}</span>
    </span>
  );
};

// A comparison from Dashboard.jsx's pill extras ({ deltaLine, deltaTone,
// trendDirection }); a line without a tone is a note, not a change.
const ComparePill = ({ extras }) => {
  if (!extras?.deltaLine) return null;
  if (!extras.deltaTone) return <span className="hero-note">{extras.deltaLine}</span>;
  return <Pill text={extras.deltaLine} direction={extras.trendDirection} tone={extras.deltaTone} />;
};

// The card frame: top accent, coloured dot, title, the period basis tag.
// `action` cards (things to act on) get a tinted surface.
export const HeroCard = ({ tone, title, tooltip, basis, action = false, className = '', children }) => (
  <section className={`hero-card is-${tone}${action ? ' is-action' : ''} ${className}`} aria-label={title}>
    <header className="hero-card-head">
      <span className="hero-card-name">
        <span className="hero-dot" aria-hidden="true" />
        <h3 className="hero-card-title">
          {title}
          {tooltip && <InfoTip label={`About ${title}`} size={12}>{tooltip}</InfoTip>}
        </h3>
      </span>
      {basis && <span className="hero-card-basis"><BasisTag {...basis} /></span>}
    </header>
    {children}
  </section>
);

// ── Card 1: annual sales and the supplier allocation ──────────────────────
export const AnnualSalesCard = ({
  allocation, yoy = null, latest = null, range = null, basis = null, tooltip = null,
}) => {
  const a = allocation || {};
  const levels = [...(a.levels || [])].sort((x, y) => x.pct - y.pct);
  const [chosenPct, setChosenPct] = useState(null);
  const pct = chosenPct ?? a.default_pct ?? levels[0]?.pct ?? null;
  const level = levels.find((l) => l.pct === pct) || levels[0] || null;

  const year = a.allocation_year;
  const hasYtd = a.ytd_sales != null && a.ytd_months > 0;
  const lastName = monthName(a.latest_month);
  const span = a.ytd_months === 1 ? lastName : `Jan–${lastName}`;
  // The months the figure covers, and how many of them have sales on record
  // (Del Monte's 2025 has 6 of its 12): never "Jan–Dec" for a part year.
  const lastIndex = a.latest_month ? Number(a.latest_month.slice(5, 7)) : 0;
  const ytdNote = a.ytd_months < lastIndex
    ? ` (${a.ytd_months} of ${lastIndex} months on record)`
    : lastIndex < 12 ? ' (year to date)' : '';
  const ytdLabel = hasYtd ? `FY ${year} sales, ${span}${ytdNote}` : year ? `FY ${year} sales` : 'Sales';

  // The existing allocation card's rule: average monthly sales against the
  // level's monthly figure (a partial year compares fairly with a full one).
  const avgMonthly = hasYtd ? a.ytd_sales / a.ytd_months : null;
  const onPace = level && avgMonthly != null ? avgMonthly >= level.monthly : null;
  const statusText = onPace == null ? null : onPace ? `On track for ${level.pct}%` : `Below the ${level.pct}% pace`;
  const yoyText = yoy?.pct != null
    ? `${yoy.pct >= 0 ? '+' : '−'}${Math.abs(yoy.pct).toFixed(1)}% vs ${yoy.label}`
    : null;

  // Progress to the chosen annual target (a whole-year basis only), with a
  // tick where sales would be by now at an even pace.
  const target = level?.annual ?? null;
  const share = target && hasYtd ? a.ytd_sales / target : null;
  const pace = a.ytd_months > 0 && a.ytd_months < 12 ? a.ytd_months / 12 : null;

  return (
    <HeroCard tone="green" title="Annual sales and allocation" tooltip={tooltip} basis={basis} className="hero-card-wide">
      <div className="hero-split">
        <div className="hero-split-col">
          <p className="hero-label">{hasYtd ? ytdLabel : range?.label || 'Sales'}</p>
          <p className="hero-value">{hasYtd ? formatCompactPesos(a.ytd_sales) : range?.value ?? '—'}</p>
          <div className="hero-pills">
            {statusText && (
              <Pill
                text={yoyText ? `${statusText} · ${yoyText}` : statusText}
                tone={onPace ? 'positive' : 'warning'}
                icon={onPace ? Check : AlertTriangle}
              />
            )}
            {!statusText && yoyText && <Pill text={yoyText} direction={yoy.pct >= 0 ? 'up' : 'down'} tone={yoy.pct >= 0 ? 'positive' : 'negative'} />}
          </div>
          {yoy?.note && <p className="hero-note">{yoy.note}</p>}
        </div>
        <div className="hero-split-col">
          <p className="hero-label">Latest month{latest?.month ? ` (${latest.month})` : ''}</p>
          <div className="hero-value-row">
            <p className="hero-value">{latest?.value ?? '—'}</p>
            {latest?.trend && <Sparkline points={latest.trend.points} color={latest.trend.color} />}
          </div>
          <div className="hero-pills"><ComparePill extras={latest?.change} /></div>
          {latest?.blockedReason && <p className="hero-note">{latest.blockedReason}</p>}
        </div>
      </div>

      {/* The selected range's own total, against the shared comparison. */}
      {hasYtd && range?.short && (
        <div className="hero-range-row">
          <span className="hero-range-text">Selected range: <strong>{range.short}</strong></span>
          <ComparePill extras={range.change} />
        </div>
      )}

      {target && share != null && (
        <div className="hero-progress">
          <div
            className="hero-progress-track"
            role="img"
            aria-label={`${formatCompactPesos(a.ytd_sales)} of the ${level.pct}% target ${formatCompactPesos(target)}`
              + `${pace ? `; an even pace would be ${Math.round(pace * 100)}% by ${lastName}` : ''}`}
          >
            <span className={`hero-progress-fill${onPace === false ? ' is-short' : ''}`} style={{ width: `${Math.min(share, 1) * 100}%` }} />
            {pace && <span className="hero-progress-pace" style={{ left: `${pace * 100}%` }} title={`Even pace by ${lastName}`} />}
          </div>
          <div className="hero-progress-labels">
            <span>FY {a.basis_year} base: {formatCompactPesos(a.basis_sales)}</span>
            <span>
              FY {year}: {formatCompactPesos(a.ytd_sales)} · {Math.round(share * 100)}% of the {level.pct}% target
            </span>
          </div>
        </div>
      )}

      <div className="hero-alloc">
        <div className="hero-alloc-head">
          <span className="hero-label is-caps">
            Estimated {target ? 'annual ' : ''}allocation target
            <InfoTip label="About the allocation target" size={12}>
              SSM&apos;s rule (client meeting, Sep 2026): the principal sets the year&apos;s allocation from the
              previous year&apos;s sales × 103% (minimum), 105% or 108% (maximum). The percentage that applies
              each year is still a question for SSM, so this is an assumption.
            </InfoTip>
          </span>
          {target && levels.length > 1 && (
            <span className="hero-alloc-range">
              Range: {formatCompactPesos(levels[0].annual)} – {formatCompactPesos(levels[levels.length - 1].annual)}
            </span>
          )}
        </div>
        {level ? (
          <div className="hero-alloc-row">
            <p className="hero-alloc-value">
              {target ? formatCompactPesos(target) : `${formatCompactPesos(level.monthly)}/month`}
              <span className="hero-alloc-basis">
                {level.pct}% × FY {a.basis_year} sales
                {a.basis_months < 12 ? ` (${a.basis_months} months on record, an average month)` : ''}
              </span>
            </p>
            <div className="hero-alloc-levels" role="group" aria-label="Allocation level">
              {levels.map((l) => (
                <button
                  key={l.pct}
                  type="button"
                  className={`hero-level${l.pct === pct ? ' is-active' : ''}`}
                  aria-pressed={l.pct === pct}
                  onClick={() => setChosenPct(l.pct)}
                >
                  {l.pct}%
                </button>
              ))}
            </div>
          </div>
        ) : (
          <p className="hero-note">{a.blocked_reason || 'The allocation is not available for this range.'}</p>
        )}
      </div>
    </HeroCard>
  );
};

// ── Small visuals that fill the three narrow cards (2026-10-09) ───────────
// Each draws figures the card already receives from GET /dashboard; none
// computes anything new beyond a share of a whole the card already states.

// Weeks of cover against SSM's policy: a bar to the cover, a tick at the
// policy. The scale runs a little past the larger of the two, so neither
// end sits on the card's edge.
export const CoverMeter = ({ weeks, policy, provisional = false }) => {
  if (weeks == null || policy == null) return null;
  const max = Math.max(weeks, policy) * 1.15 || 1;
  const times = policy > 0 ? weeks / policy : null;
  const policyAt = (policy / max) * 100;
  // The policy label hangs off its tick, kept inside the card at either end.
  const policyAlign = policyAt > 60 ? 'is-end' : policyAt < 25 ? 'is-start' : '';
  return (
    <div className="hero-meter">
      <div className="hero-meter-head">
        <span>≈ <strong>{weeks.toFixed(1)} weeks</strong> of cover{provisional ? ' (provisional)' : ''}</span>
        {times != null && <span className="hero-meter-times">{times.toFixed(1)}× policy</span>}
      </div>
      <div
        className="hero-meter-track"
        role="img"
        aria-label={`About ${weeks.toFixed(1)} weeks of cover against SSM's policy of ${policy} weeks`}
      >
        <span className="hero-meter-fill" style={{ width: `${(weeks / max) * 100}%` }} />
        <span className="hero-meter-tick" style={{ left: `${policyAt}%` }} />
      </div>
      <div className="hero-meter-scale">
        <span className={`hero-meter-policy ${policyAlign}`} style={{ left: `${policyAt}%` }}>
          SSM policy: {policy} wk
        </span>
      </div>
    </div>
  );
};

// One whole split into parts (each { key, label, value }), with a legend.
// Zero parts stay in the legend (a "0 critical" is worth reading) but draw
// no segment.
export const ShareBar = ({ parts, label, inline = false }) => {
  const total = parts.reduce((sum, p) => sum + (p.value || 0), 0);
  if (!total) return null;
  return (
    <div className="hero-share">
      <div className="hero-share-track" role="img" aria-label={label}>
        {parts.filter((p) => p.value > 0).map((p) => (
          <span key={p.key} className={`hero-share-seg is-${p.key}`} style={{ flexGrow: p.value }} />
        ))}
      </div>
      <ul className={`hero-share-legend${inline ? ' is-inline' : ''}`}>
        {parts.map((p) => (
          <li key={p.key}>
            <span className={`hero-share-swatch is-${p.key}`} aria-hidden="true" />
            <span className="hero-share-label">{p.label}</span>
            <strong>{(p.value || 0).toLocaleString()}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
};

// A few named rows with one figure each (the products furthest below
// safety stock), names cut to one line with the full name on hover.
export const MiniList = ({ title, figureLabel, rows }) => {
  if (!rows?.length) return null;
  return (
    <div className="hero-mini">
      <div className="hero-mini-head">
        <span>{title}</span>
        <span>{figureLabel}</span>
      </div>
      <ul>
        {rows.map((r) => (
          <li key={r.key}>
            <span className="hero-mini-name" title={r.name}>{r.name}</span>
            <span className="hero-mini-figure">{r.figure}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

// ── Card 2: inventory value ───────────────────────────────────────────────
export const InventoryCard = ({ value, lines = [], flag = null, change = null, cover = null, tooltip, basis }) => (
  <HeroCard tone="blue" title="Inventory value" tooltip={tooltip} basis={basis}>
    <p className="hero-value">{value}</p>
    <div className="hero-lines">
      {lines.filter(Boolean).map((line) => <p key={line} className="hero-line">{line}</p>)}
    </div>
    {cover && <CoverMeter {...cover} />}
    <div className="hero-pills hero-pills-foot">
      {flag && (
        <span className="hero-pill is-warning">
          <AlertTriangle size={12} aria-hidden="true" />
          <span>{flag.label}</span>
          {flag.detail && <InfoTip label={flag.label} size={11}>{flag.detail}</InfoTip>}
        </span>
      )}
      <ComparePill extras={change} />
    </div>
  </HeroCard>
);

// ── Cards 3 and 4: the operational cards ──────────────────────────────────
export const ActionCard = ({
  tone, title, value, unit, lines = [], badge = null, link = null, tooltip, basis, severity = null, children = null,
}) => (
  <HeroCard tone={tone} title={title} tooltip={tooltip} basis={basis} action>
    <p className={`hero-value${severity ? ` is-${severity}` : ''}`}>
      {value}
      {unit && <span className="hero-unit">{unit}</span>}
    </p>
    <div className="hero-lines">
      {lines.filter(Boolean).map((line) => <p key={line} className="hero-line">{line}</p>)}
    </div>
    {children}
    {badge && (
      <div className="hero-pills">
        <span className={`hero-pill is-${badge.tone || 'info'}`}>
          {badge.tone === 'info' && <Info size={12} aria-hidden="true" />}
          <span>{badge.label}</span>
          {badge.detail && <InfoTip label={badge.label} size={11}>{badge.detail}</InfoTip>}
        </span>
      </div>
    )}
    {link && (
      <div className="hero-link-row">
        {link.to ? (
          <Link to={link.to} className="hero-link">{link.label} <ArrowRight size={13} aria-hidden="true" /></Link>
        ) : (
          <button type="button" className="hero-link" onClick={link.onClick}>
            {link.label} <ArrowRight size={13} aria-hidden="true" />
          </button>
        )}
      </div>
    )}
  </HeroCard>
);
