import React from 'react';
import { ArrowUp, ArrowDown } from 'lucide-react';
import { STATUS_TIERS, SEMANTIC } from '../theme/colors';
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
