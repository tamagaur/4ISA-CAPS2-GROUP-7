// "Annual View" — the left card of the dashboard's "What happened?" row.
// One bar per calendar year: that year's total sales, from GET /dashboard's
// annual_sales block (backend/routers/dashboard.py, _annual_sales), which
// sums the same monthly sales the cards above and the chart beside it read.
//
// Nothing on this card is calculated in the browser and nothing is a
// placeholder: no block from the API means an empty card with the reason,
// never a stand-in number. A year with fewer than 12 months on record shows
// the months it has (named under its bar); it is not projected to a full
// year. Bars that count synthetic months (generated to complete SSM's
// history, not SSM's own figures) are hatched and say how many.
//
// The band is the dashboard's existing allocation estimate (the annual
// card's "Estimated annual allocation target": the base year's sales x
// 103-108%), read from the allocation block. It is not worked out here.
//
// Fixed, like the allocation card: the date filter and the comparison
// setting do not change it.
import React from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { CHART_COLORS } from '../theme/colors';
import { formatCompactPesos } from '../utils/formatters';
import { GRID_PROPS } from './ChartZoom';
import InfoTip from './InfoTip';
import './AnnualViewChart.css';

// Muted slate for past years, the dashboard's navy for the allocation's base
// year, orange for the year still in progress.
const BAR_COLOR = { history: '#8FA3C4', base: CHART_COLORS.heroInventory, ytd: '#F28C28' };
const BAND_COLOR = '#F28C28';
const BAND_INK = '#C2410C';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthNumber = (period) => Number(String(period).slice(5, 7));
const fy = (year) => `FY${String(year).slice(-2)}`;

// "Jan–Feb" when the months on record run without a gap, "9 of 12 months"
// when they do not: a span must never hide a missing month inside it.
const monthsOnRecord = (y) => {
  if (!y.months) return null;
  const first = monthNumber(y.first_month);
  const last = monthNumber(y.last_month);
  if (last - first + 1 !== y.months) return `${y.months} of 12 months`;
  return first === last ? MONTHS[first - 1] : `${MONTHS[first - 1]}–${MONTHS[last - 1]}`;
};

const buildRows = (annual, allocation) => {
  const years = annual?.years || [];
  const latest = [...years].reverse().find((y) => y.sales != null)?.year;
  return years.map((y) => {
    const partial = y.months > 0 && y.months < 12;
    const role = allocation?.basis_year === y.year
      ? 'base'
      : partial && y.year === latest ? 'ytd' : 'history';
    return {
      key: fy(y.year),
      year: y.year,
      value: y.sales,
      months: y.months,
      partial,
      span: partial ? monthsOnRecord(y) : null,
      synthetic: y.synthetic_months?.length || 0,
      role,
    };
  });
};

// The allocation card's own range (lowest to highest level), for a full
// base year only: the API leaves `annual` null when the base year is partial.
const buildBand = (allocation) => {
  if (!allocation || allocation.blocked_reason) return null;
  const levels = (allocation.levels || []).filter((l) => l.annual != null);
  if (levels.length < 2) return null;
  const low = levels.reduce((a, b) => (b.annual < a.annual ? b : a));
  const high = levels.reduce((a, b) => (b.annual > a.annual ? b : a));
  const line = levels.find((l) => l.pct === allocation.default_pct) || low;
  return {
    low: low.annual,
    high: high.annual,
    line: line.annual,
    linePct: line.pct,
    pcts: `${low.pct}–${high.pct}%`,
    year: allocation.allocation_year,
    basisYear: allocation.basis_year,
  };
};

// A round step that gives about five gridlines whatever the size of the
// principal's sales (₱100M steps for Unilever, ₱25M for Del Monte).
const niceStep = (top) => {
  if (!(top > 0)) return 1;
  const raw = top / 5;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const factor = [1, 2, 2.5, 5, 10].find((f) => f * magnitude >= raw) || 10;
  return factor * magnitude;
};

const hatchId = (role) => `annual-view-hatch-${role}`;

