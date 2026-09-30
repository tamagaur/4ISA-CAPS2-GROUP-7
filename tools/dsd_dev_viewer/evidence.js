// ================= EVIDENCE tab (tools/dsd_dev_viewer/evidence.js) =================
// Every number drawn here is read from D.evidence, which evidence.py loads from
// reports/evidence/ (written by scripts/evidence/*.py). The page computes layout only.
// Written for a first-time reader: each card leads with a plain-English headline chosen
// by the stored verdict, a one-line "the test", and a "how to read this" line per chart;
// the computed caption, criterion text, checks, amendments and data notes sit in a closed
// "Details (for the paper)" section. No number is typed here except what the result files
// carry; headlines carry no numbers except chart 8's (Yuan, 2026-09-30), read from its data.
// Screen charts use the viewer's dark steps; SVG/PNG exports re-render the same figure
// with the light print steps. Both palettes were checked with the dataviz validator
// (models aqua/violet/orange all-pairs; blue+magenta; blue+red; ordinal blue ramp).
// Wrapped: only drawEvidence is global, so no name here can collide with the viewer's own script.
const drawEvidence = (() => {
const EV = D.evidence;
const EVFONT = 'Segoe UI, -apple-system, Helvetica Neue, Arial, sans-serif';
const EVT = {
  dark: {surface:'#161a24', ink:'#eef0f6', ink2:'#b9bfd0', ink3:'#7d8499', grid:'rgba(255,255,255,0.08)', axis:'#3a4150',
         ma3:'#199e70', tsb:'#9085e9', xgb:'#d95926', base:'#8a8f9e', actual:'#c3c2b7',
         blue:'#3987e5', mag:'#d55181', red:'#e66767', ramp:['#86b6ef', '#3987e5', '#1c5cab'],
         W:'#0ca30c', L:'#d03b3b', T:'#4a5263', band:0.18, shade:'#ffffff'},
  light: {surface:'#ffffff', ink:'#0b0b0b', ink2:'#52514e', ink3:'#898781', grid:'#e1e0d9', axis:'#c3c2b7',
          ma3:'#1baf7a', tsb:'#4a3aa7', xgb:'#eb6834', base:'#898781', actual:'#52514e',
          blue:'#2a78d6', mag:'#e87ba4', red:'#e34948', ramp:['#86b6ef', '#2a78d6', '#104281'],
          W:'#0ca30c', L:'#d03b3b', T:'#d9d8d1', band:0.16, shade:'#000000'},
};
const evRecs = t => t ? t.rows.map(r => Object.fromEntries(t.cols.map((c, i) => [c, r[i]]))) : [];
const nf = (v, d=0) => v == null || Number.isNaN(+v) ? '—' : Number(v).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
const pc = (v, d=1) => v == null ? '—' : (v * 100).toFixed(d) + '%';
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const mlab = m => MON[+String(m).slice(5, 7) - 1] + ' ' + String(m).slice(2, 4);
const blab = w => { const [a, b] = String(w).split('..'); return mlab(a) + '–' + mlab(b); };
const EVSTATE = {};
const evOnce = {drawn: false};
const hOf = fig => typeof fig.H === 'function' ? fig.H() : fig.H;

function niceTicks(lo, hi, n=5){
  if (!(hi > lo)) hi = lo + 1;
  const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw)), e = raw / mag;
  const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(12));
  return out;
}
function txt(t, x, y, s, o={}){
  return `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" fill="${o.fill || t.ink}" font-size="${o.size || 11}"`
    + (o.anchor ? ` text-anchor="${o.anchor}"` : '') + (o.weight ? ` font-weight="${o.weight}"` : '')
    + (o.base ? ` dominant-baseline="${o.base}"` : '') + ` font-family="${EVFONT}">${esc(s)}</text>`;
}
// One test-period square: colour carries the result; the legend under the strip names it.
function evCell(t, x, y, w, h, v){
  const fill = v === 'W' ? t.W : v === 'L' ? t.L : v === 'NT' ? 'none' : t.T;
  return `<rect x="${x.toFixed(1)}" y="${y}" width="${Math.max(w, 2).toFixed(1)}" height="${h}" rx="2.5" fill="${fill}"`
    + (v === 'NT' ? ` stroke="${t.ink3}" stroke-dasharray="2 2"` : '') + `/>`;
}
const RESULT_WORDS = cmp => [['T', 'Tie (no clear difference)'], ['W', `Better than ${cmp}`], ['L', `Worse than ${cmp}`], ['NT', 'Not enough data']];

