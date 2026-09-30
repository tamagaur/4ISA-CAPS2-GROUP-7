// ================= EVIDENCE tab (tools/dsd_dev_viewer/evidence.js) =================
// Every number drawn here is read from D.evidence, which evidence.py loads from
// reports/evidence/ (written by scripts/evidence/*.py), plus the served model per
// product already in the page (D.skus, read from Forecast_Result by build.py).
// The page computes layout and simple tallies of stored values only (group averages,
// shares, counts); no model is refitted and no verdict is recomputed.
// Written for a board-level reader: every card reads The question -> The answer ->
// ONE comparison chart (ours in blue, alternatives in grey) -> What this means for SSM,
// and everything else sits in a closed "Details (for the paper)" section. Headlines and
// plain claims are chosen by the stored verdict and checked against the stored data;
// where a claim cannot be checked from stored results the card says so.
// Screen charts use the viewer's dark steps; SVG/PNG exports re-render the same figure
// with the light print steps. Palettes checked with the dataviz validator.
// Wrapped: only drawEvidence is global, so no name here can collide with the viewer's own script.
const drawEvidence = (() => {
const EV = D.evidence;
const EVFONT = 'Segoe UI, -apple-system, Helvetica Neue, Arial, sans-serif';
const EVT = {
  dark: {surface:'#161a24', ink:'#eef0f6', ink2:'#b9bfd0', ink3:'#7d8499', grid:'rgba(255,255,255,0.08)', axis:'#3a4150',
         ma3:'#199e70', tsb:'#9085e9', xgb:'#d95926', base:'#8a8f9e', actual:'#c3c2b7',
         blue:'#3987e5', mag:'#d55181', red:'#e66767', ramp:['#86b6ef', '#3987e5', '#1c5cab'],
         ours:'#3987e5', alt:'#6e7688', alt2:'#4a5263', need:'#8a8f9e', neutral:'#383835', pos:'#3987e5', neg:'#e66767',
         W:'#0ca30c', L:'#d03b3b', T:'#4a5263', band:0.18, shade:'#ffffff'},
  light: {surface:'#ffffff', ink:'#0b0b0b', ink2:'#52514e', ink3:'#898781', grid:'#e1e0d9', axis:'#c3c2b7',
          ma3:'#1baf7a', tsb:'#4a3aa7', xgb:'#eb6834', base:'#898781', actual:'#52514e',
          blue:'#2a78d6', mag:'#e87ba4', red:'#e34948', ramp:['#86b6ef', '#2a78d6', '#104281'],
          ours:'#2a78d6', alt:'#8f8e88', alt2:'#c9c8c1', need:'#b8b7b0', neutral:'#f0efec', pos:'#2a78d6', neg:'#e34948',
          W:'#0ca30c', L:'#d03b3b', T:'#d9d8d1', band:0.16, shade:'#000000'},
};
const evRecs = t => t ? t.rows.map(r => Object.fromEntries(t.cols.map((c, i) => [c, r[i]]))) : [];
const nf = (v, d=0) => v == null || Number.isNaN(+v) ? '—' : Number(v).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
const pc = (v, d=1) => v == null ? '—' : (v * 100).toFixed(d) + '%';
const rk = v => nf(Math.round(v / 1000) * 1000);           // "62,000"
const sgn = v => { const r = Math.round(v); return (r > 0 ? '+' : r < 0 ? '−' : '') + Math.abs(r) + '%'; };
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const MONL = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const mlab = m => MON[+String(m).slice(5, 7) - 1] + ' ' + String(m).slice(2, 4);
const blab = w => { const [a, b] = String(w).split('..'); return mlab(a) + '–' + mlab(b); };
const plab = w => w === 'full' ? 'Both periods combined' : ({'2025-03..2025-08': 'Mar–Aug 2025', '2025-09..2026-02': 'Sep 2025–Feb 2026'}[w] || blab(w));
const EVSTATE = {};
const evOnce = {drawn: false};
const hOf = fig => typeof fig.H === 'function' ? fig.H() : fig.H;
const listWords = a => a.length <= 1 ? a.join('') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1];
const PLACEHOLDER = 'uses team estimates until SSM confirms the real figures';

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
function hexMix(a, b, f){
  const p = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * f).toString(16).padStart(2, '0')).join('');
}
function evCell(t, x, y, w, h, v){
  const fill = v === 'W' ? t.W : v === 'L' ? t.L : v === 'NT' ? 'none' : t.T;
  return `<rect x="${x.toFixed(1)}" y="${y}" width="${Math.max(w, 2).toFixed(1)}" height="${h}" rx="2.5" fill="${fill}"`
    + (v === 'NT' ? ` stroke="${t.ink3}" stroke-dasharray="2 2"` : '') + `/>`;
}
const RESULT_WORDS = cmp => [['T', 'Tie (no clear difference)'], ['W', `Better than ${cmp}`], ['L', `Worse than ${cmp}`], ['NT', 'Not enough data']];
const yTitle = (t, fr, Y0, ph, s) => `<text transform="translate(${fr.x + 11},${(Y0 + ph / 2).toFixed(1)}) rotate(-90)" text-anchor="middle" font-size="10.5" fill="${t.ink2}" font-family="${EVFONT}">${esc(s)}</text>`;

// ---- line plot (used in Details) ----------------------------------------------
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
  if (o.y.title) g += yTitle(t, fr, Y0, ph, o.y.title);
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
      segs.forEach(sg => { if (sg.length > 1) g += `<polyline points="${sg.map(p => `${xp(p[0]).toFixed(1)},${yp(p[1]).toFixed(1)}`).join(' ')}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round"${s.dash ? ` stroke-dasharray="${s.dash}"` : ''}${s.op ? ` stroke-opacity="${s.op}"` : ''}/>`; });
    }
    if (s.markers !== false) s.pts.forEach(p => { if (p[1] == null) return;
      g += `<circle cx="${xp(p[0]).toFixed(1)}" cy="${yp(p[1]).toFixed(1)}" r="${s.r || 3.5}" fill="${s.hollow ? 'none' : s.color}" stroke="${s.hollow ? s.color : t.surface}" stroke-width="${s.hollow ? 1.8 : 1.5}"/>`; });
  });
  const labs = o.series.filter(s => s.labelEnd !== false).map(s => { const last = [...s.pts].reverse().find(p => p[1] != null);
    return last ? {s, y: yp(last[1])} : null; }).filter(Boolean).sort((a, b) => a.y - b.y);
  for (let i = 1; i < labs.length; i++) if (labs[i].y - labs[i - 1].y < 13) labs[i].y = labs[i - 1].y + 13;
  labs.forEach(l => { g += `<line x1="${(X0 + pw + 4).toFixed(1)}" x2="${(X0 + pw + 14).toFixed(1)}" y1="${l.y.toFixed(1)}" y2="${l.y.toFixed(1)}" stroke="${l.s.color}" stroke-width="2"${l.s.dash ? ` stroke-dasharray="${l.s.dash}"` : ''}/>`
    + txt(t, X0 + pw + 18, l.y, l.s.label, {size:10.5, fill:t.ink, base:'middle', weight: l.s.bold ? 700 : null}); });
  if (o.strip){
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
  const geo = {X0, Y0, pw, ph, cat, xs: o.xs, step, xp, xdom: o.xdom, series: o.series, fmt: o.y.tfmt || o.y.fmt, xlab: o.xlab, tip: o.tip};
  return {g, geo};
}

// ---- grouped vertical bars: groups x series; per-bar colour; optional labels ------------
function evGBars(t, fr, o){
  const M = {l: o.ml ?? 70, r: o.mr ?? 24, t: (o.title ? 30 : 14) + (o.legend ? 22 : 0), b: 40 + (o.gsub ? 15 * Math.max(1, ...o.gsub.map(q => String(q || '').split('\n').length)) : 0)};
  const pw = fr.w - M.l - M.r, ph = fr.h - M.t - M.b, X0 = fr.x + M.l, Y0 = fr.y + M.t;
  const G = o.groups.length, S = o.series.length, gw = pw / G, bw = Math.min(gw * 0.72 / S, 58), gap = 4;
  const vals = o.series.flatMap(s => s.vals).filter(v => v != null);
  const hi0 = Math.max(...vals, ...(o.whiskers || []).map(w => w.hi), ...(o.hrules || []).map(h => h.y)) * (o.top || 1.15), lo = 0;
  const ticks = niceTicks(lo, hi0, 4), stp = ticks[1] - ticks[0];
  while (ticks[ticks.length - 1] < hi0 - 1e-9) ticks.push(+(ticks[ticks.length - 1] + stp).toFixed(12));
  const hi = ticks[ticks.length - 1], yp = v => Y0 + ph - (v - lo) / (hi - lo) * ph;
  const bx = (gi, si) => X0 + gi * gw + (gw - (S * bw + (S - 1) * gap)) / 2 + si * (bw + gap);
  let g = o.title ? txt(t, X0, fr.y + 10, o.title, {size:11.5, weight:600}) : '';
  if (o.legend){ let lx = X0; const ly = fr.y + (o.title ? 30 : 12);
    o.legend.forEach(([col, lab, dashed]) => { g += `<rect x="${lx}" y="${ly - 6}" width="12" height="12" rx="2" fill="${dashed ? 'none' : col}"${dashed ? ` stroke="${col}" stroke-dasharray="3 2"` : ''}/>` + txt(t, lx + 17, ly, lab, {size:10.5, fill:t.ink2, base:'middle'}); lx += 17 + lab.length * 6 + 22; }); }
  ticks.forEach(v => { g += `<line x1="${X0}" x2="${(X0 + pw).toFixed(1)}" y1="${yp(v).toFixed(1)}" y2="${yp(v).toFixed(1)}" stroke="${t.grid}"/>`
    + txt(t, X0 - 6, yp(v), o.fmt(v), {size:10, fill:t.ink3, anchor:'end', base:'middle'}); });
  o.groups.forEach((gl, gi) => {
    o.series.forEach((s, si) => { const v = s.vals[gi]; if (v == null) return;
      const x = bx(gi, si), y = yp(v), h = Math.max(Y0 + ph - y, 0.5), col = s.colorAt ? s.colorAt(gi) : s.color, r = Math.min(4, h / 2, bw / 2);
      g += `<path d="M${x.toFixed(1)},${(Y0 + ph).toFixed(1)} V${(y + r).toFixed(1)} q0,-${r} ${r},-${r} H${(x + bw - r).toFixed(1)} q${r},0 ${r},${r} V${(Y0 + ph).toFixed(1)} Z" fill="${col}"${s.outline ? ` fill-opacity="0.25" stroke="${col}"` : ''}/>`;
      const lab = s.labels && s.labels[gi]; if (lab) g += txt(t, x + bw / 2, y - 6, lab, {size:10, fill:t.ink, anchor:'middle', weight: s.bold && s.bold(gi) ? 700 : null});
      const sub = s.sub && s.sub[gi]; if (sub) g += txt(t, x + bw / 2, Y0 + ph + 13, sub, {size:9.5, fill: s.subInk ? s.subInk(gi) : t.ink3, anchor:'middle', weight: s.bold && s.bold(gi) ? 700 : null}); });
    g += txt(t, X0 + (gi + 0.5) * gw, Y0 + ph + (o.series.some(s => s.sub) ? 28 : 15), gl, {size:10.5, fill:t.ink2, anchor:'middle', weight: o.boldGroup && o.boldGroup(gi) ? 700 : null});
    if (o.gsub && o.gsub[gi]){ const ink = (o.gsubInkAt && o.gsubInkAt(gi)) || o.gsubInk || t.ours;
      String(o.gsub[gi]).split('\n').forEach((ln, li) => { g += txt(t, X0 + (gi + 0.5) * gw, Y0 + ph + (o.series.some(s => s.sub) ? 43 : 30) + li * 14, ln, {size:10.5, fill: ink, anchor:'middle', weight: ink === t.ours ? 700 : null}); }); }
    if (o.gnote && o.gnote[gi]){ const top = Math.min(...o.series.map(s => s.vals[gi] == null ? Infinity : yp(s.vals[gi])));
      g += txt(t, X0 + (gi + 0.5) * gw, top - 22, o.gnote[gi], {size:10.5, fill:t.ink, anchor:'middle', weight:600}); }
  });
  g += `<line x1="${X0}" x2="${(X0 + pw).toFixed(1)}" y1="${(Y0 + ph).toFixed(1)}" y2="${(Y0 + ph).toFixed(1)}" stroke="${t.axis}"/>`;
  (o.hrules || []).forEach(h => { g += `<line x1="${X0}" x2="${(X0 + pw).toFixed(1)}" y1="${yp(h.y).toFixed(1)}" y2="${yp(h.y).toFixed(1)}" stroke="${t.ink3}" stroke-dasharray="4 3"/>`
    + txt(t, X0 + pw - 2, yp(h.y) - 5, h.label, {size:10, fill:t.ink2, anchor:'end'}); });
  (o.whiskers || []).forEach(w => { const xc = bx(w.gi, w.si) + bw / 2;
    g += `<line x1="${xc.toFixed(1)}" x2="${xc.toFixed(1)}" y1="${yp(w.lo).toFixed(1)}" y2="${yp(w.hi).toFixed(1)}" stroke="${t.ink}" stroke-width="1.5"/>`
      + [w.lo, w.hi].map(q => `<line x1="${(xc - 7).toFixed(1)}" x2="${(xc + 7).toFixed(1)}" y1="${yp(q).toFixed(1)}" y2="${yp(q).toFixed(1)}" stroke="${t.ink}" stroke-width="1.5"/>`).join(''); });
  (o.marks || []).forEach(m => { const x = bx(m.gi, m.si), y = yp(m.y);
    g += `<line x1="${(x - 5).toFixed(1)}" x2="${(x + bw + 5).toFixed(1)}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${t.ink}" stroke-width="2.5" stroke-dasharray="${m.dash || ''}"/>`; });
  if (o.ytitle) g += yTitle(t, fr, Y0, ph, o.ytitle);
  const geo = {X0, Y0, pw, ph, cat: true, xs: o.groups, step: gw, xp: v => X0 + (o.groups.indexOf(v) + 0.5) * gw, tip: o.tip, nocross: true};
  return {g, geo};
}

// ---- horizontal bars (one value per row; rows may be "not available") -----------------
function evHBars(t, fr, o){
  const M = {l: o.ml ?? 250, r: o.mr ?? 40, t: o.title ? 30 : 12, b: 30};
  const pw = fr.w - M.l - M.r, X0 = fr.x + M.l, Y0 = fr.y + M.t, rh = o.rowH || 22, ph = o.rows.length * rh;
  const xmax = o.xmax, xp = v => X0 + v / xmax * pw;
  let g = o.title ? txt(t, X0, fr.y + 10, o.title, {size:11.5, weight:600}) : '';
  niceTicks(0, xmax, 5).filter(v => v <= xmax).forEach(v => { g += `<line x1="${xp(v).toFixed(1)}" x2="${xp(v).toFixed(1)}" y1="${Y0}" y2="${Y0 + ph}" stroke="${t.grid}"/>`
    + txt(t, xp(v), Y0 + ph + 14, o.fmt(v), {size:10, fill:t.ink3, anchor:'middle'}); });
  o.rows.forEach((r, i) => { const y = Y0 + i * rh + 3, h = rh - 7;
    g += txt(t, X0 - 8, y + h / 2, r.label, {size:10.5, fill: r.ours ? t.ink : t.ink2, anchor:'end', base:'middle', weight: r.ours ? 700 : null});
    if (r.val == null){ g += txt(t, X0 + 4, y + h / 2, r.note || 'not available', {size:10, fill:t.ink3, base:'middle'}); return; }
    const w = Math.max(xp(r.val) - X0, r.val === 0 ? 0 : 2);
    g += r.val === 0 ? `<circle cx="${X0 + 5}" cy="${(y + h / 2).toFixed(1)}" r="4.5" fill="${r.color}" stroke="${t.surface}" stroke-width="1.5"/>`
                     : `<rect x="${X0}" y="${y}" width="${w.toFixed(1)}" height="${h}" rx="3" fill="${r.color}"/>`;
    g += r.text ? txt(t, X0 + Math.max(w, r.val === 0 ? 10 : 0) + 6, y + h / 2, r.text, {size:10, fill: r.ours ? t.ink : t.ink2, base:'middle', weight: r.ours ? 700 : null}) : ''; });
  g += `<line x1="${X0}" x2="${X0}" y1="${Y0}" y2="${Y0 + ph}" stroke="${t.axis}"/>`;
  if (o.xtitle) g += txt(t, X0 + pw / 2, Y0 + ph + 28, o.xtitle, {size:10.5, fill:t.ink2, anchor:'middle'});
  const geo = {X0, Y0, pw, ph, pick: (mx, my) => o.rows[Math.floor((my - Y0) / rh)] || null, tip: o.tip};
  return {g, geo};
}

