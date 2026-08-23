// Backend GET /dashboard doesn't exist yet (another team member owns
// backend/). Once it does, replace this function's body with:
//   return apiFetch(`/dashboard?principal=${principal}`)
// Until then this resolves a local all-nulls stub after a short delay so
// the loading state is real and testable. This is the ONLY place that
// shape is defined — components must never import it directly, only
// call getDashboardData(), so swapping in the real call later is a
// one-file change.

// Last 12 calendar months as 'YYYY-MM', oldest first — matches the grain
// _period/calendar_month use everywhere else in this project.
function last12Periods() {
  const periods = [];
  const now = new Date();
  for (let i = 11; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    periods.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
  }
  return periods;
}

export async function getDashboardData({ principal }) {
  await new Promise((resolve) => setTimeout(resolve, 500));

  // weeks_of_cover here is null for every point, same reason as
  // inventory.weeks_of_cover below — no valuation column on
  // inventory_fact yet. Once the backend fills these in, the LAST entry
  // of cover_series and inventory.weeks_of_cover must be the same number
  // (same query, same period) so the chart and the "Stock above policy"
  // KPI card can never disagree — that invariant is enforced by having
  // both come from this one response, not by any client-side check.
  const cover_series = last12Periods().map((period) => ({ period, weeks_of_cover: null }));

  return {
    principal: principal || 'all',
    period: null,
    inventory: { value: null, weeks_of_cover: null, policy_weeks: 3 },
    recommendations: { order_value: null, product_count: 0 },
    forecast: { unreliable_count: null, total_count: 0 },
    cover_series,
  };
}