// "All 12 months are synthetic" / "3 of 12 months are synthetic".
const syntheticText = (row) => {
  if (row.synthetic === row.months) {
    return row.months === 1 ? 'Its one month on record is synthetic' : `All ${row.months} months are synthetic`;
  }
  return `${row.synthetic} of ${row.months} months ${row.synthetic === 1 ? 'is' : 'are'} synthetic`;
};

const AnnualTooltip = ({ active, payload, band }) => {
  const row = active && payload?.[0]?.payload;
  if (!row) return null;
  return (
    <div className="chart-tooltip">
      <p className="tooltip-label">
        FY {row.year}{row.span ? ` · ${row.span}` : ''}
      </p>
      {row.value == null ? (
        <p className="tooltip-item">No sales on record</p>
      ) : (
        <>
          <p className="tooltip-item">{formatCompactPesos(row.value)} total sales</p>
          <p className="tooltip-item annual-tooltip-note">
            {row.months} of 12 months on record{row.partial ? ', not a full year' : ''}
          </p>
        </>
      )}
      {row.synthetic > 0 && (
        <p className="tooltip-item annual-tooltip-synthetic">
          {syntheticText(row)}, not SSM&apos;s own figures
        </p>
      )}
      {row.role === 'base' && band && (
        <p className="tooltip-item annual-tooltip-note">Base year of the {fy(band.year)} allocation target</p>
      )}
    </div>
  );
};

// The year, and under it the months on record when the year is not full.
const YearTick = ({ x, y, payload, rows }) => {
  const row = rows.find((r) => r.key === payload.value);
  return (
    <g transform={`translate(${x},${y})`}>
      <text dy={12} textAnchor="middle" fill={CHART_COLORS.axisLabel} fontSize={11}>{payload.value}</text>
      {row?.span && (
        <text dy={25} textAnchor="middle" fill={BAND_INK} fontSize={10} fontWeight={600}>{row.span}</text>
      )}
      {row && row.value == null && (
        <text dy={25} textAnchor="middle" fill={CHART_COLORS.axisLabel} fontSize={10}>no data</text>
      )}
    </g>
  );
};

// The figure above each bar, on a white halo so the band's dashed line
// (which sits just above the tallest bars) never strikes through it.
const BarValue = ({ x, y, width, value }) => {
  if (value == null) return null;
  return (
    <text
      x={x + width / 2}
      y={y - 6}
      textAnchor="middle"
      fill="#344054"
      fontSize={11}
      fontWeight={600}
      stroke="#fff"
      strokeWidth={3}
      paintOrder="stroke"
    >
      {formatCompactPesos(value)}
    </text>
  );
};

