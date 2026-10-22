// A rounded figure with its exact value one hover or tap away (2026-10-20):
// "about 161,000 pcs" on screen, "160,923 pcs" in the pop-up. Built on InfoTip,
// so it opens on hover, tap and keyboard like every other explanation.
import React from 'react';
import InfoTip from './InfoTip';
import { formatApprox } from '../utils/formatNumber';
import './ExactValue.css';

const ExactValue = ({ value, unit = 'pcs', label = 'Exact figure', note = null, children = null }) => {
  if (value == null) return '—';
  const exact = Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return (
    <InfoTip label={label} trigger={children ?? formatApprox(value)} triggerClassName="exact-value" className="exact-value-wrap">
      Exact: {exact}{unit ? ` ${unit}` : ''}.{note ? ` ${note}` : ''}
    </InfoTip>
  );
};

export default ExactValue;
