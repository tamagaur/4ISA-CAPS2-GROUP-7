import React from 'react';
import { X } from 'lucide-react';
import Modal from './Modal';
import { formatMonth } from '../utils/formatDate';
import { COLORS } from '../theme/colors';
import './ReorderModal.css';

// Story #80: "why was this recommended" — LP objective weights are fixed
// per DEC (w1=0.45 cost, w2=0.35 service level, w3=0.20 capacity), so the
// weight split itself is real config (analytics/optimization/lp.py), not
// per-SKU fabrication.
//
// Colors match the Dashboard's own cost/service level/storage priority
// sliders (LP_PRIORITY_ROWS in Charts.jsx) one-for-one — these are the same
// three LP weights shown two different ways (editable sliders there, a
// static "why" breakdown here), so a SKU opened from Reorder Recs shouldn't
// show a different color for "cost" than the Dashboard widget does.
const OBJECTIVE_WEIGHTS = [
  { key: 'cost', label: 'Cost minimization', weight: 45, color: COLORS.dispatched },
  { key: 'service', label: 'Service level ≥ 95%', weight: 35, color: COLORS.salesTrend },
  { key: 'capacity', label: 'Warehouse capacity', weight: 20, color: COLORS.warning },
];

const ReorderModal = ({ isOpen, onClose, data }) => {
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

        {/* Data Grid — only fields not already visible in the table row
            (safety stock, ROP, current stock, order qty and urgency are all
            columns there, so the two views don't repeat each other). */}
        <div className="reorder-modal-grid">
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">PLANNING CYCLE</span>
            <span className="reorder-grid-value">{formatMonth(data.planningCycleDate)}</span>
          </div>
        </div>

        {/* Why this recommendation — Story #80 */}
        <div className="reorder-why-section">
          <h4 className="reorder-section-title">Why this recommendation</h4>
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
