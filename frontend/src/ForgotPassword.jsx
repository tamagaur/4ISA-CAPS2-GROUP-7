import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Mail } from 'lucide-react';
import { getPasswordResetInfo, requestPasswordReset } from './auth';
import AuthShell from './components/AuthShell';

const ENTER_REGISTERED_EMAIL = 'Enter the email address your account was created with.';
// The server's own words for an email no account uses (404); also shown for
// one it can't read as an email at all (422), since no account can use that.
const NOT_REGISTERED = `No account uses this email. ${ENTER_REGISTERED_EMAIL}`;

// Self-service "Forgot password?": asks the server to email a one-time link
// for choosing a new password. If no account uses the email, the server says
// so and the page asks for the one the account was created with, keeping
// what was typed so it can be corrected (Audrey's decision, 2026-09-30; the
// trade-off is in backend/routers/auth.py, EMAIL_NOT_REGISTERED). A server
// with no email set up (the live one) says so first, and the page shows that
// instead of the form.
const ForgotPassword = () => {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [emailWrong, setEmailWrong] = useState(false);
  const [sentMessage, setSentMessage] = useState('');
  const [noEmailMessage, setNoEmailMessage] = useState('');
  const emailRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    getPasswordResetInfo()
      .then((info) => { if (!cancelled && info?.email_enabled === false) setNoEmailMessage(info.detail); })
      .catch(() => {}); // Unknown: keep the form; the server's answer to it still says what happened.
    return () => { cancelled = true; };
  }, []);

  // A warning about the email itself: say it, and put the cursor back in the
  // box with the text selected, ready to be retyped.
  const warnAboutEmail = (message) => {
    setError(message);
    setEmailWrong(true);
    emailRef.current?.select();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setEmailWrong(false);
    const typed = email.trim();
    if (!typed) {
      warnAboutEmail(ENTER_REGISTERED_EMAIL);
      return;
    }
    setIsSubmitting(true);
    try {
      setSentMessage(await requestPasswordReset(typed));
    } catch (err) {
      if (err.status === 404) warnAboutEmail(err.message || NOT_REGISTERED);
      else if (err.status === 422) warnAboutEmail(NOT_REGISTERED);
      else setError(err.message || 'Could not send the reset link. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthShell>
          <h2>Reset your <span className="page-title-accent">password</span></h2>

          {noEmailMessage || sentMessage ? (
            <div className="auth-info-message auth-card-message" role="status">{noEmailMessage || sentMessage}</div>
          ) : (
            <>
              <p className="subtitle">Enter your email and we&apos;ll send you a link to choose a new password.</p>
              {/* noValidate: the server decides what counts as an email here,
                  and the warning above the box says it in one sentence. */}
              <form onSubmit={handleSubmit} className="login-form" noValidate>
                {error && <div id="forgot-email-error" className="error-message" role="alert">{error}</div>}
                <div className="input-group">
                  <Mail className="input-icon" aria-hidden="true" />
                  <input
                    ref={emailRef}
                    type="email"
                    placeholder="Email address"
                    aria-label="Email address"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      if (error) { setError(''); setEmailWrong(false); }
                    }}
                    aria-invalid={emailWrong || undefined}
                    aria-describedby={error ? 'forgot-email-error' : undefined}
                  />
                </div>

                <button type="submit" className={`submit-btn ${isSubmitting ? 'submitting' : ''}`} disabled={isSubmitting}>
                  {isSubmitting ? 'Sending...' : 'Send Reset Link'}
                </button>
              </form>
            </>
          )}

          <div className="auth-links">
            <Link to="/login" className="auth-link">Back to sign in</Link>
          </div>
    </AuthShell>
  );
};

export default ForgotPassword;
