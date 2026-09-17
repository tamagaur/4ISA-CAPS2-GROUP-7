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
