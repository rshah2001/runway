"""Forecast backtest on the seeded personas: fit on months 1–3, predict month 4.

Each fold takes one persona's 120 days of seeded history (the same generator that seeded Nessie),
builds a schedule from the first 90 days only — bills, regular flows detected from history, the
spend model — and predicts the checking balance for each of the last 30 days. Folds cover all three
personas and several seed days, so one lucky month can't decide the result.

  * MAE  — mean absolute error of the predicted day-by-day checking balance over month 4, in $.
  * MAPE — absolute % error of month 4's total everyday spending (the part a schedule can't know).

The learning curve repeats the live model with only the last 14 / 30 / 60 / 90 days of history before
the cutoff, as if Runway had just met the person, and adds:
  * coverage — share of month-4 days whose actual balance landed inside the p10–p90 band (aim ≈ 80%)
  * payday found — share of folds where the detector learned the paycheck from that much history

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


LEARNING_CURVE_DAYS = [14, 30, 60, 90]


@dataclass(frozen=True)
class Score:
    mae: float
    mape: float
    coverage: float = 0.0  # share of test days inside the p10–p90 band
    payday_found: float = 0.0  # 1.0 if the schedule had a learned paycheck


def score_fold(persona: str, seed_day: date, fit: Fit = fit_flat, history_days: int | None = None) -> Score:
    """Fit on the history before the cutoff (all of it, or only the last `history_days`), predict month 4."""
    full = sources._load_demo(persona, seed_day)  # 120 days of history ending the day before seed_day
    cutoff = seed_day - timedelta(days=TEST_DAYS)
    train = replace(full, history=[t for t in full.history if t.date < cutoff])
    if history_days is not None:
        train = sources.recent(train, cutoff, history_days)
    sched = replace(schedule.build(train, cutoff, fit), start_balance=0.0)  # predict the change, not the level
    predicted = engine.forecast(days=TEST_DAYS - 1, start=cutoff, schedule=sched).points

    test = [t for t in full.history if cutoff <= t.date < seed_day and t.account == "Checking"]
    errors, inside, balance = [], 0, 0.0
    for point in predicted:
        balance += sum(t.amount for t in test if t.date == point.date)
        errors.append(abs(point.balance - balance))
        low = point.balance if point.balance_low is None else point.balance_low
        high = point.balance if point.balance_high is None else point.balance_high
        inside += low <= balance <= high

    actual_spend = sum(a for _, a in schedule.everyday_outflows(test, sched.regular))
    predicted_spend = sched.spend.total(cutoff, TEST_DAYS)
    return Score(
        mae=mean(errors),
        mape=abs(predicted_spend - actual_spend) / actual_spend,
        coverage=inside / len(predicted),
        payday_found=float(bool(sched.readiness and sched.readiness.paycheck_found)),
    )


def _mean_score(folds: list[Score]) -> Score:
    return Score(*(mean(getattr(f, k) for f in folds) for k in ("mae", "mape", "coverage", "payday_found")))


def run() -> dict[str, Score]:
    """Mean score per method over every (persona, seed day) fold."""
    return {
        name: _mean_score([score_fold(p, d, fit) for p in PERSONAS for d in SEED_DAYS]) for name, fit in METHODS.items()
    }


def learning_curve() -> dict[int, Score]:
    """The live model's mean score by days of history it was allowed to learn from."""
    return {
        days: _mean_score([score_fold(p, d, history_days=days) for p in PERSONAS for d in SEED_DAYS])
        for days in LEARNING_CURVE_DAYS
    }


def table(results: dict[str, Score]) -> str:
    rows = [
        f"| {name} | ${s.mae:,.2f} | {s.mape:.1%} |" for name, s in sorted(results.items(), key=lambda kv: kv[1].mae)
    ]
    header = "| Spend model | MAE, daily checking balance | MAPE, month-4 everyday spend |\n|---|---|---|"
    return "\n".join([header, *rows])


def curve_table(curve: dict[int, Score]) -> str:
    header = "| Days of history | MAE, daily checking balance | p10–p90 band coverage | Payday found |"
    header += "\n|---|---|---|---|"
    rows = [f"| {d} | ${s.mae:,.2f} | {s.coverage:.0%} | {s.payday_found:.0%} |" for d, s in curve.items()]
    return "\n".join([header, *rows])


if __name__ == "__main__":
    n = len(PERSONAS) * len(SEED_DAYS)
    folds = f"{n} folds ({len(PERSONAS)} personas × {len(SEED_DAYS)} seed days)"
    print(f"Forecast backtest — {folds}, fit months 1–3 → predict month 4\n")
    print(table(run()))
    print("\nLearning curve — live model, fit on only the last N days before the cutoff\n")
    print(curve_table(learning_curve()))
