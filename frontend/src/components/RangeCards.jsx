// Dashboard cards on the data marts' range answers (DEC-36, 2026-10-04/05):
// idle stock, the forecast's miss against sales, and the products that
// entered or left Class A. Each figure states its period and its basis, and
// the products behind it are one click away (Technical Adviser, 2 Oct 2026:
// detail behind every aggregate). The figures are GET /dashboard's (or the
// range route's) as served; nothing here recomputes one.
import React, { useState } from 'react';
import SectionLede from './ui/SectionLede';
import { ArrowRight, X } from 'lucide-react';
import {
  Area, Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import Modal from './Modal';
import ProductName from './ProductName';
import InfoTip from './InfoTip';
import MonthTick, { MONTH_TICK_EXTRA_HEIGHT, monthName } from './MonthTick';
import { ChartTable, ChartViewToggle } from './ChartTable';
import { GRID_PROPS } from './ChartZoom';
import { pesoTicks } from '../utils/pesoTicks';
import { BAR_FADE_FLOOR, Fade, endDot } from './ui/ChartParts';
import { CHART_COLORS, COLORS } from '../theme/colors';
import { formatCompactPesos } from '../utils/formatters';
import { formatUnits } from '../utils/formatNumber';
import { formatDate, formatMonth } from '../utils/formatDate';
import './AtRiskProductsModal.css';
import './PendingCards.css';
import './RangeCards.css';

const pct = (share) => (share == null ? '—' : `${(share * 100).toFixed(1)}%`);
const signedPesos = (value) => `${value >= 0 ? '+' : '−'}${formatCompactPesos(Math.abs(value))}`;

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
const CardShell = ({ title, lede, lead, scope, children, blocked }) => (
  <div className={`chart-widget${blocked ? ' chart-widget-empty' : ''}`}>
    <div className="chart-header">
      <div className="chart-title-area">
        <h4>{title}</h4>
        {lede && <SectionLede>{lede}</SectionLede>}
        {lead && <p>{lead}</p>}
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
  const priorLine = priorUsable
    ? `At the earlier stock count (${prior.count_date ? formatDate(prior.count_date) : formatMonth(prior.count_period)}): `
      + `${prior.products.toLocaleString()} products${prior.pesos != null ? ` worth ${formatCompactPesos(prior.pesos)}` : ''}, `
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
      <CardShell title={title} lede="Money stuck in stock that isn't moving" blocked>
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
    >
      <div className="range-stat-row">
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
      {priorLine && <p className="range-stat-sub">{priorLine}</p>}
      {/* The largest few by value (the payload's items, already sorted
          largest first): which products the money is in, before the list. */}
      {idle.items?.length > 0 && (
        <>
          <p className="range-list-title">Largest by stock value</p>
          <ol className="range-product-list">
            {idle.items.slice(0, IDLE_PREVIEW).map((r) => (
              <li key={r.product_key ?? r.sku_id}>
                <span className="range-product-name">
                  <ProductName name={r.product_name} code={r.sku_id} />
                  <span className="range-product-sub">
                    {r.never_sold ? 'Never sold' : r.last_sale_period ? `Last sold ${formatMonth(r.last_sale_period)}` : 'No sale in the window'}
                  </span>
                </span>
                <span className="range-product-value">{r.pesos == null ? 'No price' : formatCompactPesos(r.pesos)}</span>
              </li>
            ))}
          </ol>
        </>
      )}
      {idle.products > 0 && (
        <button type="button" className="range-card-action" onClick={onOpenList}>
          See all {idle.products.toLocaleString()} products <ArrowRight size={12} aria-hidden="true" />
        </button>
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
  { key: 'cover', label: 'Weeks of cover', render: weeksText },
];
export const STOCK_COVER_COLUMNS = [
  { key: 'cover', label: 'Weeks of cover', render: weeksText },
  { key: 'weekly', label: 'Weekly sales (₱)', sub: 'average, 12 months', render: (r) => pesosText(r.weekly_sales) },
  { key: 'pesos', label: 'Stock value (₱)', sub: 'at last purchase price', render: (r) => pesosText(r.pesos) },
];
export const ABOVE_RULE_COLUMNS = [
  { key: 'above', label: 'Above the rule (₱)', sub: 'beyond 3 weeks of its sales', render: (r) => pesosText(r.above_rule_pesos) },
  { key: 'pesos', label: 'Stock value (₱)', render: (r) => pesosText(r.pesos) },
  { key: 'cover', label: 'Weeks of cover', render: weeksText },
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
// app's forecast violet; the miss between them in the same two (violet
// where the forecast was too high, teal where too low), as the two miss
// cards under the chart are.
const FC_ACTUAL = CHART_COLORS.salesSeries;
const FC_FORECAST = COLORS.forecast;
const FC_AXIS_TITLE = { fontSize: 11, fontWeight: 600, fill: CHART_COLORS.axisLabel };

// The hover (2026-10-19), the Sales vs Inventory Value chart's own boxes:
// one per series — the month, the exact pesos, the series' name — and the
// miss under them, in pesos and as a share of what sold.
const ForecastVsActualTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const up = row.variance >= 0;
  const share = row.actual > 0 ? Math.abs((row.variance / row.actual) * 100).toFixed(1) : null;
  return (
    <div className="chart-tooltip chart-callouts">
      <div className="chart-callout" style={{ '--chart-callout': FC_ACTUAL }}>
        <span className="chart-callout-period">{formatMonth(row.period)}</span>
        <strong className="chart-callout-value">{exactPesos(row.actual)}</strong>
        <span className="chart-callout-name">Actual sales</span>
      </div>
      <div className="chart-callout" style={{ '--chart-callout': FC_FORECAST }}>
        <span className="chart-callout-period">{formatMonth(row.period)}</span>
        <strong className="chart-callout-value">{exactPesos(row.forecast)}</strong>
        <span className="chart-callout-name">Forecast</span>
      </div>
      <p className="chart-tooltip-placeholder chart-tooltip-note">
        Forecast too {up ? 'high' : 'low'} by <strong>{formatCompactPesos(Math.abs(row.variance))}</strong>
        {share ? ` (${up ? '+' : '−'}${share}% of sales)` : ''} — risk of too {up ? 'much' : 'little'} stock.
      </p>
    </div>
  );
};

// The "Monthly miss" view's hover: the month's miss, signed, which way it
// leans and its share of that month's sales, with the two figures behind it.
const MonthlyMissTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const up = row.variance >= 0;
  const share = row.actual > 0 ? Math.abs((row.variance / row.actual) * 100).toFixed(1) : null;
  return (
    <div className="chart-tooltip chart-callouts">
      <div className="chart-callout" style={{ '--chart-callout': up ? FC_FORECAST : FC_ACTUAL }}>
        <span className="chart-callout-period">{formatMonth(row.period)}</span>
        <strong className="chart-callout-value">{signedPesos(row.variance)}</strong>
        <span className="chart-callout-name">Forecast too {up ? 'high' : 'low'}{share ? ` · ${share}% of sales` : ''}</span>
        <span className="chart-callout-line">Forecast {exactPesos(row.forecast)} · sold {exactPesos(row.actual)}</span>
      </div>
      <p className="chart-tooltip-placeholder chart-tooltip-note">Risk of too {up ? 'much' : 'little'} stock that month.</p>
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


export const ForecastErrorSummaryCard = ({ accuracy, scope, onOpenList, onOpenCategories }) => {
  const [view, setView] = useState('lines');
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
  const over = accuracy.surplus_pesos ?? 0;
  const under = accuracy.shortage_pesos ?? 0;
  const missMax = Math.max(over, under, 1);
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

      {/* 2. The evidence: forecast against actual, month by month. */}
      {months.length > 0 && (
        <div className="fc-chart-block">
          <div className="fc-chart-head">
            <div>
              <p className="fc-chart-title">Forecast vs. Actual Sales</p>
              <SectionLede>The forecast against what really sold</SectionLede>
              <p className="fc-chart-sub">Monthly comparison · pesos at {String(accuracy.pesos_basis || '').split(' (')[0]}</p>
            </div>
            <div className="fc-chart-tools">
              {/* Every view's key laid in one cell, the current one shown
                  (the others keep their space, unseen): the header keeps the
                  tallest key's height, so switching views never moves the
                  card or the one beside it (2026-10-19). */}
              <div className="fc-legend-stack">
                <ul className={`fc-legend${view === 'lines' ? '' : ' is-reserved'}`} aria-label="Legend">
                  <li><span className="fc-legend-line" style={{ backgroundColor: FC_ACTUAL }} aria-hidden="true" />Actual sales</li>
                  <li><span className="fc-legend-line is-forecast" style={{ backgroundColor: FC_FORECAST }} aria-hidden="true" />Forecast</li>
                  <li><span className="fc-legend-band" style={{ backgroundColor: FC_FORECAST }} aria-hidden="true" />Forecast too high</li>
                  <li><span className="fc-legend-band" style={{ backgroundColor: FC_ACTUAL }} aria-hidden="true" />Forecast too low</li>
                </ul>
                <ul className={`fc-legend${view === 'bars' ? '' : ' is-reserved'}`} aria-label="Legend">
                  <li><span className="fc-legend-bar" style={{ backgroundColor: FC_FORECAST }} aria-hidden="true" />Forecast too high</li>
                  <li><span className="fc-legend-bar" style={{ backgroundColor: FC_ACTUAL }} aria-hidden="true" />Forecast too low</li>
                </ul>
              </div>
              <ChartViewToggle view={view} onChange={setView} options={FC_VIEWS} label="Forecast vs actual: lines, monthly miss or table" />
            </div>
          </div>
          {view === 'table' ? (
            // In the chart's own box, so the card is the same height in
            // both views; the table scrolls inside it.
            <div className="fc-chart fc-chart-table">
              <ChartTable columns={tableColumns} rows={months} caption="Forecast and actual sales by month, in pesos" />
            </div>
          ) : view === 'bars' ? (
            // The miss alone: one bar per month, forecast − actual, above
            // zero where the forecast was too high (violet), below where it
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
                    <Fade id="fc-miss-high" color={FC_FORECAST} to={BAR_FADE_FLOOR} />
                    <Fade id="fc-miss-low" color={FC_ACTUAL} to={BAR_FADE_FLOOR} flip />
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
                  <Tooltip content={<MonthlyMissTooltip />} cursor={{ fill: 'rgba(148, 163, 184, 0.12)' }} />
                  <ReferenceLine y={0} stroke="#98A2B3" />
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
                  {/* The miss, shaded between the lines: violet where the
                      forecast was too high, teal where too low. Recharts
                      draws an Area under every Line (its layer order). Neither
                      adds to the hover (tooltipType none): the note does. */}
                  <Area
                    type="monotone" dataKey="tooHigh" name="Forecast too high" fill={FC_FORECAST} fillOpacity={0.2}
                    stroke="none" dot={false} activeDot={false} isAnimationActive={false} tooltipType="none" legendType="none"
                  />
                  <Area
                    type="monotone" dataKey="tooLow" name="Forecast too low" fill={FC_ACTUAL} fillOpacity={0.2}
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
        <div className="fc-miss-cards">
          {[
            { key: 'over', label: 'Forecast too high', note: 'Forecast above sales — risk of too much stock', value: over, color: COLORS.forecast },
            { key: 'under', label: 'Forecast too low', note: 'Sales above forecast — risk of too little stock', value: under, color: CHART_COLORS.salesSeries },
          ].map((b) => (
            <div className="fc-miss-card" key={b.key}>
              <span className="fc-miss-name">{b.label}</span>
              <span className="fc-miss-value">{formatCompactPesos(b.value)}</span>
              {soldTotal && (
                <span className="fc-miss-share">
                  <HoverShare value={b.value} sold={soldTotal} label={b.label} />
                </span>
              )}
              <span className="fc-miss-note">{b.note}</span>
              {/* The two bars share one scale (the larger total), so their
                  lengths compare across the cards. */}
              <div
                className="fc-miss-track"
                role="img"
                aria-label={`${b.label}: ${formatCompactPesos(b.value)}, ${b.note}`}
              >
                <span style={{ width: `${(b.value / missMax) * 100}%`, backgroundColor: b.color }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 4. The takeaway: the products to review, with their list. */}
      {runs.count > 0 && (
        <button type="button" className="fc-action" onClick={onOpenList}>
          <span>
            <strong>{runs.count.toLocaleString()} products</strong> had forecasts that were too high {runs.run_months} or
            more months in a row — check them before ordering
          </span>
          <ArrowRight size={14} aria-hidden="true" />
        </button>
      )}
      {/* Accuracy one level up (Technical Adviser, 2 Oct 2026: "at category
          and total level"): the same scored rows summed per category, in
          pieces and pesos (GET /dashboard/accuracy?level=category). */}
      {onOpenCategories && (
        <button type="button" className="fc-action fc-action-quiet" onClick={onOpenCategories}>
          <span>See where the misses went, <strong>category by category</strong></span>
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
  { key: 'products', label: 'Products', render: (r) => (r.products ?? 0).toLocaleString() },
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

// One side (2026-10-19, after the mockup): a tinted header band — green for
// the ones that joined, red for the ones that left — then the products in
// the payload's own order, each with its change in revenue at the right.
// The full list scrolls inside the panel, so the card keeps its height.
const ChangeList = ({ title, tone, items, noun, onOpen }) => {
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
                name={item.product_name || item.category_path}
                code={item.sku_id}
                onOpen={item.sku_id && onOpen ? () => onOpen(item.sku_id) : undefined}
                openLabel="Open its forecast"
              />
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

export const ClassChanges = ({ changes, onOpen }) => {
  if (!changes?.principals?.length) return null;
  const names = { unilever: 'Unilever', delmonte: 'Del Monte' };
  const multi = changes.principals.length > 1;
  return (
    <CardShell
      title="Changes in the top sellers"
      lede="Where changes happened"
      lead={`${changes.label}, compared with ${changes.compare_label}. `
        + 'The amount beside each product is the change in its revenue between the two periods.'}
    >
      {changes.principals.map((p) => {
        const noun = p.grain === 'sku' ? 'products' : 'categories';
        return (
          <div key={p.principal} className="range-change-block">
            {multi && <span className="pending-card-label">{names[p.principal] || p.principal}</span>}
            {p.blocked_reason ? <p className="range-blocked">{p.blocked_reason}</p> : (
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
                  <ChangeList title="Joined the top sellers" tone="up" items={byChange(p.entered || [])} noun={noun} onOpen={onOpen} />
                  <ChangeList title="Left the top sellers" tone="down" items={byChange(p.left || [])} noun={noun} onOpen={onOpen} />
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

// One row per product: its estimated pesos summed over the range's months.
export const productSalesTotals = (rows = []) => {
  const byProduct = new Map();
  for (const r of rows) {
    const key = r.product_key ?? r.sku_id;
    const entry = byProduct.get(key) || {
      product_key: r.product_key, sku_id: r.sku_id, product_name: r.product_name, pesos: 0, months: new Set(),
    };
    if (r.pesos != null) entry.pesos += r.pesos;
    entry.months.add(r.period);
    byProduct.set(key, entry);
  }
  return [...byProduct.values()]
    .map((e) => ({ ...e, months: e.months.size }))
    .sort((a, b) => b.pesos - a.pesos);
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
