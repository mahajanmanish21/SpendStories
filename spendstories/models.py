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
    # Stable across runs and imports; used by tags/splits that name single transactions.
    id: str = ""
    tags: list[str] = field(default_factory=list)
    # Your share of a shared expense (0-1). ``amount`` is already scaled by it;
    # ``original_amount`` keeps what the statement said.
    share: float = 1.0
    original_amount: float | None = None


@dataclass
class LoadResult:
    source: str
    transactions: list[Transaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    method: str = ""
    # True when the file is password-protected and no password we tried opened it.
    locked: bool = False
    unlocked_with: str | None = None   # label of the password that opened it
