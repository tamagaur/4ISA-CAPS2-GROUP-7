import React from 'react';
import SectionLede from './ui/SectionLede';
import { X, ArrowRight } from 'lucide-react';
import Modal from './Modal';
import SkuDemandPatternPanel from './SkuDemandPatternPanel';
import InfoTip from './InfoTip';
import ProductName from './ProductName';
import { formatDate, formatMonth } from '../utils/formatDate';
import { formatUnits } from '../utils/formatNumber';
import { CHART_COLORS } from '../theme/colors';
import './ReorderModal.css';

// Story #80: "why was this recommended" — the LP objective weights are fixed
// (w1 cost, w2 service level, w3 storage cost), so the weight split itself is
// real config, not per-SKU fabrication. The figures come from GET
// /recommendations' lp_model (backend/lp_cycle.py, pinned to
// analytics/optimization/lp.py by tests), not constants retyped here: until
// 2026-09-29 this listed "Service level ≥ 95%" and "Warehouse capacity" as
// weights, where the solver uses a 90% service level (Z = 1.28) and w3 is
// storage cost.
//
// Colour matches the Dashboard's own cost/service level/storage priority
// bars (LP_PRIORITY_ROWS in Charts.jsx) one-for-one via
// CHART_COLORS.lpWeight — ONE model-output indigo for all three: they are
// co-equal weights of a single solver objective, not three categories,
// and the row labels carry identity (see theme/colors.js).
const objectiveWeights = (lpModel) => {
  const w = lpModel?.weights;
  if (!w) return [];
  const pct = (v) => Math.round(v * 100);
  return [
    { key: 'cost', label: 'Cost', weight: pct(w.cost), color: CHART_COLORS.lpWeight },
    {
      key: 'service',
      label: lpModel.service_level_pct != null ? `Service level (${lpModel.service_level_pct}% target)` : 'Service level',
      weight: pct(w.service_level),
      color: CHART_COLORS.lpWeight,
    },
    { key: 'storage', label: 'Storage cost', weight: pct(w.storage), color: CHART_COLORS.lpWeight },
  ];
};

// Stock is valued at purchase cost and sales at selling price, so cover
// reads a little short (backend/routers/recommendations.py days_of_cover).
const COVER_BASIS_NOTE =
  'Stock at last purchase price (₱) ÷ average daily sales value (₱/day over the last 3 sales months; a month with no sales counts as 0). Cost against selling price, so cover reads slightly short.';

