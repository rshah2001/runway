"""The forecast's own report card: how close its recent forecasts came to what happened — owner: Patil-Hemangi.

For each of the last WINDOW_DAYS days, this replays the forecast Runway would have made LEAD_DAYS
earlier — the schedule learned only from history before that morning, starting from that morning's
real balance — and compares its prediction for the day with the actual end-of-day balance. The result
reads "my week-ahead forecasts were off by $38 on average over the last 14 days".

Why replay instead of only saving each day's forecast: a replay works from the first day, for every
user, on history Runway already has, and is computed by the same engine the app runs today. What a
replay can't prove is that the app *showed* those numbers at the time (the engine may have changed
since); that is what the `forecast_snapshots` table is for once it exists, and the two can then be
compared. Suggested columns, one row per (persona, day the forecast was made, day it was for):

    persona_slug text, made_on date, target_date date, balance numeric(12,2),
    balance_low numeric(12,2), balance_high numeric(12,2), engine_version text,
    created_at timestamptz default now(), primary key (persona_slug, made_on, target_date)
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from statistics import mean

from app.forecast.sources import PersonaData

WINDOW_DAYS = 14
LEAD_DAYS = 7  # a week ahead: far enough to matter, near enough to act on
MIN_DAYS_CHECKED = 7  # fewer than this and an average says more about luck than about the forecast


@dataclass(frozen=True)
class ReportCard:
    mean_abs_error: float  # $, week-ahead forecast vs actual end-of-day balance
    days_checked: int
    lead_days: int = LEAD_DAYS


def end_of_day_balances(data: PersonaData, today: date) -> dict[date, float]:
    """Actual checking balance at the end of each day before `today`, worked back from today's balance:
    the balance on day d is today's minus every checking transaction after d."""
    first = data.history[0].date if data.history else today
    by_day: dict[date, float] = {}
    for t in data.history:
        if t.account == "Checking":
            by_day[t.date] = by_day.get(t.date, 0.0) + t.amount
    balances, balance = {}, data.checking
    d = today - timedelta(days=1)
    while d >= first - timedelta(days=1):
        balances[d] = round(balance, 2)
        balance -= by_day.get(d, 0.0)
        d -= timedelta(days=1)
    return balances


def replay(data: PersonaData, today: date, build, forecast) -> ReportCard | None:
    """Score the week-ahead forecasts for the last WINDOW_DAYS days. `build` and `forecast` are the
    engine's (passed in, so this module doesn't import the engine that imports it). None until there
    are MIN_DAYS_CHECKED days with enough history before them to have made a forecast at all."""
    actual = end_of_day_balances(data, today)
    errors = []
    for back in range(1, WINDOW_DAYS + 1):
        target = today - timedelta(days=back)
        made_on = target - timedelta(days=LEAD_DAYS - 1)  # the morning of: LEAD_DAYS days of balances ahead
        opening = actual.get(made_on - timedelta(days=1))
        if opening is None or target not in actual:
            continue
        past = replace(data, checking=opening, history=[t for t in data.history if t.date < made_on])
        if not past.history:
            continue
        predicted = forecast(days=LEAD_DAYS - 1, start=made_on, schedule=build(past, made_on)).points[-1]
        errors.append(abs(predicted.balance - actual[target]))
    if len(errors) < MIN_DAYS_CHECKED:
        return None
    return ReportCard(mean_abs_error=round(mean(errors), 2), days_checked=len(errors))
