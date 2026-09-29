import React from 'react';
import { X } from 'lucide-react';
import Modal from './Modal';
import SkuDemandPatternPanel from './SkuDemandPatternPanel';
import { formatMonth } from '../utils/formatDate';
import { formatUnits } from '../utils/formatNumber';
import { CHART_COLORS } from '../theme/colors';
import './ReorderModal.css';

// Story #80: "why was this recommended" — the LP objective weights are fixed
// (w1 cost, w2 service level, w3 storage cost), so the weight split itself is
// real config, not per-SKU fabrication. The figures come from GET
// /recommendations' lp_model (backend/lp_cycle.py, pinned to
// analytics/optimization/lp.py by tests), not constants retyped here: until
// 2026-09-29 this listed "Service level ≥ 95%" and "Warehouse capacity" as
// weights, where the solver uses a 90% service level (Z = 1.28) and w3 is
// storage cost.
//
// Colour matches the Dashboard's own cost/service level/storage priority
// bars (LP_PRIORITY_ROWS in Charts.jsx) one-for-one via
// CHART_COLORS.lpWeight — ONE model-output indigo for all three: they are
// co-equal weights of a single solver objective, not three categories,
// and the row labels carry identity (see theme/colors.js).
const objectiveWeights = (lpModel) => {
  const w = lpModel?.weights;
  if (!w) return [];
  const pct = (v) => Math.round(v * 100);
  return [
    { key: 'cost', label: 'Cost', weight: pct(w.cost), color: CHART_COLORS.lpWeight },
    {
      key: 'service',
      label: lpModel.service_level_pct != null ? `Service level (${lpModel.service_level_pct}% target)` : 'Service level',
      weight: pct(w.service_level),
      color: CHART_COLORS.lpWeight,
    },
    { key: 'storage', label: 'Storage cost', weight: pct(w.storage), color: CHART_COLORS.lpWeight },
  ];
};

// Stock is valued at purchase cost and sales at selling price, so cover
// reads a little short (backend/routers/recommendations.py days_of_cover).
const COVER_BASIS_NOTE =
  'Stock at cost (₱) ÷ average daily sales value (₱/day over the last 3 sales months; a month with no sales counts as 0). Cost against selling price, so cover reads slightly short.';

const ReorderModal = ({ isOpen, onClose, data, principal, lpModel }) => {
  if (!isOpen || !data) return null;
  const weightRows = objectiveWeights(lpModel);

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
              Order <strong>{formatUnits(data.orderQty)}</strong> units — LP optimization breakdown for this SKU's recommended order.
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
              {weightRows.map((obj) => (
                <div
                  key={obj.key}
                  className="reorder-weight-segment"
                  style={{ flex: `${obj.weight} 0 0%`, backgroundColor: obj.color }}
                  title={`${obj.label}: ${obj.weight}%`}
                />
              ))}
            </div>
            <div className="reorder-weight-legend">
              {weightRows.map((obj) => (
                <div className="reorder-weight-legend-item" key={obj.key}>
                  <span className="reorder-weight-swatch" style={{ backgroundColor: obj.color }} />
                  <span className="reorder-weight-legend-label">{obj.label}</span>
                  <span className="reorder-weight-legend-pct">{obj.weight}%</span>
                </div>
              ))}
            </div>
          </div>
          <p className="reorder-why-note">
            Constraints applied: each SKU is ordered at least up to its reorder point
            {lpModel?.z_score != null && <> (forecast + safety stock at Z = {lpModel.z_score})</>}, and the
            cycle&apos;s total must fit the warehouse capacity and each principal&apos;s supplier limit.
          </p>
        </div>
    </Modal>
  );
};

export default ReorderModal;
