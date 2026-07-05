import React from 'react';
import { X } from 'lucide-react';
import './ReorderModal.css';

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
            <span className="reorder-grid-label">ESTIMATED COST</span>
            <span className="reorder-grid-value">{data.estCost}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">URGENCY</span>
            <span className="reorder-grid-value">{data.urgency}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">SAFETY STOCK</span>
            <span className="reorder-grid-value">30</span>
          </div>
        </div>

        {/* Footer Note */}
        <div className="reorder-modal-footer-note">
          This quantity was computed by the LP model (PuLP) to minimize total inventory cost = holding cost + ordering cost, subject to constraints: service level ≥ 95%, warehouse capacity, and supplier MOQ.
        </div>
      </div>
    </div>
  );
};

export default ReorderModal;
