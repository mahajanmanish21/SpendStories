"""Render an Analysis as a single self-contained HTML file.

The page has no external resources at all (fonts, scripts, images, styles are
inline) and ships a Content-Security-Policy that forbids the browser from
fetching anything, so opening the report cannot leak data either.
"""

from __future__ import annotations

import html
import json
import math
from datetime import datetime

from .analysis import Analysis
from .formatting import money, month_label, pct

MAX_SERIES = 7  # categories drawn individually in the stacked chart; the rest fold into "Other"

CSS = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --card: #ffffff; --line: #e6e5e0; --grid: #ecebe7;
  --text: #0b0b0b; --text-2: #52514e; --muted: #77766f;
  --accent: #2a78d6; --accent-soft: #cde2fb; --neutral-mark: #c9c8c1;
  --up: #b42828; --down: #0b7a0b;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300; --s7:#6250d6; --s8:#e34948;
  --other: #a8a79f;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #1a1a19; --card: #222220; --line: #383835; --grid: #2c2c2a;
    --text: #f0efec; --text-2: #c3c2b7; --muted: #9a998f;
    --accent: #3987e5; --accent-soft: #184f95; --neutral-mark: #55544f;
    --up: #f07a7a; --down: #5bc45b;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767;
    --other: #6b6a64;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --card: #222220; --line: #383835; --grid: #2c2c2a;
  --text: #f0efec; --text-2: #c3c2b7; --muted: #9a998f;
  --accent: #3987e5; --accent-soft: #184f95; --neutral-mark: #55544f;
  --up: #f07a7a; --down: #5bc45b;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767;
  --other: #6b6a64;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1120px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 28px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 19px; margin: 40px 0 12px; }
h3 { font-size: 15px; margin: 0 0 4px; }
p.sub, .muted { color: var(--text-2); }
.small { font-size: 13px; }
.privacy { display: inline-block; margin-top: 8px; font-size: 13px; color: var(--text-2);
  border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-top: 24px; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }
