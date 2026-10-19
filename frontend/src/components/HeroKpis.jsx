// The dashboard's top row (2026-10-18 redesign, after Thea's mock-up): the
// annual sales card across the full width in two columns (Allocation |
// Progress so far, the latest month as one line at its foot; the monthly
// chart and the Latest month column came off 2026-10-18), then the four KPI
// cards in one row of
// equal columns. The bottom two (below safety stock, pending reorders) are
// operational and tinted, so the things to act on read apart from the rest.
//
// Presentation only. Every figure is one GET /dashboard already serves and
// Dashboard.jsx already reads; the arithmetic on them (a pace, a split, a
// ratio) is utils/kpiMath.js. Secondary detail lives in pop-ups (2026-10-18,
// "less crowded at 100%"): a worked-out number is itself the trigger
// (HoverValue: dotted underline, hover or tap) for its formula with the live
// values; a base figure opens its detail (NumLink: underlined on hover); each
// card keeps one "?" for its own explanation. A figure the backend does not
// send yet is "—" with the reason, never a made-up number: the same month a
// year earlier on the annual card, the reasons Class A products can't be
// checked, and the value of the pending orders (no cost data from SSM).
import React from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Check } from 'lucide-react';
import InfoTip from './InfoTip';
import BasisTag from './BasisTag';
import { formatCompactPesos } from './Charts';
import { formatMonth } from '../utils/formatDate';
import {
  allocationPace, classAChecks, coverScale, coverSplit, coverVerdict, excessAbovePolicy, formatCompactCount, formatPercent,
  policyRatio, shareOf,
} from '../utils/kpiMath';
import './HeroKpis.css';

const monthName = (period) => (period ? formatMonth(period).split(' ')[0] : null);
const signed = (pct) => `${pct >= 0 ? '+' : '−'}${Math.abs(pct).toFixed(1)}%`;
const fmtWeeks = (w) => `${Number(w).toFixed(1).replace(/\.0$/, '')} wks`;
const fp = formatCompactPesos;
const n = (v) => Number(v).toLocaleString();

// The month a year before the latest one ("vs Feb 2025") is not sent by GET
// /dashboard yet; the line stays hidden until it is (Thea, 2026-10-18).
const SHOW_LATEST_YEAR_AGO = false;

// The pending orders' value needs SSM's cost data; "est. —" stays hidden
// until it exists (Thea, 2026-10-18).
const SHOW_ORDER_VALUE = false;

// A rounded pill: icon + text, coloured by tone.
const Pill = ({ text, tone = 'neutral', icon: Icon = null }) => {
  if (!text) return null;
  return (
    <span className={`hero-pill is-${tone}`}>
      {Icon && <Icon size={12} aria-hidden="true" />}
      <span>{text}</span>
    </span>
  );
};

// A worked-out figure that opens its own explanation (InfoTip's `trigger`):
// on hover with a mouse, on tap on a touch screen, on Enter/Space from the
// keyboard. `what` says what the figure is, `sums` give the sum with the
// values on screen, `notes` anything else that used to sit on the card.
// `block` makes the trigger a whole row (a bar); `subtle` drops the dotted
// underline for a small inline count (the pop-up still opens), keeping the
// underline for the main numbers.
const HoverValue = ({ label, what = null, sums = [], notes = [], block = false, plain = false, subtle = false, children }) => (
  <InfoTip
    label={label}
    className={block ? 'hero-hover-wrap is-block' : 'hero-hover-wrap'}
    trigger={children}
    triggerClassName={`hero-hover${block ? ' is-block' : ''}${plain ? ' is-plain' : ''}${subtle ? ' is-subtle' : ''}`}
  >
    {what && <span className="hero-tip-line">{what}</span>}
    {sums.filter(Boolean).map((s) => <span key={s} className="hero-tip-line hero-tip-sum">{s}</span>)}
    {notes.filter(Boolean).map((s) => <span key={s} className="hero-tip-line">{s}</span>)}
  </InfoTip>
);

// A base figure that opens its detail: a route (`to`), or an action on this
// page (`onClick`: scroll to a chart, open a list). Without either it is
// plain text (no access, or nothing to open).
const NumLink = ({ to = null, onClick = null, title, children }) => {
  if (to) return <Link to={to} className="hero-num-link" title={title}>{children}</Link>;
  if (onClick) return <button type="button" className="hero-num-link" onClick={onClick} title={title}>{children}</button>;
  return <>{children}</>;
};

// A small header over each part of a card.
const SectionHead = ({ children }) => <p className="hero-section-head">{children}</p>;

// A card's "?" text: short paragraphs, the definition first. Elements, not
// a component, so InfoTip can measure the text and open a long one in its
// dialog (2026-10-19).
const tipLines = (lines) => lines.filter(Boolean).map((line) => <span key={line} className="hero-tip-line">{line}</span>);

// The card frame: top accent, coloured dot, title; on the right the period
// basis tag (when given, as a plain label: its explanation joins the card's
// "?") and the card's one "?". `action` cards get a tinted surface. The
// footer sits at the bottom of the card whatever its height.
export const KpiCard = ({
  tone, title, tooltip = null, basis = null, action = false, className = '', children, footer = null,
}) => {
  const lines = [...(tooltip || []), basis?.detail ? `Period: ${basis.detail}` : null].filter(Boolean);
  return (
    <section className={`hero-card is-${tone}${action ? ' is-action' : ''} ${className}`} aria-label={title}>
      <header className="hero-card-head">
        <span className="hero-card-name">
          <span className="hero-dot" aria-hidden="true" />
          <h3 className="hero-card-title">{title}</h3>
        </span>
        <span className="hero-card-side">
          {basis && <BasisTag label={basis.label} follows={basis.follows} />}
          {lines.length > 0 && (
            <InfoTip label={`About ${title}`} size={14}>{tipLines(lines)}</InfoTip>
          )}
        </span>
      </header>
      <div className="hero-card-body">{children}</div>
      {footer && <div className="hero-card-foot">{footer}</div>}
    </section>
  );
};