// ---- figure -> one SVG; hover; export -------------------------------------------------
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
    if (!g.cat && !p){ p = s.pts.reduce((b, q) => q[1] != null && (b == null || Math.abs(q[0] - x) < Math.abs(b[0] - x)) ? q : b, null); }
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
    if (g.pick){ x = g.pick(mx, my); if (x == null) return hide(); html = g.tip ? g.tip(x) : ''; }
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
function evRender(host, fig){ const {svg, geos} = evFigure(EVT.dark, fig); host.innerHTML = svg; evHover(host, fig, geos); }

// ---- words ---------------------------------------------------------------------------
const WORDS = {'CONFIRMS': ['Holds', 'good'], 'FLAWED': ['Questioned', 'bad'], 'DESCRIPTIVE': ['Description only', 'neutral'],
               'NOT TESTABLE': ["Can't test yet", 'neutral'], 'NOT BUILT': ['Not built yet', 'notbuilt'], 'CAVEAT NEEDED': ['Needs a caveat', 'warn'],
               'no flag': ['Holds', 'good']};
const CHIP_OVERRIDE = {8: c => { const A = evRecs(c.data.totals), r = A.find(q => q.allocation_pct === 105);
  return c.verdict === 'FLAWED' && A.every(q => q.run_lp_says_met) && r && r.cover_gap_php < 0
    ? [`Technically questioned: ₱${(-r.cover_gap_php).toFixed(2)} rounding`, 'warn'] : null; }};
function evChip(c){
  const ov = CHIP_OVERRIDE[c.chart] && c.data && CHIP_OVERRIDE[c.chart](c);
  if (ov) return `<span class="evchip ${ov[1]}" title="stored verdict: ${esc(c.verdict)}">! ${esc(ov[0])}</span>`;
  const s = String(c.verdict), parts = s.includes(' / ') ? s.split(' / ') : [s];
  return parts.map(p => { const m = p.match(/^([^:]+): (.+)$/), who = m && !WORDS[p] ? m[1] : null, code = who ? m[2] : p;
    const [w, cls] = WORDS[code] || [code, 'neutral'];
    return `<span class="evchip ${cls}" title="stored verdict: ${esc(p)}">${{good: '✓', bad: '!', warn: '!', notbuilt: '–', neutral: 'i'}[cls]} ${who ? esc(who) + ': ' : ''}${esc(w)}</span>`; }).join(' ');
}
const GLOSSARY = [
  ['Forecast error', 'How far forecasts were from actual sales, as a share of sales (WAPE, weighted absolute percentage error). Lower is better.'],
  ['Quality check (MASE)', 'MASE = mean absolute scaled error: a product’s forecast error divided by the error of a naive “same as last month” guess. A product passes when it is below 1.'],
  ['MA3', 'Simple 3-month average: next month = the average of the last 3 months. Our benchmark and fallback. MA2 / MA6 / MA12 = the same over 2, 6 or 12 months.'],
  ['TSB', 'Teunter–Syntetos–Babai: a smoothing method built for products that do not sell every month.'],
  ['XGBoost', 'A machine-learning model trained on all top products at once. We blend it 50/50 with MA3.'],
  ['SBA / Naive', 'Two basic benchmarks: SBA (Syntetos–Boylan approximation) is an older method for patchy sales; naive repeats last month.'],
  ['ARIMA / SARIMA / ETS', 'Classic statistical forecasting models (autoregressive, seasonal autoregressive, exponential smoothing).'],
  ['Test period', 'One half-year (e.g. Oct 2023–Feb 2024) in which every model forecast each month one step ahead.'],
  ['Tie / better / worse', 'Better or worse only when the 95% margin of error excludes “no difference” AND more products improve than worsen; otherwise a tie.'],
  ['Tier A (ABC)', 'The products that together bring in the top 80% of revenue (Tier B: the next 15%, Tier C: the last 5%).'],
  ['LP (order plan)', 'Linear programme: the optimisation that decides each month’s order within the supplier allocation.'],
  ['Allocation', 'What the supplier lets us buy: last year’s sales × 103%, 105% or 108%, split by month.'],
  ['Weeks of cover', 'How many weeks of sales the stock left at month end would last. SSM’s rule is 3 weeks.'],
  ['Safety stock / service level', 'Extra stock held against surprises; a 90% service level means running out in at most about 1 month in 10.'],
  ['Pre-registered', 'The pass/fail rule was written and committed before any result was computed.'],
  ['Team estimates', 'Some order-plan inputs (allocation %, lead time, costs, warehouse size) use team estimates until SSM confirms the real figures.'],
];

// ---- cards -------------------------------------------------------------------------------
const CARDS = {};
const BOARD = {};   // decision -> [what we chose, compared against, what it means for SSM]
const oursAlt = (t, isOurs) => isOurs ? t.ours : t.alt;

CARDS[1] = c => {
  const L = evRecs(c.data.lines), V = evRecs(c.data.verdicts), S = evRecs(c.data.sku_series);
  const full = k => L.find(r => r.window === 'full' && r.model === k) || {};
  const vFull = k => V.find(v => v.cohort === 'ALL' && v.window === 'full' && v.model === k) || {};
  const M = [['ma3', '3-month average', true], ['tsb', 'TSB', true], ['ens_xgb_ma3@A', 'XGBoost + average', true], ['sba', 'SBA', false], ['naive', 'Naive', false]];
  const newer = [full('tsb').mase_pass_pct, full('ens_xgb_ma3@A').mase_pass_pct];
  const lo = Math.round(Math.min(...newer)), hi = Math.round(Math.max(...newer)), ma = Math.round(full('ma3').mase_pass_pct);
  const blocks = [...new Set(L.filter(r => r.window !== 'full').map(r => r.window))];
  const pw = (b, k) => (L.find(r => r.window === b && r.model === k) || {}).median_wape;
  const lowerIn = k => blocks.filter(b => pw(b, k) < pw(b, 'ma3')).length;
  const used = ['ma3', 'tsb', 'ens_xgb_ma3@A'].map(k => full(k).median_wape);
  const spread = (Math.max(...used) - Math.min(...used)) * 100, bench = (Math.min(full('sba').median_wape, full('naive').median_wape) - Math.max(...used)) * 100;
  const naiveGap = Math.round((full('naive').median_wape - full('ma3').median_wape) * 100);
  const p1 = x => (x * 100).toFixed(1) + '%', tv = vFull('tsb'), xv = vFull('ens_xgb_ma3@A');
  const tie = tv.verdict === 'T' && xv.verdict === 'T';
  const better = Math.round(-Math.min(tv.ci_lo, xv.ci_lo) * 100), worse = Math.round(Math.max(tv.ci_hi, xv.ci_hi) * 100);
  const tieText = tie ? `“Tie” even though the numbers differ: TSB ${p1(full('tsb').median_wape)} and XGBoost + average ${p1(full('ens_xgb_ma3@A').median_wape)} vs the 3-month average ${p1(full('ma3').median_wape)}. `
    + `The margin of error on each gap runs from about ${better} points better to ${worse} point${worse === 1 ? '' : 's'} worse — too close to call. `
    + (lowerIn('tsb') === lowerIn('ens_xgb_ma3@A') ? `Results this close also flip: each was lower in ${lowerIn('tsb')} of ${blocks.length} test periods and higher in the rest.`
      : `Results this close also flip: TSB was lower in ${lowerIn('tsb')} of ${blocks.length} test periods, XGBoost + average in ${lowerIn('ens_xgb_ma3@A')}.`) : '';
  // served model and stored error per product, from the live Forecast_Result already in this page
  const skd = new Map((D.skus || []).map(s => [s.pk, s]));
  const SERVE = {ma3: ['short history', '3-month average', 'ma3'], tsb: ['medium history', 'TSB', 'tsb'], xgb_ma3_avg: ['long history', 'XGBoost + average', 'ens_xgb_ma3@A'],
                 provisional: ['too little history', 'provisional average', null]};
  const sv = pk => SERVE[(skd.get(pk) || {}).method] || ['history not on record', 'served model not on record', null];
  const skus = [...new Map(S.map(r => [r.pk, r])).values()].sort((a, b) => String(a.sku_code).localeCompare(String(b.sku_code)));
  const shown = pk => S.filter(r => r.pk === pk).length;
  const scored = skus.map(s => skd.get(s.pk)).filter(s => s && s.wape != null);
  const sorted = scored.map(s => s.wape).sort((a, b) => a - b), medW = sorted.length ? (sorted[(sorted.length - 1) >> 1] + sorted[sorted.length >> 1]) / 2 : null;
  // Examples come from the products that pass the quality check (stored MASE < 1) with 2+ years of sales shown.
  // Well-forecast: the middle of the lowest-error quarter. Typical: stored error closest to the typical product's.
  const elig = scored.filter(s => s.mase != null && s.mase < 1 && shown(s.pk) >= 24).sort((a, b) => a.wape - b.wape);
  const q4 = Math.ceil(elig.length / 4), well = elig.length ? elig[(q4 - 1) >> 1] : null;
  const typ = elig.slice().sort((a, b) => Math.abs(a.wape - medW) - Math.abs(b.wape - medW))[0];
  if (EVSTATE[1] == null) EVSTATE[1] = well ? well.pk : skus[0].pk;
  const rowOf = pk => S.find(r => r.pk === pk) || {};
  const kind = pk => well && pk === well.pk ? 'A well-forecast product' : typ && pk === typ.pk ? 'Typical product' : 'Your pick';
  const e0 = Math.round(full('ma3').median_wape * 100);
  BOARD[1] = ['3-month average; TSB and XGBoost for longer histories', 'SBA, naive (and each other)', 'The simple method is as accurate as the complex ones, so forecasts stay easy to explain.'];
  return {
    question: 'Is any complex model clearly better than a simple 3-month average?',
    headline: c.verdict === 'CONFIRMS' ? 'No. The newer models tie with the simple 3-month average; the two basic benchmarks do worse.'
      : 'A model we use does worse than the simple average, or a basic rule beats it.',
    main: {file: 'ch01_models', title: 'Forecast error of each model, all test periods together (lower is better)', W: 900, H: 340,
      read: 'Blue = models we use (each for a different history length); grey = benchmarks we tested and rejected. Bars of about equal height = a tie.',
      shows: [`Each bar = one model’s forecast error over all test periods (Oct 2023 – Feb 2026): how far forecasts were from actual sales. Shorter is better.`,
              `Blue = the three models we use. They are within ${spread.toFixed(1)} points of each other — a tie.`,
              `Grey = two basic benchmarks (naive = repeat last month; SBA = an older method for products with patchy sales). They are about ${Math.round(bench)} points worse, so they are not used.`,
              tieText].filter(Boolean),
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 340}, draw: evGBars, o: {groups: M.map(m => m[1]), ytitle: 'Forecast error (lower is better)', fmt: v => (v * 100).toFixed(0) + '%',
        series: [{vals: M.map(m => full(m[0]).median_wape), colorAt: gi => oursAlt(t, M[gi][2]), sub: M.map(m => m[2] ? 'Ours (used)' : 'not used'),
                  subInk: gi => M[gi][2] ? t.ink : t.ink3, bold: gi => M[gi][2]}],
        gnote: [null, 'tie', null, null, null],
        tip: k => { const m = M.find(q => q[1] === k); const r = full(m[0]); return `<div class="h">${esc(k)}${m[2] ? ' (ours)' : ''}</div><div class="r"><span>forecast error</span><b>${pc(r.median_wape)}</b></div><div class="r"><span>pass the quality check</span><b>${nf(r.mase_pass_pct)}% of products</b></div>`; }}}]},
    after: [`We still use TSB and XGBoost for longer histories because they tie on error but pass the quality check for more products (${lo === hi ? lo : lo + '–' + hi}% vs ${ma}%), so more products get a reorder plan.`],
    example: {file: () => `ch01_example_${rowOf(EVSTATE[1]).sku_code}`, title: 'Example: one product, what sold vs what the models forecast', W: 900, H: 330,
      toggle: [well, typ].every(Boolean) ? {options: [[well.pk, 'A well-forecast product'], [typ.pk, 'Typical product']], get: () => EVSTATE[1], set: v => { EVSTATE[1] = +v; }} : null,
      control: {options: skus.map(s => [s.pk, `${s.sku_code} · ${s.product_name} · ${sv(s.pk)[0]} → ${sv(s.pk)[1]}`]), get: () => EVSTATE[1], set: v => { EVSTATE[1] = +v; }},
      shows: ['Light line with dots = what actually sold each month. Blue = the model that serves this product today, forecasting one month ahead; grey = the other two models we use.',
              `Monthly sales jump up and down largely at random; forecasts aim at the general level — chasing every zigzag would be less accurate. (Naive, which just repeats last month, is about ${naiveGap} points worse than the 3-month average — first chart.)`,
              well ? `Shown first — a well-forecast product: ${rowOf(well.pk).sku_code} · ${rowOf(well.pk).product_name}. Rule: of the ${elig.length} products that pass the quality check and have 2+ years of sales, the middle of the best-forecast quarter (its error: ${Math.round(well.wape * 100)}%).`
                   : 'No product with a stored forecast error was available to pick a well-forecast example.',
              typ ? `“Typical product”: ${rowOf(typ.pk).sku_code} · ${rowOf(typ.pk).product_name}, whose error (${Math.round(typ.wape * 100)}%) is the closest to the typical product’s (${Math.round(medW * 100)}%). Or pick any product from the list.` : ''].filter(Boolean),
      build: t => { const R = S.filter(r => r.pk === EVSTATE[1]), ms = R.map(r => r.month), [hist, name, key] = sv(EVSTATE[1]), st = skd.get(EVSTATE[1]);
        return [{fr: {x: 0, y: 0, w: 900, h: 330}, o: {xs: ms, xticks: ms.filter((m, i) => i % 3 === 0), xlab: mlab, y: {fmt: v => nf(v), title: 'Units sold', zero: true},
          title: `${kind(EVSTATE[1])}${st && st.wape != null ? ` (error ${Math.round(st.wape * 100)}%)` : ''}: ${R[0].sku_code} · ${R[0].product_name} · ${hist} → served by ${name}`,
          series: [{key: 'actual', label: 'Actual sales', color: t.actual, width: 2.6, r: 2.5, pts: R.map(r => [r.month, r.actual])}]
            .concat([['ma3', '3-month average'], ['tsb', 'TSB'], ['ens_xgb_ma3@A', 'XGBoost + avg']].map(([k, lab]) => ({key: k,
              label: lab + (k === key ? ' (serves it)' : ''), bold: k === key, color: k === key ? t.ours : t.alt, width: k === key ? 3 : 1.3, markers: false,
              pts: R.map(r => [r.month, r[k]])})))}}]; }},
    faq: [
      ['How was the comparison done?', `Each month from October 2023 to February 2026, every model forecast the next month using only the months before it. The forecasts were then compared with what actually sold.`],
      [`What does “${e0}% forecast error” mean?`,
       `On a typical product, the forecast was off by about ${e0}% of that month’s actual sales (the middle value across the ${full('ma3').n} products tested).`],
      ['Which model is used for which product?', 'It depends on how many months of sales the product has: 3–11 months → 3-month average; 12–23 → TSB; 24 or more → XGBoost + average. Decision 2 tests these cut-offs.'],
      ['What is the “quality check”?', 'A product passes when its forecast beats a naive “same as last month” guess (MASE below 1). Only products that pass get an automatic reorder plan (decision 8).'],
      [`Is ${e0}% good?`, `Our data has no industry benchmark to compare with, so we can’t say. What we can say: it is about ${Math.round(bench)} points better than the two basic benchmarks.`],
    ],
    means: 'The simple method is as accurate as the complex ones, so forecasts stay easy to explain; the newer models let more products into the order plan.',
    details: [
      {file: 'ch01_periods', title: 'Forecast error in each half-year test period, with the test result per period', W: 900, H: 330 + 4 * 18 + 38,
       read: 'Each dot = one half-year test period. The squares say whether a model did better or worse than the simple average in that period.',
       build: t => [{fr: {x: 0, y: 0, w: 900, h: 330 + 4 * 18 + 38}, o: {ml: 210, xs: blocks, xlab: blab, y: {fmt: v => v.toFixed(2), title: 'Forecast error (lower is better)'},
         strip: {cmp: 'the simple average', rows: [['medium (served: TSB)', 'tsb', 'TSB, where we use it'], ['long (served: XGBoost+MA3 avg)', 'ens_xgb_ma3@A', 'XGBoost + avg, where we use it'],
                                                   ['ALL', 'sba', 'SBA, all products'], ['ALL', 'naive', 'Naive, all products']].map(([co, m, lab]) => ({label: lab, cells: Object.fromEntries(blocks.map(b => {
           const r = V.find(v => v.cohort === co && v.model === m && v.window === b); return [b, r ? r.verdict : 'NT']; }))}))},
         series: M.map(([k, lab, u]) => ({key: k, label: lab, color: u ? t[{ma3: 'ma3', tsb: 'tsb', 'ens_xgb_ma3@A': 'xgb'}[k]] : t.base, dash: u ? null : '5 3', width: u ? 2.2 : 1.6,
           pts: blocks.map(b => [b, pw(b, k) ?? null])}))}}]},
    ],
  };
};

