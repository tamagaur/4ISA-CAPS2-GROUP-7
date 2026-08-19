import React, { useState, useMemo, useRef, useEffect } from 'react';
import { Search, Clock, X, RotateCcw, Tag, Filter, AlertTriangle } from 'lucide-react';
import {
  ComposedChart,
  Bar,
  Line,
  ReferenceLine,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { COLORS } from '../theme/colors';
import './ABCClassification.css';

// Story #43 / Manuscript §3.5.5: "flags SKUs approaching tier boundaries."
// Tier cutoffs are 80% and 95% cumulative revenue (§3.4.1.2). A SKU sitting
// within this many cumulative percentage points of a cutoff is flagged as
// close to being reclassified into the tier above or below it.
const BOUNDARY_TOLERANCE_PP = 3;
const TIER_CUTOFFS = [80, 95];

const mockABCData = [
  { id: 1, sku: 'SKU-4721', product: 'Surf Powder Detergent 1kg', brand: 'Unilever', cat: 'A', avgMo: 1243, revPct: 8.2, status: 'IN STOCK' },
  { id: 2, sku: 'SKU-8934', product: 'Pineapple Juice 1L', brand: 'Del Monte', cat: 'A', avgMo: 1156, revPct: 7.8, status: 'LOW' },
  { id: 3, sku: 'SKU-2891', product: 'Knorr Cubes 8g', brand: 'Unilever', cat: 'A', avgMo: 1098, revPct: 7.3, status: 'IN STOCK' },
  { id: 4, sku: 'SKU-5632', product: 'Sweet Corn Kernel 425g', brand: 'Del Monte', cat: 'A', avgMo: 1045, revPct: 6.9, status: 'CRITICAL' },
  { id: 5, sku: 'SKU-7821', product: 'Dove Shampoo 340ml', brand: 'Unilever', cat: 'A', avgMo: 987, revPct: 6.5, status: 'IN STOCK' },
  { id: 6, sku: 'SKU-3421', product: 'Tomato Sauce 250g', brand: 'Del Monte', cat: 'A', avgMo: 923, revPct: 6.1, status: 'IN STOCK' },
  { id: 7, sku: 'SKU-9012', product: 'Lux Bar Soap 135g', brand: 'Unilever', cat: 'A', avgMo: 876, revPct: 5.8, status: 'IN STOCK' },
  { id: 8, sku: 'SKU-1234', product: 'Fruit Cocktail 432g', brand: 'Del Monte', cat: 'A', avgMo: 834, revPct: 5.5, status: 'LOW' },
  { id: 9, sku: 'SKU-6543', product: 'Creamsilk Conditioner 180ml', brand: 'Unilever', cat: 'A', avgMo: 798, revPct: 5.3, status: 'IN STOCK' },
  { id: 10, sku: 'SKU-4567', product: 'Spaghetti Sauce 500g', brand: 'Del Monte', cat: 'A', avgMo: 756, revPct: 5.0, status: 'IN STOCK' },
  { id: 11, sku: 'SKU-8901', product: 'Breeze Detergent Powder 500g', brand: 'Unilever', cat: 'A', avgMo: 721, revPct: 4.8, status: 'IN STOCK' },
  { id: 12, sku: 'SKU-2345', product: 'Tomato Ketchup 320g', brand: 'Del Monte', cat: 'A', avgMo: 689, revPct: 4.6, status: 'IN STOCK' },
  { id: 13, sku: 'SKU-7890', product: 'Rexona Deodorant 40ml', brand: 'Unilever', cat: 'A', avgMo: 654, revPct: 4.3, status: 'IN STOCK' },
  { id: 14, sku: 'SKU-3456', product: 'Peach Halves 420g', brand: 'Del Monte', cat: 'A', avgMo: 623, revPct: 4.1, status: 'IN STOCK' },
  { id: 15, sku: 'SKU-1122', product: 'Sunsilk Shampoo 180ml', brand: 'Unilever', cat: 'B', avgMo: 534, revPct: 3.2, status: 'IN STOCK' },
  { id: 16, sku: 'SKU-3344', product: 'Pineapple Tidbits 432g', brand: 'Del Monte', cat: 'B', avgMo: 498, revPct: 2.9, status: 'IN STOCK' },
  { id: 17, sku: 'SKU-5566', product: 'Closeup Toothpaste 120ml', brand: 'Unilever', cat: 'B', avgMo: 467, revPct: 2.7, status: 'LOW' },
  { id: 18, sku: 'SKU-7788', product: 'Mixed Vegetables 380g', brand: 'Del Monte', cat: 'B', avgMo: 423, revPct: 2.4, status: 'IN STOCK' },
  { id: 19, sku: 'SKU-9900', product: 'Pond\'s Powder 50g', brand: 'Unilever', cat: 'B', avgMo: 398, revPct: 2.2, status: 'IN STOCK' },
  { id: 20, sku: 'SKU-2211', product: 'Spaghetti Pasta 900g', brand: 'Del Monte', cat: 'B', avgMo: 356, revPct: 1.9, status: 'IN STOCK' },
  { id: 21, sku: 'SKU-4422', product: 'Vaseline Lotion 200ml', brand: 'Unilever', cat: 'C', avgMo: 187, revPct: 0.8, status: 'IN STOCK' },
  { id: 22, sku: 'SKU-6633', product: 'Fiesta Pasta 500g', brand: 'Del Monte', cat: 'C', avgMo: 145, revPct: 0.6, status: 'IN STOCK' },
  { id: 23, sku: 'SKU-8844', product: 'Signal Toothbrush', brand: 'Unilever', cat: 'C', avgMo: 112, revPct: 0.4, status: 'LOW' },
  { id: 24, sku: 'SKU-1155', product: 'Prune Juice 240ml', brand: 'Del Monte', cat: 'C', avgMo: 89, revPct: 0.3, status: 'IN STOCK' },
];

// Helper to extract product name and weight (supports decimals like 1.5L, 2.5kg)
const parseProductAndWeight = (product) => {
  if (!product) return { name: '', weight: '' };
  const weightRegex = /\b(\d+(?:\.\d+)?\s*(?:g|ml|l|kg|L|KG|ML|G))\b/;
  const match = product.match(weightRegex);
  if (match) {
    const weight = `(${match[1]})`;
    let name = product.replace(weightRegex, '').replace(/\s+/g, ' ').trim();
    name = name.replace(/\(\s*\)/g, '').trim();
    return { name, weight };
  }
  return { name: product, weight: '' };
};

// Helper to format SKU to 5 digits (SKU-#####)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  return sku;
};

