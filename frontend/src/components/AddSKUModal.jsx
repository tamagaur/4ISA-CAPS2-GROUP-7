import React, { useState } from 'react';
import { X, ArrowLeft, CheckCircle2 } from 'lucide-react';
import Modal from './Modal';
import './AddSKUModal.css';

const initialFormState = {
  skuCode: '',
  brand: '',
  productName: '',
  sizeVal: '',
  sizeUnit: 'L',
  unitPrice: '',
  leadTimeDays: '',
  notes: '',
};

const DEFAULT_BRANDS = [
  'Unilever',
];

// Every real Unilever sku_code in Product_Dimension is exactly 8 numeric
// characters (2,098/2,098 verified), and backend/routers/sku.py enforces
// only uniqueness, not shape — so the format rule lives here.
const SKU_CODE_LENGTH = 8;
const SKU_CODE_PATTERN = /^\d{8}$/;

const AddSKUModal = ({ isOpen, onClose, onAdd, brands = DEFAULT_BRANDS }) => {
  const [step, setStep] = useState('FORM'); // 'FORM' | 'CONFIRM' | 'SUCCESS'
  const [form, setForm] = useState({ ...initialFormState });
  const [errors, setErrors] = useState({});
  const [saveError, setSaveError] = useState('');
  const [saving, setSaving] = useState(false);

  if (!isOpen) return null;

  const availableBrands = Array.from(new Set([...DEFAULT_BRANDS, ...(brands || [])]));

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors(prev => ({ ...prev, [name]: '' }));
    }
  };

  // Real Unilever sku_code values are all exactly 8 digits (verified against
  // Product_Dimension: 2,098 rows, every one 8 numeric characters), so this
  // strips anything that isn't a digit and stops at 8 rather than
  // auto-prefixing "SKU-" — that older behavior mangled a genuine code as it
  // was typed ("20071069" became "SKU-20071..."), and the backend has no
  // SKU-prefixed rows for it to match.
  const handleSKUCodeChange = (e) => {
    const val = e.target.value.replace(/\D/g, '').slice(0, SKU_CODE_LENGTH);

    setForm(prev => ({ ...prev, skuCode: val }));
    if (errors.skuCode) {
      setErrors(prev => ({ ...prev, skuCode: '' }));
    }
  };

  // Uniform Title Case formatting for Product Name
  const handleProductNameBlur = () => {
    if ((form.productName || '').trim()) {
      const formatted = form.productName
        .trim()
        .replace(/\s+/g, ' ')
        .split(' ')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
      setForm(prev => ({ ...prev, productName: formatted }));
    }
  };

  // Format unit price to 2 decimals on blur
  const handleUnitPriceBlur = () => {
    if (form.unitPrice && !isNaN(form.unitPrice)) {
      setForm(prev => ({ ...prev, unitPrice: parseFloat(form.unitPrice).toFixed(2) }));
    }
  };

  // Was broken: referenced an undeclared `newErrors` and `skuRegex`, so every
  // submit threw ReferenceError and the form silently did nothing. Both are
  // declared properly now, and the format check matches the real data (8
  // digits) instead of the "SKU-XXXXX" shape, which no row in
  // Product_Dimension actually uses.
  const validate = () => {
    const newErrors = {};
    const skuCode = (form.skuCode || '').trim();

    if (!skuCode) {
      newErrors.skuCode = 'SKU Code is required';
    } else if (!SKU_CODE_PATTERN.test(skuCode)) {
      newErrors.skuCode = `Must be exactly ${SKU_CODE_LENGTH} digits (e.g. 20071069)`;
    }

    if (!(form.brand || '').trim()) newErrors.brand = 'Brand is required';
    if (!(form.productName || '').trim()) newErrors.productName = 'Product Name is required';

    // Both optional, but if given they have to be sane — the backend stores
    // these as numerics, so a negative price or lead time would be accepted
    // silently and then read as real data downstream.
    if ((form.unitPrice || '').trim() && !(Number(form.unitPrice) > 0)) {
      newErrors.unitPrice = 'Unit price must be greater than 0';
    }
    if ((form.leadTimeDays || '').trim() && !(Number(form.leadTimeDays) >= 0)) {
      newErrors.leadTimeDays = 'Lead time cannot be negative';
    }

    return newErrors;
  };

  // Step 1: Submit Form to Confirmation View
  const handleProceedToConfirm = (e) => {
    e.preventDefault();
    const newErrors = validate();
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }
    setStep('CONFIRM');
  };

  // Step 2: Confirm & Save New SKU
  const handleConfirmSave = async () => {
    // Guard against a double-click firing two POST /sku requests before the
    // first resolves — the second would come back as a confusing 409
    // "already exists" for the SKU the first call just created.
    if (saving) return;

    const fullProduct = (form.sizeVal || '').trim()
      ? `${(form.productName || '').trim()} ${(form.sizeVal || '').trim()}${form.sizeUnit || ''}`
      : (form.productName || '').trim();

    setSaveError('');
    setSaving(true);
    try {
      await onAdd({
        ...form,
        productName: fullProduct
      });
    } catch (err) {
      setSaveError(err.message || 'Failed to add SKU');
      setSaving(false);
      return;
    }
    setSaving(false);

    setStep('SUCCESS');

    setTimeout(() => {
      setForm({ ...initialFormState });
      setErrors({});
      setStep('FORM');
      onClose();
    }, 1500);
  };

  const handleBackToForm = () => {
    setStep('FORM');
  };

  const handleCancel = () => {
    setForm({ ...initialFormState });
    setErrors({});
    setStep('FORM');
    onClose();
  };

  const constructedFullProduct = (form.sizeVal || '').trim()
    ? `${(form.productName || '').trim()} ${(form.sizeVal || '').trim()}${form.sizeUnit || ''}`
    : (form.productName || '').trim();

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleCancel}
      label="Add new SKU"
      overlayClassName="modal-overlay"
      containerClassName="modal-card"
    >
        {step === 'FORM' ? (
          /* STEP 1: ADD SKU FORM */
          <>
            <div className="modal-header">
              <div>
                <h3 className="modal-title">Add New SKU</h3>
                <p className="modal-subtitle">
                  Enter the details for the new product. All fields marked with * are required.
                </p>
              </div>
              <button className="modal-close-btn" onClick={handleCancel} aria-label="Close modal">
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleProceedToConfirm} className="modal-form" noValidate>
              {/* Row 1: SKU Code + Brand Dropdown */}
              <div className="form-row two-col">
                <div className="form-group">
                  <label className="form-label">
                    SKU CODE <span className="required">*</span>
                  </label>
                  <input
                    type="text"
                    name="skuCode"
                    value={form.skuCode}
                    onChange={handleSKUCodeChange}
                    placeholder="e.g., 20071069"
                    inputMode="numeric"
                    maxLength={SKU_CODE_LENGTH}
                    className={`form-input ${errors.skuCode ? 'input-error' : ''}`}
                  />
                  {errors.skuCode && <span className="error-text">{errors.skuCode}</span>}
                </div>
                <div className="form-group">
                  <label className="form-label">
                    BRAND <span className="required">*</span>
                  </label>
                  <select
                    name="brand"
                    value={form.brand}
                    onChange={handleChange}
                    className={`form-input form-select ${errors.brand ? 'input-error' : ''}`}
                  >
                    <option value="">Select brand</option>
                    {availableBrands.map(b => (
                      <option key={b} value={b}>{b}</option>
                    ))}
                  </select>
                  {errors.brand && <span className="error-text">{errors.brand}</span>}
                </div>
              </div>

              {/* Row 2: Product Name */}
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">
                    PRODUCT NAME <span className="required">*</span>
                  </label>
                  <input
                    type="text"
                    name="productName"
                    value={form.productName}
                    onChange={handleChange}
                    onBlur={handleProductNameBlur}
                    placeholder="e.g., Milo 3-in-1 Chocolate Drink"
                    className={`form-input ${errors.productName ? 'input-error' : ''}`}
                  />
                  {errors.productName && <span className="error-text">{errors.productName}</span>}
                </div>
              </div>

              {/* Row 3: Size / Weight Value + Unit of Measurement */}
              <div className="form-row two-col">
                <div className="form-group">
                  <label className="form-label">
                    SIZE / WEIGHT VALUE
                  </label>
                  <input
                    type="text"
                    name="sizeVal"
                    value={form.sizeVal}
                    onChange={handleChange}
                    placeholder="e.g. 1.5, 500, 340"
                    className="form-input"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">
                    UNIT OF MEASUREMENT
                  </label>
                  <select
                    name="sizeUnit"
                    value={form.sizeUnit}
                    onChange={handleChange}
                    className="form-input form-select"
                  >
                    <option value="L">L (Liters)</option>
                    <option value="ml">ml (Milliliters)</option>
                    <option value="g">g (Grams)</option>
                    <option value="kg">kg (Kilograms)</option>
                  </select>
                </div>
              </div>

              {/* Row 4: Unit Price */}
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">
                    UNIT PRICE <span className="required">*</span>
                  </label>
                  <input
                    type="number"
                    name="unitPrice"
                    value={form.unitPrice}
                    onChange={handleChange}
                    onBlur={handleUnitPriceBlur}
                    placeholder="0.00"
                    min="0"
                    step="0.01"
                    className={`form-input ${errors.unitPrice ? 'input-error' : ''}`}
                  />
                  {errors.unitPrice && <span className="error-text">{errors.unitPrice}</span>}
                </div>
              </div>

              {/* Row 5: Lead Time */}
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">LEAD TIME (DAYS)</label>
                  <input
                    type="number"
                    name="leadTimeDays"
                    value={form.leadTimeDays}
                    onChange={handleChange}
                    placeholder="e.g. 7"
                    min="0"
                    className={`form-input ${errors.leadTimeDays ? 'input-error' : ''}`}
                  />
                  {errors.leadTimeDays && <span className="error-text">{errors.leadTimeDays}</span>}
                </div>
              </div>

              {/* Row 6: Notes */}
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">NOTES</label>
                  <textarea
                    name="notes"
                    value={form.notes}
                    onChange={handleChange}
                    placeholder="Optional notes about this SKU..."
                    rows="3"
                    className="form-input form-textarea"
                  ></textarea>
                </div>
              </div>

              {/* Actions */}
              <div className="modal-actions">
                <button type="button" className="btn-cancel" onClick={handleCancel}>
                  Cancel
                </button>
                <button type="submit" className="btn-submit">
                  Add SKU
                </button>
              </div>
            </form>
          </>
        ) : step === 'CONFIRM' ? (
          /* STEP 2: CONFIRMATION WINDOW */
          <>
            <div className="modal-header centered-header">
              <div>
                <h3 className="modal-title">Confirm New SKU</h3>
                <p className="modal-subtitle">
                  Please review the details before saving to the master ledger.
                </p>
              </div>
            </div>

            <div className="add-sku-summary-grid">
              <div className="summary-field">
                <span className="summary-field-label">SKU CODE</span>
                <span className="summary-field-val highlight-val">{form.skuCode}</span>
              </div>
              <div className="summary-field">
                <span className="summary-field-label">BRAND</span>
                <span className="summary-field-val">{form.brand}</span>
              </div>
              <div className="summary-field full">
                <span className="summary-field-label">PRODUCT NAME</span>
                <span className="summary-field-val">{constructedFullProduct}</span>
              </div>
              <div className="summary-field">
                <span className="summary-field-label">CATEGORY</span>
                <span className="summary-field-val pending-category">Pending Auto-Classification</span>
              </div>
              <div className="summary-field">
                <span className="summary-field-label">UNIT PRICE</span>
                <span className="summary-field-val">₱{parseFloat(form.unitPrice || 0).toFixed(2)}</span>
              </div>
              {form.leadTimeDays && (
                <div className="summary-field">
                  <span className="summary-field-label">LEAD TIME</span>
                  <span className="summary-field-val">{form.leadTimeDays} days</span>
                </div>
              )}
              {form.notes && (
                <div className="summary-field full">
                  <span className="summary-field-label">NOTES</span>
                  <span className="summary-field-val notes-val">{form.notes}</span>
                </div>
              )}
            </div>

            {saveError && <p className="error-text" style={{ textAlign: 'center', marginTop: '0.5rem' }}>{saveError}</p>}

            <div className="modal-actions">
              <button type="button" className="btn-cancel back-btn" onClick={handleBackToForm} disabled={saving}>
                <ArrowLeft size={14} />
                Back
              </button>
              <button type="button" className="btn-submit" onClick={handleConfirmSave} disabled={saving}>
                {saving ? 'Saving…' : 'Confirm SKU'}
              </button>
            </div>
          </>
        ) : (
          /* STEP 3: ANIMATED CHECKMARK SUCCESS WINDOW */
          <div className="add-success-anim-container">
            <div className="add-success-checkmark-circle">
              <CheckCircle2 size={40} strokeWidth={2.2} />
            </div>
            <h3 className="add-success-title">SKU Added Successfully!</h3>
            <p className="add-success-subtitle">
              New SKU <strong>{form.skuCode}</strong> has been saved to the master ledger.
            </p>
          </div>
        )}
    </Modal>
  );
};

export default AddSKUModal;
