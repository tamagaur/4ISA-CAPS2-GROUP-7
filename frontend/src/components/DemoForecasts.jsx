// The synthetic demonstration's Del Monte category forecasts (schema demo;
// CLAUDE.md rule 2, docs/DEMO_DATA.md), shown only with synthetic data on.
// Del Monte has no product-level sales, so the demonstration forecasts its
// five 2025 product categories with the deployed method, a 3-month average.
// Everything here is labelled synthetic: no accuracy is measured and no range
// is drawn (the backend sends neither), and nothing reaches an order plan.
import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FlaskConical } from 'lucide-react';
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { getDemoIndex } from '../api/demo';
import { getDemoCategoryForecast } from '../api/forecast';
import { COLORS, SEMANTIC } from '../theme/colors';
import { originLabel } from '../utils/gapReasons';
import './DemoForecasts.css';
import { isMissing, NOT_COLLECTED } from '../utils/formatters';

const monthLabel = (period) => {
  if (!period) return '';
  const [y, m] = String(period).slice(0, 7).split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
};
const titleCase = (s) => String(s).toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
const formatQty = (v) => {
  if (v == null) return '—';
  return Math.abs(v) < 10 ? v.toFixed(1) : Math.round(v).toLocaleString('en-US');
};
const compactQty = (v) => (isMissing(v) ? NOT_COLLECTED : Math.abs(v) >= 1000 ? `${Math.round(v / 100) / 10}k` : String(Math.round(v)));
const UNIT_NOTE = "Quantities are in Del Monte's own unit, which SSM has not confirmed.";

const SyntheticTag = () => (
  <span className="demo-tag"><FlaskConical size={12} aria-hidden="true" /> Synthetic data</span>
);

