// ================= EVIDENCE tab (tools/dsd_dev_viewer/evidence.js) =================
// Every number drawn here is read from D.evidence, which evidence.py loads from
// reports/evidence/ (written by scripts/evidence/*.py). The page computes layout only.
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
         W:'#0ca30c', L:'#d03b3b', T:'#3a4150', Tink:'#eef0f6', band:0.18, shade:'#ffffff'},
  light: {surface:'#ffffff', ink:'#0b0b0b', ink2:'#52514e', ink3:'#898781', grid:'#e1e0d9', axis:'#c3c2b7',
          ma3:'#1baf7a', tsb:'#4a3aa7', xgb:'#eb6834', base:'#898781', actual:'#52514e',
          blue:'#2a78d6', mag:'#e87ba4', red:'#e34948', ramp:['#86b6ef', '#2a78d6', '#104281'],
          W:'#0ca30c', L:'#d03b3b', T:'#e1e0d9', Tink:'#0b0b0b', band:0.16, shade:'#000000'},
};
const evRecs = t => t ? t.rows.map(r => Object.fromEntries(t.cols.map((c, i) => [c, r[i]]))) : [];
const nf = (v, d=0) => v == null || Number.isNaN(+v) ? '—' : Number(v).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
const pc = (v, d=1) => v == null ? '—' : (v * 100).toFixed(d) + '%';
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const mlab = m => MON[+String(m).slice(5, 7) - 1] + ' ' + String(m).slice(2, 4);
const blab = w => { const [a, b] = String(w).split('..'); return mlab(a) + '–' + mlab(b); };
const EVSTATE = {};
const evOnce = {drawn: false};

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
function evCell(t, x, y, w, h, v, text){
  const fill = v === 'W' ? t.W : v === 'L' ? t.L : v === 'NT' ? 'none' : t.T;
  const ink = v === 'W' || v === 'L' ? '#ffffff' : v === 'NT' ? t.ink3 : t.Tink;
  return `<rect x="${x.toFixed(1)}" y="${y}" width="${w.toFixed(1)}" height="${h}" rx="3" fill="${fill}"`
    + (v === 'NT' ? ` stroke="${t.axis}" stroke-dasharray="2 2"` : '') + `/>`
    + txt(t, x + w / 2, y + h / 2 + 0.5, text, {size:9.5, fill:ink, anchor:'middle', base:'middle', weight:600});
}
const majority = s => { const t = String(s || '').replace(/[-N]/g, ''); if (!t) return 'NT';
  const w = (t.match(/W/g) || []).length, l = (t.match(/L/g) || []).length;
  return w * 2 > t.length ? 'W' : l * 2 > t.length ? 'L' : 'T'; };

// ---- one line plot inside a frame -------------------------------------------
function evPlot(t, fr, o){
  const stripH = o.strip ? o.strip.rows.length * 18 + 10 : 0;
  const M = {l: o.ml ?? 58, r: o.mr ?? 128, t: o.mt ?? 16, b: 22 + (o.xsub ? 12 : 0) + (o.xtitle ? 16 : 0)};
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
  for (let i = 1; i < labs.length; i++) if (labs[i].y - labs[i - 1].y < 12) labs[i].y = labs[i - 1].y + 12;
  labs.forEach(l => { g += `<line x1="${(X0 + pw + 4).toFixed(1)}" x2="${(X0 + pw + 14).toFixed(1)}" y1="${l.y.toFixed(1)}" y2="${l.y.toFixed(1)}" stroke="${l.s.color}" stroke-width="2"${l.s.dash ? ` stroke-dasharray="${l.s.dash}"` : ''}/>`
    + txt(t, X0 + pw + 18, l.y, l.s.label, {size:10.5, fill:t.ink, base:'middle'}); });
  if (o.strip){
    const sy0 = Y0 + ph + M.b + 4, cw = Math.min(step * 0.88, 96);
    if (o.strip.title) g += txt(t, X0 - 6, sy0 - 3, o.strip.title, {size:9.5, fill:t.ink3, anchor:'end'});
    o.strip.rows.forEach((row, i) => { const y = sy0 + i * 18 + 2;
      g += txt(t, X0 - 6, y + 7, row.label, {size:10, fill:t.ink2, anchor:'end', base:'middle'});
      o.xs.forEach(xv => { const c = row.cells[String(xv)]; if (c) g += evCell(t, xp(xv) - cw / 2, y, cw, 14, c.v, c.text); }); });
  }
  const geo = {X0, Y0, pw, ph, cat, xs: o.xs, step, xp, xdom: o.xdom, series: o.series, fmt: o.y.tfmt || o.y.fmt, xlab: o.xlab, tip: o.tip, free: o.free};
  return {g, geo};
}

