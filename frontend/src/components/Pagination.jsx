import React from 'react';
import PageJump from './PageJump';

const DEFAULT_PAGE_SIZE_OPTIONS = [25, 50, 100];

// Shared pagination bar for every paginated table (SKU Management, ABC
// Classification, Audit Log). Previously each page had its own copy —
// SKU Management and ABC Classification had already drifted into an
// identical shape by convention, but Audit Log independently built a
// different one (Previous/Next text buttons + a full row of page-number
// buttons, no "Showing X–Y of Z" count, no rows-per-page control, a fixed
// 10-per-page). One component now, so "uniform" is enforced by there being
// only one implementation, not by three developers agreeing to copy each
// other correctly.
//
// onPageSizeChange is optional: a table with a fixed page size (there
// currently isn't one, but the prop stays optional rather than required)
// simply omits the rows-per-page control.
const Pagination = ({
  currentPage,
  totalPages,
  totalItems,
  pageSize,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  idPrefix,
}) => {
  if (totalItems === 0) return null;

  const firstRow = (currentPage - 1) * pageSize + 1;
  const lastRow = Math.min(currentPage * pageSize, totalItems);

  return (
    <div className="table-pagination-row">
      <span className="table-pagination-info">
        Showing {firstRow}–{lastRow} of {totalItems}
      </span>

      <div className="table-pagination-controls">
        <button
          className="table-pagination-btn"
          onClick={() => onPageChange(1)}
          disabled={currentPage === 1}
          aria-label="First page"
          title="First page"
        >
          «
        </button>
        <button
          className="table-pagination-btn"
          onClick={() => onPageChange(Math.max(1, currentPage - 1))}
          disabled={currentPage === 1}
          aria-label="Previous page"
        >
          Prev
        </button>
        <span className="table-pagination-page-label">
          Page {currentPage} of {totalPages}
        </span>
        <PageJump
          currentPage={currentPage}
          totalPages={totalPages}
          onGo={onPageChange}
          idPrefix={idPrefix}
        />
        <button
          className="table-pagination-btn"
          onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
          disabled={currentPage === totalPages}
          aria-label="Next page"
        >
          Next
        </button>
        <button
          className="table-pagination-btn"
          onClick={() => onPageChange(totalPages)}
          disabled={currentPage === totalPages}
          aria-label="Last page"
          title="Last page"
        >
          »
        </button>
      </div>

      {onPageSizeChange && (
        <div className="table-pagination-size">
          <span>Rows per page:</span>
          <select
            value={pageSize}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            aria-label="Rows per page"
          >
            {pageSizeOptions.map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
};

export default Pagination;