// ── Card 1: annual sales and the supplier allocation ──────────────────────
// `tooltip` is the sales basis sentence from Dashboard.jsx. `ytdSynthetic`,
// `allocSynthetic` and `latest.synthetic` name generated months beside the
// figure they are in (the Technical Adviser's rule).
// `onOpenYearly` scrolls to the Sales per year chart. `pct` / `onPctChange`:
// the SSM target picked (Dashboard.jsx holds it, so the Sales per year chart
// follows the same level); null means the allocation's default_pct.
export const AnnualSalesCard = ({
  allocation, yoy = null, latest = null, range = null, basis = null, tooltip = null,
  allocSynthetic = null, ytdSynthetic = null, onOpenYearly = null, pct: chosenPct = null, onPctChange = null,
}) => {
  const a = allocation || {};
  const levels = [...(a.levels || [])].sort((x, y) => x.pct - y.pct);
  const setChosenPct = (value) => onPctChange?.(value);
  const pct = chosenPct ?? a.default_pct ?? levels[0]?.pct ?? null;
  const level = levels.find((l) => l.pct === pct) || levels[0] || null;

  const year = a.allocation_year;
  const hasYtd = a.ytd_sales != null && a.ytd_months > 0;
  const lastName = monthName(a.latest_month);
  const span = a.ytd_months === 1 ? lastName : `Jan–${lastName}`;
  // The months the figure covers, and how many of them have sales on record
  // (Del Monte's 2025 has 6 of its 12): never "Jan–Dec" for a part year.
  const lastIndex = a.latest_month ? Number(a.latest_month.slice(5, 7)) : 0;
  const monthsLeft = 12 - lastIndex;
  const onRecord = a.ytd_months < lastIndex ? ` · ${a.ytd_months} of ${lastIndex} months on record` : '';
  const priorLabel = year && lastName ? `${span} ${year - 1}` : null;

  const target = level?.annual ?? null;
  const pace = hasYtd ? allocationPace({
    ytdSales: a.ytd_sales,
    ytdMonths: a.ytd_months,
    priorYtdSales: a.prior_ytd_sales,
    priorYtdMonths: a.prior_ytd_months,
    pct: level?.pct,
    target,
    monthsLeft,
  }) : null;
  const expected = pace?.expected ?? null;
  const behind = pace?.gap != null && pace.gap < 0;
  const yoyText = yoy?.pct != null ? `${signed(yoy.pct)} vs ${yoy.label}` : null;
  const yoySum = yoyText
    ? `${yoyText}: (${fp(a.ytd_sales)} − ${fp(a.prior_ytd_sales)}) ÷ ${fp(a.prior_ytd_sales)}` : null;
  const shareText = pace?.share != null ? formatPercent(Math.min(pace.share, 1)) : null;

  // The bar runs from ₱0 to the chosen annual target: what is sold, the
  // shortfall to "should be by now", and a tick there.
  const soldAt = target && hasYtd ? Math.min(a.ytd_sales / target, 1) : null;
  const expectedAt = target && expected != null ? Math.min(expected / target, 1) : null;

  // The same month a year earlier (GET /dashboard does not send it yet).
  const latestYearAgo = a.latest_month
    ? formatMonth(`${Number(a.latest_month.slice(0, 4)) - 1}-${a.latest_month.slice(5, 7)}`) : null;

  // The SSM target buttons, under the figure and FY sales (or the reason when
  // there is no figure).
  const levelButtons = levels.length > 0 ? (
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
  ) : null;
  const levelsBox = levelButtons ? (
    <div className="hero-alloc-levels-box">
      <p className="hero-label">SSM target</p>
      {levelButtons}
    </div>
  ) : null;

  const tips = [
    tooltip,
    'SSM\'s targets (client meeting, Sep 2026): the principal sets the year\'s allocation from the previous year\'s '
      + 'sales × 103% (minimum), 105% or 108% (maximum). Pick the one to compare against with the SSM target buttons.',
  ];

  return (
    <KpiCard tone="green" title="Annual sales and allocation" tooltip={tips} basis={basis} className="hero-card-wide">
      <div className="hero-annual-cols">
        {/* ── Allocation ── */}
        <div className="hero-annual-col">
          <SectionHead>Allocation</SectionHead>
          <p className="hero-label">Estimated{year ? `, FY ${year}` : ''}</p>
          {level ? (
            <>
              <p className="hero-value hero-value-xl">
                <HoverValue
                  label="How the allocation is worked out"
                  what={target
                    ? `FY ${a.basis_year} sales × the SSM target you picked.`
                    : `An average month of FY ${a.basis_year} sales × the SSM target you picked. FY ${a.basis_year} has `
                      + `${a.basis_months} of 12 months on record, so there is no yearly figure.`}
                  sums={[target
                    ? `${fp(a.basis_sales)} × ${level.pct}% = ${fp(target)}`
                    : `${fp(a.basis_sales)} ÷ ${a.basis_months} months × ${level.pct}% = ${fp(level.monthly)} a month`]}
                >
                  {target ? fp(target) : `${fp(level.monthly)}/month`}
                </HoverValue>
              </p>
              <p className="hero-kpi-asof">
                FY {a.basis_year} sales:{' '}
                <NumLink onClick={onOpenYearly} title="See sales per year"><strong>{fp(a.basis_sales)}</strong></NumLink>
                {a.basis_months < 12 ? ` (${a.basis_months} of 12 months on record)` : ''}
              </p>
            </>
          ) : (
            <p className="hero-note">{a.blocked_reason || 'The allocation is not available for this range.'}</p>
          )}
          {allocSynthetic && <p className="hero-note hero-synthetic">{allocSynthetic}</p>}
          {/* "SSM target" and its buttons, stacked under FY sales (2026-10-18). */}
          {levelsBox}
        </div>

        {/* ── Progress so far ── */}
        <div className="hero-annual-col">
          <SectionHead>Progress so far</SectionHead>
          {hasYtd ? (
            <>
              <p className="hero-label">FY {year} sales, {span}{onRecord}</p>
              <div className="hero-figure-row">
                <p className="hero-value">{fp(a.ytd_sales)}</p>
                {shareText && (
                  <p className="hero-figure-aside">
                    <HoverValue
                      label="How the share is worked out"
                      what={`FY ${year} sales so far ÷ the ${level.pct}% allocation.`}
                      sums={[`${fp(a.ytd_sales)} ÷ ${fp(target)} = ${shareText}`]}
                    >
                      {shareText}
                    </HoverValue>
                    {' '}of the allocation
                    {expected != null && (
                      <>
                        {' · '}should be{' '}
                        <HoverValue
                          label="How “should be by now” is worked out"
                          what={`Last year's sales for the same months × the SSM target, so it follows last year's pattern `
                            + `(a slow start in ${year - 1} lowers it too) rather than an even share of the year.`}
                          sums={[`${priorLabel} sales ${fp(a.prior_ytd_sales)} × ${level.pct}% = ${fp(expected)}`]}
                        >
                          {fp(expected)}
                        </HoverValue>
                        {' '}by now
                      </>
                    )}
                  </p>
                )}
              </div>
              {ytdSynthetic && <p className="hero-note hero-synthetic">{ytdSynthetic}</p>}

              {soldAt != null && (
                <div className="hero-progress">
                  <HoverValue
                    label="What the bar shows"
                    block
                    plain
                    notes={[
                      `Sold (blue): ${fp(a.ytd_sales)}`,
                      behind ? `Short (red): ${fp(Math.abs(pace.gap))}, up to "should be by now"` : null,
                      expectedAt != null ? `Should be by now (dashed tick): ${fp(expected)}` : null,
                      `End of the bar: the ${level.pct}% allocation, ${fp(target)}`,
                    ]}
                  >
                    <span className="hero-progress-track">
                      <span className="hero-progress-fill" style={{ width: `${soldAt * 100}%` }} />
                      {behind && expectedAt != null && (
                        <span
                          className="hero-progress-short"
                          style={{ left: `${soldAt * 100}%`, width: `${(expectedAt - soldAt) * 100}%` }}
                        />
                      )}
                      {expectedAt != null && <span className="hero-progress-pace" style={{ left: `${expectedAt * 100}%` }} />}
                    </span>
                  </HoverValue>
                  <div className="hero-progress-axis" aria-hidden="true">
                    <span>₱0</span>
                    <span>{fp(target)}</span>
                  </div>
                </div>
              )}

              <div className="hero-action-row">
                <div className="hero-pills">
                  {pace?.gap != null ? (
                    <HoverValue
                      label="How the gap is worked out"
                      plain
                      what="Should be by now − sales so far."
                      sums={[
                        `${fp(expected)} − ${fp(a.ytd_sales)} = ${behind ? '' : '−'}${fp(Math.abs(pace.gap))}`,
                        yoySum,
                      ]}
                    >
                      <Pill
                        text={`${behind ? 'Behind' : 'Ahead'} by ${fp(Math.abs(pace.gap))}`}
                        tone={behind ? 'negative' : 'positive'}
                        icon={behind ? AlertTriangle : Check}
                      />
                    </HoverValue>
                  ) : yoyText && (
                    <HoverValue label="How the change is worked out" plain what={`Sales so far against ${priorLabel}.`} sums={[yoySum]}>
                      <Pill text={yoyText} tone={yoy.pct >= 0 ? 'positive' : 'negative'} icon={yoy.pct >= 0 ? ArrowUpRight : ArrowDownRight} />
                    </HoverValue>
                  )}
                </div>

                {pace?.reached ? (
                  <p className="hero-sentence">The {level.pct}% allocation is already reached.</p>
                ) : pace?.perMonthNeeded != null && (
                  <p className="hero-sentence">
                    Need about{' '}
                    <HoverValue
                      label="How the amount per month is worked out"
                      what={`(Allocation − sales so far) ÷ the months left in ${year}.`}
                      sums={[`(${fp(target)} − ${fp(a.ytd_sales)}) ÷ ${monthsLeft} ${monthsLeft === 1 ? 'month' : 'months'} = ${fp(pace.perMonthNeeded)}`]}
                    >
                      <strong>{fp(pace.perMonthNeeded)} per month</strong>
                    </HoverValue>
                    {' '}for the rest of the year to reach the allocation.
                    {/* A yardstick for that figure (2026-10-19): last year's
                        average month, from the allocation's own base year. */}
                    {a.basis_sales > 0 && a.basis_months === 12 && (() => {
                      const avg = a.basis_sales / 12;
                      const diff = ((pace.perMonthNeeded - avg) / avg) * 100;
                      return (
                        <>
                          {' '}That is{' '}
                          <HoverValue
                            label="Against last year's average month"
                            what={`Last year's sales ÷ 12 months, against the amount needed per month.`}
                            sums={[`${fp(a.basis_sales)} ÷ 12 = ${fp(avg)} per month; ${fp(pace.perMonthNeeded)} is ${Math.abs(diff).toFixed(0)}% ${diff >= 0 ? 'above' : 'below'} it`]}
                          >
                            <strong>{Math.abs(diff).toFixed(0)}% {diff >= 0 ? 'above' : 'below'}</strong>
                          </HoverValue>
                          {' '}last year&apos;s average month ({fp(avg)}).
                        </>
                      );
                    })()}
                  </p>
                )}
              </div>
              {yoy?.note && <p className="hero-note">{yoy.note}</p>}
            </>
          ) : (
            // No sales yet in the year being planned (Del Monte: latest sales
            // Dec 2025, planning 2026): the selected range's sales instead.
            <>
              <p className="hero-label">{range?.label || 'Sales'}</p>
              <p className="hero-value">{range?.value ?? '—'}</p>
              {range?.synthetic && <p className="hero-note hero-synthetic">{range.synthetic}</p>}
              {year && <p className="hero-note">No FY {year} sales are on record yet.</p>}
            </>
          )}
          {/* The latest month with sales, the Progress column's last line,
              under "Need about ₱X per month". Without a figure it is left out:
              its reason (the allocation's blocked_reason) already shows in
              the Allocation column. */}
          {latest?.value && latest.value !== '—' && (
            <div className="hero-latest-line">
              <p>
                Latest month{latest.month ? ` (${latest.month})` : ''}:{' '}
                <HoverValue
                  label="About the latest month"
                  plain
                  what="Sales for the latest month with data. This updates when a new month's sales are uploaded."
                >
                  <Pill text={latest.value} tone="info" />
                </HoverValue>
                {SHOW_LATEST_YEAR_AGO && latestYearAgo && <span className="hero-latest-compare"> · vs {latestYearAgo}: —</span>}
              </p>
              {latest.synthetic && <p className="hero-note hero-synthetic">{latest.synthetic}</p>}
            </div>
          )}
          {latest?.blockedReason && latest.blockedReason !== a.blocked_reason && (
            <p className="hero-note">{latest.blockedReason}</p>
          )}
        </div>
      </div>
    </KpiCard>
  );
};

