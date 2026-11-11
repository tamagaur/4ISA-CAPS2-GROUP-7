// theme/motion.js: one motion for every graph. Run: npm test
//
// Recharts' own default (1500ms, its own curve) applies to any series that
// does not spread chartAnim/zoomAnim, and the CSS bars read the --chart-draw-*
// tokens in index.css; these tests fail if either goes its own way.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  CHART_ANIM_DELAY,
  CHART_ANIM_DURATION,
  CHART_ANIM_EASING,
  CHART_ANIM_MAX_STEPS,
  CHART_ANIM_STAGGER,
  chartAnim,
  chartAnimBegin,
} from './motion.js';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const indexCss = readFileSync(join(SRC, 'index.css'), 'utf8');

const cssToken = (name) => {
  const m = indexCss.match(new RegExp(`${name}:\\s*([^;]+);`));
  assert.ok(m, `index.css defines ${name}`);
  return m[1].trim();
};

test('the CSS bars and the Recharts graphs share one duration, curve, delay and stagger', () => {
  assert.equal(cssToken('--chart-draw-duration'), `${CHART_ANIM_DURATION}ms`);
  assert.equal(cssToken('--chart-draw-ease'), CHART_ANIM_EASING);
  assert.equal(cssToken('--chart-draw-delay'), `${CHART_ANIM_DELAY}ms`);
  assert.equal(cssToken('--chart-draw-stagger'), `${CHART_ANIM_STAGGER}ms`);
  assert.match(indexCss, new RegExp(`min\\(var\\(--chart-series, 0\\), ${CHART_ANIM_MAX_STEPS}\\)`));
});

test('the curve is written as a cubic-bezier, never a keyword', () => {
  // Recharts' 'ease-out' is CSS's ease-in-out, so a keyword would move the
  // two layers differently.
  assert.match(CHART_ANIM_EASING, /^cubic-bezier\(\s*[\d.]+,\s*[\d.]+,\s*[\d.]+,\s*[\d.]+\s*\)$/);
});

test('chartAnim staggers each further series and stops after the cap', () => {
  assert.deepEqual(chartAnim(0), {
    isAnimationActive: true,
    animationDuration: CHART_ANIM_DURATION,
    animationBegin: CHART_ANIM_DELAY,
    animationEasing: CHART_ANIM_EASING,
  });
  assert.equal(chartAnimBegin(1), CHART_ANIM_DELAY + CHART_ANIM_STAGGER);
  assert.equal(chartAnimBegin(CHART_ANIM_MAX_STEPS + 5), CHART_ANIM_DELAY + CHART_ANIM_MAX_STEPS * CHART_ANIM_STAGGER);
  assert.equal(chartAnimBegin(-1), CHART_ANIM_DELAY);
});

test('chartAnim switches the draw off for a viewer who asked for less motion', () => {
  const had = Object.prototype.hasOwnProperty.call(globalThis, 'window');
  const previous = globalThis.window;
  globalThis.window = { matchMedia: () => ({ matches: true }) };
  try {
    assert.deepEqual(chartAnim(2), { isAnimationActive: false });
  } finally {
    if (had) globalThis.window = previous;
    else delete globalThis.window;
  }
});

// Comments blanked to spaces (newlines kept, so line numbers hold): a comment
// that mentions <Area> is not a series.
const blankComments = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '))
  .replace(/(^|[^:'"`])\/\/[^\n]*/gm, (c, lead) => lead + ' '.repeat(c.length - lead.length));

// Every .jsx file under src that draws with Recharts.
const rechartsFiles = () => {
  const out = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (name.endsWith('.jsx')) {
        const text = readFileSync(path, 'utf8');
        if (/from ['"]recharts['"]/.test(text)) out.push({ path, text: blankComments(text) });
      }
    }
  };
  walk(SRC);
  return out;
};

// The opening tag that starts at `start`: up to the first `>` outside braces
// and quotes.
const openingTag = (text, start) => {
  let depth = 0;
  let quote = null;
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (ch === quote) quote = null;
    } else if (depth === 0 && (ch === '"' || ch === "'")) {
      quote = ch;
    } else if (ch === '{') {
      depth += 1;
    } else if (ch === '}') {
      depth -= 1;
    } else if (ch === '>' && depth === 0) {
      return text.slice(start, i + 1);
    }
  }
  return text.slice(start);
};

const SERIES = /<(Bar|Line|Area|Pie|Scatter|Radar|RadialBar|Funnel)(?=[\s/>])/g;

test('every Recharts series wears the shared motion', () => {
  const files = rechartsFiles();
  assert.ok(files.length > 0, 'found the Recharts files');
  const offenders = [];
  let seen = 0;
  for (const { path, text } of files) {
    for (const m of text.matchAll(SERIES)) {
      const tag = openingTag(text, m.index);
      seen += 1;
      const line = text.slice(0, m.index).split('\n').length;
      const where = `${relative(SRC, path)}:${line} <${m[1]}>`;
      if (/isAnimationActive/.test(tag)) offenders.push(`${where} sets isAnimationActive itself`);
      if (!/\b(chartAnim|zoomAnim)\(/.test(tag)) offenders.push(`${where} has no chartAnim()/zoomAnim()`);
    }
  }
  assert.ok(seen > 0, 'found Recharts series to check');
  assert.deepEqual(offenders, []);
});
