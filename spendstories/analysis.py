"""Turn categorised transactions into totals, trends, spikes and recurring payments."""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .formatting import money, month_label, pct
from .models import Transaction

SPEND_KINDS = ("expense", "refund")


@dataclass
class Settings:
    # A category-month counts as a spike when it is at least this many times its usual level...
    spike_ratio: float = 1.5
    # ...and this many robust standard deviations above it.
    spike_z: float = 3.0
    # Ignore spikes / trends smaller than this share of an average month's total spend.
    min_share: float = 0.02
    # Monthly change (as % of the category's average) for a trend to be reported.
    trend_pct: float = 5.0
    top_n: int = 15


@dataclass
class Analysis:
    start: date
    end: date
    months: list[str]
    partial_months: set[str]
    full_months: list[str]
    overview: dict
    monthly_total: pd.Series
    by_category_month: pd.DataFrame          # rows = category, cols = month
    category_summary: pd.DataFrame
    trends: list[dict]
    month_spikes: list[dict]
    large_transactions: list[dict]
    recurring: list[dict]
    top_merchants: pd.DataFrame
    transactions: pd.DataFrame
    insights: list[str] = field(default_factory=list)


def dedupe(transactions: list[Transaction]) -> tuple[list[Transaction], int]:
    """Drop rows repeated across files (overlapping statements, same file loaded twice).

    Identical rows *within* one file are kept - two coffees on the same day are
    real. Across files we keep, per identical (date, description, amount), only
    as many copies as the file with the most of them.
    """
    per_file: dict[tuple, Counter] = defaultdict(Counter)
    for t in transactions:
        per_file[(t.date, t.description.strip().lower(), t.amount)][t.source] += 1
    allowed = {k: max(c.values()) for k, c in per_file.items()}
    seen: Counter = Counter()
    kept = []
    for t in transactions:
        k = (t.date, t.description.strip().lower(), t.amount)
        if seen[k] < allowed[k]:
            kept.append(t)
            seen[k] += 1
    return kept, len(transactions) - len(kept)


def to_frame(transactions: list[Transaction]) -> pd.DataFrame:
    df = pd.DataFrame([t.__dict__ for t in transactions])
    if df.empty:
        return pd.DataFrame(columns=["date", "description", "amount", "source", "category",
                                     "kind", "merchant", "month"])
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.strftime("%Y-%m")
    return df.sort_values(["date", "source"]).reset_index(drop=True)


def _month_range(start: date, end: date) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def _partial_months(start: date, end: date) -> set[str]:
    partial = set()
    if start.day > 3:
        partial.add(start.strftime("%Y-%m"))
    last_day = calendar.monthrange(end.year, end.month)[1]
    if end.day < last_day - 3:
        partial.add(end.strftime("%Y-%m"))
    return partial


def _robust_scale(values: np.ndarray) -> float:
    med = np.median(values)
    return 1.4826 * float(np.median(np.abs(values - med)))


def _trend(series: pd.Series) -> tuple[float, float]:
    """Monthly slope, as an amount and as % of the typical month.

    Uses the Theil-Sen estimator (median of all pairwise slopes) so that one
    spike month - a holiday, a laptop - doesn't masquerade as a trend.
    """
    y = series.to_numpy(dtype=float)
    if len(y) < 3:
        return 0.0, 0.0
    i, j = np.triu_indices(len(y), k=1)
    slope = float(np.median((y[j] - y[i]) / (j - i)))
    typical = float(np.median(y))
    if typical <= 0:
        return 0.0, 0.0
    return slope, slope / typical * 100


