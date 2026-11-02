// One set of date formats for every table and label in the app:
//   formatDate      'Sep 14, 2026'
//   formatDateTime  'Sep 14, 2026, 10:32 AM'
//   formatMonth     'Mar 2026'   (a month-level period: planning cycle, ABC run)
// Chart axes keep their own compact 'Jan · 2026' tick style.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DATE_ONLY = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/;

// 'YYYY-MM-DD' and 'YYYY-MM' strings are read as calendar values, not
// parsed through Date(), which treats them as UTC midnight and can shift the
// day back by one in a negative-offset timezone.
export function formatDate(value) {
  if (!value) return '—';
  const m = DATE_ONLY.exec(String(value));
  if (m && m[3]) return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

export function formatDateTime(value) {
  if (!value) return '—';
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  return `${formatDate(d)}, ${time}`;
}

export function formatMonth(value) {
  if (!value) return '—';
  const m = DATE_ONLY.exec(String(value));
  if (m) return `${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  return String(value);
}

// 'YYYY-MM' months as runs of consecutive months, in words: "May–Jul 2024",
// "Oct 2024–Jan 2025", "Jun 2024"; several joined with commas and "and".
export function formatMonthSpans(periods = []) {
  const idx = (p) => { const [y, m] = String(p).split('-').map(Number); return y * 12 + m - 1; };
  const sorted = [...new Set(periods.map(String))].sort();
  const runs = [];
  sorted.forEach((p) => {
    const last = runs[runs.length - 1];
    if (last && idx(p) === idx(last[1]) + 1) last[1] = p; else runs.push([p, p]);
  });
  const words = runs.map(([a, b]) => {
    if (a === b) return formatMonth(a);
    const [ma, ya] = formatMonth(a).split(' ');
    return ya === formatMonth(b).split(' ')[1] ? `${ma}–${formatMonth(b)}` : `${formatMonth(a)}–${formatMonth(b)}`;
  });
  return words.length > 1 ? `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}` : words[0] || '';
}