// ---- bars (one series, optional CI whiskers) ---------------------------------
function evBars(t, fr, o){
  const M = {l: o.ml ?? 64, r: o.mr ?? 110, t: o.title ? 40 : 22, b: 34};
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
    if (o.sub) g += txt(t, xc(i), Y0 + ph + 26, o.sub[i], {size:9, fill:t.ink3, anchor:'middle'});
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
  let body = ''; const geos = [];
  fig.build(t).forEach(p => { const r = (p.draw || evPlot)(t, p.fr, p.o); body += r.g; if (r.geo) geos.push(r.geo); });
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${fig.W} ${fig.H}" width="${fig.W}" height="${fig.H}" font-family="${EVFONT}">`
    + `<rect width="${fig.W}" height="${fig.H}" fill="${t.surface}"/>${body}</svg>`;
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
  const {svg} = evFigure(EVT.light, fig), name = typeof fig.file === 'function' ? fig.file() : fig.file;
  if (kind === 'svg') return evDownload(new Blob(['<?xml version="1.0" encoding="UTF-8"?>\n' + svg], {type:'image/svg+xml'}), name + '.svg');
  const url = URL.createObjectURL(new Blob([svg], {type:'image/svg+xml'})), img = new Image();
  img.onload = () => { const s = 3, c = document.createElement('canvas'); c.width = fig.W * s; c.height = fig.H * s;
    const x = c.getContext('2d'); x.fillStyle = '#ffffff'; x.fillRect(0, 0, c.width, c.height); x.scale(s, s); x.drawImage(img, 0, 0, fig.W, fig.H);
    URL.revokeObjectURL(url); c.toBlob(b => evDownload(b, name + '.png'), 'image/png'); };
  img.src = url;
}
function evRender(host, fig){
  const {svg, geos} = evFigure(EVT.dark, fig);
  host.innerHTML = svg; evHover(host, fig, geos);
}

// ---- the charts -------------------------------------------------------------------
const EVMODELS = [['ma3', 'MA3', 'ma3', null, 2.4], ['tsb', 'TSB', 'tsb', null, 2], ['ens_xgb_ma3@A', 'XGBoost+MA3 avg', 'xgb', null, 2],
                ['sba', 'SBA (α 0.1)', 'base', '6 4', 1.6], ['naive', 'Naive', 'base', '2 3', 1.6]];
const SERVED = {ma3:'ma3', tsb:'tsb', xgb_ma3_avg:'xgb'};
const EVFIGS = {};

EVFIGS[1] = c => {
  const L = evRecs(c.data.lines), V = evRecs(c.data.verdicts), S = evRecs(c.data.sku_series);
  const blocks = [...new Set(L.filter(r => r.window !== 'full').map(r => r.window))];
  const nBy = Object.fromEntries(blocks.map(b => [b, (L.find(r => r.window === b) || {}).n]));
  const rows = [['ALL', 'tsb', 'TSB vs MA3'], ['ALL', 'ens_xgb_ma3@A', 'XGBoost+MA3 avg vs MA3'], ['ALL', 'sba', 'SBA vs MA3'],
                ['ALL', 'naive', 'Naive vs MA3'], ['medium (served: TSB)', 'tsb', 'TSB, medium bin (served)'],
                ['long (served: XGBoost+MA3 avg)', 'ens_xgb_ma3@A', 'XGB+MA3, long bin (served)']];
  const strip = {title: 'two-condition test, per block', rows: rows.map(([co, m, lab]) => ({label: lab, cells: Object.fromEntries(blocks.map(b => {
    const r = V.find(v => v.cohort === co && v.model === m && v.window === b); const v = r ? r.verdict : 'NT';
    return [b, {v, text: v === 'NT' ? 'n/t' : v}]; }))}))};
  const vtip = b => `<div class="h">${esc(blab(b))} · n = ${nBy[b]} SKUs</div>` + EVMODELS.map(([k, lab, col]) => {
    const r = L.find(q => q.window === b && q.model === k); return r ? `<div class="r"><span><i style="background:${EVT.dark[col]}"></i>${esc(lab)}</span><b>${r.median_wape.toFixed(3)}</b></div>` : ''; }).join('')
    + rows.map(([co, m, lab]) => { const r = V.find(v => v.cohort === co && v.model === m && v.window === b);
      return r && r.verdict !== 'NT' ? `<div class="r"><span>${esc(lab)}</span><b>${r.verdict} [${(+r.ci_lo).toFixed(3)}, ${(+r.ci_hi).toFixed(3)}] ${r.n_better}/${r.n_worse}</b></div>` : ''; }).join('');
  const skus = [...new Map(S.map(r => [r.pk, r])).values()].sort((a, b) => String(a.sku_code).localeCompare(String(b.sku_code)));
  if (EVSTATE[1] == null) EVSTATE[1] = skus[0].pk;
  return [
    {file: 'ch01_model_comparison', title: 'Median WAPE per half-year block (one SKU set per block) · verdict vs MA3 below', W: 900, H: 440,
     build: t => [{fr: {x: 0, y: 0, w: 900, h: 440}, o: {ml: 186, xs: blocks, xlab: blab, xsub: b => `n=${nBy[b]}`, strip, tip: vtip,
       y: {fmt: v => v.toFixed(2), title: 'median WAPE'},
       series: EVMODELS.map(([k, lab, col, dash, w]) => ({key: k, label: lab, color: t[col], dash, width: w,
         pts: blocks.map(b => [b, (L.find(r => r.window === b && r.model === k) || {}).median_wape ?? null])}))}}]},
    {file: () => `ch01_sku_${(S.find(r => r.pk === EVSTATE[1]) || {}).sku_code}`, title: 'One SKU: actual vs stored rolling one-step forecasts', W: 900, H: 330,
     control: {options: skus.map(s => [s.pk, `${s.sku_code} · ${s.product_name}`]), get: () => EVSTATE[1], set: v => { EVSTATE[1] = +v; }},
     build: t => { const R = S.filter(r => r.pk === EVSTATE[1]), ms = R.map(r => r.month);
       return [{fr: {x: 0, y: 0, w: 900, h: 330}, o: {xs: ms, xticks: ms.filter((m, i) => i % 3 === 0), xlab: mlab, y: {fmt: v => nf(v), title: 'units', zero: true},
         title: `${R[0].sku_code} · ${R[0].product_name}`,
         series: [{key: 'actual', label: 'Actual', color: t.actual, width: 2.4, pts: R.map(r => [r.month, r.actual])}]
           .concat(EVMODELS.map(([k, lab, col, dash]) => ({key: k, label: lab, color: t[col], dash, width: 1.6, markers: false, pts: R.map(r => [r.month, r[k]])}))),
         tip: m => { const r = R.find(q => q.month === m); return `<div class="h">${mlab(m)} · bin ${esc(r.bin)}</div><div class="r"><span>Actual</span><b>${nf(r.actual)}</b></div>`
           + EVMODELS.map(([k, lab, col]) => `<div class="r"><span><i style="background:${EVT.dark[col]}"></i>${esc(lab)}</span><b>${nf(r[k])}</b></div>`).join(''); }}}]; }},
  ];
};

