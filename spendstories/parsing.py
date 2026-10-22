"""Low-level helpers for turning statement text into dates and amounts."""

from __future__ import annotations

import re
from datetime import date, datetime

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}

_NUMERIC_DATE = re.compile(r"^(\d{1,4})[/\-. ](\d{1,2})[/\-. ](\d{2,4})$")
# 12 Jan 2026, 12-Jan-26, 12Jan2026
_DAY_MON_YEAR = re.compile(r"^(\d{1,2})[\s\-/.,]*([A-Za-z]{3,9})[\s\-/.,]*(\d{2,4})$")
# Jan 12, 2026 / January 12 2026
_MON_DAY_YEAR = re.compile(r"^([A-Za-z]{3,9})[\s\-/.]*(\d{1,2})(?:st|nd|rd|th)?[\s,\-/.]*(\d{2,4})$")

DATE_TOKEN = re.compile(
    r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}[\s\-]?[A-Za-z]{3,9}[\s\-,]*\d{2,4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}"
)


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 100 else n


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(value, dayfirst: bool = True) -> date | None:
    """Parse the many date styles found in statements. Returns None if unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):  # pandas Timestamp
        try:
            return value.to_pydatetime().date()
        except (ValueError, TypeError):
            return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return None
    # Drop a trailing time component ("2026-01-05 00:00:00", "05/01/2026 14:32").
    s = re.split(r"[ T]\d{1,2}:\d{2}", s, maxsplit=1)[0].strip()

    m = _NUMERIC_DATE.match(s)
    if m:
        a, b, c = m.groups()
        if len(a) == 4:  # ISO-ish yyyy-mm-dd
            return _safe_date(int(a), int(b), int(c))
        a_i, b_i = int(a), int(b)
        if a_i > 12:
            d, mo = a_i, b_i
        elif b_i > 12:
            mo, d = a_i, b_i
        elif dayfirst:
            d, mo = a_i, b_i
        else:
            mo, d = a_i, b_i
        return _safe_date(_year(c), mo, d)

    m = _DAY_MON_YEAR.match(s)
    if m and m.group(2).lower() in _MONTHS:
        return _safe_date(_year(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))

    m = _MON_DAY_YEAR.match(s)
    if m and m.group(1).lower() in _MONTHS:
        return _safe_date(_year(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def detect_dayfirst(values, default: bool = True) -> bool:
    """Decide between dd/mm and mm/dd from a column of numeric date strings."""
    day_first_votes = month_first_votes = 0
    for v in values:
        m = _NUMERIC_DATE.match(str(v).strip().split(" ")[0])
        if not m or len(m.group(1)) == 4:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            day_first_votes += 1
        elif b > 12 >= a:
            month_first_votes += 1
    if day_first_votes == month_first_votes:
        return default
    return day_first_votes > month_first_votes


_AMOUNT_CLEAN = re.compile(r"[^\d.\-]")


def parse_amount(value) -> tuple[float | None, str | None]:
    """Parse an amount string.

    Returns ``(value, marker)`` where ``marker`` is ``"cr"``/``"dr"`` when the text
    carried an explicit credit/debit suffix, otherwise None. Parentheses and a
    trailing minus are treated as negative.
    """
    if value is None:
        return None, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value != value:  # NaN
            return None, None
        return float(value), None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "-", "--"}:
        return None, None
    marker = None
    low = s.lower()
    m = re.search(r"\b(cr|dr)\.?$", low)
    if m:
        marker = m.group(1)
        s = s[: m.start()].strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.endswith("-"):
        negative, s = True, s[:-1]
    if s.endswith("+"):
        s = s[:-1]
    s = s.replace(",", "").replace(" ", "")
    if s.startswith("+"):
        s = s[1:]
    first_digit = re.search(r"\d", s)
    if first_digit and "-" in s[: first_digit.start()]:
        negative = True
    cleaned = _AMOUNT_CLEAN.sub("", s).replace("-", "")
    if not cleaned or cleaned == "." or not re.search(r"\d", cleaned):
        return None, None
    if cleaned.count(".") > 1:
        return None, None
    try:
        num = float(cleaned)
    except ValueError:
        return None, None
    return (-num if negative else num), marker


def looks_like_amount(value) -> bool:
    return parse_amount(value)[0] is not None
