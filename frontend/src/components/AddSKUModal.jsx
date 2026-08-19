import React, { useState } from 'react';
import { X, ArrowLeft, CheckCircle2 } from 'lucide-react';
import './AddSKUModal.css';

const initialFormState = {
  skuCode: '',
  brand: '',
  productName: '',
  sizeVal: '',
  sizeUnit: 'L',
  unitPrice: '',
  reorderPoint: '',
  initialStock: '',
  supplier: '',
  notes: '',
};

const DEFAULT_SUPPLIERS = [
  'Del Monte Philippines',
  'Unilever Philippines',
];

const DEFAULT_BRANDS = [
  'Del Monte',
  'Unilever',
];

const AddSKUModal = ({ isOpen, onClose, onAdd, brands = DEFAULT_BRANDS, suppliers = DEFAULT_SUPPLIERS }) => {
  const [step, setStep] = useState('FORM'); // 'FORM' | 'CONFIRM' | 'SUCCESS'
  const [form, setForm] = useState({ ...initialFormState });
  const [errors, setErrors] = useState({});

  if (!isOpen) return null;

  const availableBrands = Array.from(new Set([...DEFAULT_BRANDS, ...(brands || [])]));
  const availableSuppliers = Array.from(new Set([...DEFAULT_SUPPLIERS, ...(suppliers || [])]));

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors(prev => ({ ...prev, [name]: '' }));
    }
  };

  // Enforce uniform SKU Code formatting (SKU-XXXXX)
  const handleSKUCodeChange = (e) => {
    let val = e.target.value.toUpperCase();

    // Auto-prefix SKU- if user enters digits
    if (/^\d{1,5}$/.test(val)) {
      val = `SKU-${val}`;
    }

    setForm(prev => ({ ...prev, skuCode: val }));
    if (errors.skuCode) {
      setErrors(prev => ({ ...prev, skuCode: '' }));
    }
  };

  // Uniform Title Case formatting for Product Name
  const handleProductNameBlur = () => {
    if (form.productName.trim()) {
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

  const validate = () => {
    const newErrors = {};
    const skuRegex = /^SKU-\d{5}$/;

    if (!form.skuCode.trim()) {
      newErrors.skuCode = 'SKU Code is required';
    } else if (!skuRegex.test(form.skuCode.trim())) {
      newErrors.skuCode = 'Must follow format SKU-XXXXX (e.g. SKU-10001)';
    }

    if (!form.brand.trim()) newErrors.brand = 'Brand is required';
    if (!form.productName.trim()) newErrors.productName = 'Product Name is required';
    if (!form.unitPrice || parseFloat(form.unitPrice) <= 0) newErrors.unitPrice = 'Valid unit price is required';
    if (!form.reorderPoint && form.reorderPoint !== '0') newErrors.reorderPoint = 'Reorder Point is required';
    if (!form.supplier.trim()) newErrors.supplier = 'Supplier is required';
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
  const handleConfirmSave = () => {
    const fullProduct = form.sizeVal.trim()
      ? `${form.productName.trim()} ${form.sizeVal.trim()}${form.sizeUnit}`
      : form.productName.trim();

    onAdd({
      ...form,
      category: 'PENDING',
      productName: fullProduct
    });

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

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      handleCancel();
    }
  };

  const constructedFullProduct = form.sizeVal.trim()
    ? `${form.productName.trim()} ${form.sizeVal.trim()}${form.sizeUnit}`
    : form.productName.trim();

  return (
    <div className="modal-overlay" onClick={handleOverlayClick}>
      <div className="modal-card">
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
                    placeholder="e.g., SKU-10001"
                    maxLength={9}
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

              {/* Row 5: Reorder Point + Initial Stock */}
              <div className="form-row two-col">
                <div className="form-group">
                  <label className="form-label">
                    REORDER POINT <span className="required">*</span>
                  </label>
                  <input
                    type="number"
                    name="reorderPoint"
                    value={form.reorderPoint}
                    onChange={handleChange}
                    placeholder="0"
                    min="0"
                    className={`form-input ${errors.reorderPoint ? 'input-error' : ''}`}
                  />
                  {errors.reorderPoint && <span className="error-text">{errors.reorderPoint}</span>}
                </div>
                <div className="form-group">
                  <label className="form-label">INITIAL STOCK</label>
                  <input
                    type="number"
                    name="initialStock"
                    value={form.initialStock}
                    onChange={handleChange}
                    placeholder="0"
                    min="0"
                    className="form-input"
                  />
                </div>
              </div>

              {/* Row 6: Supplier (Dropdown Selection) */}
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">
                    SUPPLIER <span className="required">*</span>
                  </label>
                  <select
                    name="supplier"
                    value={form.supplier}
                    onChange={handleChange}
                    className={`form-input form-select ${errors.supplier ? 'input-error' : ''}`}
                  >
                    <option value="">Select supplier</option>
                    {availableSuppliers.map(sup => (
                      <option key={sup} value={sup}>{sup}</option>
                    ))}
                  </select>
                  {errors.supplier && <span className="error-text">{errors.supplier}</span>}
                </div>
              </div>

              {/* Row 7: Notes */}
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
              <div className="summary-field">
                <span className="summary-field-label">REORDER POINT</span>
                <span className="summary-field-val">{form.reorderPoint || 0} units</span>
              </div>
              <div className="summary-field">
                <span className="summary-field-label">INITIAL STOCK</span>
                <span className="summary-field-val">{form.initialStock || 0} units</span>
              </div>
              <div className="summary-field full">
                <span className="summary-field-label">SUPPLIER</span>
                <span className="summary-field-val">{form.supplier}</span>
              </div>
              {form.notes && (
                <div className="summary-field full">
                  <span className="summary-field-label">NOTES</span>
                  <span className="summary-field-val notes-val">{form.notes}</span>
                </div>
              )}
            </div>

            <div className="modal-actions">
              <button type="button" className="btn-cancel back-btn" onClick={handleBackToForm}>
                <ArrowLeft size={14} />
                Back
              </button>
              <button type="button" className="btn-submit" onClick={handleConfirmSave}>
                Confirm SKU
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
      </div>
    </div>
  );
};

export default AddSKUModal;
