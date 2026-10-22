"""Command line entry point.

    spendstories statements/                  one-off report from some files
    spendstories init                         create your library (~/SpendStories)
    spendstories import statements/           add statements to the library and rebuild the report
    spendstories inbox                        import whatever is in the library's Inbox folder
    spendstories watch                        keep importing as files land in the Inbox
    spendstories report                       rebuild the report from the library
    spendstories status                       what the library holds
    spendstories budget set "Shopping" 10000  manage monthly budgets
    spendstories setup-mac                    folders + a double-clickable updater (+ --auto)
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
import time
from pathlib import Path

from .offline import block_network

COMMANDS = ("init", "import", "inbox", "watch", "report", "status", "budget", "password", "setup-mac")

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


# ---------------------------------------------------------------- argument parsing

def _reading_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sign", choices=["auto", "positive-spend", "negative-spend"], default="auto",
                   help="for files with one signed Amount column: are spends positive or negative? "
                        "(default: guess per file)")
    dates = p.add_mutually_exclusive_group()
    dates.add_argument("--dayfirst", dest="dayfirst", action="store_true", default=None,
                       help="force dd/mm/yyyy dates when ambiguous")
    dates.add_argument("--monthfirst", dest="dayfirst", action="store_false",
                       help="force mm/dd/yyyy dates when ambiguous")
    p.add_argument("--password", "--pdf-password", dest="password", action="append", default=[], metavar="PASSWORD",
                   help="password for locked statements, tried alongside your saved ones (repeatable). "
                        "Better: save them once with 'spendstories password add'")


def _report_options(p: argparse.ArgumentParser, default_output: str | None) -> None:
    p.add_argument("-o", "--output", default=default_output,
                   help="HTML report path" + (f" (default: {default_output})" if default_output else
                                              " (default: report.html in your library)"))
    p.add_argument("--csv", metavar="PATH", help="also write all categorised transactions to this CSV")
    p.add_argument("--rules", action="append", default=[], metavar="TOML",
                   help="extra rules file (categories, tags, splits); repeatable")
    p.add_argument("--no-default-rules", action="store_true", help="use only your own rules")
    p.add_argument("--currency", default=None, help="currency symbol for display, e.g. ₹, $, €")
    p.add_argument("--open", action="store_true", help="open the report in your browser when done")
    p.add_argument("-q", "--quiet", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    """The one-off mode: spendstories <files>."""
    p = argparse.ArgumentParser(
        prog="spendstories",
        description="Analyse credit card and bank statements locally: categories, trends, spikes, budgets. "
                    "Runs fully offline - nothing is sent anywhere. "
                    f"Library commands: {', '.join(COMMANDS)} (try: spendstories init --help).",
    )
    p.add_argument("inputs", nargs="*", help="statement files (CSV, XLSX, XLS, PDF) or folders containing them")
    _report_options(p, "spend_report.html")
    _reading_options(p)
    p.add_argument("--config", metavar="TOML", help="config file with currency and budgets")
    p.add_argument("--init-rules", metavar="PATH", help="write a starter rules file and exit")
    p.add_argument("--no-dedupe", action="store_true",
                   help="keep identical rows that appear in more than one file")
    return p


def build_library_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spendstories", description="SpendStories library commands. "
                                "Everything stays in one folder on your computer.")
    p.add_argument("--home", help="library folder (default: $SPENDSTORIES_HOME or ~/SpendStories)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the library folders and starter files")

    imp = sub.add_parser("import", help="add statements to the library, then rebuild the report")
    imp.add_argument("inputs", nargs="+", help="statement files or folders")
    imp.add_argument("--move", action="store_true", help="move imported files into the library's Imported folder")
    imp.add_argument("--no-report", action="store_true", help="don't rebuild the report")
    _reading_options(imp)
    _report_options(imp, None)

    inbox = sub.add_parser("inbox", help="import everything in the Inbox folder and rebuild the report")
    _reading_options(inbox)
    _report_options(inbox, None)

    watch = sub.add_parser("watch", help="keep watching the Inbox and import new statements as they arrive")
    watch.add_argument("--interval", type=float, default=5.0, help="seconds between checks (default: 5)")
    _reading_options(watch)
    _report_options(watch, None)

    rep = sub.add_parser("report", help="rebuild the report from the library")
    _report_options(rep, None)

    sub.add_parser("status", help="show what's in the library")

    bud = sub.add_parser("budget", help="list, set or remove monthly budgets")
    bsub = bud.add_subparsers(dest="action")
    bsub.add_parser("list", help="show budgets and how the latest month is doing")
    bset = bsub.add_parser("set", help='set a budget, e.g. budget set "Shopping" 10000')
    bset.add_argument("category", help='category name as shown in the report, or "All spending"')
    bset.add_argument("amount", type=float)
    brm = bsub.add_parser("remove", help="remove a budget")
    brm.add_argument("category")

    pwd = sub.add_parser("password", help="save passwords for locked statements (in your Mac's Keychain)")
    psub = pwd.add_subparsers(dest="action")
    padd = psub.add_parser("add", help="save a password (you'll be asked to type it; it isn't shown)")
    padd.add_argument("label", nargs="?", help='a name to recognise it by, e.g. "hdfc card"')
    psub.add_parser("list", help="show the labels of saved passwords (never the passwords)")
    prm = psub.add_parser("remove", help="forget a saved password")
    prm.add_argument("label")
    ptest = psub.add_parser("test", help="check which saved password opens a file")
    ptest.add_argument("file")

    mac = sub.add_parser("setup-mac", help="create the folders and a double-clickable 'Update Report' file")
    mac.add_argument("--auto", action="store_true",
                     help="also update automatically whenever a file lands in the Inbox (macOS LaunchAgent)")
    return p


# ---------------------------------------------------------------- one-off mode

def run_oneoff(args) -> int:
    from .analysis import dedupe
    from .formatting import set_currency
    from .library import assign_ids, load_config
    from .loaders import collect_files
    from .pipeline import ReadOptions, build, describe_load, print_summary, read_statement, write_csv, write_report

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
        print("error: give at least one statement file or folder (or a command: " + ", ".join(COMMANDS) + ")",
              file=sys.stderr)
        return 2
    config = load_config(Path(args.config)) if args.config else load_config(None)
    currency = args.currency if args.currency is not None else config.currency
    set_currency(currency)
    try:
        files = collect_files(args.inputs)
    except FileNotFoundError as e:
        print(f"error: not found: {e}", file=sys.stderr)
        return 2
    if not files:
        print("error: no CSV/XLSX/XLS/PDF files found", file=sys.stderr)
        return 2

    from .library import default_home
    from .passwords import saved_passwords
    home = default_home()
    opts = ReadOptions(sign=args.sign, dayfirst=args.dayfirst, interactive=True,
                       passwords=[*(("given", p) for p in args.password),
                                  *(saved_passwords(home, config.pdf_passwords) if home.exists() else
                                    [(f"config #{i}", p) for i, p in enumerate(config.pdf_passwords, 1)])],
                       on_new_password=lambda name, pw: _offer_to_save(home, name, pw))
    transactions, notes = [], []
    for f in files:
        try:
            res = read_statement(f, opts)
        except Exception as e:  # keep going with the other files
            notes.append(f"{f.name}: could not read ({e})")
            say(f"  ✗ {f.name}: {e}")
            continue
        notes += [f"{f.name}: {w}" for w in res.warnings]
        say(describe_load(f, res))
        transactions.extend(res.transactions)
    if any("locked" in n for n in notes):
        say("  Tip: save statement passwords once with: spendstories password add")
    if not transactions:
        print("error: no transactions could be read from the inputs", file=sys.stderr)
        return 1
    if not args.no_dedupe:
        transactions, dropped = dedupe(transactions)
        if dropped:
            notes.append(f"{dropped} duplicate rows found in more than one file were counted once")
    assign_ids(transactions)

    built = build(transactions, args.rules, not args.no_default_rules, config.budgets)
    out = Path(args.output)
    write_report(out, built, notes, currency)
    if args.csv:
        write_csv(Path(args.csv), built.transactions)
    if not args.quiet:
        print_summary(built, out)
    if args.open:
        _open(out)
    return 0


# ---------------------------------------------------------------- library mode

def _open(path: Path) -> None:
    import webbrowser

    webbrowser.open(path.resolve().as_uri())


def _rebuild(lib, args, say) -> int:
    from .formatting import set_currency
    from .library import load_config, read_transactions
    from .pipeline import build, print_summary, write_csv, write_report

    config = load_config(lib.config_path)
    currency = args.currency if getattr(args, "currency", None) is not None else config.currency
    set_currency(currency)
    transactions = read_transactions(lib)
    if not transactions:
        say("The library is empty. Add statements with: spendstories import <files>, "
            f"or drop them in {lib.inbox} and run: spendstories inbox")
        return 1
    rules = [lib.rules_path, *getattr(args, "rules", [])]
    built = build(transactions, rules, not getattr(args, "no_default_rules", False), config.budgets)
    out = Path(args.output) if getattr(args, "output", None) else lib.report_path
    write_report(out, built, [], currency, lib.home)
    if getattr(args, "csv", None):
        write_csv(Path(args.csv), built.transactions)
    if not getattr(args, "quiet", False):
        print_summary(built, out)
    if getattr(args, "open", False):
        _open(out)
    return 0


def _import_files(lib, files: list[Path], args, say, move: bool) -> tuple[int, int]:
    """Import files; returns (transactions added, files that failed)."""
    from .library import config_passwords, file_away, file_sha256, import_transactions
    from .passwords import saved_passwords
    from .pipeline import ReadOptions, describe_load, read_statement

    opts = ReadOptions(sign=args.sign, dayfirst=args.dayfirst, interactive=sys.stdin.isatty(),
                       passwords=[*(("given", p) for p in args.password),
                                  *saved_passwords(lib.home, config_passwords(lib))],
                       on_new_password=lambda name, pw: _offer_to_save(lib.home, name, pw))
    added = failed = 0
    locked: list[str] = []
    for f in files:
        try:
            sha = file_sha256(f)
            res = read_statement(f, opts)
        except Exception as e:
            say(f"  ✗ {f.name}: could not read ({e})")
            failed += 1
            continue
        if not res.transactions:
            say(describe_load(f, res))
            failed += 1
            if res.locked:
                locked.append(f.name)
            continue
        outcome = import_transactions(lib, f, res.transactions, res.method, sha)
        if outcome.status == "duplicate-file":
            say(f"  • {f.name}: already imported, skipped")
        else:
            dup = outcome.rows - outcome.added
            say(describe_load(f, res) + f" → {outcome.added} new" + (f", {dup} already known" if dup else ""))
            added += outcome.added
        for w in res.warnings:
            if "best-effort" not in w:
                say(f"      note: {w}")
        if move:
            when = max(t.date for t in res.transactions)
            file_away(lib, f, when)
    if locked:
        say(f"  {len(locked)} locked file(s) left in place. Save the password with: spendstories password add"
            + (" (then run this again)" if sys.stdin.isatty() else ""))
        if not sys.stdin.isatty():
            _notify(f"{len(locked)} locked statement{'s' if len(locked) > 1 else ''} in your Inbox",
                    "Open Terminal and run: spendstories password add")
    return added, failed


def _offer_to_save(home: Path, filename: str, password: str) -> None:
    """After a typed password works, offer to remember it (never without asking)."""
    from .passwords import guess_label, store_for

    store = store_for(home)
    try:
        answer = input(f"  Save this password ({store.name}) so locked statements open automatically next time? [Y/n] ")
    except EOFError:
        return
    if answer.strip().lower() not in ("", "y", "yes"):
        return
    default = guess_label(filename)
    label = input(f"  Label for it [{default}]: ").strip() or default
    home.mkdir(parents=True, exist_ok=True)
    try:
        store.set(label, password)
        print(f"  Saved as '{label}'.", file=sys.stderr)
    except Exception as e:
        print(f"  Couldn't save it: {e}", file=sys.stderr)


def _notify(title: str, message: str) -> None:
    """A Mac notification for when we run in the background (automatic Inbox)."""
    if sys.platform != "darwin":
        return
    q = lambda v: '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        import subprocess
        subprocess.run(["osascript", "-e", f"display notification {q(message)} with title {q('SpendStories')} subtitle {q(title)}"],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def _stable_inbox_files(lib, wait: float = 2.0) -> list[Path]:
    """Inbox files that have finished downloading (size unchanged for a moment)."""
    from .loaders import collect_files

    files = collect_files([lib.inbox])
    if not files:
        return []
    sizes = {f: f.stat().st_size for f in files}
    if any(time.time() - f.stat().st_mtime < wait for f in files):
        time.sleep(wait)
    return [f for f in files if f.exists() and f.stat().st_size == sizes[f]]


def run_library(argv: list[str]) -> int:
    from .library import Library, default_home, library_status, load_config, set_budget

    args = build_library_parser().parse_args(argv)
    lib = Library(Path(args.home).expanduser() if args.home else default_home())
    quiet = getattr(args, "quiet", False)
    say = (lambda *a: None) if quiet else (lambda *a: print(*a, file=sys.stderr))
    lib.ensure()

    if args.command == "init":
        print(f"Your SpendStories library is ready at {lib.home}\n"
              f"  Inbox:   {lib.inbox}   (drop statements here, then run: spendstories inbox)\n"
              f"  Rules:   {lib.rules_path}\n"
              f"  Budgets: {lib.config_path}\n"
              f"  Report:  {lib.report_path}")
        return 0

    if args.command == "import":
        from .loaders import collect_files
        try:
            files = collect_files(args.inputs)
        except FileNotFoundError as e:
            print(f"error: not found: {e}", file=sys.stderr)
            return 2
        added, failed = _import_files(lib, files, args, say, move=args.move)
        say(f"Added {added} new transactions.")
        if args.no_report:
            return 1 if failed and not added else 0
        return _rebuild(lib, args, say)

    if args.command == "inbox":
        files = _stable_inbox_files(lib)
        if not files:
            say(f"Nothing in {lib.inbox}.")
            if not lib.report_path.exists() and library_status(lib)["transactions"]:
                return _rebuild(lib, args, say)
            if args.open and lib.report_path.exists():
                _open(lib.report_path)
            return 0
        added, failed = _import_files(lib, files, args, say, move=True)
        if failed:
            say(f"{failed} file(s) couldn't be read and were left in the Inbox.")
        if added or not lib.report_path.exists():
            return _rebuild(lib, args, say)
        say("No new transactions; report unchanged.")
        if args.open:
            _open(lib.report_path)
        return 0

    if args.command == "watch":
        say(f"Watching {lib.inbox} - drop statements there. Press Ctrl+C to stop.")
        failed_seen: set[tuple[str, float]] = set()
        try:
            while True:
                files = [f for f in _stable_inbox_files(lib) if (f.name, f.stat().st_mtime) not in failed_seen]
                if files:
                    added, _ = _import_files(lib, files, args, say, move=True)
                    for f in files:
                        if f.exists():  # unreadable; don't retry until it changes
                            failed_seen.add((f.name, f.stat().st_mtime))
                    if added:
                        _rebuild(lib, args, say)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            say("Stopped.")
            return 0

    if args.command == "report":
        return _rebuild(lib, args, say)

    if args.command == "status":
        st = library_status(lib)
        print(f"Library: {lib.home}")
        if not st["transactions"]:
            print("  Empty. Drop statements in the Inbox and run: spendstories inbox")
            return 0
        print(f"  {st['transactions']} transactions, {st['first']} to {st['last']}, from {len(st['files'])} files")
        months = st["months"]
        from .analysis import _month_range
        from datetime import date as _d
        full = _month_range(_d.fromisoformat(months[0] + "-01"), _d.fromisoformat(months[-1] + "-01"))
        gaps = [m for m in full if m not in months]
        if gaps:
            print(f"  No transactions at all in: {', '.join(gaps)} - a statement may be missing")
        from .loaders import collect_files
        waiting = collect_files([lib.inbox])
        if waiting:
            print(f"  Waiting in the Inbox (locked or unreadable): {', '.join(f.name for f in waiting)}")
        print("\n  Files")
        for f in st["files"]:
            print(f"    {f['name']:<40} {f['first_date'] or '':>10} – {f['last_date'] or '':<10} "
                  f"{f['added']:>5} new of {f['rows']}")
        return 0

    if args.command == "budget":
        action = args.action or "list"
        if action == "set":
            set_budget(lib.config_path, args.category, args.amount)
            print(f"Budget for {args.category}: {args.amount:g} a month. Run 'spendstories report' to see it.")
            return 0
        if action == "remove":
            set_budget(lib.config_path, args.category, None)
            print(f"Removed the budget for {args.category}.")
            return 0
        config = load_config(lib.config_path)
        if not config.budgets:
            print('No budgets yet. Add one with: spendstories budget set "Dining & Food Delivery" 8000')
            return 0
        from .formatting import money, set_currency
        from .library import read_transactions
        from .pipeline import build
        set_currency(config.currency)
        txns = read_transactions(lib)
        if not txns:
            for k, v in config.budgets.items():
                print(f"  {k:<32} {money(v):>12}")
            return 0
        built = build(txns, [lib.rules_path], True, config.budgets)
        icon = {"over": "✗ over", "at-risk": "! at risk", "ok": "✓ on track"}
        print(f"Budgets for {built.budget_status[0]['month']}" +
              (" (month in progress)" if built.budget_status[0]["in_progress"] else ""))
        for b in built.budget_status:
            print(f"  {b['category']:<32} {money(b['spent']):>12} of {money(b['budget']):>12}  {icon[b['status']]}")
        return 0

    if args.command == "password":
        return password_command(lib, args)

    if args.command == "setup-mac":
        return setup_mac(lib, args.auto)
    return 2


def password_command(lib, args) -> int:
    import getpass

    from .passwords import store_for

    store = store_for(lib.home)
    action = args.action or "list"
    if action == "add":
        label = args.label or input('Label (e.g. "hdfc card"): ').strip()
        if not label:
            print("A label is needed so you can tell your passwords apart.", file=sys.stderr)
            return 2
        pw = getpass.getpass(f"Password for {label} (not shown): ")
        if not pw:
            print("Nothing saved.", file=sys.stderr)
            return 1
        if getpass.getpass("Type it again: ") != pw:
            print("The two didn't match. Nothing saved.", file=sys.stderr)
            return 1
        store.set(label, pw)
        print(f"Saved '{label}' in {store.name}. Locked statements will now open automatically.")
        if collect_inbox := [f for f in lib.inbox.iterdir() if f.is_file() and not f.name.startswith(".")]:
            print(f"{len(collect_inbox)} file(s) are waiting in the Inbox - run: spendstories inbox")
        return 0
    if action == "remove":
        print(f"Removed '{args.label}'." if store.remove(args.label) else f"No saved password called '{args.label}'.")
        return 0
    if action == "test":
        from .library import config_passwords
        from .loaders import load_bytes
        from .passwords import saved_passwords

        f = Path(args.file)
        data = f.read_bytes()
        if not load_bytes(f.name, data).locked:
            print(f"{f.name} isn't locked.")
            return 0
        for label, pw in saved_passwords(lib.home, config_passwords(lib)):
            if not load_bytes(f.name, data, password=pw).locked:
                print(f"{f.name} opens with '{label}'.")
                return 0
        print(f"None of your saved passwords open {f.name}. Add one with: spendstories password add")
        return 1
    labels = store.labels()
    print(f"Saved passwords ({store.name}):" if labels else
          f"No saved passwords. Add one with: spendstories password add   (stored in {store.name})")
    for l in labels:
        print(f"  • {l}")
    return 0


def setup_mac(lib, auto: bool) -> int:
    py = sys.executable
    home = str(lib.home)
    script = lib.home / "Update Report.command"
    script.write_text(
        "#!/bin/bash\n"
        "# Double-click to import new statements from the Inbox and open your report.\n"
        f"{shlex.quote(py)} -m spendstories --home {shlex.quote(home)} inbox --open\n"
        'echo; read -n 1 -s -r -p "Done. Press any key to close this window."\n', encoding="utf-8")
    script.chmod(0o755)
    print(f"Library: {lib.home}\n"
          f"  1. Save statements from your bank into: {lib.inbox}\n"
          f"  2. Double-click '{script.name}' in that folder to update and open your report.")
    if not auto:
        print("\nWant it fully automatic? Run: spendstories setup-mac --auto")
        return 0

    label = "com.spendstories.inbox"
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / f"{label}.plist"
    from xml.sax.saxutils import escape as x
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{x(py)}</string><string>-m</string><string>spendstories</string>
    <string>--home</string><string>{x(home)}</string><string>inbox</string><string>--quiet</string>
  </array>
  <key>WatchPaths</key><array><string>{x(str(lib.inbox))}</string></array>
  <key>StandardOutPath</key><string>{x(str(lib.home / 'inbox.log'))}</string>
  <key>StandardErrorPath</key><string>{x(str(lib.home / 'inbox.log'))}</string>
  <key>ThrottleInterval</key><integer>10</integer>
</dict>
</plist>
""", encoding="utf-8")
    print(f"\nAutomatic updates: {plist}")
    if sys.platform == "darwin":
        os.system(f"launchctl unload {shlex.quote(str(plist))} 2>/dev/null; launchctl load {shlex.quote(str(plist))}")
        print("  Turned on. Any statement saved into the Inbox now updates report.html within seconds.\n"
              f"  Turn off with: launchctl unload {shlex.quote(str(plist))}")
    else:
        print(f"  (Not on a Mac - on your Mac, run: launchctl load {shlex.quote(str(plist))})")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Before anything touches a statement, make networking impossible.
    block_network()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Library commands, optionally preceded by --home PATH.
    i = 2 if argv[:1] == ["--home"] else 1 if argv and argv[0].startswith("--home=") else 0
    if len(argv) > i and argv[i] in COMMANDS:
        return run_library(argv)
    return run_oneoff(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
