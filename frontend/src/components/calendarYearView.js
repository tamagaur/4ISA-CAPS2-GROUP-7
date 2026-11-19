const hasSales = (year) => year && year.sales != null && year.months > 0;

export function calendarYearView(annual, currentAllocation, selectedYear) {
  const year = Number(selectedYear);
  if (!Number.isInteger(year)) return null;

  const rows = annual?.years || [];
  const selected = rows.find((row) => Number(row.year) === year) || null;
  const basis = rows.find((row) => Number(row.year) === year - 1) || null;
  const salesAvailable = hasSales(selected);
  const currentAllocationMatches = Number(currentAllocation?.allocation_year) === year
    && Number(currentAllocation?.basis_year) === year - 1;
  const basisSales = basis?.sales ?? (currentAllocationMatches ? currentAllocation?.basis_sales : null);
  const basisMonths = basis?.months || (currentAllocationMatches ? currentAllocation?.basis_months : 0);
  const basisAvailable = basisSales != null && basisMonths > 0;
  const levels = basis?.allocation_levels?.length
    ? basis.allocation_levels
    : currentAllocationMatches ? currentAllocation?.levels || [] : [];

  const comparison = selected?.comparison || null;
  let comparisonNote = null;
  if (salesAvailable && !comparison) {
    comparisonNote = `A like-for-like comparison with ${year - 1} is unavailable because the same months are not recorded in both years.`;
  }

  const yoy = comparison && comparison.sales > 0
    ? {
      pct: ((selected.sales - comparison.sales) / comparison.sales) * 100,
      label: comparison.label,
    }
    : null;
  if (comparison && comparison.sales <= 0) {
    comparisonNote = `Sales for ${comparison.label} are zero or less, so a percentage comparison is unavailable.`;
  }

  const blockedReason = !basisAvailable
    ? annual?.blocked_reason || `No sales are on record for calendar year ${year - 1}.`
    : basisSales <= 0
      ? `Calendar year ${year - 1} sales net to zero or less, so no allocation target can be calculated.`
      : levels.length === 0
        ? (currentAllocationMatches && currentAllocation?.blocked_reason)
          || 'The allocation target is unavailable for this principal.'
        : null;

  const allocation = {
    basis_year: year - 1,
    basis_sales: basisSales,
    basis_months: basisMonths,
    allocation_year: year,
    levels,
    default_pct: currentAllocation?.default_pct ?? null,
    blocked_reason: blockedReason,
  };

  return {
    year,
    allocationYear: year,
    basisYear: year - 1,
    basisSales,
    basisMonths,
    sales: selected?.sales ?? null,
    months: selected?.months || 0,
    firstMonth: selected?.first_month ?? null,
    lastMonth: selected?.last_month ?? null,
    syntheticMonths: selected?.synthetic_months || [],
    levels,
    defaultPct: currentAllocation?.default_pct ?? null,
    yoy,
    comparisonNote,
    blockedReason,
    allocation,
  };
}