CARDS[2] = c => {
  const L = evRecs(c.data.lines);
  const row = (f, k) => L.find(r => r.family === f && String(r.k) === String(k)) || {};
  const GR = [['3–6 months', [3, 4, 5, 6]], ['7–11 months', [7, 8, 9, 10, 11]], ['12–23 months', [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]], ['24+ months', [24, 'all']]];
  const gmean = (f, ks, col='median_wape') => { const v = ks.map(k => row(f, k)[col]).filter(x => x != null); return v.reduce((a, b) => a + b, 0) / v.length; };
  const F = [['ma3', '3-month average'], ['tsb', 'TSB'], ['xgb_ma3', 'XGBoost + average']];
  const ourRule = gi => gi <= 1 ? 'ma3' : gi === 2 ? 'tsb' : 'xgb_ma3';
  const binOf = gi => gi <= 1 ? 'short' : gi === 2 ? 'medium' : 'long';
  const shortName = {ma3: '3-mo avg', tsb: 'TSB', xgb_ma3: 'XGBoost+avg'};
  const vals = F.map(([f]) => GR.map(([, ks]) => gmean(f, ks)));
  const vOf = (f, gi) => vals[F.findIndex(x => x[0] === f)][gi];
  const best = f => { const v = GR.map(([, ks]) => gmean(f, ks)); return v.indexOf(Math.min(...v)); };
  const lowOf = gi => ({0: 3, 1: 7, 2: 12, 3: 24})[gi];
  const tsbB = best('tsb'), xgbB = best('xgb_ma3');
  const xgbLowestAll = GR.every((g, gi) => F.every(([f]) => f === 'xgb_ma3' || vOf('xgb_ma3', gi) < vOf(f, gi)));
  const gaps = GR.map((g, gi) => ourRule(gi) === 'xgb_ma3' ? null : (vOf(ourRule(gi), gi) - vOf('xgb_ma3', gi)) * 100).filter(x => x != null);
  const gapTxt = gaps.length ? Math.max(1, Math.round(gaps.reduce((a, b) => a + b, 0) / gaps.length)) : null;
  const pl = gapTxt === 1 ? '' : 's';
  const periods = String(row('tsb', 3).blocks || '').replace(/-/g, '').length;
  const spreadOf = f => { const v = GR.map((g, gi) => vOf(f, gi)); return (Math.max(...v) - Math.min(...v)) * 100; };
  const c1 = EV.charts.find(x => x.chart === 1), l1 = c1 ? evRecs(c1.data.lines).filter(r => r.window === 'full') : [];
  const w1 = k => (l1.find(r => r.model === k) || {}).median_wape;
  const gap1 = w1('ma3') != null && w1('ens_xgb_ma3@A') != null ? (w1('ma3') - w1('ens_xgb_ma3@A')) * 100 : null;
  const xs = [...new Set(L.map(r => String(r.k)))].filter(k => k !== 'all').sort((a, b) => a - b).concat(['', 'all']);
  // The direct cut-off test (stored; scripts/evidence/import_side_results.py): medium bin = the verdict, short bin = a side result.
  const CT = evRecs(c.data.cutoff12), cm = c.cutoff12_meta || {};
  const ct = (bin, w) => CT.find(r => r.bin === bin && r.window === w);
  const med = ct('medium', 'full'), sho = ct('short', 'full');
  const medWins = CT.filter(r => r.bin === 'medium' && r.window !== 'full' && r.v === 'W').length;
  const direct = !!(med && sho && cm.verdict === 'KEEP' && med.v !== 'W' && sho.v !== 'W');
  const p0 = x => Math.round(x * 100) + '%';
  BOARD[2] = ['3-month average from 3 months, TSB from 12, XGBoost from 24', 'Every cut-off from 3 to 24 months, then a direct test at 12',
              direct ? 'Our history rules hold; a direct test on newer products kept them.' : 'Our history rules are safe; XGBoost might start earlier, but that is not proven.'];
  return {
    question: 'How many months of past sales does each model need before it works well?',
    headline: c.verdict === 'CONFIRMS' ? `More history doesn't clearly help: TSB levels off by about ${lowOf(tsbB)} months, XGBoost by about ${lowOf(xgbB)}.`
      : 'A different amount of history works clearly better or worse; our cut-offs are questioned.',
    before: direct ? ['Tested directly: the current cut-offs hold.'] : [],
    main: {file: 'ch02_history', title: 'Forecast error by how many months of history the models were given (lower is better)', W: 900, H: 380,
      read: 'Each group = a range of history lengths; under it, the history group it falls in and the model our rule uses there. Blue = that model; grey = the other models.',
      shows: ['Each group = the same products, forecast as if only that many months of sales history existed. Bars = forecast error, averaged over the settings in the group.',
              'Blue = the model our rule uses: short history (3–11 months) → 3-month average; medium (12–23 months) → TSB; long (24+ months) → XGBoost + average.',
              'The 3-month average’s bar hardly moves: it only ever uses the last 3 months, so extra history can’t change it.',
              `Within each model the bars differ by less than ${Math.ceil(Math.max(spreadOf('tsb'), spreadOf('xgb_ma3')))} point between groups. TSB is lowest at ${GR[tsbB][0]}, XGBoost + average at ${GR[xgbB][0]}: "levels off" means more history stops helping, not that it hurts.`],
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 380}, draw: evGBars, o: {groups: GR.map(g => g[0]), gsub: GR.map((g, gi) => `${binOf(gi)} → we use ${shortName[ourRule(gi)]}`),
        ytitle: 'Forecast error (lower is better)', fmt: v => (v * 100).toFixed(0) + '%',
        legend: [[t.ours, 'Ours: the model our rule uses'], [t.alt, 'Other models']],
        series: F.map(([f, lab], si) => ({vals: vals[si], colorAt: gi => oursAlt(t, ourRule(gi) === f), sub: GR.map(() => lab.replace(' + average', '+avg').replace('3-month average', '3-mo avg')),
          subInk: gi => ourRule(gi) === f ? t.ink : t.ink3, bold: gi => ourRule(gi) === f})),
        tip: k => { const gi = GR.findIndex(g => g[0] === k); return `<div class="h">${esc(k)} of history (${binOf(gi)})</div>` + F.map(([f, lab], si) => `<div class="r"><span>${esc(lab)}${ourRule(gi) === f ? ' (ours)' : ''}</span><b>${pc(vals[si][gi], 1)}</b></div>`).join(''); }}}]},
    after: [c.verdict === 'CONFIRMS' ? 'No setting was clearly better or worse than the simple average.' : '',
            xgbLowestAll ? `XGBoost + average is slightly lowest in every group, even where we use other models. The gaps (about ${gapTxt} point${pl}) aren’t proven — only ${periods} test periods. `
              + (direct ? 'This chart cuts down long-established products, though; tested directly on products that really have 12–23 months, TSB did better (see the first question below).'
                        : 'It can work with shorter histories because it learns from all products together. A possible improvement, not proven — changing the rule is a separate decision.') : ''].filter(Boolean),
    faq: [
      med ? ['Why not use XGBoost + average from 12 months?',
             `We tested it directly on the ${med.n} products that really have 12–23 months of history, with the pass/fail rule written down first. `
             + `TSB did slightly better (${p0(med.inc)} vs ${p0(med.ch)} error), XGBoost + average was worse on more products than better (${med.nw} vs ${med.nb}) and won ${medWins ? medWins + ' test period' + (medWins === 1 ? '' : 's') : 'no test period'}. `
             + `Verdict: ${cm.verdict === 'KEEP' ? 'keep TSB' : String(cm.verdict || 'not stored')}. The pattern in this chart came from cutting down long-established products; the direct test on genuinely newer products is the fairer one.`
             + (sho ? ` Same for 3–11 months (a side result, not part of the verdict): ${sho.v === 'W' ? 'XGBoost + average did better than' : 'the simple 3-month average holds —'} ${sho.v === 'W' ? 'the simple 3-month average' : `XGBoost + average ${p0(sho.ch)} vs ${p0(sho.inc)} error, worse on ${sho.nw} of ${sho.n} products`}.` : '')] : null,
      ['How was this tested?', 'We took the products with at least 30 months of sales, pretended we only had their last few months (from 3 up to 24), and forecast the months that followed — the same months for every setting.'],
      [`Why only ${periods} test periods?`, `To compare every setting on the same months, each product first needed 24 months of history. That is only true from January 2025, which leaves ${periods} half-year periods.`],
      ['If XGBoost + average is lowest here, why is decision 1 a tie?', gap1 != null ? `Both cards say the same thing. Decision 1 compares all products: XGBoost + average is ${gap1.toFixed(1)} points below the 3-month average. This card uses only products with 30+ months of sales, where its lead is about ${gapTxt} point${pl}. Neither gap is large enough to be proven.` : 'Decision 1 compares all products; this card only products with 30+ months of sales. Neither gap is proven.'],
      ['What happens to products with fewer than 3 months of sales?', 'No model can forecast them yet. A provisional average is stored and clearly flagged "insufficient data".'],
    ].filter(Boolean),
    means: direct ? 'Our history rules hold: a direct test on genuinely newer products kept TSB for 12–23 months and the simple average for 3–11 months.'
      : `Our history rules are safe. XGBoost looks best from about ${lowOf(xgbB)} months although our rule starts it at 24 — not proven, only ${periods} test periods.`,
    details: [
      {file: 'ch02_truncation_wape', title: 'All 22 settings: forecast error, with the test result per setting', W: 900, H: 450,
       read: 'Left to right = more months of history. The squares: each is one half-year test period (2 per setting).',
       build: t => [{fr: {x: 0, y: 0, w: 900, h: 450}, o: {ml: 190, xs, xlab: k => k === 'all' ? 'all' : k, y: {fmt: v => v.toFixed(3), title: 'Forecast error (lower is better)'},
         vrules: [{x: '3', label: 'MA3 needs 3', dy: 10}, {x: '12', label: 'TSB from 12', dy: 10}, {x: '24', label: 'XGBoost from 24', dy: 22}],
         xtitle: 'Months of sales history the models were given (then all of it)',
         strip: {cmp: 'the simple average', title: 'Each square = one half-year test period (2 per setting)',
           rows: [['tsb', 'TSB vs simple average'], ['xgb_ma3', 'XGBoost + avg vs simple average']].map(([f, lab]) => ({label: lab,
             cells: Object.fromEntries(xs.filter(k => k !== '').map(k => { const p = String(row(f, k).blocks || '').replace(/-/g, '').split('').filter(Boolean); return [k, p.length ? p : ['NT']]; }))}))},
         series: F.map(([f, lab]) => ({key: f, label: lab, color: t[{ma3: 'ma3', tsb: 'tsb', xgb_ma3: 'xgb'}[f]], width: 2, pts: xs.map(k => [k, k === '' ? null : row(f, k).median_wape ?? null])}))}}]},
      {file: 'ch02_truncation_mase', title: 'Share of products that pass the quality check (MASE below 1), by history length', W: 900, H: 300,
       read: 'Up = more products forecast better than a naive “same as last month” guess. Higher is better.',
       build: t => [{fr: {x: 0, y: 0, w: 900, h: 300}, o: {ml: 190, xs, xlab: k => k === 'all' ? 'all' : k, y: {fmt: v => v.toFixed(0) + '%', title: 'Products passing (higher is better)'},
         series: F.map(([f, lab]) => ({key: f, label: lab, color: t[{ma3: 'ma3', tsb: 'tsb', xgb_ma3: 'xgb'}[f]], width: 2, pts: xs.map(k => [k, k === '' ? null : row(f, k).mase_pass_pct ?? null])}))}}]},
    ],
    detailsHTML: med ? `<p class="evcap"><b>Direct cut-off test</b> (verdict <b>${esc(String(cm.verdict))}</b>; pre-registered at <code>${esc(String(cm.prereg_commit))}</code>; source ${esc(String(cm.source))}). ${esc(String(cm.status || ''))}</p>`
      + `<table class="evtable"><thead><tr><th>History group</th><th>Our model</th><th>Products</th><th>XGBoost + avg error</th><th>Our model’s error</th><th>Better / worse (products)</th><th>Full-window result</th></tr></thead><tbody>`
      + [[med, 'medium (12–23) — the verdict', 'TSB'], [sho, 'short (3–11) — side result', '3-month average']].filter(r => r[0]).map(([r, lab, inc]) =>
          `<tr><td>${esc(lab)}</td><td>${esc(inc)}</td><td>${r.n}</td><td>${pc(r.ch)}</td><td>${pc(r.inc)}</td><td>${r.nb} / ${r.nw}</td><td>${esc(r.v)}</td></tr>`).join('')
      + `</tbody></table>` : '',
  };
};

