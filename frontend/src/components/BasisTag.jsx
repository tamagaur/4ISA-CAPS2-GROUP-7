// A card's period basis, in a small tag: whether its figures change with the
// date filter ("Selected range"), or are pinned to something else ("Mar 2026
// plan", "Latest stock count"). The Technical Adviser changes the filter and
// watches what moves; a card that stays put says why here, with the detail
// one tap away, rather than looking broken.
import React from 'react';
import { CalendarRange, Pin } from 'lucide-react';
import InfoTip from './InfoTip';
import './BasisTag.css';

const BasisTag = ({ label, follows = true, detail }) => {
  if (!label) return null;
  return (
    <span className={`basis-tag ${follows ? 'is-follows' : 'is-fixed'}`}>
      {follows ? <CalendarRange size={11} aria-hidden="true" /> : <Pin size={11} aria-hidden="true" />}
      <span>{label}</span>
      {detail && <InfoTip label={`About the period: ${label}`} size={11}>{detail}</InfoTip>}
    </span>
  );
};

// The detail line for a card that follows the date filter.
export const FOLLOWS_RANGE = 'Changes with the date filter.';

export default BasisTag;
