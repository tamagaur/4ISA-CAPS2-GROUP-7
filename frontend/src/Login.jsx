import React, { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, Lock, LockKeyhole, Mail } from 'lucide-react';
import {
  confirmLoginMfaSetup, isDeviceRemembered, login, REMEMBER_DAYS, SESSION_EXPIRED_KEY, startLoginMfaSetup, verifyLoginCode,
} from './auth';
import TwoStepCodeForm from './components/TwoStepCodeForm';
import TwoStepSetup from './components/TwoStepSetup';
import RecoveryCodes from './components/RecoveryCodes';
import { beginHandoff, holdForHandoff } from './components/AuthHandoff';
import AuthShell from './components/AuthShell';

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

  // The look (2026-10-16, Audrey's twilight prototype): the evening
  // warehouse yard, the logo top left and the frosted-glass card are
  // AuthShell, shared with Forgot password and Set password; the card is
  // CSS over real form fields, not a picture of one.
  return (
    <AuthShell>
      {mfa ? renderSecondStep() : (
            <>
              <h2>
                Welcome <span className="page-title-accent">back</span>
                <svg className="login-title-spark" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 13V6M9.2 14.8l5-5M11 19h7" />
                </svg>
              </h2>
              <p className="subtitle">Sign in with your assigned account</p>

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
                <div className="input-group">
                  <Mail className="input-icon" aria-hidden="true" />
                  <input
                    type="email"
                    placeholder="Email address"
                    aria-label="Email address"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      if (!rememberTouched) setRemember(isDeviceRemembered(e.target.value));
                    }}
                    required
                  />
                </div>

                <div className="input-group password-group">
                  <LockKeyhole className="input-icon" aria-hidden="true" />
                  <input
                    type={showPassword ? "text" : "password"}
                    placeholder="Password"
                    aria-label="Password"
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
