// The heading and controls above the Reorder table: quick filters, the Filter
// menu and the search box. They only choose which rows are listed
// (utils/reorderView.js filterRows); the KPI cards and quantities don't move.
import React from 'react';
import { AlertTriangle, ClipboardList, Filter, Search, X } from 'lucide-react';
import ReorderActionMenu from './ReorderActionMenu';

const CHIPS = [
  { view: 'critical', label: 'Critical', Icon: AlertTriangle },
  { view: 'all', label: 'All SKUs' },
  { view: 'review', label: 'Needs Review' },
];

const MENU_VIEWS = [
  { view: 'urgent', label: 'Urgent' },
  { view: 'planned', label: 'Planned' },
  { view: 'not_in_count', label: 'Not in stock count' },
];

const ReorderTableControls = ({ view, onViewChange, counts, query, onQueryChange }) => {
  const menuActive = MENU_VIEWS.find((m) => m.view === view);
  return (
    <div className="reorder-table-head">
      <div className="ui-card-head reorder-table-title">
        <span className="icon-tile" aria-hidden="true"><ClipboardList size={20} /></span>
        <div className="ui-card-head-text">
          <h3>Recommended Orders</h3>
          <p>Every suggested order, most urgent first.</p>
        </div>
      </div>

      <div className="reorder-chips" role="group" aria-label="Show recommendations">
        {CHIPS.map(({ view: chip, label, Icon }) => (
          <button
            key={chip}
            type="button"
            className={`reorder-chip${view === chip ? ' is-active' : ''}${chip === 'critical' ? ' is-critical' : ''}`}
            aria-pressed={view === chip}
            onClick={() => onViewChange(chip)}
          >
            {Icon && <Icon size={14} aria-hidden="true" />}
            {label}
            <span className="reorder-chip-count">· {(counts[chip] ?? 0).toLocaleString()}</span>
          </button>
        ))}
      </div>

      <div className="reorder-table-tools">
        <label className="reorder-search">
          <Search size={15} aria-hidden="true" />
          <span className="visually-hidden">Search product, SKU, or brand</span>
          <input
            type="search"
            value={query}
            placeholder="Search product, SKU, or brand"
            onChange={(e) => onQueryChange(e.target.value)}
          />
          {query && (
            <button type="button" className="reorder-search-clear" aria-label="Clear the search" onClick={() => onQueryChange('')}>
              <X size={14} aria-hidden="true" />
            </button>
          )}
        </label>
        <ReorderActionMenu
          label={menuActive ? `Filter: ${menuActive.label}` : 'Filter'}
          buttonClassName={`reorder-filter-btn${menuActive ? ' is-active' : ''}`}
          buttonContent={(
            <>
              <Filter size={14} aria-hidden="true" />
              {menuActive ? menuActive.label : 'Filter'}
            </>
          )}
          items={MENU_VIEWS.map(({ view: option, label }) => ({
            key: option,
            label: `${label} (${(counts[option] ?? 0).toLocaleString()})`,
            checked: view === option,
            onSelect: () => onViewChange(view === option ? 'all' : option),
          }))}
        />
      </div>
    </div>
  );
};

export default ReorderTableControls;