.tile .label { font-size: 13px; color: var(--text-2); }
.tile .value { font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums; }
.tile .delta { font-size: 13px; color: var(--text-2); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
ul.insights { margin: 0; padding-left: 20px; }
ul.insights li { margin: 4px 0; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; color: var(--text-2); margin: 4px 0 8px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; flex: none; }
svg text { fill: var(--text-2); font-size: 11px; font-family: inherit; }
svg .grid { stroke: var(--grid); stroke-width: 1; }
svg .axis { stroke: var(--line); stroke-width: 1; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--line); vertical-align: middle; }
th { font-weight: 600; color: var(--text-2); font-size: 13px; white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
th[data-sort] { cursor: pointer; user-select: none; }
.sharebar { height: 6px; border-radius: 3px; background: var(--accent); min-width: 2px; }
.sharetrack { width: 90px; background: var(--grid); border-radius: 3px; }
.up { color: var(--up); } .down { color: var(--down); }
.grid2 { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.mini h3 { display: flex; justify-content: space-between; gap: 8px; }
details summary { cursor: pointer; color: var(--text-2); font-size: 13px; margin-top: 8px; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.controls input, .controls select { font: inherit; font-size: 14px; padding: 6px 10px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--card); color: var(--text); }
.controls input { flex: 1 1 220px; }
#tip { position: fixed; pointer-events: none; z-index: 10; background: var(--card); color: var(--text);
  border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 13px;
  box-shadow: 0 4px 16px rgba(0,0,0,.15); display: none; max-width: 280px; }
#tip .row { display: flex; gap: 8px; align-items: center; justify-content: space-between; }
#tip .row span:last-child { font-variant-numeric: tabular-nums; }
.hit { fill: transparent; cursor: default; }
.hit:hover { fill: var(--text); fill-opacity: 0.04; }
.warn { font-size: 13px; color: var(--text-2); }
footer { margin-top: 48px; font-size: 13px; color: var(--muted); }
@media (max-width: 600px) { h1 { font-size: 23px; } .tile .value { font-size: 22px; } }
"""

JS = """
(function(){
  const tip = document.getElementById('tip');
  document.addEventListener('mousemove', e => {
    const t = e.target.closest('[data-tip]');
    if (!t) { tip.style.display = 'none'; return; }
    tip.innerHTML = t.getAttribute('data-tip');
    tip.style.display = 'block';
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + 14, y = e.clientY + 14;
    if (x + w > innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > innerHeight - 8) y = e.clientY - h - 14;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  });
  document.addEventListener('scroll', () => tip.style.display = 'none', {passive: true});

  // Transactions explorer
  const data = JSON.parse(document.getElementById('txn-data').textContent);
  const body = document.getElementById('txn-body');
  const q = document.getElementById('txn-q'), cat = document.getElementById('txn-cat'),
        kind = document.getElementById('txn-kind'), count = document.getElementById('txn-count');
  let sortKey = 'd', sortDir = -1;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  function render(){
    const term = q.value.trim().toLowerCase();
    let rows = data.filter(r => (!cat.value || r.c === cat.value) && (!kind.value || r.k === kind.value)
      && (!term || r.t.toLowerCase().includes(term) || r.s.toLowerCase().includes(term)));
    rows.sort((a, b) => (a[sortKey] < b[sortKey] ? -1 : a[sortKey] > b[sortKey] ? 1 : 0) * sortDir);
    const total = rows.reduce((s, r) => s + (r.k === 'expense' || r.k === 'refund' ? r.a : 0), 0);
    count.textContent = rows.length + ' transactions · net spend ' + window.fmt(total);
    body.innerHTML = rows.slice(0, 1500).map(r => '<tr><td class="num">' + r.d + '</td><td>' + esc(r.t) +
      '</td><td>' + esc(r.c) + '</td><td>' + r.k + '</td><td class="small muted">' + esc(r.s) +
      '</td><td class="num">' + window.fmt(r.a, true) + '</td></tr>').join('') +
      (rows.length > 1500 ? '<tr><td colspan="6" class="muted">Showing first 1,500 - narrow the filter to see more.</td></tr>' : '');
  }
  document.querySelectorAll('#txn-table th[data-sort]').forEach(th => th.addEventListener('click', () => {
    const k = th.getAttribute('data-sort');
    sortDir = (sortKey === k) ? -sortDir : (k === 'a' || k === 'd' ? -1 : 1); sortKey = k; render();
  }));
  [q, cat, kind].forEach(el => el.addEventListener('input', render));
  render();
})();
"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _nice_ticks(max_value: float, n: int = 4) -> list[float]:
    if max_value <= 0:
        return [0.0, 1.0]
    raw = max_value / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    ticks, v = [], 0.0
    while v < max_value + step * 0.001:
        ticks.append(v)
        v += step
    if ticks[-1] < max_value:
        ticks.append(v)
    return ticks


def _top_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """Column with rounded top corners and a square base."""
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h:.1f} Z")


def _series_colors(categories: list[str]) -> dict[str, str]:
    return {c: f"var(--s{i + 1})" for i, c in enumerate(categories[:MAX_SERIES])}


