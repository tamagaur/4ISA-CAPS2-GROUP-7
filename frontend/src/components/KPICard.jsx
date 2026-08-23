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
//   'danger'          — an explicit "too little" signal that must match
//                       the chart layer's shortfall red exactly (e.g. the
//                       dashboard's Stockout risk card, which is the same
//                       condition as the allocation chart's red bars) —
//                       bypasses the loss tier's softer amber on purpose.
//   'loss'           — any amount is bad; colour by direction ('worse'/
//                       'better') only, never by the amount itself.
//   'gap'             — the raw amount is normal; only exceeding a target
//                       is bad, so colour comes from isOverTarget instead
//                       of direction — this is the one exception where
//                       amount and colour are allowed to agree.
//   'recommendation'  — model output, not a health metric. Always the
//                       neutral 'action' tier, never red or green.
function tierFor(metricType, direction, isOverTarget) {
  if (metricType === 'danger') return 'danger';
  if (metricType === 'recommendation') return 'action';
  if (metricType === 'gap') return isOverTarget ? 'loss' : 'healthy';
  if (direction === 'worse') return 'loss';
  if (direction === 'better') return 'healthy';
  return 'diagnostic';
}

// Card accent colours — separate from STATUS_TIERS so most KPI card chrome
// avoids red (red is normally reserved for chart-layer alerts: data viz
// only). 'danger' is the deliberate exception — a card whose condition IS
// exactly a chart's red-bar condition should look like it, not be softened.
// Border and icon use these accents; the small delta-line text keeps
// STATUS_TIERS colours because directional text is a different semantic
// register from the card's decorative chrome.
const CARD_ACCENT_COLORS = {
  danger:     '#E5484D', // same red as the allocation chart's shortfall bars
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
  tooltip,
}) => {
  const tier = tierFor(metricType, direction, isOverTarget);
  const accentColor = CARD_ACCENT_COLORS[tier]; // card chrome (border, icon)
  // STATUS_TIERS has no 'danger' entry of its own — it's the same "this got
  // worse" delta-text meaning as 'loss', just with different card chrome.
  const statusColor = STATUS_TIERS[tier === 'danger' ? 'loss' : tier]; // delta text only
  const TrendIcon = trendDirection === 'up' ? ArrowUp : trendDirection === 'down' ? ArrowDown : null;

  // Native title attribute — a plain hover tooltip for cards that need to
  // hold a technical definition (e.g. MAPE) off the always-visible text
  // but still available to whoever wants it, with no new dependency.
  return (
    <div className="kpi-card" style={{ borderTopColor: accentColor }} title={tooltip}>
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
