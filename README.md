# SpendStories

Analyse your credit card and bank statements **on your own computer**. Point it at a folder of
statements and get a single HTML report with spending by category, month-by-month charts,
**trends** (categories steadily rising or falling) and **spikes** (months or transactions
well outside the usual), plus subscriptions and top merchants.

## Privacy: nothing leaves your machine

- **No network, enforced.** Before any statement is read, the tool switches off outbound
  networking for its own process. Any attempt to connect or look up a hostname, by this
  code or by a library it uses, fails with an error. There's a test that checks this.
- **The report is offline too.** The HTML file has every style, script and chart inline,
  and it carries a Content-Security-Policy (`default-src 'none'`) that stops the browser
  from fetching anything when you open it. No fonts, CDNs, analytics or images.
- **No accounts, uploads, telemetry or AI services.** Categorisation is keyword rules
  you can read and edit (`spendstories/default_rules.toml`).
- `.gitignore` excludes `statements/`, `reports/`, PDFs and generated reports so you
  don't commit your data by accident.

## Install

Python 3.11+.

```bash
git clone <this repo> && cd SpendStories
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
```

(Installing the dependencies is the only step that needs the internet. After that, everything
runs offline.)

## Use

```bash
# Put your statements in a folder (CSV, XLSX, XLS or PDF; subfolders are fine)
spendstories statements/ --currency ₹ --open
```

That writes `spend_report.html` and prints a summary in the terminal. Useful options:

| Option | What it does |
|---|---|
| `-o report.html` | Where to write the report |
| `--csv all.csv` | Also export every categorised transaction, handy for checking or for Excel |
| `--rules my_rules.toml` | Your own category rules, checked before the built-in ones (repeatable) |
| `--init-rules my_rules.toml` | Write a starter rules file to edit |
| `--currency ₹` | Currency symbol shown in the report |
| `--pdf-password …` | Password for protected PDF statements (you're asked for it if it's needed and not given) |
| `--dayfirst` / `--monthfirst` | Force how ambiguous dates like 03/04/2026 are read (normally guessed per file) |
| `--sign negative-spend` | For a file with a single signed Amount column, say which sign means spending (normally guessed) |
| `--no-dedupe` | Keep identical rows that appear in more than one file |

Want to try it first? Generate a year of fake statements:

```bash
python examples/make_sample_data.py
spendstories examples/sample_statements --currency ₹ --open
```

## What's in the report

- **Headline numbers**: total spend, monthly average, income, amount invested, what's left over.
- **Highlights**: the most important findings in plain sentences.
- **Monthly spending by category**: stacked chart with hover details and a table view.
- **Spikes**: category-months well above that category's usual level (at least 1.5× the median
  of the other months and statistically unusual), with the transactions that caused each one.
- **Trends**: categories that have been rising or falling steadily. A single big month doesn't
  count as a trend because the slope is a robust (Theil–Sen) estimate.
- **Categories**: total, share, monthly average, latest month vs. average, sparkline, trend.
- **Unusually large transactions**: big for their category, or a big chunk of a month's budget.
- **Recurring payments & subscriptions**: weekly, monthly, quarterly or yearly payments,
  with price rises flagged (e.g. a streaming plan going from 499 to 649).
- **Top merchants**, and a searchable, filterable list of **all transactions**.

### How money is counted

- **Spending** is purchases minus refunds.
- **Credit card bill payments and transfers between your own accounts are ignored**, so a
  purchase on the card and the bank payment for that card's bill aren't counted twice.
- **Investments** (SIPs, brokerage transfers) are shown separately, not as spending.
- **Partial months** at the start or end of your statements are left out of averages,
  trends and spike baselines when there are at least 3 full months.
- If you load overlapping statements, rows that appear identically in more than one file are
  counted once.

## Supported statements

The tool doesn't need to know your bank. It finds the header row (Date / Description /
Amount, or Debit + Credit / Withdrawal + Deposit columns) anywhere in the file, skips
preamble and summary rows, and joins descriptions that wrap onto a second line.

- **CSV / TSV / Excel (.xlsx)**: the most reliable. Use your bank's CSV or Excel export if it has one.
- **Legacy .xls**: needs `pip install xlrd`, or re-save the file as .xlsx.
- **PDF**: best effort. It reads ruled tables, and falls back to text lines that start with a
  date and end with an amount. For bank PDFs with a running balance, the sign is worked out
  from how the balance changes. Scanned (image) PDFs aren't supported. Check the `--csv`
  output after the first run.

Amounts like `1,234.50 Cr`, `(45.10)`, `45.10-` and `₹ 1,234.50` all work, and so do dates like
`05/01/2026`, `2026-01-05`, `12 Jan 2026`, `12-Jan-26` and `Jan 12, 2026`.

## Making the categories yours

```bash
spendstories --init-rules my_rules.toml
```

```toml
[categories."Dining & Food Delivery"]
keywords = ["my favourite cafe"]

[categories.Kids]
keywords = ["toy store", "school fees"]

[categories."Transfers & Card Payments"]
kind = "transfer"                 # ignored in spending totals
keywords = ["my other bank", "re:^to savings"]
```

Keywords are case-insensitive. Keywords of 5 or more characters match anywhere in the
description, so `swiggy` matches `UPI/SWIGGYINSTAMART/123`. Shorter ones must be a separate
word, so `ola` doesn't match `coca cola`. Prefix a keyword with `re:` to use a regular expression.
`kind` can be `expense` (the default), `transfer`, `investment` or `income`. The rules are
checked from top to bottom, your files first, and the first match wins. If the report says a
lot of spending is uncategorised, open the **All transactions** table, filter by
*Uncategorized* and add keywords for what you see.

## Development

```bash
pip install -e .[dev]
pytest
```

Code layout: `loaders.py` (reading files) → `categorize.py` (rules) → `analysis.py`
(totals, trends, spikes, recurring) → `report.py` (HTML). `offline.py` holds the network block.