// `periods` — the dates the page read its figures at (GET /recommendations'
// label_context, passed through by ReorderRecommendations), so each figure
// here names its period the way the table's headers do.
const ReorderModal = ({ isOpen, onClose, data, principal, lpModel, periods = {}, onOpenForecast }) => {
  if (!isOpen || !data) return null;
  const plan = data.planningCycleDate ? `${formatMonth(data.planningCycleDate)} plan` : 'this plan';
  const countLabel = periods.stockCountDate
    ? `counted ${formatDate(periods.stockCountDate)}`
    : periods.stockPeriod ? `${formatMonth(periods.stockPeriod)} count` : 'latest count';
  const coverSales = periods.coverSalesStart && periods.coverSalesEnd
    ? `${formatMonth(periods.coverSalesStart)} – ${formatMonth(periods.coverSalesEnd)}`
    : null;
  const weightRows = objectiveWeights(lpModel);
  const inputs = lpModel?.inputs || {};
  // 'aggregate' (the placeholder) makes the 3-week rule its own stage in
  // deciding a cut; 'per-sku' folds it into each target instead.
  const coverRuleDecides = inputs.cover_rule !== 'per-sku';

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      label="Reorder details"
      overlayClassName="reorder-modal-overlay"
      containerClassName="reorder-modal-card"
    >
        {/* Header */}
        <div className="reorder-modal-header">
          <div>
            {/* Name first, SKU code under it, as in the table. */}
            <h3 className="reorder-modal-title">
              <ProductName name={data.product} code={data.sku} />
            </h3>
            <SectionLede>Why this quantity</SectionLede>
            {/* Pieces, the LP's unit, with the rough case count beside it
                (worked out once on the row by ReorderRecommendations). */}
            <p className="reorder-modal-subtitle">
              Order <strong>{formatUnits(data.orderQty)}</strong> pieces
              {data.cases?.order ? ` (${data.cases.order})` : ''} for the {plan}. Below is how the order plan
              arrived at this suggestion.
            </p>
            {/* The product's own page: its sales history, the forecast and
                how that was made. Passed only with forecast.view. */}
            {onOpenForecast && (
              <button type="button" className="reorder-modal-link" onClick={() => onOpenForecast(data.sku)}>
                See this product&apos;s sales history and forecast
                <ArrowRight size={13} aria-hidden="true" />
              </button>
            )}
          </div>
          <button className="reorder-modal-close" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Data Grid — fields not already visible in the table row, plus
            the two ranking inputs so the "why is this #3" question is
            answerable here, and the target and opening stock with their
            case counts (the table shows those only on hover). */}
        <div className="reorder-modal-grid">
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">PLANNING CYCLE (MONTH)</span>
            <span className="reorder-grid-value">{formatMonth(data.planningCycleDate)}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">IMPACT RANK</span>
            <span className="reorder-grid-value">
              {data.rank != null ? `#${data.rank} of the ${plan}` : 'Unranked'}
            </span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">REVENUE SHARE (%)</span>
            <span className="reorder-grid-value">
              {data.revenueShare != null ? `${(data.revenueShare * 100).toFixed(2)}%` : '—'}
            </span>
            {periods.abcPeriod && <span className="reorder-grid-sub">of {formatMonth(periods.abcPeriod)} revenue</span>}
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">
              COVER (DAYS, ₱ BASIS)
              <InfoTip label="About cover">{data.daysOfCover != null ? COVER_BASIS_NOTE : (data.coverReason || COVER_BASIS_NOTE)}</InfoTip>
            </span>
            <span className="reorder-grid-value">
              {data.daysOfCover != null ? data.daysOfCover.toFixed(1) : '—'}
            </span>
            <span className="reorder-grid-sub">
              stock {countLabel}{coverSales ? ` ÷ sales ${coverSales}` : ''}
            </span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">TARGET STOCK (PIECES)</span>
            <span className="reorder-grid-value">{formatUnits(data.rop)} pieces</span>
            <span className="reorder-grid-sub">{plan}{data.cases?.target ? ` · ${data.cases.target}` : ''}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">OPENING STOCK (PIECES)</span>
            <span className="reorder-grid-value">
              {data.stock != null ? `${formatUnits(data.stock)} pieces` : '—'}
            </span>
            {data.stockNotInCount
              ? <span className="reorder-grid-sub">Not in the opening stock count — treated as 0, as the plan does</span>
              : data.stock == null
                ? data.stockBlockedReason && <span className="reorder-grid-sub">{data.stockBlockedReason}</span>
                : <span className="reorder-grid-sub">{countLabel}{data.cases?.stock ? ` · ${data.cases.stock}` : ''}</span>}
          </div>
        </div>

        {/* Demand pattern (sku_traits / sku_segment). Ahead of the LP
            weights on purpose: the weights are the same for every SKU,
            this is the part that is about THIS one. */}
        <div className="reorder-pattern-section">
          <SkuDemandPatternPanel skuId={data.sku} principal={principal} compact />
        </div>

        {/* How the LP arrived at this quantity — Story #80 */}
        <div className="reorder-why-section">
          <h4 className="reorder-section-title">How this recommendation was made</h4>
          {/* The 2026-09-30 model (analytics/optimization/lp.py, solved in
              stages): order up to a target, net of stock on hand. Only a
              short allocation forces a cut, taken from the rest of the
              target first and this month's demand last; within the part
              being cut, the aggregate 3-week rule (stage 2) and then the
              weights (stage 3) pick who comes up short. Until 2026-10-01
              this credited the weights alone, and said the 3-week rule held
              "across the whole warehouse" — it sums the planned SKUs only. */}
          <p className="reorder-why-intro">
            The order plan orders each SKU up to its target stock, net of what is already on hand. Only when the supplier
            allocation can&apos;t cover every SKU does it cut, taking the rest of the target first, then safety stock,
            and this month&apos;s demand last. Which SKUs take the cut is decided
            {coverRuleDecides
              ? <> first by SSM&apos;s {inputs.target_weeks ?? 3}-week stock rule (below), then by these weights:</>
              : <> by these weights:</>}
          </p>
          {/* Single 100%-stacked bar — these three weights are shares of one
              whole (they sum to 100%), so one composite bar is the correct
              part-to-whole form, not three independent progress tracks. */}
          <div className="reorder-weight-stack">
            <div className="reorder-weight-stack-track">
              {weightRows.map((obj) => (
                <div
                  key={obj.key}
                  className="reorder-weight-segment"
                  style={{ flex: `${obj.weight} 0 0%`, backgroundColor: obj.color }}
                  title={`${obj.label}: ${obj.weight}%`}
                />
              ))}
            </div>
            <div className="reorder-weight-legend">
              {weightRows.map((obj) => (
                <div className="reorder-weight-legend-item" key={obj.key}>
                  <span className="reorder-weight-swatch" style={{ backgroundColor: obj.color }} />
                  <span className="reorder-weight-legend-label">{obj.label}</span>
                  <span className="reorder-weight-legend-pct">{obj.weight}%</span>
                </div>
              ))}
            </div>
          </div>
          {/* One storage cost for every SKU makes the storage term the same
              whichever SKUs are cut (the total ordered is already fixed by
              then), so its 20% can't move a single piece. Said here so the
              bar above isn't read as three live levers. */}
          {inputs.storage_cost_per_unit != null && (
            <p className="reorder-why-caveat">
              Storage cost has no effect for now: its placeholder is the same
              ₱{Number(inputs.storage_cost_per_unit).toFixed(2)} a piece for every SKU, so it can&apos;t favour one
              over another.
            </p>
          )}
          <p className="reorder-why-note">
            Target stock = demand expected over the review period and delivery lead time
            {inputs.review_days != null && inputs.lead_days != null
              && <> ({inputs.review_days} + {inputs.lead_days} business days)</>}
            {' '}plus safety stock{lpModel?.z_score != null && <> at Z = {lpModel.z_score}</>}. The cycle&apos;s
            total order stays within the supplier allocation
            {inputs.allocation_pct != null && <> ({inputs.allocation_pct}% of last year&apos;s sales)</>} and the
            warehouse capacity.
            {coverRuleDecides
              ? <>
                  {' '}SSM&apos;s {inputs.target_weeks ?? 3}-week rule asks that the stock left at month end of the SKUs
                  in this plan — not the whole warehouse — be worth at least {inputs.target_weeks ?? 3} weeks of their
                  sales, at last purchase price; the plan keeps it where the allocation allows.
                </>
              : <> SSM&apos;s {inputs.target_weeks ?? 3}-week rule is built into each SKU&apos;s target stock as a floor.</>}
            {lpModel?.inputs_are_placeholders && ' These inputs are placeholders until SSM confirms them.'}
          </p>
        </div>
    </Modal>
  );
};

export default ReorderModal;
