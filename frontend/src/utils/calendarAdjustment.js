// The company calendar factor in plain words (2026-10-19), one wording for
// every card that mentions it: the forecast card, the error card, the order
// plan's cards and the SKU Forecast page. Kelvin's analytics/forecasting/
// calendar.py multiplies each served forecast by how that calendar month has
// sold against the 3 months before it in earlier years (company total),
// halfway toward no change. Every figure comes from the API: GET /dashboard's
// portfolio_forecast.calendar_adjustment, or a forecast row's model_params
// (calendar_factor, calendar_years, value_before_calendar).

// "×1.0762 (+7.6%)", or "×0.95–1.10" across products with different factors.
export function calendarFactorText({ factor = null, factor_min: min = null, factor_max: max = null } = {}) {
  if (factor != null) {
    const pct = (factor - 1) * 100;
    return `×${factor.toFixed(4)} (${pct >= 0 ? '+' : '−'}${Math.abs(pct).toFixed(1)}%)`;
  }
  if (min != null && max != null) return `×${min.toFixed(2)}–${max.toFixed(2)}`;
  return null;
}

// "2 earlier years", "1–2 earlier years", or null.
export function calendarYearsText({ years = null, years_min: min = null, years_max: max = null } = {}) {
  const word = (n) => (n === 1 ? 'year' : 'years');
  if (years != null) return `${years} earlier ${word(years)}`;
  if (min != null && max != null) return min === max ? `${min} earlier ${word(min)}` : `${min}–${max} earlier years`;
  return null;
}

// The sign-off clause: a method change the technical adviser has not
// approved yet (analytics.params.CALENDAR_FACTOR_SIGNED_OFF). Empty once he
// has. Worded as the app's other open decision is (TierBasisLabel.jsx's
// "team decision, adviser sign-off pending"): the dashboard is SSM's, so it names the
// role, not the person.
export const CALENDAR_PENDING = 'a team decision, adviser sign-off pending';
export function calendarSignoffText(signedOff) {
  return signedOff === false ? CALENDAR_PENDING : '';
}

// What the adjustment is, for a "?" — the API's own sentence when sent.
export const CALENDAR_METHOD_FALLBACK = 'Each product’s forecast is multiplied by how that calendar month has sold against '
  + 'the 3 months before it in earlier years: the product’s own history, pulled toward the typical product’s, halfway '
  + 'toward no change; a month with no earlier year on record is left as it is. December takes last December’s '
  + 'typical-product dip in full when last December was a dip.';

// Why the adjustment can make older months worse (Kelvin, 2026-10-19): each
// month's factor is learned only from the same month in earlier years.
export const CALENDAR_HISTORY_NOTE = 'Each month’s adjustment is learned only from the same month in earlier '
  + 'years, so a month with fewer earlier years behind it (2024 and before) has less to learn from and can come out '
  + 'further off.';
