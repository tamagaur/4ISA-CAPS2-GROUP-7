// The frame every signed-out screen shares (2026-10-16; the look redone
// 2026-10-19, Audrey's golden-hour redesign): the warehouse yard at sunset
// across the whole page, the SAN2 logo top left, the introduction on the
// left (LoginHero: the eyebrow, the headline, the feature items) and a
// white card at the right with "Having trouble?" at its foot. Sign in,
// Forgot password and Set password (invites and resets) each put their
// own heading, words and form in the card, and everything around the card
// is the same on all three (Audrey, 2026-10-19: a password page is still
// the sign-in page), so the three look like one place. The look is
// LoginPage.css (.login-page); the form pieces (.input-group, .submit-btn,
// the notices) are Login.css's.
import React from 'react';
import { Headset } from 'lucide-react';
import LoginHero from './LoginHero';
import '../Login.css';
import '../LoginPage.css';

export default function AuthShell({ children, help = true }) {
  return (
    <div className="login-container login-page">
      <div className="login-brand">
        <img src="/images/login-logo-red.png" alt="SAN2 Corporation" className="login-brand-logo" />
      </div>

      <div className="login-stage">
        <div className="login-hero"><LoginHero /></div>
        <div className="login-card">
          {children}
          {help && (
            <>
              <hr className="login-divider" />
              <div className="login-help">
                <span className="login-help-icon"><Headset aria-hidden="true" /></span>
                <p>
                  <strong>Having trouble?</strong>
                  <span>Contact your system administrator.</span>
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
