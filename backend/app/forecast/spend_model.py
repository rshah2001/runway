"""Learned day-to-day spending model — owner: Patil-Hemangi.

Bills, subscriptions and paychecks are known in advance; everyday card spending is the uncertain
part of a forecast. This learns the expected spend for each weekday from purchase history, which
captures habits like weekend eating out. Deliberately simple: a few months of one person's history
supports seven means, not a neural net, and the backtest in evals/ shows whether it earns its place.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.forecast.history import Transaction


def is_everyday_spend(t: Transaction) -> bool:
    """Card purchases that vary day to day — subscriptions are forecast from the schedule instead."""
    return t.kind == "purchase" and t.category != "Subscription" and t.amount > 0


@dataclass(frozen=True)
class SpendProfile:
    by_weekday: tuple[float, ...]  # expected spend per day, Monday first

    def expected(self, d: date) -> float:
        return self.by_weekday[d.weekday()]


def fit_weekday(transactions: list[Transaction], start: date, end: date) -> SpendProfile:
    """Mean everyday spend for each weekday over [start, end)."""
    totals, counts = [0.0] * 7, [0] * 7
    d = start
    while d < end:
        counts[d.weekday()] += 1
        d += timedelta(days=1)
    for t in transactions:
        if start <= t.date < end and is_everyday_spend(t):
            totals[t.date.weekday()] += t.amount
    return SpendProfile(tuple(total / count if count else 0.0 for total, count in zip(totals, counts, strict=True)))


def fit_flat(transactions: list[Transaction], start: date, end: date) -> SpendProfile:
    """One mean for every day — the baseline the weekday model has to beat."""
    days = (end - start).days
    total = sum(t.amount for t in transactions if start <= t.date < end and is_everyday_spend(t))
    return SpendProfile((total / days if days else 0.0,) * 7)
