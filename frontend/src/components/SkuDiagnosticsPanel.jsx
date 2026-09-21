import React, { useEffect, useState } from 'react';
import { ArrowUpRight, ArrowDownRight, Minus, Activity, CalendarRange, Waves } from 'lucide-react';
import { getSegment } from '../api/segment';
import { getDecomposition } from '../api/analytics';
import { formatMonth } from '../utils/formatDate';
import { SEMANTIC } from '../theme/colors';
import './SkuDiagnosticsPanel.css';

// "Why this SKU behaves this way" — the Phase-2 diagnostic layer
// (sku_traits + sku_segment, migration 0018), read through GET /segment.
// Shown on the SKU Forecast page and inside the Reorder detail modal, so
// the one place a planner looks at a single SKU also says WHY its demand
// looks the way it does. Everything here is printed from a real column;
// the only labels this component adds are the volatility band (from the
// backend's cv_band, with the raw cv always beside it), the plain-
// language gloss on each stability_group code, the plain name of the
// SKU's bin (both codes stay in the tooltip), and the seasonality band
// over STL's measured strength (GET /decomposition). bin_reason is printed
// verbatim — it is the pipeline's own explanation and must not be
// paraphrased into something it didn't say.

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

// Bins of the combined_v1 scheme (sales-month length, with the long bin
// split by Mann-Kendall trend), plus length_v2's plain `long` for the
// fallback when combined_v1 is absent. The history-length bins are the same
// ones the forecast router serves a model per (utils/forecastModel.js).
const BIN_LABELS = {
  insufficient: 'Too little history',
  short: 'Short history',
  medium: 'Medium history',
  long: 'Long history',
  long_up: 'Long history, rising',
  long_flat: 'Long history, flat',
  long_down: 'Long history, falling',
};

// STL seasonal strength (GET /decomposition, analytics/forecasting/
// decomposition.py: F_S = max(0, 1 - Var(R)/Var(S+R))) in display bands —
// a convention over the measured number, which always stays beside it, the
// same rule as the volatility band. The peak and trough months are only
// named when there is a pattern worth naming.
const seasonalityBand = (strength) => {
  if (strength >= 0.6) return 'Strong seasonality';
  if (strength >= 0.3) return 'Moderate seasonality';
  return 'Weak seasonality';
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

  // STL is Unilever SKU-level only (a Del Monte row is a category with no
  // SKU series), and a failure here must not blank the rest of the panel —
  // the tile just says it couldn't be computed.
  const [stl, setStl] = useState(null);
  useEffect(() => {
    if (!skuId || principal === 'delmonte') return undefined;
    let cancelled = false;
    setStl(null);
    getDecomposition(skuId, { principal })
      .then((res) => { if (!cancelled) setStl(res ?? { available: false, reason: 'No SKU-level series for this product.' }); })
      .catch(() => { if (!cancelled) setStl({ available: false, reason: 'Could not load the STL decomposition.' }); });
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
  const binSegment = data.segments?.find((s) => s.scheme === 'combined_v1')
    ?? data.segments?.find((s) => s.scheme === 'length_v2')
    ?? null;

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

          {/* Seasonality: STL decomposition of the SKU's monthly demand. */}
          {principal !== 'delmonte' && (
            <div className="sku-diag-tile" title="STL decomposition (period 12, robust) of monthly demand from the first sale">
              <span className="sku-diag-tile-label">
                <Waves size={11} aria-hidden="true" /> Seasonality
              </span>
              <span className="sku-diag-tile-value">
                {!stl ? '…' : stl.available ? seasonalityBand(stl.seasonal_strength) : 'Not enough history'}
              </span>
              <span className="sku-diag-tile-desc">
                {!stl
                  ? 'Decomposing…'
                  : !stl.available
                    ? stl.reason
                    : `${stl.seasonal_strength >= 0.3 ? `peaks in ${stl.peak_month}, lowest in ${stl.trough_month} · ` : 'no reliable yearly pattern · '}STL seasonal strength ${stl.seasonal_strength.toFixed(2)}, trend ${stl.trend_strength.toFixed(2)}`}
              </span>
            </div>
          )}
        </div>
      )}

      {/* One line under the tiles: the SKU's bin from ONE scheme,
          combined_v1 (length_v2 when it's absent), with its bin_reason
          verbatim. The per-scheme bin_reason blockquotes and the Feb-2026
          revenue-share footer that used to sit here were removed
          (2026-09-21) for restating the tiles in the pipeline's vocabulary
          (LONG_UP, stability_v1, CHURN) — so this names the bin in plain
          words and keeps the scheme and code in the tooltip. GET /segment's
          revenue_share_2026_02 is still unread here. */}
      {binSegment && (
        <p className="sku-diag-bin" title={`${binSegment.scheme}: ${binSegment.bin}`}>
          <span className="sku-diag-bin-label">Bin</span>
          <span className="sku-diag-bin-name">{BIN_LABELS[binSegment.bin] || binSegment.bin}</span>
          {binSegment.bin_reason ? ` — ${binSegment.bin_reason}` : ''}
        </p>
      )}
    </section>
  );
};

export default SkuDiagnosticsPanel;
