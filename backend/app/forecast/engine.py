"""Forecast engine — owner: Patil-Hemangi.

MOCK: projects the fictional demo persona "Maya" forward from a fixed schedule so the
app has realistic data on day one. Replace with the real engine (port `buildEvents` +
`project` from prototype/index.html, then feed it Nessie data from Tiger Data).
The function signatures are the contract main.py relies on; keep them stable.
"""

from datetime import date, timedelta

from app.schemas import Forecast, ForecastEvent, ForecastPoint, Recurring

SAFE_FLOOR = 300.0
START_BALANCE = 680.0

# (day of month, amount, label, kind) — same numbers as the prototype's PERSONA
MONTHLY = [
    (1, -650.00, "Rent", "bill"),
    (5, -62.00, "Electric + internet", "bill"),
    (8, -11.99, "Music streaming", "subscription"),
    (12, -108.00, "Car insurance", "bill"),
    (14, -15.49, "Video streaming", "subscription"),
    (17, -9.99, "Cloud storage", "subscription"),
    (20, -35.00, "Phone bill", "bill"),
    (22, -286.40, "Credit card statement", "card_payment"),
]
PAYCHECK = 780.00
WEEKLY_GROCERIES = -55.00


def _schedule(start: date, days: int) -> list[ForecastEvent]:
    events: list[ForecastEvent] = []
    # next payday is the coming Friday (never today), so the demo opens just before rent hits
    first_friday = start + timedelta(days=(4 - start.weekday()) % 7 or 7)
    for offset in range(days + 1):
        d = start + timedelta(days=offset)
        for day, amount, label, kind in MONTHLY:
            if d.day == day:
                events.append(ForecastEvent(date=d, amount=amount, label=label, kind=kind))
        if d >= first_friday and (d - first_friday).days % 14 == 0:
            events.append(ForecastEvent(date=d, amount=PAYCHECK, label="Campus job paycheck", kind="paycheck"))
        if offset % 7 == 0:
            events.append(ForecastEvent(date=d, amount=WEEKLY_GROCERIES, label="Groceries", kind="spending"))
    return events


def forecast(days: int = 30, extra: list[ForecastEvent] | None = None) -> Forecast:
    """Day-by-day projected balance from today, optionally with hypothetical events applied."""
    start = date.today()
    events = sorted(_schedule(start, days) + (extra or []), key=lambda e: e.date)
    balance, points, i = START_BALANCE, [], 0
    for offset in range(days + 1):
        d = start + timedelta(days=offset)
        while i < len(events) and events[i].date == d:
            balance += events[i].amount
            i += 1
        points.append(ForecastPoint(date=d, balance=round(balance, 2)))
    low = min(points, key=lambda p: p.balance)
    return Forecast(points=points, low=low, safe_floor=SAFE_FLOOR, events=events)


def simulate_purchase(amount: float, on: date, label: str) -> Forecast:
    """Forecast as if the user also spent `amount` on `on`."""
    hypothetical = ForecastEvent(date=on, amount=-abs(amount), label=label, kind="other")
    return forecast(extra=[hypothetical])


def recurring() -> list[Recurring]:
    """MOCK — to be replaced with the recurring-transaction detector over purchase history."""
    today = date.today()
    out = []
    for day, amount, label, kind in MONTHLY:
        if kind != "subscription":
            continue
        next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=day)
        nxt = today.replace(day=day) if today.day <= day else next_month
        out.append(Recurring(merchant=label, amount=-amount, interval_days=30, next_date=nxt))
    return out
