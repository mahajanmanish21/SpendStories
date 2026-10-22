"""Generate a year of fake statements to try SpendStories on.

    python examples/make_sample_data.py            # writes examples/sample_statements/
    spendstories examples/sample_statements --currency ₹ --open

Produces three differently-shaped files so every loader path gets exercised:
  card_a.csv   credit card CSV, preamble lines, 'Cr' suffix on payments
  bank.xlsx    bank account Excel export with Withdrawal/Deposit columns
  card_b.pdf   credit card PDF statement (needs reportlab; skipped otherwise)
All data is synthetic.
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path


def months(start: date, n: int):
    y, m = start.year, start.month
    for _ in range(n):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def generate(out: Path, start: date = date(2025, 11, 1), n_months: int = 12, seed: int = 7) -> None:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    card_a, card_b, bank = [], [], []

    def day(y, m, d):
        return date(y, m, min(d, 28))

    for i, (y, m) in enumerate(months(start, n_months)):
        # --- card A: everyday spending
        for _ in range(rng.randint(5, 7)):
            card_a.append((day(y, m, rng.randint(1, 28)), rng.choice(
                ["BIGBASKET BANGALORE", "BLINKIT GURGAON", "DMART AVENUE SUPERMARTS"]), rng.uniform(900, 2600)))
        # Dining rises steadily through the year.
        for _ in range(4 + i // 2):
            card_a.append((day(y, m, rng.randint(1, 28)), rng.choice(
                ["SWIGGY BANGALORE", "ZOMATO LTD", "STARBUCKS COFFEE", "THIRD WAVE COFFEE"]),
                rng.uniform(250, 700) * (1 + i * 0.06)))
        for _ in range(3):
            card_a.append((day(y, m, rng.randint(1, 28)), rng.choice(["UBER INDIA", "RAPIDO", "OLA CABS"]),
                           rng.uniform(150, 450)))
        card_a.append((day(y, m, 3), "NETFLIX.COM", 499.0 if i < 7 else 649.0))
        card_a.append((day(y, m, 9), "SPOTIFY INDIA", 119.0))
        card_a.append((day(y, m, 15), "INDIAN OIL PETROL PUMP", rng.uniform(2500, 3200)))
        if m == 12:  # festive season gifting
            card_a.append((day(y, m, 20), "FERNS N PETALS GIFT", 4200.0))
        if i >= 9:  # a subscription that started recently
            card_a.append((day(y, m, 17), "YOUTUBE PREMIUM GOOGLE", 129.0))
        if (y, m) == (2026, 9):  # paid the bill late once...
            card_a += [(day(y, m, 5), "LATE PAYMENT FEE", 750.0), (day(y, m, 5), "IGST ON LATE PAYMENT FEE", 135.0)]
        if (y, m) == (2026, 10):  # ...and paid interest on the carried balance
            card_a.append((day(y, m, 4), "FINANCE CHARGES", 1240.0))
        prev_total = sum(a for d, _, a in card_a if (d.year, d.month) == (y, m))
        card_a.append((day(y, m, 26), "PAYMENT RECEIVED - THANK YOU", -round(prev_total, 2)))

        # --- card B: shopping & travel
        for _ in range(rng.randint(2, 4)):
            card_b.append((day(y, m, rng.randint(1, 28)), rng.choice(
                ["AMAZON PAY INDIA", "FLIPKART INTERNET", "MYNTRA DESIGNS"]), rng.uniform(600, 3500)))
        if (y, m) == (2026, 5):  # summer holiday spike
            card_b += [(day(y, m, 4), "MAKEMYTRIP INDIA", 38500.0), (day(y, m, 6), "INDIGO AIRLINES", 21400.0),
                       (day(y, m, 18), "TAJ HOTELS GOA", 26800.0)]
        if (y, m) == (2026, 8):  # one big purchase + a refund
            card_b += [(day(y, m, 11), "APPLE STORE BKC", 89900.0), (day(y, m, 19), "AMAZON PAY INDIA REFUND", -2399.0)]
        if i % 3 == 0:
            card_b.append((day(y, m, 12), "APOLLO PHARMACY", rng.uniform(800, 1800)))
        if (y, m) == (2026, 6):  # charged twice?
            card_b += [(day(y, m, 12), "DECATHLON SPORTS INDIA", 2499.0), (day(y, m, 13), "DECATHLON SPORTS INDIA", 2499.0)]
        if (y, m) == (2026, 3):  # a purchase in dollars, with the card's markup
            card_b += [(day(y, m, 8), "AWS EMEA USD 12.00", 1015.0), (day(y, m, 8), "FOREX MARKUP FEE", 35.5)]

        # --- bank account
        bank.append((day(y, m, 1), "NEFT CR-ACME TECH PVT LTD-SALARY NOV", 0, 185000.0))
        bank.append((day(y, m, 2), "IMPS/RENT/LANDLORD SHARMA", 42000.0, 0))
        bank.append((day(y, m, 5), "ACH D- ZERODHA BROKING SIP", 15000.0, 0))
        bank.append((day(y, m, 7), "BESCOM ELECTRICITY BILL", rng.uniform(1400, 2600) * (1.6 if m in (4, 5) else 1), 0))
        bank.append((day(y, m, 8), "AIRTEL POSTPAID", 799.0, 0))
        bank.append((day(y, m, 10), "ACT FIBERNET BROADBAND", 1059.0, 0))
        bank.append((day(y, m, 14), "ATM CASH WDL MG ROAD", float(rng.choice([2000, 3000, 5000])), 0))
        bank.append((day(y, m, 27), "CREDIT CARD PAYMENT CARD A", round(-card_a[-1][2], 2), 0))
        if m == 3:
            bank.append((day(y, m, 20), "LIC OF INDIA PREMIUM", 24500.0, 0))

    # card_a.csv: preamble, then Date / Transaction Details / Amount with Cr suffix.
    with open(out / "card_a.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Credit Card Statement"])
        w.writerow(["Card No: XXXX XXXX XXXX 1234"])
        w.writerow([])
        w.writerow(["Date", "Transaction Details", "Amount (INR)"])
        for d, desc, a in sorted(card_a):
            w.writerow([d.strftime("%d/%m/%Y"), desc, f"{abs(a):,.2f}" + (" Cr" if a < 0 else "")])

    # bank.xlsx
    try:
        from openpyxl import Workbook
    except ImportError:
        print("openpyxl not installed; skipping bank.xlsx", file=sys.stderr)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Statement"
        ws.append(["Savings Account Statement"])
        ws.append(["Account: XXXXXX7890"])
        ws.append([])
        ws.append(["Txn Date", "Narration", "Withdrawal Amt", "Deposit Amt", "Closing Balance"])
        balance = 250000.0
        for d, desc, wd, dep in sorted(bank, key=lambda r: r[0]):
            balance += dep - wd
            ws.append([d.strftime("%d/%m/%y"), desc, round(wd, 2) or None, round(dep, 2) or None, round(balance, 2)])
        wb.save(out / "bank.xlsx")

    # card_b.pdf
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        print("reportlab not installed; skipping card_b.pdf", file=sys.stderr)
    else:
        rows = sorted(card_b)
        c = canvas.Canvas(str(out / "card_b.pdf"), pagesize=A4)
        per_page = 45
        for p in range(0, len(rows), per_page):
            y = 800
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "Platinum Card - Statement of Account")
            y -= 26
            c.setFont("Helvetica", 9)
            c.drawString(40, y, "Date")
            c.drawString(130, y, "Transaction Description")
            c.drawRightString(550, y, "Amount (Rs.)")
            y -= 16
            for d, desc, a in rows[p:p + per_page]:
                c.drawString(40, y, d.strftime("%d %b %Y"))
                c.drawString(130, y, desc)
                c.drawRightString(550, y, f"{abs(a):,.2f}" + (" Cr" if a < 0 else ""))
                y -= 15
            c.drawString(40, 40, f"Page {p // per_page + 1}")
            c.showPage()
        c.save()
    print(f"Sample statements written to {out}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "sample_statements"
    generate(target)
