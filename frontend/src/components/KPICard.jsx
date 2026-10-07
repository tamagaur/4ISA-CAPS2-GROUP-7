import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowUp, ArrowDown, ArrowRight, AlertTriangle } from 'lucide-react';
import { STATUS_TIERS, SEMANTIC } from '../theme/colors';
import InfoTip from './InfoTip';
import './KPICard.css';

// "colour marks what is genuinely wrong" — the caller supplies raw facts
// (direction, isOverTarget, a trend arrow), never a pre-decided tier, and
// this is the one place that turns metricType + those facts into a colour.
// That keeps every card's colour rule uniform and inspectable in one spot
// instead of re-implemented ad hoc per card in Dashboard.jsx.
//
// metricType:
//   'danger'          — an explicit "act now" signal (red) — e.g. a share
//                       of Category A SKUs at safety stock that's fallen
//                       below the act threshold, or cover under policy.
//   'watch'           — below target but not critical (amber).
//   'healthy'         — an explicit "fine" signal (green).
//   'loss'            — any amount is bad; colour by direction ('worse'/
//                       'better') only, never by the amount itself.
//   'gap'             — the raw amount is normal; only exceeding a target
//                       is bad, so colour comes from isOverTarget instead
//                       of direction — this is the one exception where
//                       amount and colour are allowed to agree.
//   'recommendation'  — model output, not a health metric. Always the
//                       neutral 'action' tier, never red or green.
//   'neutral' / none  — a plain figure (a sales total, a stock value) or a
//                       blocked card with nothing to judge: slate, the
//                       "no verdict" colour. Cards used to fall back to the
//                       indigo 'recommendation' tier here, which dressed a
//                       plain number up as model output.
function tierFor(metricType, direction, isOverTarget) {
  if (metricType === 'danger') return 'danger';
  if (metricType === 'watch') return 'loss';
  if (metricType === 'healthy') return 'healthy';
  if (metricType === 'recommendation') return 'action';
  if (metricType === 'gap') return isOverTarget ? 'loss' : 'healthy';
  if (direction === 'worse') return 'loss';
  if (direction === 'better') return 'healthy';
  return 'neutral';
}

// Card accent colours — the SEMANTIC tokens directly, so a card's border
// is the same pixel value as the chart segment or pill that means the same
// thing (a red card = red bars = red pill = "act now"). Border and icon use
// these; the small delta-line text keeps STATUS_TIERS colours because
// directional text is a different register from the card's chrome.
const CARD_ACCENT_COLORS = {
  danger:     SEMANTIC.act,
  loss:       SEMANTIC.watch,
  healthy:    SEMANTIC.healthy,
  neutral:    SEMANTIC.noData,
  action:     SEMANTIC.recommendation,
};

// 12-point sparkline beside the value (stat-tile contract): the history
// in a recessive gray, the CURRENT period as the one accented dot in the
// series' own hue — a shape cue, not a second chart, so no axes and no
// tooltip. `points` are the backend's real months only (nulls already
// dropped); under 2 points there is no shape to draw, so nothing renders.
const SPARK_W = 76;
const SPARK_H = 26;

const Sparkline = ({ points, color }) => {
  if (!points || points.length < 2) return null;
  const recent = points.slice(-12);
  const values = recent.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = SPARK_W / (recent.length - 1);
  const xy = values.map((v, i) => [i * step, SPARK_H - ((v - min) / span) * (SPARK_H - 4) - 2]);
  const path = xy.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const [lastX, lastY] = xy[xy.length - 1];
  return (
    <svg
      className="kpi-sparkline"
      width={SPARK_W}
      height={SPARK_H}
      viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
      aria-hidden="true"
    >
      <path d={path} fill="none" stroke="#CBD5E1" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r={3} fill={color} stroke="var(--color-surface, #fff)" strokeWidth={1.5} />
    </svg>
  );
};

