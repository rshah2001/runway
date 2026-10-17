"""Forecast backtest on the seeded personas: fit on months 1–3, predict month 4.

Each fold takes one persona's 120 days of seeded history (the same generator that seeded Nessie),
builds a schedule from the first 90 days only — bills, regular flows detected from history, the
spend model — and predicts the checking balance for each of the last 30 days. Folds cover all three
personas and several seed days, so one lucky month can't decide the result.

  * MAE  — mean absolute error of the predicted day-by-day checking balance over month 4, in $.
  * MAPE — absolute % error of month 4's total everyday spending (the part a schedule can't know).

Run:  python -m evals.forecast_backtest      (from backend/)
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from statistics import mean

os.environ.setdefault("RUNWAY_FORCE_MOCK", "1")  # always score the deterministic seeded data

from app.forecast import engine, schedule, sources  # noqa: E402
from app.forecast.spend_model import Outflows, SpendProfile, fit_flat, fit_weekday  # noqa: E402

TEST_DAYS = 30
PERSONAS = ["maya", "jordan", "sam"]
SEED_DAYS = [date(2026, 3, 2) + timedelta(days=37 * k) for k in range(6)]  # spread over weekdays and months

Fit = Callable[[Outflows, date, date], SpendProfile]


def _last_30_days(outflows: Outflows, start: date, end: date) -> SpendProfile:
    return fit_flat(outflows, end - timedelta(days=30), end)


METHODS: dict[str, Fit] = {
    "Flat daily mean, 90 days (live)": fit_flat,
    "Weekday means, 90 days": fit_weekday,
    "Last 30 days repeated (naive)": _last_30_days,
    "No everyday spending (bills only)": lambda o, s, e: SpendProfile((0.0,) * 7),
}


@dataclass(frozen=True)
class Score:
    mae: float
    mape: float


def score_fold(persona: str, seed_day: date, fit: Fit) -> Score:
    full = sources._load_demo(persona, seed_day)  # 120 days of history ending the day before seed_day
    cutoff = seed_day - timedelta(days=TEST_DAYS)
    train = replace(full, history=[t for t in full.history if t.date < cutoff])
    sched = replace(schedule.build(train, cutoff, fit), start_balance=0.0)  # predict the change, not the level
    predicted = engine.forecast(days=TEST_DAYS - 1, start=cutoff, schedule=sched).points

    test = [t for t in full.history if cutoff <= t.date < seed_day and t.account == "Checking"]
    errors, balance = [], 0.0
    for point in predicted:
        balance += sum(t.amount for t in test if t.date == point.date)
        errors.append(abs(point.balance - balance))

    actual_spend = sum(a for _, a in schedule.everyday_outflows(test, sched.regular))
    predicted_spend = sched.spend.total(cutoff, TEST_DAYS)
    return Score(mae=mean(errors), mape=abs(predicted_spend - actual_spend) / actual_spend)


def run() -> dict[str, Score]:
    """Mean score per method over every (persona, seed day) fold."""
    results = {}
    for name, fit in METHODS.items():
        folds = [score_fold(p, d, fit) for p in PERSONAS for d in SEED_DAYS]
        results[name] = Score(mae=mean(f.mae for f in folds), mape=mean(f.mape for f in folds))
    return results


def table(results: dict[str, Score]) -> str:
    rows = [
        f"| {name} | ${s.mae:,.2f} | {s.mape:.1%} |" for name, s in sorted(results.items(), key=lambda kv: kv[1].mae)
    ]
    header = "| Spend model | MAE, daily checking balance | MAPE, month-4 everyday spend |\n|---|---|---|"
    return "\n".join([header, *rows])


if __name__ == "__main__":
    n = len(PERSONAS) * len(SEED_DAYS)
    folds = f"{n} folds ({len(PERSONAS)} personas × {len(SEED_DAYS)} seed days)"
    print(f"Forecast backtest — {folds}, fit months 1–3 → predict month 4\n")
    print(table(run()))
