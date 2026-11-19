const hasSales = (year) => year && year.sales != null && year.months > 0;

export function calendarYearView(annual, currentAllocation, selectedYear) {
  const year = Number(selectedYear);
  if (!Number.isInteger(year)) return null;

  const rows = annual?.years || [];
  const selected = rows.find((row) => Number(row.year) === year) || null;
  const salesAvailable = hasSales(selected);
  const levels = salesAvailable && selected.allocation_levels?.length
    ? selected.allocation_levels
    : Number(currentAllocation?.basis_year) === year ? currentAllocation?.levels || [] : [];

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

  const blockedReason = !salesAvailable
    ? annual?.blocked_reason || `No sales are on record for calendar year ${year}.`
    : selected.sales <= 0
      ? `Calendar year ${year} sales net to zero or less, so no allocation target can be calculated.`
      : levels.length === 0
        ? currentAllocation?.blocked_reason || 'The allocation target is unavailable for this principal.'
        : null;

  const allocation = {
    basis_year: year,
    basis_sales: selected?.sales ?? null,
    basis_months: selected?.months || 0,
    allocation_year: year + 1,
    levels,
    default_pct: currentAllocation?.default_pct ?? null,
    blocked_reason: blockedReason,
  };

  return {
    year,
    targetYear: year + 1,
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
