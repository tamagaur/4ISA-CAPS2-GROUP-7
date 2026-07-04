import React, { useState } from 'react';
import { X } from 'lucide-react';
import './AddSKUModal.css';

const initialFormState = {
  skuCode: '',
  brand: '',
  productName: '',
  category: '',
  unitPrice: '',
  reorderPoint: '',
  initialStock: '',
  supplier: '',
  notes: '',
};

const AddSKUModal = ({ isOpen, onClose, onAdd }) => {
  const [form, setForm] = useState({ ...initialFormState });
  const [errors, setErrors] = useState({});

  if (!isOpen) return null;

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors(prev => ({ ...prev, [name]: '' }));
    }
  };

  const validate = () => {
    const newErrors = {};
    if (!form.skuCode.trim()) newErrors.skuCode = 'SKU Code is required';
    if (!form.brand.trim()) newErrors.brand = 'Brand is required';
    if (!form.productName.trim()) newErrors.productName = 'Product Name is required';
    if (!form.category) newErrors.category = 'Category is required';
    if (!form.unitPrice || parseFloat(form.unitPrice) < 0) newErrors.unitPrice = 'Valid price is required';
    if (!form.reorderPoint && form.reorderPoint !== '0') newErrors.reorderPoint = 'Reorder Point is required';
    if (!form.supplier.trim()) newErrors.supplier = 'Supplier is required';
    return newErrors;
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const newErrors = validate();
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }
    onAdd(form);
    setForm({ ...initialFormState });
    setErrors({});
    onClose();
  };

  const handleCancel = () => {
    setForm({ ...initialFormState });
    setErrors({});
    onClose();
  };

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      handleCancel();
    }
  };

  return (
    <div className="modal-overlay" onClick={handleOverlayClick}>
      <div className="modal-card">
        {/* Header */}
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

        {/* Form */}
        <form onSubmit={handleSubmit} className="modal-form" noValidate>
          {/* Row 1: SKU Code + Brand */}
          <div className="form-row two-col">
            <div className="form-group">
              <label className="form-label">
                SKU CODE <span className="required">*</span>
              </label>
              <input
                type="text"
                name="skuCode"
                value={form.skuCode}
                onChange={handleChange}
                placeholder="e.g., SKU-10001"
                className={`form-input ${errors.skuCode ? 'input-error' : ''}`}
              />
              {errors.skuCode && <span className="error-text">{errors.skuCode}</span>}
            </div>
            <div className="form-group">
              <label className="form-label">
                BRAND <span className="required">*</span>
              </label>
              <input
                type="text"
                name="brand"
                value={form.brand}
                onChange={handleChange}
                placeholder="e.g., Nestlé"
                className={`form-input ${errors.brand ? 'input-error' : ''}`}
              />
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
                placeholder="e.g., Milo 3-in-1 Chocolate Drink"
                className={`form-input ${errors.productName ? 'input-error' : ''}`}
              />
              {errors.productName && <span className="error-text">{errors.productName}</span>}
            </div>
          </div>

          {/* Row 3: Category + Unit Price */}
          <div className="form-row two-col">
            <div className="form-group">
              <label className="form-label">
                CATEGORY <span className="required">*</span>
              </label>
              <select
                name="category"
                value={form.category}
                onChange={handleChange}
                className={`form-input form-select ${errors.category ? 'input-error' : ''}`}
              >
                <option value="">Select category</option>
                <option value="A">Category A</option>
                <option value="B">Category B</option>
                <option value="C">Category C</option>
              </select>
              {errors.category && <span className="error-text">{errors.category}</span>}
            </div>
            <div className="form-group">
              <label className="form-label">
                UNIT PRICE <span className="required">*</span>
              </label>
              <input
                type="number"
                name="unitPrice"
                value={form.unitPrice}
                onChange={handleChange}
                placeholder="0.00"
                min="0"
                step="0.01"
                className={`form-input ${errors.unitPrice ? 'input-error' : ''}`}
              />
              {errors.unitPrice && <span className="error-text">{errors.unitPrice}</span>}
            </div>
          </div>

          {/* Row 4: Reorder Point + Initial Stock */}
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

          {/* Row 5: Supplier */}
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">
                SUPPLIER <span className="required">*</span>
              </label>
              <input
                type="text"
                name="supplier"
                value={form.supplier}
                onChange={handleChange}
                placeholder="e.g., Nestlé Philippines"
                className={`form-input ${errors.supplier ? 'input-error' : ''}`}
              />
              {errors.supplier && <span className="error-text">{errors.supplier}</span>}
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
                rows={3}
                className="form-input form-textarea"
              />
            </div>
          </div>

          {/* Actions */}
          <div className="modal-actions">
            <button type="button" className="cancel-btn" onClick={handleCancel}>
              Cancel
            </button>
            <button type="submit" className="add-btn">
              Add SKU
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AddSKUModal;