const AnnualViewChart = ({ annual, allocation, note }) => {
  const rows = buildRows(annual, allocation);
  const hasData = rows.some((r) => r.value != null);
  const band = hasData && rows.some((r) => r.role === 'base') ? buildBand(allocation) : null;
  const ytd = rows.find((r) => r.role === 'ytd');
  const base = rows.find((r) => r.role === 'base');
  const synthetic = rows.filter((r) => r.synthetic > 0);
  const earlier = annual?.earlier_years || [];

  const top = Math.max(0, ...rows.map((r) => r.value ?? 0), band?.high ?? 0);
  // Headroom for the labels above the bars and the band's name above it.
  const step = niceStep(top * 1.12);
  const ceiling = Math.max(step, Math.ceil((top * 1.12) / step) * step);
  const ticks = Array.from({ length: Math.round(ceiling / step) + 1 }, (_, i) => i * step);

  const title = `Annual View: ${rows.length ? `${rows.length}-Year ` : ''}Trend`
    + (band ? ` vs. ${fy(band.year)} Target Band` : '');

  return (
    <div className={`chart-widget annual-view${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>
            {title}
            <InfoTip label="About the Annual View" size={13}>
              Each bar is one calendar year&apos;s total sales in pesos (January to December), added up from the
              same monthly sales as the cards above. It does not change with the date filter. A year with fewer
              than 12 months on record shows only the months it has; nothing is projected to a full year.
              {band && (
                <>
                  {' '}The band is the estimated {fy(band.year)} allocation target shown on the annual card:
                  FY {band.basisYear} sales × {band.pcts}, with the dashed line at {band.linePct}%. The percentage
                  that applies is still a question for SSM, so the band is an assumption.
                </>
              )}
              {earlier.length > 0 && (
                <> Also on record, before these years: {earlier.map(fy).join(', ')}.</>
              )}
              {note && <> {note}.</>}
            </InfoTip>
          </h4>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">
          {annual?.blocked_reason || 'Yearly sales totals are not available yet.'}
        </p>
      ) : (
        <>
          <div className="annual-view-legend" aria-hidden="true">
            <span><i style={{ backgroundColor: BAR_COLOR.history }} />Past years</span>
            {base && <span><i style={{ backgroundColor: BAR_COLOR.base }} />Base year ({base.key})</span>}
            {ytd && <span><i style={{ backgroundColor: BAR_COLOR.ytd }} />{ytd.key} so far ({ytd.span})</span>}
            {band && (
              <span>
                <i className="annual-view-legend-band" />
                {fy(band.year)} target band, {band.pcts} of {fy(band.basisYear)}
              </span>
            )}
            {synthetic.length > 0 && (
              <span><i className="annual-view-legend-hatch" />Includes synthetic months</span>
            )}
          </div>
          {synthetic.length > 0 && (
            <p className="annual-view-synthetic">
              Synthetic months, not SSM&apos;s own figures:{' '}
              {synthetic.map((r) => `${r.key} ${r.synthetic} of ${r.months}`).join(' · ')}
            </p>
          )}
          <div className="chart-container annual-view-plot">
            <ResponsiveContainer width="99%" height="100%">
              <BarChart data={rows} margin={{ top: 22, right: 12, left: 4, bottom: 4 }} barCategoryGap="28%">
                <defs>
                  {Object.entries(BAR_COLOR).map(([role, color]) => (
                    <pattern key={role} id={hatchId(role)} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                      <rect width="7" height="7" fill={color} />
                      <rect width="3" height="7" fill="#fff" fillOpacity="0.55" />
                    </pattern>
                  ))}
                </defs>
                <CartesianGrid {...GRID_PROPS} vertical={false} />
                <XAxis
                  dataKey="key"
                  tickLine={false}
                  axisLine={{ stroke: CHART_COLORS.gridline }}
                  interval={0}
                  height={34}
                  tick={<YearTick rows={rows} />}
                />
                <YAxis
                  domain={[0, ceiling]}
                  ticks={ticks}
                  tickFormatter={(v) => formatCompactPesos(v)}
                  tickLine={false}
                  axisLine={false}
                  width={58}
                  tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                />
                <Tooltip content={<AnnualTooltip band={band} />} cursor={{ fill: 'rgba(148, 163, 184, 0.12)' }} />
                {band && (
                  <ReferenceArea
                    y1={band.low}
                    y2={band.high}
                    fill={BAND_COLOR}
                    fillOpacity={0.12}
                    stroke="none"
                    label={{ value: `${fy(band.year)} target ${band.pcts}`, position: 'top', fill: BAND_INK, fontSize: 10, offset: 4 }}
                  />
                )}
                {band && <ReferenceLine y={band.line} stroke={BAND_INK} strokeDasharray="5 4" />}
                <Bar dataKey="value" radius={[6, 6, 0, 0]} maxBarSize={56} isAnimationActive={false}>
                  {rows.map((r) => (
                    <Cell
                      key={r.key}
                      fill={r.synthetic > 0 ? `url(#${hatchId(r.role)})` : BAR_COLOR[r.role]}
                      stroke={r.synthetic > 0 ? BAR_COLOR[r.role] : 'none'}
                    />
                  ))}
                  <LabelList dataKey="value" content={<BarValue />} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
};

export default AnnualViewChart;
