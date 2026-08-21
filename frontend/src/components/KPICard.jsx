import React from 'react';
import { ArrowUp, ArrowDown } from 'lucide-react';
import { STATUS_TIERS } from '../theme/colors';
import './KPICard.css';

// "colour marks what is genuinely wrong" — the caller supplies raw facts
// (direction, isOverTarget, a trend arrow), never a pre-decided tier, and
// this is the one place that turns metricType + those facts into a colour.
// That keeps every card's colour rule uniform and inspectable in one spot
// instead of re-implemented ad hoc per card in Dashboard.jsx.
//
// metricType:
//   'loss'           — any amount is bad; colour by direction ('worse'/
//                       'better') only, never by the amount itself.
//   'gap'             — the raw amount is normal; only exceeding a target
//                       is bad, so colour comes from isOverTarget instead
//                       of direction — this is the one exception where
//                       amount and colour are allowed to agree.
//   'recommendation'  — model output, not a health metric. Always the
//                       neutral 'action' tier, never red or green.
function tierFor(metricType, direction, isOverTarget) {
  if (metricType === 'recommendation') return 'action';
  if (metricType === 'gap') return isOverTarget ? 'loss' : 'healthy';
  if (direction === 'worse') return 'loss';
  if (direction === 'better') return 'healthy';
  return 'diagnostic';
}

// contextLine: always-muted supporting line (raw values, no arrow) —
// rendered first when present.
// deltaLine: tier-coloured supporting line, paired with the arrow so the
// comparison survives in greyscale — rendered after contextLine.
const KPICard = ({
  title,
  value,
  icon,
  metricType,
  direction,
  isOverTarget,
  trendDirection,
  contextLine,
  deltaLine,
}) => {
  const tierColor = STATUS_TIERS[tierFor(metricType, direction, isOverTarget)];
  const TrendIcon = trendDirection === 'up' ? ArrowUp : trendDirection === 'down' ? ArrowDown : null;

  return (
    <div className="kpi-card" style={{ borderLeftColor: tierColor }}>
      <div className="kpi-header">
        <h3 className="kpi-title">{title}</h3>
        {icon && <div className="kpi-icon" style={{ color: tierColor }}>{icon}</div>}
      </div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-footer">
        {contextLine && <div className="kpi-context">{contextLine}</div>}
        {deltaLine && (
          <div className="kpi-subtext" style={{ color: tierColor }}>
            {TrendIcon && <TrendIcon size={12} className="kpi-trend-icon" />}
            {deltaLine}
          </div>
        )}
      </div>
    </div>
  );
};

export default KPICard;
