import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import Modal from './Modal';
import './UserFormModal.css';

const emptyForm = { fullName: '', email: '', role: 'staff', password: '' };

// Shared Add/Edit modal — `user` present means Edit (password becomes
// optional: blank = keep current hash, matching backend/schemas/users.py
// UserUpdate where password is optional).
const UserFormModal = ({ isOpen, user, onClose, onSubmit }) => {
  const [form, setForm] = useState(emptyForm);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState('');

  const isEdit = Boolean(user);

  useEffect(() => {
    if (isOpen) {
      setForm(
        user
          ? { fullName: user.full_name, email: user.email, role: user.role, password: '' }
          : emptyForm
      );
      setErrors({});
      setApiError('');
      setSubmitting(false);
    }
  }, [isOpen, user]);

  if (!isOpen) return null;

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    if (errors[name]) setErrors((prev) => ({ ...prev, [name]: '' }));
  };

  const validate = () => {
    const newErrors = {};
    if (!form.fullName.trim()) newErrors.fullName = 'Full name is required';
    if (!form.email.trim()) {
      newErrors.email = 'Email is required';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
      newErrors.email = 'Enter a valid email address';
    }
    if (!isEdit && form.password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters';
    } else if (isEdit && form.password && form.password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters';
    }
    return newErrors;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const newErrors = validate();
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setSubmitting(true);
    setApiError('');
    try {
      await onSubmit({
        fullName: form.fullName.trim(),
        email: form.email.trim(),
        role: form.role,
        password: form.password || undefined,
      });
      onClose();
    } catch (err) {
      setApiError(err.message || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };


  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      label="User details"
      overlayClassName="modal-overlay"
      containerClassName="modal-card"
    >
        <div className="modal-header">
          <div>
            <h3 className="modal-title">{isEdit ? 'Edit User' : 'Add New User'}</h3>
            <p className="modal-subtitle">
              {isEdit
                ? 'Update this account’s details. Leave password blank to keep it unchanged.'
                : 'Create a new account. All fields are required.'}
            </p>
          </div>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close modal">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form" noValidate>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">
                FULL NAME <span className="required">*</span>
              </label>
              <input
                type="text"
                name="fullName"
                value={form.fullName}
                onChange={handleChange}
                placeholder="e.g., Juan Dela Cruz"
                className={`form-input ${errors.fullName ? 'input-error' : ''}`}
              />
              {errors.fullName && <span className="error-text">{errors.fullName}</span>}
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label">
                EMAIL <span className="required">*</span>
              </label>
              <input
                type="email"
                name="email"
                value={form.email}
                onChange={handleChange}
                placeholder="name@company.com"
                className={`form-input ${errors.email ? 'input-error' : ''}`}
              />
              {errors.email && <span className="error-text">{errors.email}</span>}
            </div>
          </div>

          <div className="form-row two-col">
            <div className="form-group">
              <label className="form-label">
                ROLE <span className="required">*</span>
              </label>
              <select
                name="role"
                value={form.role}
                onChange={handleChange}
                className="form-input form-select"
              >
                <option value="staff">Staff</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">
                PASSWORD {!isEdit && <span className="required">*</span>}
              </label>
              <input
                type="password"
                name="password"
                value={form.password}
                onChange={handleChange}
                placeholder={isEdit ? 'Leave blank to keep current' : 'Min. 8 characters'}
                className={`form-input ${errors.password ? 'input-error' : ''}`}
              />
              {errors.password && <span className="error-text">{errors.password}</span>}
            </div>
          </div>

          {apiError && <div className="form-api-error">{apiError}</div>}

          <div className="modal-actions">
            <button type="button" className="btn-cancel" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-submit" disabled={submitting}>
              {submitting ? 'Saving...' : isEdit ? 'Save Changes' : 'Add User'}
            </button>
          </div>
        </form>
    </Modal>
  );
};

export default UserFormModal;
