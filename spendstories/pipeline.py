"""The steps shared by one-off runs and the library: read → categorise → analyse → report."""

from __future__ import annotations

import calendar
import csv
import getpass
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .analysis import Analysis, Settings, analyze
from .categorize import categorize, category_kinds, load_rules
from .checks import run_checks
from .extras import apply_extras, load_extras
from .formatting import money, pct
from .loaders import load_bytes
from .models import LoadResult, Transaction
from .report import render_html


@dataclass
class ReadOptions:
    sign: str = "auto"
    dayfirst: bool | None = None
    # (label, password) pairs to try on locked files, e.g. from the Keychain.
    passwords: list[tuple[str, str]] = field(default_factory=list)
    interactive: bool = False
    # Called with (file name, password) after a typed-in password works, to offer saving it.
    on_new_password: Callable[[str, str], None] | None = None


def read_statement(path: Path, opts: ReadOptions) -> LoadResult:
    """Load one file. Locked files are tried with every known password, then (if allowed) we ask."""
    data = path.read_bytes()
    res = load_bytes(path.name, data, opts.sign, None, opts.dayfirst)
    if not res.locked:
        return res
    for label, pw in opts.passwords:
        res = load_bytes(path.name, data, opts.sign, pw, opts.dayfirst)
        if not res.locked:
            res.unlocked_with = label
            return res
    if opts.interactive and sys.stdin.isatty():
        for attempt in range(3):
            pw = getpass.getpass(f"{path.name} is locked. Password (Enter to skip): ")
            if not pw:
                break
            res = load_bytes(path.name, data, opts.sign, pw, opts.dayfirst)
            if not res.locked:
                res.unlocked_with = "typed"
                opts.passwords.append(("typed", pw))  # try it on the next files too
                if opts.on_new_password:
                    opts.on_new_password(path.name, pw)
                return res
            print("  That password didn't open it." + (" Try again." if attempt < 2 else ""), file=sys.stderr)
    return res


def describe_load(path: Path, res: LoadResult) -> str:
    if res.locked:
        return f"  🔒 {path.name}: locked, and none of your saved passwords open it"
    if not res.transactions:
        return f"  ✗ {path.name}: no transactions found" + (f" ({'; '.join(res.warnings)})" if res.warnings else "")
    dates = sorted(t.date for t in res.transactions)
    return (f"  ✓ {path.name}: {len(res.transactions)} transactions "
            f"({dates[0]:%d %b %Y} – {dates[-1]:%d %b %Y}, {res.method}"
            + (", unlocked" if getattr(res, "unlocked_with", None) else "") + ")")


@dataclass
class Built:
    transactions: list[Transaction]
    analysis: Analysis
    checks: list[dict]
    kinds: dict[str, str]
    budgets: dict[str, float]
    budget_status: list[dict]


def build(transactions: list[Transaction], rule_files: list, use_default_rules: bool = True,
          budgets: dict[str, float] | None = None) -> Built:
    rules = load_rules(rule_files, use_defaults=use_default_rules)
    categorize(transactions, rules)
    apply_extras(transactions, load_extras(rule_files))
    analysis = analyze(transactions, Settings())
    checks = run_checks(transactions, analysis.recurring, analysis.overview["avg_monthly_spend"])
    kinds = category_kinds(rules)
    for t in transactions:
        kinds.setdefault(t.category, "expense")
    budgets = dict(budgets or {})
    return Built(transactions, analysis, checks, kinds, budgets, budget_status(analysis, budgets))


def budget_status(a: Analysis, budgets: dict[str, float]) -> list[dict]:
    """How the latest month is doing against each budget, projecting a month still in progress."""
    if not budgets:
        return []
    month = a.months[-1]
    dim = calendar.monthrange(a.end.year, a.end.month)[1]
    # Same rule as partial months elsewhere: within 3 days of month end counts as complete.
    elapsed = a.end.day / dim if a.end.day < dim - 3 else 1.0
    out = []
    for cat, limit in budgets.items():
        if cat == "All spending":
            spent = float(a.monthly_total[month])
        elif cat in a.by_category_month.index:
            spent = float(a.by_category_month.loc[cat, month])
        else:
            spent = 0.0
        projected = spent / elapsed if elapsed > 0.1 else spent
        status = "over" if spent > limit else "at-risk" if projected > limit * 1.02 else "ok"
        out.append({"category": cat, "budget": limit, "spent": spent, "projected": projected,
                    "status": status, "month": month, "in_progress": elapsed < 1.0})
    order = {"over": 0, "at-risk": 1, "ok": 2}
    out.sort(key=lambda b: (order[b["status"]], -b["spent"] / b["budget"]))
    return out


def write_report(path: Path, built: Built, notes: list[str], currency: str, home: Path | None = None) -> None:
    html = render_html(built.transactions, built.kinds, built.analysis.recurring, notes, currency,
                       budgets=built.budgets, checks=built.checks, home=str(home) if home else None)
    path.write_text(html, encoding="utf-8")


def write_csv(path: Path, transactions: list[Transaction]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "description", "amount", "original_amount", "share", "category", "kind",
                    "merchant", "tags", "source", "id"])
        for t in sorted(transactions, key=lambda t: t.date):
            w.writerow([t.date.isoformat(), t.description, f"{t.amount:.2f}",
                        f"{(t.original_amount if t.original_amount is not None else t.amount):.2f}",
                        f"{t.share:g}", t.category, t.kind, t.merchant, "; ".join(t.tags), t.source, t.id])


def print_summary(built: Built, report: Path) -> None:
    a, o = built.analysis, built.analysis.overview
    print()
    print(f"Spend Stories · {a.start:%d %b %Y} – {a.end:%d %b %Y}")
    print(f"  Total spending   {money(o['total_spend'])}   (avg {money(o['avg_monthly_spend'])}/month)")
    if o["income"]:
        print(f"  Income           {money(o['income'])}")
    print()
    print("  Top categories")
    for r in a.category_summary.head(8).itertuples():
        arrow = {"up": " ▲", "down": " ▼"}.get(r.trend, "")
        print(f"    {r.category:<32} {money(r.total):>14}  {pct(r.share):>4}{arrow}")
    alerts = [b for b in built.budget_status if b["status"] != "ok"]
    if alerts:
        print()
        print("  Budget alerts")
        for b in alerts:
            if b["status"] == "over":
                print(f"    ✗ {b['category']}: {money(b['spent'])} of {money(b['budget'])} - over budget")
            else:
                print(f"    ! {b['category']}: {money(b['spent'])} of {money(b['budget'])} so far, "
                      f"heading for {money(b['projected'])}")
    if a.insights:
        print()
        print("  Highlights")
        for line in a.insights:
            print(f"    • {line}")
    warn = [c for c in built.checks if c["severity"] == "warn"]
    if warn:
        print()
        print("  Worth a look")
        for c in warn[:6]:
            print(f"    • {c['title']}")
    print()
    print(f"Report: {report.resolve()}")