def stacked_month_chart(a: Analysis) -> tuple[str, str]:
    pivot = a.by_category_month.clip(lower=0)
    cats = list(pivot.index)
    shown = cats[:MAX_SERIES]
    colors = _series_colors(shown)
    rows = [(c, pivot.loc[c]) for c in shown]
    if len(cats) > MAX_SERIES:
        rows.append(("Other", pivot.loc[cats[MAX_SERIES:]].sum()))
        colors["Other"] = "var(--other)"

    months = a.months
    W, H = 1000, 320
    left, right, top, bottom = 56, 8, 12, 34
    pw, ph = W - left - right, H - top - bottom
    totals = pivot.sum(axis=0)
    ticks = _nice_ticks(float(totals.max()))
    ymax = ticks[-1]
    band = pw / max(len(months), 1)
    bw = min(24 if len(months) > 12 else 36, band * 0.6)
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Monthly spending by category">']
    for t in ticks:
        y = top + ph - t / ymax * ph
        parts.append(f'<line class="grid" x1="{left}" x2="{W - right}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{esc(money(t, compact=True))}</text>')
    label_every = max(1, math.ceil(len(months) / 12))
    for i, m in enumerate(months):
        cx = left + band * (i + 0.5)
        x = cx - bw / 2
        y_cursor = top + ph
        segs = [(name, float(series[m])) for name, series in rows if float(series[m]) > 0]
        for k, (name, v) in enumerate(segs):
            h = v / ymax * ph
            gap = 2 if k < len(segs) - 1 else 0
            y = y_cursor - h
            draw_h = max(h - gap, 0.5)
            if k == len(segs) - 1:
                parts.append(f'<path d="{_top_path(x, y, bw, draw_h)}" fill="{colors[name]}"/>')
            else:
                parts.append(f'<rect x="{x:.1f}" y="{y + gap:.1f}" width="{bw:.1f}" height="{draw_h:.1f}" fill="{colors[name]}"/>')
            y_cursor = y
        tip_rows = "".join(
            f'<div class="row"><span><i class="swatch" style="background:{colors[name]}"></i> {esc(name)}</span>'
            f'<span>{esc(money(float(series[m])))}</span></div>'
            for name, series in reversed(rows) if float(series[m]) > 0)
        partial = " (partial month)" if m in a.partial_months else ""
        tip = (f'<b>{esc(month_label(m))}{partial}</b><div class="row"><span>Total</span>'
               f'<span><b>{esc(money(float(totals[m])))}</b></span></div>{tip_rows}')
        parts.append(f'<rect class="hit" x="{left + band * i:.1f}" y="{top}" width="{band:.1f}" height="{ph}" data-tip="{esc(tip)}"/>')
        if i % label_every == 0:
            lbl = datetime.strptime(m, "%Y-%m").strftime("%b %y") + ("*" if partial else "")
            parts.append(f'<text x="{cx:.1f}" y="{H - 12}" text-anchor="middle">{lbl}</text>')
    parts.append(f'<line class="axis" x1="{left}" x2="{W - right}" y1="{top + ph}" y2="{top + ph}"/>')
    parts.append("</svg>")
    legend = '<div class="legend">' + "".join(
        f'<span><i class="swatch" style="background:{colors[n]}"></i>{esc(n)}</span>' for n, _ in rows) + "</div>"
    return legend + "".join(parts), _month_table(a, rows)


def _month_table(a: Analysis, rows) -> str:
    head = "".join(f'<th class="num">{esc(month_label(m))}</th>' for m in a.months)
    body = "".join(
        f"<tr><td>{esc(n)}</td>" + "".join(f'<td class="num">{esc(money(float(s[m])))}</td>' for m in a.months) + "</tr>"
        for n, s in rows)
    total = "".join(f'<td class="num"><b>{esc(money(float(a.monthly_total[m])))}</b></td>' for m in a.months)
    return (f'<details><summary>Show as table</summary><div class="scroll"><table><tr><th>Category</th>{head}</tr>'
            f'{body}<tr><td><b>Total</b></td>{total}</tr></table></div></details>')


def sparkline(values: list[float], w: int = 110, h: int = 28) -> str:
    if len(values) < 2:
        return ""
    vmax, vmin = max(max(values), 1e-9), min(min(values), 0)
    span = vmax - vmin or 1
    pts = [(2 + i * (w - 6) / (len(values) - 1), h - 3 - (v - vmin) / span * (h - 6)) for i, v in enumerate(values)]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    ex, ey = pts[-1]
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">'
            f'<polyline points="{path}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3.5" fill="var(--accent)" stroke="var(--card)" stroke-width="2"/></svg>')


