import React from 'react';
import { X } from 'lucide-react';
import Modal from './Modal';
import { formatUnits } from '../utils/formatNumber';
import { formatDate, formatMonth } from '../utils/formatDate';
import ProductName from './ProductName';
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

// Helper for category badge circle
const getCatClass = (cat) => {
  switch (cat) {
    case 'A': return 'cat-circle cat-a';
    case 'B': return 'cat-circle cat-b';
    case 'C': return 'cat-circle cat-c';
    default: return 'cat-circle';
  }
};

const ViewSKUModal = ({ isOpen, sku, onClose, onEdit, onOpenForecast, onOpenReorder }) => {
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
        {/* Header — the name first, its SKU code under it, as every
            product list shows it. A Del Monte sell-out category has no code
            (its id is the category path), so its name stands alone. */}
        <div className="view-sku-modal-header">
          <h3 className="view-sku-product-title">
            <ProductName name={sku.product} code={sku.grain === 'category' ? null : formatSKU(sku.code)} />
          </h3>
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
                <span className="view-sku-label">{sku.grain === 'category' ? 'CATEGORY PATH' : 'SKU CODE'}</span>
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

            {/* ABC class, with the run it comes from: a last-known class
                can be months old. Labelled CATEGORY until 2026-10-03, the
                word Del Monte's product categories also use. */}
            {sku.cat && (
              <div className="view-sku-field">
                <span className="view-sku-label">ABC CLASS</span>
                <div className="view-sku-badge-wrapper">
                  <span className={getCatClass(sku.cat)}>{sku.cat}</span>
                  {sku.catPeriod && <span className="view-sku-asof">{formatMonth(sku.catPeriod)} run</span>}
                </div>
                {/* An old Del Monte sub-category (SKUManagement's preRegroup,
                    2026-10-22): its class is history, not counted. */}
                {sku.preRegroup && (
                  <span className="view-sku-asof">before the Jan 2025 regrouping, so not counted in the class totals</span>
                )}
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
                    : <>{Number(sku.currentStockCases).toLocaleString(undefined, { maximumFractionDigits: 2 })} cases</>}
                </span>
                {/* Cases only: no pack size to convert with (2026-10-22). */}
                {sku.currentStock == null && (
                  <span className="view-sku-asof">no pieces-per-case recorded, so pieces can&apos;t be shown</span>
                )}
                {/* The count's own day (GET /sku's stock_count_date): the
                    file filed as "Mar 2026" was counted on 6 Apr 2026. */}
                {sku.stockCountDate
                  ? <span className="view-sku-asof">as of the count on {formatDate(sku.stockCountDate)}</span>
                  : sku.stockCountPeriod && <span className="view-sku-asof">from the {formatMonth(sku.stockCountPeriod)} count (exact day not recorded)</span>}
              </div>
            )}

            {/* Unit Price */}
            {sku.unitPrice !== undefined && sku.unitPrice !== null && (
              <div className="view-sku-field">
                <span className="view-sku-label">UNIT PRICE</span>
                <span className="view-sku-value mono-val">{formatCurrency(sku.unitPrice)}</span>
              </div>
            )}

            {/* An "avg sales per month … units" field sat here until
                2026-10-22. Nothing ever filled it: GET /sku sends no average
                (backend/routers/sku.py's _SELECT_ONE) and SKU Management maps
                none, so it never rendered, and it named neither the unit
                (pieces) nor the months averaged (Technical Adviser, 2 Oct
                2026: every number with its period and unit). Removed rather
                than given a window the backend does not state. */}

            {/* Target stock — GET /sku's reorder_point is the LP's rop_i, which
                since the 2026-09-30 run is the order-up-to level, not a
                reorder trigger. The SKU table already calls it Target stock;
                this label said REORDER POINT until 2026-10-01. */}
            {sku.reorderPt !== undefined && sku.reorderPt !== null && (
              <div className="view-sku-field">
                <span className="view-sku-label">TARGET STOCK</span>
                {/* Whole pieces rounded up, as the SKU table shows it. */}
                <span className="view-sku-value mono-val">{formatUnits(sku.reorderPt)} pieces</span>
                {sku.planCycle && <span className="view-sku-asof">{formatMonth(sku.planCycle)} plan</span>}
              </div>
            )}

            {/* Supplier */}
            {sku.supplier && (
              <div className="view-sku-field">
                <span className="view-sku-label">SUPPLIER</span>
                <span className="view-sku-value">{sku.supplier}</span>
              </div>
            )}

            {/* Cost per piece — Product_Dimension.unit_cost (migration 0045): what SSM
                pays, latest month's case cost / pack size. Hidden when it cannot be
                derived (no cost row or no pack size; all of Del Monte today). */}
            {sku.unitCost !== undefined && sku.unitCost !== null && (
              <div className="view-sku-field">
                <span className="view-sku-label">COST PER PIECE</span>
                <span className="view-sku-value mono-val">₱{Number(sku.unitCost).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
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
          {/* Where this product goes next: its sales history and forecast,
              and its order recommendation when the plan has one. Each is
              passed only when the page it opens is allowed and applies. */}
          {onOpenForecast && (
            <button className="view-sku-btn-close" onClick={() => { onClose(); onOpenForecast(); }}>
              Sales and forecast
            </button>
          )}
          {onOpenReorder && (
            <button className="view-sku-btn-close" onClick={() => { onClose(); onOpenReorder(); }}>
              Order recommendation
            </button>
          )}
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
