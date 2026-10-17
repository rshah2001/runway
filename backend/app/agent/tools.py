"""Tools the agent can call — owner: Patil-Hemangi.

This is where "the LLM never does math" is enforced. Each tool calls the deterministic forecast
engine and returns every number the reply could need, already formatted ("$251.61", "Nov 5"), so
the model only has to quote. Read tools are pure; the write tools only create a PendingAction.

Every tool works on one persona's real data. The persona comes from the request, never from the
model: `call` drops any persona the model tries to pass, so a prompt injection can't read or move
another user's money.
"""

import math
import re
import secrets
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app import data
from app.forecast import engine, readiness, sources
from app.forecast.recurring import detect_recurring
from app.forecast.schedule import Schedule
from app.forecast.sources import PersonaData
from app.schemas import Bridge, Contact, Forecast, ForecastEvent, ForecastPoint, P2PSummary, PendingAction

PENDING: dict[str, PendingAction] = {}  # in-memory for now; moves to the DB with Tiger Data
ACTION_PERSONA: dict[str, str] = {}  # whose money a pending action touches, until Auth0 supplies the user
# what a pending P2P request asks for, (contact_id, memo): kept off PendingAction so the API shape is unchanged
ACTION_P2P: dict[str, tuple[str, str]] = {}
TRANSFER_STEP = 50.0  # proposals round up to a tidy amount instead of an exact-cents shortfall
MAX_PURCHASE = 100_000.0
SAFE_DATE_SEARCH_DAYS = 90
LOOKAHEAD_DAYS = 30  # a purchase is judged on the month that follows it
MAX_P2P_REQUEST = 1000.0  # the per-request cap POST /p2p/requests enforces (P2PSend.amount)
MAX_SPLIT_PEOPLE = 20
MAX_MEMO_CHARS = 80  # P2PSend.memo's limit, so an approved request always fits the route's contract
RECENT_PAYMENTS = 5
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


# ---------- peer-to-peer: who owes you, and asking someone to pay you back ----------


def _cents(x: float | Decimal) -> float:
    """Round half-up to cents: round() on a binary float may send $0.125 either way."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _p2p(persona: str) -> P2PSummary:
    """The persona's P2P data, through the same data layer as GET /p2p. An unknown persona is an error,
    never somebody's contacts: demo data would otherwise invent contacts for any slug."""
    if persona not in {p.slug for p in data.personas()}:
        raise sources.UnknownPersona(persona)  # call() turns this into an error result
    try:
        return data.p2p_summary(persona)
    except data.PersonaNotFound:
        raise sources.UnknownPersona(persona) from None


def who_owes_me(*, persona: str = engine.DEFAULT_PERSONA, today: date | None = None) -> dict[str, Any]:
    """Open IOUs (who owes the user, how much, what for, how long) and recent payments, with totals.

    Totals and days open are worked out here, so the model only has to quote them.
    """
    today = today or sources.local_today()
    summary = _p2p(persona)
    open_requests = [r for r in summary.requests if r.status == "open"]
    owed_by: dict[str, float] = {}
    for r in open_requests:
        owed_by[r.contact] = _cents(owed_by.get(r.contact, 0) + r.amount)
    recent = summary.payments[:RECENT_PAYMENTS]  # newest first, per the P2PSummary contract
    return {
        "open_count": len(open_requests),
        "total_owed_to_you": money(_cents(sum(r.amount for r in open_requests))),
        "open_requests": [
            {
                "contact": r.contact,
                "amount": money(r.amount),
                "memo": r.memo,
                "days_open": max(0, (today - r.created).days),  # never negative if the data's clock runs ahead
                "since": day(r.created),
            }
            for r in open_requests
        ],
        "owed_by_contact": [{"contact": name, "owes_you": money(total)} for name, total in owed_by.items()],
        "recent_payments": [
            {
                "day": day(p.date),
                "contact": p.contact,
                "direction": "paid you" if p.direction == "in" else "you paid",
                "amount": money(p.amount),
                "memo": p.memo,
            }
            for p in recent
        ],
        "recently_received": money(_cents(sum(p.amount for p in recent if p.direction == "in"))),
        "recently_sent": money(_cents(sum(p.amount for p in recent if p.direction == "out"))),
        "contacts": [c.name for c in summary.contacts],
    }


