// Cards and markers from the 3 Oct 2026 analysis (section B). Since the
// kelvin-etl merge (2026-10-06) the backend serves their data:
//   ForecastErrorCard, StockLimitedNote  SKU Forecast, from GET /dashboard/
//                      accuracy?level=product (that product's rows)
//   ReviewBadge        Reorder Recs, from GET /recommendations needs_review +
//                      review_reasons
// Class A changes moved to RangeCards.jsx with its endpoint. AccuracyLevels
// stays held back (SHOW_ACCURACY_PCT, SKUForecast.jsx): no bare percentage
// on screen. /preview (PendingPreview.jsx) shows it on labelled sample data.
//
// ForecastErrorCard's `error`: { pieces_per_month, pesos_per_month,
//   direction: 'surplus' | 'shortage' | 'mixed', direction_months,
//   months_scored, window_start, window_end }
import React from 'react';
import { AlertTriangle, Eye } from 'lucide-react';
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
