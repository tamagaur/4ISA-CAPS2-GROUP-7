import React, { useEffect, useMemo, useState } from 'react';
import SectionLede from './ui/SectionLede';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { ArrowUpRight, ArrowDownRight, ArrowRight, Minus, X } from 'lucide-react';
import {
  Area,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
  Tooltip,
  ResponsiveContainer,
  ReferenceArea,
} from 'recharts';
import { getCategoryTrends } from '../api/analytics';
import { getRangePareto } from '../api/dashboard';
import { usePermissions } from '../permissions/context';
import { P } from '../permissions/keys';
import Modal from './Modal';
import ProductName from './ProductName';
import './AtRiskProductsModal.css';
import ExactValue from './ExactValue';
import { PAGE_NAMES, tierBadge, tierTechnical } from '../labels';
import { periodToParam } from '../periodFilter';
import { labelForPrincipal } from '../principals';
import { formatMonth } from '../utils/formatDate';
import { formatCompactPesos } from '../utils/formatters';
import { CHART_COLORS, COLORS } from '../theme/colors';
import { GRID_PROPS, pointLabels, seriesDot } from './ChartZoom';
import { ChartViewToggle } from './ChartTable';
import { isPlaceholderPeriod } from '../dataMode';
import { placeholderSpan, renderPlaceholderBand } from '../utils/placeholderBand';
import RefreshingNote from './RefreshingNote';
import InfoTip from './InfoTip';
import MonthTick, { MONTH_TICK_EXTRA_HEIGHT, monthName } from './MonthTick';
import PageHeader from './ui/PageHeader';
import { LoadingStatus, SkeletonChart, SkeletonLine, SkeletonTable } from './Skeleton';
import LoadError, { describeLoadError } from './ui/LoadError';
import SlowLoadNotice from './ui/SlowLoadNotice';
import './CategoryTrends.css';
import './GapNote.css';
import { gapLabel } from '../utils/gapReasons';

// formatCompactPesos is unsigned by design (callers such as "falling ₱42k a
// month" supply the direction in words). Revenue itself can be negative when
// returns outweigh sales in a month — Del Monte DAIRY, Apr 2025, read "₱925"
// for -₱925 — so revenue figures carry their own sign.
const formatRevenue = (value) => (value < 0 ? `−${formatCompactPesos(value)}` : formatCompactPesos(value));

// "What are the projected growth and decline trajectories for each product
// category over the coming year?" — the analytical mapping's P1, from GET
// /category-trends (analytics/forecasting/category_trend.py).
//
// A TREND projection, said as such everywhere: a Theil–Sen line through the
// last 24 months of revenue, extended 12 months, with Mann–Kendall deciding
// whether the direction is real. It answers "which way is this category
// heading and how fast", not "what will next month be" — that is the SKU
// forecast's job.

