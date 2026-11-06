// The synthetic demonstration's order plans (schema demo; CLAUDE.md rule 2), shown only when the Topbar's
// "Include synthetic data" switch is on AND the server's DM_DEMO_ENABLED is on, because only then does the API send
// the block this reads (GET /recommendations `demo_unilever` / `order_plan`, GET /dashboard `demonstration`).
//
// Two plans, one component:
//   Unilever  demo forecast + REAL stock and cost (demo.unilever_sku_lp), listed beside, never inside, the real
//             recommendations.
//   Del Monte generated demand AND generated stock (demo.dm_category_lp), per product category.
// Nothing here can be accepted, dismissed or ordered, and every part of the card says it is synthetic.
import React, { useMemo, useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { SyntheticTag } from './DemoForecasts';
import { isMissing, NOT_COLLECTED } from '../utils/formatters';
import './DemoOrderPlan.css';

const COLLAPSED_ROWS = 10;
const DM_UNIT_NOTE = "Quantities are in Del Monte's own unit, which SSM has not confirmed.";

const titleCase = (s) => String(s).toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
const qty = (v) => {
  if (isMissing(v)) return NOT_COLLECTED;
  return Math.abs(v) < 10 ? Number(v).toFixed(1) : Math.round(v).toLocaleString('en-US');
};
const monthLabel = (period) => {
  if (!period) return '';
  const [y, m] = String(period).slice(0, 7).split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
};

const COPY = {
  unilever: {
    title: 'Sample-data order plan: Unilever SKUs',
    lead: "Demonstration only. This plan uses the sample-data forecast with Unilever's real stock count and cost. "
      + 'It is separate from the real recommendations above, cannot be accepted or dismissed, and is never used for SSM’s orders.',
    keyHeader: 'SKU',
    key: (it) => it.sku_id,
  },
  delmonte: {
    title: 'Sample-data order plan: Del Monte categories',
    lead: 'Demonstration only. Del Monte has no real forecast, so this plan rests on a sample-data forecast and sample-data '
      + 'stock, two generated layers. It cannot be accepted, dismissed or ordered, and is never used for SSM’s orders.',
    keyHeader: 'Category',
    key: (it) => titleCase(it.category),
  },
};

export const DemoOrderPlanCard = ({ plan, kind, deadStock = null, id }) => {
  const [showAll, setShowAll] = useState(false);
  const copy = COPY[kind];
  const items = useMemo(
    () => (plan?.available ? [...(plan.items || [])].sort((a, b) => (b.order_qty ?? 0) - (a.order_qty ?? 0)) : []),
    [plan],
  );
  if (!plan || !copy) return null;

  const shown = showAll ? items : items.slice(0, COLLAPSED_ROWS);
  const period = items[0]?.period;
  const totalOrder = items.reduce((s, it) => s + (it.order_qty ?? 0), 0);
  const ordering = items.filter((it) => (it.order_qty ?? 0) > 0).length;

  return (
    <section className="demo-plan" id={id} aria-label={copy.title}>
      <div className="demo-plan-head">
        <SyntheticTag />
        <h4 className="demo-plan-title">{copy.title}</h4>
      </div>
      <p className="demo-plan-lead">{copy.lead}</p>

      {!plan.available ? (
        <p className="demo-plan-empty">
          <FlaskConical size={13} aria-hidden="true" /> No sample-data order plan has been generated yet
          {plan.reason ? `: ${plan.reason}` : '.'}
        </p>
      ) : (
        <>
          <p className="demo-plan-summary">
            {period ? `${monthLabel(period)} · ` : ''}
            {items.length} {kind === 'delmonte' ? 'categories' : 'SKUs'} planned, {ordering} with an order,{' '}
            <strong>{qty(totalOrder)}</strong> {kind === 'delmonte' ? 'units' : 'pieces'} in total (sample data).
          </p>
          <div className="demo-plan-table-wrap">
            <table className="demo-plan-table">
              <caption className="visually-hidden">{copy.title}: sample data, for demonstration only</caption>
              <thead>
                <tr>
                  <th scope="col">{copy.keyHeader}</th>
                  <th scope="col" className="num">Forecast (sample data)</th>
                  <th scope="col" className="num">{kind === 'delmonte' ? 'Stock (sample data)' : 'Stock on hand (real count)'}</th>
                  <th scope="col" className="num">Safety stock</th>
                  <th scope="col" className="num">Target stock</th>
                  <th scope="col" className="num">Sample-data order</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((it) => (
                  <tr key={kind === 'delmonte' ? it.category : it.sku_id}>
                    <td>{copy.key(it)}</td>
                    <td className="num">{qty(it.forecast_quantity)}</td>
                    <td className="num">{qty(it.stock_on_hand)}</td>
                    <td className="num">{qty(it.safety_stock)}</td>
                    <td className="num">{qty(it.target_stock)}</td>
                    <td className="num demo-plan-order">{qty(it.order_qty)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {items.length > COLLAPSED_ROWS && (
            <button type="button" className="demo-plan-toggle" onClick={() => setShowAll((v) => !v)} aria-expanded={showAll}>
              {showAll ? 'Show the top 10 only' : `Show all ${items.length}, largest order first`}
            </button>
          )}
          {kind === 'delmonte' && <p className="demo-plan-note">{DM_UNIT_NOTE}</p>}
          {plan.demonstration_note && (
            <details className="demo-plan-details">
              <summary>How this sample-data plan was made</summary>
              <p>{plan.demonstration_note}</p>
            </details>
          )}
        </>
      )}

      {kind === 'delmonte' && deadStock && (
        <div className="demo-plan-dead">
          <h5>Dead stock (sample data)</h5>
          {deadStock.available ? (
            <>
              <p>
                Of {Object.values(deadStock.counts || {}).reduce((a, b) => a + b, 0)} generated categories:{' '}
                <strong>{deadStock.counts?.dead_stock ?? 0}</strong> dead stock,{' '}
                <strong>{deadStock.counts?.critical ?? 0}</strong> critically low,{' '}
                <strong>{deadStock.counts?.in_stock ?? 0}</strong> in stock. The stock itself is generated.
              </p>
              {deadStock.demonstration_note && (
                <details className="demo-plan-details">
                  <summary>How dead stock is judged here</summary>
                  <p>{deadStock.demonstration_note}</p>
                </details>
              )}
            </>
          ) : (
            <p className="demo-plan-empty">Not available{deadStock.reason ? `: ${deadStock.reason}` : '.'}</p>
          )}
        </div>
      )}
    </section>
  );
};

export default DemoOrderPlanCard;
