// The Reorder page's Act Now card (2026-11-09, adviser feedback): one card for
// every top seller that needs someone now, in priority order, so no figure reads as
// a separate pile to add to another. The groups come from utils/reorderView.js
// actNowGroups, which puts each SKU in one group only; the card only shows them.
// Each tile leads to its SKUs: the first two filter the table, the third and the
// grey line open the "Not in This Plan" list cut to theirs.
import React from 'react';
import { ArrowRight } from 'lucide-react';
import InfoTip from './InfoTip';
import { BELOW_TARGET, MANUAL_ORDER } from '../labels';
import { belowTargetHint, checkManuallyNote, confirmLine } from '../utils/reorderView';

const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;

// planLabel: "Mar 2026 plan". countHeader: "Stock counted Mar 2, 2026", or how the
// opening stock was obtained when there is no counted day.
const ReorderActNowCard = ({
  groups, planLabel, countHeader, noStockFigureCount = 0, onFilterTable, onOpenNotPlanned,
}) => {
  const { orderFirst, orderNow, checkManually, confirm, total } = groups;
  // Tiles 1 and 3 say "Out of stock" without "(not counted)": each hint says why
  // (the table, the drawer and the Reference Guide keep the longer label).
  const tiles = [
    {
      key: 'orderFirst',
      tone: 'is-first',
      label: 'Out of stock',
      n: orderFirst.length,
      chip: 'Order ready · do first',
      hint: 'Not in the stock count, so treated as 0.',
      link: `Review ${plural(orderFirst.length, 'order')}`,
      onClick: () => onFilterTable('not_in_count'),
    },
    {
      key: 'orderNow',
      tone: 'is-now',
      label: BELOW_TARGET,
      n: orderNow.length,
      chip: 'Order ready',
      hint: belowTargetHint(orderNow),
      link: `Review ${plural(orderNow.length, 'order')}`,
      onClick: () => onFilterTable('below_target'),
    },
    {
      key: 'checkManually',
      tone: 'is-manual',
      label: 'Out of stock',
      n: checkManually.length,
      chip: MANUAL_ORDER,
      hint: checkManuallyNote(checkManually),
      link: `See the ${plural(checkManually.length, 'product')}`,
      onClick: () => onOpenNotPlanned('checkManually'),
    },
  ];
  const grey = confirmLine(confirm);
  const bar = tiles.filter((tile) => tile.n > 0);

  return (
    <section className="reorder-actnow" aria-labelledby="reorder-actnow-title">
      <div className="reorder-actnow-head">
        <div className="reorder-actnow-heading">
          <span className="reorder-actnow-eyebrow">
            Act now
            <InfoTip label="About Act now">
              Each top seller is counted once, in the first tile that fits it. The first two are in the plan and still await
              a decision, so they go down as orders are accepted or dismissed. The third is not in the plan, so it has no
              suggested order: check its stock and order by hand if needed. Top sellers that may be discontinued are listed
              under the tiles and are not in the total.
              {noStockFigureCount > 0
                && ` ${noStockFigureCount.toLocaleString()} more in the plan have no stock figure in pieces (NO DATA), so they are not ranked here.`}
            </InfoTip>
          </span>
          <h3 className="reorder-actnow-title" id="reorder-actnow-title">
            {total > 0
              ? `${total.toLocaleString()} top seller${total === 1 ? ' needs' : 's need'} attention`
              : 'No top sellers need action right now.'}
          </h3>
        </div>
        <p className="reorder-actnow-period">
          {planLabel}
          {countHeader && <><br />{countHeader}</>}
        </p>
      </div>

      {total > 0 && (
        <>
          {/* The three groups in proportion; the tiles below carry the figures. */}
          <div
            className="reorder-actnow-bar"
            role="img"
            aria-label={tiles.map((tile) => `${tile.n} ${tile.label.toLowerCase()}, ${tile.chip.toLowerCase()}`).join('; ')}
          >
            {bar.map((tile) => <span key={tile.key} className={tile.tone} style={{ flexGrow: tile.n }} />)}
          </div>

          <ul className="reorder-actnow-tiles">
            {tiles.map((tile) => (
              <li key={tile.key} className={`reorder-actnow-tile ${tile.tone}${tile.n === 0 ? ' is-empty' : ''}`}>
                <span className="reorder-actnow-label">
                  <span className="reorder-actnow-dot" aria-hidden="true" />
                  {tile.label}
                </span>
                <span className="reorder-actnow-count">{tile.n.toLocaleString()}</span>
                <span className="reorder-actnow-chip">{tile.chip}</span>
                <span className="reorder-actnow-hint">{tile.hint}</span>
                {tile.n > 0 && (
                  <button type="button" className="reorder-actnow-link" onClick={tile.onClick}>
                    {tile.link} <ArrowRight size={13} aria-hidden="true" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {grey && (
        <button type="button" className="reorder-actnow-grey" onClick={() => onOpenNotPlanned('confirm')}>
          {grey}
        </button>
      )}
    </section>
  );
};

export default ReorderActNowCard;