// ---- one line plot inside a frame -------------------------------------------
function evPlot(t, fr, o){
  const legW = w => 19 + w.length * 5.6 + 18;
  const legLines = o.strip ? (() => { let n = 1, x = 0; RESULT_WORDS(o.strip.cmp || 'the simple average').forEach(([, w]) => {
    if (x && x + legW(w) > fr.w - (o.ml ?? 64) - 10){ n++; x = 0; } x += legW(w); }); return n; })() : 0;
  const stripH = o.strip ? o.strip.rows.length * 18 + 16 + 20 * legLines + 2 : 0;
  const M = {l: o.ml ?? 64, r: o.mr ?? 170, t: o.mt ?? 16, b: 24 + (o.xsub ? 12 : 0) + (o.xtitle ? 16 : 0)};
  const pw = fr.w - M.l - M.r, ph = fr.h - M.t - M.b - stripH;
  const X0 = fr.x + M.l, Y0 = fr.y + M.t;
  const cat = !o.xnum, step = cat ? pw / o.xs.length : 0;
  const xp = cat ? v => X0 + (o.xs.indexOf(v) + 0.5) * step : v => X0 + (v - o.xdom[0]) / (o.xdom[1] - o.xdom[0]) * pw;
  const ys = [];
  o.series.forEach(s => { s.pts.forEach(p => p[1] != null && ys.push(p[1])); (s.band || []).forEach(b => { if (b[1] != null) ys.push(b[1], b[2]); }); });
  (o.hrules || []).forEach(h => ys.push(h.y));
  let lo = o.y.dom ? o.y.dom[0] : Math.min(...ys), hi = o.y.dom ? o.y.dom[1] : Math.max(...ys);
  if (o.y.zero) lo = Math.min(0, lo);
  if (!o.y.dom){ const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 0.01; hi += pad; if (!o.y.zero) lo -= pad; }
  const ticks = niceTicks(lo, hi, o.y.nt || 5).filter(v => v >= lo - 1e-9 && v <= hi + 1e-9);
  const yp = v => Y0 + ph - (v - lo) / (hi - lo) * ph;
  let g = '';
  (o.rects || []).forEach(r => {
    const x0 = xp(r.x0) - step / 2, x1 = xp(r.x1) + step / 2;
    g += `<rect x="${x0.toFixed(1)}" y="${Y0}" width="${(x1 - x0).toFixed(1)}" height="${ph.toFixed(1)}" fill="${t.shade}" fill-opacity="${r.op}"/>`
      + (r.label ? txt(t, (x0 + x1) / 2, Y0 + 10, r.label, {size:9.5, fill:t.ink3, anchor:'middle'}) : '');
  });
  ticks.forEach(v => { g += `<line x1="${X0}" x2="${(X0 + pw).toFixed(1)}" y1="${yp(v).toFixed(1)}" y2="${yp(v).toFixed(1)}" stroke="${t.grid}"/>`
    + txt(t, X0 - 6, yp(v), o.y.fmt(v), {size:10, fill:t.ink3, anchor:'end', base:'middle'}); });
  (o.xticks || o.xs).forEach(v => {
    g += txt(t, xp(v), Y0 + ph + 14, o.xlab ? o.xlab(v) : String(v), {size:10, fill:t.ink3, anchor:'middle'});
    if (o.xsub) g += txt(t, xp(v), Y0 + ph + 26, o.xsub(v), {size:9, fill:t.ink3, anchor:'middle'});
  });
  g += `<line x1="${X0}" x2="${(X0 + pw).toFixed(1)}" y1="${(Y0 + ph).toFixed(1)}" y2="${(Y0 + ph).toFixed(1)}" stroke="${t.axis}"/>`;
  if (o.xtitle) g += txt(t, X0 + pw / 2, Y0 + ph + 22 + (o.xsub ? 12 : 0) + 6, o.xtitle, {size:10.5, fill:t.ink2, anchor:'middle'});
  if (o.y.title) g += `<text transform="translate(${fr.x + 11},${(Y0 + ph / 2).toFixed(1)}) rotate(-90)" text-anchor="middle" font-size="10.5" fill="${t.ink2}" font-family="${EVFONT}">${esc(o.y.title)}</text>`;
  if (o.title) g += txt(t, X0, fr.y + 9, o.title, {size:11, fill:t.ink, weight:600});
  (o.hrules || []).forEach(h => { g += `<line x1="${X0}" x2="${(X0 + pw).toFixed(1)}" y1="${yp(h.y).toFixed(1)}" y2="${yp(h.y).toFixed(1)}" stroke="${t.ink3}" stroke-dasharray="4 3"/>`
    + (h.label ? (h.inside ? txt(t, X0 + 4, yp(h.y) - 4, h.label, {size:9.5, fill:t.ink3})
                           : txt(t, X0 + pw + 4, yp(h.y), h.label, {size:9.5, fill:t.ink3, base:'middle'})) : ''); });
  (o.vrules || []).forEach(v => { const x = xp(v.x);
    g += `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${Y0}" y2="${(Y0 + ph).toFixed(1)}" stroke="${t.ink3}" stroke-dasharray="3 3"/>`
      + txt(t, x + 3, Y0 + (v.dy || 10), v.label, {size:9.5, fill:t.ink2}); });
  o.series.forEach(s => { const b = (s.band || []).filter(q => q[1] != null && q[2] != null); if (b.length < 2) return;
    const up = b.map(q => `${xp(q[0]).toFixed(1)},${yp(q[2]).toFixed(1)}`), dn = b.slice().reverse().map(q => `${xp(q[0]).toFixed(1)},${yp(q[1]).toFixed(1)}`);
    g += `<polygon points="${up.concat(dn).join(' ')}" fill="${s.color}" fill-opacity="${t.band}"/>`; });
  o.series.forEach(s => {
    if (s.line !== false){
      const segs = []; let cur = [];
      s.pts.forEach(p => { if (p[1] == null){ if (cur.length) segs.push(cur); cur = []; } else cur.push(p); });
      if (cur.length) segs.push(cur);
      segs.forEach(sg => { if (sg.length > 1) g += `<polyline points="${sg.map(p => `${xp(p[0]).toFixed(1)},${yp(p[1]).toFixed(1)}`).join(' ')}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round"${s.dash ? ` stroke-dasharray="${s.dash}"` : ''}/>`; });
    }
    if (s.markers !== false) s.pts.forEach(p => { if (p[1] == null) return;
      g += `<circle cx="${xp(p[0]).toFixed(1)}" cy="${yp(p[1]).toFixed(1)}" r="${s.r || 3.5}" fill="${s.hollow ? 'none' : s.color}" stroke="${s.hollow ? s.color : t.surface}" stroke-width="${s.hollow ? 1.8 : 1.5}"/>`; });
  });
  const labs = o.series.filter(s => s.labelEnd !== false).map(s => { const last = [...s.pts].reverse().find(p => p[1] != null);
    return last ? {s, y: yp(last[1])} : null; }).filter(Boolean).sort((a, b) => a.y - b.y);
  for (let i = 1; i < labs.length; i++) if (labs[i].y - labs[i - 1].y < 13) labs[i].y = labs[i - 1].y + 13;
  labs.forEach(l => { g += `<line x1="${(X0 + pw + 4).toFixed(1)}" x2="${(X0 + pw + 14).toFixed(1)}" y1="${l.y.toFixed(1)}" y2="${l.y.toFixed(1)}" stroke="${l.s.color}" stroke-width="2"${l.s.dash ? ` stroke-dasharray="${l.s.dash}"` : ''}/>`
    + txt(t, X0 + pw + 18, l.y, l.s.label, {size:10.5, fill:t.ink, base:'middle'}); });
  if (o.strip){
    // Result strip: one row per comparison; each square = one half-year test period.
    const sy0 = Y0 + ph + M.b + 14, cw = Math.min(step * 0.86, 96);
    g += txt(t, X0, sy0 - 4, o.strip.title || 'Each square = one half-year test period', {size:9.5, fill:t.ink3});
    o.strip.rows.forEach((row, i) => { const y = sy0 + i * 18 + 2;
      g += txt(t, X0 - 8, y + 7, row.label, {size:10, fill:t.ink2, anchor:'end', base:'middle'});
      o.xs.forEach(xv => { const c = row.cells[String(xv)]; if (!c) return; const vs = Array.isArray(c) ? c : [c];
        const gap = 3, sw = (cw - gap * (vs.length - 1)) / vs.length;
        vs.forEach((v, j) => { g += evCell(t, xp(xv) - cw / 2 + j * (sw + gap), y, sw, 14, v); }); }); });
    let lx = X0, ly = sy0 + o.strip.rows.length * 18 + 14;
    RESULT_WORDS(o.strip.cmp || 'the simple average').forEach(([v, w]) => {
      if (lx > X0 && lx + legW(w) > fr.x + fr.w - 10){ lx = X0; ly += 20; }
      g += evCell(t, lx, ly - 6, 14, 12, v) + txt(t, lx + 19, ly, w, {size:10, fill:t.ink2, base:'middle'});
      lx += legW(w); });
  }
  const geo = {X0, Y0, pw, ph, cat, xs: o.xs, step, xp, xdom: o.xdom, series: o.series, fmt: o.y.tfmt || o.y.fmt, xlab: o.xlab, tip: o.tip, free: o.free};
  return {g, geo};
}

// ---- bars (one series, optional interval whiskers) ------------------------------
function evBars(t, fr, o){
  const M = {l: o.ml ?? 70, r: o.mr ?? 120, t: o.title ? 40 : 22, b: 36};
  const pw = fr.w - M.l - M.r, ph = fr.h - M.t - M.b, X0 = fr.x + M.l, Y0 = fr.y + M.t;
  const n = o.cats.length, step = pw / n, bw = Math.min(step * 0.42, 48);
  const hi0 = Math.max(...o.vals.map((v, i) => Math.max(v, o.hi ? o.hi[i] : v)), ...(o.hrules || []).map(h => h.y)) * 1.18;
  const ticks = niceTicks(0, hi0, 4), stp = ticks[1] - ticks[0];
  while (ticks[ticks.length - 1] < hi0 - 1e-9) ticks.push(+(ticks[ticks.length - 1] + stp).toFixed(12));
  const hi = ticks[ticks.length - 1];
  const yp = v => Y0 + ph - v / hi * ph, xc = i => X0 + (i + 0.5) * step;
  let g = o.title ? txt(t, X0, fr.y + 9, o.title, {size:11, weight:600}) : '';
  ticks.forEach(v => { g += `<line x1="${X0}" x2="${(X0 + pw).toFixed(1)}" y1="${yp(v).toFixed(1)}" y2="${yp(v).toFixed(1)}" stroke="${t.grid}"/>`
    + txt(t, X0 - 6, yp(v), o.fmt(v), {size:10, fill:t.ink3, anchor:'end', base:'middle'}); });
  o.vals.forEach((v, i) => {
    const x = xc(i) - bw / 2, y = yp(v), h = Math.max(Y0 + ph - y, 0.5), col = (o.colors && o.colors[i]) || t.blue, r = Math.min(4, h / 2, bw / 2);
    g += `<path d="M${x.toFixed(1)},${(Y0 + ph).toFixed(1)} V${(y + r).toFixed(1)} q0,-${r} ${r},-${r} H${(x + bw - r).toFixed(1)} q${r},0 ${r},${r} V${(Y0 + ph).toFixed(1)} Z" fill="${col}"/>`;
    if (o.lo) g += `<line x1="${xc(i).toFixed(1)}" x2="${xc(i).toFixed(1)}" y1="${yp(o.lo[i]).toFixed(1)}" y2="${yp(o.hi[i]).toFixed(1)}" stroke="${t.ink}" stroke-width="1.5"/>`
      + [o.lo[i], o.hi[i]].map(q => `<line x1="${(xc(i) - 6).toFixed(1)}" x2="${(xc(i) + 6).toFixed(1)}" y1="${yp(q).toFixed(1)}" y2="${yp(q).toFixed(1)}" stroke="${t.ink}" stroke-width="1.5"/>`).join('');
    const top = Math.min(y, o.hi ? yp(o.hi[i]) : y);
    if (o.labels) g += txt(t, xc(i), top - 6, o.labels[i], {size:10, fill:t.ink, anchor:'middle'});
    g += txt(t, xc(i), Y0 + ph + 14, o.cats[i], {size:10, fill:t.ink2, anchor:'middle'});
    if (o.sub) g += txt(t, xc(i), Y0 + ph + 27, o.sub[i], {size:9, fill:t.ink3, anchor:'middle'});
  });
  g += `<line x1="${X0}" x2="${(X0 + pw).toFixed(1)}" y1="${(Y0 + ph).toFixed(1)}" y2="${(Y0 + ph).toFixed(1)}" stroke="${t.axis}"/>`;
  (o.hrules || []).forEach(h => { g += `<line x1="${X0}" x2="${(X0 + pw).toFixed(1)}" y1="${yp(h.y).toFixed(1)}" y2="${yp(h.y).toFixed(1)}" stroke="${t.ink3}" stroke-dasharray="4 3"/>`
    + txt(t, X0 + pw + 4, yp(h.y), h.label, {size:9.5, fill:t.ink2, base:'middle'}); });
  if (o.ytitle) g += `<text transform="translate(${fr.x + 11},${(Y0 + ph / 2).toFixed(1)}) rotate(-90)" text-anchor="middle" font-size="10.5" fill="${t.ink2}" font-family="${EVFONT}">${esc(o.ytitle)}</text>`;
  const geo = {X0, Y0, pw, ph, cat: true, xs: o.cats, step, xp: v => xc(o.cats.indexOf(v)), tip: o.tip, nocross: true};
  return {g, geo};
}

