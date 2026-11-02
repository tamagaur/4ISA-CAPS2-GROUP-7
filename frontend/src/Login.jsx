import React, { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, Lock, LockKeyhole, Mail, Sparkles } from 'lucide-react';
import {
  API_URL, confirmLoginMfaSetup, isDeviceRemembered, login, REMEMBER_DAYS, SESSION_EXPIRED_KEY, startLoginMfaSetup,
  verifyLoginCode,
} from './auth';
import TwoStepCodeForm from './components/TwoStepCodeForm';
import TwoStepSetup from './components/TwoStepSetup';
import RecoveryCodes from './components/RecoveryCodes';
import { beginHandoff, holdForHandoff } from './components/AuthHandoff';
import AuthShell from './components/AuthShell';

// Waking the server (audit SEC-6, 2026-10-21). The backend is on Render's free
// plan, which sleeps after about 15 minutes idle; the first request after that
// takes about a minute while it starts. The page now pings GET /status (no
// sign-in needed, backend/main.py; the sidebar's light uses it too) as soon as
// it opens, so the server is starting while the person types. If it hasn't
// answered within WAKE_NOTICE_MS (the audit's "about 5 s") the form says so,
// and it asks again every WAKE_RETRY_MS until the server answers.
// After WAKE_GIVE_UP_MS with no answer (2026-10-22, audit NEW3-FE-3) a cold
// start is no longer the likely reason, so the notice says the server can't
// be reached instead; the pings carry on quietly, every WAKE_SLOW_RETRY_MS
// rather than every WAKE_RETRY_MS (2026-10-24, audit #16: a page left open on
// a down server pinged it every 5 s forever), and the notice goes as soon as
// one is answered. One ping at a time: the next is scheduled only after the
// last has failed. This is a wake/status check only; sign-in doesn't wait on it.
const WAKE_NOTICE_MS = 5000;
const WAKE_RETRY_MS = 5000;
const WAKE_GIVE_UP_MS = 90000;
const WAKE_SLOW_RETRY_MS = 30000;

