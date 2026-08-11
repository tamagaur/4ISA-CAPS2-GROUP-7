import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import ReorderModal from './ReorderModal';
import './ReorderRecommendations.css';

const mockReorderData = [
  { id: 1, sku: 'SKU-4721', brand: 'Unilever', product: 'Surf Powder Detergent 1kg', rop: 120, stock: 45, orderQty: 200, urgency: 'CRITICAL', estCost: '₱24,500', actionStatus: null, loadingAction: null },
  { id: 2, sku: 'SKU-8934', brand: 'Del Monte', product: 'Pineapple Juice 1L', rop: 80, stock: 12, orderQty: 180, urgency: 'CRITICAL', estCost: '₱32,400', actionStatus: null, loadingAction: null },
  { id: 3, sku: 'SKU-2891', brand: 'Unilever', product: 'Knorr Cubes 8g', rop: 150, stock: 78, orderQty: 150, urgency: 'URGENT', estCost: '₱18,750', actionStatus: null, loadingAction: null },
  { id: 4, sku: 'SKU-1523', brand: 'Del Monte', product: 'Tomato Sauce 250g', rop: 100, stock: 89, orderQty: 140, urgency: 'URGENT', estCost: '₱15,000', actionStatus: null, loadingAction: null },
  { id: 5, sku: 'SKU-7642', brand: 'Unilever', product: 'Dove Shampoo 340ml', rop: 90, stock: 56, orderQty: 120, urgency: 'PLANNED', estCost: '₱14,200', actionStatus: null, loadingAction: null },
  { id: 6, sku: 'SKU-9234', brand: 'Del Monte', product: 'Sweet Corn 425g', rop: 140, stock: 102, orderQty: 160, urgency: 'PLANNED', estCost: '₱11,700', actionStatus: null, loadingAction: null },
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

// Helper to format SKU to 5 digits (SKU-#####)
const formatSKU = (sku) => {
  if (!sku) return '';
  const match = sku.match(/^SKU-(\d+)$/i);
  if (match) {
    return `SKU-${match[1].padStart(5, '0')}`;
  }
  return sku;
};

const ReorderRecommendations = () => {
  const [data, setData] = useState(mockReorderData);
  const [selectedItem, setSelectedItem] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleOpenDetails = (item) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  const handleAction = (id, actionType) => {
    // Set loading state
    setData(prev => prev.map(item => 
      item.id === id ? { ...item, loadingAction: actionType } : item
    ));

    // Simulate API call
    setTimeout(() => {
      setData(prev => prev.map(item => 
        item.id === id ? { ...item, loadingAction: null, actionStatus: actionType } : item
      ));
    }, 800);
  };

  const getUrgencyBadge = (urgency) => {
    switch (urgency) {
      case 'CRITICAL': return 'urgency-badge badge-critical';
      case 'URGENT': return 'urgency-badge badge-urgent';
      case 'PLANNED': return 'urgency-badge badge-planned';
      default: return 'urgency-badge';
    }
  };

  const renderActionColumn = (item) => {
    if (item.loadingAction) {
      return (
        <div className="action-status-container">
          <Loader2 className="spinner-icon" size={16} />
          <span className="loading-text">Processing...</span>
        </div>
      );
    }
    
    if (item.actionStatus) {
      return (
        <div className="action-status-container">
          <span className={`status-badge status-${item.actionStatus.toLowerCase()}`}>
            {item.actionStatus === 'HOLD' ? 'ON HOLD' : item.actionStatus}
          </span>
        </div>
      );
    }

    return (
      <div className="action-buttons">
        <button className="action-btn approve-btn" onClick={() => handleAction(item.id, 'APPROVED')}>Approve</button>
        <button className="action-btn hold-btn" onClick={() => handleAction(item.id, 'HOLD')}>Hold</button>
        <button className="action-btn reject-btn" onClick={() => handleAction(item.id, 'REJECTED')}>Reject</button>
      </div>
    );
  };

  return (
    <div className="reorder-page">
      <div className="reorder-content">
        {/* Page Header */}
        <div className="reorder-page-header">
          <h2 className="reorder-page-title">
            Reorder recommendations
          </h2>
          <p className="reorder-page-subtitle">
            LP-optimized purchase quantities for Category A SKUs. Minimizes total inventory cost while preventing stockouts.
          </p>
        </div>

        {/* Summary Cards */}
        <div className="reorder-summary-grid">
          <div className="reorder-summary-card card-red">
            <div className="card-content">
              <span className="reorder-card-label">CRITICAL SKUS</span>
              <span className="reorder-card-value">2</span>
            </div>
          </div>
          <div className="reorder-summary-card card-yellow">
            <div className="card-content">
              <span className="reorder-card-label">URGENT SKUS</span>
              <span className="reorder-card-value">2</span>
              <span className="reorder-card-desc">Within 3 days</span>
            </div>
          </div>
          <div className="reorder-summary-card card-blue">
            <div className="card-content">
              <span className="reorder-card-label">LP BUDGET</span>
              <span className="reorder-card-value">₱930.4k</span>
              <span className="reorder-card-desc">LP - optimized</span>
            </div>
          </div>
          <div className="reorder-summary-card card-green">
            <div className="card-content">
              <span className="reorder-card-label">WAREHOUSE UTIL.</span>
              <span className="reorder-card-value">68%</span>
              <span className="reorder-card-desc">of capacity</span>
            </div>
          </div>
        </div>

        {/* Table */}
        <div className="reorder-table-wrapper">
          <table className="reorder-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>BRAND</th>
                <th>PRODUCT</th>
                <th>ROP</th>
                <th>CURRENT STOCK</th>
                <th>ORDER QTY</th>
                <th>URGENCY</th>
                <th>EST. COST</th>
                <th>DETAILS</th>
                <th>ACTION</th>
              </tr>
            </thead>
            <tbody>
              {data.map((item) => (
                <tr key={item.id}>
                  <td className="reorder-sku-cell">{formatSKU(item.sku)}</td>
                  <td>{item.brand}</td>
                  <td className="reorder-product-cell">
                    {(() => {
                      const { name, weight } = parseProductAndWeight(item.product);
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                          <span className="reorder-product-name">{name}</span>
                          {weight && (
                            <span className="reorder-product-weight" style={{ fontSize: '0.75rem', color: '#718096', marginTop: '0.2rem' }}>
                              {weight}
                            </span>
                          )}
                        </div>
                      );
                    })()}
                  </td>
                  <td>{item.rop}</td>
                  <td className="reorder-stock-cell">{item.stock}</td>
                  <td className="reorder-qty-cell">{item.orderQty}</td>
                  <td>
                    <span className={getUrgencyBadge(item.urgency)}>
                      {item.urgency}
                    </span>
                  </td>
                  <td className="reorder-cost-cell">{item.estCost}</td>
                  <td>
                    <button className="details-btn" onClick={() => handleOpenDetails(item)}>Details</button>
                  </td>
                  <td>
                    {renderActionColumn(item)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <ReorderModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        data={selectedItem}
      />
    </div>
  );
};

export default ReorderRecommendations;
