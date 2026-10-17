"""Tools the agent can call — owner: Patil-Hemangi.

This is where "the LLM never does math" is enforced. Each tool calls the deterministic forecast
engine and returns every number the reply could need, already formatted ("$251.61", "Nov 5"), so
the model only has to quote. Read tools are pure; the one write tool only creates a PendingAction.

Every tool works on one persona's real data. The persona comes from the request, never from the
model: `call` drops any persona the model tries to pass, so a prompt injection can't read or move
another user's money.
"""

import math
import re
import secrets
from datetime import date, timedelta
from typing import Any

from app.forecast import engine, readiness, sources
from app.forecast.recurring import detect_recurring
from app.forecast.schedule import Schedule
from app.forecast.sources import PersonaData
from app.schemas import Forecast, ForecastEvent, ForecastPoint, PendingAction

PENDING: dict[str, PendingAction] = {}  # in-memory for now; moves to the DB with Tiger Data
ACTION_PERSONA: dict[str, str] = {}  # whose savings a pending transfer moves, until Auth0 supplies the user
TRANSFER_STEP = 50.0  # proposals round up to a tidy amount instead of an exact-cents shortfall
MAX_PURCHASE = 100_000.0
SAFE_DATE_SEARCH_DAYS = 90
LOOKAHEAD_DAYS = 30  # a purchase is judged on the month that follows it
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def money(x: float) -> str:
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def day(d: date) -> str:
    return f"{d:%a} {d:%b} {d.day}"  # not %-d: that is glibc-only and crashes on Windows


def resolve_date(when: str | None, today: date) -> date:
    """Turn 'YYYY-MM-DD', 'today', 'tomorrow' or a weekday name into a date (default: tomorrow).

    Date arithmetic is done here rather than by the model, for the same reason as money math.
    A weekday means the next one after today, as in "Friday" said on a Friday.
    """
    text = (when or "tomorrow").strip().lower()
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    for i, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name}", text):
            return today + timedelta(days=(i - today.weekday()) % 7 or 7)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"Can't read the date {when!r}; use YYYY-MM-DD, 'today', 'tomorrow' or a weekday") from None


def _inputs(persona: str, today: date) -> tuple[PersonaData, Schedule]:
    """Read the persona's data once per tool call; every forecast in the call reuses it."""
    data = sources.load(persona, today)
    return data, engine.schedule_from(data, today)


def _shortfall(f: Forecast) -> float:
    return round(max(0.0, f.safe_floor - f.low.balance), 2)


def _mood(low_balance: float, safe_floor: float) -> dict[str, Any]:
    """Tone inputs for the agent, computed here so the model never compares numbers itself."""
    return {"status": engine.status(low_balance, safe_floor)}


def _confidence(sched: Schedule) -> dict[str, Any]:
    """How sure the forecast is, in words the agent can pass on: readiness status, a ready-made note,
    and the recent track record when there is one."""
    ready = sched.readiness
    if ready is None:
        return {}
    out: dict[str, Any] = {"readiness": ready.status, "confidence_note": readiness.confidence_note(ready)}
    if ready.rolling_error is not None:
        out["track_record"] = f"week-ahead forecasts off by {money(ready.rolling_error)} on average lately"
    return out


def _range(p: ForecastPoint) -> str | None:
    if p.balance_low is None or p.balance_high is None:
        return None
    return f"{money(p.balance_low)} to {money(p.balance_high)}"


def _low_summary(f: Forecast) -> dict[str, Any]:
    return {
        **_mood(f.low.balance, f.safe_floor),
        "lowest_balance": money(f.low.balance),
        "lowest_day": day(f.low.date),
        "safety_floor": money(f.safe_floor),
        "below_safety_floor": f.low.balance < f.safe_floor,
        "shortfall": money(_shortfall(f)),
    }


def get_forecast(days: int = 30, *, persona: str = engine.DEFAULT_PERSONA, today: date | None = None) -> dict[str, Any]:
    """Projected checking balance: the tightest day and the upcoming cash flows."""
    today = today or sources.local_today()
    days = max(1, min(int(days), engine.MAX_DAYS))
    _, sched = _inputs(persona, today)
    f = engine.forecast(days=days, start=today, schedule=sched)
    scheduled = [e for e in f.events if e.kind != "spending"]  # the daily estimates would crowd out the bills
    upcoming = [{"day": day(e.date), "label": e.label, "amount": money(e.amount)} for e in scheduled[:12]]
    return {
        **_low_summary(f),
        **_confidence(sched),
        "lowest_balance_range": _range(f.low),
        "balance_today": money(sched.start_balance),  # the real balance, before today's estimated spending
        "everyday_spending_per_week": money(sched.spend.total(today, 7)),
        "balance_at_end": money(f.points[-1].balance),
        "horizon_days": days,
        "upcoming": upcoming,
    }


