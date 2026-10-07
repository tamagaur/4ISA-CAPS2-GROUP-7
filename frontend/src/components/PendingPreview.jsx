// /preview — cards built but held back from the real pages, on SAMPLE data,
// so the team can see and judge them. Nothing here is SSM's data and
// nothing here is linked from the app's navigation. The other section B
// cards went live with the kelvin-etl merge (PendingCards.jsx header).
import React from 'react';
import { AccuracyLevels } from './PendingCards';

const SAMPLE = {
  accuracy: { product_pct: 35.0, category_pct: 18.4, total_pct: 9.6 },
};

const PendingPreview = () => (
  <div className="pending-preview">
    <h2>Cards held <span className="page-title-accent">back</span></h2>
    <p className="pending-preview-banner">
      <strong>Sample data — not SSM&apos;s.</strong> Every figure on this page is made up to show the layout.
    </p>

    <section>
      <h3>Accuracy colours, at three levels</h3>
      <p className="pending-preview-where">
        Goes on: SKU Forecast. Held back (SHOW_ACCURACY_PCT): the Technical Adviser asked for no bare percentage
        on screen; the forecast miss is shown in pieces and pesos instead.
      </p>
      <AccuracyLevels accuracy={SAMPLE.accuracy} />
    </section>
  </div>
);

export default PendingPreview;
