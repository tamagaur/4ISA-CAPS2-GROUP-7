// The arithmetic the dashboard's four KPI cards do on GET /dashboard's own
// figures (HeroKpis.jsx): a ratio, a share, a split. Nothing here is a new
// measurement, and every function answers null when the figure can't be
// formed, so a card draws "—" or no bar rather than a made-up 0.
// Tested by kpiMath.test.js (`npm test`).

const num = (value) => (value == null || Number.isNaN(Number(value)) ? null : Number(value));

// Weeks of cover ÷ the policy's weeks ("2.1× policy"), on the weeks figure
// as served (two decimals), not the one-decimal figure the card prints.
export function policyRatio(weeks, policyWeeks) {
  const w = num(weeks);
  const p = num(policyWeeks);
  if (w == null || p == null || p <= 0 || w < 0) return null;
  return w / p;
}

// Where the stock-cover meter ends, in whole weeks: far enough for the cover
// and for twice the policy, then on to the next even week, so the fill never
// ends flush with the track (6.2 weeks against a 3-week policy: 0 to 8).
export function coverScale(weeks, policyWeeks) {
  const w = num(weeks);
  if (w == null || w < 0) return null;
  const p = num(policyWeeks);
  const reach = Math.max(w, p != null && p > 0 ? p * 2 : 0);
  return Math.floor(reach / 2) * 2 + 2;
}

// part ÷ whole as a 0–1 share; null when there is no whole to divide by.
export function shareOf(part, whole) {
  const a = num(part);
  const b = num(whole);
  if (a == null || b == null || b <= 0 || a < 0) return null;
  return Math.min(a / b, 1);
}

// A share as a whole percentage. A share that is not zero never prints as
// "0%", and one that is not everything never prints as "100%".
export function formatPercent(share) {
  const s = num(share);
  if (s == null) return '—';
  if (s <= 0) return '0%';
  if (s >= 1) return '100%';
  const pct = Math.round(s * 100);
  if (pct < 1) return '<1%';
  if (pct > 99) return '>99%';
  return `${pct}%`;
}

// Pending plan rows by urgency. "Planned" is what is left of the pending
// count after the others, so the parts always add up to the total; when the
// counts disagree (more critical + urgent than pending) there is no honest
// split, and the answer is null.
export function urgencyParts({ pending, critical = 0, urgent = 0, noData = 0 }) {
  const total = num(pending);
  if (total == null || total <= 0) return null;
  const c = num(critical) ?? 0;
  const u = num(urgent) ?? 0;
  const n = num(noData) ?? 0;
  const planned = total - c - u - n;
  if (c < 0 || u < 0 || n < 0 || planned < 0) return null;
  return [
    { key: 'critical', label: 'Critical', value: c },
    { key: 'urgent', label: 'Urgent', value: u },
    { key: 'planned', label: 'Planned', value: planned },
    // Shown only when there are any: a stock figure the plan could not read.
    ...(n > 0 ? [{ key: 'nodata', label: 'No stock data', value: n }] : []),
  ];
}

// A count in a few characters: 3,800,930 -> "3.8M", 356,287 -> "356.3K",
// 812 -> "812". The exact figure belongs in a tooltip beside it.
export function formatCompactCount(value) {
  const v = num(value);
  if (v == null) return '—';
  const abs = Math.abs(v);
  const sign = v < 0 ? '−' : '';
  if (abs >= 999_950) return `${sign}${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}${(abs / 1_000).toFixed(1)}K`;
  return `${sign}${Math.round(abs)}`;
}
