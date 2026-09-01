import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { Search, Star, ArrowRight, Clock, Filter, X } from 'lucide-react';
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import { COLORS } from '../theme/colors';
import { getABCClassification } from '../api/abc';
import { getForecast } from '../api/forecast';
import DateFilter from './DateFilter';
import './SKUForecast.css';

// Unlike Dashboard/ABC Classification/Reorder Recs/Bad Orders, this page's
// date range is its OWN, local to this component — not the shared
// cross-page one in DashboardLayout (see the localRange state below, and
// DateFilter's "local mode"). It seeds from the dashboard's range once on
// mount, then never affects and is never affected by any other page.
// Trims which real actuals get plotted (see chartData below); the
// forecast point itself always stays anchored to the latest real month —
// MA3's one-step forecast is a batch-computed value, not something a
// picked range can honestly recompute on the fly.
const MONTH_TO_NUM = {
  Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
  Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12',
};
const toPeriod = (month, year) =>
  month && year ? `${year}-${MONTH_TO_NUM[month]}` : undefined;

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const hasActual = payload.some(p => p.dataKey === 'actual');
    const displayPayload = hasActual 
        ? payload.filter(p => p.dataKey !== 'forecast')
        : payload;

    return (
      <div className="forecast-tooltip">
        <p className="tooltip-label">{label}</p>
        {displayPayload.map((entry, index) => {
          if (entry.dataKey === 'ci') {
            return (
              <p key={index} className="tooltip-item">
                <span className="tooltip-dot" style={{ backgroundColor: '#F3E8FF', border: '1px solid #EBC9E1' }}></span>
                Confidence interval: {entry.value[0]} - {entry.value[1]}
              </p>
            );
          }
          return (
            <p key={index} className="tooltip-item" style={{ color: entry.color }}>
              <span className="tooltip-dot" style={{ backgroundColor: entry.color }}></span>
              {entry.name}: {entry.value}
            </p>
          );
        })}
      </div>
    );
  }
  return null;
};

