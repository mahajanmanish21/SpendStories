from __future__ import annotations

import math
from datetime import datetime

CURRENCY = ""


def set_currency(symbol: str) -> None:
    global CURRENCY
    CURRENCY = symbol


def money(value: float, compact: bool = False) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if compact:
        for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if v >= div:
                n = v / div
                return f"{sign}{CURRENCY}{n:.1f}{suffix}" if n < 100 else f"{sign}{CURRENCY}{n:.0f}{suffix}"
        return f"{sign}{CURRENCY}{v:.0f}"
    if v < 0.005:
        return f"{CURRENCY}0"
    return f"{sign}{CURRENCY}{v:,.0f}" if v >= 100 else f"{sign}{CURRENCY}{v:,.2f}"


def pct(value: float) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    return f"{value * 100:.0f}%"


def month_label(month: str, short: bool = True) -> str:
    d = datetime.strptime(month, "%Y-%m")
    return d.strftime("%b %Y" if short else "%B %Y")
