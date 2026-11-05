// The review drawer (2026-11-02): one recommendation in a side panel, opened from
// its product name, its Review order action or a ?sku= link. It replaces the
// detail window (ReorderModal) and keeps all of what that said.
//
// It works nothing out and decides nothing: the figures are the row's own, and
// the buttons are the actions utils/reorderView.js rowActions gave the row, the
// same list the table offers. The page runs them through the same handlers and
// their usual dialogs, and the server checks every request.
//
// Story #80, "why was this recommended": the LP objective weights are fixed (w1
// cost, w2 service level, w3 storage cost), so the weight split itself is real
// config, not per-SKU fabrication. The figures come from GET /recommendations'
// lp_model (backend/lp_cycle.py, pinned to analytics/optimization/lp.py by
// tests), not constants retyped here. The page says "about 9 times in 10 (a 90%
// service level)" and keeps Z behind a "?" (Technical Adviser, 2 Oct 2026: no
// unexplained jargon).
//
// Colour matches the Dashboard's own cost/service level/storage priority bars
// (LP_PRIORITY_ROWS in Charts.jsx) one-for-one via CHART_COLORS.lpWeight — ONE
// model-output indigo for all three: they are co-equal weights of a single
// solver objective, not three categories, and the row labels carry identity.
import React from 'react';
import { AlertTriangle, ArrowRight, ChevronDown, Info, X } from 'lucide-react';
import Modal from './Modal';
import SkuDemandPatternPanel from './SkuDemandPatternPanel';
import InfoTip from './InfoTip';
import { ReviewBadge } from './PendingCards';
import { TierChip } from './TierBasisLabel';
import { formatDate, formatMonth } from '../utils/formatDate';
import { formatCoverDays, formatUnits } from '../utils/formatNumber';
import {
  COVER_BASIS_NOTE, MONTH_TOTAL_NOTE, NO_SALES_FORECAST_NOTE, forecastsNoSales, noOrderReason, ordersNothing,
  projectedLabel, projectedNote, revenueShareBasis,
} from '../utils/reorderView';
import { REVIEW_REASON_TEXT } from '../utils/reviewReasons';
import { URGENCY_HOVER, getUrgencyBadge } from '../utils/urgency';
import { CHART_COLORS } from '../theme/colors';
import './ReorderReviewDrawer.css';

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

// "9 times in 10" from the served service level (90), never retyped.
const timesInTen = (pct) => (pct % 10 === 0 ? `${pct / 10} times in 10` : `${pct} times in 100`);

const Figure = ({ label, tip, value, sub }) => (
  <div className="reorder-drawer-figure">
    <dt>{label}{tip}</dt>
    <dd>{value}</dd>
    {sub && <dd className="reorder-drawer-figure-sub">{sub}</dd>}
  </div>
);

const Warning = ({ icon = 'warn', children }) => (
  <li className={`reorder-drawer-warning${icon === 'info' ? ' is-info' : ''}`}>
    {icon === 'info' ? <Info size={15} aria-hidden="true" /> : <AlertTriangle size={15} aria-hidden="true" />}
    <span>{children}</span>
  </li>
);

