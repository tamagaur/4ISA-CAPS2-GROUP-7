import React, { useState, useMemo } from 'react';
import { Plus } from 'lucide-react';
import AddSKUModal from './AddSKUModal';
import './SKUManagement.css';

const mockSKUs = [
  { id: '001', code: 'SKU-10234', brand: 'Del Monte', supplier: 'Del Monte Philippines', product: 'Pineapple Juice 1L', cat: 'A', leadTime: '7 days', reorderPt: 800, status: 'ACTIVE' },
  { id: '002', code: 'SKU-10198', brand: 'Unilever', supplier: 'Unilever Philippines', product: 'Knorr Cubes 8g', cat: 'A', leadTime: '5 days', reorderPt: 600, status: 'ACTIVE' },
  { id: '003', code: 'SKU-10456', brand: 'Del Monte', supplier: 'Del Monte Philippines', product: 'Spaghetti Sauce 500g', cat: 'A', leadTime: '6 days', reorderPt: 500, status: 'ACTIVE' },
  { id: '004', code: 'SKU-10789', brand: 'Unilever', supplier: 'Unilever Philippines', product: 'Surf Powder Detergent 1kg', cat: 'A', leadTime: '4 days', reorderPt: 1200, status: 'ACTIVE' },
  { id: '005', code: 'SKU-10112', brand: 'Del Monte', supplier: 'Del Monte Philippines', product: 'Sweet Corn Kernel 425g', cat: 'A', leadTime: '7 days', reorderPt: 400, status: 'ACTIVE' },
  { id: '006', code: 'SKU-20101', brand: 'Del Monte', supplier: 'Del Monte Philippines', product: 'Tomato Sauce 250g', cat: 'B', leadTime: '7 days', reorderPt: 800, status: 'ACTIVE' },
  { id: '007', code: 'SKU-20145', brand: 'Unilever', supplier: 'Unilever Philippines', product: 'Dove Shampoo 340ml', cat: 'B', leadTime: '5 days', reorderPt: 300, status: 'ACTIVE' },
  { id: '008', code: 'SKU-20289', brand: 'Del Monte', supplier: 'Del Monte Philippines', product: 'Fruit Cocktail 432g', cat: 'B', leadTime: '6 days', reorderPt: 200, status: 'ACTIVE' },
  { id: '009', code: 'SKU-30856', brand: 'Unilever', supplier: 'Unilever Philippines', product: 'Ponds Face Cream 50g', cat: 'C', leadTime: '5 days', reorderPt: 150, status: 'ACTIVE' },
  { id: '010', code: 'SKU-99999', brand: 'Del Monte', supplier: 'Del Monte Philippines', product: 'Ketchup 320g (Discontinued)', cat: 'C', leadTime: 'N/A', reorderPt: 0, status: 'INACTIVE' },
];

// Helper to extract product name and weight
const parseProductAndWeight = (product) => {
  const weightRegex = /\b(\d+(?:g|ml|L|kg))\b/i;
  const match = product.match(weightRegex);
  if (match) {
    const weight = `(${match[1]})`;
    let name = product.replace(weightRegex, '').replace(/\s+/g, ' ').trim();
    name = name.replace(/\(\s*\)/g, '').trim();
    return { name, weight };
  }
  return { name: product, weight: '' };
};