EVFIGS[2] = c => {
  const L = evRecs(c.data.lines);
  const xs = [...new Set(L.map(r => String(r.k)))].filter(k => k !== 'all').sort((a, b) => a - b).concat(['', 'all']);
  const row = (f, k) => L.find(r => r.family === f && String(r.k) === k) || {};
  const F = [['ma3', 'MA3 (k-invariant)', 'ma3'], ['tsb', 'TSB', 'tsb'], ['xgb_ma3', 'XGBoost+MA3 avg', 'xgb']];
  const xl = k => k === 'all' ? 'full' : k;   // '' is the visual gap before the full-history point
  const strip = {title: 'blocks vs MA3 (2 testable)', rows: [['tsb', 'TSB vs MA3'], ['xgb_ma3', 'XGB+MA3 vs MA3']].map(([f, lab]) => ({label: lab,
    cells: Object.fromEntries(xs.filter(k => k !== '').map(k => { const b = String(row(f, k).blocks || '').replace(/-/g, ''); return [k, {v: majority(b), text: b || 'n/t'}]; }))}))};
  const vr = [{x: '3', label: 'MA3 from 3', dy: 10}, {x: '12', label: 'TSB from 12', dy: 10}, {x: '24', label: 'XGB+MA3 from 24', dy: 22}];
  const tip = k => k === '' ? '' : `<div class="h">k = ${xl(k)} months of history</div>` + F.map(([f, lab, col]) => { const r = row(f, k);
    return `<div class="r"><span><i style="background:${EVT.dark[col]}"></i>${esc(lab)}</span><b>${(+r.median_wape).toFixed(3)} · MASE<1 ${(+r.mase_pass_pct).toFixed(0)}%${r.blocks ? ' · ' + esc(r.blocks) : ''}</b></div>`; }).join('');
  const mk = (t, col, title, yfmt, strip_) => ({fr: {x: 0, y: 0, w: 900, h: strip_ ? 420 : 300}, o: {ml: 150, xs, xlab: xl, strip: strip_, vrules: vr, tip,
    xtitle: 'k = months of history kept (forecast months with >= 24 months of history)', y: {fmt: yfmt, title},
    series: F.map(([f, lab, cc]) => ({key: f, label: lab, color: t[cc], width: f === 'ma3' ? 2.4 : 2, pts: xs.map(k => [k, k === '' ? null : row(f, k)[col] ?? null])}))}});
  return [
    {file: 'ch02_truncation_wape', title: 'Median WAPE vs history kept · block verdicts vs MA3 below', W: 900, H: 420,
     build: t => [mk(t, 'median_wape', 'median WAPE', v => v.toFixed(3), strip)]},
    {file: 'ch02_truncation_mase', title: 'Share of SKUs with MASE < 1 (pipeline gate 1.0) vs history kept', W: 900, H: 300,
     build: t => [mk(t, 'mase_pass_pct', '% SKUs MASE < 1', v => v.toFixed(0) + '%', null)]},
  ];
};

EVFIGS[3] = c => {
  const L = evRecs(c.data.lines), V = evRecs(c.data.verdicts);
  const blocks = [...new Set(L.filter(r => r.window !== 'full').map(r => r.window))];
  const W_ = [['ma2', 'MA2', 0, null], ['ma3', 'MA3', null, null], ['ma6', 'MA6', 1, '6 3'], ['ma12', 'MA12', 2, '2 3']];
  const full = m => (V.find(v => v.model === m && v.window === 'full') || {}).verdict;
  const strip = {title: 'vs MA3, per block', rows: W_.filter(w => w[0] !== 'ma3').map(([m, lab]) => ({label: `${lab} vs MA3 (full window: ${full(m)})`,
    cells: Object.fromEntries(blocks.map(b => { const r = V.find(v => v.model === m && v.window === b); return [b, {v: r ? r.verdict : 'NT', text: r ? r.verdict : 'n/t'}]; }))}))};
  return [{file: 'ch03_ma_window', title: 'Median WAPE per half-year block by moving-average window', W: 900, H: 400,
    build: t => [{fr: {x: 0, y: 0, w: 900, h: 400}, o: {ml: 196, xs: blocks, xlab: blab, strip, y: {fmt: v => v.toFixed(2), title: 'median WAPE'},
      series: W_.map(([m, lab, ri, dash]) => ({key: m, label: lab, color: ri == null ? t.ma3 : t.ramp[ri], dash, width: ri == null ? 2.6 : 1.8,
        pts: blocks.map(b => [b, (L.find(r => r.window === b && r.model === m) || {}).median_wape ?? null])}))}}]}];
};

