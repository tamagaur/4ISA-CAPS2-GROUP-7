import React, { useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react';
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { getCategoryTrends } from '../api/analytics';
import { labelForPrincipal } from '../principals';
import { formatMonth } from '../utils/formatDate';
import { formatCompactPesos } from '../utils/formatters';
import { CHART_COLORS, COLORS } from '../theme/colors';
import { isPlaceholderPeriod } from '../dataMode';
import { placeholderSpan, renderPlaceholderBand } from '../utils/placeholderBand';
import RefreshingNote from './RefreshingNote';
import './CategoryTrends.css';

// "What are the projected growth and decline trajectories for each product
// category over the coming year?" — the analytical mapping's P1, from GET
// /category-trends (analytics/forecasting/category_trend.py).
//
// A TREND projection, said as such everywhere: a Theil–Sen line through the
// last 24 months of revenue, extended 12 months, with Mann–Kendall deciding
// whether the direction is real. It answers "which way is this category
// heading and how fast", not "what will next month be" — that is the SKU
// forecast's job.

const DIRECTION = {
  growing: { label: 'Growing', Icon: ArrowUpRight, className: 'ct-dir-up' },
  declining: { label: 'Declining', Icon: ArrowDownRight, className: 'ct-dir-down' },
  flat: { label: 'No clear trend', Icon: Minus, className: 'ct-dir-flat' },
};
const signed = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`);
const titleCase = (name) => (name || '').toLowerCase().replace(/(^|[\s/&-])\S/g, (c) => c.toUpperCase());
const axisMonth = (period) => {
  const [m, y] = (formatMonth(period) || '').split(' ');
  return y ? `${m} · ${y}` : period;
};

const TrendTooltip = ({ active, payload, label, placeholder }) => {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="ct-tooltip">
      <p className="ct-tooltip-title">{axisMonth(label)}</p>
      {p.actual != null && <p>Revenue: {formatCompactPesos(p.actual)}</p>}
      {p.fitted != null && <p>Trend line: {formatCompactPesos(p.fitted)}</p>}
      {p.projection != null && p.actual == null && <p>Projected trend: {formatCompactPesos(p.projection)}</p>}
      {isPlaceholderPeriod(label, placeholder) && <p className="ct-tooltip-placeholder">Placeholder month — not SSM&apos;s data</p>}
    </div>
  );
};

// `placeholder` is the payload's data_mode.placeholder window — set only in
// preview mode (src/dataMode.js), so real mode draws no band.
const CategoryChart = ({ category, placeholder = null }) => {
  const data = useMemo(() => {
    const history = category.history || [];
    const fitted = category.fitted || [];
    const offset = history.length - fitted.length;
    const rows = history.map((h, i) => ({
      period: h.period,
      actual: h.revenue,
      fitted: i >= offset ? fitted[i - offset] : null,
      projection: null,
    }));
    if (category.available && rows.length) {
      // Start the projection at the line's last value so it reads as one line.
      rows[rows.length - 1].projection = rows[rows.length - 1].fitted;
      (category.projection_periods || []).forEach((period, i) => {
        rows.push({ period, actual: null, fitted: null, projection: category.projection[i] });
      });
    }
    return rows;
  }, [category]);
  const bandSpan = placeholderSpan(data, placeholder);

  return (
    <div className="ct-chart">
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 10, right: 16, left: 4, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART_COLORS.gridline} />
          {renderPlaceholderBand(bandSpan)}
          <XAxis dataKey="period" tickFormatter={axisMonth} minTickGap={24} tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }} />
          <YAxis tickFormatter={formatCompactPesos} tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }} width={56} />
          <Tooltip content={<TrendTooltip placeholder={placeholder} />} />
          <Line dataKey="actual" name="Revenue" stroke={CHART_COLORS.salesSeries} strokeWidth={2} dot={{ r: 2 }} connectNulls={false} isAnimationActive={false} />
          <Line dataKey="fitted" name="Trend line" stroke={CHART_COLORS.cumulativeCurve} strokeWidth={1.5} strokeDasharray="3 3" dot={false} connectNulls={false} isAnimationActive={false} />
          <Line dataKey="projection" name="Projected trend" stroke={COLORS.forecast} strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="ct-legend">
        <span><i className="ct-swatch ct-swatch-actual" />Monthly revenue</span>
        <span><i className="ct-swatch ct-swatch-fitted" />Trend line (last {category.points ?? 24} months)</span>
        {category.available && <span><i className="ct-swatch ct-swatch-projection" />Trend, next 12 months</span>}
        {bandSpan && <span><i className="ct-swatch ct-swatch-placeholder" />Placeholder months — not SSM&apos;s data</span>}
      </div>
    </div>
  );
};

const PrincipalSection = ({ section, placeholder = null }) => {
  const categories = section.categories || [];
  const [selected, setSelected] = useState(() => categories.find((c) => c.available)?.category ?? categories[0]?.category);
  const current = categories.find((c) => c.category === selected) ?? categories[0];
  const observed = section.observed_months || [];
  const anyProjection = categories.some((c) => c.available);

  return (
    <section className="ct-card">
      <div className="ct-card-header">
        <h3 className="ct-card-title">{labelForPrincipal(section.principal)}</h3>
        <p className="ct-card-subtitle">
          {observed.length
            ? `${observed.length} month${observed.length === 1 ? '' : 's'} with data, ${formatMonth(observed[0])} – ${formatMonth(observed[observed.length - 1])}.`
            : 'No revenue data loaded.'}
          {section.principal === 'delmonte' &&
            ' Only months since Del Monte regrouped its categories in Jan 2025 count — the older sub-categories are different categories.'}
          {section.principal === placeholder?.principal && observed.some((m) => isPlaceholderPeriod(m, placeholder)) &&
            ` ${formatMonth(placeholder.start)} – ${formatMonth(placeholder.end)} is placeholder data (preview), not SSM's.`
            + ' The trend line and projection use only the last 24 months, all real, so they are the same as without it.'}
        </p>
      </div>
      {!anyProjection && categories.length > 0 && (
        <p className="ct-note">
          No category has the {12} months with data a projection needs yet, so this shows history only.
        </p>
      )}
      {categories.length > 0 && (
        <div className="data-table-card ct-table-card">
          <table className="data-table ct-table">
            <thead>
              <tr>
                <th>Category</th>
                <th className="table-num">Revenue, last 12 months</th>
                <th>Trend</th>
                <th className="table-num" title="The next 12 months on the trend line against the last 12 on the same line">Next 12 months vs last 12</th>
                <th className="table-num" title="Mann–Kendall p-value; below 0.05 the direction is statistically real">Significance</th>
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
                    <td className="table-num">{formatCompactPesos(c.revenue_last_12)}</td>
                    <td>
                      {c.available ? (
                        <span className={`ct-dir ${dir.className}`}>{DirIcon && <DirIcon size={14} aria-hidden="true" />}{dir.label}</span>
                      ) : (
                        <span className="ct-dir ct-dir-none">Not enough months</span>
                      )}
                    </td>
                    <td className="table-num">
                      {c.available ? (
                        <>
                          <strong>{signed(c.change_pct)}</strong>
                          <span className="ct-range"> ({signed(c.change_pct_low)} to {signed(c.change_pct_high)})</span>
                        </>
                      ) : (
                        <span className="ct-muted">{c.points} of 12 months</span>
                      )}
                    </td>
                    <td className="table-num">{c.mk_p == null ? '—' : c.mk_p < 0.001 ? 'p < 0.001' : `p = ${c.mk_p.toFixed(3)}`}</td>
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
                {' '}— trend {current.slope_per_month >= 0 ? 'rising' : 'falling'} {formatCompactPesos(Math.abs(current.slope_per_month))} a month
                {current.direction === 'flat' ? ', but not significantly' : ''}
              </span>
            )}
          </h4>
          <CategoryChart category={current} placeholder={placeholder} />
          {!current.available && <p className="ct-note">{current.reason}</p>}
        </div>
      )}
    </section>
  );
};