// contextLine: always-muted supporting line (raw values, no arrow) —
// rendered first when present.
// deltaLine: tier-coloured supporting line, paired with the arrow so the
// comparison survives in greyscale — rendered after contextLine.
// trend: { points: [{period, value}], color } — the card's own metric,
// month by month, straight from the backend (kpis.sales_trend /
// kpis.soh_trend); cards without monthly history simply pass nothing.
// deltaTone: 'positive' | 'negative' | 'neutral' — renders deltaLine as a
// shaded pill coloured by the change itself, independent of the card's
// accent tier. Without it, deltaLine keeps the tier-coloured text line.
// unit: a short muted word after the value ("SKUs"); callers leave it off
// when the card is blocked and the value is "—".
// note: a second muted line under contextLine — another reading of the same
// figure (e.g. the range's total under a month's sales).
// flag: a caveat the reader must see beside the figure (e.g. a stock count
// the team judged unusual): a string, or { label, detail } — a short amber
// badge on the card with the full sentence one tap away.
// The status colour (metricType) marks the icon tile only, never the whole
// card (UI pass, 2026-10-08): four KPI cards side by side were four
// coloured stripes competing for the eye.
// action: { label, onClick } or { label, to } — the way from this figure to
// what is behind it (a list, another page), as a quiet link in the footer.
// The figure's detail sits one click away instead of on the card.
const KPICard = ({
  title,
  value,
  unit,
  icon,
  metricType,
  direction,
  isOverTarget,
  trendDirection,
  contextLine,
  note,
  flag,
  deltaLine,
  deltaTone,
  tooltip,
  trend,
  action,
}) => {
  const tier = tierFor(metricType, direction, isOverTarget);
  const accentColor = CARD_ACCENT_COLORS[tier]; // card chrome (border, icon)
  // STATUS_TIERS has no 'danger' entry of its own — it's the same "this got
  // worse" delta-text meaning as 'loss', just with different card chrome.
  const statusColor = STATUS_TIERS[tier === 'danger' ? 'loss' : tier]; // delta text only
  const TrendIcon = trendDirection === 'up' ? ArrowUp : trendDirection === 'down' ? ArrowDown : null;

  // `tooltip` holds a technical definition (e.g. weeks of cover) off the
  // always-visible text, behind a "?" that taps, hovers and tabs open.
  const flagLabel = flag && typeof flag === 'object' ? flag.label : flag;
  const flagDetail = flag && typeof flag === 'object' ? flag.detail : null;
  return (
    <div className="kpi-card" data-tier={tier}>
      <div className="kpi-header">
        {icon && (
          <div className="kpi-icon" style={{ color: accentColor, backgroundColor: `color-mix(in srgb, ${accentColor} 12%, white)` }}>
            {icon}
          </div>
        )}
        <h3 className="kpi-title">
          {title}
          {tooltip && <InfoTip label={`About ${title}`}>{tooltip}</InfoTip>}
        </h3>
      </div>
      <div className="kpi-value-row">
        <div className="kpi-value">
          {value}
          {unit && <span className="kpi-unit">{unit}</span>}
        </div>
        {trend && <Sparkline points={trend.points} color={trend.color} />}
      </div>
      <div className="kpi-footer">
        {contextLine && <div className="kpi-context">{contextLine}</div>}
        {note && <div className="kpi-context kpi-note">{note}</div>}
        {flagLabel && (
          <div className="kpi-flag">
            <AlertTriangle size={12} aria-hidden="true" />
            <span>{flagLabel}</span>
            {flagDetail && <InfoTip label={flagLabel} size={12}>{flagDetail}</InfoTip>}
          </div>
        )}
        {deltaLine && deltaTone && (
          <span className={`kpi-delta-pill is-${deltaTone}`}>
            {TrendIcon && <TrendIcon size={12} className="kpi-trend-icon" aria-hidden="true" />}
            {/* The arrow is decorative to a screen reader; say it. */}
            {trendDirection && <span className="visually-hidden">{trendDirection === 'up' ? 'Up ' : 'Down '}</span>}
            {deltaLine}
          </span>
        )}
        {deltaLine && !deltaTone && (
          <div className="kpi-subtext" style={{ color: statusColor }}>
            {TrendIcon && <TrendIcon size={12} className="kpi-trend-icon" />}
            {deltaLine}
          </div>
        )}
        {action && (action.to ? (
          <Link to={action.to} className="kpi-action">
            {action.label} <ArrowRight size={12} aria-hidden="true" />
          </Link>
        ) : (
          <button type="button" className="kpi-action" onClick={action.onClick}>
            {action.label} <ArrowRight size={12} aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );
};

export default KPICard;
