// Dashboard cards on the data marts' range answers (DEC-36, 2026-10-04/05):
// idle stock, the forecast's miss against sales, and the products that
// entered or left Class A. Each figure states its period and its basis, and
// the products behind it are one click away (Technical Adviser, 2 Oct 2026:
// detail behind every aggregate). The figures are GET /dashboard's (or the
// range route's) as served; nothing here recomputes one.
import React, { useState } from 'react';
import { ArrowDownRight, ArrowRight, ArrowUpRight, X } from 'lucide-react';
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import Modal from './Modal';
import ProductName from './ProductName';
import InfoTip from './InfoTip';
import MonthTick, { MONTH_TICK_EXTRA_HEIGHT, monthName } from './MonthTick';
import { ChartTable, ChartViewToggle } from './ChartTable';
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
  isOpen, onClose, title, subtitle, columns, rows, loading, error, footnote, onOpenProduct, openLabel,
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
const CardShell = ({ title, lead, scope, children, blocked }) => (
  <div className={`chart-widget${blocked ? ' chart-widget-empty' : ''}`}>
    <div className="chart-header">
      <div className="chart-title-area">
        <h4>{title}</h4>
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

export const IdleStockCard = ({ idle, scope, onOpenList }) => {
  if (!idle) return null;
  const window = idle.window_start && idle.window_end
    ? `${formatMonth(idle.window_start)} – ${formatMonth(idle.window_end)}`
    : `the last ${idle.window_rule_months} months`;
  const counted = idle.count_date ? `counted ${formatDate(idle.count_date)}`
    : idle.count_period ? `${formatMonth(idle.count_period)} count` : null;
  if (idle.blocked_reason) {
    return (
      <CardShell title="Idle stock" blocked>
        <p className="range-blocked">{idle.blocked_reason}</p>
      </CardShell>
    );
  }
  return (
    <CardShell
      title="Idle stock"
      scope={scope}
      lead={`Products on hand in the stock ${counted || 'count'} that sold nothing in ${window}.`}
    >
      <div className="range-stat-row">
        <Stat label="Products" value={idle.products.toLocaleString()} sub={`${idle.never_sold.toLocaleString()} never sold`} />
        <Stat
          label="Stock value"
          value={formatCompactPesos(idle.pesos)}
          sub={`${idle.pesos_basis}${idle.products_with_value < idle.products
            ? ` · ${idle.products - idle.products_with_value} without a price, not in the sum` : ''}`}
        />
      </div>
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

const ForecastVsActualTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const up = row.variance >= 0;
  return (
    <div className="chart-tooltip">
      <p style={{ fontWeight: 700, margin: '0 0 0.25rem 0' }}>{formatMonth(row.period)}</p>
      <p className="chart-tooltip-row">
        <span className="chart-tooltip-swatch" style={{ backgroundColor: CHART_COLORS.salesSeries }} aria-hidden="true" />
        Actual sales: <strong>{exactPesos(row.actual)}</strong>
      </p>
      <p className="chart-tooltip-row">
        <span className="chart-tooltip-swatch" style={{ backgroundColor: COLORS.forecast }} aria-hidden="true" />
        Forecast: <strong>{exactPesos(row.forecast)}</strong>
      </p>
      <p className="chart-tooltip-row">
        Forecast {up ? 'above' : 'below'} sales by <strong>{formatCompactPesos(Math.abs(row.variance))}</strong>
        {row.actual > 0 ? ` (${up ? '+' : '−'}${Math.abs((row.variance / row.actual) * 100).toFixed(1)}%)` : ''}
      </p>
    </div>
  );
};

export const ForecastErrorSummaryCard = ({ accuracy, scope, onOpenList, onOpenCategories }) => {
  const [view, setView] = useState('chart');
  if (!accuracy) return null;
  if (accuracy.blocked_reason || !accuracy.products) {
    return (
      <CardShell title="Forecast accuracy" blocked>
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
    .map((m) => ({
      period: m.period,
      actual: m.actual_pesos,
      forecast: m.actual_pesos + m.net_miss_pesos,
      variance: m.net_miss_pesos,
    }));
  const over = accuracy.surplus_pesos ?? 0;
  const under = accuracy.shortage_pesos ?? 0;
  const missMax = Math.max(over, under, 1);
  const tableColumns = [
    { key: 'period', label: 'Month', align: 'left', format: (v) => formatMonth(v) },
    { key: 'actual', label: 'Actual sales (₱)', format: exactPesos },
    { key: 'forecast', label: 'Forecast (₱)', format: exactPesos },
    { key: 'variance', label: 'Forecast − actual (₱)', format: (v) => `${v >= 0 ? '+' : '−'}${exactPesos(Math.abs(v))}` },
  ];

  return (
    <div className="chart-widget fc-card">
      <div className="fc-head">
        <h4 className="fc-title">Forecast accuracy</h4>
        <span className="fc-period">{accuracy.label}</span>
      </div>
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
              <p className="fc-chart-sub">Monthly comparison · pesos at {String(accuracy.pesos_basis || '').split(' (')[0]}</p>
            </div>
            <div className="fc-chart-tools">
              <ul className="fc-legend" aria-label="Legend">
                <li><span className="fc-legend-line" style={{ backgroundColor: CHART_COLORS.salesSeries }} aria-hidden="true" />Actual sales</li>
                <li><span className="fc-legend-line is-forecast" style={{ backgroundColor: COLORS.forecast }} aria-hidden="true" />Forecast</li>
              </ul>
              <ChartViewToggle view={view} onChange={setView} label="Forecast vs actual: chart or table" />
            </div>
          </div>
          {view === 'table' ? (
            <ChartTable columns={tableColumns} rows={months} caption="Forecast and actual sales by month, in pesos" />
          ) : (
            <div
              className="fc-chart"
              role="img"
              aria-label={`Line chart of monthly actual sales and forecast in pesos, ${accuracy.label}. Use the Table view for the exact figures.`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={months} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke={CHART_COLORS.gridline} />
                  <XAxis
                    dataKey="period"
                    tickFormatter={monthName}
                    axisLine={false}
                    tickLine={false}
                    tick={<MonthTick fontSize={11} fill={CHART_COLORS.axisLabel} />}
                    minTickGap={12}
                    height={30 + MONTH_TICK_EXTRA_HEIGHT}
                  />
                  <YAxis
                    tickFormatter={(v) => formatCompactPesos(v)}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 11, fill: CHART_COLORS.axisLabel }}
                    width={56}
                    domain={[0, 'auto']}
                  />
                  <Tooltip content={<ForecastVsActualTooltip />} cursor={{ stroke: CHART_COLORS.gridline }} />
                  <Line
                    type="monotone" dataKey="actual" name="Actual sales" stroke={CHART_COLORS.salesSeries} strokeWidth={2.5}
                    dot={{ r: 2.5, fill: CHART_COLORS.salesSeries, strokeWidth: 0 }} activeDot={{ r: 5 }} isAnimationActive={false}
                  />
                  <Line
                    type="monotone" dataKey="forecast" name="Forecast" stroke={COLORS.forecast} strokeWidth={2.5}
                    strokeDasharray="6 4" dot={{ r: 2.5, fill: COLORS.forecast, strokeWidth: 0 }} activeDot={{ r: 5 }}
                    isAnimationActive={false}
                  />
                </LineChart>
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
        <div className="fc-miss-cards">
          {[
            { key: 'over', label: 'Forecast too high', note: 'Forecast above sales — risk of too much stock', value: over, color: COLORS.forecast },
            { key: 'under', label: 'Forecast too low', note: 'Sales above forecast — risk of too little stock', value: under, color: CHART_COLORS.salesSeries },
          ].map((b) => (
            <div className="fc-miss-card" key={b.key}>
              <span className="fc-miss-name">{b.label}</span>
              <span className="fc-miss-value">{formatCompactPesos(b.value)}</span>
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
            <strong>{runs.count.toLocaleString()} products</strong> were over-forecast for {runs.run_months} or more months
            in a row — review them
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
const LIST_PREVIEW = 6;

const ChangeList = ({ title, icon, items, onOpen }) => {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? items : items.slice(0, LIST_PREVIEW);
  return (
    <div className="pending-change-list">
      <span className="pending-card-label">{icon} {title} ({items.length})</span>
      {items.length === 0 ? <p className="pending-change-empty">None</p> : (
        <ul>
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
        <button type="button" className="range-card-action" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
    </div>
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

export const ClassChanges = ({ changes, onOpen }) => {
  if (!changes?.principals?.length) return null;
  const names = { unilever: 'Unilever', delmonte: 'Del Monte' };
  const multi = changes.principals.length > 1;
  return (
    <CardShell
      title="Class A changes"
      lead={`${changes.label} against ${changes.compare_label}: products that entered or left the top sellers, `
        + 'with the change in each one’s revenue between the two periods.'}
    >
      {changes.principals.map((p) => (
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
              <p className="range-note">
                Class A: {p.compare_class_a_count.toLocaleString()} → {p.class_a_count.toLocaleString()} {p.grain === 'sku' ? 'products' : 'categories'}
                {' '}({p.stayed_count.toLocaleString()} stayed). Entered: {formatCompactPesos(p.entered_compare_revenue)} →{' '}
                {formatCompactPesos(p.entered_revenue)}. Left: {formatCompactPesos(p.left_compare_revenue)} →{' '}
                {formatCompactPesos(p.left_revenue)}. Pesos at {p.pesos_basis}.
              </p>
              <div className="pending-change-grid">
                <ChangeList title="Entered Class A" icon={<ArrowUpRight size={12} aria-hidden="true" />} items={byChange(p.entered || [])} onOpen={onOpen} />
                <ChangeList title="Left Class A" icon={<ArrowDownRight size={12} aria-hidden="true" />} items={byChange(p.left || [])} onOpen={onOpen} />
              </div>
              <p className="range-source">{p.revenue_rule}</p>
            </>
          )}
        </div>
      ))}
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
