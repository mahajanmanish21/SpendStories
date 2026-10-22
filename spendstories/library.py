"""Your SpendStories library: a folder on disk that remembers every statement.

Layout (default ``~/SpendStories``, override with ``--home`` or ``SPENDSTORIES_HOME``):

    Inbox/            drop new statements here
    Imported/YYYY-MM/ statements move here once they're in the database
    spendstories.db   every transaction ever imported (SQLite)
    rules.toml        your categories, tags and splits (checked before the built-in rules)
    config.toml       currency and budgets
    report.html       the latest report

Nothing in here ever leaves your computer.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .models import Transaction

DB_NAME = "spendstories.db"

STARTER_CONFIG = """\
# SpendStories settings. Edit freely; the next report picks changes up.

# Currency symbol shown in reports, e.g. "₹", "$", "€". Leave empty for none.
currency = ""

# Locked statements: save their passwords with  spendstories password add
# (kept in your Mac's Keychain, not in this file).

# Monthly budgets. Use category names exactly as they appear in the report.
# "All spending" is a budget for everything together.
[budgets]
# "All spending" = 90000
# "Dining & Food Delivery" = 8000
# "Shopping" = 10000
"""

STARTER_RULES = """\
# Your SpendStories rules. Checked before the built-in rules, so they win.
# Tip: fix categories, tags and shares by clicking in the report, then use
# "Save my changes" there to get lines you can paste in here.

# ---- Categories ---------------------------------------------------------
# Keywords are case-insensitive ("re:" prefix = regular expression).
# merchants = exact merchant names as shown in the report.
# kind: expense (default) | transfer (ignored) | investment | income
#
# [categories."Dining & Food Delivery"]
# keywords = ["my favourite cafe"]
#
# [categories."Transfers & Card Payments"]
# kind = "transfer"
# keywords = ["my other bank"]

# ---- Tags: group spending across categories (a trip, a wedding, a renovation)
# A transaction gets the tag when it is inside the dates (if given), in one of the
# categories (if given) and matches a keyword/merchant/transaction (if any given).
#
# [tags."Goa trip"]
# from = 2026-05-01
# to = 2026-05-20
# categories = ["Travel", "Dining & Food Delivery", "Transport"]

# ---- Splits: shared expenses where you only bear part of the cost ---------
# Counted at your share everywhere in the report.
#
# [[splits]]
# share = 0.5
# keywords = ["landlord"]
"""


def default_home() -> Path:
    return Path(os.environ.get("SPENDSTORIES_HOME") or Path.home() / "SpendStories").expanduser()


@dataclass
class Library:
    home: Path

    @property
    def inbox(self) -> Path: return self.home / "Inbox"
    @property
    def imported(self) -> Path: return self.home / "Imported"
    @property
    def db_path(self) -> Path: return self.home / DB_NAME
    @property
    def rules_path(self) -> Path: return self.home / "rules.toml"
    @property
    def config_path(self) -> Path: return self.home / "config.toml"
    @property
    def report_path(self) -> Path: return self.home / "report.html"

    def ensure(self) -> "Library":
        for d in (self.home, self.inbox, self.imported):
            d.mkdir(parents=True, exist_ok=True)
        try:
            self.home.chmod(0o700)  # statements are private: owner-only
        except OSError:
            pass
        if not self.rules_path.exists():
            self.rules_path.write_text(STARTER_RULES, encoding="utf-8")
        if not self.config_path.exists():
            self.config_path.write_text(STARTER_CONFIG, encoding="utf-8")
        with self.connect() as con:
            con.executescript(SCHEMA)
        return self

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def exists(self) -> bool:
        return self.db_path.exists()


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL,
    method TEXT,
    rows INTEGER,
    added INTEGER,
    first_date TEXT,
    last_date TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    source TEXT NOT NULL,
    file_id INTEGER REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS transactions_date ON transactions(date);
"""


# ---------------------------------------------------------------- ids

def transaction_id(d: date, description: str, amount: float, occurrence: int) -> str:
    key = f"{d.isoformat()}|{' '.join(description.lower().split())}|{amount:.2f}|{occurrence}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def assign_ids(transactions: list[Transaction]) -> None:
    """Give each transaction a stable id.

    Identical rows inside one statement (two coffees, same day, same price) get
    occurrence numbers 0, 1, ... so they stay distinct, while the same row seen
    again in an overlapping statement maps to the same id and is stored once.
    """
    seen: Counter = Counter()
    for t in transactions:
        k = (t.source, t.date, " ".join(t.description.lower().split()), round(t.amount, 2))
        t.id = transaction_id(t.date, t.description, t.amount, seen[k])
        seen[k] += 1


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- import / read

