// The dashboard's top row (2026-10-10 redesign after the team's mock-up;
// 2026-10-18 rebuilt after Audrey's second mock-up and the Technical
// Adviser's reading of the page): one wide card on the left (annual sales
// against SSM's supplier allocation) and four cards in two rows on the right.
// Read left to right, top to bottom, the five cards are one argument:
//   sales are behind the allocation -> yet a lot of money sits in stock ->
//   about double SSM's 3-week rule -> but top sellers still run low ->
//   here is what to order, most urgent first.
// Every card ends in an action or a link, and every figure names its period.
//
// Presentation only. Every figure is one GET /dashboard already serves and
// Dashboard.jsx already computes (kpis, allocation, safety_stock_exposure,
// reorder_preview, idle_stock); the only arithmetic is utils/kpiMath.js's
// (a ratio, a share, a split, the sales expected by now from last year's
// pattern, what each remaining month must bring in), each stated in the
// card's "?" and tested. A figure that can't be formed is "—" with the
// reason, never a 0.
import React, { useState } from 'react';
import SectionLede from './ui/SectionLede';
import { Link } from 'react-router-dom';
import { ArrowDown, ArrowUp, ArrowUpRight, ArrowRight, Check, AlertTriangle } from 'lucide-react';
import InfoTip from './InfoTip';
import BasisTag from './BasisTag';
import { formatCompactPesos } from './Charts';
import { formatMonth } from '../utils/formatDate';
import {
  coverScale, expectedByNow, formatPercent, neededPerMonth, policyRatio, shareOf,
} from '../utils/kpiMath';
import './HeroKpis.css';

const monthName = (period) => (period ? formatMonth(period).split(' ')[0] : null);
const plural = (n, one, many) => (n === 1 ? one : many);