// The shared soft badges (ui.css): growing green, declining amber, no clear
// trend neutral — revenue direction has a valence, and the words carry it
// so colour is never the only signal.
const DIRECTION = {
  growing: { label: 'Growing', Icon: ArrowUpRight, className: 'badge-success' },
  declining: { label: 'Declining', Icon: ArrowDownRight, className: 'badge-warning' },
  flat: { label: 'No clear trend', Icon: Minus, className: 'badge-neutral' },
};
// One minus sign everywhere on the page (U+2212, as formatRevenue uses).
const MINUS = '\u2212';
const signed = (v) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? MINUS : ''}${Math.abs(v).toFixed(1)}%`);
// The exact peso figure for a hover: "₱97,385,224.18", "−₱925".
const exactPesos = (v) => (v == null ? null
  : `${v < 0 ? MINUS : ''}₱${Math.abs(v).toLocaleString('en-PH', { maximumFractionDigits: 2 })}`);
const exactSignedPesos = (v) => (v == null ? null : `${v >= 0 ? '+' : ''}${exactPesos(v)}`);
const signedPesos = (v) => (v == null ? '—' : `${v >= 0 ? '+' : MINUS}${formatCompactPesos(Math.abs(v))}`);

// The projected change in pesos, line against line (2026-10-25): the trend
// line's total over the next projection months (projected_12) minus its total
// over the last trailing months (the last `trailing` points of `fitted`),
// the same two sums the % compares (analytics/forecasting/category_trend.py
// _change_pct), so the ₱ and the % always agree. Both come from the payload.
const linePesoChange = (c, trailing) => {
  if (!c.available || c.projected_12 == null || !c.fitted?.length || !trailing) return null;
  const past = c.fitted.slice(-trailing).reduce((sum, v) => sum + v, 0);
  return past > 0 ? c.projected_12 - past : null;
};

// A category this small a share of the principal's revenue over the last 12
// months gets a "Small category" note, so a big % on a tiny base isn't
// over-read (the user's 1% rule, 2026-10-25).
const SMALL_CATEGORY_SHARE = 0.01;

// The Unilever bucket for products with no category (category_trends.py
// COALESCE(category_path, 'UNCLASSIFIED')).
const UNCLASSIFIED = 'UNCLASSIFIED';

// The trend's direction is "sure" when Mann–Kendall's p-value is below the
// method's significance level (the backend's own alpha).
const isSure = (c, method) => c.mk_p != null && method?.significance_alpha != null && c.mk_p < method.significance_alpha;
// The backend sends no % (and no range) when the trend line is already at
// zero over the last 12 months (analytics/forecasting/category_trend.py).
const NO_BASE_TEXT = 'The trend line is already at ₱0 over the last 12 months, so there is nothing to compare a '
  + 'projection with. Its direction is shown, but no change.';
const changeText = (c) => (c.change_pct == null ? '—' : `${signed(c.change_pct)} (${signed(c.change_pct_low)} to ${signed(c.change_pct_high)})`);
const pText = (p) => (p == null ? null : p < 0.001 ? 'p < 0.001' : `p = ${p.toFixed(3)}`);

// What a gap or zero month means, in plain words, for the notes under the
// chart (2026-10-25): a short line on screen and the technical detail
// behind its "?". Shown only for kinds of month the selected category has.
// The backend's own text (gap_note) carries internal codes, so it is not
// printed here; this restates it.
const MONTH_NOTES = {
  no_sale: {
    text: 'Months with no sales are shown as ₱0.',
    tip: 'A month with no sales row between the first and last sale means the products sold nothing that month. '
      + 'This is provisional until SSM confirms its sales listing leaves out zero-sale months.',
  },
  returns_exceeded_sales: {
    text: 'In some months returns matched or exceeded sales, so net revenue is shown as ₱0.',
    tip: 'The category had sales rows those months, but returns cancelled them out. Different from a month with '
      + 'no sales at all.',
  },
  category_absent: {
    text: 'Some months this category wasn’t reported while others were; they are left empty, not zero.',
    tip: 'The cause is unknown, so those months are not read as zero sales.',
  },
  not_collected: {
    text: 'Some months no category was reported at all; they are left empty, not zero.',
    tip: 'A collection failure: nothing was received for those months, so no value is filled in.',
  },
};
const MonthNotes = ({ category, skippedMonths = [] }) => {
  const codes = new Set((category?.history || []).map((h) => h.reason).filter(Boolean));
  if (skippedMonths.length) codes.add('not_collected');
  const shown = Object.keys(MONTH_NOTES).filter((k) => codes.has(k));
  if (!shown.length) return null;
  return (
    <div className="gap-note ct-month-notes" role="note">
      {shown.map((k) => (
        <p key={k}>
          {MONTH_NOTES[k].text}
          {k === 'not_collected' && skippedMonths.length > 0 && ` (${skippedMonths.map((m) => formatMonth(m.period)).join(', ')})`}
          <InfoTip label="About these months" size={12}>{MONTH_NOTES[k].tip}</InfoTip>
        </p>
      ))}
    </div>
  );
};

// The trend in plain words, under the pop-up's chart (2026-10-25).
const TREND_SENTENCE = {
  growing: 'Growing: revenue has been rising steadily.',
  declining: 'Declining: revenue has been falling.',
  flat: 'No clear trend: revenue goes up and down with no steady direction.',
};

// The Trend badge's pop-up: the category's monthly revenue with the fitted
// trend line dashed on top, the first and last month under it, the highest
// and lowest month labelled, and one plain sentence. Drawn for the dark
// InfoTip bubble, so the lines are light. Every value is the payload's own
// (history, fitted); nothing is recomputed.
const POP_W = 240;
const POP_H = 112;
// The bottom padding holds the Low label's row, then the month labels.
const POP_PAD = { top: 12, right: 6, bottom: 26, left: 6 };
const TrendPopup = ({ category }) => {
  const history = category.history || [];
  const fitted = category.fitted || [];
  if (history.length < 2) return <span>{TREND_SENTENCE[category.direction] ?? ''}</span>;
  const values = history.map((h) => h.revenue ?? 0);
  const offset = history.length - fitted.length;
  const all = [...values, ...fitted];
  // Scaled to the series' own range (not from ₱0), so the shape fills the
  // chart; the High and Low labels carry the actual levels.
  const max = Math.max(...all);
  const min = Math.min(...all);
  const span = max - min || 1;
  const iw = POP_W - POP_PAD.left - POP_PAD.right;
  const ih = POP_H - POP_PAD.top - POP_PAD.bottom;
  const x = (i) => POP_PAD.left + (i / (history.length - 1)) * iw;
  const y = (v) => POP_PAD.top + ih - ((v - min) / span) * ih;
  const line = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const trend = fitted.map((v, i) => `${x(i + offset).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const hi = values.indexOf(Math.max(...values));
  const lo = values.indexOf(Math.min(...values));
  // A label sits inside the chart: left-aligned near the left edge,
  // right-aligned near the right one.
  const anchor = (i) => (x(i) < 40 ? 'start' : x(i) > POP_W - 40 ? 'end' : 'middle');
  return (
    <span className="ct-trend-pop">
      <svg width={POP_W} height={POP_H} viewBox={`0 0 ${POP_W} ${POP_H}`} role="img"
        aria-label={`Monthly revenue, ${formatMonth(history[0].period)} to ${formatMonth(history[history.length - 1].period)}`}>
        <polyline points={line} fill="none" stroke="#7DD3C7" strokeWidth="1.6" strokeLinejoin="round" />
        {trend && <polyline points={trend} fill="none" stroke="#FFFFFF" strokeOpacity="0.9" strokeWidth="1.4" strokeDasharray="4 3" />}
        <circle cx={x(hi)} cy={y(values[hi])} r="2.5" fill="#7DD3C7" />
        <text x={x(hi)} y={y(values[hi]) - 4} textAnchor={anchor(hi)} className="ct-trend-pop-mark">
          {`High ${formatMonth(history[hi].period)}: ${formatRevenue(values[hi])}`}
        </text>
        {lo !== hi && (
          <>
            <circle cx={x(lo)} cy={y(values[lo])} r="2.5" fill="#7DD3C7" />
            <text x={x(lo)} y={y(values[lo]) + 11} textAnchor={anchor(lo)} className="ct-trend-pop-mark">
              {`Low ${formatMonth(history[lo].period)}: ${formatRevenue(values[lo])}`}
            </text>
          </>
        )}
        <text x={POP_PAD.left} y={POP_H - 3} textAnchor="start" className="ct-trend-pop-axis">{formatMonth(history[0].period)}</text>
        <text x={POP_W - POP_PAD.right} y={POP_H - 3} textAnchor="end" className="ct-trend-pop-axis">
          {formatMonth(history[history.length - 1].period)}
        </text>
      </svg>
      <span className="ct-trend-pop-legend">
        <i className="ct-trend-pop-key is-revenue" aria-hidden="true" />Monthly revenue
        <i className="ct-trend-pop-key is-trend" aria-hidden="true" />Trend line
      </span>
      <span className="ct-trend-pop-text">{TREND_SENTENCE[category.direction] ?? ''}</span>
    </span>
  );
};

