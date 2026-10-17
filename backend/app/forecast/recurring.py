"""Recurring-transaction detector ("subscription detective") — owner: Patil-Hemangi.

A merchant counts as recurring when its charges arrive on a steady cadence for a steady amount.
Both conditions matter: a coffee shop visited every few days is frequent but not a subscription,
and a $15.49 charge that shows up once is just a purchase. Rules, not ML: with a few months of
history per user there is too little data to learn from, and every decision stays explainable.

Timing is checked per charge against its expected slot (same weekday rhythm, or same day of the
month), not per gap between charges: one late charge then counts as one miss instead of two.
"""

import calendar
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from app.forecast.history import Transaction
from app.schemas import Recurring

MIN_CHARGES = 3
# cadence name → (period in days, slot tolerance in days)
CADENCES = {"weekly": (7, 1), "biweekly": (14, 2), "monthly": (30, 3)}
AMOUNT_TOLERANCE = 0.05  # max relative deviation from the median charge
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


def _next_charge(last: date, cadence: str, day_of_month: int) -> date:
    if cadence != "monthly":
        return last + timedelta(days=CADENCES[cadence][0])
    year, month = (last.year + 1, 1) if last.month == 12 else (last.year, last.month + 1)
    return _month_day(year, month, day_of_month)


def detect_recurring(transactions: list[Transaction], today: date) -> list[Recurring]:
    """Recurring card charges still active as of `today`, soonest next charge first.

    Only purchases are considered: bills and paychecks are already known from the schedule, and
    the point of the detective is finding the charges the user forgot about.
    """
    by_merchant: dict[str, list[Transaction]] = defaultdict(list)
    for t in transactions:
        if t.kind == "purchase" and t.amount > 0:
            by_merchant[t.merchant.strip().lower()].append(t)

    found: list[Recurring] = []
    for charges in by_merchant.values():
        charges.sort(key=lambda t: t.date)
        if len(charges) < MIN_CHARGES or not _steady_amount([t.amount for t in charges]):
            continue
        dates = [t.date for t in charges]
        cadence = next((c for c in CADENCES if _fits(dates, c)), None)
        if cadence is None:
            continue
        period, tolerance = CADENCES[cadence]
        last = charges[-1]
        if (today - last.date).days > period * 1.5 + tolerance:
            continue  # missed its last charge: probably cancelled
        days = [d.day for d in dates]
        day_of_month = round(median(days))  # usual billing day, robust to one late charge
        if day_of_month >= 28:
            day_of_month = max(days)  # month-end billers: a clamped Feb 28 must not stick for March
        next_date = _next_charge(last.date, cadence, day_of_month)
        while next_date < today:  # the charge is due already but hasn't posted; expect it next cycle
            next_date = _next_charge(next_date, cadence, day_of_month)
        found.append(Recurring(merchant=last.merchant, amount=last.amount, interval_days=period, next_date=next_date))
    return sorted(found, key=lambda r: r.next_date)