const SKUManagement = () => {
  const [skus, setSkus] = useState(mockSKUs);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [supplierFilter, setSupplierFilter] = useState('All Suppliers');
  const [brandFilter, setBrandFilter] = useState('All Brands');
  const [categoryFilter, setCategoryFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const suppliers = ['All Suppliers', ...new Set(skus.map(s => s.supplier))];
  const brands = ['All Brands', ...new Set(skus.map(s => s.brand))];

  const filteredSKUs = useMemo(() => {
    return skus.filter(sku => {
      const matchesSearch = searchQuery === '' ||
        sku.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.product.toLowerCase().includes(searchQuery.toLowerCase()) ||
        sku.brand.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesSupplier = supplierFilter === 'All Suppliers' || sku.supplier === supplierFilter;
      const matchesBrand = brandFilter === 'All Brands' || sku.brand === brandFilter;
      const matchesCategory = categoryFilter === 'All' || sku.cat === categoryFilter;
      const matchesStatus = statusFilter === 'ALL' ||
        (statusFilter === 'ACTIVE' && sku.status === 'ACTIVE') ||
        (statusFilter === 'INACTIVE' && sku.status === 'INACTIVE');
      return matchesSearch && matchesSupplier && matchesBrand && matchesCategory && matchesStatus;
    });
  }, [skus, searchQuery, supplierFilter, brandFilter, categoryFilter, statusFilter]);

  const totalSKUs = skus.length;
  const activeSKUs = skus.filter(s => s.status === 'ACTIVE').length;
  const inactiveSKUs = skus.filter(s => s.status === 'INACTIVE').length;

  const handleAddSKU = (formData) => {
    const newId = String(skus.length + 1).padStart(3, '0');
    const newSKU = {
      id: newId,
      code: formData.skuCode,
      brand: formData.brand,
      supplier: formData.supplier,
      product: formData.productName,
      cat: formData.category,
      leadTime: '5 days',
      reorderPt: parseInt(formData.reorderPoint) || 0,
      status: 'ACTIVE',
    };
    setSkus(prev => [...prev, newSKU]);
  };

  const getCatClass = (cat) => {
    switch (cat) {
      case 'A': return 'cat-badge cat-a';
      case 'B': return 'cat-badge cat-b';
      case 'C': return 'cat-badge cat-c';
      default: return 'cat-badge';
    }
  };

  return (
    <div className="sku-management">
      <div className="sku-content">
        {/* Page Header */}
        <div className="sku-page-header">
          <div>
            <h2 className="sku-page-title">The SKU ledger</h2>
            <p className="sku-page-subtitle">
              Add, edit, deactivate, or remove products from the inventory system. The master record the forecasts draw from.
            </p>
          </div>
          <button className="add-sku-btn" onClick={() => setIsModalOpen(true)}>
            <Plus size={16} />
            Add SKU
          </button>
        </div>

        {/* Summary Cards */}
        <div className="sku-summary-grid">
          <div className="sku-summary-card summary-total">
            <span className="summary-label">TOTAL SKUS</span>
            <span className="summary-value">{totalSKUs}</span>
          </div>
          <div className="sku-summary-card summary-active">
            <span className="summary-label">ACTIVE</span>
            <span className="summary-value">{activeSKUs}</span>
          </div>
          <div className="sku-summary-card summary-inactive">
            <span className="summary-label">INACTIVE</span>
            <span className="summary-value">{inactiveSKUs}</span>
          </div>
        </div>

        {/* Filters Row */}
        <div className="sku-filters-row">
          <div className="sku-search-wrapper">
            <svg className="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              type="text"
              placeholder="Search by code, name, or brand..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="sku-search-input"
            />
          </div>

          <div className="sku-filter-controls">
            <select
              value={supplierFilter}
              onChange={(e) => setSupplierFilter(e.target.value)}
              className="sku-filter-select"
            >
              {suppliers.map(s => <option key={s} value={s}>{s}</option>)}
            </select>

            <select
              value={brandFilter}
              onChange={(e) => setBrandFilter(e.target.value)}
              className="sku-filter-select"
            >
              {brands.map(b => <option key={b} value={b}>{b}</option>)}
            </select>

            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="sku-filter-select"
            >
              <option value="All">Category (A/B/C)</option>
              <option value="A">Category A</option>
              <option value="B">Category B</option>
              <option value="C">Category C</option>
            </select>

            <div className="status-toggle-group">
              {['ALL', 'ACTIVE', 'INACTIVE'].map(status => (
                <button
                  key={status}
                  className={`status-toggle-btn ${statusFilter === status ? 'active' : ''}`}
                  onClick={() => setStatusFilter(status)}
                >
                  {status}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Table */}
        <div className="sku-table-wrapper">
          <table className="sku-table">
            <thead>
              <tr>
                <th>#</th>
                <th>SKU CODE</th>
                <th>BRAND</th>
                <th>SUPPLIER</th>
                <th>PRODUCT</th>
                <th>CAT</th>
                <th>LEAD TIME (DAYS)</th>
                <th>REORDER PT</th>
                <th>STATUS</th>
                <th>ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {filteredSKUs.map((sku) => (
                <tr key={sku.id}>
                  <td className="row-number">{sku.id}</td>
                  <td className="sku-code-cell">{sku.code}</td>
                  <td>{sku.brand}</td>
                  <td className="supplier-cell">{sku.supplier}</td>
                  <td className="product-cell">
                    {(() => {
                      const { name, weight } = parseProductAndWeight(sku.product);
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                          <span className="sku-product-name">{name}</span>
                          {weight && (
                            <span className="sku-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                              {weight}
                            </span>
                          )}
                        </div>
                      );
                    })()}
                  </td>
                  <td><span className={getCatClass(sku.cat)}>{sku.cat}</span></td>
                  <td>{sku.leadTime}</td>
                  <td className="reorder-cell">{sku.reorderPt.toLocaleString()}</td>
                  <td>
                    <span className={`status-badge ${sku.status === 'ACTIVE' ? 'status-active' : 'status-inactive'}`}>
                      {sku.status}
                    </span>
                  </td>
                  <td>
                    <button className="view-btn">View</button>
                  </td>
                </tr>
              ))}
              {filteredSKUs.length === 0 && (
                <tr>
                  <td colSpan="10" className="no-results">No SKUs found matching your filters.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <AddSKUModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onAdd={handleAddSKU}
      />
    </div>
  );
};

export default SKUManagement;
