"""Build the report: one self-contained HTML file holding the data and a small app.

The app (``app/app.js`` + ``app/app.css``) is inlined, the transactions are
embedded as JSON, and the page ships a Content-Security-Policy that forbids
the browser from fetching anything, so opening the report cannot leak data.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from importlib import resources

from .models import Transaction

CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
       "img-src data:; base-uri 'none'; form-action 'none'")


def _asset(name: str) -> str:
    return resources.files("spendstories").joinpath("app", name).read_text("utf-8")


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "item"):  # numpy scalars
        return o.item()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def report_data(transactions: list[Transaction], kinds: dict[str, str], recurring: list[dict],
                warnings: list[str] | None = None, currency: str = "") -> dict:
    txns = sorted(transactions, key=lambda t: (t.date, t.source))
    sources = sorted({t.source for t in txns})
    src_idx = {s: i for i, s in enumerate(sources)}
    return {
        "currency": currency,
        "generated": datetime.now().strftime("%d %b %Y %H:%M"),
        "sources": sources,
        "warnings": list(warnings or []),
        "kinds": kinds,
        "recurring": [{k: v for k, v in r.items()} for r in recurring],
        # Compact rows: [date, description, amount, category, kind, merchant, source index]
        "txns": [[t.date.isoformat(), t.description, round(t.amount, 2), t.category, t.kind, t.merchant,
                  src_idx[t.source]] for t in txns],
    }


def render_html(transactions: list[Transaction], kinds: dict[str, str], recurring: list[dict],
                warnings: list[str] | None = None, currency: str = "") -> str:
    data = report_data(transactions, kinds, recurring, warnings, currency)
    payload = json.dumps(data, ensure_ascii=False, default=_json_default, separators=(",", ":"))
    # Keep the JSON from closing its own <script> element.
    payload = payload.replace("</", "<\\/").replace("<!--", "<\\!--")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="no-referrer">
<title>Spend Stories</title>
<style>{_asset("app.css")}</style>
</head>
<body>
<div id="app"><noscript><p style="padding:24px">This report needs JavaScript turned on. It runs entirely on your computer.</p></noscript></div>
<script type="application/json" id="ss-data">{payload}</script>
<script>{_asset("app.js")}</script>
</body>
</html>"""