const CategoryTrends = () => {
  const { principal } = useOutletContext() || {};
  const [state, setState] = useState({ status: 'loading', data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, status: 'loading', error: null }));
    getCategoryTrends({ principal })
      .then((data) => { if (!cancelled) setState({ status: 'loaded', data, error: null }); })
      .catch((err) => { if (!cancelled) setState((prev) => ({ ...prev, status: 'error', error: err.message })); });
    return () => { cancelled = true; };
  }, [principal]);

  const data = state.data;
  return (
    <div className="ct-page">
      <div className="ct-content">
        <div className="ct-header">
          <h2 className="ct-title">
            Category <span className="page-title-accent">trends</span>
          </h2>
          <p className="ct-subtitle">
            Monthly revenue by product category, and where its trend points over the next 12 months.
          </p>
        </div>

        {state.status === 'loading' && !data && <p className="ct-note" role="status">Loading category trends…</p>}
        {state.status === 'loading' && data && <RefreshingNote>Updating {labelForPrincipal(principal)}…</RefreshingNote>}
        {state.status === 'error' && <p className="ct-note" role="alert">Could not load category trends: {state.error}</p>}

        {data && (data.principals || []).map((section) => (
          <PrincipalSection
            key={`${section.principal}|${principal ?? ''}`}
            section={section}
            placeholder={data.data_mode?.placeholder ?? null}
          />
        ))}

        {data && (
          <p className="ct-method">
            <strong>How this is measured.</strong> A trend projection, not a validated forecast: a Theil–Sen line through
            the last {data.method?.window_months ?? 24} months of revenue with data, extended{' '}
            {data.method?.projection_months ?? 12} months. The direction counts as real only when a Mann–Kendall test gives
            p &lt; 0.05. The percentage compares the next 12 months on the line with the last 12 on the same line; the range
            in brackets uses the slope&apos;s 95% confidence bounds. A category needs {data.method?.min_points ?? 12} months
            with data before it gets a projection.
          </p>
        )}
      </div>
    </div>
  );
};

export default CategoryTrends;
