import React, { useState } from 'react';
import { X, ArrowLeft } from 'lucide-react';
import Modal from './Modal';
import SaveResult from './SaveResult';
import { useSaveResult } from '../utils/useSaveResult';
import './AddSKUModal.css';

const initialFormState = {
  skuCode: '',
  brand: '',
  productName: '',
  sizeVal: '',
  sizeUnit: 'L',
};

// Real brands come from the caller (SKUManagement passes every brand in
// Product_Dimension). 'Unilever' used to sit here, but that's the principal,
// not a brand — no SKU in the database has brand = 'Unilever'.
const DEFAULT_BRANDS = [];

// Every real Unilever sku_code in Product_Dimension is exactly 8 numeric
// characters (2,098/2,098 verified), and backend/routers/sku.py enforces
// only uniqueness, not shape — so the format rule lives here.
const SKU_CODE_LENGTH = 8;
const SKU_CODE_PATTERN = /^\d{8}$/;

const AddSKUModal = ({ isOpen, onClose, onAdd, brands = DEFAULT_BRANDS }) => {
  const [step, setStep] = useState('FORM'); // 'FORM' | 'CONFIRM'; the result after saving is SaveResult's
  const [form, setForm] = useState({ ...initialFormState });
  const [errors, setErrors] = useState({});
  const [saveError, setSaveError] = useState('');
  // Also the double-click guard: a second POST /sku before the first resolves
  // would come back as a confusing 409 "already exists" for the SKU the first
  // call just created.
  const { saving, result, run } = useSaveResult();

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

  // Step 2: Confirm & Save New SKU — a green check then close, or a red X
  // then back to this step with the reason.
  const handleConfirmSave = () => {
    const fullProduct = (form.sizeVal || '').trim()
      ? `${(form.productName || '').trim()} ${(form.sizeVal || '').trim()}${form.sizeUnit || ''}`
      : (form.productName || '').trim();

    setSaveError('');
    run(() => onAdd({ ...form, productName: fullProduct }), {
      onSaved: () => {
        setForm({ ...initialFormState });
        setErrors({});
        setStep('FORM');
        onClose();
      },
      onFailed: setSaveError,
      fallbackError: 'Failed to add SKU',
    });
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
      closeOnOverlayClick={!saving}
      closeOnEscape={!saving}
    >
        {result ? (
          <SaveResult
            ok={result.ok}
            title={result.ok ? 'SKU added' : "Couldn't add the SKU"}
            message={result.ok
              ? <>New SKU <strong>{form.skuCode}</strong> has been saved to the master ledger.</>
              : result.message}
          />
        ) : step === 'FORM' ? (
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

              {/* Unit price, lead time and notes used to be fields here (unit
                  price marked required), but POST /sku only writes code, name,
                  pack size and brand, so whatever was typed was discarded. The
                  Product_Dimension columns exist (migration 0002). */}
              <p className="add-sku-unsaved-note">
                Unit price, lead time and notes can&apos;t be recorded here yet: the system doesn&apos;t save these fields.
              </p>

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
        ) : (
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

            {/* Name first, then its code: products read by name everywhere
                (Technical Adviser, 2026-10-03). */}
            <div className="add-sku-summary-grid">
              <div className="summary-field full">
                <span className="summary-field-label">PRODUCT NAME</span>
                <span className="summary-field-val">{constructedFullProduct}</span>
              </div>
              <div className="summary-field">
                <span className="summary-field-label">SKU CODE</span>
                <span className="summary-field-val highlight-val">{form.skuCode}</span>
              </div>
              <div className="summary-field">
                <span className="summary-field-label">BRAND</span>
                <span className="summary-field-val">{form.brand}</span>
              </div>
              <div className="summary-field">
                <span className="summary-field-label">ABC CLASS</span>
                <span className="summary-field-val pending-category">Pending Auto-Classification</span>
              </div>

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
        )}
    </Modal>
  );
};

export default AddSKUModal;