// Manuscript §3.4.4.2.2/§3.4.4.2.3: Pareto/80-20 validation and Cumulative
// Revenue Coverage Ratio. Both series are already percentages (revenue %
// per SKU, cumulative %), so bars and the cumulative line share one 0-100
// axis by construction — no dual-axis needed.
const ParetoTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const point = payload[0].payload;
    return (
      <div className="abc-pareto-tooltip">
        <p className="abc-pareto-tooltip-title">Rank #{label} — {formatSKU(point.sku)}</p>
        <p className="abc-pareto-tooltip-line" style={{ color: COLORS.dispatched }}>
          Revenue share: {point.revPct.toFixed(1)}%
        </p>
        <p className="abc-pareto-tooltip-line" style={{ color: COLORS.brandPrimary }}>
          Cumulative: {point.cumulativePct.toFixed(1)}%
        </p>
      </div>
    );
  }
  return null;
};

const ABCClassification = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('ALL');
  const [brandFilter, setBrandFilter] = useState('ALL');

  const [isComboboxOpen, setIsComboboxOpen] = useState(false);
  const [highlightedSKUId, setHighlightedSKUId] = useState(null);
  const comboboxRef = useRef(null);

  // Persistent Recently Searched SKUs
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_recent_abc_searches');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  // Handle click outside combobox to close dropdown
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (comboboxRef.current && !comboboxRef.current.contains(e.target)) {
        setIsComboboxOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const catACount = mockABCData.filter(d => d.cat === 'A').length;
  const catBCount = mockABCData.filter(d => d.cat === 'B').length;
  const catCCount = mockABCData.filter(d => d.cat === 'C').length;

  const brandsList = ['ALL', ...Array.from(new Set(mockABCData.map(d => d.brand)))];

  // Cumulative revenue % and boundary-proximity flag, computed once over the
  // full value-ranked list (not the filtered view) so flags stay correct
  // regardless of what the user is currently searching/filtering for.
  const dataWithCumulative = useMemo(() => {
    const sorted = [...mockABCData].sort((a, b) => b.revPct - a.revPct);
    let running = 0;
    return sorted.map((item, index) => {
      running += item.revPct;
      const nearestCutoff = TIER_CUTOFFS.reduce((closest, cutoff) =>
        Math.abs(cutoff - running) < Math.abs(closest - running) ? cutoff : closest
      , TIER_CUTOFFS[0]);
      const distance = Math.abs(nearestCutoff - running);
      return {
        ...item,
        rank: index + 1,
        cumulativePct: running,
        nearBoundary: distance <= BOUNDARY_TOLERANCE_PP,
        boundaryCutoff: nearestCutoff,
      };
    });
  }, []);

  const filteredData = useMemo(() => {
    return dataWithCumulative.filter(item => {
      const matchesSearch = searchQuery === '' ||
        item.sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.brand.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = categoryFilter === 'ALL' || item.cat === categoryFilter;
      const matchesBrand = brandFilter === 'ALL' || item.brand === brandFilter;
      return matchesSearch && matchesCat && matchesBrand;
    });
  }, [dataWithCumulative, searchQuery, categoryFilter, brandFilter]);

  const boundaryCount = useMemo(
    () => dataWithCumulative.filter(item => item.nearBoundary).length,
    [dataWithCumulative]
  );

  const handleSelectSuggestion = (item) => {
    setSearchQuery(item.sku);
    setIsComboboxOpen(false);

    // Save to recent searches
    setRecentSearches(prev => {
      const filtered = prev.filter(s => s.id !== item.id);
      const updated = [item, ...filtered].slice(0, 5);
      localStorage.setItem('san2_recent_abc_searches', JSON.stringify(updated));
      return updated;
    });

    // Scroll & Highlight row
    setHighlightedSKUId(item.id);
    setTimeout(() => {
      const el = document.getElementById(`abc-row-${item.id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 80);

    setTimeout(() => {
      setHighlightedSKUId(null);
    }, 2000);
  };

  const hasActiveFilters = searchQuery !== '' || categoryFilter !== 'ALL' || brandFilter !== 'ALL';

  const handleClearFilters = () => {
    setSearchQuery('');
    setCategoryFilter('ALL');
    setBrandFilter('ALL');
  };

  const getStatusClass = (status) => {
    switch (status) {
      case 'IN STOCK': return 'abc-status abc-in-stock';
      case 'LOW': return 'abc-status abc-low';
      case 'CRITICAL': return 'abc-status abc-critical';
      default: return 'abc-status';
    }
  };

  const getCatBadgeClass = (cat) => {
    switch (cat) {
      case 'A': return 'abc-cat-badge abc-cat-a';
      case 'B': return 'abc-cat-badge abc-cat-b';
      case 'C': return 'abc-cat-badge abc-cat-c';
      default: return 'abc-cat-badge';
    }
  };

  return (
    <div className="abc-page">
      <div className="abc-content">
        {/* Page Header */}
        <div className="abc-page-header">
          <h2 className="abc-page-title">ABC Classification</h2>
          <p className="abc-page-subtitle">
            Products ranked by sales value. Category A = the top 20% of SKUs driving roughly 80% of revenue. Click a code to open its forecast.
            <span className="abc-boundary-legend"> <AlertTriangle size={12} className="abc-boundary-legend-icon" /> flags a SKU within {BOUNDARY_TOLERANCE_PP}pp of a tier cutoff — likely to reclassify next review cycle.</span>
          </p>
        </div>

        {/* Summary Cards */}
        <div className="abc-summary-grid">
          <div className="abc-summary-card abc-card-a">
            <span className="abc-card-label">CATEGORY A</span>
            <span className="abc-card-value">{catACount}</span>
            <span className="abc-card-desc">Top 20% · 80% of revenue</span>
          </div>
          <div className="abc-summary-card abc-card-b">
            <span className="abc-card-label">CATEGORY B</span>
            <span className="abc-card-value">{catBCount}</span>
            <span className="abc-card-desc">Middle tier · 15% of revenue</span>
          </div>
          <div className="abc-summary-card abc-card-c">
            <span className="abc-card-label">CATEGORY C</span>
            <span className="abc-card-value">{catCCount}</span>
            <span className="abc-card-desc">Long tail · 5% of revenue</span>
          </div>
          <div className="abc-summary-card abc-card-total">
            <span className="abc-card-label">TOTAL SKUS</span>
            <span className="abc-card-value">1,247</span>
            {boundaryCount > 0 && (
              <span className="abc-card-desc abc-card-desc-warning">
                <AlertTriangle size={11} /> {boundaryCount} near a tier boundary
              </span>
            )}
          </div>
        </div>

        {/* Pareto Chart — Manuscript §3.4.4.2.2 (80/20 validation) / §3.4.4.2.3 (CRCR) */}
        <div className="abc-pareto-container">
          <div className="abc-pareto-header">
            <h3 className="abc-pareto-title">Pareto analysis</h3>
            <div className="abc-pareto-legend">
              <div className="abc-pareto-legend-item">
                <span className="abc-pareto-legend-swatch" style={{ backgroundColor: COLORS.dispatched }} />
                <span>Revenue share per SKU</span>
              </div>
              <div className="abc-pareto-legend-item">
                <span className="abc-pareto-legend-line" style={{ backgroundColor: COLORS.brandPrimary }} />
                <span>Cumulative revenue</span>
              </div>
              <div className="abc-pareto-legend-item">
                <span className="abc-pareto-legend-line abc-pareto-legend-dashed" style={{ backgroundColor: COLORS.gridline }} />
                <span>Tier cutoffs (80% / 95%)</span>
              </div>
            </div>
          </div>
          <div className="abc-pareto-chart-wrapper">
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={dataWithCumulative} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={COLORS.gridline} />
                <XAxis
                  dataKey="rank"
                  axisLine={true}
                  tickLine={true}
                  tick={{ fill: '#a0aec0', fontSize: 11 }}
                  label={{ value: 'SKU rank, by revenue', position: 'insideBottom', offset: -5, fill: '#a0aec0', fontSize: 11 }}
                />
                <YAxis
                  domain={[0, 100]}
                  ticks={[0, 20, 40, 60, 80, 100]}
                  tickFormatter={(v) => `${v}%`}
                  axisLine={true}
                  tickLine={true}
                  tick={{ fill: '#a0aec0', fontSize: 11 }}
                />
                <Tooltip content={<ParetoTooltip />} cursor={{ fill: '#f7fafc' }} />
                <ReferenceLine y={80} stroke={COLORS.gridline} strokeDasharray="4 4" label={{ value: 'A/B — 80%', position: 'right', fill: '#a0aec0', fontSize: 10 }} />
                <ReferenceLine y={95} stroke={COLORS.gridline} strokeDasharray="4 4" label={{ value: 'B/C — 95%', position: 'right', fill: '#a0aec0', fontSize: 10 }} />
                <Bar dataKey="revPct" fill={COLORS.dispatched} radius={[2, 2, 0, 0]} barSize={16} isAnimationActive={false} />
                <Line
                  type="monotone"
                  dataKey="cumulativePct"
                  stroke={COLORS.brandPrimary}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 5 }}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Searchable Combobox & Filters Bar */}
        <div className="abc-filters-row">
          {/* Search Combobox */}
          <div className="abc-combobox-container" ref={comboboxRef}>
            <div className="abc-search-wrapper">
              <Search className="abc-search-icon" size={16} />
              <input
                type="text"
                placeholder="Search by product name, SKU, or brand..."
                value={searchQuery}
                onFocus={() => setIsComboboxOpen(true)}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setIsComboboxOpen(true);
                }}
                className="abc-search-input"
              />
              {searchQuery && (
                <button className="abc-input-clear-btn" onClick={() => setSearchQuery('')} title="Clear search">
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Combobox Dropdown Panel */}
            {isComboboxOpen && (
              <div className="abc-combobox-dropdown">
                {searchQuery.trim() !== '' ? (
                  /* Live Suggestions */
                  <div className="abc-combobox-section">
                    <div className="abc-section-header">
                      <span>SUGGESTIONS ({filteredData.length})</span>
                    </div>
                    {filteredData.length > 0 ? (
                      filteredData.map((item) => (
                        <div
                          key={item.id}
                          className="abc-suggestion-row"
                          onClick={() => handleSelectSuggestion(item)}
                        >
                          <div className="abc-row-left">
                            <span className="abc-row-sku">{formatSKU(item.sku)}</span>
                            <span className="abc-row-brand">{item.brand}</span>
                          </div>
                          <div className="abc-row-middle">
                            <span className="abc-row-product">{item.product}</span>
                            <span className="abc-row-rev">{item.revPct}% of revenue</span>
                          </div>
                          <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                        </div>
                      ))
                    ) : (
                      <div className="abc-no-suggestions">No matching products found.</div>
                    )}
                  </div>
                ) : (
                  /* Quick Access Panel */
                  <div className="abc-combobox-default">
                    {recentSearches.length > 0 && (
                      <div className="abc-combobox-section">
                        <div className="abc-section-header">
                          <Clock size={12} />
                          <span>RECENTLY SEARCHED</span>
                        </div>
                        {recentSearches.map((item) => (
                          <div
                            key={item.id}
                            className="abc-suggestion-row"
                            onClick={() => handleSelectSuggestion(item)}
                          >
                            <div className="abc-row-left">
                              <span className="abc-row-sku">{formatSKU(item.sku)}</span>
                              <span className="abc-row-brand">{item.brand}</span>
                            </div>
                            <div className="abc-row-middle">
                              <span className="abc-row-product">{item.product}</span>
                            </div>
                            <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="abc-combobox-section">
                      <div className="abc-section-header">
                        <span>TOP ABC CLASSIFIED SKUS</span>
                      </div>
                      {filteredData.slice(0, 5).map((item) => (
                        <div
                          key={item.id}
                          className="abc-suggestion-row"
                          onClick={() => handleSelectSuggestion(item)}
                        >
                          <div className="abc-row-left">
                            <span className="abc-row-sku">{formatSKU(item.sku)}</span>
                            <span className="abc-row-brand">{item.brand}</span>
                          </div>
                          <div className="abc-row-middle">
                            <span className="abc-row-product">{item.product}</span>
                            <span className="abc-row-rev">{item.revPct}% revenue</span>
                          </div>
                          <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Filter Controls Row */}
          <div className="abc-filter-controls">
            <div className="abc-filter-select-wrapper">
              <span className="abc-filter-icon-label"><Tag size={12} /> Brand:</span>
              <select
                value={brandFilter}
                onChange={(e) => setBrandFilter(e.target.value)}
              >
                {brandsList.map(b => (
                  <option key={b} value={b}>{b === 'ALL' ? 'All Brands' : b}</option>
                ))}
              </select>
            </div>

            <div className="abc-cat-toggle-group">
              {['ALL', 'A', 'B', 'C'].map(cat => (
                <button
                  key={cat}
                  className={`abc-cat-toggle-btn ${categoryFilter === cat ? 'active' : ''}`}
                  onClick={() => setCategoryFilter(cat)}
                >
                  {cat === 'ALL' ? 'ALL' : `CAT ${cat}`}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Active Filter Chips Bar */}
        {hasActiveFilters && (
          <div className="abc-active-chips-row">
            <span className="abc-chips-label">
              <Filter size={12} /> Active Filters:
            </span>

            {searchQuery && (
              <span className="abc-active-chip">
                Search: "{searchQuery}"
                <button className="abc-chip-remove" onClick={() => setSearchQuery('')}>
                  <X size={12} />
                </button>
              </span>
            )}

            {brandFilter !== 'ALL' && (
              <span className="abc-active-chip">
                Brand: {brandFilter}
                <button className="abc-chip-remove" onClick={() => setBrandFilter('ALL')}>
                  <X size={12} />
                </button>
              </span>
            )}

            {categoryFilter !== 'ALL' && (
              <span className="abc-active-chip">
                Category: CAT {categoryFilter}
                <button className="abc-chip-remove" onClick={() => setCategoryFilter('ALL')}>
                  <X size={12} />
                </button>
              </span>
            )}

            <button
              className="abc-clear-all-chips-btn"
              onClick={handleClearFilters}
              title="Reset all filters"
            >
              <RotateCcw size={12} />
              Clear all filters
            </button>
          </div>
        )}

        {/* Table */}
        <div className="abc-table-wrapper">
          <table className="abc-table">
            <thead>
              <tr>
                <th>#</th>
                <th>SKU</th>
                <th>PRODUCT</th>
                <th>BRAND</th>
                <th>CAT</th>
                <th>AVG/MO</th>
                <th>REV %</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {filteredData.map((item, index) => (
                <tr
                  key={item.id}
                  id={`abc-row-${item.id}`}
                  className={highlightedSKUId === item.id ? 'highlighted-row-flash' : ''}
                >
                  <td className="abc-row-num">{index + 1}</td>
                  <td className="abc-sku-cell">{formatSKU(item.sku)}</td>
                  <td className="abc-product-cell">
                    {(() => {
                      const { name, weight } = parseProductAndWeight(item.product);
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                          <span className="abc-product-name">{name}</span>
                          {weight && (
                            <span className="abc-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                              {weight}
                            </span>
                          )}
                        </div>
                      );
                    })()}
                  </td>
                  <td className="abc-brand-cell">{item.brand}</td>
                  <td>
                    <span className="abc-cat-cell-inner">
                      <span className={getCatBadgeClass(item.cat)}>{item.cat}</span>
                      {item.nearBoundary && (
                        <AlertTriangle
                          size={13}
                          className="abc-boundary-icon"
                          title={`Cumulative revenue ${item.cumulativePct.toFixed(1)}% — within ${BOUNDARY_TOLERANCE_PP}pp of the ${item.boundaryCutoff}% tier cutoff`}
                        />
                      )}
                    </span>
                  </td>
                  <td className="abc-avg-cell">{item.avgMo.toLocaleString()}</td>
                  <td className="abc-rev-cell">{item.revPct.toFixed(1)}%</td>
                  <td><span className={getStatusClass(item.status)}>{item.status}</span></td>
                </tr>
              ))}
              {filteredData.length === 0 && (
                <tr>
                  <td colSpan="8" className="abc-no-results">No products found matching your filters.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default ABCClassification;