def find_contact(name: str, contacts: list[Contact]) -> Contact | None:
    """The contact called `name` (first name, any case, or contact id). No fuzzy matching on purpose:
    a request must go to exactly the person the user named, so "Al" never silently becomes "Alex"."""
    wanted = (name or "").strip().lower()
    return next((c for c in contacts if wanted in (c.name.lower(), c.id.lower())), None) if wanted else None


def split_share(total: float, people: int) -> tuple[float, float]:
    """(each other person's share, what the user covers) of `total` split `people` ways, the user included.

    Shares round to cents and the user absorbs the leftover cent, so the parts always add up to the total.
    """
    if not 2 <= people <= MAX_SPLIT_PEOPLE:
        raise ValueError(f"A split needs between 2 and {MAX_SPLIT_PEOPLE} people, counting you")
    whole = Decimal(str(total))
    share = _cents(whole / people)
    return share, _cents(whole - Decimal(str(share)) * (people - 1))


def _memo(memo: str | None, split: bool) -> str:
    text = " ".join((memo or "").split())[:MAX_MEMO_CHARS]
    return text or ("Split" if split else "Request")


def _no_such_contact(asked_for: str, contacts: list[Contact]) -> dict[str, Any]:
    return {
        "contact_found": False,
        "asked_for": asked_for,
        "your_contacts": [c.name for c in contacts],
        "status": "no such contact: ask the user which of their contacts they mean; nothing was created",
    }


def request_money(
    contact: str,
    amount: float | None = None,
    total: float | None = None,
    people: int | None = None,
    memo: str | None = None,
    *,
    persona: str = engine.DEFAULT_PERSONA,
    today: date | None = None,
) -> dict[str, Any]:
    """Propose asking one of the persona's contacts for money: a set `amount`, or their share of a
    `total` split `people` ways (default 2: the user and the contact).

    The share is computed here, never by the model, and the contact must be one of the persona's own:
    an unknown name creates nothing. Nothing is sent either way: this creates a PendingAction, and the
    request reaches the contact only when the user approves it.
    """
    summary = _p2p(persona)
    match = find_contact(contact, summary.contacts)
    if match is None:
        return _no_such_contact(contact, summary.contacts)
    split = amount is None
    if split:
        if total is None:
            raise ValueError("Say how much they owe, or the total to split")
        whole, people = abs(float(total)), int(people or 2)
        ask, you_cover = split_share(whole, people)
    else:
        ask = _cents(abs(float(amount)))
    if not 0 < ask <= MAX_P2P_REQUEST:
        raise ValueError(f"A request must be between $0 and {money(MAX_P2P_REQUEST)}")
    note = _memo(memo, split)
    action = PendingAction(
        id=secrets.token_urlsafe(16),  # unguessable, like a transfer's
        kind="p2p_request",
        description=f"Ask {match.name} for {money(ask)}: {note}",
        amount=ask,
    )
    PENDING[action.id] = action
    ACTION_PERSONA[action.id] = persona
    ACTION_P2P[action.id] = (match.id, note)
    result: dict[str, Any] = {
        "contact_found": True,
        "action_id": action.id,
        "contact": match.name,
        "request": money(ask),
        "memo": note,
        "already_owes_you": money(match.owes_you),
        "status": "awaiting the user's approval — nothing has been sent yet",
    }
    if split:
        result |= {"total": money(whole), "people": people, "you_cover": money(you_cover)}
    return result


# ---------- family safety net (read-only) ----------

# plain-words status for each bridge, so the model never has to interpret status codes
BRIDGE_STATUS = {
    "pending_approval": "waiting for {lender}'s OK",
    "declined": "{lender} said no",
    "funding": "on its way",
    "active": "covered; goes back automatically on {due}",
    "repaying": "going back today",
    "repaid": "paid back on {repaid}",
    "repay_failed": "late: couldn't go back on {due}",
    "failed": "didn't go through; nothing moved",
}