// ---- figure: panels -> one SVG --------------------------------------------------
function evFigure(t, fig){
  let body = ''; const geos = [], H = hOf(fig);
  fig.build(t).forEach(p => { const r = (p.draw || evPlot)(t, p.fr, p.o); body += r.g; if (r.geo) geos.push(r.geo); });
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${fig.W} ${H}" width="${fig.W}" height="${H}" font-family="${EVFONT}">`
    + `<rect width="${fig.W}" height="${H}" fill="${t.surface}"/>${body}</svg>`;
  return {svg, geos};
}
function evTipRows(g, x){
  return g.series.filter(s => s.tip !== false).map(s => {
    let p = s.pts.find(q => q[0] === x);
    if (!g.cat && !p){ const k = s.pts.reduce((b, q) => q[1] != null && (b == null || Math.abs(q[0] - x) < Math.abs(b[0] - x)) ? q : b, null); p = k; }
    return p && p[1] != null ? `<div class="r"><span><i style="background:${s.color}"></i>${esc(s.label)}</span><b>${g.fmt(p[1])}</b></div>` : '';
  }).join('');
}
function evHover(host, fig, geos){
  const svg = host.querySelector('svg'), tipEl = $('#etip');
  const NS = 'http://www.w3.org/2000/svg', cross = document.createElementNS(NS, 'line');
  cross.setAttribute('stroke', EVT.dark.ink3); cross.setAttribute('visibility', 'hidden'); svg.appendChild(cross);
  const hide = () => { tipEl.style.display = 'none'; cross.setAttribute('visibility', 'hidden'); };
  svg.onmousemove = ev => {
    const r = svg.getBoundingClientRect(), k = fig.W / r.width, mx = (ev.clientX - r.left) * k, my = (ev.clientY - r.top) * k;
    const g = geos.find(q => mx >= q.X0 && mx <= q.X0 + q.pw && my >= q.Y0 && my <= q.Y0 + q.ph);
    if (!g) return hide();
    let x, html;
    if (g.pick){ x = g.pick(mx, my); if (x == null) return hide(); html = g.tip(x); }
    else {
      x = g.cat ? g.xs[Math.max(0, Math.min(g.xs.length - 1, Math.floor((mx - g.X0) / g.step)))]
                : g.xdom[0] + (mx - g.X0) / g.pw * (g.xdom[1] - g.xdom[0]);
      html = g.tip ? g.tip(x) : `<div class="h">${esc(g.xlab ? g.xlab(x) : x)}</div>` + evTipRows(g, x);
    }
    if (!html) return hide();
    if (!g.nocross && !g.pick){ const px = g.cat ? g.xp(x) : mx;
      [['x1', px], ['x2', px], ['y1', g.Y0], ['y2', g.Y0 + g.ph]].forEach(([a, v]) => cross.setAttribute(a, v)); cross.setAttribute('visibility', 'visible'); }
    tipEl.innerHTML = html; tipEl.style.display = 'block';
    tipEl.style.left = Math.min(window.innerWidth - tipEl.offsetWidth - 8, ev.clientX + 14) + 'px';
    tipEl.style.top = Math.min(window.innerHeight - tipEl.offsetHeight - 8, ev.clientY + 14) + 'px';
  };
  svg.onmouseleave = hide;
}
function evDownload(blob, name){
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
function evExport(fig, kind){
  const {svg} = evFigure(EVT.light, fig), name = typeof fig.file === 'function' ? fig.file() : fig.file, H = hOf(fig);
  if (kind === 'svg') return evDownload(new Blob(['<?xml version="1.0" encoding="UTF-8"?>\n' + svg], {type:'image/svg+xml'}), name + '.svg');
  const url = URL.createObjectURL(new Blob([svg], {type:'image/svg+xml'})), img = new Image();
  img.onload = () => { const s = 3, c = document.createElement('canvas'); c.width = fig.W * s; c.height = H * s;
    const x = c.getContext('2d'); x.fillStyle = '#ffffff'; x.fillRect(0, 0, c.width, c.height); x.scale(s, s); x.drawImage(img, 0, 0, fig.W, H);
    URL.revokeObjectURL(url); c.toBlob(b => evDownload(b, name + '.png'), 'image/png'); };
  img.src = url;
}
function evRender(host, fig){
  const {svg, geos} = evFigure(EVT.dark, fig);
  host.innerHTML = svg; evHover(host, fig, geos);
}

// ---- plain words --------------------------------------------------------------------
const NAME = {ma3: '3-month average (MA3)', tsb: 'TSB', xgb: 'XGBoost + 3-month avg', sba: 'SBA', naive: 'Naive'};
const ERR = 'Forecast error (lower is better)';
// Verdict chip in words; the stored verdict code stays in Details and in the chip's tooltip.
const WORDS = {'CONFIRMS': ['Our choice holds', 'good'], 'FLAWED': ['Our choice is questioned', 'bad'],
               'DESCRIPTIVE': ['Description only', 'neutral'], 'NOT TESTABLE': ["Can't be tested yet", 'neutral'],
               'NOT BUILT': ['Not built yet', 'notbuilt'], 'CAVEAT NEEDED': ['Needs a caveat', 'warn'], 'no flag': ['Our choice holds', 'good']};
function evChip(v){
  const s = String(v);
  const parts = s.includes(' / ') ? s.split(' / ') : [s];
  return parts.map(p => { const m = p.match(/^([^:]+): (.+)$/), who = m && !WORDS[p] ? m[1] : null, code = who ? m[2] : p;
    const [w, cls] = WORDS[code] || [code, 'neutral'];
    return `<span class="evchip ${cls}" title="stored verdict: ${esc(p)}">${{good: '✓', bad: '!', warn: '!', notbuilt: '–', neutral: 'i'}[cls]} ${who ? esc(who) + ': ' : ''}${esc(w)}</span>`; }).join(' ');
}
const DECISION = {1: 'Which forecasting model to use', 2: 'How much sales history each model needs', 3: 'Averaging the last 3 months (vs 2, 6 or 12)',
  4: 'How to mix XGBoost with the 3-month average', 5: 'Whether transforming the sales data helps', 6: 'Products we cannot forecast well',
  7: "Which products count as 'A' (top revenue)", 8: 'How much stock the supplier allocation allows', 9: 'How the order plan weighs cost, service and storage',
  10: 'How much safety stock to hold', 11: 'Whether sales follow a yearly season', 12: 'Where real and placeholder data exist'};
const TEST = {
  1: 'We would question our choice if a model we use lost to the simple average in most test periods, or a basic rule beat it.',
  2: 'We would question our cut-offs if less history clearly won, or more history clearly lost, in most test periods.',
  3: 'We would question the 3-month window if another window won overall and in most test periods.',
  4: 'We would question the 50/50 mix if another mix won in most test periods.',
  5: 'We would question dropping transforms if any truly won, or if wins came clearly more often than luck.',
  6: 'This only checks that the list and its causes rebuild exactly from the stored data.',
  7: 'No pass/fail rule exists for this; it describes how revenue is spread across products.',
  8: 'We would question the default 105% if month-end stock fell below 3 weeks, or if 108% fixed shortages that 105% leaves.',
  9: 'We would question the weights if any small change (±0.10) changed which products get cut.',
  10: 'We would question the 90% buffer if stockouts clearly happened more than 10% of the time.',
  11: 'We would add a caveat if every pair of full years showed the same seasonal shape.',
  12: 'Plan only; built once the data-coverage table is in the live database.',
};
// Headlines follow the STORED verdict: a different verdict gets a different sentence.
const HEAD = {
  1: c => c.verdict === 'CONFIRMS' ? 'The newer models tie with the simple 3-month average; none does worse.'
    : 'A model we use does worse than the simple average, or a basic rule beats it.',
  2: c => c.verdict === 'CONFIRMS' ? 'Giving the models more or less history never clearly changes the result.'
    : 'A different amount of history works clearly better or worse; our cut-offs are questioned.',
  3: c => c.verdict === 'CONFIRMS' ? 'Averaging 2, 6 or 12 months is no better than averaging 3.' : 'Another averaging window beats the 3-month average.',
  4: c => c.verdict === 'CONFIRMS' ? 'No other XGBoost/average mix beats the 50/50 mix we use.' : 'A different XGBoost/average mix beats our 50/50 mix.',
  5: c => c.verdict === 'CONFIRMS' ? 'Transforming the sales data never truly helped; its wins look like luck.'
    : 'Transforming the sales data helps more often than luck would explain.',
  6: () => 'Some products forecast poorly; the list is reproducible and each cause is measured.',
  7: () => 'A small group of top products brings in most of the revenue.',
  8: c => { const A = evRecs(c.data.totals), r = A.find(q => q.allocation_pct === 105);
    const boundary = c.verdict === 'FLAWED' && A.every(q => q.run_lp_says_met) && r && r.cover_gap_php < 0;
    return boundary ? `Every allocation level keeps 3 weeks of stock; the 'questioned' flag is a ₱${(-r.cover_gap_php).toFixed(2)} rounding gap.`
      : c.verdict === 'CONFIRMS' ? 'At every allocation level, stock covers the 3-week target.' : 'At the default allocation, stock falls short of the 3-week target.'; },
  9: c => c.verdict === 'CONFIRMS' ? "Small changes to the plan's weights don't change which products get cut."
    : "Small changes to the plan's weights change which products get cut.",
  10: c => c.verdict === 'CONFIRMS' ? 'Stockouts happen no more often than the promised 90% service level allows.'
    : 'Stockouts happen more often than the promised service level allows.',
  11: c => /CAVEAT/.test(c.verdict) ? 'Sales repeat the same yearly season overall; the paper should mention it.'
    : /NOT TESTABLE/.test(c.verdict) ? 'Unilever shows no consistent yearly season; Del Monte lacks a full year to test.'
    : 'Neither principal shows a consistent yearly season.',
  12: () => 'Not built yet: it waits for the data-coverage table to reach the live database.',
};
const GLOSSARY = [
  ['Forecast', 'Our estimate of next month’s sales for one product.'],
  ['Forecast error (WAPE)', 'How far forecasts were from actual sales, as a share of sales. Lower is better.'],
  ['MASE', 'Forecast error divided by the error of a naive “same as last month” guess. Below 1 = better than that guess.'],
  ['MA3 (simple 3-month average)', 'Next month = the average of the last 3 months. Our benchmark and fallback.'],
  ['MA2 / MA6 / MA12', 'The same idea over 2, 6 or 12 months.'],
  ['TSB', 'A smoothing method built for products that do not sell every month (Teunter–Syntetos–Babai).'],
  ['XGBoost', 'A machine-learning model trained on all top products at once. We average it 50/50 with MA3.'],
  ['SBA / Naive', 'Two basic benchmarks: SBA is an older method for patchy sales; naive repeats last month.'],
  ['Test period', 'One half-year (e.g. Oct 2023–Feb 2024) in which every model forecast each month one step ahead.'],
  ['Tie / Better / Worse', 'Better or worse only when the 95% margin of error excludes “no difference” AND more products improve than worsen; otherwise a tie.'],
  ['Tier A (ABC)', 'The products that together bring in the top 80% of revenue. t3m = the same ranking on a 3-month window.'],
  ['LP (order plan)', 'The optimisation that decides each month’s order within the supplier allocation.'],
  ['Allocation', 'What the supplier lets us buy: last year’s sales × 103%, 105% or 108%, split by month.'],
  ['Weeks of cover', 'How many weeks of sales the stock left at month end would last. SSM’s rule is 3 weeks.'],
  ['Safety stock / service level', 'Extra stock held against surprises; a 90% service level means running out in about 1 month in 10.'],
  ['Pre-registered', 'The pass/fail rule was written and committed before any result was computed.'],
  ['Amendment', 'A later change to a check’s data source or column, approved and listed on the card; never a change to the pass/fail rule.'],
];

// ---- the charts -------------------------------------------------------------------
const EVMODELS = [['ma3', NAME.ma3, 'ma3', null, 2.6, true], ['tsb', NAME.tsb, 'tsb', null, 2, true], ['ens_xgb_ma3@A', NAME.xgb, 'xgb', null, 2, true],
                  ['sba', NAME.sba, 'base', '6 4', 1.6, false], ['naive', NAME.naive, 'base', '2 3', 1.6, false]];
const SERVED = {ma3:'ma3', tsb:'tsb', xgb_ma3_avg:'xgb'};
const EVFIGS = {};

EVFIGS[1] = c => {
  const L = evRecs(c.data.lines), V = evRecs(c.data.verdicts), S = evRecs(c.data.sku_series);
  const blocks = [...new Set(L.filter(r => r.window !== 'full').map(r => r.window))];
  const nBy = Object.fromEntries(blocks.map(b => [b, (L.find(r => r.window === b) || {}).n]));
  const more = () => !!EVSTATE.t1;
  const rowsAll = [['medium (served: TSB)', 'tsb', 'TSB, where we use it', true], ['long (served: XGBoost+MA3 avg)', 'ens_xgb_ma3@A', 'XGBoost + avg, where we use it', true],
                   ['ALL', 'tsb', 'TSB, all products', false], ['ALL', 'ens_xgb_ma3@A', 'XGBoost + avg, all products', false],
                   ['ALL', 'sba', 'SBA, all products', false], ['ALL', 'naive', 'Naive, all products', false]];
  const rows = () => rowsAll.filter(r => r[3] || more());
  const strip = () => ({cmp: 'the simple average', rows: rows().map(([co, m, lab]) => ({label: lab, cells: Object.fromEntries(blocks.map(b => {
    const r = V.find(v => v.cohort === co && v.model === m && v.window === b); return [b, r ? r.verdict : 'NT']; }))}))});
  const vtip = b => `<div class="h">${esc(blab(b))} · ${nBy[b]} products</div>` + EVMODELS.filter(m => m[5] || more()).map(([k, lab, col]) => {
    const r = L.find(q => q.window === b && q.model === k); return r ? `<div class="r"><span><i style="background:${EVT.dark[col]}"></i>${esc(lab)}</span><b>${r.median_wape.toFixed(3)}</b></div>` : ''; }).join('');
  const skus = [...new Map(S.map(r => [r.pk, r])).values()].sort((a, b) => String(a.sku_code).localeCompare(String(b.sku_code)));
  if (EVSTATE[1] == null) EVSTATE[1] = skus[0].pk;
  const toggle = {label: 'Also show the two basic benchmarks (SBA, naive) and all-product results', key: 't1'};
  return [
    {file: 'ch01_model_comparison', title: 'Forecast error in each half-year test period',
     read: 'Each dot = one half-year test period (Oct 2023 – Feb 2026). Up = more forecast error, so lower is better. '
       + 'The squares underneath say whether each model did better or worse than the simple 3-month average in that period. '
       + 'MA3 = simple 3-month average; TSB = a method for products that don’t sell every month; XGBoost = a machine-learning model, averaged 50/50 with MA3. '
       + 'Gaps between lines smaller than the margin of error count as ties; the squares show which differences are real.',
     toggle, W: 900, H: () => 330 + rows().length * 18 + 38,
     build: t => [{fr: {x: 0, y: 0, w: 900, h: 330 + rows().length * 18 + 38}, o: {ml: 210, xs: blocks, xlab: blab, xsub: b => `${nBy[b]} products`, strip: strip(), tip: vtip,
       y: {fmt: v => v.toFixed(2), title: ERR},
       series: EVMODELS.filter(m => m[5] || more()).map(([k, lab, col, dash, w]) => ({key: k, label: lab, color: t[col], dash, width: w,
         pts: blocks.map(b => [b, (L.find(r => r.window === b && r.model === k) || {}).median_wape ?? null])}))}}]},
    {file: () => `ch01_sku_${(S.find(r => r.pk === EVSTATE[1]) || {}).sku_code}`, title: 'One product: what sold vs what each model forecast',
     read: 'Pick a product. Grey = what actually sold each month; coloured lines = what each model forecast one month ahead. Closer to grey is better.',
     toggle, W: 900, H: 330,
     control: {options: skus.map(s => [s.pk, `${s.sku_code} · ${s.product_name}`]), get: () => EVSTATE[1], set: v => { EVSTATE[1] = +v; }},
     build: t => { const R = S.filter(r => r.pk === EVSTATE[1]), ms = R.map(r => r.month);
       return [{fr: {x: 0, y: 0, w: 900, h: 330}, o: {xs: ms, xticks: ms.filter((m, i) => i % 3 === 0), xlab: mlab, y: {fmt: v => nf(v), title: 'Units sold', zero: true},
         title: `${R[0].sku_code} · ${R[0].product_name}`,
         series: [{key: 'actual', label: 'Actual sales', color: t.actual, width: 2.4, pts: R.map(r => [r.month, r.actual])}]
           .concat(EVMODELS.filter(m => m[5] || more()).map(([k, lab, col, dash]) => ({key: k, label: lab, color: t[col], dash, width: 1.6, markers: false, pts: R.map(r => [r.month, r[k]])}))),
         tip: m => { const r = R.find(q => q.month === m); return `<div class="h">${mlab(m)}</div><div class="r"><span>Actual sales</span><b>${nf(r.actual)}</b></div>`
           + EVMODELS.filter(q => q[5] || more()).map(([k, lab, col]) => `<div class="r"><span><i style="background:${EVT.dark[col]}"></i>${esc(lab)}</span><b>${nf(r[k])}</b></div>`).join(''); }}}]; }},
  ];
};

EVFIGS[2] = c => {
  const L = evRecs(c.data.lines);
  const xs = [...new Set(L.map(r => String(r.k)))].filter(k => k !== 'all').sort((a, b) => a - b).concat(['', 'all']);
  const row = (f, k) => L.find(r => r.family === f && String(r.k) === k) || {};
  const F = [['ma3', '3-month average (unaffected)', 'ma3'], ['tsb', NAME.tsb, 'tsb'], ['xgb_ma3', NAME.xgb, 'xgb']];
  const xl = k => k === 'all' ? 'all' : k;   // '' is the visual gap before the full-history point
  const periods = b => String(b || '').replace(/-/g, '').split('');
  const strip = {cmp: 'the simple average', title: 'Each square = one half-year test period (2 per setting)',
    rows: [['tsb', 'TSB vs simple average'], ['xgb_ma3', 'XGBoost + avg vs simple average']].map(([f, lab]) => ({label: lab,
      cells: Object.fromEntries(xs.filter(k => k !== '').map(k => { const p = periods(row(f, k).blocks); return [k, p.length ? p : ['NT']]; }))}))};
  const vr = [{x: '3', label: 'MA3 needs 3', dy: 10}, {x: '12', label: 'TSB from 12', dy: 10}, {x: '24', label: 'XGBoost from 24', dy: 22}];
  const tip = k => k === '' ? '' : `<div class="h">${k === 'all' ? 'all available history' : k + ' months of history'}</div>` + F.map(([f, lab, col]) => { const r = row(f, k);
    return `<div class="r"><span><i style="background:${EVT.dark[col]}"></i>${esc(lab)}</span><b>${(+r.median_wape).toFixed(3)} · ${(+r.mase_pass_pct).toFixed(0)}% beat naive</b></div>`; }).join('');
  const mk = (t, col, title, yfmt, strip_, h) => ({fr: {x: 0, y: 0, w: 900, h}, o: {ml: 190, xs, xlab: xl, strip: strip_, vrules: vr, tip,
    xtitle: 'Months of sales history the models were given (then all of it)', y: {fmt: yfmt, title},
    series: F.map(([f, lab, cc]) => ({key: f, label: lab, color: t[cc], width: f === 'ma3' ? 2.6 : 2, pts: xs.map(k => [k, k === '' ? null : row(f, k)[col] ?? null])}))}});
  return [
    {file: 'ch02_truncation_wape', title: 'Forecast error when the models see only the last few months',
     read: 'Left to right = more months of sales history given to the models; dashed lines = the cut-offs we use. Up = more error, so lower is better. '
       + 'Only products with at least 30 months of sales are used, so every setting is tested on the same months. MA3 always uses just 3 months, so its line is flat. '
       + 'Gaps between lines smaller than the margin of error count as ties; the squares show which differences are real.',
     W: 900, H: 450, build: t => [mk(t, 'median_wape', ERR, v => v.toFixed(3), strip, 450)]},
    {file: 'ch02_truncation_mase', title: 'Share of products forecast better than a naive guess',
     read: 'Up = more products whose forecast beats a naive “same as last month” guess (MASE below 1). Higher is better.',
     W: 900, H: 300, build: t => [mk(t, 'mase_pass_pct', 'Products beating a naive guess (higher is better)', v => v.toFixed(0) + '%', null, 300)]},
  ];
};

EVFIGS[3] = c => {
  const L = evRecs(c.data.lines), V = evRecs(c.data.verdicts);
  const blocks = [...new Set(L.filter(r => r.window !== 'full').map(r => r.window))];
  const W_ = [['ma2', '2-month average (MA2)', 0, null], ['ma3', '3-month average (MA3, ours)', null, null], ['ma6', '6-month average (MA6)', 1, '6 3'], ['ma12', '12-month average (MA12)', 2, '2 3']];
  const strip = {cmp: 'the 3-month average', rows: W_.filter(w => w[0] !== 'ma3').map(([m, lab]) => ({label: lab.replace(/ \(.*/, '') + ' vs 3-month',
    cells: Object.fromEntries(blocks.map(b => { const r = V.find(v => v.model === m && v.window === b); return [b, r ? r.verdict : 'NT']; }))}))};
  return [{file: 'ch03_ma_window', title: 'Forecast error of moving averages over different windows',
    read: 'Each dot = one half-year test period. Up = more forecast error, so lower is better. The squares say whether each window did better or worse than the 3-month average in that period. '
      + 'Gaps between lines smaller than the margin of error count as ties; the squares show which differences are real.',
    W: 900, H: 420,
    build: t => [{fr: {x: 0, y: 0, w: 900, h: 420}, o: {ml: 190, mr: 190, xs: blocks, xlab: blab, strip, y: {fmt: v => v.toFixed(2), title: ERR},
      series: W_.map(([m, lab, ri, dash]) => ({key: m, label: lab, color: ri == null ? t.ma3 : t.ramp[ri], dash, width: ri == null ? 2.6 : 1.8,
        pts: blocks.map(b => [b, (L.find(r => r.window === b && r.model === m) || {}).median_wape ?? null])}))}}]}];
};

EVFIGS[4] = c => {
  const L = evRecs(c.data.lines), V = evRecs(c.data.verdicts);
  const ws = [...new Set(L.map(r => r.weight))].sort((a, b) => a - b);
  const wins = [...new Set(L.filter(r => r.n > 0).map(r => r.window))];
  const lab = w => w === 'full' ? 'All test months' : blab(w);
  const cells = ag => Object.fromEntries(ws.map(w => { const vv = V.filter(v => v.weight === w && v.against === ag && v.window !== 'full' && v.verdict !== 'NT').map(v => v.verdict);
    return [String(w), (ag === 'w=0.5' && w === 0.5) || (ag === 'MA3' && w === 0) ? null : (vv.length ? vv : ['NT'])]; }));
  const fullPts = L.filter(r => r.window === 'full' && r.median_wape != null);
  const best = fullPts.length ? fullPts.reduce((b, r) => r.median_wape < b.median_wape ? r : b) : null;
  const dip = c.verdict === 'CONFIRMS' && best && best.weight !== 0.5
    ? ` The ‘All test months’ line is lowest at ${best.weight.toFixed(1)}, but no mix beats 50/50 in the test periods (see the squares), so that dip is within the margin of error.` : '';
  const strip = {cmp: 'the comparison in the row', title: 'Each square = one half-year test period (2 per weight)',
    rows: [{label: 'vs our 50/50 mix', cells: cells('w=0.5')}, {label: 'vs 3-month average alone', cells: cells('MA3')}]};
  return [{file: 'ch04_blend_weight', title: 'Forecast error for each XGBoost / 3-month-average mix (products with 24+ months of history)',
    read: 'Left = only the 3-month average; right = only XGBoost; 0.5 = the 50/50 mix we use. Up = more error, so lower is better. '
      + 'Only two half-year periods can be tested, because products reach 24 months of history only from Jan 2025.' + dip,
    W: 900, H: 430,
    build: t => [{fr: {x: 0, y: 0, w: 900, h: 430}, o: {ml: 170, xs: ws, xlab: w => w.toFixed(1), strip, xtitle: 'Weight on XGBoost (0 = only the 3-month average, 1 = only XGBoost)',
      vrules: [{x: 0.5, label: 'our mix (0.5)'}], y: {fmt: v => v.toFixed(3), title: ERR},
      series: wins.map((w, i) => ({key: w, label: lab(w), color: w === 'full' ? t.ramp[2] : t.ramp[i === 1 ? 1 : 0],
        dash: w === 'full' ? null : (i === 1 ? '6 3' : '2 3'), width: w === 'full' ? 2.6 : 1.8,
        pts: ws.map(x => [x, (L.find(r => r.window === w && r.weight === x) || {}).median_wape ?? null])}))}}]}];
};

EVFIGS[5] = c => {
  const R = evRecs(c.data.rates);
  const plain = {'original 50': 'Earlier 50 methods', 'phase 1 (35)': '35 transforms', 'phase 2 (77)': '77 more transforms', 'all 162': 'All 162 together'};
  return [{file: 'ch05_transforms', title: 'How often a method won a test period, compared with pure luck',
    read: 'Each bar = how often methods in that group beat the method we use in a half-year test period; the black whisker is the margin of error. '
      + 'Dashed line = how often they would win by luck alone. Bars below the line = no real gain.',
    W: 900, H: 340,
    build: t => [{fr: {x: 0, y: 0, w: 900, h: 340}, draw: evBars, o: {cats: R.map(r => plain[r.candidate_set] || r.candidate_set), vals: R.map(r => r.block_win_rate),
      lo: R.map(r => r.cp_lo), hi: R.map(r => r.cp_hi), colors: R.map(r => r.candidate_set === 'all 162' ? t.ramp[2] : t.blue),
      labels: R.map(r => `${r.block_wins} wins in ${nf(r.testable_blocks)}`), sub: R.map(r => `${r.real} real wins`),
      fmt: v => (v * 100).toFixed(1) + '%', ytitle: 'Share of test periods won (lower = less gain)',
      hrules: [{y: R[0].chance_per_block, label: `luck alone (${(R[0].chance_per_block * 100).toFixed(1)}%)`}],
      tip: k => { const r = R.find(q => (plain[q.candidate_set] || q.candidate_set) === k); return `<div class="h">${esc(k)} · ${r.candidates} methods</div>`
        + `<div class="r"><span>test periods won</span><b>${r.block_wins} / ${nf(r.testable_blocks)} = ${pc(r.block_win_rate, 2)}</b></div>`
        + `<div class="r"><span>margin of error (95%)</span><b>${pc(r.cp_lo, 2)} – ${pc(r.cp_hi, 2)}</b></div>`
        + `<div class="r"><span>real wins</span><b>${r.real}</b></div>`; }}}]}];
};

EVFIGS[6] = c => {
  const S = evRecs(c.data.skus), M = evRecs(c.data.months);
  if (EVSTATE[6] == null) EVSTATE[6] = S[0].pk;
  const causes = [...new Set(S.map(s => s.cause_group))], cnt = causes.map(k => S.filter(s => s.cause_group === k).length);
  const plainCause = {'level shift': 'Sales level jumped', 'spiky': 'Sudden spikes', 'high volatility': 'Very up-and-down',
                      'tiny scale': 'Very small volumes', 'none of the above': 'No clear cause', 'intermittent': 'Months with no sales', 'trend reversal': 'Trend reversed'};
  const pcause = k => plainCause[k] || k;
  return [
    {file: () => `ch06_unfit_${(S.find(s => s.pk === EVSTATE[6]) || {}).sku_code}`, title: 'One poorly-forecast product: sales, our forecast and its likely range',
     read: 'Pick a product. Grey = actual monthly sales. Coloured line = our forecast for the recent test months, with its likely range shaded. '
       + 'Circle = an unusual spike. Shaded columns = the two periods compared when checking for a jump in the sales level.',
     W: 900, H: 340,
     control: {options: S.map(s => [s.pk, `${s.sku_code} · ${s.product_name} · ${pcause(s.cause_group)}`]), get: () => EVSTATE[6], set: v => { EVSTATE[6] = +v; }},
     build: t => {
       const s = S.find(q => q.pk === EVSTATE[6]), R = M.filter(r => r.pk === s.pk), ms = R.map(r => r.month), col = t[SERVED[s.served_model]] || t.blue;
       const rects = []; const firstLast = f => { const k = R.filter(f); return k.length ? [k[0].month, k[k.length - 1].month] : null; };
       const pr = firstLast(r => r.level_prior), rc = firstLast(r => r.level_recent);
       if (pr) rects.push({x0: pr[0], x1: pr[1], op: 0.05, label: 'earlier 12 months'}); if (rc) rects.push({x0: rc[0], x1: rc[1], op: 0.11, label: 'last 6'});
       return [{fr: {x: 0, y: 0, w: 900, h: 340}, o: {xs: ms, xticks: ms.filter((m, i) => i % 3 === 0), xlab: mlab, rects,
         title: `${s.sku_code} · ${s.product_name} · main cause: ${pcause(s.cause_group)}`,
         y: {fmt: v => nf(v), title: 'Units sold', zero: true},
         series: [{key: 'actual', label: 'Actual sales', color: t.actual, width: 2.2, r: 2.5, pts: R.map(r => [r.month, r.actual])},
                  {key: 'fc', label: 'Our forecast + range', color: col, width: 2, band: R.map(r => [r.month, r.band_lo, r.band_hi]),
                   pts: R.map(r => [r.month, r.holdout ? r.forecast : null])},
                  {key: 'spike', label: 'Unusual spike', color: t.ink, line: false, hollow: true, r: 6, pts: R.map(r => [r.month, r.spike ? r.actual : null])}],
         tip: m => { const r = R.find(q => q.month === m); return `<div class="h">${mlab(m)}${r.spike ? ' · unusual spike' : ''}</div>`
           + `<div class="r"><span>Actual sales</span><b>${nf(r.actual)}</b></div>` + (r.holdout ? `<div class="r"><span>Our forecast</span><b>${nf(r.forecast)}</b></div>`
           + `<div class="r"><span>Likely range</span><b>${nf(r.band_lo)} – ${nf(r.band_hi)}</b></div><div class="r"><span>Outside the range</span><b>${r.outside_band ? 'yes' : 'no'}</b></div>` : ''); }}}]; }},
    {file: 'ch06_unfit_causes', title: 'Poorly-forecast products by main cause',
     read: 'Each bar = how many poorly-forecast products share that main cause. Hover a bar to list them.',
     W: 900, H: 290,
     build: t => [{fr: {x: 0, y: 0, w: 900, h: 290}, draw: evBars, o: {cats: causes.map(pcause), vals: cnt, labels: cnt.map(String), fmt: v => v.toFixed(0), ytitle: 'Number of products',
       tip: k => { const orig = causes.find(q => pcause(q) === k); return `<div class="h">${esc(k)}</div>` + S.filter(s => s.cause_group === orig).map(s => `<div class="r"><span>${esc(s.sku_code)}</span><b>${esc(s.product_name)}</b></div>`).join(''); }}}]},
  ];
};

EVFIGS[7] = c => {
  const C7 = evRecs(c.data.curve);
  const S = [['unilever', 'single', 'Unilever', 'blue', null], ['unilever', 't3m', 'Unilever, 3-month view', 'blue', '6 4'], ['delmonte', 'single', 'Del Monte (categories)', 'mag', null]]
    .map(([p, m, lab, col, dash]) => ({p, m, lab, col, dash, R: C7.filter(r => r.principal === p && r.method === m)})).filter(s => s.R.length);
  return [{file: 'ch07_pareto', title: 'How revenue builds up across products, highest earners first',
    read: 'Left to right = products ranked from highest to lowest revenue (as a share of all products). Up = share of total revenue so far. '
      + 'A steep early rise means a few products carry most of the revenue. Products left of where a line crosses 80% are Tier A.'
      + (S.find(s => s.p === 'delmonte') ? ` Del Monte is ranked by product category, and it has only ${S.find(s => s.p === 'delmonte').R.length} categories, so its line has that many points.` : ''),
    W: 900, H: 390,
    build: t => [{fr: {x: 0, y: 0, w: 900, h: 390}, o: {xnum: true, xdom: [0, 1], xs: [0, 0.2, 0.4, 0.6, 0.8, 1], xlab: v => (v * 100).toFixed(0) + '%', mr: 190,
      xtitle: 'Products, from highest to lowest revenue (share of all products)', y: {dom: [0, 1.02], fmt: v => (v * 100).toFixed(0) + '%', title: 'Share of total revenue'},
      hrules: [{y: 0.8, label: '80% of revenue: Tier A ends', inside: true}, {y: 0.95, label: '95%: Tier B ends', inside: true}],
      series: S.map(s => ({key: s.p + s.m, label: s.lab, color: t[s.col], dash: s.dash, width: 2,
        markers: s.R.length < 20, r: 4.5, pts: s.R.map(r => [r.rank_share, r.cumulative_share]), R: s.R})),
      tip: x => `<div class="h">top ${(x * 100).toFixed(0)}% of products</div>` + S.map(s => { const r = s.R.reduce((b, q) => Math.abs(q.rank_share - x) < Math.abs(b.rank_share - x) ? q : b);
        return `<div class="r"><span><i style="background:${EVT.dark[s.col]}"></i>${esc(s.lab)}</span><b>#${r.rank} ${esc(r.label)} · Tier ${r.tier} · ${(r.cumulative_share * 100).toFixed(2)}%</b></div>`; }).join('')}}]}];
};

EVFIGS[8] = c => {
  const A = evRecs(c.data.totals), cats = A.map(r => r.allocation_pct + '%');
  const tip = k => { const r = A.find(q => q.allocation_pct + '%' === k); return `<div class="h">allocation ${esc(k)} of last year's sales</div>`
    + `<div class="r"><span>ordered / needed</span><b>${nf(r.ordered)} / ${nf(r.need)} units</b></div><div class="r"><span>could not order</span><b>${nf(r.shortfall)} units, ${r.n_short} products</b></div>`
    + `<div class="r"><span>stock at month end</span><b>${(+r.month_end_cover_weeks).toFixed(6)} weeks</b></div><div class="r"><span>vs the 3-week target</span><b>₱${(+r.cover_gap_php).toFixed(2)}</b></div>`; };
  return [{file: 'ch08_allocation', title: 'What each allocation level leaves: shortages and weeks of stock (planning inputs are placeholders)',
    read: 'Each bar = one allocation level (103%, 105%, 108% of last year’s sales; 105% is the default). '
      + 'Left: units we could not order (lower is better). Right: weeks of sales the month-end stock would cover (dashed = 3-week target).',
    W: 900, H: 330,
    build: t => [
      {fr: {x: 0, y: 0, w: 450, h: 330}, draw: evBars, o: {title: 'Units we could not order (lower is better)', cats, vals: A.map(r => r.shortfall),
        labels: A.map(r => `${nf(r.shortfall)} (${r.n_short} products)`), sub: A.map(r => r.allocation_pct === 105 ? 'default' : ''), fmt: v => nf(v), mr: 30, tip}},
      {fr: {x: 450, y: 0, w: 450, h: 330}, draw: evBars, o: {title: 'Weeks of stock at month end', cats, vals: A.map(r => r.month_end_cover_weeks),
        labels: A.map(r => `${(+r.month_end_cover_weeks).toFixed(2)} weeks`),
        sub: A.map(r => r.cover_gap_php < 0 ? `₱${(-r.cover_gap_php).toFixed(2)} short of 3 weeks` : 'above 3 weeks'),
        fmt: v => v.toFixed(1), hrules: [{y: 3, label: '3-week target'}], mr: 90, tip}}]}];
};

EVFIGS[9] = c => {
  const G = evRecs(c.data.grid), d0 = G.find(g => g.is_default);
  const draw = (t, fr) => {
    const M = {l: 64, r: 280, t: 16, b: 40}, side = Math.min(fr.w - M.l - M.r, fr.h - M.t - M.b), X0 = fr.x + M.l, Y0 = fr.y + M.t, n = 21, cs = side / n;
    const cx = w1 => X0 + Math.round(w1 / 0.05) * cs, cy = w2 => Y0 + side - (Math.round(w2 / 0.05) + 1) * cs;
    let g = '';
    G.forEach(r => { const x = cx(r.w1), y = cy(r.w2);
      g += `<rect x="${(x + 1).toFixed(1)}" y="${(y + 1).toFixed(1)}" width="${(cs - 2).toFixed(1)}" height="${(cs - 2).toFixed(1)}" rx="2" fill="${r.cut_set_differs ? t.red : t.blue}"`
        + (r.neighbour ? ` stroke="${t.ink}" stroke-width="1.4"` : '') + `/>`; });
    g += `<circle cx="${(cx(d0.w1) + cs / 2).toFixed(1)}" cy="${(cy(d0.w2) + cs / 2).toFixed(1)}" r="${(cs * 0.62).toFixed(1)}" fill="none" stroke="${t.ink}" stroke-width="2"/>`;
    [0, 0.2, 0.4, 0.6, 0.8, 1].forEach(v => { g += txt(t, cx(v) + cs / 2, Y0 + side + 14, v.toFixed(1), {size:10, fill:t.ink3, anchor:'middle'})
      + txt(t, X0 - 6, cy(v) + cs / 2, v.toFixed(1), {size:10, fill:t.ink3, anchor:'end', base:'middle'}); });
    g += txt(t, X0 + side / 2, Y0 + side + 30, 'Weight on cost → (weight on storage = what is left)', {size:10.5, fill:t.ink2, anchor:'middle'});
    g += `<text transform="translate(${fr.x + 14},${(Y0 + side / 2).toFixed(1)}) rotate(-90)" text-anchor="middle" font-size="10.5" fill="${t.ink2}" font-family="${EVFONT}">Weight on service →</text>`;
    const lx = X0 + side + 24; let ly = Y0 + 10;
    [[t.blue, 'Same products cut as today'], [t.red, 'Different products cut']].forEach(([cl, s]) => { g += `<rect x="${lx}" y="${ly - 6}" width="12" height="12" rx="2" fill="${cl}"/>` + txt(t, lx + 18, ly, s, {size:10.5, base:'middle'}); ly += 20; });
    g += `<rect x="${lx}" y="${ly - 6}" width="12" height="12" rx="2" fill="none" stroke="${t.ink}" stroke-width="1.4"/>` + txt(t, lx + 18, ly, 'Small change from today (±0.10)', {size:10.5, base:'middle'}); ly += 20;
    g += `<circle cx="${lx + 6}" cy="${ly}" r="7" fill="none" stroke="${t.ink}" stroke-width="2"/>` + txt(t, lx + 18, ly, `Today: cost ${d0.w1}, service ${d0.w2}, storage ${d0.w3}`, {size:10.5, base:'middle'});
    const geo = {X0, Y0, pw: side, ph: side, pick: (mx, my) => { const i = Math.floor((mx - X0) / cs), j = n - 1 - Math.floor((my - Y0) / cs);
        return G.find(r => Math.round(r.w1 / 0.05) === i && Math.round(r.w2 / 0.05) === j) || null; },
      tip: r => `<div class="h">cost ${r.w1} · service ${r.w2} · storage ${r.w3}${r.is_default ? ' (today)' : ''}</div>`
        + `<div class="r"><span>products cut short</span><b>${r.n_short}</b></div><div class="r"><span>units short</span><b>${nf(r.shortfall)}</b></div>`
        + `<div class="r"><span>order cost</span><b>₱${nf(r.order_cost)}</b></div><div class="r"><span>same products cut as today?</span><b>${r.cut_set_differs ? 'no' : 'yes'}</b></div>`};
    return {g, geo};
  };
  return [{file: 'ch09_lp_weights', title: 'Does changing the order plan’s priorities change which products get cut?',
    read: 'Each square = one way of weighting cost, service and storage in the order plan (LP), in steps of 0.05. Across = weight on cost; up = weight on service. '
      + 'Blue = the same products get cut short as today; red = different ones. The outlined squares are small changes from today’s weights.',
    W: 900, H: 470, build: () => [{fr: {x: 0, y: 0, w: 900, h: 470}, draw}]}];
};

EVFIGS[10] = c => {
  const T = evRecs(c.data.curve), xs = T.map(r => Math.round(r.service_level * 100)), at = x => T[xs.indexOf(x)];
  const cur = [{x: 90, label: 'ours (90%)'}];
  const p = (t, x, title, key, fmt, extra) => ({fr: {x, y: 0, w: 300, h: 300}, o: {ml: 58, mr: 16, mt: 24, xs, xticks: [85, 90, 95, 99], xlab: v => v + '%', title,
    vrules: cur, y: {fmt, zero: true}, ...extra, series: extra && extra.series ? extra.series : [{key, label: title, color: t.blue, labelEnd: false, r: 2.5, pts: xs.map(v => [v, at(v)[key]])}],
    tip: v => { const r = at(v); return `<div class="h">promised service level ${v}%</div>`
      + `<div class="r"><span>safety stock held</span><b>${nf(r.total_safety_stock_pieces)} units</b></div>`
      + `<div class="r"><span>months with a stockout / year (estimate)</span><b>${nf(r.model_stockout_sku_months_per_year, 1)}</b></div>`
      + `<div class="r"><span>demand beat forecast + buffer (measured)</span><b>${pc(r.measured_exceedance)}</b></div>`
      + `<div class="r"><span>allowed by the promise</span><b>${pc(r.nominal_exceedance)}</b></div>`; }}});
  return [{file: 'ch10_service_level', title: 'Holding more safety stock vs running out',
    read: 'Left to right = a higher promised service level (90% = our setting). Left: extra stock held (up = more stock). '
      + 'Middle: estimated product-months with a stockout per year (lower is better). Right: how often real demand beat forecast plus buffer, measured (blue) vs what the promise allows (dashed); below the dashed line = the buffer does its job.',
    W: 900, H: 300,
    build: t => [
      p(t, 0, 'Safety stock held (units)', 'total_safety_stock_pieces', v => nf(v / 1000) + 'k'),
      p(t, 300, 'Stockout months / year (estimate)', 'model_stockout_sku_months_per_year', v => nf(v)),
      p(t, 600, 'Demand beat forecast + buffer', null, v => (v * 100).toFixed(0) + '%', {mr: 74, series: [
        {key: 'meas', label: 'measured', color: t.blue, r: 2.5, band: xs.map(v => [v, at(v).measured_ci_lo, at(v).measured_ci_hi]), pts: xs.map(v => [v, at(v).measured_exceedance])},
        {key: 'nom', label: 'promised', color: t.base, dash: '4 3', markers: false, pts: xs.map(v => [v, at(v).nominal_exceedance])}]})]}];
};

EVFIGS[11] = c => {
  const I = evRecs(c.data.index), moys = [...Array(12).keys()].map(i => i + 1);
  const panel = (t, x, w, p, ser, title, years) => ({fr: {x, y: 0, w, h: 320}, o: {ml: 48, mr: 100, mt: 24, xs: moys, xlab: m => MON[m - 1].slice(0, 1), title,
    hrules: [{y: 1, label: ''}], y: {fmt: v => v.toFixed(1)},
    series: years.map((yy, i) => { const R = I.filter(r => r.principal === p && r.series === ser && r.year === yy); if (!R.length) return null;
      const part = R[0].months_in_year < 12 ? ` (${R[0].months_in_year} of 12 mo)` : '';
      return {key: String(yy), label: `${yy}${part}`, color: t.ramp[i], dash: part ? '4 3' : null, width: 2, r: 3,
        pts: moys.map(m => [m, (R.find(r => r.moy === m) || {}).index ?? null])}; }).filter(Boolean),
    tip: m => `<div class="h">${MON[m - 1]} · ${esc(title)}</div>` + years.map((yy, i) => { const r = I.find(q => q.principal === p && q.series === ser && q.year === yy && q.moy === m);
      return r ? `<div class="r"><span><i style="background:${EVT.dark.ramp[i]}"></i>${yy}</span><b>${(+r.index).toFixed(2)} × average · ₱${nf(r.net_amount / 1e6, 2)}M</b></div>` : ''; }).join('')}});
  const br = (t) => ({fr: {x: 600, y: 0, w: 300, h: 320}, o: {ml: 48, mr: 100, mt: 24, xs: moys, xlab: m => MON[m - 1].slice(0, 1), title: 'Del Monte by branch, 2023',
    hrules: [{y: 1, label: ''}], y: {fmt: v => v.toFixed(1)},
    series: [['branch pangasinan (2023 only)', 'Pangasinan', 'blue'], ['branch ilocos (2023 only)', 'Ilocos', 'mag']].map(([s, lab, col]) => {
      const R = I.filter(r => r.series === s); return {key: s, label: lab, color: t[col], width: 2, r: 3, pts: moys.map(m => [m, (R.find(r => r.moy === m) || {}).index ?? null])}; })}});
  return [{file: 'ch11_month_of_year', title: 'Each month’s sales compared with that year’s average month',
    read: 'Each line = one year; left to right = January to December. Above 1 = a stronger-than-average month. '
      + 'Lines that rise and fall together would mean a repeating yearly season. Dashed lines = incomplete years.',
    W: 900, H: 320,
    build: t => [panel(t, 0, 300, 'delmonte', 'total', 'Del Monte, all branches', [2023, 2024, 2025]),
                 panel(t, 300, 300, 'unilever', 'total', 'Unilever', [2023, 2024, 2025]), br(t)]}];
};

// ---- cards ---------------------------------------------------------------------------
function evDetails(c){
  const checks = (c.checks || []).map(k => `<li><span class="${k.pass ? 'evok' : 'evno'}">${k.pass ? '✓' : '✗'} ${esc(k.id)}</span> ${esc(k.detail)}</li>`).join('');
  const amends = (c.amendments || []).map(a => `<div class="evamend"><b>Amended ${esc(a.date)} (${esc(a.item)}, ${esc(a.approved_by)}):</b> ${esc(a.amended)} <span class="muted">— ${esc(a.reason)}</span></div>`).join('');
  const files = Object.values(c.files || {}).map(f => `<code>${esc(f)}</code>`).join(' ');
  return `<details class="evdetails"><summary>Details (for the paper)</summary>`
    + `<div class="evcrit"><b>Pre-registered — flawed if:</b> ${esc(c.criterion)} <span class="muted">Otherwise: ${esc(c.otherwise)}. Stored verdict: <b>${esc(c.verdict)}</b>.</span></div>`
    + (c.verdict_detail ? `<div class="evdetail">${esc(c.verdict_detail)}</div>` : '')
    + (c.caption ? `<p class="evcap"><b>Caption.</b> ${esc(c.caption)} <button class="evbtn evcopy" data-c="${c.chart}">Copy caption</button></p>` : '')
    + amends
    + (checks ? `<ul class="evlist checks">${checks}</ul>` : '')
    + ((c.data_notes || []).length ? `<ul class="evlist">${c.data_notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>` : '')
    + `<div class="evprov"><span>MASE gate used: <b>${esc(c.mase_gate_used)}</b></span><span>Re-run after 5f: <b>${esc(c.rerun_after_5f)}</b></span>`
    + (c.script ? `<span>Script <code>${esc(c.script)}</code> @ <code>${esc(c.code_commit)}</code>, ${esc(c.computed_at)}</span>` : '')
    + (c.caption_restamped_by ? `<span>Caption restamped by <code>${esc(c.caption_restamped_by)}</code></span>` : '')
    + (files ? `<span>Data ${files}</span>` : '') + `</div></details>`;
}
function evCard(c){
  const figs = c.verdict === 'NOT BUILT' ? [] : (EVFIGS[c.chart] ? EVFIGS[c.chart](c) : []);
  c._figs = figs;
  return `<article class="evcard" id="ev-${c.chart}"><div class="evhead"><span class="evnum">Decision ${c.chart}</span>`
    + `<span class="evdec">${esc(DECISION[c.chart] || c.title)}</span>${evChip(c.verdict)}</div>`
    + `<h3 class="evheadline">${esc(HEAD[c.chart] ? HEAD[c.chart](c) : c.title)}</h3>`
    + `<p class="evtest"><b>The test:</b> ${esc(TEST[c.chart] || '')}</p>`
    + `<div class="evfigs">${figs.map((f, i) => `<figure class="evfig"><div class="evfhead"><span class="evftitle">${esc(f.title)}</span>`
      + (f.control ? `<select class="evsel" data-c="${c.chart}" data-f="${i}">${f.control.options.map(([v, l]) => `<option value="${v}"${v === f.control.get() ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>` : '')
      + `<span class="evbtns"><button class="evbtn" data-c="${c.chart}" data-f="${i}" data-k="svg">SVG</button><button class="evbtn" data-c="${c.chart}" data-f="${i}" data-k="png">PNG</button></span></div>`
      + `<div class="evread"><b>How to read this:</b> ${esc(f.read || '')}</div>`
      + (f.toggle && i === figs.findIndex(q => q.toggle) ? `<label class="evtoggle"><input type="checkbox" data-c="${c.chart}" data-t="${f.toggle.key}"${EVSTATE[f.toggle.key] ? ' checked' : ''}> ${esc(f.toggle.label)}</label>` : '')
      + `<div class="evsvg" id="evs-${c.chart}-${i}"></div></figure>`).join('')}</div>`
    + (c.verdict === 'NOT BUILT' ? '' : evDetails(c)) + `</article>`;
}
function drawEvidence(){
  if (evOnce.drawn) return;
  evOnce.drawn = true;
  const C = EV.charts;
  const intro = `<div class="card evintro"><h2>Evidence: is each modelling decision backed by the data?</h2>`
    + `<p class="evlead">Each card below tests one decision we made. The pass/fail rule for every test was written down and committed <b>before</b> the result was computed, `
    + `and results are shown exactly as they came out, including the one that questions our choice. A “tie” means the data cannot tell two options apart.</p>`
    + `<p class="evlead">Read each card from the top: the <b>headline</b> is the takeaway, the <b>coloured label</b> says whether our choice holds, and the chart shows why. `
    + `Numbers for the paper, the exact test and the data notes are under <b>Details (for the paper)</b> on each card. Real sales only; SVG/PNG exports use a white print style.</p>`
    + (EV.uncommitted.length ? `<p class="evno">Computed from uncommitted code: charts ${EV.uncommitted.join(', ')}.</p>` : '')
    + `<div class="evsumgrid">${C.map(c => `<a class="evsumrow" href="#ev-${c.chart}"><span class="evnum">${c.chart}</span><span>${esc(DECISION[c.chart] || c.title)}</span><span>${evChip(c.verdict)}</span></a>`).join('')}</div>`
    + `<details class="evgloss"><summary>Glossary: every term on this page</summary><dl>${GLOSSARY.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl></details>`
    + `<details class="evgloss"><summary>Technical summary (checks, MASE gate, re-run after session 5f)</summary><table class="evsum"><thead><tr><th>#</th><th>Chart</th><th>Stored verdict</th><th>Checks</th><th>MASE gate</th><th>Re-run after 5f</th></tr></thead><tbody>`
    + C.map(c => `<tr><td class="num">${c.chart}</td><td>${esc(c.title)}</td><td>${esc(c.verdict)}</td>`
      + `<td>${(c.checks || []).map(k => `<span class="${k.pass ? 'evok' : 'evno'}">${k.pass ? '✓' : '✗'} ${esc(k.id)}</span>`).join(' ') || '<span class="muted">—</span>'}</td>`
      + `<td>${esc(c.mase_gate_used)}</td><td>${esc(c.rerun_after_5f)}</td></tr>`).join('') + `</tbody></table></details></div>`;
  $('#evidence').innerHTML = intro + `<div class="evgrid">${C.map(evCard).join('')}</div>`;
  C.forEach(c => (c._figs || []).forEach((f, i) => evRender($(`#evs-${c.chart}-${i}`), f)));
  $('#evidence').addEventListener('click', e => {
    const b = e.target.closest('.evbtn'); if (!b) return;
    const c = C.find(x => x.chart === +b.dataset.c);
    if (b.classList.contains('evcopy')){ navigator.clipboard.writeText(c.caption).then(() => { b.textContent = 'Copied'; setTimeout(() => { b.textContent = 'Copy caption'; }, 1200); }); return; }
    evExport(c._figs[+b.dataset.f], b.dataset.k);
  });
  $('#evidence').addEventListener('change', e => {
    const s = e.target.closest('.evsel'), tg = e.target.closest('input[data-t]');
    const c = C.find(x => x.chart === +(s || tg || {dataset: {}}).dataset.c); if (!c) return;
    if (s){ const f = c._figs[+s.dataset.f]; f.control.set(s.value); evRender($(`#evs-${c.chart}-${s.dataset.f}`), f); }
    if (tg){ EVSTATE[tg.dataset.t] = tg.checked; c._figs.forEach((f, i) => { if (f.toggle) evRender($(`#evs-${c.chart}-${i}`), f); }); }
  });
}
// Dev hook (scripted checks and batch export): the light print SVG of chart `chart`, figure `fig`.
window.evidenceExportSVG = (chart, fig) => { drawEvidence(); const c = EV.charts.find(x => x.chart === chart);
  return c && c._figs[fig] ? evFigure(EVT.light, c._figs[fig]).svg : null; };
// Dev hook for the readability check: each card's headline, chip text and chart titles.
window.evidenceCards = () => { drawEvidence(); return EV.charts.map(c => ({chart: c.chart, verdict: c.verdict, headline: HEAD[c.chart] ? HEAD[c.chart](c) : '',
  words: (HEAD[c.chart] ? HEAD[c.chart](c) : '').split(/\s+/).length})); };
return drawEvidence;
})();