def mini_columns(a: Analysis, series, highlight: set[str], w: int = 320, h: int = 110) -> str:
    """Small month-by-month column chart with chosen months in the accent colour."""
    months = a.months
    vals = [max(float(series[m]), 0) for m in months]
    ymax = max(vals) or 1
    band = (w - 8) / len(months)
    bw = min(18, band * 0.62)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">']
    base = h - 18
    for i, (m, v) in enumerate(zip(months, vals)):
        cx = 4 + band * (i + 0.5)
        bh = v / ymax * (base - 6)
        fill = "var(--accent)" if m in highlight else "var(--neutral-mark)"
        if bh > 0:
            parts.append(f'<path d="{_top_path(cx - bw / 2, base - bh, bw, bh, 3)}" fill="{fill}"/>')
        tip = f"<b>{esc(month_label(m))}</b><br>{esc(money(v))}"
        parts.append(f'<rect class="hit" x="{4 + band * i:.1f}" y="0" width="{band:.1f}" height="{base}" data-tip="{esc(tip)}"/>')
    parts.append(f'<line class="axis" x1="4" x2="{w - 4}" y1="{base}" y2="{base}"/>')
    parts.append(f'<text x="4" y="{h - 4}">{esc(month_label(months[0]))}</text>')
    parts.append(f'<text x="{w - 4}" y="{h - 4}" text-anchor="end">{esc(month_label(months[-1]))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def mini_line(a: Analysis, series, w: int = 320, h: int = 110) -> str:
    months = a.full_months
    vals = [float(series[m]) for m in months]
    ymax = max(max(vals), 1)
    base = h - 18
    xs = [6 + i * (w - 12) / max(len(months) - 1, 1) for i in range(len(months))]
    ys = [base - v / ymax * (base - 8) for v in vals]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">',
             f'<line class="axis" x1="4" x2="{w - 4}" y1="{base}" y2="{base}"/>',
             f'<polyline points="{pts}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>',
             f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="4" fill="var(--accent)" stroke="var(--card)" stroke-width="2"/>']
    step = (w - 12) / max(len(months) - 1, 1)
    for x, m, v in zip(xs, months, vals):
        tip = f"<b>{esc(month_label(m))}</b><br>{esc(money(v))}"
        parts.append(f'<rect class="hit" x="{x - step / 2:.1f}" y="0" width="{step:.1f}" height="{base}" data-tip="{esc(tip)}"/>')
    parts.append(f'<text x="4" y="{h - 4}">{esc(month_label(months[0]))}</text>')
    parts.append(f'<text x="{w - 4}" y="{h - 4}" text-anchor="end">{esc(month_label(months[-1]))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _tile(label: str, value: str, delta: str = "") -> str:
    d = f'<div class="delta">{delta}</div>' if delta else ""
    return f'<div class="tile"><div class="label">{esc(label)}</div><div class="value">{esc(value)}</div>{d}</div>'


def render_html(a: Analysis, warnings: list[str] | None = None, currency: str = "") -> str:
    o = a.overview
    period = f"{a.start:%d %b %Y} – {a.end:%d %b %Y}"

    tiles = [
        _tile("Total spending", money(o["total_spend"], compact=True), f"{o['spend_transactions']} purchases"),
        _tile("Average per month", money(o["avg_monthly_spend"], compact=True),
              "full months only" if a.partial_months and len(a.full_months) >= 3 else ""),
    ]
    if o["income"]:
        tiles.append(_tile("Income", money(o["income"], compact=True)))
    if o["invested"]:
        tiles.append(_tile("Invested", money(o["invested"], compact=True)))
    if o["net_saved"] is not None:
        tiles.append(_tile("Left over", money(o["net_saved"], compact=True),
                           f"{pct(o['net_saved'] / o['income'])} of income" if o["income"] else ""))
    if o["refunds"]:
        tiles.append(_tile("Refunds received", money(o["refunds"], compact=True)))

    insights = "".join(f"<li>{esc(i)}</li>" for i in a.insights) or "<li>No notable patterns yet - add more months of statements.</li>"
    chart, chart_table = stacked_month_chart(a)

    # Category table
    cat_rows = []
    max_share = float(a.category_summary["share"].max()) if len(a.category_summary) else 1
    for r in a.category_summary.itertuples():
        trend = ""
        if r.trend == "up":
            trend = f'<span class="up">▲ {abs(r.trend_pct):.0f}%/mo</span>'
        elif r.trend == "down":
            trend = f'<span class="down">▼ {abs(r.trend_pct):.0f}%/mo</span>'
        vs = "" if math.isnan(r.vs_avg) else f'{"+" if r.vs_avg >= 0 else ""}{r.vs_avg * 100:.0f}%'
        width = max(r.share / max_share * 100, 1) if r.share > 0 else 0
        cat_rows.append(
            f"<tr><td>{esc(r.category)}</td><td class=\"num\">{esc(money(r.total))}</td>"
            f'<td class="num">{pct(r.share)}</td><td><div class="sharetrack"><div class="sharebar" style="width:{width:.0f}%"></div></div></td>'
            f'<td class="num">{esc(money(r.monthly_avg))}</td><td class="num">{esc(money(r.last_month))}</td>'
            f'<td class="num">{vs}</td><td>{sparkline(r.series)}</td><td>{trend}</td><td class="num">{r.count}</td></tr>')
    last_full = month_label(a.full_months[-1]) if a.full_months else ""

    # Spikes
    spike_cards = []
    for sp in a.month_spikes[:9]:
        series = a.monthly_total if sp["category"] == "All spending" else a.by_category_month.loc[sp["category"]]
        drivers = "".join(f'<li>{d["date"]:%d %b} · {esc(d["description"][:48])} · <b>{esc(money(d["amount"]))}</b></li>'
                          for d in sp["drivers"])
        ratio = f"{sp['ratio']:.1f}× usual" if sp["usual"] >= 1 else "new"
        spike_cards.append(
            f'<div class="card mini"><h3><span>{esc(sp["category"])} · {esc(month_label(sp["month"]))}</span>'
            f'<span class="up">{ratio}</span></h3><div class="small muted">{esc(money(sp["amount"]))} vs '
            + (f'usual {esc(money(sp["usual"]))}' if sp["usual"] >= 1 else "next to nothing in a typical month")
            + f'</div>{mini_columns(a, series, {sp["month"]})}'
            f'<ul class="small" style="margin:6px 0 0;padding-left:18px">{drivers}</ul></div>')
    spikes_html = (f'<div class="grid2">{"".join(spike_cards)}</div>' if spike_cards else
                   f'<p class="muted">No monthly spikes detected{"" if len(a.full_months) >= 3 else " - spike detection needs at least 3 months of data"}.</p>')

    # Trends
    trend_cards = []
    for t in a.trends[:9]:
        cls = "up" if t["direction"] == "up" else "down"
        arrow = "▲" if cls == "up" else "▼"
        trend_cards.append(
            f'<div class="card mini"><h3><span>{esc(t["category"])}</span><span class="{cls}">{arrow} {abs(t["slope_pct"]):.0f}% / month</span></h3>'
            f'<div class="small muted">{esc(money(t["first"]))} in {esc(month_label(t["first_month"]))} → '
            f'{esc(money(t["last"]))} in {esc(month_label(t["last_month"]))}</div>'
            f'{mini_line(a, a.by_category_month.loc[t["category"]])}</div>')
    trends_html = (f'<div class="grid2">{"".join(trend_cards)}</div>' if trend_cards else
                   f'<p class="muted">No sustained category trends{"" if len(a.full_months) >= 3 else " - trends need at least 3 months of data"}.</p>')

    large_rows = "".join(
        f'<tr><td class="num">{r["date"]:%d %b %Y}</td><td>{esc(r["description"])}</td><td>{esc(r["category"])}</td>'
        f'<td class="num">{esc(money(r["typical"]))}</td><td class="num"><b>{esc(money(r["amount"]))}</b></td></tr>'
        for r in a.large_transactions)

    rec_rows = "".join(
        f'<tr><td>{esc(r["merchant"].title())}<div class="small muted">{esc(r["description"][:60])}</div></td>'
        f'<td>{esc(r["category"])}</td><td>{r["frequency"]}</td><td class="num">{esc(money(r["amount"]))}</td>'
        f'<td class="num">{esc(money(r["monthly_cost"]))}</td><td class="num">{r["count"]}</td>'
        f'<td class="num">{r["last"]:%d %b %Y}</td><td class="num">'
        + (f'<span class="up">▲ {pct(r["price_change"])}</span>' if r["price_change"] >= 0.05 else
           f'<span class="down">▼ {pct(-r["price_change"])}</span>' if r["price_change"] <= -0.05 else "")
        + "</td></tr>" for r in a.recurring)

    merch_rows = "".join(
        f'<tr><td>{esc(r.merchant.title())}</td><td>{esc(r.category)}</td><td class="num">{r.count}</td>'
        f'<td class="num">{esc(money(r.total))}</td></tr>' for r in a.top_merchants.itertuples())

    df = a.transactions
    txn_json = json.dumps([
        {"d": r.date.strftime("%Y-%m-%d"), "t": r.description, "c": r.category, "k": r.kind,
         "s": r.source, "a": round(float(r.amount), 2)} for r in df.itertuples()
    ], ensure_ascii=False).replace("</", "<\\/")
    cat_options = "".join(f'<option>{esc(c)}</option>' for c in sorted(df["category"].unique()))

    warn_html = ""
    if warnings:
        warn_html = "<h2>Notes on the input</h2><ul class=\"warn\">" + "".join(f"<li>{esc(w)}</li>" for w in warnings) + "</ul>"

    fmt_js = (f"window.fmt=function(v,full){{const s=v<0?'-':'',a=Math.abs(v);"
              f"return s+{json.dumps(currency)}+a.toLocaleString(undefined,{{maximumFractionDigits:a>=100?0:2,minimumFractionDigits:a>=100?0:2}});}};")

    partial_note = ""
    if a.partial_months:
        partial_note = (f'<p class="small muted">* Partial month ({", ".join(month_label(m) for m in sorted(a.partial_months))}): '
                        "statements don't cover the whole month, so it's left out of averages, trends and spike baselines.</p>"
                        if len(a.full_months) >= 3 else "")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<title>Spend Stories</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>Spend Stories</h1>
<p class="sub">{esc(period)} · {len(a.months)} months · {o['transactions']} transactions from {len(o['sources'])} statement file(s)</p>
<span class="privacy">🔒 Generated offline on your computer. This page loads nothing from the internet.</span>

<div class="tiles">{''.join(tiles)}</div>

<h2>Highlights</h2>
<div class="card"><ul class="insights">{insights}</ul></div>

<h2>Monthly spending by category</h2>
<div class="card">{chart}{chart_table}</div>
{partial_note}

<h2>Spikes</h2>
<p class="small muted">Months where a category was well above its usual level (median of the other months).</p>
{spikes_html}

<h2>Trends</h2>
<p class="small muted">Categories that have been rising or falling steadily over the months covered.</p>
{trends_html}

<h2>Categories</h2>
<div class="card scroll"><table>
<tr><th>Category</th><th class="num">Total</th><th class="num">Share</th><th></th><th class="num">Avg / month</th>
<th class="num">{esc(last_full)}</th><th class="num">vs avg</th><th>Monthly</th><th>Trend</th><th class="num">Txns</th></tr>
{''.join(cat_rows)}
</table></div>

<h2>Unusually large transactions</h2>
{f'<div class="card scroll"><table><tr><th class="num">Date</th><th>Description</th><th>Category</th><th class="num">Typical in category</th><th class="num">Amount</th></tr>{large_rows}</table></div>' if large_rows else '<p class="muted">None stood out.</p>'}

<h2>Recurring payments &amp; subscriptions</h2>
{f'<div class="card scroll"><table><tr><th>Merchant</th><th>Category</th><th>Every</th><th class="num">Amount</th><th class="num">≈ per month</th><th class="num">Times</th><th class="num">Last</th><th class="num">Price change</th></tr>{rec_rows}</table></div>' if rec_rows else '<p class="muted">No recurring payments detected.</p>'}

<h2>Top merchants</h2>
<div class="card scroll"><table><tr><th>Merchant</th><th>Category</th><th class="num">Txns</th><th class="num">Total</th></tr>{merch_rows}</table></div>

<h2>All transactions</h2>
<div class="controls">
<input id="txn-q" type="search" placeholder="Search description or statement…" aria-label="Search transactions">
<select id="txn-cat" aria-label="Category"><option value="">All categories</option>{cat_options}</select>
<select id="txn-kind" aria-label="Type"><option value="">All types</option><option value="expense">Expenses</option>
<option value="refund">Refunds</option><option value="income">Income</option><option value="transfer">Transfers (ignored)</option>
<option value="investment">Investments</option></select>
</div>
<div id="txn-count" class="small muted"></div>
<div class="card scroll"><table id="txn-table">
<thead><tr><th class="num" data-sort="d">Date ↕</th><th data-sort="t">Description ↕</th><th data-sort="c">Category ↕</th><th data-sort="k">Type ↕</th><th data-sort="s">Statement ↕</th><th class="num" data-sort="a">Amount ↕</th></tr></thead>
<tbody id="txn-body"></tbody></table></div>
{warn_html}
<footer>Spending = purchases minus refunds. Card bill payments and transfers between your own accounts are ignored so nothing is counted twice. Amounts in the statements' own currency.</footer>
</main>
<div id="tip" role="tooltip"></div>
<script type="application/json" id="txn-data">{txn_json}</script>
<script>{fmt_js}{JS}</script>
</body>
</html>"""
