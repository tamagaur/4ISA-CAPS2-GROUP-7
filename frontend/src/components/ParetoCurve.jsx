// The Pareto curve of a ranking over the selected range (GET /dashboard/pareto):
// the products in rank order along the bottom, their running share of revenue
// up the side. The 2 Oct to-do list asked for "Pareto chart + list of the top
// grossers for the selected range"; the list was there, the curve only in the
// ABC page's one-month view (AbcBreakdowns.jsx), by brand.
//
// One point per ranked product would be a thousand bars, so this draws the
// running total as an area, coloured by class, with the run's own cut-offs
// (the payload's `cutoffs`, never a retyped 80/95) and a dot where Class A
// ends: the sentence under the title reads that dot.
import React, { useMemo } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { CHART_COLORS } from '../theme/colors';
import { GRID_PROPS } from './ChartZoom';
import './ParetoCurve.css';

const TIERS = ['A', 'B', 'C'];
const TIER_COLOR = { A: CHART_COLORS.abcRamp[0], B: CHART_COLORS.abcRamp[1], C: CHART_COLORS.abcRamp[2] };
// Enough points for a smooth curve at any card width; class boundaries are
// always kept, so the dot and the colour changes sit on real products.
const MAX_POINTS = 240;

const CurveTooltip = ({ active, payload, many }) => {
  const point = active && payload?.[0]?.payload;
  if (!point || !point.count) return null;
  return (
    <div className="chart-tooltip">
      <p className="tooltip-label">Top {point.count.toLocaleString()} {many}</p>
      <p className="tooltip-item">{point.x.toFixed(1)}% of those ranked</p>
      <p className="tooltip-item">{point.y.toFixed(1)}% of revenue</p>
    </div>
  );
};

const ParetoCurve = ({ block, cutoffs = null, label = 'the selected range', height = 220 }) => {
  const many = block?.grain === 'category' ? 'categories' : 'SKUs';
  const { points, aEnd, total } = useMemo(() => {
    const ranked = (block?.classes || [])
      .flatMap((cls) => (cls.products || []).map((p) => ({ rank: p.rank, share: p.cumulative_share, tier: cls.tier })))
      .filter((p) => p.share != null)
      .sort((a, b) => a.rank - b.rank);
    const n = ranked.length;
    if (n === 0) return { points: [], aEnd: null, total: 0 };
    const step = Math.max(1, Math.ceil(n / MAX_POINTS));
    const out = [{ x: 0, y: 0, count: 0, yA: 0 }];
    let lastA = null;
    ranked.forEach((p, i) => {
      const boundary = i === n - 1 || ranked[i + 1].tier !== p.tier;
      if (!boundary && i % step !== 0) return;
      const point = { x: ((i + 1) / n) * 100, y: p.share * 100, count: i + 1 };
      point[`y${p.tier}`] = point.y;
      // A boundary point belongs to both classes, so the areas meet.
      if (boundary && i < n - 1) point[`y${ranked[i + 1].tier}`] = point.y;
      if (p.tier === 'A') lastA = point;
      out.push(point);
    });
    return { points: out, aEnd: lastA, total: n };
  }, [block]);

  if (total < 3 || block?.blocked_reason) return null;
  const aCut = cutoffs?.A != null ? cutoffs.A * 100 : null;
  const bCut = cutoffs?.B != null ? cutoffs.B * 100 : null;

  return (
    <figure className="pareto-curve">
      <figcaption className="pareto-curve-caption">
        <strong>Pareto curve</strong>
        {aEnd && (
          <span>
            {' '}· the top {aEnd.count.toLocaleString()} {many} ({aEnd.x.toFixed(0)}% of the {total.toLocaleString()} ranked)
            make {aEnd.y.toFixed(0)}% of {label} revenue
          </span>
        )}
      </figcaption>
      <div className="pareto-curve-legend" aria-hidden="true">
        {TIERS.map((t) => <span key={t}><i style={{ backgroundColor: TIER_COLOR[t] }} />Class {t}</span>)}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={points} margin={{ top: 8, right: 16, left: 4, bottom: 18 }}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis
            type="number"
            dataKey="x"
            domain={[0, 100]}
            ticks={[0, 20, 40, 60, 80, 100]}
            tickFormatter={(v) => `${v}%`}
            tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
            label={{ value: `${many} in rank order (% of those ranked)`, position: 'insideBottom', offset: -10, fill: CHART_COLORS.axisLabel, fontSize: 11 }}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 20, 40, 60, 80, 100]}
            tickFormatter={(v) => `${v}%`}
            tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }}
            width={54}
            label={{ value: 'Running % of revenue', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fill: CHART_COLORS.axisLabel, fontSize: 11 } }}
          />
          <Tooltip content={<CurveTooltip many={many} />} />
          {aCut != null && (
            <ReferenceLine y={aCut} stroke={CHART_COLORS.cumulativeCurve} strokeDasharray="4 3" label={{ value: `A ${Math.round(aCut)}%`, position: 'insideTopRight', fill: CHART_COLORS.axisLabel, fontSize: 11 }} />
          )}
          {bCut != null && (
            <ReferenceLine y={bCut} stroke={CHART_COLORS.cumulativeCurve} strokeDasharray="2 3" label={{ value: `B ${Math.round(bCut)}%`, position: 'insideTopRight', fill: CHART_COLORS.axisLabel, fontSize: 11 }} />
          )}
          {TIERS.map((t) => (
            <Area
              key={t}
              type="linear"
              dataKey={`y${t}`}
              stroke={TIER_COLOR[t]}
              strokeWidth={2}
              fill={TIER_COLOR[t]}
              fillOpacity={0.18}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
          {aEnd && (
            <ReferenceDot x={aEnd.x} y={aEnd.y} r={5} fill={TIER_COLOR.A} stroke="var(--color-surface, #fff)" strokeWidth={2} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </figure>
  );
};

export default ParetoCurve;
