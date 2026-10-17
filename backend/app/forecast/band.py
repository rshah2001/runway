"""The forecast's range: how far everyday spending could push the balance either way — owner: Patil-Hemangi.

Bills and paydays are known; everyday spending is the only part of the forecast that is uncertain, so
the band comes from how much this person's spending has actually varied. Method: a moving-block
bootstrap over the daily spending totals the rate was learned from. Each simulated future is built
from real 7-day stretches of the person's history, laid end to end; the band at day k runs from p95 down
to p10 of total spending by day k across BOOTSTRAP_PATHS such futures: a p5–p90 balance.

Why a bootstrap instead of per-day quantiles: quantiles don't add up. The p90 of one day's spending
times 30 is far more than the p90 of a month's spending, because big days and small days average out,
so summing daily quantiles would give a band that is much too wide by the end of the month. Why blocks
instead of single days: spending clusters (a weekly grocery run, a busy weekend), and resampling whole
weeks keeps those clusters intact, so the band isn't falsely narrow.

What it doesn't cover: a paycheck or bill that changes amount or date. Those are taken as scheduled.
Deterministic (fixed seed), so the same history always gives the same band — the agent and the safety
net must never see two different numbers for one question.
"""

import random
from functools import lru_cache

BOOTSTRAP_PATHS = 400
BLOCK_DAYS = 7
# Quantiles of SPENDING. High spending gives the low balance, so the cautious end comes from the top.
# Asymmetric on purpose: the safety net plans on balance_low, so it is set from p95 spending (the
# backtest at p90 let 13% of real days fall below it); balance_high only needs to be a fair p90.
SPEND_QUANTILE_FOR_LOW_BALANCE = 0.95
SPEND_QUANTILE_FOR_HIGH_BALANCE = 0.10
SEED = 20261017


def _horizon_bucket(days: int) -> int:
    """Round the horizon up to a power of two, so a run of slightly different horizons (the agent tries
    many purchase dates) reuses one cached band instead of rebuilding it each time."""
    bucket = 32
    while bucket < days:
        bucket *= 2
    return bucket


def _quantile(sorted_values: list[float], q: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


@lru_cache(maxsize=64)
def _spread(daily: tuple[float, ...], days: int) -> tuple[tuple[float, float], ...]:
    """(extra spending at p95, spending saved at p10) versus the mean, for cumulative days 1..days."""
    rng = random.Random(SEED)
    block = min(BLOCK_DAYS, len(daily))
    starts = len(daily) - block + 1
    totals = [[0.0] * days for _ in range(BOOTSTRAP_PATHS)]
    for path in totals:
        running, k = 0.0, 0
        while k < days:
            start = rng.randrange(starts)
            for value in daily[start : start + block]:
                if k == days:
                    break
                running += value
                path[k] = running
                k += 1
    mean_day = sum(daily) / len(daily)
    spread = []
    for k in range(days):
        by_day = sorted(path[k] for path in totals)
        expected = mean_day * (k + 1)
        down = max(0.0, _quantile(by_day, SPEND_QUANTILE_FOR_LOW_BALANCE) - expected)
        up = max(0.0, expected - _quantile(by_day, SPEND_QUANTILE_FOR_HIGH_BALANCE))
        spread.append((down, up))
    return tuple(spread)


def spread(daily: tuple[float, ...], days: int) -> tuple[tuple[float, float], ...]:
    """How far below / above the expected balance the p5 / p90 balance sits after each of `days` days.

    `daily` is the everyday spending total of every day in the learning window, zeros included. Both
    values are ≥ 0 when the history has any variation; with no history the band is empty (zero width)."""
    if not daily or days <= 0:
        return ((0.0, 0.0),) * max(days, 0)
    return _spread(daily, _horizon_bucket(days))[:days]
