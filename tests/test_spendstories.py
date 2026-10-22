import socket
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

from spendstories.analysis import analyze, dedupe  # noqa: E402
from spendstories.categorize import categorize, load_rules, merchant_key  # noqa: E402
from spendstories.loaders import extract_from_rows, load_file  # noqa: E402
from spendstories.models import Transaction  # noqa: E402
from spendstories.parsing import detect_dayfirst, parse_amount, parse_date  # noqa: E402


# ---------------------------------------------------------------- parsing

@pytest.mark.parametrize("text,dayfirst,expected", [
    ("05/01/2026", True, date(2026, 1, 5)),
    ("05/01/2026", False, date(2026, 5, 1)),
    ("25/01/26", False, date(2026, 1, 25)),      # unambiguous wins over preference
    ("2026-03-04", True, date(2026, 3, 4)),
    ("12 Jan 2026", True, date(2026, 1, 12)),
    ("12-Jan-26", True, date(2026, 1, 12)),
    ("Jan 12, 2026", True, date(2026, 1, 12)),
    ("05/01/2026 14:32", True, date(2026, 1, 5)),
    ("Opening balance", True, None),
    ("31/02/2026", True, None),
])
def test_parse_date(text, dayfirst, expected):
    assert parse_date(text, dayfirst) == expected


def test_detect_dayfirst():
    assert detect_dayfirst(["01/02/2026", "25/02/2026"]) is True
    assert detect_dayfirst(["02/25/2026", "01/02/2026"]) is False
    assert detect_dayfirst(["01/02/2026"], default=False) is False