def _bridge(b: Bridge) -> dict[str, Any]:
    words = BRIDGE_STATUS.get(b.status, b.status).format(
        lender=b.lender_name, due=day(b.due_date), repaid=day(b.repaid_on) if b.repaid_on else "payday"
    )
    return {"from": b.lender_name, "to": b.borrower_name, "amount": money(b.amount), "status": words, "why": b.reason}


def explain_safety_net(*, persona: str = engine.DEFAULT_PERSONA, today: date | None = None) -> dict[str, Any]:
    """The family safety net from this user's side: who covered them, what they lent and when it comes
    back, the limits they set, and requests waiting for their OK.

    Read-only by design. It can't approve, decline, start or change anything: those happen only in the
    app's Family screen, from the person whose money it is.
    """
    from app import safety_views  # the backend's read-only view of the safety net

    today = today or sources.local_today()
    s = safety_views.summary(persona)
    _, sched = _inputs(persona, today)
    now = engine.forecast(start=today, schedule=sched)
    return {
        # tone follows the chat's own forecast, the same engine the safety net plans on
        **_mood(now.low.balance, now.safe_floor),
        "covered_me": [_bridge(b) for b in s.borrowed],
        "i_lent": [_bridge(b) for b in s.lent],
        "waiting_for_my_ok": [_bridge(b) for b in s.approvals_waiting],
        "limits_i_set": [
            {
                "for": lim.borrower_name,
                "limit": money(lim.limit),
                "out_now": money(lim.outstanding),
                "left": money(lim.remaining),
                "on": lim.enabled,
            }
            for lim in s.limits_i_set
        ],
        "family_covering_me": [
            {"who": lim.lender_name, "up_to": money(lim.limit), "on": lim.enabled} for lim in s.limits_for_me
        ],
        "recent": [e.message for e in s.events[:5]],
        "can_change_here": False,
        "where_to_act": "The Family screen in the app: approve or decline requests, and change limits there.",
    }


# ---------- needs vs. could-wait, until payday ----------

# Which spending is a need is decided here, never by the model. Scheduled bills (rent, utilities,
# insurance, phone, loans, the card payment) are always needs; for everyday purchases it goes by category.
NEED_CATEGORIES = {"Groceries", "Gas", "Health", "Education", "Utilities", "Transport", "Childcare"}
WAIT_CATEGORIES = {"Dining", "Entertainment", "Shopping", "Home", "Travel"}  # subscriptions are listed one by one
SPEND_HISTORY_DAYS = 90
NO_PAYDAY_DAYS = 14  # no payday learned yet: plan two weeks ahead


def _until_payday(sched: Schedule, today: date) -> tuple[date, bool]:
    """The next payday (exclusive end of the window), and whether it's a real learned one."""
    paydays = [f.next_date for f in sched.regular if f.kind == "paycheck" and f.next_date > today]
    return (min(paydays), True) if paydays else (today + timedelta(days=NO_PAYDAY_DAYS), False)


def _usual_until(data: PersonaData, categories: set[str], today: date, days: int) -> list[tuple[str, float]]:
    """What this person usually spends per category over `days`, from their last SPEND_HISTORY_DAYS."""
    since = today - timedelta(days=SPEND_HISTORY_DAYS)
    totals: dict[str, float] = {}
    for t in data.history:
        if t.kind == "purchase" and t.amount < 0 and since <= t.date < today and t.category in categories:
            totals[t.category] = totals.get(t.category, 0.0) + -t.amount
    usual = [(c, round(total / SPEND_HISTORY_DAYS * days, 2)) for c, total in totals.items()]
    return sorted((u for u in usual if u[1] >= 1), key=lambda u: -u[1])