const SKUForecast = () => {
  const navigate = useNavigate();
  const dropdownRef = useRef(null);

  // This page's chart has its OWN date range, independent of the shared
  // cross-page one in DashboardLayout — seeded from the dashboard's
  // CURRENT applied range the moment this page mounts (matching "opens
  // with the dashboard's selection"), then lives entirely in this
  // component's own state from that point on. Changing it here never
  // writes back to the shared range (see DateFilter's `localValue`/
  // `onLocalChange` "local mode"), and since this is a route-level
  // component it remounts — re-seeding fresh — every time the user
  // navigates back to this page, so a later dashboard change is picked
  // up on the NEXT visit without this page's own pick ever leaking to
  // any other page in the meantime.
  const dashboardRange = useOutletContext() || {};
  const [localRange, setLocalRange] = useState(() => ({
    startMonth: dashboardRange.startMonth,
    startYear: dashboardRange.startYear,
    endMonth: dashboardRange.endMonth,
    endYear: dashboardRange.endYear,
  }));
  const rangeStartPeriod = toPeriod(localRange.startMonth, localRange.startYear);
  const rangeEndPeriod = toPeriod(localRange.endMonth, localRange.endYear);

  // "Reset" (DateFilter's local-mode reset button) — snaps this page's own
  // range back to the dashboard's, same source the initial seed above used.
  const resetToDashboardRange = () => setLocalRange({
    startMonth: dashboardRange.startMonth,
    startYear: dashboardRange.startYear,
    endMonth: dashboardRange.endMonth,
    endYear: dashboardRange.endYear,
  });

  const [rawItems, setRawItems] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    setListError(null);
    getABCClassification({})
      .then((res) => {
        if (cancelled) return;
        setRawItems(res.items || []);
      })
      .catch((err) => {
        if (cancelled) return;
        setListError(err.message || 'Failed to load SKU list');
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Map ABC classification rows -> the SKU-picker shape this page renders.
  const sourceSKUs = useMemo(
    () =>
      rawItems.map((item) => ({
        code: item.sku_id,
        name: item.product_name || 'Unknown Product',
        brand: 'Unilever',
        cat: item.tier,
      })),
    [rawItems]
  );

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('ALL');
  const [selectedBrand, setSelectedBrand] = useState('ALL');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  // Selected SKU
  const [selectedSKU, setSelectedSKU] = useState(null);

  // Re-select when the loaded list changes.
  useEffect(() => {
    if (sourceSKUs.length > 0) {
      setSelectedSKU((prev) => (prev && sourceSKUs.some((s) => s.code === prev.code) ? prev : sourceSKUs[0]));
    } else {
      setSelectedSKU(null);
    }
  }, [sourceSKUs]);

  // Persistent Pinned SKUs
  const [pinnedSKUs, setPinnedSKUs] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_pinned_skus');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  // Persistent Recently Viewed/Forecasted SKUs (Max 5)
  const [recentSKUs, setRecentSKUs] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_recent_forecast_skus');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Toggle pin/unpin SKU
  const togglePinSKU = (code, e) => {
    if (e) e.stopPropagation();
    let updated;
    if (pinnedSKUs.includes(code)) {
      updated = pinnedSKUs.filter(c => c !== code);
    } else {
      updated = [...pinnedSKUs, code];
    }
    setPinnedSKUs(updated);
    localStorage.setItem('san2_pinned_skus', JSON.stringify(updated));
  };

  // Select SKU handler
  const handleSelectSKU = (sku) => {
    setSelectedSKU(sku);
    setIsDropdownOpen(false);

    // Update recent SKUs history (prepend, deduplicate, keep last 5)
    const updatedRecent = [sku.code, ...recentSKUs.filter(c => c !== sku.code)].slice(0, 5);
    setRecentSKUs(updatedRecent);
    localStorage.setItem('san2_recent_forecast_skus', JSON.stringify(updatedRecent));
  };

  // Unique Brands list
  const brandsList = ['ALL', ...Array.from(new Set(sourceSKUs.map(s => s.brand)))];

  // Filtering Logic
  const filteredSKUs = useMemo(() => {
    return sourceSKUs.filter(sku => {
      const matchesSearch = searchQuery === '' ||
        sku.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.brand.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = selectedCategory === 'ALL' || sku.cat === selectedCategory;
      const matchesBrand = selectedBrand === 'ALL' || sku.brand === selectedBrand;
      return matchesSearch && matchesCat && matchesBrand;
    });
  }, [sourceSKUs, searchQuery, selectedCategory, selectedBrand]);

  const hasActiveFilterOrSearch = selectedCategory !== 'ALL' || selectedBrand !== 'ALL' || searchQuery.trim() !== '';

  const pinnedSKUObjects = sourceSKUs.filter(sku => pinnedSKUs.includes(sku.code));
  const recentSKUObjects = sourceSKUs.filter(sku => recentSKUs.includes(sku.code) && !pinnedSKUs.includes(sku.code));
  const catASKUObjects = sourceSKUs.filter(
    sku => sku.cat === 'A' && !pinnedSKUs.includes(sku.code) && !recentSKUs.includes(sku.code)
  );

  const isSelectedPinned = selectedSKU ? pinnedSKUs.includes(selectedSKU.code) : false;

  // Forecast data for the selected SKU — fetched from Forecast_Result via
  // GET /forecast/{sku_id}. May legitimately come back with an empty
  // forecast[] if the MA3 baseline runner (scripts/run_baseline_forecast.py)
  // hasn't produced output for this SKU.
  const [forecastResult, setForecastResult] = useState(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState(null);

  useEffect(() => {
    if (!selectedSKU) {
      setForecastResult(null);
      return;
    }
    let cancelled = false;
    setForecastLoading(true);
    setForecastError(null);
    getForecast(selectedSKU.code)
      .then((res) => {
        if (cancelled) return;
        setForecastResult(res);
      })
      .catch((err) => {
        if (cancelled) return;
        setForecastError(err.message || 'Failed to load forecast');
      })
      .finally(() => {
        if (!cancelled) setForecastLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedSKU]);

  // Combine real trailing actuals + real forecast horizon into one chart
  // series. It now dynamically fills missing months between the first and last
  // actual data point with 0 to prevent straight lines skipping across void periods.
  //
  // This page's OWN local date range (2026-09, see localRange above): actuals
  // are trimmed to [rangeStartPeriod, rangeEndPeriod] before the gap-fill
  // below runs, so a narrower pick shows a narrower trailing-history window —
  // same "picker controls what's plotted" behavior Dashboard/ABC/Bad Orders
  // have with the shared range, just scoped to this one chart. The forecast
  // point is NOT filtered by range — GET /forecast always returns MA3's
  // single latest-real-month+1 forecast regardless of what range is picked
  // (see this file's MONTH_TO_NUM comment above).
  const chartData = useMemo(() => {
    if (!forecastResult) return [];

    // Sort actuals to ensure they are chronologically ordered, trimmed to
    // this page's own local range (never selected yet -> full history).
    const sortedActuals = [...(forecastResult.actuals || [])]
      .filter((a) => (!rangeStartPeriod || a.period >= rangeStartPeriod) && (!rangeEndPeriod || a.period <= rangeEndPeriod))
      .sort((a, b) => a.period.localeCompare(b.period));

    const actualPoints = [];
    if (sortedActuals.length > 0) {
      let currentPeriod = sortedActuals[0].period;
      const endPeriod = sortedActuals[sortedActuals.length - 1].period;
      let actualIndex = 0;
      
      while (currentPeriod <= endPeriod) {
        if (actualIndex < sortedActuals.length && sortedActuals[actualIndex].period === currentPeriod) {
          actualPoints.push({
            label: currentPeriod,
            actual: sortedActuals[actualIndex].quantity,
          });
          actualIndex++;
        } else {
          actualPoints.push({
            label: currentPeriod,
            actual: 0,
          });
        }
        
        const [yearStr, monthStr] = currentPeriod.split('-');
        let year = parseInt(yearStr, 10);
        let month = parseInt(monthStr, 10);
        month++;
        if (month > 12) {
          month = 1;
          year++;
        }
        currentPeriod = `${year}-${month.toString().padStart(2, '0')}`;
      }

      // Inject the final actual sales quantity into the forecast data key
      // so Recharts can draw a continuous line between the last actual point and the first forecast point
      actualPoints[actualPoints.length - 1].forecast = actualPoints[actualPoints.length - 1].actual;
    }

    const forecastPoints = (forecastResult.forecast || []).map((f) => ({
      label: f.forecast_date,
      forecast: f.forecast_value,
      ci: f.confidence_lower != null && f.confidence_upper != null
        ? [f.confidence_lower, f.confidence_upper]
        : undefined,
    }));
    return [...actualPoints, ...forecastPoints];
  }, [forecastResult, rangeStartPeriod, rangeEndPeriod]);

  const latestForecastPoint = forecastResult?.forecast?.length
    ? forecastResult.forecast[forecastResult.forecast.length - 1]
    : null;

  return (
    <div className="forecast-page">
      <div className="forecast-content">
        {/* Header */}
        <div className="forecast-header">
          <div className="header-text-group">
            <h2 className="forecast-title">
              Demand <span>forecasted</span>
            </h2>
            <p className="forecast-subtitle">
              MA3 (3-month moving average) projection for Category A SKUs, from Forecast_Result
            </p>
          </div>

          <div className="forecast-header-actions">
            <DateFilter localValue={localRange} onLocalChange={setLocalRange} onReset={resetToDashboardRange} />
            <button
              className="browse-all-skus-btn"
              onClick={() => navigate('/sku-management')}
              title="Go to SKU Management table"
            >
              <span>Browse all SKUs</span>
              <ArrowRight size={14} />
            </button>
          </div>
        </div>

        {/* Selection Area with Filter Controls */}
        <div className="forecast-selection">
          <div className="selection-top-bar">
            <label className="selection-label">SELECT SKU TO FORECAST</label>
          </div>

          {/* Controls Bar: Filters & Search Combobox */}
          <div className="combobox-controls-bar">
            {/* Filter Chips / Dropdowns */}
            <div className="forecast-filter-group">
              <div className="filter-dropdown-wrapper">
                <span className="filter-icon-label"><Filter size={12} /> Cat:</span>
                <select
                  className="filter-select"
                  value={selectedCategory}
                  onChange={(e) => {
                    setSelectedCategory(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                >
                  <option value="ALL">All Categories</option>
                  <option value="A">Category A</option>
                  <option value="B">Category B</option>
                  <option value="C">Category C</option>
                </select>
              </div>

              <div className="filter-dropdown-wrapper">
                <span className="filter-icon-label">Brand:</span>
                <select
                  className="filter-select"
                  value={selectedBrand}
                  onChange={(e) => {
                    setSelectedBrand(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                >
                  {brandsList.map(b => (
                    <option key={b} value={b}>{b === 'ALL' ? 'All Brands' : b}</option>
                  ))}
                </select>
              </div>

              {(selectedCategory !== 'ALL' || selectedBrand !== 'ALL' || searchQuery !== '') && (
                <button
                  className="clear-filters-btn"
                  onClick={() => {
                    setSelectedCategory('ALL');
                    setSelectedBrand('ALL');
                    setSearchQuery('');
                  }}
                  title="Clear all filters"
                >
                  <X size={12} />
                  <span>Clear</span>
                </button>
              )}
            </div>

            {/* Searchable Combobox */}
            <div className="search-combobox-wrapper" ref={dropdownRef}>
              <div className="search-input-inner">
                <Search className="search-icon" size={18} />
                <input
                  type="text"
                  placeholder="Search by SKU code, name, or brand..."
                  value={searchQuery}
                  onFocus={() => setIsDropdownOpen(true)}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setIsDropdownOpen(true);
                  }}
                  className="search-input"
                />
                {searchQuery && (
                  <button className="input-clear-btn" onClick={() => setSearchQuery('')}>
                    <X size={14} />
                  </button>
                )}
              </div>

              {/* Combobox Results Dropdown Panel */}
              {isDropdownOpen && (
                <div className="combobox-results-panel">
                  {hasActiveFilterOrSearch ? (
                    /* Filtered Search Results List */
                    <div className="combobox-section">
                      <div className="section-header-title">
                        <span>SEARCH RESULTS ({filteredSKUs.length})</span>
                      </div>
                      {filteredSKUs.length > 0 ? (
                        filteredSKUs.map(sku => (
                          <div
                            key={sku.code}
                            className={`result-row ${selectedSKU?.code === sku.code ? 'selected' : ''}`}
                            onClick={() => handleSelectSKU(sku)}
                          >
                            <button
                              className={`star-pin-btn ${pinnedSKUs.includes(sku.code) ? 'pinned' : ''}`}
                              onClick={(e) => togglePinSKU(sku.code, e)}
                              title={pinnedSKUs.includes(sku.code) ? "Unpin SKU" : "Pin SKU to top"}
                            >
                              <Star size={15} fill={pinnedSKUs.includes(sku.code) ? '#F5A623' : 'none'} />
                            </button>
                            <div className="result-code-group">
                              <span className="result-sku-code">{sku.code}</span>
                              <span className="result-brand">{sku.brand}</span>
                            </div>
                            <span className="result-product-name">{sku.name}</span>
                            <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                          </div>
                        ))
                      ) : (
                        <div className="no-results-msg">No data for this selection.</div>
                      )}
                    </div>
                  ) : (
                    /* Default Panel (Empty Search & No Filters) */
                    <div className="combobox-default-view">
                      {/* Section 1: Pinned / Favorited SKUs */}
                      {pinnedSKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <Star size={12} fill="#F5A623" color="#F5A623" />
                            <span>PINNED SKUS</span>
                          </div>
                          {pinnedSKUObjects.map(sku => (
                            <div
                              key={sku.code}
                              className={`result-row ${selectedSKU?.code === sku.code ? 'selected' : ''}`}
                              onClick={() => handleSelectSKU(sku)}
                            >
                              <button
                                className="star-pin-btn pinned"
                                onClick={(e) => togglePinSKU(sku.code, e)}
                                title="Unpin SKU"
                              >
                                <Star size={15} fill="#F5A623" />
                              </button>
                              <div className="result-code-group">
                                <span className="result-sku-code">{sku.code}</span>
                                <span className="result-brand">{sku.brand}</span>
                              </div>
                              <span className="result-product-name">{sku.name}</span>
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Section 2: Recently Forecasted SKUs */}
                      {recentSKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <Clock size={12} />
                            <span>RECENTLY FORECASTED</span>
                          </div>
                          {recentSKUObjects.map(sku => (
                            <div
                              key={sku.code}
                              className={`result-row ${selectedSKU?.code === sku.code ? 'selected' : ''}`}
                              onClick={() => handleSelectSKU(sku)}
                            >
                              <button
                                className={`star-pin-btn ${pinnedSKUs.includes(sku.code) ? 'pinned' : ''}`}
                                onClick={(e) => togglePinSKU(sku.code, e)}
                                title="Pin SKU"
                              >
                                <Star size={15} fill={pinnedSKUs.includes(sku.code) ? '#F5A623' : 'none'} />
                              </button>
                              <div className="result-code-group">
                                <span className="result-sku-code">{sku.code}</span>
                                <span className="result-brand">{sku.brand}</span>
                              </div>
                              <span className="result-product-name">{sku.name}</span>
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Section 3: Category A SKUs */}
                      {catASKUObjects.length > 0 && (
                        <div className="combobox-section">
                          <div className="section-header-title">
                            <span>CATEGORY A SKUS (HIGH PRIORITY)</span>
                          </div>
                          {catASKUObjects.map(sku => (
                            <div
                              key={sku.code}
                              className={`result-row ${selectedSKU?.code === sku.code ? 'selected' : ''}`}
                              onClick={() => handleSelectSKU(sku)}
                            >
                              <button
                                className={`star-pin-btn ${pinnedSKUs.includes(sku.code) ? 'pinned' : ''}`}
                                onClick={(e) => togglePinSKU(sku.code, e)}
                                title="Pin SKU"
                              >
                                <Star size={15} fill={pinnedSKUs.includes(sku.code) ? '#F5A623' : 'none'} />
                              </button>
                              <div className="result-code-group">
                                <span className="result-sku-code">{sku.code}</span>
                                <span className="result-brand">{sku.brand}</span>
                              </div>
                              <span className="result-product-name">{sku.name}</span>
                              <span className={`forecast-cat-badge cat-${sku.cat}`}>Cat {sku.cat}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {listLoading && <p className="forecast-subtitle">Loading SKU list…</p>}
        {listError && <p className="forecast-subtitle">Error: {listError}</p>}

        {selectedSKU && (
          <>
            {/* Selected SKU Card */}
            <div className="selected-sku-card">
              <div className="sku-info-left">
                <div className="sku-code-header-row">
                  <span className="sku-code-label">SELECTED SKU CODE</span>
                  <button
                    className={`card-star-btn ${isSelectedPinned ? 'pinned' : ''}`}
                    onClick={(e) => togglePinSKU(selectedSKU.code, e)}
                    title={isSelectedPinned ? "Unpin SKU" : "Pin SKU to top of search"}
                  >
                    <Star size={15} fill={isSelectedPinned ? '#F5A623' : 'none'} color={isSelectedPinned ? '#F5A623' : '#a0aec0'} />
                    <span className="pin-text">{isSelectedPinned ? 'Pinned' : 'Pin SKU'}</span>
                  </button>
                </div>
                <span className="sku-code-value">{selectedSKU.code}</span>
                <span className="sku-product-name">{selectedSKU.name}</span>
                <span className="sku-brand-name">Brand: {selectedSKU.brand}</span>
              </div>
              <div className="sku-info-right">
                <span className={`forecast-cat-badge cat-${selectedSKU.cat}`}>Category {selectedSKU.cat}</span>
              </div>
            </div>

            {/* Chart Section */}
            <div className="forecast-chart-container">
              {forecastLoading && <p className="forecast-subtitle">Loading forecast…</p>}
              {forecastError && <p className="forecast-subtitle">Error: {forecastError}</p>}

              {!forecastLoading && !forecastError && forecastResult && forecastResult.forecast.length === 0 && (
                <p className="forecast-subtitle">
                  No MA3 forecast has been generated for {selectedSKU.code} yet.
                </p>
              )}

              {!forecastLoading && !forecastError && forecastResult && (
                <>
                  {/* Model Accuracy Stat Row */}
                  <div className="forecast-accuracy-row">
                    <div className="forecast-stat-block">
                      <span className="forecast-stat-label">MAPE</span>
                      <span className="forecast-stat-value forecast-stat-value-neutral">
                        {latestForecastPoint?.mape != null
                          ? latestForecastPoint.mape >= 999.0
                            ? '>999%'
                            : `${latestForecastPoint.mape.toFixed(1)}%`
                          : '—'}
                      </span>
                      <span className="forecast-stat-desc">latest forecast run</span>
                    </div>
                    <div className="forecast-stat-divider" />
                    <div className="forecast-stat-block">
                      <span className="forecast-stat-label">HORIZON</span>
                      <span className="forecast-stat-value forecast-stat-value-neutral">
                        {forecastResult.forecast.length}
                      </span>
                      <span className="forecast-stat-desc">forecast point{forecastResult.forecast.length === 1 ? '' : 's'}</span>
                    </div>
                  </div>

                  {/* Chart Legend */}
                  <div className="chart-legend">
                    {chartData.some((pt) => pt.actual != null) && (
                      <div className="legend-item">
                        <span className="legend-line line-actual"></span>
                        <span className="legend-label">Actual Sales</span>
                      </div>
                    )}
                    <div className="legend-item">
                      <span className="legend-line line-forecast"></span>
                      <span className="legend-label">Forecast</span>
                    </div>
                    {forecastResult.forecast.some((f) => f.confidence_lower != null && f.confidence_upper != null) && (
                      <div className="legend-item">
                        <span className="legend-area area-ci"></span>
                        <span className="legend-label">Confidence Interval</span>
                      </div>
                    )}
                  </div>

                  {/* Chart */}
                  <div className="chart-wrapper">
                    <ResponsiveContainer width="100%" height={400}>
                      <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={COLORS.gridline} />
                        <XAxis
                          dataKey="label"
                          axisLine={true}
                          tickLine={true}
                          tick={{ fill: '#a0aec0', fontSize: 12 }}
                          dy={10}
                          // Recharts' default tick-skip anchors from the END
                          // of the axis (interval="preserveEnd") — harmless
                          // at the old fixed ~12-point series, but with a
                          // range picker now able to span ~39 months
                          // (Jan 2023 - Mar 2026), that default silently
                          // dropped the label at the true first month,
                          // reading as "the chart starts later than I
                          // picked" even though the plotted line itself
                          // was always correct (verified: chartData's
                          // first point is genuinely the picked start
                          // month). preserveStart guarantees the first
                          // tick is always shown; equidistant keeps the
                          // rest evenly spaced instead of clumping.
                          interval="equidistantPreserveStart"
                        />
                        <YAxis
                          axisLine={true}
                          tickLine={true}
                          tick={{ fill: '#a0aec0', fontSize: 12 }}
                          dx={-10}
                        />
                        <Tooltip content={<CustomTooltip />} />

                        <Area
                          type="monotone"
                          dataKey="ci"
                          stroke="none"
                          fill={COLORS.forecastBg}
                          name="Confidence interval"
                          isAnimationActive={false}
                        />

                        <Line
                          type="monotone"
                          dataKey="actual"
                          stroke={COLORS.salesTrend}
                          strokeWidth={2}
                          dot={{ r: 4, fill: COLORS.salesTrend, strokeWidth: 0 }}
                          activeDot={{ r: 6 }}
                          name="Actual Sales"
                          isAnimationActive={false}
                          connectNulls
                        />

                        <Line
                          type="monotone"
                          dataKey="forecast"
                          stroke={COLORS.forecast}
                          strokeWidth={2}
                          strokeDasharray="5 5"
                          dot={{ r: 4, fill: COLORS.forecast, strokeWidth: 0 }}
                          activeDot={{ r: 6 }}
                          name="Forecast"
                          isAnimationActive={false}
                          connectNulls
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default SKUForecast;
