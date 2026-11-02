// "Good afternoon, Mikhaella!" — the dashboard's welcome banner (2026-10-21,
// Audrey: moved out of the top bar, where it sat beside the principal filter
// on every page since 2026-10-16, into a banner above "Inventory pulse").
// The name is the one on the My profile page (/auth/me, through the
// permissions provider; the login token until that loads), so it follows a
// rename at once. The time of day is the browser's clock, re-read every
// minute and whenever the tab comes back into view, so a tab left open says
// "Good evening" when evening comes. utils/greeting.js holds both rules.
import React, { useEffect, useState } from 'react';
import { Warehouse } from 'lucide-react';
import { usePermissions } from '../../permissions/context';
import { getCurrentUser } from '../../auth';
import { firstNameOf, greetingFor } from '../../utils/greeting';

const MINUTE = 60 * 1000;

// The greeting words and the first name, kept current.
const useGreeting = () => {
  const { profile } = usePermissions();
  const token = getCurrentUser();
  const name = firstNameOf(profile?.fullName ?? token?.fullName, profile?.email ?? token?.email);
  const [greeting, setGreeting] = useState(() => greetingFor(new Date().getHours()));
  useEffect(() => {
    const tick = () => setGreeting(greetingFor(new Date().getHours()));
    const timer = setInterval(tick, MINUTE);
    document.addEventListener('visibilitychange', tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, []);
  return { greeting, name };
};

// The banner: the greeting large, the name in the brand accent, and one
// short line under it; a quiet warehouse mark on the right to balance the
// row (decoration only: hidden from screen readers, and from narrow screens
// in Dashboard.css). A paragraph, not a heading: the page's heading is
// still "Inventory pulse" below it.
const WelcomeBanner = ({ subtitle = "Here's your inventory overview." }) => {
  const { greeting, name } = useGreeting();
  return (
    <section className="welcome-banner" aria-label="Welcome">
      <div className="welcome-text">
        <p className="welcome-greeting">
          {greeting}{name ? <>, <span className="welcome-name">{name}</span></> : null}!
        </p>
        {subtitle && <p className="welcome-sub">{subtitle}</p>}
      </div>
      <span className="welcome-mark" aria-hidden="true">
        <Warehouse size={30} strokeWidth={1.6} />
      </span>
    </section>
  );
};

export default WelcomeBanner;