EVFIGS[4] = c => {
  const L = evRecs(c.data.lines), V = evRecs(c.data.verdicts);
  const ws = [...new Set(L.map(r => r.weight))].sort((a, b) => a - b);
  const wins = [...new Set(L.filter(r => r.n > 0).map(r => r.window))];
  const lab = w => w === 'full' ? 'full window' : blab(w);
  const cells = ag => Object.fromEntries(ws.map(w => { const vv = V.filter(v => v.weight === w && v.against === ag && v.window !== 'full' && v.verdict !== 'NT').map(v => v.verdict).join('');
    return [String(w), ag === 'w=0.5' && w === 0.5 || ag === 'MA3' && w === 0 ? {v: 'NT', text: 'ref'} : {v: majority(vv), text: vv || 'n/t'}]; }));
  const strip = {title: 'testable blocks', rows: [{label: 'vs w = 0.5 (served)', cells: cells('w=0.5')}, {label: 'vs MA3 (w = 0)', cells: cells('MA3')}]};
  return [{file: 'ch04_blend_weight', title: 'Long bin: median WAPE by weight on XGBoost in the average (w = 0 is MA3)', W: 900, H: 400,
    build: t => [{fr: {x: 0, y: 0, w: 900, h: 400}, o: {ml: 150, xs: ws, xlab: w => w.toFixed(1), strip, xtitle: 'w = weight on XGBoost',
      vrules: [{x: 0.5, label: 'served (0.5)'}], y: {fmt: v => v.toFixed(3), title: 'median WAPE'},
      series: wins.map((w, i) => ({key: w, label: lab(w), color: w === 'full' ? t.ramp[2] : t.ramp[i === 1 ? 1 : 0],
        dash: w === 'full' ? null : (i === 1 ? '6 3' : '2 3'), width: w === 'full' ? 2.6 : 1.8,
        pts: ws.map(x => [x, (L.find(r => r.window === w && r.weight === x) || {}).median_wape ?? null])}))}}]}];
};

EVFIGS[5] = c => {
  const R = evRecs(c.data.rates);
  return [{file: 'ch05_transforms', title: 'Block-win rate against MA3 and served, with 95% Clopper-Pearson interval, vs chance', W: 900, H: 330,
    build: t => [{fr: {x: 0, y: 0, w: 900, h: 330}, draw: evBars, o: {cats: R.map(r => r.candidate_set), vals: R.map(r => r.block_win_rate),
      lo: R.map(r => r.cp_lo), hi: R.map(r => r.cp_hi), colors: R.map(r => r.candidate_set === 'all 162' ? t.ramp[2] : t.blue),
      labels: R.map(r => `${r.block_wins} / ${nf(r.testable_blocks)}`), sub: R.map(r => `${r.real} real · ${r.exploratory} exploratory`),
      fmt: v => (v * 100).toFixed(1) + '%', ytitle: 'block wins / testable blocks',
      hrules: [{y: R[0].chance_per_block, label: `chance ${(R[0].chance_per_block * 100).toFixed(1)}%`}],
      tip: k => { const r = R.find(q => q.candidate_set === k); return `<div class="h">${esc(k)} · ${r.candidates} candidates</div>`
        + `<div class="r"><span>block wins</span><b>${r.block_wins} / ${nf(r.testable_blocks)} = ${pc(r.block_win_rate, 2)}</b></div>`
        + `<div class="r"><span>95% CI</span><b>${pc(r.cp_lo, 2)} – ${pc(r.cp_hi, 2)}</b></div>`
        + `<div class="r"><span>testable cells</span><b>${r.testable_cells}</b></div><div class="r"><span>exploratory / real</span><b>${r.exploratory} / ${r.real}</b></div>`; }}}]}];
};

EVFIGS[6] = c => {
  const S = evRecs(c.data.skus), M = evRecs(c.data.months);
  if (EVSTATE[6] == null) EVSTATE[6] = S[0].pk;
  const causes = [...new Set(S.map(s => s.cause_group))], cnt = causes.map(k => S.filter(s => s.cause_group === k).length);
  return [
    {file: () => `ch06_unfit_${(S.find(s => s.pk === EVSTATE[6]) || {}).sku_code}`, title: 'Unfit SKU: real series, served holdout forecast with its band, measured cause', W: 900, H: 340,
     control: {options: S.map(s => [s.pk, `${s.router_bin} · ${s.sku_code} · ${s.product_name} · ${s.cause_group} · MASE ${(+s.mase_used).toFixed(2)}`]),
               get: () => EVSTATE[6], set: v => { EVSTATE[6] = +v; }},
     build: t => {
       const s = S.find(q => q.pk === EVSTATE[6]), R = M.filter(r => r.pk === s.pk), ms = R.map(r => r.month), col = t[SERVED[s.served_model]] || t.blue;
       const rects = []; const firstLast = f => { const k = R.filter(f); return k.length ? [k[0].month, k[k.length - 1].month] : null; };
       const pr = firstLast(r => r.level_prior), rc = firstLast(r => r.level_recent);
       if (pr) rects.push({x0: pr[0], x1: pr[1], op: 0.05, label: 'prior 12'}); if (rc) rects.push({x0: rc[0], x1: rc[1], op: 0.11, label: 'last 6'});
       return [{fr: {x: 0, y: 0, w: 900, h: 340}, o: {xs: ms, xticks: ms.filter((m, i) => i % 3 === 0), xlab: mlab, rects,
         title: `${s.sku_code} · ${s.product_name} · ${s.router_bin} bin · ${s.cause_group} · MASE ${(+s.mase_used).toFixed(3)} (${s.verdict_source})`,
         y: {fmt: v => nf(v), title: 'units', zero: true},
         series: [{key: 'actual', label: 'Actual', color: t.actual, width: 2.2, r: 2.5, pts: R.map(r => [r.month, r.actual])},
                  {key: 'fc', label: `Forecast (${s.served_model})`, color: col, width: 2, band: R.map(r => [r.month, r.band_lo, r.band_hi]),
                   pts: R.map(r => [r.month, r.holdout ? r.forecast : null])},
                  {key: 'spike', label: 'Spike (> 3 × MAD)', color: t.ink, line: false, hollow: true, r: 6, pts: R.map(r => [r.month, r.spike ? r.actual : null])}],
         tip: m => { const r = R.find(q => q.month === m); return `<div class="h">${mlab(m)}${r.spike ? ' · spike' : ''}${r.level_prior ? ' · prior-12 window' : ''}${r.level_recent ? ' · last-6 window' : ''}</div>`
           + `<div class="r"><span>Actual</span><b>${nf(r.actual)}</b></div>` + (r.holdout ? `<div class="r"><span>Forecast</span><b>${nf(r.forecast)}</b></div>`
           + `<div class="r"><span>Band</span><b>${nf(r.band_lo)} – ${nf(r.band_hi)}</b></div><div class="r"><span>Outside band</span><b>${r.outside_band ? 'yes' : 'no'}</b></div>` : ''); }}}]; }},
    {file: 'ch06_unfit_causes', title: 'Unfit SKUs by measured cause (first matching rule)', W: 900, H: 280,
     build: t => [{fr: {x: 0, y: 0, w: 900, h: 280}, draw: evBars, o: {cats: causes, vals: cnt, labels: cnt.map(String), fmt: v => v.toFixed(0), ytitle: 'SKUs',
       sub: causes.map(k => { const b = {}; S.filter(s => s.cause_group === k).forEach(s => { b[s.router_bin] = (b[s.router_bin] || 0) + 1; });
         return Object.entries(b).map(([x, n]) => `${x} ${n}`).join(' · '); }),
       tip: k => `<div class="h">${esc(k)}</div>` + S.filter(s => s.cause_group === k).map(s => `<div class="r"><span>${esc(s.sku_code)}</span><b>${(+s.mase_used).toFixed(2)}</b></div>`).join('')}}]},
  ];
};

