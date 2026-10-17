"""Forecast backtest: train on 3 months of history, predict the next 30 days of everyday spending.

Bills, subscriptions and paychecks are scheduled, so they forecast exactly; everyday card spending is
where a forecast goes wrong. Each fold fits on the 90 days before a cutoff and is scored on the 30
days after it. Folds roll over several cutoffs and history seeds so one lucky month can't decide it.

Run:  python -m evals.forecast_backtest      (from backend/)
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from app.forecast.history import Transaction, demo_history
from app.forecast.schedule import MAYA
from app.forecast.spend_model import fit_flat, fit_weekday, is_everyday_spend

TRAIN_DAYS, TEST_DAYS = 90, 30
CUTOFFS = [date(2026, 3, 2) + timedelta(days=37 * k) for k in range(6)]  # spread across weekdays and months
SEEDS = [7, 11, 23, 42, 99]

Predictor = Callable[[list[Transaction], date], Callable[[date], float]]


def schedule_dials(_: list[Transaction], cutoff: date) -> Callable[[date], float]:
    """The persona's hand-set estimates, as the live forecast uses them: groceries weekly, fun on the 10th."""

    def spend(d: date) -> float:
        groceries = MAYA.weekly_spend if (d - cutoff).days % 7 == 0 else 0.0
        return groceries + (MAYA.monthly_spend if d.day == 10 else 0.0)

    return spend


def learned_flat(history: list[Transaction], cutoff: date) -> Callable[[date], float]:
    return fit_flat(history, cutoff - timedelta(days=TRAIN_DAYS), cutoff).expected


def learned_weekday(history: list[Transaction], cutoff: date) -> Callable[[date], float]:
    return fit_weekday(history, cutoff - timedelta(days=TRAIN_DAYS), cutoff).expected


METHODS: dict[str, Predictor] = {
    "Schedule dials (live today)": schedule_dials,
    "Learned: flat daily mean": learned_flat,
    "Learned: weekday means": learned_weekday,
}


@dataclass(frozen=True)
class Score:
    mae: float  # mean absolute error of the cumulative-spend path, $ per day
    mape: float  # absolute % error of the 30-day spend total


def score_fold(predict: Predictor, seed: int, cutoff: date) -> Score:
    history = demo_history(cutoff + timedelta(days=TEST_DAYS), months=4, seed=seed)
    train = [t for t in history if t.date < cutoff]  # the predictor never sees the test window
    spend = predict(train, cutoff)
    actual_by_day: dict[date, float] = {}
    for t in history:
        if cutoff <= t.date < cutoff + timedelta(days=TEST_DAYS) and is_everyday_spend(t):
            actual_by_day[t.date] = actual_by_day.get(t.date, 0.0) + t.amount
    errors, cum_actual, cum_pred = [], 0.0, 0.0
    for offset in range(TEST_DAYS):
        d = cutoff + timedelta(days=offset)
        cum_actual += actual_by_day.get(d, 0.0)
        cum_pred += spend(d)
        errors.append(abs(cum_actual - cum_pred))
    return Score(mae=mean(errors), mape=abs(cum_pred - cum_actual) / cum_actual)


def run() -> dict[str, Score]:
    """Mean score per method over every (seed, cutoff) fold."""
    results = {}
    for name, predict in METHODS.items():
        folds = [score_fold(predict, seed, cutoff) for seed in SEEDS for cutoff in CUTOFFS]
        results[name] = Score(mae=mean(f.mae for f in folds), mape=mean(f.mape for f in folds))
    return results


def table(results: dict[str, Score]) -> str:
    rows = [
        f"| {name} | ${s.mae:,.2f} | {s.mape:.1%} |" for name, s in sorted(results.items(), key=lambda kv: kv[1].mae)
    ]
    header = "| Method | MAE, cumulative spend ($/day) | MAPE, 30-day total |\n|---|---|---|"
    return "\n".join([header, *rows])


if __name__ == "__main__":
    n = len(SEEDS) * len(CUTOFFS)
    print(f"Forecast backtest — {n} folds ({len(SEEDS)} seeds × {len(CUTOFFS)} cutoffs), train 90d → test 30d\n")
    print(table(run()))
