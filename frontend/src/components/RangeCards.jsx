// Dashboard cards on the data marts' range answers (DEC-36, 2026-10-04/05):
// idle stock, the forecast's miss against sales, and the products that
// entered or left Class A. Each figure states its period and its basis, and
// the products behind it are one click away (Technical Adviser, 2 Oct 2026:
// detail behind every aggregate). The figures are GET /dashboard's (or the
// range route's) as served; nothing here recomputes one.
import React, { useEffect, useState } from 'react';
import SectionLede from './ui/SectionLede';
import { AlertTriangle, ArrowDown, ArrowRight, ArrowUp, X } from 'lucide-react';
import {
  Area, Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import Modal from './Modal';
import ProductName from './ProductName';
import InfoTip from './InfoTip';
import { ClassBadge } from './ui/StatusBadge';
import MonthTick, { MONTH_TICK_EXTRA_HEIGHT, monthName } from './MonthTick';
import { ChartTable, ChartViewToggle } from './ChartTable';
import { GRID_PROPS } from './ChartZoom';
import { pesoTicks } from '../utils/pesoTicks';
import { categoryLabel } from '../utils/categoryLabel';
import { MISS_STATUS_LABEL, missStatus } from '../utils/forecastHighlights';
import { BAR_FADE_FLOOR, Fade, endDot } from './ui/ChartParts';
import { getForecastAccuracy } from '../api/dashboard';
import { CALENDAR_HISTORY_NOTE, CALENDAR_METHOD_FALLBACK, calendarSignoffText } from '../utils/calendarAdjustment';
import { CHART_COLORS, COLORS } from '../theme/colors';
import { formatCompactPesos, isMissing, NOT_COLLECTED } from '../utils/formatters';
import { formatUnits } from '../utils/formatNumber';
import { formatCount, missShare } from '../utils/missTotals';
import { formatDate, formatMonth } from '../utils/formatDate';
import './AtRiskProductsModal.css';
import './PendingCards.css';
import './RangeCards.css';

const pct = (share) => (share == null ? '—' : `${(share * 100).toFixed(1)}%`);
// A missing change (null) prints the not-collected marker, never ₱0 (audit FE-4).
const signedPesos = (value) => (isMissing(value) ? NOT_COLLECTED : `${value >= 0 ? '+' : '−'}${formatCompactPesos(Math.abs(value))}`);

// A product list behind a card's figure, in the at-risk list's frame.
// columns: [{ key, label, sub, render(row) }]; the first column is the product.
export const ProductListModal = ({
  isOpen, onClose, title, lede, subtitle, columns, rows, loading, error, footnote, onOpenProduct, openLabel,
  firstColumnLabel = 'Product',
}) => {
  if (!isOpen) return null;
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      labelledBy="range-list-title"
      overlayClassName="at-risk-overlay"
      containerClassName="at-risk-card"
    >
      <div className="at-risk-header">
        <div>
          <h3 id="range-list-title" className="at-risk-title">{title}</h3>
          {lede && <SectionLede>{lede}</SectionLede>}
          {subtitle && <p className="at-risk-subtitle">{subtitle}</p>}
        </div>
        <button type="button" className="at-risk-close" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
      </div>
      {loading && <p className="range-list-status">Loading the list…</p>}
      {error && <p className="range-list-status" role="alert">{error}</p>}
      {!loading && !error && (
        <div className="at-risk-table-wrap" tabIndex={0}>
          <table className="at-risk-table">
            <thead>
              <tr>
                <th scope="col" className="at-risk-col-product">{firstColumnLabel}</th>
                {columns.map((col) => (
                  <th scope="col" key={col.key}>
                    {col.label}
                    {col.sub && <span className="at-risk-th-sub">{col.sub}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.sku_id || row.product_key || row.product_name}>
                  <td className="at-risk-col-product">
                    <ProductName
                      name={row.product_name}
                      code={row.sku_id}
                      onOpen={row.sku_id && onOpenProduct ? () => onOpenProduct(row.sku_id) : undefined}
                      openLabel={openLabel}
                    />
                  </td>
                  {columns.map((col) => <td key={col.key}>{col.render(row)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="at-risk-footer">
        {footnote && <p className="at-risk-footnote">{footnote}</p>}
        <div className="at-risk-actions">
          <button type="button" className="at-risk-btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </Modal>
  );
};

const Stat = ({ label, value, sub }) => (
  <div className="range-stat">
    <span className="range-stat-label">{label}</span>
    <span className="range-stat-value">{value}</span>
    {sub && <span className="range-stat-sub">{sub}</span>}
  </div>
);

// scope: the principals a figure covers when narrower than the page's filter
// ("Unilever only" under All principals), from the payload's coverage.
// leadVisible: the lead states the card's periods or count date, so it stays
// on the plain dashboard (Dashboard.css .keep-visible; Technical Adviser,
// 2 Oct 2026: every number with its period).
const CardShell = ({ title, lede, lead, leadVisible = false, scope, children, blocked, className = '' }) => (
  <div className={`chart-widget${className ? ` ${className}` : ''}${blocked ? ' chart-widget-empty' : ''}`}>
    <div className="chart-header">
      <div className="chart-title-area">
        <h4>{title}</h4>
        {lede && <SectionLede>{lede}</SectionLede>}
        {lead && <p className={leadVisible ? 'keep-visible' : undefined}>{lead}</p>}
        {scope && <p className="chart-placeholder-note">{scope}</p>}
      </div>
    </div>
    {children}
  </div>
);

// Idle stock (GET /dashboard idle_stock): products in the range-end count
// that sold nothing in the window before it. Del Monte sells by category, so
// the backend says why no product can be shown unsold.
// How many idle products the card names before the full list.
const IDLE_PREVIEW = 5;

export const IdleStockCard = ({ idle, scope, onOpenList, prior = null }) => {
  if (!idle) return null;
  // Named for what it is, in plain words (2026-10-15).
  const title = idle.window_rule_months
    ? <span>Stock with <span className="title-accent">no sale</span> in {idle.window_rule_months} months</span>
    : <span><span className="title-accent">Idle</span> stock</span>;
  // The same measure at the comparison period's count ("how long has this
  // been happening?", the Technical Adviser, 2 Oct 2026). `prior` is the
  // idle_stock block of GET /dashboard for the date bar's "Compare with"
  // period; left out when that count is missing or is this same count.
  const priorUsable = prior && !prior.blocked_reason && prior.products != null
    && (prior.count_date || prior.count_period)
    && (prior.count_date !== idle.count_date || prior.count_period !== idle.count_period);
  const priorChange = priorUsable ? idle.products - prior.products : 0;
  // Two parts of one sentence, the first set in bold on the card.
  const priorLead = priorUsable
    ? `At the earlier stock count (${prior.count_date ? formatDate(prior.count_date) : formatMonth(prior.count_period)}):`
    : null;
  const priorRest = priorUsable
    ? `${prior.products.toLocaleString()} products${prior.pesos != null ? ` worth ${formatCompactPesos(prior.pesos)}` : ''}, `
      + (priorChange === 0 ? 'the same number as now.'
        : `${Math.abs(priorChange).toLocaleString()} ${priorChange < 0 ? 'more' : 'fewer'} than now.`)
    : null;
  const window = idle.window_start && idle.window_end
    ? `${formatMonth(idle.window_start)} – ${formatMonth(idle.window_end)}`
    : `the last ${idle.window_rule_months} months`;
  const counted = idle.count_date ? `counted ${formatDate(idle.count_date)}`
    : idle.count_period ? `${formatMonth(idle.count_period)} count` : null;
  if (idle.blocked_reason) {
    return (
      <CardShell title={title} lede="Money stuck in stock that isn't moving" blocked className="dash-action-card idle-card">
        <p className="range-blocked">{idle.blocked_reason}</p>
      </CardShell>
    );
  }
  return (
    <CardShell
      title={title}
      lede="Money stuck in stock that isn't moving"
      scope={scope}
      lead={`Products on hand in the stock ${counted || 'count'} that sold nothing in ${window}.`}
      leadVisible
      className="dash-action-card idle-card"
    >
      {/* Two KPI blocks side by side, stacked when the card is narrow
          (RangeCards.css .idle-kpis; its own class, so the other range
          cards' .range-stat-row and its phone rules are untouched). */}
      <div className="idle-kpis">
        {/* The finding first (2026-10-19): most of these products have never
            sold at all, which is the question for SSM (why were they bought?). */}
        <Stat
          label="Never sold"
          value={`${idle.never_sold.toLocaleString()} of ${idle.products.toLocaleString()}`}
          sub={`products with no sale in the window; the other ${(idle.products - idle.never_sold).toLocaleString()} stopped selling`}
        />
        <Stat
          label="Stock value"
          value={formatCompactPesos(idle.pesos)}
          sub={`${idle.pesos_basis}${idle.products_with_value < idle.products
            ? ` · ${idle.products - idle.products_with_value} without a price, not in the sum` : ''}`}
        />
      </div>
      {priorLead && (
        <p className="idle-prior"><strong>{priorLead}</strong> {priorRest}</p>
      )}
      {/* What to do with it (Technical Adviser, 2 Oct 2026: what to order,
          and what to do with stock that stopped selling). 2026-10-22. */}
      {/* The largest few by value (the payload's items, already sorted
          largest first): which products the money is in, before the list.
          Ranked 01-05; the name first, then its SKU code and when it last
          sold on one muted line, the value at the right. */}
      {idle.items?.length > 0 && (
        <>
          <p className="range-list-title">Largest by stock value</p>
          <ol className="idle-rank-list">
            {idle.items.slice(0, IDLE_PREVIEW).map((r, i) => (
              <li key={r.product_key ?? r.sku_id}>
                <span className="idle-rank-num" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
                <span className="idle-rank-body">
                  <ProductName name={r.product_name || r.sku_id} className="idle-rank-name" />
                  <span className="idle-rank-meta">
                    {r.product_name && r.sku_id != null && <span className="idle-rank-code">{r.sku_id}</span>}
                    <span className={`idle-rank-status${r.never_sold ? ' is-never' : ''}`}>
                      {r.never_sold ? 'Never sold' : r.last_sale_period ? `Last sold ${formatMonth(r.last_sale_period)}` : 'No sale in the window'}
                    </span>
                  </span>
                </span>
                <span className={`idle-rank-value${r.pesos == null ? ' is-missing' : ''}`}>
                  {r.pesos == null ? 'No price' : formatCompactPesos(r.pesos)}
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
      {idle.products > 0 && (
        <div className="dash-card-footer">
          <button type="button" className="range-card-action" onClick={onOpenList}>
            See all {idle.products.toLocaleString()} products <ArrowRight size={14} aria-hidden="true" />
          </button>
        </div>
      )}
    </CardShell>
  );
};

export const IDLE_COLUMNS = [
  { key: 'pieces', label: 'Stock (pieces)', render: (r) => (r.pieces == null ? '—' : formatUnits(r.pieces)) },
  { key: 'pesos', label: 'Stock value (₱)', sub: 'at last purchase price', render: (r) => (r.pesos == null ? '—' : formatCompactPesos(r.pesos)) },
  { key: 'last', label: 'Last sale', render: (r) => (r.never_sold ? 'Never sold' : r.last_sale_period ? formatMonth(r.last_sale_period) : '—') },
];

// The lists behind the stock cards (GET /dashboard/stock-detail, 2026-10-19).
// Weeks of cover is the product's stock over its own average weekly sales;
// a product that sold nothing in those 12 months has no cover figure.
const weeksText = (r) => (r.weeks_of_cover != null ? `${r.weeks_of_cover.toFixed(1)} wks`
  : r.no_sale_in_window ? 'No sale in 12 months' : '—');
const pesosText = (v) => (v == null ? '—' : formatCompactPesos(v));
export const STOCK_VALUE_COLUMNS = [
  { key: 'pieces', label: 'Stock (pieces)', render: (r) => (r.pieces == null ? '—' : formatUnits(r.pieces)) },
  { key: 'pesos', label: 'Stock value (₱)', sub: 'at last purchase price', render: (r) => pesosText(r.pesos) },
  { key: 'cover', label: 'Weeks of cover', sub: 'in pesos', render: weeksText },
];
export const STOCK_COVER_COLUMNS = [
  { key: 'cover', label: 'Weeks of cover', sub: 'in pesos', render: weeksText },
  { key: 'weekly', label: 'Weekly sales (₱)', sub: 'average, 12 months', render: (r) => pesosText(r.weekly_sales) },
  { key: 'pesos', label: 'Stock value (₱)', sub: 'at last purchase price', render: (r) => pesosText(r.pesos) },
];
// The list behind the Stock cover card's "Above SSM's 3-week rule"
// (Dashboard.jsx, 2026-10-22). `policyWeeks` is the response's own
// policy_weeks. Every column names its unit; the weeks here are stock pesos
// over sales pesos, so they say "in pesos" beside the card's pieces figure.
export const aboveRuleColumns = (policyWeeks) => [
  { key: 'above', label: 'Above the rule (₱)', sub: `beyond ${policyWeeks} weeks of its sales`, render: (r) => pesosText(r.above_rule_pesos) },
  { key: 'pesos', label: 'Stock value (₱)', sub: 'at last purchase price', render: (r) => pesosText(r.pesos) },
  { key: 'pieces', label: 'Stock (pieces)', render: (r) => (r.pieces == null ? '—' : formatUnits(r.pieces)) },
  { key: 'weekly', label: 'Weekly sales (₱)', sub: 'average, at selling price', render: (r) => pesosText(r.weekly_sales) },
  { key: 'cover', label: 'Weeks of cover', sub: 'in pesos', render: weeksText },
];
const UNCHECKABLE_REASON = {
  no_safety_stock: 'No safety stock in the plan',
  no_stock_count: 'No stock count',
  missing_both: 'Missing both',
};
export const UNCHECKABLE_COLUMNS = [
  { key: 'reason', label: 'Why it can’t be checked', render: (r) => UNCHECKABLE_REASON[r.reason] || r.reason },
  { key: 'stock', label: 'Stock (pieces)', render: (r) => (r.current_stock == null ? '—' : formatUnits(r.current_stock)) },
];

// Forecast against sales over the range (GET /dashboard forecast_accuracy),
// for a client reader (2026-10-08): one plain answer, the monthly chart as
// its evidence, where the misses went, and the products to review. Every
// figure is the payload's; the definitions sit behind the "?".
//   company_total.value            the miss on the company's monthly totals
//   typical_product_weighted.value the miss product by product
//   by_month[].actual_pesos        actual sales, pesos at selling price
//   by_month[].net_miss_pesos      forecast − actual (backend/marts.py), so
//                                  the forecast in pesos is actual + net miss
//   surplus_pesos / shortage_pesos the over- and under-forecast totals
const wholePct = (share) => `${Math.round(share * 100)}%`;
const exactPesos = (v) => `₱${Math.round(v).toLocaleString('en-PH')}`;

// The chart's colours: actual sales in the card's teal, the forecast in the
// app's forecast violet (solid against dashed). The miss between them
// (2026-10-21, mockup pass): coral where the forecast was too high, teal
// where it was too low, the same two as the miss cards under the chart.
// Too low stays teal, not the mockup's blue: colors.js's hue-pair rule
// (measured) keeps blue and violet out of one chart, since red-blind viewers
// can't tell them apart. It is a deeper teal than the actual line
// (CHART_COLORS.missTooLow, 2026-10-24): the same teal made the legend's
// "Actual sales" and "Forecast too low" swatches one colour.
const FC_ACTUAL = CHART_COLORS.salesSeries;
const FC_FORECAST = COLORS.forecast;
const FC_TOO_HIGH = CHART_COLORS.missTooHigh;
const FC_TOO_LOW = CHART_COLORS.missTooLow;
const FC_AXIS_TITLE = { fontSize: 11, fontWeight: 600, fill: CHART_COLORS.axisLabel };

// The hover, in both chart views (2026-10-21, mockup pass): the month, its
// actual sales and forecast, the difference between them and which way it
// went (utils/forecastHighlights.missStatus: too high above zero, too low
// below, a match at exactly zero; nothing is called "accurate", since no
// threshold for that is on record). Compact pesos, the exact ones under them.
const FcSwatch = ({ color, dashed = false }) => (
  <span className={`fc-tip-swatch${dashed ? ' is-dashed' : ''}`} style={{ '--fc-swatch': color }} aria-hidden="true" />
);
const ForecastVsActualTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const status = missStatus(row.variance);
  const share = row.actual > 0 && row.variance ? Math.abs((row.variance / row.actual) * 100).toFixed(1) : null;
  return (
    <div className="chart-tooltip fc-tooltip">
      <p className="fc-tooltip-month">{formatMonth(row.period)}</p>
      <dl className="fc-tooltip-rows">
        <div><dt><FcSwatch color={FC_ACTUAL} />Actual sales</dt><dd>{formatCompactPesos(row.actual)}</dd></div>
        <div><dt><FcSwatch color={FC_FORECAST} dashed />Forecast sales</dt><dd>{formatCompactPesos(row.forecast)}</dd></div>
        <div>
          <dt>Difference</dt>
          <dd>{formatCompactPesos(Math.abs(row.variance))}{share ? <span className="fc-tooltip-share"> · {share}% of sales</span> : null}</dd>
        </div>
        {status && (
          <div><dt>Status</dt><dd className={`fc-tooltip-status is-${status}`}>{MISS_STATUS_LABEL[status]}</dd></div>
        )}
      </dl>
      <p className="fc-tooltip-exact">Exact: {exactPesos(row.actual)} sold · {exactPesos(row.forecast)} forecast</p>
    </div>
  );
};

// The miss axis: the same step either side of zero, about two gridlines
// each way, so a month too high and a month too low read on one scale.
const missTicks = (values) => {
  const top = Math.max(...values.map((v) => Math.abs(v ?? 0)), 1);
  const magnitude = 10 ** Math.floor(Math.log10(top / 2));
  const step = ([1, 2, 2.5, 5, 10].find((f) => f * magnitude >= top / 2) || 10) * magnitude;
  const steps = Math.ceil(top / step);
  return Array.from({ length: 2 * steps + 1 }, (_, i) => (i - steps) * step);
};
const missTick = (v) => (v < 0 ? `−${formatCompactPesos(v)}` : formatCompactPesos(v));

// The chart's views: the two lines with the miss shaded between them, the
// miss alone as one bar per month, and the rows (2026-10-19).
const FC_VIEWS = [['lines', 'Lines'], ['bars', 'Monthly miss'], ['table', 'Table']];

// A miss total as a share of the range's sales, its sum one hover away.
const HoverShare = ({ value, sold, label }) => (
  <InfoTip label={`How "${label}" compares with sales`} trigger={<>{wholePct(value / sold)} of sales</>} triggerClassName="fc-miss-share-trigger">
    {formatCompactPesos(value)} ÷ {formatCompactPesos(sold)} sold over the range = {wholePct(value / sold)}. Both at the same
    selling-price basis.
  </InfoTip>
);


// The error card's two bases (2026-10-19): the run the card shows first —
// calendar-adjusted, as the live forecast is made — and the same backtest
// without the adjustment (GET /dashboard's forecast_accuracy.compare_run),
// so the adjustment's effect on the picked range is on the card.
const FC_BASES = [['adjusted', 'Calendar-adjusted'], ['before', 'Before the adjustment']];

// "closer" / "further off" / a mixed verdict, from the two headline misses
// of the adjusted and the unadjusted run over the same months.
const adjustmentVerdict = (adj, bef) => {
  const pairs = [[adj.company_total?.value, bef.company_total?.value], [adj.typical_product_weighted?.value, bef.typical_product_weighted?.value]]
    .filter(([a, b]) => a != null && b != null);
  if (!pairs.length) return null;
  const better = pairs.filter(([a, b]) => a < b).length;
  const worse = pairs.filter(([a, b]) => a > b).length;
  if (better === pairs.length) return 'The adjustment brought these months closer on both.';
  if (worse === pairs.length) return 'The adjustment left these months further off on both.';
  return 'Mixed: closer on one, further off on the other.';
};

export const ForecastErrorSummaryCard = ({
  accuracy: served, scope, onOpenList, onOpenCategories,
  // The page's principal, for fetching the unadjusted run; the forecast's
  // calendar_adjustment (signed_off, method), for the card's note.
  principal = null, calendar = null,
}) => {
  const [view, setView] = useState('lines');
  const [basis, setBasis] = useState('adjusted');
  const [twin, setTwin] = useState(null); // { key, data } — the unadjusted run, same months
  const twinRunId = served?.compare_run?.run_id ?? null;
  const twinStart = served?.start_period ?? null;
  const twinEnd = served?.end_period ?? null;
  const twinKey = twinRunId != null ? `${twinRunId}|${twinStart}|${twinEnd}|${principal}` : null;
  useEffect(() => {
    if (!twinKey) return undefined;
    let cancelled = false;
    getForecastAccuracy({ period: twinEnd, startPeriod: twinStart, principal, run_id: twinRunId })
      .then((data) => { if (!cancelled) setTwin({ key: twinKey, data }); })
      .catch(() => { if (!cancelled) setTwin({ key: twinKey, data: null }); });
    return () => { cancelled = true; };
  }, [twinKey, twinRunId, twinStart, twinEnd, principal]);
  const twinData = twin?.key === twinKey && twin.data && !twin.data.blocked_reason ? twin.data : null;
  const showingBefore = basis === 'before' && Boolean(twinData);
  const accuracy = showingBefore ? twinData : served;
  if (!accuracy) return null;
  if (accuracy.blocked_reason || !accuracy.products) {
    return (
      <CardShell title={<span>How <span className="title-accent">close</span> the forecasts were</span>} lede="Where the forecast was right, and where it missed" blocked>
        <p className="range-blocked">{accuracy.blocked_reason || 'No forecasts were checked against sales in this range.'}</p>
      </CardShell>
    );
  }
  const runs = accuracy.over_forecast_runs || {};
  const company = accuracy.company_total?.value;
  const typical = accuracy.typical_product_weighted?.value;
  const months = [...(accuracy.by_month || [])]
    .filter((m) => m.actual_pesos != null && m.net_miss_pesos != null)
    .sort((a, b) => (a.period < b.period ? -1 : 1))
    .map((m) => {
      const actual = m.actual_pesos;
      const forecast = m.actual_pesos + m.net_miss_pesos;
      return {
        period: m.period,
        actual,
        forecast,
        variance: m.net_miss_pesos,
        // The miss as a band between the two lines (a range area each way):
        // from sales up to the forecast where it was too high, from the
        // forecast up to sales where it was too low; flat (no band) otherwise.
        tooHigh: [actual, Math.max(forecast, actual)],
        tooLow: [Math.min(forecast, actual), actual],
      };
    });
  // The ₱ axis starts just under the lowest value (utils/pesoTicks, the
  // Sales vs Inventory Value chart's rule): from ₱0 both lines sat in the
  // top third of the plot and a ₱10M swing read as a wobble.
  const ticks = pesoTicks(months.flatMap((m) => [m.actual, m.forecast]));
  const varianceTicks = months.length ? missTicks(months.map((m) => m.variance)) : null;
  const lastIndex = months.length - 1;
  // null when the backend sent no total: shown as — with no share or bar, never ₱0 (utils/missTotals).
  const over = accuracy.surplus_pesos;
  const under = accuracy.shortage_pesos;
  // Each total as a share of what sold over the range (actual_pesos, the
  // same basis), so "₱60.4M" has a size: 20% of sales.
  const soldTotal = accuracy.actual_pesos > 0 ? accuracy.actual_pesos : null;
  const tableColumns = [
    { key: 'period', label: 'Month', align: 'left', format: (v) => formatMonth(v) },
    { key: 'actual', label: 'Actual sales (₱)', format: exactPesos },
    { key: 'forecast', label: 'Forecast (₱)', format: exactPesos },
    { key: 'variance', label: 'Forecast − actual (₱)', format: (v) => `${v >= 0 ? '+' : '−'}${exactPesos(Math.abs(v))}` },
  ];

  return (
    <div className="chart-widget fc-card">
      <div className="fc-head">
        <h4 className="fc-title"><span>How <span className="title-accent">close</span> the forecasts were</span></h4>
        <span className="fc-period">{accuracy.label}</span>
      </div>
      <SectionLede>Where the forecast was right, and where it missed</SectionLede>
      {scope && <p className="chart-placeholder-note">{scope}</p>}

      {/* 1. The answer, in plain words. */}
      <p className="fc-answer">
        {company != null && (
          <>Across the whole company, forecasts were within <strong>{wholePct(company)}</strong> of actual sales.</>
        )}
        {typical != null && (
          <>
            {' '}Product by product, the typical miss is {company != null && typical > company ? 'bigger' : 'about the same'}:{' '}
            <strong>{wholePct(typical)}</strong>.
          </>
        )}
        <InfoTip label="How these two figures are measured">
          <span className="fc-tip-line"><strong>Company total ({company != null ? pct(company) : '—'}).</strong>{' '}
            {accuracy.company_total?.label} ({accuracy.company_total?.unit}).</span>
          <span className="fc-tip-line"><strong>Typical product ({typical != null ? pct(typical) : '—'}).</strong>{' '}
            {accuracy.typical_product_weighted?.label} ({accuracy.typical_product_weighted?.unit}).</span>
          <span className="fc-tip-line">
            Both are a weighted absolute percentage error (WAPE): the size of the misses as a share of what actually sold.
            {' '}{accuracy.products.toLocaleString()} products, {accuracy.product_months.toLocaleString()} product-months;
            {' '}{accuracy.forecast_source === 'backtest_recreated' ? 'forecasts as made at the time (backtest)' : 'stored forecast runs'}
            {accuracy.run_labels?.length ? `: ${accuracy.run_labels.join('; ')}` : ''}.
          </span>
          {accuracy.possibly_stock_limited > 0 && (
            <span className="fc-tip-line">
              {accuracy.possibly_stock_limited.toLocaleString()} product-months may be stock-limited (stock may have run
              out), so their sales may understate demand.
            </span>
          )}
        </InfoTip>
      </p>

      {/* How to read this (2026-10-21, mockup pass): the comparison in one
          plain sentence, then which forecasts are scored. That part keeps
          its switch (calendar-adjusted, or the same months before the
          adjustment: GET /dashboard's forecast_accuracy.compare_run) and the
          pending-confirmation notice on its face; the two runs' figures and
          the method sit one click down. Shown even with
          SHOW_CHART_DESCRIPTIONS off: asked for by name. */}
      <div className="fc-read">
        <p className="fc-read-title">How to read this</p>
        <p className="fc-read-text">
          Compare what we predicted with what actually sold. Forecasts that are too high may lead to excess stock,
          while forecasts that are too low may increase the risk of stockouts.
        </p>
        {served.calendar_adjusted && served.calendar_adjusted !== 'no' && (
          <div className="fc-read-method">
            <div className="fc-read-method-row">
              {twinData && (
                <ChartViewToggle view={basis} onChange={setBasis} options={FC_BASES} label="Forecasts scored: calendar-adjusted or before the adjustment" />
              )}
              <p className="fc-read-status">
                {showingBefore
                  ? <>Showing the same months <strong>before the calendar adjustment</strong>, as the backtest was first published.</>
                  : served.calendar_adjusted === 'partly'
                    ? 'Some of these months are scored on calendar-adjusted forecasts and some are not.'
                    : <>Scored on <strong>calendar-adjusted</strong> forecasts, as the live forecast is made</>}
                {!showingBefore && served.calendar_adjusted === 'yes'
                  && (calendarSignoffText(calendar?.signed_off) ? <> — {calendarSignoffText(calendar.signed_off)}.</> : '.')}
              </p>
            </div>
            <details className="fc-read-more">
              <summary>About the calendar adjustment</summary>
              {twinData && (
                <p className="fc-basis-compare">
                  Same months, company total · typical product: calendar-adjusted <strong>{pct(served.company_total?.value)}</strong> ·{' '}
                  <strong>{pct(served.typical_product_weighted?.value)}</strong>; before the adjustment{' '}
                  <strong>{pct(twinData.company_total?.value)}</strong> · <strong>{pct(twinData.typical_product_weighted?.value)}</strong>.
                  {' '}{adjustmentVerdict(served, twinData)}
                </p>
              )}
              <p>{calendar?.method || CALENDAR_METHOD_FALLBACK}</p>
              <p>{CALENDAR_HISTORY_NOTE}</p>
              {served.compare_run && (
                <p>Calendar-adjusted: {served.run_labels?.join('; ')}. Before the adjustment: {served.compare_run.label}.</p>
              )}
            </details>
          </div>
        )}
      </div>

      {/* 2. The evidence: forecast against actual, month by month. */}
      {months.length > 0 && (
        <div className="fc-chart-block">
          <div className="fc-chart-head">
            <div>
              <p className="fc-chart-title">Forecast vs. Actual Sales</p>
              <SectionLede>The forecast against what really sold</SectionLede>
              <p className="fc-chart-sub">Monthly comparison · pesos at {String(accuracy.pesos_basis || '').split(' (')[0]}</p>
            </div>
            {/* The view switch beside the chart's title, the key on its own
                row under them (2026-10-21: a shorter card, to match the
                forecast card beside it). */}
            <div className="fc-chart-tools">
              <ChartViewToggle view={view} onChange={setView} options={FC_VIEWS} label="Forecast vs actual: lines, monthly miss or table" />
            </div>
          </div>
          {/* Every view's key laid in one cell, the current one shown (the
              others keep their space, unseen): the row keeps the tallest
              key's height, so switching views never moves the card or the
              one beside it (2026-10-19). */}
          <div className="fc-legend-stack">
            <ul className={`fc-legend${view === 'lines' ? '' : ' is-reserved'}`} aria-label="Legend">
              <li><span className="fc-legend-line" style={{ backgroundColor: FC_ACTUAL }} aria-hidden="true" />Actual sales</li>
              <li><span className="fc-legend-line is-forecast" style={{ backgroundColor: FC_FORECAST }} aria-hidden="true" />Forecast</li>
              <li><span className="fc-legend-band" style={{ backgroundColor: FC_TOO_HIGH }} aria-hidden="true" />Forecast too high</li>
              <li><span className="fc-legend-band" style={{ backgroundColor: FC_TOO_LOW }} aria-hidden="true" />Forecast too low</li>
            </ul>
            <ul className={`fc-legend${view === 'bars' ? '' : ' is-reserved'}`} aria-label="Legend">
              <li><span className="fc-legend-bar" style={{ backgroundColor: FC_TOO_HIGH }} aria-hidden="true" />Forecast too high</li>
              <li><span className="fc-legend-bar" style={{ backgroundColor: FC_TOO_LOW }} aria-hidden="true" />Forecast too low</li>
            </ul>
          </div>
          {view === 'table' ? (
            // In the chart's own box, so the card is the same height in
            // both views; the table scrolls inside it.
            <div className="fc-chart fc-chart-table">
              <ChartTable columns={tableColumns} rows={months} caption="Forecast and actual sales by month, in pesos" />
            </div>
          ) : view === 'bars' ? (
            // The miss alone: one bar per month, forecast − actual, above
            // zero where the forecast was too high (coral), below where it
            // was too low (teal) — the same rows as the lines, folded.
            <div
              className="fc-chart"
              role="img"
              aria-label={`Bar chart of the monthly miss, forecast minus actual sales in pesos, ${accuracy.label}: `
                + 'above zero the forecast was too high, below zero too low. Use the Table view for the exact figures.'}
            >
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={months} margin={{ top: 12, right: 16, left: 0, bottom: 4 }} barCategoryGap="28%">
                  <defs>
                    {/* Solid at the bar's tip, fading to the zero line, either side of it. */}
                    <Fade id="fc-miss-high" color={FC_TOO_HIGH} to={BAR_FADE_FLOOR} />
                    <Fade id="fc-miss-low" color={FC_TOO_LOW} to={BAR_FADE_FLOOR} flip />
                  </defs>
                  <CartesianGrid {...GRID_PROPS} />
                  <XAxis
                    dataKey="period"
                    tickFormatter={monthName}
                    axisLine={false}
                    tickLine={false}
                    tick={<MonthTick fontSize={11} fill={CHART_COLORS.axisLabel} />}
                    minTickGap={12}
                    height={30 + MONTH_TICK_EXTRA_HEIGHT + 14}
                    label={{ value: 'Month', position: 'insideBottom', offset: 0, ...FC_AXIS_TITLE }}
                  />
                  <YAxis
                    tickFormatter={missTick}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 11, fill: CHART_COLORS.axisLabel }}
                    width={64}
                    domain={varianceTicks ? [varianceTicks[0], varianceTicks[varianceTicks.length - 1]] : ['auto', 'auto']}
                    ticks={varianceTicks ?? undefined}
                    label={{ value: 'Forecast − actual (₱)', angle: -90, position: 'insideLeft', textAnchor: 'middle', ...FC_AXIS_TITLE }}
                  />
                  <Tooltip content={<ForecastVsActualTooltip />} cursor={{ fill: 'rgba(148, 163, 184, 0.12)' }} />
                  <ReferenceLine y={0} stroke="var(--color-slate-400)" />
                  <Bar dataKey="variance" name="Forecast − actual" radius={3} maxBarSize={28} isAnimationActive={false}>
                    {months.map((m) => <Cell key={m.period} fill={m.variance >= 0 ? 'url(#fc-miss-high)' : 'url(#fc-miss-low)'} />)}
                  </Bar>
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div
              className="fc-chart"
              role="img"
              aria-label={`Line chart of monthly actual sales and forecast in pesos, ${accuracy.label}. Use the Table view for the exact figures.`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={months} margin={{ top: 12, right: 16, left: 0, bottom: 4 }}>
                  {/* Horizontal gridlines only, as every chart on the page. */}
                  <CartesianGrid {...GRID_PROPS} />
                  <XAxis
                    dataKey="period"
                    tickFormatter={monthName}
                    axisLine={false}
                    tickLine={false}
                    tick={<MonthTick fontSize={11} fill={CHART_COLORS.axisLabel} />}
                    minTickGap={12}
                    height={30 + MONTH_TICK_EXTRA_HEIGHT + 14}
                    label={{ value: 'Month', position: 'insideBottom', offset: 0, ...FC_AXIS_TITLE }}
                  />
                  <YAxis
                    tickFormatter={(v) => formatCompactPesos(v)}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 11, fill: CHART_COLORS.axisLabel }}
                    width={64}
                    domain={ticks ? [ticks[0], ticks[ticks.length - 1]] : [0, 'auto']}
                    ticks={ticks ?? undefined}
                    label={{ value: 'Pesos (₱)', angle: -90, position: 'insideLeft', textAnchor: 'middle', ...FC_AXIS_TITLE }}
                  />
                  <Tooltip content={<ForecastVsActualTooltip />} cursor={{ stroke: CHART_COLORS.gridline }} />
                  {/* The miss, shaded between the lines: coral where the
                      forecast was too high, teal where too low. Recharts
                      draws an Area under every Line (its layer order). Neither
                      adds to the hover (tooltipType none): the note does. */}
                  <Area
                    type="monotone" dataKey="tooHigh" name="Forecast too high" fill={FC_TOO_HIGH} fillOpacity={0.16}
                    stroke="none" dot={false} activeDot={false} isAnimationActive={false} tooltipType="none" legendType="none"
                  />
                  <Area
                    type="monotone" dataKey="tooLow" name="Forecast too low" fill={FC_TOO_LOW} fillOpacity={0.18}
                    stroke="none" dot={false} activeDot={false} isAnimationActive={false} tooltipType="none" legendType="none"
                  />
                  <Line
                    type="monotone" dataKey="actual" name="Actual sales" stroke={FC_ACTUAL} strokeWidth={3}
                    strokeLinecap="round" dot={endDot(FC_ACTUAL, lastIndex)}
                    activeDot={{ r: 5, strokeWidth: 2, stroke: 'var(--color-surface, #fff)' }} isAnimationActive={false}
                  />
                  <Line
                    type="monotone" dataKey="forecast" name="Forecast" stroke={FC_FORECAST} strokeWidth={2.5}
                    strokeLinecap="round" strokeDasharray="6 4" dot={endDot(FC_FORECAST, lastIndex)}
                    activeDot={{ r: 5, strokeWidth: 2, stroke: 'var(--color-surface, #fff)' }} isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* 3. Where the misses went: two bars on one scale. */}
      <div className="fc-misses">
        <div className="fc-misses-head">
        <p className="fc-misses-title">
          Where the misses went
          <InfoTip label="What these amounts are">
            The forecast&apos;s differences from actual sales over {accuracy.label}, valued at{' '}
            {accuracy.pesos_basis}. &ldquo;Forecast too high&rdquo; adds up the months a product&apos;s forecast was
            above what it sold; &ldquo;forecast too low&rdquo; the months it was below. They show the direction the
            forecasts lean, not stock that was counted as excess or sales that were actually lost.
          </InfoTip>
        </p>
        <SectionLede>Too high, or too low?</SectionLede>
        </div>
        {/* Coral up, teal down (2026-10-21, mockup pass). The bar is the
            total's share of the range's sales, the same figure as the line
            above it, so its length means what it says; without sales to
            divide by there is no share and no bar. */}
        <div className="fc-miss-cards">
          {[
            { key: 'over', tone: 'high', Icon: ArrowUp, label: 'Forecast too high', note: 'Forecast above sales — risk of excess stock.', value: over },
            { key: 'under', tone: 'low', Icon: ArrowDown, label: 'Forecast too low', note: 'Sales above forecast — risk of stockouts.', value: under },
          ].map((b) => ({ ...b, share: missShare(b.value, soldTotal) })).map((b) => (
            <div className={`fc-miss-card is-${b.tone}`} key={b.key}>
              <div className="fc-miss-top">
                <span className="fc-miss-name">{b.label}</span>
                <span className="fc-miss-icon" aria-hidden="true"><b.Icon size={16} strokeWidth={2.5} /></span>
              </div>
              <span className="fc-miss-value">{formatCompactPesos(b.value)}</span>
              {b.share != null && (
                <span className="fc-miss-share">
                  <HoverShare value={b.value} sold={soldTotal} label={b.label} />
                </span>
              )}
              <span className="fc-miss-note">{b.note}</span>
              {b.share != null && (
                <div
                  className="fc-miss-track"
                  role="img"
                  aria-label={`${b.label}: ${formatCompactPesos(b.value)}, ${wholePct(b.share)} of sales over ${accuracy.label}`}
                >
                  <span style={{ width: `${Math.min(100, b.share * 100)}%` }} />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* 4. The takeaway: the products to review, with their list. */}
      {runs.count > 0 && (
        <button type="button" className="fc-action fc-action-alert" onClick={() => onOpenList(showingBefore ? twinRunId : null)}>
          <AlertTriangle className="fc-action-icon" size={16} aria-hidden="true" />
          <span className="fc-action-text">
            <strong>{runs.count.toLocaleString()} products</strong> had forecasts that were too high {runs.run_months} or
            more months in a row.
          </span>
          <ArrowRight size={14} aria-hidden="true" />
        </button>
      )}
      {/* Accuracy one level up (Technical Adviser, 2 Oct 2026: "at category
          and total level"): the same scored rows summed per category, in
          pieces and pesos (GET /dashboard/accuracy?level=category). */}
      {onOpenCategories && (
        <button type="button" className="fc-action fc-action-quiet" onClick={() => onOpenCategories(showingBefore ? twinRunId : null)}>
          <span className="fc-action-text">See where the misses went, <strong>category by category</strong></span>
          <ArrowRight size={14} aria-hidden="true" />
        </button>
      )}
    </div>
  );
};

// One row per product category: the forecast against what sold, in pieces,
// and the misses in pesos split by direction. Pieces and pesos only; the
// accuracy percentages stay on the card's two headline figures.
const signedPieces = (v) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}${formatUnits(Math.abs(v))}`);
export const CATEGORY_MISS_COLUMNS = [
  { key: 'products', label: 'Products', render: (r) => formatCount(r.products) },
  { key: 'forecast', label: 'Forecast (pieces)', sub: 'summed over the range', render: (r) => formatUnits(r.forecast_pieces) },
  { key: 'actual', label: 'Sold (pieces)', sub: 'summed over the range', render: (r) => formatUnits(r.actual_pieces) },
  { key: 'net', label: 'Net miss (pieces)', sub: '+ forecast too high, − too low', render: (r) => signedPieces(r.net_miss_pieces) },
  { key: 'over', label: 'Forecast too high (₱)', render: (r) => formatCompactPesos(r.surplus_pesos) },
  { key: 'under', label: 'Forecast too low (₱)', render: (r) => formatCompactPesos(r.shortage_pesos) },
];

export const OVER_RUN_COLUMNS = [
  { key: 'run', label: 'Months in a row', sub: 'forecast above sales', render: (r) => r.run_length },
  { key: 'last', label: 'Last month', render: (r) => (r.last_month ? formatMonth(r.last_month) : '—') },
  { key: 'pieces', label: 'Surplus (pieces)', sub: 'over the run', render: (r) => (r.surplus_pieces == null ? '—' : formatUnits(r.surplus_pieces)) },
  { key: 'pesos', label: 'Surplus (₱)', sub: 'at selling price', render: (r) => (r.surplus_pesos == null ? '—' : formatCompactPesos(r.surplus_pesos)) },
  { key: 'limited', label: 'Possibly stock-limited', render: (r) => (r.possibly_stock_limited ? 'Yes' : r.possibly_stock_limited === false ? 'No' : '—') },
];

// Products that entered or left Class A (GET /dashboard/class-changes): the
// range against the same months a year before, ranked on one revenue rule.
// How many each side names before "See all" opens the rest, in place.
const LIST_PREVIEW = 5;

// One product's class in the comparison period and now, from the payload's
// own compare_class / class (null = not ranked in that range; the item's
// *_note says why). Shown only where a page asks for it (showClassMove: the
// ABC page, 2026-10-24); the ranking is the backend's, nothing is re-ranked.
// A Del Monte side with nothing collected (note 'not_collected', backend/
// marts.py _unranked_side) says so, apart from a real "no sales".
const ClassMove = ({ before, now, beforeNote, nowNote }) => {
  const word = (tier, note) => (tier ? `Class ${tier}` : note === 'not_collected' ? 'not collected' : 'not ranked');
  const side = (tier, note) => (tier ? <ClassBadge tier={tier} />
    : <span className="class-move-none" title={note && note !== 'not_collected' ? note : undefined}>{word(tier, note)}</span>);
  return (
    <span className="class-move">
      <span className="visually-hidden">{`${word(before, beforeNote)} before, ${word(now, nowNote)} now`}</span>
      <span className="class-move-sides" aria-hidden="true">
        {side(before, beforeNote)}
        <ArrowRight size={12} />
        {side(now, nowNote)}
      </span>
    </span>
  );
};

// One side (2026-10-19, after the mockup): a tinted header band — green for
// the ones that joined, red for the ones that left — then the products in
// the payload's own order, each with its change in revenue at the right.
// The full list scrolls inside the panel, so the card keeps its height.
const ChangeList = ({ title, tone, items, noun, onOpen, showClassMove = false }) => {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? items : items.slice(0, LIST_PREVIEW);
  return (
    <section className={`pending-change-list is-${tone}`} aria-label={`${title} (${items.length})`}>
      <h5 className="pending-change-head">
        {title} <span className="pending-change-count">({items.length})</span>
      </h5>
      {items.length === 0 ? <p className="pending-change-empty">None</p> : (
        <ul className={showAll ? 'is-expanded' : undefined}>
          {shown.map((item) => (
            <li key={item.sku_id || item.product_key || item.product_name}>
              <ProductName
                // A row without a SKU is a Del Monte category, served as its
                // raw path; shown readable, the key keeps the raw (2026-10-26).
                name={item.sku_id ? (item.product_name || item.category_path) : categoryLabel(item.product_name || item.category_path)}
                code={item.sku_id}
                onOpen={item.sku_id && onOpen ? () => onOpen(item.sku_id) : undefined}
                openLabel="Open its forecast"
              />
              {showClassMove && (
                <ClassMove before={item.compare_class} now={item.class}
                  beforeNote={item.compare_class_note} nowNote={item.class_note} />
              )}
              {item.change_pesos != null && (
                <span className={`pending-change-delta ${item.change_pesos >= 0 ? 'is-up' : 'is-down'}`}>
                  {signedPesos(item.change_pesos)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {items.length > LIST_PREVIEW && (
        <button type="button" className="range-card-action pending-change-more" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Show fewer' : `See all ${items.length} ${noun}`} <ArrowRight size={13} aria-hidden="true" />
        </button>
      )}
    </section>
  );
};

// Del Monte regrouped its product categories in Jan 2025 (ABCClassification
// DEL_MONTE_REGROUP_PERIOD): a comparison across that month sets old
// sub-category names against new ones, so most "entered" and "left" rows are
// a renaming, not a change in what sold.
const DEL_MONTE_REGROUP_PERIOD = '2025-01';
const crossesRegroup = (changes, p) => p.principal === 'delmonte'
  && changes.compare_start_period < DEL_MONTE_REGROUP_PERIOD
  && changes.end_period >= DEL_MONTE_REGROUP_PERIOD;

const byChange = (items) => [...items].sort((a, b) => Math.abs(b.change_pesos ?? 0) - Math.abs(a.change_pesos ?? 0));

// One side's totals: both figures when the backend has them. A figure it
// withholds (null, with its *_revenue_reason — a Del Monte range with
// nothing collected, since 2026-10-16) is named for what it is, never a ₱0
// that reads as a real zero.
const REASON_TEXT = { not_collected: 'not collected' };
const whyNone = (reason) => REASON_TEXT[reason] || reason || 'no figure';
const sideSentence = (who, before, beforeReason, now, nowReason) => {
  const b = before != null ? <strong>{formatCompactPesos(before)}</strong> : null;
  const n = now != null ? <strong>{formatCompactPesos(now)}</strong> : null;
  if (b && n) return <>The ones that {who} sold {b} a year earlier and {n} now. </>;
  if (n) return <>The ones that {who} sold {n} now; a year earlier their sales were {whyNone(beforeReason)}. </>;
  if (b) return <>The ones that {who} sold {b} a year earlier; their sales now are {whyNone(nowReason)}. </>;
  return <>The ones that {who} have no sales figure on either side ({whyNone(nowReason)}). </>;
};

// `showClassMove`: each product's class before and now beside its name (the
// ABC page). The Dashboard leaves it off and keeps its compact rows.
export const ClassChanges = ({ changes, onOpen, showClassMove = false }) => {
  if (!changes?.principals?.length) return null;
  const names = { unilever: 'Unilever', delmonte: 'Del Monte' };
  const multi = changes.principals.length > 1;
  return (
    <CardShell
      title="Changes in the top sellers"
      lede="Where changes happened"
      lead={`${changes.label}, compared with ${changes.compare_label}. `
        + 'The amount beside each product is the change in its revenue between the two periods.'}
      leadVisible
    >
      {changes.principals.map((p) => {
        const noun = p.grain === 'sku' ? 'products' : 'categories';
        const one = p.grain === 'sku' ? 'product' : 'category';
        // A side where nothing at all was collected (Del Monte, Mar 2024 -
        // Feb 2025). The backend marks every compared category's revenue on
        // that side `not_collected` (backend/marts._unranked_side, only when
        // the principal has no real month in the range). Ranked from nothing,
        // that side has no top sellers, so the card used to say "0 categories
        // a year earlier" and list every current one as joined (audit FE-4,
        // 2026-10-21). No comparison is possible; it says so instead.
        const compareMissing = p.entered_compare_revenue_reason === 'not_collected'
          || p.left_compare_revenue_reason === 'not_collected';
        const nowMissing = p.entered_revenue_reason === 'not_collected'
          || p.left_revenue_reason === 'not_collected';
        const missingSide = compareMissing ? changes.compare_label : nowMissing ? changes.label : null;
        // "Open its forecast" for Unilever SKUs only: a Del Monte row is a
        // category, with no product forecast to open (ABCClassification's
        // openForecast, the same rule).
        const openRow = p.principal === 'unilever' ? onOpen : undefined;
        return (
          <div key={p.principal} className="range-change-block">
            {multi && <span className="pending-card-label">{names[p.principal] || p.principal}</span>}
            {p.blocked_reason ? <p className="range-blocked">{p.blocked_reason}</p> : missingSide ? (
              <p className="range-blocked">
                No comparison: {names[p.principal] || p.principal} sales were not collected for {missingSide}, so
                no {one} can be said to have joined or left the
                top sellers.{' '}
                {compareMissing
                  ? <>Top sellers in {changes.label}: <strong>{p.class_a_count.toLocaleString()}</strong> {noun}.</>
                  : <>Top sellers in {changes.compare_label}: <strong>{p.compare_class_a_count.toLocaleString()}</strong> {noun}.</>}
              </p>
            ) : (
              <>
                {crossesRegroup(changes, p) && (
                  <p className="range-regroup-note">
                    <strong>Del Monte regrouped its product categories in Jan 2025</strong>, so this comparison sets the
                    old sub-category names against the new ones: most categories below entered or left because they
                    were renamed, not because their sales changed.
                  </p>
                )}
                {/* The counts and totals in bold, so the sentence scans. */}
                <p className="range-note range-change-summary">
                  Top sellers: <strong>{p.compare_class_a_count.toLocaleString()}</strong> {noun} a year
                  earlier, <strong>{p.class_a_count.toLocaleString()}</strong> now
                  (<strong>{p.stayed_count.toLocaleString()}</strong> stayed).{' '}
                  {/* A side with nobody in it says so, rather than "sold ₱0 and ₱0". */}
                  {(p.entered || []).length > 0
                    ? sideSentence('joined', p.entered_compare_revenue, p.entered_compare_revenue_reason, p.entered_revenue, p.entered_revenue_reason)
                    : 'None joined. '}
                  {(p.left || []).length > 0
                    ? sideSentence('left', p.left_compare_revenue, p.left_compare_revenue_reason, p.left_revenue, p.left_revenue_reason)
                    : 'None left. '}
                  Pesos at {p.pesos_basis}.
                </p>
                <div className="pending-change-grid">
                  <ChangeList title="Joined the top sellers" tone="up" items={byChange(p.entered || [])} noun={noun} onOpen={openRow} showClassMove={showClassMove} />
                  <ChangeList title="Left the top sellers" tone="down" items={byChange(p.left || [])} noun={noun} onOpen={openRow} showClassMove={showClassMove} />
                </div>
                <p className="range-source">{p.revenue_rule}</p>
              </>
            )}
          </div>
        );
      })}
    </CardShell>
  );
};

// Del Monte's product sales (GET /dashboard/product-sales): SSM has no
// product-level Del Monte sales, so these are its real sell-out split by
// each product's stock share (DEC-31) — every row an estimate. Shown under
// the data plan's own label (PROJECT_STATE §18.6), never as a KPI.
export const DEMO_PRODUCT_SALES_LABEL =
  'Demo: Del Monte product sales estimated from total sales × stock share — SSM has no product-level sales';
const PRODUCT_SALES_PREVIEW = 8;

// One row per product: its estimated pesos summed over the range's months. A month with no estimate (pesos
// null) adds nothing and is not counted; a product with no estimate in ANY month has pesos null (rendered as
// NOT_COLLECTED), never 0 — a summed 0 means estimates that added up to zero. Those products sort last.
export const productSalesTotals = (rows = []) => {
  const byProduct = new Map();
  for (const r of rows) {
    const key = r.product_key ?? r.sku_id;
    const entry = byProduct.get(key) || {
      product_key: r.product_key, sku_id: r.sku_id, product_name: r.product_name, pesos: null, months: new Set(),
    };
    if (r.pesos != null) {
      entry.pesos = (entry.pesos ?? 0) + r.pesos;
      entry.months.add(r.period);
    }
    byProduct.set(key, entry);
  }
  return [...byProduct.values()]
    .map((e) => ({ ...e, months: e.months.size }))
    .sort((a, b) => (a.pesos == null) - (b.pesos == null) || (b.pesos ?? 0) - (a.pesos ?? 0));
};

export const PRODUCT_SALES_COLUMNS = [
  { key: 'pesos', label: 'Estimated sales (₱)', sub: 'selling price, ex-VAT', render: (r) => formatCompactPesos(r.pesos) },
  { key: 'months', label: 'Months', sub: 'with an estimate', render: (r) => r.months },
];

export const DelMonteProductSalesCard = ({ sales, onOpenList }) => {
  if (!sales) return null;
  const totals = productSalesTotals(sales.rows);
  if (!totals.length) {
    return (
      <CardShell title="Del Monte product sales (demo)" blocked>
        <p className="range-blocked">No estimated product sales in {sales.label}.</p>
      </CardShell>
    );
  }
  return (
    <CardShell
      title="Del Monte product sales (demo)"
      lead={`${totals.length.toLocaleString()} products, ${sales.label}, highest estimated sales first.`}
    >
      <p className="range-regroup-note"><strong>{DEMO_PRODUCT_SALES_LABEL}.</strong></p>
      <ol className="range-product-list">
        {totals.slice(0, PRODUCT_SALES_PREVIEW).map((r) => (
          <li key={r.product_key ?? r.sku_id}>
            <ProductName name={r.product_name} code={r.sku_id} />
            <span className="range-product-value">{formatCompactPesos(r.pesos)}</span>
          </li>
        ))}
      </ol>
      {totals.length > PRODUCT_SALES_PREVIEW && (
        <button type="button" className="range-card-action" onClick={() => onOpenList(totals)}>
          See all {totals.length.toLocaleString()} products <ArrowRight size={12} aria-hidden="true" />
        </button>
      )}
    </CardShell>
  );
};
