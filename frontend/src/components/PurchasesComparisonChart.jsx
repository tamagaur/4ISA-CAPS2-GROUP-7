// The "Purchases" view of the dashboard's Sales vs Inventory Value card
// (layout pass, 2026-10-13). For each month, Jan to Dec: a solid bar for
// sales, a light outlined bar for purchases beside it, and the same month's
// sales a year earlier as a wider pale bar behind the sales bar.
//
// LAYOUT PREVIEW ONLY. Every value drawn here comes from
// MOCK_PURCHASES_COMPARISON below. Nothing is read from GET /dashboard and
// nothing is calculated: the real sales, purchases and prior-year figures,
// and the rule for which year the bars stand for, are pending further
// instructions. When they arrive, the mock constant is replaced by a `data`
// prop of the same shape and the "Mock data" pill goes away with it.
//
// Last year's sales were first drawn as a short dash per month, as in the
// reference picture. Audrey chose the bar behind on 2026-10-13: a dash
// floats free of the bars when last year was the higher one and, lying
// across the pair, could be read as belonging to purchases too. A bar
// behind starts at ₱0 like the sales bar, so the two years are compared
// length against length, and it stands behind sales alone.
import React, { useLayoutEffect, useRef, useState } from 'react';
import {
  Bar, CartesianGrid, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { CHART_COLORS } from '../theme/colors';
import { chartAnim } from '../theme/motion';
import { formatCompactPesos } from '../utils/formatters';
import { GRID_PROPS } from './ChartZoom';
import './PurchasesComparisonChart.css';

// ---- TEMPORARY MOCK DATA — replace with real figures -----------------------
// Placeholder pesos so the chart can be designed; they are not SSM's sales
// or purchases, and they are not the reference picture's numbers either.
// Round millions on purpose, so nobody takes them for a measurement.
const M = 1_000_000;
const MOCK_PURCHASES_COMPARISON = [
  { month: 'Jan', sales: 28 * M, purchases: 30 * M, previousSales: 26 * M },
  { month: 'Feb', sales: 26 * M, purchases: 21 * M, previousSales: 28 * M },
  { month: 'Mar', sales: 31 * M, purchases: 24 * M, previousSales: 33 * M },
  { month: 'Apr', sales: 27 * M, purchases: 33 * M, previousSales: 24 * M },
  { month: 'May', sales: 30 * M, purchases: 20 * M, previousSales: 32 * M },
  { month: 'Jun', sales: 33 * M, purchases: 28 * M, previousSales: 30 * M },
  { month: 'Jul', sales: 25 * M, purchases: 41 * M, previousSales: 27 * M },
  { month: 'Aug', sales: 29 * M, purchases: 23 * M, previousSales: 31 * M },
  { month: 'Sep', sales: 32 * M, purchases: 35 * M, previousSales: 29 * M },
  { month: 'Oct', sales: 34 * M, purchases: 27 * M, previousSales: 30 * M },
  { month: 'Nov', sales: 30 * M, purchases: 38 * M, previousSales: 26 * M },
  { month: 'Dec', sales: 22 * M, purchases: 29 * M, previousSales: 31 * M },
];
// ----------------------------------------------------------------------------

// Colour tells the year, as on the card's other views: both of this year's
// bars wear `color` (sales solid, purchases a light fill with an outline)
// and last year's bar wears `previousColor`, much lighter, so the eye goes
// to this year first. The card passes each year's own colour; these are
// the fallbacks for a chart drawn without them.
const DEFAULT_COLOR = CHART_COLORS.heroSales;
const DEFAULT_PREVIOUS_COLOR = '#64748B';
const PURCHASES_FILL_OPACITY = 0.2;
// How much of last year's colour its bar keeps; the rest is the card's white.
const PREVIOUS_TINT = 0.32;
// A colour mixed into white, as a solid: a see-through fill would let the
// gridlines show through the bar.
const tint = (hex, share) => {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex;
  const n = parseInt(hex.slice(1), 16);
  const mix = (channel) => Math.round(255 - (255 - channel) * share);
  return `rgb(${mix(n >> 16)}, ${mix((n >> 8) & 255)}, ${mix(n & 255)})`;
};

// Sizes follow the chart's own width, measured below, not the window's: the
// card is narrower with the menu open than with it closed at the same
// window size. Under MIN_CHART_WIDTH twelve groups of bars are too thin to
// read, so the plot keeps that width and scrolls sideways inside its box.
const MIN_CHART_WIDTH = 480;
const NARROW_CHART_WIDTH = 560;
const MARGIN = { top: 16, right: 12, left: 0, bottom: 10 };
const MAX_BAR = 22;
const MIN_BAR = 5;
const BAR_RADIUS = 4;
// How much of a month's slot its bars may take.
const GROUP_SHARE = 0.74;
// How far last year's bar shows on each side of this year's sales bar, as
// a share of the bar's width.
const SHOULDER_SHARE = 0.3;

const AXIS_TITLE = { fontSize: 10, fontWeight: 600, fill: CHART_COLORS.axisLabel };
// Room for the "Month" title under the ticks, as on the card's other views.
const X_AXIS_HEIGHT = 44;

const useElementWidth = (ref) => {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => setWidth(el.getBoundingClientRect().width);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
};

// A round step that gives about five gridlines, from ₱0: a bar's length is
// its value, so this axis never starts above zero.
const pesoTicks = (rows) => {
  const top = Math.max(0, ...rows.flatMap((r) => [r.sales, r.purchases, r.previousSales]).filter((v) => v != null));
  if (!(top > 0)) return [0];
  const raw = top / 5;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 2.5, 5, 10].find((f) => f * magnitude >= raw) || 10) * magnitude;
  const ticks = [];
  for (let v = 0; v < top + step; v += step) ticks.push(v);
  return ticks;
};

