"""Tags (group spending across categories) and splits (count shared costs at your share).

Both live in your rules file next to categories:

    [tags."Goa trip"]
    from = 2026-05-01
    to = 2026-05-20
    categories = ["Travel"]          # optional
    keywords = ["goa"]               # optional; also merchants = [...], transactions = [...]

    [[splits]]
    share = 0.5
    keywords = ["landlord"]
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .categorize import _keyword_pattern
from .models import Transaction


@dataclass
class Selector:
    start: date | None = None
    end: date | None = None
    categories: frozenset[str] = frozenset()
    pattern: re.Pattern | None = None
    merchants: frozenset[str] = frozenset()
    transactions: frozenset[str] = frozenset()

    @property
    def has_matchers(self) -> bool:
        return bool(self.pattern or self.merchants or self.transactions)

    def matches(self, t: Transaction) -> bool:
        if t.id in self.transactions:  # naming a transaction is always enough
            return True
        if self.start and t.date < self.start:
            return False
        if self.end and t.date > self.end:
            return False
        if self.categories and t.category not in self.categories:
            return False
        if not self.has_matchers:
            return bool(self.start or self.end or self.categories)
        return bool((self.pattern and self.pattern.search(t.description)) or t.merchant in self.merchants)


@dataclass
class Tag:
    name: str
    selector: Selector


@dataclass
class Split:
    share: float
    selector: Selector


@dataclass
class Extras:
    tags: list[Tag] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)


def _as_date(v, where: str) -> date | None:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        raise ValueError(f"{where}: dates must look like 2026-05-01") from None


def _selector(spec: dict, where: str) -> Selector:
    keywords = spec.get("keywords") or []
    try:
        pattern = re.compile("|".join(f"(?:{_keyword_pattern(k)})" for k in keywords), re.I) if keywords else None
    except re.error as e:
        raise ValueError(f"{where}: bad regex: {e}") from e
    return Selector(
        start=_as_date(spec.get("from"), where), end=_as_date(spec.get("to"), where),
        categories=frozenset(spec.get("categories") or []), pattern=pattern,
        merchants=frozenset(m.strip().lower() for m in spec.get("merchants") or []),
        transactions=frozenset(spec.get("transactions") or []),
    )


def load_extras(paths: list[str | Path] | None) -> Extras:
    ex = Extras()
    for path in paths or []:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        for name, spec in (data.get("tags") or {}).items():
            sel = _selector(spec, f"{path}: tag {name!r}")
            if not (sel.has_matchers or sel.start or sel.end or sel.categories):
                raise ValueError(f"{path}: tag {name!r} needs dates, categories, keywords, merchants or transactions")
            ex.tags.append(Tag(name, sel))
        for i, spec in enumerate(data.get("splits") or [], start=1):
            where = f"{path}: split #{i}"
            try:
                share = float(spec.get("share"))
            except (TypeError, ValueError):
                raise ValueError(f"{where}: needs share = a number between 0 and 1") from None
            if not 0 <= share <= 1:
                raise ValueError(f"{where}: share must be between 0 and 1 (0.5 = half)")
            sel = _selector(spec, where)
            if not (sel.has_matchers or sel.categories):
                raise ValueError(f"{where}: needs keywords, merchants, categories or transactions")
            ex.splits.append(Split(share, sel))
    return ex


def apply_extras(transactions: list[Transaction], extras: Extras) -> None:
    """Attach tags and scale shared expenses. Call after categorise (selectors can use categories)."""
    for t in transactions:
        if t.original_amount is None:
            t.original_amount = t.amount
        t.tags = [tag.name for tag in extras.tags if tag.selector.matches(t)]
        # A split that names this exact transaction beats a general rule.
        split = (next((s for s in extras.splits if t.id in s.selector.transactions), None)
                 or next((s for s in extras.splits if s.selector.matches(t)), None))
        t.share = split.share if split else 1.0
        t.amount = round(t.original_amount * t.share, 2)