const Login = () => {
  const location = useLocation();
  const navigate = useNavigate();
  // A confirmation from the page that sent the user here (SetPassword:
  // "Your password is set..."). Kept in state, then cleared from the history
  // entry below so a reload or Back doesn't show it again.
  const [notice] = useState(() => location.state?.notice || '');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  // "Remember me" (2026-10-16, on the password form; it was on the code
  // step): skip the authenticator code on this browser for REMEMBER_DAYS.
  // Pre-ticked for an email this browser already remembers, until the
  // person changes it themselves.
  const [remember, setRemember] = useState(false);
  const [rememberTouched, setRememberTouched] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  // Explains an involuntary bounce back to this page. auth.js sets the flag
  // immediately before redirecting on an expired/rejected token; without it
  // the user just reappeared at the login screen mid-action with no reason
  // given (the "Session expired" error apiFetch throws can never render,
  // since the redirect has already started by the time it's caught).
  const [sessionExpired, setSessionExpired] = useState(false);
  // Two-step sign-in (backend/mfa.py), after a right password:
  //   { step: 'verify', token }            enter the code from the app
  //   { step: 'setup', token, setup }      this role must set it up first
  //   { step: 'codes', codes }             setup done: save the recovery codes
  // null = the password form.
  const [mfa, setMfa] = useState(null);
  // True once GET /status has gone WAKE_NOTICE_MS without answering, until it does.
  const [serverWaking, setServerWaking] = useState(false);
  // True once it has gone WAKE_GIVE_UP_MS without answering, until it does.
  const [serverUnreachable, setServerUnreachable] = useState(false);
  // The password (and code) accepted: the hand-off screen ("Signing in to
  // the dashboard…", shown by App.jsx's SignInHandoff) for a moment, then
  // the dashboard, with the screen staying up until the dashboard is in.
  const enterDashboard = async () => {
    beginHandoff('in');
    await holdForHandoff();
    navigate('/');
  };

  useEffect(() => {
    try {
      if (sessionStorage.getItem(SESSION_EXPIRED_KEY)) {
        setSessionExpired(true);
        // One-shot: don't repeat the notice on a later voluntary visit.
        sessionStorage.removeItem(SESSION_EXPIRED_KEY);
      }
    } catch { /* storage unavailable — just skip the notice */ }
  }, []);

  useEffect(() => {
    let done = false;
    let retry = null;
    const controller = new AbortController();
    const noticeTimer = setTimeout(() => { if (!done) setServerWaking(true); }, WAKE_NOTICE_MS);
    const giveUpTimer = setTimeout(() => { if (!done) setServerUnreachable(true); }, WAKE_GIVE_UP_MS);
    const startedAt = Date.now();
    const ping = () => {
      retry = null;
      if (done) return;
      fetch(`${API_URL}/status`, { cache: 'no-store', signal: controller.signal })
        .then((res) => {
          if (!res.ok) throw new Error(`status ${res.status}`);
          done = true;
          setServerWaking(false);
          setServerUnreachable(false);
        })
        .catch(() => {
          // Render answers 502/503 while it boots, or the connection drops;
          // ask again until it is up (or the page is left), less often once
          // it has been down past WAKE_GIVE_UP_MS.
          if (done || controller.signal.aborted) return;
          const delay = Date.now() - startedAt < WAKE_GIVE_UP_MS ? WAKE_RETRY_MS : WAKE_SLOW_RETRY_MS;
          clearTimeout(retry);
          retry = setTimeout(ping, delay);
        });
    };
    ping();
    return () => {
      done = true;
      controller.abort();
      clearTimeout(noticeTimer);
      clearTimeout(giveUpTimer);
      clearTimeout(retry);
    };
  }, []);

  useEffect(() => {
    if (location.state?.notice) {
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      const data = await login(email, password, { remember });
      if (data.mfa_step === 'verify') {
        setMfa({ step: 'verify', token: data.mfa_token });
      } else if (data.mfa_step === 'setup') {
        setMfa({ step: 'setup', token: data.mfa_token, setup: await startLoginMfaSetup(data.mfa_token) });
      } else {
        await enterDashboard();
      }
    } catch (err) {
      setError(err.message || 'Login failed. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Back to the password form: on request, or because the 5-minute step
  // token ran out (err.code 'mfa_expired').
  const backToPassword = (message = '') => {
    setMfa(null);
    setPassword('');
    setError(message);
  };

  // Thrown errors are shown by the code form itself, except an expired step.
  const withExpiry = (action) => async (code, options) => {
    try {
      await action(code, options);
    } catch (err) {
      if (err.code === 'mfa_expired') {
        backToPassword(err.message);
        return;
      }
      throw err;
    }
  };

  // "Remember me" (ticked on the password form): this browser isn't asked
  // for the code again for REMEMBER_DAYS (the password still is).
  const handleVerify = withExpiry(async (code, { remember = false } = {}) => {
    await verifyLoginCode(mfa.token, code, { email, remember });
    await enterDashboard();
  });

  const handleSetupConfirm = withExpiry(async (code) => {
    const data = await confirmLoginMfaSetup(mfa.token, code);
    setMfa({ step: 'codes', codes: data.recovery_codes });
  });

  const renderSecondStep = () => {
    if (mfa.step === 'codes') {
      return (
        <>
          <h2>Save your recovery <span className="page-title-accent">codes</span></h2>
          <p className="subtitle">Two-step sign-in is on.</p>
          <RecoveryCodes codes={mfa.codes} email={email} onDone={enterDashboard} doneLabel="Continue" variant="login" />
        </>
      );
    }
    const isSetup = mfa.step === 'setup';
    return (
      <>
        {isSetup ? (
          <h2>Set up two-step <span className="page-title-accent">sign-in</span></h2>
        ) : (
          <h2>Two-step <span className="page-title-accent">sign-in</span></h2>
        )}
        <p className="subtitle">
          {isSetup
            ? 'Your account needs a code from your phone each time you sign in. Set it up to continue.'
            : 'Enter the 6-digit code from your authenticator app.'}
          {!isSetup && remember && ` This device will be remembered for ${REMEMBER_DAYS} days.`}
        </p>
        {isSetup ? (
          <TwoStepSetup setup={mfa.setup} onConfirm={handleSetupConfirm} variant="login" />
        ) : (
          <TwoStepCodeForm
            onSubmit={(code) => handleVerify(code, { remember })}
            submitLabel="Verify"
            allowRecovery
            variant="login"
          />
        )}
        <div className="auth-links">
          <button type="button" className="auth-link twostep-link" onClick={() => backToPassword()}>
            Back to sign in
          </button>
        </div>
      </>
    );
  };

  // The look (2026-10-19, Audrey's golden-hour redesign, after the
  // 2026-10-16 twilight glass): the warehouse yard at sunset, the logo top
  // left, the introduction on the left and the white card at the right are
  // all AuthShell, shared with Forgot password and Set password, and stay
  // up through the two-step screens. The card is CSS over real form
  // fields, not a picture of one. "Welcome *Back*" carries the brand's
  // red-to-orange and a small sparkle (Audrey: colour, and welcoming).
  return (
    <AuthShell>
      {mfa ? renderSecondStep() : (
            <>
              <h2 className="login-welcome">
                Welcome <span className="page-title-accent login-welcome-accent">Back</span>
                <Sparkles className="login-welcome-spark" aria-hidden="true" />
              </h2>
              <p className="subtitle">Sign in to access the SAN2 Decision Support Dashboard</p>

              <form onSubmit={handleSubmit} className="login-form">
                {notice && !error && (
                  <div className="auth-success-message" role="status">{notice}</div>
                )}
                {sessionExpired && !notice && !error && (
                  <div className="session-expired-message" role="status">
                    Your session expired, so you were signed out. Please log in again.
                  </div>
                )}
                {error && <div className="error-message" role="alert">{error}</div>}
                {serverWaking && !serverUnreachable && !error && (
                  <div className="auth-info-message" role="status">
                    Starting the server… It sleeps when nobody has used the dashboard for a while and takes up to
                    a minute to wake. You can sign in now; it goes through as soon as the server is up.
                  </div>
                )}
                {serverUnreachable && !error && (
                  <div className="auth-info-message" role="status">
                    Can&apos;t reach the server. Check your connection or try again later.
                  </div>
                )}
                {/* Visible labels (2026-10-19): the placeholder is a hint now,
                    not the field's only name. */}
                <div className="login-field">
                  <label htmlFor="login-email">Email address</label>
                  <div className="input-group">
                    <Mail className="input-icon" aria-hidden="true" />
                    <input
                      id="login-email"
                      type="email"
                      placeholder="Enter your email"
                      autoComplete="email"
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        if (!rememberTouched) setRemember(isDeviceRemembered(e.target.value));
                      }}
                      required
                    />
                  </div>
                </div>

                <div className="login-field">
                  <label htmlFor="login-password">Password</label>
                  <div className="input-group password-group">
                    <LockKeyhole className="input-icon" aria-hidden="true" />
                    <input
                      id="login-password"
                      type={showPassword ? "text" : "password"}
                      placeholder="Enter your password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                    />
                    <button
                      type="button"
                      className="toggle-password"
                      onClick={() => setShowPassword(!showPassword)}
                      aria-label="Toggle password visibility"
                    >
                      {showPassword ? (
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                          <line x1="1" y1="1" x2="23" y2="23"></line>
                        </svg>
                      ) : (
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                          <circle cx="12" cy="12" r="3"></circle>
                        </svg>
                      )}
                    </button>
                  </div>
                </div>

                <div className="login-forgot-row login-options-row">
                  <label className="login-remember">
                    <input
                      type="checkbox"
                      checked={remember}
                      onChange={(e) => { setRemember(e.target.checked); setRememberTouched(true); }}
                    />
                    <span>Remember this Device?</span>
                  </label>
                  <Link to="/forgot-password" className="auth-link">Forgot password?</Link>
                </div>

                <button type="submit" className={`submit-btn ${isSubmitting ? 'submitting' : ''}`} disabled={isSubmitting}>
                  {isSubmitting ? 'Signing In...' : (
                    <>Sign In <ArrowRight className="submit-btn-arrow" aria-hidden="true" /></>
                  )}
                </button>
              </form>

              <p className="auth-notice">
                <Lock className="auth-notice-icon" aria-hidden="true" />
                For authorized SSM purchasing staff only.
              </p>
            </>
          )}
    </AuthShell>
  );
};

export default Login;