const formatExactPesos = (value) => `₱${Math.round(value).toLocaleString('en-PH')}`;

// A bar's outline with rounded top corners and a square foot on the baseline.
const topRounded = (x, y, width, height, radius) => {
  const r = Math.max(0, Math.min(radius, width / 2, height));
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
};

// The three keys, drawn the way the plot draws each bar.
const Swatch = ({ kind, color }) => (
  <span
    className="purchases-compare-swatch"
    style={kind === 'purchases'
      ? {
          backgroundColor: `color-mix(in srgb, ${color} ${PURCHASES_FILL_OPACITY * 100}%, transparent)`,
          boxShadow: `inset 0 0 0 1.5px ${color}`,
        }
      : { backgroundColor: color }}
    aria-hidden="true"
  />
);

// The hovered month: a soft band behind its bars, as wide as the month's
// slot. Recharts hands a mixed chart's cursor the two ends of a vertical
// line through the month's centre; the band is drawn around it.
const MonthBand = ({ points, band }) => {
  if (!points || points.length < 2) return null;
  const [top, bottom] = points;
  return (
    <rect
      x={top.x - band / 2}
      y={top.y}
      width={band}
      height={Math.max(0, bottom.y - top.y)}
      rx={4}
      fill="rgba(15, 23, 42, 0.05)"
      pointerEvents="none"
    />
  );
};

const ComparisonTooltip = ({ active, payload, series, mock }) => {
  const row = active && payload?.[0]?.payload;
  if (!row) return null;
  const lines = series.filter((sr) => row[sr.key] != null);
  return (
    <div className="chart-tooltip">
      <p className="purchases-compare-tooltip-month">{row.month}</p>
      {lines.map((sr) => (
        <p key={sr.key} className="chart-tooltip-row purchases-compare-tooltip-row">
          <Swatch kind={sr.key} color={sr.color} />
          <span>{sr.name}</span>
          <strong>{formatExactPesos(row[sr.key])}</strong>
        </p>
      ))}
      {mock && <p className="chart-tooltip-placeholder">Mock values, layout preview only</p>}
    </div>
  );
};

