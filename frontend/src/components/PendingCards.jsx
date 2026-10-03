// Cards and markers from the 3 Oct 2026 analysis (section B) whose data the
// backend does not serve yet. Each is built against the field names below
// and renders nothing until its field arrives, so wiring an endpoint later
// is a backend change only. /preview (PendingPreview.jsx) shows them all on
// labelled sample data.
//
// Field names these read — to be confirmed in the API contract:
//   GET /forecast (one SKU)
//     error_summary  { pieces_per_month, pesos_per_month, direction:
//                      'surplus' | 'shortage' | 'mixed', direction_months,
//                      months_scored, window_start, window_end }
//     accuracy       { product_pct, category_pct, total_pct }
//     actuals[].stock_limited   true where stock may have run out
//   GET /recommendations items[]
//     review_flag    why the row needs a look before ordering, else null
//     on_order_qty   pieces ordered and not yet arrived, else null
//   GET /dashboard
//     abc_changes    { period, previous_period,
//                      entered: [{ sku_id, product_name, revenue, previous_revenue }],
//                      left:    [{ … same … }] }
import React from 'react';
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Eye } from 'lucide-react';
import ProductName from './ProductName';
import { formatMonth } from '../utils/formatDate';
import { formatUnits } from '../utils/formatNumber';
import './PendingCards.css';

const WEEKS_PER_MONTH = 4.3;
const pesos = (value) => `₱${Math.round(value).toLocaleString('en-PH')}`;

// How far off the forecast is, in the units a buyer orders in and in money,
// with its direction — never as a bare percentage (no "WAPE" on screen).
const DIRECTION_TEXT = {
  surplus: 'Mostly surplus (the forecast ran above sales)',
  shortage: 'Mostly shortage (the forecast ran below sales)',
  mixed: 'No steady direction (above some months, below others)',
};
export const ForecastErrorCard = ({ error }) => {
  if (!error || error.pieces_per_month == null) return null;
  const perMonth = error.pieces_per_month;
  const window = error.window_start && error.window_end
    ? `${formatMonth(error.window_start)} – ${formatMonth(error.window_end)}`
    : null;
  return (
    <div className="pending-error-card">
      <span className="pending-card-label">Typical forecast miss</span>
      <p className="pending-error-line">
        Off by about <strong>{formatUnits(perMonth)} pieces</strong>
        {error.pesos_per_month != null && <> ({pesos(error.pesos_per_month)})</>} per month, or about{' '}
        <strong>{formatUnits(perMonth / WEEKS_PER_MONTH)} pieces</strong> per week.
      </p>
      {DIRECTION_TEXT[error.direction] && (
        <p className="pending-error-direction">
          {DIRECTION_TEXT[error.direction]}
          {error.direction !== 'mixed' && error.direction_months != null && error.months_scored != null
            ? ` for ${error.direction_months} of ${error.months_scored} months` : ''}
          {window ? ` · tested on ${window}` : ''}.
        </p>
      )}
    </div>
  );
};

