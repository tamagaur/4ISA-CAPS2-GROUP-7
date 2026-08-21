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

// Card accent colours — separate from STATUS_TIERS so the KPI card chrome
// never uses red (red is reserved for chart-layer alerts: data viz only).
// Border and icon use these non-red accents; the small delta-line text
// keeps STATUS_TIERS colours because directional text is a different
// semantic register from the card's decorative chrome.
const CARD_ACCENT_COLORS = {
  loss:       '#D97706', // amber  — caution signal without chart-alert red
  healthy:    '#059669', // emerald
  diagnostic: '#64748B', // slate  — no inherent direction
  action:     '#4F46E5', // indigo — model output / recommendation
};

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
  const tier = tierFor(metricType, direction, isOverTarget);
  const accentColor = CARD_ACCENT_COLORS[tier]; // card chrome (border, icon)
  const statusColor = STATUS_TIERS[tier];        // delta text only
  const TrendIcon = trendDirection === 'up' ? ArrowUp : trendDirection === 'down' ? ArrowDown : null;

  return (
    <div className="kpi-card" style={{ borderTopColor: accentColor }}>
      <div className="kpi-header">
        <h3 className="kpi-title">{title}</h3>
        {icon && <div className="kpi-icon" style={{ color: accentColor }}>{icon}</div>}
      </div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-footer">
        {contextLine && <div className="kpi-context">{contextLine}</div>}
        {deltaLine && (
          <div className="kpi-subtext" style={{ color: statusColor }}>
            {TrendIcon && <TrendIcon size={12} className="kpi-trend-icon" />}
            {deltaLine}
          </div>
        )}
      </div>
    </div>
  );
};

export default KPICard;
