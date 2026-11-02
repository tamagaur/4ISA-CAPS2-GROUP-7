import React, { useEffect, useState } from 'react';
import { Eye, EyeOff, KeyRound, X } from 'lucide-react';
import Modal from './Modal';
import { useToast } from './ToastProvider';
import { changePassword } from '../api/profile';
import { requestPasswordReset } from '../auth';
import './TwoStep.css';

// Change password, opened from My profile's Account security (Audrey,
// 2026-10-20). Asks for the current password first (POST
// /auth/change-password checks it), so a signed-in computer left open
// can't be used to take the account over. Forgotten it? The link under the
// box emails a reset link to the account's own address, as Forgot password
// on the sign-in page does. This browser stays signed in; others are
// signed out.
const MIN_CHARS = 8;
const MAX_BYTES = 72;
const SAME_PASSWORD = "That's your current password. Choose a different one.";

function newPasswordProblem(current, next, confirm) {
  if (Array.from(next).length < MIN_CHARS) return `Use at least ${MIN_CHARS} characters for the new password.`;
  if (new TextEncoder().encode(next).length > MAX_BYTES) {
    return 'That password is too long. Keep it to 72 characters or fewer (accented letters and emoji count as more than one).';
  }
  if (next === current) return SAME_PASSWORD;
  if (next !== confirm) return 'The two new passwords don’t match.';
  return '';
}

const ChangePasswordModal = ({ isOpen, onClose, email }) => {
  const toast = useToast();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  // Forgot your current password: the server's answer (sent, or email
  // isn't set up) or its error.
  const [resetNote, setResetNote] = useState('');
  const [resetError, setResetError] = useState('');
  const [sendingReset, setSendingReset] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setCurrent('');
    setNext('');
    setConfirm('');
    setShow(false);
    setError('');
    setResetNote('');
    setResetError('');
  }, [isOpen]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!current) {
      setError('Enter your current password.');
      return;
    }
    const problem = newPasswordProblem(current, next, confirm);
    if (problem) {
      setError(problem);
      return;
    }
    setError('');
    setSaving(true);
    try {
      await changePassword(current, next);
      toast.success('Password changed');
      onClose();
    } catch (err) {
      setError(err.message || 'Could not change your password.');
    } finally {
      setSaving(false);
    }
  };

  const sendResetLink = async () => {
    setResetNote('');
    setResetError('');
    setSendingReset(true);
    try {
      setResetNote(await requestPasswordReset(email));
    } catch (err) {
      setResetError(err.message || 'Could not send the reset link.');
    } finally {
      setSendingReset(false);
    }
  };

  const type = show ? 'text' : 'password';

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      labelledBy="change-password-title"
      overlayClassName="twostep-modal-overlay"
      containerClassName="twostep-modal-card"
      closeOnOverlayClick={!saving}
    >
      <div className="twostep-modal-header">
        <div className="twostep-modal-icon"><KeyRound size={20} /></div>
        <h3 id="change-password-title" className="twostep-modal-title">Change password</h3>
        <button type="button" className="twostep-icon-btn" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
      </div>
      <div className="twostep-modal-body">
        <form className="change-password-form" onSubmit={handleSubmit} noValidate>
          {/* Lets a password manager file the new password under this account. */}
          <input type="email" name="username" autoComplete="username" value={email || ''} readOnly hidden />

          <div className="change-password-field">
            <label htmlFor="cp-current">Current password</label>
            <div className="change-password-input">
              <input
                id="cp-current"
                className="profile-input"
                type={type}
                autoComplete="current-password"
                value={current}
                onChange={(e) => { setCurrent(e.target.value); setError(''); }}
              />
              <button
                type="button"
                className="twostep-icon-btn change-password-toggle"
                onClick={() => setShow((v) => !v)}
                aria-label={show ? 'Hide passwords' : 'Show passwords'}
              >
                {show ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <button
              type="button"
              className="twostep-link change-password-forgot"
              onClick={sendResetLink}
              disabled={sendingReset}
            >
              {sendingReset ? 'Sending a reset link…' : 'Forgot your current password?'}
            </button>
            {resetNote && <p className="twostep-hint" role="status">{resetNote}</p>}
            {resetError && <div className="twostep-error" role="alert">{resetError}</div>}
          </div>

          <div className="change-password-field">
            <label htmlFor="cp-new">New password</label>
            <input
              id="cp-new"
              className="profile-input"
              type={type}
              autoComplete="new-password"
              value={next}
              onChange={(e) => { setNext(e.target.value); setError(''); }}
            />
          </div>

          <div className="change-password-field">
            <label htmlFor="cp-confirm">Confirm new password</label>
            <input
              id="cp-confirm"
              className="profile-input"
              type={type}
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => { setConfirm(e.target.value); setError(''); }}
            />
            <p className="twostep-hint">
              At least {MIN_CHARS} characters, different from your current password. Other browsers signed in to
              your account will be signed out.
            </p>
          </div>

          {error && <div className="twostep-error" role="alert">{error}</div>}

          <div className="twostep-actions">
            <button type="button" className="twostep-btn" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="twostep-btn twostep-btn-primary" disabled={saving}>
              {saving ? 'Saving…' : 'Change password'}
            </button>
          </div>
        </form>
      </div>
    </Modal>
  );
};

export default ChangePasswordModal;