EVFIGS[7] = c => {
  const C7 = evRecs(c.data.curve);
  const S = [['unilever', 'single', 'UL single', 'blue', null], ['unilever', 't3m', 'UL t3m', 'blue', '6 4'], ['delmonte', 'single', 'DM single', 'mag', null]]
    .map(([p, m, lab, col, dash]) => ({p, m, lab, col, dash, R: C7.filter(r => r.principal === p && r.method === m)})).filter(s => s.R.length);
  const per = s => `${s.R[0].period}, ${s.R.length} ${s.p === 'delmonte' ? 'categories' : 'SKUs'}`;
  return [{file: 'ch07_pareto', title: 'Cumulative revenue share against rank, latest period (stored ABC_Classification): '
      + S.map(s => `${s.lab} ${per(s)}`).join(' · '), W: 900, H: 380,
    build: t => [{fr: {x: 0, y: 0, w: 900, h: 380}, o: {xnum: true, xdom: [0, 1], xs: [0, 0.2, 0.4, 0.6, 0.8, 1], xlab: v => (v * 100).toFixed(0) + '%',
      xtitle: 'rank / items classified', y: {dom: [0, 1.02], fmt: v => (v * 100).toFixed(0) + '%', title: 'cumulative revenue share'},
      hrules: [{y: 0.8, label: 'A|B cut 0.80', inside: true}, {y: 0.95, label: 'B|C cut 0.95', inside: true}],
      series: S.map(s => ({key: s.p + s.m, label: s.lab, color: t[s.col], dash: s.dash, width: 2,
        markers: s.R.length < 20, r: 4.5, pts: s.R.map(r => [r.rank_share, r.cumulative_share]), R: s.R})),
      tip: x => `<div class="h">rank share ${(x * 100).toFixed(1)}%</div>` + S.map(s => { const r = s.R.reduce((b, q) => Math.abs(q.rank_share - x) < Math.abs(b.rank_share - x) ? q : b);
        return `<div class="r"><span><i style="background:${EVT.dark[s.col]}"></i>${esc(s.lab)}</span><b>#${r.rank} ${esc(r.label)} · ${r.tier} · ${(r.cumulative_share * 100).toFixed(2)}%</b></div>`; }).join('')}}]}];
};

EVFIGS[8] = c => {
  const A = evRecs(c.data.totals), cats = A.map(r => r.allocation_pct + '%');
  const tip = k => { const r = A.find(q => q.allocation_pct + '%' === k); return `<div class="h">allocation ${esc(k)} of last year's sales</div>`
    + `<div class="r"><span>order / need</span><b>${nf(r.ordered)} / ${nf(r.need)}</b></div><div class="r"><span>shortfall</span><b>${nf(r.shortfall)} on ${r.n_short} SKUs</b></div>`
    + `<div class="r"><span>month-end cover</span><b>${(+r.month_end_cover_weeks).toFixed(9)} wk</b></div><div class="r"><span>vs 3-week requirement</span><b>PHP ${(+r.cover_gap_php).toFixed(4)}</b></div>`
    + `<div class="r"><span>run_lp log says</span><b>${r.run_lp_says_met ? 'met (within PHP 1)' : 'short'}</b></div>`; };
  return [{file: 'ch08_allocation', title: 'Supplier allocation: shortfall and month-end cover (placeholder inputs)', W: 900, H: 320,
    build: t => [
      {fr: {x: 0, y: 0, w: 450, h: 320}, draw: evBars, o: {title: 'Shortfall (pieces)', cats, vals: A.map(r => r.shortfall), labels: A.map(r => `${nf(r.shortfall)} · ${r.n_short} SKUs`),
        sub: A.map(r => r.allocation_pct === 105 ? 'default' : ''), fmt: v => nf(v), mr: 30, tip}},
      {fr: {x: 450, y: 0, w: 450, h: 320}, draw: evBars, o: {title: 'Month-end cover (weeks)', cats, vals: A.map(r => r.month_end_cover_weeks),
        labels: A.map(r => `${(+r.month_end_cover_weeks).toFixed(6)}`), sub: A.map(r => `PHP ${r.cover_gap_php >= 0 ? '+' : '−'}${nf(Math.abs(r.cover_gap_php), 2)} vs req.`),
        fmt: v => v.toFixed(1), hrules: [{y: 3, label: 'target 3 wk'}], mr: 80, tip}}]}];
};