// ── Inventory value ───────────────────────────────────────────────────────
// `lastCount` / `yearAgo`: { value: '+6.7%' | null, tone, direction, sub,
// reason, now, then } from Dashboard.jsx (now/then are the two pesos figures
// compared). `idle`: { label, value, share, stock, note, reason }, value null
// (then `reason`) where idle stock can't be measured (Del Monte). `flag`:
// { label, detail } for a count the team judged unusual. `onOpenChart`
// scrolls to the Sales vs Inventory Value chart; `onOpenIdle` opens the
// no-sale list.
// `na` adds a small muted "n/a" beside a "—" (the "vs last count" box).
const CompareCell = ({ label, cell, na = false }) => {
  const Arrow = cell?.direction === 'up' ? ArrowUpRight : cell?.direction === 'down' ? ArrowDownRight : null;
  return (
    <div className="hero-compare-cell">
      <p className="hero-compare-label">{label}</p>
      {cell?.value ? (
        <p className={`hero-compare-value is-${cell.tone || 'neutral'}`}>
          <HoverValue
            label={`How “${label}” is worked out`}
            what={`(This count − the ${cell.sub || 'earlier count'}) ÷ the ${cell.sub || 'earlier count'}, both at last purchase price.`}
            sums={[cell.now != null && cell.then != null ? `(${fp(cell.now)} − ${fp(cell.then)}) ÷ ${fp(cell.then)} = ${cell.value}` : null]}
            notes={[cell.note]}
          >
            {Arrow && <Arrow size={14} aria-hidden="true" />}
            {cell.value}
          </HoverValue>
        </p>
      ) : (
        <p className="hero-compare-value is-missing">
          <HoverValue label={`Why “${label}” is not shown`} what={cell?.reason || 'Not available'}>—</HoverValue>
          {na && <span className="hero-compare-na">n/a</span>}
        </p>
      )}
    </div>
  );
};

