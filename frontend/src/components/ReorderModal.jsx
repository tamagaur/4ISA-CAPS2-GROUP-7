import React from 'react';
import { X } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LabelList } from 'recharts';
import { COLORS } from '../theme/colors';
import './ReorderModal.css';

// Story #80: "why was this recommended" — LP objective weights are fixed
// per DEC (w1=0.45 cost, w2=0.35 service level, w3=0.20 capacity), so the
// weight split itself is real config, not per-SKU fabrication. The dollar/
// unit figures under each bar are derived from this item's own data.
const OBJECTIVE_WEIGHTS = [
  { key: 'cost', label: 'Cost minimization', weight: 45, color: COLORS.salesTrend },
  { key: 'service', label: 'Service level ≥ 95%', weight: 35, color: COLORS.success },
  { key: 'capacity', label: 'Warehouse capacity', weight: 20, color: COLORS.dispatched },
];

const CompareTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    const p = payload[0].payload;
    return (
      <div style={{
        backgroundColor: '#ffffff',
        border: '1px solid #e2e8f0',
        padding: '0.6rem 0.9rem',
        borderRadius: '8px',
        boxShadow: '0 4px 15px rgba(0, 0, 0, 0.08)',
        fontSize: '0.78rem',
      }}>
        <strong>{p.name}</strong>: {p.qty} units
      </div>
    );
  }
  return null;
};

const ReorderModal = ({ isOpen, onClose, data }) => {
  if (!isOpen || !data) return null;

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const savedUnits = data.threeWeekRuleQty - data.orderQty;
  const savedPct = Math.round((savedUnits / data.threeWeekRuleQty) * 100);
  const savedCost = Math.round(savedUnits * (data.unitCost || 0));

  const compareData = [
    { name: 'Three-Week Rule', qty: data.threeWeekRuleQty, fill: COLORS.gridline },
    { name: 'LP-Optimized', qty: data.orderQty, fill: COLORS.brandPrimary },
  ];

  return (
    <div className="reorder-modal-overlay" onClick={handleOverlayClick}>
      <div className="reorder-modal-card">
        {/* Header */}
        <div className="reorder-modal-header">
          <div>
            <h3 className="reorder-modal-title">Reorder: {data.product}</h3>
            <p className="reorder-modal-subtitle">
              LP optimization breakdown for this SKU's recommended order.
            </p>
          </div>
          <button className="reorder-modal-close" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Data Grid */}
        <div className="reorder-modal-grid">
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">REORDER POINT (ROP)</span>
            <span className="reorder-grid-value">{data.rop}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">CURRENT STOCK</span>
            <span className="reorder-grid-value">{data.stock}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">OPTIMAL ORDER QTY</span>
            <span className="reorder-grid-value">{data.orderQty}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">ESTIMATED COST</span>
            <span className="reorder-grid-value">{data.estCost}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">URGENCY</span>
            <span className="reorder-grid-value">{data.urgency}</span>
          </div>
          <div className="reorder-grid-item">
            <span className="reorder-grid-label">SAFETY STOCK</span>
            <span className="reorder-grid-value">{data.safetyStock ?? '—'}</span>
          </div>
        </div>

        {/* Baseline Comparison — Story #56 */}
        <div className="reorder-compare-section">
          <div className="reorder-section-header">
            <h4 className="reorder-section-title">vs. the three-week rule</h4>
            <span className="reorder-savings-badge">
              ↓ {savedPct}% fewer units · ₱{savedCost.toLocaleString()} saved this cycle
            </span>
          </div>
          <div className="reorder-compare-chart">
            <ResponsiveContainer width="100%" height={90}>
              <BarChart data={compareData} layout="vertical" margin={{ top: 0, right: 30, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#edf2f7" />
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" width={100} tick={{ fill: '#4a5568', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip content={<CompareTooltip />} cursor={{ fill: '#f7fafc' }} />
                <Bar dataKey="qty" radius={[0, 4, 4, 0]} barSize={20}>
                  <LabelList dataKey="qty" position="right" style={{ fontSize: 11, fontWeight: 700, fill: '#1a202c' }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Why this recommendation — Story #80 */}
        <div className="reorder-why-section">
          <h4 className="reorder-section-title">Why this recommendation</h4>
          <p className="reorder-why-intro">
            The LP model weighs three objectives when solving for this SKU's order quantity:
          </p>
          <div className="reorder-weight-bars">
            {OBJECTIVE_WEIGHTS.map((obj) => (
              <div className="reorder-weight-row" key={obj.key}>
                <div className="reorder-weight-label-row">
                  <span className="reorder-weight-label">{obj.label}</span>
                  <span className="reorder-weight-pct">{obj.weight}%</span>
                </div>
                <div className="reorder-weight-track">
                  <div
                    className="reorder-weight-fill"
                    style={{ width: `${obj.weight}%`, backgroundColor: obj.color }}
                  />
                </div>
              </div>
            ))}
          </div>
          <p className="reorder-why-note">
            Constraints applied: service level ≥ 95%, supplier MOQ, and warehouse capacity headroom.
            Lead time for this supplier is {data.leadTimeDays ?? '—'} days.
          </p>
        </div>
      </div>
    </div>
  );
};

export default ReorderModal;
