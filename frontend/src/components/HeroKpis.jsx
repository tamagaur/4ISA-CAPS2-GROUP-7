// The dashboard's top row (2026-10-10 redesign, after the team's reference
// mock-up; 2026-10-11 layout): one wide performance card on the left (annual
// sales against SSM's supplier allocation) and four small cards in two rows
// on the right. The top two are what SSM holds (inventory value, stock
// cover); the bottom two are operational (below safety stock, pending
// reorders) and tinted, so the things to act on read apart from the rest.
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
import { ArrowDown, ArrowUp, ArrowUpRight, Check, AlertTriangle } from 'lucide-react';
import InfoTip from './InfoTip';
import BasisTag from './BasisTag';
import { Sparkline } from './KPICard';
import { formatCompactPesos } from './Charts';
import { formatMonth } from '../utils/formatDate';
import { coverScale, formatPercent, policyRatio, shareOf } from '../utils/kpiMath';
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

// ── The four KPI cards (2026-10-11 redesign) ──────────────────────────────
// One skeleton for all four, after the team's reference mock-up: the figure
// with one supporting line and the date it is for; what supports it (a
// comparison, a meter, a share); the way to the detail. On the two
// operational cards (`split`) the supporting figures sit beside the main one
// when the card is wide enough, and under it otherwise (HeroKpis.css).
//
// Presentation only, like the rest of this file. The arithmetic the cards do
// on GET /dashboard's figures (a ratio, a share, a split) is utils/kpiMath.js.
// What a card used to spell out in lines of text (the price basis, what moves
// with the date filter, how a figure is formed) is now in its "?"; warnings
// about the data (an unusual count, a provisional figure) stay on the card.

// A card's "?" text: short paragraphs, the definition first.
const TipText = ({ lines }) => (
  <>
    {lines.filter(Boolean).map((line) => <span key={line} className="hero-tip-line">{line}</span>)}
  </>
);

export const KpiCard = ({
  tone, title, tooltip = null, action = false, split = false, primary, detail = null, footer = null,
}) => (
  <section
    className={`hero-card hero-kpi is-${tone}${action ? ' is-action' : ''}${split ? ' is-split' : ''}`}
    aria-label={title}
  >
    <header className="hero-kpi-head">
      <span className="hero-card-name">
        <span className="hero-dot" aria-hidden="true" />
        <h3 className="hero-card-title">{title}</h3>
      </span>
      {tooltip?.some(Boolean) && (
        <InfoTip label={`About ${title}`} size={14}><TipText lines={tooltip} /></InfoTip>
      )}
    </header>
    <div className="hero-kpi-body">
      <div className="hero-kpi-primary">{primary}</div>
      {detail && <div className="hero-kpi-detail">{detail}</div>}
    </div>
    {footer && <div className="hero-kpi-foot">{footer}</div>}
  </section>
);

// The big figure and its two lines: what it counts, and the date it is for.
// A figure that can't be shown is "—" with the reason as its line.
const KpiPrimary = ({ value, unit = null, severity = null, subtitle = null, subtitleTitle, asOf = null }) => (
  <>
    <p className="hero-value">
      <span className={severity ? `is-${severity}` : undefined}>{value}</span>
      {unit && <span className="hero-unit">{unit}</span>}
    </p>
    {subtitle && <p className="hero-kpi-sub" title={subtitleTitle}>{subtitle}</p>}
    {asOf && <p className="hero-kpi-asof">{asOf}</p>}
  </>
);

// ── Inventory value ───────────────────────────────────────────────────────
// `change` is the shared comparison's pill.
export const InventoryCard = ({
  value, subtitle = null, subtitleTitle, asOf = null, change = null, tooltip = null,
}) => (
  <KpiCard
    tone="blue"
    title="Inventory value"
    tooltip={tooltip}
    primary={<KpiPrimary value={value} subtitle={subtitle} subtitleTitle={subtitleTitle} asOf={asOf} />}
    detail={change?.deltaLine ? <div className="hero-pills"><ComparePill extras={change} /></div> : null}
  />
);

