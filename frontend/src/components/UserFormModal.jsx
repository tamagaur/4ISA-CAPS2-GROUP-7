import React, { useState, useEffect } from 'react';
import { X, ArrowRight } from 'lucide-react';
import Modal from './Modal';
import SaveResult from './SaveResult';
import { getCurrentUser } from '../auth';
import { ROLES } from '../permissions/keys';
import { useSaveResult } from '../utils/useSaveResult';
import './UserFormModal.css';

const emptyForm = { fullName: '', email: '', role: 'staff' };

// Shared Add/Edit modal — `user` present means Edit. There's no password
// field: a new account gets an emailed link to choose its own, so no admin
// ever knows anyone's password.
//
// Edit: name, email and role, saved here. onSubmit(values) resolves with
// { message } for the green check (it throws when the save fails, which
// shows a red X); onSaved(outcome) runs once the check has played, and
// closes the dialog.
//
// Add is step 1 of 2: name and email, then Next hands them to onNext and
// the Permissions modal takes over for the role and pages (step 2), where
// Save creates the account. `draft` refills the fields when that modal's
// Back returns here.
const UserFormModal = ({ isOpen, user, draft = null, existingEmails = [], onClose, onSubmit, onSaved, onNext }) => {
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
      if (user) setForm({ fullName: user.full_name, email: user.email, role: user.role });
      else setForm(draft ? { ...emptyForm, fullName: draft.fullName, email: draft.email } : emptyForm);
      // Back from step 2 after the server said the email is taken.
      setErrors(!user && draft?.emailError ? { email: draft.emailError } : {});
      setApiError('');
      reset();
    }
  }, [isOpen, user, draft, reset]);

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
    } else if (existingEmails.some((email) => email.toLowerCase() === form.email.trim().toLowerCase())) {
      // Any capitalisation is the same account (the server's rule too).
      newErrors.email = 'A user with this email already exists.';
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

    // Add: on to the Permissions modal.
    if (!isEdit) {
      onNext({ fullName: form.fullName.trim(), email: form.email.trim() });
      return;
    }

    const values = { fullName: form.fullName.trim(), email: form.email.trim(), role: form.role };
    // Nothing changed means nothing to save, so no "saved" either.
    if (values.fullName === user.full_name && values.email === user.email && values.role === user.role) {
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
          title={result.ok ? 'Changes saved' : "Couldn't save"}
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
                  : 'Step 1 of 2 · Their name and email. They’ll get an email with a link to set their own password.'}
              </p>
            </div>
            <button className="modal-close-btn" onClick={onClose} disabled={saving} aria-label="Close modal">
              <X size={20} />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="modal-form" noValidate>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label" htmlFor="user-form-name">
                  FULL NAME <span className="required">*</span>
                </label>
                <input
                  id="user-form-name"
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
                <label className="form-label" htmlFor="user-form-email">
                  EMAIL <span className="required">*</span>
                </label>
                <input
                  id="user-form-email"
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

            {/* Edit keeps the role here; Add chooses it in the Permissions modal. */}
            {isEdit && (
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
                    {ROLES.map((role) => (
                      <option key={role.value} value={role.value}>{role.label}</option>
                    ))}
                  </select>
                  {/* The tooltip alone never shows on a phone, or to a keyboard user. */}
                  {isSelf && (
                    <span id="user-form-role-hint" className="form-hint">You can&apos;t change your own role.</span>
                  )}
                </div>
              </div>
            )}

            {apiError && <div className="form-api-error">{apiError}</div>}

            <div className="modal-actions">
              <button type="button" className="btn-cancel" onClick={onClose} disabled={saving}>
                Cancel
              </button>
              <button type="submit" className="btn-submit" disabled={saving}>
                {isEdit ? (saving ? 'Saving...' : 'Save Changes') : (
                  <>
                    Next
                    <ArrowRight size={16} aria-hidden="true" />
                  </>
                )}
              </button>
            </div>
          </form>
        </>
      )}
    </Modal>
  );
};

export default UserFormModal;
