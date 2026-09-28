import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import Modal from './Modal';
import SaveResult from './SaveResult';
import { getCurrentUser } from '../auth';
import { useSaveResult } from '../utils/useSaveResult';
import './UserFormModal.css';

const emptyForm = { fullName: '', email: '', role: 'staff' };

// Shared Add/Edit modal — `user` present means Edit. There's no password
// field: a new account gets an emailed link to choose its own, so no admin
// ever knows anyone's password.
//
// onSubmit(values) saves and resolves with { message } for the green check
// (it throws when the save fails, which shows a red X); onSaved(outcome)
// runs once the check has played, and closes the dialog.
const UserFormModal = ({ isOpen, user, onClose, onSubmit, onSaved }) => {
  const [form, setForm] = useState(emptyForm);
  const [errors, setErrors] = useState({});
  const [apiError, setApiError] = useState('');
  const { saving, result, run, reset } = useSaveResult();

  const isEdit = Boolean(user);
  // The server refuses a change to your own role (so an admin can't lock
  // themselves out by accident); say so up front rather than after Save.
  const isSelf = isEdit && user.email === getCurrentUser()?.email;

  useEffect(() => {
    if (isOpen) {
      setForm(
        user
          ? { fullName: user.full_name, email: user.email, role: user.role }
          : emptyForm
      );
      setErrors({});
      setApiError('');
      reset();
    }
  }, [isOpen, user, reset]);

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
    return newErrors;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const newErrors = validate();
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    const values = { fullName: form.fullName.trim(), email: form.email.trim(), role: form.role };
    // Nothing changed means nothing to save, so no "saved" either.
    if (isEdit && values.fullName === user.full_name && values.email === user.email && values.role === user.role) {
      onClose();
      return;
    }

    setApiError('');
    await run(() => onSubmit(values), {
      onSaved: (outcome) => (onSaved ? onSaved(outcome) : onClose()),
      onFailed: setApiError,
    });
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      label="User details"
      overlayClassName="modal-overlay"
      containerClassName="modal-card"
      closeOnOverlayClick={!saving}
      closeOnEscape={!saving}
    >
      {result ? (
        <SaveResult
          ok={result.ok}
          title={result.ok ? (isEdit ? 'Changes saved' : 'User added') : "Couldn't save"}
          message={result.ok ? result.value?.message : result.message}
        />
      ) : (
        <>
          <div className="modal-header">
            <div>
              <h3 className="modal-title">{isEdit ? 'Edit User' : 'Add New User'}</h3>
              <p className="modal-subtitle">
                {isEdit
                  ? 'Update this account’s details.'
                  : 'They’ll get an email with a link to set their own password.'}
              </p>
            </div>
            <button className="modal-close-btn" onClick={onClose} disabled={saving} aria-label="Close modal">
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

            <div className="form-row">
              <div className="form-group" title={isSelf ? "You can't change your own role" : undefined}>
                <label className="form-label" htmlFor="user-form-role">
                  ROLE <span className="required">*</span>
                </label>
                <select
                  id="user-form-role"
                  name="role"
                  value={form.role}
                  onChange={handleChange}
                  className="form-input form-select"
                  disabled={isSelf}
                  aria-describedby={isSelf ? 'user-form-role-hint' : undefined}
                >
                  <option value="staff">Staff</option>
                  <option value="admin">Admin</option>
                </select>
                {/* The tooltip alone never shows on a phone, or to a keyboard user. */}
                {isSelf && (
                  <span id="user-form-role-hint" className="form-hint">You can&apos;t change your own role.</span>
                )}
              </div>
            </div>

            {apiError && <div className="form-api-error">{apiError}</div>}

            <div className="modal-actions">
              <button type="button" className="btn-cancel" onClick={onClose} disabled={saving}>
                Cancel
              </button>
              <button type="submit" className="btn-submit" disabled={saving}>
                {saving ? 'Saving...' : isEdit ? 'Save Changes' : 'Add User'}
              </button>
            </div>
          </form>
        </>
      )}
    </Modal>
  );
};

export default UserFormModal;
