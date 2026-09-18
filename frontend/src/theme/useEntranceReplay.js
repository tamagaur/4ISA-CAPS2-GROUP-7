// Replay the CSS entrance animations when a page's data changes.
//
// The 2026-09-18 entrance pass (chart-card-enter / chartWidgetEnter) was
// deliberately mount-only: React keeps the cards mounted across a date or
// principal change, so nothing re-ran and the page just swapped its
// numbers in place. That reads as "nothing happened" on a filter change
// the user explicitly asked for, so the cards now rebuild on every applied
// filter change too — the frame re-entering is what makes a refetch look
// like a refetch.
//
// Restarting a CSS animation needs the element's `animation-name` to
// actually CHANGE; re-setting the same name is a no-op, and the usual
// alternatives are worse:
//
//   - remounting via a `key` throws away the chart subtree, so Recharts
//     re-measures its ResponsiveContainer from zero width and any local
//     state inside the card (ABC's search, pagination) resets;
//   - the offsetWidth reflow hack needs a DOM ref per animated element,
//     and there are 20+ of them across three pages.
//
// So this returns a 0/1 cycle that flips whenever `signature` changes.
// The page puts it on one wrapper as `data-enter-cycle`, and the
// stylesheets swap every animation-name to its identical `-b` twin
// through inherited custom properties — one attribute replays every card
// and bar underneath it, with no remount and no refs.
//
// `signature` should identify the DATA, not the control: pass the key of
// the response that is actually on screen, so the rebuild plays when the
// new numbers land rather than when the dropdown is clicked (which would
// animate an empty frame and then sit still while the request is in
// flight).
//
// prefers-reduced-motion needs nothing here — each stylesheet's existing
// `animation: none` override already wins over the swapped name, so a
// replay is a no-op for a viewer who has asked for less motion.
import { useState } from 'react';

export function useEntranceReplay(signature) {
  // Derived state, adjusted during render rather than in an effect: an
  // effect would paint one frame under the OLD cycle first, which shows
  // the new data fully settled and only then rewinds it to animate in.
  const [state, setState] = useState({ signature, cycle: 0 });

  if (state.signature !== signature) {
    setState({ signature, cycle: state.cycle === 0 ? 1 : 0 });
  }

  return state.cycle;
}

export default useEntranceReplay;
