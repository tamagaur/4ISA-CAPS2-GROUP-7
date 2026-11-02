// A rounded figure with its exact value one hover or tap away (2026-10-20):
// "about 161,000 pcs" on screen, "160,923 pcs" in the pop-up. Built on InfoTip,
// so it opens on hover, tap and keyboard like every other explanation.
import React from 'react';
import InfoTip from './InfoTip';
import { formatApprox } from '../utils/formatNumber';
import './ExactValue.css';

// `exact` (2026-10-25): the exact figure's own text, for a unit that goes
// before the number ("₱97,385,224"); `unit` is then not added.
const ExactValue = ({ value, unit = 'pcs', label = 'Exact figure', note = null, exact: exactText = null, children = null }) => {
  if (value == null) return '—';
  const exact = exactText ?? Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (exactText != null) unit = null;
  return (
    <InfoTip label={label} trigger={children ?? formatApprox(value)} triggerClassName="exact-value" className="exact-value-wrap">
      Exact: {exact}{unit ? ` ${unit}` : ''}.{note ? ` ${note}` : ''}
    </InfoTip>
  );
};

export default ExactValue;
