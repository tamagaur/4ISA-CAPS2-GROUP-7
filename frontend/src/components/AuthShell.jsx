// The frame every signed-out screen shares (2026-10-16): the evening
// warehouse yard across the whole page, the SAN2 logo top left, and the
// frosted-glass card with the logo at its head and "Having trouble?" at
// its foot. Sign in, Forgot password and Set password (invites and
// resets) each put their own heading, words and form in the card, so the
// three look like one place. The look is LoginPage.css (.login-page); the
// form pieces (.input-group, .submit-btn, the notices) are Login.css's.
import React from 'react';
import { Headset } from 'lucide-react';
import '../Login.css';
import '../LoginPage.css';

export default function AuthShell({ children, help = true }) {
  return (
    <div className="login-container login-page">
      {/* "Corporation" in white for the dark sky; the card's copy below
          is the standard one. */}
      <div className="login-brand">
        <img src="/images/login-logo-red-light.png" alt="SAN2 Corporation" className="login-brand-logo" />
      </div>

      <div className="login-stage">
        <div className="login-card">
          <img src="/images/login-logo-red.png" alt="SAN2 Corporation" className="login-card-logo" />
          {children}
          {help && (
            <div className="login-help">
              <span className="login-help-icon"><Headset aria-hidden="true" /></span>
              <p>
                <strong>Having trouble?</strong>
                <span>Contact your system administrator.</span>
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
