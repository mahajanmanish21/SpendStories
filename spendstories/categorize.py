"""Keyword-based categorisation driven by editable TOML rule files."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .models import Transaction

UNCATEGORIZED = "Uncategorized"
OTHER_INCOME = "Other Income"
KINDS = {"expense", "transfer", "investment", "income"}


@dataclass
class Rule:
    category: str
    kind: str
    pattern: re.Pattern | None
    merchants: frozenset[str] = frozenset()

    def matches(self, description: str, merchant: str) -> bool:
        return merchant in self.merchants or (self.pattern is not None and bool(self.pattern.search(description)))


def _keyword_pattern(keyword: str) -> str:
    if keyword.startswith("re:"):
        return keyword[3:]
    kw = keyword.lower().strip()
    escaped = re.escape(kw)
    if len(kw.replace(" ", "")) >= 5:
        return escaped
    return rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"


def _rules_from_toml(data: dict, source: str) -> list[Rule]:
    rules = []
    for name, spec in (data.get("categories") or {}).items():
        kind = spec.get("kind", "expense")
        if kind not in KINDS:
            raise ValueError(f"{source}: category {name!r} has unknown kind {kind!r}")
        keywords = spec.get("keywords") or []
        # Exact merchant names, as shown in the report (the report's "save as rules file" writes these).
        merchants = frozenset(m.strip().lower() for m in spec.get("merchants") or [])
        if not keywords and not merchants:
            continue
        pattern = None
        if keywords:
            try:
                pattern = re.compile("|".join(f"(?:{_keyword_pattern(k)})" for k in keywords), re.I)
            except re.error as e:
                raise ValueError(f"{source}: bad regex in category {name!r}: {e}") from e
        rules.append(Rule(name, kind, pattern, merchants))
    return rules


def load_rules(user_rules: list[str | Path] | None = None, use_defaults: bool = True) -> list[Rule]:
    rules: list[Rule] = []
    for path in user_rules or []:
        with open(path, "rb") as f:
            rules.extend(_rules_from_toml(tomllib.load(f), str(path)))
    if use_defaults:
        text = resources.files("spendstories").joinpath("default_rules.toml").read_text("utf-8")
        rules.extend(_rules_from_toml(tomllib.loads(text), "default_rules.toml"))
    return rules


def category_kinds(rules: list[Rule]) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for r in rules:
        kinds.setdefault(r.category, r.kind)
    kinds.setdefault(UNCATEGORIZED, "expense")
    kinds.setdefault(OTHER_INCOME, "income")
    return kinds


_NOISE = re.compile(
    r"^(?:upi|pos|ecom|nfc|vps|vin|imps|neft|rtgs|ach|nach|bil|bill|mmt|int|onl|online|"
    r"purchase|card|debit|credit|txn|ref|sq|tst|pp|paypal)\b[\s/*:\-]*",
    re.I,
)


def merchant_key(description: str) -> str:
    """A short, stable name for the merchant, used to group repeat payments."""
    s = description.lower()
    for _ in range(3):
        s = _NOISE.sub("", s).strip()
    s = re.sub(r"[^a-z&' ]+", " ", s)       # drop digits, refs, punctuation
    words = [w for w in s.split() if len(w) > 1 and w not in {"pvt", "ltd", "private", "limited",
                                                              "inc", "llc", "india", "the", "www",
                                                              "com", "in", "co"}]
    return " ".join(words[:3]) or description.strip().lower()[:30]


def categorize(transactions: list[Transaction], rules: list[Rule]) -> None:
    """Assign category, kind and merchant to each transaction in place."""
    for t in transactions:
        t.merchant = merchant_key(t.description)
        rule = next((r for r in rules if r.matches(t.description, t.merchant)), None)
        if rule is None:
            if t.amount < 0:
                t.category, t.kind = OTHER_INCOME, "income"
            else:
                t.category, t.kind = UNCATEGORIZED, "expense"
            continue
        t.category = rule.category
        if rule.kind == "expense":
            t.kind = "refund" if t.amount < 0 else "expense"
        else:
            t.kind = rule.kind
