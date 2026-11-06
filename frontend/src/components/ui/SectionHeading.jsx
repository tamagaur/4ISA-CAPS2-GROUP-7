// A section's heading in the Dashboard's style (its Slot, 2026-10-16), for
// the other pages: a short question with one key phrase in .title-accent, the
// section's one "?" when there is something to explain, a thin accent rule
// running to the right, then the period tags (BasisTag): teal when the
// section follows the date filter, grey with a pin when it is fixed to a
// month or a stock count. Styles in ui.css (.section-heading).
//
//   <SectionHeading id="x-title" tags={<BasisTag label="Stock counted Apr 6, 2026" follows={false} />}>
//     Do the top sellers have <span className="title-accent">enough stock</span>?
//   </SectionHeading>
//
// `id` lets the section name itself (aria-labelledby). `info` is the "?"
// text, `infoLabel` its button's name. Under ui.css's .ui-section the
// heading keeps a 16px gap to the card below it.
import React from 'react';
import InfoTip from '../InfoTip';

const SectionHeading = ({ id, children, info = null, infoLabel = 'More about this section', tags = null, as: Tag = 'h3' }) => (
  <div className="section-heading">
    <Tag id={id} className="section-heading-question">{children}</Tag>
    {info && <InfoTip label={infoLabel} size={14}>{info}</InfoTip>}
    <span className="section-heading-rule" aria-hidden="true" />
    {tags && <span className="section-heading-tags">{tags}</span>}
  </div>
);

export default SectionHeading;