CARDS[3] = c => {
  const L = evRecs(c.data.lines), V = evRecs(c.data.verdicts);
  const W_ = [['ma2', '2 months', false], ['ma3', '3 months', true], ['ma6', '6 months', false], ['ma12', '12 months', false]];
  const lab = m => (W_.find(w => w[0] === m) || [m, m])[1], lab2 = m => ({ma2: '2-month', ma3: '3-month', ma6: '6-month', ma12: '12-month'})[m] || m;
  const full = m => (L.find(r => r.window === 'full' && r.model === m) || {}).median_wape;
  const blocks = [...new Set(L.filter(r => r.window !== 'full').map(r => r.window))];
  const bw = (b, m) => (L.find(r => r.window === b && r.model === m) || {}).median_wape;
  const lowerIn = m => blocks.filter(b => bw(b, m) < bw(b, 'ma3')).length;
  const flab = w => String(w).split('..').map(m => MON[+m.slice(5, 7) - 1] + ' ' + m.slice(0, 4)).join('–');
  const alts = W_.filter(w => !w[2]).map(w => w[0]), top = alts.slice().sort((a, b) => lowerIn(b) - lowerIn(a))[0];
  const vb = V.filter(v => v.window !== 'full'), wins = vb.filter(v => v.verdict === 'W'), losses = vb.filter(v => v.verdict === 'L');
  const topAllTie = V.filter(v => v.model === top).every(v => v.verdict === 'T' || v.verdict === 'NT');
  const spread = Math.max(...alts.map(m => Math.abs(full(m) - full('ma3')))) * 100;
  const n = (L.find(r => r.window === 'full' && r.model === 'ma3') || {}).n;
  BOARD[3] = ['Average of the last 3 months', '2, 6 and 12 months', 'Keep the 3-month average; the other windows are no more accurate.'];
  return {
    question: 'How many recent months should the simple average use: 2, 3, 6 or 12?',
    before: ['Short windows react fast to change but jump around; long windows are smooth but slow to notice change. (Not the same as decision 2: that asks how much history a model needs; this asks how many recent months the simple average uses.)'],
    headline: c.verdict === 'CONFIRMS' ? 'Three months is as good as any other window: no window is clearly better.' : 'Another averaging window beats the 3-month average.',
    main: {file: 'ch03_window', title: 'Forecast error of the simple average by window, all test periods together (lower is better)', W: 900, H: 320,
      read: 'Blue = ours (3 months); grey = the alternatives. Bars of about equal height = a tie.',
      shows: [`Each bar = the simple average’s forecast error when it averages the last 2, 3, 6 or 12 months (${n} products, Oct 2023 – Feb 2026). Shorter is better.`,
              `Blue = ours, 3 months (${pc(full('ma3'))}). The others: ${alts.map(m => `${lab(m)} ${pc(full(m))}`).join(', ')} — all within ${Math.ceil(spread)} points: a tie.`,
              topAllTie ? `The ${lab2(top)} average was slightly lower than ours in ${lowerIn(top)} of ${blocks.length} test periods, but never by enough to count as better (its margin of error always included “no difference”).`
                        : `The ${lab2(top)} average was lower than ours in ${lowerIn(top)} of ${blocks.length} test periods.`,
              (losses.length ? `In single test periods, ${listWords(losses.map(v => `the ${lab2(v.model)} average was clearly worse once (${flab(v.window)})`))}` : 'No window was clearly worse in any single test period')
                + (wins.length ? `; ${listWords(wins.map(v => `the ${lab2(v.model)} average was clearly better once (${flab(v.window)})`))}.` : '; no window was ever clearly better.')],
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 320}, draw: evGBars, o: {groups: W_.map(w => w[1]), ytitle: 'Forecast error (lower is better)', fmt: v => (v * 100).toFixed(0) + '%',
        series: [{vals: W_.map(w => full(w[0])), colorAt: gi => oursAlt(t, W_[gi][2]), sub: W_.map(w => w[2] ? 'Ours' : ''), subInk: () => t.ink, bold: gi => W_[gi][2]}],
        tip: k => { const w = W_.find(q => q[1] === k); return `<div class="h">average of the last ${esc(k)}</div><div class="r"><span>forecast error</span><b>${pc(full(w[0]))}</b></div>`; }}}]},
    faq: [
      ['Why test 6 and 12 months?', `A longer average is smoother (12 months covers a whole year); a shorter one reacts faster. We checked whether smoother is more accurate — it isn’t: 12 months is ${pc(full('ma12'))} overall vs ${pc(full('ma3'))} for 3 months, a tie.`],
      ['What about sudden jumps in sales?', 'Detecting sudden jumps in sales is a different question — see decision 6.'],
      [`The ${lab2(top)} average was lower in ${lowerIn(top)} of ${blocks.length} periods — why not switch?`,
       topAllTie ? 'In every period its margin of error included “no difference”, so by the rule written down beforehand it is a tie, and a tie keeps the current choice.'
                 : 'See the per-period results under Details.'],
      ['How was this tested?', 'The same way as decision 1: each month from October 2023 to February 2026, each window forecast the next month from the months before it, and the forecasts were compared with what sold.'],
    ],
    means: 'Keep the 3-month average; the other windows are no more accurate.',
    details: [{file: 'ch03_periods', title: 'Per half-year test period, with the test result per period', W: 900, H: 420,
      read: 'Each dot = one half-year test period. The squares say whether each window did better or worse than 3 months in that period.',
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 420}, o: {ml: 190, mr: 150, xs: blocks, xlab: blab, y: {fmt: v => v.toFixed(2), title: 'Forecast error (lower is better)'},
        strip: {cmp: 'the 3-month average', rows: W_.filter(w => !w[2]).map(([m, lb]) => ({label: `${lb} vs 3 months`,
          cells: Object.fromEntries(blocks.map(b => { const r = V.find(v => v.model === m && v.window === b); return [b, r ? r.verdict : 'NT']; }))}))},
        series: W_.map(([m, lb, ours], i) => ({key: m, label: lb + (ours ? ' (ours)' : ''), color: ours ? t.ma3 : t.ramp[[0, 0, 1, 2][i]], dash: [null, null, '6 3', '2 3'][i], width: ours ? 2.6 : 1.8,
          pts: blocks.map(b => [b, bw(b, m) ?? null])}))}}]}],
  };
};

CARDS[4] = c => {
  const L = evRecs(c.data.lines), V = evRecs(c.data.verdicts);
  const wins = [...new Set(L.filter(r => r.n > 0).map(r => r.window))];
  const at = (w, x) => (L.find(r => r.window === w && r.weight === x) || {}).median_wape;
  const OPT = [[0, 'Only the average', false], [0.5, '50/50 (ours)', true], [1, 'Only XGBoost', false]];
  const blocks = wins.filter(w => w !== 'full');
  const helps = blocks.some(w => at(w, 1) < at(w, 0)), hurts = blocks.some(w => at(w, 1) > at(w, 0));
  const ws = [...new Set(L.map(r => r.weight))].sort((a, b) => a - b);
  const cells = ag => Object.fromEntries(ws.map(w => { const vv = V.filter(v => v.weight === w && v.against === ag && v.window !== 'full' && v.verdict !== 'NT').map(v => v.verdict);
    return [String(w), (ag === 'w=0.5' && w === 0.5) || (ag === 'MA3' && w === 0) ? null : (vv.length ? vv : ['NT'])]; }));
  const vv = (w, ag, win) => V.find(v => v.weight === w && v.against === ag && v.window === win) || {};
  const WORD = {T: 'a tie', W: 'clearly better', L: 'clearly worse', NT: 'not testable'};
  const fullN = (L.find(r => r.window === 'full' && r.weight === 0.5) || {}).n;
  const fw = ws.map(x => [x, at('full', x)]).filter(p => p[1] != null), minW = fw.reduce((a, b) => b[1] < a[1] ? b : a);
  const lostVs50 = w => blocks.filter(b => vv(w, 'w=0.5', b).verdict === 'L');
  const between = (at('full', 0.5) - at('full', 0)) * (at('full', 0.5) - at('full', 1)) < 0;
  const spread = (Math.max(...OPT.map(o => at('full', o[0]))) - Math.min(...OPT.map(o => at('full', o[0])))) * 100;
  BOARD[4] = ['50/50 blend of XGBoost and the 3-month average', 'Every mix from 0% to 100% XGBoost', 'Keep the 50/50 blend; leaning on XGBoost helps in some half-years and hurts in others.'];
  return {
    question: 'When we blend XGBoost with the simple average, how much weight should XGBoost get?',
    headline: c.verdict === 'CONFIRMS' && helps && hurts ? 'XGBoost helps in some periods and hurts in others; 50/50 is the safe middle.'
      : c.verdict === 'CONFIRMS' ? 'No other mix beats the 50/50 blend we use.' : 'A different XGBoost/average mix beats our 50/50 blend.',
    main: {file: 'ch04_blend', title: 'Forecast error for three blends, by test period (products with 24+ months of history; lower is better)', W: 900, H: 340,
      read: 'Each group = a test period. Blue = ours (50/50); grey = all average or all XGBoost. Where the right-hand grey bar is shorter, XGBoost helped that period; taller, it hurt.',
      shows: [`Each group = a half-year test period, and the first = both combined. Only ${blocks.length} periods could be tested: the blend is for products with 24+ months of sales (${fullN} here), and the first reached that in January 2025.`,
              'Blue = ours (50/50). Grey: left = only the 3-month average, right = only XGBoost.',
              blocks.map(b => { const r = vv(1, 'w=0.5', b); return `${plab(b)}: only XGBoost was ${at(b, 1) > at(b, 0.5) ? 'higher' : 'lower'} than ours (${pc(at(b, 1))} vs ${pc(at(b, 0.5))}) — ${WORD[r.verdict] || 'not stored'}`; }).join('; ') + '.',
              `Combined, the three are within ${spread.toFixed(1)} points of each other${between ? '; 50/50 sits between the two extremes' : ''}.`],
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 340}, draw: evGBars, o: {groups: wins.map(plab), ytitle: 'Forecast error (lower is better)', fmt: v => (v * 100).toFixed(0) + '%',
        legend: [[t.alt, 'Only the average'], [t.ours, '50/50 (ours)'], [t.alt2, 'Only XGBoost']],
        series: OPT.map(([x, lab, ours]) => ({vals: wins.map(w => at(w, x)), color: ours ? t.ours : x === 0 ? t.alt : t.alt2})),
        tip: k => { const w = wins[wins.map(plab).indexOf(k)]; return `<div class="h">${esc(k)}</div>` + OPT.map(([x, lab]) => `<div class="r"><span>${esc(lab)}</span><b>${pc(at(w, x))}</b></div>`).join(''); }}}]},
    faq: [
      ['Why not XGBoost alone?', `Against our 50/50 blend it was ${blocks.map(b => { const r = vv(1, 'w=0.5', b); return `${WORD[r.verdict] || 'not stored'} in ${plab(b)}${r.verdict === 'L' ? ` (worse on ${r.n_worse} of ${r.n} products)` : ''}`; }).join(' and ')}. `
        + `Against the 3-month average alone it was ${blocks.map(b => `${WORD[vv(1, 'MA3', b).verdict] || 'not stored'} in ${plab(b)}`).join(' and ')}. `
        + 'So it is worse in some periods, and the blend is easier to explain: half of it is the simple 3-month average.'],
      [`The lowest combined error is at ${minW[0].toFixed(1)} XGBoost — why not use that?`, minW[0] === 0.5 ? 'It is our blend.'
        : `Its lead over 50/50 (${pc(minW[1])} vs ${pc(at('full', 0.5))}) is ${WORD[vv(minW[0], 'w=0.5', 'full').verdict] || 'not stored'}` + (lostVs50(minW[0]).length ? `, and it was clearly worse than 50/50 in ${listWords(lostVs50(minW[0]).map(plab))}.` : '.')],
      [`Why only ${blocks.length} test periods?`, 'The blend is only used for products with 24 or more months of sales; the first products reached that in January 2025, so the earlier half-years have none.'],
    ],
    means: 'Keep the 50/50 blend: leaning more on XGBoost would help in some half-years and hurt in others.',
    details: [{file: 'ch04_blend_weight', title: 'All 11 blends (0 = only the average, 1 = only XGBoost), with the test result per period', W: 900, H: 430,
      read: 'Each line = one time period. The squares: each is one half-year test period (2 per blend).',
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 430}, o: {ml: 170, xs: ws, xlab: w => w.toFixed(1), xtitle: 'Weight on XGBoost', vrules: [{x: 0.5, label: 'ours (0.5)'}],
        y: {fmt: v => v.toFixed(3), title: 'Forecast error (lower is better)'},
        strip: {cmp: 'the comparison in the row', title: 'Each square = one half-year test period (2 per blend)', rows: [{label: 'vs our 50/50 blend', cells: cells('w=0.5')}, {label: 'vs 3-month average alone', cells: cells('MA3')}]},
        series: wins.map((w, i) => ({key: w, label: plab(w), color: w === 'full' ? t.ramp[2] : t.ramp[i === 1 ? 1 : 0], dash: w === 'full' ? null : (i === 1 ? '6 3' : '2 3'), width: w === 'full' ? 2.6 : 1.8,
          pts: ws.map(x => [x, at(w, x) ?? null])}))}}]}],
  };
};

CARDS[5] = c => {
  const R = evRecs(c.data.rates), all = R.find(r => r.candidate_set === 'all 162') || {}, N = evRecs(c.data.names);
  const plain = {'original 50': 'First 50 methods tried', 'phase 1 (35)': 'Round 2: 35 reshapings', 'phase 2 (77)': 'Round 3: 77 more', 'all 162': 'All 162 together'};
  // Examples per bar, named only when the stored candidate list contains them.
  const has = (set, f) => N.some(r => r.set === set && f(r));
  const EX0 = [['naive', 'naive'], ['snaive12', 'seasonal naive'], ['holt', 'Holt'], ['theta', 'Theta'], ['ets_auto', 'ETS'], ['croston', 'Croston'], ['rf@A', 'random forest'],
               ['ridge@A', 'ridge regression'], ['mlp@A', 'neural net'], ['lgbm@A', 'LightGBM'], ['xgb_raw@A', 'XGBoost alone']].filter(([k]) => has('original 50', r => r.candidate === k)).map(e => e[1]);
  const EX1 = [['log1p', 'log'], ['sqrt', 'square root'], ['boxcox', 'Box-Cox'], ['cbrt', 'cube root'], ['winsor', 'spike capping (winsorize)'], ['yeojohnson', 'Yeo-Johnson'],
               ['asinh', 'inverse hyperbolic sine'], ['anscombe', 'Anscombe'], ['diff1', 'differencing once'], ['stl12', 'seasonal adjustment (STL)']].filter(([k]) => has('phase 1 (35)', r => r.part === k)).map(e => e[1]);
  const EX2 = [['A:', 'differencing twice, three times or seasonally (D2, D3, S12)'], ['B:', 'a transform + differencing'], ['C:', 'repeated transforms (e.g. square root twice)'],
               ['D:', 'automatic differencing'], ['E:', 'auto-ARIMA / fixed SARIMA']].filter(([p]) => has('phase 2 (77)', r => String(r.part || '').startsWith(p))).map(e => e[1]);
  const EXS = {'original 50': 'naive, Holt, ETS, XGBoost…', 'phase 1 (35)': 'log, square root, Box-Cox…', 'phase 2 (77)': 'differencing, ARIMA…', 'all 162': ''};
  const chance = R[0].chance_per_block, allBelow = R.every(r => r.cp_hi < chance);
  BOARD[5] = ['No transform (forecast the sales as they are)', `${all.candidates || 162} alternatives, incl. log / square-root transforms`, 'No need to add data transforms: more complexity, no real accuracy gain.'];
  return {
    question: 'Does reshaping the sales numbers before forecasting help?',
    before: ['A transform = for example using the log or square root of sales, forecasting that, then converting back.'],
    headline: c.verdict === 'CONFIRMS' ? `No. None of the ${all.candidates} alternatives truly beat our method; their few wins look like luck.`
      : 'Transforming the sales data helps more often than luck would explain.',
    main: {file: 'ch05_transforms', title: 'How often the alternatives beat ours (no transform) in a half-year test period', W: 900, H: 345,
      read: 'Ours = no transform: every bar is measured against it. Grey bars = alternatives. The black whisker = the range the true rate likely falls in. Dashed line = how often they would win by pure luck.',
      shows: [EX0.length ? `First 50 methods tried = the original model comparison, e.g. ${listWords(EX0)}.` : 'First 50 methods tried = the original model comparison.',
              EX1.length ? `Round 2 (35) = reshaping the sales before forecasting — ${listWords(EX1)} — applied to our models and to a simple combination of methods.` : 'Round 2 (35) = reshaping the sales before forecasting.',
              EX2.length ? `Round 3 (77) = ${listWords(EX2)}.` : 'Round 3 (77) = further reshaping methods.',
              `Each bar = the share of half-year test periods those methods won against ours. ${allBelow ? 'Even the top of every whisker is below the dashed “pure luck” line' : 'Compare each whisker with the dashed “pure luck” line'} (${pc(chance, 1)}).`],
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 345}, draw: evGBars, o: {groups: R.map(r => plain[r.candidate_set] || r.candidate_set), ytitle: 'Test periods won', fmt: v => (v * 100).toFixed(1) + '%',
        gsub: R.map(r => EXS[r.candidate_set] ? 'e.g. ' + EXS[r.candidate_set] : ''), gsubInk: t.ink3,
        legend: [[t.ours, 'Ours = no transform (the baseline each bar is compared with)', true], [t.alt, 'Alternatives']],
        series: [{vals: R.map(r => r.block_win_rate), colorAt: () => t.alt}],
        hrules: [{y: chance, label: 'pure luck'}],
        whiskers: R.map((r, gi) => ({gi, si: 0, lo: r.cp_lo, hi: r.cp_hi})),
        tip: k => { const r = R.find(q => (plain[q.candidate_set] || q.candidate_set) === k); return `<div class="h">${esc(k)}</div>`
          + `<div class="r"><span>test periods won</span><b>${r.block_wins} of ${nf(r.testable_blocks)} (${pc(r.block_win_rate, 1)})</b></div>`
          + `<div class="r"><span>likely range of the true rate</span><b>${pc(r.cp_lo, 1)}–${pc(r.cp_hi, 1)}</b></div><div class="r"><span>real wins</span><b>${r.real}</b></div>`; }}}]},
    after: [`A “real win” = better overall AND in most test periods — none of the ${all.candidates} managed it.`],
    faq: [
      ['What is a “real win”?', `Better overall AND in most half-year test periods, by the same tie / better / worse rule as decision 1. None of the ${all.candidates} managed it.`],
      [`Where does the ${pc(chance, 1)} “pure luck” line come from?`, `A period counts as a win only when the 95% margin of error sits entirely on the better side. A method no better than ours still lands there by chance about 1 time in 40 (${pc(chance, 1)}).`],
      ['So what were the few wins?', `${all.block_wins} wins in ${nf(all.testable_blocks)} period comparisons (${pc(all.block_win_rate, 1)}) — fewer than luck alone would give. That is what “look like luck” means.`],
    ],
    means: 'No need to add data transforms: they add complexity without a real accuracy gain.',
    details: [],
  };
};

