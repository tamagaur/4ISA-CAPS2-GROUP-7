import React from 'react';
import { History, RotateCcw } from 'lucide-react';
import EmptyState from './ui/EmptyState';
import { formatWhen, loadedStateWord, monthName } from '../utils/monthlyBatchSteps';

const pieces = (n) => Math.round(n).toLocaleString('en-US');
const planText = (plan) => (plan ? `${monthName(plan.cycle)}: ${plan.rows.toLocaleString('en-US')} products, ${pieces(plan.pieces)} pieces` : 'No plan written');

// The months loaded onto the system, newest first, and (for an admin) the way back. Each rollback point is the system as it was before that month, so
// rolling a month back also removes the months loaded after it. The words are facts about the input: the sales of these months are generated.
const LoadedMonths = ({ loaded, released = [], max, canRollback, busy, onRollback }) => {
  if (!loaded?.length && !released?.length) {
    return (
      <EmptyState icon={History} title="No month has been loaded yet" compact>
        A month appears here once its sales file is loaded, with the plan it produced.
      </EmptyState>
    );
  }
  return (
    <div className="mb-loaded">
      <p className="mb-small">
        The sales of these months are generated: SSM has not sent their files. Their forecasts and plans rest on them, and forecast error is not shown for them.
      </p>
      <div className="mb-table-wrap">
        <table className="mb-table">
          <thead>
            <tr>
              <th scope="col">Month</th>
              <th scope="col">Status</th>
              <th scope="col">Plan it produced</th>
              <th scope="col">Loaded</th>
              {canRollback && <th scope="col">Roll back</th>}
            </tr>
          </thead>
          <tbody>
            {[...loaded].reverse().map((entry) => (
              <tr key={entry.month}>
                <th scope="row">{monthName(entry.month)}</th>
                <td>{loadedStateWord(entry.state)}</td>
                <td>{planText(entry.plan)}</td>
                <td>{formatWhen(entry.loaded_at || entry.taken_at) || 'n/a'}{entry.loaded_by ? ` by ${entry.loaded_by}` : ''}</td>
                {canRollback && (
                  <td>
                    <span className="mb-small">
                      Back to before {monthName(entry.month)}: {entry.restores_to?.rows != null
                        ? `${entry.restores_to.rows.toLocaleString('en-US')} products, ${pieces(entry.restores_to.pieces)} pieces`
                        : 'its earlier plan'}
                    </span>
                    <button type="button" className="btn btn-secondary btn-sm mb-rollback-btn" disabled={busy} onClick={() => onRollback(entry.month)}>
                      <RotateCcw size={14} aria-hidden="true" />
                      Roll back {monthName(entry.month)}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canRollback && (
        <p className="mb-small">
          Rolling a month back puts the system back to how it was before that month was loaded, and removes any month loaded after it. Anything decided on the
          Reorder page since is undone too. The last {max} loads can be rolled back{released?.length ? `; ${released.map(monthName).join(', ')} can no longer be` : ''}.
        </p>
      )}
    </div>
  );
};

export default LoadedMonths;