// `periods`: the dates the page read its figures at (GET /recommendations'
// label_context), so each figure here names its period as the table's headers do.
// `projectedCount`: the stock_counts entry when the plan started from a projection.
// `countFlag`: the opening count's reviewed note, when it has one.
// `actions`: rowActions' answer for this row; onAction(id) runs one.
const ReorderReviewDrawer = ({
  isOpen, onClose, data, brand, principal, lpModel, periods = {}, projectedCount, countFlag, actions, onAction, openRequest, requestNote, onOpenForecast,
}) => {
  if (!isOpen || !data) return null;
  const plan = data.planningCycleDate ? `${formatMonth(data.planningCycleDate)} plan` : 'this plan';
  let countLabel = 'latest count';
  if (projectedCount) countLabel = projectedLabel(projectedCount);
  else if (periods.stockCountDate) countLabel = `counted ${formatDate(periods.stockCountDate)}`;
  else if (periods.stockPeriod) countLabel = `${formatMonth(periods.stockPeriod)} count`;
  const coverSales = periods.coverSalesStart && periods.coverSalesEnd
    ? `${formatMonth(periods.coverSalesStart)} – ${formatMonth(periods.coverSalesEnd)}`
    : null;
  const weightRows = objectiveWeights(lpModel);
  const inputs = lpModel?.inputs || {};
  // 'aggregate' (the placeholder) makes the 3-week rule its own stage in
  // deciding a cut; 'per-sku' folds it into each target instead.
  const coverRuleDecides = inputs.cover_rule !== 'per-sku';

  // Every action the row has but the drawer's own: it is already open.
  const buttons = [actions?.primary, ...(actions?.secondary || [])]
    .filter((a) => a && a.id !== 'review_order');
  const emphasised = actions?.primary?.id;
  const noOrder = actions?.state === 'no_order';
  const canSetQuantity = buttons.some((a) => a.id === 'quantity');

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      labelledBy="reorder-drawer-title"
      overlayClassName="reorder-drawer-overlay"
      containerClassName="reorder-drawer"
    >
      <header className="reorder-drawer-head">
        <div className="reorder-drawer-heading">
          <h3 className="reorder-drawer-title" id="reorder-drawer-title">{data.product}</h3>
          <p className="reorder-drawer-code">{data.sku}{brand ? ` · ${brand}` : ''}</p>
          <div className="reorder-drawer-badges">
            <TierChip tier={data.tier} tierPeriod={data.tierPeriod} isCurrent={data.tierIsCurrent} anchor={String(data.planningCycleDate || '').slice(0, 7)} />
            <span className={getUrgencyBadge(data.urgency)} title={URGENCY_HOVER[data.urgency]}>{data.urgency}</span>
            <ReviewBadge reason={data.reviewFlag} />
            {openRequest && (
              <span className="pill reorder-request-pill">
                {openRequest.kind === 'dismissal' ? 'Dismissal requested' : 'Pending approval'}
              </span>
            )}
            {data.actionStatus && (
              <span className={`pill ${data.actionStatus === 'ACCEPTED' ? 'pill-planned' : 'pill-neutral'}`}>{data.actionStatus}</span>
            )}
          </div>
        </div>
        <button type="button" className="reorder-drawer-close" onClick={onClose} aria-label="Close the review panel">
          <X size={18} aria-hidden="true" />
        </button>
      </header>

      <div className="reorder-drawer-body">
        {/* The figure to act on first; the rest of the panel explains it. */}
        <section className="reorder-drawer-order" aria-label="Suggested order">
          <span className="reorder-drawer-order-label">Suggested order · {plan}</span>
          <span className="reorder-drawer-order-qty">{formatUnits(data.orderQty)} <small>pieces</small></span>
          {data.cases?.order && <span className="reorder-drawer-order-cases">{data.cases.order}</span>}
          {data.planQty != null && data.planQty !== data.orderQty && (
            <span className="reorder-drawer-order-cases">Accepted: {formatUnits(data.planQty)} pieces</span>
          )}
          {!ordersNothing(data) && <span className="reorder-drawer-order-note">{MONTH_TOTAL_NOTE}</span>}
        </section>

        {(data.needsReview || forecastsNoSales(data) || data.stockNotInCount || data.stock == null || openRequest || data.shortUnits > 0 || actions?.state === 'what_if' || noOrder || projectedCount) && (
          <ul className="reorder-drawer-warnings">
            {data.needsReview && (
              <Warning>
                Flagged for review: {data.reviewReasons.map((r) => REVIEW_REASON_TEXT[r] || r).join('; ') || 'likely large miss'}. A
                large miss is likely, so check this quantity before ordering.
              </Warning>
            )}
            {forecastsNoSales(data) && <Warning>{NO_SALES_FORECAST_NOTE}</Warning>}
            {data.stockNotInCount && (
              <Warning>
                This SKU is not in the opening stock count, so the plan treats it as 0 on hand. The 0 was never counted:
                confirm the available stock before ordering.
              </Warning>
            )}
            {data.stock == null && (
              <Warning>No stock figure in pieces for this SKU{data.stockBlockedReason ? `: ${data.stockBlockedReason}` : ''}.</Warning>
            )}
            {data.shortUnits > 0 && (
              <Warning>
                Cut to fit the supplier allocation: this order is {formatUnits(data.shortUnits)} pieces short, and ends the
                month that far below its target.
              </Warning>
            )}
            {projectedCount && <Warning icon="info">{projectedNote(projectedCount)}</Warning>}
            {noOrder && (
              <Warning icon="info">
                {noOrderReason(data, { countLabel, countFlag })}
                {canSetQuantity && ' You can still set a quantity if this looks wrong.'}
              </Warning>
            )}
            {openRequest && <Warning icon="info">{requestNote}</Warning>}
            {actions?.state === 'what_if' && (
              <Warning icon="info">A what-if row from the preview, never saved, so there is nothing to decide.</Warning>
            )}
          </ul>
        )}

        <dl className="reorder-drawer-figures">
          <Figure
            label="Opening stock"
            value={data.stock != null ? `${formatUnits(data.stock)} pieces` : '—'}
            sub={data.stockNotInCount
              ? 'Not in stock count, treated as 0'
              : data.stock == null ? null : `${countLabel}${data.cases?.stock ? ` · ${data.cases.stock}` : ''}`}
          />
          <Figure label="Safety stock" value={`${formatUnits(data.safetyStock)} pieces`} sub={plan} />
          <Figure
            label="Target stock"
            value={`${formatUnits(data.rop)} pieces`}
            sub={`${plan}${data.cases?.target ? ` · ${data.cases.target}` : ''}`}
          />
          {data.onOrderQty != null && (
            <Figure label="On order" value={`${formatUnits(data.onOrderQty)} pieces`} sub="not yet arrived; never subtracted from the order" />
          )}
          <Figure
            label="Cover (days)"
            tip={<InfoTip label="About cover">{data.daysOfCover != null ? COVER_BASIS_NOTE : (data.coverReason || COVER_BASIS_NOTE)}</InfoTip>}
            value={data.daysOfCover != null ? formatCoverDays(data.daysOfCover) : '—'}
            sub={`stock ${countLabel}${coverSales ? ` ÷ sales ${coverSales}` : ''}`}
          />
          <Figure
            label="Forecast"
            value={data.forecast != null ? `${formatUnits(data.forecast)} pieces` : '—'}
            sub={data.planningCycleDate ? formatMonth(data.planningCycleDate) : null}
          />
          <Figure label="Revenue share" value={data.revenueShare != null ? `${(data.revenueShare * 100).toFixed(2)}%` : '—'} sub={periods.abcPeriod ? revenueShareBasis(data.principal, formatMonth(periods.abcPeriod)) : null} />
          <Figure label="Impact rank" value={data.rank != null ? `#${data.rank}` : 'Unranked'} sub={`of the ${plan}`} />
        </dl>

        {/* The product's own page: its sales history, the forecast and how that
            was made. Passed only with forecast.view. */}
        {onOpenForecast && (
          <button type="button" className="reorder-drawer-link" onClick={() => onOpenForecast(data.sku)}>
            See this product&apos;s sales history and forecast
            <ArrowRight size={13} aria-hidden="true" />
          </button>
        )}

        {/* Demand pattern (sku_traits / sku_segment). Ahead of the LP weights
            on purpose: the weights are the same for every SKU, this is the part
            that is about THIS one. */}
        <div className="reorder-pattern-section">
          <SkuDemandPatternPanel skuId={data.sku} principal={principal} compact />
        </div>

        {/* How the LP arrived at this quantity — Story #80 */}
        <details className="reorder-why-section">
          <summary className="reorder-section-title">
            How this recommendation was made
            <ChevronDown size={16} aria-hidden="true" />
          </summary>
          {/* The 2026-09-30 model (analytics/optimization/lp.py, solved in
              stages): order up to a target, net of stock on hand. Only a
              short allocation forces a cut, taken from the rest of the
              target first and this month's demand last; within the part
              being cut, the aggregate 3-week rule (stage 2) and then the
              weights (stage 3) pick who comes up short. */}
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
            {' '}plus safety stock
            {lpModel?.service_level_pct != null && (
              <>
                , set to cover demand about {timesInTen(lpModel.service_level_pct)} (a {lpModel.service_level_pct}% service level)
                {lpModel.z_score != null && (
                  <InfoTip label="About the service level">
                    {`Safety stock = ${lpModel.z_score} (Z, the normal-curve value for ${lpModel.service_level_pct}%) × how much monthly sales swing, scaled to the review and delivery days.`}
                  </InfoTip>
                )}
              </>
            )}. The cycle&apos;s
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
          {/* Methods that set this quantity, said beside it (Technical Adviser,
              2 Oct 2026; 2026-10-22): the reliability check that admits a
              product to the plan (MASE < 1, a team decision, DEC-46, not
              confirmed by SSM or the adviser), the
              safety-stock scaling (lp_model.safety_stock_assumption) and the
              weights (analytics/params.py LP_WEIGHTS, team-asserted). */}
          <p className="reorder-why-note">
            A product enters the plan only if it is Class A and its forecast&apos;s test error is below the average
            month-to-month change in its sales before the test months (a reliability check the team adopted, not
            confirmed by SSM or the adviser).
            {lpModel?.safety_stock_assumption && (
              <>
                {' '}Its safety stock scales month-to-month swings in sales down to the review and delivery days,
                which assumes one day&apos;s sales don&apos;t affect the next: an assumption pending adviser
                confirmation.
                <InfoTip label="The safety stock formula">{lpModel.safety_stock_assumption}</InfoTip>
              </>
            )}
            {weightRows.length > 0 && ' The weights above are a team setting; source not yet confirmed.'}
          </p>
        </details>
      </div>

      {buttons.length > 0 && (
        <footer className="reorder-drawer-actions">
          {buttons.map((action) => (
            <button
              key={action.id}
              type="button"
              className={`reorder-drawer-action${action.id === emphasised ? ' is-primary' : ''}`}
              disabled={action.disabled}
              onClick={() => onAction(action.id)}
            >
              {action.label}
            </button>
          ))}
        </footer>
      )}
    </Modal>
  );
};

export default ReorderReviewDrawer;