export const InventoryCard = ({
  value, subtitle = null, subtitleTitle, asOf = null, flag = null, lastCount = null, yearAgo = null,
  idle = null, tooltip = null, onOpenChart = null, onOpenIdle = null,
}) => {
  const hasStock = value !== '—';
  // The no-sale list, the same one the slow-stock figure opens.
  const idleList = hasStock && idle?.value != null && onOpenIdle && idle.products > 0;
  return (
    <KpiCard
      tone="blue"
      title="Inventory value"
      tooltip={tooltip}
      footer={asOf || idleList ? (
        <>
          {asOf && <span className="hero-foot-note">{asOf}</span>}
          {idleList && (
            <button type="button" className="hero-link" onClick={onOpenIdle}>
              See the {n(idle.products)} {idle.products === 1 ? 'product' : 'products'} <ArrowUpRight size={14} aria-hidden="true" />
            </button>
          )}
        </>
      ) : null}
    >
      <SectionHead>Stock value</SectionHead>
      <div className="hero-value-tagged">
        <p className="hero-value">
          {hasStock ? <NumLink onClick={onOpenChart} title="See the inventory value chart">{value}</NumLink> : value}
        </p>
        {flag && (
          <HoverValue label={flag.label} plain what={flag.detail}>
            <Pill text={flag.label} tone="warning" icon={AlertTriangle} />
          </HoverValue>
        )}
      </div>
      {subtitle && <p className="hero-kpi-sub" title={subtitleTitle}>{subtitle}</p>}

      {hasStock && (
        <div className="hero-block">
          <SectionHead>Compared with</SectionHead>
          <div className="hero-compare">
            <CompareCell label="vs last count" cell={lastCount} na />
            <CompareCell label="vs a year ago" cell={yearAgo} />
          </div>
        </div>
      )}

      {hasStock && idle && (
        <div className="hero-block">
          <SectionHead>Slow stock</SectionHead>
          <p className="hero-idle-head">
            <span>{idle.label}</span>
            <strong>
              {idle.value != null ? (
                <>
                  <NumLink onClick={onOpenIdle} title="See the products with no sale">{fp(idle.value)}</NumLink>
                  {idle.share != null && (
                    <>
                      {' · '}
                      <HoverValue
                        label="How the slow-stock share is worked out"
                        what="Stock with no sale in the period ÷ the whole stock value, both at last purchase price, on the same count."
                        sums={[`${fp(idle.value)} ÷ ${fp(idle.stock)} = ${formatPercent(idle.share)}`]}
                      >
                        {formatPercent(idle.share)}
                      </HoverValue>
                    </>
                  )}
                </>
              ) : (
                <HoverValue label="Why slow stock is not shown" what={idle.reason || 'Not available'}>—</HoverValue>
              )}
            </strong>
          </p>
          {idle.share != null && (
            <HoverValue
              label="What the bar shows"
              block
              plain
              notes={[
                `The whole bar is the stock value, ${fp(idle.stock)}: moving stock on the left (blue).`,
                `Slow stock on the right (red): ${fp(idle.value)}, ${formatPercent(idle.share)}.`,
              ]}
            >
              <span className="hero-idle-track">
                <span className="hero-idle-slow" style={{ width: `${Math.max(idle.share * 100, 1)}%` }} />
              </span>
            </HoverValue>
          )}
          {idle.value != null && idle.note && <p className="hero-note">{idle.note}</p>}
        </div>
      )}
    </KpiCard>
  );
};

