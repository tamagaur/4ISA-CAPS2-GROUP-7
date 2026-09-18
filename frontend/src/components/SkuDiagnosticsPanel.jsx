import React, { useEffect, useState } from 'react';
import { ArrowUpRight, ArrowDownRight, Minus, Activity, CalendarRange, Quote } from 'lucide-react';
import { getSegment } from '../api/segment';
import { formatMonth } from '../utils/formatDate';
import { SEMANTIC } from '../theme/colors';
import './SkuDiagnosticsPanel.css';

// "Why this SKU behaves this way" — the Phase-2 diagnostic layer
// (sku_traits + sku_segment, migration 0018), read through GET /segment.
// Shown on the SKU Forecast page and inside the Reorder detail modal, so
// the one place a planner looks at a single SKU also says WHY its demand
// looks the way it does. Everything here is printed from a real column;
// the only labels this component adds are the volatility band (from the
// backend's cv_band, with the raw cv always beside it) and the plain-
// language gloss on each stability_group code (the code itself stays in
// the tooltip). bin_reason is printed verbatim — it is the pipeline's own
// explanation and must not be paraphrased into something it didn't say.

// Coefficient-of-variation bands are a display convention over the stored
// cv (thresholds live in backend/routers/segment.py: < 0.5 low, < 1.0
// medium, else high). Colours follow the app-wide rule: green = steady,
// amber = watch, red = erratic enough to act on.
const CV_BAND_META = {
  low: { label: 'Low volatility', gloss: 'steady month to month', color: SEMANTIC.healthy },
  medium: { label: 'Medium volatility', gloss: 'noticeable month-to-month swings', color: SEMANTIC.watch },
  high: { label: 'High volatility', gloss: 'erratic — spikes and gaps', color: SEMANTIC.act },
};

// Mann-Kendall trend (p < 0.05). Direction only — a rising or falling
// series isn't good or bad on its own, so these stay neutral ink, never
// green/red.
const TREND_META = {
  up: { label: 'Rising', Icon: ArrowUpRight, gloss: 'statistically significant upward trend' },
  down: { label: 'Falling', Icon: ArrowDownRight, gloss: 'statistically significant downward trend' },
  none: { label: 'No clear trend', Icon: Minus, gloss: 'no significant direction either way' },
};

// stability_group codes from reports/BINNING_ROUND1_2026-09.md (38-period
// window, 2023-01 to 2026-02).
//
// These count CATEGORY-A MEMBERSHIP, not selling months: orchestrate_segment.py
// derives them from COUNT(*) over abc_classification WHERE tier = 'A', and
// traits.py::stability_group() buckets that count (== 38 -> all_38,
// >= 30 -> at_least_30, else churn). An earlier version of this gloss
// described them as selling months, which printed a visible contradiction —
// a SKU with history_months = 31 rendered "31 selling months" beside
// "Fewer than 30 selling months". history_months is a separate trait and is
// shown in its own tile.
const STABILITY_GLOSS = {
  all_38: 'Category A in all 38 periods observed',
  at_least_30: 'Category A in at least 30 of the 38 periods',
  churn: 'Moves in and out of Category A — fewer than 30 of the 38 periods',
};