CARDS[6] = c => {
  const S = evRecs(c.data.skus), M = evRecs(c.data.months), R = evRecs(c.data.rescue);
  const n = S.length, nScored = R.length ? R[0].products : null;
  const stored = R.filter(r => r.status === 'stored'), notStored = R.filter(r => r.status !== 'stored');
  const alts = stored.filter(r => !/^Ours/.test(r.approach)), ours = stored.find(r => /^Ours/.test(r.approach));
  const maxBest = alts.length ? Math.max(...alts.map(r => +r.best_single_method)) : null;
  const bestRows = alts.filter(r => +r.best_single_method === maxBest), zeroAlts = alts.filter(r => +r.best_single_method === 0).length;
  const luck = alts.filter(r => r.held_earlier === 'not checked' && +r.best_single_method > 0);
  const promo = S.filter(s => /\(\d+\+\d+\)/.test(s.product_name)).length;
  if (EVSTATE[6] == null) EVSTATE[6] = S[0].pk;
  const plainCause = {'level shift': 'Sales level jumped', 'spiky': 'Sudden spikes', 'high volatility': 'Very up-and-down', 'tiny scale': 'Very small volumes',
                      'none of the above': 'No clear cause', 'intermittent': 'Months with no sales', 'trend reversal': 'Trend reversed'};
  const pcause = k => plainCause[k] || k;
  const SERVED = {ma3: 'ma3', tsb: 'tsb', xgb_ma3_avg: 'xgb'};
  const NOTE = 'tested as a group — none passed; which products each one helped wasn’t saved';
  BOARD[6] = ['Flag them for manual review (buyer decides)', 'Other models, spike capping, differencing, transforms', 'These products need the buyer’s judgement each month.'];
  return {
    question: 'Which products can’t be forecast well, and can any method fix them?',
    headline: R.length ? `${n} products forecast poorly; no method we tried rescues more than ${maxBest} of them.`
      : `${n} products forecast poorly; per-product results of other methods are not available from stored results.`,
    main: R.length ? {file: 'ch06_rescue', title: `How many of the ${nScored} poorly-forecast products each approach rescued (brought below the fit line)`, W: 900, H: 30 + R.length * 22 + 50,
      read: `Blue = ours (the model that serves them today); grey = alternatives we tried. Bar = the best single method in that group. The other ${n - nScored} products were scored on a different test window and are not comparable here.`,
      shows: [`Each row = one approach tried on the ${nScored} poorly-forecast products; the bar = how many it brought below the fit line (MASE below 1.1, the fit-review gate) on the common test months.`,
              ours ? `Blue = ours, the model serving them today: ${ours.best_single_method} — that’s why these products are flagged.` : 'Blue = ours (not stored).',
              `The best alternative${bestRows.length > 1 ? 's' : ''} (${listWords(bestRows.map(r => r.approach))}) rescued ${maxBest} of ${nScored}; ${zeroAlts} of the ${alts.length} counted approaches rescued none.`
                + (luck.length ? ` “May be luck — not re-checked” = ${listWords(luck.map(r => r.approach))}: those rescues were never re-tested on earlier periods.` : ''),
              notStored.length ? `${notStored.length} rows have no bar: ${NOTE}.` : ''].filter(Boolean),
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 30 + R.length * 22 + 50}, draw: evHBars, o: {xmax: nScored, fmt: v => nf(v), xtitle: `Products rescued (out of ${nScored})`,
        rows: R.map(r => { const isO = /^Ours/.test(r.approach), v = r.status === 'stored' ? +r.best_single_method : null;
          return {label: r.approach, ours: isO, val: v, color: isO ? t.ours : t.alt, note: NOTE,
            text: v == null ? '' : isO ? `${v} — that’s why these products are flagged` : `${v}` + (r.held_earlier === 'not checked' && v > 0 ? ' · may be luck — not re-checked' : ''), raw: r}; }),
        tip: row => row.raw.status !== 'stored' ? `<div class="h">${esc(row.label)}</div>${esc(row.raw.status)}`
          : `<div class="h">${esc(row.label)}</div><div class="r"><span>methods tried</span><b>${row.raw.methods}</b></div>`
            + `<div class="r"><span>best single method rescued</span><b>${row.raw.best_single_method}</b></div><div class="r"><span>rescued by any method</span><b>${row.raw.any_method}</b></div>`
            + `<div class="r"><span>rescue held on earlier periods</span><b>${esc(String(row.raw.held_earlier || '—'))}</b></div>`}}]} : null,
    after: [`<b>What the system does instead:</b> flags these products “needs manual review”. They are left out of the automatic order plan, which only plans products that pass the quality check, so the buyer decides — for example with a larger buffer. (An automatic larger buffer is not built.)`,
            `Observation, not a cause: ${promo} of the ${n} have a promo-pack marker like “(11+1)” in their name.`],
    afterHTML: true,
    faq: [
      ['What does “rescued” mean?', 'The product’s forecast got below the fit line — MASE below 1.1 (the fit-review gate), i.e. clearly better than a “same as last month” guess — on the common test months, September 2025 to February 2026.'],
      [`Why are only ${nScored} of the ${n} counted?`, `The other ${n - nScored} were scored on a different test window, so their results can’t be put on the same chart.`],
      bestRows.length ? [`${bestRows[0].approach} rescued ${maxBest} — why not use it?`, `${maxBest} of ${nScored} leaves ${nScored - maxBest} still flagged, so the buyer’s review is needed either way.`
        + (bestRows[0].held_earlier === 'not checked' ? ' Its rescues were also never re-checked on earlier periods.' : ` Of the products this group rescued, ${bestRows[0].held_earlier} also held up on earlier periods.`)] : null,
      ['Is the promo-pack marker the cause?', `Not tested. ${promo} of the ${n} have a marker like “(11+1)” in the name; that is an observation only.`],
    ].filter(Boolean),
    means: 'These products need the buyer’s judgement each month; no forecasting method we tried fixes them.',
    details: [
      {file: () => `ch06_unfit_${(S.find(s => s.pk === EVSTATE[6]) || {}).sku_code}`, title: 'A concrete example: one poorly-forecast product', W: 900, H: 340,
       control: {options: S.map(s => [s.pk, `${s.sku_code} · ${s.product_name} · ${pcause(s.cause_group)}`]), get: () => EVSTATE[6], set: v => { EVSTATE[6] = +v; }},
       read: 'Grey = actual monthly sales. Coloured line = our forecast for the recent test months, with its likely range shaded. Circle = an unusual spike.',
       build: t => {
         const s = S.find(q => q.pk === EVSTATE[6]), RR = M.filter(r => r.pk === s.pk), ms = RR.map(r => r.month), col = t[SERVED[s.served_model]] || t.blue;
         const rects = []; const fl = f => { const k = RR.filter(f); return k.length ? [k[0].month, k[k.length - 1].month] : null; };
         const pr = fl(r => r.level_prior), rc = fl(r => r.level_recent);
         if (pr) rects.push({x0: pr[0], x1: pr[1], op: 0.05, label: 'earlier 12 months'}); if (rc) rects.push({x0: rc[0], x1: rc[1], op: 0.11, label: 'last 6'});
         return [{fr: {x: 0, y: 0, w: 900, h: 340}, o: {xs: ms, xticks: ms.filter((m, i) => i % 3 === 0), xlab: mlab, rects,
           title: `${s.sku_code} · ${s.product_name} · main cause: ${pcause(s.cause_group)}`, y: {fmt: v => nf(v), title: 'Units sold', zero: true},
           series: [{key: 'actual', label: 'Actual sales', color: t.actual, width: 2.2, r: 2.5, pts: RR.map(r => [r.month, r.actual])},
                    {key: 'fc', label: 'Our forecast + range', color: col, width: 2, band: RR.map(r => [r.month, r.band_lo, r.band_hi]), pts: RR.map(r => [r.month, r.holdout ? r.forecast : null])},
                    {key: 'spike', label: 'Unusual spike', color: t.ink, line: false, hollow: true, r: 6, pts: RR.map(r => [r.month, r.spike ? r.actual : null])}]}}]; }},
      {file: 'ch06_unfit_causes', title: 'Poorly-forecast products by main cause', W: 900, H: 280,
       read: 'Each bar = how many of these products share that main cause.',
       build: t => { const causes = [...new Set(S.map(s => s.cause_group))];
         return [{fr: {x: 0, y: 0, w: 900, h: 280}, draw: evGBars, o: {groups: causes.map(pcause), fmt: v => v.toFixed(0), ytitle: 'Products',
           series: [{vals: causes.map(k => S.filter(s => s.cause_group === k).length), color: t.alt, labels: causes.map(k => String(S.filter(s => s.cause_group === k).length))}]}}]; }},
    ],
    detailsHTML: R.length ? `<p class="evcap">Rescue tally: <code>reports/evidence/ch06_rescue.csv</code> (script <code>scripts/evidence/ch06_rescue.py</code>), from stored per-product results of the transforms experiment (fce007e, common test window). “Rescued” = the product’s MASE falls below the fit line (1.1) on that window. Phase-2 methods were also checked on earlier periods; phase-1 methods were not.</p>` : '',
  };
};