// `year` and `previousYear` only name the bars in the legend and tooltip;
// which year the bars really stand for is part of the pending date rules.
// `color` and `previousColor` are those two years' colours on the card.
// `purchasesEstimated` adds "(est.)" to the purchases label, for when the
// figures drawn are an estimate and not purchase records.
const PurchasesComparisonChart = ({
  data = MOCK_PURCHASES_COMPARISON,
  mock = data === MOCK_PURCHASES_COMPARISON,
  year = null,
  previousYear = null,
  color = DEFAULT_COLOR,
  previousColor = DEFAULT_PREVIOUS_COLOR,
  purchasesEstimated = false,
}) => {
  const boxRef = useRef(null);
  const boxWidth = useElementWidth(boxRef);
  const scrolls = boxWidth > 0 && boxWidth < MIN_CHART_WIDTH;
  const chartWidth = Math.max(boxWidth, MIN_CHART_WIDTH);
  const narrow = chartWidth < NARROW_CHART_WIDTH;
  const yAxisWidth = narrow ? 54 : 64;

  // One month's slot, then the bars inside it, left to right: last year's
  // shoulder, this year's sales bar, the other shoulder, a gap, the
  // purchases bar. The bar width is set outright (not left to Recharts) so
  // the bars stay together in the middle of their slot and last year's bar
  // can be drawn around the sales bar to the pixel.
  const slot = (chartWidth - yAxisWidth - MARGIN.left - MARGIN.right) / data.length;
  const gap = slot < 40 ? 2 : 3;
  const barSize = Math.max(MIN_BAR, Math.min(MAX_BAR, Math.floor((slot * GROUP_SHARE - gap) / (2 + SHOULDER_SHARE * 2))));
  const shoulder = Math.max(2, Math.round(barSize * SHOULDER_SHARE));
  const barGap = gap + shoulder;
  const pairWidth = barSize * 2 + barGap;

  const previousFill = tint(previousColor, PREVIOUS_TINT);
  const series = [
    { key: 'sales', name: year ? `Sales ${year}` : 'Sales', color },
    { key: 'purchases', name: `${year ? `Purchases ${year}` : 'Purchases'}${purchasesEstimated ? ' (est.)' : ''}`, color },
    { key: 'previousSales', name: previousYear ? `Sales ${previousYear}` : 'Sales, previous year', color: previousFill },
  ];
  const [sales, purchases, previous] = series;
  const ticks = pesoTicks(data);

  // Last year's bar, on a month axis of its own so it takes no place beside
  // the other two. It is laid out as wide as the pair, so its left edge is
  // the sales bar's left edge; from there it is drawn around the sales bar,
  // a shoulder wider on each side.
  const previousBar = ({ x, y, height }) => (height > 0
    ? <path d={topRounded(x - shoulder, y, barSize + shoulder * 2, height, BAR_RADIUS)} fill={previousFill} />
    : null);

  return (
    <div className="purchases-compare">
      <div className="purchases-compare-top">
        <ul className="custom-legend custom-legend-top purchases-compare-legend">
          {series.map((sr) => (
            <li key={sr.key} className="legend-item"><Swatch kind={sr.key} color={sr.color} />{sr.name}</li>
          ))}
        </ul>
        {mock && (
          <span className="purchases-compare-mock" title="Layout preview: these values are placeholders, not SSM's data">
            Mock data
          </span>
        )}
      </div>
      <div
        className="purchases-compare-scroll"
        ref={boxRef}
        {...(scrolls ? { tabIndex: 0, role: 'group', 'aria-label': 'Monthly chart, scrolls sideways' } : {})}
      >
        <div className="chart-container chart-container-yoy" style={{ minWidth: MIN_CHART_WIDTH }}>
          <ResponsiveContainer width="99%" height="100%">
            <ComposedChart data={data} margin={MARGIN} barGap={barGap}>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis
                dataKey="month"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: narrow ? 9 : 10, fill: CHART_COLORS.axisLabel }}
                dy={10}
                interval={0}
                height={X_AXIS_HEIGHT}
                label={{ value: 'Month', position: 'insideBottom', offset: 0, ...AXIS_TITLE }}
              />
              <XAxis xAxisId="previous" dataKey="month" hide />
              <YAxis
                axisLine={false}
                tickLine={false}
                width={yAxisWidth}
                tick={{ fontSize: narrow ? 9 : 10, fill: CHART_COLORS.axisLabel }}
                tickFormatter={(v) => formatCompactPesos(v)}
                domain={[0, ticks[ticks.length - 1]]}
                ticks={ticks}
                label={{ value: 'Pesos (₱)', angle: -90, position: 'insideLeft', textAnchor: 'middle', ...AXIS_TITLE }}
              />
              <Tooltip
                cursor={<MonthBand band={slot} />}
                content={<ComparisonTooltip series={series} mock={mock} />}
              />
              {/* Drawn first, so this year's sales bar sits in front of it. */}
              <Bar
                xAxisId="previous"
                dataKey="previousSales"
                name={previous.name}
                barSize={pairWidth}
                shape={previousBar}
                {...chartAnim()}
              />
              {/* The sales bar keeps a hairline of the card's own colour, so
                  its fill never touches last year's behind it. */}
              <Bar
                dataKey="sales"
                name={sales.name}
                fill={color}
                stroke="var(--color-surface, #fff)"
                strokeWidth={1}
                barSize={barSize}
                radius={[BAR_RADIUS, BAR_RADIUS, 0, 0]}
                {...chartAnim()}
              />
              <Bar
                dataKey="purchases"
                name={purchases.name}
                fill={color}
                fillOpacity={PURCHASES_FILL_OPACITY}
                stroke={color}
                strokeWidth={1.5}
                barSize={barSize}
                radius={[BAR_RADIUS, BAR_RADIUS, 0, 0]}
                {...chartAnim(1)}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
      {scrolls && <p className="purchases-compare-note">Swipe sideways to see all 12 months.</p>}
      {mock && (
        <p className="purchases-compare-note">
          Layout preview only: these bars are placeholder values, not SSM&apos;s figures. The recorded months are in the Table view.
        </p>
      )}
    </div>
  );
};

export default PurchasesComparisonChart;