EVFIGS[9] = c => {
  const G = evRecs(c.data.grid), d0 = G.find(g => g.is_default);
  const draw = (t, fr) => {
    const M = {l: 60, r: 230, t: 16, b: 40}, side = Math.min(fr.w - M.l - M.r, fr.h - M.t - M.b), X0 = fr.x + M.l, Y0 = fr.y + M.t, n = 21, cs = side / n;
    const cx = w1 => X0 + Math.round(w1 / 0.05) * cs, cy = w2 => Y0 + side - (Math.round(w2 / 0.05) + 1) * cs;
    let g = '';
    G.forEach(r => { const x = cx(r.w1), y = cy(r.w2);
      g += `<rect x="${(x + 1).toFixed(1)}" y="${(y + 1).toFixed(1)}" width="${(cs - 2).toFixed(1)}" height="${(cs - 2).toFixed(1)}" rx="2" fill="${r.cut_set_differs ? t.red : t.blue}"`
        + (r.neighbour ? ` stroke="${t.ink}" stroke-width="1.4"` : '') + `/>`; });
    g += `<circle cx="${(cx(d0.w1) + cs / 2).toFixed(1)}" cy="${(cy(d0.w2) + cs / 2).toFixed(1)}" r="${(cs * 0.62).toFixed(1)}" fill="none" stroke="${t.ink}" stroke-width="2"/>`;
    [0, 0.2, 0.4, 0.6, 0.8, 1].forEach(v => { g += txt(t, cx(v) + cs / 2, Y0 + side + 14, v.toFixed(1), {size:10, fill:t.ink3, anchor:'middle'})
      + txt(t, X0 - 6, cy(v) + cs / 2, v.toFixed(1), {size:10, fill:t.ink3, anchor:'end', base:'middle'}); });
    g += txt(t, X0 + side / 2, Y0 + side + 30, 'w1 = weight on cost (w3 storage = 1 − w1 − w2)', {size:10.5, fill:t.ink2, anchor:'middle'});
    g += `<text transform="translate(${fr.x + 14},${(Y0 + side / 2).toFixed(1)}) rotate(-90)" text-anchor="middle" font-size="10.5" fill="${t.ink2}" font-family="${EVFONT}">w2 = weight on service</text>`;
    const lx = X0 + side + 24; let ly = Y0 + 10;
    [[t.blue, 'same cut SKUs as current weights'], [t.red, 'different cut SKUs']].forEach(([cl, s]) => { g += `<rect x="${lx}" y="${ly - 6}" width="12" height="12" rx="2" fill="${cl}"/>` + txt(t, lx + 18, ly, s, {size:10.5, base:'middle'}); ly += 20; });
    g += `<rect x="${lx}" y="${ly - 6}" width="12" height="12" rx="2" fill="none" stroke="${t.ink}" stroke-width="1.4"/>` + txt(t, lx + 18, ly, 'within ±0.10 of current', {size:10.5, base:'middle'}); ly += 20;
    g += `<circle cx="${lx + 6}" cy="${ly}" r="7" fill="none" stroke="${t.ink}" stroke-width="2"/>` + txt(t, lx + 18, ly, `current (${d0.w1}, ${d0.w2}, ${d0.w3})`, {size:10.5, base:'middle'});
    const geo = {X0, Y0, pw: side, ph: side, pick: (mx, my) => { const i = Math.floor((mx - X0) / cs), j = n - 1 - Math.floor((my - Y0) / cs);
        return G.find(r => Math.round(r.w1 / 0.05) === i && Math.round(r.w2 / 0.05) === j) || null; },
      tip: r => `<div class="h">w1 ${r.w1} · w2 ${r.w2} · w3 ${r.w3}${r.is_default ? ' (current)' : ''}</div>`
        + `<div class="r"><span>SKUs cut</span><b>${r.n_short}</b></div><div class="r"><span>shortfall</span><b>${nf(r.shortfall)}</b></div>`
        + `<div class="r"><span>order cost</span><b>PHP ${nf(r.order_cost)}</b></div><div class="r"><span>cut set vs current</span><b>${r.cut_set_differs ? 'different' : 'same'}</b></div>`};
    return {g, geo};
  };
  return [{file: 'ch09_lp_weights', title: 'LP weights grid (step 0.05), allocation 103%: does the set of cut SKUs change?', W: 900, H: 470,
    build: () => [{fr: {x: 0, y: 0, w: 900, h: 470}, draw}]}];
};

