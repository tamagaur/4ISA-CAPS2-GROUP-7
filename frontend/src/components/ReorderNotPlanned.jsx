// The top sellers the current plan has no row for (GET /recommendations
// ?include_not_planned=true, 2026-11-03). The plan only covers Class A products whose
// forecast passed the accuracy check, so without this the page says nothing about the
// rest, however low their stock. Read-only and beside the plan: no order quantity, no
// action, and never in the plan's counts, total or Accept all. The server orders it,
// lowest cover first, with no cut-off: nothing here decides what counts as low.
import React, { useState } from 'react';
import { AlertTriangle, ChevronDown, PackageSearch } from 'lucide-react';
import InfoTip from './InfoTip';
import ProductName from './ProductName';
import { formatMonth } from '../utils/formatDate';
import { matchesSearch, notPlannedLede, revenueShareBasis } from '../utils/reorderView';

// How many rows show before "Show all". A length for the page, not a limit on the
// list: the first rows are the lowest cover, and the rest are one click away.
const FIRST_ROWS = 10;

const ReorderNotPlanned = ({
  items, tier, tierPeriod, countLabel, coverSalesLabel, coverNote, abcLabel, notInCountNote, query = '', brandOf, formatSku,
  onOpenForecast,
}) => {
  const [showAll, setShowAll] = useState(false);
  const searching = query.trim() !== '';
  const matched = searching
    ? items.filter((item) => matchesSearch({ product: item.product_name, sku: item.sku_id }, query, brandOf({ sku: item.sku_id })))
    : items;
  if (matched.length === 0) return null;
  const listed = searching || showAll ? matched : matched.slice(0, FIRST_ROWS);
  const shareBasis = abcLabel ? revenueShareBasis('unilever', abcLabel) : null;

  return (
    <section className={`reorder-notplanned is-${tier}`} aria-labelledby="reorder-notplanned-title">
      <div className="reorder-notplanned-head">
        <span className="reorder-how-icon" aria-hidden="true"><PackageSearch size={18} /></span>
        <div className="reorder-how-heading">
          <h3 className="reorder-how-title" id="reorder-notplanned-title">Not in This Plan</h3>
          <p className="reorder-how-lede">
            {notPlannedLede(items, tierPeriod ? formatMonth(tierPeriod) : null)} The plan gives them no quantity and no urgency,
            so low stock here raises no alert. Lowest cover first.
            {searching && ` ${matched.length.toLocaleString()} of them match your search.`}
          </p>
        </div>
      </div>

      <div className="reorder-notplanned-scroll">
        <table className="data-table reorder-notplanned-table">
          {tier !== 'cards' && (
            <thead>
              <tr>
                <th scope="col" className="col-text col-product">Product (SKU)</th>
                <th scope="col" className="col-text">Why It Isn&apos;t Planned</th>
                <th scope="col" className="table-center">
                  Opening Stock
                  <span className="reorder-th-period">{countLabel}, in pieces</span>
                </th>
                <th scope="col" className="table-center">
                  Sales a Month
                  <span className="reorder-th-period">{coverSalesLabel ? `${coverSalesLabel} average` : 'recent average'}, in pieces</span>
                </th>
                <th scope="col" className="table-center">
                  <span className="reorder-head-label">
                    Cover (Days)
                    <InfoTip label="About cover">{coverNote}</InfoTip>
                  </span>
                </th>
                {tier !== 'tablet' && (
                  <th scope="col" className="table-center">
                    Revenue Share
                    {shareBasis && <span className="reorder-th-period">{shareBasis}</span>}
                  </th>
                )}
              </tr>
            </thead>
          )}
          <tbody>
            {listed.map((item) => (
              <tr key={item.sku_id}>
                <td className="cell-product">
                  <ProductName
                    name={item.product_name || 'Unknown Product'}
                    code={formatSku(item.sku_id)}
                    onOpen={onOpenForecast ? () => onOpenForecast(item.sku_id) : undefined}
                    openLabel="See this product’s sales history and forecast"
                  />
                </td>
                <td className="col-text reorder-notplanned-why" data-label="Why It Isn’t Planned">{item.reason}</td>
                <td className="table-center" data-label="Opening Stock">
                  {item.stock_not_in_count && (
                    <span className="reorder-count-flag" title={notInCountNote}>
                      <AlertTriangle size={12} aria-hidden="true" />
                      Not in stock count
                    </span>
                  )}
                  {!item.stock_not_in_count && item.current_stock != null && Math.round(item.current_stock).toLocaleString()}
                  {!item.stock_not_in_count && item.current_stock == null && (
                    <span className="cell-empty" title={item.cover_blocked_reason || undefined}>—</span>
                  )}
                </td>
                <td className="table-center" data-label="Sales a Month">
                  {item.avg_monthly_pieces != null
                    ? Math.round(item.avg_monthly_pieces).toLocaleString()
                    : <span className="cell-empty">—</span>}
                </td>
                <td className="table-center" data-label="Cover (Days)" title={item.days_of_cover != null ? undefined : (item.cover_blocked_reason || undefined)}>
                  {item.days_of_cover != null ? item.days_of_cover.toFixed(1) : <span className="cell-empty">—</span>}
                </td>
                {tier !== 'tablet' && (
                  <td className="table-center" data-label="Revenue Share">
                    {item.revenue_share != null ? `${(item.revenue_share * 100).toFixed(2)}%` : <span className="cell-empty">—</span>}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!searching && matched.length > FIRST_ROWS && (
        <div className="reorder-notplanned-more">
          <button type="button" className="reorder-group-toggle" onClick={() => setShowAll((v) => !v)} aria-expanded={showAll}>
            <ChevronDown size={14} className={showAll ? 'reorder-notplanned-chevron-open' : undefined} aria-hidden="true" />
            {showAll ? `Show the first ${FIRST_ROWS}` : `Show all ${matched.length.toLocaleString()}`}
          </button>
        </div>
      )}
    </section>
  );
};

export default ReorderNotPlanned;