@dataclass
class ImportOutcome:
    name: str
    status: str            # added | duplicate-file | empty | error
    rows: int = 0
    added: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)


def import_transactions(lib: Library, path: Path, transactions: list[Transaction], method: str,
                        sha: str | None = None) -> ImportOutcome:
    sha = sha or file_sha256(path)
    with lib.connect() as con:
        if con.execute("SELECT 1 FROM files WHERE sha256 = ?", (sha,)).fetchone():
            return ImportOutcome(path.name, "duplicate-file", message="already imported")
        assign_ids(transactions)
        dates = sorted(t.date for t in transactions)
        cur = con.execute(
            "INSERT INTO files (name, sha256, imported_at, method, rows, first_date, last_date) VALUES (?,?,?,?,?,?,?)",
            (path.name, sha, datetime.now().isoformat(timespec="seconds"), method, len(transactions),
             dates[0].isoformat() if dates else None, dates[-1].isoformat() if dates else None))
        file_id = cur.lastrowid
        before = con.total_changes
        con.executemany(
            "INSERT OR IGNORE INTO transactions (id, date, description, amount, source, file_id) VALUES (?,?,?,?,?,?)",
            [(t.id, t.date.isoformat(), t.description, t.amount, t.source, file_id) for t in transactions])
        added = con.total_changes - before
        con.execute("UPDATE files SET added = ? WHERE id = ?", (added, file_id))
    return ImportOutcome(path.name, "added", rows=len(transactions), added=added)


def read_transactions(lib: Library) -> list[Transaction]:
    with lib.connect() as con:
        rows = con.execute("SELECT id, date, description, amount, source FROM transactions ORDER BY date, rowid").fetchall()
    return [Transaction(date=date.fromisoformat(r["date"]), description=r["description"], amount=r["amount"],
                        source=r["source"], id=r["id"]) for r in rows]


def library_status(lib: Library) -> dict:
    with lib.connect() as con:
        files = [dict(r) for r in con.execute("SELECT * FROM files ORDER BY first_date, name")]
        n, first, last = con.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM transactions").fetchone()
        months = [r[0] for r in con.execute("SELECT DISTINCT substr(date, 1, 7) FROM transactions ORDER BY 1")]
    return {"files": files, "transactions": n, "first": first, "last": last, "months": months}


def file_away(lib: Library, path: Path, when: date | None) -> Path:
    """Move a processed statement out of the Inbox into Imported/YYYY-MM/."""
    folder = lib.imported / (when.strftime("%Y-%m") if when else "unknown")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    i = 2
    while target.exists():
        target = folder / f"{path.stem} ({i}){path.suffix}"
        i += 1
    shutil.move(str(path), target)
    return target


# ---------------------------------------------------------------- config

@dataclass
class Config:
    currency: str = ""
    budgets: dict[str, float] = field(default_factory=dict)
    pdf_passwords: list[str] = field(default_factory=list)


def load_config(path: Path | None) -> Config:
    if not path or not Path(path).exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    budgets = {}
    for k, v in (data.get("budgets") or {}).items():
        try:
            if float(v) > 0:
                budgets[str(k)] = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{path}: budget for {k!r} must be a number") from None
    return Config(currency=str(data.get("currency") or ""), budgets=budgets,
                  # Plain-text fallback; `spendstories password add` is the better place.
                  pdf_passwords=[str(p) for p in [*(data.get("passwords") or []), *(data.get("pdf_passwords") or [])]])


def config_passwords(lib: Library) -> list[str]:
    return load_config(lib.config_path).pdf_passwords


def set_budget(path: Path, category: str, amount: float | None) -> None:
    """Add, change (amount) or remove (None) one budget line, keeping the rest of the file."""
    text = path.read_text(encoding="utf-8") if path.exists() else STARTER_CONFIG
    lines = text.splitlines()
    key = '"' + category.replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "[budgets]")
    except StopIteration:
        lines += ["", "[budgets]"]
        start = len(lines) - 1
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
    existing = next((i for i in range(start + 1, end)
                     if lines[i].split("=")[0].strip() in (key, category) and not lines[i].lstrip().startswith("#")), None)
    new_line = f"{key} = {amount:g}" if amount is not None else None
    if existing is not None:
        if new_line:
            lines[existing] = new_line
        else:
            del lines[existing]
    elif new_line:
        lines.insert(start + 1, new_line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