EVFIGS[10] = c => {
  const T = evRecs(c.data.curve), xs = T.map(r => Math.round(r.service_level * 100)), at = x => T[xs.indexOf(x)];
  const cur = [{x: 90, label: 'current Z 1.28'}];
  const p = (t, x, title, key, fmt, extra) => ({fr: {x, y: 0, w: 300, h: 300}, o: {ml: 58, mr: 16, mt: 24, xs, xticks: [85, 90, 95, 99], xlab: v => v + '%', title,
    vrules: cur, y: {fmt, zero: true}, ...extra, series: extra && extra.series ? extra.series : [{key, label: title, color: t.blue, labelEnd: false, r: 2.5, pts: xs.map(v => [v, at(v)[key]])}],
    tip: v => { const r = at(v); return `<div class="h">service level ${v}% · Z ${(+r.z).toFixed(3)}</div>`
      + `<div class="r"><span>safety stock</span><b>${nf(r.total_safety_stock_pieces)} pcs · PHP ${nf(r.total_safety_stock_php)}</b></div>`
      + `<div class="r"><span>model-implied stockout SKU-months / yr</span><b>${nf(r.model_stockout_sku_months_per_year, 1)}</b></div>`
      + `<div class="r"><span>measured exceedance</span><b>${pc(r.measured_exceedance)} (${pc(r.measured_ci_lo)}–${pc(r.measured_ci_hi)})</b></div>`
      + `<div class="r"><span>nominal</span><b>${pc(r.nominal_exceedance)}</b></div>`; }}});
  return [{file: 'ch10_service_level', title: 'Service level: stock held, model-implied stockouts, measured exceedance', W: 900, H: 300,
    build: t => [
      p(t, 0, 'Safety stock held (pieces)', 'total_safety_stock_pieces', v => nf(v / 1000) + 'k'),
      p(t, 300, 'Model-implied stockout SKU-months / yr', 'model_stockout_sku_months_per_year', v => nf(v)),
      p(t, 600, 'Months demand > forecast + Zσ', null, v => (v * 100).toFixed(0) + '%', {mr: 70, series: [
        {key: 'meas', label: 'measured', color: t.blue, r: 2.5, band: xs.map(v => [v, at(v).measured_ci_lo, at(v).measured_ci_hi]), pts: xs.map(v => [v, at(v).measured_exceedance])},
        {key: 'nom', label: 'nominal', color: t.base, dash: '4 3', markers: false, pts: xs.map(v => [v, at(v).nominal_exceedance])}]})]}];
};

EVFIGS[11] = c => {
  const I = evRecs(c.data.index), moys = [...Array(12).keys()].map(i => i + 1);
  const panel = (t, x, w, p, ser, title, years) => ({fr: {x, y: 0, w, h: 320}, o: {ml: 48, mr: 96, mt: 24, xs: moys, xlab: m => MON[m - 1].slice(0, 1), title,
    hrules: [{y: 1, label: ''}], y: {fmt: v => v.toFixed(1)},
    series: years.map((yy, i) => { const R = I.filter(r => r.principal === p && r.series === ser && r.year === yy); if (!R.length) return null;
      const part = R[0].months_in_year < 12 ? ` (${R[0].months_in_year}/12 mo)` : '';
      return {key: String(yy), label: `${yy}${part}`, color: t.ramp[i], dash: part ? '4 3' : null, width: 2, r: 3,
        pts: moys.map(m => [m, (R.find(r => r.moy === m) || {}).index ?? null])}; }).filter(Boolean),
    tip: m => `<div class="h">${MON[m - 1]} · ${esc(title)}</div>` + years.map((yy, i) => { const r = I.find(q => q.principal === p && q.series === ser && q.year === yy && q.moy === m);
      return r ? `<div class="r"><span><i style="background:${EVT.dark.ramp[i]}"></i>${yy}</span><b>${(+r.index).toFixed(2)} · PHP ${nf(r.net_amount / 1e6, 2)}M · ${nf(r.rows)} rows</b></div>` : ''; }).join('')}});
  const br = (t) => ({fr: {x: 600, y: 0, w: 300, h: 320}, o: {ml: 48, mr: 96, mt: 24, xs: moys, xlab: m => MON[m - 1].slice(0, 1), title: 'Del Monte by branch, 2023',
    hrules: [{y: 1, label: ''}], y: {fmt: v => v.toFixed(1)},
    series: [['branch pangasinan (2023 only)', 'Pangasinan', 'blue'], ['branch ilocos (2023 only)', 'Ilocos', 'mag']].map(([s, lab, col]) => {
      const R = I.filter(r => r.series === s); return {key: s, label: lab, color: t[col], width: 2, r: 3, pts: moys.map(m => [m, (R.find(r => r.moy === m) || {}).index ?? null])}; })}});
  return [{file: 'ch11_month_of_year', title: 'Month-of-year index (month / that year\'s mean month), real net pesos', W: 900, H: 320,
    build: t => [panel(t, 0, 300, 'delmonte', 'total', 'Del Monte, all branches', [2023, 2024, 2025]),
                 panel(t, 300, 300, 'unilever', 'total', 'Unilever (La Union)', [2023, 2024, 2025]), br(t)]}];
};