CARDS[7] = c => {
  const C7 = evRecs(c.data.curve), T7 = evRecs(c.data.tiers), MV = evRecs(c.data.unilever_moves);
  const U = C7.filter(r => r.principal === 'unilever' && r.method === 'single'), DM = C7.filter(r => r.principal === 'delmonte');
  const nU = U.length, tierN = k => U.filter(r => r.tier === k).length, share = k => U.filter(r => r.tier === k).reduce((a, r) => a + r.revenue_share, 0);
  const t3 = T7.find(r => r.principal === 'unilever' && r.method === 't3m') || {}, t1 = T7.find(r => r.principal === 'unilever' && r.method === 'single') || {};
  const tdm = T7.find(r => r.principal === 'delmonte') || {};
  const per = p => p ? MONL[+String(p).slice(5, 7) - 1] + ' ' + String(p).slice(0, 4) : 'period not stored';
  const perS = p => p ? MON[+String(p).slice(5, 7) - 1] + ' ' + String(p).slice(0, 4) : '';
  const changed = MV.filter(r => r.single !== r.t3m).reduce((a, r) => a + r.n, 0), aMoves = MV.filter(r => (r.single === 'A') !== (r.t3m === 'A')).reduce((a, r) => a + r.n, 0);
  const nA = tierN('A'), pctA = Math.round(nA / nU * 100), n3 = (t3.A || 0) + (t3.B || 0) + (t3.C || 0);
  BOARD[7] = ['Rank by the latest month’s revenue', 'Rank by a 3-month average', 'SSM can focus forecasting and ordering effort on about 1 product in 5.'];
  const draw = (t, fr) => {
    // left: Unilever cumulative curve (ours); right: A/B/C bars, ours vs the 3-month view
    const L = {x: fr.x, y: fr.y, w: 560, h: fr.h}, Rt = {x: fr.x + 580, y: fr.y, w: fr.w - 580, h: fr.h};
    const X0 = L.x + 64, Y0 = L.y + 30, pw = L.w - 90, ph = L.h - 80, xp = v => X0 + v * pw, yp = v => Y0 + ph - v / 1.02 * ph;
    let g = txt(t, X0, fr.y + 12, `Unilever, ${perS(t1.period)}: running share of revenue, top earner first (ours)`, {size:11.5, weight:600});
    [0, 0.2, 0.4, 0.6, 0.8, 1].forEach(v => { g += `<line x1="${X0}" x2="${X0 + pw}" y1="${yp(v).toFixed(1)}" y2="${yp(v).toFixed(1)}" stroke="${t.grid}"/>` + txt(t, X0 - 6, yp(v), (v * 100) + '%', {size:10, fill:t.ink3, anchor:'end', base:'middle'})
      + txt(t, xp(v), Y0 + ph + 14, (v * 100) + '%', {size:10, fill:t.ink3, anchor:'middle'}); });
    g += `<polyline points="${U.map(r => `${xp(r.rank_share).toFixed(1)},${yp(r.cumulative_share).toFixed(1)}`).join(' ')}" fill="none" stroke="${t.ours}" stroke-width="2.4"/>`;
    const a = U.filter(r => r.tier === 'A'), last = a[a.length - 1];
    g += `<line x1="${X0}" x2="${xp(last.rank_share).toFixed(1)}" y1="${yp(0.8).toFixed(1)}" y2="${yp(0.8).toFixed(1)}" stroke="${t.ink3}" stroke-dasharray="4 3"/>`
      + `<line x1="${xp(last.rank_share).toFixed(1)}" x2="${xp(last.rank_share).toFixed(1)}" y1="${yp(0.8).toFixed(1)}" y2="${(Y0 + ph).toFixed(1)}" stroke="${t.ink3}" stroke-dasharray="4 3"/>`
      + `<circle cx="${xp(last.rank_share).toFixed(1)}" cy="${yp(last.cumulative_share).toFixed(1)}" r="5" fill="${t.ours}" stroke="${t.surface}" stroke-width="2"/>`
      + txt(t, xp(last.rank_share) + 8, yp(0.8) + 22, `↑ ${nA} products = Tier A (80% of revenue)`, {size:11, weight:700});
    g += txt(t, X0 + pw / 2, Y0 + ph + 30, 'Products, from highest to lowest revenue (share of all products)', {size:10.5, fill:t.ink2, anchor:'middle'});
    g += yTitle(t, L, Y0, ph, 'Share of total revenue');
    // right: stacked bars of product counts per tier, with the count in each box
    const bx = Rt.x + 20, bw = Rt.w - 40, rows = [[`Ours: latest month — ${nU} products`, [tierN('A'), tierN('B'), tierN('C')], true], [`3-month view — ${n3} products`, [t3.A, t3.B, t3.C], false]];
    g += txt(t, bx, fr.y + 12, 'Products in each tier', {size:11.5, weight:600});
    const tot = Math.max(...rows.map(r => r[1].reduce((x, y) => x + y, 0)));
    rows.forEach(([lab, v, ours], i) => { const y = Y0 + 20 + i * 90; let x = bx;
      g += txt(t, bx, y - 8, lab, {size:11, weight: ours ? 700 : null, fill: ours ? t.ink : t.ink2});
      ['A', 'B', 'C'].forEach((tier, j) => { const w = v[j] / tot * bw, col = ours ? [t.ours, hexMix(t.ours, t.surface, 0.45), hexMix(t.ours, t.surface, 0.7)][j] : [t.alt, hexMix(t.alt, t.surface, 0.4), hexMix(t.alt, t.surface, 0.65)][j];
        const s = w > 38 ? `${tier} ${v[j]}` : w > 14 ? tier : '';
        g += `<rect x="${x.toFixed(1)}" y="${y}" width="${Math.max(w - 2, 1).toFixed(1)}" height="30" rx="3" fill="${col}"/>` + (s ? txt(t, x + w / 2, y + 16, s, {size:11, weight:700, anchor:'middle', base:'middle', fill: j === 0 ? '#ffffff' : t.ink}) : '');
        x += w; }); });
    g += txt(t, bx, Y0 + 210, `A = top 80% of revenue · B = next 15% · C = last 5%`, {size:10, fill:t.ink3});
    return {g, geo: null};
  };
  return {
    question: 'Which products bring in most of the revenue?',
    headline: `Just ${nA} of Unilever’s ${nU} products (${pctA}%) bring in 80% of revenue (${per(t1.period)}).`,
    main: {file: 'ch07_abc', title: `Revenue concentration and the resulting tiers, ${per(t1.period)} (ours vs a 3-month view)`, W: 900, H: 330,
      read: 'Left: the steep early rise means a few products carry most of the revenue. Right: how many products land in each tier with our ranking (blue) and with a 3-month view (grey).',
      shows: [`Left: Unilever’s products ranked from the top earner down; the line is the running share of revenue. It climbs steeply — the first ${nA} products (${pctA}% of all) reach 80%.`,
              'Tier A = the products that make up the top 80% of revenue; B = the next 15%; C = the last 5%.',
              `Right: products per tier. Ours (latest month, ${per(t1.period)}): A ${tierN('A')}, B ${tierN('B')}, C ${tierN('C')}. A 3-month view: A ${t3.A}, B ${t3.B}, C ${t3.C} (it covers ${n3} products, ours ${nU}).`,
              `Switching to the 3-month view would change the tier of ${changed} products (${aMoves} move into or out of Tier A).`],
      build: () => [{fr: {x: 0, y: 0, w: 900, h: 330}, draw}]},
    faq: [
      ['Why rank by the latest month and not a 3-month average?', `This card describes the difference only; no accuracy test was written for it (its result is “description only”). With the 3-month view, ${changed} products would change tier.`],
      ['Which products were the forecasts on this page tested on?', `Unilever products in Tier A as of ${per(t1.period)}.`],
      ['What about Del Monte?', `Del Monte is ranked by product category, not by product: ${DM.length} categories in its latest classified month (${per(tdm.period)}), shown under Details.`],
      ['Why 80%, 15% and 5%?', 'These are the usual ABC cut-offs: A = the top 80% of revenue, B = the next 15%, C = the last 5%.'],
    ],
    means: 'SSM can focus forecasting and ordering effort on about 1 product in 5.',
    details: [{file: 'ch07_delmonte', title: `Del Monte, ranked by category (${DM.length} categories in its latest month, ${per(tdm.period)})`, W: 900, H: 260,
      read: 'Share of Del Monte revenue by category, latest classified month.',
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 260}, draw: evGBars, o: {groups: DM.map(r => r.label), fmt: v => (v * 100).toFixed(0) + '%', ytitle: 'Share of revenue',
        series: [{vals: DM.map(r => r.revenue_share), color: t.mag, labels: DM.map(r => pc(r.revenue_share, 1)), sub: DM.map(r => 'Tier ' + r.tier)}]}}]}],
    detailsHTML: `<p class="evcap">Unilever, latest month (ours, ${per(t1.period)}): A ${tierN('A')} products → ${pc(share('A'), 1)} of revenue; B ${tierN('B')} → ${pc(share('B'), 1)}; C ${tierN('C')} → ${pc(share('C'), 1)}. `
      + `3-month view: A ${t3.A}, B ${t3.B}, C ${t3.C}. Between the two, ${changed} products change tier (${aMoves} move into or out of Tier A).</p>`,
  };
};

CARDS[8] = c => {
  // The default allocation is now 103% (SSM's guaranteed minimum). The stored results were computed when 105% was the
  // placeholder default; they are shown unchanged, and 103% was one of the three levels measured.
  const OURS = 103, RUN_DEFAULT = 105;
  const A = evRecs(c.data.totals), r103 = A.find(q => q.allocation_pct === OURS) || {}, r105 = A.find(q => q.allocation_pct === RUN_DEFAULT) || {};
  const levels = A.map(r => r.allocation_pct + '%'), ours = gi => A[gi].allocation_pct === OURS;
  const cents = r => r.cover_gap_php != null && r.cover_gap_php < 0 ? (-r.cover_gap_php).toFixed(2) : null;
  const gap = cents(r105), gap103 = cents(r103), kept = r => !!r.run_lp_says_met;
  const r108 = A.find(q => q.allocation_pct === 108);
  const tag = r => r.allocation_pct === OURS ? ' (ours: new default)' : r.allocation_pct === RUN_DEFAULT ? ' (placeholder default when this was run)' : '';
  BOARD[8] = ['103% of last year’s sales (new default: SSM’s guaranteed minimum)', '105% (placeholder default when this was run) and 108%',
              `At 103%, ${r103.n_short} products run short (${nf(r103.shortfall)} units)${kept(r103) ? '; the 3-week stock rule is kept' : ''}. More allocation = fewer shortages.`];
  return {
    question: 'How much does the supplier allocation limit what we can order?',
    headline: `At our new default (103%), ${r103.n_short} products run short by ${nf(r103.shortfall)} units in total; the 3-week stock rule is ${kept(r103) ? 'kept' : 'not kept'}.`,
    main: {file: 'ch08_allocation', title: 'Units needed vs units we could order, at each allocation level', W: 900, H: 355,
      read: `Each group = an allocation level. Light bar = what the products need; solid bar = what the allocation lets us order; the gap = shortage. Blue = ours (103%, the new default). Computed when 105% was the placeholder default. The rest of the order plan ${PLACEHOLDER}.`,
      shows: ['Each group = one allocation level: the most the supplier lets us buy, as a share of last year’s sales for the same months.',
              `Light outlined bar = the units the ${A[0].products} products need; solid bar = what the allocation lets us order. The gap is the shortage.`,
              A.map(r => `${r.allocation_pct}%${tag(r)}: ${r.n_short} products short, ${nf(r.shortfall)} units`).join('; ') + '.',
              'The 3-week stock rule is kept at every level (see the note below the chart).'],
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 355}, draw: evGBars, o: {groups: levels, ytitle: 'Units', fmt: v => nf(v / 1e6, 1) + 'M',
        gsub: A.map(r => r.allocation_pct === OURS ? 'Ours (new default:\nSSM’s guaranteed minimum)' : r.allocation_pct === RUN_DEFAULT ? 'placeholder default\nwhen this was run' : ''),
        gsubInkAt: gi => ours(gi) ? null : t.ink3,
        boldGroup: ours, legend: [[t.need, 'Needed', true], [t.ours, 'Could order: ours (103%)'], [t.alt, 'Could order: other levels']],
        series: [{vals: A.map(r => r.need), colorAt: () => t.need, outline: true}, {vals: A.map(r => r.ordered), colorAt: gi => oursAlt(t, ours(gi))}],
        gnote: A.map(r => `short: ${rk(r.shortfall)} units`),
        tip: k => { const r = A[levels.indexOf(k)]; return `<div class="h">allocation ${r.allocation_pct}% of last year’s sales${esc(tag(r))}</div>`
          + `<div class="r"><span>needed</span><b>${nf(r.need)}</b></div><div class="r"><span>could order</span><b>${nf(r.ordered)}</b></div>`
          + `<div class="r"><span>short</span><b>${nf(r.shortfall)} units, ${r.n_short} products</b></div>`; }}}]},
    after: ['The 3-week stock rule is kept at every level. (The stored test flags 105% — the default when it ran — because it falls ₱0.02 short of 3 weeks, a rounding gap within the order plan’s own ₱1 tolerance.'
            + (gap103 ? ` At 103% the stored month-end stock is also ₱${gap103} short: the same rounding gap.)` : ')')],
    faq: [
      ['What is the supplier allocation?', `The most the supplier lets us buy: last year’s sales for the same months × 103%, 105% or 108%. Our new default is 103%, SSM’s guaranteed minimum. The rest of the order plan ${PLACEHOLDER}.`],
      ['Was the chart re-run at the new default?', 'No. It keeps the stored results, computed when 105% was the placeholder default. 103% was one of the three levels measured in that run, so its figures are measured, not estimated.'],
      ['Which products get cut when there isn’t enough?', `The order plan decides, using the weights for cost, service and storage (decision 9). The ${r103.n_short} products short at 103% are listed under Details.`],
      ['Why is this card “technically questioned”?', gap ? `The rule written down beforehand tests the default at the time, 105%: the plan must end the month with 3 weeks of stock. At 105% it ends ₱${gap} short of that — a rounding gap, well inside the order plan’s own ₱1 tolerance.`
        + (gap103 ? ` At 103% it is ₱${gap103} short too.` : '') + ' We report it exactly as the rule says.'
        : 'See the stored verdict under Details.'],
    ],
    means: `At our new default (103%, SSM’s guaranteed minimum), ${r103.n_short} products run short by ${nf(r103.shortfall)} units, and the 3-week stock rule is ${kept(r103) ? 'kept' : 'not kept'}.`
      + (r108 ? ` A higher allocation cuts shortages (${r108.n_short} products at 108%).` : ''),
    details: [],
    detailsHTML: `<p class="evcap"><b>Default changed after this was computed:</b> the stored results and the pre-registered test use 105%, the placeholder default at the time; the default is now 103% (SSM’s guaranteed minimum). The chart data are unchanged.</p>`
      + `<p class="evcap"><b>Products short at 103% (${r103.n_short}):</b> ${esc(String(r103.short_skus || '').split(';').join(', '))}.</p>`,
  };
};

CARDS[9] = c => {
  const G = evRecs(c.data.grid), d0 = G.find(g => g.is_default) || {};
  const diff = G.filter(g => g.cut_set_differs), onlyExtremes = diff.every(g => g.w1 <= 0.1 + 1e-9 || g.w2 < 1e-9);
  const sameShort = new Set(G.map(g => Math.round(g.shortfall))).size === 1;
  const nb = G.filter(g => g.neighbour && !g.is_default), nbDiff = nb.filter(g => g.cut_set_differs).length;
  const costCut = diff.filter(g => g.w2 > 1e-9).length ? Math.max(...diff.filter(g => g.w2 > 1e-9).map(g => g.w1)) : null;
  const c8 = EV.charts.find(x => x.chart === 8), a8 = c8 ? evRecs(c8.data.totals) : [], lowest = a8.length ? Math.min(...a8.map(r => r.allocation_pct)) : null;
  const atLowest = lowest != null && (a8.find(r => r.allocation_pct === lowest) || {}).n_short === d0.n_short;
  BOARD[9] = ['Cost 0.45, service 0.35, storage 0.20', `${G.length - 1} other mixes of the three weights`, 'SSM can set these priorities roughly; the same products get cut unless one priority is switched off.'];
  const draw = (t, fr) => {
    const M = {l: 70, r: 300, t: 20, b: 44}, side = Math.min(fr.w - M.l - M.r, fr.h - M.t - M.b), X0 = fr.x + M.l, Y0 = fr.y + M.t, n = 21, cs = side / n;
    const cx = w1 => X0 + Math.round(w1 / 0.05) * cs, cy = w2 => Y0 + side - (Math.round(w2 / 0.05) + 1) * cs;
    let g = '';
    G.forEach(r => { const x = cx(r.w1), y = cy(r.w2);
      g += `<rect x="${(x + 1).toFixed(1)}" y="${(y + 1).toFixed(1)}" width="${(cs - 2).toFixed(1)}" height="${(cs - 2).toFixed(1)}" rx="2" fill="${r.cut_set_differs ? t.red : t.alt}"`
        + (r.neighbour ? ` stroke="${t.ink}" stroke-width="1.2"` : '') + `/>`; });
    g += `<rect x="${(cx(d0.w1) + 1).toFixed(1)}" y="${(cy(d0.w2) + 1).toFixed(1)}" width="${(cs - 2).toFixed(1)}" height="${(cs - 2).toFixed(1)}" rx="2" fill="${t.ours}"/>`
      + `<circle cx="${(cx(d0.w1) + cs / 2).toFixed(1)}" cy="${(cy(d0.w2) + cs / 2).toFixed(1)}" r="${(cs * 0.75).toFixed(1)}" fill="none" stroke="${t.ours}" stroke-width="2.5"/>`
      + `<rect x="${(cx(d0.w1) + cs * 1.45).toFixed(1)}" y="${(cy(d0.w2) - 2).toFixed(1)}" width="40" height="${(cs + 4).toFixed(1)}" rx="4" fill="${t.surface}" stroke="${t.ours}"/>`
      + txt(t, cx(d0.w1) + cs * 1.45 + 20, cy(d0.w2) + cs / 2, 'Ours', {size:12, weight:700, base:'middle', anchor:'middle'});
    g += txt(t, X0 + side / 2, Y0 + side + 16, '← service ignored (bottom row)', {size:10.5, fill:t.red, anchor:'middle'});
    g += `<text transform="translate(${(X0 - 22).toFixed(1)},${(Y0 + side / 2).toFixed(1)}) rotate(-90)" text-anchor="middle" font-size="10.5" fill="${t.red}" font-family="${EVFONT}">cost nearly ignored (left columns)</text>`;
    g += txt(t, X0 + side / 2, Y0 + side + 34, 'Weight on cost →', {size:10.5, fill:t.ink2, anchor:'middle'});
    g += `<text transform="translate(${fr.x + 12},${(Y0 + side / 2).toFixed(1)}) rotate(-90)" text-anchor="middle" font-size="10.5" fill="${t.ink2}" font-family="${EVFONT}">Weight on service →</text>`;
    const lx = X0 + side + 28; let ly = Y0 + 10;
    [[t.ours, 'Ours'], [t.alt, 'Other mix: same products cut as ours'], [t.red, 'Other mix: different products cut']].forEach(([cl, s]) => { g += `<rect x="${lx}" y="${ly - 6}" width="12" height="12" rx="2" fill="${cl}"/>` + txt(t, lx + 18, ly, s, {size:10.5, base:'middle'}); ly += 20; });
    g += `<rect x="${lx}" y="${ly - 6}" width="12" height="12" rx="2" fill="none" stroke="${t.ink}" stroke-width="1.2"/>` + txt(t, lx + 18, ly, 'Small change from ours (±0.10)', {size:10.5, base:'middle'}); ly += 30;
    g += txt(t, lx, ly, 'Storage gets whatever is left,', {size:10.5, fill:t.ink2}) + txt(t, lx, ly + 15, 'so only half the square is possible.', {size:10.5, fill:t.ink2});
    const geo = {X0, Y0, pw: side, ph: side, pick: (mx, my) => { const i = Math.floor((mx - X0) / cs), j = n - 1 - Math.floor((my - Y0) / cs);
        return G.find(r => Math.round(r.w1 / 0.05) === i && Math.round(r.w2 / 0.05) === j) || null; },
      tip: r => `<div class="h">cost ${r.w1} · service ${r.w2} · storage ${r.w3}${r.is_default ? ' (ours)' : ''}</div>`
        + `<div class="r"><span>products cut short</span><b>${r.n_short}</b></div><div class="r"><span>same products as ours?</span><b>${r.cut_set_differs ? 'no' : 'yes'}</b></div>`};
    return {g, geo};
  };
  return {
    question: 'Does it matter exactly how we weigh cost, service and storage?',
    before: ['Cost = cut expensive items first; service = protect the items that bring in the most revenue; storage = the cost of holding stock (one team estimate for every product for now, so it changes little).'],
    headline: c.verdict === 'CONFIRMS' && onlyExtremes ? `Weights barely matter: the same ${d0.n_short} products are cut unless cost or service is nearly ignored.`
      : c.verdict === 'CONFIRMS' ? "Small changes to the weights don't change which products get cut." : "Small changes to the weights change which products get cut.",
    main: {file: 'ch09_weights', title: `Every mix of the three weights (steps of 0.05)${lowest != null && atLowest ? `, at the lowest allocation (${lowest}%)` : ''}: are the same products cut as with ours?`, W: 900, H: 480,
      read: 'Each square = one mix. Across = weight on cost; up = weight on service. Grey = same products cut as ours; red = different ones.',
      shows: ['Each square = one way to weigh cost, service and storage',
              `Grey = cuts the same ${d0.n_short} products as ours`,
              onlyExtremes ? 'Red appears only when cost or service is almost ignored' : 'Red also appears away from the edges',
              onlyExtremes ? 'So the exact weights don’t matter much' : 'So the exact weights can matter'],
      build: () => [{fr: {x: 0, y: 0, w: 900, h: 480}, draw}]},
    after: [sameShort ? `Total shortfall is ${rk(G[0].shortfall)} units everywhere; only which products are short changes.` : ''].filter(Boolean),
    faq: [
      ['What if SSM wants to lean more on service, or on cost?', `Every mix within 0.10 of ours on each weight cuts the same ${d0.n_short} products (${nb.length - nbDiff} of the ${nb.length} nearby mixes).`
        + (onlyExtremes && costCut != null ? ` Different products are cut only when cost gets ${costCut.toFixed(2)} or less, or service gets 0.` : '')],
      ['Does the total shortage change?', sameShort ? `No: ${rk(G[0].shortfall)} units short in every mix; only which products are short changes.` : 'Yes; see the tooltip on each square.'],
      ['Why is only half the square filled?', 'The three weights add up to 1, and storage gets whatever cost and service leave, so cost + service can’t be more than 1.'],
      lowest != null && atLowest ? [`Why test at ${lowest}%?`, `It is the lowest allocation tested, where the most products are cut (${d0.n_short} of ${d0.n_short != null && a8[0] ? a8[0].products : '—'}).`] : null,
    ].filter(Boolean),
    means: 'SSM can set these priorities roughly; the same products get cut unless one priority is switched off.',
    details: [],
  };
};

