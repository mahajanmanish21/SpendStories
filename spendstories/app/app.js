/* SpendStories report app. Runs entirely in the page from the embedded data;
   it never makes a network request (the page's CSP forbids it anyway). */
(() => {
'use strict';

const RAW = JSON.parse(document.getElementById('ss-data').textContent);
const CUR = RAW.currency || '';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Per-browser conveniences only (filters, theme, your category fixes). Never required.
const store = {
  get(k, d) { try { const v = localStorage.getItem('spendstories:' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('spendstories:' + k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
};

// ------------------------------------------------------------------ formatting
function money(v, compact) {
  if (v == null || !isFinite(v)) return '–';
  const s = v < 0 ? '−' : '', a = Math.abs(v);
  if (a < 0.005) return CUR + '0';
  if (compact) {
    for (const [d, u] of [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]) {
      if (a >= d) { const n = a / d; return s + CUR + (n < 100 ? n.toFixed(1).replace(/\.0$/, '') : n.toFixed(0)) + u; }
    }
    return s + CUR + a.toFixed(0);
  }
  const dp = a >= 100 ? 0 : 2;
  return s + CUR + a.toLocaleString(undefined, { maximumFractionDigits: dp, minimumFractionDigits: dp });
}
const signedMoney = (v, compact) => (v > 0 ? '+' : '') + money(v, compact);
const pct = (v, withSign) => (v == null || !isFinite(v)) ? '–' : ((withSign && v > 0 ? '+' : '') + Math.round(v * 100) + '%');
const MN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MNL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const mLabel = m => MN[+m.slice(5, 7) - 1] + ' ' + m.slice(0, 4);
const mLong = m => MNL[+m.slice(5, 7) - 1] + ' ' + m.slice(0, 4);
const mShort = m => MN[+m.slice(5, 7) - 1] + ' ’' + m.slice(2, 4);
const dLabel = d => +d.slice(8, 10) + ' ' + MN[+d.slice(5, 7) - 1] + ' ' + d.slice(0, 4);
const title = s => String(s).replace(/\b[a-z]/g, c => c.toUpperCase());
const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');

// ------------------------------------------------------------------ statistics
const sum = a => a.reduce((s, x) => s + x, 0);
const mean = a => a.length ? sum(a) / a.length : 0;
function median(a) {
  if (!a.length) return 0;
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
const mad = a => { const m = median(a); return 1.4826 * median(a.map(x => Math.abs(x - m))); };
// Theil–Sen: median of pairwise slopes. One spike month can't fake a trend.
function theilSen(y) {
  const n = y.length;
  if (n < 2) return { slope: 0, intercept: y[0] || 0 };
  const sl = [];
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) sl.push((y[j] - y[i]) / (j - i));
  const slope = median(sl);
  return { slope, intercept: median(y.map((v, i) => v - slope * i)) };
}
const movingAvg = (y, w) => y.map((_, i) => i < w - 1 ? null : mean(y.slice(i - w + 1, i + 1)));

// ------------------------------------------------------------------ data
const KINDS = Object.assign({}, RAW.kinds);
let overrides = store.get('overrides', {});        // merchant -> category
let txedits = store.get('txedits', {});            // transaction id -> {tags, share}
let budgetEdits = store.get('budgets', {});        // category -> amount (null = removed)
let dismissed = store.get('dismissed', {});        // check key -> true
const TX = RAW.txns.map((r, i) => ({
  i, d: r[0], m: r[0].slice(0, 7), t: r[1], a: r[2], c0: r[3], k0: r[4], mer: r[5], s: RAW.sources[r[6]], c: r[3], k: r[4],
  id: r[7] || 'r' + i, tags0: r[8] || [], share0: r[9] == null ? 1 : r[9], orig: r[10] == null ? r[2] : r[10], tags: r[8] || [], share: r[9] == null ? 1 : r[9],
}));
const TXID = new Map(TX.map(t => [t.id, t]));
let BUDGETS = {};
function applyBudgets() {
  BUDGETS = Object.assign({}, RAW.budgets || {});
  for (const [k, v] of Object.entries(budgetEdits)) { if (v == null) delete BUDGETS[k]; else BUDGETS[k] = v; }
}
const isSpend = t => t.k === 'expense' || t.k === 'refund';
const ORIG_CAT = {};
for (const t of TX) if (!(t.mer in ORIG_CAT)) ORIG_CAT[t.mer] = t.c0;

function kindFor(t) {
  if (t.c === t.c0) return t.k0;
  const k = KINDS[t.c] || 'expense';
  return k === 'expense' ? (t.a < 0 ? 'refund' : 'expense') : k;
}
function applyOverrides() {
  for (const k in overrides) if (!(overrides[k] in KINDS)) KINDS[overrides[k]] = 'expense';
  for (const t of TX) {
    const e = txedits[t.id];
    t.tags = e && e.tags ? e.tags : t.tags0;
    t.share = e && e.share != null ? e.share : t.share0;
    t.a = Math.round(t.orig * t.share * 100) / 100;
    t.c = overrides[t.mer] || t.c0; t.k = kindFor(t);
  }
  applyBudgets();
}
const allTags = () => [...new Set(TX.flatMap(t => t.tags))].sort((a, b) => a.localeCompare(b));
const nChanges = () => Object.keys(overrides).length + Object.keys(txedits).length + Object.keys(budgetEdits).length;

function monthRange(a, b) {
  const out = [];
  let y = +a.slice(0, 4), m = +a.slice(5, 7);
  const by = +b.slice(0, 4), bm = +b.slice(5, 7);
  while (y < by || (y === by && m <= bm)) { out.push(y + '-' + String(m).padStart(2, '0')); if (++m > 12) { m = 1; y++; } }
  return out;
}
const DSTART = TX.length ? TX.reduce((a, t) => t.d < a ? t.d : a, TX[0].d) : '2000-01-01';
const DEND = TX.length ? TX.reduce((a, t) => t.d > a ? t.d : a, TX[0].d) : '2000-01-01';
const ALL_MONTHS = monthRange(DSTART.slice(0, 7), DEND.slice(0, 7));
// The first/last month is partial when the statements don't cover all of it.
const PARTIAL = new Set();
if (+DSTART.slice(8, 10) > 3) PARTIAL.add(DSTART.slice(0, 7));
if (+DEND.slice(8, 10) < new Date(+DEND.slice(0, 4), +DEND.slice(5, 7), 0).getDate() - 3) PARTIAL.add(DEND.slice(0, 7));

// Colours follow the category, not its rank in the current filter.
let COLOR = {};
function assignColors() {
  const tot = {};
  for (const t of TX) if (isSpend(t)) tot[t.c] = (tot[t.c] || 0) + t.a;
  COLOR = {};
  Object.keys(tot).sort((a, b) => tot[b] - tot[a]).forEach((c, i) => { COLOR[c] = i < 7 ? `var(--s${i + 1})` : 'var(--other)'; });
}
const colorOf = c => COLOR[c] || 'var(--other)';
const SERIES_CATS = () => Object.keys(COLOR).filter(c => COLOR[c] !== 'var(--other)');

// ------------------------------------------------------------------ state
const S = {
  range: store.get('range', 'all'),
  from: store.get('from', ALL_MONTHS[0]),
  to: store.get('to', ALL_MONTHS[ALL_MONTHS.length - 1]),
  window: store.get('window', 3),
  oneoffs: store.get('oneoffs', false),   // include one-off spikes in period comparisons?
  overlays: store.get('overlays', { trend: true, ma: false, avg: true }),
  heat: store.get('heat', 'row'),
  trendFilter: 'all',
  catSort: 'total',
  merQ: '',
  sort: {},
  tx: {},
};
const TXFIX = {};

function rangeMonths() {
  const all = ALL_MONTHS;
  switch (S.range) {
    case 'all': return all;
    case 'ytd': { const y = all[all.length - 1].slice(0, 4); return all.filter(m => m.startsWith(y)); }
    case 'custom': { const a = S.from <= S.to ? S.from : S.to, b = S.from <= S.to ? S.to : S.from; const r = all.filter(m => m >= a && m <= b); return r.length ? r : all; }
    default: { const n = +S.range; return all.slice(-n); }
  }
}

// ------------------------------------------------------------------ analysis
let D = null;

function analyzeSeries(values, baseIdx, threshold) {
  const y = baseIdx.map(i => values[i]), n = y.length, W = S.window;
  const avg = mean(y), med = median(y);
  const r = { avg, med, n, slope: 0, slopePct: 0, intercept: avg, label: 'few', spikes: [], recent: null, prior: null,
    change: null, changePct: null, forecast: null, cv: 0, max: null };
  if (!n) return r;
  let mi = 0; y.forEach((v, k) => { if (v > y[mi]) mi = k; }); r.max = { i: baseIdx[mi], value: y[mi] };
  const sd = Math.sqrt(mean(y.map(v => (v - avg) ** 2)));
  r.cv = avg > 0 ? sd / avg : 0;
  const compare = vals => {
    if (n < W + 1) return;
    const rec = vals.slice(-W), pri = vals.slice(Math.max(0, n - 2 * W), n - W);
    r.recent = mean(rec); r.prior = mean(pri); r.change = r.recent - r.prior;
    r.changePct = r.prior > 0 ? r.change / r.prior : null;
  };
  compare(y);
  if (n < 3) return r;
  const ts = theilSen(y);
  r.slope = ts.slope; r.intercept = ts.intercept;
  const typical = med > 0 ? med : avg;
  r.slopePct = typical > 0 ? ts.slope / typical : 0;
  r.forecast = Math.max(0, ts.intercept + ts.slope * n);
  for (let k = 0; k < n; k++) {
    const others = y.filter((_, j) => j !== k), usual = median(others), v = y[k];
    const scale = Math.max(mad(others), 0.1 * usual, 1);
    if (v - usual >= threshold && v >= 1.5 * Math.max(usual, 1) && (v - usual) / scale >= 3) r.spikes.push({ i: baseIdx[k], k, value: v, usual });
  }
  // Unless asked otherwise, compare periods as if each spike month had been a usual month,
  // so a single laptop or holiday doesn't read as a change in behaviour.
  r.adjusted = false;
  if (!S.oneoffs && r.spikes.length) {
    const yAdj = [...y];
    for (const sp of r.spikes) { if (sp.k >= n - 2 * W) r.adjusted = true; yAdj[sp.k] = sp.usual; }
    if (r.adjusted) compare(yAdj);
  }
  const agrees = r.change == null || (r.slope > 0 ? r.change > 0 : r.change < 0);
  if (Math.abs(r.slopePct) >= 0.05 && agrees && avg >= threshold) r.label = r.slope > 0 ? 'rising' : 'falling';
  else if (r.spikes.length) r.label = 'spiky';
  else if (r.cv > 0.6) r.label = 'irregular';
  else r.label = 'steady';
  return r;
}

function derive() {
  const months = rangeMonths();
  const idx = new Map(months.map((m, i) => [m, i]));
  const n = months.length;
  const tx = TX.filter(t => idx.has(t.m));
  const full = months.filter(m => !PARTIAL.has(m));
  const baseIdx = (full.length >= 3 ? full : months).map(m => idx.get(m));
  const total = new Array(n).fill(0), purchases = new Array(n).fill(0);
  const cats = new Map(), mers = new Map();
  let income = 0, invested = 0, refunds = 0, transfers = 0;
  const blank = (name, extra) => Object.assign({ name, values: new Array(n).fill(0), counts: new Array(n).fill(0), total: 0, count: 0 }, extra);
  for (const t of tx) {
    if (t.k === 'income') { income -= t.a; continue; }
    if (t.k === 'investment') { invested += t.a; continue; }
    if (t.k === 'transfer') { transfers++; continue; }
    const i = idx.get(t.m);
    total[i] += t.a;
    if (t.k === 'refund') refunds -= t.a; else purchases[i]++;
    let c = cats.get(t.c);
    if (!c) cats.set(t.c, c = blank(t.c));
    c.values[i] += t.a; c.total += t.a;
    if (t.k === 'expense') { c.counts[i]++; c.count++; }
    let me = mers.get(t.mer);
    if (!me) mers.set(t.mer, me = blank(t.mer, { cats: {}, first: t.d, last: t.d, sample: t.t }));
    me.values[i] += t.a; me.total += t.a;
    if (t.k === 'expense') { me.counts[i]++; me.count++; }
    me.cats[t.c] = (me.cats[t.c] || 0) + 1;
    if (t.d < me.first) me.first = t.d;
    if (t.d >= me.last) { me.last = t.d; me.sample = t.t; }
  }
  const spendTotal = sum(total);
  const avgMonth = mean(baseIdx.map(i => total[i]));
  const threshold = 0.02 * Math.max(avgMonth, 1);
  const overall = analyzeSeries(total, baseIdx, threshold);
  const catList = [...cats.values()].sort((a, b) => b.total - a.total);
  for (const c of catList) { c.share = spendTotal ? c.total / spendTotal : 0; c.stats = analyzeSeries(c.values, baseIdx, threshold); }
  const merList = [...mers.values()].sort((a, b) => b.total - a.total);
  for (const me of merList) {
    me.category = Object.keys(me.cats).sort((a, b) => me.cats[b] - me.cats[a])[0];
    me.share = spendTotal ? me.total / spendTotal : 0;
    me.stats = analyzeSeries(me.values, baseIdx, threshold * 0.5);
  }
  D = { months, idx, tx, baseIdx, total, purchases, spendTotal, avgMonth, threshold, overall, cats: catList, catMap: cats,
    mers: merList, merMap: mers, income, invested, refunds, transfers };
}

const LABELS = {
  rising: ['▲', 'Rising', 'up'], falling: ['▼', 'Falling', 'down'], spiky: ['◆', 'Spiky', ''],
  irregular: ['∿', 'Irregular', ''], steady: ['—', 'Steady', ''], few: ['·', 'Too little data', ''],
};
function badge(st, short) {
  const [ic, txt, cls] = LABELS[st.label];
  const extra = (st.label === 'rising' || st.label === 'falling') ? ` ${Math.abs(Math.round(st.slopePct * 100))}%/mo` : '';
  return `<span class="badge ${cls}" title="${esc(labelHelp(st.label))}">${ic} ${short && extra ? '' : txt}${extra}</span>`;
}
function labelHelp(l) {
  return {
    rising: 'Steady upward trend (robust fit, ignores one-off spikes)',
    falling: 'Steady downward trend (robust fit, ignores one-off spikes)',
    spiky: 'Mostly stable, with one or more unusual months',
    irregular: 'Varies a lot from month to month without a clear direction',
    steady: 'No meaningful trend',
    few: 'Needs at least 3 months of data',
  }[l];
}
function delta(v, base, compact) {
  if (v == null || !isFinite(v)) return '<span class="faint">–</span>';
  const cls = v > 0 ? 'up' : v < 0 ? 'down' : '';
  const ar = v > 0 ? '▲ ' : v < 0 ? '▼ ' : '';
  const p = base ? ` (${pct(v / base, true)})` : '';
  return `<span class="delta ${cls}">${ar}${money(Math.abs(v), compact)}${p}</span>`;
}
function deltaPct(p) {
  if (p == null || !isFinite(p)) return '<span class="faint">–</span>';
  const cls = p > 0.005 ? 'up' : p < -0.005 ? 'down' : '';
  return `<span class="delta ${cls}">${p > 0.005 ? '▲ ' : p < -0.005 ? '▼ ' : ''}${pct(Math.abs(p))}</span>`;
}
const windowName = () => S.window === 1 ? 'last month' : `last ${S.window} months`;
const priorName = () => S.window === 1 ? 'the month before' : `the ${S.window} before`;

// ------------------------------------------------------------------ links
const catHref = c => '#/category/' + encodeURIComponent(c);
const merHref = m => '#/merchant/' + encodeURIComponent(m);
const monthHref = m => '#/month/' + m;
const txHref = p => '#/transactions?' + new URLSearchParams(p).toString();
const tagHref = g => '#/tag/' + encodeURIComponent(g);

// ------------------------------------------------------------------ chart primitives
let CH = {}, chSeq = 0;
function slot(fn, cls) { const k = 'c' + (++chSeq); CH[k] = fn; return `<div class="chart ${cls || ''}" data-ch="${k}"></div>`; }
function drawCharts() { for (const el of $$('[data-ch]')) { const fn = CH[el.dataset.ch]; if (fn) el.innerHTML = fn(Math.floor(el.clientWidth)); } }

function niceTicks(max, n = 4) {
  if (!(max > 0)) return [0, 1];
  const raw = max / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(x => x * mag).find(s => s >= raw);
  const t = [];
  for (let v = 0; v < max + step * 1e-3; v += step) t.push(v);
  if (t[t.length - 1] < max) t.push(t[t.length - 1] + step);
  return t;
}
function topPath(x, y, w, h, r = 4) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}
function hBarPath(x0, x1, y, h, r = 4) {
  const w = Math.abs(x1 - x0); r = Math.min(r, w, h / 2);
  if (x1 >= x0) return `M${x0},${y}H${x1 - r}Q${x1},${y} ${x1},${y + r}V${y + h - r}Q${x1},${y + h} ${x1 - r},${y + h}H${x0}Z`;
  return `M${x0},${y}H${x1 + r}Q${x1},${y} ${x1},${y + r}V${y + h - r}Q${x1},${y + h} ${x1 + r},${y + h}H${x0}Z`;
}
const f1 = v => Math.round(v * 10) / 10;

/* Columns (single or stacked) with optional trend / moving-average / average overlays. */
function columnChart(o) {
  const W = Math.max(o.width || 600, 280), H = o.height || 260;
  const L = 52, R = o.forecast ? 34 : 12, T = 16, B = 28, pw = W - L - R, ph = H - T - B, n = o.months.length;
  const totals = o.months.map((_, i) => o.series.reduce((s, se) => s + Math.max(se.values[i], 0), 0));
  const st = o.stats, ov = o.overlays || {};
  const lines = [];
  let maxV = Math.max(...totals, 1);
  const base = o.baseIdx || o.months.map((_, i) => i);
  if (st && ov.trend && st.n >= 3) {
    lines.push({ cls: 'ln-trend', pts: base.map((i, k) => [i, Math.max(0, st.intercept + st.slope * k)]) });
    if (o.forecast && st.forecast != null) lines.push({ cls: 'ln-fc', pts: [[base[base.length - 1], Math.max(0, st.intercept + st.slope * (base.length - 1))], [n - 0.35, st.forecast]] });
  }
  if (st && ov.ma && n >= 3) lines.push({ cls: 'ln-ma', pts: movingAvg(totals, 3).map((v, i) => [i, v]).filter(p => p[1] != null) });
  const avgV = st && ov.avg ? st.avg : null;
  for (const l of lines) for (const p of l.pts) maxV = Math.max(maxV, p[1]);
  const ticks = niceTicks(maxV), ymax = ticks[ticks.length - 1];
  const band = pw / n, bw = Math.max(3, Math.min(n > 24 ? 14 : 28, band * 0.62));
  const X = i => L + band * (i + 0.5), Y = v => T + ph - Math.max(0, v) / ymax * ph;
  const p = [`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Chart')}">`];
  for (const t of ticks) {
    const y = f1(Y(t));
    p.push(`<line class="grid" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text x="${L - 8}" y="${y + 4}" text-anchor="end">${esc(money(t, true))}</text>`);
  }
  const every = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(pw / 58))));
  const spikes = o.spikes || new Set();
  for (let i = 0; i < n; i++) {
    const m = o.months[i], x = f1(X(i) - bw / 2), partial = PARTIAL.has(m);
    const segs = o.series.map(se => ({ se, v: Math.max(se.values[i], 0) })).filter(s => s.v > 0);
    let yc = T + ph;
    segs.forEach((s, k) => {
      const h = s.v / ymax * ph, last = k === segs.length - 1, gap = last ? 0 : 2, y = yc - h, dh = Math.max(h - gap, 0.5);
      const op = partial ? ' fill-opacity=".45"' : '';
      p.push(last ? `<path d="${topPath(x, f1(y), f1(bw), f1(dh))}" fill="${s.se.color}"${op}/>`
        : `<rect x="${x}" y="${f1(y + gap)}" width="${f1(bw)}" height="${f1(dh)}" fill="${s.se.color}"${op}/>`);
      yc = y;
    });
    if (spikes.has(i)) p.push(`<circle cx="${f1(X(i))}" cy="${f1(Y(totals[i]) - 10)}" r="4.5" fill="var(--up)" stroke="var(--card)" stroke-width="2"/>`);
    let tip = `<b>${esc(mLong(m))}</b>${partial ? ' <span class="faint">(partial month)</span>' : ''}<div class="r"><span>${o.series.length > 1 ? 'Total' : esc(o.valueLabel || 'Spent')}</span><span><b>${esc(money(totals[i]))}</b></span></div>`;
    if (o.series.length > 1) {
      for (const se of [...o.series].reverse()) if (se.values[i] > 0) tip += `<div class="r"><span><i class="swatch" style="background:${se.color}"></i> ${esc(se.name)}</span><span>${esc(money(se.values[i]))}</span></div>`;
    }
    if (st && avgV) tip += `<div class="r"><span class="faint">vs average</span><span>${esc(signedMoney(totals[i] - avgV, true))}</span></div>`;
    if (spikes.has(i)) tip += `<div class="up">◆ Spike – well above usual</div>`;
    const go = o.go ? o.go(m) : '';
    if (go) tip += `<div class="hint">Click for details</div>`;
    p.push(`<rect class="hit${go ? ' link' : ''}" x="${f1(L + band * i)}" y="${T}" width="${f1(band)}" height="${ph}" data-tip="${esc(tip)}"${go ? ` data-go="${esc(go)}"` : ''}/>`);
    if (i % every === 0) p.push(`<text x="${f1(X(i))}" y="${H - 8}" text-anchor="middle">${mShort(m)}${partial ? '*' : ''}</text>`);
  }
  p.push(`<line class="axis" x1="${L}" x2="${W - R}" y1="${T + ph}" y2="${T + ph}"/>`);
  if (avgV != null) {
    const y = f1(Y(avgV));
    p.push(`<line class="avgline" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text x="${L + 4}" y="${y - 5}">avg ${esc(money(avgV, true))}</text>`);
  }
  for (const l of lines) p.push(`<polyline class="${l.cls}" points="${l.pts.map(q => f1(X(q[0])) + ',' + f1(Y(q[1]))).join(' ')}"/>`);
  if (o.forecast && st && ov.trend && st.forecast != null) {
    p.push(`<circle cx="${f1(X(n - 0.35))}" cy="${f1(Y(st.forecast))}" r="4" fill="var(--card)" stroke="var(--text)" stroke-width="2"/>`);
    p.push(`<text x="${f1(X(n - 0.35))}" y="${f1(Y(st.forecast) - 9)}" text-anchor="middle">next?</text>`);
  }
  p.push('</svg>');
  return p.join('');
}

function overlayLegend(o, withForecast) {
  const chip = (k, cls, txt) => `<button class="chip${S.overlays[k] ? ' on' : ''}" data-overlay="${k}"><i class="lk ${cls}" style="border-top-style:${cls === 'ma' ? 'dashed' : 'solid'};border-top-width:${k === 'avg' ? 1 : 2}px;border-top-color:${k === 'ma' ? 'var(--text-2)' : k === 'avg' ? 'var(--muted)' : 'var(--text)'}"></i>${txt}</button>`;
  return `<div class="chips" role="group" aria-label="Chart overlays">${chip('trend', '', 'Trend line' + (withForecast ? ' & forecast' : ''))}${chip('ma', 'ma', '3-month average')}${chip('avg', 'avg', 'Average')}${o ? `<span class="small faint" style="align-self:center">${o}</span>` : ''}</div>`;
}

function lineChart(o) {
  const W = Math.max(o.width || 300, 220), H = o.height || 130, L = 46, R = 10, T = 12, B = 24, pw = W - L - R, ph = H - T - B;
  const n = o.months.length, vals = o.values;
  const ticks = niceTicks(Math.max(...vals.filter(v => v != null), 1), 3), ymax = ticks[ticks.length - 1];
  const X = i => L + (n === 1 ? pw / 2 : i * pw / (n - 1)), Y = v => T + ph - v / ymax * ph;
  const p = [`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || '')}">`];
  for (const t of ticks) { const y = f1(Y(t)); p.push(`<line class="grid" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text x="${L - 6}" y="${y + 4}" text-anchor="end">${esc(o.fmt(t, true))}</text>`); }
  let seg = [];
  const segs = [];
  vals.forEach((v, i) => { if (v == null) { if (seg.length) segs.push(seg); seg = []; } else seg.push([X(i), Y(v)]); });
  if (seg.length) segs.push(seg);
  for (const s of segs) p.push(`<polyline points="${s.map(q => f1(q[0]) + ',' + f1(q[1])).join(' ')}" fill="none" stroke="${o.color || 'var(--accent)'}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`);
  const step = n > 1 ? pw / (n - 1) : pw;
  vals.forEach((v, i) => {
    if (v != null && (n <= 18 || i === n - 1)) p.push(`<circle cx="${f1(X(i))}" cy="${f1(Y(v))}" r="${i === n - 1 ? 4 : 3}" fill="${o.color || 'var(--accent)'}" stroke="var(--card)" stroke-width="2"/>`);
    const tip = `<b>${esc(mLong(o.months[i]))}</b><br>${v == null ? 'none' : esc(o.fmt(v))}`;
    p.push(`<rect class="hit" x="${f1(X(i) - step / 2)}" y="${T}" width="${f1(step)}" height="${ph}" data-tip="${esc(tip)}"/>`);
  });
  p.push(`<line class="axis" x1="${L}" x2="${W - R}" y1="${T + ph}" y2="${T + ph}"/>`);
  p.push(`<text x="${L}" y="${H - 6}">${mShort(o.months[0])}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${mShort(o.months[n - 1])}</text></svg>`);
  return p.join('');
}

function heatmap(o) {
  const W = Math.max(o.width || 600, 300), n = o.months.length, lw = W < 560 ? 104 : 168;
  const cw = (W - lw) / n, ch = 26, top = 4, H = top + o.rows.length * ch + 26;
  const gmax = Math.max(1, ...o.rows.flatMap(r => r.values));
  const p = [`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Spending heatmap by category and month">`];
  const maxChars = Math.floor((lw - 10) / 6.6);
  o.rows.forEach((r, k) => {
    const y = top + k * ch, rmax = Math.max(1, ...r.values);
    const name = r.name.length > maxChars ? r.name.slice(0, maxChars - 1) + '…' : r.name;
    p.push(`<text class="lbl" x="0" y="${y + ch / 2 + 4}">${esc(name)}</text>`);
    p.push(`<rect class="hit link" x="0" y="${y}" width="${lw - 6}" height="${ch - 2}" data-go="${esc(catHref(r.name))}" data-tip="${esc(`<b>${esc(r.name)}</b><div class="hint">Click to open category</div>`)}"/>`);
    r.values.forEach((v, i) => {
      const t = v <= 0 ? -1 : (o.mode === 'row' ? v / rmax : Math.sqrt(v / gmax));
      const step = t < 0 ? null : Math.min(8, Math.floor(t * 8.999));
      const x = lw + i * cw, fill = step == null ? 'var(--grid)' : `var(--h${step})`;
      p.push(`<rect x="${f1(x)}" y="${y}" width="${f1(Math.max(cw - 2, 1))}" height="${ch - 2}" rx="3" fill="${fill}"/>`);
      const spike = r.spikes && r.spikes.has(i);
      if (spike && cw >= 10) p.push(`<circle cx="${f1(x + cw - 7)}" cy="${y + 6}" r="3" fill="var(--up)" stroke="var(--card)" stroke-width="1.5"/>`);
      const tip = `<b>${esc(r.name)}</b> · ${esc(mLabel(o.months[i]))}<br>${esc(money(v))}${r.avg ? ` <span class="faint">(avg ${esc(money(r.avg, true))})</span>` : ''}${spike ? '<div class="up">◆ Spike</div>' : ''}<div class="hint">Click for this month</div>`;
      p.push(`<rect class="hit link" x="${f1(x)}" y="${y}" width="${f1(cw)}" height="${ch}" data-tip="${esc(tip)}" data-go="${esc(monthHref(o.months[i]))}"/>`);
    });
  });
  const every = Math.max(1, Math.ceil(n / Math.max(1, Math.floor((W - lw) / 52))));
  o.months.forEach((m, i) => { if (i % every === 0) p.push(`<text x="${f1(lw + i * cw + cw / 2)}" y="${H - 8}" text-anchor="middle">${mShort(m)}</text>`); });
  p.push('</svg>');
  return p.join('');
}

function divergingBars(o) {
  const W = Math.max(o.width || 500, 280), lw = W < 520 ? 104 : 170, vw = 64, rowH = 30;
  const H = o.items.length * rowH + 6;
  const maxAbs = Math.max(1, ...o.items.map(it => Math.abs(it.value)));
  const center = lw + (W - lw) / 2, half = (W - lw) / 2 - vw;
  const maxChars = Math.floor((lw - 10) / 6.6);
  const p = [`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || '')}">`];
  o.items.forEach((it, k) => {
    const y = k * rowH + 3, bh = 14, by = y + (rowH - bh) / 2 - 2;
    const name = it.name.length > maxChars ? it.name.slice(0, maxChars - 1) + '…' : it.name;
    p.push(`<text class="lbl" x="${lw - 10}" y="${by + 11}" text-anchor="end">${esc(name)}</text>`);
    const x1 = center + it.value / maxAbs * half;
    if (Math.abs(x1 - center) >= 0.5) p.push(`<path d="${hBarPath(center, f1(x1), f1(by), bh)}" fill="${it.value > 0 ? 'var(--up)' : 'var(--down)'}"/>`);
    const tx = it.value >= 0 ? x1 + 6 : x1 - 6;
    p.push(`<text x="${f1(tx)}" y="${by + 11}" text-anchor="${it.value >= 0 ? 'start' : 'end'}">${esc(it.valueLabel || signedMoney(it.value, true))}</text>`);
    p.push(`<rect class="hit${it.go ? ' link' : ''}" x="0" y="${y - 2}" width="${W}" height="${rowH}" data-tip="${esc(it.tip || '')}"${it.go ? ` data-go="${esc(it.go)}"` : ''}/>`);
  });
  p.push(`<line class="axis" x1="${f1(center)}" x2="${f1(center)}" y1="0" y2="${H}"/></svg>`);
  return p.join('');
}

function sparkline(values, color, w = 96, h = 26) {
  if (!values || values.length < 2) return '';
  const vmax = Math.max(...values, 1e-9), vmin = Math.min(...values, 0), span = vmax - vmin || 1;
  const pts = values.map((v, i) => [2 + i * (w - 6) / (values.length - 1), h - 3 - (v - vmin) / span * (h - 6)]);
  const [ex, ey] = pts[pts.length - 1];
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts.map(q => f1(q[0]) + ',' + f1(q[1])).join(' ')}" fill="none" stroke="${color || 'var(--accent)'}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${f1(ex)}" cy="${f1(ey)}" r="3" fill="${color || 'var(--accent)'}" stroke="var(--card)" stroke-width="1.5"/></svg>`;
}

// ------------------------------------------------------------------ small components
const tile = (label, value, note, href) => `<${href ? `a href="${href}"` : 'div'} class="tile"><div class="label">${label}</div><div class="value">${value}</div>${note ? `<div class="note">${note}</div>` : ''}</${href ? 'a' : 'div'}>`;
const sw = c => `<i class="swatch" style="background:${colorOf(c)}"></i>`;
const shareBar = (v, max, color) => `<span class="share"><i style="width:${Math.max(2, Math.round(v / (max || 1) * 100))}%;background:${color || 'var(--accent)'}"></i></span>`;
function crumbs(items) {
  return `<nav class="crumbs" aria-label="Breadcrumb">${items.map((it, k) => (k ? '<span class="sep">›</span>' : '') + (it[1] ? `<a href="${it[1]}">${esc(it[0])}</a>` : `<span>${esc(it[0])}</span>`)).join('')}</nav>`;
}
function sortTable(id, rows, cols, defKey, defDir = -1) {
  const st = S.sort[id] || { key: defKey, dir: defDir };
  const col = cols.find(c => c.key === st.key) || cols[0];
  if (col.val) rows.sort((a, b) => { const x = col.val(a), y = col.val(b); return (x < y ? -1 : x > y ? 1 : 0) * st.dir; });
  const head = cols.map(c => `<th class="${c.num ? 'num' : ''} ${c.cls || ''}"${c.val ? ` data-sort="${id}:${c.key}"` : ''}>${c.label}${st.key === c.key && c.val ? ` <span class="arrow">${st.dir > 0 ? '↑' : '↓'}</span>` : ''}</th>`).join('');
  return { head, rows };
}
function partialNote(months) {
  const p = months.filter(m => PARTIAL.has(m));
  if (!p.length) return '';
  return `<div class="footnote">* ${p.map(mLabel).join(', ')}: partial month (statements don't cover all of it). Faded in charts and left out of averages and trends${D.baseIdx.length < 3 ? ' once you have 3 full months' : ''}.</div>`;
}
function noData(msg) {
  return `<div class="card empty">${msg}${S.range !== 'all' ? `<div style="margin-top:10px"><button class="btn" data-set="range:all">Show all time</button></div>` : ''}</div>`;
}

// ------------------------------------------------------------------ highlights
function highlights() {
  const H = [], o = D.overall, W = S.window;
  for (const b of budgetAlerts(LAST_MONTH).slice(0, 3)) {
    H.push({ ic: b.status === 'over' ? '✗' : '!', cls: 'up', go: '#/budgets',
      text: b.status === 'over' ? `<b>${esc(b.cat)}</b> is over budget in ${mLabel(LAST_MONTH)}: ${money(b.spent, true)} of ${money(b.limit, true)}.`
        : `<b>${esc(b.cat)}</b> is heading over budget: ${money(b.spent, true)} of ${money(b.limit, true)} so far, on pace for ${money(b.projected, true)}.` });
  }
  const openChecks = (RAW.checks || []).filter(c => c.severity === 'warn' && !dismissed[checkKey(c)]);
  if (openChecks.length) H.push({ ic: '⚑', cls: 'up', go: '#/checks', text: `${plural(openChecks.length, 'thing')} worth a look: ${openChecks.slice(0, 2).map(c => esc(c.title)).join('; ')}${openChecks.length > 2 ? '…' : ''}` });
  if (o.n >= 3) {
    if (Math.abs(o.slopePct) >= 0.02) {
      H.push({ ic: o.slope > 0 ? '▲' : '▼', cls: o.slope > 0 ? 'up' : 'down', go: '#/trends',
        text: `Overall spending is <b>${o.slope > 0 ? 'rising' : 'falling'}</b> by about ${money(Math.abs(o.slope), true)} a month (${Math.abs(Math.round(o.slopePct * 100))}% of a typical month).` });
    } else H.push({ ic: '—', go: '#/trends', text: 'Overall spending is <b>broadly flat</b> over this period.' });
  }
  if (o.changePct != null && Math.abs(o.changePct) >= 0.05) {
    H.push({ ic: o.change > 0 ? '▲' : '▼', cls: o.change > 0 ? 'up' : 'down', go: '#/trends',
      text: `Your ${windowName()} averaged <b>${money(o.recent, true)}</b>/month: ${pct(Math.abs(o.changePct))} ${o.change > 0 ? 'more' : 'less'} than ${priorName()}${o.adjusted ? ' (setting aside one-off spikes)' : ''}.` });
  }
  const movers = D.cats.filter(c => c.stats.change != null).sort((a, b) => b.stats.change - a.stats.change);
  const up = movers[0], down = movers[movers.length - 1];
  if (up && up.stats.change >= D.threshold) H.push({ ic: '▲', cls: 'up', go: catHref(up.name),
    text: `Biggest increase: <b>${esc(up.name)}</b>, up ${money(up.stats.change, true)}/month (${windowName()} vs ${priorName()}${up.stats.adjusted ? ', one-off spikes aside' : ''}).` });
  if (down && down !== up && down.stats.change <= -D.threshold) H.push({ ic: '▼', cls: 'down', go: catHref(down.name),
    text: `Biggest drop: <b>${esc(down.name)}</b>, down ${money(-down.stats.change, true)}/month.` });
  for (const c of D.cats.filter(c => c.stats.label === 'rising' && c !== up).slice(0, 2)) {
    H.push({ ic: '▲', cls: 'up', go: catHref(c.name), text: `<b>${esc(c.name)}</b> has been rising steadily, about ${Math.round(c.stats.slopePct * 100)}% a month.` });
  }
  const spikes = D.cats.flatMap(c => c.stats.spikes.map(s => Object.assign({ cat: c.name }, s)))
    .sort((a, b) => (b.value - b.usual) - (a.value - a.usual)).slice(0, 3);
  for (const s of spikes) {
    H.push({ ic: '◆', cls: 'up', go: monthHref(D.months[s.i]),
      text: `Spike: <b>${esc(s.cat)}</b> reached ${money(s.value, true)} in ${mLabel(D.months[s.i])}` + (s.usual >= 1 ? `, ${(s.value / s.usual).toFixed(1)}× the usual ${money(s.usual, true)}.` : ', when a typical month has next to nothing.') });
  }
  const rec = RAW.recurring || [];
  if (rec.length) {
    H.push({ ic: '↻', go: '#/merchants', text: `${plural(rec.length, 'recurring payment')} found, about <b>${money(sum(rec.map(r => r.monthly_cost)), true)}</b> a month.` });
    for (const r of rec.filter(r => r.price_change >= 0.05).slice(0, 2)) {
      H.push({ ic: '▲', cls: 'up', go: merHref(r.merchant), text: `<b>${esc(title(r.merchant))}</b> went up ${pct(r.price_change)} (now ${money(r.amount)} ${r.frequency}).` });
    }
  }
  const unc = D.catMap.get('Uncategorized');
  if (unc && unc.share >= 0.08) H.push({ ic: '?', go: txHref({ cat: 'Uncategorized' }),
    text: `${pct(unc.share)} of spending is <b>uncategorised</b>. Click a category label in the transactions list to fix it.` });
  return H;
}

// ------------------------------------------------------------------ views
const VIEWS = {};

VIEWS.overview = () => {
  if (!D.tx.length) return noData('No transactions in this period.');
  const o = D.overall, W = S.window;
  const last = D.baseIdx.length ? D.baseIdx[D.baseIdx.length - 1] : D.months.length - 1;
  const lastV = D.total[last];
  const tiles = [
    tile('Spent', money(D.spendTotal, true), `${plural(sum(D.purchases), 'purchase')} · ${D.months.length} months`, '#/transactions'),
    tile('Average month', money(D.avgMonth, true), D.baseIdx.length < D.months.length ? 'full months only' : 'across the period'),
    tile('Trend', o.n >= 3 ? `<span class="${o.slope > 0.02 * o.med ? 'up' : o.slope < -0.02 * o.med ? 'down' : ''}">${o.slope >= 0 ? '▲' : '▼'} ${money(Math.abs(o.slope), true)}</span>` : '–',
      o.n >= 3 ? `per month (${pct(o.slopePct, true)}) · see trends ›` : 'needs 3+ months', '#/trends'),
    tile(`${mLabel(D.months[last])}`, money(lastV, true), D.avgMonth ? `${delta(lastV - D.avgMonth, D.avgMonth, true)} vs average` : '', monthHref(D.months[last])),
  ];
  if (BUDGETS['All spending']) { const b = budgetRow('All spending', BUDGETS['All spending'], LAST_MONTH); tiles.splice(3, 0, tile(`Budget · ${mLabel(LAST_MONTH)}`, `${money(b.spent, true)} <span class="small faint">of ${money(b.limit, true)}</span>`, bBadge(b.status), '#/budgets')); }
  if (D.income) tiles.push(tile('Income', money(D.income, true), D.invested ? `${money(D.invested, true)} invested` : ''));
  if (D.income) { const left = D.income - D.spendTotal - D.invested; tiles.push(tile('Left over', `<span class="${left < 0 ? 'up' : ''}">${money(left, true)}</span>`, `${pct(left / D.income)} of income`)); }

  const hl = highlights();
  const cats = SERIES_CATS().filter(c => D.catMap.has(c));
  const series = cats.map(c => ({ name: c, color: colorOf(c), values: D.catMap.get(c).values }));
  const rest = D.cats.filter(c => !cats.includes(c.name));
  if (rest.length) series.push({ name: 'Other', color: 'var(--other)', values: D.months.map((_, i) => sum(rest.map(c => c.values[i]))) });
  const legend = `<div class="legend">${series.map(s => s.name === 'Other' ? `<a href="#/categories"><i class="swatch" style="background:${s.color}"></i>Other (${rest.length})</a>` : `<a href="${catHref(s.name)}"><i class="swatch" style="background:${s.color}"></i>${esc(s.name)}</a>`).join('')}</div>`;
  const chart = slot(w => columnChart({ width: w, months: D.months, series, stats: D.overall, baseIdx: D.baseIdx, overlays: { avg: S.overlays.avg }, go: monthHref, label: 'Monthly spending by category' }));
  const maxShare = D.cats.length ? D.cats[0].share : 1;
  const catRows = D.cats.slice(0, 8).map(c => `<tr class="link" data-go="${esc(catHref(c.name))}"><td><span class="name">${sw(c.name)}<a href="${catHref(c.name)}">${esc(c.name)}</a></span></td>
    <td class="hide-sm">${shareBar(c.share, maxShare, colorOf(c.name))}</td><td class="num">${money(c.total, true)}</td><td class="num faint">${pct(c.share)}</td><td class="num">${badge(c.stats, true)}</td></tr>`).join('');
  const rec = (RAW.recurring || []).slice(0, 6);
  const recRows = rec.map(r => `<tr class="link" data-go="${esc(merHref(r.merchant))}"><td><a href="${merHref(r.merchant)}">${esc(title(r.merchant))}</a><div class="small faint">${esc(r.frequency)}</div></td><td class="num">${money(r.amount)}</td><td class="num">${r.price_change >= 0.05 ? `<span class="badge up">▲ ${pct(r.price_change)}</span>` : ''}</td></tr>`).join('');

  return `<h1>Overview</h1><p class="sub">${dLabel(D.tx[0].d)} – ${dLabel(D.tx[D.tx.length - 1].d)} · ${plural(D.tx.length, 'transaction')}</p>
  <div class="tiles">${tiles.join('')}</div>
  <h2>Highlights</h2><p class="desc">What stands out. Click any line for the details.</p>
  <div class="card"><ul class="hl">${hl.map(h => `<li><a href="${h.go}"><span class="ic ${h.cls || ''}">${h.ic}</span><span>${h.text}</span><span class="go">›</span></a></li>`).join('') || '<li class="muted">Nothing notable yet. Add more months of statements.</li>'}</ul></div>
  <h2>Month by month</h2><p class="desc">Click a month to see what you spent it on and what was unusual. Click a category in the legend to explore it.</p>
  <div class="card">${legend}${chart}${partialNote(D.months)}${monthTable(series)}</div>
  <div class="cols" style="margin-top:12px">
    <div class="card"><div class="head-row"><h3>Where it goes</h3><a class="small" href="#/categories">All ${D.cats.length} categories ›</a></div>
      <table><tbody>${catRows}</tbody></table></div>
    <div class="card"><div class="head-row"><h3>Recurring payments</h3><a class="small" href="#/merchants">All merchants ›</a></div>
      ${rec.length ? `<table><tbody>${recRows}</tbody></table><div class="small muted" style="margin-top:6px">≈ ${money(sum((RAW.recurring || []).map(r => r.monthly_cost)))} a month in total</div>` : '<p class="muted small">None detected.</p>'}</div>
  </div>`;
};

function monthTable(series) {
  const head = D.months.map(m => `<th class="num">${mShort(m)}</th>`).join('');
  const rows = series.map(s => `<tr><td>${esc(s.name)}</td>${s.values.map(v => `<td class="num">${money(v)}</td>`).join('')}</tr>`).join('');
  return `<details class="tbl"><summary>Show as table</summary><div class="scroll"><table><tr><th>Category</th>${head}</tr>${rows}<tr><td><b>Total</b></td>${D.total.map(v => `<td class="num"><b>${money(v)}</b></td>`).join('')}</tr></table></div></details>`;
}

VIEWS.trends = () => {
  if (!D.tx.length) return noData('No transactions in this period.');
  const o = D.overall, W = S.window, months = D.months;
  const seg = `<div class="seg" role="group" aria-label="Comparison window">${[1, 3, 6].map(w => `<button class="${S.window === w ? 'on' : ''}" data-set="window:${w}">${w === 1 ? '1 month' : w + ' months'}</button>`).join('')}</div>`;
  // Same period last year
  let yoy = null;
  const lastM = D.baseIdx.length ? months[D.baseIdx[D.baseIdx.length - 1]] : null;
  if (lastM) {
    const ly = (+lastM.slice(0, 4) - 1) + lastM.slice(4);
    const i = ALL_MONTHS.indexOf(ly);
    if (i >= 0 && !PARTIAL.has(ly)) {
      const v = sum(TX.filter(t => t.m === ly && isSpend(t)).map(t => t.a)), cur = D.total[D.idx.get(lastM)];
      if (v > 0) yoy = { m: lastM, ly, cur, v };
    }
  }
  const tiles = [
    tile('Direction', o.n >= 3 ? badge(o) : '–', o.n >= 3 ? `${o.slope >= 0 ? '+' : '−'}${money(Math.abs(o.slope), true)} per month, robust fit` : 'needs 3+ months'),
    tile(`${title(windowName())} vs ${priorName()}`, o.change != null ? delta(o.change, null, true) : '–', o.change != null ? `${money(o.recent, true)}/mo vs ${money(o.prior, true)}/mo (${pct(o.changePct, true)})` : `needs ${W + 1}+ months`),
    yoy ? tile(`${mLabel(yoy.m)} vs a year earlier`, delta(yoy.cur - yoy.v, null, true), `${money(yoy.cur, true)} vs ${money(yoy.v, true)} (${pct((yoy.cur - yoy.v) / yoy.v, true)})`)
      : tile('Same month last year', '–', 'needs 13+ months of statements'),
    tile('Next month, if the trend holds', o.forecast != null ? money(o.forecast, true) : '–', o.forecast != null ? 'a rough guide, not a prediction' : 'needs 3+ months'),
  ];
  const spikeSet = new Set(o.spikes.map(s => s.i));
  const main = slot(w => columnChart({ width: w, height: 300, months, series: [{ name: 'Spending', color: 'var(--accent)', values: D.total }], stats: o, baseIdx: D.baseIdx, overlays: S.overlays, spikes: spikeSet, go: monthHref, forecast: true, label: 'Total monthly spending with trend' }));

  // Drivers
  const movers = D.cats.filter(c => c.stats.change != null && Math.abs(c.stats.change) >= 0.5).sort((a, b) => b.stats.change - a.stats.change);
  const top = movers.length > 12 ? [...movers.slice(0, 6), ...movers.slice(-6)] : movers;
  const drivers = top.length ? slot(w => divergingBars({ width: w, label: 'Change by category', items: top.map(c => ({
    name: c.name, value: c.stats.change, go: catHref(c.name),
    tip: `<b>${esc(c.name)}</b><div class="r"><span>${esc(title(windowName()))}</span><span>${esc(money(c.stats.recent))}/mo</span></div><div class="r"><span>${esc(title(priorName()))}</span><span>${esc(money(c.stats.prior))}/mo</span></div>${c.stats.adjusted ? '<div class="faint">◆ a spike month was set aside</div>' : ''}<div class="hint">Click to explore</div>`,
  })) })) : '<p class="muted">Not enough months to compare yet.</p>';

  // Category trend table
  const filt = S.trendFilter;
  let rows = D.cats.filter(c => filt === 'all' || c.stats.label === filt);
  const cols = [
    { key: 'name', label: 'Category', val: c => c.name },
    { key: 'spark', label: 'Monthly', cls: 'hide-sm' },
    { key: 'avg', label: 'Avg / month', num: 1, val: c => c.stats.avg },
    { key: 'recent', label: title(windowName()), num: 1, val: c => c.stats.recent ?? -1, cls: 'hide-sm' },
    { key: 'change', label: 'Change', num: 1, val: c => c.stats.change ?? 0 },
    { key: 'slope', label: 'Trend', num: 1, val: c => c.stats.label === 'rising' || c.stats.label === 'falling' ? c.stats.slope : 0 },
    { key: 'fc', label: 'Next month?', num: 1, val: c => c.stats.forecast ?? -1, cls: 'hide-sm' },
  ];
  const tbl = sortTable('trendcats', rows, cols, 'change', -1);
  const counts = {}; for (const c of D.cats) counts[c.stats.label] = (counts[c.stats.label] || 0) + 1;
  const chips = ['all', 'rising', 'falling', 'spiky', 'steady', 'irregular'].filter(k => k === 'all' || counts[k]).map(k => `<button class="chip${filt === k ? ' on' : ''}" data-set="trendFilter:${k}">${k === 'all' ? 'All' : LABELS[k][0] + ' ' + LABELS[k][1]} <span class="faint">${k === 'all' ? D.cats.length : counts[k]}</span></button>`).join('');
  const trendRows = tbl.rows.map(c => `<tr class="link" data-go="${esc(catHref(c.name))}"><td><span class="name">${sw(c.name)}<a href="${catHref(c.name)}">${esc(c.name)}</a></span></td>
    <td class="hide-sm">${sparkline(D.baseIdx.map(i => c.values[i]), colorOf(c.name))}</td><td class="num">${money(c.stats.avg)}</td>
    <td class="num hide-sm">${c.stats.recent != null ? money(c.stats.recent) : '–'}</td><td class="num">${deltaPct(c.stats.changePct ?? (c.stats.change > 0 ? Infinity : null))}</td>
    <td class="num">${badge(c.stats)}</td><td class="num hide-sm">${c.stats.forecast != null ? money(c.stats.forecast, true) : '–'}</td></tr>`).join('');

  // Heatmap
  const heatRows = D.cats.filter(c => c.total > 0).map(c => ({ name: c.name, values: c.values.map(v => Math.max(v, 0)), avg: c.stats.avg, spikes: new Set(c.stats.spikes.map(s => s.i)) }));
  const heat = slot(w => heatmap({ width: w, months, rows: heatRows, mode: S.heat }));

  // Merchant trends
  const recentIdx = D.baseIdx.slice(-W), recentSet = new Set(recentIdx.map(i => months[i]));
  const firstRecent = recentIdx.length ? months[recentIdx[0]] : null;
  const growing = D.mers.filter(m => m.stats.change != null && m.stats.change >= D.threshold * 0.5).sort((a, b) => b.stats.change - a.stats.change).slice(0, 6);
  const fresh = firstRecent ? D.mers.filter(m => m.first.slice(0, 7) >= firstRecent && m.first.slice(0, 7) > months[0] && m.total >= D.threshold * 0.5).sort((a, b) => b.total - a.total).slice(0, 6) : [];
  const lastActive = months[months.length - 1];
  const stopped = firstRecent ? D.mers.filter(m => m.last.slice(0, 7) < firstRecent && m.values.filter(v => v > 0).length >= 3 && lastActive >= firstRecent).sort((a, b) => b.total - a.total).slice(0, 6) : [];
  const merList = (arr, f) => arr.length ? `<table><tbody>${arr.map(m => `<tr class="link" data-go="${esc(merHref(m.name))}"><td><a href="${merHref(m.name)}">${esc(title(m.name))}</a><div class="small faint">${esc(m.category)}</div></td><td class="num">${f(m)}</td></tr>`).join('')}</tbody></table>` : '<p class="small muted">None.</p>';

  return `<h1>Trends</h1><p class="sub">How your spending is changing, and why.</p>
  <div class="toolbar"><span class="ctl">Compare the ${seg} with the same length of time before</span>
    <span class="ctl">One-off spikes <span class="seg">${[['false', 'Set aside'], ['true', 'Include']].map(([k, t]) => `<button class="${String(S.oneoffs) === k ? 'on' : ''}" data-set="oneoffs:${k}" title="${k === 'false' ? 'Treat spike months as ordinary months when comparing periods, so you see changes in habits' : 'Compare raw totals, spikes and all'}">${t}</button>`).join('')}</span></span></div>
  <div class="tiles">${tiles.join('')}</div>
  <h2>Overall spending</h2><p class="desc">The trend line uses a robust fit, so one unusual month (a holiday, a laptop) doesn't tilt it. Red dots mark spikes. Click a month for details.</p>
  <div class="card">${overlayLegend('', true)}<div style="height:8px"></div>${main}${partialNote(months)}</div>
  <h2>What's driving the change</h2><p class="desc">Average monthly spend per category, ${windowName()} compared with ${priorName()}${S.oneoffs ? '' : ', with one-off spikes set aside'}. Click a bar to explore.</p>
  <div class="card">${drivers}</div>
  <h2>Category trends</h2><p class="desc">Each category's direction over the period. Sort by any column; click a row to dig in.</p>
  <div class="chips" style="margin-bottom:10px">${chips}</div>
  <div class="card scroll"><table><thead><tr>${tbl.head}</tr></thead><tbody>${trendRows || '<tr><td class="muted">No categories match.</td></tr>'}</tbody></table></div>
  <h2>Seasonality map</h2><p class="desc">Darker = more spending. Spot the months each category peaks. Click a cell to open that month.</p>
  <div class="card"><div class="toolbar"><div class="seg">${[['row', "Each category's own scale"], ['abs', 'Same scale']].map(([k, t]) => `<button class="${S.heat === k ? 'on' : ''}" data-set="heat:${k}">${t}</button>`).join('')}</div>
  <span class="small muted">Less <span class="ramp">${[0, 2, 4, 6, 8].map(i => `<i style="background:var(--h${i})"></i>`).join('')}</span> More · <span class="up">●</span> spike</span></div>${heat}</div>
  <h2>Merchant trends</h2><p class="desc">Where you've started, stopped or stepped up spending (${windowName()} vs ${priorName()}).</p>
  <div class="cols3">
    <div class="card"><h3>▲ Spending more at</h3>${merList(growing, m => `<span class="up">+${money(m.stats.change, true)}/mo</span>`)}</div>
    <div class="card"><h3>✦ New in the ${windowName()}</h3>${merList(fresh, m => money(m.total, true))}</div>
    <div class="card"><h3>✕ Stopped</h3><p class="small faint" style="margin:-4px 0 4px">regular before, nothing in the ${windowName()}</p>${merList(stopped, m => `last ${dLabel(m.last)}`)}</div>
  </div>`;
};

VIEWS.categories = () => {
  if (!D.cats.length) return noData('No spending in this period.');
  const sorts = { total: ['Biggest', (a, b) => b.total - a.total], change: ['Biggest increase', (a, b) => (b.stats.change ?? -1e18) - (a.stats.change ?? -1e18)], trend: ['Fastest rising', (a, b) => b.stats.slopePct - a.stats.slopePct], name: ['A–Z', (a, b) => a.name.localeCompare(b.name)] };
  const cats = [...D.cats].sort(sorts[S.catSort][1]);
  const cards = cats.map(c => `<a class="card catcard" href="${catHref(c.name)}"><div class="head-row"><span class="name">${sw(c.name)}<b>${esc(c.name)}</b></span>${badge(c.stats, true)}</div>
    <div class="amt">${money(c.total, true)}</div><div class="meta"><span>${pct(c.share)} · ${money(c.stats.avg, true)}/mo</span>${sparkline(D.baseIdx.map(i => c.values[i]), colorOf(c.name), 90, 24)}</div>
    <div class="meta" style="margin-top:2px"><span>${title(windowName())}: ${c.stats.changePct != null ? deltaPct(c.stats.changePct) : c.stats.change != null ? delta(c.stats.change, null, true) : '–'}</span><span>${plural(c.count, 'purchase')}</span></div></a>`).join('');
  const other = [];
  if (D.income) other.push(`<a href="${txHref({ kind: 'income' })}">Income ${money(D.income, true)}</a>`);
  if (D.invested) other.push(`<a href="${txHref({ kind: 'investment' })}">Investments ${money(D.invested, true)}</a>`);
  if (D.transfers) other.push(`<a href="${txHref({ kind: 'transfer' })}">${plural(D.transfers, 'transfer')} between your accounts</a>`);
  return `<h1>Categories</h1><p class="sub">${D.cats.length} categories · ${money(D.spendTotal, true)} spent</p>
  <div class="toolbar"><span class="ctl">Sort <select data-setsel="catSort">${Object.entries(sorts).map(([k, v]) => `<option value="${k}"${S.catSort === k ? ' selected' : ''}>${v[0]}</option>`).join('')}</select></span></div>
  <div class="catgrid">${cards}</div>
  ${other.length ? `<p class="small muted" style="margin-top:16px">Not counted as spending: ${other.join(' · ')}</p>` : ''}`;
};

function trendExplainer(e) {
  // Split the change in a category/merchant into "how often" vs "how much each time".
  const st = e.stats, W = S.window;
  if (st.change == null) return '';
  const idxR = D.baseIdx.slice(-W), idxP = D.baseIdx.slice(Math.max(0, D.baseIdx.length - 2 * W), D.baseIdx.length - W);
  const cnt = ix => mean(ix.map(i => e.counts[i]));
  const spent = ix => sum(ix.map(i => e.values[i])), num = ix => sum(ix.map(i => e.counts[i]));
  const cR = cnt(idxR), cP = cnt(idxP), tR = num(idxR) ? spent(idxR) / num(idxR) : null, tP = num(idxP) ? spent(idxP) / num(idxP) : null;
  if (!cP || tP == null || tR == null) return '';
  const fc = cR / cP - 1, tc = tR / tP - 1;
  const word = (v, a, b) => Math.abs(v) < 0.05 ? 'about the same' : `${pct(Math.abs(v))} ${v > 0 ? a : b}`;
  let lead;
  if (Math.abs(st.changePct ?? 0) < 0.05) lead = 'Spending here is about level';
  else lead = `Spending here is ${st.change > 0 ? 'up' : 'down'} ${pct(Math.abs(st.changePct))}`;
  const driver = Math.abs(fc) >= Math.abs(tc) ? (fc > 0 ? 'mostly because you buy more often' : 'mostly because you buy less often')
    : (tc > 0 ? 'mostly because each purchase costs more' : 'mostly because each purchase costs less');
  return `<p style="margin:0 0 10px">${lead}${Math.abs(st.changePct ?? 0) >= 0.05 ? `, <b>${driver}</b>` : ''}: ${cR.toFixed(1)} purchases a month (${word(fc, 'more', 'fewer')}) at about ${money(tR)} each (${word(tc, 'more', 'less')}), ${windowName()} vs ${priorName()}.</p>`;
}

function detailCharts(e, color) {
  const ticket = D.months.map((_, i) => e.counts[i] ? e.values[i] / e.counts[i] : null);
  return `<div class="cols">
    <div class="card"><h3>Purchases per month</h3>${slot(w => lineChart({ width: w, months: D.months, values: e.counts, color, fmt: (v, c) => c ? String(Math.round(v)) : plural(Math.round(v), 'purchase'), label: 'Purchases per month' }))}</div>
    <div class="card"><h3>Average purchase</h3>${slot(w => lineChart({ width: w, months: D.months, values: ticket, color, fmt: (v, c) => money(v, c), label: 'Average purchase size' }))}</div></div>`;
}

VIEWS.category = name => {
  const c = D.catMap.get(name);
  const head = crumbs([['Categories', '#/categories'], [name]]);
  if (!c) return head + `<h1>${sw(name)}${esc(name)}</h1>` + noData('No spending in this category in the selected period.');
  const st = c.stats, color = colorOf(name);
  const spikes = new Set(st.spikes.map(s => s.i));
  const chart = slot(w => columnChart({ width: w, months: D.months, series: [{ name, color, values: c.values }], stats: st, baseIdx: D.baseIdx, overlays: S.overlays, spikes, go: m => monthHref(m), forecast: true, label: name + ' by month' }));
  const mers = D.mers.filter(m => m.cats[name]).map(m => {
    // merchant's spend inside this category only
    const values = D.months.map(() => 0); let total = 0, count = 0;
    for (const t of D.tx) if (t.mer === m.name && t.c === name && isSpend(t)) { values[D.idx.get(t.m)] += t.a; total += t.a; if (t.k === 'expense') count++; }
    return { name: m.name, values, total, count, stats: analyzeSeries(values, D.baseIdx, D.threshold * 0.5), last: m.last };
  }).filter(m => m.total !== 0);
  const cols = [
    { key: 'name', label: 'Merchant', val: m => m.name },
    { key: 'spark', label: 'Monthly', cls: 'hide-sm' },
    { key: 'total', label: 'Total', num: 1, val: m => m.total },
    { key: 'share', label: 'Share', num: 1, val: m => m.total, cls: 'hide-sm' },
    { key: 'count', label: 'Purchases', num: 1, val: m => m.count },
    { key: 'change', label: 'Change', num: 1, val: m => m.stats.change ?? 0 },
    { key: 'last', label: 'Last', num: 1, val: m => m.last, cls: 'hide-sm' },
  ];
  const tbl = sortTable('catmer:' + name, mers, cols, 'total', -1);
  const merRows = tbl.rows.slice(0, 60).map(m => `<tr class="link" data-go="${esc(merHref(m.name))}"><td><a href="${merHref(m.name)}">${esc(title(m.name))}</a></td>
    <td class="hide-sm">${sparkline(D.baseIdx.map(i => m.values[i]), color, 80, 22)}</td><td class="num">${money(m.total)}</td>
    <td class="num hide-sm">${pct(c.total ? m.total / c.total : 0)}</td><td class="num">${m.count}</td><td class="num">${m.stats.change != null ? delta(m.stats.change, null, true) : '–'}</td><td class="num hide-sm">${dLabel(m.last)}</td></tr>`).join('');
  const peak = st.max;
  const tiles = [
    tile('Total', money(c.total, true), `${pct(c.share)} of all spending`),
    tile('Average month', money(st.avg, true), `${plural(c.count, 'purchase')} in total`),
    tile(`${title(windowName())} vs ${priorName()}`, st.change != null ? delta(st.change, null, true) : '–', st.change != null ? `${money(st.recent, true)}/mo vs ${money(st.prior, true)}/mo` : 'needs more months'),
    tile('Biggest month', peak ? money(peak.value, true) : '–', peak ? `<a href="${monthHref(D.months[peak.i])}">${mLabel(D.months[peak.i])} ›</a>` : ''),
    tile('Next month, if the trend holds', st.forecast != null ? money(st.forecast, true) : '–', labelHelp(st.label)),
  ];
  const id = 'cat:' + name; TXFIX[id] = { cat: name };
  return `${head}<h1>${sw(name)}${esc(name)} ${badge(st)}</h1><p class="sub">${money(c.total)} over ${plural(D.months.length, 'month')}</p>
  <div class="tiles">${tiles.join('')}</div>
  <h2>Month by month</h2><p class="desc">Click a month to see everything you spent that month.</p>
  <div class="card">${overlayLegend('', true)}<div style="height:8px"></div>${chart}${partialNote(D.months)}</div>
  <h2>Why is it changing?</h2><p class="desc">More purchases, or bigger ones?</p>
  ${trendExplainer(c)}${detailCharts(c, color)}
  <h2>Merchants</h2><p class="desc">${plural(mers.length, 'merchant')} in ${esc(name)}. Click one for its full history.</p>
  <div class="card scroll"><table><thead><tr>${tbl.head}</tr></thead><tbody>${merRows}</tbody></table></div>
  <h2>Transactions</h2>${txTable(id)}`;
};

VIEWS.merchants = () => {
  const q = S.merQ.toLowerCase();
  let rows = D.mers.filter(m => !q || m.name.includes(q) || m.category.toLowerCase().includes(q) || m.sample.toLowerCase().includes(q));
  const cols = [
    { key: 'name', label: 'Merchant', val: m => m.name },
    { key: 'cat', label: 'Category', val: m => m.category, cls: 'hide-sm' },
    { key: 'spark', label: 'Monthly', cls: 'hide-sm' },
    { key: 'total', label: 'Total', num: 1, val: m => m.total },
    { key: 'count', label: 'Purchases', num: 1, val: m => m.count },
    { key: 'avg', label: 'Avg purchase', num: 1, val: m => m.count ? m.total / m.count : 0, cls: 'hide-sm' },
    { key: 'change', label: 'Change', num: 1, val: m => m.stats.change ?? 0 },
    { key: 'last', label: 'Last', num: 1, val: m => m.last, cls: 'hide-sm' },
  ];
  const tbl = sortTable('mers', rows, cols, 'total', -1);
  const lim = S.merLimit || 100;
  const body = tbl.rows.slice(0, lim).map(m => `<tr class="link" data-go="${esc(merHref(m.name))}"><td><a href="${merHref(m.name)}">${esc(title(m.name))}</a><div class="small faint trunc">${esc(m.sample)}</div></td>
    <td class="hide-sm"><span class="name">${sw(m.category)}${esc(m.category)}</span></td><td class="hide-sm">${sparkline(D.baseIdx.map(i => m.values[i]), colorOf(m.category), 80, 22)}</td>
    <td class="num">${money(m.total)}</td><td class="num">${m.count}</td><td class="num hide-sm">${m.count ? money(m.total / m.count) : '–'}</td><td class="num">${m.stats.change != null ? delta(m.stats.change, null, true) : '–'}</td><td class="num hide-sm">${dLabel(m.last)}</td></tr>`).join('');
  const rec = RAW.recurring || [];
  const recRows = rec.map(r => `<tr class="link" data-go="${esc(merHref(r.merchant))}"><td><a href="${merHref(r.merchant)}">${esc(title(r.merchant))}</a><div class="small faint trunc">${esc(r.description)}</div></td>
    <td class="hide-sm">${esc(currentCat(r.merchant))}</td><td>${esc(r.frequency)}</td><td class="num">${money(r.amount)}</td><td class="num">${money(r.monthly_cost)}</td>
    <td class="num hide-sm">${dLabel(r.last)}</td><td class="num">${r.price_change >= 0.05 ? `<span class="badge up">▲ ${pct(r.price_change)}</span>` : r.price_change <= -0.05 ? `<span class="badge down">▼ ${pct(-r.price_change)}</span>` : ''}</td></tr>`).join('');
  return `<h1>Merchants</h1><p class="sub">${plural(D.mers.length, 'merchant')} in this period</p>
  <h2>Recurring payments & subscriptions</h2><p class="desc">Payments that repeat at a steady interval across all your statements. Price changes are flagged.</p>
  ${rec.length ? `<div class="card scroll"><table><thead><tr><th>Merchant</th><th class="hide-sm">Category</th><th>Every</th><th class="num">Amount</th><th class="num">≈ per month</th><th class="num hide-sm">Last</th><th class="num">Price</th></tr></thead><tbody>${recRows}</tbody></table>
    <div class="small muted" style="margin-top:6px">≈ ${money(sum(rec.map(r => r.monthly_cost)))} a month, ${money(sum(rec.map(r => r.monthly_cost)) * 12, true)} a year</div></div>` : '<p class="muted">None detected.</p>'}
  <h2>All merchants</h2>
  <div class="filters"><input type="search" placeholder="Search merchants…" value="${esc(S.merQ)}" data-merq aria-label="Search merchants"></div>
  <div class="card scroll" id="mertable"><table><thead><tr>${tbl.head}</tr></thead><tbody>${body}</tbody></table>
  ${tbl.rows.length > lim ? `<div style="margin-top:8px"><button class="btn" data-set="merLimit:${lim + 200}">Show more (${tbl.rows.length - lim} left)</button></div>` : ''}</div>`;
};
const currentCat = mer => overrides[mer] || ORIG_CAT[mer] || '';

VIEWS.merchant = key => {
  const m = D.merMap.get(key);
  const cat = currentCat(key);
  const head = crumbs([['Categories', '#/categories'], [cat, catHref(cat)], [title(key)]]);
  const recat = `<button class="btn" data-recat="${esc(key)}">Change category</button>`;
  if (!m) return head + `<h1>${esc(title(key))}</h1>` + noData('No spending with this merchant in the selected period.');
  const color = colorOf(cat), st = m.stats;
  const rec = (RAW.recurring || []).find(r => r.merchant === key);
  const tiles = [
    tile('Total', money(m.total, true), `${pct(m.share)} of all spending`),
    tile('Purchases', String(m.count), m.count ? `avg ${money(m.total / m.count)} each` : ''),
    tile('Average month', money(st.avg, true), st.change != null ? `${delta(st.change, null, true)} ${windowName()} vs ${priorName()}` : ''),
    tile('First – last', `<span style="font-size:17px">${dLabel(m.first)}</span>`, `to ${dLabel(m.last)}`),
  ];
  if (rec) tiles.push(tile('Recurring', money(rec.amount), `${rec.frequency}${rec.price_change >= 0.05 ? ` · <span class="up">▲ ${pct(rec.price_change)}</span>` : ''}`));
  const id = 'mer:' + key; TXFIX[id] = { mer: key };
  const chart = slot(w => columnChart({ width: w, months: D.months, series: [{ name: title(key), color, values: m.values }], stats: st, baseIdx: D.baseIdx, overlays: S.overlays, spikes: new Set(st.spikes.map(s => s.i)), go: monthHref, label: key + ' by month' }));
  return `${head}<h1>${esc(title(key))} ${badge(st)}</h1><p class="sub"><span class="name">${sw(cat)}<a href="${catHref(cat)}">${esc(cat)}</a></span> · ${recat}</p>
  <div class="tiles">${tiles.join('')}</div>
  <h2>Month by month</h2><div class="card">${overlayLegend('')}<div style="height:8px"></div>${chart}</div>
  <h2>Why is it changing?</h2>${trendExplainer(m)}${detailCharts(m, color)}
  <h2>Transactions</h2>${txTable(id)}`;
};

VIEWS.month = mo => {
  const i = D.idx.get(mo);
  const head = crumbs([['Overview', '#/overview'], [mLong(mo)]]);
  if (i == null) return head + noData('That month is outside the data.');
  const prev = i > 0 ? D.months[i - 1] : null, next = i < D.months.length - 1 ? D.months[i + 1] : null;
  const nav = `<span class="pager">${prev ? `<a class="btn" href="${monthHref(prev)}">‹ ${mShort(prev)}</a>` : ''}${next ? `<a class="btn" href="${monthHref(next)}">${mShort(next)} ›</a>` : ''}</span>`;
  const total = D.total[i], avg = D.avgMonth;
  const items = D.cats.map(c => ({ c, v: c.values[i], diff: c.values[i] - c.stats.avg })).filter(x => Math.abs(x.diff) >= 0.5 || x.v);
  const bars = items.filter(x => Math.abs(x.diff) >= Math.max(D.threshold * 0.25, 1)).sort((a, b) => b.diff - a.diff);
  const top = bars.length > 14 ? [...bars.slice(0, 8), ...bars.slice(-6)] : bars;
  const mtx = D.tx.filter(t => t.m === mo);
  const spendTx = mtx.filter(t => t.k === 'expense').sort((a, b) => b.a - a.a).slice(0, 8);
  const firstSeen = D.mers.filter(m => m.first.slice(0, 7) === mo && mo !== D.months[0]).sort((a, b) => b.total - a.total).slice(0, 8);
  const spikes = D.cats.flatMap(c => c.stats.spikes.filter(s => s.i === i).map(s => Object.assign({ cat: c.name }, s)));
  const biggest = [...items].sort((a, b) => b.v - a.v)[0];
  const tiles = [
    tile('Spent', money(total, true), `${plural(D.purchases[i], 'purchase')}${PARTIAL.has(mo) ? ' · partial month' : ''}`),
    tile('vs an average month', delta(total - avg, null, true), avg ? `${(total / avg).toFixed(2)}× the average of ${money(avg, true)}` : ''),
    tile('Biggest category', biggest ? esc(biggest.c.name) : '–', biggest ? money(biggest.v, true) : '', biggest ? catHref(biggest.c.name) : null),
    tile('Spikes', String(spikes.length), spikes.length ? spikes.map(s => esc(s.cat)).join(', ') : 'nothing unusual'),
  ];
  const id = 'month:' + mo; TXFIX[id] = { month: mo };
  const brows = Object.keys(BUDGETS).map(c => budgetRow(c, BUDGETS[c], mo));
  const budgetsHtml = brows.length ? `<h2>Budgets</h2><div class="card scroll"><table><tbody>${brows.map(b => `<tr><td>${b.cat === 'All spending' ? '<b>All spending</b>' : `<span class="name">${sw(b.cat)}${esc(b.cat)}</span>`}</td><td style="min-width:110px">${meter(b)}</td><td class="num">${money(b.spent)} <span class="faint">of ${money(b.limit)}</span></td><td>${bBadge(b.status)}</td></tr>`).join('')}</tbody></table></div>` : '';
  const tagged = [...new Set(mtx.flatMap(t => t.tags))];
  return `${head}<div class="head-row"><h1>${mLong(mo)}</h1><span class="pager">${nav}<button class="btn no-print" data-print>Print summary</button></span></div>
  <div class="tiles">${tiles.join('')}</div>${budgetsHtml}
  ${tagged.length ? `<p class="small" style="margin-top:12px">Tags this month: ${tagged.map(g => `<a class="tag" href="${tagHref(g)}">#${esc(g)}</a>`).join(' ')}</p>` : ''}
  <h2>Compared with an average month</h2><p class="desc">How much more (red) or less (green) you spent on each category than usual.</p>
  <div class="card">${top.length ? slot(w => divergingBars({ width: w, label: 'Category vs average', items: top.map(x => ({ name: x.c.name, value: x.diff, go: catHref(x.c.name),
    tip: `<b>${esc(x.c.name)}</b><div class="r"><span>${esc(mLabel(mo))}</span><span>${esc(money(x.v))}</span></div><div class="r"><span>Average month</span><span>${esc(money(x.c.stats.avg))}</span></div><div class="hint">Click to explore</div>` })) })) : '<p class="muted">A very ordinary month.</p>'}</div>
  <div class="cols" style="margin-top:12px">
    <div class="card"><h3>Biggest purchases</h3><table><tbody>${spendTx.map(t => `<tr class="link" data-go="${esc(merHref(t.mer))}"><td><span class="trunc">${esc(t.t)}</span><div class="small faint">${dLabel(t.d)} · ${esc(t.c)}</div></td><td class="num">${money(t.a)}</td></tr>`).join('') || '<tr><td class="muted">None</td></tr>'}</tbody></table></div>
    <div class="card"><h3>First time this month</h3>${firstSeen.length ? `<table><tbody>${firstSeen.map(m => `<tr class="link" data-go="${esc(merHref(m.name))}"><td><a href="${merHref(m.name)}">${esc(title(m.name))}</a><div class="small faint">${esc(m.category)}</div></td><td class="num">${money(m.values[i])}</td></tr>`).join('')}</tbody></table>` : '<p class="small muted">No new merchants.</p>'}</div>
  </div>
  <div class="print-break"></div><h2>All transactions in ${mLong(mo)}</h2>${txTable(id)}`;
};

VIEWS.transactions = (_, params) => {
  const id = 'all';
  const f = S.tx[id] = S.tx[id] || { q: '', cat: '', kind: '', month: '', tag: '', sort: 'd', dir: -1, limit: 200 };
  if (params) { for (const k of ['cat', 'kind', 'month', 'q', 'tag']) if (params.has(k)) f[k] = params.get(k); }
  TXFIX[id] = {};
  return `<h1>Transactions</h1><p class="sub">Every transaction in the period. Click a category to re-categorise that merchant everywhere; click ✎ to tag a transaction or mark it as shared.</p><div style="height:12px"></div>${txTable(id, true)}`;
};


// ------------------------------------------------------------------ budgets
const LAST_MONTH = ALL_MONTHS[ALL_MONTHS.length - 1];
function monthElapsed(m) {
  // Share of the month the statements cover (1 for any finished month).
  if (m !== LAST_MONTH || !PARTIAL.has(m)) return 1;
  const dim = new Date(+m.slice(0, 4), +m.slice(5, 7), 0).getDate();
  return Math.max(+DEND.slice(8, 10) / dim, 0.05);
}
function spentIn(cat, m) {
  const i = D.idx.get(m);
  if (i == null) return sum(TX.filter(t => t.m === m && isSpend(t) && (cat === 'All spending' || t.c === cat)).map(t => t.a));
  if (cat === 'All spending') return D.total[i];
  const c = D.catMap.get(cat);
  return c ? c.values[i] : 0;
}
function budgetRow(cat, limit, m) {
  const spent = spentIn(cat, m), el = monthElapsed(m);
  const projected = el < 1 ? spent / el : spent;
  const status = spent > limit ? 'over' : projected > limit * 1.02 ? 'risk' : 'ok';
  return { cat, limit, spent, projected, status, elapsed: el, left: limit - spent };
}
const BSTATUS = { ok: ['✓', 'On track', 'good'], risk: ['!', 'At risk', 'warn'], over: ['✗', 'Over', 'bad'] };
const bBadge = st => `<span class="badge st-${BSTATUS[st][2]}">${BSTATUS[st][0]} ${BSTATUS[st][1]}</span>`;
function meter(b) {
  const w = Math.min(b.spent / b.limit, 1) * 100, pace = b.elapsed < 1 ? `<i class="pace" style="left:${(b.elapsed * 100).toFixed(1)}%" title="Where you'd be if spending evenly"></i>` : '';
  return `<span class="meter m-${BSTATUS[b.status][2]}"><i style="width:${w.toFixed(1)}%"></i>${pace}</span>`;
}
function niceRound(v) {
  if (v <= 0) return 0;
  const mag = 10 ** Math.floor(Math.log10(v)), step = mag / 10;
  return Math.ceil(v / step) * step;
}
function budgetAlerts(m) {
  return Object.entries(BUDGETS).map(([c, l]) => budgetRow(c, l, m)).filter(b => b.status !== 'ok');
}

VIEWS.budgets = (_, params) => {
  const months = D.months.length ? D.months : ALL_MONTHS;
  const m = params && params.get('m') && months.includes(params.get('m')) ? params.get('m') : months[months.length - 1];
  const el = monthElapsed(m);
  const cats = Object.keys(BUDGETS).sort((a, b) => (a === 'All spending' ? -1 : b === 'All spending' ? 1 : 0) || a.localeCompare(b));
  const rows = cats.map(c => budgetRow(c, BUDGETS[c], m));
  const histMonths = ALL_MONTHS.filter(x => x <= m && !PARTIAL.has(x)).slice(-6);
  const hist = c => histMonths.map(x => { const v = spentIn(c, x), over = v > BUDGETS[c]; return `<i class="hd ${over ? 'over' : 'ok'}" title="${esc(mLabel(x))}: ${esc(money(v))}${over ? ' – over' : ''}"></i>`; }).join('');
  const sel = `<select data-budgetmonth aria-label="Month">${months.slice().reverse().map(x => `<option value="${x}"${x === m ? ' selected' : ''}>${mLabel(x)}${x === LAST_MONTH && PARTIAL.has(x) ? ' (in progress)' : ''}</option>`).join('')}</select>`;
  const body = rows.map(b => `<tr><td><span class="name">${b.cat === 'All spending' ? '<i class="swatch" style="background:var(--text)"></i><b>All spending</b>' : `${sw(b.cat)}<a href="${catHref(b.cat)}">${esc(b.cat)}</a>`}</span></td>
    <td class="num">${money(b.spent)}</td><td style="min-width:120px">${meter(b)}</td>
    <td class="num"><input class="budget-in" type="number" min="0" step="any" inputmode="decimal" value="${b.limit}" data-budget="${esc(b.cat)}" aria-label="Budget for ${esc(b.cat)}"></td>
    <td class="num">${b.left >= 0 ? `${money(b.left)} left` : `<span class="up">${money(-b.left)} over</span>`}${el < 1 ? `<div class="small faint">heading for ${money(b.projected, true)}</div>` : ''}</td>
    <td>${bBadge(b.status)}</td><td class="hide-sm"><span class="hist">${hist(b.cat)}</span></td>
    <td><button class="linkbtn small" data-budgetrm="${esc(b.cat)}" aria-label="Remove budget">Remove</button></td></tr>`).join('');
  // Suggestions for categories without a budget: typical (median) month, rounded up.
  const base = D.baseIdx.slice(-6);
  const suggest = [{ name: 'All spending', values: D.total }, ...D.cats.filter(c => (KINDS[c.name] || 'expense') === 'expense')]
    .filter(c => !(c.name in BUDGETS))
    .map(c => ({ name: c.name, v: niceRound(median(base.map(i => c.values[i]))) })).filter(x => x.v > 0).slice(0, 12);
  const over = rows.filter(b => b.status === 'over').length, risk = rows.filter(b => b.status === 'risk').length;
  const totalB = rows.filter(b => b.cat !== 'All spending').reduce((a, b) => a + b.limit, 0);
  const tiles = rows.length ? [
    tile('Budgets', String(rows.length), totalB ? `${money(totalB, true)} a month across categories` : ''),
    tile('Over budget', `<span class="${over ? 'up' : ''}">${over}</span>`, over ? rows.filter(b => b.status === 'over').map(b => esc(b.cat)).join(', ') : 'none'),
    tile('At risk', String(risk), el < 1 ? `if you keep spending at this pace (${pct(el)} of the month gone)` : 'only for a month in progress'),
  ] : [];
  return `<div class="head-row"><h1>Budgets</h1><span class="ctl">Month ${sel}</span></div>
  <p class="sub">${el < 1 ? `${mLong(m)} is in progress: your statements run to ${dLabel(DEND)}. The marker on each bar shows where you'd be spending evenly.` : `How ${mLong(m)} went against your monthly budgets.`}</p>
  ${rows.length ? `<div class="tiles">${tiles.join('')}</div>
  <h2>${mLong(m)}</h2><div class="card scroll"><table><thead><tr><th>Budget</th><th class="num">Spent</th><th></th><th class="num">Monthly limit</th><th class="num">Left</th><th>Status</th><th class="hide-sm" title="Green = within budget, red = over">Last ${histMonths.length} months <span class="faint">(<span style="color:var(--good)">●</span> ok <span style="color:var(--critical)">●</span> over)</span></th><th></th></tr></thead><tbody>${body}</tbody></table></div>`
    : `<div class="card empty" style="margin-top:16px">No budgets yet. Pick one below to start, or type your own.</div>`}
  <h2>Add a budget</h2><p class="desc">Suggested from your typical month (the median of the last ${base.length} full months), rounded up. Click to add, then adjust the amount.</p>
  <div class="chips">${suggest.map(x => `<button class="chip" data-budgetadd="${esc(x.name)}:${x.v}">${x.name === 'All spending' ? '' : sw(x.name)}${esc(x.name)} · ${money(x.v, true)}</button>`).join('') || '<span class="muted small">Every category already has a budget.</span>'}</div>
  <p class="small faint" style="margin-top:14px">Budget changes made here are kept in this browser. Use “Save my changes” at the top to make them permanent${RAW.home ? '' : ' (or keep budgets in a config file and run with --config)'}.</p>`;
};

// ------------------------------------------------------------------ checks
const checkKey = c => c.kind + ':' + c.title;
const CHECK_ICON = { duplicate: '⧉', fees: '%', price: '▲', 'new-recurring': '✦', subscriptions: '↻', foreign: '¤' };
VIEWS.checks = (_, params) => {
  const all = RAW.checks || [];
  const showAll = params && params.get('all') === '1';
  const open = all.filter(c => !dismissed[checkKey(c)]);
  const list = showAll ? all : open;
  const card = c => {
    const items = (c.items || []).map(i => TXID.get(i)).filter(Boolean);
    const isDone = !!dismissed[checkKey(c)];
    const rows = items.slice(0, 12).map(t => `<tr class="link" data-go="${esc(merHref(t.mer))}"><td class="num">${dLabel(t.d)}</td><td><span class="trunc">${esc(t.t)}</span></td><td class="num">${money(t.a)}</td></tr>`).join('');
    return `<div class="card check ${c.severity}${isDone ? ' done' : ''}"><h3><span class="ic ${c.severity === 'warn' ? 'up' : ''}">${CHECK_ICON[c.kind] || '•'}</span> ${esc(c.title)}</h3>
      <p class="small" style="margin:4px 0 8px">${esc(c.detail)}</p>
      ${c.merchant ? `<a class="small" href="${merHref(c.merchant)}">See ${esc(title(c.merchant))} ›</a>` : ''}
      ${rows ? `<table class="small"><tbody>${rows}</tbody></table>${items.length > 12 ? `<div class="small faint">and ${items.length - 12} more</div>` : ''}` : ''}
      <div style="margin-top:8px"><button class="linkbtn small" data-dismiss="${esc(checkKey(c))}">${isDone ? '↺ Show again' : '✓ Mark as reviewed'}</button></div></div>`;
  };
  const warn = list.filter(c => c.severity === 'warn'), info = list.filter(c => c.severity !== 'warn');
  const nDone = all.length - open.length;
  return `<h1>Checks</h1><p class="sub">Things in your statements worth a second look: possible double charges, fees and interest, subscription changes, foreign-currency spending.</p>
  ${!all.length ? '<div class="card empty" style="margin-top:16px">✓ Nothing to flag. No duplicate charges, fees or subscription changes found.</div>' : ''}
  ${warn.length ? `<h2>Worth a look</h2><div class="cols">${warn.map(card).join('')}</div>` : ''}
  ${info.length ? `<h2>Good to know</h2><div class="cols">${info.map(card).join('')}</div>` : ''}
  ${all.length && !list.length ? '<div class="card empty" style="margin-top:16px">✓ All reviewed.</div>' : ''}
  ${nDone ? `<p class="small" style="margin-top:14px">${showAll ? `<a href="#/checks">Hide reviewed</a>` : `<a href="#/checks?all=1">Show ${plural(nDone, 'reviewed item')}</a>`}</p>` : ''}
  <p class="small faint">Checks cover all your statements, whatever period is selected.</p>`;
};

// ------------------------------------------------------------------ tags
function tagStats(g) {
  const tx = TX.filter(t => t.tags.includes(g));
  const spend = tx.filter(isSpend);
  const byCat = {};
  for (const t of spend) byCat[t.c] = (byCat[t.c] || 0) + t.a;
  return { tx, total: sum(spend.map(t => t.a)), first: tx.length ? tx[0].d : null, last: tx.length ? tx[tx.length - 1].d : null, byCat };
}
VIEWS.tags = () => {
  const tags = allTags();
  const help = `<div class="card small" style="margin-top:16px"><b>How to tag</b>: click ✎ next to any transaction (in Transactions, a month, a category…) and add a tag such as <i>Goa trip</i> or <i>Wedding</i>.
    To tag lots at once, add a rule to your rules file, e.g. <code>[tags."Goa trip"]</code> with <code>from = 2026-05-01</code>, <code>to = 2026-05-20</code>.</div>`;
  if (!tags.length) return `<h1>Tags</h1><p class="sub">Group spending across categories: a trip, a wedding, a home project.</p>${help}`;
  const cards = tags.map(g => {
    const st = tagStats(g);
    const cats = Object.entries(st.byCat).sort((a, b) => b[1] - a[1]);
    const bar = cats.map(([c, v]) => `<i style="width:${(v / (st.total || 1) * 100).toFixed(1)}%;background:${colorOf(c)}" title="${esc(c)}: ${esc(money(v))}"></i>`).join('');
    return `<a class="card catcard" href="${tagHref(g)}"><div class="head-row"><b>#${esc(g)}</b><span class="small faint">${plural(st.tx.length, 'transaction')}</span></div>
      <div class="amt">${money(st.total, true)}</div><div class="meta"><span>${st.first ? dLabel(st.first) + (st.last !== st.first ? ' – ' + dLabel(st.last) : '') : ''}</span></div>
      <div class="stackbar">${bar}</div><div class="meta" style="margin-top:4px"><span>${cats.slice(0, 3).map(([c]) => esc(c)).join(', ')}</span></div></a>`;
  }).join('');
  return `<h1>Tags</h1><p class="sub">What each trip, event or project really cost, across categories. Tags ignore the period filter.</p>
  <div class="catgrid" style="margin-top:16px">${cards}</div>${help}`;
};
VIEWS.tag = g => {
  const st = tagStats(g);
  const head = crumbs([['Tags', '#/tags'], ['#' + g]]);
  if (!st.tx.length) return head + `<h1>#${esc(g)}</h1><div class="card empty">No transactions have this tag any more.</div>`;
  const cats = Object.entries(st.byCat).sort((a, b) => b[1] - a[1]);
  const max = cats.length ? cats[0][1] : 1;
  const shared = st.tx.filter(t => t.share !== 1);
  const days = (new Date(st.last) - new Date(st.first)) / 864e5 + 1;
  const id = 'tag:' + g; TXFIX[id] = { tag: g };
  return `${head}<h1>#${esc(g)}</h1><p class="sub">${dLabel(st.first)}${st.last !== st.first ? ' – ' + dLabel(st.last) : ''}</p>
  <div class="tiles">${tile('Total cost', money(st.total, true), shared.length ? `your share; ${plural(shared.length, 'shared item')}` : '')}
    ${tile('Transactions', String(st.tx.length), days > 1 ? `over ${Math.round(days)} days` : '')}
    ${tile('Per day', days > 1 ? money(st.total / days, true) : '–', '')}
    ${tile('vs your average month', D.avgMonth ? pct(st.total / D.avgMonth) : '–', 'of a typical month’s spending')}</div>
  <h2>By category</h2><div class="card"><table><tbody>${cats.map(([c, v]) => `<tr class="link" data-go="${esc(catHref(c))}"><td><span class="name">${sw(c)}${esc(c)}</span></td><td>${shareBar(v, max, colorOf(c))}</td><td class="num">${money(v)}</td><td class="num faint">${pct(v / (st.total || 1))}</td></tr>`).join('')}</tbody></table></div>
  <h2>Transactions</h2>${txTable(id)}`;
};

// ------------------------------------------------------------------ transactions table
function txTable(id, full) {
  const f = S.tx[id] = S.tx[id] || { q: '', cat: '', kind: '', month: '', tag: '', sort: 'd', dir: -1, limit: 100 };
  const fx = TXFIX[id] || {};
  const tags = allTags();
  const catOpts = [...new Set(D.tx.map(t => t.c))].sort().map(c => `<option${f.cat === c ? ' selected' : ''}>${esc(c)}</option>`).join('');
  const kinds = [['', 'All types'], ['expense', 'Purchases'], ['refund', 'Refunds'], ['income', 'Income'], ['investment', 'Investments'], ['transfer', 'Transfers (not counted)']];
  const controls = `<div class="filters"><input type="search" placeholder="Search description…" value="${esc(f.q)}" data-txf="${esc(id)}:q" aria-label="Search">
    ${fx.cat ? '' : `<select data-txf="${esc(id)}:cat" aria-label="Category"><option value="">All categories</option>${catOpts}</select>`}
    ${fx.mer ? '' : `<select data-txf="${esc(id)}:kind" aria-label="Type">${kinds.map(([k, t]) => `<option value="${k}"${f.kind === k ? ' selected' : ''}>${t}</option>`).join('')}</select>`}
    ${fx.month || !full ? '' : `<select data-txf="${esc(id)}:month" aria-label="Month"><option value="">All months</option>${D.months.map(m => `<option value="${m}"${f.month === m ? ' selected' : ''}>${mLabel(m)}</option>`).join('')}</select>`}
    ${fx.tag || !tags.length ? '' : `<select data-txf="${esc(id)}:tag" aria-label="Tag"><option value="">All tags</option><option value="*"${f.tag === '*' ? ' selected' : ''}>Any tag</option><option value="~"${f.tag === '~' ? ' selected' : ''}>Shared (split)</option>${tags.map(g => `<option${f.tag === g ? ' selected' : ''}>${esc(g)}</option>`).join('')}</select>`}</div>`;
  return `<div data-txt="${esc(id)}">${controls}<div class="txbody">${txBody(id)}</div></div>`;
}
function txBody(id) {
  const f = S.tx[id], fx = TXFIX[id] || {}, q = f.q.trim().toLowerCase();
  const tagOk = (tag, t) => !tag || (tag === '*' ? t.tags.length > 0 : tag === '~' ? t.share !== 1 : t.tags.includes(tag));
  const pool = fx.ids ? fx.ids.map(i => TXID.get(i)).filter(Boolean) : fx.tag ? TX : D.tx;
  let rows = pool.filter(t => (!fx.cat || t.c === fx.cat) && (!fx.mer || t.mer === fx.mer) && (!fx.month || t.m === fx.month)
    && tagOk(fx.tag, t) && tagOk(f.tag, t)
    && (!f.cat || t.c === f.cat) && (!f.kind || t.k === f.kind) && (!f.month || t.m === f.month)
    && (!q || t.t.toLowerCase().includes(q) || t.mer.includes(q) || t.s.toLowerCase().includes(q)));
  const key = { d: t => t.d + String(t.i).padStart(7, '0'), t: t => t.t.toLowerCase(), c: t => t.c, k: t => t.k, s: t => t.s, a: t => t.a }[f.sort] || (t => t.d);
  rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * f.dir; });
  const spent = sum(rows.filter(isSpend).map(t => t.a)), got = -sum(rows.filter(t => t.k === 'income').map(t => t.a));
  const th = (k, label, cls) => `<th class="${cls || ''}" data-txsort="${esc(id)}:${k}">${label}${f.sort === k ? ` <span class="arrow">${f.dir > 0 ? '↑' : '↓'}</span>` : ''}</th>`;
  const body = rows.slice(0, f.limit).map(t => `<tr><td class="num">${dLabel(t.d)}</td>
    <td><a href="${merHref(t.mer)}" class="trunc" title="${esc(t.t)}">${esc(t.t)}</a>${t.tags.length ? `<div class="tags">${t.tags.map(g => `<a class="tag" href="${tagHref(g)}">#${esc(g)}</a>`).join('')}</div>` : ''}</td>
    <td><button class="catbtn" data-recat="${esc(t.mer)}" title="Change category for all ${esc(title(t.mer))} transactions">${sw(t.c)}${esc(t.c)}<span class="caret">▾</span></button></td>
    <td class="kind hide-sm">${{ expense: 'purchase', refund: 'refund', income: 'income', investment: 'investment', transfer: 'transfer' }[t.k]}</td>
    <td class="small faint hide-sm">${esc(t.s)}</td><td class="num">${t.a < 0 ? `<span class="down">${money(t.a)}</span>` : money(t.a)}${t.share !== 1 ? `<div class="small faint">${pct(t.share)} of ${money(t.orig)}</div>` : ''}</td>
    <td class="edit-cell"><button class="iconbtn sm" data-edit="${esc(t.id)}" title="Tag or split this transaction" aria-label="Tag or split this transaction">✎</button></td></tr>`).join('');
  return `<div class="small muted" style="margin-bottom:6px">${plural(rows.length, 'transaction')} · spent ${money(spent)}${got ? ` · received ${money(got)}` : ''}</div>
  <div class="card scroll"><table><thead><tr>${th('d', 'Date', 'num')}${th('t', 'Description')}${th('c', 'Category')}${th('k', 'Type', 'hide-sm')}${th('s', 'Statement', 'hide-sm')}${th('a', 'Amount', 'num')}<th class="edit-cell"></th></tr></thead>
  <tbody>${body || '<tr><td colspan="7" class="muted">No transactions match.</td></tr>'}</tbody></table>
  ${rows.length > f.limit ? `<div style="margin-top:8px"><button class="btn" data-txmore="${esc(id)}">Show more (${rows.length - f.limit} left)</button></div>` : ''}</div>`;
}

