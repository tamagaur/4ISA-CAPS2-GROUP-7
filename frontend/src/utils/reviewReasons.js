// GET /recommendations' and GET /dashboard reorder_preview's review_reasons
// (review_flag) in a planner's words. Shared so the Reorder page and the
// Dashboard's Suggested orders say the same thing.
export const REVIEW_REASON_TEXT = {
  collapse: 'sales over the last 3 months fell below half the 12-month average',
  over_forecast_run: 'the forecast ran above sales 3 or more months in a row',
};

// "Check before ordering: <reason>; <reason>." A reason code without a text
// is shown as its code rather than dropped.
export const reviewReasonsSentence = (reasons = []) => {
  const parts = (reasons || []).map((r) => REVIEW_REASON_TEXT[r] || r);
  return parts.length ? `Check before ordering: ${parts.join('; ')}.` : 'Check before ordering.';
};
