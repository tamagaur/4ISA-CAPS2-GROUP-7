import React, { useState, useMemo, useRef, useEffect } from 'react';
import { Plus, Search, Clock, X, RotateCcw, Building, Tag, Layers, Filter, CheckCircle, XCircle, Package } from 'lucide-react';
import AddSKUModal from './AddSKUModal';
import ViewSKUModal from './ViewSKUModal';
import EditSKUModal from './EditSKUModal';
import { logAction } from '../utils/auditLogger';
import './SKUManagement.css';

const mockSKUs = [
  { 
    id: '001', 
    code: 'SKU-10234', 
    brand: 'Del Monte', 
    supplier: 'Del Monte Philippines', 
    product: 'Pineapple Juice 1L', 
    cat: 'A', 
    leadTime: '7 days', 
    reorderPt: 800, 
    status: 'ACTIVE',
    currentStock: 420,
    unitPrice: 65.00,
    avgSalesPerMonth: 9800,
    lastOrderDate: '2026-04-15',
    notes: 'High-velocity SKU. Monitor stock weekly.'
  },
  { 
    id: '002', 
    code: 'SKU-10198', 
    brand: 'Unilever', 
    supplier: 'Unilever Philippines', 
    product: 'Knorr Cubes 8g', 
    cat: 'A', 
    leadTime: '5 days', 
    reorderPt: 600, 
    status: 'ACTIVE',
    currentStock: 980,
    unitPrice: 15.50,
    avgSalesPerMonth: 8200,
    lastOrderDate: '2026-03-20',
    notes: 'Fast-moving culinary basic. Minimum reorder batch size is 20 master boxes.'
  },
  { 
    id: '003', 
    code: 'SKU-10456', 
    brand: 'Del Monte', 
    supplier: 'Del Monte Philippines', 
    product: 'Spaghetti Sauce 500g', 
    cat: 'A', 
    leadTime: '6 days', 
    reorderPt: 500, 
    status: 'ACTIVE',
    currentStock: 620,
    unitPrice: 48.00,
    avgSalesPerMonth: 3900,
    lastOrderDate: '2026-03-10',
    notes: 'Q4 holiday volume driver.'
  },
  { 
    id: '004', 
    code: 'SKU-10789', 
    brand: 'Unilever', 
    supplier: 'Unilever Philippines', 
    product: 'Surf Powder Detergent 1kg', 
    cat: 'A', 
    leadTime: '4 days', 
    reorderPt: 1200, 
    status: 'ACTIVE',
    currentStock: 1450,
    unitPrice: 110.00,
    avgSalesPerMonth: 11000,
    lastOrderDate: '2026-03-25',
    notes: 'Top tier Category A revenue generator.'
  },
  { 
    id: '005', 
    code: 'SKU-10112', 
    brand: 'Del Monte', 
    supplier: 'Del Monte Philippines', 
    product: 'Sweet Corn Kernel 425g', 
    cat: 'A', 
    leadTime: '7 days', 
    reorderPt: 400, 
    status: 'ACTIVE',
    currentStock: 530,
    unitPrice: 38.50,
    avgSalesPerMonth: 2800,
    lastOrderDate: '2026-03-02',
    notes: ''
  },
  { 
    id: '006', 
    code: 'SKU-20101', 
    brand: 'Del Monte', 
    supplier: 'Del Monte Philippines', 
    product: 'Tomato Sauce 250g', 
    cat: 'B', 
    leadTime: '7 days', 
    reorderPt: 800, 
    status: 'ACTIVE',
    currentStock: 740,
    unitPrice: 24.00,
    avgSalesPerMonth: 4100,
    lastOrderDate: '2026-02-28',
    notes: 'Steady steady-state sales velocity.'
  },
  { 
    id: '007', 
    code: 'SKU-20145', 
    brand: 'Unilever', 
    supplier: 'Unilever Philippines', 
    product: 'Dove Shampoo 340ml', 
    cat: 'B', 
    leadTime: '5 days', 
    reorderPt: 300, 
    status: 'ACTIVE',
    currentStock: 410,
    unitPrice: 195.00,
    avgSalesPerMonth: 1600,
    lastOrderDate: '2026-03-12',
    notes: 'Premium personal care category.'
  },
  { 
    id: '008', 
    code: 'SKU-20289', 
    brand: 'Del Monte', 
    supplier: 'Del Monte Philippines', 
    product: 'Fruit Cocktail 432g', 
    cat: 'B', 
    leadTime: '6 days', 
    reorderPt: 200, 
    status: 'ACTIVE',
    currentStock: 310,
    unitPrice: 72.00,
    avgSalesPerMonth: 1900,
    lastOrderDate: '2026-03-18',
    notes: ''
  },
  { 
    id: '009', 
    code: 'SKU-30856', 
    brand: 'Unilever', 
    supplier: 'Unilever Philippines', 
    product: 'Ponds Face Cream 50g', 
    cat: 'C', 
    leadTime: '5 days', 
    reorderPt: 150, 
    status: 'ACTIVE',
    currentStock: 220,
    unitPrice: 145.00,
    avgSalesPerMonth: 950,
    lastOrderDate: '2026-02-14',
    notes: 'Category C low-velocity item.'
  },
  { 
    id: '010', 
    code: 'SKU-99999', 
    brand: 'Del Monte', 
    supplier: 'Del Monte Philippines', 
    product: 'Ketchup 320g (Discontinued)', 
    cat: 'C', 
    leadTime: 'N/A', 
    reorderPt: 0, 
    status: 'DISABLED',
    currentStock: 0,
    unitPrice: 32.00,
    avgSalesPerMonth: 0,
    lastOrderDate: '2025-11-01',
    notes: 'Discontinued product line. Depleted remaining stock.'
  },
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

const SKUManagement = () => {
  const [skus, setSkus] = useState(mockSKUs);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isViewModalOpen, setIsViewModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  
  const [selectedSKU, setSelectedSKU] = useState(null);
  const [editingSKU, setEditingSKU] = useState(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [supplierFilter, setSupplierFilter] = useState('All Suppliers');
  const [brandFilter, setBrandFilter] = useState('All Brands');
  const [categoryFilter, setCategoryFilter] = useState('All');
  
  const [activeTab, setActiveTab] = useState('ALL'); // 'ALL' | 'ACTIVE' | 'DISABLED'

  // Combobox & Highlight State
  const [isComboboxOpen, setIsComboboxOpen] = useState(false);
  const [highlightedSKUId, setHighlightedSKUId] = useState(null);
  const comboboxRef = useRef(null);

  // Persistent Recently Viewed SKUs (max 5)
  const [recentlyViewedSKUs, setRecentlyViewedSKUs] = useState(() => {
    try {
      const saved = localStorage.getItem('san2_recent_sku_views');
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
      const matchesStatus = activeTab === 'ALL' || sku.status === activeTab;
      return matchesSearch && matchesSupplier && matchesBrand && matchesCategory && matchesStatus;
    });
  }, [skus, searchQuery, supplierFilter, brandFilter, categoryFilter, activeTab]);

  const totalSKUs = skus.length;
  const activeSKUs = skus.filter(s => s.status === 'ACTIVE').length;
  const inactiveSKUs = skus.filter(s => s.status === 'DISABLED').length;

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
      currentStock: parseInt(formData.initialStock) || 0,
      unitPrice: parseFloat(formData.unitPrice) || 0,
      avgSalesPerMonth: 1500,
      lastOrderDate: new Date().toISOString().split('T')[0],
      notes: formData.notes || ''
    };
    setSkus(prev => [...prev, newSKU]);
    
    // Log the addition
    logAction('Add SKU', `Added new SKU: ${newSKU.code} (${newSKU.product})`);
  };

  const handleOpenViewModal = (sku) => {
    setSelectedSKU(sku);
    setIsViewModalOpen(true);

    // Track recently viewed SKU (max 5)
    setRecentlyViewedSKUs(prev => {
      const filtered = prev.filter(s => s.id !== sku.id);
      const updated = [sku, ...filtered].slice(0, 5);
      try {
        localStorage.setItem('san2_recent_sku_views', JSON.stringify(updated));
      } catch (err) {
        console.error('Failed to save recent view', err);
      }
      return updated;
    });
  };

  const handleOpenEditModal = (sku) => {
    setIsViewModalOpen(false);
    setEditingSKU(sku);
    setIsEditModalOpen(true);
  };

  const handleSaveSKU = (updatedSKU) => {
    const previousSKU = skus.find(s => s.id === updatedSKU.id);
    
    // Determine what changed for the audit log
    const changes = [];
    if (previousSKU) {
      if (previousSKU.product !== updatedSKU.product) changes.push(`Product Name: ${previousSKU.product} -> ${updatedSKU.product}`);
      if (previousSKU.brand !== updatedSKU.brand) changes.push(`Brand: ${previousSKU.brand} -> ${updatedSKU.brand}`);
      if (previousSKU.cat !== updatedSKU.cat) changes.push(`Category: ${previousSKU.cat} -> ${updatedSKU.cat}`);
      if (previousSKU.reorderPt !== updatedSKU.reorderPt) changes.push(`Reorder Pt: ${previousSKU.reorderPt} -> ${updatedSKU.reorderPt}`);
      if (previousSKU.unitPrice !== updatedSKU.unitPrice) changes.push(`Unit Price: ${previousSKU.unitPrice} -> ${updatedSKU.unitPrice}`);
      if (previousSKU.status !== updatedSKU.status) changes.push(`Status: ${previousSKU.status} -> ${updatedSKU.status}`);
    }

    setSkus(prev => prev.map(s => s.id === updatedSKU.id ? updatedSKU : s));
    setSelectedSKU(updatedSKU);
    
    // Log the edit
    const details = changes.length > 0 
      ? `Updated SKU ${updatedSKU.code}. Changes: ${changes.join(', ')}`
      : `Updated SKU ${updatedSKU.code} (minor details)`;
      
    logAction('Edit SKU', details);
  };

  // Handle selecting a combobox suggestion row
  const handleSelectSuggestion = (sku) => {
    setSearchQuery(sku.code);
    setIsComboboxOpen(false);

    // Highlight target row and scroll smoothly to it
    setHighlightedSKUId(sku.id);
    setTimeout(() => {
      const el = document.getElementById(`sku-row-${sku.id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 80);

    // Clear flash highlight after 2s
    setTimeout(() => {
      setHighlightedSKUId(null);
    }, 2000);
  };

  const hasActiveFilters =
    searchQuery !== '' ||
    supplierFilter !== 'All Suppliers' ||
    brandFilter !== 'All Brands' ||
    categoryFilter !== 'All';

  const handleClearFilters = () => {
    setSearchQuery('');
    setSupplierFilter('All Suppliers');
    setBrandFilter('All Brands');
    setCategoryFilter('All');
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
            <h2 className="sku-page-title">SKU Ledger</h2>
            <p className="sku-page-subtitle">
              Add, edit, deactivate, or remove products from the inventory system. The master record the forecasts draw from.
            </p>
          </div>
          <button className="add-sku-btn" onClick={() => setIsAddModalOpen(true)}>
            <Plus size={16} />
            Add SKU
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="sku-top-tabs">
          <button 
            className={`sku-tab-btn ${activeTab === 'ALL' ? 'active' : ''}`}
            onClick={() => setActiveTab('ALL')}
          >
            <Package size={16} color="#3b82f6" className="sku-tab-icon" />
            All SKUs
          </button>
          <button 
            className={`sku-tab-btn ${activeTab === 'ACTIVE' ? 'active' : ''}`}
            onClick={() => setActiveTab('ACTIVE')}
          >
            <CheckCircle size={16} color="#38a169" className="sku-tab-icon" />
            Active SKUs
          </button>
          <button 
            className={`sku-tab-btn ${activeTab === 'DISABLED' ? 'active' : ''}`}
            onClick={() => setActiveTab('DISABLED')}
          >
            <XCircle size={16} color="#e53e3e" className="sku-tab-icon" />
            Disabled SKUs
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
            <span className="summary-label">DISABLED</span>
            <span className="summary-value">{inactiveSKUs}</span>
          </div>
        </div>

        {/* Filters Row */}
        <div className="sku-filters-row">
          {/* Searchable Combobox */}
          <div className="sku-combobox-container" ref={comboboxRef}>
            <div className="sku-search-wrapper">
              <Search className="search-icon" size={16} />
              <input
                type="text"
                placeholder="Search by code, name, or brand..."
                value={searchQuery}
                onFocus={() => setIsComboboxOpen(true)}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setIsComboboxOpen(true);
                }}
                className="sku-search-input"
              />
              {searchQuery && (
                <button
                  className="sku-input-clear-btn"
                  onClick={() => setSearchQuery('')}
                  title="Clear search"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Combobox Dropdown Panel */}
            {isComboboxOpen && (
              <div className="sku-combobox-dropdown">
                {searchQuery.trim() !== '' ? (
                  /* Live Matching Suggestions */
                  <div className="sku-combobox-section">
                    <div className="sku-section-header">
                      <span>SUGGESTIONS ({filteredSKUs.length})</span>
                    </div>
                    {filteredSKUs.length > 0 ? (
                      filteredSKUs.map((sku) => (
                        <div
                          key={sku.id}
                          className="sku-suggestion-row"
                          onClick={() => handleSelectSuggestion(sku)}
                        >
                          <div className="sku-row-left">
                            <span className="sku-row-code">{sku.code}</span>
                            <span className="sku-row-brand">{sku.brand}</span>
                          </div>
                          <div className="sku-row-middle">
                            <span className="sku-row-product">{sku.product}</span>
                            <span className="sku-row-supplier">{sku.supplier}</span>
                          </div>
                          <div className="sku-row-right">
                            <span className={getCatClass(sku.cat)}>{sku.cat}</span>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="sku-no-suggestions">No matching SKUs found.</div>
                    )}
                  </div>
                ) : (
                  /* Quick Access Panel when search input is focused with no query */
                  <div className="sku-combobox-default">
                    {recentlyViewedSKUs.length > 0 ? (
                      <div className="sku-combobox-section">
                        <div className="sku-section-header">
                          <Clock size={12} />
                          <span>RECENTLY VIEWED</span>
                        </div>
                        {recentlyViewedSKUs.map((sku) => (
                          <div
                            key={sku.id}
                            className="sku-suggestion-row"
                            onClick={() => handleSelectSuggestion(sku)}
                          >
                            <div className="sku-row-left">
                              <span className="sku-row-code">{sku.code}</span>
                              <span className="sku-row-brand">{sku.brand}</span>
                            </div>
                            <div className="sku-row-middle">
                              <span className="sku-row-product">{sku.product}</span>
                              <span className="sku-row-supplier">{sku.supplier}</span>
                            </div>
                            <div className="sku-row-right">
                              <span className={getCatClass(sku.cat)}>{sku.cat}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="sku-combobox-section">
                        <div className="sku-section-header">
                          <span>RECENT SKUS</span>
                        </div>
                        {filteredSKUs.slice(0, 5).map((sku) => (
                          <div
                            key={sku.id}
                            className="sku-suggestion-row"
                            onClick={() => handleSelectSuggestion(sku)}
                          >
                            <div className="sku-row-left">
                              <span className="sku-row-code">{sku.code}</span>
                              <span className="sku-row-brand">{sku.brand}</span>
                            </div>
                            <div className="sku-row-middle">
                              <span className="sku-row-product">{sku.product}</span>
                              <span className="sku-row-supplier">{sku.supplier}</span>
                            </div>
                            <div className="sku-row-right">
                              <span className={getCatClass(sku.cat)}>{sku.cat}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Filter Controls Row: Icon-Labeled Wrappers */}
          <div className="sku-filter-controls">
            <div className="sku-filter-select-wrapper">
              <span className="sku-filter-icon-label"><Building size={12} /> Supplier:</span>
              <select
                value={supplierFilter}
                onChange={(e) => setSupplierFilter(e.target.value)}
              >
                {suppliers.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>

            <div className="sku-filter-select-wrapper">
              <span className="sku-filter-icon-label"><Tag size={12} /> Brand:</span>
              <select
                value={brandFilter}
                onChange={(e) => setBrandFilter(e.target.value)}
              >
                {brands.map(b => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>

            <div className="sku-filter-select-wrapper">
              <span className="sku-filter-icon-label"><Layers size={12} /> Category:</span>
              <select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
              >
                <option value="All">Category (A/B/C)</option>
                <option value="A">Category A</option>
                <option value="B">Category B</option>
                <option value="C">Category C</option>
              </select>
            </div>
          </div>
        </div>

        {/* Active Filter Chips Bar */}
        {hasActiveFilters && (
          <div className="sku-active-chips-row">
            <span className="chips-label">
              <Filter size={12} /> Active Filters:
            </span>

            {searchQuery && (
              <span className="sku-active-chip">
                Search: "{searchQuery}"
                <button className="sku-chip-remove" onClick={() => setSearchQuery('')}>
                  <X size={12} />
                </button>
              </span>
            )}

            {supplierFilter !== 'All Suppliers' && (
              <span className="sku-active-chip">
                Supplier: {supplierFilter}
                <button className="sku-chip-remove" onClick={() => setSupplierFilter('All Suppliers')}>
                  <X size={12} />
                </button>
              </span>
            )}

            {brandFilter !== 'All Brands' && (
              <span className="sku-active-chip">
                Brand: {brandFilter}
                <button className="sku-chip-remove" onClick={() => setBrandFilter('All Brands')}>
                  <X size={12} />
                </button>
              </span>
            )}

            {categoryFilter !== 'All' && (
              <span className="sku-active-chip">
                Category: Category {categoryFilter}
                <button className="sku-chip-remove" onClick={() => setCategoryFilter('All')}>
                  <X size={12} />
                </button>
              </span>
            )}

            <button
              className="clear-all-chips-btn"
              onClick={handleClearFilters}
              title="Reset all filters and search query"
            >
              <RotateCcw size={12} />
              Clear all filters
            </button>
          </div>
        )}

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
                <tr
                  key={sku.id}
                  id={`sku-row-${sku.id}`}
                  className={highlightedSKUId === sku.id ? 'highlighted-row-flash' : ''}
                >
                  <td className="row-number">{sku.id}</td>
                  <td 
                    className="sku-code-cell" 
                    style={{ cursor: 'pointer' }}
                    onClick={() => handleOpenViewModal(sku)}
                    title="Click to view full SKU details"
                  >
                    {sku.code}
                  </td>
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
                    <button 
                      className="view-btn"
                      onClick={() => handleOpenViewModal(sku)}
                    >
                      View
                    </button>
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
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onAdd={handleAddSKU}
        brands={brands.filter(b => b !== 'All Brands')}
        suppliers={suppliers.filter(s => s !== 'All Suppliers')}
      />

      <ViewSKUModal
        isOpen={isViewModalOpen}
        sku={selectedSKU}
        onClose={() => setIsViewModalOpen(false)}
        onEdit={handleOpenEditModal}
      />

      <EditSKUModal
        isOpen={isEditModalOpen}
        sku={editingSKU}
        onClose={() => setIsEditModalOpen(false)}
        onSave={handleSaveSKU}
      />
    </div>
  );
};

export default SKUManagement;
