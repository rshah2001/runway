"""Recurring-transaction detector — owner: Patil-Hemangi.

A series counts as recurring when it arrives on a steady cadence for a steady amount. Both matter: a
coffee shop visited every few days is frequent but not a subscription, and a $15.49 charge that shows
up once is just a purchase. Rules, not ML: with a few months of one person's history there is too
little data to learn from, and every decision stays explainable.

The same detector serves two callers: the "subscription detective" (card purchases) and the forecast,
which uses it to find paydays and other regular money in or out of checking from history alone.

Timing is checked per charge against its expected slot (same weekday rhythm, or same day of the
month), not per gap between charges: one late charge then counts as one miss instead of two.
"""

import calendar
from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from statistics import median

from app.forecast.sources import Txn
from app.schemas import Recurring

MIN_CHARGES = 3
# cadence name → (period in days, slot tolerance in days)
CADENCES = {"weekly": (7, 1), "biweekly": (14, 2), "monthly": (30, 3)}
AMOUNT_TOLERANCE = 0.05  # max relative deviation from the median amount
MIN_ON_SLOT_SHARE = 0.75  # share of charges that must land on their slot; tolerates one late charge


def _month_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _on_slot(d: date, anchor: date, cadence: str) -> bool:
    """Whether `d` lands within tolerance of the slot grid that `anchor` defines."""
    period, tolerance = CADENCES[cadence]
    if cadence == "monthly":
        return abs(d.day - _month_day(d.year, d.month, anchor.day).day) <= tolerance
    drift = (d - anchor).days % period
    return min(drift, period - drift) <= tolerance


def _fits(dates: list[date], cadence: str) -> bool:
    """Charges come once per period, without skipped periods, and mostly on their slot."""
    period, tolerance = CADENCES[cadence]
    gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
    if min(gaps) < period / 2 or max(gaps) > period * 1.5 + tolerance:
        return False
    # the anchor is whichever charge explains the most others, so a late first charge can't skew it
    best = max(sum(_on_slot(d, anchor, cadence) for d in dates) for anchor in dates)
    return best / len(dates) >= MIN_ON_SLOT_SHARE


def _steady_amount(amounts: list[float]) -> bool:
    mid = median(amounts)
    return all(abs(a - mid) <= max(AMOUNT_TOLERANCE * mid, 0.01) for a in amounts)


def next_after(last: date, interval_days: int, day_of_month: int) -> date:
    """The occurrence after `last`: same day next month for monthly series, else `interval_days` on."""
    if interval_days < CADENCES["monthly"][0]:
        return last + timedelta(days=interval_days)
    year, month = (last.year + 1, 1) if last.month == 12 else (last.year, last.month + 1)
    return _month_day(year, month, day_of_month)


def detect_recurring(history: list[Txn], today: date, include: Callable[[Txn], bool] | None = None) -> list[Recurring]:
    """Series still active as of `today`, soonest next occurrence first. Amounts are positive.

    `include` picks the transactions to look at; by default, card and debit purchases, since bills
    are already known from the bills table and the detective's job is the charges people forget.
    """
    include = include or (lambda t: t.kind == "purchase" and t.amount < 0)
    by_label: dict[str, list[Txn]] = defaultdict(list)
    for t in history:
        if include(t):
            by_label[t.label.strip().lower()].append(t)

    found: list[Recurring] = []
    for series in by_label.values():
        series.sort(key=lambda t: t.date)
        amounts = [abs(t.amount) for t in series]
        if len(series) < MIN_CHARGES or not _steady_amount(amounts):
            continue
        dates = [t.date for t in series]
        cadence = next((c for c in CADENCES if _fits(dates, c)), None)
        if cadence is None:
            continue
        period, tolerance = CADENCES[cadence]
        last = series[-1]
        if (today - last.date).days > period * 1.5 + tolerance:
            continue  # missed its last occurrence: probably cancelled
        days = [d.day for d in dates]
        day_of_month = round(median(days))  # usual billing day, robust to one late charge
        if day_of_month >= 28:
            day_of_month = max(days)  # month-end billers: a clamped Feb 28 must not stick for March
        next_date = next_after(last.date, period, day_of_month)
        while next_date < today:  # due already but not posted yet; expect it next cycle
            next_date = next_after(next_date, period, day_of_month)
        found.append(Recurring(merchant=last.label, amount=abs(last.amount), interval_days=period, next_date=next_date))
    return sorted(found, key=lambda r: r.next_date)


def provisional(history: list[Txn], today: date, include: Callable[[Txn], bool]) -> list[Recurring]:
    """Series with exactly two matching charges: too few for `detect_recurring` (which needs MIN_CHARGES
    on a steady slot) but enough to expect a third. Used for income only, so a new user's forecast has
    their paycheck in it after two paydays instead of three; readiness marks it as provisional.

    Strict, since two points always fit some interval: same label, amounts within AMOUNT_TOLERANCE, a
    gap that matches a cadence within its tolerance (monthly: the same day of the month), and the second
    one recent enough that the series is still running."""
    by_label: dict[str, list[Txn]] = defaultdict(list)
    for t in history:
        if include(t):
            by_label[t.label.strip().lower()].append(t)
    found: list[Recurring] = []
    for series in by_label.values():
        if len(series) != 2:
            continue
        first, second = sorted(series, key=lambda t: t.date)
        if not _steady_amount([abs(first.amount), abs(second.amount)]):
            continue
        gap = (second.date - first.date).days
        cadence = next(
            (c for c, (period, tol) in CADENCES.items() if c != "monthly" and abs(gap - period) <= tol), None
        )
        if cadence is None and 25 <= gap <= 35 and abs(first.date.day - second.date.day) <= CADENCES["monthly"][1]:
            cadence = "monthly"
        if cadence is None:
            continue
        period, tolerance = CADENCES[cadence]
        if (today - second.date).days > period * 1.5 + tolerance:
            continue  # the next one is overdue: don't count on it
        next_date = next_after(second.date, period, second.date.day)
        while next_date < today:
            next_date = next_after(next_date, period, second.date.day)
        found.append(
            Recurring(merchant=second.label, amount=abs(second.amount), interval_days=period, next_date=next_date)
        )
    return sorted(found, key=lambda r: r.next_date)
