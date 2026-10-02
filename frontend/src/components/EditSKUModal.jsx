import React, { useState, useEffect } from 'react';
import { X, ArrowLeft, XCircle } from 'lucide-react';
import Modal from './Modal';
import SaveResult from './SaveResult';
import { useSaveResult } from '../utils/useSaveResult';
import './EditSKUModal.css';

// Helper to format SKU Code (e.g. SKU-10234)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  return sku;
};

// Helper to parse product string into name, size value, and unit of measurement
const parseProductComponents = (fullProduct) => {
  if (!fullProduct) return { baseName: '', sizeVal: '', sizeUnit: 'L' };
  // A size only when it stands on its own: not glued to a letter, digit or
  // point before it. "24X13.5ML" has no separate size (it used to split as
  // "24X13." + "5ml" and save back as "24X13. 5ml"); "16(5+1)120G" does.
  const regex = /(?<![\w.])(\d+(?:\.\d+)?)\s*(g|ml|l|kg|L|KG|ML|G)\b/;
  const match = fullProduct.match(regex);
  if (match) {
    const val = match[1];
    let unit = match[2];
    const lowerUnit = unit.toLowerCase();
    if (lowerUnit === 'ml') unit = 'ml';
    else if (lowerUnit === 'kg') unit = 'kg';
    else if (lowerUnit === 'g') unit = 'g';
    else if (lowerUnit === 'l') unit = 'L';

    let baseName = fullProduct.replace(regex, '').replace(/\s+/g, ' ').trim();
    baseName = baseName.replace(/\(\s*\)/g, '').trim();
    return { baseName, sizeVal: val, sizeUnit: unit };
  }
  return { baseName: fullProduct, sizeVal: '', sizeUnit: 'L' };
};

