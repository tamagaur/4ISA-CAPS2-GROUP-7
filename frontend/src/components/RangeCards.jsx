// Dashboard cards on the data marts' range answers (DEC-36, 2026-10-04/05):
// idle stock, the forecast's miss against sales, and the products that
// entered or left Class A. Each figure states its period and its basis, and
// the products behind it are one click away (Technical Adviser, 2 Oct 2026:
// detail behind every aggregate). The figures are GET /dashboard's (or the
// range route's) as served; nothing here recomputes one.
import React, { useState } from 'react';
import { ArrowDownRight, ArrowRight, ArrowUpRight, X } from 'lucide-react';
import Modal from './Modal';
import ProductName from './ProductName';
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
                <th scope="col" className="at-risk-col-product">Product</th>
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
      {idle.products > 0 && (
        <button type="button" className="range-card-action" onClick={onOpenList}>
          See the {idle.products.toLocaleString()} products <ArrowRight size={12} aria-hidden="true" />
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

// Forecast against sales over the range (GET /dashboard forecast_accuracy).
// Money first: how much the forecasts ran above and below sales, in pesos.
// The two percentages follow, each under the backend's own label, because
// one bare percentage hides which of the two is being quoted (3 Oct 2026).
export const ForecastErrorSummaryCard = ({ accuracy, scope, onOpenList }) => {
  if (!accuracy) return null;
  if (accuracy.blocked_reason || !accuracy.products) {
    return (
      <CardShell title="How far off were the forecasts?" blocked>
        <p className="range-blocked">{accuracy.blocked_reason || 'No forecasts were checked against sales in this range.'}</p>
      </CardShell>
    );
  }
  const runs = accuracy.over_forecast_runs || {};
  const levels = [accuracy.company_total, accuracy.typical_product_weighted].filter((l) => l && l.value != null);
  return (
    <CardShell
      title="How far off were the forecasts?"
      scope={scope}
      lead={`Forecasts against actual sales, ${accuracy.label}: ${accuracy.products.toLocaleString()} products, `
        + `${accuracy.product_months.toLocaleString()} product-months. Pesos at ${accuracy.pesos_basis}.`}
    >
      <div className="range-stat-row">
        <Stat label="Forecast above sales" value={formatCompactPesos(accuracy.surplus_pesos)} sub="surplus: stock bought that did not sell" />
        <Stat label="Forecast below sales" value={formatCompactPesos(accuracy.shortage_pesos)} sub="shortage: sales the stock could miss" />
      </div>
      {levels.length > 0 && (
        <ul className="range-levels">
          {levels.map((level) => (
            <li key={level.label}>
              <strong>{pct(level.value)}</strong> {level.label}
            </li>
          ))}
        </ul>
      )}
      {accuracy.possibly_stock_limited > 0 && (
        <p className="range-note">
          {accuracy.possibly_stock_limited.toLocaleString()} of the product-months may be stock-limited (stock may
          have run out), so their sales may understate demand.
        </p>
      )}
      {runs.count > 0 && (
        <button type="button" className="range-card-action" onClick={onOpenList}>
          {runs.count.toLocaleString()} products over-forecast {runs.run_months}+ months in a row <ArrowRight size={12} aria-hidden="true" />
        </button>
      )}
      <p className="range-source">
        {accuracy.forecast_source === 'backtest_recreated' ? 'Forecasts as made at the time (backtest)' : 'Stored forecast runs'}
        {accuracy.run_labels?.length ? `: ${accuracy.run_labels.join('; ')}` : ''}.
      </p>
    </CardShell>
  );
};

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
