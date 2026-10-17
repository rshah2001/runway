"""How sure the forecast is, like a wearable's calibration period — owner: Patil-Hemangi.

A forecast is only as good as what it has learned: the payday rhythm (from deposits) and the everyday
spending rate (from recent outflows). Until both are learned, Runway says so instead of presenting a
guess as a fact, and the safety net won't move money automatically on it.

  * calibrating — under CALIBRATING_DAYS of history, or no paycheck seen yet: treat it as a sketch
  * learning    — some history, but the payday rhythm or the spending rate isn't settled
  * confident   — the detector has locked onto a payday AND the spending rate rests on
                  CONFIDENT_SPEND_DAYS or more

"Confident" requires the payday the forecast actually uses, not just paychecks seen: the recurring
detector needs MIN_CHARGES on a steady cadence before it schedules income, and a forecast with no
income in it shouldn't call itself sure. Every figure in `reasons` comes from here, never the LLM.
"""

from collections.abc import Sequence
from datetime import date

from app.forecast.recurring import MIN_CHARGES
from app.forecast.report_card import ReportCard
from app.forecast.sources import PersonaData, Txn
from app.schemas import LeftOut, Readiness

CALIBRATING_DAYS = 14
CONFIDENT_SPEND_DAYS = 30


def history_start(data: PersonaData) -> date | None:
    """The first day Runway has data for. History is oldest first."""
    return data.history[0].date if data.history else None


def _paychecks_seen(data: PersonaData, paycheck_label: str | None) -> int:
    """Deposits into checking that belong to the payday series: the detected paycheck's label, or
    before detection, the label that brought in the most money (the likeliest employer)."""
    deposits = [t for t in data.history if t.account == "Checking" and t.kind == "deposit" and t.amount > 0]
    if paycheck_label is None:
        totals: dict[str, float] = {}
        for t in deposits:
            totals[t.label] = totals.get(t.label, 0.0) + t.amount
        paycheck_label = max(totals, key=lambda k: totals[k], default=None)
    return sum(t.label == paycheck_label for t in deposits)


def assess(
    data: PersonaData,
    today: date,
    *,
    spend_days: int,
    paycheck: tuple[str, float, int] | None,
    left_out: Sequence[Txn] = (),
    paycheck_provisional: bool = False,
) -> Readiness:
    """Readiness for one persona as of `today`.

    `spend_days` is how many days the spending rate was learned from; `paycheck` is the detected
    (label, amount, interval_days), or None when no payday rhythm was found; `left_out` are the
    one-off purchases kept out of the spending rate.
    """
    first = history_start(data)
    days = (today - first).days if first else 0
    seen = _paychecks_seen(data, paycheck[0] if paycheck else None)

    if days < CALIBRATING_DAYS or seen == 0:
        status = "calibrating"
    elif paycheck is not None and not paycheck_provisional and spend_days >= CONFIDENT_SPEND_DAYS:
        status = "confident"
    else:
        status = "learning"

    reasons = [f"I've watched {days} day{'s' if days != 1 else ''} of your money."]
    if paycheck is not None and paycheck_provisional:
        _, amount, interval = paycheck
        reasons.append(
            f"I've seen {seen} paychecks of ${amount:,.2f} {interval} days apart, so I'm counting on the next one; "
            f"I'll be sure after the {MIN_CHARGES}rd."
        )
    elif paycheck is not None:
        label, amount, interval = paycheck
        reasons.append(f"Found your payday: ${amount:,.2f} every {interval} days ({label}).")
    elif seen == 0:
        reasons.append("I haven't seen a paycheck yet, so there's no income in this forecast.")
    else:
        reasons.append(
            f"I've seen {seen} of the {MIN_CHARGES} paychecks I need on a steady rhythm before I count on your payday."
        )
    if spend_days >= CONFIDENT_SPEND_DAYS:
        reasons.append(f"Your everyday spending rate comes from the last {spend_days} days.")
    else:
        reasons.append(f"Still learning your everyday spending: day {spend_days} of {CONFIDENT_SPEND_DAYS}.")
    for t in left_out:
        reasons.append(f"Left out of your usual spending: ${-t.amount:,.2f} {t.label} on {t.date:%b} {t.date.day}.")

    if status == "confident":
        progress = 1.0
    else:  # half for the spending rate, half for the payday; capped so "learning" never reads 100%
        progress = min(spend_days / CONFIDENT_SPEND_DAYS, 1) / 2 + min(seen / MIN_CHARGES, 1) / 2
        progress = round(min(progress, 0.95), 2)

    return Readiness(
        status=status,
        days_of_history=days,
        paychecks_seen=seen,
        paycheck_found=paycheck is not None and not paycheck_provisional,
        paycheck_provisional=paycheck_provisional,
        spend_days=spend_days,
        progress=progress,
        reasons=reasons,
        left_out=[LeftOut(date=t.date, amount=-t.amount, label=t.label) for t in left_out],
    )


def with_report_card(ready: Readiness, card: ReportCard | None) -> Readiness:
    """Readiness plus how its recent forecasts actually did. Informational: a dollar error means
    different things for different balances, so it doesn't change the status."""
    if card is None:
        return ready
    reason = (
        f"My {card.lead_days}-day-ahead forecasts were off by ${card.mean_abs_error:,.2f} on average "
        f"over the last {card.days_checked} days."
    )
    return ready.model_copy(
        update={
            "rolling_error": card.mean_abs_error,
            "rolling_error_days": card.days_checked,
            "reasons": [*ready.reasons, reason],
        }
    )


def _how_long(days: int) -> str:
    return f"{days // 30} months" if days >= 60 else f"{days} days"


def confidence_note(ready: Readiness) -> str:
    """One plain sentence on how sure the forecast is, for the agent to say in its own voice. Written
    here, not by the model, so the figures in it are the engine's."""
    if ready.status == "confident":
        return f"I've watched {_how_long(ready.days_of_history)} of your money, so I'm sure of this."
    if ready.status == "learning" and ready.days_of_history < CONFIDENT_SPEND_DAYS:
        day = f"day {ready.days_of_history} of {CONFIDENT_SPEND_DAYS}"
        return f"I'm still learning your money, {day}, so take this as a rough guide."
    if ready.status == "learning":
        return "I haven't locked onto your payday yet, so take this as a rough guide."
    return (
        f"I've only known your money for {_how_long(ready.days_of_history)} and haven't learned your payday yet, "
        "so this is a sketch, not a forecast."
    )
