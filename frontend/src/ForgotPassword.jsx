import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getPasswordResetInfo, requestPasswordReset } from './auth';
import './Login.css';

// Self-service "Forgot password?": asks the server to email a one-time link
// for choosing a new password. The server answers the same way whether or
// not the email has an account, and this page only ever repeats that
// answer — it must never hint at which it was. A server with no email set up
// (the live one) says so first, and the page shows that instead of the form.
const ForgotPassword = () => {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [sentMessage, setSentMessage] = useState('');
  const [noEmailMessage, setNoEmailMessage] = useState('');

  useEffect(() => {
    let cancelled = false;
    getPasswordResetInfo()
      .then((info) => { if (!cancelled && info?.email_enabled === false) setNoEmailMessage(info.detail); })
      .catch(() => {}); // Unknown: keep the form; the server's answer to it still says what happened.
    return () => { cancelled = true; };
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      setSentMessage(await requestPasswordReset(email));
    } catch (err) {
      setError(err.message || 'Could not send the reset link. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-left">
        <div className="logo-section">
          <img src="/logo.png" alt="SAN2 Corporation Logo" className="logo-image" />
          <p className="dashboard-title">Inventory Decision Support Dashboard</p>
          <ul className="login-feature-list">
            <li>Per-SKU demand forecasting</li>
            <li>ABC-classified replenishment</li>
            <li>Reorder recommendations</li>
          </ul>
        </div>
      </div>

      <div className="login-right">
        <div className="login-card">
          <h2>Reset your <span className="page-title-accent">password</span></h2>

          {noEmailMessage || sentMessage ? (
            <div className="auth-info-message auth-card-message" role="status">{noEmailMessage || sentMessage}</div>
          ) : (
            <>
              <p className="subtitle">Enter your email and we&apos;ll send you a link to choose a new password.</p>
              <form onSubmit={handleSubmit} className="login-form">
                {error && <div className="error-message" role="alert">{error}</div>}
                <div className="input-group">
                  <input
                    type="email"
                    placeholder="Email address"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
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
        </div>

        <p className="help-text">Having trouble? Contact your system administrator.</p>
      </div>
    </div>
  );
};

export default ForgotPassword;