// ------------------------------------------------------------------ re-categorising
let popEl = null;
function closePop() { if (popEl) { popEl.remove(); popEl = null; } }
function openRecat(btn) {
  closePop();
  const mer = btn.dataset.recat, cur = currentCat(mer);
  const n = TX.filter(t => t.mer === mer).length;
  const cats = Object.keys(KINDS).sort();
  popEl = document.createElement('div');
  popEl.className = 'pop';
  popEl.innerHTML = `<div>Move <b>${esc(title(mer))}</b> (${plural(n, 'transaction')}) to:</div>
    <select aria-label="New category">${cats.map(c => `<option${c === cur ? ' selected' : ''}>${esc(c)}</option>`).join('')}</select>
    <div class="row"><input type="text" placeholder="…or a new category" aria-label="New category name"><button class="btn primary">Move</button></div>
    ${overrides[mer] ? `<div style="margin-top:8px"><button class="linkbtn" data-reset="${esc(mer)}">Restore original (${esc(ORIG_CAT[mer])})</button></div>` : ''}`;
  document.body.appendChild(popEl);
  const r = btn.getBoundingClientRect();
  popEl.style.left = Math.max(8, Math.min(r.left, innerWidth - 296)) + 'px';
  popEl.style.top = (r.bottom + 6 + popEl.offsetHeight > innerHeight ? Math.max(8, r.top - popEl.offsetHeight - 6) : r.bottom + 6) + 'px';
  const sel = $('select', popEl), inp = $('input', popEl);
  const go = () => { const v = inp.value.trim() || sel.value; closePop(); if (v && v !== cur) setOverride(mer, v); };
  sel.addEventListener('change', go);
  $('button.primary', popEl).addEventListener('click', go);
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') go(); if (e.key === 'Escape') closePop(); });
  const rb = $('[data-reset]', popEl);
  if (rb) rb.addEventListener('click', () => { closePop(); setOverride(mer, ORIG_CAT[mer]); });
  sel.focus();
}
function setOverride(mer, cat) {
  const before = overrides[mer];
  if (cat === ORIG_CAT[mer]) delete overrides[mer]; else overrides[mer] = cat;
  store.set('overrides', overrides);
  refresh();
  const n = TX.filter(t => t.mer === mer).length;
  toast(`Moved ${plural(n, 'transaction')} from ${title(mer)} to ${cat}.`, () => {
    if (before) overrides[mer] = before; else delete overrides[mer];
    store.set('overrides', overrides); refresh();
  });
}
function refresh() { applyOverrides(); assignColors(); derive(); render(false); }
let toastTimer;
function toast(msg, undo) {
  $$('.toast').forEach(e => e.remove());
  const el = document.createElement('div');
  el.className = 'toast'; el.setAttribute('role', 'status');
  el.innerHTML = `<span>${esc(msg)}</span>${undo ? '<button>Undo</button>' : ''}`;
  document.body.appendChild(el);
  if (undo) $('button', el).addEventListener('click', () => { el.remove(); undo(); });
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.remove(), 7000);
}
function openEdit(btn) {
  closePop();
  const t = TXID.get(btn.dataset.edit);
  if (!t) return;
  let tags = [...t.tags];
  const shares = [[1, 'All mine'], [0.5, 'Half'], [1 / 3, 'A third'], [0.25, 'A quarter'], [0, 'None (fully repaid)']];
  popEl = document.createElement('div');
  popEl.className = 'pop';
  const known = allTags();
  const draw = () => {
    popEl.innerHTML = `<div class="small faint">${dLabel(t.d)} · ${money(t.orig)}</div><div style="font-weight:600;margin:2px 0 8px">${esc(t.t)}</div>
    <div>Tags <span class="faint small">(a trip, an event, a project)</span></div>
    <div class="tags" style="margin:4px 0">${tags.map((g, k) => `<span class="tag">#${esc(g)} <button class="linkbtn" data-untag="${k}" aria-label="Remove tag">×</button></span>`).join('') || '<span class="small faint">none</span>'}</div>
    <div class="row" style="margin-top:4px"><input type="text" list="ss-taglist" placeholder="Add a tag…" aria-label="Add a tag"><button class="btn" data-addtag>Add</button></div>
    <datalist id="ss-taglist">${known.map(g => `<option value="${esc(g)}">`).join('')}</datalist>
    <div style="margin-top:10px">Your share <span class="faint small">(for shared costs someone pays you back for)</span></div>
    <select data-share aria-label="Your share">${shares.map(([v, l]) => `<option value="${v}"${Math.abs(v - t.share) < 0.001 ? ' selected' : ''}>${l} · ${pct(v)}</option>`).join('')}
      ${shares.some(([v]) => Math.abs(v - t.share) < 0.001) ? '' : `<option value="${t.share}" selected>${pct(t.share)}</option>`}<option value="custom">Other %…</option></select>
    <div class="row"><span class="spacer"></span><button class="btn" data-cancel>Cancel</button><button class="btn primary" data-save>Save</button></div>`;
  };
  draw();
  document.body.appendChild(popEl);
  const r = btn.getBoundingClientRect();
  popEl.style.left = Math.max(8, Math.min(r.right - 280, innerWidth - 296)) + 'px';
  popEl.style.top = (r.bottom + 6 + popEl.offsetHeight > innerHeight ? Math.max(8, r.top - popEl.offsetHeight - 6) : r.bottom + 6) + 'px';
  const addTag = () => { const inp = $('input', popEl), v = inp.value.trim().replace(/^#/, ''); if (v && !tags.includes(v)) tags.push(v); const share = $('[data-share]', popEl).value; draw(); $('[data-share]', popEl).value = share; $('input', popEl).focus(); };
  popEl.addEventListener('click', e => {
    const el = e.target;
    if (el.matches('[data-addtag]')) addTag();
    else if (el.matches('[data-untag]')) { tags.splice(+el.dataset.untag, 1); const share = $('[data-share]', popEl).value; draw(); $('[data-share]', popEl).value = share; }
    else if (el.matches('[data-cancel]')) closePop();
    else if (el.matches('[data-save]')) {
      const pending = $('input', popEl).value.trim().replace(/^#/, '');
      if (pending && !tags.includes(pending)) tags.push(pending);
      let share = $('[data-share]', popEl).value;
      if (share === 'custom') { const p = prompt('Your share, in percent (0-100):', String(Math.round(t.share * 100))); if (p == null) return; share = Math.min(100, Math.max(0, +p || 0)) / 100; }
      closePop();
      setTxEdit(t, tags, +share);
    }
  });
  popEl.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input')) { e.preventDefault(); addTag(); } if (e.key === 'Escape') closePop(); });
  $('input', popEl).focus();
}
function setTxEdit(t, tags, share) {
  const before = txedits[t.id];
  const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
  if (same(tags, t.tags0) && Math.abs(share - t.share0) < 1e-9) delete txedits[t.id];
  else txedits[t.id] = { tags, share };
  store.set('txedits', txedits);
  refresh();
  const what = [tags.length ? 'tags: ' + tags.join(', ') : 'no tags', share !== 1 ? `your share ${pct(share)}` : ''].filter(Boolean).join(' · ');
  toast(`Saved: ${what}.`, () => { if (before) txedits[t.id] = before; else delete txedits[t.id]; store.set('txedits', txedits); refresh(); });
}
function setBudget(cat, amount) {
  const base = (RAW.budgets || {})[cat];
  if (amount == null || !(amount > 0)) { if (base != null) budgetEdits[cat] = null; else delete budgetEdits[cat]; }
  else if (base === amount) delete budgetEdits[cat];
  else budgetEdits[cat] = amount;
  store.set('budgets', budgetEdits);
  refresh();
}
function rulesToml() {
  const by = {};
  for (const [mer, cat] of Object.entries(overrides)) (by[cat] = by[cat] || []).push(mer);
  let out = '';
  for (const cat of Object.keys(by).sort()) {
    out += `\n[categories.${JSON.stringify(cat)}]\n`;
    if ((KINDS[cat] || 'expense') !== 'expense' && RAW.kinds[cat]) out += `kind = "${KINDS[cat]}"\n`;
    out += `merchants = [${by[cat].sort().map(m => JSON.stringify(m)).join(', ')}]\n`;
  }
  const tagged = {}, shares = {};
  for (const [id, e] of Object.entries(txedits)) {
    const t = TXID.get(id); if (!t) continue;
    for (const g of e.tags || []) if (!t.tags0.includes(g)) (tagged[g] = tagged[g] || []).push(id);
    if (e.share != null && Math.abs(e.share - t.share0) > 1e-9) (shares[e.share] = shares[e.share] || []).push(id);
  }
  for (const g of Object.keys(tagged).sort()) out += `\n[tags.${JSON.stringify(g)}]\ntransactions = [${tagged[g].map(i => JSON.stringify(i)).join(', ')}]\n`;
  for (const sh of Object.keys(shares)) out += `\n[[splits]]\nshare = ${+(+sh).toFixed(4)}\ntransactions = [${shares[sh].map(i => JSON.stringify(i)).join(', ')}]\n`;
  return out;
}
function budgetsToml() {
  const keys = Object.keys(BUDGETS);
  if (!keys.length) return '[budgets]\n';
  return '[budgets]\n' + keys.map(k => `${JSON.stringify(k)} = ${BUDGETS[k]}`).join('\n') + '\n';
}
function exportModal() {
  const rules = rulesToml().trim(), budgets = Object.keys(budgetEdits).length ? budgetsToml() : '';
  const home = RAW.home;
  const block = (title, file, text, how) => `<h4 style="margin:14px 0 4px">${title}</h4><p class="small muted" style="margin:0 0 6px">${how}</p>
    <textarea readonly rows="8">${esc(text)}</textarea>
    <div class="pager" style="margin-top:6px"><a class="btn primary" download="${file}" href="data:text/plain;charset=utf-8,${encodeURIComponent(text + '\n')}">Download ${file}</a><button class="btn" data-copy>Copy</button></div>`;
  const bg = document.createElement('div');
  bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal" role="dialog" aria-label="Save my changes"><h3>Keep your changes</h3>
  <p class="small muted">Your edits are only saved in this browser. To use them in every future report, add these lines to your settings files.</p>
  ${rules ? block('Categories, tags and shares', 'rules.toml', rules, home ? `Paste at the end of <code>${esc(home)}/rules.toml</code> (open it with TextEdit).` : 'Save as <code>my_rules.toml</code> and run with <code>--rules my_rules.toml</code>.') : ''}
  ${budgets ? block('Budgets', 'config.toml', budgets.trim(), home ? `Replace the <code>[budgets]</code> section of <code>${esc(home)}/config.toml</code> with this.` : 'Save as <code>config.toml</code> and run with <code>--config config.toml</code>.') : ''}
  <p class="small">${home ? 'Then run <code>spendstories report</code> (or double-click “Update Report”). Once the files have them, you can click “Clear browser edits”.' : ''}</p>
  <div class="pager"><span class="spacer"></span><button class="btn" data-close>Close</button></div></div>`;
  document.body.appendChild(bg);
  bg.addEventListener('click', e => {
    if (e.target === bg || e.target.matches('[data-close]')) bg.remove();
    if (e.target.matches('[data-copy]')) { const ta = e.target.parentElement.previousElementSibling; ta.select(); try { document.execCommand('copy'); e.target.textContent = 'Copied'; } catch (err) { /* select is enough */ } }
  });
}

// ------------------------------------------------------------------ shell & routing
function shell() {
  document.getElementById('app').innerHTML = `
  <header class="top"><div class="bar">
    <a class="brand" href="#/overview">Spend Stories</a><span class="lock" title="This page was generated on your computer and cannot load anything from the internet.">🔒 Offline</span>
    <span class="spacer"></span>
    <span class="ctl"><label for="ss-range">Period</label><select id="ss-range">${[['all', 'All time'], ['12', 'Last 12 months'], ['6', 'Last 6 months'], ['3', 'Last 3 months'], ['ytd', 'This year'], ['custom', 'Custom…']].map(([k, t]) => `<option value="${k}">${t}</option>`).join('')}</select></span>
    <span class="ctl" id="ss-custom" hidden><select id="ss-from" aria-label="From">${ALL_MONTHS.map(m => `<option value="${m}">${mLabel(m)}</option>`).join('')}</select>–<select id="ss-to" aria-label="To">${ALL_MONTHS.map(m => `<option value="${m}">${mLabel(m)}</option>`).join('')}</select></span>
    <button class="iconbtn" id="ss-theme" title="Light / dark" aria-label="Toggle light or dark theme">☾</button>
  </div><nav class="tabs" aria-label="Sections">
    <a href="#/overview" data-tab="overview">Overview</a><a href="#/trends" data-tab="trends">Trends</a><a href="#/budgets" data-tab="budgets">Budgets</a>
    <a href="#/categories" data-tab="categories">Categories</a><a href="#/tags" data-tab="tags">Tags</a><a href="#/merchants" data-tab="merchants">Merchants</a>
    <a href="#/transactions" data-tab="transactions">Transactions</a><a href="#/checks" data-tab="checks">Checks<span class="count" id="ss-checks-n"></span></a></nav></header>
  <div class="changes" id="ss-changes"></div>
  <main id="ss-view"></main>
  <footer>Spending = purchases minus refunds. Card bill payments and transfers between your own accounts aren't counted, so nothing is counted twice. Investments are shown separately.
  ${RAW.warnings && RAW.warnings.length ? `<details style="margin-top:8px"><summary>Notes on the input files (${RAW.warnings.length})</summary><ul>${RAW.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></details>` : ''}
  <div style="margin-top:6px">Generated ${esc(RAW.generated)} from ${RAW.sources.map(esc).join(', ')}.</div></footer>
  <div id="tip" role="tooltip"></div>`;
}

function parseRoute() {
  const h = decodeURIComponent((location.hash || '#/overview').slice(2));
  const [path, query] = h.split('?');
  const parts = path.split('/');
  const view = parts[0] || 'overview';
  const arg = parts.slice(1).join('/');
  return { view: VIEWS[view] ? view : 'overview', arg, params: query ? new URLSearchParams(query) : null, key: location.hash };
}
const TAB = { overview: 'overview', month: 'overview', trends: 'trends', budgets: 'budgets', categories: 'categories', category: 'categories', tags: 'tags', tag: 'tags', merchants: 'merchants', merchant: 'merchants', transactions: 'transactions', checks: 'checks' };
let lastKey = null;
function render(scroll = true) {
  closePop();
  CH = {};
  const r = parseRoute();
  if (r.view === 'month' && !D.idx.has(r.arg) && ALL_MONTHS.includes(r.arg) && S.range !== 'all') { S.range = 'all'; derive(); }
  $$('[data-tab]').forEach(a => a.classList.toggle('on', a.dataset.tab === TAB[r.view]));
  $('#ss-range').value = S.range;
  $('#ss-custom').hidden = S.range !== 'custom';
  $('#ss-from').value = S.from; $('#ss-to').value = S.to;
  const nc = nChanges(), parts = [];
  if (Object.keys(overrides).length) parts.push(plural(Object.keys(overrides).length, 'category fix'));
  if (Object.keys(txedits).length) parts.push(plural(Object.keys(txedits).length, 'tagged/split transaction'));
  if (Object.keys(budgetEdits).length) parts.push(plural(Object.keys(budgetEdits).length, 'budget change'));
  $('#ss-changes').innerHTML = nc ? `<div><span>✎ ${parts.join(', ')}, saved in this browser only.</span><button class="linkbtn" data-export>Save my changes</button><button class="linkbtn" data-resetall>Clear browser edits</button></div>` : '';
  $('#ss-view').innerHTML = VIEWS[r.view](r.arg, r.params);
  document.title = 'Spend Stories · ' + ({ overview: 'Overview', trends: 'Trends', budgets: 'Budgets', categories: 'Categories', tags: 'Tags', checks: 'Checks', merchants: 'Merchants', transactions: 'Transactions', category: r.arg, merchant: title(r.arg), tag: '#' + r.arg, month: r.arg && mLong(r.arg) }[r.view] || '');
  const nOpen = (RAW.checks || []).filter(c => c.severity === 'warn' && !dismissed[checkKey(c)]).length;
  $('#ss-checks-n').textContent = nOpen ? String(nOpen) : '';
  drawCharts();
  if (scroll && r.key !== lastKey) window.scrollTo(0, 0);
  lastKey = r.key;
}

function setState(k, v) {
  if (['window', 'merLimit'].includes(k)) v = +v;
  if (k === 'oneoffs') v = v === true || v === 'true';
  S[k] = v;
  if (['range', 'window', 'heat', 'from', 'to', 'oneoffs'].includes(k)) store.set(k, v);
  if (['range', 'window', 'from', 'to', 'oneoffs'].includes(k)) derive();
  render(false);
}

function bind() {
  document.addEventListener('click', e => {
    const t = e.target;
    if (popEl && !popEl.contains(t) && !t.closest('[data-recat], [data-edit]')) closePop();
    let el;
    if ((el = t.closest('[data-recat]'))) { e.preventDefault(); e.stopPropagation(); openRecat(el); return; }
    if ((el = t.closest('[data-edit]'))) { e.preventDefault(); e.stopPropagation(); openEdit(el); return; }
    if ((el = t.closest('[data-budgetadd]'))) { const s2 = el.dataset.budgetadd, i = s2.lastIndexOf(':'); setBudget(s2.slice(0, i), +s2.slice(i + 1)); return; }
    if ((el = t.closest('[data-budgetrm]'))) { setBudget(el.dataset.budgetrm, null); return; }
    if ((el = t.closest('[data-dismiss]'))) { const k = el.dataset.dismiss; if (dismissed[k]) delete dismissed[k]; else dismissed[k] = true; store.set('dismissed', dismissed); render(false); return; }
    if (t.closest('[data-print]')) { window.print(); return; }
    if ((el = t.closest('[data-set]'))) { const [k, v] = el.dataset.set.split(':'); setState(k, v); return; }
    if ((el = t.closest('[data-overlay]'))) { const k = el.dataset.overlay; S.overlays[k] = !S.overlays[k]; store.set('overlays', S.overlays); render(false); return; }
    if ((el = t.closest('[data-sort]'))) {
      const tableId = el.dataset.sort.slice(0, el.dataset.sort.lastIndexOf(':')), k = el.dataset.sort.slice(el.dataset.sort.lastIndexOf(':') + 1);
      const cur = S.sort[tableId];
      S.sort[tableId] = { key: k, dir: cur && cur.key === k ? -cur.dir : (k === 'name' || k === 'cat' ? 1 : -1) };
      render(false); return;
    }
    if ((el = t.closest('[data-txsort]'))) {
      const s = el.dataset.txsort, id = s.slice(0, s.lastIndexOf(':')), k = s.slice(s.lastIndexOf(':') + 1), f = S.tx[id];
      f.dir = f.sort === k ? -f.dir : (k === 'd' || k === 'a' ? -1 : 1); f.sort = k;
      $(`[data-txt="${CSS.escape(id)}"] .txbody`).innerHTML = txBody(id); return;
    }
    if ((el = t.closest('[data-txmore]'))) { const id = el.dataset.txmore; S.tx[id].limit += 300; $(`[data-txt="${CSS.escape(id)}"] .txbody`).innerHTML = txBody(id); return; }
    if (t.closest('[data-export]')) { exportModal(); return; }
    if (t.closest('[data-resetall]')) {
      const saved = [overrides, txedits, budgetEdits];
      overrides = {}; txedits = {}; budgetEdits = {};
      const persist = () => { store.set('overrides', overrides); store.set('txedits', txedits); store.set('budgets', budgetEdits); refresh(); };
      persist();
      toast('Cleared your browser edits.', () => { [overrides, txedits, budgetEdits] = saved; persist(); }); return;
    }
    if (t.closest('a, button, input, select, textarea')) return;
    if ((el = t.closest('[data-go]'))) location.hash = el.dataset.go;
  });
  document.addEventListener('input', e => {
    const t = e.target;
    if (t.dataset.txf) {
      const s = t.dataset.txf, id = s.slice(0, s.lastIndexOf(':')), k = s.slice(s.lastIndexOf(':') + 1);
      S.tx[id][k] = t.value; S.tx[id].limit = Math.max(100, S.tx[id].limit > 300 ? 100 : S.tx[id].limit);
      $(`[data-txt="${CSS.escape(id)}"] .txbody`).innerHTML = txBody(id);
    } else if (t.hasAttribute('data-merq')) {
      S.merQ = t.value; const pos = t.selectionStart; render(false);
      const ni = $('[data-merq]'); if (ni) { ni.focus(); try { ni.setSelectionRange(pos, pos); } catch (err) { /* ok */ } }
    }
  });
  document.addEventListener('change', e => {
    const t = e.target;
    if (t.id === 'ss-range') setState('range', t.value);
    else if (t.id === 'ss-from') { S.range = 'custom'; setState('from', t.value); }
    else if (t.id === 'ss-to') { S.range = 'custom'; setState('to', t.value); }
    else if (t.dataset.setsel) setState(t.dataset.setsel, t.value);
    else if (t.dataset.budget != null) setBudget(t.dataset.budget, t.value === '' ? null : +t.value);
    else if (t.hasAttribute('data-budgetmonth')) location.hash = '#/budgets?m=' + t.value;
  });
  $('#ss-theme').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    store.set('theme', root.dataset.theme);
  });
  window.addEventListener('hashchange', () => render(true));
  let rt;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(drawCharts, 120); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { closePop(); $$('.modal-bg').forEach(m => m.remove()); } });

  const tip = $('#tip');
  document.addEventListener('mousemove', e => {
    const el = e.target.closest && e.target.closest('[data-tip]');
    if (!el || !el.getAttribute('data-tip')) { tip.style.display = 'none'; return; }
    tip.innerHTML = el.getAttribute('data-tip');
    tip.style.display = 'block';
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + 14, y = e.clientY + 14;
    if (x + w > innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > innerHeight - 8) y = e.clientY - h - 14;
    tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
  });
  document.addEventListener('scroll', () => { tip.style.display = 'none'; }, { passive: true });
}

// ------------------------------------------------------------------ boot
const theme = store.get('theme', null);
if (theme) document.documentElement.dataset.theme = theme;
if (!ALL_MONTHS.includes(S.from)) S.from = ALL_MONTHS[0];
if (!ALL_MONTHS.includes(S.to)) S.to = ALL_MONTHS[ALL_MONTHS.length - 1];
shell();
applyOverrides();
assignColors();
derive();
bind();
render(true);
window.__spendstories = { D: () => D, S, TX };
})();
