import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Eye, EyeOff, LockKeyhole } from 'lucide-react';
import { getLinkInfo, setPasswordWithLink } from './auth';
import AuthShell from './components/AuthShell';

// The server's rules (POST /auth/set-password): at least 8 characters and
// at most 72 bytes of UTF-8 — bcrypt ignores everything past byte 72.
const MIN_CHARS = 8;
const MAX_BYTES = 72;

const LINK_DEAD_MESSAGE =
  'This link has expired or has already been used. Ask your admin for a new one, or use Forgot password.';

// Invite and reset emails link to /set-password#token=…. The token rides in
// the fragment because a browser never sends the fragment to any server, so
// it can't end up in a server or proxy log.
function readTokenFromHash() {
  const match = /(?:^#|&)token=([^&]*)/.exec(window.location.hash);
  if (!match) return '';
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return '';
  }
}

function passwordProblem(password, confirm) {
  // Array.from counts characters the way the server's len() does; .length
  // would count an emoji as two.
  if (Array.from(password).length < MIN_CHARS) return `Use at least ${MIN_CHARS} characters.`;
  if (new TextEncoder().encode(password).length > MAX_BYTES) {
    return 'That password is too long. Keep it to 72 characters or fewer (accented letters and emoji count as more than one).';
  }
  if (password !== confirm) return 'The two passwords don’t match.';
  return '';
}

// Where invite and reset links land: the person chooses their own password,
// so no admin ever knows it. Public page — no session needed.
const SetPassword = () => {
  const navigate = useNavigate();
  // Read once and kept only in memory; the effect below then takes it out
  // of the address bar.
  const [token] = useState(readTokenFromHash);
  // 'checking' | 'ready' | 'missing' (opened without a link, e.g. reloaded —
  // the token is never stored) | 'invalid' (expired or used) | 'unreachable'
  const [linkState, setLinkState] = useState(token ? 'checking' : 'missing');
  const [linkInfo, setLinkInfo] = useState(null);
  const [checkAttempt, setCheckAttempt] = useState(0);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  // Out of the address bar means out of browser history, a copied URL and a
  // screenshot too. history.state is passed through untouched: it holds
  // React Router's bookkeeping for this entry.
  useEffect(() => {
    if (window.location.hash) {
      window.history.replaceState(window.history.state, '', window.location.pathname);
    }
  }, []);

  useEffect(() => {
    if (!token) return undefined;
    let cancelled = false;
    setLinkState('checking');
    getLinkInfo(token)
      .then((info) => {
        if (cancelled) return;
        setLinkInfo(info);
        setLinkState('ready');
      })
      .catch((err) => {
        if (cancelled) return;
        // 400/422 mean the link itself is no good. Anything else (server
        // down, no network) says nothing about the link, and since the token
        // is already gone from the URL, a reload can't retry — so offer one.
        setLinkState(err.status === 400 || err.status === 422 ? 'invalid' : 'unreachable');
      });
    return () => { cancelled = true; };
  }, [token, checkAttempt]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const problem = passwordProblem(password, confirm);
    if (problem) {
      setError(problem);
      return;
    }
    setError('');
    setIsSubmitting(true);
    try {
      await setPasswordWithLink(token, password);
      navigate('/login', { replace: true, state: { notice: 'Your password is set. Sign in with it now.' } });
    } catch (err) {
      setIsSubmitting(false);
      // The link can lapse (or be used in another tab) while this form sits open.
      if (err.status === 400) setLinkState('invalid');
      else setError(err.message || 'Could not set your password. Please try again.');
    }
  };

  const renderCard = () => {
    if (linkState === 'checking') {
      return <p className="subtitle auth-checking" role="status">Checking your link…</p>;
    }

    if (linkState === 'missing') {
      // Not "expired": after a reload the link itself may still be good.
      return (
        <>
          <h2>Open your <span className="page-title-accent">link</span></h2>
          <div className="auth-info-message auth-card-message" role="status">
            This page works through the link in your invite or password-reset email. Open that
            link again. If it has expired, ask your admin for a new one, or use Forgot password.
          </div>
          <div className="auth-links">
            <Link to="/forgot-password" className="auth-link">Forgot password?</Link>
            <Link to="/login" className="auth-link">Back to sign in</Link>
          </div>
        </>
      );
    }

    if (linkState === 'invalid') {
      return (
        <>
          <h2>Link <span className="page-title-accent">expired</span></h2>
          <div className="auth-info-message auth-card-message" role="alert">{LINK_DEAD_MESSAGE}</div>
          <div className="auth-links">
            <Link to="/forgot-password" className="auth-link">Forgot password?</Link>
            <Link to="/login" className="auth-link">Back to sign in</Link>
          </div>
        </>
      );
    }

    if (linkState === 'unreachable') {
      return (
        <>
          <h2>Can&apos;t check this <span className="page-title-accent">link</span></h2>
          <div className="login-form auth-card-message">
            <div className="error-message" role="alert">
              We couldn&apos;t check your link just now. Check your connection and try again.
            </div>
            <button type="button" className="submit-btn" onClick={() => setCheckAttempt((n) => n + 1)}>
              Try Again
            </button>
          </div>
          <div className="auth-links">
            <Link to="/login" className="auth-link">Back to sign in</Link>
          </div>
        </>
      );
    }

    const isReset = linkInfo?.purpose === 'reset';
    const firstName = linkInfo?.full_name?.trim().split(/\s+/)[0];

    return (
      <>
        {isReset ? (
          <h2>Choose a new <span className="page-title-accent">password</span></h2>
        ) : (
          <h2>Set your <span className="page-title-accent">password</span></h2>
        )}
        <p className="subtitle">
          {isReset ? (
            <>This replaces the current password for <strong>{linkInfo.email}</strong>.</>
          ) : (
            <>{firstName ? `Welcome, ${firstName}. ` : ''}Choose a password for <strong>{linkInfo.email}</strong>.</>
          )}
        </p>

        <form onSubmit={handleSubmit} className="login-form">
          {error && <div className="error-message" role="alert">{error}</div>}
          {/* Lets a password manager file the new password under this account. */}
          <input type="email" name="username" autoComplete="username" value={linkInfo.email} readOnly hidden />

          <div className="login-field">
            <label htmlFor="set-password">New password</label>
            <div className="input-group password-group">
              <LockKeyhole className="input-icon" aria-hidden="true" />
              <input
                id="set-password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Enter a new password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="toggle-password"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? 'Hide passwords' : 'Show passwords'}
              >
                {showPassword ? <EyeOff /> : <Eye />}
              </button>
            </div>
          </div>

          <div className="login-field">
            <label htmlFor="set-confirm">Confirm new password</label>
            <div className="input-group">
              <LockKeyhole className="input-icon" aria-hidden="true" />
              <input
                id="set-confirm"
                type={showPassword ? 'text' : 'password'}
                placeholder="Re-enter the new password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
              />
            </div>
          </div>
          <p className="auth-hint">At least {MIN_CHARS} characters.</p>

          <button type="submit" className={`submit-btn ${isSubmitting ? 'submitting' : ''}`} disabled={isSubmitting}>
            {isSubmitting ? 'Saving...' : isReset ? 'Save New Password' : 'Set Password'}
          </button>
        </form>

        <div className="auth-links">
          <Link to="/login" className="auth-link">Back to sign in</Link>
        </div>
      </>
    );
  };

  return <AuthShell>{renderCard()}</AuthShell>;
};

export default SetPassword;