// ── Stock cover ───────────────────────────────────────────────────────────
// `cover` is { weeks, provisional, stockValue } or null (then `reason`). The
// bar runs from 0 to utils/kpiMath.coverScale's end: the weeks the policy
// needs, then the extra past it (or the shortfall, unfilled). `runningLow` is
// the below-safety-stock count, so the card can say when the totals hide a
// shortage (`onOpenLow` opens that list); `toConfirm` the open questions
// about the data, as served, behind the "Provisional" badge in the footer.
export const StockCoverCard = ({
  cover = null, reason = null, policyWeeks = null, salesWindow = null, runningLow = null, toConfirm = [],
  tooltip = null, onOpenLow = null,
  // The pesos beyond the rule product by product (GET /dashboard's
  // kpis.above_policy, 2026-10-19): { pesos, products, no_sale_products,
  // policy_weeks }, or null when the backend has no figure.
  abovePolicy = null,
}) => {
  const ratio = cover ? policyRatio(cover.weeks, policyWeeks) : null;
  const scale = cover ? coverScale(cover.weeks, policyWeeks) : null;
  const split = cover ? coverSplit(cover.weeks, policyWeeks) : null;
  const verdict = coverVerdict(ratio);
  const at = (w) => `${(shareOf(w, scale) ?? 0) * 100}%`;
  const confirm = (toConfirm || []).filter(Boolean);
  // Average weekly sales is not sent; it is the cover's own two figures worked
  // back (stock ÷ weeks), so it is shown as "≈".
  const weekly = cover?.stockValue != null && cover.weeks > 0 ? cover.stockValue / cover.weeks : null;
  // Money in stock past the policy's weeks. The backend's figure when it
  // sends one: product by product, each product's stock beyond the rule's
  // weeks of its own sales, added up — the sum its stock-detail list is
  // made of, so a reader can ask "which products?". Else the cover's own
  // figures rearranged (kpiMath.excessAbovePolicy), an aggregate that nets
  // products under the rule against those over it, so "≈" and lower.
  const excess = cover ? excessAbovePolicy(cover.stockValue, cover.weeks, policyWeeks) : null;
  const perProduct = cover && abovePolicy?.pesos != null ? abovePolicy : null;

  // One sentence: the total against the target, and the top sellers the total
  // can hide (cover is an average over every product).
  const low = runningLow > 0 ? (
    <>
      <NumLink onClick={onOpenLow} title="See the products below safety stock">
        <strong className="is-danger">{runningLow} top {runningLow === 1 ? 'product is' : 'products are'} running low</strong>
      </NumLink>.
    </>
  ) : null;
  const above = ratio != null && ratio > 1.1;
  const below = ratio != null && ratio < 0.9;
  const summary = ratio == null ? null
    : above ? (low ? <>Too much stock overall, but {low}</> : 'More stock than the target overall.')
      : below ? (low ? <>Less stock than the target overall, and {low}</> : 'Less stock than the target overall.')
        : (low ? <>On target overall, but {low}</> : 'On target overall.');

  return (
    <KpiCard
      tone="teal"
      title="Stock cover"
      tooltip={tooltip}
      footer={cover && confirm.length > 0 ? (
        <span className="hero-foot-badge">
          <HoverValue label="Why the figure is provisional" plain notes={confirm}>
            <span className="hero-kpi-tag">Provisional</span>
          </HoverValue>
          <span className="hero-foot-note">· {confirm.length} {confirm.length === 1 ? 'thing' : 'things'} to confirm</span>
        </span>
      ) : null}
    >
      <SectionHead>Weeks of stock</SectionHead>
      <div className="hero-value-tagged">
        <p className="hero-value">
          {cover ? (
            <HoverValue
              label="How the weeks are worked out"
              what={`Stock value ÷ average weekly sales${weekly != null ? '. The weekly figure is worked back from the two (stock ÷ weeks), so it is approximate.' : '.'}`}
              sums={[
                weekly != null ? `${fp(cover.stockValue)} ÷ ≈ ${fp(weekly)} per week = ${cover.weeks.toFixed(1)} weeks` : null,
                split && split.extra > 0 ? `Needed: min(${cover.weeks.toFixed(1)}, ${policyWeeks}) = ${fmtWeeks(split.needed)}; Extra: ${cover.weeks.toFixed(1)} − ${policyWeeks} = ${fmtWeeks(split.extra)}` : null,
                split && split.short > 0 ? `Have ${fmtWeeks(split.needed)}; Short: ${policyWeeks} − ${cover.weeks.toFixed(1)} = ${fmtWeeks(split.short)}` : null,
              ]}
              notes={[
                salesWindow ? `At the average selling speed, ${salesWindow}.` : null,
                split ? `On the bar: teal = ${split.extra > 0 ? 'needed' : 'have'} (${fmtWeeks(split.needed)})`
                  + `${split.extra > 0 ? `, amber = extra (${fmtWeeks(split.extra)})` : ''}`
                  + `${split.short > 0 ? `, grey = short (${fmtWeeks(split.short)})` : ''}; the tick is the ${policyWeeks}-week target.` : null,
              ]}
            >
              {cover.weeks.toFixed(1)} weeks
            </HoverValue>
          ) : '—'}
        </p>
        {verdict && (
          <HoverValue
            label="How the comparison is worked out"
            plain
            what={`Weeks of stock ÷ SSM's ${policyWeeks}-week policy (the target).`}
            sums={[`${cover.weeks.toFixed(2)} ÷ ${policyWeeks} = ${ratio.toFixed(2)}×`]}
          >
            <Pill text={verdict.text} tone={verdict.tone} />
          </HoverValue>
        )}
      </div>
      {!cover && reason && <p className="hero-kpi-sub">{reason}</p>}

      {split && scale && (
        <div className="hero-meter">
          <div
            className="hero-meter-track"
            role="img"
            aria-label={`${cover.weeks.toFixed(1)} weeks of stock cover against a ${policyWeeks}-week target, `
              + `on a scale of 0 to ${scale} weeks`}
          >
            <span className="hero-meter-needed" style={{ width: at(split.needed) }} />
            {split.extra > 0 && (
              <span className="hero-meter-extra" style={{ left: at(split.needed), width: at(split.extra) }} />
            )}
            <span className="hero-meter-mark" style={{ left: at(policyWeeks) }} />
          </div>
          <div className="hero-meter-axis" aria-hidden="true">
            <span>0 wks</span>
            <span className="hero-meter-policy" style={{ left: `max(${at(policyWeeks)}, 54px)` }}>Target {policyWeeks}</span>
            <span>{scale} wks</span>
          </div>
        </div>
      )}
      {cover && !split && policyWeeks != null && <p className="hero-note">Target: {policyWeeks} weeks</p>}

      {perProduct ? (
        <div className="hero-excess-row">
          <HoverValue
            label="How the money tied up is worked out"
            plain
            what={`Product by product: each product's stock value beyond ${perProduct.policy_weeks ?? policyWeeks} weeks of its own `
              + `average weekly sales${salesWindow ? ` (${salesWindow})` : ''}, added up over the ${n(perProduct.products)} products `
              + 'holding more than that.'}
            notes={[
              perProduct.no_sale_products > 0
                ? `${n(perProduct.no_sale_products)} products had no sale in those months, so all of their stock counts as beyond the rule.`
                : null,
              excess != null
                ? `The whole-stock shortcut (${fp(cover.stockValue)} × (${cover.weeks.toFixed(2)} − ${policyWeeks}) ÷ ${cover.weeks.toFixed(2)}) `
                  + `gives ≈ ${fp(excess)}: it nets products under the rule against those over it, so it reads lower.`
                : null,
              'Stock is at last purchase price and sales at selling price, so the figure is approximate.',
              cover.provisional || confirm.length > 0 ? `Provisional: ${confirm.join(' ')}` : null,
            ]}
          >
            <span className="hero-excess">
              Above SSM&apos;s {policyWeeks}-week rule: <strong>{fp(perProduct.pesos)}</strong> in {n(perProduct.products)} products
            </span>
          </HoverValue>
        </div>
      ) : excess != null && (
        <div className="hero-excess-row">
          <HoverValue
            label="How the money tied up is worked out"
            plain
            what={`Stock value beyond ${policyWeeks} weeks of sales: stock × (weeks − ${policyWeeks}) ÷ weeks, the same as `
              + `stock − ${policyWeeks} weeks × average weekly sales (worked back as stock ÷ weeks).`}
            sums={[`${fp(cover.stockValue)} × (${cover.weeks.toFixed(2)} − ${policyWeeks}) ÷ ${cover.weeks.toFixed(2)} ≈ ${fp(excess)}`]}
            notes={[
              'An estimate: stock is at last purchase price and sales at selling price, so the cover behind it is approximate.',
              cover.provisional || confirm.length > 0 ? `Provisional: ${confirm.join(' ')}` : null,
            ]}
          >
            <span className="hero-excess">
              Above SSM&apos;s {policyWeeks}-week rule: <strong>≈ {fp(excess)}</strong> tied up
            </span>
          </HoverValue>
        </div>
      )}

      {summary && <p className="hero-callout">{summary}</p>}
    </KpiCard>
  );
};