def budget_suggestions(*, persona: str = engine.DEFAULT_PERSONA, today: date | None = None) -> dict[str, Any]:
    """What's a need and what could wait until the next payday, with amounts, all computed here.

    Needs: bills due before payday, plus usual spending on essentials (groceries, gas, health…).
    Could wait: subscriptions renewing before payday (exact amounts), plus usual spending on dining,
    entertainment, shopping and the like, estimated from the person's own last 90 days. Suggestions only:
    nothing is paused or changed. Most everyday purchases go on the card, so holding off mostly shrinks
    next month's card bill; it doesn't lift checking before payday, which is what a transfer is for."""
    today = today or sources.local_today()
    data, sched = _inputs(persona, today)
    payday, learned = _until_payday(sched, today)
    days = (payday - today).days
    f = engine.forecast(days=max(days - 1, 0), start=today, schedule=sched)
    bills = [
        {"what": e.label, "amount": money(-e.amount), "day": day(e.date)}
        for e in f.events
        if e.amount < 0 and e.kind in ("bill", "card_payment")
    ]
    renewing = [s for s in detect_recurring(data.history, today) if s.next_date < payday]
    usual_needs = _usual_until(data, NEED_CATEGORIES, today, days)
    usual_wants = _usual_until(data, WAIT_CATEGORIES, today, days)
    could_wait = [
        *[
            {"what": s.merchant, "amount": money(s.amount), "kind": "subscription", "day": day(s.next_date)}
            for s in renewing
        ],
        *[{"what": c, "amount": money(a), "kind": "usual spending"} for c, a in usual_wants],
    ]
    could_wait.sort(key=lambda w: -float(w["amount"].strip("$").replace(",", "")))
    total = sum(s.amount for s in renewing) + sum(a for _, a in usual_wants)
    return {
        **_low_summary(f),
        "until": f"payday {day(payday)}" if learned else f"{day(payday)} (no payday learned yet)",
        "days_until_payday": days,
        "needs": {
            "bills_before_payday": bills,
            "usual_essentials": [{"what": c, "amount": money(a)} for c, a in usual_needs],
        },
        "could_wait_until_payday": could_wait,
        "could_keep_in_your_pocket": money(total),
        "note": "Suggestions only: nothing is paused or cancelled. Most of this is card spending, so holding off "
        "shrinks next month's card bill; a transfer from savings is what covers a dip in checking before payday.",
    }


# ---------- weekly money brief ----------

BRIEF_DAYS = 7


def _purchases_between(data: PersonaData, start: date, end: date) -> float:
    """Everything bought in [start, end), card or debit: what a person means by "what I spent"."""
    return sum(-t.amount for t in data.history if t.kind == "purchase" and t.amount < 0 and start <= t.date < end)


def weekly_brief(*, persona: str = engine.DEFAULT_PERSONA, today: date | None = None) -> dict[str, Any]:
    """The facts for a weekly money brief, every one computed here: the week's low point and whether
    it's safe, what's coming in and going out, subscriptions renewing, spending this week vs last, and
    anything from the family safety net due this week. The model only turns them into a few sentences."""
    from app import safety_views  # the backend's read-only view of the safety net

    today = today or sources.local_today()
    data, sched = _inputs(persona, today)
    end = today + timedelta(days=BRIEF_DAYS - 1)
    f = engine.forecast(days=BRIEF_DAYS - 1, start=today, schedule=sched)
    coming = [  # plain amounts with a direction: people say "a $35 phone bill", not "a -$35 bill"
        {
            "day": day(e.date),
            "label": e.label,
            "amount": money(abs(e.amount)),
            "in_or_out": "in" if e.amount > 0 else "out",
        }
        for e in f.events
        if e.kind != "spending"
    ]
    renewing = [
        {"merchant": s.merchant, "amount": money(s.amount), "day": day(s.next_date)}
        for s in detect_recurring(data.history, today)
        if s.next_date <= end
    ]
    last = _purchases_between(data, today - timedelta(days=BRIEF_DAYS), today)
    before = _purchases_between(data, today - timedelta(days=2 * BRIEF_DAYS), today - timedelta(days=BRIEF_DAYS))
    s = safety_views.summary(persona)
    due = [b for b in s.borrowed + s.lent if today <= b.due_date <= end and b.status in ("active", "repaying")]
    return {
        **_low_summary(f),
        **_confidence(sched),
        "week": f"{day(today)} to {day(end)}",
        "safe_to_spend_this_week": money(max(0.0, f.low.balance - f.safe_floor)),
        "coming_up": coming,
        "subscriptions_renewing": renewing,
        "spent_last_7_days": money(last),
        "spent_the_7_days_before": money(before),
        "spending_vs_week_before": "more" if last > before else "less" if last < before else "the same",
        "family_money_due_back_this_week": [
            {"from": b.borrower_name, "to": b.lender_name, "amount": money(b.amount), "day": day(b.due_date)}
            for b in due
        ],
        "family_requests_waiting_for_you": len(s.approvals_waiting),
        # money's tight: the brief can name a couple of things that could wait (suggestions only)
        **(
            {"could_wait_until_payday": budget_suggestions(persona=persona, today=today)["could_wait_until_payday"][:2]}
            if engine.status(f.low.balance, f.safe_floor) != "healthy"
            else {}
        ),
    }


