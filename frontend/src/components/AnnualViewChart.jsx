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
// The band is SSM's targets (the base year's sales × 103–108%), read from
// the allocation block, not worked out here. The dashed line is the target
// picked on the Summary card (`selectedPct`, held by Dashboard.jsx), and the
// year in progress gets a dashed, unfilled "to go" bar from its sales up to
// that line (2026-10-19): the line's figure minus the year's sales.
//
// The full 5-year window always shows (2026-10-19): a year with no figure
// is an empty slot labelled "No data recorded" and when SSM's records start;
// with synthetic data on, its synthetic months make it a hatched bar.
//
// Fixed, like the allocation card: the date filter and the comparison
// setting do not change it (the "All years" tag says so).
import React from 'react';
import BasisTag from './BasisTag';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  usePlotArea,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { CHART_COLORS } from '../theme/colors';
import { formatCompactPesos } from '../utils/formatters';
import { GRID_PROPS } from './ChartZoom';
import InfoTip from './InfoTip';
import { BAR_FADE_FLOOR, Callout, CalloutLine, CalloutNote, Callouts, Fade } from './ui/ChartParts';
import './AnnualViewChart.css';
import { FIRST_DATA_YEAR } from '../dataCoverage';

// Muted slate for past years, the dashboard's navy for the allocation's base
// year, orange for the year still in progress.
const BAR_COLOR = { history: '#8FA3C4', base: CHART_COLORS.heroInventory, ytd: '#F28C28' };
const BAND_COLOR = '#F28C28';
const BAND_INK = '#C2410C';
const AXIS_TITLE = { fontSize: 11, fontWeight: 600, fill: CHART_COLORS.axisLabel };

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
  const rows = years.map((y) => {
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
  // Year over year (2026-10-19): a full year against the full year before
  // it, under its label; never for a partial year, and never across a gap.
  return rows.map((r, i) => {
    const prev = rows[i - 1];
    const full = (x) => x && x.value != null && x.months === 12;
    const yoy = full(r) && full(prev) && prev.year === r.year - 1 && prev.value > 0
      ? ((r.value - prev.value) / prev.value) * 100
      : null;
    return { ...r, yoy, yoyAgainst: yoy != null ? prev.key : null };
  });
};

// The allocation card's own range (lowest to highest level), for a full
// base year only: the API leaves `annual` null when the base year is partial.
const buildBand = (allocation, selectedPct = null) => {
  if (!allocation || allocation.blocked_reason) return null;
  const levels = (allocation.levels || []).filter((l) => l.annual != null);
  if (levels.length < 2) return null;
  const low = levels.reduce((a, b) => (b.annual < a.annual ? b : a));
  const high = levels.reduce((a, b) => (b.annual > a.annual ? b : a));
  const line = levels.find((l) => l.pct === (selectedPct ?? allocation.default_pct)) || low;
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
const fadeId = (role) => `annual-view-fade-${role}`;

// "All 12 months are synthetic" / "3 of 12 months are synthetic".
const syntheticText = (row) => {
  if (row.synthetic === row.months) {
    return row.months === 1 ? 'Its one month on record is synthetic' : `All ${row.months} months are synthetic`;
  }
  return `${row.synthetic} of ${row.months} months ${row.synthetic === 1 ? 'is' : 'are'} synthetic`;
};

// The hover, in the dashboard's shared boxes (ui/ChartParts): one box in
// the bar's own colour — the year and its months on record, the pesos,
// what they are — with the "to go" and base-year lines under it; a year
// with nothing on record, or synthetic months, as a plain note.
const AnnualTooltip = ({ active, payload, band }) => {
  const row = active && payload?.[0]?.payload;
  if (!row) return null;
  const period = `FY ${row.year}${row.span ? ` · ${row.span}` : ''}`;
  if (row.value == null) {
    return (
      <Callouts>
        <CalloutNote>
          {period}: {row.year < FIRST_DATA_YEAR
            ? `no data recorded before ${FIRST_DATA_YEAR} — SSM\u2019s records start in January ${FIRST_DATA_YEAR}.`
            : 'no sales on record.'}
        </CalloutNote>
      </Callouts>
    );
  }
  return (
    <Callouts>
      <Callout
        color={BAR_COLOR[row.role]}
        period={period}
        value={formatCompactPesos(row.value)}
        name={row.toGo != null ? 'Sales so far' : 'Total sales'}
      >
        <CalloutLine>{row.months} of 12 months on record{row.partial ? ', not a full year' : ''}</CalloutLine>
        {row.yoy != null && (
          <CalloutLine><strong>{row.yoy >= 0 ? '+' : '−'}{Math.abs(row.yoy).toFixed(1)}%</strong> on {row.yoyAgainst}</CalloutLine>
        )}
        {row.toGo != null && band && (
          <CalloutLine><strong>{formatCompactPesos(row.toGo)}</strong> to go to the {formatCompactPesos(band.line)} target</CalloutLine>
        )}
        {row.role === 'base' && band && <CalloutLine>Base year of the {fy(band.year)} allocation target</CalloutLine>}
      </Callout>
      {row.synthetic > 0 && <CalloutNote>{syntheticText(row)}, not SSM&apos;s own figures.</CalloutNote>}
    </Callouts>
  );
};

// The year, and under it the months on record when the year is not full,
// or its change on the year before when it is (green up, red down).
const YOY_UP = '#2A8551';
const YOY_DOWN = '#D54848';
const YearTick = ({ x, y, payload, rows }) => {
  const row = rows.find((r) => r.key === payload.value);
  return (
    <g transform={`translate(${x},${y})`}>
      <text dy={12} textAnchor="middle" fill={CHART_COLORS.axisLabel} fontSize={11}>{payload.value}</text>
      {row?.span && (
        <text dy={25} textAnchor="middle" fill={BAND_INK} fontSize={11} fontWeight={600}>{row.span}</text>
      )}
      {row && row.value == null && (
        <text dy={25} textAnchor="middle" fill={CHART_COLORS.axisLabel} fontSize={11}>no data</text>
      )}
      {row?.yoy != null && (
        <text dy={25} textAnchor="middle" fill={row.yoy >= 0 ? YOY_UP : YOY_DOWN} fontSize={11} fontWeight={600}>
          {row.yoy >= 0 ? '+' : '−'}{Math.abs(row.yoy).toFixed(1)}%
        </text>
      )}
    </g>
  );
};

// The figure above each bar, on a white halo so the band's dashed line
// (which sits just above the tallest bars) never strikes through it.
//
// On a phone the bars stand about 50px apart and "₱384.8M" beside
// "₱387.3M" ran into each other. Each bar carries its figure twice, in full
// and rounded to the whole million (₱385M, a size smaller), and the card's
// width picks which one shows (AnnualViewChart.css). The tooltip always has
// the decimal.
const BarValue = ({ x, y, width, value }) => {
  if (value == null) return null;
  const text = { x: x + width / 2, y: y - 6, textAnchor: 'middle', fill: '#344054', fontWeight: 600, stroke: '#fff', strokeWidth: 3, paintOrder: 'stroke' };
  const short = Math.abs(value) >= 1_000_000 ? `₱${Math.round(value / 1_000_000)}M` : formatCompactPesos(value);
  return (
    <g>
      <text {...text} fontSize={11} className="annual-view-value">{formatCompactPesos(value)}</text>
      <text {...text} fontSize={11} className="annual-view-value-short" aria-hidden="true">{short}</text>
    </g>
  );
};

// "₱340.1M" over "to go", in the middle of the dashed bar (empty space, so
// it covers nothing), two lines so it stays inside the bar's width.
const ToGoLabel = ({ x, y, width, height, value }) => {
  if (value == null || !(height > 32)) return null;
  const cx = x + width / 2;
  const cy = y + height / 2;
  const text = { x: cx, textAnchor: 'middle', fill: BAND_INK, fontSize: 9.5, fontWeight: 600 };
  return (
    <g>
      <text {...text} y={cy - 2}>{formatCompactPesos(value)}</text>
      <text {...text} y={cy + 10}>to go</text>
    </g>
  );
};

// One label above the band, left-aligned: the target picked and the band's
// range ("103% target · ₱405.2M · band 103–108%"), clear of the bars, the
// band and the dashed "to go" bar (2026-10-19).
const BandLabel = ({ viewBox, band }) => {
  if (!viewBox || !band) return null;
  return (
    <text
      x={viewBox.x + 2}
      y={viewBox.y - 6}
      textAnchor="start"
      fill={BAND_INK}
      fontSize={11}
      fontWeight={600}
      className="annual-view-band-label"
    >
      {band.linePct}% target · {formatCompactPesos(band.line)} · band {band.pcts}
    </text>
  );
};

// "No data recorded" / "SSM's records start Jan 2023", centred in the slot of
// a year with no figure. The years are equal slots across the plot, so a
// slot's centre is its place in the row; four short lines fit a narrow slot.
const EmptyYearLabels = ({ rows, start }) => {
  const plot = usePlotArea();
  if (!plot || !rows.length) return null;
  const slot = plot.width / rows.length;
  const lines = [
    ['No data', '#667085', 600, 10.5],
    ['recorded', '#667085', 600, 10.5],
    ["SSM's records", '#98A2B3', 400, 9.5],
    [`start ${start}`, '#98A2B3', 400, 9.5],
  ];
  return (
    <g className="annual-view-empty">
      {rows.map((r, i) => (r.value != null ? null : (
        <g key={r.key}>
          {lines.map(([text, fill, weight, size], k) => (
            <text
              key={text}
              x={plot.x + (i + 0.5) * slot}
              y={plot.y + plot.height * 0.62 + k * 13 + (k >= 2 ? 4 : 0)}
              textAnchor="middle"
              fill={fill}
              fontSize={size}
              fontWeight={weight}
            >
              {text}
            </text>
          ))}
        </g>
      )))}
    </g>
  );
};

const AnnualViewChart = ({ annual, allocation, note, selectedPct = null }) => {
  const allRows = buildRows(annual, allocation);
  const hasData = allRows.some((r) => r.value != null);
  const band = hasData && allRows.some((r) => r.role === 'base') ? buildBand(allocation, selectedPct) : null;
  // Every year of the window stays, an empty one as a labelled slot; with
  // synthetic data on, the years it fills have a (hatched) figure. The year
  // in progress gets its "to go" bar up to the selected target, when it is
  // that target's year.
  const rows = allRows
    .map((r) => ({
      ...r,
      toGo: band && r.value != null && r.role === 'ytd' && r.year === band.year && band.line > r.value ? band.line - r.value : null,
    }));
  const hidden = allRows.filter((r) => r.value == null);
  // When SSM's own records start for this principal: the first month of the
  // earliest year with a real (not all-synthetic) month, else Jan of
  // FIRST_DATA_YEAR (both principals start Jan 2023).
  const firstReal = (annual?.years || [])
    .filter((y) => y.sales != null && (y.synthetic_months?.length || 0) < y.months && y.first_month)
    .map((y) => y.first_month)
    .sort()[0];
  const recordsStart = firstReal
    ? `${MONTHS[monthNumber(firstReal) - 1]} ${firstReal.slice(0, 4)}`
    : `Jan ${FIRST_DATA_YEAR}`;
  const hasToGo = rows.some((r) => r.toGo != null);
  const ytd = rows.find((r) => r.role === 'ytd');
  const base = rows.find((r) => r.role === 'base');
  const synthetic = rows.filter((r) => r.synthetic > 0);
  const earlier = annual?.earlier_years || [];

  const top = Math.max(0, ...rows.map((r) => r.value ?? 0), band?.high ?? 0);
  // Headroom for the labels above the bars and the band's name above it.
  const step = niceStep(top * 1.12);
  const ceiling = Math.max(step, Math.ceil((top * 1.12) / step) * step);
  const ticks = Array.from({ length: Math.round(ceiling / step) + 1 }, (_, i) => i * step);

  // Plain words for SSM's staff (2026-10-15); was "Annual View: 5-Year
  // Trend vs. FY26 Target Band".

  return (
    <div className={`chart-widget annual-view${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>
            <span>Sales <span className="title-accent">per year</span>{band ? `, against the ${fy(band.year)} target` : ''}</span>
            <InfoTip label="About Sales per year" size={13}>
              <span className="chart-tip-line">
                Each bar is one year&apos;s total sales (Jan–Dec). Years with missing months show only what&apos;s
                recorded{ytd?.span ? `, so ${ytd.key} is ${ytd.span} only` : ''}.
                {band && (
                  <>
                    {' '}The band is FY {band.basisYear} sales × SSM&apos;s targets ({band.pcts}); the dashed line is the
                    target selected on the Summary card{hasToGo ? ', and the dashed bar is what is still to go to it' : ''}.
                  </>
                )}
                {' '}This chart shows all years and doesn&apos;t follow the date filter.
              </span>
              <span className="chart-tip-line">
                SSM&apos;s records start {recordsStart}
                {hidden.length > 0 ? `, so ${hidden.map((r) => r.key).join(' and ')} ${hidden.length === 1 ? 'has' : 'have'} no data and ${hidden.length === 1 ? 'shows' : 'show'} as an empty slot` : ''};
                {' '}earlier years appear as hatched bars only with synthetic data on.
                {earlier.length > 0 && <> Also on record, before these years: {earlier.map(fy).join(', ')}.</>}
              </span>
              {note && <span className="chart-tip-line">{note}.</span>}
            </InfoTip>
            <BasisTag label="All years" follows={false} />
          </h4>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">
          {/* No annual_sales at all is a backend older than this card
              (2026-10-18: seen when the API had not been restarted or
              redeployed), not missing data; it says so. */}
          {annual == null
            ? "The backend didn't send yearly totals. It may need a restart or redeploy."
            : annual.blocked_reason || 'Yearly sales totals are not available yet.'}
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
            {hasToGo && (
              <span><i className="annual-view-legend-togo" />To go to the {band.linePct}% target</span>
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
                  {/* Every bar fades down to the floor the dashboard's other
                      bars fade to; a synthetic year keeps its hatch. */}
                  {Object.entries(BAR_COLOR).map(([role, color]) => (
                    <Fade key={`fade-${role}`} id={fadeId(role)} color={color} to={BAR_FADE_FLOOR} />
                  ))}
                  {Object.entries(BAR_COLOR).map(([role, color]) => (
                    <pattern key={role} id={hatchId(role)} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                      <rect width="7" height="7" fill={color} />
                      <rect width="3" height="7" fill="#fff" fillOpacity="0.55" />
                    </pattern>
                  ))}
                </defs>
                <CartesianGrid {...GRID_PROPS} vertical={false} />
                {/* Both axes say what they count (Sir Catubag, 2 Oct 2026),
                    as every other chart on the page does. */}
                <XAxis
                  dataKey="key"
                  tickLine={false}
                  axisLine={{ stroke: CHART_COLORS.gridline }}
                  interval={0}
                  height={48}
                  tick={<YearTick rows={rows} />}
                  label={{ value: 'Year', position: 'insideBottom', offset: 0, ...AXIS_TITLE }}
                />
                <YAxis
                  domain={[0, ceiling]}
                  ticks={ticks}
                  tickFormatter={(v) => formatCompactPesos(v)}
                  tickLine={false}
                  axisLine={false}
                  width={64}
                  tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
                  label={{ value: 'Pesos (₱)', angle: -90, position: 'insideLeft', textAnchor: 'middle', ...AXIS_TITLE }}
                />
                <Tooltip content={<AnnualTooltip band={band} />} cursor={{ fill: 'rgba(148, 163, 184, 0.12)' }} />
                {band && (
                  <ReferenceArea
                    y1={band.low}
                    y2={band.high}
                    fill={BAND_COLOR}
                    fillOpacity={0.12}
                    stroke="none"
                    label={<BandLabel band={band} />}
                  />
                )}
                {band && (
                  <ReferenceLine y={band.line} stroke={BAND_INK} strokeDasharray="5 4" />
                )}
                <Bar dataKey="value" stackId="year" radius={[6, 6, 0, 0]} maxBarSize={56} isAnimationActive={false}>
                  {rows.map((r) => (
                    <Cell
                      key={r.key}
                      fill={r.synthetic > 0 ? `url(#${hatchId(r.role)})` : `url(#${fadeId(r.role)})`}
                      stroke={r.synthetic > 0 ? BAR_COLOR[r.role] : 'none'}
                    />
                  ))}
                  <LabelList dataKey="value" content={<BarValue />} />
                </Bar>
                {hidden.length > 0 && <EmptyYearLabels rows={rows} start={recordsStart} />}
                {hasToGo && (
                  <Bar
                    dataKey="toGo"
                    stackId="year"
                    fill="none"
                    stroke={BAND_INK}
                    strokeWidth={1.5}
                    strokeDasharray="5 3"
                    maxBarSize={56}
                    isAnimationActive={false}
                  >
                    <LabelList dataKey="toGo" content={<ToGoLabel />} />
                  </Bar>
                )}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
};

export default AnnualViewChart;
