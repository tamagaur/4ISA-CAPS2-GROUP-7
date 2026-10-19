import React, { useEffect, useMemo, useState } from 'react';
import SectionLede from './ui/SectionLede';
import { useOutletContext } from 'react-router-dom';
import { ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react';
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
} from 'recharts';
import { getCategoryTrends } from '../api/analytics';
import { periodToParam } from '../periodFilter';
import { labelForPrincipal } from '../principals';
import { formatMonth } from '../utils/formatDate';
import { formatCompactPesos } from '../utils/formatters';
import { CHART_COLORS, COLORS } from '../theme/colors';
import { GRID_PROPS, pointLabels, seriesDot } from './ChartZoom';
import { ChartTable, ChartViewToggle } from './ChartTable';
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
import GapNote from './GapNote';
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
const signed = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`);
const titleCase = (name) => (name || '').toLowerCase().replace(/(^|[\s/&-])\S/g, (c) => c.toUpperCase());
// 'Mar 2025 – Feb 2026'; null when either end is missing.
const monthSpan = (start, end) => (start && end ? `${formatMonth(start)} – ${formatMonth(end)}` : null);
const axisMonth = (period) => {
  const [m, y] = (formatMonth(period) || '').split(' ');
  return y ? `${m} · ${y}` : period;
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
        <p>Likely range: {formatCompactPesos(p.bandLow)} – {formatCompactPesos(p.bandHigh)}</p>
      )}
      {isPlaceholderPeriod(label, placeholder) && <p className="ct-tooltip-placeholder">Placeholder month — not SSM&apos;s data</p>}
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
    const rows = history.map((h, i) => ({
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

  // Selective direct labels: the last actual month's revenue, and the
  // projected level at the end of the trend line.
  const actualLabels = useMemo(() => {
    const lastActual = [...data].reverse().find((r) => r.actual != null);
    return pointLabels(data, lastActual
      ? [{ period: lastActual.period, text: formatRevenue(lastActual.actual) }]
      : []);
  }, [data]);
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
        <ChartTable
          caption="Monthly revenue and trend projection, in pesos"
          columns={[
            { key: 'period', label: 'Month', format: (v) => axisMonth(v), align: 'left' },
            { key: 'actual', label: 'Revenue (₱)', format: (v) => formatRevenue(v) },
            { key: 'fitted', label: 'Trend line (₱)', format: (v) => formatCompactPesos(v) },
            { key: 'projection', label: 'Projected trend (₱)', format: (v) => formatCompactPesos(v) },
            ...(hasRange ? [
              { key: 'bandLow', label: 'Range low (₱)', format: (v) => formatCompactPesos(v) },
              { key: 'bandHigh', label: 'Range high (₱)', format: (v) => formatCompactPesos(v) },
            ] : []),
          ]}
          rows={data}
        />
      ) : (
        <>
          <ResponsiveContainer width="100%" height={340}>
            <ComposedChart data={data} margin={{ top: 10, right: 16, left: 4, bottom: 8 }}>
              <CartesianGrid {...GRID_PROPS} />
              {renderPlaceholderBand(bandSpan)}
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
                  label={{ value: 'Projection starts', position: 'insideTopRight', fontSize: 11, fill: CHART_COLORS.axisLabel }}
                />
              )}
              <Line dataKey="actual" name="Revenue" stroke={CHART_COLORS.salesSeries} strokeWidth={2} strokeLinecap="round" dot={seriesDot({ color: CHART_COLORS.salesSeries, r: 3 })} connectNulls={false} isAnimationActive={false} label={actualLabels} />
              <Line dataKey="fitted" name="Trend line" stroke={CHART_COLORS.cumulativeCurve} strokeWidth={1.5} strokeDasharray="3 3" dot={false} connectNulls={false} isAnimationActive={false} />
              <Line dataKey="projection" name="Projected trend" stroke={COLORS.forecast} strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls={false} isAnimationActive={false} label={projectionLabels} />
            </ComposedChart>
          </ResponsiveContainer>
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
              <span>
                <i className="ct-swatch ct-swatch-band" />
                Likely range ({Math.round(method.slope_confidence * 100)}% slope bounds)
              </span>
            )}
            {bandSpan && <span><i className="ct-swatch ct-swatch-placeholder" />Placeholder months — not SSM&apos;s data</span>}
          </div>
        </>
      )}
    </div>
  );
};

const PrincipalSection = ({ section, method, placeholder = null }) => {
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
            ` ${formatMonth(placeholder.start)} – ${formatMonth(placeholder.end)} is placeholder data (preview), not SSM's.`
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
                <th className="table-num">
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
                <th>Trend</th>
                <th className="table-num">
                  Projected change (%)
                  <InfoTip label="About this projection">
                    The trend line&apos;s total over the next {method?.projection_months} months
                    {projectionWindow ? ` (${projectionWindow})` : ''} against its total over the last {method?.trailing_months}
                    {trailingWindow ? ` (${trailingWindow})` : ''}. In brackets, the same with the slope&apos;s confidence bounds.
                  </InfoTip>
                  <span className="ct-th-period">
                    {projectionWindow && trailingWindow
                      ? `${projectionWindow} vs ${trailingWindow}`
                      : `next ${method?.projection_months} months vs last ${method?.trailing_months}`}
                  </span>
                </th>
                <th className="table-num">
                  Trend confidence
                  <InfoTip label="About trend confidence">
                    Strong means the direction is unlikely to be chance: a Mann–Kendall test p-value below{' '}
                    {method?.significance_alpha}. Weak means it could be noise.
                  </InfoTip>
                </th>
              </tr>
            </thead>
            <tbody>
              {categories.map((c) => {
                const dir = DIRECTION[c.direction];
                const DirIcon = dir?.Icon;
                return (
                  <tr
                    key={c.category}
                    className={c.category === current?.category ? 'ct-row-selected' : ''}
                    onClick={() => setSelected(c.category)}
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(c.category); } }}
                    aria-selected={c.category === current?.category}
                  >
                    <td className="ct-name">{titleCase(c.category)}</td>
                    <td className="table-num">{formatRevenue(c.revenue_last_12)}</td>
                    <td>
                      {c.available ? (
                        <span className={`badge ${dir.className}`}>{DirIcon && <DirIcon size={12} aria-hidden="true" />}{dir.label}</span>
                      ) : (
                        // The backend's own short status: "Not enough
                        // months" or "No recent sales".
                        <span className="badge badge-neutral" title={c.reason}>{c.label}</span>
                      )}
                    </td>
                    <td className="table-num">
                      {c.available ? (
                        <>
                          <strong>{signed(c.change_pct)}</strong>
                          <span className="ct-range"> ({signed(c.change_pct_low)} to {signed(c.change_pct_high)})</span>
                        </>
                      ) : c.points > 0 && method ? (
                        <span className="ct-muted">{c.points} of {method.min_points} months</span>
                      ) : (
                        <span className="ct-muted">—</span>
                      )}
                    </td>
                    <td className="table-num">
                      {c.mk_p == null ? '—' : (
                        <>
                          {method?.significance_alpha != null && (c.mk_p < method.significance_alpha ? 'Strong' : 'Weak')}
                          <span className="ct-range"> ({c.mk_p < 0.001 ? 'p < 0.001' : `p = ${c.mk_p.toFixed(3)}`})</span>
                        </>
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
          <h4 className="ct-detail-title">
            {titleCase(current.category)}
            {current.available && (
              <span className="ct-detail-sub">
                {' '}— revenue trend {current.slope_per_month >= 0 ? 'rising' : 'falling'} {formatCompactPesos(Math.abs(current.slope_per_month))} a month
                {current.direction === 'flat' ? ', but not significantly' : ''}
              </span>
            )}
          </h4>
          <SectionLede>Where this category is heading</SectionLede>
          <CategoryChart category={current} method={method} placeholder={placeholder} />
          {!current.available && <p className="ct-note">{current.reason}</p>}
        </div>
      )}
      {/* Months no category reported at all (Del Monte collection failures),
          left off the chart's axis, and what every reason means. */}
      {section.skipped_months?.length > 0 && (
        <p className="ct-note">
          Not collected, no category reported: {section.skipped_months.map((m) => formatMonth(m.period)).join(', ')}.
        </p>
      )}
      <GapNote note={section.gap_note} />
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
          <p className="ct-method">
            <strong>How this is measured.</strong> A trend projection, not a validated forecast: a Theil–Sen line through
            the last {data.method.window_months} months of revenue with data, starting at the category&apos;s first sale,
            extended {data.method.projection_months} months. The direction counts as real only when a Mann–Kendall test
            gives p &lt; {data.method.significance_alpha}. The percentage compares the next {data.method.projection_months} months
            on the line with the last {data.method.trailing_months} on the same line; the range in brackets uses the
            slope&apos;s {Math.round(data.method.slope_confidence * 100)}% confidence bounds. A category needs{' '}
            {data.method.min_points} months with data from its first sale before it gets a projection.
          </p>
        )}
      </div>
    </div>
  );
};

export default CategoryTrends;
