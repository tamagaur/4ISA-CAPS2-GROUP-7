import React from 'react';
import KPICard from './KPICard';
import DateFilter from './DateFilter';
import {
  SalesVsStockWidget, ABCDonutWidget, CategoryStockBarWidget,
  PortfolioForecastWidget, ReorderRecommendationWidget,
} from './Charts';
import { Package, Wallet, ShieldAlert, Target } from 'lucide-react';
import './Dashboard.css';
import './Charts.css';

// ── LAYOUT-ONLY MOCK DATA ────────────────────────────────────────────────
// This dashboard is being rebuilt against the hand-drawn wireframe (5 KPI
// cards, Sales vs. Stock on Hand hero chart with the suppliers' fixed
// allocation line, ABC donut, and the per-category stock matrix). None of
// it is wired to the backend yet — per the anti-fabrication principle,
// everything below is clearly-mock, deliberately unrealistic-looking
// placeholder data, not a stand-in for real figures. Swap this block out
// once the real endpoints for these five widgets exist.
const MOCK_SALES_VS_STOCK = [
  { period: 'Jan', sales: 42000, stockOnHand: 58000 },
  { period: 'Feb', sales: 45500, stockOnHand: 55000 },
  { period: 'Mar', sales: 41000, stockOnHand: 60000 },
  { period: 'Apr', sales: 47000, stockOnHand: 57500 },
  { period: 'May', sales: 50500, stockOnHand: 53000 },
  { period: 'Jun', sales: 48000, stockOnHand: 51000 },
  { period: 'Jul', sales: 52000, stockOnHand: 49500 },
  { period: 'Aug', sales: 49500, stockOnHand: 54000 },
  { period: 'Sep', sales: 46500, stockOnHand: 56500 },
  { period: 'Oct', sales: 51000, stockOnHand: 52500 },
  { period: 'Nov', sales: 53500, stockOnHand: 50000 },
  { period: 'Dec', sales: 57000, stockOnHand: 47500 },
];
const MOCK_FIXED_ALLOCATION = 52000;

const MOCK_ABC_DATA = [
  { tier: 'A', count: 48, sharePct: 78 },
  { tier: 'B', count: 112, sharePct: 15 },
  { tier: 'C', count: 260, sharePct: 7 },
];

const MOCK_CATEGORY_STOCK = [
  { category: 'Deo', tier: 'A', deadStock: 320, inStock: 1850 },
  { category: 'Snacks', tier: 'A', deadStock: 180, inStock: 2100 },
  { category: 'Personal Care', tier: 'B', deadStock: 410, inStock: 1200 },
  { category: 'Fragrance', tier: 'B', deadStock: 260, inStock: 980 },
  { category: 'Seasoning', tier: 'C', deadStock: 540, inStock: 610 },
  { category: 'Canned Goods', tier: 'C', deadStock: 390, inStock: 520 },
];

// Actual demand for Wk 1-8, then SARIMA forecast + confidence band for
// Wk 8-12, sharing the Wk 8 point so the two lines read as continuous —
// same shape as the reference screenshot.
const MOCK_PORTFOLIO_FORECAST = [
  { period: 'Wk 1', actual: 18500 },
  { period: 'Wk 2', actual: 19200 },
  { period: 'Wk 3', actual: 20100 },
  { period: 'Wk 4', actual: 21400 },
  { period: 'Wk 5', actual: 21800 },
  { period: 'Wk 6', actual: 21200 },
  { period: 'Wk 7', actual: 22600 },
  { period: 'Wk 8', actual: 24000, forecast: 24000, confidenceLower: 24000, confidenceUpper: 24000 },
  { period: 'Wk 9', forecast: 24800, confidenceLower: 23600, confidenceUpper: 26200 },
  { period: 'Wk 10', forecast: 25600, confidenceLower: 23200, confidenceUpper: 28200 },
  { period: 'Wk 11', forecast: 26400, confidenceLower: 23000, confidenceUpper: 30200 },
  { period: 'Wk 12', forecast: 27200, confidenceLower: 22800, confidenceUpper: 32200 },
];

const MOCK_REORDER_ROWS = [
  { sku: 'SKU-00231', product: 'Dove Shampoo 340ml', urgency: 'CRITICAL', orderQty: 420 },
  { sku: 'SKU-00118', product: 'Knorr Cubes 8g', urgency: 'CRITICAL', orderQty: 610 },
  { sku: 'SKU-00305', product: 'Surf Powder Detergent 1kg', urgency: 'URGENT', orderQty: 260 },
  { sku: 'SKU-00092', product: 'Close-Up Toothpaste 160g', urgency: 'URGENT', orderQty: 190 },
  { sku: 'SKU-00447', product: 'Lipton Iced Tea 25s', urgency: 'PLANNED', orderQty: 340 },
];

const Dashboard = () => {
  return (
    <div className="dashboard">
      <div className="dashboard-content">
        <div className="dashboard-header">
          <div className="dashboard-title-row">
            <h2>Inventory <span>pulse</span></h2>
            <DateFilter />
          </div>
          <p>Inventory and ordering overview — SSM Urdaneta warehouse</p>
        </div>

        {/* ── 4 KPI cards ────────────────────────────────────────────── */}
        <div className="dashboard-section">
          <div className="kpi-grid">
            <KPICard
              title="Sales"
              value="₱48,000"
              metricType="recommendation"
              contextLine="This period's total sales"
              icon={<Wallet size={20} />}
            />
            <KPICard
              title="SOH value"
              value="₱6.4M"
              metricType="recommendation"
              contextLine="Stock-on-hand valuation"
              icon={<Package size={20} />}
            />
            <KPICard
              title="Safety stock rate"
              value="82%"
              metricType="recommendation"
              contextLine="Share of SKUs at/above safety stock"
              icon={<ShieldAlert size={20} />}
            />
            <KPICard
              title="Fixed point ratio"
              value="0.94"
              metricType="recommendation"
              contextLine="Stock on hand vs. fixed allocation"
              icon={<Target size={20} />}
            />
          </div>
        </div>

        {/* ── Sales vs. Stock on Hand — hero chart ──────────────────────── */}
        <div className="dashboard-section">
          <div className="chart-primary">
            <SalesVsStockWidget data={MOCK_SALES_VS_STOCK} fixedAllocation={MOCK_FIXED_ALLOCATION} />
          </div>
        </div>

        {/* ── ABC donut + category stock matrix ─────────────────────────── */}
        <div className="dashboard-section">
          <div className="chart-duo chart-duo-abc">
            <ABCDonutWidget data={MOCK_ABC_DATA} />
            <CategoryStockBarWidget data={MOCK_CATEGORY_STOCK} />
          </div>
        </div>

        {/* ── Portfolio-level aggregate forecast + reorder recommendations ── */}
        <div className="dashboard-section">
          <div className="chart-duo">
            <PortfolioForecastWidget
              series={MOCK_PORTFOLIO_FORECAST}
              gatedSkuCount={142}
              avgMape={12.4}
              scopeLabel="Unilever only"
            />
            <ReorderRecommendationWidget
              rows={MOCK_REORDER_ROWS}
              criticalCount={2}
              urgentCount={2}
              totalOrderQty={1820}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
