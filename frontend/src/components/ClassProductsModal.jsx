// The products behind an ABC class on the dashboard: "which ones?", one
// click behind the count (Technical Adviser, 2 Oct 2026). The list is the
// same ranking the ring draws, GET /dashboard/pareto for the selected range,
// so its row count is the card's count. Each product also shows its sales
// against the same months a year earlier (GET /dashboard/yoy), the
// per-product year-over-year he asked for.
import React, { useEffect, useState } from 'react';
import { ArrowRight, X } from 'lucide-react';
import Modal from './Modal';
import ProductName from './ProductName';
import { formatCompactPesos } from './Charts';
import { getRangePareto, getRangeYoy } from '../api/dashboard';
import { labelForPrincipal } from '../principals';
import './AtRiskProductsModal.css';

const pct = (share, digits = 1) => (share == null ? '—' : `${(share * 100).toFixed(digits)}%`);

// "+12.4%" / "−8.0%" against the same months a year earlier; "new" when the
// product had no sales then, "—" when there is nothing to compare.
export const yoyText = (row) => {
  if (!row || row.pesos == null) return { text: '—', tone: null };
  if (row.prior_pesos == null || row.prior_pesos <= 0) return { text: 'new', tone: null };
  const change = (row.pesos - row.prior_pesos) / row.prior_pesos;
  // Fewer months of sales a year earlier than now is not a like-for-like
  // year: the figure says how many it had.
  const partial = row.prior_months != null && row.months != null && row.prior_months < row.months
    ? ` (${row.prior_months} of ${row.months} months then)` : '';
  return {
    text: `${change >= 0 ? '+' : '−'}${Math.abs(change * 100).toFixed(1)}%${partial}`,
    tone: change >= 0 ? 'up' : 'down',
  };
};

const ClassProductsModal = ({ isOpen, onClose, tier, args, onOpenProduct, onOpenAbcPage }) => {
  const [state, setState] = useState({ key: null, pareto: null, yoy: null, error: null });
  const key = isOpen ? JSON.stringify([args?.period, args?.startPeriod, args?.principal]) : null;

  useEffect(() => {
    if (!key) return undefined;
    let cancelled = false;
    // Year-over-year is a bonus column: the list still shows if it fails.
    Promise.all([getRangePareto(args), getRangeYoy(args).catch(() => null)])
      .then(([pareto, yoy]) => { if (!cancelled) setState({ key, pareto, yoy, error: null }); })
      .catch((err) => { if (!cancelled) setState({ key, pareto: null, yoy: null, error: err.message || 'Failed to load the class list' }); });
    return () => { cancelled = true; };
    // `args` is read through `key`, which changes exactly when its parts do.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!isOpen) return null;
  const loading = state.key !== key;
  const pareto = loading ? null : state.pareto;
  const priorLabel = state.yoy?.prior_label || 'the same months last year';
  const yoyByKey = new Map(
    (state.yoy?.principals || []).flatMap((p) => (p.rows || []).map((r) => [`${p.principal}|${r.product_key}`, r])),
  );
  const blocks = (pareto?.principals || [])
    .map((p) => ({ ...p, cls: (p.classes || []).find((c) => c.tier === tier) }))
    .filter((p) => p.cls);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      labelledBy="class-products-title"
      overlayClassName="at-risk-overlay"
      containerClassName="at-risk-card"
    >
      <div className="at-risk-header">
        <div>
          <h3 id="class-products-title" className="at-risk-title">Class {tier} products</h3>
          <p className="at-risk-subtitle">
            Ranked on sales over {pareto?.label || 'the selected range'}, highest first · pesos at{' '}
            {blocks[0]?.pesos_basis || 'selling price'}
          </p>
        </div>
        <button type="button" className="at-risk-close" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
      </div>

      {loading && <p className="at-risk-money">Loading the list…</p>}
      {!loading && state.error && <p className="at-risk-money">{state.error}</p>}
      {!loading && !state.error && blocks.length === 0 && (
        <p className="at-risk-money">No products were ranked in this range.</p>
      )}

      {blocks.map((block) => {
        const isCategory = block.grain === 'category';
        return (
          <React.Fragment key={block.principal}>
            <p className="at-risk-money">
              {blocks.length > 1 && <strong>{labelForPrincipal(block.principal)}: </strong>}
              <strong>{block.cls.count.toLocaleString()}</strong> {isCategory ? 'categories' : 'products'} made{' '}
              <strong>{pct(block.cls.share)}</strong> of {pareto.label} revenue
              {block.cls.revenue != null && <> (about <strong>{formatCompactPesos(block.cls.revenue)}</strong>)</>}.
            </p>
            <div className="at-risk-table-wrap" tabIndex={0}>
              <table className="at-risk-table">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col" className="at-risk-col-product">{isCategory ? 'Category' : 'Product'}</th>
                    <th scope="col">
                      Revenue (₱)
                      <span className="at-risk-th-sub">{pareto.label}</span>
                    </th>
                    {!isCategory && (
                      <th scope="col">
                        Sold (pieces)
                        <span className="at-risk-th-sub">{pareto.label}</span>
                      </th>
                    )}
                    <th scope="col">
                      Share (%)
                      <span className="at-risk-th-sub">of {pareto.label} revenue</span>
                    </th>
                    <th scope="col">
                      Running total (%)
                      <span className="at-risk-th-sub">from the top seller down</span>
                    </th>
                    <th scope="col">
                      Change (%)
                      <span className="at-risk-th-sub">vs {priorLabel}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {block.cls.products.map((item) => {
                    const yoy = yoyText(yoyByKey.get(`${block.principal}|${item.product_key}`));
                    // Only a product with a SKU code has a forecast page.
                    const canOpen = !isCategory && item.sku_id && onOpenProduct;
                    return (
                      <tr key={item.product_key ?? item.product_name ?? item.category_path}>
                        <td>{item.rank}</td>
                        <td className="at-risk-col-product">
                          <ProductName
                            name={item.product_name || item.category_path}
                            code={isCategory ? null : item.sku_id}
                            onOpen={canOpen ? () => onOpenProduct(item.sku_id) : undefined}
                            openLabel="Open its forecast"
                          />
                        </td>
                        <td>{formatCompactPesos(item.revenue)}</td>
                        {!isCategory && (
                          <td>{item.pieces != null ? Math.round(item.pieces).toLocaleString() : '—'}</td>
                        )}
                        <td>{pct(item.share, 2)}</td>
                        <td>{pct(item.cumulative_share)}</td>
                        <td className={yoy.tone ? `class-yoy-${yoy.tone}` : undefined}>{yoy.text}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </React.Fragment>
        );
      })}

      <div className="at-risk-footer">
        <p className="at-risk-footnote">
          Change compares each product&apos;s sales with the same months a year earlier. Click a product to open its forecast.
        </p>
        <div className="at-risk-actions">
          <button type="button" className="at-risk-btn" onClick={onClose}>Close</button>
          {onOpenAbcPage && (
            <button type="button" className="at-risk-btn is-primary" onClick={onOpenAbcPage}>
              Open on the ABC page <ArrowRight size={14} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
};

export default ClassProductsModal;