const SkuDiagnosticsPanel = ({ skuId, principal, compact = false }) => {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });

  useEffect(() => {
    if (!skuId) return undefined;
    let cancelled = false;
    setState({ status: 'loading', data: null, error: null });
    getSegment(skuId, { principal })
      .then((res) => {
        if (cancelled) return;
        setState({ status: 'loaded', data: res, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({ status: 'error', data: null, error: err.message || 'Failed to load SKU diagnostics' });
      });
    return () => { cancelled = true; };
  }, [skuId, principal]);

  const heading = (
    <div className="sku-diag-header">
      <h4 className="sku-diag-title">
        <Activity size={15} aria-hidden="true" />
        Why this SKU behaves this way
      </h4>
      {state.data?.traits?.cohort_period && (
        <span className="sku-diag-cohort" title="The ABC classification period this SKU's diagnostics were computed for">
          Cohort {formatMonth(state.data.traits.cohort_period)}
        </span>
      )}
    </div>
  );

  if (state.status === 'loading') {
    return (
      <section className={`sku-diag${compact ? ' sku-diag-compact' : ''}`} aria-busy="true">
        {heading}
        <p className="sku-diag-note" role="status">Loading diagnostics…</p>
      </section>
    );
  }

  if (state.status === 'error') {
    return (
      <section className={`sku-diag${compact ? ' sku-diag-compact' : ''}`}>
        {heading}
        <p className="sku-diag-note" role="alert">Could not load diagnostics: {state.error}</p>
      </section>
    );
  }

  const data = state.data;
  // A 404 (getSegment -> null) or a product with no Phase-2 rows: say so
  // plainly. Never a placeholder band or trend.
  if (!data || !data.analyzed) {
    return (
      <section className={`sku-diag sku-diag-unanalyzed${compact ? ' sku-diag-compact' : ''}`}>
        {heading}
        <p className="sku-diag-empty-title">Not yet analyzed</p>
        <p className="sku-diag-note">
          {data?.not_analyzed_reason
            || `No diagnostic record exists for ${skuId} — it isn't in any segmentation cohort yet.`}
        </p>
      </section>
    );
  }

  const t = data.traits;
  const band = t?.cv_band ? CV_BAND_META[t.cv_band] : null;
  const trend = t?.trend ? TREND_META[t.trend] : null;
  const TrendIcon = trend?.Icon;

  return (
    <section className={`sku-diag${compact ? ' sku-diag-compact' : ''}`}>
      {heading}

      {t && (
        <div className="sku-diag-tiles">
          {/* Volatility: the band is the headline, the raw cv sits under
              it so the label never replaces the measurement. */}
          <div className="sku-diag-tile" style={{ '--tile-accent': band?.color || SEMANTIC.noData }}>
            <span className="sku-diag-tile-label">Volatility</span>
            <span className="sku-diag-tile-value">{band ? band.label : 'Not measured'}</span>
            <span className="sku-diag-tile-desc">
              {t.cv != null ? `CV ${t.cv.toFixed(2)} · ${band.gloss}` : 'no coefficient of variation stored'}
            </span>
          </div>

          <div className="sku-diag-tile sku-diag-tile-trend">
            <span className="sku-diag-tile-label">Trend</span>
            <span className="sku-diag-tile-value">
              {TrendIcon && <TrendIcon size={18} aria-hidden="true" className="sku-diag-trend-icon" />}
              {trend ? trend.label : '—'}
            </span>
            <span className="sku-diag-tile-desc">{trend ? `${trend.gloss} (Mann-Kendall, p < 0.05)` : ''}</span>
          </div>

          <div className="sku-diag-tile">
            <span className="sku-diag-tile-label">
              <CalendarRange size={11} aria-hidden="true" /> History
            </span>
            <span className="sku-diag-tile-value">
              {t.history_months} selling month{t.history_months === 1 ? '' : 's'}
            </span>
            <span className="sku-diag-tile-desc" title={`stability_group: ${t.stability_group}`}>
              {STABILITY_GLOSS[t.stability_group] || t.stability_group}
              {t.first_sale_period ? ` · first sale ${formatMonth(t.first_sale_period)}` : ''}
              {` · longest run ${t.longest_run}`}
              {t.restart_flag ? ' · restarted after a 3+ month gap' : ''}
            </span>
          </div>
        </div>
      )}

      {/* The pipeline's own words. One block per scheme; bin_reason is
          quoted verbatim, the bin name is the label. */}
      {data.segments.length > 0 && (
        <div className="sku-diag-reasons">
          {data.segments.map((seg) => (
            <blockquote className="sku-diag-reason" key={`${seg.scheme}-${seg.abc_method}`}>
              <Quote size={13} aria-hidden="true" className="sku-diag-reason-icon" />
              <div>
                <span className="sku-diag-reason-bin">
                  {seg.bin}
                  <span className="sku-diag-reason-scheme" title="Binning scheme · ABC method">
                    {seg.scheme} · {seg.abc_method}
                  </span>
                </span>
                <p className="sku-diag-reason-text">{seg.bin_reason}</p>
              </div>
            </blockquote>
          ))}
        </div>
      )}

      {t?.revenue_share_2026_02 != null && (
        <p className="sku-diag-note">
          {(t.revenue_share_2026_02 * 100).toFixed(2)}% of Unilever revenue in the Feb 2026 classification.
        </p>
      )}
    </section>
  );
};

export default SkuDiagnosticsPanel;
