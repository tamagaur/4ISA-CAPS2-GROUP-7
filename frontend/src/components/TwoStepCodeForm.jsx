import React, { useId, useState } from 'react';
import './TwoStep.css';

// The one code box every two-step sign-in screen uses: signing in, finishing
// setup, turning it off, new recovery codes (backend/mfa.py). onSubmit gets
// the code and throws to show an error. With allowRecovery a link switches
// the box to a recovery code, for a lost phone.
//
// variant="login" borrows the sign-in page's own field and button styles
// (Login.css), so the second step looks like the first.
//
// rememberLabel (sign-in only) adds a "Remember me" checkbox under the box;
// onSubmit then gets { remember } as its second argument.
const TwoStepCodeForm = ({
  onSubmit,
  submitLabel = 'Verify',
  busyLabel = 'Checking…',
  allowRecovery = false,
  rememberLabel = null,
  rememberHint = null,
  variant,
}) => {
  const inputId = useId();
  const [code, setCode] = useState('');
  const [remember, setRemember] = useState(false);
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const isLogin = variant === 'login';

  // Six digits, spaces allowed; a recovery code is ten letters/digits plus a dash.
  const ready = useRecovery
    ? code.replace(/[\s-]/g, '').length >= 10
    : code.replace(/\s/g, '').length === 6;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (busy || !ready) return;
    setError('');
    setBusy(true);
    try {
      await onSubmit(code.trim(), { remember: Boolean(rememberLabel) && remember });
    } catch (err) {
      setError(err.message || "That code didn't work. Please try again.");
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  const switchMode = () => {
    setUseRecovery((v) => !v);
    setCode('');
    setError('');
  };

  const input = (
    <input
      id={inputId}
      className={isLogin ? 'twostep-login-input' : 'twostep-code-input'}
      type="text"
      inputMode={useRecovery ? 'text' : 'numeric'}
      autoComplete={useRecovery ? 'off' : 'one-time-code'}
      autoCapitalize="off"
      spellCheck={false}
      placeholder={useRecovery ? 'xxxxx-xxxxx' : '6-digit code'}
      maxLength={useRecovery ? 20 : 7}
      value={code}
      onChange={(e) => setCode(useRecovery ? e.target.value : e.target.value.replace(/[^\d ]/g, ''))}
      aria-label={useRecovery ? 'Recovery code' : '6-digit code from your authenticator app'}
      // The box is the only thing to do on these screens.
      autoFocus
    />
  );

  return (
    <form className={isLogin ? 'login-form' : 'twostep-code-form'} onSubmit={handleSubmit}>
      {error && <div className={isLogin ? 'error-message' : 'twostep-error'} role="alert">{error}</div>}
      {isLogin ? <div className="input-group">{input}</div> : input}
      {rememberLabel && (
        <label className="twostep-remember">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span>
            {rememberLabel}
            {rememberHint && <span className="twostep-remember-hint">{rememberHint}</span>}
          </span>
        </label>
      )}
      <button
        type="submit"
        className={isLogin ? `submit-btn ${busy ? 'submitting' : ''}` : 'twostep-btn twostep-btn-primary'}
        disabled={busy || !ready}
      >
        {busy ? busyLabel : submitLabel}
      </button>
      {allowRecovery && (
        <button type="button" className="twostep-link" onClick={switchMode}>
          {useRecovery ? 'Use the code from the app instead' : 'Lost your phone? Use a recovery code'}
        </button>
      )}
    </form>
  );
};

export default TwoStepCodeForm;
