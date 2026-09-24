import { useEffect, useState } from 'react';
import { getSKUs } from '../api/sku';

// sku_id -> real brand (SURF, KNORR, …) from the product master.
//
// GET /abc and GET /recommendations don't return a brand, so ABC
// Classification and Reorder Recs used to print a hardcoded 'Unilever' in
// their Brand column — the principal, not a brand, and the same word on
// every row. GET /sku does carry Product_Dimension.brand, and it's cached
// (api/cache.js), so this costs one request shared with SKU Management.
//
// Scoped to the page's principal (2026-09-24), like every other request on
// these pages: sku_code is not unique across principals, and the unscoped
// list was the one request that ignored the Topbar filter.
//
// Returns null until loaded (or if the request fails): callers show '—'
// rather than guessing, and SKUs the master has no brand for stay '—'.
export function useBrandLookup(principal) {
  const [brands, setBrands] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getSKUs({ principal })
      .then((res) => {
        if (cancelled) return;
        const map = new Map();
        (res.items || []).forEach((item) => {
          // Trimmed to match SKU Management's own normalization, so the same
          // brand doesn't render padded on one page and clean on another.
          const brand = (item.brand || '').trim();
          if (item.sku_id && brand) map.set(String(item.sku_id), brand);
        });
        setBrands(map);
      })
      .catch(() => {
        // Brand is supplementary on these pages; the table still renders.
      });
    return () => {
      cancelled = true;
    };
  }, [principal]);

  return brands;
}