@pytest.mark.parametrize("text,expected", [
    ("1,234.50", (1234.5, None)),
    ("₹ 1,234.50", (1234.5, None)),
    ("$-12.00", (-12.0, None)),
    ("-12.00", (-12.0, None)),
    ("(45.10)", (-45.1, None)),
    ("45.10-", (-45.1, None)),
    ("5,000.00 Cr", (5000.0, "cr")),
    ("5,000.00 DR", (5000.0, "dr")),
    ("", (None, None)),
    ("abc", (None, None)),
    (12.5, (12.5, None)),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


# ---------------------------------------------------------------- loaders

def test_card_csv_with_preamble_and_cr_suffix(tmp_path):
    f = tmp_path / "card.csv"
    f.write_text("Card statement\nCard: XXXX1234\n\nDate,Transaction Details,Amount (INR)\n"
                 "02/01/2026,SWIGGY,450.00\n03/01/2026,PAYMENT RECEIVED,\"1,000.00 Cr\"\n"
                 "Total,,550.00\n")
    res = load_file(f)
    assert [(t.date, t.description, t.amount) for t in res.transactions] == [
        (date(2026, 1, 2), "SWIGGY", 450.0),
        (date(2026, 1, 3), "PAYMENT RECEIVED", -1000.0),
    ]


def test_bank_debit_credit_columns():
    rows = [["Txn Date", "Narration", "Withdrawal Amt", "Deposit Amt", "Closing Balance"],
            ["01/02/26", "SALARY", "", "50,000.00", "60,000.00"],
            ["02/02/26", "RENT", "20,000.00", "", "40,000.00"],
            ["", "continued narration", "", "", ""],
            ["", "Opening balance", "", "", "10,000"]]
    txns, _ = extract_from_rows(rows, "bank")
    assert [(t.description, t.amount) for t in txns] == [("SALARY", -50000.0),
                                                        ("RENT continued narration", 20000.0)]


def test_single_amount_column_negative_spend_is_flipped():
    rows = [["Date", "Description", "Amount"],
            ["2026-01-01", "COFFEE", "-4.50"], ["2026-01-02", "GROCER", "-60.00"],
            ["2026-01-03", "PAYCHECK", "2000.00"]]
    txns, warnings = extract_from_rows(rows, "bank")
    assert [t.amount for t in txns] == [4.5, 60.0, -2000.0]
    assert any("flipped" in w for w in warnings)
    txns, _ = extract_from_rows(rows, "bank", sign="positive-spend")
    assert [t.amount for t in txns] == [-4.5, -60.0, 2000.0]


def test_crdr_type_column():
    rows = [["Date", "Description", "Amount", "Dr/Cr"],
            ["01/03/2026", "AMAZON", "999", "DR"], ["02/03/2026", "REFUND AMAZON", "999", "CR"]]
    txns, _ = extract_from_rows(rows, "card")
    assert [t.amount for t in txns] == [999.0, -999.0]


def test_headerless_csv_columns_are_guessed(tmp_path):
    f = tmp_path / "raw.csv"
    f.write_text("01/04/2026,UBER TRIP,12.50\n02/04/2026,NETFLIX.COM,15.99\n05/04/2026,WHOLE FOODS,80.10\n")
    res = load_file(f)
    assert [t.amount for t in res.transactions] == [12.5, 15.99, 80.1]
    assert any("guessed" in w for w in res.warnings)


def test_sample_files_all_load(tmp_path):
    from make_sample_data import generate

    generate(tmp_path)
    for name in ("card_a.csv", "bank.xlsx", "card_b.pdf"):
        if not (tmp_path / name).exists():
            continue  # optional dependency missing
        res = load_file(tmp_path / name)
        assert len(res.transactions) > 30, name
        assert all(t.date.year in (2025, 2026) for t in res.transactions)
    if (tmp_path / "card_b.pdf").exists():
        pdf = load_file(tmp_path / "card_b.pdf").transactions
        refund = [t for t in pdf if "REFUND" in t.description]
        assert refund and refund[0].amount == -2399.0
        apple = [t for t in pdf if "APPLE" in t.description]
        assert apple and apple[0].amount == 89900.0


# ---------------------------------------------------------------- categorisation

def _t(d, desc, amount, source="s"):
    return Transaction(date=d, description=desc, amount=amount, source=source)


def test_categorize_defaults_and_kinds():
    rules = load_rules()
    txns = [_t(date(2026, 1, 1), "UPI/SWIGGYINSTAMART/123", 300),
            _t(date(2026, 1, 1), "COCA COLA DISTRIBUTOR", 50),
            _t(date(2026, 1, 1), "PAYMENT RECEIVED - THANK YOU", -5000),
            _t(date(2026, 1, 1), "AMAZON REFUND", -200),
            _t(date(2026, 1, 1), "NEFT CR ACME SALARY", -90000),
            _t(date(2026, 1, 1), "SOMETHING ODD", 10),
            _t(date(2026, 1, 1), "MYSTERY CREDIT XYZ", -10)]
    categorize(txns, rules)
    got = [(t.category, t.kind) for t in txns]
    assert got[0] == ("Groceries", "expense")       # instamart before swiggy dining
    assert got[1][0] != "Transport"                  # "ola" must not match "cola"
    assert got[2] == ("Transfers & Card Payments", "transfer")
    assert got[3] == ("Shopping", "refund")
    assert got[4] == ("Income", "income")
    assert got[5] == ("Uncategorized", "expense")
    assert got[6] == ("Other Income", "income")


def test_user_rules_take_priority(tmp_path):
    f = tmp_path / "mine.toml"
    f.write_text('[categories.Kids]\nkeywords = ["amazon kids"]\n')
    txns = [_t(date(2026, 1, 1), "AMAZON KIDS STORE", 100)]
    categorize(txns, load_rules([f]))
    assert txns[0].category == "Kids"


def test_merchant_key():
    assert merchant_key("UPI/NETFLIX.COM/9876543") == merchant_key("POS NETFLIX COM 1234")
    assert merchant_key("IMPS/RENT/LANDLORD SHARMA") == "rent landlord sharma"


# ---------------------------------------------------------------- analysis

def _year_of(builder):
    txns = []
    for i in range(12):
        y, m = (2025 + (i + 10) // 12, (i + 10) % 12 + 1)
        txns.extend(builder(i, y, m))
    return txns


def test_trend_spike_recurring_detection():
    def month(i, y, m):
        out = [_t(date(y, m, 2), "LANDLORD RENT", 1000.0),
               _t(date(y, m, 5), "BIGBASKET", 300.0 + (i % 3) * 5),
               _t(date(y, m, 9), "SWIGGY ORDER", 100.0 + 25 * i),          # steady rise
               _t(date(y, m, 3), "NETFLIX.COM", 10.0 if i < 8 else 13.0),  # price rise
               _t(date(y, m, 1), "SALARY ACME", -5000.0),
               _t(date(y, m, 28), "WHOLE MONTH END", 1.0)]
        if i == 6:
            out.append(_t(date(y, m, 15), "MAKEMYTRIP FLIGHTS", 2500.0))   # spike month
        return out

    txns = _year_of(month)
    categorize(txns, load_rules())
    a = analyze(txns)
    assert a.partial_months == set()
    trend_cats = {t["category"]: t["direction"] for t in a.trends}
    assert trend_cats.get("Dining & Food Delivery") == "up"
    assert "Rent & Housing" not in trend_cats
    assert "Travel" not in trend_cats               # one spike isn't a trend
    spikes = {(s["category"], s["month"]) for s in a.month_spikes}
    assert ("Travel", a.months[6]) in spikes
    assert ("All spending", a.months[6]) in spikes
    assert not any(s[0] == "Rent & Housing" for s in spikes)
    rec = {r["merchant"]: r for r in a.recurring}
    assert rec["netflix"]["frequency"] == "monthly"
    assert rec["netflix"]["price_change"] == pytest.approx(0.3)
    assert rec["landlord rent"]["price_change"] == 0
    assert [l["description"] for l in a.large_transactions] == ["MAKEMYTRIP FLIGHTS"]
    assert a.overview["income"] == 60000
    assert any("Netflix" in line for line in a.insights)


def test_partial_months_excluded_from_baseline():
    txns = [_t(date(2026, 1, 20), "BIGBASKET", 50.0)] + [
        _t(date(2026, m, d), "BIGBASKET", 100.0) for m in (2, 3, 4) for d in (1, 28)]
    txns.append(_t(date(2026, 5, 3), "BIGBASKET", 10.0))
    categorize(txns, load_rules())
    a = analyze(txns)
    assert a.partial_months == {"2026-01", "2026-05"}
    assert a.full_months == ["2026-02", "2026-03", "2026-04"]
    assert a.overview["avg_monthly_spend"] == 200


def test_dedupe_across_files_only():
    same_file = [_t(date(2026, 1, 1), "COFFEE", 3.0, "a"), _t(date(2026, 1, 1), "COFFEE", 3.0, "a")]
    overlap = [_t(date(2026, 1, 1), "COFFEE", 3.0, "b")]
    kept, dropped = dedupe(same_file + overlap)
    assert len(kept) == 2 and dropped == 1


# ---------------------------------------------------------------- privacy & CLI

def test_network_is_blocked_by_cli(tmp_path, monkeypatch):
    from spendstories import offline
    from spendstories.cli import main

    saved = (socket.socket, socket.create_connection, socket.getaddrinfo,
             socket.gethostbyname, socket.gethostbyname_ex)
    try:
        f = tmp_path / "s.csv"
        f.write_text("Date,Description,Amount\n01/01/2026,UBER,10\n")
        assert main([str(f), "-o", str(tmp_path / "r.html"), "-q"]) == 0
        with pytest.raises(offline.NetworkBlockedError):
            socket.create_connection(("example.com", 443))
        with pytest.raises(offline.NetworkBlockedError):
            socket.getaddrinfo("example.com", 443)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(offline.NetworkBlockedError):
            s.connect(("93.184.216.34", 80))
        s.close()
    finally:
        (socket.socket, socket.create_connection, socket.getaddrinfo,
         socket.gethostbyname, socket.gethostbyname_ex) = saved
        offline._installed = False


def test_cli_end_to_end(tmp_path):
    from make_sample_data import generate
    from spendstories import offline
    from spendstories.cli import main

    saved = (socket.socket, socket.create_connection, socket.getaddrinfo,
             socket.gethostbyname, socket.gethostbyname_ex)
    try:
        generate(tmp_path / "in")
        out, csv_out = tmp_path / "report.html", tmp_path / "t.csv"
        assert main([str(tmp_path / "in"), "-o", str(out), "--csv", str(csv_out), "--currency", "₹", "-q"]) == 0
        page = out.read_text(encoding="utf-8")
        assert "Content-Security-Policy" in page and "default-src 'none'" in page
        # The report must not reference anything external.
        for needle in ("http://", "https://", "src=\"//", "@import"):
            assert needle not in page
        assert "Travel" in page and "Spikes" in page
        assert csv_out.read_text(encoding="utf-8").startswith("date,description,amount")
    finally:
        (socket.socket, socket.create_connection, socket.getaddrinfo,
         socket.gethostbyname, socket.gethostbyname_ex) = saved
        offline._installed = False


def test_bank_pdf_sign_from_running_balance(tmp_path):
    canvas_mod = pytest.importorskip("reportlab.pdfgen.canvas")
    f = tmp_path / "bank.pdf"
    c = canvas_mod.Canvas(str(f))
    lines = [("01-03-2026", "Opening Balance", "", "10,000.00"),
             ("02-03-2026", "UPI/ZOMATO/123", "450.00", "9,550.00"),
             ("03-03-2026", "NEFT SALARY ACME", "50,000.00", "59,550.00"),
             ("04-03-2026", "ATM WDL", "2,000.00", "57,550.00")]
    y = 780
    for d, desc, amt, bal in lines:
        c.drawString(40, y, d)
        c.drawString(120, y, desc)
        if amt:
            c.drawRightString(450, y, amt)
        c.drawRightString(550, y, bal)
        y -= 16
    c.save()
    res = load_file(f)
    assert [(t.description, t.amount) for t in res.transactions] == [
        ("UPI/ZOMATO/123", 450.0), ("NEFT SALARY ACME", -50000.0), ("ATM WDL", 2000.0)]
