import React, { useState, useMemo } from 'react';
import './ABCClassification.css';

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

const ABCClassification = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('ALL');

  const catACount = mockABCData.filter(d => d.cat === 'A').length;
  const catBCount = mockABCData.filter(d => d.cat === 'B').length;
  const catCCount = mockABCData.filter(d => d.cat === 'C').length;
  const totalCount = mockABCData.length;

  const filteredData = useMemo(() => {
    return mockABCData.filter(item => {
      const matchesSearch = searchQuery === '' ||
        item.sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.brand.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = categoryFilter === 'ALL' || item.cat === categoryFilter;
      return matchesSearch && matchesCat;
    });
  }, [searchQuery, categoryFilter]);

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
          <h2 className="abc-page-title">A. B. C.</h2>
          <p className="abc-page-subtitle">
            Products ranked by sales value. Category A = the top 20% of SKUs driving roughly 80% of revenue. Click a code to open its forecast.
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
          </div>
        </div>

        {/* Filters */}
        <div className="abc-filters-row">
          <div className="abc-search-wrapper">
            <svg className="abc-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              type="text"
              placeholder="Search by product name, SKU, or brand..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="abc-search-input"
            />
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
                <tr key={item.id}>
                  <td className="abc-row-num">{index + 1}</td>
                  <td className="abc-sku-cell">{item.sku}</td>
                  <td className="abc-product-cell">{item.product}</td>
                  <td className="abc-brand-cell">{item.brand}</td>
                  <td><span className={getCatBadgeClass(item.cat)}>{item.cat}</span></td>
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