// ── Below safety stock ────────────────────────────────────────────────────
// `below` of the `checked` Class A products, of `total` in the plan; null
// `below` (or nothing checked) is the blocked card, with `reason`. Why the
// rest can't be checked, by reason (`uncheckable`: safety_stock_exposure's
// no_safety_stock / no_stock_count / missing_both, 2026-10-19), is in the
// "Can't check" pop-up; "—" when the backend sends no counts. `abcTo` links
// the Class A total to the ABC page (null without access).
const UNCHECKED_REASONS = [
  ['no_safety_stock', 'No safety stock in the plan'],
  ['no_stock_count', 'No stock count'],
  ['missing_both', 'Missing both'],
];

export const BelowSafetyCard = ({
  below = null, checked = 0, total = null, severity = null, asOf = null, reason = null, tooltip = null,
  onOpen = null, abcTo = null, uncheckable = null,
}) => {
  const share = below == null ? null : shareOf(below, checked);
  if (share == null) {
    return (
      <KpiCard tone="orange" title="Below safety stock" action>
        <SectionHead>Running low</SectionHead>
        <p className="hero-value">—</p>
        {reason && <p className="hero-kpi-sub">{reason}</p>}
      </KpiCard>
    );
  }
  const parts = classAChecks({ all: total, checked, below });
  const at = (k) => `${(shareOf(k, total) ?? 0) * 100}%`;
  return (
    <KpiCard
      tone="orange"
      title="Below safety stock"
      action
      tooltip={tooltip}
      footer={(
        <>
          {asOf && <span className="hero-foot-note">{asOf}</span>}
          <span className="hero-foot-links">
            {onOpen && below > 0 && (
              <button type="button" className="hero-link" onClick={onOpen}>
                See {below === 1 ? 'the product' : `the ${n(below)} products`} <ArrowUpRight size={14} aria-hidden="true" />
              </button>
            )}
            {abcTo && <Link to={abcTo} className="hero-link">Class A list <ArrowUpRight size={14} aria-hidden="true" /></Link>}
          </span>
        </>
      )}
    >
      <SectionHead>Running low</SectionHead>
      <p className="hero-value">
        <HoverValue
          label="How the count is worked out"
          what="Class A products whose stock is below their safety stock, out of those that can be checked (they have both a safety stock in the plan and a stock count)."
          sums={[`${n(below)} below safety stock, of ${n(checked)} checked = ${formatPercent(share)}`]}
        >
          <span className={severity ? `is-${severity}` : undefined}>{n(below)}</span>
        </HoverValue>
        <span className="hero-unit">of {n(checked)} checked</span>
      </p>

      {parts && (
        <div className="hero-block">
          <SectionHead>All Class A products</SectionHead>
          <p className="hero-idle-head">
            <span>In the plan</span>
            <strong><NumLink to={abcTo} title="See the ABC classification">{n(total)}</NumLink></strong>
          </p>
          <div
            className="hero-checks-track"
            role="img"
            aria-label={`${parts.below} running low, ${parts.ok} OK, ${parts.unchecked} can't be checked, of ${total} Class A products`}
          >
            {parts.below > 0 && <span className="hero-checks-seg is-low" style={{ width: at(parts.below) }} />}
            {parts.ok > 0 && <span className="hero-checks-seg is-ok" style={{ width: at(parts.ok) }} />}
          </div>
          <ul className="hero-legend">
            <li><span className="hero-swatch is-low" aria-hidden="true" />Running low {n(parts.below)}</li>
            <li>
              <span className="hero-swatch is-ok" aria-hidden="true" />
              <HoverValue label="How OK is worked out" subtle what="Checked − running low." sums={[`${n(checked)} − ${n(parts.below)} = ${n(parts.ok)}`]}>
                OK {n(parts.ok)}
              </HoverValue>
            </li>
            {parts.unchecked > 0 && (
              <li>
                <span className="hero-swatch is-unchecked" aria-hidden="true" />
                <HoverValue
                  label="Why these can't be checked"
                  subtle
                  what="All Class A products in the plan − checked."
                  sums={[`${n(total)} − ${n(checked)} = ${n(parts.unchecked)}`]}
                  notes={uncheckable
                    ? UNCHECKED_REASONS.map(([key, text]) => `${text}: ${n(uncheckable[key] ?? 0)}`)
                    : [
                      ...UNCHECKED_REASONS.map(([, text]) => `${text}: — (not available yet)`),
                      'The dashboard does not send the counts by reason yet.',
                    ]}
                >
                  Can&apos;t check {n(parts.unchecked)}
                </HoverValue>
              </li>
            )}
          </ul>
        </div>
      )}
    </KpiCard>
  );
};

