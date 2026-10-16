// "Good afternoon, Mikhaella!" in the top bar, beside the principal
// filter, on every page (2026-10-16; it began above the dashboard's title
// and moved up the same day so it is in view everywhere). The name is the
// one on the My profile page (/auth/me, through the
// permissions provider; the login token until that loads), so it follows
// a rename at once. The time of day is the browser's clock, re-read every
// minute, so a tab left open says "Good evening" when evening comes.
// On a change of page it dips out and back in with the page
// (PageTransition.css's timing): the element is keyed on the path, so it
// remounts and its entrance (Topbar.css) plays again.
import React, { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { usePermissions } from '../../permissions/context';
import { getCurrentUser } from '../../auth';
import { firstNameOf, greetingFor } from '../../utils/greeting';

const MINUTE = 60 * 1000;

const Greeting = () => {
  const { profile } = usePermissions();
  const { pathname } = useLocation();
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
  if (!name) return <p key={pathname} className="topbar-greeting">{greeting}!</p>;
  return (
    <p key={pathname} className="topbar-greeting">
      {greeting}, <strong className="topbar-greeting-name">{name}</strong>!
    </p>
  );
};

export default Greeting;
