// /preview — the section B cards (PendingCards.jsx) on SAMPLE data, so the
// team can see and judge each screen before its endpoint exists. Nothing
// here is SSM's data and nothing here is linked from the app's navigation:
// on the real pages each card appears only once the backend serves its
// field.
import React from 'react';
import {
  AccuracyLevels, ClassChanges, ForecastErrorCard, ReviewBadge, StockLimitedNote,
} from './PendingCards';
import ProductName from './ProductName';

const SAMPLE = {
  error: {
    pieces_per_month: 112, pesos_per_month: 3360, direction: 'surplus', direction_months: 4,
    months_scored: 6, window_start: '2025-09', window_end: '2026-02',
  },
  accuracy: { product_pct: 35.0, category_pct: 18.4, total_pct: 9.6 },
  stockLimited: ['2025-12'],
  changes: {
    period: '2026-02', previous_period: '2026-01',
    entered: [
      { sku_id: 'SAMPLE-001', product_name: 'Sample product A 24x15ml', revenue: 412000, previous_revenue: 268000 },
      { sku_id: 'SAMPLE-002', product_name: 'Sample product B 12x100g', revenue: 305000, previous_revenue: 241000 },
    ],
    left: [
      { sku_id: 'SAMPLE-003', product_name: 'Sample product C 48x11g', revenue: 96000, previous_revenue: 287000 },
    ],
  },
};

const PendingPreview = () => (
  <div className="pending-preview">
    <h2>Cards waiting on <span className="page-title-accent">data</span></h2>
    <p className="pending-preview-banner">
      <strong>Sample data — not SSM&apos;s.</strong> These screens are built and ready; every figure on this page is
      made up to show the layout. On the real pages each one appears only when the backend serves its data.
    </p>

    <section>
      <h3>Forecast miss in pieces and pesos</h3>
      <p className="pending-preview-where">Goes on: SKU Forecast, beside the forecast. Replaces the percentage.</p>
      <ForecastErrorCard error={SAMPLE.error} />
    </section>

    <section>
      <h3>Accuracy colours, at three levels</h3>
      <p className="pending-preview-where">Goes on: SKU Forecast. Held back until the accuracy figures are recomputed.</p>
      <AccuracyLevels accuracy={SAMPLE.accuracy} />
    </section>

    <section>
      <h3>&ldquo;Review before ordering&rdquo; badge and stock on order</h3>
      <p className="pending-preview-where">
        Goes on: Reorder Recs. A flagged row is left out of &ldquo;Accept all in view&rdquo;; the on-order column
        appears once purchase orders are loaded.
      </p>
      <table className="pending-preview-table">
        <thead>
          <tr><th>Product</th><th>Suggested qty (pieces)</th><th>On order, not yet arrived (pieces)</th><th>Urgency</th></tr>
        </thead>
        <tbody>
          <tr>
            <td><ProductName name="Sample product D 288x13ml" code="SAMPLE-674" /></td>
            <td>20,714</td>
            <td>4,320</td>
            <td>
              CRITICAL<br />
              <ReviewBadge reason="Sales collapsed in the last 3 months; the forecast may be far too high." />
            </td>
          </tr>
          <tr>
            <td><ProductName name="Sample product E 60x28ml" code="SAMPLE-101" /></td>
            <td>1,327</td>
            <td>0</td>
            <td>URGENT</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section>
      <h3>Possibly stock-limited months</h3>
      <p className="pending-preview-where">Goes on: SKU Forecast, under the chart.</p>
      <StockLimitedNote periods={SAMPLE.stockLimited} />
    </section>

    <section>
      <h3>Entered / left Class A</h3>
      <p className="pending-preview-where">Goes on: Dashboard, under the ABC cards.</p>
      <ClassChanges changes={SAMPLE.changes} />
    </section>
  </div>
);

export default PendingPreview;