const EditSKUModal = ({ isOpen, sku, onClose, onSave }) => {
  const [step, setStep] = useState('FORM'); // 'FORM' | 'CONFIRM'; the result after saving is SaveResult's

  const [form, setForm] = useState({
    productNameOnly: '',
    sizeVal: '',
    sizeUnit: 'L',
    brand: '',
    unitPrice: '',
    leadTimeDays: '',
    notes: '',
    status: 'ACTIVE'
  });
  const [saveError, setSaveError] = useState('');
  // Also the double-click guard against two PATCH /sku/:id requests.
  const { saving, result, run } = useSaveResult();

  // Populate form state when sku prop changes
  useEffect(() => {
    if (sku) {
      const { baseName, sizeVal, sizeUnit } = parseProductComponents(sku.product);
      setForm({
        productNameOnly: baseName,
        sizeVal: sizeVal,
        sizeUnit: sizeUnit || 'L',
        brand: sku.brand || '',
        unitPrice: sku.unitPrice !== undefined && sku.unitPrice !== null ? String(sku.unitPrice) : '',
        leadTimeDays: sku.leadTimeDays !== undefined && sku.leadTimeDays !== null ? String(sku.leadTimeDays) : '',
        notes: sku.notes || '',
        status: sku.status || 'ACTIVE'
      });
      setStep('FORM');
      setSaveError('');
    }
  }, [sku, isOpen]);

  // Escape-to-close, focus trapping and role="dialog" now come from the
  // shared <Modal> shell below (this file's own keydown listener was one of
  // only three such ad hoc implementations in the app).
  if (!isOpen || !sku) return null;

  const handleClose = () => {
    setStep('FORM');
    onClose();
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
  };

  // Helper to construct full product title with separate size and unit.
  // Untouched name and size fields give back the stored name exactly: the
  // split-and-rebuild is only for edits, so it can never reformat a name
  // nobody changed (it rewrote 361 Unilever names that way, 2026-10-02).
  const constructFullProduct = () => {
    const original = parseProductComponents(sku.product);
    if (form.productNameOnly === original.baseName && form.sizeVal === original.sizeVal
        && (!original.sizeVal || form.sizeUnit === original.sizeUnit)) {
      return sku.product || '';
    }
    const pName = form.productNameOnly.trim();
    if (form.sizeVal.trim()) {
      return `${pName} ${form.sizeVal.trim()}${form.sizeUnit}`;
    }
    return pName;
  };

  // Move to Confirmation view
  const handleSaveClick = (e) => {
    e.preventDefault();
    setStep('CONFIRM');
  };

  // Back to Form view
  const handleBackToForm = () => {
    setStep('FORM');
  };

  // Compute detected changes list
  const getChangedFields = () => {
    const changes = [];
    const fullProduct = constructFullProduct();
    if (fullProduct !== (sku.product || '').trim()) {
      changes.push({ label: 'Product Name / Size', from: sku.product, to: fullProduct });
    }
    // Brand can be set or changed but not cleared (PATCH /sku ignores null).
    if (form.brand.trim() && form.brand.trim() !== (sku.brand || '').trim()) {
      changes.push({ label: 'Brand', from: sku.brand || '—', to: form.brand.trim() });
    }
    return changes;
  };

  const changedFields = getChangedFields();

  // Confirm changes and save — a green check then close, or a red X then
  // back to this step with the reason.
  const handleConfirmChanges = () => {
    // Only product name and brand are stored by PATCH /sku; everything else
    // keeps the SKU's current values.
    const updatedSKU = {
      ...sku,
      product: constructFullProduct(),
      brand: form.brand.trim() || sku.brand,
    };

    setSaveError('');
    run(() => onSave?.(updatedSKU), {
      onSaved: handleClose,
      onFailed: setSaveError,
      fallbackError: 'Failed to save changes',
    });
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      label={`Edit SKU ${sku.code}`}
      overlayClassName="edit-sku-modal-overlay"
      containerClassName="edit-sku-modal-card"
      closeOnOverlayClick={!saving}
      closeOnEscape={!saving}
    >
        {result ? (
          <SaveResult
            ok={result.ok}
            title={result.ok ? 'Changes saved' : "Couldn't save the changes"}
            message={result.ok
              ? <>Product details for <strong>{formatSKU(sku.code)}</strong> were updated.</>
              : result.message}
          />
        ) : step === 'FORM' ? (
          /* STEP 1: EDIT SKU FORM */
          <>
            <div className="edit-sku-modal-header">
              <div>
                <h3 className="edit-sku-modal-title">Edit SKU — {formatSKU(sku.code)}</h3>
                <p className="edit-sku-modal-subtitle">
                  Update the product name or brand. Changes will be reflected immediately.
                </p>
              </div>
              <button className="edit-sku-close-btn" onClick={handleClose} aria-label="Close modal">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSaveClick} className="edit-sku-form">
              <div className="edit-form-body">
                {/* Product Base Name */}
                <div className="edit-form-group full-width">
                  <label className="edit-form-label">
                    PRODUCT NAME <span className="req-star">*</span>
                  </label>
                  <input
                    type="text"
                    name="productNameOnly"
                    value={form.productNameOnly}
                    onChange={handleChange}
                    placeholder="e.g. Pineapple Juice"
                    required
                    className="edit-form-input"
                  />
                </div>

                {/* Dedicated Size Value & Unit of Measurement Dropdown */}
                <div className="edit-form-row two-col">
                  <div className="edit-form-group">
                    <label className="edit-form-label">
                      SIZE / WEIGHT VALUE
                    </label>
                    <input
                      type="text"
                      name="sizeVal"
                      value={form.sizeVal}
                      onChange={handleChange}
                      placeholder="e.g. 1.5, 500, 340"
                      className="edit-form-input"
                    />
                  </div>

                  <div className="edit-form-group">
                    <label className="edit-form-label">
                      UNIT OF MEASUREMENT
                    </label>
                    <select
                      name="sizeUnit"
                      value={form.sizeUnit}
                      onChange={handleChange}
                      className="edit-form-select"
                    >
                      <option value="L">L (Liters)</option>
                      <option value="ml">ml (Milliliters)</option>
                      <option value="g">g (Grams)</option>
                      <option value="kg">kg (Kilograms)</option>
                    </select>
                  </div>
                </div>

                {/* Row 3: Brand */}
                <div className="edit-form-row">
                  <div className="edit-form-group">
                    <label className="edit-form-label">
                      BRAND
                    </label>
                    <input
                      type="text"
                      name="brand"
                      value={form.brand}
                      onChange={handleChange}
                      placeholder="e.g. SURF"
                      className="edit-form-input"
                    />
                  </div>
                </div>

                {/* Product_Dimension has these columns (migration 0002), but
                    PATCH /sku only writes product_name, pack_size and brand, so
                    they're locked until the endpoint saves them. They used to be
                    editable (unit price was even required) and reported as saved. */}
                <p className="edit-form-unsaved-note">
                  Unit price, lead time, status and notes can&apos;t be changed here yet: the system doesn&apos;t save
                  these fields. They&apos;re shown for reference only.
                </p>

                {/* Row 4: Unit Price + Lead Time */}
                <div className="edit-form-row two-col">
                  <div className="edit-form-group">
                    <label className="edit-form-label">
                      UNIT PRICE
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      name="unitPrice"
                      value={form.unitPrice}
                      placeholder="—"
                      disabled
                      className="edit-form-input"
                    />
                  </div>

                  <div className="edit-form-group">
                    <label className="edit-form-label">
                      LEAD TIME (DAYS)
                    </label>
                    <input
                      type="number"
                      name="leadTimeDays"
                      value={form.leadTimeDays}
                      placeholder="—"
                      disabled
                      className="edit-form-input"
                    />
                  </div>
                </div>

                {/* Row 5: Status */}
                <div className="edit-form-row two-col">
                  <div className="edit-form-group">
                    <label className="edit-form-label">
                      STATUS
                    </label>
                    <select
                      name="status"
                      value={form.status}
                      disabled
                      className="edit-form-select"
                    >
                      <option value="ACTIVE">Active</option>
                      <option value="DISABLED">Disabled</option>
                    </select>
                  </div>
                </div>

                {/* Row 6: Notes */}
                <div className="edit-form-group full-width">
                  <label className="edit-form-label">NOTES</label>
                  <textarea
                    name="notes"
                    value={form.notes}
                    placeholder="—"
                    disabled
                    rows="3"
                    className="edit-form-input"
                  ></textarea>
                </div>
              </div>

              {saveError && <p className="error-text" style={{ textAlign: 'center' }}>{saveError}</p>}

              <div className="edit-sku-modal-footer">
                <button type="button" className="edit-sku-btn-cancel" onClick={handleClose}>
                  Cancel
                </button>
                <button type="submit" className="edit-sku-btn-save">
                  Save Changes
                </button>
              </div>
            </form>
          </>
        ) : step === 'CONFIRM' ? (
          /* STEP 2: CONFIRM CHANGES VIEW */
          <>
            <div className="edit-sku-modal-header centered-header">
              <h3 className="edit-sku-modal-title">Confirm Changes — {formatSKU(sku.code)}</h3>
            </div>

            <div className="confirm-changes-body">
              {changedFields.length === 0 ? (
                <div className="no-changes-container">
                  <div className="no-changes-x-circle">
                    <XCircle size={36} strokeWidth={2.2} />
                  </div>
                  <div className="no-changes-msg">No changes detected</div>
                  <p className="no-changes-subtext">The SKU details match the current record.</p>
                </div>
              ) : (
                <div className="changed-fields-list">
                  <div className="changed-summary-title">Modified details summary:</div>
                  {changedFields.map((field, idx) => (
                    <div key={idx} className="changed-field-row">
                      <span className="changed-field-name">{field.label}:</span>
                      <span className="changed-from">{field.from}</span>
                      <span className="changed-arrow">→</span>
                      <span className="changed-to">{field.to}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {saveError && <p className="error-text" style={{ textAlign: 'center' }}>{saveError}</p>}

            <div className="edit-sku-modal-footer">
              <button type="button" className="edit-sku-btn-back" onClick={handleBackToForm}>
                <ArrowLeft size={14} />
                Back
              </button>
              <button type="button" className="edit-sku-btn-confirm" onClick={handleConfirmChanges} disabled={saving}>
                {saving ? 'Saving…' : 'Confirm Changes'}
              </button>
            </div>
          </>
        ) : null}
    </Modal>
  );
};

export default EditSKUModal;
