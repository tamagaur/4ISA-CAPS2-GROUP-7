// The arithmetic the dashboard's five KPI cards do on GET /dashboard's own
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

// The year so far against the allocation (2026-10-18 redesign). "Expected"
// follows last year's own pattern: the same months' sales a year earlier ×
// the chosen level (Thea's decision A, 2026-10-18), so a slow first quarter
// last year lowers it too; it is null unless both years have the same number
// of months on record. `monthsLeft` is the calendar months after the latest
// one; `perMonthNeeded` is what the rest of the year needs to reach the target.
export function allocationPace({ ytdSales, ytdMonths, priorYtdSales, priorYtdMonths, pct, target, monthsLeft }) {
  const ytd = num(ytdSales);
  const months = num(ytdMonths);
  if (ytd == null || months == null || months <= 0) return null;
  const prior = num(priorYtdSales);
  const level = num(pct);
  const t = num(target);
  const left = num(monthsLeft);
  const expected = prior != null && prior > 0 && level != null && num(priorYtdMonths) === months
    ? (prior * level) / 100 : null;
  const reached = t != null && ytd >= t;
  return {
    expected,
    gap: expected != null ? ytd - expected : null,
    share: t != null && t > 0 ? ytd / t : null,
    reached,
    perMonthNeeded: t != null && !reached && left != null && left > 0 ? (t - ytd) / left : null,
  };
}

// Stock cover against the policy, in weeks: the part the policy needs and
// what is past it, or how far short it falls.
export function coverSplit(weeks, policyWeeks) {
  const w = num(weeks);
  const p = num(policyWeeks);
  if (w == null || w < 0 || p == null || p <= 0) return null;
  return { needed: Math.min(w, p), extra: Math.max(w - p, 0), short: Math.max(p - w, 0) };
}

// The cover ratio in words, for the pill beside the weeks: within 10% of the
// policy is on target; past it, the nearest half ("About double the target"
// at 2.07×). Above the target is a warning (trapped capital, the problem the
// DSD exists for), below it a risk.
export function coverVerdict(ratio) {
  const r = num(ratio);
  if (r == null || r < 0) return null;
  if (r < 0.9) return { text: 'Below the target', tone: 'negative' };
  if (r <= 1.1) return { text: 'On target', tone: 'positive' };
  if (r < 1.25) return { text: 'A little above the target', tone: 'warning' };
  const half = Math.round(r * 2) / 2;
  const words = { 2: 'About double the target', 3: 'About triple the target' };
  return { text: words[half] || `About ${half}× the target`, tone: 'warning' };
}

// Money in stock past the policy's weeks of cover (Stock cover card, "tied
// up"): the share of the stock value beyond `policyWeeks`, i.e. stock − policy
// weeks × average weekly sales, with weekly sales worked back as stock ÷ weeks.
// No backend field holds it; it is the cover's own two figures rearranged, so
// the card shows it as an estimate. Null at or below the policy, or without
// both figures.
export function excessAbovePolicy(stockValue, weeks, policyWeeks) {
  const s = num(stockValue);
  const w = num(weeks);
  const p = num(policyWeeks);
  if (s == null || w == null || p == null || s < 0 || w <= 0 || p <= 0 || w <= p) return null;
  return (s * (w - p)) / w;
}

// Class A products: below safety stock, at or above it, and those the plan
// can't check (no safety stock, or no stock count). Null when the counts
// can't be split honestly.
export function classAChecks({ all, checked, below }) {
  const a = num(all);
  const c = num(checked);
  const b = num(below);
  if (a == null || c == null || b == null || b < 0 || c < b || a < c) return null;
  return { below: b, ok: c - b, unchecked: a - c };
}

// The colour of a change in stock depends on where cover stands: more stock
// is bad when cover is already above the policy, good when it is below.
// Without a cover figure (or a flat change) it is neutral.
export function stockChangeTone(pct, coverRatio) {
  const p = num(pct);
  const r = num(coverRatio);
  if (p == null || p === 0 || r == null) return 'neutral';
  if (r > 1.1) return p > 0 ? 'negative' : 'positive';
  if (r < 0.9) return p > 0 ? 'positive' : 'negative';
  return 'neutral';
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
