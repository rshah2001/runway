"""Forecast engine — owner: Patil-Hemangi.

Deterministic port of `buildEvents` + `project` from prototype/index.html. Every number the app
shows and the agent says comes from here, never from the LLM.

The demo runs on the fictional persona in `schedule.MAYA`; feeding it Nessie data means building a
`Schedule` from Nessie instead. The function signatures are the contract main.py relies on.
"""

import calendar
from collections import defaultdict
from collections.abc import Iterator
from datetime import date, timedelta

from app.forecast.schedule import MAYA, Schedule
from app.schemas import Forecast, ForecastEvent, ForecastPoint, Recurring

MAX_DAYS = 365


def _on_day(year: int, month: int, day: int) -> date:
    """`day` of the given month, clamped so a bill on the 31st lands on Feb 28/29."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _months(start: date, end: date) -> Iterator[tuple[int, int]]:
    """(year, month) for every month touching [start, end], inclusive."""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _next_on_or_after(start: date, day: int) -> date:
    """The first date on or after `start` that falls on `day` of a month."""
    candidate = _on_day(start.year, start.month, day)
    if candidate >= start:
        return candidate
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return _on_day(year, month, day)


def _paychecks(schedule: Schedule, start: date, end: date) -> Iterator[ForecastEvent]:
    pay = schedule.paycheck
    # first payday is the next payday weekday strictly after today, so the demo opens before
    # payday — the tight window the forecast exists to catch
    d = start + timedelta(days=(pay.weekday - start.weekday()) % 7 or 7)
    while d <= end:
        yield ForecastEvent(date=d, amount=pay.amount, label=pay.label, kind="paycheck")
        d += timedelta(days=pay.every_days)


def _monthly_charges(schedule: Schedule, start: date, end: date) -> Iterator[ForecastEvent]:
    for year, month in _months(start, end):
        for charge in schedule.monthly:
            yield ForecastEvent(
                date=_on_day(year, month, charge.day), amount=-charge.amount, label=charge.label, kind=charge.kind
            )
        if schedule.monthly_spend > 0:
            yield ForecastEvent(
                date=_on_day(year, month, 10),
                amount=-schedule.monthly_spend,
                label="Discretionary — eating out, one-offs",
                kind="spending",
            )


def _installments(schedule: Schedule, start: date, end: date) -> Iterator[ForecastEvent]:
    for plan in schedule.installments:
        # payments start next month: this month's is already reflected in the balance
        months = [ym for ym in _months(start, end) if ym != (start.year, start.month)]
        for year, month in months[: plan.months_left]:
            yield ForecastEvent(
                date=_on_day(year, month, plan.day), amount=-plan.monthly, label=plan.label, kind="bill"
            )


def _card_payoffs(schedule: Schedule, start: date) -> Iterator[ForecastEvent]:
    for card in schedule.cards:
        if card.balance > 0:
            yield ForecastEvent(
                date=_next_on_or_after(start, card.pay_day),
                amount=-card.balance,
                label=f"Pay {card.label} statement in full",
                kind="card_payment",
            )


def _weekly_spend(schedule: Schedule, start: date, end: date) -> Iterator[ForecastEvent]:
    d = start
    while schedule.weekly_spend > 0 and d <= end:
        yield ForecastEvent(date=d, amount=-schedule.weekly_spend, label="Groceries", kind="spending")
        d += timedelta(days=7)


def build_events(schedule: Schedule, start: date, end: date) -> list[ForecastEvent]:
    """Every scheduled cash flow in [start, end], sorted by date with income first within a day."""
    events = [
        *_paychecks(schedule, start, end),
        *_monthly_charges(schedule, start, end),
        *_installments(schedule, start, end),
        *_card_payoffs(schedule, start),
        *_weekly_spend(schedule, start, end),
    ]
    in_window = [e for e in events if start <= e.date <= end]
    return sorted(in_window, key=lambda e: (e.date, -e.amount))


def project(start_balance: float, events: list[ForecastEvent], start: date, days: int) -> list[ForecastPoint]:
    """End-of-day balance for each day from `start` through `start + days`.

    Events outside the window are ignored: earlier ones are already in `start_balance`.
    """
    net_by_day: dict[date, float] = defaultdict(float)
    for e in events:
        net_by_day[e.date] += e.amount
    balance, points = start_balance, []
    for offset in range(days + 1):
        d = start + timedelta(days=offset)
        balance += net_by_day.get(d, 0.0)
        points.append(ForecastPoint(date=d, balance=round(balance, 2)))
    return points


def forecast(
    days: int = 30,
    extra: list[ForecastEvent] | None = None,
    *,
    start: date | None = None,
    schedule: Schedule = MAYA,
) -> Forecast:
    """Day-by-day projected checking balance from `start` (default today), plus hypothetical events."""
    start = start or date.today()
    end = start + timedelta(days=days)
    hypothetical = [e for e in extra or [] if start <= e.date <= end]
    events = sorted(build_events(schedule, start, end) + hypothetical, key=lambda e: (e.date, -e.amount))
    points = project(schedule.start_balance, events, start, days)
    low = min(points, key=lambda p: p.balance)  # earliest of equal lows: that's when you'd need to act
    return Forecast(points=points, low=low, safe_floor=schedule.safe_floor, events=events)


def simulate_purchase(amount: float, on: date, label: str, *, start: date | None = None) -> Forecast:
    """Forecast as if the user also spent `amount` on `on`.

    A date in the past means the money would go out now. The horizon stretches to cover the purchase
    (up to MAX_DAYS) so a far-off purchase is never silently dropped from the answer.
    """
    start = start or date.today()
    on = max(on, start)
    days = min(max(30, (on - start).days), MAX_DAYS)
    hypothetical = ForecastEvent(date=on, amount=-abs(amount), label=label, kind="other")
    return forecast(days=days, extra=[hypothetical], start=start)


def recurring(*, start: date | None = None, schedule: Schedule = MAYA) -> list[Recurring]:
    """Subscriptions with their next charge date.

    Reads the schedule for now; the recurring-transaction detector over purchase history replaces it.
    """
    start = start or date.today()
    return [
        Recurring(merchant=c.label, amount=c.amount, interval_days=30, next_date=_next_on_or_after(start, c.day))
        for c in schedule.monthly
        if c.kind == "subscription"
    ]
