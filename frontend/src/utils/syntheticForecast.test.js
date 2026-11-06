import test from 'node:test';
import assert from 'node:assert/strict';
import { forecastLabels, REAL_FORECAST_LABELS, SYNTHETIC_FORECAST_LABELS } from './syntheticForecast.js';

test('only an explicit demonstration: true response gets the synthetic labels', () => {
  assert.equal(forecastLabels({ demonstration: true, forecast: [] }), SYNTHETIC_FORECAST_LABELS);
  for (const real of [null, undefined, {}, { demonstration: false }, { demonstration: 'true' }, { data_source: 'real' }]) {
    assert.equal(forecastLabels(real), REAL_FORECAST_LABELS);
  }
});

test('the synthetic series never shares a name, legend, end label or stat label with the real one', () => {
  for (const key of ['name', 'legend', 'endLabel', 'statLabel']) {
    assert.notEqual(SYNTHETIC_FORECAST_LABELS[key], REAL_FORECAST_LABELS[key]);
    assert.match(SYNTHETIC_FORECAST_LABELS[key], /sample/i);
  }
  assert.equal(REAL_FORECAST_LABELS.watermark, null);
  assert.match(SYNTHETIC_FORECAST_LABELS.watermark, /SAMPLE/);
});