CARDS[10] = c => {
  const T = evRecs(c.data.curve), xs = T.map(r => Math.round(r.service_level * 100)), at = x => T[xs.indexOf(x)];
  const show = [85, 90, 95, 99].filter(x => xs.includes(x)), meas = c.measured_rate;
  const over = show.filter(x => at(x).measured_exceedance > at(x).nominal_exceedance);
  const hm = String(c.caption || '').match(/\((\d+) of the products, (\d+) SKU-months, (\d{4}-\d{2})\.\.(\d{4}-\d{2})/);
  const ml = m => MONL[+m.slice(5, 7) - 1] + ' ' + m.slice(0, 4);
  const s90 = at(90).total_safety_stock_pieces, s95 = at(95) ? at(95).total_safety_stock_pieces : null;
  BOARD[10] = ['90% service level', '85% to 99%', 'The 90% buffer does its job; going higher ties up much more stock.'];
  return {
    question: 'How much extra stock should we keep for surprises?',
    headline: c.verdict === 'CONFIRMS' ? `Our 90% buffer works: stockouts happened in ${Math.round(meas * 100)}% of months, within the promised 10%.`
      : 'Stockouts happen more often than the promised service level allows.',
    main: {file: 'ch10_service', title: 'How often demand ran past forecast + buffer, at each service level (lower is better)', W: 900, H: 340,
      read: 'Bar = measured on past months; thick dashed mark = what the service level promises. Blue = ours (90%). Bars below their mark = the buffer does its job.',
      shows: ['Each group = one service level: the share of months we aim to have enough stock. 90% = run out in at most 1 month in 10.',
              'Bar = how often demand actually ran past the forecast plus the buffer on past months; dashed mark = the promised maximum.',
              `Ours (90%): ${pc(meas)} of months, under the promised 10%. ` + (over.length ? `At ${listWords(over.map(x => x + '%'))} the measured rate (${listWords(over.map(x => pc(at(x).measured_exceedance)))}) is slightly above its promise; the other levels shown are below theirs.` : 'Every level shown is below its promise.'),
              `More service needs more safety stock: ${listWords(show.map((x, i) => `${rk(at(x).total_safety_stock_pieces)}${i ? '' : ' units'} at ${x}%`))}.`],
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 340}, draw: evGBars, o: {groups: show.map(x => x + '% service' + (x === 90 ? ' (ours)' : '')), ytitle: 'Months out of stock', fmt: v => (v * 100).toFixed(0) + '%',
        boldGroup: gi => show[gi] === 90, top: 1.3, legend: [[t.ours, 'Measured (ours)'], [t.alt, 'Measured (other levels)'], [t.ink, 'Promised maximum (dashed mark)', true]],
        series: [{vals: show.map(x => at(x).measured_exceedance), colorAt: gi => oursAlt(t, show[gi] === 90)}],
        marks: show.map((x, gi) => ({gi, si: 0, y: at(x).nominal_exceedance, dash: '6 3'})),
        tip: k => { const x = show[show.findIndex(q => k.startsWith(q + '%'))], r = at(x); return `<div class="h">${x}% service level</div>`
          + `<div class="r"><span>measured stockout rate</span><b>${pc(r.measured_exceedance)}</b></div><div class="r"><span>promised at most</span><b>${pc(r.nominal_exceedance)}</b></div>`
          + `<div class="r"><span>safety stock held</span><b>${nf(r.total_safety_stock_pieces)} units</b></div>`; }}}]},
    after: [`Promised: out of stock at most 1 month in 10. Actual: ${pc(meas)} of months. Higher levels cut stockouts further but need much more stock (table in Details). The order plan ${PLACEHOLDER}.`],
    faq: [
      ['What does a 90% service level mean?', 'Enough extra stock that demand should run past the forecast plus the buffer in at most 1 month in 10.'],
      s95 != null ? ['Why not 95%?', `It would hold about ${Math.round((s95 / s90 - 1) * 100)}% more safety stock (${rk(s95)} vs ${rk(s90)} units) to cut stockouts from ${pc(meas, 0)} to ${pc(at(95).measured_exceedance, 0)} of months. That trade-off is SSM’s call; this card only shows it.`] : null,
      ['How was it measured?', hm ? `On past months (${ml(hm[3])} – ${ml(hm[4])}, ${nf(+hm[2])} product-months for ${hm[1]} products): how often actual sales went above the forecast plus the buffer.`
        : 'On past months: how often actual sales went above the forecast plus the buffer.'],
      ['Are these real stock numbers?', `Not fully: the buffer depends on the lead time and review days, and the order plan ${PLACEHOLDER}.`],
    ].filter(Boolean),
    means: 'The 90% buffer does its job; going higher would tie up much more stock for fewer stockouts.',
    details: [{file: 'ch10_estimate', title: 'Formula estimate (not a measurement): product-months with a stockout per year', W: 900, H: 280,
      read: 'From the normal-demand formula the order plan assumes; an estimate, not measured.',
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 280}, o: {xs, xticks: [85, 90, 95, 99], xlab: v => v + '%', vrules: [{x: 90, label: 'ours (90%)'}], y: {fmt: v => nf(v), zero: true, title: 'Stockout months / year'},
        series: [{key: 'e', label: 'estimate', color: t.alt, pts: xs.map(v => [v, at(v).model_stockout_sku_months_per_year])}]}}]}],
    detailsHTML: `<table class="evtable"><thead><tr><th>Service level</th><th>Safety stock held (units)</th><th>Measured stockout rate</th><th>Promised at most</th></tr></thead><tbody>`
      + show.map(x => { const r = at(x); return `<tr><td>${x}%${x === 90 ? ' (ours)' : ''}</td><td>${nf(r.total_safety_stock_pieces)}</td><td>${pc(r.measured_exceedance)}</td><td>${pc(r.nominal_exceedance)}</td></tr>`; }).join('') + `</tbody></table>`,
  };
};

CARDS[11] = c => {
  const I = evRecs(c.data.index), P = evRecs(c.data.pairs);
  const tot = p => I.filter(r => r.principal === p && r.series === 'total');
  const years = p => [...new Set(tot(p).map(r => r.year))].sort();
  const val = (p, y, m) => (tot(p).find(r => r.year === y && r.moy === m) || {}).index;
  const full = p => years(p).filter(y => tot(p).filter(r => r.year === y).length === 12);
  const fy = full('unilever');
  const steady = [...Array(12).keys()].map(i => i + 1).map(m => { const v = fy.map(y => Math.round(val('unilever', y, m) * 100 - 100));
    return v.length >= 2 && v.every(x => x !== 0) && (v.every(x => x > 0) || v.every(x => x < 0)) ? [m, v[0] > 0 ? 'high' : 'low'] : null; }).filter(Boolean);
  const dmYears = years('delmonte').filter(y => val('delmonte', y, 11) != null && val('delmonte', y, 12) != null);
  const dmNovDecHigh = dmYears.length >= 2 && dmYears.every(y => val('delmonte', y, 11) > 1 && val('delmonte', y, 12) > 1);
  const orderSize = (y, ms) => { const R = tot('delmonte').filter(r => r.year === y && ms.includes(r.moy)); return R.reduce((a, r) => a + r.net_amount, 0) / R.reduce((a, r) => a + r.rows, 0); };
  const ratio = dmYears.map(y => orderSize(y, [11, 12]) / orderSize(y, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]));
  const pang = (() => { const b = I.filter(r => r.series === 'branch pangasinan (2023 only)' && [11, 12].includes(r.moy)), tt = tot('delmonte').filter(r => r.year === 2023 && [11, 12].includes(r.moy));
    return tt.length && b.length ? b.reduce((a, r) => a + r.net_amount, 0) / tt.reduce((a, r) => a + r.net_amount, 0) : null; })();
  const highs = steady.filter(s => s[1] === 'high').map(s => MONL[s[0] - 1]), lows = steady.filter(s => s[1] === 'low').map(s => MONL[s[0] - 1]);
  const UP = P.filter(p => p.principal === 'unilever'), matched = UP.filter(p => p.positive_significant === true);
  const dmMonths = years('delmonte').map(y => `${tot('delmonte').filter(r => r.year === y).length} months of ${y}`);
  BOARD[11] = ['No seasonal adjustment in the forecasts', 'A month-by-month pattern repeating across years', 'Plan without a seasonal adjustment for now; re-check when full years of Del Monte data arrive.'];
  const heat = (t, fr) => {
    let g = ''; const panels = [['unilever', 'Unilever'], ['delmonte', 'Del Monte']], cw = (fr.w - 150) / 12, rh = 30;
    let y0 = fr.y + 26;
    g += txt(t, fr.x + 110, fr.y + 10, 'Each month vs that year’s normal month (blue = higher, red = lower; grey = no data)', {size:11, fill:t.ink2});
    MON.forEach((m, i) => { g += txt(t, fr.x + 110 + (i + 0.5) * cw, y0 + 4, m, {size:10, fill:t.ink3, anchor:'middle'}); });
    y0 += 12;
    panels.forEach(([p, lab]) => {
      g += txt(t, fr.x + 4, y0 + 12, lab, {size:12, weight:700});
      years(p).forEach((y, ri) => { const yy = y0 + 20 + ri * rh, n = tot(p).filter(r => r.year === y).length;
        g += txt(t, fr.x + 104, yy + rh / 2 - 2, `${y}${n < 12 ? ` (${n} of 12 mo)` : ''}`, {size:10.5, fill: n < 12 ? t.ink3 : t.ink2, anchor:'end', base:'middle'});
        for (let m = 1; m <= 12; m++){ const v = val(p, y, m), x = fr.x + 110 + (m - 1) * cw;
          if (v == null){ g += `<rect x="${(x + 1).toFixed(1)}" y="${yy}" width="${(cw - 2).toFixed(1)}" height="${rh - 4}" rx="3" fill="none" stroke="${t.axis}" stroke-dasharray="2 2"/>`; continue; }
          const d = v - 1, f = Math.min(Math.abs(d) / 0.4, 1), col = hexMix(t.neutral, d >= 0 ? t.pos : t.neg, 0.25 + 0.75 * f), fade = n < 12 ? ' fill-opacity="0.55"' : '';
          g += `<rect x="${(x + 1).toFixed(1)}" y="${yy}" width="${(cw - 2).toFixed(1)}" height="${rh - 4}" rx="3" fill="${col}"${fade}/>`
            + txt(t, x + cw / 2, yy + (rh - 4) / 2 + 1, sgn(d * 100), {size:10, anchor:'middle', base:'middle', fill: f > 0.55 ? '#ffffff' : t.ink}); } });
      y0 += 20 + years(p).length * rh + 18; });
    const geo = {X0: fr.x + 110, Y0: fr.y + 38, pw: fr.w - 150, ph: y0 - fr.y - 38, pick: () => null};
    return {g, geo};
  };
  const dmSent = dmNovDecHigh ? `Del Monte: November–December high in both years we have — too little data to call it seasonal.` : `Del Monte: too little data to call anything seasonal.`;
  const ulSent = /NOT TESTABLE|no flag|CONFIRMS/.test(c.verdict) ? `Unilever: a few months lean the same way each year${lows.length ? ` (e.g. ${lows.slice(0, 2).join(' and ')} low)` : ''}, but the full pattern does not repeat reliably.` : '';
  return {
    question: 'Do sales go up or down in the same months every year?',
    headline: /CAVEAT/.test(c.verdict) ? 'Sales repeat the same yearly pattern overall; the paper should mention it.'
      : 'Unilever’s yearly pattern doesn’t repeat reliably; Del Monte has too little data to tell.',
    main: {file: 'ch11_season', title: 'Ours: no seasonal adjustment. Does any month repeat high or low every year?', W: 900, H: 330,
      read: 'Each row = one year; each cell = how that month compared with the year’s normal month (“+11%” = 11% above). A real season shows the same colour in the same column every year. Faded rows = incomplete years.',
      shows: ['Each row = one year; each cell = that month vs the year’s normal month (“+11%” = 11% above).',
              'A real season would show the same colour in the same column every year.',
              `Unilever: ${steady.length ? `${steady.length} of 12 months (${steady.map(s => MONL[s[0] - 1]).join(', ')}) lean the same way in all ${fy.length} full years` : 'no month leans the same way in every full year'}, but the whole-year shape matched in only ${matched.length} of ${UP.length} pairs of years${matched.length ? ` (${listWords(matched.map(p => p.years.replace('-', '–')))})` : ''}.`,
              `Del Monte: ${listWords(dmMonths)} — no two full years to compare.`],
      build: () => [{fr: {x: 0, y: 0, w: 900, h: 330}, draw: heat}]},
    after: [ulSent + ' ' + dmSent, `Our choice: no seasonal adjustment. Unilever months that lean the same way in all full years: ${highs.length ? 'higher — ' + listWords(highs) : 'none higher'}; ${lows.length ? 'lower — ' + listWords(lows) : 'none lower'}. Our test needs the whole year’s shape to match between every pair of years, and it does not.`],
    faq: [
      ['How was it tested?', 'For every pair of full years we checked whether the 12-month shape matches (a rank correlation). A seasonal pattern needs a clear match in every pair.'],
      matched.length ? [`${listWords(matched.map(p => p.years.replace('-', '–')))} match — isn’t that seasonal?`, `Only ${matched.length} of ${UP.length} pairs matched; ${listWords(UP.filter(p => !p.positive_significant).map(p => p.years.replace('-', '–')))} did not. A match in one pair only could be chance.`] : null,
      ['Why can’t Del Monte be tested yet?', `Its data has ${listWords(dmMonths)}, so there are no two full years to compare.`],
      dmNovDecHigh ? ['What about Del Monte’s high November–December?', `An observation only: the average invoice in those months was ${ratio.map((r, i) => `${r.toFixed(1)}× the rest of ${dmYears[i]}`).join(' and ')}. Whether these were promotional orders is not in the stored results.`] : null,
      ['What would change the decision?', 'A re-check once Del Monte has at least two full years of data.'],
    ].filter(Boolean),
    means: 'Plan orders without a seasonal adjustment for now; re-check once full years of Del Monte data arrive.',
    details: [{file: 'ch11_branch', title: 'Del Monte by branch, 2023 (the only year with a branch field)', W: 900, H: 280,
      read: 'Each month vs 2023’s normal month, per branch.',
      build: t => [{fr: {x: 0, y: 0, w: 900, h: 280}, o: {xs: [...Array(12).keys()].map(i => i + 1), xlab: m => MON[m - 1], hrules: [{y: 1, label: 'normal month'}], y: {fmt: v => sgn((v - 1) * 100), title: 'vs normal month'},
        series: [['branch pangasinan (2023 only)', 'Pangasinan', 'blue'], ['branch ilocos (2023 only)', 'Ilocos', 'mag']].map(([s, lab, col]) => { const R = I.filter(r => r.series === s);
          return {key: s, label: lab, color: t[col], width: 2, r: 3, pts: [...Array(12).keys()].map(i => [i + 1, (R.find(r => r.moy === i + 1) || {}).index ?? null])}; })}}]}],
    detailsHTML: `<p class="evcap">Del Monte November–December: the average invoice was ${ratio.map((r, i) => `${r.toFixed(1)}× the rest of ${dmYears[i]}`).join(' and ')} (from stored monthly totals and invoice counts)`
      + (pang != null ? `; in 2023 the Pangasinan branch was ${pc(pang, 0)} of Nov–Dec sales (2024–25 rows carry towns, not branches)` : '')
      + `. Whether these were promotional orders: not available from stored results.</p>`,
  };
};