def _lowest_from(amount: float, on: date, today: date, sched: Schedule) -> ForecastPoint:
    """Lowest balance in the LOOKAHEAD_DAYS starting at `on`, with the purchase made on `on`.

    Days before the purchase are left out: if you're already short on the 5th, that is the
    forecast's problem, not this purchase's (same rule as the prototype's verdictFor).
    """
    purchase = ForecastEvent(date=on, amount=-amount, label="Purchase", kind="other")
    days = min((on - today).days + LOOKAHEAD_DAYS, engine.MAX_DAYS)
    f = engine.forecast(days=days, extra=[purchase], start=today, schedule=sched)
    return min((p for p in f.points if p.date >= on), key=lambda p: p.balance)


def _first_safe_day(amount: float, after: date, today: date, sched: Schedule) -> date | None:
    """Earliest day after `after` when spending `amount` keeps the following month above the floor."""
    for offset in range(1, SAFE_DATE_SEARCH_DAYS + 1):
        d = after + timedelta(days=offset)
        if _lowest_from(amount, d, today, sched).balance >= sched.safe_floor:
            return d
    return None


def simulate_purchase(
    amount: float,
    when: str | None = None,
    label: str = "Purchase",
    *,
    persona: str = engine.DEFAULT_PERSONA,
    today: date | None = None,
) -> dict[str, Any]:
    """Whether a purchase is safe over the month after it, and if not, when it would be."""
    today = today or sources.local_today()
    amount = abs(float(amount))
    if not 0 < amount <= MAX_PURCHASE:
        raise ValueError(f"Purchase amount must be between $0 and {money(MAX_PURCHASE)}")
    on = resolve_date(when, today)
    if (on - today).days > engine.MAX_DAYS - LOOKAHEAD_DAYS:
        raise ValueError("That's too far ahead to forecast — pick a date within the next 11 months")
    _, sched = _inputs(persona, today)
    base = engine.forecast(start=today, schedule=sched)
    low = _lowest_from(amount, on, today, sched)
    shortfall = round(max(0.0, base.safe_floor - low.balance), 2)
    result: dict[str, Any] = {
        "verdict": "safe" if shortfall == 0 else "not_safe",
        # tone follows the worse of this purchase's month and the dips already coming without it
        **_mood(min(low.balance, base.low.balance), base.safe_floor),
        "purchase": f"{label} {money(amount)} on {day(on)}",
        "lowest_balance_with_it": money(low.balance),
        "lowest_day_with_it": day(low.date),
        "safety_floor": money(base.safe_floor),
        "shortfall": money(shortfall),
        "already_below_floor_without_it": base.low.balance < base.safe_floor,
        "lowest_without_it": f"{money(base.low.balance)} on {day(base.low.date)}",
        **_confidence(sched),
    }
    if shortfall:
        later = _first_safe_day(amount, on, today, sched)
        result["first_safe_day"] = day(later) if later else None
        result["transfer_that_would_cover_it"] = money(_round_up(shortfall))
    return result


def find_recurring(*, persona: str = engine.DEFAULT_PERSONA, today: date | None = None) -> dict[str, Any]:
    """Subscriptions detected from purchase history, with totals."""
    today = today or sources.local_today()
    data, sched = _inputs(persona, today)
    subs = detect_recurring(data.history, today)
    now = engine.forecast(start=today, schedule=sched)
    monthly = sum(s.amount * 30 / s.interval_days for s in subs)
    return {
        "count": len(subs),
        "subscriptions": [
            {"merchant": s.merchant, "amount": money(s.amount), "every_days": s.interval_days, "next": day(s.next_date)}
            for s in subs
        ],
        "monthly_total": money(monthly),
        "yearly_total": money(monthly * 12),
        **_mood(now.low.balance, now.safe_floor),
    }


def _round_up(x: float) -> float:
    return math.ceil(x / TRANSFER_STEP) * TRANSFER_STEP if x > 0 else 0.0