// ── Pending reorders ──────────────────────────────────────────────────────
// `count` null is the card without LP access (`reason`). `parts` is
// utils/kpiMath.urgencyParts' split of the same pending rows, or null when
// there is nothing to split; `orderQty` the pieces those rows ask for (in the
// count's pop-up). The orders' value needs SSM's cost data, so it is "—"
// (`valueReason`, in its pop-up). `criticalTo` opens the Reorder page
// filtered to critical rows.
const URGENCY_ROWS = {
  critical: { name: 'critical', what: 'below safety stock', act: 'Act first' },
  urgent: { name: 'urgent', what: 'below target stock', act: 'Next' },
  planned: { name: 'routine', what: 'stock is fine', act: 'Can wait' },
  nodata: { name: 'no stock data', what: 'stock can\'t be read', act: 'Check the count' },
};

export const PendingReordersCard = ({
  count = null, reason = null, asOf = null, parts = null, orderQty = null, tooltip = null, to = '/reorder',
  criticalTo = null, valueReason = 'Waiting for SSM cost data',
  // Why the plan holds these products of all the top sellers (2026-10-19):
  // { total, evaluated, passed, failed, gate } from GET /dashboard's forecast
  // block. `criticalNote` says why Critical can exceed the Below safety
  // stock card's count. Either null leaves its line out.
  scope = null, criticalNote = null,
}) => {
  if (count == null) {
    return (
      <KpiCard tone="purple" title="Pending reorders" action>
        <SectionHead>Waiting for decision</SectionHead>
        <p className="hero-value">—</p>
        {reason && <p className="hero-kpi-sub">{reason}</p>}
      </KpiCard>
    );
  }
  const value = (key) => parts?.find((p) => p.key === key)?.value ?? 0;
  const routineSum = parts
    ? `${n(count)} − ${n(value('critical'))} critical − ${n(value('urgent'))} urgent`
      + `${value('nodata') > 0 ? ` − ${n(value('nodata'))} no stock data` : ''} = ${n(value('planned'))}`
    : null;
  return (
    <KpiCard
      tone="purple"
      title="Pending reorders"
      action
      tooltip={tooltip}
      footer={(
        <>
          {asOf && <span className="hero-foot-note">{asOf}</span>}
          {count > 0 && <Link to={to} className="hero-link">Review plan <ArrowUpRight size={14} aria-hidden="true" /></Link>}
        </>
      )}
    >
      <SectionHead>Waiting for decision</SectionHead>
      <p className="hero-value">
        {orderQty > 0 ? (
          <HoverValue
            label="Pieces to order"
            what={`${n(orderQty)} pieces in total (${formatCompactCount(orderQty)}).`}
            notes={['Each pending order\'s quantity, rounded up to a whole piece, then added up (the Reorder page\'s own total).']}
          >
            {n(count)}
          </HoverValue>
        ) : n(count)}
        <span className="hero-unit">
          {count === 1 ? 'product' : 'products'}
          {SHOW_ORDER_VALUE && (
            <>
              {' · est. '}
              <HoverValue label="Order value" what={`Order value: ${valueReason.charAt(0).toLowerCase()}${valueReason.slice(1)}.`}>—</HoverValue>
            </>
          )}
        </span>
      </p>

      {parts ? (
        <div className="hero-block">
          <SectionHead>By urgency</SectionHead>
          <ul className="hero-urgency">
            {parts.map((p) => {
              const row = URGENCY_ROWS[p.key];
              const label = <strong>{n(p.value)} {row.name}</strong>;
              return (
                <li key={p.key} className={`is-${p.key}`}>
                  <span>
                    {p.key === 'critical' && p.value > 0 ? <NumLink to={criticalTo} title="See the critical orders">{label}</NumLink>
                      : p.key === 'planned' ? (
                        <HoverValue label="How routine is worked out" subtle what="Pending orders that are not critical, urgent or without stock data." sums={[routineSum]}>
                          {label}
                        </HoverValue>
                      ) : label}
                    {' · '}{row.what}
                  </span>
                  <span className="hero-urgency-act">{row.act}</span>
                </li>
              );
            })}
          </ul>
          {criticalNote && <p className="hero-note">{criticalNote}</p>}
        </div>
      ) : count === 0 ? <p className="hero-note">Nothing is awaiting a decision.</p> : null}

      {scope && (
        <p className="hero-note">
          <HoverValue
            label="Why only these products are planned"
            subtle
            what={`Of the ${n(scope.total)} top sellers, ${n(scope.evaluated)} had enough history to test. ${n(scope.passed)} passed `
              + `the reliability check and are planned; ${n(scope.failed)} did not (their forecast was no better than last `
              + `month's number${scope.gate != null ? `: MASE ${scope.gate} or more` : ''}); ${n(scope.total - scope.evaluated)} `
              + `had too little history. The ${n(scope.total - scope.passed)} not planned stay on SSM's own rule.`}
          >
            Plans {n(scope.passed)} of {n(scope.total)} top sellers
          </HoverValue>
          {' · '}{n(scope.failed)} failed the reliability check, {n(scope.total - scope.evaluated)} too new to test
        </p>
      )}
    </KpiCard>
  );
};