// Dashboard, step 4, Del Monte: GET /dashboard's demonstration.forecasts.
export const DemoForecastList = ({ forecasts = [], canOpenForecast = false }) => {
  const navigate = useNavigate();
  if (!forecasts.length) return null;
  const period = forecasts[0]?.forecast_period;
  return (
    <div className="demo-forecasts">
      <div className="demo-forecasts-head">
        <SyntheticTag />
        <p className="demo-forecasts-lead">
          Del Monte has no product-level sales, so the synthetic data forecasts its {forecasts.length} product
          categories instead: the average of their last 3 months, for {monthLabel(period)}. Not checked for accuracy,
          and never used for SSM&apos;s real orders.
        </p>
      </div>
      <div className="demo-forecasts-table-wrap">
        <table className="demo-forecasts-table">
          <thead>
            <tr>
              <th scope="col">Category</th>
              <th scope="col" className="num">{monthLabel(period)} forecast</th>
              <th scope="col">Months averaged that are synthetic</th>
            </tr>
          </thead>
          <tbody>
            {forecasts.map((f) => (
              <tr key={f.category}>
                <td>{titleCase(f.category)}</td>
                <td className="num">{f.status === 'ok' ? formatQty(f.forecast_quantity) : f.status}</td>
                <td>{f.generated_months_in_average} of 3</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="demo-forecasts-note">{UNIT_NOTE}</p>
      {canOpenForecast && (
        <button type="button" className="demo-forecasts-link" onClick={() => navigate('/forecast')}>
          See each category&apos;s history
        </button>
      )}
    </div>
  );
};

// A month copied from SSM's own figure is a filled dot; a generated month is
// hollow. The tooltip names how it was made.
const OriginDot = ({ cx, cy, payload }) => {
  if (cx == null || cy == null || payload?.quantity == null) return null;
  const real = payload.origin === 'real_copy';
  return (
    <circle
      key={`dot-${payload.period}`}
      cx={cx}
      cy={cy}
      r={real ? 3.5 : 3}
      fill={real ? COLORS.dispatched : 'var(--color-surface, #fff)'}
      stroke={real ? COLORS.dispatched : SEMANTIC.noData}
      strokeWidth={1.5}
    />
  );
};

// Only the forecast month gets a dot; the dashed line leaves from the last month's own dot.
const ForecastDot = ({ cx, cy, payload }) => (
  cx == null || cy == null || !payload?.isForecast ? null
    : <circle key={`fc-${payload.period}`} cx={cx} cy={cy} r={4} fill={COLORS.forecast} stroke={COLORS.forecast} />
);

const DemoTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="demo-tooltip">
      <p className="demo-tooltip-title">{monthLabel(row.period)}</p>
      {row.isForecast ? (
        <p>Forecast: <strong>{formatQty(row.ahead)}</strong>, the average of the last 3 months</p>
      ) : (
        <>
          <p>Quantity: <strong>{formatQty(row.quantity)}</strong></p>
          <p className="demo-tooltip-origin">
            {row.origin === 'real_copy' ? "SSM's own figure" : `Synthetic: ${originLabel(row.origin)}`}
          </p>
        </>
      )}
    </div>
  );
};

// Forecast page, Del Monte: one category's demonstration history (GET
// /forecast/{category}?principal=delmonte&category=) and its forecast. The
// categories are the 2025 ones in GET /demo/index.
export const DemoCategoryForecast = () => {
  const [categories, setCategories] = useState(null);
  const [selected, setSelected] = useState(null);
  const [result, setResult] = useState(undefined);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getDemoIndex('delmonte')
      .then((index) => {
        if (cancelled) return;
        const keys = (index?.series || []).filter((s) => s.taxonomy && s.taxonomy !== 'pre_2025').map((s) => s.key);
        setCategories(keys);
        setSelected((current) => current || keys[0] || null);
      })
      .catch(() => { if (!cancelled) setError('Could not load the synthetic categories.'); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selected) return undefined;
    let cancelled = false;
    setResult(undefined);
    setError(null);
    getDemoCategoryForecast(selected)
      .then((res) => { if (!cancelled) setResult(res); })
      .catch(() => { if (!cancelled) setError('Could not load this category forecast.'); });
    return () => { cancelled = true; };
  }, [selected]);

  const { rows, forecast, firstReal, ticks } = useMemo(() => {
    if (!result) return { rows: [], forecast: null, firstReal: null, ticks: [] };
    const fc = (result.forecast || [])[0] || null;
    const out = (result.actuals || []).map((a) => ({
      period: a.period, quantity: a.quantity, origin: a.origin, before: a.generated_before_first_observation,
    }));
    if (fc && out.length) {
      // The dashed forecast line starts at the last month and ends at the forecast.
      out[out.length - 1] = { ...out[out.length - 1], ahead: out[out.length - 1].quantity };
      out.push({ period: String(fc.forecast_date).slice(0, 7), ahead: fc.forecast_value, isForecast: true });
    }
    return {
      rows: out,
      forecast: fc,
      firstReal: out.find((r) => r.origin === 'real_copy')?.period ?? null,
      ticks: out.filter((r) => r.period.endsWith('-01')).map((r) => r.period),
    };
  }, [result]);

  const counts = result?.origin_counts || {};
  const madeUp = Object.entries(counts).filter(([origin, n]) => origin !== 'real_copy' && n > 0);
  const generated = madeUp.reduce((sum, [, n]) => sum + n, 0);

  return (
    <section className="demo-cat" aria-labelledby="demo-cat-title">
      <div className="demo-forecasts-head">
        <SyntheticTag />
        <h3 className="demo-cat-title" id="demo-cat-title">Category forecasts from synthetic data</h3>
        <p className="demo-cat-lead">
          Del Monte has no product-level sales, so there is no product forecast. With synthetic data on, each of its
          product categories gets one instead: the average of its last 3 months, from history that fills the months
          SSM did not collect. For viewing only: not checked for accuracy, and never used for SSM&apos;s real orders.
        </p>
      </div>

      {categories && categories.length === 0 && !error && (
        <p className="demo-cat-note">Synthetic data is not switched on for this server.</p>
      )}
      {categories && categories.length > 0 && (
        <div className="demo-cat-chips" role="group" aria-label="Category">
          {categories.map((key) => (
            <button
              key={key}
              type="button"
              className="demo-cat-chip"
              aria-pressed={selected === key}
              onClick={() => setSelected(key)}
            >
              {titleCase(key)}
            </button>
          ))}
        </div>
      )}
      {error && <p className="demo-cat-note" role="alert">{error}</p>}
      {selected && result === undefined && !error && <p className="demo-cat-note">Loading {titleCase(selected)}…</p>}
      {selected && result === null && (
        <p className="demo-cat-note">No synthetic history for {titleCase(selected)}.</p>
      )}

      {rows.length > 0 && (
        <>
          {forecast && (
            <p className="demo-cat-summary">
              {monthLabel(forecast.forecast_date)} forecast for {titleCase(selected)}:{' '}
              <strong>{formatQty(forecast.forecast_value)}</strong>
            </p>
          )}
          <div className="demo-cat-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
                <CartesianGrid stroke="var(--color-border, #E4E7EC)" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="period"
                  ticks={ticks}
                  tickFormatter={(p) => String(p).slice(0, 4)}
                  tick={{ fontSize: 11, fill: 'var(--color-text-muted, #64748B)' }}
                  tickLine={false}
                />
                <YAxis
                  width={44}
                  tickFormatter={compactQty}
                  tick={{ fontSize: 11, fill: 'var(--color-text-muted, #64748B)' }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip content={<DemoTooltip />} />
                <Line
                  type="monotone"
                  dataKey="quantity"
                  name="History"
                  stroke={SEMANTIC.noData}
                  strokeWidth={1.5}
                  dot={OriginDot}
                  activeDot={{ r: 5 }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="ahead"
                  name="Forecast"
                  stroke={COLORS.forecast}
                  strokeWidth={2}
                  strokeDasharray="6 4"
                  dot={ForecastDot}
                  connectNulls
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <ul className="demo-cat-legend">
            <li>
              <svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="3.5" fill={COLORS.dispatched} /></svg>
              SSM&apos;s own figure ({counts.real_copy || 0} months)
            </li>
            <li>
              <svg width="10" height="10" aria-hidden="true">
                <circle cx="5" cy="5" r="3" fill="none" stroke={SEMANTIC.noData} strokeWidth="1.5" />
              </svg>
              Synthetic ({generated} months: {madeUp.map(([origin, n]) => `${n} ${originLabel(origin)}`).join(', ')})
            </li>
            <li>
              <svg width="18" height="10" aria-hidden="true">
                <line x1="0" y1="5" x2="18" y2="5" stroke={COLORS.forecast} strokeWidth="2" strokeDasharray="5 3" />
              </svg>
              Forecast
            </li>
          </ul>
          {rows.some((r) => r.before) && firstReal && (
            <p className="demo-cat-note">
              {titleCase(selected)} first appears in SSM&apos;s data in {monthLabel(firstReal)}, after the Jan 2025
              change of categories. Earlier months are back-cast at its own level, because the 2025 categories are new
              names for business Del Monte already had.
            </p>
          )}
          <p className="demo-cat-note">{UNIT_NOTE}</p>
        </>
      )}
    </section>
  );
};