def analyze(transactions: list[Transaction], settings: Settings | None = None) -> Analysis:
    s = settings or Settings()
    df = to_frame(transactions)
    if df.empty:
        raise ValueError("no transactions to analyse")

    start, end = df["date"].min().date(), df["date"].max().date()
    months = _month_range(start, end)
    partial = _partial_months(start, end)
    full = [m for m in months if m not in partial]
    # Too little history to drop partial months from the baselines - use what we have.
    baseline_months = full if len(full) >= 3 else months

    spend = df[df["kind"].isin(SPEND_KINDS)]
    pivot = (spend.pivot_table(index="category", columns="month", values="amount", aggfunc="sum")
             .reindex(columns=months).fillna(0.0))
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    monthly_total = pivot.sum(axis=0).reindex(months).fillna(0.0)

    total_spend = float(spend["amount"].sum())
    income = float(-df.loc[df["kind"] == "income", "amount"].sum())
    invested = float(df.loc[df["kind"] == "investment", "amount"].sum())
    refunds = float(-spend.loc[spend["kind"] == "refund", "amount"].sum())
    avg_month = float(monthly_total[baseline_months].mean()) if baseline_months else total_spend
    threshold = s.min_share * max(avg_month, 1.0)

    overview = {
        "total_spend": total_spend,
        "avg_monthly_spend": avg_month,
        "income": income,
        "invested": invested,
        "refunds": refunds,
        "net_saved": income - total_spend - invested if income else None,
        "transactions": int(len(df)),
        "spend_transactions": int((spend["kind"] == "expense").sum()),
        "transfers_ignored": int((df["kind"] == "transfer").sum()),
        "months": len(months),
        "sources": sorted(df["source"].unique()),
        "uncategorized_share": float(spend.loc[spend["category"] == "Uncategorized", "amount"].sum()
                                     / total_spend) if total_spend else 0.0,
    }

    # ---- per-category summary and trends
    rows, trends = [], []
    last_full = baseline_months[-1] if baseline_months else months[-1]
    for cat, series in pivot.iterrows():
        base = series[baseline_months]
        cat_avg = float(base.mean())
        slope, slope_pct = _trend(base)
        n = len(base)
        recent = float(base.iloc[-3:].mean()) if n >= 4 else float("nan")
        earlier = float(base.iloc[:-3].iloc[-3:].mean()) if n >= 4 else float("nan")
        direction = ""
        if n >= 3 and cat_avg >= threshold and abs(slope_pct) >= s.trend_pct:
            direction = "up" if slope > 0 else "down"
            # Require the recent months to agree with the fitted line.
            if n >= 4 and ((direction == "up" and recent <= earlier) or
                           (direction == "down" and recent >= earlier)):
                direction = ""
        if direction:
            trends.append({
                "category": cat, "direction": direction, "slope": slope, "slope_pct": slope_pct,
                "first": float(base.iloc[0]), "last": float(base.iloc[-1]),
                "first_month": base.index[0], "last_month": base.index[-1],
                "recent_avg": recent, "earlier_avg": earlier, "months": n,
            })
        cat_total = float(series.sum())
        rows.append({
            "category": cat,
            "total": cat_total,
            "share": cat_total / total_spend if total_spend else 0.0,
            "monthly_avg": cat_avg,
            "last_month": float(series[last_full]),
            "vs_avg": (float(series[last_full]) / cat_avg - 1) if cat_avg > 0 else float("nan"),
            "trend": direction,
            "trend_pct": slope_pct,
            "count": int(((spend["category"] == cat) & (spend["kind"] == "expense")).sum()),
            "series": series.tolist(),
        })
    category_summary = pd.DataFrame(rows)
    trends.sort(key=lambda t: -abs(t["slope"]))

    # Overall spending trend as a pseudo-category.
    t_slope, t_pct = _trend(monthly_total[baseline_months])
    overview["trend_slope"], overview["trend_pct"] = t_slope, t_pct

    # ---- month spikes (per category, plus the total)
    expenses = spend[spend["kind"] == "expense"]
    cat_median = expenses.groupby("category")["amount"].median()
    month_spikes = []
    series_to_check = [("All spending", monthly_total)] + list(pivot.iterrows())
    if len(baseline_months) >= 3:
        for cat, series in series_to_check:
            base = series[baseline_months]
            for m in baseline_months:
                value = float(base[m])
                others = base.drop(m).to_numpy(dtype=float)
                usual = float(np.median(others))
                scale = max(_robust_scale(others), 0.1 * usual, 1.0)
                z = (value - usual) / scale
                if (value - usual >= threshold and value >= s.spike_ratio * max(usual, 1.0)
                        and z >= s.spike_z):
                    # Explain the spike with the most *unusual* transactions that month:
                    # rank by how far each is above its category's typical amount, so
                    # the rent paid every month doesn't crowd out the holiday.
                    in_month = expenses[(expenses["month"] == m)
                                        & ((expenses["category"] == cat) if cat != "All spending" else True)]
                    excess = in_month["amount"] - in_month["category"].map(cat_median)
                    drivers = in_month.loc[excess.sort_values(ascending=False).index[:3]]
                    month_spikes.append({
                        "category": cat, "month": m, "amount": value, "usual": usual,
                        "ratio": value / usual if usual > 0 else float("inf"), "z": z,
                        "drivers": [{"date": d.date.date(), "description": d.description,
                                     "amount": d.amount} for d in drivers.itertuples()],
                    })
    month_spikes.sort(key=lambda x: -(x["amount"] - x["usual"]))

    # ---- unusually large individual transactions
    large = []
    big_floor = max(0.05 * avg_month, threshold)
    for cat, grp in expenses.groupby("category"):
        amounts = grp["amount"].to_numpy(dtype=float)
        med = float(np.median(amounts))
        scale = max(_robust_scale(amounts), 0.25 * med)
        for row in grp.itertuples():
            if row.amount < big_floor:
                continue
            # Big for its category (needs some history to know what's normal)...
            unusual = len(amounts) >= 5 and row.amount >= 3 * med and (row.amount - med) / scale >= 4
            # ...or simply a big chunk of a month's budget - unless it's a regular
            # amount for the category, like rent.
            huge = row.amount >= 0.25 * avg_month and (len(amounts) < 3 or row.amount >= 2 * med)
            if unusual or huge:
                large.append({"date": row.date.date(), "description": row.description,
                              "category": cat, "amount": float(row.amount), "typical": med,
                              "source": row.source})
    large.sort(key=lambda x: -x["amount"])
    large = large[: s.top_n]

    recurring = find_recurring(expenses)

    top_merchants = (expenses.groupby("merchant")
                     .agg(total=("amount", "sum"), count=("amount", "size"),
                          category=("category", lambda c: c.mode().iat[0]))
                     .sort_values("total", ascending=False).head(s.top_n).reset_index())

    a = Analysis(start=start, end=end, months=months, partial_months=partial,
                 full_months=baseline_months, overview=overview, monthly_total=monthly_total,
                 by_category_month=pivot, category_summary=category_summary, trends=trends,
                 month_spikes=month_spikes, large_transactions=large, recurring=recurring,
                 top_merchants=top_merchants, transactions=df)
    a.insights = build_insights(a)
    return a


