// Idle stock — the dashboard's answer to "is any of our stock dead?" from
// actual sales (Technical Adviser, 2 Oct 2026; GET /dashboard's idle_stock,
// backend/marts.idle_stock): products in the stock count with no piece sold
// in the months before it, each valued at last purchase price. It replaced
// the card that read the warehouse's own Active/Inactive flag, which said
// nothing about whether a product sells.
//
// idle: { count_period, count_date, window_start, window_end, window_months,
//         products, products_with_value, pesos, pesos_basis, never_sold,
//         items: [{ sku_id, product_name, category_path, pesos, pieces,
//         cases, last_sale_period, never_sold }] (the largest by value),
//         blocked_reason }
import React from 'react';
import ProductName from './ProductName';
import { formatCompactPesos } from './Charts';
import { formatDate, formatMonth } from '../utils/formatDate';
import { formatUnits } from '../utils/formatNumber';
import './IdleStockWidget.css';

const exactPesos = (value) => `₱${Math.round(value).toLocaleString('en-PH')}`;

const IdleStockWidget = ({ idle }) => {
  const data = idle || {};
  const items = data.items || [];
  const hasData = !data.blocked_reason && data.products != null && data.count_period;
  const window = data.window_start && data.window_end
    ? `${formatMonth(data.window_start)} – ${formatMonth(data.window_end)}`
    : null;
  const counted = data.count_date ? `stock counted ${formatDate(data.count_date)}` : data.count_period
    ? `${formatMonth(data.count_period)} count` : null;
  return (
    <div className={`chart-widget${hasData ? '' : ' chart-widget-empty'}`}>
      <div className="chart-header">
        <div className="chart-title-area">
          <h4>Idle stock <span className="chart-unit">no sales in {data.window_rule_months ?? 6} months</span></h4>
          <p>
            Products in the stock count that sold no piece in the {data.window_months ?? data.window_rule_months ?? 6} sales
            months before it{window ? ` (${window})` : ''}, valued {data.pesos_basis || 'at last purchase price'}
            {counted ? ` · ${counted}` : ''}.
          </p>
        </div>
      </div>

      {!hasData ? (
        <p className="dashboard-empty-note">{data.blocked_reason || 'No idle-stock figure for this range'}</p>
      ) : (
        <div className="idle-stock-body">
          <div className="idle-stock-stats">
            <div className="idle-stock-stat is-lead">
              <span className="idle-stock-stat-value">{data.pesos != null ? formatCompactPesos(data.pesos) : '—'}</span>
              <span className="idle-stock-stat-label">tied up in idle stock</span>
            </div>
            <div className="idle-stock-stat">
              <span className="idle-stock-stat-value">{data.products.toLocaleString()}</span>
              <span className="idle-stock-stat-label">products with no sales{window ? `, ${window}` : ''}</span>
            </div>
            <div className="idle-stock-stat">
              <span className="idle-stock-stat-value">{(data.never_sold ?? 0).toLocaleString()}</span>
              <span className="idle-stock-stat-label">of them have never sold</span>
            </div>
          </div>

          {items.length > 0 && (
            <>
              <p className="idle-stock-list-title">
                The {items.length} largest by value{data.products > items.length ? `, of ${data.products.toLocaleString()}` : ''}
              </p>
              <div className="idle-stock-table-wrap">
                <table className="idle-stock-table">
                  <thead>
                    <tr>
                      <th scope="col" className="idle-col-product">Product</th>
                      <th scope="col">Stock (pieces)</th>
                      <th scope="col">Value (₱)</th>
                      <th scope="col">Last sale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.sku_id || item.product_name}>
                        <td className="idle-col-product"><ProductName name={item.product_name} code={item.sku_id} /></td>
                        <td>{item.pieces != null ? formatUnits(item.pieces) : '—'}</td>
                        <td>{item.pesos != null ? exactPesos(item.pesos) : '—'}</td>
                        <td>{item.never_sold ? 'Never sold' : item.last_sale_period ? formatMonth(item.last_sale_period) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default IdleStockWidget;
