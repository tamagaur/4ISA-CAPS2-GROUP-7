import React, { useState, useEffect } from 'react';
import { X, ArrowLeft, CheckCircle2, XCircle } from 'lucide-react';
import './ReportBadOrderModal.css';

// Helper to format SKU Code (e.g. SKU-07642)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.trim().match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  const digitsMatch = sku.trim().match(/^(\d+)$/);
  if (digitsMatch) {
    return `SKU-${digitsMatch[1].padStart(5, '0')}`;
  }
  return sku.trim().toUpperCase();
};

const skuDatabase = {
  'SKU-07642': { brand: 'Unilever', product: 'Dove Shampoo 340ml' },
  'SKU-01523': { brand: 'Del Monte', product: 'Tomato Sauce 250g' },
  'SKU-09234': { brand: 'Del Monte', product: 'Sweet Corn 425g' },
  'SKU-04721': { brand: 'Unilever', product: 'Surf Powder Detergent 1kg' },
  'SKU-08934': { brand: 'Del Monte', product: 'Pineapple Juice 1L' },
  'SKU-02891': { brand: 'Unilever', product: 'Knorr Cubes 8g' },
};

const availableSKUs = [
  'SKU-07642',
  'SKU-01523',
  'SKU-09234',
  'SKU-04721',
  'SKU-08934',
  'SKU-02891',
];

