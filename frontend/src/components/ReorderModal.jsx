import React from 'react';
import { X } from 'lucide-react';
import Modal from './Modal';
import SkuDemandPatternPanel from './SkuDemandPatternPanel';
import { formatMonth } from '../utils/formatDate';
import { CHART_COLORS } from '../theme/colors';
import './ReorderModal.css';

// Story #80: "why was this recommended" — LP objective weights are fixed
// per DEC (w1=0.45 cost, w2=0.35 service level, w3=0.20 capacity), so the
// weight split itself is real config (analytics/optimization/lp.py), not
// per-SKU fabrication.
//
// Colors match the Dashboard's own cost/service level/storage priority
// bars (LP_PRIORITY_ROWS in Charts.jsx) one-for-one via
// CHART_COLORS.lpWeights — three categorical hues, none of them a status
// colour (Storage used to be amber, which reads as "watch" everywhere
// else in the app).
const OBJECTIVE_WEIGHTS = [
  { key: 'cost', label: 'Cost minimization', weight: 45, color: CHART_COLORS.lpWeights.cost },
  { key: 'service', label: 'Service level ≥ 95%', weight: 35, color: CHART_COLORS.lpWeights.service_level },
  { key: 'capacity', label: 'Warehouse capacity', weight: 20, color: CHART_COLORS.lpWeights.storage },
];

const COVER_BASIS_NOTE =
  'Stock at cost (₱) ÷ average daily sales value (₱/day, last 3 sales months). Peso basis because stock is in cases and demand in pieces.';

const ReorderModal = ({ isOpen, onClose, data, principal }) => {
  if (!isOpen || !data) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      label="Reorder details"
      overlayClassName="reorder-modal-overlay"
      containerClassName="reorder-modal-card"
    >
        {/* Header */}
        <div className="reorder-modal-header">
          <div>
            <h3 className="reorder-modal-title">Reorder: {data.product}</h3>
            <p className="reorder-modal-subtitle">
              Order <strong>{Number(data.orderQty ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</strong> units — LP optimization breakdown for this SKU's recommended order.
            </p>
          </div>
          <button className="reorder-modal-close" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Data Grid — fields not already visible in the table row, plus
            the two ranking inputs so the "why is this #3" question is
            answerable here. */}
        <div className="reorder-modal-grid">
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">PLANNING CYCLE</span>
            <span className="reorder-grid-value">{formatMonth(data.planningCycleDate)}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">IMPACT RANK</span>
            <span className="reorder-grid-value">
              {data.rank != null ? `#${data.rank} in cycle` : 'Unranked'}
            </span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">REVENUE SHARE</span>
            <span className="reorder-grid-value">
              {data.revenueShare != null ? `${(data.revenueShare * 100).toFixed(2)}%` : '—'}
            </span>
          </div>
          <div className="reorder-grid-item" title={data.daysOfCover != null ? COVER_BASIS_NOTE : (data.coverReason || COVER_BASIS_NOTE)}>
            <span className="reorder-grid-label">COVER (DAYS, ₱ BASIS)</span>
            <span className="reorder-grid-value">
              {data.daysOfCover != null ? data.daysOfCover.toFixed(1) : '—'}
            </span>
          </div>
        </div>

        {/* Demand pattern (sku_traits / sku_segment). Ahead of the LP
            weights on purpose: the weights are the same for every SKU,
            this is the part that is about THIS one. */}
        <div className="reorder-pattern-section">
          <SkuDemandPatternPanel skuId={data.sku} principal={principal} compact />
        </div>

        {/* How the LP arrived at this quantity — Story #80 */}
        <div className="reorder-why-section">
          <h4 className="reorder-section-title">How this recommendation was made</h4>
          <p className="reorder-why-intro">
            The LP model weighs three objectives when solving for this SKU's order quantity:
          </p>
          {/* Single 100%-stacked bar — these three weights are shares of one
              whole (they sum to 100%), so one composite bar is the correct
              part-to-whole form, not three independent progress tracks. */}
          <div className="reorder-weight-stack">
            <div className="reorder-weight-stack-track">
              {OBJECTIVE_WEIGHTS.map((obj) => (
                <div
                  key={obj.key}
                  className="reorder-weight-segment"
                  style={{ flex: `${obj.weight} 0 0%`, backgroundColor: obj.color }}
                  title={`${obj.label}: ${obj.weight}%`}
                />
              ))}
            </div>
            <div className="reorder-weight-legend">
              {OBJECTIVE_WEIGHTS.map((obj) => (
                <div className="reorder-weight-legend-item" key={obj.key}>
                  <span className="reorder-weight-swatch" style={{ backgroundColor: obj.color }} />
                  <span className="reorder-weight-legend-label">{obj.label}</span>
                  <span className="reorder-weight-legend-pct">{obj.weight}%</span>
                </div>
              ))}
            </div>
          </div>
          <p className="reorder-why-note">
            Constraints applied: service level ≥ 95%, supplier MOQ, and warehouse capacity headroom.
          </p>
        </div>
    </Modal>
  );
};

export default ReorderModal;
