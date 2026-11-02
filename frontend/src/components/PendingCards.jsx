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
// ForecastErrorCard's `error` (SKUForecast.jsx productAccuracy):
//   { pieces_per_month, pesos_per_month, pesos_basis, direction: 'surplus' |
//   'shortage' | 'mixed' (the net miss's sign), over_months, under_months,
//   months_scored, window_start, window_end, source, share_of_forecast }
//   share_of_forecast: the summed miss ÷ the summed forecast over the same
//   rows (a fraction), or null when the forecasts sum to 0.
import React from 'react';
import { AlertTriangle, Eye } from 'lucide-react';
import { formatMonth, formatMonthSpans } from '../utils/formatDate';
import { formatUnits } from '../utils/formatNumber';
import { formatExactPesos } from '../utils/formatters';
import InfoTip from './InfoTip';
import './PendingCards.css';

const WEEKS_PER_MONTH = 4.3;
const pesos = formatExactPesos;

// How far off the forecast is, in the units a buyer orders in and in money,
// with its direction — never as a bare percentage (no "WAPE" on screen).
// Direction is the sign of the net miss over the months scored, the
// backend's own rule; the months that ran each way are said beside it.
const DIRECTION_TEXT = {
  surplus: 'Overall above sales (a net surplus)',
  shortage: 'Overall below sales (a net shortage)',
  mixed: 'Above and below sales cancel out',
};
// `detailed` (Sales forecast's "Show details", 2026-10-20): the direction,
// months, source and pesos basis written out instead of behind a "?".
// `showShare` false leaves the percentage out where the page already says it
// (Sales forecast's "Typical miss" row beside the MASE, 2026-10-24).
export const ForecastErrorCard = ({ error, detailed = false, showShare = true }) => {
  if (!error || error.pieces_per_month == null) return null;
  const perMonth = error.pieces_per_month;
  const share = showShare ? error.share_of_forecast : null;
  const window = !error.window_start || !error.window_end ? null
    : error.window_start === error.window_end ? formatMonth(error.window_start)
      : `${formatMonth(error.window_start)} – ${formatMonth(error.window_end)}`;
  return (
    <div className="pending-error-card">
      <span className="pending-card-label">How far off past forecasts were</span>
      <p className="pending-error-line">
        Off by about <strong>{formatUnits(perMonth)} pcs</strong>
        {error.pesos_per_month != null && <> ({pesos(error.pesos_per_month)})</>} per month, or about{' '}
        <strong>{formatUnits(perMonth / WEEKS_PER_MONTH)} pcs</strong> per week
        {share != null && <> &middot; <strong>~{Math.round(share * 100)}%</strong> of the forecast</>}
        .
        {/* The direction, months and source sit behind the "?" (2026-10-19),
            or written out under the line in a details section. */}
        {!detailed && <InfoTip label="About this forecast miss" size={12}>
          {share != null && (
            <>The percentage is the total miss divided by the total forecast over the months scored. </>
          )}
          {DIRECTION_TEXT[error.direction] ?? ''}
          {DIRECTION_TEXT[error.direction] && error.months_scored != null && error.over_months != null
            ? `: above sales in ${error.over_months} and below in ${error.under_months} of ${error.months_scored} `
              + `month${error.months_scored === 1 ? '' : 's'}`
            : ''}
          {window ? ` · ${window}` : ''}
          {error.source ? ` · ${error.source}` : ''}
          {error.pesos_per_month != null && error.pesos_basis ? ` · pesos at ${error.pesos_basis}` : ''}.
        </InfoTip>}
      </p>
      {detailed && (
        <p className="pending-error-direction">
          {share != null && 'The percentage is the total miss divided by the total forecast over the months scored. '}
          {DIRECTION_TEXT[error.direction] ?? ''}
          {DIRECTION_TEXT[error.direction] && error.months_scored != null && error.over_months != null
            ? `: above sales in ${error.over_months} and below in ${error.under_months} of ${error.months_scored} `
              + `month${error.months_scored === 1 ? '' : 's'}`
            : ''}
          {window ? ` · ${window}` : ''}
          {error.source ? ` · ${error.source}` : ''}
          {error.pesos_per_month != null && error.pesos_basis ? ` · pesos at ${error.pesos_basis}` : ''}.
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
export const STOCK_LIMITED_TEXT = 'stock may have run out';
export const StockLimitedNote = ({ periods = [] }) => {
  if (!periods.length) return null;
  return (
    <p className="pending-stock-limited">
      <AlertTriangle size={12} aria-hidden="true" />
      <span>
        <strong>Stock may have run out in {formatMonthSpans(periods)}</strong>.
      </span>
    </p>
  );
};