// The products in one category (2026-10-25): GET /dashboard/pareto's ranking
// for the same 12 months the table's revenue covers, filtered to the
// category, highest revenue first, each with a link to its Sales forecast.
const CategoryProductsModal = ({ isOpen, onClose, category, products, rangeLabel, onOpenProduct }) => {
  if (!isOpen) return null;
  const rows = [...products].sort((a, b) => (b.revenue ?? 0) - (a.revenue ?? 0));
  const total = rows.reduce((sum, r) => sum + (r.revenue ?? 0), 0);
  return (
    <Modal isOpen={isOpen} onClose={onClose} labelledBy="ct-products-title" overlayClassName="at-risk-overlay" containerClassName="at-risk-card">
      <div className="at-risk-header">
        <div>
          <h3 id="ct-products-title" className="at-risk-title">{titleCase(category)}: its products</h3>
          <SectionLede>Who is behind this category</SectionLede>
          <p className="at-risk-subtitle">
            {rows.length.toLocaleString()} product{rows.length === 1 ? '' : 's'} with sales over {rangeLabel || 'the last 12 months'},
            {' '}{formatCompactPesos(total)} in all · highest revenue first
          </p>
        </div>
        <button type="button" className="at-risk-close" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="at-risk-money">No product in this category had sales over these months.</p>
      ) : (
        <div className="at-risk-table-wrap" tabIndex={0}>
          <table className="at-risk-table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col" className="at-risk-col-product">Product</th>
                <th scope="col">Seller</th>
                <th scope="col">
                  Revenue (₱)
                  <span className="at-risk-th-sub">{rangeLabel}</span>
                </th>
                <th scope="col"><span className="visually-hidden">Sales forecast</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item, i) => (
                <tr key={item.product_key ?? item.sku_id}>
                  <td>{i + 1}</td>
                  <td className="at-risk-col-product">
                    <ProductName
                      name={item.product_name || item.sku_id}
                      code={item.sku_id}
                      onOpen={onOpenProduct && item.sku_id ? () => onOpenProduct(item.sku_id) : undefined}
                      openLabel="Open its sales forecast"
                    />
                  </td>
                  <td title={tierTechnical(item.tier)}>{tierBadge(item.tier) || '—'}</td>
                  <td>{formatCompactPesos(item.revenue)}</td>
                  <td>
                    {onOpenProduct && item.sku_id && (
                      <button type="button" className="ct-link-btn" onClick={() => onOpenProduct(item.sku_id)}>
                        {PAGE_NAMES.forecast} <ArrowRight size={12} aria-hidden="true" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="at-risk-footer">
        <p className="at-risk-footnote">Revenue is the same ranking the Dashboard&apos;s top-seller list uses, for these months.</p>
        <div className="at-risk-actions">
          <button type="button" className="at-risk-btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </Modal>
  );
};
const titleCase = (name) => (name || '').toLowerCase().replace(/(^|[\s/&-])\S/g, (c) => c.toUpperCase());
// 'Mar 2025 – Feb 2026'; null when either end is missing.
const monthSpan = (start, end) => (start && end ? `${formatMonth(start)} – ${formatMonth(end)}` : null);
const axisMonth = (period) => {
  const [m, y] = (formatMonth(period) || '').split(' ');
  return y ? `${m} · ${y}` : period;
};

// The projection band's name (2026-10-25): the range of the TREND line, not
// of a single month, which varies more.
const BAND_LABEL = 'Likely range of the trend (single months will vary more)';
// The months the trend line is fitted over, shaded on the chart.
const FIT_LABEL = 'Months used to fit the trend';

// "Projection starts", and why the projection doesn't start at the last
// month's revenue: it continues the trend line (2026-10-25).
// Drawn at the foot of the line, on the projection's side, where the chart
// is empty (the history's lines run up to the line on its left).
const ProjectionStartLabel = ({ viewBox }) => {
  if (!viewBox) return null;
  const x = viewBox.x + 6;
  const y = viewBox.y + viewBox.height - 22;
  return (
    <g>
      <text x={x} y={y} textAnchor="start" fontSize={11} fill={CHART_COLORS.axisLabel}>Projection starts</text>
      <text x={x} y={y + 13} textAnchor="start" fontSize={10} fill={CHART_COLORS.axisLabel}>
        Follows the trend line, not the last month.
      </text>
    </g>
  );
};

const TrendTooltip = ({ active, payload, label, placeholder, rows = [] }) => {
  if (!active) return null;
  // A month with no value on any line (a Del Monte month the category didn't
  // report) has no payload; its row still says why.
  const p = payload?.[0]?.payload || rows.find((r) => r.period === label);
  if (!p) return null;
  return (
    <div className="ct-tooltip">
      <p className="ct-tooltip-title">{axisMonth(label)}</p>
      {p.reason && <p className="ct-tooltip-gap">{gapLabel(p.reason)}</p>}
      {p.actual != null && <p>Revenue: {formatRevenue(p.actual)}</p>}
      {p.actual == null && (p.reason === 'category_absent' || p.reason === 'not_collected') && <p>Revenue: not reported</p>}
      {p.fitted != null && <p>Trend line: {formatCompactPesos(p.fitted)}</p>}
      {p.projection != null && p.actual == null && <p>Projected trend: {formatCompactPesos(p.projection)}</p>}
      {p.bandLow != null && p.bandHigh != null && p.bandHigh > p.bandLow && p.actual == null && (
        <p>
          Likely range of the trend: {formatCompactPesos(p.bandLow)} – {formatCompactPesos(p.bandHigh)}
          <span className="ct-tooltip-sub"> (single months will vary more)</span>
        </p>
      )}
      {p.lastYear != null && <p>Same month last year: {formatRevenue(p.lastYear)}</p>}
      {p.inFit && <p className="ct-tooltip-sub">{FIT_LABEL}</p>}
      {isPlaceholderPeriod(label, placeholder) && <p className="ct-tooltip-placeholder">Sample data — not SSM&apos;s</p>}
    </div>
  );
};

// The chart's table view (2026-10-25), in two sections: the next 12 months
// as projected (the trend and its likely range), then the past months newest
// first (revenue, the trend line where it is fitted, and the change from the
// same month a year earlier). The months the trend line is fitted over carry
// a "Used for trend" tag. Each section's header row stays in view while the
// box scrolls. The values are the chart's own rows (CategoryChart's `data`).
const pctVsLastYear = (row) => (row.actual != null && row.lastYear != null && row.lastYear > 0
  ? ((row.actual - row.lastYear) / row.lastYear) * 100 : null);
const Pesos = ({ value, signedValue = false }) => (value == null ? '—' : (
  <ExactValue value={value} exact={signedValue ? exactSignedPesos(value) : exactPesos(value)} label="Exact figure">
    {signedValue ? signedPesos(value) : formatRevenue(value)}
  </ExactValue>
));
const CategoryTable = ({ category, data }) => {
  const projected = new Set(category.projection_periods || []);
  const ahead = data.filter((r) => projected.has(r.period));
  const past = data.filter((r) => !projected.has(r.period)).reverse();
  return (
    <div className="ct-table-view" tabIndex={0}>
      {ahead.length > 0 && (
        <>
          <p className="ct-table-view-title">Next {ahead.length} months (projected)</p>
          <table className="data-table ct-table-view-table">
            <caption className="visually-hidden">The trend projected over the next {ahead.length} months, in pesos</caption>
            <thead>
              <tr>
                <th scope="col">Month</th>
                <th scope="col" className="table-center">Projected trend (₱)</th>
                <th scope="col" className="table-center">
                  Likely range (₱)
                  <span className="ct-th-period">of the trend; single months vary more</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {ahead.map((r) => (
                <tr key={r.period}>
                  <td>{formatMonth(r.period)}</td>
                  <td className="table-center ct-num"><Pesos value={r.projection} /></td>
                  <td className="table-center ct-num">
                    {r.bandLow != null && r.bandHigh != null
                      ? <>{formatCompactPesos(r.bandLow)} – {formatCompactPesos(r.bandHigh)}</>
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <p className="ct-table-view-title">Past months</p>
      <table className="data-table ct-table-view-table">
        <caption className="visually-hidden">Monthly revenue and the trend line, newest first, in pesos</caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            <th scope="col" className="table-center">Revenue (₱)</th>
            <th scope="col" className="table-center">
              Trend line (₱)
              <span className="ct-th-period">&ldquo;—&rdquo; before the trend window</span>
            </th>
            <th scope="col" className="table-center">vs same month last year (%)</th>
          </tr>
        </thead>
        <tbody>
          {past.map((r) => (
            <tr key={r.period} className={r.inFit ? 'ct-row-fit' : ''}>
              <td>
                {formatMonth(r.period)}
                {r.inFit && <span className="ct-fit-tag">Used for trend</span>}
              </td>
              <td className="table-center ct-num">
                {r.actual != null ? <Pesos value={r.actual} /> : <span className="ct-muted">{r.reason ? gapLabel(r.reason) : '—'}</span>}
              </td>
              <td className="table-center ct-num">{r.fitted != null ? <Pesos value={r.fitted} /> : '—'}</td>
              <td className="table-center ct-num">{signed(pctVsLastYear(r))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// `placeholder` is the payload's data_mode.placeholder window — set only in
// preview mode (src/dataMode.js), so real mode draws no band. `method` is
// GET /category-trends' method block: every number this page states about
// the method comes from it, never from this file.
const CategoryChart = ({ category, method, placeholder = null }) => {
  const [view, setView] = useState('chart');
  const data = useMemo(() => {
    const history = category.history || [];
    const fitted = category.fitted || [];
    const offset = history.length - fitted.length;
    // The same month a year earlier, when the category reported it (a Del
    // Monte month it didn't report has no figure, not 0).
    const byPeriod = new Map(history
      .filter((h) => h.reason !== 'category_absent' && h.reason !== 'not_collected')
      .map((h) => [h.period, h.revenue]));
    const yearEarlier = (period) => `${Number(period.slice(0, 4)) - 1}${period.slice(4)}`;
    const lastYearOf = (period) => byPeriod.get(yearEarlier(period)) ?? null;
    const rows = history.map((h, i) => ({
      lastYear: lastYearOf(h.period),
      inFit: category.available && i >= offset,
      period: h.period,
      // A Del Monte month the category didn't report comes as 0 so the trend
      // can be fitted, but the backend says it is not zero sales
      // (category_absent / not_collected): the line breaks there instead of
      // dropping to 0. A Unilever no-sale month is a real 0 and stays.
      actual: h.reason === 'category_absent' || h.reason === 'not_collected' ? null : h.revenue,
      // Why the month is 0 or empty (backend/series_gaps.py), for the tooltip.
      reason: h.reason ?? null,
      fitted: i >= offset ? fitted[i - offset] : null,
      projection: null,
      bandLow: null,
      bandBase: null,
      bandSpanV: null,
      bandHigh: null,
    }));
    if (category.available && rows.length) {
      // Start the projection at the line's last value so it reads as one
      // line, and collapse the likely-range band to zero width there —
      // uncertainty is nil at the last known month and widens from it.
      const last = rows[rows.length - 1];
      last.projection = last.fitted;
      last.bandLow = last.bandHigh = last.fitted;
      last.bandBase = last.fitted;
      last.bandSpanV = 0;
      (category.projection_periods || []).forEach((period, i) => {
        // projection_low/high are the slope's confidence bounds extended
        // over the projection months (analytics/forecasting/
        // category_trend.py) — the backend's numbers, drawn as a band.
        const low = category.projection_low?.[i] ?? null;
        const high = category.projection_high?.[i] ?? null;
        rows.push({
          period,
          lastYear: lastYearOf(period),
          inFit: false,
          actual: null,
          fitted: null,
          projection: category.projection[i],
          bandLow: low,
          bandHigh: high,
          bandBase: low,
          bandSpanV: low != null && high != null ? high - low : null,
        });
      });
    }
    return rows;
  }, [category]);
  const bandSpan = placeholderSpan(data, placeholder);
  const hasRange = category.available && data.some((r) => (r.bandSpanV ?? 0) > 0);
  // The divider month: where history ends and the projection begins.
  const lastActualPeriod = category.available && (category.history || []).length
    ? category.history[category.history.length - 1].period
    : null;
  // The months the trend line is fitted over (the last `fitted.length` of
  // the history) and the months it is projected into, named for the legend.
  const history = category.history || [];
  const fittedCount = (category.fitted || []).length;
  const fitWindow = category.available && fittedCount && history.length >= fittedCount
    ? monthSpan(history[history.length - fittedCount].period, history[history.length - 1].period)
    : null;
  const projectionWindow = monthSpan(category.projection_periods?.[0], category.projection_periods?.[category.projection_periods.length - 1]);
  const fitStart = category.available && fittedCount && history.length >= fittedCount
    ? history[history.length - fittedCount].period : null;

  // One direct label: the projected level at the end of the trend line. The
  // last month's revenue is in the hover only (2026-10-25): its label sat on
  // top of the lines where history hands over to the projection.
  const projectionLabels = useMemo(() => {
    const end = [...data].reverse().find((r) => r.projection != null && r.actual == null);
    return pointLabels(data, end
      ? [{ period: end.period, text: `Trend ${formatCompactPesos(end.projection)}` }]
      : []);
  }, [data]);

  return (
    <div className="ct-chart">
      <div className="ct-chart-tools">
        <ChartViewToggle view={view} onChange={setView} label="Category trend: chart or table" />
      </div>
      {view === 'table' ? (
        <CategoryTable category={category} data={data} />
      ) : (
        <>
          {/* The key above the plot, as on the Sales forecast page (2026-10-25). */}
          <div className="ct-legend">
            <span><i className="ct-swatch ct-swatch-actual" />Monthly revenue</span>
            {category.available && (
              <span>
                <i className="ct-swatch ct-swatch-fitted" />Trend line, {fitWindow ?? `last ${category.points} months`}
              </span>
            )}
            {category.available && method && (
              <span>
                <i className="ct-swatch ct-swatch-projection" />Projected trend, {projectionWindow ?? `next ${method.projection_months} months`}
              </span>
            )}
            {hasRange && method && (
              <span title={`${Math.round(method.slope_confidence * 100)}% slope bounds`}>
                <i className="ct-swatch ct-swatch-band" />
                {BAND_LABEL}
              </span>
            )}
            {fitStart && <span><i className="ct-swatch ct-swatch-fit" />{FIT_LABEL}{fitWindow ? `, ${fitWindow}` : ''}</span>}
            {bandSpan && <span><i className="ct-swatch ct-swatch-placeholder" />Sample data — not SSM&apos;s</span>}
          </div>
          <ResponsiveContainer width="100%" height={340}>
            <ComposedChart data={data} margin={{ top: 10, right: 16, left: 4, bottom: 8 }}>
              <CartesianGrid {...GRID_PROPS} />
              {renderPlaceholderBand(bandSpan)}
              {/* The months the trend line is fitted over (2026-10-25). */}
              {fitStart && lastActualPeriod && (
                <ReferenceArea x1={fitStart} x2={lastActualPeriod} fill="#94A3B8" fillOpacity={0.1} stroke="none" ifOverflow="hidden" />
              )}
              {/* Axis titles say what each axis counts (Sir Catubag, 2 Oct
                  2026). The X axis is 40px tall so "Month" sits under the
                  ticks; the Y axis is 64px wide to fit "Revenue (₱)" left of
                  ticks like ₱1.2M. */}
              <XAxis
                dataKey="period"
                tickFormatter={monthName}
                minTickGap={24}
                tick={<MonthTick fill={CHART_COLORS.axisLabel} fontSize={11} />}
                height={40 + MONTH_TICK_EXTRA_HEIGHT}
                label={{ value: 'Month', position: 'insideBottom', offset: 0, fontSize: 11, fill: CHART_COLORS.axisLabel }}
              />
              <YAxis
                tickFormatter={formatRevenue}
                tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                width={64}
                label={{ value: 'Revenue (₱)', angle: -90, position: 'insideLeft', fontSize: 11, fill: CHART_COLORS.axisLabel }}
              />
              <Tooltip content={<TrendTooltip placeholder={placeholder} rows={data} />} />
              {/* The projection's likely range: an invisible base up to the
                  low bound, then the visible band on top of it (the same
                  stacking the portfolio forecast's cone uses), so the
                  shading covers exactly [low, high]. */}
              {hasRange && (
                <>
                  <Area dataKey="bandBase" stackId="ctBand" stroke="none" fill="transparent" isAnimationActive={false} />
                  <Area dataKey="bandSpanV" stackId="ctBand" stroke="none" fill={COLORS.forecast} fillOpacity={0.10} isAnimationActive={false} />
                </>
              )}
              {/* Where history hands over to the projected trend. */}
              {lastActualPeriod && (
                <ReferenceLine
                  x={lastActualPeriod}
                  stroke={CHART_COLORS.axisLabel}
                  strokeDasharray="4 4"
                  label={<ProjectionStartLabel />}
                />
              )}
              <Line dataKey="actual" name="Revenue" stroke={CHART_COLORS.salesSeries} strokeWidth={2} strokeLinecap="round" dot={seriesDot({ color: CHART_COLORS.salesSeries, r: 3 })} connectNulls={false} isAnimationActive={false} />
              <Line dataKey="fitted" name="Trend line" stroke={CHART_COLORS.cumulativeCurve} strokeWidth={1.5} strokeDasharray="3 3" dot={false} connectNulls={false} isAnimationActive={false} />
              <Line dataKey="projection" name="Projected trend" stroke={COLORS.forecast} strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls={false} isAnimationActive={false} label={projectionLabels} />
            </ComposedChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  );
};

const PrincipalSection = ({ section, method, placeholder = null }) => {
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  // The product list and the Unclassified count read GET /dashboard/pareto,
  // which needs the Dashboard's permission (not this page's): without it both
  // are left out and say why (2026-10-25).
  const canSeeProducts = hasPermission(P.DASHBOARD_VIEW);
  const canOpenForecast = hasPermission(P.FORECAST_VIEW);
  const canOpenProducts = hasPermission(P.SKU_VIEW);
  const isUnilever = section.principal === 'unilever';
  const categories = section.categories || [];
  const [selected, setSelected] = useState(() => categories.find((c) => c.available)?.category ?? categories[0]?.category);
  const current = categories.find((c) => c.category === selected) ?? categories[0];
  const observed = section.observed_months || [];
  const anyProjection = categories.some((c) => c.available);
  // The table's windows, from the payload: revenue sums the last
  // trailing_months OBSERVED months; every projected category shares the
  // same projection months (they continue from the last observed month).
  const trailing = method?.trailing_months ? observed.slice(-method.trailing_months) : [];
  const trailingWindow = trailing.length ? monthSpan(trailing[0], trailing[trailing.length - 1]) : null;
  const spanMonths = trailing.length
    ? (Number(trailing[trailing.length - 1].slice(0, 4)) * 12 + Number(trailing[trailing.length - 1].slice(5, 7)))
      - (Number(trailing[0].slice(0, 4)) * 12 + Number(trailing[0].slice(5, 7))) + 1
    : 0;
  const trailingGapNote = spanMonths > trailing.length ? ` (${trailing.length} months with data)` : '';
  const sharedProjection = categories.find((c) => c.projection_periods?.length)?.projection_periods || [];
  const projectionWindow = monthSpan(sharedProjection[0], sharedProjection[sharedProjection.length - 1]);
  const exactWindows = projectionWindow && trailingWindow ? `${projectionWindow} vs ${trailingWindow}` : null;
  const shortWindows = `Next ${method?.projection_months ?? 12} months vs last ${method?.trailing_months ?? 12}`;
  // Each category's share of the principal's revenue over the same months.
  const revenueTotal = categories.reduce((sum, c) => sum + Math.max(0, c.revenue_last_12 || 0), 0);
  const shareOf = (c) => (revenueTotal > 0 ? Math.max(0, c.revenue_last_12 || 0) / revenueTotal : null);

  // Unilever's products over the table's 12 months, ranked like the
  // Dashboard (GET /dashboard/pareto), for the product list and the
  // Unclassified count. Del Monte's rows are categories, so none.
  const rangeStart = trailing[0];
  const rangeEnd = trailing[trailing.length - 1];
  const [products, setProducts] = useState({ key: null, rows: [], label: null, total: null, error: null });
  const productsKey = isUnilever && canSeeProducts && rangeStart && rangeEnd ? `${rangeStart}|${rangeEnd}` : null;
  useEffect(() => {
    if (!productsKey) return undefined;
    let cancelled = false;
    getRangePareto({ period: rangeEnd, startPeriod: rangeStart, principal: 'unilever' })
      .then((res) => {
        if (cancelled) return;
        const block = (res.principals || []).find((p) => p.principal === 'unilever');
        const rows = (block?.classes || []).flatMap((cls) => (cls.products || []).map((p) => ({ ...p, tier: cls.tier })));
        setProducts({ key: productsKey, rows, label: res.label, total: block?.ranked_revenue ?? null, error: null });
      })
      .catch((err) => { if (!cancelled) setProducts({ key: productsKey, rows: [], label: null, total: null, error: err.message }); });
    return () => { cancelled = true; };
    // rangeStart / rangeEnd are read through productsKey.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productsKey]);
  const productsLoaded = productsKey != null && products.key === productsKey && !products.error;
  const productsIn = (name) => products.rows.filter((p) => (p.category_path || UNCLASSIFIED) === name);
  const [listFor, setListFor] = useState(null);

  return (
    <section className="ct-card">
      <div className="ct-card-header">
        <h3 className="ct-card-title">{labelForPrincipal(section.principal)}</h3>
        <SectionLede>Every category's direction at a glance</SectionLede>
        <p className="ct-card-subtitle">
          {observed.length
            ? `${observed.length} month${observed.length === 1 ? '' : 's'} with data, ${formatMonth(observed[0])} – ${formatMonth(observed[observed.length - 1])}.`
            : 'No revenue data loaded.'}
          {section.series_start &&
            ` Only months since ${labelForPrincipal(section.principal)} regrouped its categories in ${formatMonth(section.series_start)} count — the older sub-categories are different categories.`}
          {method && section.principal === placeholder?.principal && observed.some((m) => isPlaceholderPeriod(m, placeholder)) &&
            ` ${formatMonth(placeholder.start)} – ${formatMonth(placeholder.end)} is sample data, not SSM's.`
            + ` The trend line and projection use only the last ${method.window_months} months, all real, so they are the same as without it.`}
        </p>
      </div>
      {!anyProjection && categories.length > 0 && method && (
        <p className="ct-note">
          No category has the {method.min_points} months with data a projection needs yet, so this shows history only.
        </p>
      )}
      {categories.length > 0 && (
        <div className="data-table-card ct-table-card">
          <table className="data-table ct-table">
            <thead>
              <tr>
                <th>Category</th>
                {/* Each header names its months (Sir Catubag, 2 Oct
                    2026). The revenue window is the last trailing_months
                    months WITH data (category_trends.py sums observed
                    months), so for a principal with missing files it can
                    span more calendar months than its count. */}
                <th className="table-center ct-num">
                  Revenue (₱)
                  {/* GET /category-trends sums Unilever's product-months with
                      net sales above zero (backend/routers/category_trends.py),
                      the ABC ranking's rule, so the categories add up to more
                      than the Dashboard's net sales (₱392.7M against ₱391.1M
                      for Mar 2025 – Feb 2026, checked 2026-10-12). */}
                  {section.principal === 'unilever' && (
                    <InfoTip label="About these revenue figures">
                      A product&apos;s month where returns exceeded its sales is left out, as in the ABC ranking. The
                      categories therefore add up to slightly more than the Dashboard&apos;s sales total, which nets
                      every return.
                    </InfoTip>
                  )}
                  {trailingWindow
                    ? <span className="ct-th-period">{trailingWindow}{trailingGapNote}</span>
                    : <span className="ct-th-period">last {method?.trailing_months} months</span>}
                </th>
                <th className="table-center">Trend</th>
                <th className="table-center ct-num">
                  Projected change (%)
                  <InfoTip label="About this projection">
                    The trend line&apos;s total over the next {method?.projection_months} months
                    {projectionWindow ? ` (${projectionWindow})` : ''} against its total over the last {method?.trailing_months}
                    {trailingWindow ? ` (${trailingWindow})` : ''}. In brackets, the same with the slope&apos;s confidence bounds.
                    {' '}A category with no clear trend shows &ldquo;—&rdquo;: its projection isn&apos;t reliable.
                  </InfoTip>
                  <span className="ct-th-period">
                    {exactWindows
                      ? <InfoTip label="The months compared" trigger={shortWindows} triggerClassName="ct-th-trigger">{exactWindows}</InfoTip>
                      : shortWindows}
                  </span>
                </th>
                <th className="table-center ct-num">
                  Projected change (₱)
                  <InfoTip label="About the peso change">
                    The same comparison in pesos: the trend line&apos;s next {method?.projection_months} months minus its last{' '}
                    {method?.trailing_months}, so it always agrees with the percentage.
                  </InfoTip>
                  <span className="ct-th-period">
                    {exactWindows
                      ? <InfoTip label="The months compared" trigger={shortWindows} triggerClassName="ct-th-trigger">{exactWindows}</InfoTip>
                      : shortWindows}
                  </span>
                </th>
                <th className="table-center ct-num">
                  How sure is this trend?
                  <InfoTip label="About how sure the trend is">
                    Sure means the direction is unlikely to be chance: a Mann–Kendall test p-value below{' '}
                    {method?.significance_alpha}. Not sure means it could be noise. Each row&apos;s p-value is in its hover
                    and in &ldquo;Show details&rdquo;.
                  </InfoTip>
                </th>
              </tr>
            </thead>
            <tbody>
              {categories.map((c) => {
                const dir = DIRECTION[c.direction];
                const DirIcon = dir?.Icon;
                const clear = c.available && c.direction !== 'flat';
                const share = shareOf(c);
                const small = share != null && share < SMALL_CATEGORY_SHARE;
                const peso = linePesoChange(c, method?.trailing_months);
                const unclassified = isUnilever && c.category === UNCLASSIFIED;
                const unclassifiedCount = unclassified && productsLoaded ? productsIn(UNCLASSIFIED).length : null;
                const noTrendTip = c.available
                  ? `No clear direction, so this projection isn't reliable. The line says ${signed(c.change_pct)}`
                    + ` (${signed(c.change_pct_low)} to ${signed(c.change_pct_high)})${peso != null ? `, ${signedPesos(peso)}` : ''}.`
                  : null;
                return (
                  <tr
                    key={c.category}
                    className={c.category === current?.category ? 'ct-row-selected' : ''}
                    onClick={() => setSelected(c.category)}
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(c.category); } }}
                    aria-selected={c.category === current?.category}
                  >
                    <td className="ct-name">
                      {titleCase(c.category)}
                      {small && (
                        <InfoTip label="About small categories" trigger="Small category" triggerClassName="ct-small-tag" className="ct-small-tip">
                          {`${(share * 100).toFixed(2)}% of ${labelForPrincipal(section.principal)}'s revenue over these months: `
                            + 'a large % change here is a small amount of money.'}
                        </InfoTip>
                      )}
                      {unclassified && (
                        <span className="ct-unclassified-note">
                          Products without a category
                          {unclassifiedCount != null ? ` (${unclassifiedCount.toLocaleString()} with sales)` : ''}. Assign them in{' '}
                          {canOpenProducts ? (
                            <button
                              type="button"
                              className="ct-link-btn"
                              onClick={(e) => { e.stopPropagation(); navigate('/sku-management'); }}
                            >
                              {PAGE_NAMES.products}
                            </button>
                          ) : PAGE_NAMES.products}.
                        </span>
                      )}
                    </td>
                    <td className="table-center ct-num">
                      <ExactValue value={c.revenue_last_12} exact={exactPesos(c.revenue_last_12)} label="Exact revenue">
                        {formatRevenue(c.revenue_last_12)}
                      </ExactValue>
                    </td>
                    <td className="table-center">
                      {c.available ? (
                        <InfoTip
                          label={`${titleCase(c.category)}: trend`}
                          trigger={(
                            <span className={`badge ${dir.className}`}>
                              {DirIcon && <DirIcon size={12} aria-hidden="true" />}{dir.label}
                            </span>
                          )}
                          triggerClassName="ct-trend-trigger"
                          className="ct-trend-tip"
                        >
                          <TrendPopup category={c} />
                        </InfoTip>
                      ) : (
                        // The backend's own short status: "Not enough
                        // months" or "No recent sales".
                        <InfoTip label="Why there is no trend" trigger={<span className="badge badge-neutral">{c.label}</span>} triggerClassName="ct-trend-trigger" className="ct-trend-tip">
                          {c.reason}
                        </InfoTip>
                      )}
                    </td>
                    <td className="table-center ct-num">
                      {clear && c.change_pct == null ? (
                        <InfoTip label="Why there is no projected change" trigger="—" triggerClassName="ct-muted ct-dash">
                          {NO_BASE_TEXT}
                        </InfoTip>
                      ) : clear ? (
                        <>
                          <strong>{signed(c.change_pct)}</strong>
                          <span className="ct-range"> ({signed(c.change_pct_low)} to {signed(c.change_pct_high)})</span>
                        </>
                      ) : c.available ? (
                        <InfoTip label="Why there is no projected change" trigger="—" triggerClassName="ct-muted ct-dash">
                          {noTrendTip}
                        </InfoTip>
                      ) : (
                        <InfoTip label="Why there is no projected change" trigger="—" triggerClassName="ct-muted ct-dash">
                          {c.reason}
                        </InfoTip>
                      )}
                    </td>
                    <td className="table-center ct-num">
                      {clear && peso != null ? (
                        <strong>
                          <ExactValue value={peso} exact={exactSignedPesos(peso)} label="Exact peso change">{signedPesos(peso)}</ExactValue>
                        </strong>
                      ) : (
                        <InfoTip label="Why there is no peso change" trigger="—" triggerClassName="ct-muted ct-dash">
                          {clear ? NO_BASE_TEXT : c.available ? noTrendTip : c.reason}
                        </InfoTip>
                      )}
                    </td>
                    <td className="table-center ct-num">
                      {c.mk_p == null ? '—' : (
                        <InfoTip
                          label="How sure is this trend?"
                          trigger={isSure(c, method) ? 'Sure' : 'Not sure'}
                          triggerClassName="ct-sure-trigger"
                        >
                          {`Mann–Kendall ${pText(c.mk_p)}: ${isSure(c, method)
                            ? `below ${method.significance_alpha}, so the direction is unlikely to be chance.`
                            : `not below ${method.significance_alpha}, so the direction could be noise.`}`}
                        </InfoTip>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {current && (
        <div className="ct-detail">
          <h3 className="ui-card-title">{titleCase(current.category)}: past revenue and trend</h3>
          <SectionLede>
            {current.available
              ? `${current.slope_per_month >= 0 ? 'Rising' : 'Falling'} about ${formatCompactPesos(Math.abs(current.slope_per_month))} a month`
                + `${current.direction === 'flat' ? ', but not a steady direction' : ''}`
              : current.reason}
          </SectionLede>
          {isUnilever && canSeeProducts && (
            <button
              type="button"
              className="ct-products-btn"
              onClick={() => setListFor(current.category)}
              disabled={!productsLoaded}
            >
              {productsLoaded
                ? `See its ${productsIn(current.category).length.toLocaleString()} products`
                : products.error ? 'The product list couldn’t be loaded' : 'Loading its products…'}
              {productsLoaded && <ArrowRight size={13} aria-hidden="true" />}
            </button>
          )}
          {isUnilever && !canSeeProducts && (
            <p className="ct-note">The product list needs access to the Dashboard.</p>
          )}
          {!isUnilever && (
            <p className="ct-note">Del Monte&apos;s sales are recorded by category, so there is no product list.</p>
          )}
          <CategoryChart category={current} method={method} placeholder={placeholder} />
          {/* What this category's gap and zero months mean, in plain words. */}
          <MonthNotes category={current} skippedMonths={section.skipped_months || []} />
        </div>
      )}
      <CategoryProductsModal
        isOpen={listFor != null}
        onClose={() => setListFor(null)}
        category={listFor}
        products={listFor ? productsIn(listFor) : []}
        rangeLabel={products.label}
        onOpenProduct={canOpenForecast ? (sku) => navigate(`/forecast?sku=${encodeURIComponent(sku)}`) : null}
      />
    </section>
  );
};

const CategoryTrends = () => {
  const { principal, endMonth, endYear } = useOutletContext() || {};
  // The page follows the END of the shared date range (2026-10-12): trends
  // are fitted as of that month, on the months of sales up to it, and the
  // revenue column is the 12 months ending there. The range's START is
  // deliberately not sent: the fit needs up to 24 months and at least 12, so
  // a 6-month range would leave every category with too few points, and a
  // 12-month one would halve the history behind each trend.
  const period = periodToParam(endMonth, endYear) || undefined;
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  // Try again on a failed load re-runs the request.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, status: 'loading', error: null }));
    getCategoryTrends({ principal, period })
      .then((data) => { if (!cancelled) setState({ status: 'loaded', data, error: null }); })
      .catch((err) => { if (!cancelled) setState((prev) => ({ ...prev, status: 'error', error: describeLoadError(err) })); });
    return () => { cancelled = true; };
  }, [principal, period, attempt]);

  const data = state.data;
  return (
    <div className="ct-page">
      <div className="ct-content">
        <PageHeader
          title="Category"
          accent="trends"
          subtitle={`Monthly revenue by product category, and where its trend points${data?.method ? ` over the next ${data.method.projection_months} months.` : '.'}`}
        />

        {/* One principal card in the loaded order: header, the 5-column
            category table, then the selected category's 300px chart. */}
        {state.status === 'loading' && !data && (
          <>
            <LoadingStatus>Loading category trends…</LoadingStatus>
            <SlowLoadNotice />
            <section className="ct-card" aria-hidden="true">
              <div className="ct-card-header skeleton-page-header">
                <SkeletonLine width="9rem" height="1.1rem" />
                <SkeletonLine width="60%" height="0.75rem" />
              </div>
              <div className="data-table-card ct-table-card">
                <SkeletonTable rows={6} columns={5} />
              </div>
              <div className="ct-detail">
                <SkeletonLine width="14rem" height="0.9rem" />
                <SkeletonChart variant="line" height={300} />
              </div>
            </section>
          </>
        )}
        {state.status === 'loading' && data && <RefreshingNote>Updating {labelForPrincipal(principal)}…</RefreshingNote>}
        {state.status === 'error' && (
          <LoadError what="the category trends" message={state.error} onRetry={() => setAttempt((n) => n + 1)} />
        )}

        {data && (data.principals || []).map((section) => (
          <PrincipalSection
            key={`${section.principal}|${principal ?? ''}`}
            section={section}
            method={data.method}
            placeholder={data.data_mode?.placeholder ?? null}
          />
        ))}

        {/* Every figure here is GET /category-trends' method block
            (analytics/forecasting/category_trend.py) — no fallbacks, so a
            number on this page can't disagree with the one the backend used. */}
        {data?.method && (
          <details className="ct-details ui-details">
            <summary>Show details: how this is measured</summary>
          <p className="ct-method">
            A trend projection, not a validated forecast: a Theil–Sen line through
            the last {data.method.window_months} months of revenue with data, starting at the category&apos;s first sale,
            extended {data.method.projection_months} months. The direction counts as real only when a Mann–Kendall test
            gives p &lt; {data.method.significance_alpha}. The percentage compares the next {data.method.projection_months} months
            on the line with the last {data.method.trailing_months} on the same line; the range in brackets uses the
            slope&apos;s {Math.round(data.method.slope_confidence * 100)}% confidence bounds. A category needs{' '}
            {data.method.min_points} months with data from its first sale before it gets a projection. The peso change is
            the same comparison in pesos. &ldquo;Sure&rdquo; means p &lt; {data.method.significance_alpha}.
          </p>
          {(data.principals || []).map((section) => (
            <div className="ct-details-table" key={section.principal}>
              <p className="ct-details-title">{labelForPrincipal(section.principal)}, each category</p>
              <div className="data-table-card">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th className="table-center">Mann–Kendall p</th>
                      <th className="table-center">Slope (₱ a month)</th>
                      <th className="table-center">Change (%) with range</th>
                      <th className="table-center">Change (₱)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(section.categories || []).map((c) => (
                      <tr key={c.category}>
                        <td>{titleCase(c.category)}</td>
                        <td className="table-center ct-num">{c.mk_p == null ? '—' : c.mk_p < 0.001 ? '< 0.001' : c.mk_p.toFixed(3)}</td>
                        <td className="table-center ct-num">{c.slope_per_month == null ? '—' : formatRevenue(c.slope_per_month)}</td>
                        <td className="table-center ct-num">{c.available ? changeText(c) : '—'}</td>
                        <td className="table-center ct-num">{signedPesos(linePesoChange(c, data.method?.trailing_months))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
          </details>
        )}
      </div>
    </div>
  );
};

export default CategoryTrends;
