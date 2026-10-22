"""Command line entry point: spendstories <statements...>"""

from __future__ import annotations

import argparse
import csv
import getpass
import sys
from pathlib import Path

from .offline import block_network

STARTER_RULES = """\
# My SpendStories rules. These are checked before the built-in rules, so they
# win. Keywords are case-insensitive; prefix with "re:" for a regex.
# Run with: spendstories statements/ --rules my_rules.toml
#
# kind: expense (default) | transfer (ignored) | investment | income

[categories."Dining & Food Delivery"]
keywords = ["my favourite cafe"]

[categories."Transfers & Card Payments"]
kind = "transfer"
keywords = ["my other bank", "re:^to savings"]

[categories."Kids"]
keywords = ["toy store", "kidzania", "school fees"]
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spendstories",
        description="Analyse credit card and bank statements locally: categories, trends, spikes. "
                    "Runs fully offline - nothing is sent anywhere.",
    )
    p.add_argument("inputs", nargs="*", help="statement files (CSV, XLSX, XLS, PDF) or folders containing them")
    p.add_argument("-o", "--output", default="spend_report.html", help="HTML report path (default: %(default)s)")
    p.add_argument("--csv", metavar="PATH", help="also write all categorised transactions to this CSV")
    p.add_argument("--rules", action="append", default=[], metavar="TOML",
                   help="your own category rules (checked before the built-in ones); repeatable")
    p.add_argument("--no-default-rules", action="store_true", help="use only your --rules files")
    p.add_argument("--init-rules", metavar="PATH", help="write a starter rules file and exit")
    p.add_argument("--currency", default="", help="currency symbol for display, e.g. ₹, $, €")
    p.add_argument("--sign", choices=["auto", "positive-spend", "negative-spend"], default="auto",
                   help="for files with one signed Amount column: are spends positive or negative? "
                        "(default: guess per file)")
    dates = p.add_mutually_exclusive_group()
    dates.add_argument("--dayfirst", dest="dayfirst", action="store_true", default=None,
                       help="force dd/mm/yyyy dates when ambiguous")
    dates.add_argument("--monthfirst", dest="dayfirst", action="store_false",
                       help="force mm/dd/yyyy dates when ambiguous")
    p.add_argument("--pdf-password", help="password for protected PDF statements (prompted if needed)")
    p.add_argument("--no-dedupe", action="store_true",
                   help="keep identical rows that appear in more than one file")
    p.add_argument("--open", action="store_true", help="open the report in your browser when done")
    p.add_argument("-q", "--quiet", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    # Before anything touches a statement, make networking impossible.
    block_network()

    from .analysis import Settings, analyze, dedupe
    from .categorize import categorize, category_kinds, load_rules
    from .formatting import money, pct, set_currency
    from .loaders import collect_files, load_file
    from .report import render_html

    args = build_parser().parse_args(argv)
    say = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    if args.init_rules:
        path = Path(args.init_rules)
        if path.exists():
            print(f"{path} already exists; not overwriting", file=sys.stderr)
            return 1
        path.write_text(STARTER_RULES, encoding="utf-8")
        print(f"Wrote {path}. Edit it, then pass --rules {path}")
        return 0
    if not args.inputs:
        build_parser().print_usage(sys.stderr)
        print("error: give at least one statement file or folder", file=sys.stderr)
        return 2

    set_currency(args.currency)
    try:
        files = collect_files(args.inputs)
    except FileNotFoundError as e:
        print(f"error: not found: {e}", file=sys.stderr)
        return 2
    if not files:
        print("error: no CSV/XLSX/XLS/PDF files found", file=sys.stderr)
        return 2

    rules = load_rules(args.rules, use_defaults=not args.no_default_rules)
    transactions, notes = [], []
    password = args.pdf_password
    for f in files:
        try:
            res = load_file(f, sign=args.sign, pdf_password=password, dayfirst=args.dayfirst)
            if (not res.transactions and any("password" in w for w in res.warnings)
                    and password is None and sys.stdin.isatty()):
                password = getpass.getpass(f"Password for {f.name}: ")
                res = load_file(f, sign=args.sign, pdf_password=password, dayfirst=args.dayfirst)
        except Exception as e:  # keep going with the other files
            notes.append(f"{f.name}: could not read ({e})")
            say(f"  ✗ {f.name}: {e}")
            continue
        for w in res.warnings:
            notes.append(f"{f.name}: {w}")
        if res.transactions:
            dates = sorted(t.date for t in res.transactions)
            say(f"  ✓ {f.name}: {len(res.transactions)} transactions "
                f"({dates[0]:%d %b %Y} – {dates[-1]:%d %b %Y}, {res.method})")
        else:
            say(f"  ✗ {f.name}: no transactions found" + (f" ({'; '.join(res.warnings)})" if res.warnings else ""))
        transactions.extend(res.transactions)

    if not transactions:
        print("error: no transactions could be read from the inputs", file=sys.stderr)
        return 1
    if not args.no_dedupe:
        transactions, dropped = dedupe(transactions)
        if dropped:
            notes.append(f"{dropped} duplicate rows found in more than one file were counted once")

    categorize(transactions, rules)
    analysis = analyze(transactions, Settings())

    out = Path(args.output)
    kinds = category_kinds(rules)
    for t in transactions:
        kinds.setdefault(t.category, "expense")
    out.write_text(render_html(transactions, kinds, analysis.recurring, notes, args.currency), encoding="utf-8")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "description", "amount", "category", "kind", "merchant", "source"])
            for t in sorted(transactions, key=lambda t: t.date):
                w.writerow([t.date.isoformat(), t.description, f"{t.amount:.2f}", t.category,
                            t.kind, t.merchant, t.source])

    if not args.quiet:
        o = analysis.overview
        print()
        print(f"Spend Stories · {analysis.start:%d %b %Y} – {analysis.end:%d %b %Y}")
        print(f"  Total spending   {money(o['total_spend'])}   (avg {money(o['avg_monthly_spend'])}/month)")
        if o["income"]:
            print(f"  Income           {money(o['income'])}")
        print()
        print("  Top categories")
        for r in analysis.category_summary.head(8).itertuples():
            arrow = {"up": " ▲", "down": " ▼"}.get(r.trend, "")
            print(f"    {r.category:<32} {money(r.total):>14}  {pct(r.share):>4}{arrow}")
        if analysis.insights:
            print()
            print("  Highlights")
            for line in analysis.insights:
                print(f"    • {line}")
        print()
        print(f"Report: {out.resolve()}")
        if args.csv:
            print(f"Transactions CSV: {Path(args.csv).resolve()}")

    if args.open:
        import webbrowser

        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