CARDS[12] = c => {
  BOARD[12] = ['— (not built yet)', '—', 'Will show where real, placeholder and missing data sit, once the coverage table is live.'];
  return {question: 'Where do we have real data, placeholder data, or none?', headline: 'Not built yet: it waits for the data-coverage table to reach the live database.', main: null, means: 'Nothing to act on yet.', details: []};
};

// ---- page ----------------------------------------------------------------------------------
function evDetailsBlock(c, spec){
  const checks = (c.checks || []).map(k => `<li><span class="${k.pass ? 'evok' : 'evno'}">${k.pass ? '✓' : '✗'} ${esc(k.id)}</span> ${esc(k.detail)}</li>`).join('');
  const amends = (c.amendments || []).map(a => `<div class="evamend"><b>Amended ${esc(a.date)} (${esc(a.item)}, ${esc(a.approved_by)}):</b> ${esc(a.amended)} <span class="muted">— ${esc(a.reason)}</span></div>`).join('');
  const files = Object.values(c.files || {}).map(f => `<code>${esc(f)}</code>`).join(' ');
  return `<details class="evdetails"><summary>Details (for the paper)</summary>`
    + (spec.details || []).map((f, i) => evFigHTML(c, f, 'd' + i)).join('')
    + (spec.detailsHTML || '')
    + `<div class="evcrit"><b>Pre-registered — flawed if:</b> ${esc(c.criterion)} <span class="muted">Otherwise: ${esc(c.otherwise)}. Stored verdict: <b>${esc(c.verdict)}</b>.</span></div>`
    + (c.verdict_detail ? `<div class="evdetail">${esc(c.verdict_detail)}</div>` : '')
    + (c.caption ? `<p class="evcap"><b>Caption.</b> ${esc(c.caption)} <button class="evbtn evcopy" data-c="${c.chart}">Copy caption</button></p>` : '')
    + amends + (checks ? `<ul class="evlist checks">${checks}</ul>` : '')
    + ((c.data_notes || []).length ? `<ul class="evlist">${c.data_notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>` : '')
    + `<div class="evprov"><span>MASE gate used: <b>${esc(c.mase_gate_used)}</b></span><span>Re-run after 5f: <b>${esc(c.rerun_after_5f)}</b></span>`
    + (c.script ? `<span>Script <code>${esc(c.script)}</code> @ <code>${esc(c.code_commit)}</code>, ${esc(c.computed_at)}</span>` : '')
    + (c.caption_restamped_by ? `<span>Caption restamped by <code>${esc(c.caption_restamped_by)}</code></span>` : '')
    + (files ? `<span>Data ${files}</span>` : '') + `</div></details>`;
}
function evFigHTML(c, f, key){
  return `<figure class="evfig${key === 'm' ? ' evmain' : ''}"><div class="evfhead"><span class="evftitle">${esc(f.title)}</span>`
    + (f.toggle ? `<span class="evtog">${f.toggle.options.map(([v, l]) => `<button class="evbtn evtogb${String(v) === String(f.toggle.get()) ? ' on' : ''}" data-c="${c.chart}" data-f="${key}" data-v="${v}">${esc(l)}</button>`).join('')}</span>` : '')
    + (f.control ? `<select class="evsel" data-c="${c.chart}" data-f="${key}">${f.control.options.map(([v, l]) => `<option value="${v}"${v === f.control.get() ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>` : '')
    + `<span class="evbtns"><button class="evbtn" data-c="${c.chart}" data-f="${key}" data-k="svg">SVG</button><button class="evbtn" data-c="${c.chart}" data-f="${key}" data-k="png">PNG</button></span></div>`
    + (f.read ? `<div class="evread"><b>How to read this:</b> ${esc(f.read)}</div>` : '')
    + `<div class="evsvg" id="evs-${c.chart}-${key}"></div>`
    + ((f.shows || []).length ? `<div class="evshows"><b>What the chart shows</b><ul>${f.shows.map(b => `<li>${esc(b)}</li>`).join('')}</ul></div>` : '')
    + `</figure>`;
}
function evRefresh(c, key){
  const f = c._figs[key]; evRender($(`#evs-${c.chart}-${key}`), f);
  const sel = document.querySelector(`.evsel[data-c="${c.chart}"][data-f="${key}"]`); if (sel && f.control) sel.value = String(f.control.get());
  document.querySelectorAll(`.evtogb[data-c="${c.chart}"][data-f="${key}"]`).forEach(b => b.classList.toggle('on', b.dataset.v === String(f.toggle.get())));
}
function evCard(c){
  const spec = CARDS[c.chart] ? CARDS[c.chart](c) : {question: '', headline: c.title, main: null, details: []};
  c._spec = spec; c._figs = {m: spec.main}; if (spec.example) c._figs.x = spec.example;
  (spec.details || []).forEach((f, i) => { c._figs['d' + i] = f; });
  const lines = (arr, cls) => (arr || []).map(s => `<p class="${cls}">${spec.afterHTML && cls === 'evafter' ? s : esc(s)}</p>`).join('');
  return `<article class="evcard evslide" id="ev-${c.chart}"><div class="evhead"><span class="evnum">Decision ${c.chart}</span>${evChip(c)}</div>`
    + `<p class="evq"><b>The question:</b> ${esc(spec.question)}</p>`
    + `<h3 class="evheadline">${esc(spec.headline)}</h3>`
    + lines(spec.before, 'evbefore')
    + (spec.main ? evFigHTML(c, spec.main, 'm') : '')
    + lines(spec.after, 'evafter')
    + (spec.example ? evFigHTML(c, spec.example, 'x') : '')
    + ((spec.faq || []).length ? `<div class="evfaq"><div class="evfaqh">Questions a first-time reader asks</div><dl>${spec.faq.map(([q, a]) => `<dt>${esc(q)}</dt><dd>${esc(a)}</dd>`).join('')}</dl></div>` : '')
    + `<p class="evmeans"><b>What this means for SSM:</b> ${esc(spec.means || '')}</p>`
    + (c.verdict === 'NOT BUILT' ? '' : evDetailsBlock(c, spec)) + `</article>`;
}
function lpBox(){
  const c8 = EV.charts.find(c => c.chart === 8), n = c8 ? (evRecs(c8.data.totals)[0] || {}).products : null;
  return `<section class="card evlpbox evslide" id="ev-lp"><h3 class="evheadline">What the order plan (LP) does</h3><ol class="evlp">`
    + `<li>For each of the ${n ?? 'planned'} products it works out the <b>need</b>: next month’s forecast + the stock it should end the month with (including a safety buffer) − stock already on hand.</li>`
    + `<li>It respects three limits: the <b>supplier allocation</b> (last year’s sales × 103–108%), <b>warehouse space</b>, and SSM’s rule of keeping <b>3 weeks of sales</b> in stock.</li>`
    + `<li>If the allocation is smaller than the total need, some products get less — the plan decides which, using the <b>weights</b> (decision 9).</li></ol>`
    + `<p class="evbefore">Like a store that only lets you buy 95 kg when your family needs 100 kg: you keep 3 weeks of food in the pantry and decide which items get cut.</p>`
    + `<p class="evbefore">The plan ${PLACEHOLDER} (allocation %, lead time, costs, warehouse size).</p></section>`;
}
function boardTable(C){
  const res = c => evChip(c);
  return `<section class="card evboard evslide" id="ev-board"><h3 class="evheadline">Board summary</h3><table class="evsum evboardtbl"><thead><tr><th>Decision</th><th>What we chose</th><th>What we compared it against</th><th>Result</th><th>What it means for SSM</th></tr></thead><tbody>`
    + C.map(c => { const b = BOARD[c.chart] || ['', '', '']; return `<tr><td><a href="#ev-${c.chart}">${c.chart}. ${esc(c._spec.question)}</a></td><td>${esc(b[0])}</td><td>${esc(b[1])}</td><td>${res(c)}</td><td>${esc(b[2])}</td></tr>`; }).join('')
    + `</tbody></table></section>`;
}
function drawEvidence(){
  if (evOnce.drawn) return;
  evOnce.drawn = true;
  const C = EV.charts;
  const cards = C.map(c => ({c, html: evCard(c)}));      // builds specs and BOARD rows first
  const intro = `<div class="card evintro"><div class="evintrohead"><h2>Evidence: is each decision backed by the data?</h2>`
    + `<button class="evbtn evpbtn" id="evPresent">▶ Presentation view</button></div>`
    + `<p class="evlead">Each card tests one decision we made. The pass/fail rule for every test was written down <b>before</b> the result was computed, and results are shown as they came out — including the one that is questioned. `
    + `Read a card top to bottom: <b>the question</b>, <b>the answer</b>, one chart comparing our choice (blue, “Ours”) with the alternatives (grey), and <b>what it means for SSM</b>. Exact figures are under <b>Details (for the paper)</b>.</p>`
    + (EV.uncommitted.length ? `<p class="evno">Computed from uncommitted code: charts ${EV.uncommitted.join(', ')}.</p>` : '')
    + `<details class="evgloss"><summary>Glossary: every term on this page</summary><dl>${GLOSSARY.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl></details>`
    + `<details class="evgloss"><summary>Technical summary (checks, MASE gate, re-run after session 5f)</summary><table class="evsum"><thead><tr><th>#</th><th>Chart</th><th>Stored verdict</th><th>Checks</th><th>MASE gate</th><th>Re-run after 5f</th></tr></thead><tbody>`
    + C.map(c => `<tr><td class="num">${c.chart}</td><td>${esc(c.title)}</td><td>${esc(c.verdict)}</td>`
      + `<td>${(c.checks || []).map(k => `<span class="${k.pass ? 'evok' : 'evno'}">${k.pass ? '✓' : '✗'} ${esc(k.id)}</span>`).join(' ') || '<span class="muted">—</span>'}</td>`
      + `<td>${esc(c.mase_gate_used)}</td><td>${esc(c.rerun_after_5f)}</td></tr>`).join('') + `</tbody></table></details></div>`;
  const body = cards.map(({c, html}) => (c.chart === 8 ? lpBox() : '') + html).join('');
  $('#evidence').innerHTML = intro + boardTable(C) + `<div class="evgrid">${body}</div>`
    + `<div class="evpnav" id="evPnav" hidden><button class="evbtn" id="evPrev">← Previous</button><span id="evPpos"></span><button class="evbtn" id="evNext">Next →</button><button class="evbtn" id="evPexit">Exit presentation</button></div>`;
  C.forEach(c => Object.entries(c._figs).forEach(([k, f]) => { if (f) evRender($(`#evs-${c.chart}-${k}`), f); }));
  const root = $('#evidence');
  root.addEventListener('click', e => {
    const b = e.target.closest('.evbtn'); if (!b || !b.dataset.c) return;
    const c = C.find(x => x.chart === +b.dataset.c);
    if (b.classList.contains('evtogb')){ c._figs[b.dataset.f].toggle.set(b.dataset.v); evRefresh(c, b.dataset.f); return; }
    if (b.classList.contains('evcopy')){ navigator.clipboard.writeText(c.caption).then(() => { b.textContent = 'Copied'; setTimeout(() => { b.textContent = 'Copy caption'; }, 1200); }); return; }
    evExport(c._figs[b.dataset.f], b.dataset.k);
  });
  root.addEventListener('change', e => {
    const s = e.target.closest('.evsel'); if (!s) return;
    const c = C.find(x => x.chart === +s.dataset.c); c._figs[s.dataset.f].control.set(s.value); evRefresh(c, s.dataset.f);
  });
  // Presentation view: one slide per screen (board summary, then each card; the order-plan box before decision 8).
  const slides = () => [...root.querySelectorAll('.evslide')];
  let pos = 0;
  const show = () => { const s = slides(); pos = Math.max(0, Math.min(s.length - 1, pos));
    s.forEach((el, i) => el.classList.toggle('evcurrent', i === pos)); $('#evPpos').textContent = `${pos + 1} / ${s.length}`; window.scrollTo(0, 0); };
  const setPresent = on => { $('#tab-evidence').classList.toggle('evpresent', on); $('#evPnav').hidden = !on; if (on){ pos = 0; show(); } };
  $('#evPresent').onclick = () => setPresent(true);
  $('#evPexit').onclick = () => setPresent(false);
  $('#evPrev').onclick = () => { pos--; show(); };
  $('#evNext').onclick = () => { pos++; show(); };
  document.addEventListener('keydown', e => { if (!$('#tab-evidence').classList.contains('evpresent')) return;
    if (e.key === 'ArrowRight' || e.key === 'PageDown') { pos++; show(); } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { pos--; show(); } else if (e.key === 'Escape') setPresent(false); });
  window.evidencePresent = (on, p) => { setPresent(on); if (p != null){ pos = p; show(); } };
}
// Dev hooks (scripted checks and batch export).
window.evidenceExportSVG = (chart, fig) => { drawEvidence(); const c = EV.charts.find(x => x.chart === chart);
  const f = c && c._figs[fig === 0 ? 'm' : fig]; return f ? evFigure(EVT.light, f).svg : null; };
window.evidenceFigKeys = () => { drawEvidence(); return EV.charts.flatMap(c => Object.entries(c._figs).filter(([, f]) => f).map(([k]) => [c.chart, k])); };
window.evidenceCards = () => { drawEvidence(); return EV.charts.map(c => ({chart: c.chart, question: c._spec.question, headline: c._spec.headline, means: c._spec.means, board: BOARD[c.chart]})); };
return drawEvidence;
})();