def find_recurring(expenses: pd.DataFrame) -> list[dict]:
    """Payments to the same merchant at a steady interval and similar amount."""
    out = []
    periods = [("weekly", 7, 2, 52 / 12), ("monthly", 30.4, 6, 1.0),
               ("quarterly", 91, 12, 1 / 3), ("yearly", 365, 25, 1 / 12)]
    for merchant, grp in expenses.groupby("merchant"):
        if len(grp) < 2:
            continue
        grp = grp.sort_values("date")
        amounts = grp["amount"].to_numpy(dtype=float)
        med = float(np.median(amounts))
        # Loose band so a price rise (e.g. a subscription going 499 -> 649) stays in the group.
        steady = grp[np.abs(amounts - med) <= 0.35 * med]
        if len(steady) < 3 and not (len(steady) == 2 and (steady["date"].iloc[1] - steady["date"].iloc[0]).days > 300):
            continue
        gaps = np.diff(steady["date"].to_numpy()).astype("timedelta64[D]").astype(float)
        gaps = gaps[gaps > 0]
        if len(gaps) == 0:
            continue
        gap = float(np.median(gaps))
        for name, days, tolerance, per_month in periods:
            if abs(gap - days) <= tolerance and np.mean(np.abs(gaps - days) <= tolerance * 1.5) >= 0.6:
                amts = steady["amount"].to_numpy(dtype=float)
                latest = float(amts[-1])
                # A price change is only meaningful for fixed-price payments: find where
                # the current price started and compare with the stable price before it.
                k = len(amts) - 1
                while k > 0 and abs(amts[k - 1] - latest) <= 0.01 * latest:
                    k -= 1
                before = amts[:k]
                change = 0.0
                if len(before) >= 2 and np.std(before) <= 0.02 * np.mean(before):
                    change = latest / float(np.mean(before)) - 1
                out.append({
                    "merchant": merchant,
                    "description": steady["description"].iloc[-1],
                    "category": steady["category"].mode().iat[0],
                    "frequency": name,
                    "amount": latest,
                    "monthly_cost": latest * per_month,
                    "count": int(len(steady)),
                    "first": steady["date"].iloc[0].date(),
                    "last": steady["date"].iloc[-1].date(),
                    "price_change": change,
                })
                break
    out.sort(key=lambda r: -r["monthly_cost"])
    return out


def build_insights(a: Analysis) -> list[str]:
    """Plain-language headline findings."""
    o = a.overview
    lines = []
    if a.category_summary is not None and len(a.category_summary):
        top = a.category_summary.iloc[0]
        lines.append(f"{top['category']} is your biggest spend: {money(top['total'])} "
                     f"({pct(top['share'])} of all spending).")
    if len(a.full_months) >= 3 and abs(o["trend_pct"]) >= 3:
        word = "rising" if o["trend_slope"] > 0 else "falling"
        lines.append(f"Overall spending is {word} by about {money(abs(o['trend_slope']))} a month "
                     f"({abs(o['trend_pct']):.0f}% of an average month).")
    for sp in a.month_spikes[:4]:
        if sp["usual"] >= 1:
            usual = f"{sp['ratio']:.1f}x the usual {money(sp['usual'])}"
        else:
            usual = "when a typical month has next to nothing"
        lines.append(f"Spike: {sp['category']} in {month_label(sp['month'])} was {money(sp['amount'])}, {usual}.")
    for t in a.trends[:4]:
        word = "up" if t["direction"] == "up" else "down"
        lines.append(f"Trend: {t['category']} is {word} about {abs(t['slope_pct']):.0f}% a month "
                     f"({money(t['first'])} in {month_label(t['first_month'])} → "
                     f"{money(t['last'])} in {month_label(t['last_month'])}).")
    rec_total = sum(r["monthly_cost"] for r in a.recurring)
    if a.recurring:
        lines.append(f"{len(a.recurring)} recurring payments found, about {money(rec_total)} a month.")
        for r in a.recurring:
            if r["price_change"] >= 0.05:
                lines.append(f"{r['merchant'].title()} went up {pct(r['price_change'])} "
                             f"(now {money(r['amount'])} {r['frequency']}).")
    if o["uncategorized_share"] >= 0.1:
        lines.append(f"{pct(o['uncategorized_share'])} of spending is uncategorised - add keywords "
                     f"to a rules file (see README) to sharpen the analysis.")
    return lines
