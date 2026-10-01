import React from 'react';
import { X } from 'lucide-react';
import Modal from './Modal';
import { formatUnits } from '../utils/formatNumber';
import './ViewSKUModal.css';

// Helper to format SKU Code (e.g. SKU-10234)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  return sku;
};

// Helper to format date into "Apr 15, 2026"
const formatDate = (dateStr) => {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

// Helper for category badge circle
const getCatClass = (cat) => {
  switch (cat) {
    case 'A': return 'cat-circle cat-a';
    case 'B': return 'cat-circle cat-b';
    case 'C': return 'cat-circle cat-c';
    default: return 'cat-circle';
  }
};

const ViewSKUModal = ({ isOpen, sku, onClose, onEdit }) => {
  // Escape-to-close now comes from the shared <Modal> shell below, along
  // with focus trapping and role="dialog".
  if (!isOpen || !sku) return null;


  // Helper to format currency
  const formatCurrency = (val) => {
    if (val === undefined || val === null || val === '') return null;
    const num = parseFloat(val);
    if (isNaN(num)) return val;
    return `₱${num.toFixed(2)}`;
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      label="SKU details"
      overlayClassName="view-sku-modal-overlay"
      containerClassName="view-sku-modal-card"
    >
        {/* Header */}
        <div className="view-sku-modal-header">
          <h3 className="view-sku-product-title">{sku.product}</h3>
          <button className="view-sku-close-btn" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Modal Body */}
        <div className="view-sku-body">
          <div className="view-sku-grid">
            {/* SKU Code */}
            {sku.code && (
              <div className="view-sku-field">
                <span className="view-sku-label">SKU CODE</span>
                <span className="view-sku-value sku-code-text">{formatSKU(sku.code)}</span>
              </div>
            )}

            {/* Brand */}
            {sku.brand && (
              <div className="view-sku-field">
                <span className="view-sku-label">BRAND</span>
                <span className="view-sku-value">{sku.brand}</span>
              </div>
            )}

            {/* Category */}
            {sku.cat && (
              <div className="view-sku-field">
                <span className="view-sku-label">CATEGORY</span>
                <div className="view-sku-badge-wrapper">
                  <span className={getCatClass(sku.cat)}>{sku.cat}</span>
                </div>
              </div>
            )}

            {/* Status */}
            {sku.status && (
              <div className="view-sku-field">
                <span className="view-sku-label">STATUS</span>
                <div className="view-sku-badge-wrapper">
                  <span className={`status-pill ${sku.status === 'ACTIVE' ? 'status-active' : 'status-inactive'}`}>
                    {sku.status}
                  </span>
                </div>
              </div>
            )}

            {/* Current Stock — pieces, the unit the target stock below is in
                (GET /sku), with the warehouse's own case count beside it. It
                read "423 units" for 121,964 pieces until 2026-09-29. A product
                with no usable pack size has the case count only. */}
            {(sku.currentStock != null || sku.currentStockCases != null) && (
              <div className="view-sku-field">
                <span className="view-sku-label">CURRENT STOCK</span>
                <span className="view-sku-value mono-val">
                  {sku.currentStock != null
                    ? <>
                        {sku.currentStock.toLocaleString()} pieces
                        {sku.currentStockCases != null && <> ({sku.currentStockCases.toLocaleString()} cases)</>}
                      </>
                    : <>{sku.currentStockCases.toLocaleString()} cases</>}
                </span>
              </div>
            )}

            {/* Unit Price */}
            {sku.unitPrice !== undefined && sku.unitPrice !== null && (
              <div className="view-sku-field">
                <span className="view-sku-label">UNIT PRICE</span>
                <span className="view-sku-value mono-val">{formatCurrency(sku.unitPrice)}</span>
              </div>
            )}

            {/* Avg Sales per Month */}
            {sku.avgSalesPerMonth !== undefined && sku.avgSalesPerMonth !== null && (
              <div className="view-sku-field">
                <span className="view-sku-label">AVG SALES PER MONTH</span>
                <span className="view-sku-value mono-val">{sku.avgSalesPerMonth.toLocaleString()} units</span>
              </div>
            )}

            {/* Target stock — GET /sku's reorder_point is the LP's rop_i, which
                since the 2026-09-30 run is the order-up-to level, not a
                reorder trigger. The SKU table already calls it Target stock;
                this label said REORDER POINT until 2026-10-01. */}
            {sku.reorderPt !== undefined && sku.reorderPt !== null && (
              <div className="view-sku-field">
                <span className="view-sku-label">TARGET STOCK</span>
                {/* Whole pieces rounded up, as the SKU table shows it. */}
                <span className="view-sku-value mono-val">{formatUnits(sku.reorderPt)} pieces</span>
              </div>
            )}

            {/* Supplier */}
            {sku.supplier && (
              <div className="view-sku-field">
                <span className="view-sku-label">SUPPLIER</span>
                <span className="view-sku-value">{sku.supplier}</span>
              </div>
            )}

            {/* Lead Time */}
            {sku.leadTime && sku.leadTime !== 'N/A' && (
              <div className="view-sku-field">
                <span className="view-sku-label">LEAD TIME</span>
                <span className="view-sku-value">{sku.leadTime}</span>
              </div>
            )}

            {/* Last Order Date */}
            {sku.lastOrderDate && (
              <div className="view-sku-field">
                <span className="view-sku-label">LAST ORDER DATE</span>
                <span className="view-sku-value">{formatDate(sku.lastOrderDate)}</span>
              </div>
            )}
          </div>

          {/* Notes (Full Width) */}
          {sku.notes && sku.notes.trim() !== '' && (
            <div className="view-sku-notes-section">
              <span className="view-sku-label">NOTES</span>
              <p className="view-sku-notes-text">{sku.notes}</p>
            </div>
          )}
        </div>

        {/* Modal Footer Actions */}
        <div className="view-sku-modal-footer">
          <button className="view-sku-btn-close" onClick={onClose}>
            Close
          </button>
          {/* onEdit is only passed for admin accounts — staff get a
              read-only view (POST/PATCH /sku are admin-only). */}
          {onEdit && (
            <button className="view-sku-btn-edit" onClick={() => { onClose(); onEdit(sku); }}>
              Edit SKU
            </button>
          )}
        </div>
    </Modal>
  );
};

export default ViewSKUModal;