def discard(action_id: str) -> None:
    """Forget a proposal that was never shown to the user, so it can never be approved."""
    PENDING.pop(action_id, None)
    ACTION_PERSONA.pop(action_id, None)
    ACTION_P2P.pop(action_id, None)


def persona_of(action_id: str) -> str:
    """Whose money a pending action touches, so approval acts for that persona and only they may approve."""
    return ACTION_PERSONA.get(action_id, engine.DEFAULT_PERSONA)


def p2p_details(action_id: str) -> tuple[str, str] | None:
    """(contact_id, memo) of a pending P2P request, so approval creates exactly what was proposed."""
    return ACTION_P2P.get(action_id)


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
    {
        "type": "function",
        "name": "who_owes_me",
        "description": "Money friends and family owe the user: open IOUs (who, how much, what for, how many "
        "days open), recent payments in and out, and totals. Use for 'who owes me', 'did Alex pay me back', "
        "'what am I owed'.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "request_money",
        "description": "Propose asking one of the user's contacts to pay them: a set amount ('ask Alex for $45 "
        "for concert tickets') or the contact's share of a bill ('split dinner $60 with Alex'). For a split, pass "
        "the total and the number of people; the share is calculated for you. If the result says no such "
        "contact, ask the user which contact they mean; never invent one. This does NOT send anything: the "
        "user must approve.",
        "parameters": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "The contact's first name, as the user said it."},
                "amount": {
                    "type": "number",
                    "description": "What the contact owes, exactly as the user said it. Omit for a split.",
                },
                "total": {"type": "number", "description": "For a split: the whole bill, as the user said it."},
                "people": {
                    "type": "integer",
                    "description": "For a split: how many people share the bill, counting the user. Default 2.",
                },
                "memo": {"type": "string", "description": "What it's for, e.g. 'Dinner split', 'Concert tickets'."},
            },
            "required": ["contact"],
        },
    },
    {
        "type": "function",
        "name": "explain_safety_net",
        "description": "The family safety net: who covered the user's dips and when it goes back, money the user "
        "lent and whether it came back, limits they set for family, and requests waiting for their OK. Use for "
        "'did anyone cover me', 'did I get my money back', 'what's waiting for me'. Read-only: it cannot approve, "
        "decline or start anything.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "budget_suggestions",
        "description": "What's a need and what could wait until the next payday, with amounts: bills and "
        "essentials vs subscriptions renewing and usual dining/entertainment/shopping. Use for 'what can I cut', "
        "'how can I save', 'what are my necessities', 'tips for a tight month'. Suggestions only: changes nothing.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "weekly_brief",
        "description": "Everything for a short brief on the user's coming week: the lowest point and whether it's "
        "safe, paychecks and bills coming, subscriptions renewing, spending this week vs last, and family "
        "safety-net money due back. Use for 'brief me', 'how's my week looking', 'weekly summary'.",
        "parameters": {"type": "object", "properties": {}},
    },
]

READ_TOOLS = {
    "get_forecast": get_forecast,
    "simulate_purchase": simulate_purchase,
    "find_recurring": find_recurring,
    "who_owes_me": who_owes_me,
    "explain_safety_net": explain_safety_net,
    "weekly_brief": weekly_brief,
    "budget_suggestions": budget_suggestions,
}
WRITE_TOOLS = {"propose_transfer": propose_transfer, "request_money": request_money}


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
