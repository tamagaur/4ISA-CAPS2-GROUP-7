// The introduction on the sign-in page (2026-10-19, Audrey's golden-hour
// redesign), standing on the yard to the left of the card: the eyebrow,
// the headline, a line on what the dashboard does, and three feature
// items. (The mock-up's two floating chart cards beside the words were
// taken out the same day at Audrey's request.) Styles: LoginPage.css
// (.login-hero, .login-intro, .login-features).
import React from 'react';
import { ChartColumn, PackageCheck, Users } from 'lucide-react';

export default function LoginHero() {
  return (
    <>
      <div className="login-intro">
        <p className="login-eyebrow">Inventory Decision Support Dashboard</p>
        {/* One span per line, so the lines can rise one after the other
            when the page opens (LoginPage.css, login-rise). */}
        <h1 className="login-headline">
          <span className="login-headline-line">Smarter Inventory</span>
          <span className="login-headline-line">Decisions for a</span>
          <span className="login-headline-line">
            <span className="login-headline-accent">Stronger</span> Tomorrow
          </span>
        </h1>
        <p className="login-lede">
          Turn sales data into actionable inventory decisions. Forecast demand,
          optimize orders, and keep essential products on shelves.
        </p>
      </div>

      <ul className="login-features">
        <li className="login-feature">
          <span className="login-feature-icon"><ChartColumn aria-hidden="true" /></span>
          <span>Data-driven<br />forecasting</span>
        </li>
        <li className="login-feature">
          <span className="login-feature-icon"><PackageCheck aria-hidden="true" /></span>
          <span>Optimized<br />reorder plans</span>
        </li>
        <li className="login-feature">
          <span className="login-feature-icon"><Users aria-hidden="true" /></span>
          <span>Built for<br />SSM teams</span>
        </li>
      </ul>
    </>
  );
}