def propose_transfer(
    purchase_amount: float | None = None,
    purchase_when: str | None = None,
    *,
    persona: str = engine.DEFAULT_PERSONA,
    today: date | None = None,
) -> dict[str, Any]:
    """Propose moving just enough from savings to keep checking above the floor.

    The amount is computed here — never chosen by the model — from the forecast, optionally with the
    purchase the user is considering. Nothing moves: this creates a PendingAction that executes
    only when the user approves it.
    """
    today = today or sources.local_today()
    data, sched = _inputs(persona, today)
    if purchase_amount:
        on = resolve_date(purchase_when, today)
        f = engine.simulate_purchase(abs(float(purchase_amount)), on, "Purchase", start=today, schedule=sched)
    else:
        f = engine.forecast(start=today, schedule=sched)
    amount = _round_up(_shortfall(f))
    if amount == 0:
        return {"needed": False, **_low_summary(f)}
    if amount > data.savings:
        return {
            "needed": True,
            "possible": False,
            "savings_balance": money(data.savings),
            "transfer_needed": money(amount),
        }
    action = PendingAction(
        id=secrets.token_urlsafe(16),  # unguessable: until Auth0 lands, the id alone authorizes approval
        kind="transfer",
        description=f"Move {money(amount)} from Savings to Checking",
        amount=amount,
    )
    PENDING[action.id] = action
    ACTION_PERSONA[action.id] = persona
    return {
        "needed": True,
        "possible": True,
        "action_id": action.id,
        "transfer": money(amount),
        "lowest_day": day(f.low.date),
        "lowest_balance_before": money(f.low.balance),
        "lowest_balance_after": money(f.low.balance + amount),
        "safety_floor": money(f.safe_floor),
        "status": "awaiting the user's approval — nothing has moved yet",
        **_confidence(sched),
    }


def persona_of(action_id: str) -> str:
    """Whose transfer a pending action is, so approval moves that persona's money."""
    return ACTION_PERSONA.get(action_id, engine.DEFAULT_PERSONA)


# Declarations Gemini sees. Descriptions say *when* to use each tool; the code above says *how*.
# None of them takes a persona: whose data a tool sees is fixed by the request, not the model.
DECLARATIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_forecast",
        "description": "Projected checking balance over the next days: the tightest day, whether it dips "
        "below the safety floor, and upcoming bills and paychecks. Use for 'will I be okay', 'what's coming up'.",
        "parameters": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Horizon in days, 1-365. Default 30."}},
        },
    },
    {
        "type": "function",
        "name": "simulate_purchase",
        "description": "Check whether the user can safely afford a purchase. Use for any 'can I afford / buy / "
        "go to X' question that names an amount.",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Price in dollars, exactly as the user said it."},
                "when": {
                    "type": "string",
                    "description": "The user's words for the day: a weekday name like 'friday', 'today', "
                    "'tomorrow', or YYYY-MM-DD. Omit if not mentioned.",
                },
                "label": {"type": "string", "description": "Short name for the purchase, e.g. 'Concert'."},
            },
            "required": ["amount"],
        },
    },
    {
        "type": "function",
        "name": "find_recurring",
        "description": "Subscriptions and other recurring card charges detected in purchase history, with totals.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "propose_transfer",
        "description": "Propose a savings-to-checking transfer that keeps the balance above the safety floor. "
        "Use when the user asks to fix a shortfall. The amount is calculated for you. If the user was asking "
        "about a purchase, pass it so the transfer covers it. This does NOT move money: the user must approve.",
        "parameters": {
            "type": "object",
            "properties": {
                "purchase_amount": {"type": "number", "description": "The purchase to cover, if any."},
                "purchase_when": {
                    "type": "string",
                    "description": "When that purchase happens, as in simulate_purchase.",
                },
            },
        },
    },
]

READ_TOOLS = {"get_forecast": get_forecast, "simulate_purchase": simulate_purchase, "find_recurring": find_recurring}
WRITE_TOOLS = {"propose_transfer": propose_transfer}


def call(
    name: str, arguments: dict[str, Any], today: date | None = None, persona: str = engine.DEFAULT_PERSONA
) -> dict[str, Any]:
    """Run a tool by name for `persona`. Errors come back as data so the model can recover instead of
    the request failing. The model never chooses whose data a tool sees."""
    fn = READ_TOOLS.get(name) or WRITE_TOOLS.get(name)
    if fn is None:
        return {"error": f"Unknown tool {name!r}"}
    args = {k: v for k, v in arguments.items() if k not in ("persona", "today")}
    try:
        return fn(**args, persona=persona, today=today)
    except (TypeError, ValueError, sources.UnknownPersona) as e:
        return {"error": str(e)}