// Accuracy colours. The cut-offs are the team's own choice, and the legend
// says so rather than presenting them as a standard.
export const ACCURACY_THRESHOLDS = { good: 15, fair: 30 };
const accuracyTier = (pct) => (pct <= ACCURACY_THRESHOLDS.good ? 'good' : pct <= ACCURACY_THRESHOLDS.fair ? 'fair' : 'poor');
export const AccuracyChip = ({ pct, label }) => {
  if (pct == null) return null;
  return (
    <span className={`pending-accuracy-chip is-${accuracyTier(pct)}`}>
      {label ? `${label}: ` : ''}{pct.toFixed(1)}% off
    </span>
  );
};
export const AccuracyLegend = () => (
  <span className="pending-accuracy-legend">
    <span className="pending-accuracy-dot is-good" aria-hidden="true" /> up to {ACCURACY_THRESHOLDS.good}%
    <span className="pending-accuracy-dot is-fair" aria-hidden="true" /> {ACCURACY_THRESHOLDS.good}–{ACCURACY_THRESHOLDS.fair}%
    <span className="pending-accuracy-dot is-poor" aria-hidden="true" /> over {ACCURACY_THRESHOLDS.fair}%
    <em>team-chosen thresholds</em>
  </span>
);
// The same miss at three levels: one product is noisy, a category less so,
// the total least — a single percentage hides which is being quoted.
export const AccuracyLevels = ({ accuracy }) => {
  if (!accuracy) return null;
  const levels = [['This product', accuracy.product_pct], ['Its category', accuracy.category_pct], ['All products', accuracy.total_pct]]
    .filter(([, pct]) => pct != null);
  if (!levels.length) return null;
  return (
    <div className="pending-accuracy-levels">
      {levels.map(([label, pct]) => <AccuracyChip key={label} label={label} pct={pct} />)}
      <AccuracyLegend />
    </div>
  );
};

// A recommendation that needs a person's eye before it is ordered (a sudden
// collapse in sales, a likely big miss). Flagged rows are left out of
// "Accept all in view" by the page that shows this.
export const ReviewBadge = ({ reason }) => {
  if (!reason) return null;
  return (
    <span className="pending-review-badge" title={reason}>
      <Eye size={11} aria-hidden="true" /> Review before ordering
    </span>
  );
};

// A month where stock may have run out, so its sales may understate demand.
export const STOCK_LIMITED_TEXT = 'stock may have run out; sales may understate demand';
export const StockLimitedNote = ({ periods = [] }) => {
  if (!periods.length) return null;
  return (
    <p className="pending-stock-limited">
      <AlertTriangle size={12} aria-hidden="true" />
      <span>
        <strong>Possibly stock-limited: {periods.map((p) => formatMonth(p)).join(', ')}</strong> — {STOCK_LIMITED_TEXT}.
      </span>
    </p>
  );
};

// Which products entered or left Class A between two ABC runs, with the
// change in each one's revenue.
const ChangeList = ({ title, icon, items, onOpen }) => (
  <div className="pending-change-list">
    <span className="pending-card-label">{icon} {title} ({items.length})</span>
    {items.length === 0 ? <p className="pending-change-empty">None</p> : (
      <ul>
        {items.map((item) => {
          const delta = item.revenue != null && item.previous_revenue != null ? item.revenue - item.previous_revenue : null;
          return (
            <li key={item.sku_id || item.product_name}>
              <ProductName
                name={item.product_name}
                code={item.sku_id}
                onOpen={item.sku_id && onOpen ? () => onOpen(item.sku_id) : undefined}
              />
              {delta != null && (
                <span className={`pending-change-delta ${delta >= 0 ? 'is-up' : 'is-down'}`}>
                  {delta >= 0 ? '+' : '−'}{pesos(Math.abs(delta))}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    )}
  </div>
);
export const ClassChanges = ({ changes, onOpen }) => {
  if (!changes || (!changes.entered && !changes.left)) return null;
  const span = changes.previous_period && changes.period
    ? `${formatMonth(changes.previous_period)} to ${formatMonth(changes.period)}`
    : null;
  return (
    <div className="chart-widget pending-class-changes">
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Class A changes</h4>
          <p>
            Products that entered or left the top sellers{span ? `, ${span}` : ''}, with the change in each
            one&apos;s monthly revenue (₱).
          </p>
        </div>
      </div>
      <div className="pending-change-grid">
        <ChangeList title="Entered Class A" icon={<ArrowUpRight size={12} aria-hidden="true" />} items={changes.entered || []} onOpen={onOpen} />
        <ChangeList title="Left Class A" icon={<ArrowDownRight size={12} aria-hidden="true" />} items={changes.left || []} onOpen={onOpen} />
      </div>
    </div>
  );
};
