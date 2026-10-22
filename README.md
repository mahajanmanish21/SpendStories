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

## Install (Mac)

You need Python 3.11 or newer. The `python3` that comes with macOS is too old. Install a newer one
with [Homebrew](https://brew.sh) (`brew install python`) or from python.org.

```bash
git clone <this repo> && cd SpendStories
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
spendstories setup-mac          # creates ~/SpendStories with an Inbox and an "Update Report" file
```

Installing is the only step that uses the internet. After that, everything runs offline.

## Your monthly routine

`setup-mac` creates a folder in your home directory:

```
~/SpendStories/
  Inbox/                 ← save new statements here
  Update Report.command  ← double-click: imports the Inbox and opens your report
  Imported/2026-10/…     ← statements move here once they're in your history
  report.html            ← your report (open it any time)
  rules.toml             ← your categories, tags and shared-expense splits
  config.toml            ← currency, budgets, PDF passwords
  spendstories.db        ← every transaction you've ever imported
```

Each month:

1. Download your card and bank statements and save them into `~/SpendStories/Inbox`.
2. Double-click **Update Report**. The new transactions are added to your history and the
   report opens.

Want it fully hands-off? Run `spendstories setup-mac --auto`. After that, saving a file into
the Inbox updates `report.html` within seconds, with nothing to click. (This is a macOS
LaunchAgent; turn it off with the `launchctl unload` command it prints.)

**Your history builds up.** Every transaction goes into a local database, so trends,
same-month-last-year comparisons and budgets get better each month. Overlapping statements
are fine: rows already in your history are skipped, so the same transaction is never counted
twice. Two genuinely identical purchases in one statement (two coffees, same day, same price)
are both kept. Importing the same file twice does nothing.

### Commands

| Command | What it does |
|---|---|
| `spendstories inbox [--open]` | Import everything in the Inbox, file it away, rebuild the report |
| `spendstories import FILES… [--move]` | Import statements from anywhere |
| `spendstories report [--open] [--csv all.csv]` | Rebuild the report (e.g. after editing rules or budgets) |
| `spendstories status` | What's in your history: files, date range, months with no transactions |
| `spendstories budget set "Shopping" 10000` | Set a monthly budget (`budget list`, `budget remove …`) |
| `spendstories watch` | Keep running and import files as they land (alternative to `--auto`) |
| `spendstories setup-mac [--auto]` | Create the folders and the double-clickable updater |
| `spendstories --home PATH …` | Use a library somewhere other than `~/SpendStories` |

Protected PDFs: add `pdf_passwords = ["…"]` to `config.toml` so the Inbox can open them
without asking. That file stays on your Mac.

### One-off reports

You can also skip the library and make a report straight from some files:

```bash
spendstories statements/ --currency ₹ --open     # writes spend_report.html
```

| Option | What it does |
|---|---|
| `-o report.html` | Where to write the report |
| `--csv all.csv` | Also export every categorised transaction, handy for checking or for Excel |
| `--rules my_rules.toml` | Your own rules (categories, tags, splits), checked before the built-in ones |
| `--config config.toml` | Currency and budgets |
| `--currency ₹` | Currency symbol shown in the report |
| `--pdf-password …` | Password for protected PDF statements (you're asked for it if it's needed) |
| `--dayfirst` / `--monthfirst` | Force how ambiguous dates like 03/04/2026 are read (normally guessed per file) |
| `--sign negative-spend` | For a file with a single signed Amount column, say which sign means spending |
| `--no-dedupe` | Keep identical rows that appear in more than one file |

Want to try it first? Generate a year of fake statements:

```bash
python examples/make_sample_data.py
spendstories examples/sample_statements --currency ₹ --open
```

## Using the report

The report is a small app in a single HTML file. It works offline: open it by double-clicking.
Everything is clickable, so you can start from the big picture and go down to single transactions:

```
Overview ──► a month ──► a category ──► a merchant ──► its transactions
    │            ▲             ▲
    └─► Trends ──┴─────────────┘  (any bar, cell or row takes you deeper)
```

The **Period** picker (all time, last 12/6/3 months, this year, custom) applies to every view.
The browser's back button works as you'd expect.

- **Overview** (the high-level view): what you spent, your average month, the overall trend,
  how the latest month compares, income and what's left over. Below that are plain-language
  **highlights** (each one links to its details), a month-by-month chart split by category,
  where the money goes, and your recurring payments.
- **Trends**:
  - **Direction** of your overall spending, using a robust trend line that a single holiday
    or laptop can't tilt. Toggle a 3-month moving average and the average on the chart.
    You also get a "next month if the trend holds" estimate and a comparison with the same
    month last year (needs 13+ months of statements).
  - **What's driving the change**: how much more or less you spend per category, comparing
    the last 1, 3 or 6 months with the same length of time before. **One-off spikes are set
    aside by default**, so you see changes in your habits. Switch them back in with one click.
  - **Category trends** table: each category labelled *Rising*, *Falling*, *Spiky*,
    *Steady* or *Irregular*. You can sort and filter it.
  - **Seasonality map**: a category × month heatmap, with spikes marked, for spotting which
    months each category peaks.
  - **Merchant trends**: where you're spending more, new merchants, and ones you've stopped using.
- **Category** page: monthly chart with trend line and forecast, biggest month, and
  **"Why is it changing?"**, which splits the change into *buying more often* vs.
  *each purchase costing more*, with charts of both. Also its merchants and transactions.
- **Merchant** page: the same detail for one merchant, plus recurring-payment info.
- **Month** page: how the month compares with an average month for each category, its biggest
  purchases, merchants used for the first time, and every transaction. Use ‹ › to step between months.
- **Merchants**: recurring payments and subscriptions with price rises flagged, and a
  searchable, sortable list of every merchant.
- **Transactions**: search and filter everything, including by tag.
- **Budgets**: each budget for the month you pick, with how much is left. While a month is in
  progress it shows where you're heading at your current pace (✓ on track, ! at risk, ✗ over),
  and a marker on each bar shows where you'd be if you spent evenly. You also get the last 6
  months at a glance, and suggested budgets based on your typical month. Edit amounts right on
  the page. Over-budget and at-risk categories show up in the Overview highlights and in the
  terminal summary.
- **Checks** (money leaks):
  - possible double charges (same merchant and amount within 3 days)
  - fees, interest and late-payment charges, with what each one usually means
  - subscriptions that went up in price, new recurring payments (a free trial that turned
    paid?) and what your subscriptions cost per year
  - foreign-currency spending, which usually carries a 2-3.5% card markup

  Mark items as reviewed to clear them. The tab shows how many still need a look.
- **Tags**: what a trip, wedding or project really cost, across categories, with the daily
  cost and how it compares with a normal month.
- **Print a month**: on any month page, **Print summary** gives a clean one-page summary
  (use "Save as PDF" in the print dialog to keep it).

**Fixing things in the report:**
- Click a **category** next to any transaction to move every transaction from that merchant.
- Click **✎** to **tag** a transaction (e.g. *Goa trip*) or set **your share** of a shared
  cost. Half, a third or any percentage counts only your part everywhere in the report; the
  original amount is still shown.
- Change **budgets** on the Budgets page.

Every change has an undo. Changes are kept in that browser. Click **Save my changes** at the
top to get the lines to paste into `rules.toml` / `config.toml` (it tells you which file),
so every future report includes them.

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

[categories.Music]
merchants = ["spotify"]           # exact merchant names as shown in the report
```

Keywords are case-insensitive. Keywords of 5 or more characters match anywhere in the
description, so `swiggy` matches `UPI/SWIGGYINSTAMART/123`. Shorter ones must be a separate
word, so `ola` doesn't match `coca cola`. Prefix a keyword with `re:` to use a regular expression.
`merchants` lists exact merchant names as shown in the report. The report's
**Save as a rules file** button writes these for you. `kind` can be `expense` (the default), `transfer`, `investment` or `income`. The rules are
checked from top to bottom, your files first, and the first match wins. If the report says a
lot of spending is uncategorised, open the **All transactions** table, filter by
*Uncategorized* and add keywords for what you see.

## Tags and shared expenses

Tag many transactions at once, or count shared costs at your share, with rules in `rules.toml`:

```toml
[tags."Goa trip"]
from = 2026-05-01
to = 2026-05-20
categories = ["Travel", "Dining & Food Delivery", "Transport"]   # optional
# keywords = ["goa"], merchants = ["taj hotels goa"]              # optional

[[splits]]                      # flatmate pays half the rent
share = 0.5
keywords = ["landlord"]
```

A transaction gets a tag when it falls within the dates (if given), is in one of the
categories (if given), and matches a keyword or merchant (if any are given). Splits work the
same way; the first matching split wins, and a split that names a specific transaction
always beats a general one. The report's **Save my changes** writes these for you.

## Development

```bash
pip install -e .[dev]
pytest
```

Code layout: `loaders.py` (reading files) → `library.py` (the local database, config and
budgets) → `categorize.py` and `extras.py` (categories, tags, splits) → `analysis.py` and
`checks.py` (totals, trends, spikes, recurring, money leaks) → `report.py`, which embeds
the data and the app (`app/app.js`, `app/app.css`) in one HTML file. `pipeline.py` ties the
steps together and `cli.py` holds the commands. `offline.py` holds the
network block. The browser test in `tests/` uses Playwright if it is installed and skips otherwise.
