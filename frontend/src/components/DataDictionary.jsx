import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, BookOpen } from 'lucide-react';
import PageHeader from './ui/PageHeader';
import './DataDictionary.css';

const sections = [
  { id: 'summary', label: 'Summary' },
  { id: 'sales-stock', label: 'Sales & stock' },
  { id: 'top-products', label: 'Top products' },
];

const entries = {
  summary: [
    {
      term: 'Annual sales and allocation',
      definition: 'Sales recorded for the displayed financial year, alongside the selected supplier-allocation level.',
      method: 'The target is the prior year’s sales multiplied by the selected 103%, 105%, or 108% level. The pace compares average monthly sales so far with that level’s monthly amount. Year-to-date sales are compared with the same months in the prior year; if the months on record differ, the page marks the comparison as not like-for-like.',
    },
    {
      term: 'Inventory value',
      definition: 'The value of stock in the latest available count on or before the selected date range ends.',
      method: 'Stock is valued using each product’s last purchase price. This is a stock snapshot, not the value of purchases or sales during the selected range.',
    },
    {
      term: 'Stock cover',
      definition: 'An estimate of how long the counted stock would last at the recent sales rate.',
      method: 'Stock value is compared with average weekly sales over the 12 months up to the stock count. The card compares the result with SSM’s three-week policy. Stock is valued at purchase price while sales are at selling price, so the bases differ. Unilever’s figure is marked provisional because its stock and sales sources do not yet have a confirmed location match.',
    },
    {
      term: 'Below safety stock',
      definition: 'Counted top sellers whose available stock is below their calculated safety-stock level.',
      method: 'Only products with both a usable stock count and a safety-stock target can be compared. The displayed total is not a count of every product in the catalogue.',
    },
    {
      term: 'Pending reorders',
      definition: 'Reorder recommendations that are still waiting for a decision.',
      method: 'This reflects the current reorder-plan cycle. It is separate from the number of products below safety stock.',
    },
  ],
  'sales-stock': [
    {
      term: 'Sales',
      definition: 'Recorded sales value for the selected principal and period, shown in pesos.',
      method: 'Sales use the source’s recorded selling values. The comparison and range totals only cover months with sales on record; gaps are not silently treated alike for both principals.',
    },
    {
      term: 'Stock on hand',
      definition: 'The value of stock recorded in an inventory count for a month.',
      method: 'The chart labels stock by its count date when available. Del Monte’s records may identify only the count month, not the exact day. Inventory value uses last purchase price; this is not a unit count.',
    },
    {
      term: 'Purchases received',
      definition: 'The value of recorded stock receipts for a month, shown in the Purchases view.',
      method: 'Where purchase records are unavailable, receipts may be estimated from stock counts and sales. The chart marks estimates explicitly; estimated receipts are not a dashboard KPI.',
    },
    {
      term: 'Returns',
      definition: 'The value of returns present in the source records.',
      method: 'The Returns view uses recorded returns only. It does not fill missing return data with an estimate.',
    },
    {
      term: 'Annual sales',
      definition: 'Sales grouped by calendar year in the annual view.',
      method: 'A partial year is labelled with the months on record. In demonstration mode, generated months are visibly identified and are not presented as real results.',
    },
    {
      term: 'Missing months and estimates',
      definition: 'A missing data point can mean different things depending on the source.',
      method: 'For Unilever, a month without a sales row is treated as zero sales. For Del Monte, a missing category month means the data was not collected, not that sales were zero. Any demonstration estimates are labelled; generated data does not feed real KPIs, forecasts, ABC classifications, or the real order plan.',
    },
  ],
  'top-products': [
    {
      term: 'ABC classification',
      definition: 'A ranking that groups products by their share of recorded revenue.',
      method: 'Items are sorted from highest to lowest revenue and assigned using cumulative revenue share: Class A through 80%, Class B from 80% to 95%, and Class C from 95% onward. These are ranking cutoffs, not a promise that a fixed number of items falls into each class.',
    },
    {
      term: 'Top products / Class A',
      definition: 'The high-revenue items in the most recent applicable ABC classification run.',
      method: 'Unilever uses Class A over the latest 12 months, plus products first sold within 12 months that are Class A over the latest three months. This basis is pending Technical Adviser confirmation. Del Monte remains classified on the single-month basis; its ranked items are categories, not individual SKUs.',
    },
    {
      term: 'Classification period',
      definition: 'The month for which the ABC classes were calculated.',
      method: 'The classification period is shown separately from the dashboard’s selected sales range because a saved ABC run may be for a different period. Check the displayed period before comparing classes with the range.',
    },
    {
      term: 'Revenue share and cumulative share',
      definition: 'Revenue share is one item’s portion of total ranked revenue; cumulative share is the running total down the revenue ranking.',
      method: 'These shares determine ABC class. They describe historical revenue contribution and are not a forecast, stock-risk score, or order quantity.',
    },
  ],
};

function DictionarySection({ id, title, items }) {
  return (
    <section className="dictionary-section ui-card" id={id} aria-labelledby={`${id}-title`}>
      <header className="dictionary-section-header">
        <h3 id={`${id}-title`}>{title}</h3>
        <p>Definitions and how the dashboard figures are formed.</p>
      </header>
      <dl className="dictionary-list">
        {items.map(({ term, definition, method }) => (
          <div className="dictionary-entry" key={term}>
            <dt>{term}</dt>
            <dd>
              <p>{definition}</p>
              <p><strong>Methodology:</strong> {method}</p>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

const DataDictionary = () => (
  <main className="data-dictionary-page">
    <PageHeader
      title="Reference"
      accent="Guide"
      subtitle="Plain-language definitions and methodology for the dashboard’s Summary, Sales & stock, and Top products."
      actions={(
        <Link className="btn btn-secondary" to="/">
          <ArrowLeft size={15} aria-hidden="true" />
          Back to dashboard
        </Link>
      )}
    />

    <div className="dictionary-intro ui-card">
      <BookOpen size={20} aria-hidden="true" />
      <p>
        Figures depend on the selected principal, date range, and data mode. Where data is
        unavailable or a basis is still provisional, the dashboard labels the limitation
        rather than treating it as a measured value.
      </p>
    </div>

    <nav className="dictionary-nav" aria-label="Reference guide sections">
      {sections.map(({ id, label }) => (
        <a className="btn btn-secondary btn-sm" href={`#${id}`} key={id}>{label}</a>
      ))}
    </nav>

    <div className="dictionary-sections">
      {sections.map(({ id, label }) => (
        <DictionarySection key={id} id={id} title={label} items={entries[id]} />
      ))}
    </div>
  </main>
);

export default DataDictionary;
