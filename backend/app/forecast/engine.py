"""Forecast engine — owner: Patil-Hemangi.

Deterministic port of `buildEvents` + `project` from prototype/index.html, fed with each persona's
real data (see `sources` and `schedule`). Every number the app shows and the agent says comes from
here, never from the LLM. The route-facing functions (`forecast`, `simulate_purchase`, `recurring`)
keep their original signatures; `persona` is a new keyword argument that defaults to the demo persona.
"""

import calendar
from collections import defaultdict
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Literal

from app.forecast import band, sources
from app.forecast.recurring import detect_recurring, next_after
from app.forecast.schedule import Schedule, build
from app.schemas import Forecast, ForecastEvent, ForecastPoint, Readiness, Recurring

DEFAULT_PERSONA = "maya"
MAX_DAYS = 365
TIGHT_MARGIN = 150.0  # a low point within this much of the floor counts as "tight"

Status = Literal["healthy", "tight", "overdraft_risk"]


def status(low_balance: float, safe_floor: float) -> Status:
    """Green / amber / red for a low point. Decided here so the app's colour and the agent's tone agree."""
    if low_balance < safe_floor:
        return "overdraft_risk"
    return "tight" if low_balance < safe_floor + TIGHT_MARGIN else "healthy"


def schedule_for(
    persona: str = DEFAULT_PERSONA, today: date | None = None, *, history_days: int | None = None
) -> Schedule:
    """Load a persona's data and build its schedule. Callers that forecast repeatedly (the agent's
    tools) build it once and pass it in, so one question never reads the database twice.

    `history_days` pretends Runway has only known the persona that long — for the demo's "day 12"
    calibration story and the learning-curve eval. None uses everything."""
    today = today or sources.local_today()
    data = sources.load(persona, today)
    if history_days is not None:
        data = sources.recent(data, today, history_days)
    return build(data, today)


def readiness(
    persona: str = DEFAULT_PERSONA, today: date | None = None, *, history_days: int | None = None
) -> Readiness:
    """How sure a forecast for `persona` is today: calibrating, learning or confident, with reasons."""
    ready = schedule_for(persona, today, history_days=history_days).readiness
    assert ready is not None  # build() always sets it
    return ready


# ---------- events ----------


def _on_day(year: int, month: int, day: int) -> date:
    """`day` of the given month, clamped so a bill on the 31st lands on Feb 28/29."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _months(start: date, end: date) -> Iterator[tuple[int, int]]:
    """(year, month) for every month touching [start, end], inclusive."""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _monthly_charges(schedule: Schedule, start: date, end: date) -> Iterator[ForecastEvent]:
    for year, month in _months(start, end):
        for charge in schedule.monthly:
            yield ForecastEvent(
                date=_on_day(year, month, charge.day), amount=-charge.amount, label=charge.label, kind=charge.kind
            )


def _regular_flows(schedule: Schedule, end: date) -> Iterator[ForecastEvent]:
    for flow in schedule.regular:
        d = flow.next_date
        while d <= end:
            yield ForecastEvent(date=d, amount=flow.amount, label=flow.label, kind=flow.kind)
            d = next_after(d, flow.interval_days, flow.next_date.day)


def _everyday_spend(schedule: Schedule, start: date, end: date) -> Iterator[ForecastEvent]:
    """Learned everyday spending, booked on the day it is expected. Booking a week's estimate up front
    would take money out of today's balance that hasn't been spent yet and pull the low point earlier.
    Lists meant for people (the app's "Coming up", the agent's `upcoming`) leave these events out."""
    d = start
    while d <= end:
        amount = round(schedule.spend.expected(d), 2)
        if amount > 0:
            yield ForecastEvent(date=d, amount=-amount, label="Everyday spending (estimate)", kind="spending")
        d += timedelta(days=1)


def build_events(schedule: Schedule, start: date, end: date) -> list[ForecastEvent]:
    """Every expected cash flow in [start, end], sorted by date with income first within a day."""
    events = [
        *_monthly_charges(schedule, start, end),
        *_regular_flows(schedule, end),
        *_everyday_spend(schedule, start, end),
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


# ---------- route-facing ----------


def forecast(
    days: int = 30,
    extra: list[ForecastEvent] | None = None,
    *,
    persona: str = DEFAULT_PERSONA,
    start: date | None = None,
    schedule: Schedule | None = None,
) -> Forecast:
    """Day-by-day projected checking balance from `start` (default today), plus hypothetical events."""
    start = start or sources.local_today()
    schedule = schedule or schedule_for(persona, start)
    end = start + timedelta(days=days)
    hypothetical = [e for e in extra or [] if start <= e.date <= end]
    events = sorted(build_events(schedule, start, end) + hypothetical, key=lambda e: (e.date, -e.amount))
    points = with_range(project(schedule.start_balance, events, start, days), schedule)
    low = min(points, key=lambda p: p.balance)  # earliest of equal lows: that's when you'd need to act
    cautious = min(points, key=lambda p: p.balance_low if p.balance_low is not None else p.balance)
    return Forecast(
        points=points,
        low=low,
        safe_floor=schedule.safe_floor,
        events=events,
        readiness=schedule.readiness,
        cautious_low=cautious if schedule.daily_spend else None,
    )


def with_range(points: list[ForecastPoint], schedule: Schedule) -> list[ForecastPoint]:
    """Each point with its p10–p90 balance from how much this person's everyday spending varies.
    Point i has i + 1 days of spending in it (today's included), so it takes the spread for i + 1 days."""
    if not schedule.daily_spend:
        return points
    spreads = band.spread(schedule.daily_spend, len(points))
    return [
        p.model_copy(update={"balance_low": round(p.balance - down, 2), "balance_high": round(p.balance + up, 2)})
        for p, (down, up) in zip(points, spreads, strict=True)
    ]


def simulate_purchase(
    amount: float,
    on: date,
    label: str,
    *,
    persona: str = DEFAULT_PERSONA,
    start: date | None = None,
    schedule: Schedule | None = None,
) -> Forecast:
    """Forecast as if the user also spent `amount` on `on`.

    A date in the past means the money would go out now. The horizon stretches to cover the purchase
    (up to MAX_DAYS) so a far-off purchase is never silently dropped from the answer.
    """
    start = start or sources.local_today()
    on = max(on, start)
    days = min(max(30, (on - start).days), MAX_DAYS)
    hypothetical = ForecastEvent(date=on, amount=-abs(amount), label=label, kind="other")
    return forecast(days=days, extra=[hypothetical], persona=persona, start=start, schedule=schedule)


def recurring(*, persona: str = DEFAULT_PERSONA, start: date | None = None) -> list[Recurring]:
    """Recurring card charges detected in the persona's purchase history ("subscription detective")."""
    start = start or sources.local_today()
    return detect_recurring(sources.load(persona, start).history, start)
