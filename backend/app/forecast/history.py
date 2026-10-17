"""Seeded transaction history for the fictional demo persona — owner: Patil-Hemangi.

Stands in for the transactions Nessie + Tiger Data will provide. It is generated from the same
`Schedule` the forecast uses plus random card purchases (port of `seedTxns` in prototype/index.html),
so the recurring detector and the forecast backtest have realistic, reproducible input.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.forecast.schedule import MAYA, Schedule

TxnKind = Literal["purchase", "bill", "deposit", "transfer"]


@dataclass(frozen=True)
class Transaction:
    date: date
    merchant: str
    amount: float  # positive = money out, negative = money in
    category: str
    kind: TxnKind


# (category, merchant, min $, max $, visits per week) — the prototype's demo merchants
CARD_MERCHANTS = [
    ("Grocery", "FreshMart", 18, 72, 1.3),
    ("Restaurants", "Chipotle", 10, 16, 0.9),
    ("Restaurants", "Starbucks", 5, 9, 1.4),
    ("Restaurants", "Pizza place", 12, 24, 0.4),
    ("Gas", "Shell", 28, 45, 0.6),
    ("Shopping", "Target", 15, 60, 0.4),
    ("Shopping", "Amazon", 12, 48, 0.5),
    ("Entertainment", "Movie theater", 14, 28, 0.2),
    ("Other", "Campus bookstore", 8, 40, 0.15),
]


class _ParkMiller:
    """The prototype's tiny LCG, so the history is identical on every machine and run."""

    def __init__(self, seed: int = 7) -> None:
        self.state = seed

    def __call__(self) -> float:
        self.state = (self.state * 16807) % 2147483647
        return self.state / 2147483647


def _months_back(d: date, months: int) -> date:
    year, month = divmod(d.year * 12 + d.month - 1 - months, 12)
    return date(year, month + 1, min(d.day, calendar.monthrange(year, month + 1)[1]))


def demo_history(end: date, months: int = 4, schedule: Schedule = MAYA, seed: int = 7) -> list[Transaction]:
    """Every transaction in the `months` before `end` (exclusive), oldest first."""
    rnd = _ParkMiller(seed)
    pay = schedule.paycheck
    # paydays are anchored to the forecast's next payday, so history and forecast share one rhythm
    next_payday = end + timedelta(days=(pay.weekday - end.weekday()) % 7 or 7)
    out: list[Transaction] = []
    d = _months_back(end, months)
    while d < end:
        last_day = calendar.monthrange(d.year, d.month)[1]
        for charge in schedule.monthly:
            if d.day == min(charge.day, last_day):
                # subscriptions bill the card; fixed bills autopay from checking
                kind: TxnKind = "purchase" if charge.kind == "subscription" else "bill"
                out.append(
                    Transaction(d, charge.label, charge.amount, "Subscription" if kind == "purchase" else "Bill", kind)
                )
        if (next_payday - d).days % pay.every_days == 0:
            out.append(Transaction(d, pay.label, -pay.amount, "Income", "deposit"))
        for category, merchant, lo, hi, per_week in CARD_MERCHANTS:
            if rnd() < per_week / 7:
                out.append(Transaction(d, merchant, round(lo + rnd() * (hi - lo), 2), category, "purchase"))
        for card in schedule.cards:
            if d.day == min(card.pay_day, last_day):
                out.append(Transaction(d, f"{card.label} payment", 250.00, "Payment", "transfer"))
        d += timedelta(days=1)
    return out