// ---- cards ---------------------------------------------------------------------------
function evChip(v){
  const s = String(v), cls = s === 'CONFIRMS' ? 'good' : s === 'FLAWED' ? 'bad' : s.startsWith('CAVEAT') ? 'warn' : s === 'NOT BUILT' ? 'notbuilt' : 'neutral';
  return `<span class="evchip ${cls}">${{good: '✓', bad: '✗', warn: '!', notbuilt: '–', neutral: 'i'}[cls]} ${esc(s)}</span>`;
}
function evCard(c){
  const figs = c.verdict === 'NOT BUILT' ? [] : (EVFIGS[c.chart] ? EVFIGS[c.chart](c) : []);
  c._figs = figs;
  const checks = (c.checks || []).map(k => `<li><span class="${k.pass ? 'evok' : 'evno'}">${k.pass ? '✓' : '✗'} ${esc(k.id)}</span> ${esc(k.detail)}</li>`).join('');
  const amends = (c.amendments || []).map(a => `<div class="evamend"><b>Amended ${esc(a.date)} (${esc(a.item)}, ${esc(a.approved_by)}):</b> ${esc(a.amended)} <span class="muted">— ${esc(a.reason)}</span></div>`).join('');
  const files = Object.values(c.files || {}).map(f => `<code>${esc(f)}</code>`).join(' ');
  return `<article class="evcard" id="ev-${c.chart}"><div class="evhead"><span class="evnum">${c.chart}</span><h3>${esc(c.title)}</h3>${evChip(c.verdict)}</div>`
    + `<div class="evcrit"><b>Pre-registered — flawed if:</b> ${esc(c.criterion)} <span class="muted">Otherwise: ${esc(c.otherwise)}.</span></div>`
    + (c.verdict_detail ? `<div class="evdetail">${esc(c.verdict_detail)}</div>` : '')
    + (c.verdict === 'NOT BUILT' ? `<p class="evcap">Plan only. Source: <code>etl_coverage</code> (migration 0033), not yet in public. Built later: real / synthetic (labelled) / missing by principal × table × month.</p>` : '')
    + `<div class="evfigs">${figs.map((f, i) => `<figure class="evfig"><div class="evfhead"><span class="evftitle">${esc(f.title)}</span>`
      + (f.control ? `<select class="evsel" data-c="${c.chart}" data-f="${i}">${f.control.options.map(([v, l]) => `<option value="${v}"${v === f.control.get() ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>` : '')
      + `<span class="evbtns"><button class="evbtn" data-c="${c.chart}" data-f="${i}" data-k="svg">SVG</button><button class="evbtn" data-c="${c.chart}" data-f="${i}" data-k="png">PNG</button></span></div>`
      + `<div class="evsvg" id="evs-${c.chart}-${i}"></div></figure>`).join('')}</div>`
    + (c.caption ? `<p class="evcap">${esc(c.caption)} <button class="evbtn evcopy" data-c="${c.chart}">Copy caption</button></p>` : '')
    + amends
    + (checks ? `<ul class="evlist checks">${checks}</ul>` : '')
    + ((c.data_notes || []).length ? `<ul class="evlist">${c.data_notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>` : '')
    + `<div class="evprov"><span>MASE gate used: <b>${esc(c.mase_gate_used)}</b></span><span>Re-run after 5f: <b>${esc(c.rerun_after_5f)}</b></span>`
    + (c.script ? `<span>Script <code>${esc(c.script)}</code> @ <code>${esc(c.code_commit)}</code>, ${esc(c.computed_at)}</span>` : '')
    + (files ? `<span>Data ${files}</span>` : '') + `</div></article>`;
}
function drawEvidence(){
  if (evOnce.drawn) return;
  evOnce.drawn = true;
  const C = EV.charts;
  const intro = `<div class="card evintro"><h2>Evidence — one chart per modelling decision</h2>`
    + `<p>Every number on this tab is read from <code>reports/evidence/</code>, written by the scripts under <code>scripts/evidence/</code>; each caption is generated from the data. `
    + `The flawed-if criteria were committed before any computation (<code>${esc(EV.prereg)}</code>); every later change to a check is listed as an amendment on its chart. `
    + `Verdicts are shown exactly as computed, flawed ones included. Ties are drawn as ties (grey T cells). Real data only; SVG/PNG exports use a light print palette.</p>`
    + (EV.uncommitted.length ? `<p class="evno">Computed from uncommitted code: charts ${EV.uncommitted.join(', ')}.</p>` : '')
    + `<table class="evsum"><thead><tr><th>#</th><th>Chart</th><th>Verdict</th><th>Checks</th><th>MASE gate</th><th>Re-run after 5f</th></tr></thead><tbody>`
    + C.map(c => `<tr><td class="num">${c.chart}</td><td><a href="#ev-${c.chart}">${esc(c.title)}</a></td><td>${evChip(c.verdict)}</td>`
      + `<td>${(c.checks || []).map(k => `<span class="${k.pass ? 'evok' : 'evno'}">${k.pass ? '✓' : '✗'} ${esc(k.id)}</span>`).join(' ') || '<span class="muted">—</span>'}</td>`
      + `<td>${esc(c.mase_gate_used)}</td><td>${esc(c.rerun_after_5f)}</td></tr>`).join('') + `</tbody></table></div>`;
  $('#evidence').innerHTML = intro + `<div class="evgrid">${C.map(evCard).join('')}</div>`;
  C.forEach(c => (c._figs || []).forEach((f, i) => evRender($(`#evs-${c.chart}-${i}`), f)));
  $('#evidence').addEventListener('click', e => {
    const b = e.target.closest('.evbtn'); if (!b) return;
    const c = C.find(x => x.chart === +b.dataset.c);
    if (b.classList.contains('evcopy')){ navigator.clipboard.writeText(c.caption).then(() => { b.textContent = 'Copied'; setTimeout(() => { b.textContent = 'Copy caption'; }, 1200); }); return; }
    evExport(c._figs[+b.dataset.f], b.dataset.k);
  });
  $('#evidence').addEventListener('change', e => {
    const s = e.target.closest('.evsel'); if (!s) return;
    const c = C.find(x => x.chart === +s.dataset.c), f = c._figs[+s.dataset.f];
    f.control.set(s.value); evRender($(`#evs-${c.chart}-${s.dataset.f}`), f);
  });
}
// Dev hook (scripted checks and batch export): the light print SVG of chart `chart`, figure `fig`.
window.evidenceExportSVG = (chart, fig) => { drawEvidence(); const c = EV.charts.find(x => x.chart === chart);
  return c && c._figs[fig] ? evFigure(EVT.light, c._figs[fig]).svg : null; };
return drawEvidence;
})();
