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
//
// The opening animation waits for the yard picture (Audrey, 2026-10-21):
// until it has loaded and decoded, the page holds its first frame, then
// .is-ready lets the picture's veil, the words and the card all start
// together. A slow connection waits at most YARD_WAIT_MS; after that the
// page opens anyway and the picture comes in when it arrives, as before.
import React, { useEffect, useState } from 'react';
import { Headset } from 'lucide-react';
import LoginHero from './LoginHero';
// The same file LoginPage.css's image-set picks, so this load is the one
// the page shows.
import yardUrl from '../assets/login/warehouse-background.webp';
import '../Login.css';
import '../LoginPage.css';

const YARD_WAIT_MS = 1500;
// Once loaded, moving between Sign in, Forgot password and Set password
// doesn't wait again.
let yardLoaded = false;

function useYardReady() {
  const [ready, setReady] = useState(yardLoaded);
  useEffect(() => {
    if (ready) return undefined;
    let active = true;
    const start = () => { if (active) setReady(true); };
    const image = new Image();
    image.src = yardUrl;
    // decode() also resolves for a picture already in the cache; a failed
    // load rejects, and the page opens without it.
    image.decode()
      .then(() => { yardLoaded = true; })
      .catch(() => {})
      .finally(start);
    const timer = setTimeout(start, YARD_WAIT_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [ready]);
  return ready;
}

export default function AuthShell({ children, help = true }) {
  const ready = useYardReady();
  return (
    <div className={`login-container login-page${ready ? ' is-ready' : ''}`}>
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
