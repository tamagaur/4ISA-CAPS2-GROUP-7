// A product as people read it: the NAME first, its SKU code underneath in
// small muted text (Sir Catubag, 2 Oct 2026: "product name first, code
// underneath — everywhere"). One component so every table and list shows
// products the same way.
//
// `onOpen` makes the name the click target that used to be the code link
// (a real <button>, so keyboards and screen readers reach it). Without it the
// name is plain text. A missing name falls back to the code alone, never an
// empty cell.
import React from 'react';
import './ProductName.css';

const ProductName = ({ name, code, onOpen, openLabel, className = '' }) => {
  const label = (name || '').trim();
  const sku = code != null && code !== '' ? String(code) : '';
  const title = label || sku || '—';
  return (
    <span className={`product-name ${className}`}>
      {/* The full name on hover, for a list that clamps long names. */}
      {onOpen ? (
        <button
          type="button"
          className="product-name-title product-name-link"
          onClick={onOpen}
          aria-label={openLabel ? `${openLabel}: ${title}` : undefined}
          title={title}
        >
          {title}
        </button>
      ) : (
        <span className="product-name-title" title={title}>{title}</span>
      )}
      {label && sku && <span className="product-name-code">{sku}</span>}
    </span>
  );
};

export default ProductName;
