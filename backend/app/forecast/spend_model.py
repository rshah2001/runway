"""Learned day-to-day spending model — owner: Patil-Hemangi.

Bills, paydays and other regular transfers are known in advance; everyday spending is the uncertain
part of a forecast. This learns the expected spend per day from recent history. Deliberately simple:
a few months of one person's history supports a handful of means, not a neural net, and the
backtest in evals/ decides which variant the live forecast uses.
"""

from dataclasses import dataclass
from datetime import date, timedelta

Outflows = list[tuple[date, float]]  # (day, dollars out), positive


@dataclass(frozen=True)
class SpendProfile:
    by_weekday: tuple[float, ...]  # expected spend per day, Monday first

    def expected(self, d: date) -> float:
        return self.by_weekday[d.weekday()]

    def total(self, start: date, days: int) -> float:
        return sum(self.expected(start + timedelta(days=i)) for i in range(days))


def _day_counts(start: date, end: date) -> list[int]:
    counts = [0] * 7
    d = start
    while d < end:
        counts[d.weekday()] += 1
        d += timedelta(days=1)
    return counts


def daily_totals(outflows: Outflows, start: date, end: date) -> tuple[float, ...]:
    """Spending on each day of [start, end), zeros included: the raw material for the forecast's range."""
    totals = [0.0] * max(0, (end - start).days)
    for d, amount in outflows:
        if start <= d < end:
            totals[(d - start).days] += amount
    return tuple(round(t, 2) for t in totals)


def fit_weekday(outflows: Outflows, start: date, end: date) -> SpendProfile:
    """Mean spend for each weekday over [start, end) — catches habits like weekend shopping."""
    totals, counts = [0.0] * 7, _day_counts(start, end)
    for d, amount in outflows:
        if start <= d < end:
            totals[d.weekday()] += amount
    return SpendProfile(tuple(t / c if c else 0.0 for t, c in zip(totals, counts, strict=True)))


def fit_flat(outflows: Outflows, start: date, end: date) -> SpendProfile:
    """One mean for every day."""
    days = (end - start).days
    total = sum(amount for d, amount in outflows if start <= d < end)
    return SpendProfile((total / days if days else 0.0,) * 7)
