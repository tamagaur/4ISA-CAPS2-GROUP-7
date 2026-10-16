// The page-to-page transition inside the app shell (2026-10-16). React
// Router swaps the routed element the instant the URL changes, so one
// page used to vanish and the next appear in the same frame. Now the
// page that is leaving stays on screen for PAGE_LEAVE_MS while it fades
// out, and the next one mounts in a fresh wrapper whose entrance fades
// and lifts it in (PageTransition.css). The sidebar and top bar stay put.
//
// The leaving page is the element from the last render before the URL
// changed (useOutlet), drawn with the filter context it already had: it
// is on its way out. At every other moment the live outlet renders, so a
// filter change reaches the open page exactly as before. A viewer who
// asks for reduced motion gets an immediate swap and no animation (the
// stylesheet turns the keyframes off too).
import React, { Suspense, useEffect, useRef, useState } from 'react';
import { useLocation, useOutlet } from 'react-router-dom';
import { prefersReducedMotion } from '../theme/motion';
import './PageTransition.css';

// How long the leaving page fades; the entrance in the stylesheet is
// longer, so the new page settles after the old one has gone.
export const PAGE_LEAVE_MS = 160;

export default function PageTransition({ context, fallback = null }) {
  const location = useLocation();
  const outlet = useOutlet(context);
  const [page, setPage] = useState(() => ({ key: location.pathname }));
  const wrapRef = useRef(null);
  // The element last rendered for the page on screen, kept for its fade.
  const lastOutlet = useRef(outlet);
  const leaving = page.key !== location.pathname;
  if (!leaving) lastOutlet.current = outlet;

  // The URL changed: let the old page fade, then show the new one. A
  // second change during the fade just moves the target.
  useEffect(() => {
    if (!leaving) return undefined;
    const swap = () => setPage({ key: location.pathname });
    if (prefersReducedMotion()) {
      swap();
      return undefined;
    }
    const timer = setTimeout(swap, PAGE_LEAVE_MS);
    return () => clearTimeout(timer);
  }, [leaving, location.pathname]);

  // A page opens at its top, whatever the last one was scrolled to.
  useEffect(() => {
    const pane = wrapRef.current?.closest('.main-content');
    if (pane && pane.scrollTop > 0) pane.scrollTo({ top: 0 });
  }, [page.key]);

  return (
    <div
      ref={wrapRef}
      key={page.key}
      className={`page-transition ${leaving ? 'is-leaving' : 'is-entering'}`}
    >
      <Suspense fallback={fallback}>{leaving ? lastOutlet.current : outlet}</Suspense>
    </div>
  );
}
