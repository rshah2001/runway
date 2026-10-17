"""The safety net's view of the forecast — a thin adapter over the forecast engine (app/forecast).

There is exactly one forecast in Runway: the chat, the charts and the safety net all read the same
engine, so they can never disagree about a number on stage. This module only adds what the safety
net needs on top: bridge repayments already scheduled, and the next payday.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import psycopg

from app.db import repo, safety_repo
from app.forecast import engine, sources
from app.forecast.schedule import Schedule
from app.schemas import ForecastEvent

LOCAL_TZ = sources.LOCAL_TZ
HORIZON_DAYS = 35  # a little over a month: covers the gap to any payday plus the days after it


@dataclass(frozen=True)
class Projection:
    slug: str
    first_name: str
    age: int
    start_balance: Decimal
    days: list[tuple[date, Decimal]]  # end-of-day checking balance, starting today
    next_payday: date | None
    paycheck: Decimal | None
    events: list[ForecastEvent] = field(default_factory=list)  # what moves the balance

    def low(self, start: date, end: date) -> tuple[date, Decimal] | None:
        """Lowest end-of-day balance in [start, end)."""
        window = [(d, b) for d, b in self.days if start <= d < end]
        return min(window, key=lambda x: x[1]) if window else None

    def balance_on(self, d: date) -> Decimal | None:
        return next((b for day, b in self.days if day == d), None)


def next_paycheck(schedule: Schedule, today: date) -> tuple[date | None, Decimal | None]:
    """The earliest upcoming paycheck the engine found in the persona's history."""
    paychecks = [f for f in schedule.regular if f.kind == "paycheck" and f.amount > 0 and f.next_date > today]
    if not paychecks:
        return None, None
    first = min(paychecks, key=lambda f: f.next_date)
    return first.next_date, Decimal(str(first.amount))


def projection_for(
    slug: str,
    *,
    first_name: str,
    age: int,
    today: date,
    schedule: Schedule | None = None,
    scheduled: list[ForecastEvent] = (),
    days: int = HORIZON_DAYS,
) -> Projection:
    """Run the engine for one persona, with any already-scheduled bridge repayments included."""
    schedule = schedule or engine.schedule_for(slug, today)
    f = engine.forecast(days=days - 1, extra=list(scheduled), persona=slug, start=today, schedule=schedule)
    payday, paycheck = next_paycheck(schedule, today)
    return Projection(
        slug=slug,
        first_name=first_name,
        age=age,
        start_balance=Decimal(str(schedule.start_balance)),
        days=[(p.date, Decimal(str(p.balance))) for p in f.points],
        next_payday=payday,
        paycheck=paycheck,
        events=f.events,
    )


def project(conn: psycopg.Connection, slug: str, today: date | None = None, days: int = HORIZON_DAYS) -> Projection:
    """Live projection: the engine's forecast plus outstanding bridges' repayments on their due dates."""
    today = today or sources.local_today()
    p = repo.persona(conn, slug)
    scheduled = []
    for b in safety_repo.outstanding_bridges(conn):
        if b["borrower_slug"] == slug:
            scheduled.append(
                ForecastEvent(
                    date=b["due_date"], amount=-float(b["amount"]), label=f"Repay {b['lender_name']}", kind="transfer"
                )
            )
        elif b["lender_slug"] == slug:
            scheduled.append(
                ForecastEvent(
                    date=b["due_date"],
                    amount=float(b["amount"]),
                    label=f"{b['borrower_name']} pays you back",
                    kind="transfer",
                )
            )
    return projection_for(
        slug, first_name=p["first_name"], age=p["age"] or 0, today=today, scheduled=scheduled, days=days
    )
