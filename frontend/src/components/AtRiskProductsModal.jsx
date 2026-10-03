// The list behind the dashboard's "N of M below safety stock": which Class A
// products they are, by how much each is short, and what the order plan
// suggests — with the way through to that plan (Technical Adviser, 2 Oct
// 2026: "nasaan siya?" — detail one click behind every aggregate, and the
// cards connected: which products matter -> which are at risk -> what to
// order).
//
// `items` are GET /dashboard's safety_stock_exposure.below_items: the very
// rows the count was taken from, most revenue first, in pieces. `chain` is
// how the count is arrived at, step by step, so "35 of 70" explains itself:
// the Class A products, the ones the order plan covers, the ones with a
// stock count, and the ones below safety stock.
import React from 'react';
import { ArrowRight, X } from 'lucide-react';
import Modal from './Modal';
import ProductName from './ProductName';
import { formatCompactPesos } from '../utils/formatters';
import { formatUnits } from '../utils/formatNumber';
import './AtRiskProductsModal.css';

const pct = (share, digits = 1) => (share == null ? '—' : `${(share * 100).toFixed(digits)}%`);

const AtRiskProductsModal = ({
  isOpen,
  onClose,
  items = [],
  chain,
  revenueShare = null,
  revenueTotal = null,
  onOpenProduct,
  onOpenPlan,
}) => {
  if (!isOpen) return null;
  const { classACount, plannedCount, measurableCount, belowCount, abcMonth, planLabel, countDay } = chain;
  // "in pesos?" — the share of the month's revenue these products earned,
  // and that share of the month's ranked revenue in pesos.
  const revenuePesos = revenueShare != null && revenueTotal != null ? revenueShare * revenueTotal : null;
  const steps = [
    { value: classACount, label: 'Class A products', note: abcMonth ? `top sellers of ${abcMonth}` : 'top sellers' },
    { value: plannedCount, label: 'in the order plan', note: planLabel ? `${planLabel} · forecast passed the accuracy check` : null },
    { value: measurableCount, label: 'have a stock count', note: countDay ? `counted ${countDay}` : null },
    { value: belowCount, label: 'below safety stock', note: 'listed here', last: true },
  ].filter((step) => step.value != null);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      labelledBy="at-risk-title"
      overlayClassName="at-risk-overlay"
      containerClassName="at-risk-card"
    >
      <div className="at-risk-header">
        <div>
          <h3 id="at-risk-title" className="at-risk-title">Class A products below safety stock</h3>
          <p className="at-risk-subtitle">
            Stock on hand against each product&apos;s safety stock, in pieces
            {planLabel ? ` · ${planLabel}` : ''}{countDay ? ` · stock counted ${countDay}` : ''}
          </p>
        </div>
        <button type="button" className="at-risk-close" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
      </div>

      {/* How the count is arrived at: each step is a subset of the one
          before it, so the reader sees what "N of M" is a count of. */}
      <ol className="at-risk-chain" aria-label="How this count is arrived at">
        {steps.map((step, i) => (
          <li key={step.label} className={`at-risk-step${step.last ? ' is-last' : ''}`}>
            {i > 0 && <ArrowRight size={14} className="at-risk-step-arrow" aria-hidden="true" />}
            <span className="at-risk-step-body">
              <span className="at-risk-step-value">{step.value.toLocaleString()}</span>
              <span className="at-risk-step-label">{step.label}</span>
              {step.note && <span className="at-risk-step-note">{step.note}</span>}
            </span>
          </li>
        ))}
      </ol>

      {revenueShare != null && (
        <p className="at-risk-money">
          Together these {belowCount} products earned <strong>{pct(revenueShare)}</strong> of{' '}
          {abcMonth ? `${abcMonth} ` : 'the month’s '}revenue
          {revenuePesos != null && <> (about <strong>{formatCompactPesos(revenuePesos)}</strong>)</>}.
        </p>
      )}

      <div className="at-risk-table-wrap" tabIndex={0}>
        <table className="at-risk-table">
          <thead>
            <tr>
              <th scope="col" className="at-risk-col-product">Product</th>
              <th scope="col">
                Stock (pieces)
                {countDay && <span className="at-risk-th-sub">counted {countDay}</span>}
              </th>
              <th scope="col">
                Safety stock (pieces)
                {planLabel && <span className="at-risk-th-sub">{planLabel}</span>}
              </th>
              <th scope="col">
                Short by (pieces)
                <span className="at-risk-th-sub">safety stock − stock</span>
              </th>
              <th scope="col">
                Suggested order (pieces)
                {planLabel && <span className="at-risk-th-sub">{planLabel}</span>}
              </th>
              <th scope="col">
                Revenue share (%)
                {abcMonth && <span className="at-risk-th-sub">of {abcMonth} revenue</span>}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.sku_id || item.product_name}>
                <td className="at-risk-col-product">
                  <ProductName
                    name={item.product_name}
                    code={item.sku_id}
                    onOpen={item.sku_id && onOpenProduct ? () => onOpenProduct(item.sku_id) : undefined}
                    openLabel="Open in the order plan"
                  />
                </td>
                <td>{formatUnits(item.current_stock)}</td>
                <td>{formatUnits(item.ss_i)}</td>
                <td className="at-risk-short">{formatUnits(item.short_by)}</td>
                <td>{item.order_qty == null ? '—' : formatUnits(item.order_qty)}</td>
                <td>{pct(item.revenue_share, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="at-risk-footer">
        <p className="at-risk-footnote">
          Click a product to open it in the order plan. Most revenue first.
        </p>
        <div className="at-risk-actions">
          <button type="button" className="at-risk-btn" onClick={onClose}>Close</button>
          <button type="button" className="at-risk-btn is-primary" onClick={onOpenPlan}>
            Open the order plan <ArrowRight size={14} aria-hidden="true" />
          </button>
        </div>
      </div>
    </Modal>
  );
};

export default AtRiskProductsModal;