// ── Stock cover ───────────────────────────────────────────────────────────
// `cover` is { weeks, provisional } or null (then `reason`); `flag` a reviewed
// warning about the count ({ label, detail }). The meter runs from 0 to
// utils/kpiMath.coverScale's end with a tick at the policy's weeks; the fill
// is solid up to the tick and lighter past it (the cover beyond the policy).
export const StockCoverCard = ({
  cover = null, reason = null, policyWeeks = null, flag = null, tooltip = null,
}) => {
  const ratio = cover ? policyRatio(cover.weeks, policyWeeks) : null;
  const scale = cover ? coverScale(cover.weeks, policyWeeks) : null;
  const fill = scale ? shareOf(cover.weeks, scale) : null;
  const mark = scale && ratio != null ? shareOf(policyWeeks, scale) : null;
  return (
    <KpiCard
      tone="teal"
      title="Stock cover"
      tooltip={tooltip}
      primary={(
        <>
          <p className="hero-value hero-value-tagged">
            <span>{cover ? `${cover.weeks.toFixed(1)} weeks` : '—'}</span>
            {cover?.provisional && <span className="hero-kpi-tag">Provisional</span>}
          </p>
          {!cover && reason && <p className="hero-kpi-sub">{reason}</p>}
          {fill != null && (
            <div className="hero-meter" style={mark != null ? { '--hero-mark': `${mark * 100}%` } : undefined}>
              <div
                className="hero-meter-track"
                role="img"
                aria-label={`${cover.weeks.toFixed(1)} weeks of stock cover on a scale of 0 to ${scale} weeks`
                  + `${mark != null ? `; the policy is ${policyWeeks} weeks` : ''}`}
              >
                <span className="hero-meter-fill" style={{ width: `${fill * 100}%` }} />
                {mark != null && (
                  <>
                    <span
                      className={`hero-meter-within${fill > mark ? ' is-cut' : ''}`}
                      style={{ width: `${Math.min(fill, mark) * 100}%` }}
                    />
                    <span className="hero-meter-mark" />
                  </>
                )}
              </div>
              <div className="hero-meter-axis" aria-hidden="true">
                <span>0</span>
                {mark != null && <span className="hero-meter-policy">Policy: {policyWeeks} weeks</span>}
                <span>{scale}</span>
              </div>
            </div>
          )}
        </>
      )}
      detail={ratio != null || flag ? (
        <div className="hero-pills">
          {ratio != null && (
            <span className="hero-pill is-info" title={`${cover.weeks} weeks of cover ÷ the ${policyWeeks}-week policy`}>
              {ratio.toFixed(1)}× policy
            </span>
          )}
          {flag && (
            <span className="hero-pill is-warning">
              <AlertTriangle size={12} aria-hidden="true" />
              <span>{flag.label}</span>
              {flag.detail && <InfoTip label={flag.label} size={11}>{flag.detail}</InfoTip>}
            </span>
          )}
        </div>
      ) : null}
      // Without a meter the policy is still said, as the old card's footer did.
      footer={mark == null && policyWeeks != null
        ? <span className="hero-kpi-foot-note">Policy: {policyWeeks} weeks</span> : null}
    />
  );
};

// ── Below safety stock ────────────────────────────────────────────────────
// `below` of the `checked` SKUs; null `below` (or nothing checked) is the
// blocked card, with `reason`. The bar is the same share the percentage prints.
export const BelowSafetyCard = ({
  below = null, checked = 0, severity = null, asOf = null, reason = null, tooltip = null, onOpen = null,
}) => {
  const share = below == null ? null : shareOf(below, checked);
  if (share == null) {
    return (
      <KpiCard
        tone="orange"
        title="Below safety stock"
        action
        primary={<KpiPrimary value="—" subtitle={reason} />}
      />
    );
  }
  return (
    <KpiCard
      tone="orange"
      title="Below safety stock"
      action
      split
      tooltip={tooltip}
      primary={(
        <KpiPrimary
          value={below.toLocaleString()}
          unit={`/ ${checked.toLocaleString()}`}
          severity={severity}
          subtitle={`Class A ${below === 1 ? 'SKU' : 'SKUs'} at risk`}
          asOf={asOf}
        />
      )}
      detail={(
        <>
          <p className="hero-kpi-figure">{formatPercent(share)}</p>
          <p className="hero-kpi-label">of the {checked.toLocaleString()} {checked === 1 ? 'SKU' : 'SKUs'} checked</p>
          <div
            className="hero-kpi-bar"
            role="img"
            aria-label={`${below} of ${checked} checked Class A SKUs are below safety stock (${formatPercent(share)})`}
          >
            {share > 0 && <span className="hero-kpi-bar-fill" style={{ width: `${share * 100}%` }} />}
          </div>
        </>
      )}
      footer={onOpen && below > 0 ? (
        <button type="button" className="hero-link" onClick={onOpen}>
          View {below.toLocaleString()} {below === 1 ? 'SKU' : 'SKUs'} <ArrowUpRight size={14} aria-hidden="true" />
        </button>
      ) : null}
    />
  );
};

// ── Pending reorders ──────────────────────────────────────────────────────
// `count` null is the card without LP access (`reason`). `parts` is
// utils/kpiMath.urgencyParts' split of the same pending rows, or null when
// there is nothing to split; `orderQty` the pieces those rows ask for.
export const PendingReordersCard = ({
  count = null, reason = null, asOf = null, parts = null, orderQty = null, tooltip = null, to = '/reorder',
}) => {
  if (count == null) {
    return (
      <KpiCard
        tone="purple"
        title="Pending reorders"
        action
        primary={<KpiPrimary value="—" subtitle={reason} />}
      />
    );
  }
  return (
    <KpiCard
      tone="purple"
      title="Pending reorders"
      action
      split
      tooltip={tooltip}
      primary={(
        <KpiPrimary
          value={count.toLocaleString()}
          subtitle={`${count === 1 ? 'SKU' : 'SKUs'} awaiting decision`}
          asOf={asOf}
        />
      )}
      detail={parts ? (
        <>
          <ul className="hero-kpi-legend">
            {parts.map((p) => (
              <li key={p.key} className={`is-${p.key}`}>
                <strong>{p.value.toLocaleString()}</strong>
                <span>{p.label}</span>
              </li>
            ))}
          </ul>
          <div
            className="hero-share-track"
            role="img"
            aria-label={`${count} pending SKUs by urgency: ${parts.map((p) => `${p.value} ${p.label.toLowerCase()}`).join(', ')}`}
          >
            {parts.filter((p) => p.value > 0).map((p) => (
              <span key={p.key} className={`hero-share-seg is-${p.key}`} style={{ flexGrow: p.value }} />
            ))}
          </div>
          {orderQty > 0 && <p className="hero-kpi-label">{orderQty.toLocaleString()} pcs to order</p>}
        </>
      ) : count === 0 ? <p className="hero-note">Nothing is awaiting a decision.</p> : null}
      footer={count > 0 ? (
        <Link to={to} className="hero-link">Review plan <ArrowUpRight size={14} aria-hidden="true" /></Link>
      ) : null}
    />
  );
};
