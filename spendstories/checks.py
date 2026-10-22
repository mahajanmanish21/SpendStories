"""Money-leak checks: things worth a second look in your statements."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta

from .formatting import money, pct
from .models import Transaction

FEE_PATTERN = re.compile(
    r"late (?:payment )?fee|late charge|finance charge|interest (?:charge|on)|\binterest\b(?!.*credit)|"
    r"over ?limit|annual fee|joining fee|renewal fee|forex markup|markup fee|cross currency|"
    r"currency conversion|foreign (?:transaction|txn) fee|cash advance fee|bank charges?|\bchrg\b|"
    r"min(?:imum)? bal|non[- ]maintenance|penal|bounce|return charge|sms (?:alert )?charge", re.I)
FOREIGN_PATTERN = re.compile(
    r"\b(?:USD|EUR|GBP|AED|SGD|AUD|CAD|JPY|CHF|THB|MYR|HKD|NZD|SAR|QAR)\b|forex|cross currency|"
    r"currency conversion|international|\bintl\b|foreign", re.I)


def run_checks(transactions: list[Transaction], recurring: list[dict], avg_month: float) -> list[dict]:
    """Return a list of findings: {kind, severity, title, detail, amount, items: [transaction ids]}."""
    findings: list[dict] = []
    spend = [t for t in transactions if t.kind == "expense"]
    floor = max(avg_month * 0.002, 1.0)

    # 1. Possible duplicate charges: same merchant, same amount, within 3 days.
    by_key = defaultdict(list)
    for t in spend:
        if t.amount >= floor:
            by_key[(t.merchant, round(t.amount, 2))].append(t)
    recurring_merchants = {r["merchant"] for r in recurring if r["frequency"] in ("weekly",)}
    for (merchant, amount), group in by_key.items():
        if merchant in recurring_merchants or len(group) < 2:
            continue
        group.sort(key=lambda t: t.date)
        for a, b in zip(group, group[1:]):
            if (b.date - a.date) <= timedelta(days=3):
                findings.append({
                    "kind": "duplicate", "severity": "warn",
                    "title": f"Possible double charge: {a.description}",
                    "detail": f"{money(amount)} charged on {a.date:%d %b} and {b.date:%d %b %Y}"
                              + (" (different statements)" if a.source != b.source else "")
                              + ". Fine if you really bought twice; otherwise ask for a refund.",
                    "amount": amount, "date": b.date.isoformat(), "items": [a.id, b.id],
                })

    # 2. Fees, interest and penalties.
    fees = [t for t in spend if t.category == "Fees & Charges" or FEE_PATTERN.search(t.description)]
    if fees:
        total = sum(t.amount for t in fees)
        interest = [t for t in fees if re.search(r"interest|finance charge", t.description, re.I)]
        late = [t for t in fees if re.search(r"late|penal|bounce|over ?limit", t.description, re.I)]
        detail = f"{len(fees)} charges."
        if interest:
            detail += f" Interest: {money(sum(t.amount for t in interest))}, which usually means a card bill wasn't paid in full."
        if late:
            detail += f" Late or penalty fees: {money(sum(t.amount for t in late))}. Autopay avoids these."
        findings.append({"kind": "fees", "severity": "warn" if (interest or late) else "info",
                         "title": f"You paid {money(total)} in fees and charges", "detail": detail,
                         "amount": total, "items": [t.id for t in sorted(fees, key=lambda t: t.date)]})

    # 3. Subscriptions: price rises and new ones.
    if transactions:
        end = max(t.date for t in transactions)
        for r in recurring:
            if r["price_change"] >= 0.05:
                findings.append({"kind": "price", "severity": "warn",
                                 "title": f"{r['merchant'].title()} went up {pct(r['price_change'])}",
                                 "detail": f"Now {money(r['amount'])} {r['frequency']} "
                                           f"(about {money(r['monthly_cost'] * 12)} a year). Still worth it?",
                                 "amount": r["monthly_cost"] * 12, "merchant": r["merchant"], "items": []})
            if (end - r["first"]).days <= 100 and r["count"] >= 2:
                findings.append({"kind": "new-recurring", "severity": "info",
                                 "title": f"New recurring payment: {r['merchant'].title()}",
                                 "detail": f"Started {r['first']:%d %b %Y}, {money(r['amount'])} {r['frequency']}. "
                                           "Was that intended (free trial turned paid)?",
                                 "amount": r["monthly_cost"] * 12, "merchant": r["merchant"], "items": []})
        subs = [r for r in recurring if r["category"] == "Subscriptions & Entertainment"]
        if subs:
            yearly = sum(r["monthly_cost"] for r in subs) * 12
            findings.append({"kind": "subscriptions", "severity": "info",
                             "title": f"{len(subs)} subscriptions cost about {money(yearly)} a year",
                             "detail": ", ".join(f"{r['merchant'].title()} {money(r['amount'])}" for r in subs[:8])
                                       + ". Cancel the ones you don't use.",
                             "amount": yearly, "items": []})

    # 4. Foreign-currency spending (usually carries a markup).
    foreign = [t for t in spend if FOREIGN_PATTERN.search(t.description) and t not in fees]
    if foreign:
        total = sum(t.amount for t in foreign)
        findings.append({"kind": "foreign", "severity": "info",
                         "title": f"{len(foreign)} foreign-currency purchase{'s' if len(foreign) != 1 else ''}, {money(total)}",
                         "detail": "Cards often add a 2-3.5% markup on these. A zero-markup card can save "
                                   f"roughly {money(total * 0.03)}.",
                         "amount": total, "items": [t.id for t in foreign]})

    order = {"warn": 0, "info": 1}
    findings.sort(key=lambda f: (order[f["severity"]], -f["amount"]))
    return findings
