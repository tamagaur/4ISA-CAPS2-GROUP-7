// The latest month with real sales data — the date picker's ceiling and the
// "today" every page's default range ends on (DateFilter.jsx,
// DashboardLayout.jsx). Unilever's demand runs 2023-01 to 2026-02 and Del
// Monte's sell-out 2023-01 to 2025-12, so the later of the two bounds the
// picker.
//
// Hard-coded, so it needs a manual edit when a new month of data loads —
// this is the ONE place to make it. GET /dashboard also returns the value
// as `latest_data_period` (task E3); reading it from there is the follow-up
// that retires this constant.
export const LATEST_DATA_PERIOD = { month: 'Feb', year: '2026' };

// First year of real data — both principals start in 2023-01.
export const FIRST_DATA_YEAR = 2023;
