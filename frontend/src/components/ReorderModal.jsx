import React from 'react';
import { X } from 'lucide-react';
import { COLORS } from '../theme/colors';
import './ReorderModal.css';

// Story #80: "why was this recommended" — LP objective weights are fixed
// per DEC (w1=0.45 cost, w2=0.35 service level, w3=0.20 capacity), so the
// weight split itself is real config (analytics/optimization/lp.py), not
// per-SKU fabrication.
const OBJECTIVE_WEIGHTS = [
  { key: 'cost', label: 'Cost minimization', weight: 45, color: COLORS.salesTrend },
  { key: 'service', label: 'Service level ≥ 95%', weight: 35, color: COLORS.success },
  { key: 'capacity', label: 'Warehouse capacity', weight: 20, color: COLORS.dispatched },
];

const ReorderModal = ({ isOpen, onClose, data }) => {
  if (!isOpen || !data) return null;

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div className="reorder-modal-overlay" onClick={handleOverlayClick}>
      <div className="reorder-modal-card">
        {/* Header */}
        <div className="reorder-modal-header">
          <div>
            <h3 className="reorder-modal-title">Reorder: {data.product}</h3>
            <p className="reorder-modal-subtitle">
              LP optimization breakdown for this SKU's recommended order.
            </p>
          </div>
          <button className="reorder-modal-close" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Data Grid */}
        <div className="reorder-modal-grid">
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">REORDER POINT (ROP)</span>
            <span className="reorder-grid-value">{data.rop}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">CURRENT STOCK</span>
            <span className="reorder-grid-value">{data.stock}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">OPTIMAL ORDER QTY</span>
            <span className="reorder-grid-value">{data.orderQty}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">URGENCY</span>
            <span className="reorder-grid-value">{data.urgency}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">SAFETY STOCK</span>
            <span className="reorder-grid-value">{data.safetyStock ?? '—'}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">PLANNING CYCLE</span>
            <span className="reorder-grid-value">{data.planningCycleDate ?? '—'}</span>
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
      </div>
    </div>
  );
};

export default ReorderModal;