// A rounded change pill: arrow + text, coloured by direction (or tone).
const Pill = ({ text, direction, tone = 'neutral', icon = null, title }) => {
  if (!text) return null;
  const Icon = icon || (direction === 'up' ? ArrowUp : direction === 'down' ? ArrowDown : null);
  return (
    <span className={`hero-pill is-${tone}`} title={title}>
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

// One line under each card's title: what the reader learns from it
// (ui/SectionLede.jsx, 2026-10-16).
const HERO_LEDE = {
  'Annual sales and allocation': 'How the year is pacing against the target',
  'Inventory value': 'Money sitting on the shelves',
  'Stock cover': 'How long the stock will last',
  'Below safety stock': 'Class A products close to running out',
  'Pending reorders': 'Orders waiting for your decision',
};

// The card frame: top accent, coloured dot, title, the period basis tag.
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
    {HERO_LEDE[title] && <SectionLede className="hero-card-lede">{HERO_LEDE[title]}</SectionLede>}
    {children}
  </section>
);

// ── Card 1: annual sales and the supplier allocation ──────────────────────

const MONTH_INITIALS = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'];

// The year as a strip of twelve months (fills the card's lower half, so the
// tall card never ends in blank space): the months with sales as solid
// bars (GET /dashboard's allocation.trend, the latest twelve months with
// sales), the months still to come as outlined bars at what each must bring
// in to reach the target, and a dashed line at last year's average month.
// `lastIndex` is the last month already past (the months after it are
// still to come); `refLine` a dashed reference ({ value, label }).
const PaceStrip = ({ title, year, points, lastIndex = 0, needPerMonth = null, refLine = null }) => {
  const actual = new Map(
    (points || [])
      .filter((p) => String(p.period || '').startsWith(`${year}-`))
      .map((p) => [Number(String(p.period).slice(5, 7)), p.value]),
  );
  const cols = MONTH_INITIALS.map((initial, i) => {
    const m = i + 1;
    const label = formatMonth(`${year}-${String(m).padStart(2, '0')}`);
    if (m <= lastIndex) {
      const value = actual.get(m) ?? null;
      return value == null
        ? { m, initial, kind: 'none', value: null, title: `${label}: no sales on record` }
        : { m, initial, kind: 'actual', value, title: `${label}: ${formatCompactPesos(value)} sold` };
    }
    return needPerMonth != null
      ? { m, initial, kind: 'needed', value: needPerMonth, title: `${label}: about ${formatCompactPesos(needPerMonth)} needed` }
      : { m, initial, kind: 'none', value: null, title: label };
  });
  const max = Math.max(...cols.map((c) => c.value ?? 0), refLine?.value ?? 0, 1);
  const pct = (v) => `${Math.max((v / max) * 100, 2)}%`;
  const summary = cols.filter((c) => c.kind === 'actual').map((c) => c.title).join('; ');
  const missing = cols.filter((c) => c.kind === 'none' && c.m <= lastIndex).length;
  return (
    <div className="hero-pace">
      <div className="hero-pace-head">
        <span className="hero-label is-caps">{title}</span>
        <ul className="hero-pace-legend" aria-hidden="true">
          <li className="is-actual">Actual</li>
          {missing > 0 && <li className="is-none">No sales on record</li>}
          {needPerMonth != null && <li className="is-needed">Needed</li>}
          {refLine && <li className="is-avg">{refLine.label}</li>}
        </ul>
      </div>
      <div
        className="hero-pace-plot"
        role="img"
        aria-label={`${title}: ${summary}`
          + `${missing > 0 ? `; ${missing} ${plural(missing, 'month has', 'months have')} no sales on record` : ''}`
          + `${needPerMonth != null ? `; about ${formatCompactPesos(needPerMonth)} needed in each remaining month` : ''}`
          + `${refLine ? `; ${refLine.label}: ${formatCompactPesos(refLine.value)}` : ''}`}
      >
        <div className="hero-pace-bars">
          {refLine && (
            <span className="hero-pace-avg" style={{ bottom: pct(refLine.value) }}>
              <span className="hero-pace-avg-label">{formatCompactPesos(refLine.value)}</span>
            </span>
          )}
          {cols.map((c) => (
            <div key={c.m} className={`hero-pace-col is-${c.kind}`} title={c.title}>
              {c.value != null && <span className="hero-pace-bar" style={{ height: pct(c.value) }} />}
            </div>
          ))}
        </div>
        <div className="hero-pace-months" aria-hidden="true">
          {cols.map((c) => <span key={c.m}>{c.initial}</span>)}
        </div>
      </div>
    </div>
  );
};

export const AnnualSalesCard = ({
  allocation, yoy = null, latest = null, range = null, basis = null, tooltip = null,
  // "FY 2025 sales include synthetic months: …" when the target's basis does.
  allocSynthetic = null,
  // Stock cover ÷ SSM's rule and the rule's weeks, for the one sentence that
  // ties this card to the stock cards beside it.
  stockRatio = null, policyWeeks = null,
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
    : '';

  // The chosen level's annual target (a whole-year basis only).
  const target = level?.annual ?? null;
  const share = target && hasYtd ? a.ytd_sales / target : null;
  // Where sales should be by now: last year's own month-by-month pattern
  // (the same months' share of last year's sales, applied to the target);
  // an even twelfth a month when that pattern can't be read.
  const expected = target && hasYtd ? expectedByNow({
    target, priorYtd: a.prior_ytd_sales, basisSales: a.basis_sales,
    ytdMonths: a.ytd_months, priorMonths: a.prior_ytd_months, basisMonths: a.basis_months,
  }) : null;
  const evenPace = target && hasYtd && a.ytd_months < 12 ? target * (a.ytd_months / 12) : null;
  const byNow = expected ?? evenPace;
  const byNowRule = expected != null
    ? `Following FY ${a.basis_year}'s own month-by-month pattern: ${span} ${a.basis_year} brought in `
      + `${formatPercent(a.prior_ytd_sales / a.basis_sales)} of that year's sales, so the same share of the `
      + `${level.pct}% target is expected by ${lastName}.`
    : evenPace != null ? 'At an even pace: a twelfth of the target each month.' : null;
  const gap = byNow != null ? a.ytd_sales - byNow : null; // + ahead, − behind
  const behind = gap != null && gap < 0;
  const need = target && hasYtd ? neededPerMonth({ target, ytdSales: a.ytd_sales, ytdMonths: a.ytd_months }) : null;
  const yearDone = hasYtd && a.ytd_months >= 12;
  const lastYearAvg = a.basis_months === 12 && a.basis_sales != null ? a.basis_sales / 12 : null;
  const yoyText = yoy?.pct != null
    ? `${yoy.pct >= 0 ? '+' : '−'}${Math.abs(yoy.pct).toFixed(1)}% vs ${yoy.label}`
    : null;
  // Without a "by now" (no whole-year target): the older rule, average
  // monthly sales against the level's monthly figure.
  const avgMonthly = hasYtd ? a.ytd_sales / a.ytd_months : null;
  const onPace = level && avgMonthly != null ? avgMonthly >= level.monthly : null;

  const status = (() => {
    if (gap != null) {
      const text = `${behind ? 'Behind' : 'Ahead'} by ${formatCompactPesos(Math.abs(gap))}${yoyText ? ` · ${yoyText}` : ''}`;
      return { text, tone: behind ? 'warning' : 'positive', icon: behind ? AlertTriangle : Check };
    }
    if (onPace != null) {
      const text = `${onPace ? `On track for ${level.pct}%` : `Below the ${level.pct}% pace`}${yoyText ? ` · ${yoyText}` : ''}`;
      return { text, tone: onPace ? 'positive' : 'warning', icon: onPace ? Check : AlertTriangle };
    }
    if (yoyText) return { text: yoyText, tone: yoy.pct >= 0 ? 'positive' : 'negative', direction: yoy.pct >= 0 ? 'up' : 'down' };
    return null;
  })();
  const needLine = yearDone && share != null
    ? <>The year closed at <strong>{formatPercent(share)}</strong> of the allocation.</>
    : need != null && need > 0
      ? <>Need about <strong>{formatCompactPesos(need)} per month</strong> for the rest of the year to reach the allocation.</>
      : need === 0 ? <>The allocation is already reached.</> : null;
  // The one sentence that joins this card to the stock cards: sales and
  // stock read together, as the Technical Adviser reads the row.
  const stockNote = stockRatio == null || gap == null ? null
    : behind && stockRatio > 1.25 ? 'Sales are behind, so the extra stock is not from selling more than planned.'
      : !behind && stockRatio > 1.25 ? `Sales are ahead, yet stock is still above SSM's ${policyWeeks}-week rule.`
        : null;

  const fillPct = share != null ? Math.min(share, 1) * 100 : 0;
  const byNowPct = byNow != null && target ? Math.min(byNow / target, 1) * 100 : null;

  return (
    <HeroCard tone="green" title="Annual sales and allocation" tooltip={tooltip} basis={basis} className="hero-card-wide">
      {/* The allocation and the level it is set at. */}
      <div className="hero-alloc-top">
        <div className="hero-alloc-labels">
          <p className="hero-label">
            Estimated {target ? 'annual ' : ''}allocation{year ? `, FY ${year}` : ''}
            {level && (
              <InfoTip label="About the allocation" size={12}>
                SSM&apos;s rule (client meeting, Sep 2026): the principal sets the year&apos;s allocation from the
                previous year&apos;s sales × 103% (minimum), 105% or 108% (maximum). Which percentage applies
                each year is still a question for SSM, so this is an assumption.
                {a.basis_months < 12 ? ` FY ${a.basis_year} has ${a.basis_months} months on record, so only a monthly figure can be set.` : ''}
              </InfoTip>
            )}
          </p>
          {levels.length > 1 && <span className="hero-label">SSM target</span>}
        </div>
        <div className="hero-alloc-row">
          {level ? (
            <p className="hero-alloc-value">
              <span
                className="hero-dotted"
                title={`${level.pct}% × FY ${a.basis_year} sales of ${formatCompactPesos(a.basis_sales)}`
                  + `${a.basis_months < 12 ? ` (${a.basis_months} months on record, an average month)` : ''}`}
              >
                {target ? formatCompactPesos(target) : (
                  <>{formatCompactPesos(level.monthly)}<span className="hero-alloc-unit">/month</span></>
                )}
              </span>
            </p>
          ) : (
            <p className="hero-note">{a.blocked_reason || 'The allocation is not available for this range.'}</p>
          )}
          {levels.length > 1 && (
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
          )}
        </div>
        {level && (
          <p className="hero-note">
            FY {a.basis_year} sales: <strong>{formatCompactPesos(a.basis_sales)}</strong>
            {a.basis_months < 12 ? ` (${a.basis_months} of 12 months)` : ''}
          </p>
        )}
        {allocSynthetic && <p className="hero-note hero-synthetic">{allocSynthetic}</p>}
      </div>

      <div className="hero-rule" />

      {/* The year so far against that allocation. */}
      {hasYtd ? (
        <div className="hero-ytd">
          <p className="hero-label">FY {year} sales so far ({span}){ytdNote}</p>
          <div className="hero-ytd-row">
            <p className="hero-ytd-value">{formatCompactPesos(a.ytd_sales)}</p>
            {share != null && (
              <span className="hero-ytd-note">
                {formatPercent(share)} of the allocation
                {byNow != null && (
                  <>
                    {' · '}should be {formatCompactPesos(byNow)} by now
                    <InfoTip label="About where sales should be by now" size={12}>{byNowRule}</InfoTip>
                  </>
                )}
              </span>
            )}
          </div>
          {target && share != null && (
            <div className="hero-progress">
              <div
                className="hero-progress-track"
                role="img"
                aria-label={`${formatCompactPesos(a.ytd_sales)} sold of the ${level.pct}% allocation ${formatCompactPesos(target)}`
                  + `${byNow != null ? `; ${formatCompactPesos(byNow)} expected by ${lastName}` : ''}`}
              >
                <span className="hero-progress-fill" style={{ width: `${fillPct}%` }} />
                {behind && byNowPct != null && (
                  <span className="hero-progress-short" style={{ left: `${fillPct}%`, width: `${byNowPct - fillPct}%` }} />
                )}
                {byNowPct != null && <span className="hero-progress-pace" style={{ left: `${byNowPct}%` }} />}
              </div>
              <div className="hero-progress-ends" aria-hidden="true">
                <span>₱0</span>
                <span>{formatCompactPesos(target)}</span>
              </div>
              <ul className="hero-progress-legend" aria-hidden="true">
                <li className="is-sold">Sold</li>
                {behind && <li className="is-short">Short</li>}
                {byNowPct != null && <li className="is-pace">Should be by now</li>}
              </ul>
            </div>
          )}
          {status && (
            <div className="hero-pills">
              <Pill text={status.text} tone={status.tone} icon={status.icon} direction={status.direction} />
            </div>
          )}
          {yoy?.note && <p className="hero-note">{yoy.note}</p>}
          {needLine && <p className="hero-need">{needLine}</p>}
        </div>
      ) : (
        <div className="hero-ytd">
          <p className="hero-label">{range?.label || 'Sales'}</p>
          <div className="hero-ytd-row">
            <p className="hero-ytd-value">{range?.value ?? '—'}</p>
          </div>
          <div className="hero-pills"><ComparePill extras={range?.change} /></div>
          {range?.synthetic && <p className="hero-note hero-synthetic">{range.synthetic}</p>}
          {yoy?.note && <p className="hero-note">{yoy.note}</p>}
        </div>
      )}

      {stockNote && (
        <p className="hero-connector">
          <ArrowRight size={14} aria-hidden="true" />
          <span>{stockNote}</span>
        </p>
      )}

      {/* The year month by month (fills the card's lower half). With sales
          in the planned year: its months so far, what each remaining month
          needs, and last year's average month. Without any (Del Monte plans
          2026 on 2025's months): last year's months, the ones SSM did not
          collect hatched, against the monthly allocation. */}
      {hasYtd && target ? (
        <PaceStrip
          title={`Monthly pace, FY ${year}`}
          year={year}
          points={a.trend?.points}
          lastIndex={lastIndex}
          needPerMonth={need != null && need > 0 ? need : null}
          refLine={lastYearAvg != null ? { value: lastYearAvg, label: `FY ${a.basis_year} average month` } : null}
        />
      ) : !hasYtd && level && a.basis_year ? (
        <PaceStrip
          title={`Monthly sales, FY ${a.basis_year}${a.basis_months < 12 ? ` (${a.basis_months} of 12 months on record)` : ''}`}
          year={a.basis_year}
          points={a.trend?.points}
          lastIndex={12}
          refLine={level.monthly != null ? { value: level.monthly, label: `FY ${year} allocation, per month` } : null}
        />
      ) : null}

      {/* The selected range's own total, and the latest month, each against
          the page's "Compare with". */}
      <div className="hero-foot-rows">
        {hasYtd && range?.short && (
          <div className="hero-foot-row">
            <span>Selected range: <strong>{range.short}</strong></span>
            <ComparePill extras={range.change} />
            {range.synthetic && <span className="hero-synthetic">{range.synthetic}</span>}
          </div>
        )}
        <div className="hero-foot-row">
          <span>Latest month{latest?.month ? ` (${latest.month})` : ''}: <strong>{latest?.value ?? '—'}</strong></span>
          <ComparePill extras={latest?.change} />
          {latest?.synthetic && <span className="hero-synthetic">{latest.synthetic}</span>}
          {latest?.blockedReason && <span className="hero-note">{latest.blockedReason}</span>}
        </div>
      </div>
    </HeroCard>
  );
};

// ── The four KPI cards ────────────────────────────────────────────────────
// One skeleton for all four: head / body (the figure, then what supports
// it) / a footer pinned to the bottom with the date and the way to the
// detail, so the four cards' footers line up whatever each one holds.

// A card's "?" text: short paragraphs, the definition first.
const TipText = ({ lines }) => (
  <>
    {lines.filter(Boolean).map((line) => <span key={line} className="hero-tip-line">{line}</span>)}
  </>
);

export const KpiCard = ({
  tone, title, tooltip = null, action = false, primary, detail = null, footer = null,
}) => (
  <section className={`hero-card hero-kpi is-${tone}${action ? ' is-action' : ''}`} aria-label={title}>
    <header className="hero-kpi-head">
      <span className="hero-card-name">
        <span className="hero-dot" aria-hidden="true" />
        <h3 className="hero-card-title">{title}</h3>
      </span>
      {tooltip?.some(Boolean) && (
        <InfoTip label={`About ${title}`} size={14}><TipText lines={tooltip} /></InfoTip>
      )}
    </header>
    {HERO_LEDE[title] && <SectionLede className="hero-card-lede">{HERO_LEDE[title]}</SectionLede>}
    <div className="hero-kpi-body">
      <div className="hero-kpi-primary">{primary}</div>
      {detail && <div className="hero-kpi-detail">{detail}</div>}
    </div>
    {footer && <div className="hero-kpi-foot">{footer}</div>}
  </section>
);

// The big figure and its two lines: what it counts, and the date it is for.
const KpiPrimary = ({ value, unit = null, severity = null, subtitle = null, subtitleTitle }) => (
  <>
    <p className="hero-value">
      <span className={severity ? `is-${severity}` : undefined}>{value}</span>
      {unit && <span className="hero-unit">{unit}</span>}
    </p>
    {subtitle && <p className="hero-kpi-sub" title={subtitleTitle}>{subtitle}</p>}
  </>
);

// A reviewed warning about a count ({ label, detail }) beside a figure.
const FlagPill = ({ flag }) => (
  <span className="hero-pill is-warning">
    <AlertTriangle size={12} aria-hidden="true" />
    <span>{flag.label}</span>
    {flag.detail && <InfoTip label={flag.label} size={11}>{flag.detail}</InfoTip>}
  </span>
);

// A small comparison tile: its label, then the pill (or the reason there is
// no comparison).
const Tile = ({ label, extras, none = 'Not compared' }) => (
  <div className="hero-tile">
    <span className="hero-tile-label">{label}</span>
    {extras?.deltaLine ? <ComparePill extras={extras} /> : <span className="hero-tile-none">{none}</span>}
  </div>
);

// ── Inventory value ───────────────────────────────────────────────────────
// `lastCount` and `yearAgo` are Dashboard.jsx's pill extras; `excess` the
// stock held beyond SSM's rule ({ pesos, policyWeeks, provisional });
// `idle` the stock with no sale in the window ({ pesos, products, share,
// windowMonths, onOpen }).
export const InventoryCard = ({
  value, reason = null, pieces = null, piecesTitle, basisText = 'at last purchase price', asOf = null,
  flag = null, lastCount = null, yearAgo = null, yearAgoLabel = 'vs a year ago', excess = null, idle = null,
  tooltip = null, onOpenList = null, productCount = null,
}) => {
  const blocked = value === '—';
  return (
    <KpiCard
      tone="blue"
      title="Inventory value"
      tooltip={tooltip}
      primary={(
        <>
          <p className="hero-value hero-value-tagged">
            <span>{value}</span>
            {!blocked && flag && <FlagPill flag={flag} />}
          </p>
          <p className="hero-kpi-sub" title={piecesTitle}>
            {blocked ? reason : [pieces, basisText].filter(Boolean).join(' · ')}
          </p>
        </>
      )}
      detail={blocked ? null : (
        <>
          {(lastCount || yearAgo) && (
            <div className="hero-tiles">
              <Tile label="vs last count" extras={lastCount} none={lastCount === null ? 'No earlier count' : 'Not compared'} />
              <Tile label={yearAgoLabel} extras={yearAgo} none="No comparison chosen" />
            </div>
          )}
          {excess && excess.pesos != null && (
            <div className="hero-excess">
              <span className="hero-excess-label">
                Above SSM&apos;s {excess.policyWeeks}-week rule
                <InfoTip label="About the stock above SSM's rule" size={11}>
                  Product by product: each product&apos;s stock beyond {excess.policyWeeks} weeks of its own average sales,
                  added up (a product that sold nothing in the 12 months counts in full). A product holding less than{' '}
                  {excess.policyWeeks} weeks does not make up for another holding more, so this is more than the overall
                  gap on the Stock cover card. {excess.provisional ? 'Provisional while the cover is.' : ''}
                </InfoTip>
              </span>
              <span className="hero-excess-value">{excess.pesos > 0 ? formatCompactPesos(excess.pesos) : 'None'}</span>
              <span className="hero-excess-sub">
                {excess.pesos > 0 ? 'money tied up beyond the rule' : 'stock is within the rule'}
                {excess.provisional ? ' · provisional' : ''}
                {excess.onOpen && excess.products > 0 && (
                  <>
                    {' · '}
                    <button type="button" className="hero-inline-link" onClick={excess.onOpen}>
                      {excess.products.toLocaleString()} products <ArrowUpRight size={12} aria-hidden="true" />
                    </button>
                  </>
                )}
              </span>
            </div>
          )}
          {idle && idle.pesos != null && (
            <div className="hero-idle">
              <div className="hero-idle-head">
                <span>
                  Not sold in {idle.windowMonths} months
                  {idle.onOpen && idle.products > 0 && (
                    <>
                      {' · '}
                      <button type="button" className="hero-inline-link" onClick={idle.onOpen}>
                        {idle.products.toLocaleString()} products <ArrowUpRight size={12} aria-hidden="true" />
                      </button>
                    </>
                  )}
                </span>
                <strong>{formatCompactPesos(idle.pesos)}{idle.share != null ? ` · ${formatPercent(idle.share)}` : ''}</strong>
              </div>
              <div
                className="hero-idle-track"
                role="img"
                aria-label={`${formatCompactPesos(idle.pesos)} of this stock, ${formatPercent(idle.share)}, had no sale in ${idle.windowMonths} months`}
              >
                <span className="hero-idle-moving" style={{ flexGrow: Math.max(1 - (idle.share ?? 0), 0) }} />
                {idle.share > 0 && <span className="hero-idle-slow" style={{ flexGrow: idle.share }} />}
              </div>
              <div className="hero-idle-axis" aria-hidden="true">
                <span>Moving stock</span>
                <span>Slow stock</span>
              </div>
            </div>
          )}
        </>
      )}
      footer={blocked ? null : (
        <>
          {asOf && <span className="hero-kpi-foot-note">{asOf}</span>}
          {onOpenList && (
            <button type="button" className="hero-link" onClick={onOpenList}>
              {productCount ? `All ${productCount.toLocaleString()} products` : 'By product'} <ArrowUpRight size={14} aria-hidden="true" />
            </button>
          )}
        </>
      )}
    />
  );
};

// ── Stock cover ───────────────────────────────────────────────────────────
// `cover` is { weeks, provisional } or null (then `reason`). The meter runs
// from 0 to utils/kpiMath.coverScale's end: teal up to SSM's rule, amber
// past it. `confirm` lists what is still to be confirmed about the figure;
// `below` is the below-safety-stock count (null when it can't be formed).
export const StockCoverCard = ({
  cover = null, reason = null, policyWeeks = null, window = null, confirm = [], monthsNote = null,
  below = null, onOpenBelow = null, tooltip = null, onOpenList = null,
}) => {
  const ratio = cover ? policyRatio(cover.weeks, policyWeeks) : null;
  const scale = cover ? coverScale(cover.weeks, policyWeeks) : null;
  const fill = scale ? shareOf(cover.weeks, scale) : null;
  const mark = scale && ratio != null ? shareOf(policyWeeks, scale) : null;
  const extraWeeks = ratio != null && ratio > 1 ? cover.weeks - policyWeeks : null;
  const rule = `SSM's ${policyWeeks}-week rule`;
  const verdict = ratio == null ? null
    : ratio >= 1.75 && ratio < 2.25 ? { text: `About double ${rule}`, tone: 'warning' }
      : ratio >= 2.75 && ratio < 3.25 ? { text: `About triple ${rule}`, tone: 'warning' }
        : ratio > 1.25 ? { text: `${ratio.toFixed(1)}× ${rule}`, tone: 'warning' }
          : ratio < 0.9 ? { text: `Below ${rule}`, tone: 'negative' }
            : { text: `About ${rule}`, tone: 'positive' };
  const lowText = below != null && below > 0
    ? `${below} top ${plural(below, 'product is', 'products are')} running low`
    : null;
  const lowPart = lowText && (onOpenBelow
    ? <button type="button" className="hero-story-link" onClick={onOpenBelow}>{lowText}</button>
    : <strong className="hero-story-strong">{lowText}</strong>);
  const story = ratio == null ? null
    : ratio > 1.25
      ? (lowPart ? <>Too much stock overall, but {lowPart}.</>
        : below === 0 ? <>Too much stock overall, and no top product is running low.</>
          : <>More stock than the rule overall.</>)
      : ratio < 0.9
        ? (lowPart ? <>Less stock than the rule overall, and {lowPart}.</> : <>Less stock than the rule overall.</>)
        : (lowPart ? <>Stock is about the rule overall, but {lowPart}.</> : null);
  const toConfirm = (confirm || []).filter(Boolean);
  return (
    <KpiCard
      tone="teal"
      title="Stock cover"
      tooltip={tooltip}
      primary={(
        <>
          <p className="hero-value hero-value-tagged">
            <span>{cover ? `${cover.weeks.toFixed(1)} weeks` : '—'}</span>
            {verdict && <Pill text={verdict.text} tone={verdict.tone} />}
          </p>
          <p className="hero-kpi-sub">
            {!cover ? reason : `At the average selling speed${window ? `, ${window}` : ''}`}
          </p>
        </>
      )}
      detail={fill != null ? (
        <>
          <div className="hero-meter" style={mark != null ? { '--hero-mark': `${mark * 100}%` } : undefined}>
            <div
              className="hero-meter-track"
              role="img"
              aria-label={`${cover.weeks.toFixed(1)} weeks of stock cover on a scale of 0 to ${scale} weeks`
                + `${mark != null ? `; SSM's rule is ${policyWeeks} weeks` : ''}`}
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
              <span>0 wks</span>
              {mark != null && <span className="hero-meter-policy">Rule: {policyWeeks} wks</span>}
              <span>{scale} wks</span>
            </div>
            {mark != null && (
              <ul className="hero-meter-legend" aria-hidden="true">
                <li className="is-within">Needed ({policyWeeks} wks)</li>
                {extraWeeks != null && <li className="is-beyond">Extra ({extraWeeks.toFixed(1)} wks)</li>}
              </ul>
            )}
          </div>
          {story && <p className="hero-story">{story}</p>}
          {monthsNote && <p className="hero-kpi-note">{monthsNote}</p>}
        </>
      ) : null}
      footer={cover && (toConfirm.length > 0 || cover.provisional || onOpenList) ? (
        <>
        {(toConfirm.length > 0 || cover.provisional) && <div className="hero-confirm">
          <div className="hero-confirm-head">
            <span className="hero-kpi-tag">Provisional</span>
            <span>
              {toConfirm.length > 0
                ? `${toConfirm.length} ${plural(toConfirm.length, 'thing', 'things')} to confirm`
                : 'Not a final figure'}
            </span>
          </div>
          {toConfirm.length > 0 && <ul>{toConfirm.map((t) => <li key={t}>{t}</li>)}</ul>}
        </div>}
        {onOpenList && (
          <button type="button" className="hero-link hero-link-end" onClick={onOpenList}>
            Cover by product <ArrowUpRight size={14} aria-hidden="true" />
          </button>
        )}
        </>
      ) : !cover && policyWeeks != null ? <span className="hero-kpi-foot-note">SSM&apos;s rule: {policyWeeks} weeks</span> : null}
    />
  );
};

// ── Below safety stock ────────────────────────────────────────────────────
// `below` of the `checked` Class A SKUs, out of `tierA` in the class; null
// `below` (or nothing checked) is the blocked card, with `reason`.
export const BelowSafetyCard = ({
  below = null, checked = 0, tierA = null, tierLabel = null, units = 'products', severity = null,
  asOf = null, reason = null, tooltip = null, onOpen = null, classLink = null, uncheckable = null,
  onOpenUnchecked = null,
}) => {
  const share = below == null ? null : shareOf(below, checked);
  if (share == null) {
    return (
      <KpiCard
        tone="orange"
        title="Below safety stock"
        action
        primary={<KpiPrimary value="—" subtitle={reason} />}
        footer={classLink ? (
          <Link to={classLink} className="hero-link">Class A list <ArrowUpRight size={14} aria-hidden="true" /></Link>
        ) : null}
      />
    );
  }
  const ok = Math.max(checked - below, 0);
  const unchecked = tierA != null ? Math.max(tierA - checked, 0) : null;
  const whole = tierA ?? checked;
  return (
    <KpiCard
      tone="orange"
      title="Below safety stock"
      action
      tooltip={tooltip}
      primary={(
        <KpiPrimary
          value={below.toLocaleString()}
          unit={`of ${checked.toLocaleString()} checked`}
          severity={severity}
          subtitle={below > 0 ? 'Order these first.' : 'None are below their safety stock.'}
        />
      )}
      detail={(
        <div className="hero-classa">
          <div className="hero-classa-head">
            <span>All Class A {units}{tierLabel ? ` (${tierLabel})` : ''}</span>
            <strong>{whole.toLocaleString()}</strong>
          </div>
          <div
            className="hero-share-track"
            role="img"
            aria-label={`Of ${whole} Class A ${units}: ${below} running low, ${ok} OK`
              + `${unchecked ? `, ${unchecked} can't be checked` : ''}`}
          >
            {below > 0 && <span className="hero-share-seg is-low" style={{ flexGrow: below }} />}
            {ok > 0 && <span className="hero-share-seg is-ok" style={{ flexGrow: ok }} />}
            {unchecked > 0 && <span className="hero-share-seg is-cant" style={{ flexGrow: unchecked }} />}
          </div>
          <ul className="hero-share-legend" aria-hidden="true">
            <li className="is-low">Running low {below.toLocaleString()}</li>
            <li className="is-ok">OK {ok.toLocaleString()}</li>
            {unchecked > 0 && <li className="is-cant">Can&apos;t check {unchecked.toLocaleString()}</li>}
          </ul>
          {unchecked > 0 && (uncheckable ? (
            // GET /dashboard's safety_stock_exposure.uncheckable: each row
            // counted once, by what it lacks (2026-10-18).
            <div className="hero-kpi-note hero-why">
              <span className="hero-why-title">
                Why {unchecked.toLocaleString()} can&apos;t be checked
                {onOpenUnchecked && (
                  <button type="button" className="hero-inline-link" onClick={onOpenUnchecked}>
                    See them <ArrowUpRight size={12} aria-hidden="true" />
                  </button>
                )}
              </span>
              <ul>
                {[
                  ['No safety stock in the plan', uncheckable.no_safety_stock],
                  ['No stock count', uncheckable.no_stock_count],
                  ['Missing both', uncheckable.missing_both],
                ].filter(([, n]) => n > 0).map(([label, n]) => (
                  <li key={label}><span>{label}</span><strong>{n.toLocaleString()}</strong></li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="hero-kpi-note">
              Why {unchecked.toLocaleString()} can&apos;t be checked: no safety stock in the plan, or no stock count.
              They are left out of both numbers.
            </p>
          ))}
        </div>
      )}
      footer={(
        <>
          {asOf && <span className="hero-kpi-foot-note">{asOf}</span>}
          <span className="hero-links">
            {onOpen && below > 0 && (
              <button type="button" className="hero-link" onClick={onOpen}>
                See the {below.toLocaleString()} <ArrowUpRight size={14} aria-hidden="true" />
              </button>
            )}
            {classLink && (
              <Link to={classLink} className="hero-link">Class A list <ArrowUpRight size={14} aria-hidden="true" /></Link>
            )}
          </span>
        </>
      )}
    />
  );
};

// ── Pending reorders ──────────────────────────────────────────────────────
// `count` null is the card without LP access (`reason`). `parts` is
// utils/kpiMath.urgencyParts' split of the same pending rows, or null when
// there is nothing to split; `orderQty` the pieces those rows ask for.
const QUEUE = {
  critical: { what: 'below safety stock', when: 'Order now' },
  urgent: { what: 'below target stock', when: 'This week' },
  planned: { what: 'stock is fine', when: 'Can wait' },
  nodata: { what: 'no stock figure', when: 'Check first' },
};

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
  const critical = parts?.find((p) => p.key === 'critical')?.value ?? 0;
  return (
    <KpiCard
      tone="purple"
      title="Pending reorders"
      action
      tooltip={tooltip}
      primary={(
        <KpiPrimary
          value={count.toLocaleString()}
          unit={plural(count, 'product', 'products')}
          subtitle={count === 0 ? 'Nothing is waiting for a decision.'
            : orderQty > 0 ? `${orderQty.toLocaleString()} pieces to order in all` : 'Waiting for a decision'}
        />
      )}
      detail={parts ? (
        <>
          <ul className="hero-queue">
            {parts.map((p) => (
              <li key={p.key} className={`is-${p.key}${p.value === 0 ? ' is-zero' : ''}`}>
                <span className="hero-queue-count"><strong>{p.value.toLocaleString()}</strong> {p.label.toLowerCase()}</span>
                <span className="hero-queue-what">· {QUEUE[p.key]?.what}</span>
                <span className="hero-queue-when">{QUEUE[p.key]?.when}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      footer={(
        <>
          {asOf && <span className="hero-kpi-foot-note">{asOf}</span>}
          {count > 0 && (
            <Link to={critical > 0 ? `${to}?urgency=critical` : to} className="hero-link">
              {critical > 0 ? `Review the ${critical.toLocaleString()} critical` : 'Open the plan'}
              {' '}<ArrowUpRight size={14} aria-hidden="true" />
            </Link>
          )}
        </>
      )}
    />
  );
};
