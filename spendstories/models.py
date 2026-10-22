from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Transaction:
    date: date
    description: str
    # Positive = money going out (a spend), negative = money coming in
    # (refund, payment received, salary...). Every loader normalises to this.
    amount: float
    source: str
    category: str = "Uncategorized"
    # expense | refund | income | transfer
    kind: str = "expense"
    merchant: str = ""


@dataclass
class LoadResult:
    source: str
    transactions: list[Transaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    method: str = ""
