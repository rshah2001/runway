"""The cash flows the forecast engine projects for one persona — owner: Patil-Hemangi.

A `Schedule` is plain data, built from a persona's real inputs (`sources.PersonaData`):
  * bills from the bills table — known amounts on known days;
  * regular money in and out of checking (paychecks, fixed transfers), detected from history;
  * everyday spending, learned from the last 90 days of checking outflows that are neither.
Keeping it separate from the engine makes the engine a pure function of (schedule, start, horizon),
which is what lets the backtest fit a schedule on months 1–3 and score it on month 4.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Literal

from app.forecast import readiness
from app.forecast.recurring import detect_recurring
from app.forecast.sources import PersonaData, Txn
from app.forecast.spend_model import Outflows, SpendProfile, daily_totals, fit_flat
from app.schemas import Readiness

EventKind = Literal["paycheck", "bill", "subscription", "card_payment", "spending", "transfer", "other"]

SAFE_FLOOR = 300.0
SPEND_WINDOW_DAYS = 90  # the backtest's training window: long enough to smooth out one odd week
ONE_OFF_FACTOR = 3.0
ONE_OFF_MIN = 75.0  # dollars: a $20 dinner is never a one-off, even for someone who spends $5 a day
MIN_SPEND_DAYS_FOR_ONE_OFFS = 5


@dataclass(frozen=True)
class MonthlyCharge:
    """A fixed charge on the same day each month; days past month-end clamp to the last day."""

    day: int
    amount: float  # positive = money out
    label: str
    kind: EventKind = "bill"


@dataclass(frozen=True)
class RegularFlow:
    """Money that reliably moves in or out of checking on a cadence, found in history."""

    label: str
    amount: float  # signed: positive = money in
    interval_days: int
    next_date: date
    kind: EventKind


@dataclass(frozen=True)
class Schedule:
    start_balance: float  # checking only: savings is the cushion, not spending money
    safe_floor: float = SAFE_FLOOR
    monthly: list[MonthlyCharge] = field(default_factory=list)
    regular: list[RegularFlow] = field(default_factory=list)
    spend: SpendProfile = SpendProfile((0.0,) * 7)
    readiness: Readiness | None = None  # how sure a forecast from this schedule is
    daily_spend: tuple[float, ...] = ()  # each day's everyday spending in the learning window: the range


def _checking_flow(t: Txn) -> bool:
    """Money moving in or out of checking other than purchases and bills."""
    return t.account == "Checking" and t.kind in ("deposit", "transfer", "withdrawal")


def regular_flows(history: list[Txn], today: date) -> list[RegularFlow]:
    """Paychecks and fixed transfers that repeat on a steady cadence for a steady amount."""
    incoming = detect_recurring(history, today, lambda t: _checking_flow(t) and t.amount > 0)
    outgoing = detect_recurring(history, today, lambda t: _checking_flow(t) and t.amount < 0)
    biggest_in = max((r.amount for r in incoming), default=0)
    flows = [
        # the largest steady income is the paycheck; smaller ones are splits and allowances
        RegularFlow(
            r.merchant, r.amount, r.interval_days, r.next_date, "paycheck" if r.amount == biggest_in else "transfer"
        )
        for r in incoming
    ]
    flows += [RegularFlow(r.merchant, -r.amount, r.interval_days, r.next_date, "transfer") for r in outgoing]
    return flows


def everyday_txns(history: list[Txn], regular: list[RegularFlow]) -> list[Txn]:
    """Checking outflows that are neither bills nor a detected regular transfer: debit purchases,
    occasional transfers. Card purchases are left out — they reach checking as the card-payment bill."""
    regular_labels = {f.label.strip().lower() for f in regular}
    return [
        t
        for t in history
        if t.account == "Checking"
        and t.amount < 0
        and t.kind in ("purchase", "transfer", "withdrawal")
        and t.label.strip().lower() not in regular_labels
    ]


def everyday_outflows(history: list[Txn], regular: list[RegularFlow]) -> Outflows:
    """`everyday_txns` as (day, dollars out) pairs, the spend model's input."""
    return [(t.date, -t.amount) for t in everyday_txns(history, regular)]


def one_offs(txns: list[Txn], start: date, end: date) -> list[Txn]:
    """Purchases in [start, end) too big and too unusual to be part of the everyday rate: more than
    ONE_OFF_FACTOR × the median spending day, at least ONE_OFF_MIN dollars, at a merchant seen only
    once in the window. All three are required: a big monthly warehouse-club run is big but not rare,
    and a first visit to a new café is rare but not big. A $406 car repair is both."""
    window = [t for t in txns if start <= t.date < end]
    by_day: dict[date, float] = {}
    for t in window:
        by_day[t.date] = by_day.get(t.date, 0.0) + -t.amount
    if len(by_day) < MIN_SPEND_DAYS_FOR_ONE_OFFS:
        return []  # too few spending days to know what "usual" is
    usual_day = median(by_day.values())
    visits: dict[str, int] = {}
    for t in window:
        visits[t.label.strip().lower()] = visits.get(t.label.strip().lower(), 0) + 1
    return [
        t
        for t in window
        if -t.amount > max(ONE_OFF_FACTOR * usual_day, ONE_OFF_MIN) and visits[t.label.strip().lower()] == 1
    ]


def spend_window(data: PersonaData, today: date) -> tuple[date, date]:
    """The days the spending rate is learned from: the last SPEND_WINDOW_DAYS, or since the first day
    with data if that is more recent. Dividing a new user's 12 days of spending by 90 would make them
    look like they barely spend."""
    first = readiness.history_start(data) or today
    return max(today - timedelta(days=SPEND_WINDOW_DAYS), first), today


def build(data: PersonaData, today: date, fit=fit_flat) -> Schedule:
    """A persona's schedule as of `today`, learned from the history before it."""
    regular = regular_flows(data.history, today)
    start, end = spend_window(data, today)
    everyday = everyday_txns(data.history, regular)
    unusual = one_offs(everyday, start, end)
    # one-offs stay out of the rate (a car repair isn't a habit) but stay in the range: life has them
    spend = fit([(t.date, -t.amount) for t in everyday if t not in unusual], start, end)
    outflows = [(t.date, -t.amount) for t in everyday]
    monthly = [
        MonthlyCharge(b.day, b.amount, b.label, "card_payment" if "credit card" in b.label.lower() else "bill")
        for b in data.bills
    ]
    paycheck = next(((f.label, f.amount, f.interval_days) for f in regular if f.kind == "paycheck"), None)
    ready = readiness.assess(data, today, spend_days=(end - start).days, paycheck=paycheck, left_out=unusual)
    return Schedule(
        start_balance=data.checking,
        monthly=monthly,
        regular=regular,
        spend=spend,
        readiness=ready,
        daily_spend=daily_totals(outflows, start, end),
        safe_floor=data.safe_floor,  # what this person keeps (app/prefs.py)
    )