const ReportBadOrderModal = ({ isOpen, onClose, onSubmitReport }) => {
  const [step, setStep] = useState('FORM'); // 'FORM' | 'CONFIRM' | 'SUCCESS'
  const [skuCode, setSkuCode] = useState('');
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('');
  const [value, setValue] = useState('');
  const [notes, setNotes] = useState('');
  const [formatError, setFormatError] = useState('');

  // Reset modal state when opened
  useEffect(() => {
    if (isOpen) {
      setStep('FORM');
      setSkuCode('');
      setQty('');
      setReason('');
      setValue('');
      setNotes('');
      setFormatError('');
    }
  }, [isOpen]);

  // Listen for Escape key press to dismiss modal
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isOpen) {
        handleClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  if (!isOpen) return null;

  const handleClose = () => {
    setStep('FORM');
    onClose();
  };

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      handleClose();
    }
  };

  // SKU formatting on blur
  const handleSkuBlur = () => {
    if (skuCode) {
      const formatted = formatSKU(skuCode);
      setSkuCode(formatted);

      // Validate format
      const skuRegex = /^SKU-\d{5}$/;
      if (!skuRegex.test(formatted)) {
        setFormatError('Invalid SKU format. Must follow SKU-XXXXX convention (5 digits).');
      } else {
        setFormatError('');
      }
    }
  };

  const handleFormSubmit = (e) => {
    e.preventDefault();
    const formatted = formatSKU(skuCode);
    setSkuCode(formatted);

    const skuRegex = /^SKU-\d{5}$/;
    if (!skuRegex.test(formatted)) {
      setFormatError('Invalid SKU format. Must follow SKU-XXXXX convention (e.g., SKU-07642).');
      return;
    }

    setFormatError('');
    setStep('CONFIRM');
  };

  const isValidReport = skuCode && qty && parseInt(qty) > 0 && reason && value && parseFloat(value) > 0;

  const handleConfirmSave = () => {
    const formattedSKU = formatSKU(skuCode);
    const lookup = skuDatabase[formattedSKU] || { brand: 'Other', product: 'General Stock Item' };

    const reportData = {
      sku: formattedSKU,
      brand: lookup.brand,
      product: lookup.product,
      qty: parseInt(qty) || 0,
      reason: reason,
      value: parseFloat(value) || 0,
      notes: notes.trim(),
    };

    onSubmitReport(reportData);
    setStep('SUCCESS');

    // Auto-dismiss after 1.5 seconds
    setTimeout(() => {
      handleClose();
    }, 1500);
  };

  const formattedSKUDisplay = formatSKU(skuCode);
  const resolvedInfo = skuDatabase[formattedSKUDisplay] || { brand: 'Other', product: 'General Stock Item' };

  return (
    <div className="report-modal-overlay" onClick={handleOverlayClick}>
      <div className="report-modal-container">
        {/* Modal Header */}
        <div className="report-modal-header">
          <h3 className="report-modal-title">
            {step === 'FORM' && 'Report Bad Order'}
            {step === 'CONFIRM' && 'Confirm Incident Report'}
            {step === 'SUCCESS' && 'Report Submitted'}
          </h3>
          <button className="report-close-btn" onClick={handleClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Modal Body */}
        <div className="report-modal-body">
          {/* STEP 1: FORM */}
          {step === 'FORM' && (
            <form onSubmit={handleFormSubmit} className="report-form">
              {/* SKU Field with validation & format hint */}
              <div className="report-form-group">
                <label className="report-label" htmlFor="report-sku">
                  SKU CODE <span className="req-asterisk">*</span>
                </label>
                <div className="sku-input-wrapper">
                  <input
                    id="report-sku"
                    type="text"
                    placeholder="e.g., SKU-01847 or 1847"
                    value={skuCode}
                    onChange={(e) => {
                      setSkuCode(e.target.value);
                      if (formatError) setFormatError('');
                    }}
                    onBlur={handleSkuBlur}
                    className={`report-input ${formatError ? 'input-error' : ''}`}
                    required
                  />
                  <select
                    className="report-sku-quick-select"
                    onChange={(e) => {
                      if (e.target.value) {
                        setSkuCode(e.target.value);
                        setFormatError('');
                      }
                    }}
                    value=""
                  >
                    <option value="" disabled>Select from SKU list...</option>
                    {availableSKUs.map(s => (
                      <option key={s} value={s}>{s} - {skuDatabase[s]?.product}</option>
                    ))}
                  </select>
                </div>
                {formatError ? (
                  <span className="report-error-msg">{formatError}</span>
                ) : (
                  <span className="report-hint-msg">Format: SKU-XXXXX (5 digits, e.g., SKU-07642)</span>
                )}
              </div>

              {/* Quantity */}
              <div className="report-form-group">
                <label className="report-label" htmlFor="report-qty">
                  QUANTITY LOST <span className="req-asterisk">*</span>
                </label>
                <input
                  id="report-qty"
                  type="number"
                  placeholder="e.g., 24"
                  min="1"
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                  className="report-input"
                  required
                />
              </div>

              {/* Reason Dropdown */}
              <div className="report-form-group">
                <label className="report-label" htmlFor="report-reason">
                  INCIDENT REASON <span className="req-asterisk">*</span>
                </label>
                <select
                  id="report-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="report-select"
                  required
                >
                  <option value="" disabled>Select a reason</option>
                  <option value="Transport Damage">Transport Damage</option>
                  <option value="Expiry">Expiry</option>
                  <option value="Storage Issue">Storage Issue</option>
                  <option value="Supplier Defect">Supplier Defect</option>
                </select>
              </div>

              {/* Value (₱) */}
              <div className="report-form-group">
                <label className="report-label" htmlFor="report-value">
                  TOTAL VALUE (₱) <span className="req-asterisk">*</span>
                </label>
                <input
                  id="report-value"
                  type="number"
                  placeholder="e.g., 12600"
                  min="0"
                  step="0.01"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  className="report-input"
                  required
                />
              </div>

              {/* Notes */}
              <div className="report-form-group">
                <label className="report-label" htmlFor="report-notes">
                  ADDITIONAL NOTES
                </label>
                <textarea
                  id="report-notes"
                  placeholder="Additional details regarding the incident..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  className="report-textarea"
                  rows={3}
                />
              </div>

              {/* Form Action Buttons matching reference styling */}
              <div className="report-modal-actions">
                <button type="button" className="report-btn report-btn-cancel" onClick={handleClose}>
                  Cancel
                </button>
                <button type="submit" className="report-btn report-btn-submit">
                  Submit
                </button>
              </div>
            </form>
          )}

          {/* STEP 2: CONFIRMATION SUMMARY GRID & NO-CHANGES / INVALID INDICATOR */}
          {step === 'CONFIRM' && (
            <div className="report-confirm-view">
              {!isValidReport ? (
                /* No Changes / Invalid Incident Details Indicator */
                <div className="report-no-changes-container">
                  <XCircle size={64} className="no-changes-x-circle" />
                  <h4 className="no-changes-title">Incomplete Incident Details</h4>
                  <p className="no-changes-desc">
                    Please ensure SKU Code, Quantity, Reason, and Value fields are correctly filled out.
                  </p>
                  <div className="report-confirm-actions">
                    <button className="report-btn report-btn-back" onClick={() => setStep('FORM')}>
                      <ArrowLeft size={16} />
                      Back
                    </button>
                  </div>
                </div>
              ) : (
                /* Valid Report Summary Grid */
                <div className="report-summary-container">
                  <div className="confirm-header-msg">
                    <p>Please review the bad order incident details before saving to the master ledger.</p>
                  </div>

                  <div className="report-summary-grid">
                    <div className="summary-item">
                      <span className="summary-item-label">SKU CODE</span>
                      <span className="summary-item-value sku-code-highlight">{formattedSKUDisplay}</span>
                    </div>

                    <div className="summary-item">
                      <span className="summary-item-label">BRAND</span>
                      <span className="summary-item-value">{resolvedInfo.brand}</span>
                    </div>

                    <div className="summary-item full-width">
                      <span className="summary-item-label">PRODUCT NAME</span>
                      <span className="summary-item-value">{resolvedInfo.product}</span>
                    </div>

                    <div className="summary-item">
                      <span className="summary-item-label">QUANTITY LOST</span>
                      <span className="summary-item-value qty-value-highlight">{parseInt(qty).toLocaleString()} units</span>
                    </div>

                    <div className="summary-item">
                      <span className="summary-item-label">REASON</span>
                      <span className="summary-item-value reason-badge">{reason}</span>
                    </div>

                    <div className="summary-item">
                      <span className="summary-item-label">REPORTED VALUE</span>
                      <span className="summary-item-value value-highlight">
                        ₱{parseFloat(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    </div>

                    {notes.trim() && (
                      <div className="summary-item full-width">
                        <span className="summary-item-label">NOTES</span>
                        <span className="summary-item-value notes-value">{notes.trim()}</span>
                      </div>
                    )}
                  </div>

                  {/* Confirmation Buttons: Back & Confirm */}
                  <div className="report-confirm-actions">
                    <button className="report-btn report-btn-back" onClick={() => setStep('FORM')}>
                      <ArrowLeft size={16} />
                      Back
                    </button>
                    <button className="report-btn report-btn-submit" onClick={handleConfirmSave}>
                      Confirm & Submit
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* STEP 3: SUCCESS ANIMATION (GREEN CHECKMARK POP INSIDE MODAL) */}
          {step === 'SUCCESS' && (
            <div className="report-success-anim-container">
              <div className="success-icon-wrapper">
                <CheckCircle2 size={64} className="success-check-icon" />
              </div>
              <h4 className="success-anim-title">Incident Reported Successfully!</h4>
              <p className="success-anim-desc">
                Bad order report for <strong>{formattedSKUDisplay}</strong> has been logged into the inventory system.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ReportBadOrderModal;
